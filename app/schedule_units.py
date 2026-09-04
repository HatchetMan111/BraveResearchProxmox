"""Erzeugt systemd-Timer pro Modul aus config.yaml.

Jedes aktivierte Modul mit aktivem (effektivem) Zeitplan bekommt einen eigenen
Timer `research-lxc-mod-<name>.timer`, der den bestehenden Template-Service
`research-lxc@<name>.service` auslöst. Module mit Zeitplan "nur manuell"
bekommen keinen Timer; veraltete Timer-Dateien werden entfernt.

Der Sammel-Timer `research-lxc-all.timer` wird deaktiviert, sobald mindestens
ein Modul-Timer existiert (sonst liefen Module doppelt); gibt es gar keine
Auto-Module, bleibt er als Rückfall aktiv.

Aufruf (als root -- macht der Installer automatisch nach jedem Lauf):
    cd /opt/research-lxc && venv/bin/python -m app.schedule_units --config config.yaml --apply

Ohne --apply: zeigt nur den geplanten Zustand (dry-run). Nach Änderungen am
Zeitplan im Dashboard also entweder den Installer erneut laufen lassen oder
diesen Befehl als root ausführen -- die Web-UI selbst darf keine systemd-Units
anfassen (läuft als unprivilegierter Service-User).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

TIMER_PREFIX = "research-lxc-mod-"
ALL_TIMER = "research-lxc-all.timer"

WEEKDAY_MAP = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}
WEEKDAY_DE = {
    "mon": "Mo",
    "tue": "Di",
    "wed": "Mi",
    "thu": "Do",
    "fri": "Fr",
    "sat": "Sa",
    "sun": "So",
}

DEFAULT_TIME = "06:00"


def _valid_time(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", text):
        return text
    return DEFAULT_TIME


def _valid_frequency(value: Any) -> str:
    text = str(value or "daily").strip().lower()
    return text if text in ("daily", "weekly") else "daily"


def _valid_weekday(value: Any) -> str:
    text = str(value or "mon").strip().lower()
    return text if text in WEEKDAY_MAP else "mon"


def global_default(raw: dict[str, Any]) -> dict[str, Any]:
    """Der globale Standard-Zeitplan aus config.yaml (Abschnitt `schedule`)."""
    sched = raw.get("schedule", {}) or {}
    return {
        "enabled": bool(sched.get("enabled", True)),
        "time": _valid_time(sched.get("time", DEFAULT_TIME)),
        "frequency": _valid_frequency(sched.get("frequency", "daily")),
        "weekday": _valid_weekday(sched.get("weekday", "mon")),
    }


def effective_schedule(raw: dict[str, Any], module_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Effektiver Zeitplan eines Moduls: eigener (falls use_default falsch)
    oder globaler Standard. Ergebnis enthält immer auto/time/frequency/weekday,
    custom (eigener vs. Standard) und einen lesbaren human-Text."""
    glob = global_default(raw)
    own = ((module_cfg or {}).get("schedule") or {}) if isinstance(module_cfg, dict) else {}
    if not own or own.get("use_default", True):
        auto = glob["enabled"]
        merged = dict(glob)
        custom = False
        prefix = "Standard: "
    else:
        merged = {
            "enabled": bool(own.get("enabled", True)),
            "time": _valid_time(own.get("time", glob["time"])),
            "frequency": _valid_frequency(own.get("frequency", glob["frequency"])),
            "weekday": _valid_weekday(own.get("weekday", glob["weekday"])),
        }
        auto = merged["enabled"]
        custom = True
        prefix = ""
    if not auto:
        human = f"{prefix}nur manuell".strip()
    elif merged["frequency"] == "weekly":
        human = f"{prefix}wöchentlich ({WEEKDAY_DE[merged['weekday']]} {merged['time']} Uhr)"
    else:
        human = f"{prefix}täglich {merged['time']} Uhr"
    return {
        "auto": auto,
        "time": merged["time"],
        "frequency": merged["frequency"],
        "weekday": merged["weekday"],
        "custom": custom,
        "human": human,
    }


def oncalendar(sched: dict[str, Any]) -> str | None:
    """Systemd-OnCalendar-Spezifikation oder None bei 'nur manuell'."""
    if not sched.get("auto"):
        return None
    if sched.get("frequency") == "weekly":
        return f"{WEEKDAY_MAP[sched['weekday']]} *-*-* {sched['time']}:00"
    return f"*-*-* {sched['time']}:00"


def iter_modules(raw: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Alle konfigurierten Module als (name, cfg): eingebaute zuerst,
    dann eigene aus custom_modules."""
    result: list[tuple[str, dict[str, Any]]] = []
    for name, cfg in (raw.get("modules", {}) or {}).items():
        if isinstance(cfg, dict):
            result.append((name, cfg))
    for cm in raw.get("custom_modules", []) or []:
        if isinstance(cm, dict) and cm.get("name"):
            result.append((cm["name"], cm))
    return result


def timer_filename(module_name: str) -> str:
    return f"{TIMER_PREFIX}{module_name}.timer"


def render_timer(module_name: str, oncal: str) -> str:
    return f"""[Unit]
Description=Geplanter Lauf: {module_name} (Recherche-LXC)

[Timer]
OnCalendar={oncal}
Persistent=true
Unit=research-lxc@{module_name}.service

[Install]
WantedBy=timers.target
"""


def compute_plan(raw: dict[str, Any]) -> dict[str, str]:
    """Gewünschte Timer-Dateien {Dateiname: Inhalt} für alle Auto-Module."""
    plan: dict[str, str] = {}
    for name, cfg in iter_modules(raw):
        if not cfg.get("enabled", True):
            continue
        eff = effective_schedule(raw, cfg)
        oncal = oncalendar(eff)
        if oncal is None:
            continue
        plan[timer_filename(name)] = render_timer(name, oncal)
    return plan


def sync_files(units_dir: str | Path, plan: dict[str, str]) -> dict[str, Any]:
    """Schreibt/updated Timer-Dateien, entfernt veraltete. Gibt
    {"written": [...], "removed": [...], "changed": bool} zurück."""
    units_dir = Path(units_dir)
    units_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for fname, content in plan.items():
        path = units_dir / fname
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            written.append(fname)
    removed: list[str] = []
    for path in sorted(units_dir.glob(f"{TIMER_PREFIX}*.timer")):
        if path.name not in plan:
            path.unlink()
            removed.append(path.name)
    return {"written": written, "removed": removed, "changed": bool(written or removed)}


def apply_systemd(plan_names: list[str], removed_names: list[str]) -> dict[str, list[str]]:
    """daemon-reload + Timer (de-)aktivieren. Nur als root sinnvoll."""
    actions: dict[str, list[str]] = {"enabled": [], "disabled": []}

    def run(*args: str) -> None:
        subprocess.run(list(args), capture_output=True, timeout=60, check=False)

    run("systemctl", "daemon-reload")
    for name in plan_names:
        run("systemctl", "enable", "--now", name)
        actions["enabled"].append(name)
    for name in removed_names:
        run("systemctl", "disable", "--now", name)
        actions["disabled"].append(name)
    # Sammel-Timer nur als Rückfall, wenn es gar keine Modul-Timer gibt.
    if plan_names:
        run("systemctl", "disable", "--now", ALL_TIMER)
        actions["disabled"].append(ALL_TIMER)
    else:
        run("systemctl", "enable", "--now", ALL_TIMER)
        actions["enabled"].append(ALL_TIMER)
    return actions


def load_raw_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config nicht gefunden: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Modul-Timer aus config.yaml erzeugen/anwenden")
    parser.add_argument("--config", default="config.yaml", help="Pfad zur config.yaml")
    parser.add_argument("--units-dir", default="/etc/systemd/system", help="Ziel für Timer-Units")
    parser.add_argument("--apply", action="store_true", help="Dateien schreiben + systemd umschalten (root nötig)")
    args = parser.parse_args(argv)

    try:
        raw = load_raw_config(args.config)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    plan = compute_plan(raw)
    if not args.apply:
        if plan:
            print("Geplante Modul-Timer (dry-run, --apply wendet an):")
            for fname in sorted(plan):
                for line in plan[fname].splitlines():
                    if line.startswith("OnCalendar=") or line.startswith("Unit="):
                        print(f"  {fname}: {line}")
        else:
            print("Keine Auto-Module -- Rückfall: research-lxc-all.timer bleibt aktiv.")
        return 0

    result = sync_files(args.units_dir, plan)
    actions = apply_systemd(sorted(plan), result["removed"])
    print(f"Timer geschrieben/aktualisiert: {result['written'] or 'keine'}")
    print(f"Timer entfernt: {result['removed'] or 'keine'}")
    print(f"systemd aktiviert: {actions['enabled'] or 'keine'}")
    print(f"systemd deaktiviert: {actions['disabled'] or 'keine'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
