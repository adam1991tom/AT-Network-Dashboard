from __future__ import annotations

from typing import Any

from app.database import connect
from app.docker_routes import _HOSTS as _DOCKER_HOSTS
from app.docker_routes import _client_from_payload as _docker_client_from_payload
from app.integrations.gemini import GeminiClient
from app.monitoring import live_snapshot
from app.settings_store import all_settings, get_secret


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


def _current_state_summary() -> str:
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

    containers_summary: list[str] = []
    for host in _DOCKER_HOSTS:
        client, error = _docker_client_from_payload(host, {})
        if error:
            continue
        try:
            data = client.containers()
            for c in data.get("containers", []):
                if c.get("status") != "running":
                    containers_summary.append(f"{host}/{c.get('name')}: {c.get('status')}")
        except Exception:
            continue

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

    lines.append("\n=== Non-running Docker containers ===")
    lines.extend(containers_summary or ["(none known, or Docker agents not configured)"])

    lines.append("\n=== Live snapshot ===")
    lines.append(f"Gateway: wan_up={gateway.get('wan_up')} cpu={gateway.get('cpu')} memory={gateway.get('memory')} uptime_s={gateway.get('uptime')}")
    lines.append(f"UPS: status={ups.get('status')} load_pct={ups.get('load_pct')} connected={ups.get('connected')}")
    return "\n".join(lines)


def chat(message: str) -> dict[str, Any]:
    client, error = _gemini_client()
    if error:
        return error
    message = (message or "").strip()
    if not message:
        return {"ok": False, "message": "Enter a question"}
    context = _current_state_summary()
    prompt = (
        "You are the AI administrator embedded in a home network/server monitoring dashboard called AT Network "
        "Dashboard. Answer the user's question using the current state below plus general troubleshooting knowledge. "
        "Be concise and specific. This chat cannot directly execute commands itself — autonomous fixes happen "
        "automatically through the incident pipeline when enabled in Settings, so if asked to 'do' something, explain "
        "what will happen automatically (if anything) and point to the Incidents or Settings page rather than "
        "pretending to have taken an action.\n\n"
        f"Current system state:\n{context}\n\nQuestion: {message}\n"
    )
    result = client.chat(prompt)
    if not result.get("ok"):
        return result
    con = connect()
    try:
        con.execute("INSERT INTO ai_chat_log(role,message) VALUES ('user',?)", (message,))
        con.execute("INSERT INTO ai_chat_log(role,message) VALUES ('assistant',?)", (result["text"],))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "reply": result["text"]}


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
        con.execute("INSERT INTO ai_reports(window_hours,report_text) VALUES (?,?)", (hours, text))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "report": text}


def recent_reports(limit: int = 20) -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute(
            "SELECT id,ts,window_hours,report_text FROM ai_reports ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
