from __future__ import annotations

import json
from typing import Any

import requests

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient:
    """Thin REST client for Google's free-tier Gemini API — no SDK dependency.

    Uses response_mime_type=application/json so the model is constrained to
    return parseable JSON instead of prose we'd have to scrape.
    """

    def __init__(self, api_key: str, model: str = "gemini-3.6-flash") -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or "gemini-3.6-flash").strip()

    def _generate_text(self, prompt: str, max_tokens: int = 1024, json_mode: bool = True) -> dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "message": "Gemini API key not configured"}
        url = f"{API_BASE}/{self.model}:generateContent"
        generation_config: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            # temperature/top_p/top_k are deprecated on Gemini 3.x generateContent
            # calls (Google's migration guidance says to strip them), so only
            # output shaping is configured here.
            "generationConfig": generation_config,
        }
        try:
            response = requests.post(url, params={"key": self.api_key}, json=payload, timeout=45)
        except requests.RequestException as exc:
            return {"ok": False, "message": str(exc)}
        if response.status_code == 429:
            return {"ok": False, "message": "Gemini free-tier rate limit hit — try again shortly"}
        if not response.ok:
            try:
                detail = response.json().get("error", {}).get("message")
            except Exception:
                detail = None
            return {"ok": False, "message": detail or f"HTTP {response.status_code}"}
        try:
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError, ValueError):
            return {"ok": False, "message": "Gemini returned no usable content (likely blocked by safety filters)"}
        return {"ok": True, "text": text}

    def _generate(self, prompt: str) -> dict[str, Any]:
        result = self._generate_text(prompt, json_mode=True)
        if not result.get("ok"):
            return result
        try:
            parsed = json.loads(result["text"])
        except (TypeError, ValueError):
            return {"ok": False, "message": "Gemini response was not valid JSON", "raw": result["text"][:500]}
        return {"ok": True, "data": parsed}

    def diagnose_incident(self, prompt: str) -> dict[str, Any]:
        return self._generate(prompt)

    def chat(self, prompt: str, max_tokens: int = 1500) -> dict[str, Any]:
        """Free-form text response, not constrained to JSON — for the AI Ops
        Center chat and natural-language reports."""
        result = self._generate_text(prompt, max_tokens=max_tokens, json_mode=False)
        if not result.get("ok"):
            return result
        return {"ok": True, "text": result["text"].strip()}

    def test_connection(self) -> dict[str, Any]:
        result = self._generate('Reply with strict JSON only: {"ok": true, "note": "connection test"}')
        if result.get("ok"):
            return {"ok": True, "message": f"Connected to Gemini ({self.model})"}
        return {"ok": False, "message": result.get("message", "Unknown error")}
