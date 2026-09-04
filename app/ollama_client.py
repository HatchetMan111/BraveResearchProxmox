"""Client für eine externe, selbst gehostete Ollama-Instanz.

Läuft nicht auf dem Brave-Budget -- deshalb wird die eigentliche
Verarbeitungsarbeit (Filtern, Strukturieren, Zusammenfassen, Umformulieren
im Zielstil) bewusst hierher verlagert statt in zusätzliche Brave-Queries.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int = 180,
        session: requests.Session | None = None,
    ):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.model = (model or "").strip()
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def _friendly_http_error(self, resp: requests.Response) -> OllamaError:
        """Wandelt einen HTTP-Fehler in eine verständliche deutsche Meldung um.

        Hintergrund: Ollama antwortet mit 404 sowohl wenn der Endpunkt falsch
        ist als auch wenn das *Modell* auf dem Server fehlt
        ({"error": "model 'x' not found, try pulling it first"}). Ohne diese
        Unterscheidung wirkt es so, als wäre der Server falsch konfiguriert,
        obwohl nur der Modellname nicht stimmt -- genau das ist hier passiert.
        """
        status = resp.status_code
        body_text = ""
        server_error = ""
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                server_error = str(data["error"])
                body_text = server_error
        except ValueError:
            # Kein JSON (z.B. Reverse-Proxy-Fehlerseite) -> Rohtext kürzen
            try:
                body_text = (resp.text or "").strip()[:300]
            except Exception:
                body_text = ""

        if status == 404 and ("model" in body_text.lower() and "not found" in body_text.lower()):
            return OllamaError(
                f"Modell '{self.model}' ist auf dem Ollama-Server "
                f"({self.base_url}) nicht installiert. "
                f"Im Dashboard unter Einstellungen auf 'Modelle laden' klicken, "
                f"ein installiertes Modell aus der Auswahlliste wählen und speichern. "
                f"Servermeldung: {body_text}"
            )
        if status == 404:
            return OllamaError(
                f"Ollama-Endpunkt nicht gefunden (404) unter {self.base_url}/api/generate. "
                f"Base-URL prüfen (nur Schema+Host+Port, z.B. http://192.168.178.95:11434, "
                f"ohne Pfad-Endung) und sicherstellen, dass Ollama läuft "
                f"(Test: {self.base_url}/api/tags im Browser). "
                f"Servermeldung: {body_text or 'keine'}"
            )
        detail = body_text or f"HTTP {status}"
        return OllamaError(f"Ollama-Anfrage fehlgeschlagen (HTTP {status}): {detail}")

    def generate(self, prompt: str, system: str | None = None) -> str:
        if not self.base_url:
            raise OllamaError(
                "Keine Ollama Base-URL konfiguriert. "
                "Im Dashboard unter Einstellungen die Base-URL eintragen "
                "(z.B. http://192.168.178.95:11434)."
            )
        if not self.model:
            raise OllamaError(
                "Kein Ollama-Modell konfiguriert. "
                "Im Dashboard unter Einstellungen auf 'Modelle laden' klicken, "
                "ein Modell aus der Auswahlliste wählen und speichern."
            )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        try:
            resp = self.session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout_seconds,
            )
            if resp.status_code >= 400:
                raise self._friendly_http_error(resp)
        except OllamaError:
            raise
        except requests.RequestException as exc:
            raise OllamaError(
                f"Ollama-Server unter {self.base_url} nicht erreichbar: {exc}. "
                f"Prüfen ob Ollama läuft, Host/Port stimmen und der LXC "
                f"den Host erreichen kann."
            ) from exc

        data = resp.json()
        response_text = data.get("response", "").strip()
        if not response_text:
            raise OllamaError("Ollama hat eine leere Antwort geliefert.")
        return response_text
