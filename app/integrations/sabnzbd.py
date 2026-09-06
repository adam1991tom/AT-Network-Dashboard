from __future__ import annotations
import requests


class SabnzbdClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()

    def _api(self, mode: str, timeout: int = 10, **params) -> dict:
        if not self.base_url:
            raise ValueError("Enter the SABnzbd URL")
        if not self.api_key:
            raise ValueError("Enter the API key")
        query = {"mode": mode, "output": "json", "apikey": self.api_key, **params}
        response = requests.get(f"{self.base_url}/api", params=query, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and "error" in data:
            raise ValueError(str(data["error"]))
        return data

    def queue(self) -> dict:
        return self._api("queue").get("queue") or {}

    def pause_queue(self) -> dict:
        return self._api("pause")

    def resume_queue(self) -> dict:
        return self._api("resume")

    def pause_job(self, nzo_id: str) -> dict:
        return self._api("queue", name="pause", value=nzo_id)

    def resume_job(self, nzo_id: str) -> dict:
        return self._api("queue", name="resume", value=nzo_id)

    def delete_job(self, nzo_id: str) -> dict:
        return self._api("queue", name="delete", value=nzo_id, del_files=1)

    def version(self) -> str:
        return str(self._api("version").get("version") or "")

    def test_connection(self) -> dict:
        try:
            version = self.version()
            return {"ok": True, "message": f"Connected to SABnzbd {version}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def summary(self) -> dict:
        queue = self.queue()
        slots = queue.get("slots") or []
        return {
            "ok": True,
            "status": queue.get("status"),
            "paused": bool(queue.get("paused")),
            "speed_kbps": queue.get("kbpersec"),
            "mb_left": queue.get("mbleft"),
            "timeleft": queue.get("timeleft"),
            "queue_count": int(queue.get("noofslots_total") or 0),
            "queue": [
                {"nzo_id": s.get("nzo_id"), "name": s.get("filename"), "status": s.get("status"), "size_mb": s.get("mb"), "percentage": s.get("percentage")}
                for s in slots[:10]
            ],
        }
