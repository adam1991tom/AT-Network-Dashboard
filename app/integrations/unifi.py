from __future__ import annotations

import requests


class UniFiClient:
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl

    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key}

    def test_connection(self) -> dict:
        for path in (
            "/proxy/network/integration/v1/info",
            "/integration/v1/info",
            "/proxy/network/integration/v1/sites",
        ):
            try:
                response = requests.get(
                    self.base_url + path,
                    headers=self.headers,
                    timeout=10,
                    verify=self.verify_ssl,
                )
                if response.ok:
                    return {"ok": True, "endpoint": path, "status_code": response.status_code}
            except requests.RequestException:
                continue
        return {"ok": False, "message": "Unable to connect to UniFi"}
