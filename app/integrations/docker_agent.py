from __future__ import annotations
import requests


class DockerAgentClient:
    """Talks to a small per-host sidecar (docker-agent/) that holds the
    actual Docker socket access, so the main app never touches a raw
    socket itself - only this scoped HTTP API, authenticated with a
    shared token."""

    def __init__(self, base_url: str, token: str):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()

    def _headers(self) -> dict:
        return {"X-Agent-Token": self.token}

    def containers(self, timeout: int = 20) -> dict:
        if not self.base_url:
            raise ValueError("Enter the agent URL")
        if not self.token:
            raise ValueError("Enter the agent token")
        response = requests.get(f"{self.base_url}/containers", headers=self._headers(), timeout=timeout)
        response.raise_for_status()
        return response.json()

    def _action(self, container_id: str, action: str, timeout: int = 20) -> dict:
        if not self.base_url:
            raise ValueError("Enter the agent URL")
        if not self.token:
            raise ValueError("Enter the agent token")
        response = requests.post(f"{self.base_url}/containers/{container_id}/{action}", headers=self._headers(), timeout=timeout)
        response.raise_for_status()
        return response.json()

    def start(self, container_id: str) -> dict:
        return self._action(container_id, "start")

    def stop(self, container_id: str) -> dict:
        return self._action(container_id, "stop")

    def restart(self, container_id: str) -> dict:
        return self._action(container_id, "restart")

    def test_connection(self) -> dict:
        try:
            data = self.containers()
            return {"ok": True, "message": f"Connected · {len(data.get('containers', []))} containers on {data.get('host', '')}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
