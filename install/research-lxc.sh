#!/usr/bin/env bash
# Recherche-LXC Installer
# Im Stil der Proxmox VE Community Helper Scripts (community-scripts.github.io/ProxmoxVE)
#
# ZWEI MODI (automatische Erkennung, über Flag erzwingbar):
#
#  1) HOST-MODUS (Standard auf dem Proxmox-Host): erstellt automatisch einen
#     LXC-Container und installiert die App darin. Ein Befehl als root auf dem
#     Proxmox-Host genügt:
#
#       bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BraveResearchProxmox/main/install/research-lxc.sh)"
#
#     Existiert bereits ein Container mit demselben Hostnamen, wird KEIN neuer
#     erstellt, sondern die App darin aktualisiert (Update-Pfad).
#
#  2) CONTAINER-MODUS (innerhalb eines bestehenden LXC als root): installiert
#     bzw. aktualisiert die App direkt. Wird automatisch gewählt, wenn kein
#     Proxmox-Host erkennbar ist, oder explizit per Flag:
#
#       bash -c "$(wget -qLO - .../research-lxc.sh)" -- --inner
#
# Konfiguration über Umgebungsvariablen (alle optional):
#   RESEARCH_CTID=101  RESEARCH_HOSTNAME=research-lxc  RESEARCH_STORAGE=local-lvm
#   RESEARCH_TEMPLATE_STORAGE=local  RESEARCH_CORES=1  RESEARCH_MEMORY=1024
#   RESEARCH_DISK=8  RESEARCH_BRIDGE=vmbr0  RESEARCH_IP=dhcp
#   RESEARCH_PASSWORD=...  (sonst zufällig, wird am Ende einmalig angezeigt)
#   RESEARCH_TEMPLATE=debian-12-standard_12.7-1_amd64.tar.zst (sonst neueste 12er)
#
# Idempotent: erneutes Ausführen aktualisiert Container/Repo/venv/Units,
# ohne bestehende config.yaml zu überschreiben.

set -euo pipefail

REPO_URL="https://github.com/HatchetMan111/BraveResearchProxmox.git"
RAW_SCRIPT_URL="https://raw.githubusercontent.com/HatchetMan111/BraveResearchProxmox/main/install/research-lxc.sh"
APP_DIR="/opt/research-lxc"
SERVICE_USER="research"

# ---------- Farbige Ausgabe (Community-Scripts-Stil) ----------
# Alles nach stderr: stdout bleibt sauber für Command-Substitution
# (z.B. tpl_ref=$(ensure_template) darf keinen Info-Text enthalten).
RD=$(printf '\033[01;31m'); GN=$(printf '\033[1;92m'); YW=$(printf '\033[33m')
CL=$(printf '\033[m')
msg_info()  { echo -e " ${YW}➜${CL} $1" >&2; }
msg_ok()    { echo -e " ${GN}✔${CL} $1" >&2; }
msg_error() { echo -e " ${RD}✘${CL} $1" >&2; }

usage() {
  cat <<'EOF'
Recherche-LXC Installer -- Host-Modus (erstellt LXC) oder Container-Modus (--inner).

Aufruf auf dem Proxmox-Host (erstellt/aktualisiert den Container):
  bash -c "$(wget -qLO - <url>/research-lxc.sh)" [-- CTID 101] [...]

Aufruf im Container (nur App installieren/aktualisieren):
  bash -c "$(wget -qLO - <url>/research-lxc.sh)" -- --inner

Optionen (Host-Modus):
  --ctid ID        Container-ID (Standard: nächste freie ab 100)
  --hostname NAME  Container-Name (Standard: research-lxc)
  --storage NAME   Storage für Root-Disk (Standard: local-lvm)
  --cores N        CPU-Cores (Standard: 1)
  --memory MB      RAM in MB (Standard: 1024)
  --disk GB        Root-Disk in GB (Standard: 8)
  --bridge NAME    Netzwerk-Bridge (Standard: vmbr0)
  --ip ADDR        IP, z.B. dhcp oder 192.168.178.130/24,gw=192.168.178.1 (Standard: dhcp)
  --inner          Container-Modus erzwingen (App direkt installieren)
  --host           Host-Modus erzwingen (LXC erstellen)
  --uninstall      Lokale Installation entfernen (Units, Service-User, /opt/research-lxc)
                   ACHTUNG: löscht auch config.yaml, Reports und Budget-DB!
  -h, --help       Diese Hilfe
Umgebungsvariablen RESEARCH_CTID, RESEARCH_HOSTNAME, RESEARCH_STORAGE,
RESEARCH_CORES, RESEARCH_MEMORY, RESEARCH_DISK, RESEARCH_BRIDGE,
RESEARCH_IP, RESEARCH_PASSWORD, RESEARCH_TEMPLATE wirken identisch.
EOF
}

# ---------- Argumente ----------
FORCE_MODE=""   # "host" | "inner" | ""
UNINSTALL=0
CTID="${RESEARCH_CTID:-}"
HOSTNAME="${RESEARCH_HOSTNAME:-research-lxc}"
STORAGE="${RESEARCH_STORAGE:-local-lvm}"
TPL_STORAGE="${RESEARCH_TEMPLATE_STORAGE:-local}"
CORES="${RESEARCH_CORES:-1}"
MEMORY="${RESEARCH_MEMORY:-1024}"
DISK="${RESEARCH_DISK:-8}"
BRIDGE="${RESEARCH_BRIDGE:-vmbr0}"
IPCONF="${RESEARCH_IP:-dhcp}"
ROOTPW="${RESEARCH_PASSWORD:-}"
TEMPLATE="${RESEARCH_TEMPLATE:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --inner) FORCE_MODE="inner"; shift ;;
    --host) FORCE_MODE="host"; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --ctid) CTID="$2"; shift 2 ;;
    --hostname) HOSTNAME="$2"; shift 2 ;;
    --storage) STORAGE="$2"; shift 2 ;;
    --cores) CORES="$2"; shift 2 ;;
    --memory) MEMORY="$2"; shift 2 ;;
    --disk) DISK="$2"; shift 2 ;;
    --bridge) BRIDGE="$2"; shift 2 ;;
    --ip) IPCONF="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) msg_error "Unbekannte Option: $1 (Hilfe: --help)"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  msg_error "Bitte als root ausführen."
  exit 1
fi

is_proxmox_host() {
  [[ -d /etc/pve ]] && command -v pct >/dev/null 2>&1
}

# Explizites Flag gewinnt, sonst Umgebung erkennen: Proxmox-Host -> host,
# alles andere (LXC/VM/Host ohne PVE) -> inner.
MODE="$FORCE_MODE"
if [[ -z "$MODE" ]]; then
  if is_proxmox_host; then
    MODE="host"
  else
    MODE="inner"
  fi
fi

# =====================================================================
# CONTAINER-MODUS: App direkt installieren/aktualisieren (wie bisher)
# =====================================================================
install_inner() {
  msg_info "Container-Modus: installiere App in diesem Container..."

  if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    msg_ok "Service-User '$SERVICE_USER' angelegt"
  else
    msg_info "Service-User '$SERVICE_USER' existiert bereits"
  fi

  msg_info "Aktualisiere Paketquellen und installiere Abhängigkeiten..."
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip git curl wget >/dev/null
  msg_ok "Systemabhängigkeiten installiert (python3, venv, git)"

  # git läuft in diesem Script immer als root; nach dem ersten Lauf gehört
  # APP_DIR aber dem Service-User 'research' (siehe chown weiter unten).
  # Ohne diese Ausnahme verweigert git ab Version 2.35.2 den Zugriff mit
  # "detected dubious ownership" bei jedem erneuten Lauf (Update/Re-Install).
  git config --global --add safe.directory "$APP_DIR"

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
  cp "$APP_DIR/deploy/research-lxc-all.timer" /etc/systemd/system/
  cp "$APP_DIR/deploy/research-lxc-web.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now research-lxc-all.timer
  msg_ok "Timer aktiviert (alle aktivierten Module täglich 06:00, siehe Dashboard)"
  # WICHTIG: 'enable --now' startet einen bereits laufenden Service NICHT neu
  # (das 'start' darin ist ein No-Op, wenn der Service schon aktiv ist). Ohne
  # expliziten Restart würde das Dashboard nach jedem Update mit dem alten
  # Code im Speicher weiterlaufen -- neue Routen/Features blieben unsichtbar.
  systemctl enable research-lxc-web.service
  systemctl restart research-lxc-web.service
  msg_ok "Web-Dashboard gestartet/aktualisiert (Port 8000)"

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
}

# =====================================================================
# HOST-MODUS: LXC erstellen (oder vorhandenen aktualisieren)
# =====================================================================

# Freie CTID finden (pvesh nextid) bzw. übergebene prüfen.
# Gibt zurück: vorhandene CTID (Update-Pfad) oder freie CTID (Neuanlage).
resolve_ctid() {
  if [[ -n "$CTID" ]]; then
    [[ "$CTID" =~ ^[0-9]+$ ]] || { msg_error "--ctid muss numerisch sein."; exit 1; }
    echo "$CTID"
    return 0
  fi
  # Gleichnamigen Container wiederverwenden (Update-Pfad)?
  local found=""
  found=$(pct list 2>/dev/null | awk -v name="$HOSTNAME" '$3 == name {print $1; exit}')
  if [[ -n "$found" ]]; then
    echo "$found"
    return 0
  fi
  pvesh get /cluster/nextid
}

ensure_template() {
  if [[ -n "$TEMPLATE" ]]; then
    if ! pveam list "$TPL_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
      msg_error "Template '$TEMPLATE' nicht auf Storage '$TPL_STORAGE' gefunden. Verfügbar z.B.:"
      pveam available --section system 2>/dev/null | grep -i "debian-12" | head -5 || true
      exit 1
    fi
    echo "$TPL_STORAGE:vztmpl/$TEMPLATE"
    return 0
  fi
  local tpl=""
  tpl=$(pveam list "$TPL_STORAGE" 2>/dev/null | grep -o "debian-12-standard[^[:space:]]*\.tar\.[a-z0-9.]*" | sort -V | tail -1 || true)
  if [[ -z "$tpl" ]]; then
    msg_info "Lade Debian-12-Template herunter (einmalig)..."
    pveam update >/dev/null
    tpl=$(pveam available --section system 2>/dev/null | grep -o "debian-12-standard[^[:space:]]*\.tar\.[a-z0-9.]*" | sort -V | tail -1 || true)
    if [[ -z "$tpl" ]]; then
      msg_error "Kein Debian-12-Template gefunden."
      exit 1
    fi
    pveam download "$TPL_STORAGE" "$tpl" >/dev/null
    msg_ok "Template $tpl heruntergeladen"
  else
    msg_info "Nutze vorhandenes Template $tpl"
  fi
  echo "$TPL_STORAGE:vztmpl/$tpl"
}

wait_for_network() {
  local ctid="$1" tries=0
  local max_tries="${RESEARCH_WAIT_TRIES:-60}"  # 60 x 2 s = max. 120 s
  msg_info "Warte auf Container-Netzwerk (IP + DNS, max. 120 s)..."
  while [[ $tries -lt $max_tries ]]; do
    if container_ready "$ctid"; then
      local ip=""
      ip=$(pct exec "$ctid" -- hostname -I 2>/dev/null | awk '{print $1}')
      msg_ok "Container-Netz bereit ($ip)"
      return 0
    fi
    sleep 2
    tries=$((tries + 1))
  done
  msg_error "Container-Netz nicht bereit. Diagnose:"
  pct status "$ctid" 2>&1 || true
  pct exec "$ctid" -- sh -c 'grep -H . /sys/class/net/*/operstate' 2>&1 || true
  echo "  container-IP: $(pct exec "$ctid" -- hostname -I 2>/dev/null || echo '?')" >&2
  pct config "$ctid" 2>/dev/null | grep -E "net0|hostname" >&2 || true
  msg_error "Prüfen: DHCP im LAN aktiv? Bridge korrekt (--bridge)? Alternativ statische IP setzen: --ip 192.168.178.130/24,gw=192.168.178.1"
  exit 1
}

# True, wenn der Container läuft, eine IP hat und DNS auflöst.
# Nutzt bewusst KEIN ping: iputils-ping fehlt in minimalen Templates oft,
# getent (glibc) und hostname sind dagegen immer vorhanden.
container_ready() {
  local ctid="$1" ip=""
  pct status "$ctid" 2>/dev/null | grep -q "status: running" || return 1
  ip=$(pct exec "$ctid" -- hostname -I 2>/dev/null | awk '{print $1}')
  [[ -n "$ip" ]] || return 1
  pct exec "$ctid" -- getent hosts github.com >/dev/null 2>&1 || return 1
  return 0
}

run_inner_in_container() {
  local ctid="$1"
  local tmp_host="/tmp/research-lxc-install-$$.sh"
  msg_info "Übertrage Installer in den Container (CT $ctid)..."
  if ! wget -qLO "$tmp_host" "$RAW_SCRIPT_URL"; then
    msg_error "Konnte Installer nicht herunterladen ($RAW_SCRIPT_URL)."
    exit 1
  fi
  pct push "$ctid" "$tmp_host" /root/research-lxc.sh
  rm -f "$tmp_host"
  msg_info "Installiere App im Container (das dauert einige Minuten)..."
  pct exec "$ctid" -- bash /root/research-lxc.sh --inner
}

install_host() {
  command -v pct >/dev/null || { msg_error "pct nicht gefunden -- kein Proxmox-Host? Im Container '--inner' nutzen."; exit 1; }

  local ctid tpl_ref
  ctid=$(resolve_ctid)

  # Update-Pfad: gleichnamiger Container existiert bereits -> nur App aktualisieren.
  if pct status "$ctid" >/dev/null 2>&1; then
    local cur_name=""
    cur_name=$(pct list 2>/dev/null | awk -v id="$ctid" '$1 == id {print $3}')
    msg_info "Container CT $ctid ('$cur_name') existiert bereits -- aktualisiere App darin (kein neuer LXC)..."
    pct start "$ctid" 2>/dev/null || true
    wait_for_network "$ctid"
    run_inner_in_container "$ctid"
    local ip=""
    ip=$(pct exec "$ctid" -- hostname -I 2>/dev/null | awk '{print $1}')
    echo ""
    msg_ok "Update abgeschlossen. Dashboard: http://${ip:-<Container-IP>}:8000"
    return 0
  fi

  # Neuanlage prüfen: Storage/Bridge vorhanden?
  pvesm status --storage "$STORAGE" >/dev/null 2>&1 \
    || { msg_error "Storage '$STORAGE' nicht gefunden (z.B. --storage local-lvm)."; exit 1; }

  tpl_ref=$(ensure_template)

  local generated_pw=0
  if [[ -z "$ROOTPW" ]]; then
    ROOTPW=$(openssl rand -base64 12 | tr -d '/+=' | head -c 16)
    generated_pw=1
  fi

  msg_info "Erstelle LXC-Container CT $ctid ('$HOSTNAME')..."
  pct create "$ctid" "$tpl_ref" \
    --hostname "$HOSTNAME" \
    --storage "$STORAGE" \
    --rootfs "$STORAGE:$DISK" \
    --cores "$CORES" \
    --memory "$MEMORY" \
    --swap 512 \
    --net0 "name=eth0,bridge=$BRIDGE,ip=$IPCONF" \
    --unprivileged 1 \
    --features nesting=1 \
    --onboot 1 \
    --start 1 \
    --password "$ROOTPW"
  msg_ok "Container CT $ctid erstellt und gestartet"

  wait_for_network "$ctid"
  run_inner_in_container "$ctid"

  local ip=""
  ip=$(pct exec "$ctid" -- hostname -I 2>/dev/null | awk '{print $1}')

  #ACHTUNG: Falls dieses Script versehentlich früher direkt auf dem Host lief,
  # liegt dort eine Host-Installation (kein LXC). Darauf hinweisen, damit nicht
  # zwei Instanzen (Host + Container) parallel laufen.
  if [[ -d /opt/research-lxc ]]; then
    echo ""
    msg_info "Hinweis: Auf dem HOST existiert /opt/research-lxc (frühere Direkt-Installation, kein LXC)."
    echo "  Zum Aufräumen auf dem Host (Container läuft unabhängig weiter):"
    echo "    systemctl disable --now research-lxc-all.timer research-lxc-web.service"
    echo "    rm /etc/systemd/system/research-lxc-*.service /etc/systemd/system/research-lxc-all.timer"
    echo "    systemctl daemon-reload; userdel research; rm -rf /opt/research-lxc"
  fi

  echo ""
  msg_ok "Fertig! Container CT $ctid ('$HOSTNAME') läuft."
  echo ""
  echo -e "  ${GN}┌──────────────────────────────────────────────────────────┐${CL}"
  echo -e "  ${GN}│${CL}  Dashboard:  ${GN}http://${ip:-<Container-IP>}:8000${CL}"
  echo -e "  ${GN}│${CL}  Dort zuerst unter '/settings' Brave API Key, Ollama-URL,"
  echo -e "  ${GN}│${CL}  Branche/Region und Ziel-E-Mail eintragen."
  if [[ "$generated_pw" == "1" ]]; then
    echo -e "  ${GN}│${CL}  Container-root-Passwort (einmalig angezeigt): ${GN}${ROOTPW}${CL}"
  fi
  echo -e "  ${GN}└──────────────────────────────────────────────────────────┘${CL}"
  echo ""
  echo "  Update später: denselben Befehl erneut auf dem Host ausführen."
  echo "  Container-Shell: pct enter $ctid | Logs: pct exec $ctid -- journalctl -u research-lxc-web.service -n 50"
  echo ""
}

# ---------- Start ----------
if [[ "$UNINSTALL" == "1" ]]; then
  # Sicherheitsnetz: niemals / oder ein leeres Ziel löschen.
  if [[ -z "$APP_DIR" || "$APP_DIR" == "/" ]]; then
    msg_error "Unsicheres APP_DIR, Abbruch."
    exit 1
  fi
  msg_info "Deinstalliere lokale Installation ($APP_DIR)..."
  systemctl disable --now research-lxc-all.timer research-lxc-web.service 2>/dev/null || true
  rm -f /etc/systemd/system/research-lxc@.service \
        /etc/systemd/system/research-lxc-all.timer \
        /etc/systemd/system/research-lxc-web.service
  systemctl daemon-reload 2>/dev/null || true
  if id "$SERVICE_USER" &>/dev/null; then
    userdel "$SERVICE_USER" 2>/dev/null || true
    msg_ok "Service-User '$SERVICE_USER' entfernt"
  fi
  if [[ -d "$APP_DIR" ]]; then
    rm -rf "$APP_DIR"
    msg_ok "$APP_DIR entfernt (inkl. config.yaml, Reports, Budget-DB)"
  fi
  msg_ok "Deinstallation abgeschlossen."
  exit 0
fi

if [[ "$MODE" == "host" ]]; then
  install_host
else
  install_inner
fi
