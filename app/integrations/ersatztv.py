from __future__ import annotations
import requests


class ErsatzTvClient:
    """ErsatzTV's local API requires no authentication by default."""

    def __init__(self, base_url: str):
        self.base_url = (base_url or "").strip().rstrip("/")

    def _get(self, path: str, timeout: int = 10):
        if not self.base_url:
            raise ValueError("Enter the ErsatzTV URL")
        response = requests.get(f"{self.base_url}{path}", timeout=timeout)
        response.raise_for_status()
        return response.json()

    def channels(self) -> list[dict]:
        return self._get("/api/channels") or []

    def test_connection(self) -> dict:
        try:
            channels = self.channels()
            return {"ok": True, "message": f"Connected · {len(channels)} channels"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def summary(self) -> dict:
        channels = self.channels()
        return {
            "ok": True,
            "channel_count": len(channels),
            "channels": [{"number": c.get("number"), "name": c.get("name")} for c in channels],
        }
