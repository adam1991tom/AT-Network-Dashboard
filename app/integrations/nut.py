from __future__ import annotations

from urllib.parse import urlparse

import requests


class NutPiHttpClient:
    def __init__(self, host: str, status_path: str = "/api/nutpi/status.cgi") -> None:
        raw = host.strip()
        self.status_path = status_path if status_path.startswith("/") else f"/{status_path}"

        # Accept either a plain host/IP (10.0.0.11), host:port
        # (10.0.0.11:80), or a full URL (http://10.0.0.11:80).
        if raw.startswith(("http://", "https://")):
            parsed = urlparse(raw)
            self.scheme = parsed.scheme or "http"
            self.netloc = parsed.netloc
            base_path = parsed.path.rstrip("/")
            self.base_path = base_path if base_path and base_path != "/" else ""
        else:
            self.scheme = "http"
            self.netloc = raw.rstrip("/")
            self.base_path = ""

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.netloc}{self.base_path}{self.status_path}"

    def status(self) -> dict:
        response = requests.get(self.url, timeout=10)
        response.raise_for_status()
        return response.json()

    def test_connection(self) -> dict:
        try:
            data = self.status()
            return {
                "ok": True,
                "message": "Connected to NUTPI",
                "status": data.get("ups.status"),
                "load": data.get("ups.load"),
                "input_voltage": data.get("input.voltage"),
                "output_voltage": data.get("output.voltage"),
                "battery_voltage": data.get("battery.voltage"),
                "url": self.url,
            }
        except (requests.RequestException, ValueError) as exc:
            return {"ok": False, "message": str(exc), "url": self.url}
