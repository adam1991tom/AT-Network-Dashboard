from __future__ import annotations
import time
from typing import Any

from app.integrations.discord import DiscordNotifier
from app.integrations.whatsapp import WhatsAppNotifier
from app.settings_store import get_secret

_last_notice: dict[str, float] = {}
_last_notice_wa: dict[str, float] = {}
_RANK = {"warning": 1, "major": 2, "critical": 3}


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _notify_allowed(cfg: dict[str, Any], category: str, severity: str) -> bool:
    if not _bool(cfg.get("discord_enabled")):
        return False
    if _RANK.get(severity, 1) < _RANK.get(str(cfg.get("notification_min_severity") or "warning"), 1):
        return False
    c = str(category or "").lower()
    key = (
        "notify_internet" if c in {"isp", "internet"} else
        "notify_wifi" if c == "wi-fi" else
        "notify_power" if c == "ups" else
        "notify_gateway" if c == "gateway" else
        "notify_system"
    )
    return _bool(cfg.get(key), True)


def _whatsapp_allowed(cfg: dict[str, Any], severity: str) -> bool:
    if not _bool(cfg.get("whatsapp_enabled")):
        return False
    return _RANK.get(severity, 1) >= _RANK.get(str(cfg.get("whatsapp_min_severity") or "major"), 2)


def notify_incident_transition(cfg: dict[str, Any], incident_key: str, transition: str, severity: str, category: str, device: str, summary: str, details: str) -> None:
    if _bool(cfg.get("maintenance_mode")):
        return
    try:
        if _notify_allowed(cfg, category, severity):
            cooldown = max(1, int(float(cfg.get("notification_cooldown_minutes") or 15))) * 60
            key = f"{incident_key}:{transition}"
            now = time.monotonic()
            if now - _last_notice.get(key, 0) >= cooldown:
                hook = get_secret("discord_webhook") or ""
                if hook:
                    icon = "🚨" if transition == "open" else "✅"
                    DiscordNotifier(hook).send(f"{icon} {summary}\n{category} · {device} · {severity.upper()} · {transition.upper()}\n{details}")
                    _last_notice[key] = now
    except Exception as exc:
        print(f"notifications: incident notify failed: {exc}")
    try:
        if _whatsapp_allowed(cfg, severity):
            cooldown = max(1, int(float(cfg.get("whatsapp_cooldown_minutes") or 30))) * 60
            key = f"{incident_key}:{transition}"
            now = time.monotonic()
            if now - _last_notice_wa.get(key, 0) >= cooldown:
                base_url = str(cfg.get("whatsapp_base_url") or "").strip()
                session_id = str(cfg.get("whatsapp_session_id") or "").strip()
                chat_id = str(cfg.get("whatsapp_chat_id") or "").strip()
                if base_url and session_id and chat_id:
                    api_key = get_secret("whatsapp_api_key") or ""
                    icon = "🚨" if transition == "open" else "✅"
                    WhatsAppNotifier(base_url, api_key, session_id, chat_id).send(f"{icon} {summary}\n{category} · {device} · {severity.upper()} · {transition.upper()}\n{details}")
                    _last_notice_wa[key] = now
    except Exception as exc:
        print(f"notifications: whatsapp notify failed: {exc}")
