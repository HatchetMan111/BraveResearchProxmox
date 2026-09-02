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
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def generate(self, prompt: str, system: str | None = None) -> str:
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
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama-Anfrage fehlgeschlagen: {exc}") from exc

        data = resp.json()
        response_text = data.get("response", "").strip()
        if not response_text:
            raise OllamaError("Ollama hat eine leere Antwort geliefert.")
        return response_text
