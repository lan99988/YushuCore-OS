from __future__ import annotations

import json
from typing import Any, Callable
from urllib.request import Request, urlopen


class OllamaClient:
    """Local-only Ollama API client. It never selects a cloud provider."""

    def __init__(self, *, base_url: str = "http://127.0.0.1:11434", opener: Callable[..., Any] | None = None, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._opener = opener or urlopen
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._opener(request, timeout=self.timeout) as response:
            if getattr(response, "status", 200) >= 400:
                raise RuntimeError(f"ollama request failed: {response.status}")
            return json.loads(response.read().decode("utf-8"))

    def health(self) -> dict[str, object]:
        request = Request(f"{self.base_url}/api/tags", method="GET")
        with self._opener(request, timeout=self.timeout) as response:
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                raise RuntimeError("ollama health request failed")
            return {"status": "available", "http_status": status, "local": True}

    def generate(self, model: str, prompt: str) -> dict[str, object]:
        if not model.strip() or not prompt.strip():
            raise ValueError("model and prompt are required")
        return self._post("/api/generate", {"model": model, "prompt": prompt, "stream": False})

    def route(self, *, sensitivity: str) -> dict[str, str]:
        if sensitivity not in {"level_0", "level_1", "level_2", "level_3", "level_4"}:
            raise ValueError("invalid sensitivity")
        return {"provider": "local", "reason": "Ollama local-first route"}
