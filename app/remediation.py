from __future__ import annotations

import time
from typing import Any

from app.database import connect
from app.docker_routes import _HOSTS as _DOCKER_HOSTS
from app.docker_routes import _client_from_payload as _docker_client_from_payload
from app.docker_routes import _plexmania_from_payload
from app.integrations.gemini import GeminiClient
from app.integrations.shell_agent import ShellAgentClient
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings, get_secret

_last_fix: dict[str, float] = {}
_ai_last_action: dict[str, float] = {}
_shell_action_times: list[float] = []

# Per-category allow-list of actions the AI assistant may recommend/execute.
# UPS and ISP have no safe automatic action (see _execute_action) so they are
# diagnosis-only. Categories not listed here are outside this feature's scope
# and are skipped entirely. "Media" only grants restart_plexmania_process/
# run_windows_command for plexmania-* incidents specifically (checked in
# _execute_action) - other Media incidents (Sonarr/Radarr/etc., which live on
# newtiny as Docker containers, not on the plexmania Windows host) stay
# diagnosis-only here since they're already covered by the System category.
_AI_ACTION_ALLOWLIST: dict[str, set[str]] = {
    "Wi-Fi": {"restart_ap", "none"},
    "Gateway": {"restart_gateway", "none"},
    "Internet": {"restart_gateway", "none"},
    "UPS": {"none"},
    "ISP": {"none"},
    "System": {"restart_container", "run_command", "none"},
    "Media": {"restart_plexmania_process", "run_windows_command", "none"},
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
    needs_command = "run_command" in allowed or "run_windows_command" in allowed
    command_field = (
        ', "command": "<exact command to run, ONLY when recommended_action is run_command or run_windows_command, else empty string>"'
        if needs_command else ""
    )
    return (
        "You are the autonomous administrator for a home network and server monitoring dashboard. "
        "An incident has just started:\n\n"
        f"Category: {category}\nDevice: {device}\nSeverity: {severity}\nSummary: {summary}\nDetails: {details}\n\n"
        "Respond with strict JSON only, matching this shape:\n"
        '{"explanation": "<one or two sentence plain-English explanation of the likely cause>", '
        f'"recommended_action": "<one of: {options}>", '
        f'"confidence": <number 0.0-1.0>, "reasoning": "<one sentence on why this action is or is not warranted>"{command_field}}}\n\n'
        "Rules:\n"
        '- "restart_ap" reboots one Wi-Fi access point (roughly a 30 second outage for clients on that AP only).\n'
        '- "restart_gateway" reboots the entire router/gateway (a full 60-90 second outage for the whole network) — '
        "only recommend this when a reboot plausibly fixes the described symptom (e.g. WAN reported offline, or a "
        "resource looks stuck/exhausted), never for a purely physical/environmental issue like high temperature, and "
        "never when the symptom looks like an upstream ISP outage that a local reboot cannot fix.\n"
        '- "restart_container" restarts one named Docker container (safe, brief restart of just that one service).\n'
        '- "run_command" runs a single shell command directly on the host with full privileges. Use it only when no '
        "narrower action applies (e.g. freeing disk space, clearing a stuck process, restarting a system service). "
        "Put the exact command in the \"command\" field. Prefer the least invasive command that could plausibly fix "
        "the described symptom, never combine unrelated operations with ; or &&, and never guess at a fix for a "
        "symptom the details don't actually support.\n"
        '- "restart_plexmania_process" restarts one named app (plex, ersatztv, or nexroll) on the separate plexmania '
        "Windows host (safe, brief restart of just that one app).\n"
        '- "run_windows_command" runs a single PowerShell command directly on the plexmania Windows host, with the '
        "same caveats as run_command above (least invasive command, exact text in the \"command\" field, never guess).\n"
        '- "none" means diagnose only, do not act.\n'
        f"- Only ever choose from: {options}. Never invent another action.\n"
    )


def _shell_rate_limited(cfg: dict[str, Any]) -> bool:
    """Global cap across all incidents on how many shell commands the AI can run
    per hour, on top of the per-incident cooldown — a backstop against a
    misbehaving/looping diagnosis repeatedly "fixing" the same flapping issue."""
    limit = max(1, int(float(cfg.get("ai_shell_max_actions_per_hour") or 6)))
    now = time.monotonic()
    cutoff = now - 3600
    while _shell_action_times and _shell_action_times[0] < cutoff:
        _shell_action_times.pop(0)
    if len(_shell_action_times) >= limit:
        return True
    _shell_action_times.append(now)
    return False


def _execute_action(action: str, incident_key: str, cfg: dict[str, Any], command: str = "") -> dict[str, Any]:
    if action == "restart_container":
        for host in _DOCKER_HOSTS:
            prefix = f"docker-container-{host}-"
            if incident_key.startswith(prefix):
                container_name = incident_key[len(prefix):]
                client, error = _docker_client_from_payload(host, {})
                if error:
                    return {"ok": False, "message": error.get("message", "Docker agent not configured")}
                try:
                    return client.restart(container_name)
                except Exception as exc:
                    return {"ok": False, "message": str(exc)}
        return {"ok": False, "message": "Could not determine which container/host to restart from this incident"}

    if action == "run_command":
        if not command:
            return {"ok": False, "message": "No command was supplied"}
        if _shell_rate_limited(cfg):
            return {"ok": False, "message": "Global shell-action rate limit reached for this hour — skipped"}
        if not _bool(cfg.get("shell_agent_enabled")):
            return {"ok": False, "message": "Shell agent is not enabled"}
        agent_url = str(cfg.get("shell_agent_url") or "").strip()
        agent_token = get_secret("shell_agent_token") or ""
        if not agent_url or not agent_token:
            return {"ok": False, "message": "Shell agent is not configured"}
        result = ShellAgentClient(agent_url, agent_token).exec(command, timeout=45)
        if result.get("blocked"):
            return {"ok": False, "message": result.get("message") or "Command blocked by safety denylist"}
        stdout = str(result.get("stdout") or "").strip()
        stderr = str(result.get("stderr") or "").strip()
        pieces = [f"$ {command}", f"exit={result.get('exit_code', '?')}"]
        if stdout:
            pieces.append(stdout[:1500])
        if stderr:
            pieces.append(f"stderr: {stderr[:800]}")
        return {"ok": bool(result.get("ok")), "message": " | ".join(pieces) if result.get("exit_code") is not None else str(result.get("message") or "")}

    if action == "restart_plexmania_process":
        prefix, suffix = "plexmania-", "-down"
        if not (incident_key.startswith(prefix) and incident_key.endswith(suffix)):
            return {"ok": False, "message": "restart_plexmania_process is only valid for plexmania-* incidents"}
        app_name = incident_key[len(prefix):-len(suffix)]
        if app_name == "agent":
            return {"ok": False, "message": "The plexmania agent itself is unreachable — no in-app action can restart a specific process on a host it can't already talk to"}
        client, error = _plexmania_from_payload({})
        if error:
            return {"ok": False, "message": error.get("message", "plexmania agent not configured")}
        try:
            return client.restart(app_name)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    if action == "run_windows_command":
        if not command:
            return {"ok": False, "message": "No command was supplied"}
        if _shell_rate_limited(cfg):
            return {"ok": False, "message": "Global shell-action rate limit reached for this hour — skipped"}
        client, error = _plexmania_from_payload({})
        if error:
            return {"ok": False, "message": error.get("message", "plexmania agent not configured")}
        result = client.exec(command, timeout=45)
        if result.get("blocked"):
            return {"ok": False, "message": result.get("message") or "Command blocked by safety denylist"}
        stdout = str(result.get("stdout") or "").strip()
        stderr = str(result.get("stderr") or "").strip()
        pieces = [f"$ {command}", f"exit={result.get('exit_code', '?')}"]
        if stdout:
            pieces.append(stdout[:1500])
        if stderr:
            pieces.append(f"stderr: {stderr[:800]}")
        return {"ok": bool(result.get("ok")), "message": " | ".join(pieces) if result.get("exit_code") is not None else str(result.get("message") or "")}

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
    if category == "Media" and not incident_key.startswith("plexmania-"):
        allowed = {"none"}  # e.g. Sonarr/Radarr Docker containers - System category already covers these

    client = GeminiClient(api_key, str(cfg.get("ai_model") or "gemini-3.6-flash"))
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
    command = str(data.get("command") or "").strip()
    if action not in allowed:
        action = "none"
    if action != "run_command":
        command = ""
    combined_message = f"{explanation} ({reasoning})" if reasoning else explanation
    if command:
        combined_message = f"{combined_message} — proposed command: `{command}`"

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

    exec_result = _execute_action(action, incident_key, cfg, command=command)
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
