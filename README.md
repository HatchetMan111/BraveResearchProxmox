# Recherche-LXC – Brave Search + externes Ollama

Automatisiertes Recherche-Tool für einen Proxmox-LXC-Container. Nutzt die
Brave Search API (hart limitiert auf ein konfigurierbares Monatsbudget,
Standard 950 Requests) und lässt die Ergebnisse von einer **externen,
selbst gehosteten Ollama-Instanz** filtern, strukturieren und im
gewünschten Stil zusammenfassen.

Zwei Module sind eingebaut, beliebig viele weitere lassen sich **ganz ohne
Code über das Web-Dashboard** anlegen:

- **`competitor_analysis`** – lokale Konkurrenzanalyse für eine Branche+Region
- **`news_digest`** – lokale News-Zusammenfassung im vorgegebenen Redaktionsstil
- **eigene Module** – Name, Suchanfragen und Ollama-Anweisung frei definierbar unter `/modules`

## 🚀 Schnellinstallation

**Auf dem Proxmox-Host als root** – erstellt automatisch einen LXC-Container
(Debian 12, 1 Core, 1024 MB RAM, 8 GB Disk, DHCP) und installiert alles darin:

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BraveResearchProxmox/main/install/research-lxc.sh)"
```

Anpassen z.B.: `... -- --ctid 101 --hostname research-lxc --storage local-lvm --memory 2048`
(alle Optionen: `--help`; alternativ per Umgebungsvariablen `RESEARCH_CTID`,
`RESEARCH_HOSTNAME`, `RESEARCH_STORAGE`, `RESEARCH_CORES`, `RESEARCH_MEMORY`,
`RESEARCH_DISK`, `RESEARCH_BRIDGE`, `RESEARCH_IP`, `RESEARCH_PASSWORD`).

**Update:** denselben Befehl einfach erneut auf dem Host ausführen – erkennt
den vorhandenen Container am Hostnamen und aktualisiert nur die App
(`config.yaml` bleibt erhalten).

**Deinstallation** (entfernt Units, Service-User und `/opt/research-lxc`
inkl. Config, Reports und Budget-DB – ggf. vorher sichern):

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BraveResearchProxmox/main/install/research-lxc.sh)" -- --uninstall
```

**Alternative:** Container manuell erstellen und dann *im Container* als root:

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BraveResearchProxmox/main/install/research-lxc.sh)" -- --inner
```

Das Script installiert alles nicht-interaktiv und startet direkt ein
**Web-Dashboard** (Port 8000) – die komplette Konfiguration (Brave API Key,
Ollama-URL/-Modell, Branche, Region, Ziel-E-Mail) erfolgt dort per Formular,
nicht mehr per SSH-Terminal-Abfrage. Am Ende der Installation zeigt das
Script die passende URL (`http://<Container-IP>:8000`) direkt an.

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
- ✅ **Modular** – neue Recherche-Themen als eigenes Modul über das Dashboard
  anlegen (kein Code nötig) oder als Python-Datei unter `app/modules/`
- ✅ **Reports als Markdown**, optional zusätzlich per E-Mail (SMTP)
- ✅ **Web-Dashboard** – Konfiguration per Browser-Formular, Reports ansehen,
  Läufe manuell anstoßen, Budget-Stand auf einen Blick (kein SSH nötig)
- ✅ **Ollama-Modell-Auswahl** – Dashboard fragt die auf der Ollama-Instanz
  bereits installierten Modelle ab, Auswahl per Dropdown statt Tippfehler-Risiko

## 📋 Voraussetzungen

### Minimale LXC-Container-Anforderungen

- ✅ **OS**: Debian 12 oder Ubuntu 22.04/24.04
- ✅ **CPU**: 1 Core (ausreichend, keine lokale KI-Last)
- ✅ **RAM**: 512 MB
- ✅ **Disk**: 4 GB
- ✅ **Netzwerk**: Zugang zu api.search.brave.com und zur externen
  Ollama-Instanz; Port 8000 im LAN erreichbar für das Dashboard

### Externe Abhängigkeiten

- Brave Search API Key: <https://api-dashboard.search.brave.com>
- Eine erreichbare, separat gehostete Ollama-Instanz (nicht Teil dieses LXC)

## 🎯 Manuelle Nutzung

```bash
cd /opt/research-lxc

# Einzelnen Modul-Lauf testen (ohne E-Mail-Versand, mit Debug-Log)
sudo -u research venv/bin/python -m app.main \
  --module competitor_analysis --config config.yaml --no-email -v

# Alle aktivierten Module nacheinander (eingebaute + eigene) -- das läuft
# auch täglich automatisch per Timer, siehe unten
sudo -u research venv/bin/python -m app.main \
  --module all --config config.yaml --no-email -v
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
  model: "..."                  # im Dashboard aus installierten Modellen wählbar

modules:
  competitor_analysis:
    branche: "Ihre Branche"
    region: "Ihre Region"
  news_digest:
    region: "Ihre Region"
    themen: ["Energie", "Förderprogramme"]
    stil: "sachlich, lokal, freundlich"

custom_modules:
  - name: vereinsnachrichten
    enabled: true
    search_type: news            # "web" oder "news"
    queries:
      - "Musterverein Neuigkeiten"
    system_prompt: "Fasse kurz und sachlich zusammen."
```

Eigenes Modul hinzufügen -- drei Wege:

1. **Aus Vorlage** (empfohlen): unter `/modules` bei „Aus Vorlage anlegen“
   ein Thema wählen (Arbeitsmarkt, Immobilien, Veranstaltungen,
   Kommunalpolitik, Verkehr, Energie, Gesundheit, Bildung, Tourismus,
   Wirtschaft) – nur Region/Stadt eintragen, Queries und Auswertung kommen
   aus der Vorlage und bleiben editierbar.
2. **Ohne Code**: über das Dashboard unter `/modules` -- Name, Suchanfragen
   und Ollama-Anweisung eintragen, läuft ab sofort beim täglichen
   `--module all`-Lauf mit.
2. **Als Python-Modul**: Datei unter `app/modules/` mit `NAME`,
   `SEARCH_TYPE`, `build_queries()` und `build_prompt()` anlegen und in
   `app/modules/__init__.py` registrieren -- sinnvoll für Module mit
   komplexerer Query- oder Prompt-Logik als die einfache Query-Liste der
   Dashboard-Module. Reine Themen-Vorlagen (Platzhalter wie `{region}`)
   gehören dagegen in `app/modules/templates.py` -- ganz ohne neue Route.

## ⏰ Zeitplan pro Modul

Jedes Modul kann **täglich oder wöchentlich zu einer eigenen Uhrzeit** laufen
– oder nur manuell:

- **Eingebaute Module**: unter `/settings` je Modul „Eigener Zeitplan“
  ankreuzen (sonst gilt der Standard aus dem Zeitplan-Bereich).
- **Eigene Module**: direkt beim Anlegen/Bearbeiten unter `/modules`
  (Schritt 4 „Zeitplan“).
- **Anwenden**: Danach den Installer erneut laufen lassen *oder* als root im
  App-Ordner `venv/bin/python -m app.schedule_units --config config.yaml --apply`
  – erst dann werden die System-Timer (`research-lxc-mod-<name>.timer`)
  angelegt bzw. aktualisiert. Die Web-UI darf aus Sicherheitsgründen keine
  systemd-Units anfassen.
- **Prüfen**: `systemctl list-timers 'research-lxc-*'` oder die
  Zeitplan-Karte auf dem Dashboard.

## 🖥️ Web-Dashboard

Nach der Installation erreichbar unter `http://<Container-IP>:8000`
(die genaue Adresse zeigt der Installer am Ende an, alternativ
`hostname -I` im Container):

| Route         | Zweck                                                        |
|---------------|---------------------------------------------------------------|
| `/`           | Budget-Stand, Modul-Status, "Jetzt ausführen"-Button, letzte Reports |
| `/settings`   | Allgemeine Konfiguration + die beiden eingebauten Module        |
| `/modules`    | Eigene Module anlegen/bearbeiten/löschen, ganz ohne Code        |
| `/reports`    | Alle bisherigen Reports, als Markdown gerendert                |

Änderungen unter `/settings` werden direkt in `config.yaml` geschrieben und
gelten sofort für den nächsten Timer- oder manuellen Lauf – kein Neustart
nötig. Läuft als eigener Service `research-lxc-web.service`, getrennt von
den zeitgesteuerten Batch-Läufen.

## 🔧 Troubleshooting

```bash
# Timer-Status
systemctl list-timers 'research-lxc-*'

# Logs eines Laufs (alle Module -- so heißt der von research-lxc-all.timer getriggerte Service)
journalctl -u research-lxc@all.service -n 100

# Logs eines einzelnen manuellen Modul-Laufs (Instanzname = Modulname)
journalctl -u research-lxc@competitor_analysis.service -n 100

# Budget-Stand prüfen
sqlite3 /opt/research-lxc/data/budget.db "SELECT * FROM budget;"

# Cache leeren (erzwingt frische Brave-Requests)
rm /opt/research-lxc/data/cache.db

# Dashboard-Status / neu starten
systemctl status research-lxc-web.service
systemctl restart research-lxc-web.service
journalctl -u research-lxc-web.service -n 100
```

### Ollama nicht erreichbar

Base-URL in `config.yaml` prüfen, Erreichbarkeit testen:

```bash
curl http://OLLAMA-HOST:11434/api/tags
```

Zeigt der Befehl die Modelle korrekt, aber das Dashboard nicht, siehe
"Neue Funktionen/Fixes nicht sichtbar" unten -- meist läuft dann noch der
alte Dashboard-Prozess.

### Ollama-Cloud-Modelle (`...-cloud`-Tags)

Über die Ollama-Cloud bezogene Modelle (Tag endet auf `-cloud`, z.B.
`gemma3:27b-cloud`) tauchen nach `ollama pull` normal in `/api/tags` auf und
sollten damit auch im Dashboard-Dropdown erscheinen. Bekanntes Ollama-Problem
(Stand 2026, [ollama/ollama#16314](https://github.com/ollama/ollama/issues/16314)):
auf manchen Systemen wird beim eigentlichen Generieren (`/api/generate`) das
`-cloud`-Suffix intern verschluckt, wodurch Ollama das Modell dann nicht mehr
findet, obwohl es korrekt gelistet wird. Erkennbar am Report-Status "Fehler"
mit einer Ollama-Fehlermeldung zum Modellnamen. Workaround laut Ollama-Issue:
auf dem Ollama-Host einen lokalen Alias ohne Sonderzeichen anlegen:

```bash
echo "FROM gemma3:27b-cloud" > Modelfile
ollama create gemma3-cloud-alias -f Modelfile
```

und im Dashboard dann `gemma3-cloud-alias` als Modell eintragen.

### Neue Funktionen/Fixes nicht sichtbar (Dashboard wirkt "alt")

Der Installer aktualisiert bei erneutem Lauf zwar Repo, venv und
systemd-Units, aber ein bereits laufendes Dashboard wird von
`systemctl enable --now` **nicht neu gestartet** (das ist ein bekanntes
systemd-Verhalten: `--now` startet nur, wenn der Service noch nicht läuft).
Seit dem entsprechenden Fix macht das der Installer automatisch
(`systemctl restart research-lxc-web.service` bei jedem Lauf) -- bei älteren
Ständen hilft manuell:

```bash
systemctl restart research-lxc-web.service
```

### Budget dauerhaft erschöpft

`max_requests_per_month` in `config.yaml` senken oder Modul-Queries
reduzieren (`queries_extra` leer lassen, weniger `themen`).

## 🔒 Sicherheit

- Läuft unter eigenem Service-User `research` (kein Login-Shell)
- Kein Reverse-Proxy/TLS enthalten – Dashboard läuft unverschlüsselt und
  **ohne Login** auf Port 8000, reicht fürs Heimnetz/internes Netz. Für
  Zugriff von außen unbedingt hinter Reverse-Proxy mit Auth (z.B. Caddy
  + Basic-Auth) oder VPN stellen
- API-Keys/SMTP-Passwort können statt in `config.yaml` auch per
  Umgebungsvariable gesetzt werden (`BRAVE_API_KEY`, `SMTP_PASSWORD`)

## 📝 Lizenz

MIT License – siehe [LICENSE](LICENSE)

---

Made with ❤️ für die Proxmox-Community · Credits: [Proxmox Helper Scripts](https://community-scripts.github.io/ProxmoxVE/)
