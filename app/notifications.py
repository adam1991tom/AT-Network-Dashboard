from __future__ import annotations
import time
from typing import Any

from app.integrations.discord import DiscordNotifier
from app.settings_store import get_secret

_last_notice: dict[str, float] = {}
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


def notify_incident_transition(cfg: dict[str, Any], incident_key: str, transition: str, severity: str, category: str, device: str, summary: str, details: str) -> None:
    if _bool(cfg.get("maintenance_mode")):
        return
    try:
        if not _notify_allowed(cfg, category, severity):
            return
        cooldown = max(1, int(float(cfg.get("notification_cooldown_minutes") or 15))) * 60
        key = f"{incident_key}:{transition}"
        now = time.monotonic()
        if now - _last_notice.get(key, 0) < cooldown:
            return
        hook = get_secret("discord_webhook") or ""
        if hook:
            icon = "🚨" if transition == "open" else "✅"
            DiscordNotifier(hook).send(f"{icon} {summary}\n{category} · {device} · {severity.upper()} · {transition.upper()}\n{details}")
            _last_notice[key] = now
    except Exception as exc:
        print(f"notifications: incident notify failed: {exc}")
