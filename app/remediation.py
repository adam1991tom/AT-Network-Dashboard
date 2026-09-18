from __future__ import annotations

import time
from typing import Any

from app.database import connect
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings, get_secret

_last_fix: dict[str, float] = {}


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _log(incident_key: str, category: str, device: str, action: str, ok: bool, message: str) -> None:
    con = connect()
    try:
        con.execute(
            "INSERT INTO remediation_actions(incident_key,category,device,action,result_ok,message) VALUES (?,?,?,?,?,?)",
            (incident_key, category, device, action, 1 if ok else 0, message),
        )
        con.commit()
    finally:
        con.close()


def maybe_fix(incident_key: str, category: str, device: str) -> None:
    """Attempt a safe, reversible auto-fix for a small allow-list of known-recoverable
    incident types. Currently handles exactly one case: reboot a single access point that
    is reporting sustained high Wi-Fi retries (incident_key 'wifi-retries:<device_id>:<band>').

    Deliberately does NOT touch the gateway/router (internet-offline, gateway-wan-offline,
    gateway-* incidents) or UPS/power incidents — those either have no safe software fix or
    risk cutting off the connection this dashboard needs to keep managing the network.
    """
    if category != "Wi-Fi" or not incident_key.startswith("wifi-retries:"):
        return
    cfg = all_settings()
    if not _bool(cfg.get("auto_remediation_enabled")):
        return
    if _bool(cfg.get("maintenance_mode")):
        return
    if not _bool(cfg.get("unifi_enabled")):
        return

    cooldown = max(5, int(float(cfg.get("auto_remediation_cooldown_minutes") or 60))) * 60
    now = time.monotonic()
    if now - _last_fix.get(incident_key, 0) < cooldown:
        return

    api_key = get_secret("unifi_api_key") or ""
    url = str(cfg.get("unifi_url", "")).strip()
    if not api_key or not url:
        return

    # incident_key is "wifi-retries:<device_id>:<band>" and device_id is frequently a MAC
    # address (colon-separated), so split off the band from the right rather than the left.
    rest = incident_key[len("wifi-retries:"):]
    device_id, _, _band = rest.rpartition(":")
    if not device_id:
        return

    _last_fix[incident_key] = now
    client = UniFiClient(url, api_key, _bool(cfg.get("unifi_verify_ssl")))
    result = client.restart_device(device_id)
    _log(incident_key, category, device, "restart_access_point", bool(result.get("ok")), str(result.get("message") or ""))


def recent_actions(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    con = connect()
    try:
        rows = con.execute(
            "SELECT id,ts,incident_key,category,device,action,result_ok,message FROM remediation_actions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
