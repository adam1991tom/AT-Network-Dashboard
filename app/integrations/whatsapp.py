from __future__ import annotations

import requests


class WhatsAppNotifier:
    """Sends alert text through a self-hosted OpenWA (https://www.open-wa.org) instance,
    using its REST API: POST /api/sessions/{sessionId}/messages/send-text, authenticated
    with an X-API-Key header and a JSON body of {"chatId": ..., "text": ...}. The session
    must already be connected (QR-scanned) in OpenWA before this will work.
    """

    def __init__(self, base_url: str, api_key: str, session_id: str, chat_id: str) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.session_id = (session_id or "").strip()
        self.chat_id = (chat_id or "").strip()

    def send(self, message: str) -> dict:
        if not self.base_url:
            return {"ok": False, "message": "OpenWA server URL not configured"}
        if not self.session_id:
            return {"ok": False, "message": "OpenWA session ID not configured"}
        if not self.chat_id:
            return {"ok": False, "message": "WhatsApp recipient (chat id) not configured"}
        headers = {"Content-Type": "application/json", "X-API-Key": self.api_key}
        try:
            response = requests.post(
                f"{self.base_url}/api/sessions/{self.session_id}/messages/send-text",
                headers=headers,
                json={"chatId": self.chat_id, "text": message},
                timeout=15,
            )
            return {
                "ok": response.ok,
                "status_code": response.status_code,
                "body": response.text[:300] if not response.ok else None,
            }
        except requests.RequestException as exc:
            return {"ok": False, "message": str(exc)}
