from __future__ import annotations

import requests


class NutPiHttpClient:
    def __init__(self, host: str, status_path: str = "/api/nutpi/status.cgi") -> None:
        self.host = host.strip()
        self.status_path = status_path if status_path.startswith("/") else f"/{status_path}"

    @property
    def url(self) -> str:
        return f"http://{self.host}{self.status_path}"

    def status(self) -> dict:
        response = requests.get(self.url, timeout=10)
        response.raise_for_status()
        return response.json()

    def test_connection(self) -> dict:
        try:
            data = self.status()
            return {
                "ok": True,
                "status": data.get("ups.status"),
                "load": data.get("ups.load"),
                "url": self.url,
            }
        except (requests.RequestException, ValueError) as exc:
            return {"ok": False, "message": str(exc)}
