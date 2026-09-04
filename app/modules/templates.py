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
