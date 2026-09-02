# Recherche-LXC – Brave Search + externes Ollama

Automatisiertes Recherche-Tool für einen Proxmox-LXC-Container. Nutzt die
Brave Search API (hart limitiert auf ein konfigurierbares Monatsbudget,
Standard 950 Requests) und lässt die Ergebnisse von einer **externen,
selbst gehosteten Ollama-Instanz** filtern, strukturieren und im
gewünschten Stil zusammenfassen.

Zwei Module sind enthalten und beliebig erweiterbar:

- **`competitor_analysis`** – lokale Konkurrenzanalyse für eine Branche+Region
- **`news_digest`** – lokale News-Zusammenfassung im vorgegebenen Redaktionsstil

## 🚀 Schnellinstallation

Container erstellen (siehe Voraussetzungen), dann als root im Container:

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BraveResearchProxmox/main/install/research-lxc.sh)"
```

Das Script fragt interaktiv nach Brave API Key, Ollama-URL/-Modell, Branche,
Region und Ziel-E-Mail ab und richtet danach zwei systemd-Timer ein
(Konkurrenzanalyse wöchentlich, News-Digest täglich).

## ✨ Features

- ✅ **Hartes Request-Budget** – SQLite-Zähler pro Kalendermonat, Hard-Stop
  vor dem Erreichen des Brave-Gratislimits (kein Teilverbrauch möglich)
- ✅ **TTL-Cache** – wiederkehrende Queries verbrauchen kein Budget
- ✅ **Externes Ollama** – die eigentliche Verarbeitung (Filtern,
  Zusammenfassen, Stiltransfer) läuft unbegrenzt und kostenlos außerhalb des
  Brave-Budgets
- ✅ **Graceful Degradation** – geht das Budget mitten im Lauf aus, bricht
  der Lauf nicht ab, sondern fasst zusammen, was vorliegt, und markiert den
  Report deutlich als unvollständig
- ✅ **Modular** – neue Recherche-Themen sind ein neues Modul unter `app/modules/`
- ✅ **Reports als Markdown**, optional zusätzlich per E-Mail (SMTP)

## 📋 Voraussetzungen

### Minimale LXC-Container-Anforderungen

- ✅ **OS**: Debian 12 oder Ubuntu 22.04/24.04
- ✅ **CPU**: 1 Core (ausreichend, keine lokale KI-Last)
- ✅ **RAM**: 512 MB
- ✅ **Disk**: 4 GB
- ✅ **Netzwerk**: Zugang zu api.search.brave.com und zur externen Ollama-Instanz

### Externe Abhängigkeiten

- Brave Search API Key: <https://api-dashboard.search.brave.com>
- Eine erreichbare, separat gehostete Ollama-Instanz (nicht Teil dieses LXC)

## 🎯 Manuelle Nutzung

```bash
cd /opt/research-lxc

# Einzelnen Modul-Lauf testen (ohne E-Mail-Versand, mit Debug-Log)
sudo -u research venv/bin/python -m app.main \
  --module competitor_analysis --config config.yaml --no-email -v

sudo -u research venv/bin/python -m app.main \
  --module news_digest --config config.yaml --no-email -v
```

Reports landen als Markdown unter `reports/`.

## ⚙️ Konfiguration

Alles Weitere in `config.yaml` (aus `config.example.yaml` erzeugt):

```yaml
brave:
  api_key: "..."
  max_requests_per_month: 950   # Sicherheitspuffer unter dem 1000er-Gratislimit

ollama:
  base_url: "http://OLLAMA-HOST:11434"
  model: "llama3.1"

modules:
  competitor_analysis:
    branche: "SmartHome Integration"
    region: "Main-Tauber-Kreis"
  news_digest:
    region: "Main-Tauber-Kreis"
    themen: ["Energie", "SmartHome", "Förderprogramme"]
    stil: "sachlich, lokal, freundlich"
```

Neues Modul hinzufügen: Datei unter `app/modules/` mit `NAME`,
`SEARCH_TYPE`, `build_queries()` und `build_prompt()` anlegen und in
`app/modules/__init__.py` registrieren.

## 🔧 Troubleshooting

```bash
# Timer-Status
systemctl list-timers 'research-lxc-*'

# Logs eines Laufs
journalctl -u research-lxc@competitor_analysis.service -n 100

# Budget-Stand prüfen
sqlite3 /opt/research-lxc/data/budget.db "SELECT * FROM budget;"

# Cache leeren (erzwingt frische Brave-Requests)
rm /opt/research-lxc/data/cache.db
```

### Ollama nicht erreichbar

Base-URL in `config.yaml` prüfen, Erreichbarkeit testen:

```bash
curl http://OLLAMA-HOST:11434/api/tags
```

### Budget dauerhaft erschöpft

`max_requests_per_month` in `config.yaml` senken oder Modul-Queries
reduzieren (`queries_extra` leer lassen, weniger `themen`).

## 🔒 Sicherheit

- Läuft unter eigenem Service-User `research` (kein Login-Shell)
- Kein Reverse-Proxy/TLS enthalten – Tool hat keine Weboberfläche, reicht
  fürs Heimnetz/internes Netz
- API-Keys/SMTP-Passwort können statt in `config.yaml` auch per
  Umgebungsvariable gesetzt werden (`BRAVE_API_KEY`, `SMTP_PASSWORD`)

## 📝 Lizenz

MIT License – siehe [LICENSE](LICENSE)

---

Made with ❤️ für die Proxmox-Community · Credits: [Proxmox Helper Scripts](https://community-scripts.github.io/ProxmoxVE/)
