from __future__ import annotations

import requests


class DiscordNotifier:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url.strip()

    def send(self, message: str) -> dict:
        if not self.webhook_url:
            return {"ok": False, "message": "Webhook not configured"}
        try:
            response = requests.post(
                self.webhook_url,
                json={"content": message},
                timeout=10,
            )
            return {
                "ok": response.status_code in {200, 204},
                "status_code": response.status_code,
            }
        except requests.RequestException as exc:
            return {"ok": False, "message": str(exc)}
