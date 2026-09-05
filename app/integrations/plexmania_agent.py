from __future__ import annotations
import requests


class PlexmaniaAgentClient:
    """Talks to the plexmania-agent PowerShell HTTP listener (see
    plexmania-agent/agent.ps1). No Docker on that host - Plex, ErsatzTV and
    NeXroll run as bare Windows processes, so this offers process
    status + restart instead of container start/stop/restart, but uses the
    same shared-token auth shape as DockerAgentClient."""

    def __init__(self, base_url: str, token: str):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()

    def _headers(self) -> dict:
        return {"X-Agent-Token": self.token}

    def processes(self, timeout: int = 10) -> dict:
        if not self.base_url:
            raise ValueError("Enter the agent URL")
        if not self.token:
            raise ValueError("Enter the agent token")
        response = requests.get(f"{self.base_url}/processes", headers=self._headers(), timeout=timeout)
        response.raise_for_status()
        return response.json()

    def restart(self, name: str, timeout: int = 40) -> dict:
        if not self.base_url:
            raise ValueError("Enter the agent URL")
        if not self.token:
            raise ValueError("Enter the agent token")
        response = requests.post(f"{self.base_url}/processes/{name}/restart", headers=self._headers(), timeout=timeout)
        response.raise_for_status()
        return response.json()

    def test_connection(self) -> dict:
        try:
            data = self.processes()
            return {"ok": True, "message": f"Connected · {len(data.get('processes', []))} apps on {data.get('host', '')}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
