from __future__ import annotations

import time
from typing import Any

from app.database import connect
from app.integrations.gemini import GeminiClient
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings, get_secret

_last_fix: dict[str, float] = {}
_ai_last_action: dict[str, float] = {}

# Per-category allow-list of actions the AI assistant may recommend/execute.
# UPS and ISP have no safe automatic action (see _execute_action) so they are
# diagnosis-only. Categories not listed here are outside this feature's scope
# (e.g. Media, System) and are skipped entirely.
_AI_ACTION_ALLOWLIST: dict[str, set[str]] = {
    "Wi-Fi": {"restart_ap", "none"},
    "Gateway": {"restart_gateway", "none"},
    "Internet": {"restart_gateway", "none"},
    "UPS": {"none"},
    "ISP": {"none"},
}


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _log(
    incident_key: str,
    category: str,
    device: str,
    action: str,
    ok: bool,
    message: str,
    source: str = "rule",
    explanation: str = "",
    confidence: float | None = None,
) -> None:
    con = connect()
    try:
        con.execute(
            "INSERT INTO remediation_actions(incident_key,category,device,action,result_ok,message,source,explanation,confidence) VALUES (?,?,?,?,?,?,?,?,?)",
            (incident_key, category, device, action, 1 if ok else 0, message, source, explanation, confidence),
        )
        con.commit()
    finally:
        con.close()


def maybe_fix(incident_key: str, category: str, device: str) -> None:
    """Legacy rule-based fallback, used only when the AI assistant is not enabled
    or not configured with an API key yet. Handles exactly one case: reboot a
    single access point that is reporting sustained high Wi-Fi retries
    (incident_key 'wifi-retries:<device_id>:<band>').

    Deliberately does not touch the gateway/router or UPS/power here — once the
    AI assistant is configured, handle_incident_opened() takes over and makes
    judgment-based decisions across all categories instead.
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


def _build_prompt(category: str, device: str, severity: str, summary: str, details: str, allowed: set[str]) -> str:
    options = ", ".join(sorted(allowed))
    return (
        "You are a network operations assistant for a home network monitoring dashboard. "
        "An incident has just started:\n\n"
        f"Category: {category}\nDevice: {device}\nSeverity: {severity}\nSummary: {summary}\nDetails: {details}\n\n"
        "Respond with strict JSON only, matching this shape:\n"
        '{"explanation": "<one or two sentence plain-English explanation of the likely cause>", '
        f'"recommended_action": "<one of: {options}>", '
        '"confidence": <number 0.0-1.0>, "reasoning": "<one sentence on why this action is or is not warranted>"}\n\n'
        "Rules:\n"
        '- "restart_ap" reboots one Wi-Fi access point (roughly a 30 second outage for clients on that AP only).\n'
        '- "restart_gateway" reboots the entire router/gateway (a full 60-90 second outage for the whole network) — '
        "only recommend this when a reboot plausibly fixes the described symptom (e.g. WAN reported offline, or a "
        "resource looks stuck/exhausted), never for a purely physical/environmental issue like high temperature, and "
        "never when the symptom looks like an upstream ISP outage that a local reboot cannot fix.\n"
        '- "none" means diagnose only, do not act.\n'
        f"- Only ever choose from: {options}. Never invent another action.\n"
    )


def _execute_action(action: str, incident_key: str, cfg: dict[str, Any]) -> dict[str, Any]:
    api_key = get_secret("unifi_api_key") or ""
    url = str(cfg.get("unifi_url", "")).strip()
    if not _bool(cfg.get("unifi_enabled")) or not api_key or not url:
        return {"ok": False, "message": "UniFi integration is not configured"}
    client = UniFiClient(url, api_key, _bool(cfg.get("unifi_verify_ssl")))

    if action == "restart_ap":
        if not incident_key.startswith("wifi-retries:"):
            return {"ok": False, "message": "AP restart is only valid for wifi-retries incidents"}
        # Never trust a device/MAC named by the model — always derive it from the
        # incident_key the monitoring loop generated, so a hallucinated target can't
        # cause the wrong device (or the gateway) to be restarted.
        rest = incident_key[len("wifi-retries:"):]
        device_id, _, _band = rest.rpartition(":")
        if not device_id:
            return {"ok": False, "message": "Could not determine access point from incident"}
        return client.restart_device(device_id)

    if action == "restart_gateway":
        try:
            snapshot = client.snapshot()
            mac = str((snapshot.get("gateway") or {}).get("mac") or "")
        except Exception as exc:
            return {"ok": False, "message": f"Could not look up gateway MAC: {exc}"}
        if not mac:
            return {"ok": False, "message": "Gateway MAC not available from UniFi snapshot"}
        return client.restart_gateway(mac)

    return {"ok": False, "message": f"Unknown action '{action}'"}


def handle_incident_opened(incident_key: str, category: str, device: str, severity: str, summary: str, details: str) -> None:
    """Single entry point called whenever an incident transitions to active.

    When the AI assistant is enabled and configured, asks Gemini to diagnose the
    incident and — if the separate autonomous-action switch is also on — executes
    a safe action chosen from a strict per-category allow-list. Falls back to the
    pre-existing rule-based Wi-Fi-only auto-fix otherwise.
    """
    cfg = all_settings()
    if _bool(cfg.get("maintenance_mode")):
        return
    if not _bool(cfg.get("auto_remediation_enabled")):
        return

    api_key = get_secret("gemini_api_key") or ""
    if not _bool(cfg.get("ai_enabled")) or not api_key:
        maybe_fix(incident_key, category, device)
        return

    allowed = _AI_ACTION_ALLOWLIST.get(category)
    if allowed is None:
        return  # category outside the scope of AI diagnosis

    client = GeminiClient(api_key, str(cfg.get("ai_model") or "gemini-2.0-flash"))
    prompt = _build_prompt(category, device, severity, summary, details, allowed)
    result = client.diagnose_incident(prompt)
    if not result.get("ok"):
        _log(incident_key, category, device, "ai_diagnose", False, str(result.get("message") or "Gemini request failed"), source="ai")
        return

    data = result.get("data") or {}
    explanation = str(data.get("explanation") or "").strip()[:2000]
    reasoning = str(data.get("reasoning") or "").strip()[:1000]
    confidence = _clamp01(data.get("confidence"))
    action = str(data.get("recommended_action") or "none").strip()
    if action not in allowed:
        action = "none"
    combined_message = f"{explanation} ({reasoning})" if reasoning else explanation

    if action == "none" or not _bool(cfg.get("ai_autonomous_enabled")):
        label = "diagnose_only" if action == "none" else f"recommend_{action}"
        _log(incident_key, category, device, label, True, combined_message, source="ai", explanation=explanation, confidence=confidence)
        return

    cooldown_key = f"{incident_key}:{action}"
    cooldown = max(5, int(float(cfg.get("ai_autonomous_cooldown_minutes") or 30))) * 60
    now = time.monotonic()
    if now - _ai_last_action.get(cooldown_key, 0) < cooldown:
        _log(incident_key, category, device, f"{action}_skipped_cooldown", True, combined_message, source="ai", explanation=explanation, confidence=confidence)
        return
    _ai_last_action[cooldown_key] = now

    exec_result = _execute_action(action, incident_key, cfg)
    final_message = f"{combined_message} — {exec_result.get('message', '')}".strip(" —")
    _log(incident_key, category, device, action, bool(exec_result.get("ok")), final_message, source="ai", explanation=explanation, confidence=confidence)


def recent_actions(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    con = connect()
    try:
        rows = con.execute(
            "SELECT id,ts,incident_key,category,device,action,result_ok,message,source,explanation,confidence FROM remediation_actions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
