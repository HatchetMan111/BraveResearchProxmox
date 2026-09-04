"""Vorlagen-Katalog für eigene Module ("Aus Vorlage anlegen" im Dashboard).

Jede Vorlage beschreibt ein Recherche-Thema mit Platzhaltern ({region},
{stadt}, {branche}), aus denen beim Anlegen konkrete Brave-Suchanfragen
gerendert werden. Der Nutzer füllt nur Region/Stadt/Branche aus -- Queries
und Ollama-Anweisung kommen aus der Vorlage (bleiben editierbar).

Neue Vorlage hinzufügen: Dict nach dem Muster unten ergänzen, fertig --
keine weitere Registrierung nötig. Alle Platzhalter in `queries` müssen in
`fields` definiert sein (prüft test_module_templates.py).
"""

from __future__ import annotations

import re
from typing import Any

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


def _placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text))


TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "job_markt",
        "title": "Arbeitsmarkt & Stellenangebote",
        "description": "Offene Stellen, Ausbildungsplätze und Fachkräfte-Themen in deiner Region.",
        "suggested_name": "arbeitsmarkt",
        "search_type": "web",
        "fields": [
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": True},
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": False},
            {"name": "branche", "label": "Branche (optional)", "placeholder": "z.B. Handwerk", "required": False},
        ],
        "queries": [
            "Stellenangebote {region}",
            "Jobs {stadt}",
            "Fachkräfte gesucht {branche} {region}",
            "Ausbildungsplätze {region}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zum regionalen Arbeitsmarkt und erstellst "
            "daraus einen ausführlichen Stellenmarkt-Bericht auf Deutsch (ca. 1 Seite). "
            "Struktur: 1. Überblick (3-4 Sätze: welche Branchen suchen, was fällt auf), "
            "2. konkrete Stellenangebote als Liste mit Markdown-Link [Titel](URL), "
            "Unternehmen, Ort und 1 Satz Beschreibung, 3. Ausbildungsplätze extra, "
            "4. Fazit für Jobsuchende. Erfinde keine Stellen, verlinke jede Quelle."
        ),
    },
    {
        "key": "immobilien",
        "title": "Immobilienmarkt",
        "description": "Miet-/Kaufpreise, Angebote und Marktentwicklung vor Ort.",
        "suggested_name": "immobilien",
        "search_type": "web",
        "fields": [
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": True},
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": False},
        ],
        "queries": [
            "Immobilienpreise {region}",
            "Mietwohnungen {stadt}",
            "Haus kaufen {region}",
            "Mietpreisentwicklung {region}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zum regionalen Immobilienmarkt und erstellst "
            "daraus einen ausführlichen Marktbericht auf Deutsch (ca. 1 Seite). "
            "Struktur: 1. Überblick (Preislage Miete/Kauf, Trend), 2. aktuelle Angebote "
            "als Liste mit Markdown-Link [Titel](URL) plus Preis und Ort (soweit in den Daten), "
            "3. Einschätzung: wird es teurer oder günstiger? Erfinde keine Fakten, verlinke jede Quelle."
        ),
    },
    {
        "key": "veranstaltungen",
        "title": "Veranstaltungen & Termine",
        "description": "Konzerte, Feste, Märkte und Termine in Stadt und Region.",
        "suggested_name": "veranstaltungen",
        "search_type": "news",
        "fields": [
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Veranstaltungen {stadt}",
            "Konzerte Feste {region}",
            "Veranstaltungskalender {stadt}",
        ],
        "system_prompt": (
            "Du erhältst rohe News-Suchergebnisse zu Veranstaltungen und erstellst daraus "
            "einen freundlichen Terminkalender-Bericht auf Deutsch. Struktur: 1. Überblick "
            "(2-3 Sätze), 2. Termine als Liste mit Markdown-Link [Titel](URL), Datum "
            "(falls bekannt), Ort und 1-2 Sätzen Beschreibung, 3. Hinweis, wenn etwas "
            "unklar ist, statt zu raten. Schreibe einladend, wie eine lokale Veranstaltungsseite."
        ),
    },
    {
        "key": "kommunalpolitik",
        "title": "Kommunalpolitik & Verwaltung",
        "description": "Rathaus, Beschlüsse, Förderprogramme und Bürgerservice.",
        "suggested_name": "kommunalpolitik",
        "search_type": "news",
        "fields": [
            {"name": "stadt", "label": "Stadt / Gemeinde", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Stadtrat {stadt} Beschlüsse",
            "Rathaus {region} Nachrichten",
            "Förderprogramme Kommune {region}",
        ],
        "system_prompt": (
            "Du erhältst rohe News-Suchergebnisse zu Kommunalpolitik und Verwaltung und "
            "erstellst daraus einen sachlichen Bürger-Bericht auf Deutsch (ca. 1 Seite). "
            "Struktur: 1. Überblick (wichtigste Beschlüsse/Neuigkeiten), 2. einzelne Themen "
            "als Absätze mit Markdown-Link [Titel](URL) und Einordnung (was bedeutet das "
            "für Bürger?), 3. Förderprogramme und Fristen extra hervorheben. Nüchtern und "
            "verständlich, ohne Parteijargon."
        ),
    },
    {
        "key": "verkehr",
        "title": "Verkehr, Baustellen & ÖPNV",
        "description": "Sperrungen, Baustellen, Fahrplanänderungen und ÖPNV-News.",
        "suggested_name": "verkehr",
        "search_type": "news",
        "fields": [
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": True},
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": False},
        ],
        "queries": [
            "Baustellen Sperrungen {region}",
            "ÖPNV {region} Änderungen",
            "Verkehr {stadt}",
        ],
        "system_prompt": (
            "Du erhältst rohe News-Suchergebnisse zu Verkehr und erstellst daraus einen "
            "praktischen Verkehrsüberblick auf Deutsch. Struktur: 1. Überblick (2-3 Sätze: "
            "wo klemmt es gerade?), 2. Baustellen/Sperrungen als Liste mit Markdown-Link "
            "[Titel](URL), Ort, Dauer (falls bekannt) und Umleitung, 3. ÖPNV-Änderungen "
            "extra. Kurz, konkret, alltagstauglich."
        ),
    },
    {
        "key": "energie",
        "title": "Energiepreise & Versorgung",
        "description": "Strom, Heizen, Tanken und Förderung rund um Energie.",
        "suggested_name": "energie",
        "search_type": "web",
        "fields": [
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": True},
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": False},
        ],
        "queries": [
            "Strompreise {region}",
            "Heizöl Pellets Preise {region}",
            "Spritpreise {stadt}",
            "Solar Förderung {region}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Energiepreisen und erstellst daraus "
            "einen ausführlichen Energie-Bericht auf Deutsch (ca. 1 Seite). Struktur: "
            "1. Überblick (Strom, Heizen, Tanken: wo stehen die Preise?), 2. Details pro "
            "Bereich mit Markdown-Link [Titel](URL) und konkreten Zahlen aus den Daten, "
            "3. Spartipps/Förderungen aus den Quellen. Nur Zahlen aus den Rohdaten nennen, "
            "nichts schätzen."
        ),
    },
    {
        "key": "gesundheit",
        "title": "Gesundheit & Notdienste",
        "description": "Ärzte, Apotheken-Notdienst und Klinik-Nachrichten.",
        "suggested_name": "gesundheit",
        "search_type": "web",
        "fields": [
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Apotheken Notdienst {stadt}",
            "Ärzte {region}",
            "Klinik {stadt} Nachrichten",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Gesundheitsthemen und erstellst daraus "
            "einen sachlichen Gesundheitsüberblick auf Deutsch. Struktur: 1. Notdienste "
            "(Apotheken/Bereitschaft mit Markdown-Link [Titel](URL) und Erreichbarkeit), "
            "2. Ärzte/Versorgung in der Region, 3. Klinik- und Gesundheitsnews. Wichtig: "
            "keine medizinischen Ratschläge erfinden, nur gefundene Informationen wiedergeben."
        ),
    },
    {
        "key": "bildung",
        "title": "Bildung & Weiterbildung",
        "description": "Schulen, Kitas, VHS-Kurse und Weiterbildung vor Ort.",
        "suggested_name": "bildung",
        "search_type": "web",
        "fields": [
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Weiterbildung Kurse {region}",
            "Schulen Kitas {stadt}",
            "VHS Programm {stadt}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Bildung und erstellst daraus einen "
            "freundlichen Bildungsüberblick auf Deutsch. Struktur: 1. Überblick (2-3 Sätze), "
            "2. Angebote als Liste mit Markdown-Link [Titel](URL), Zielgruppe und Terminen "
            "(falls bekannt), 3. Anmeldefristen extra hervorheben. Verständlich für Eltern "
            "und Weiterbildungsinteressierte."
        ),
    },
    {
        "key": "tourismus_gastro",
        "title": "Tourismus & Gastronomie",
        "description": "Ausflugsziele, Übernachtung, Restaurants und Freizeit.",
        "suggested_name": "tourismus",
        "search_type": "web",
        "fields": [
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": True},
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": False},
        ],
        "queries": [
            "Tourismus {region}",
            "Restaurants Neueröffnungen {stadt}",
            "Ausflugsziele {region}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Tourismus und Gastronomie und erstellst "
            "daraus einen einladenden Freizeit-Bericht auf Deutsch. Struktur: 1. Überblick "
            "(2-3 Sätze: was lohnt sich gerade?), 2. Tipps als Liste mit Markdown-Link "
            "[Titel](URL) und 1-2 Sätzen Beschreibung, 3. Neuigkeiten (Eröffnungen, "
            "Veranstaltungen) extra. Schreibe lebendig, wie ein lokaler Freizeitblog."
        ),
    },
    {
        "key": "wirtschaft",
        "title": "Wirtschaft & Förderung",
        "description": "Firmen-News, Gewerbegebiete und Förderprogramme für Unternehmen.",
        "suggested_name": "wirtschaft",
        "search_type": "web",
        "fields": [
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": True},
            {"name": "branche", "label": "Branche (optional)", "placeholder": "z.B. Handwerk", "required": False},
        ],
        "queries": [
            "Wirtschaft {region}",
            "Förderprogramme Unternehmen {region}",
            "Gewerbegebiete {region}",
            "{branche} {region} Nachrichten",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zur regionalen Wirtschaft und erstellst "
            "daraus einen ausführlichen Wirtschaftsbericht auf Deutsch (ca. 1 Seite). "
            "Struktur: 1. Überblick (Konjunktur, Neuansiedlungen, Auffälligkeiten), "
            "2. Firmen-News mit Markdown-Link [Titel](URL), 3. Förderprogramme mit Fristen "
            "und Voraussetzungen extra. Sachlich, mit Blick auf lokale Unternehmen."
        ),
    },
    {
        "key": "abfall",
        "title": "Abfall & Entsorgung",
        "description": "Müllabfuhr-Termine, Wertstoffhof, Sperrmüll und Gebühren vor Ort.",
        "suggested_name": "abfall",
        "search_type": "web",
        "fields": [
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Müllabfuhr Termine {stadt}",
            "Wertstoffhof {stadt} Öffnungszeiten",
            "Sperrmüll {stadt} Anmeldung",
            "Müllgebühren {region}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zur Abfallentsorgung und erstellst daraus "
            "eine praktische Entsorgungsübersicht auf Deutsch. Fokus zuerst auf die Stadt "
            "(konkrete Termine, Adressen, Öffnungszeiten, Anmeldungen), danach ein Ausblick "
            "auf die Region (Gebühren, Regelungen, Unterschiede). Struktur: 1. Müllabfuhr "
            "in der Stadt (Termine/Rhythmus mit Markdown-Link [Titel](URL)), 2. Wertstoffhof "
            "und Sperrmüll (Anfahrt, Zeiten, Anmeldung), 3. Regions-Ausblick (Gebühren, "
            "Neuerungen). Kurz, konkret, alltagstauglich -- nur belegte Fakten."
        ),
    },
    {
        "key": "sport",
        "title": "Sport vor Ort",
        "description": "Vereine, Ergebnisse und Sportevents in Stadt und Region.",
        "suggested_name": "sport",
        "search_type": "news",
        "fields": [
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Sport {stadt} Ergebnisse",
            "Sportveranstaltungen {region}",
            "Sportverein {stadt} Nachrichten",
        ],
        "system_prompt": (
            "Du erhältst rohe News-Suchergebnisse zum lokalen Sport und erstellst daraus "
            "einen lebendigen Sportüberblick auf Deutsch. Fokus zuerst auf die Stadt "
            "(Vereine, Ergebnisse, Termine), danach ein Ausblick auf die Region. Struktur: "
            "1. Überblick (2-3 Sätze: was war los, was steht an?), 2. Ergebnisse und "
            "Meldungen der Stadt-Vereine mit Markdown-Link [Titel](URL), 3. Sportevents "
            "und Termine in der Region, 4. Mitmach-Angebote (Probetraining, Anmeldung) "
            "extra. Schreibe begeistert wie eine lokale Sportseite."
        ),
    },
    {
        "key": "vereine",
        "title": "Vereine & Ehrenamt",
        "description": "Feuerwehr, Sport-, Musikvereine, Mitmachen und Förderung.",
        "suggested_name": "vereine",
        "search_type": "web",
        "fields": [
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Vereine {stadt} Mitmachen",
            "Ehrenamt {region} Angebote",
            "Feuerwehr Musikverein {stadt}",
            "Vereinsförderung {region}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Vereinen und Ehrenamt und erstellst "
            "daraus einen einladenden Vereinsüberblick auf Deutsch. Fokus zuerst auf die "
            "Stadt (welche Vereine gibt es, wer sucht Mitglieder?), danach ein Ausblick "
            "auf die Region. Struktur: 1. Überblick (2-3 Sätze), 2. Vereine der Stadt als "
            "Liste mit Markdown-Link [Titel](URL), Sparte und Mitmach-Info, 3. Ehrenamts- "
            "und Förderangebote der Region, 4. Ansprechpartner/Termine extra. Herzlich und "
            "motivierend, wie ein Vereinsportal."
        ),
    },
    {
        "key": "kultur",
        "title": "Kultur & Geschichte",
        "description": "Museen, Ausstellungen, Denkmäler und Heimatgeschichte.",
        "suggested_name": "kultur",
        "search_type": "web",
        "fields": [
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Museen {stadt}",
            "Heimatgeschichte {region}",
            "Denkmäler {stadt}",
            "Ausstellungen {stadt}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Kultur und Geschichte und erstellst "
            "daraus einen anschaulichen Kulturüberblick auf Deutsch. Fokus zuerst auf die "
            "Stadt (Museen, Denkmäler, Ausstellungen), danach ein Ausblick auf die Region "
            "(Geschichte, Sehenswürdigkeiten, Kulturorte). Struktur: 1. Überblick (2-3 "
            "Sätze), 2. Kulturorte der Stadt mit Markdown-Link [Titel](URL), Öffnungszeiten "
            "und Eintritt (falls bekannt), 3. Geschichte und Ausflugsziele der Region. "
            "Erzählfreudig, wie ein lokaler Kulturführer."
        ),
    },
    {
        "key": "bauen",
        "title": "Bauen & Baugebiete",
        "description": "Baugebiete, Bebauungspläne, Bauplätze und Neubau vor Ort.",
        "suggested_name": "bauen",
        "search_type": "web",
        "fields": [
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Baugebiete {stadt}",
            "Bebauungspläne {stadt}",
            "Bauplätze {region}",
            "Neubau {stadt}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Bauen und Baugebieten und erstellst "
            "daraus einen ausführlichen Bau-Überblick auf Deutsch (ca. 1 Seite). Fokus "
            "zuerst auf die Stadt (Baugebiete, Pläne, Neubauvorhaben im Detail), danach "
            "ein Ausblick auf die Region (Bauplätze, Preise, Entwicklung). Struktur: "
            "1. Überblick (wo wird gebaut, was ist geplant?), 2. Baugebiete und Vorhaben "
            "der Stadt mit Markdown-Link [Titel](URL), Stand und Ansprechpartner (falls "
            "bekannt), 3. Regions-Ausblick (Angebot, Preise, Trend). Sachlich und konkret "
            "für Bauinteressierte -- nur belegte Fakten."
        ),
    },
    {
        "key": "landwirtschaft",
        "title": "Landwirtschaft & Forst",
        "description": "Ernte, Holzpreise, Jagd, Hofläden und Agrar-Themen der Region.",
        "suggested_name": "landwirtschaft",
        "search_type": "web",
        "fields": [
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": True},
            {"name": "stadt", "label": "Stadt / Ort", "placeholder": "z.B. Musterstadt", "required": False},
        ],
        "queries": [
            "Landwirtschaft {region} Ernte",
            "Holzpreise {region}",
            "Jagd Forst {region}",
            "Hofladen {stadt}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Landwirtschaft und Forst und erstellst "
            "daraus einen bodenständigen Agrar-Überblick auf Deutsch. Fokus zuerst auf den "
            "eigenen Ort (Hofläden, Betriebe, Termine), danach ein Ausblick auf die Region "
            "(Ernte, Holzmarkt, Jagd, Wald). Struktur: 1. Überblick (Saison, Wetterfolgen, "
            "Marktlage in 3-4 Sätzen), 2. Themen der Region mit Markdown-Link [Titel](URL) "
            "und konkreten Zahlen aus den Daten, 3. Direktvermarkter und Termine vor Ort. "
            "Sachlich, ohne Fachchinesisch -- nur Zahlen aus den Rohdaten."
        ),
    },
    {
        "key": "steuern",
        "title": "Steuern & Verordnungen",
        "description": "Grundsteuer, Satzungen, neue Pflichten und Fristen der Kommune.",
        "suggested_name": "steuern",
        "search_type": "web",
        "fields": [
            {"name": "stadt", "label": "Stadt / Gemeinde", "placeholder": "z.B. Musterstadt", "required": True},
            {"name": "region", "label": "Region / Landkreis", "placeholder": "z.B. Landkreis Musterstadt", "required": False},
        ],
        "queries": [
            "Grundsteuer {stadt} Hebesatz",
            "Satzungen Verordnungen {stadt}",
            "Neue Vorschriften {region}",
        ],
        "system_prompt": (
            "Du erhältst rohe Web-Suchergebnisse zu Steuern und Verordnungen und erstellst "
            "daraus einen verständlichen Bürger-Überblick auf Deutsch. Fokus zuerst auf die "
            "eigene Stadt/Gemeinde (Hebesätze, Satzungen, Fristen im Detail), danach ein "
            "Ausblick auf die Region (Unterschiede, Neuerungen). Struktur: 1. Überblick "
            "(was ändert sich, was ist zu tun?), 2. Regelungen der Stadt mit Markdown-Link "
            "[Titel](URL), konkreten Sätzen/Fristen und Einordnung (wen betrifft es?), "
            "3. Regions-Ausblick. Nüchtern und bürgernah -- keine Rechtsberatung, nur "
            "gefundene Informationen, Fristen extra hervorheben."
        ),
    },
]


def get_template(key: str) -> dict[str, Any] | None:
    for t in TEMPLATES:
        if t["key"] == key:
            return t
    return None


def render_queries(template: dict[str, Any], values: dict[str, str]) -> list[str]:
    """Rendert Query-Vorlagen mit Werten. Queries, deren optionale Felder leer
    sind, werden übersprungen; leere Pflichtfelder führen zu ValueError."""
    for field in template["fields"]:
        if field.get("required") and not (values.get(field["name"]) or "").strip():
            raise ValueError(f"Bitte '{field['label']}' ausfüllen.")
    queries: list[str] = []
    for raw_query in template["queries"]:
        needed = _placeholders(raw_query)
        if any(not (values.get(p) or "").strip() for p in needed):
            continue  # optionales Feld leer -> diese Query weglassen
        query = raw_query.format(**{p: values.get(p, "").strip() for p in needed})
        query = " ".join(query.split())
        if query and query not in queries:
            queries.append(query)
    if not queries:
        raise ValueError("Keine Suchanfrage übrig -- bitte alle Pflichtfelder ausfüllen.")
    return queries
