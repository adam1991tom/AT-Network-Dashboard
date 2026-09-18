from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from app import remediation
from app.database import connect
from app.docker_routes import _HOSTS as _DOCKER_HOSTS
from app.docker_routes import _client_from_payload as _docker_client_from_payload
from app.docker_routes import _plexmania_from_payload
from app.integrations.gemini import GeminiClient
from app.integrations.shell_agent import ShellAgentClient
from app.integrations.unifi import UniFiClient
from app.monitoring import live_snapshot
from app.settings_store import all_settings, get_secret

# Actions the chat may execute directly (as opposed to only diagnosing), on
# top of what the automatic incident pipeline already does. Kept intentionally
# smaller than remediation.py's allow-list — restart_ap needs a device_id the
# chat has no reliable way to name from a Wi-Fi AP's display name alone, so
# it's left to the automatic pipeline for now.
_CHAT_ACTIONS = {"restart_container", "restart_plexmania_process", "restart_gateway", "run_command", "run_windows_command", "none"}


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _gemini_client() -> tuple[GeminiClient | None, dict[str, Any] | None]:
    cfg = all_settings()
    if not _bool(cfg.get("ai_enabled")):
        return None, {"ok": False, "message": "AI Assistant is disabled — enable it in Settings > Integrations first"}
    key = get_secret("gemini_api_key") or ""
    if not key:
        return None, {"ok": False, "message": "No Gemini API key configured in Settings > Integrations"}
    return GeminiClient(key, str(cfg.get("ai_model") or "gemini-3.6-flash")), None


def _gather_state() -> dict[str, Any]:
    con = connect()
    try:
        incidents = con.execute(
            "SELECT category,device,severity,summary,started_at FROM incidents WHERE active=1 ORDER BY started_at DESC LIMIT 20"
        ).fetchall()
        recent = con.execute(
            "SELECT ts,category,device,action,result_ok,source,explanation FROM remediation_actions ORDER BY id DESC LIMIT 15"
        ).fetchall()
    finally:
        con.close()

    all_containers: list[tuple[str, str, str]] = []  # (host, name, status)
    for host in _DOCKER_HOSTS:
        client, error = _docker_client_from_payload(host, {})
        if error:
            continue
        try:
            data = client.containers()
            for c in data.get("containers", []):
                all_containers.append((host, str(c.get("name")), str(c.get("status"))))
        except Exception:
            continue

    plexmania_processes: list[dict[str, Any]] = []
    plex_client, plex_error = _plexmania_from_payload({})
    if not plex_error:
        try:
            plexmania_processes = plex_client.processes().get("processes", [])
        except Exception:
            plexmania_processes = []

    snapshot = live_snapshot()
    gateway = snapshot.get("gateway") or {}
    ups = snapshot.get("ups") or {}

    lines = ["=== Active incidents ==="]
    for row in incidents:
        lines.append(f"- [{row['severity']}] {row['category']} / {row['device']}: {row['summary']} (since {row['started_at']})")
    if not incidents:
        lines.append("(none)")

    lines.append("\n=== Recent AI/auto-fix actions ===")
    for row in recent:
        status = "ok" if row["result_ok"] else "FAILED"
        lines.append(f"- {row['ts']} [{row['source']}] {row['category']}/{row['device']} {row['action']} ({status}): {row['explanation'] or ''}")
    if not recent:
        lines.append("(none)")

    lines.append("\n=== Docker containers (host/name: status) ===")
    lines.extend([f"{h}/{n}: {s}" for h, n, s in all_containers] or ["(none known, or Docker agents not configured)"])

    lines.append("\n=== plexmania (10.0.0.6) processes ===")
    lines.extend([f"{p.get('name')}: running={p.get('running')} port_open={p.get('port_open')}" for p in plexmania_processes] or ["(not configured or unreachable)"])

    lines.append("\n=== Live snapshot ===")
    lines.append(f"Gateway: wan_up={gateway.get('wan_up')} cpu={gateway.get('cpu')} memory={gateway.get('memory')} uptime_s={gateway.get('uptime')}")
    lines.append(f"UPS: status={ups.get('status')} load_pct={ups.get('load_pct')} connected={ups.get('connected')}")

    return {
        "text": "\n".join(lines),
        "containers": all_containers,
        "plexmania_processes": [str(p.get("name")) for p in plexmania_processes],
    }


def _current_state_summary() -> str:
    return _gather_state()["text"]


def _decide_prompt(message: str, state: dict[str, Any]) -> str:
    by_host: dict[str, list[str]] = {}
    for host, name, _status in state["containers"]:
        by_host.setdefault(host, []).append(name)
    containers_block = "\n".join(f'  host "{h}": ' + ", ".join(names) for h, names in by_host.items()) or "  (none)"
    plexmania = ", ".join(state["plexmania_processes"]) or "(none)"
    return (
        "You are the autonomous administrator for a home network/server monitoring dashboard, chatting directly "
        "with the owner (this is chat, not an automatic incident). Decide whether their message is asking you to "
        "take an action right now, or is just a question / wants information.\n\n"
        f"Current state:\n{state['text']}\n\n"
        f"Known Docker containers, grouped by host:\n{containers_block}\n"
        f"Known plexmania (10.0.0.6) processes (pick target from exactly these): {plexmania}\n\n"
        f"User message: {message}\n\n"
        "Respond with strict JSON only:\n"
        '{"intent": "<action or question>", '
        '"action": "<one of: restart_container, restart_plexmania_process, restart_gateway, run_command, run_windows_command, none>", '
        '"host": "<the host name (e.g. newtiny) - ONLY for restart_container, else empty>", '
        '"target": "<for restart_container: ONLY the container name, e.g. \\"uptime-kuma\\", never host/name combined. '
        'for restart_plexmania_process: the exact process name. Empty for other actions>", '
        '"command": "<exact command - shell command for run_command (runs on newtiny), PowerShell command for '
        'run_windows_command (runs on the plexmania Windows host), else empty>", '
        '"reasoning": "<one sentence>"}\n\n'
        "Rules: only set intent to \"action\" if the user is clearly asking you to fix/restart/run something now, not "
        "just describing a problem. target and host must be copied exactly from the lists above (as separate fields, "
        "never combined) — never invent a name. If nothing matches or you're unsure, use action \"none\" and intent "
        "\"question\"."
    )


def _normalize_host_target(host: str, target: str) -> tuple[str, str]:
    """The model is instructed to keep host/target separate, but if it still
    combines them as "host/name" or "host:name" (in either field), recover
    the two parts rather than sending a bogus combined string downstream."""
    for value in (target, host):
        for sep in ("/", ":"):
            if sep in value:
                maybe_host, _, maybe_name = value.partition(sep)
                if maybe_host in _DOCKER_HOSTS and maybe_name:
                    return maybe_host, maybe_name
    return host, target


def _execute_chat_action(action: str, host: str, target: str, command: str, cfg: dict[str, Any]) -> dict[str, Any]:
    if action == "restart_container":
        host, target = _normalize_host_target(host, target)
        if host not in _DOCKER_HOSTS or not target:
            return {"ok": False, "message": "Could not identify which container/host to restart"}
        client, error = _docker_client_from_payload(host, {})
        if error:
            return {"ok": False, "message": error.get("message", "Docker agent not configured")}
        try:
            return client.restart(target)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    if action == "restart_plexmania_process":
        if not target:
            return {"ok": False, "message": "Could not identify which process to restart"}
        client, error = _plexmania_from_payload({})
        if error:
            return {"ok": False, "message": error.get("message", "plexmania agent not configured")}
        try:
            return client.restart(target)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    if action == "restart_gateway":
        api_key = get_secret("unifi_api_key") or ""
        url = str(cfg.get("unifi_url", "")).strip()
        if not remediation._bool(cfg.get("unifi_enabled")) or not api_key or not url:
            return {"ok": False, "message": "UniFi integration is not configured"}
        client = UniFiClient(url, api_key, remediation._bool(cfg.get("unifi_verify_ssl")))
        try:
            snapshot = client.snapshot()
            mac = str((snapshot.get("gateway") or {}).get("mac") or "")
        except Exception as exc:
            return {"ok": False, "message": f"Could not look up gateway MAC: {exc}"}
        if not mac:
            return {"ok": False, "message": "Gateway MAC not available from UniFi snapshot"}
        return client.restart_gateway(mac)

    if action == "run_command":
        if not command:
            return {"ok": False, "message": "No command was supplied"}
        if remediation._shell_rate_limited(cfg):
            return {"ok": False, "message": "Global shell-action rate limit reached for this hour — try again later"}
        if not remediation._bool(cfg.get("shell_agent_enabled")):
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
        return {"ok": bool(result.get("ok")), "message": " | ".join(pieces)}

    if action == "run_windows_command":
        if not command:
            return {"ok": False, "message": "No command was supplied"}
        if remediation._shell_rate_limited(cfg):
            return {"ok": False, "message": "Global shell-action rate limit reached for this hour — try again later"}
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
        return {"ok": bool(result.get("ok")), "message": " | ".join(pieces)}

    return {"ok": False, "message": f"Unknown action '{action}'"}


def chat(message: str) -> dict[str, Any]:
    client, error = _gemini_client()
    if error:
        return error
    message = (message or "").strip()
    if not message:
        return {"ok": False, "message": "Enter a question"}

    cfg = all_settings()
    state = _gather_state()
    can_act = remediation._bool(cfg.get("auto_remediation_enabled")) and remediation._bool(cfg.get("ai_autonomous_enabled")) and not remediation._bool(cfg.get("maintenance_mode"))

    reply_text: str
    if can_act:
        decision = client.diagnose_incident(_decide_prompt(message, state))
        data = decision.get("data") if decision.get("ok") else {}
        action = str((data or {}).get("action") or "none").strip()
        if action not in _CHAT_ACTIONS:
            action = "none"
        intent = str((data or {}).get("intent") or "question").strip()
        if intent == "action" and action != "none":
            host = str((data or {}).get("host") or "").strip()
            target = str((data or {}).get("target") or "").strip()
            command = str((data or {}).get("command") or "").strip()
            reasoning = str((data or {}).get("reasoning") or "").strip()
            if action == "restart_container":
                host, target = _normalize_host_target(host, target)
            exec_result = _execute_chat_action(action, host, target, command, cfg)
            outcome = "succeeded" if exec_result.get("ok") else "failed"
            device = target or host or "-"
            remediation._log(
                f"chat:{action}:{device}", "Chat", device, action, bool(exec_result.get("ok")),
                str(exec_result.get("message") or ""), source="ai-chat", explanation=reasoning,
            )
            reply_text = f"{'Done' if exec_result.get('ok') else 'Tried, but it failed'} — {action.replace('_', ' ')} on {device} {outcome}.\n\n{exec_result.get('message') or ''}".strip()
        else:
            no_action_reason = str((data or {}).get("reasoning") or "").strip() or "no matching action/target was found for this message"
            answer = client.chat(_qa_prompt(message, state["text"], no_action_reason))
            if not answer.get("ok"):
                return answer
            reply_text = answer["text"]
    else:
        answer = client.chat(_qa_prompt(message, state["text"], "autonomous actions are currently switched off in Settings"))
        if not answer.get("ok"):
            return answer
        reply_text = answer["text"]
        if any(word in message.lower() for word in ("fix", "restart", "run ", "reboot")):
            reply_text += "\n\n(Autonomous actions are currently off in Settings > AI & Automation — I can only diagnose, not act, until that's turned on.)"

    con = connect()
    try:
        con.execute("INSERT INTO ai_chat_log(role,message) VALUES ('user',?)", (message,))
        con.execute("INSERT INTO ai_chat_log(role,message) VALUES ('assistant',?)", (reply_text,))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "reply": reply_text}


def _qa_prompt(message: str, state_text: str, no_action_taken_reason: str) -> str:
    return (
        "You are the AI administrator embedded in a home network/server monitoring dashboard called AT Network "
        "Dashboard. Answer the user's message using the current state below plus general troubleshooting knowledge. "
        "Be concise and specific.\n\n"
        "IMPORTANT: no action is being executed as part of this reply "
        f"({no_action_taken_reason}). Never write as if you are currently performing, initiating, or have just "
        "completed an action (e.g. never say \"restarting now\" or \"I've restarted it\") — if the user asked for "
        "something to be done, explain plainly that it wasn't done and why (e.g. the target couldn't be identified, "
        "the host is unreachable, or autonomous actions are off), and what they can do instead. Only ever describe "
        "actions the automatic incident pipeline actually already logged (visible in the state below) as having "
        "happened.\n\n"
        f"Current system state:\n{state_text}\n\nUser message: {message}\n"
    )


def chat_history(limit: int = 50) -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute(
            "SELECT id,ts,role,message FROM ai_chat_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        con.close()


def generate_report(hours: int = 24) -> dict[str, Any]:
    client, error = _gemini_client()
    if error:
        return error
    hours = max(1, min(int(hours or 24), 24 * 30))
    con = connect()
    try:
        incidents = con.execute(
            "SELECT category,device,severity,summary,started_at,ended_at,active FROM incidents WHERE datetime(started_at) >= datetime('now', ?) ORDER BY started_at DESC",
            (f"-{hours} hours",),
        ).fetchall()
        actions = con.execute(
            "SELECT ts,category,device,action,result_ok,source,explanation FROM remediation_actions WHERE datetime(ts) >= datetime('now', ?) ORDER BY ts DESC",
            (f"-{hours} hours",),
        ).fetchall()
    finally:
        con.close()

    if not incidents and not actions:
        text = f"No incidents or AI/auto-fix actions in the last {hours} hours — everything was quiet."
    else:
        lines = [f"Incidents in the last {hours}h ({len(incidents)}):"]
        for row in incidents:
            state = "ACTIVE" if row["active"] else "resolved"
            tail = f", ended {row['ended_at']}" if row["ended_at"] else ""
            lines.append(f"- [{row['severity']}] {row['category']}/{row['device']} ({state}): {row['summary']} — started {row['started_at']}{tail}")
        lines.append(f"\nActions taken in the last {hours}h ({len(actions)}):")
        for row in actions:
            status = "succeeded" if row["result_ok"] else "FAILED"
            lines.append(f"- {row['ts']} [{row['source']}] {row['category']}/{row['device']} {row['action']} {status}: {row['explanation'] or ''}")
        prompt = (
            "You are writing a short ops report for the owner of a home network/server monitoring dashboard, covering "
            f"the last {hours} hours. Summarize what happened in plain English: what broke, what fixed itself, what "
            "the AI diagnosed and/or did, and anything that still needs the owner's attention. Be concise (roughly "
            "150-300 words), use short paragraphs or bullet points, and don't just restate every log line verbatim.\n\n"
            + "\n".join(lines)
        )
        result = client.chat(prompt, max_tokens=1200)
        if not result.get("ok"):
            return result
        text = result["text"]

    con = connect()
    try:
        con.execute("INSERT INTO ai_reports(window_hours,report_text,report_type) VALUES (?,?,'incident_summary')", (hours, text))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "report": text}


def _gather_trends(hours: int) -> str:
    con = connect()
    try:
        wifi_rows = con.execute(
            "SELECT ap_name,band,AVG(retries) avg_retries,MAX(retries) max_retries,AVG(utilization) avg_util,AVG(clients) avg_clients "
            "FROM wifi_history WHERE datetime(ts) >= datetime('now', ?) GROUP BY ap_name,band ORDER BY max_retries DESC",
            (f"-{hours} hours",),
        ).fetchall()
        speed_row = con.execute(
            "SELECT AVG(download) avg_down,MIN(download) min_down,AVG(upload) avg_up,AVG(latency) avg_latency,COUNT(*) n "
            "FROM speedtest_history WHERE datetime(ts) >= datetime('now', ?)",
            (f"-{hours} hours",),
        ).fetchone()
        gw_row = con.execute(
            "SELECT AVG(cpu) avg_cpu,MAX(cpu) max_cpu,AVG(memory) avg_mem,MAX(memory) max_mem,AVG(temperature) avg_temp,"
            "SUM(rx_errors+tx_errors+rx_dropped+tx_dropped) total_errors FROM gateway_history WHERE datetime(ts) >= datetime('now', ?)",
            (f"-{hours} hours",),
        ).fetchone()
        resolved_incident_count = con.execute(
            "SELECT COUNT(*) FROM incidents WHERE active=0 AND datetime(started_at) >= datetime('now', ?)", (f"-{hours} hours",)
        ).fetchone()[0]
    finally:
        con.close()

    lines = [f"=== Wi-Fi trend by AP/band over the last {hours}h ==="]
    for row in wifi_rows:
        lines.append(
            f"- {row['ap_name']} {row['band']}: avg retries {row['avg_retries']:.1f}%, peak {row['max_retries']:.1f}%, "
            f"avg utilisation {row['avg_util']:.0f}%, avg clients {row['avg_clients']:.1f}"
        )
    if not wifi_rows:
        lines.append("(no Wi-Fi samples in this window)")

    lines.append("\n=== ISP speed trend ===")
    if speed_row and speed_row["n"]:
        lines.append(
            f"Avg download {speed_row['avg_down']:.0f} Mbps, worst {speed_row['min_down']:.0f} Mbps, "
            f"avg upload {speed_row['avg_up']:.0f} Mbps, avg latency {speed_row['avg_latency']:.0f} ms, over {speed_row['n']} tests"
        )
    else:
        lines.append("(no speed tests in this window)")

    lines.append("\n=== Gateway trend ===")
    if gw_row and gw_row["avg_cpu"] is not None:
        lines.append(
            f"Avg CPU {gw_row['avg_cpu']:.0f}% (peak {gw_row['max_cpu']:.0f}%), avg memory {gw_row['avg_mem']:.0f}% (peak {gw_row['max_mem']:.0f}%), "
            f"avg temperature {gw_row['avg_temp']:.0f}°C, total interface errors/drops {int(gw_row['total_errors'] or 0)}"
        )
    else:
        lines.append("(no gateway samples in this window)")

    lines.append(f"\n=== Incidents that resolved on their own or were auto-fixed in this window: {resolved_incident_count} ===")
    return "\n".join(lines)


def generate_network_health_report(hours: int = 168) -> dict[str, Any]:
    client, error = _gemini_client()
    if error:
        return error
    hours = max(24, min(int(hours or 168), 24 * 90))
    trends = _gather_trends(hours)
    prompt = (
        "You are a network engineer reviewing trend data for a home network, covering the last "
        f"{hours} hours, to proactively spot problems before they become incidents — not just reacting to alerts. "
        "Look for things like: an AP/band with persistently high retries or utilisation (candidate for a channel or "
        "channel-width change, or repositioning), a speed trend that's degrading, or a gateway resource trending "
        "toward its limit. Write a short, specific report (150-300 words) with concrete recommendations where "
        "something stands out — if everything genuinely looks healthy, say so briefly rather than inventing "
        "concerns.\n\n" + trends
    )
    result = client.chat(prompt, max_tokens=1200)
    if not result.get("ok"):
        return result
    text = result["text"]
    con = connect()
    try:
        con.execute("INSERT INTO ai_reports(window_hours,report_text,report_type) VALUES (?,?,'network_health')", (hours, text))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "report": text}


def recent_reports(limit: int = 20) -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute(
            "SELECT id,ts,window_hours,report_text,report_type FROM ai_reports ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


_health_worker_started = False
_health_worker_lock = threading.Lock()
HEALTH_CHECK_INTERVAL_SECONDS = 3600  # hourly check for whether a day has passed


def _health_report_due(cfg: dict[str, Any]) -> bool:
    if not remediation._bool(cfg.get("network_health_report_enabled")):
        return False
    con = connect()
    try:
        row = con.execute("SELECT ts FROM ai_reports WHERE report_type='network_health' ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        con.close()
    if not row:
        return True
    try:
        last = datetime.fromisoformat(str(row["ts"]))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - last).total_seconds() >= 86400


def _health_worker() -> None:
    while True:
        try:
            if _health_report_due(all_settings()):
                generate_network_health_report(168)
        except Exception as exc:
            print(f"ai_center: health report check failed: {exc}")
        time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)


def start_health_report_scheduler() -> None:
    global _health_worker_started
    with _health_worker_lock:
        if _health_worker_started:
            return
        threading.Thread(target=_health_worker, name="at-health-report-scheduler", daemon=True).start()
        _health_worker_started = True
