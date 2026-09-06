from __future__ import annotations
import requests


class PlexClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()

    def _get(self, path: str, timeout: int = 10) -> dict:
        if not self.base_url:
            raise ValueError("Enter the Plex server URL")
        if not self.token:
            raise ValueError("Enter the Plex token")
        response = requests.get(
            f"{self.base_url}{path}",
            params={"X-Plex-Token": self.token},
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        return (response.json() or {}).get("MediaContainer") or {}

    def identity(self) -> dict:
        return self._get("/identity")

    def sections(self) -> list[dict]:
        return self._get("/library/sections").get("Directory") or []

    def sessions(self) -> list[dict]:
        return self._get("/status/sessions").get("Metadata") or []

    def _action(self, path: str, params: dict, timeout: int = 15) -> dict:
        if not self.base_url:
            raise ValueError("Enter the Plex server URL")
        if not self.token:
            raise ValueError("Enter the Plex token")
        response = requests.get(f"{self.base_url}{path}", params={**params, "X-Plex-Token": self.token}, timeout=timeout)
        response.raise_for_status()
        return {"ok": True}

    def refresh_section(self, key: str) -> dict:
        if not self.base_url:
            raise ValueError("Enter the Plex server URL")
        if not self.token:
            raise ValueError("Enter the Plex token")
        response = requests.put(f"{self.base_url}/library/sections/{key}/refresh", params={"X-Plex-Token": self.token}, timeout=15)
        response.raise_for_status()
        return {"ok": True}

    def terminate_session(self, session_id: str, reason: str = "") -> dict:
        return self._action("/status/sessions/terminate", {"sessionId": session_id, "reason": reason or "Stopped from AT Network Dashboard"})

    def test_connection(self) -> dict:
        try:
            data = self.identity()
            return {"ok": True, "message": f"Connected · Plex version {data.get('version', 'unknown')}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def summary(self) -> dict:
        sessions = self.sessions()
        sections = self.sections()
        return {
            "ok": True,
            "stream_count": len(sessions),
            "sessions": [
                {
                    "session_id": (s.get("Session") or {}).get("id"),
                    "user": (s.get("User") or {}).get("title"),
                    "title": s.get("grandparentTitle") and f"{s.get('grandparentTitle')} - {s.get('title')}" or s.get("title"),
                    "state": (s.get("Player") or {}).get("state"),
                    "progress_percent": round(100 * int(s.get("viewOffset") or 0) / int(s.get("duration") or 1)),
                }
                for s in sessions
            ],
            "libraries": [{"key": sec.get("key"), "name": sec.get("title"), "type": sec.get("type")} for sec in sections],
        }
