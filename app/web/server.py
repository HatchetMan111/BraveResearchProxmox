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
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown as md_lib
import requests
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import output, pipeline
from ..budget_tracker import BudgetExceededError, BudgetTracker
from ..config import load_config
from ..modules import MODULES
from ..ollama_client import OllamaError
from . import config_io

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("RESEARCH_LXC_CONFIG", "config.yaml")).resolve()

# Namen, die nicht für eigene Module verwendet werden dürfen: die beiden
# eingebauten Module sowie "all" (reserviert für --module all).
RESERVED_MODULE_NAMES = set(MODULES) | {"all"}

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
        return {"used": status.used, "limit": status.limit, "remaining": status.remaining, "month": status.month}
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
    return [{"name": f.name, "mtime": datetime.fromtimestamp(f.stat().st_mtime)} for f in files]


def _valid_module_names(raw_cfg: dict[str, Any]) -> set[str]:
    return set(MODULES) | {cm.get("name") for cm in raw_cfg.get("custom_modules", []) if cm.get("name")}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    context = {
        "modules": raw_cfg.get("modules", {}),
        "custom_modules": raw_cfg.get("custom_modules", []),
        "run_status": RUN_STATUS,
        "budget": _budget_snapshot(raw_cfg),
        "reports": _list_reports(raw_cfg, limit=8),
        "ollama_base_url": raw_cfg.get("ollama", {}).get("base_url", ""),
        "config_missing_api_key": not raw_cfg.get("brave", {}).get("api_key"),
    }
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    return templates.TemplateResponse(request, "settings.html", {"cfg": raw_cfg, "saved": False})


@app.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request):
    form = await request.form()
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)

    def get(name: str, default: str = "") -> str:
        return str(form.get(name, default)).strip()

    raw_cfg["brave"]["api_key"] = get("brave_api_key", raw_cfg["brave"].get("api_key", ""))
    raw_cfg["brave"]["max_requests_per_month"] = int(get("brave_max_requests_per_month", "950") or 950)

    raw_cfg["ollama"]["base_url"] = get("ollama_base_url")
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

    config_io.save_raw_config(CONFIG_PATH, raw_cfg)
    logger.info("Konfiguration über Dashboard aktualisiert (%s)", CONFIG_PATH)

    return templates.TemplateResponse(request, "settings.html", {"cfg": raw_cfg, "saved": True})


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


def _execute_run(module_name: str) -> None:
    with _RUN_LOCK:
        RUN_STATUS[module_name] = {"status": "running", "started_at": datetime.now(timezone.utc)}
    try:
        config = load_config(CONFIG_PATH)
        result = pipeline.run_module(module_name, config)
        report_path = output.write_report(result, config.output)
        output.send_report_email(result, report_path, config.output)
        with _RUN_LOCK:
            RUN_STATUS[module_name] = {
                "status": "error" if result.budget_exhausted and not result.queries_run else "done",
                "finished_at": datetime.now(timezone.utc),
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
        },
    )


@app.get("/modules/new", response_class=HTMLResponse)
def module_new_form(request: Request):
    return templates.TemplateResponse(
        request,
        "module_form.html",
        {"module": None, "error": None, "is_edit": False},
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
        {"module": module, "error": None, "is_edit": True},
    )


def _module_from_form(form) -> dict[str, Any]:
    queries = [line.strip() for line in str(form.get("queries", "")).splitlines() if line.strip()]
    return {
        "name": str(form.get("name", "")).strip(),
        "enabled": "enabled" in form,
        "search_type": "news" if form.get("search_type") == "news" else "web",
        "queries": queries,
        "system_prompt": str(form.get("system_prompt", "")).strip(),
    }


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
            request, "module_form.html", {"module": {**module, "name": original_name}, "error": error, "is_edit": False}
        )

    config_io.upsert_custom_module(raw_cfg, module)
    config_io.save_raw_config(CONFIG_PATH, raw_cfg)
    logger.info("Neues eigenes Modul '%s' angelegt", module["name"])
    return RedirectResponse("/modules", status_code=303)


@app.post("/modules/{name}/edit", response_class=HTMLResponse)
async def module_edit_save(request: Request, name: str):
    form = await request.form()
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    if config_io.find_custom_module(raw_cfg, name) is None:
        return PlainTextResponse("Modul nicht gefunden.", status_code=404)

    module = _module_from_form(form)
    module["name"] = name  # Name bleibt beim Bearbeiten fest (ist der Identifier)

    if not module["queries"]:
        return templates.TemplateResponse(
            request,
            "module_form.html",
            {"module": module, "error": "Bitte mindestens eine Suchanfrage angeben (eine pro Zeile).", "is_edit": True},
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
def reports_list(request: Request):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    return templates.TemplateResponse(
        request, "reports.html", {"reports": _list_reports(raw_cfg)}
    )


@app.get("/reports/{filename}", response_class=HTMLResponse)
def report_detail(request: Request, filename: str):
    raw_cfg = config_io.load_raw_config(CONFIG_PATH)
    reports_dir = _reports_dir(raw_cfg)
    path = (reports_dir / filename).resolve()
    # Verhindert Pfad-Traversal (z.B. filename=../../etc/passwd)
    if reports_dir.resolve() not in path.parents or path.suffix != ".md":
        return PlainTextResponse("Ungültiger Dateiname.", status_code=400)
    if not path.exists():
        return PlainTextResponse("Report nicht gefunden.", status_code=404)

    content_html = md_lib.markdown(path.read_text(encoding="utf-8"))
    return templates.TemplateResponse(
        request, "report.html", {"filename": filename, "content_html": content_html}
    )
