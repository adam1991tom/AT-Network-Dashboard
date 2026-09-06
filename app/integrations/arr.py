from __future__ import annotations
from typing import Any
import requests


class ArrClient:
    """Shared client for Sonarr/Radarr/Prowlarr - all three run the same
    Servarr API shape (v3 for Sonarr/Radarr, v1 for Prowlarr), just with
    different resource names."""

    # Missing-content search command differs by app; Sonarr/Radarr are the
    # only two kinds this client is used for besides Prowlarr (which
    # overrides summary()/actions entirely below).
    MISSING_SEARCH_COMMAND = {"sonarr": "MissingEpisodeSearch", "radarr": "MissingMoviesSearch"}

    def __init__(self, base_url: str, api_key: str, api_version: str = "v3", verify_ssl: bool = True, kind: str = "sonarr"):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.api_version = api_version
        self.verify_ssl = bool(verify_ssl)
        self.kind = kind

    def _check(self) -> None:
        if not self.base_url:
            raise ValueError("Enter the server URL")
        if not self.api_key:
            raise ValueError("Enter the API key")

    def _get(self, path: str, timeout: int = 10) -> Any:
        self._check()
        url = f"{self.base_url}/api/{self.api_version}{path}"
        response = requests.get(url, headers={"X-Api-Key": self.api_key}, timeout=timeout, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, json_body: dict | None = None, timeout: int = 15) -> Any:
        self._check()
        url = f"{self.base_url}/api/{self.api_version}{path}"
        response = requests.post(url, headers={"X-Api-Key": self.api_key}, json=json_body, timeout=timeout, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json() if response.content else {}

    def _delete(self, path: str, params: dict | None = None, timeout: int = 15) -> Any:
        self._check()
        url = f"{self.base_url}/api/{self.api_version}{path}"
        response = requests.delete(url, headers={"X-Api-Key": self.api_key}, params=params, timeout=timeout, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json() if response.content else {}

    def trigger_command(self, name: str) -> dict:
        return self._post("/command", {"name": name})

    def rss_sync(self) -> dict:
        return self.trigger_command("RssSync")

    def missing_search(self) -> dict:
        return self.trigger_command(self.MISSING_SEARCH_COMMAND.get(self.kind, "MissingEpisodeSearch"))

    def remove_queue_item(self, queue_id: int, remove_from_client: bool = True, blocklist: bool = False) -> dict:
        return self._delete(f"/queue/{queue_id}", params={"removeFromClient": str(remove_from_client).lower(), "blocklist": str(blocklist).lower()})

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
                    "id": item.get("id"),
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
        super().__init__(base_url, api_key, api_version="v1", verify_ssl=verify_ssl, kind="prowlarr")

    def test_all_indexers(self) -> dict:
        results = self._post("/indexer/testall") or []
        failures = [r for r in results if not r.get("isValid", True)]
        return {"tested": len(results), "failing": len(failures)}

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
