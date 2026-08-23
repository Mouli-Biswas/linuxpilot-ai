"""
ollama_client.py
-----------------
Thin async wrapper around the local Ollama HTTP API for talking to
Qwen 2.5 Instruct. Every other AI module (intent classifier, planner,
summarizer) goes through this single client so the model name, host,
and generation defaults live in exactly one place.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from backend.utils.config import settings

logger = logging.getLogger("linuxpilot.ollama")


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns a malformed response."""


class OllamaClient:
    def __init__(
        self,
        host: str = settings.OLLAMA_HOST,
        model: str = settings.OLLAMA_MODEL,
        timeout: float = 30.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def is_available(self) -> bool:
        """Quickly check if the Ollama server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.host}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        """Single-shot completion. Returns raw text from the model."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        url = f"{self.host}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.error("Ollama request failed: %s", exc)
            raise OllamaError(f"Could not reach Ollama at {url}: {exc}") from exc

        text = data.get("response", "")
        if not text:
            raise OllamaError(f"Ollama returned an empty response: {data}")
        return text

    async def generate_json(self, prompt: str, system: Optional[str] = None) -> dict:
        """Convenience wrapper that enforces JSON mode and parses the result."""
        raw = await self.generate(prompt, system=system, json_mode=True, temperature=0.0)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Qwen occasionally wraps JSON in ```json fences despite format=json.
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as exc:
                logger.error("Failed to parse JSON from model output: %s", raw)
                raise OllamaError(f"Model did not return valid JSON: {exc}") from exc


ollama_client = OllamaClient()

