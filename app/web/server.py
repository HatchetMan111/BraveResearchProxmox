"""Web-Dashboard für den Recherche-LXC.

Läuft als eigener systemd-Service (research-lxc-web.service) getrennt von
den zeitgesteuerten CLI-Läufen. Liest/schreibt dieselbe config.yaml wie
app.main -- Änderungen über die UI gelten sofort für den nächsten
Timer-Lauf, ohne Neustart.

Start (Entwicklung):  uvicorn app.web.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown as md_lib
import requests
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import output, pipeline, schedule_units
from ..budget_tracker import BudgetExceededError, BudgetTracker
from ..config import load_config
from ..modules import MODULES
from ..modules.templates import TEMPLATES, get_template, render_queries
from ..ollama_client import OllamaClient, OllamaError
from . import config_io

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("RESEARCH_LXC_CONFIG", "config.yaml")).resolve()

# Namen, die nicht für eigene Module verwendet werden dürfen: die beiden
# eingebauten Module sowie "all" (reserviert für --module all).
RESERVED_MODULE_NAMES = set(MODULES) | {"all"}

# Anzeigenamen für die UI (statt Technik-Kürzel wie "competitor_analysis").
MODULE_TITLES = {
    "competitor_analysis": "Konkurrenzanalyse",
    "news_digest": "News-Digest",
}


def pretty_module_name(name: str) -> str:
    """Lesbarer Modulname: bekannte Titel, sonst 'mein_modul' -> 'Mein Modul'."""
    if name in MODULE_TITLES:
        return MODULE_TITLES[name]
    return name.replace("_", " ").replace("-", " ").strip().title() or name


_REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})_(.+)$")


def pretty_report(meta: dict[str, Any]) -> dict[str, Any]:
    """Reichert einen Report-Eintrag {name, mtime, ...} um lesbare Felder an:
    title ('Konkurrenzanalyse'), date_str ('04.09.2026 06:00'), rel ('vor 3 Stunden')."""
    name = meta.get("name", "")
    stem = name[:-3] if name.endswith(".md") else name
    match = _REPORT_RE.match(stem)
    if match:
        date_part, hh, mm, module = match.groups()
        try:
            dt = datetime.strptime(f"{date_part} {hh}:{mm}", "%Y-%m-%d %H:%M")
            date_str = dt.strftime("%d.%m.%Y %H:%M")
        except ValueError:
            date_str = ""
            module = stem
        title = pretty_module_name(module)
    else:
        title = pretty_module_name(stem)
        date_str = ""
    return {**meta, "title": title, "date_str": date_str, "rel": human_rel(meta.get("mtime"))}


def human_rel(moment: datetime | None, now: datetime | None = None) -> str:
    """Relative Zeitangabe ('vor 3 Stunden', 'gestern') für Report-Listen."""
    if not isinstance(moment, datetime):
        return ""
    now = now or datetime.now()
    try:
        delta = now - moment.replace(tzinfo=None)
    except (TypeError, ValueError):
        return ""
    secs = max(0, int(delta.total_seconds()))
    if secs < 60:
        return "gerade eben"
    if secs < 3600:
        minutes = secs // 60
        return f"vor {minutes} Minute" if minutes == 1 else f"vor {minutes} Minuten"
    if secs < 86400:
        hours = secs // 3600
        return f"vor {hours} Stunde" if hours == 1 else f"vor {hours} Stunden"
    if secs < 2 * 86400:
        return "gestern"
    if secs < 7 * 86400:
        return f"vor {secs // 86400} Tagen"
    return moment.strftime("%d.%m.%Y")

app = FastAPI(title="Recherche-LXC Dashboard")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# In-Memory-Status der laufenden/letzten Läufe pro Modul. Reicht für die
# MVP-Version (ein einzelner uvicorn-Worker); überlebt keinen Neustart.
_RUN_LOCK = threading.Lock()
RUN_STATUS: dict[str, dict[str, Any]] = {name: {"status": "idle"} for name in MODULES}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")
    return slug or "modul"


def _reports_dir(raw_cfg: dict[str, Any]) -> Path:
    value = Path(raw_cfg.get("output", {}).get("reports_dir", "reports"))
    return value if value.is_absolute() else (CONFIG_PATH.parent / value)


def _budget_snapshot(raw_cfg: dict[str, Any]) -> dict[str, Any] | None:
    budget_db = raw_cfg.get("budget", {}).get("db_path", "data/budget.db")
    budget_path = Path(budget_db)
    if not budget_path.is_absolute():
        budget_path = CONFIG_PATH.parent / budget_path
    max_req = raw_cfg.get("brave", {}).get("max_requests_per_month", 950)
    try:
        tracker = BudgetTracker(budget_path, max_requests_per_month=max_req)
        status = tracker.status()
        pct = (status.used / status.limit * 100) if status.limit else 0
        level = "ok" if pct < 70 else ("warn" if pct < 90 else "danger")
        return {"used": status.used, "limit": status.limit, "remaining": status.remaining,
                "month": status.month, "pct": pct, "level": level}
    except Exception:  # Datenbank evtl. noch nicht angelegt -- kein harter Fehler fürs Dashboard
        logger.exception("Konnte Budget-Status nicht lesen")
        return None


def _list_reports(raw_cfg: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    reports_dir = _reports_dir(raw_cfg)
    if not reports_dir.exists():
        return []
    files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit:
        files = files[:limit]
    metas = [{"name": f.name, "mtime": datetime.fromtimestamp(f.stat().st_mtime)} for f in files]
    return [pretty_report(m) for m in metas]


def _valid_module_names(raw_cfg: dict[str, Any]) -> set[str]:
    return set(MODULES) | {cm.get("name") for cm in raw_cfg.get("custom_modules", []) if cm.get("name")}


def _format_duration(total_seconds: float | None) -> str:
    """Formatiert Sekunden als '3 min 12 s' / '45 s' / '1 h 5 min'."""
    if total_seconds is None:
        return "–"
    secs = max(0, int(total_seconds))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min {s} s"
    return f"{s} s"


def _run_status_view() -> dict[str, dict[str, Any]]:
    """Reichert RUN_STATUS um lesbare Laufzeit-/Fertig-Infos fürs Dashboard an."""
    now = datetime.now(timezone.utc)
    view: dict[str, dict[str, Any]] = {}
    with _RUN_LOCK:
        items = {k: dict(v) for k, v in RUN_STATUS.items()}
    for name, st in items.items():
        started = st.get("started_at")
        finished = st.get("finished_at")
        if st.get("status") == "running" and isinstance(started, datetime):
            st["elapsed_seconds"] = (now - started).total_seconds()
            st["elapsed_str"] = _format_duration(st["elapsed_seconds"])
            st["started_str"] = started.astimezone().strftime("%H:%M:%S")
        if isinstance(finished, datetime):
            st["finished_str"] = finished.astimezone().strftime("%d.%m.%Y %H:%M")
            if isinstance(started, datetime):
                st["duration_seconds"] = (finished - started).total_seconds()
                st["duration_str"] = _format_duration(st["duration_seconds"])
        view[name] = st
    return view


def _schedule_info(raw_cfg: dict[str, Any]) -> dict[str, Any]:
    sched = raw_cfg.get("schedule", {}) or {}
    enabled = bool(sched.get("enabled", True))
    time = str(sched.get("time", "06:00") or "06:00")
    if not re.fullmatch(r"\d{2}:\d{2}", time):
        time = "06:00"
    frequency = str(sched.get("frequency", "daily") or "daily")
    if frequency not in ("daily", "weekly"):
        frequency = "daily"
    weekday = str(sched.get("weekday", "mon") or "mon").lower()
    if weekday not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        weekday = "mon"
    weekday_de = {"mon": "Mo", "tue": "Di", "wed": "Mi", "thu": "Do",
                  "fri": "Fr", "sat": "Sa", "sun": "So"}[weekday]
    if frequency == "weekly":
        human = f"wöchentlich ({weekday_de} {time} Uhr)"
    else:
        human = f"täglich {time} Uhr"
    return {"enabled": enabled, "time": time, "frequency": frequency,
            "weekday": weekday, "human": human}


def _timer_status() -> dict[str, Any]:
    """Status der Recherche-Timer: pro-Modul-Timer (research-lxc-mod-*.timer)
    oder als Rückfall der Sammel-Timer. Fail-safe: None bei Fehler."""
    try:
        out = subprocess.run(
            ["systemctl", "list-timers", "research-lxc-*", "--no-pager", "--no-legend"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [l.strip() for l in (out.stdout or "").splitlines() if "research-lxc" in l]
        mod = [l for l in lines if "research-lxc-mod-" in l]
        if mod:
            nxt = mod[0].split()[0] if mod[0].split() else ""
            return {
                "active": True,
                "count": len(mod),
                "detail": f"{len(mod)} Modul-Timer aktiv.",
                "next": nxt,
            }
        all_t = [l for l in lines if "research-lxc-all.timer" in l]
        if all_t:
            nxt = all_t[0].split()[0] if all_t[0].split() else ""
            return {"active": True, "count": 0, "detail": "Sammel-Timer aktiv.", "next": nxt}
        return {"active": False, "count": 0, "detail": "Kein Timer aktiv.", "next": ""}
    except Exception:
        return {"active": None, "count": 0, "detail": "Timer-Status nicht abfragbar.", "next": ""}


def _all_module_schedules(raw_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Effektiver Zeitplan je Modul (eingebaut + eigene) fürs Dashboard."""
    return {
        name: schedule_units.effective_schedule(raw_cfg, cfg)
        for name, cfg in schedule_units.iter_modules(raw_cfg)
    }


def _parse_schedule_fields(form, prefix: str = "") -> dict[str, Any] | None:
    """Liest Zeitplan-Felder aus dem Formular (Prefix z.B. 'competitor_',
    '' für eigene Module). Gibt None zurück, wenn das Formular gar keine
    Zeitplan-Felder enthält (alte Posts/Tests bleiben unberührt)."""
    if f"{prefix}schedule_time" not in form:
        return None

    def get(name: str, default: str = "") -> str:
        return str(form.get(name, default)).strip()

    time = get(f"{prefix}schedule_time", "06:00")
    freq = get(f"{prefix}schedule_frequency", "daily").lower()
    day = get(f"{prefix}schedule_weekday", "mon").lower()
    return {
        "use_default": f"{prefix}schedule_custom" not in form,
        "enabled": f"{prefix}schedule_enabled" in form,
        "time": time if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time) else "06:00",
        "frequency": freq if freq in ("daily", "weekly") else "daily",
        "weekday": day if day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") else "mon",
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    context = {
        "modules": raw_cfg.get("modules", {}),
        "custom_modules": raw_cfg.get("custom_modules", []),
        "run_status": _run_status_view(),
        "budget": _budget_snapshot(raw_cfg),
        "reports": _list_reports(raw_cfg, limit=8),
        "ollama_base_url": raw_cfg.get("ollama", {}).get("base_url", ""),
        "config_missing_api_key": not raw_cfg.get("brave", {}).get("api_key"),
        "schedule": _schedule_info(raw_cfg),
        "schedules": _all_module_schedules(raw_cfg),
        "titles": {name: pretty_module_name(name)
                   for name in list(raw_cfg.get("modules", {}))
                   + [cm.get("name") for cm in raw_cfg.get("custom_modules", []) if cm.get("name")]},
        "timer": _timer_status(),
    }
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    return templates.TemplateResponse(
        request, "settings.html",
        {"cfg": raw_cfg, "schedules": _all_module_schedules(raw_cfg), "saved": False},
    )


@app.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request):
    form = await request.form()
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)

    def get(name: str, default: str = "") -> str:
        return str(form.get(name, default)).strip()

    raw_cfg["brave"]["api_key"] = get("brave_api_key", raw_cfg["brave"].get("api_key", ""))
    raw_cfg["brave"]["max_requests_per_month"] = int(get("brave_max_requests_per_month", "950") or 950)

    raw_cfg["ollama"]["base_url"] = get("ollama_base_url").rstrip("/")
    raw_cfg["ollama"]["model"] = get("ollama_model")

    comp = raw_cfg["modules"].setdefault("competitor_analysis", {})
    comp["enabled"] = "competitor_enabled" in form
    comp["branche"] = get("competitor_branche")
    comp["region"] = get("competitor_region")

    news = raw_cfg["modules"].setdefault("news_digest", {})
    news["enabled"] = "news_enabled" in form
    news["region"] = get("news_region")
    news["stil"] = get("news_stil", "sachlich, lokal, freundlich")
    themen_raw = get("news_themen")
    news["themen"] = [t.strip() for t in themen_raw.split(",") if t.strip()]

    raw_cfg["output"]["email_to"] = get("email_to")
    raw_cfg["output"]["email_from"] = get("email_from")
    smtp = raw_cfg["output"].setdefault("smtp", {})
    smtp["host"] = get("smtp_host")
    smtp["port"] = int(get("smtp_port", "587") or 587)
    smtp["user"] = get("smtp_user")
    smtp["password"] = get("smtp_password", smtp.get("password", ""))
    smtp["use_tls"] = "smtp_use_tls" in form

    sched = raw_cfg.setdefault("schedule", {})
    sched["enabled"] = "schedule_enabled" in form
    wanted_time = get("schedule_time", sched.get("time", "06:00"))
    sched["time"] = wanted_time if re.fullmatch(r"\d{2}:\d{2}", wanted_time) else "06:00"
    wanted_freq = get("schedule_frequency", sched.get("frequency", "daily"))
    sched["frequency"] = wanted_freq if wanted_freq in ("daily", "weekly") else "daily"
    wanted_day = get("schedule_weekday", sched.get("weekday", "mon")).lower()
    sched["weekday"] = wanted_day if wanted_day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") else "mon"

    # Eigene Zeitpläne der eingebauten Module (nur wenn das Formular
    # Zeitplan-Felder mitschickt -- sonst Bestand lassen).
    comp_sched = _parse_schedule_fields(form, prefix="competitor_")
    if comp_sched is not None:
        comp["schedule"] = comp_sched
    news_sched = _parse_schedule_fields(form, prefix="news_")
    if news_sched is not None:
        news["schedule"] = news_sched

    config_io.save_raw_config(CONFIG_PATH, raw_cfg)
    logger.info("Konfiguration über Dashboard aktualisiert (%s)", CONFIG_PATH)

    return templates.TemplateResponse(
        request, "settings.html",
        {"cfg": raw_cfg, "schedules": _all_module_schedules(raw_cfg), "saved": True},
    )


@app.get("/api/ollama-models")
def api_ollama_models(base_url: str = ""):
    """Fragt /api/tags der externen Ollama-Instanz ab, damit das Dashboard
    eine Auswahlliste der dort bereits installierten Modelle anzeigen kann,
    statt den Modellnamen frei eintippen zu müssen."""
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    url = (base_url or raw_cfg.get("ollama", {}).get("base_url", "")).strip().rstrip("/")
    if not url:
        return JSONResponse({"models": [], "error": "Keine Ollama-URL angegeben."})
    try:
        resp = requests.get(f"{url}/api/tags", timeout=8)
        resp.raise_for_status()
        data = resp.json()
        models = sorted({m.get("name") for m in data.get("models", []) if m.get("name")})
        return JSONResponse({"models": models})
    except requests.RequestException as exc:
        return JSONResponse({"models": [], "error": f"Ollama nicht erreichbar: {exc}"})
    except ValueError:
        return JSONResponse({"models": [], "error": "Unerwartete Antwort von Ollama."})


@app.get("/api/ollama-test")
def api_ollama_test(base_url: str = "", model: str = ""):
    """Prüft vor dem Speichern/Lauf, ob Base-URL erreichbar ist und das Modell
    dort installiert ist. Gibt klares Feedback statt dem kryptischen
    '404 Client Error for /api/generate' erst beim nächtlichen Lauf."""
    url = (base_url or "").strip().rstrip("/")
    name = (model or "").strip()
    if not url:
        return JSONResponse({"ok": False, "message": "Keine Ollama-URL angegeben."})
    if not name:
        return JSONResponse({"ok": False, "message": "Kein Modell angegeben."})
    try:
        resp = requests.get(f"{url}/api/tags", timeout=8)
        resp.raise_for_status()
        data = resp.json()
        models = sorted({m.get("name") for m in data.get("models", []) if m.get("name")})
    except requests.RequestException as exc:
        return JSONResponse(
            {
                "ok": False,
                "message": f"Ollama unter {url} nicht erreichbar: {exc}. "
                "Läuft Ollama? Stimmt IP/Port? Erreichbar vom LXC aus?",
            }
        )
    except ValueError:
        return JSONResponse({"ok": False, "message": "Unerwartete Antwort von Ollama (/api/tags)."})

    # "llama3.1" soll auch "llama3.1:latest" treffen
    def _base(n: str) -> str:
        return n.split(":")[0].lower()

    match = name in models or any(_base(m) == _base(name) for m in models)
    if not match:
        shown = ", ".join(models[:10]) if models else "keine"
        return JSONResponse(
            {
                "ok": False,
                "models": models,
                "message": f"Modell '{name}' ist auf {url} NICHT installiert. "
                f"Installiert: {shown}. "
                f"Auf dem Ollama-Host 'ollama pull {name}' ausführen "
                f"oder ein installiertes Modell aus der Liste wählen.",
            }
        )

    # Optionaler Tiefen-Check per /api/show (ältere Ollama-Versionen ohne
    # diesen Endpunkt gelten bei Tags-Treffer trotzdem als OK).
    try:
        show = requests.post(f"{url}/api/show", json={"name": name}, timeout=15)
        if show.status_code == 404:
            return JSONResponse(
                {
                    "ok": False,
                    "models": models,
                    "message": f"Modell '{name}' meldet 404 per /api/show "
                    f"-- exakten Namen aus der Liste übernehmen.",
                }
            )
        show.raise_for_status()
    except requests.RequestException:
        pass  # Tags-Treffer reicht als Positiv-Signal
    except ValueError:
        pass

    return JSONResponse(
        {"ok": True, "models": models, "message": f"✔ OK: '{name}' auf {url} bereit."}
    )


@app.get("/api/run-status")
def api_run_status():
    """JSON-Status aller Modul-Läufe für das Dashboard-Auto-Refresh
    (Start-/Fertig-Zeit, Dauer, Report-Datei)."""
    view = _run_status_view()
    payload: dict[str, dict[str, Any]] = {}
    for name, st in view.items():
        item = dict(st)
        for key in ("started_at", "finished_at"):
            val = item.get(key)
            if isinstance(val, datetime):
                item[key] = val.isoformat()
        payload[name] = item
    return JSONResponse({"runs": payload})


def _execute_run(module_name: str) -> None:
    with _RUN_LOCK:
        RUN_STATUS[module_name] = {"status": "running", "started_at": datetime.now(timezone.utc)}
    try:
        config = load_config(CONFIG_PATH)
        result = pipeline.run_module(module_name, config)
        report_path = output.write_report(result, config.output)
        output.send_report_email(result, report_path, config.output)
        finished = datetime.now(timezone.utc)
        with _RUN_LOCK:
            started = RUN_STATUS.get(module_name, {}).get("started_at", finished)
            RUN_STATUS[module_name] = {
                "status": "error" if result.budget_exhausted and not result.queries_run else "done",
                "started_at": started,
                "finished_at": finished,
                "duration_seconds": (finished - started).total_seconds()
                if isinstance(started, datetime) else None,
                "report_file": report_path.name,
                "budget_exhausted": result.budget_exhausted,
            }
    except (BudgetExceededError, OllamaError, ValueError) as exc:
        logger.error("Lauf '%s' fehlgeschlagen: %s", module_name, exc)
        with _RUN_LOCK:
            RUN_STATUS[module_name] = {"status": "error", "finished_at": datetime.now(timezone.utc), "error": str(exc)}
    except Exception as exc:  # unerwarteter Fehler -- im Dashboard sichtbar machen statt verschlucken
        logger.exception("Unerwarteter Fehler im Lauf '%s'", module_name)
        with _RUN_LOCK:
            RUN_STATUS[module_name] = {"status": "error", "finished_at": datetime.now(timezone.utc), "error": str(exc)}


@app.post("/run/{module_name}")
def trigger_run(module_name: str, background_tasks: BackgroundTasks):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    if module_name not in _valid_module_names(raw_cfg):
        return PlainTextResponse(f"Unbekanntes Modul: {module_name}", status_code=404)
    if RUN_STATUS.get(module_name, {}).get("status") == "running":
        return RedirectResponse("/", status_code=303)
    background_tasks.add_task(_execute_run, module_name)
    with _RUN_LOCK:
        RUN_STATUS[module_name] = {"status": "running", "started_at": datetime.now(timezone.utc)}
    return RedirectResponse("/", status_code=303)


@app.get("/modules", response_class=HTMLResponse)
def modules_list(request: Request):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    return templates.TemplateResponse(
        request,
        "modules.html",
        {
            "builtin_modules": raw_cfg.get("modules", {}),
            "custom_modules": raw_cfg.get("custom_modules", []),
            "schedules": _all_module_schedules(raw_cfg),
            "titles": {name: pretty_module_name(name)
                       for name in list(raw_cfg.get("modules", {}))
                       + [cm.get("name") for cm in raw_cfg.get("custom_modules", []) if cm.get("name")]},
            "templates": TEMPLATES,
        },
    )


def _schedule_form_defaults(raw_cfg: dict[str, Any], module: dict[str, Any] | None) -> dict[str, Any]:
    """Vorbelegung für das Zeitplan-Formular eigener Module: effektive Werte
    plus getrennte Flags für 'eigener Zeitplan' und 'automatisch'."""
    eff = schedule_units.effective_schedule(raw_cfg, module)
    own = ((module or {}).get("schedule") or {}) if isinstance(module, dict) else {}
    return {
        "custom": bool(own and not own.get("use_default", True)),
        "enabled": eff["auto"],
        "time": eff["time"],
        "frequency": eff["frequency"],
        "weekday": eff["weekday"],
        "global_human": schedule_units.effective_schedule(raw_cfg, None)["human"],
    }


@app.get("/modules/new", response_class=HTMLResponse)
def module_new_form(request: Request):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    return templates.TemplateResponse(
        request,
        "module_form.html",
        {"module": None, "error": None, "is_edit": False,
         "sched": _schedule_form_defaults(raw_cfg, None)},
    )


@app.get("/modules/{name}/edit", response_class=HTMLResponse)
def module_edit_form(request: Request, name: str):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    module = config_io.find_custom_module(raw_cfg, name)
    if module is None:
        return PlainTextResponse("Modul nicht gefunden.", status_code=404)
    return templates.TemplateResponse(
        request,
        "module_form.html",
        {"module": module, "error": None, "is_edit": True,
         "sched": _schedule_form_defaults(raw_cfg, module)},
    )


@app.get("/modules/from-template/{key}", response_class=HTMLResponse)
def module_from_template_form(request: Request, key: str):
    """Schritt 1: Vorlage wählen -> nur Region/Stadt/... ausfüllen statt
    Queries von Hand zu schreiben."""
    template = get_template(key)
    if template is None:
        return PlainTextResponse("Vorlage nicht gefunden.", status_code=404)
    return templates.TemplateResponse(
        request,
        "module_template_form.html",
        {"template": template, "values": {}, "module_name": template["suggested_name"],
         "error": None, "queries_text": "", "queries_touched": False},
    )


@app.post("/modules/from-template/{key}", response_class=HTMLResponse)
async def module_from_template_save(request: Request, key: str):
    template = get_template(key)
    if template is None:
        return PlainTextResponse("Vorlage nicht gefunden.", status_code=404)
    form = await request.form()
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)

    values = {f["name"]: str(form.get(f"field_{f['name']}", "")).strip() for f in template["fields"]}
    module_name = str(form.get("name", "")).strip() or template["suggested_name"]
    search_type = "news" if form.get("search_type") == "news" else template["search_type"]
    system_prompt = str(form.get("system_prompt", "")).strip() or template["system_prompt"]

    def show(error: str, queries_text: str, touched: bool):
        return templates.TemplateResponse(
            request, "module_template_form.html",
            {"template": template, "values": values, "module_name": module_name,
             "error": error, "queries_text": queries_text, "queries_touched": touched,
             "search_type": search_type, "system_prompt": system_prompt},
        )

    # Manuell erweiterte Vorschau gewinnt; sonst aus der Vorlage rendern.
    touched = str(form.get("queries_touched", "")).strip() == "1"
    submitted = [line.strip() for line in str(form.get("queries", "")).splitlines()]
    submitted = [q for q in dict.fromkeys(submitted) if q]  # entleeren + dedupe
    if touched:
        if not submitted:
            return show("Bitte mindestens eine Suchanfrage angeben (oder auf Vorlage zurücksetzen).", "", True)
        queries = submitted
    else:
        try:
            queries = render_queries(template, values)
        except ValueError as exc:
            return show(str(exc), "", False)

    slug = _slugify(module_name)
    if not module_name:
        return show("Bitte einen Namen für das Modul angeben.", "\n".join(queries), touched)
    if slug in RESERVED_MODULE_NAMES:
        return show(f"Der Name '{slug}' ist reserviert, bitte einen anderen wählen.", "\n".join(queries), touched)
    if config_io.find_custom_module(raw_cfg, slug) is not None:
        return show(f"Ein Modul namens '{slug}' existiert bereits.", "\n".join(queries), touched)

    config_io.upsert_custom_module(raw_cfg, {
        "name": slug,
        "enabled": "enabled" in form,
        "search_type": search_type,
        "queries": queries,
        "system_prompt": system_prompt,
    })
    config_io.save_raw_config(CONFIG_PATH, raw_cfg)
    logger.info("Modul '%s' aus Vorlage '%s' angelegt (%d Queries)", slug, key, len(queries))
    return RedirectResponse("/modules", status_code=303)


def _module_from_form(form) -> dict[str, Any]:
    queries = [line.strip() for line in str(form.get("queries", "")).splitlines() if line.strip()]
    module = {
        "name": str(form.get("name", "")).strip(),
        "enabled": "enabled" in form,
        "search_type": "news" if form.get("search_type") == "news" else "web",
        "queries": queries,
        "system_prompt": str(form.get("system_prompt", "")).strip(),
    }
    sched = _parse_schedule_fields(form)
    if sched is not None:
        module["schedule"] = sched
    return module


@app.post("/modules/new", response_class=HTMLResponse)
async def module_new_save(request: Request):
    form = await request.form()
    module = _module_from_form(form)
    original_name = module["name"]
    module["name"] = _slugify(original_name)

    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    error = None
    if not original_name:
        error = "Bitte einen Namen für das Modul angeben."
    elif module["name"] in RESERVED_MODULE_NAMES:
        error = f"Der Name '{module['name']}' ist reserviert, bitte einen anderen wählen."
    elif config_io.find_custom_module(raw_cfg, module["name"]) is not None:
        error = f"Ein Modul namens '{module['name']}' existiert bereits."
    elif not module["queries"]:
        error = "Bitte mindestens eine Suchanfrage angeben (eine pro Zeile)."

    if error:
        return templates.TemplateResponse(
            request, "module_form.html", {"module": {**module, "name": original_name}, "error": error, "is_edit": False,
                                          "sched": _schedule_form_defaults(raw_cfg, module)}
        )

    config_io.upsert_custom_module(raw_cfg, module)
    config_io.save_raw_config(CONFIG_PATH, raw_cfg)
    logger.info("Neues eigenes Modul '%s' angelegt", module["name"])
    return RedirectResponse("/modules", status_code=303)


@app.post("/modules/{name}/edit", response_class=HTMLResponse)
async def module_edit_save(request: Request, name: str):
    form = await request.form()
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    existing = config_io.find_custom_module(raw_cfg, name)
    if existing is None:
        return PlainTextResponse("Modul nicht gefunden.", status_code=404)

    module = _module_from_form(form)
    module["name"] = name  # Name bleibt beim Bearbeiten fest (ist der Identifier)
    if "schedule" not in module and "schedule" in existing:
        module["schedule"] = existing["schedule"]  # Bestand lassen, wenn Formular nichts mitschickt

    if not module["queries"]:
        return templates.TemplateResponse(
            request,
            "module_form.html",
            {"module": module, "error": "Bitte mindestens eine Suchanfrage angeben (eine pro Zeile).", "is_edit": True,
             "sched": _schedule_form_defaults(raw_cfg, module)},
        )

    config_io.upsert_custom_module(raw_cfg, module)
    config_io.save_raw_config(CONFIG_PATH, raw_cfg)
    logger.info("Eigenes Modul '%s' aktualisiert", name)
    return RedirectResponse("/modules", status_code=303)


@app.post("/modules/{name}/delete")
def module_delete(name: str):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    config_io.delete_custom_module(raw_cfg, name)
    config_io.save_raw_config(CONFIG_PATH, raw_cfg)
    with _RUN_LOCK:
        RUN_STATUS.pop(name, None)
    logger.info("Eigenes Modul '%s' gelöscht", name)
    return RedirectResponse("/modules", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
def reports_list(request: Request, q: str = ""):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    query = (q or "").strip()
    reports = _list_reports(raw_cfg)
    results: list[dict[str, Any]] | None = None
    if query:
        results = _search_reports(_reports_dir(raw_cfg), reports, query)
    return templates.TemplateResponse(
        request, "reports.html", {"reports": reports, "query": query, "results": results}
    )


def _search_reports(
    reports_dir: Path, reports_meta: list[dict[str, Any]], query: str, limit_files: int = 200
) -> list[dict[str, Any]]:
    """Volltextsuche über Report-Dateien (neueste zuerst, Dateinamen-Treffer
    vorne). Gibt Treffer mit Textausschnitt zurück."""
    q = query.lower()
    hits: list[dict[str, Any]] = []
    for meta in reports_meta[:limit_files]:
        try:
            text = (reports_dir / meta["name"]).read_text(encoding="utf-8")
        except OSError:
            continue
        idx = text.lower().find(q)
        name_hit = q in meta["name"].lower()
        if idx == -1 and not name_hit:
            continue
        if idx == -1:
            excerpt = " ".join(text[:200].split())
        else:
            start = max(0, idx - 100)
            snippet = " ".join(text[start : idx + 100].split())
            excerpt = ("…" if start > 0 else "") + snippet + "…"
        hits.append({**meta, "excerpt": excerpt, "name_hit": name_hit})
    hits.sort(key=lambda h: not h["name_hit"])  # stabil: Dateinamen-Treffer zuerst
    return [{k: v for k, v in h.items() if k != "name_hit"} for h in hits]


@app.get("/reports/{filename}", response_class=HTMLResponse)
def report_detail(request: Request, filename: str):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    path, error = _resolve_report_file(raw_cfg, filename)
    if error is not None:
        return error

    content_html = md_lib.markdown(path.read_text(encoding="utf-8"))
    sidecar = output.load_sources_sidecar(_reports_dir(raw_cfg), filename) or {}
    pretty = pretty_report({"name": filename, "mtime": datetime.fromtimestamp(path.stat().st_mtime)})
    return templates.TemplateResponse(
        request, "report.html", {"filename": filename, "content_html": content_html,
                                 "pretty": pretty,
                                 "query_count": len(sidecar.get("queries_run", []) or []),
                                 "has_sidecar": bool(sidecar),
                                 "question": "", "answer_html": None, "ask_error": None,
                                 "source_count": len(sidecar.get("sources", []) or [])}
    )


def _resolve_report_file(raw_cfg: dict[str, Any], filename: str):
    """Report-Pfad auflösen inkl. Schutz vor Pfad-Traversal.
    Gibt (path, None) oder (None, Fehler-Response) zurück."""
    reports_dir = _reports_dir(raw_cfg)
    path = (reports_dir / filename).resolve()
    # Verhindert Pfad-Traversal (z.B. filename=../../etc/passwd)
    if reports_dir.resolve() not in path.parents or path.suffix != ".md":
        return None, PlainTextResponse("Ungültiger Dateiname.", status_code=400)
    if not path.exists():
        return None, PlainTextResponse("Report nicht gefunden.", status_code=404)
    return path, None


@app.get("/reports/{filename}/pdf")
def report_pdf(filename: str):
    """Report als PDF-Download (zum Ablegen/Weitergeben)."""
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    path, error = _resolve_report_file(raw_cfg, filename)
    if error is not None:
        return error
    try:
        pdf_bytes = output.render_report_pdf(path.read_text(encoding="utf-8"), title=path.stem)
    except RuntimeError as exc:
        logger.error("PDF-Erzeugung für %s fehlgeschlagen: %s", filename, exc)
        return PlainTextResponse("PDF konnte nicht erzeugt werden.", status_code=500)
    pdf_name = f"{path.stem}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{pdf_name}"'},
    )


MAX_FOLLOWUP_SOURCES = 50
MAX_FOLLOWUP_REPORT_CHARS = 12000


def build_followup_prompt(
    question: str, report_md: str, sidecar: dict[str, Any] | None
) -> tuple[str, str]:
    """Baut den Nachfrage-Prompt aus Report-Text + gespeicherten Quellen.
    Rein lokal (Ollama), kein Brave-Lauf, kein Budget-Verbrauch."""
    sources = ((sidecar or {}).get("sources", []) or [])[:MAX_FOLLOWUP_SOURCES]
    if sources:
        lines = []
        for s in sources:
            age = f" ({s.get('age')})" if s.get("age") else ""
            snippet = (s.get("snippet") or "")[:500]
            lines.append(
                f"- {s.get('title') or s.get('url', '')}{age} "
                f"({s.get('url', '')}): {snippet}"
            )
        src_block = "\n".join(lines)
        src_note = f"{len(sources)} gespeicherte Quellen"
    else:
        src_block = "(keine strukturierten Quellen vorhanden -- nur Report-Text)"
        src_note = "nur Report-Text (alter Report ohne Quellen-Sidecar)"
    system = (
        "Du beantwortest eine Nachfrage zu einem vorliegenden Recherche-Report. "
        "Nutze AUSSCHLIESSLICH den Report-Text und die gespeicherten Quellen unten -- "
        "keine neuen Recherchen, keine erfundenen Fakten. Wenn die Antwort nicht in "
        "den Daten steht, sage das ehrlich und schlage ggf. eine neue Suche vor. "
        "Belege Aussagen mit Markdown-Links [Titel](URL). Antworte auf Deutsch, "
        "kurz und konkret."
    )
    user = (
        f"Frage: {question}\n\n"
        f"Report-Text:\n{report_md[:MAX_FOLLOWUP_REPORT_CHARS]}\n\n"
        f"Gespeicherte Quellen ({src_note}):\n{src_block}"
    )
    return system, user


@app.post("/reports/{filename}/ask", response_class=HTMLResponse)
async def report_ask(request: Request, filename: str):
    """Nachfrage zum Report beantworten -- nur Ollama + gespeicherte Daten,
    bewusst OHNE Brave-Lauf (verbraucht kein Budget). Braucht nicht einmal
    einen Brave API Key, nur Ollama-Einstellungen."""
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    path, error = _resolve_report_file(raw_cfg, filename)
    if error is not None:
        return error

    form = await request.form()
    question = str(form.get("question", "")).strip()
    md_text = path.read_text(encoding="utf-8")
    content_html = md_lib.markdown(md_text)

    def show(answer_html=None, ask_error=None):
        sidecar = output.load_sources_sidecar(_reports_dir(raw_cfg), filename) or {}
        pretty = pretty_report({"name": filename, "mtime": datetime.fromtimestamp(path.stat().st_mtime)})
        return templates.TemplateResponse(
            request, "report.html",
            {"filename": filename, "content_html": content_html,
             "pretty": pretty,
             "query_count": len(sidecar.get("queries_run", []) or []),
             "has_sidecar": bool(sidecar),
             "question": question, "answer_html": answer_html,
             "ask_error": ask_error,
             "source_count": len(sidecar.get("sources", []) or [])},
        )

    if not question:
        return show(ask_error="Bitte eine Frage eingeben.")

    ollama_cfg = raw_cfg.get("ollama", {}) or {}
    base_url = str(ollama_cfg.get("base_url", "") or "").strip()
    model = str(ollama_cfg.get("model", "") or "").strip()
    if not base_url or not model:
        return show(ask_error="Kein Ollama-Modell konfiguriert -- erst unter Einstellungen wählen und speichern.")
    try:
        timeout = int(ollama_cfg.get("timeout_seconds", 180) or 180)
    except (TypeError, ValueError):
        timeout = 180

    sidecar = output.load_sources_sidecar(_reports_dir(raw_cfg), filename)
    system, user = build_followup_prompt(question, md_text, sidecar)
    try:
        answer_md = OllamaClient(base_url, model, timeout).generate(user, system=system)
    except OllamaError as exc:
        logger.error("Nachfrage zu %s fehlgeschlagen: %s", filename, exc)
        return show(ask_error=str(exc))
    return show(answer_html=md_lib.markdown(answer_md))
