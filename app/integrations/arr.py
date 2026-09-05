from __future__ import annotations
from typing import Any
import requests


class ArrClient:
    """Shared client for Sonarr/Radarr/Prowlarr - all three run the same
    Servarr API shape (v3 for Sonarr/Radarr, v1 for Prowlarr), just with
    different resource names."""

    def __init__(self, base_url: str, api_key: str, api_version: str = "v3", verify_ssl: bool = True):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.api_version = api_version
        self.verify_ssl = bool(verify_ssl)

    def _get(self, path: str, timeout: int = 10) -> Any:
        if not self.base_url:
            raise ValueError("Enter the server URL")
        if not self.api_key:
            raise ValueError("Enter the API key")
        url = f"{self.base_url}/api/{self.api_version}{path}"
        response = requests.get(url, headers={"X-Api-Key": self.api_key}, timeout=timeout, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()

    def status(self) -> dict:
        return self._get("/system/status")

    def health(self) -> list[dict]:
        return self._get("/health") or []

    def queue(self) -> dict:
        return self._get("/queue?pageSize=25")

    def test_connection(self) -> dict:
        try:
            data = self.status()
            return {"ok": True, "message": f"Connected to {data.get('appName','')} {data.get('version','')}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def summary(self) -> dict:
        status = self.status()
        health = self.health()
        queue = self.queue()
        warnings = [h for h in health if str(h.get("type", "")).lower() in {"warning", "error"}]
        return {
            "ok": True,
            "app_name": status.get("appName"),
            "version": status.get("version"),
            "health": [{"type": h.get("type"), "message": h.get("message")} for h in warnings],
            "queue_count": int(queue.get("totalRecords") or 0),
            "queue": [
                {
                    "title": item.get("title"),
                    "status": item.get("status"),
                    "size": item.get("size"),
                    "sizeleft": item.get("sizeleft"),
                    "timeleft": item.get("timeleft"),
                }
                for item in (queue.get("records") or [])[:10]
            ],
        }


class ProwlarrClient(ArrClient):
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = True):
        super().__init__(base_url, api_key, api_version="v1", verify_ssl=verify_ssl)

    def indexers(self) -> list[dict]:
        return self._get("/indexer") or []

    def indexer_status(self) -> list[dict]:
        # Non-empty entries are indexers currently blocked/failing; a healthy
        # setup returns an empty list, not a per-indexer "healthy" status.
        return self._get("/indexerstatus") or []

    def summary(self) -> dict:
        status = self.status()
        indexers = self.indexers()
        enabled = [i for i in indexers if i.get("enable")]
        failing_ids = {row.get("indexerId") for row in self.indexer_status()}
        by_id = {i.get("id"): i.get("name") for i in indexers}
        return {
            "ok": True,
            "app_name": status.get("appName"),
            "version": status.get("version"),
            "indexer_count": len(indexers),
            "enabled_count": len(enabled),
            "failing": [{"name": by_id.get(i, f"#{i}")} for i in failing_ids],
        }
