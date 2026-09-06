from __future__ import annotations
import requests


class TautulliClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()

    def _cmd(self, cmd: str, timeout: int = 10, **params) -> dict:
        if not self.base_url:
            raise ValueError("Enter the Tautulli URL")
        if not self.api_key:
            raise ValueError("Enter the API key")
        query = {"apikey": self.api_key, "cmd": cmd, **params}
        response = requests.get(f"{self.base_url}/api/v2", params=query, timeout=timeout)
        response.raise_for_status()
        payload = response.json().get("response") or {}
        if payload.get("result") != "success":
            raise ValueError(str(payload.get("message") or "Tautulli request failed"))
        return payload.get("data") or {}

    def activity(self) -> dict:
        return self._cmd("get_activity")

    def libraries(self) -> list[dict]:
        return self._cmd("get_libraries") or []

    def terminate_session(self, session_id: str, message: str = "") -> dict:
        return self._cmd("terminate_session", session_id=session_id, message=message or "Stopped from AT Network Dashboard")

    def test_connection(self) -> dict:
        try:
            data = self.activity()
            return {"ok": True, "message": f"Connected · {data.get('stream_count', 0)} active streams"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def summary(self) -> dict:
        activity = self.activity()
        libraries = self.libraries()
        sessions = activity.get("sessions") or []
        return {
            "ok": True,
            "stream_count": int(activity.get("stream_count") or 0),
            "transcode_count": int(activity.get("stream_count_transcode") or 0),
            "total_bandwidth_kbps": activity.get("total_bandwidth"),
            "sessions": [
                {
                    "session_id": s.get("session_key"),
                    "user": s.get("user"),
                    "title": s.get("full_title"),
                    "state": s.get("state"),
                    "progress_percent": s.get("progress_percent"),
                    "quality": s.get("quality_profile") or s.get("transcode_decision"),
                }
                for s in sessions
            ],
            "libraries": [
                {"name": lib.get("section_name"), "type": lib.get("section_type"), "count": lib.get("count")}
                for lib in libraries
            ],
        }
