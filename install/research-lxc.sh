#!/usr/bin/env bash
# Recherche-LXC Installer
# Im Stil der Proxmox VE Community Helper Scripts (community-scripts.github.io/ProxmoxVE)
#
# Wird INNERHALB eines bereits erstellten Debian/Ubuntu-LXC-Containers als root
# ausgeführt (Container-Erstellung siehe README.md):
#
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BraveResearchProxmox/main/install/research-lxc.sh)"
#
# Idempotent: erneutes Ausführen aktualisiert Repo, venv und Konfiguration,
# ohne bestehende config.yaml zu überschreiben.

set -euo pipefail

REPO_URL="https://github.com/HatchetMan111/BraveResearchProxmox.git"
APP_DIR="/opt/research-lxc"
SERVICE_USER="research"

# ---------- Farbige Ausgabe (Community-Scripts-Stil) ----------
RD=$(printf '\033[01;31m'); GN=$(printf '\033[1;92m'); YW=$(printf '\033[33m')
CL=$(printf '\033[m')
msg_info()  { echo -e " ${YW}➜${CL} $1"; }
msg_ok()    { echo -e " ${GN}✔${CL} $1"; }
msg_error() { echo -e " ${RD}✘${CL} $1"; }

if [[ $EUID -ne 0 ]]; then
  msg_error "Bitte als root ausführen."
  exit 1
fi

msg_info "Aktualisiere Paketquellen und installiere Abhängigkeiten..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl >/dev/null
msg_ok "Systemabhängigkeiten installiert (python3, venv, git)"

if ! id "$SERVICE_USER" &>/dev/null; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  msg_ok "Service-User '$SERVICE_USER' angelegt"
else
  msg_info "Service-User '$SERVICE_USER' existiert bereits"
fi

if [[ -d "$APP_DIR/.git" ]]; then
  msg_info "Bestehende Installation gefunden, aktualisiere Repo..."
  git -C "$APP_DIR" pull --ff-only
  msg_ok "Repo aktualisiert"
else
  msg_info "Klone Repository nach $APP_DIR..."
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
  msg_ok "Repository geklont"
fi

msg_info "Erstelle Python-venv und installiere Requirements..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
msg_ok "venv unter $APP_DIR/venv eingerichtet"

mkdir -p "$APP_DIR/data" "$APP_DIR/reports"

if [[ -f "$APP_DIR/config.yaml" ]]; then
  msg_info "config.yaml existiert bereits, wird NICHT überschrieben."
else
  cp "$APP_DIR/config.example.yaml" "$APP_DIR/config.yaml"
  # Platzhalter-Werte leeren -- die eigentliche Konfiguration (Brave API Key,
  # Ollama-URL, Branche, Region, ...) erfolgt komplett über das Web-Dashboard
  # unter /settings, nicht mehr per SSH-Terminal-Abfrage.
  sed -i \
    -e 's|DEIN_BRAVE_API_KEY||' \
    -e 's|http://OLLAMA-HOST:11434||' \
    "$APP_DIR/config.yaml"
  msg_ok "config.yaml aus Vorlage erstellt (noch leer -- Konfiguration erfolgt im Dashboard)"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

msg_info "Installiere systemd-Units..."
cp "$APP_DIR/deploy/research-lxc@.service" /etc/systemd/system/
cp "$APP_DIR/deploy/research-lxc-competitor.timer" /etc/systemd/system/
cp "$APP_DIR/deploy/research-lxc-news.timer" /etc/systemd/system/
cp "$APP_DIR/deploy/research-lxc-web.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now research-lxc-competitor.timer research-lxc-news.timer
msg_ok "Timer aktiviert (Konkurrenzanalyse wöchentlich Mo 06:00, News-Digest täglich 07:00)"
systemctl enable --now research-lxc-web.service
msg_ok "Web-Dashboard gestartet (Port 8000)"

IP=$(hostname -I | awk '{print $1}')

echo ""
msg_ok "Installation abgeschlossen."
echo ""
echo -e "  ${GN}┌──────────────────────────────────────────────────────────┐${CL}"
echo -e "  ${GN}│${CL}  Dashboard:  ${GN}http://${IP}:8000${CL}"
echo -e "  ${GN}│${CL}  Dort zuerst unter '/settings' Brave API Key, Ollama-URL,"
echo -e "  ${GN}│${CL}  Branche/Region und Ziel-E-Mail eintragen."
echo -e "  ${GN}└──────────────────────────────────────────────────────────┘${CL}"
echo ""
echo "  Alternativ per Konsole konfigurieren: nano $APP_DIR/config.yaml"
echo ""
echo "  Manueller Testlauf:"
echo "    cd $APP_DIR && sudo -u $SERVICE_USER venv/bin/python -m app.main \\"
echo "      --module competitor_analysis --config config.yaml --no-email -v"
echo ""
echo "  Nächste Timer-Läufe:  systemctl list-timers 'research-lxc-*'"
echo "  Reports:              ls $APP_DIR/reports/"
echo "  Logs (Batch-Läufe):   journalctl -u research-lxc@competitor_analysis.service"
echo "  Logs (Dashboard):     journalctl -u research-lxc-web.service"
echo ""
