from __future__ import annotations
import requests


class NexrollClient:
    """NeXroll's /external/* API is authenticated via an X-API-Key header,
    separate from its session-based web UI login."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()

    def _get(self, path: str, timeout: int = 10) -> dict:
        if not self.base_url:
            raise ValueError("Enter the NeXroll URL")
        if not self.api_key:
            raise ValueError("Enter the API key")
        response = requests.get(f"{self.base_url}{path}", headers={"X-API-Key": self.api_key}, timeout=timeout)
        response.raise_for_status()
        return response.json()

    def status(self) -> dict:
        return self._get("/external/status")

    def test_connection(self) -> dict:
        try:
            data = self.status()
            return {"ok": True, "message": f"Connected · {data.get('preroll_count', 0)} prerolls, {data.get('schedule_count', 0)} schedules"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def summary(self) -> dict:
        data = self.status()
        return {
            "ok": True,
            "plex_connected": bool(data.get("plex_connected")),
            "preroll_count": data.get("preroll_count"),
            "category_count": data.get("category_count"),
            "schedule_count": data.get("schedule_count"),
        }
