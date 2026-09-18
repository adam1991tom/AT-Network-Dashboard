from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.database import connect, write_transaction
from app.integrations.gemini import GeminiClient
from app.integrations.shell_agent import ShellAgentClient
from app.remediation import _bool, _log
from app.settings_store import all_settings, get_secret, set_settings

CHECK_INTERVAL_SECONDS = 300  # 5 minutes - this is a slow background poll, not a tight loop
STALE_RUN_TIMEOUT_SECONDS = 3 * 3600  # a run with no "completed" marker after this long is presumed dead

_worker_started = False
_worker_lock = threading.Lock()


def _shell_client(cfg: dict[str, Any]) -> ShellAgentClient | None:
    if not _bool(cfg.get("shell_agent_enabled")):
        return None
    url = str(cfg.get("shell_agent_url") or "").strip()
    token = get_secret("shell_agent_token") or ""
    if not url or not token:
        return None
    return ShellAgentClient(url, token)


def _due_for_scheduled_run(cfg: dict[str, Any]) -> bool:
    if not _bool(cfg.get("maintenance_schedule_enabled")):
        return False
    last = str(cfg.get("maintenance_last_run_at") or "").strip()
    if not last:
        return True
    days = max(1, int(float(cfg.get("maintenance_schedule_days") or 7)))
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - last_dt).total_seconds() >= days * 86400


def _active_run(con) -> dict[str, Any] | None:
    row = con.execute("SELECT * FROM maintenance_runs WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def _launch(client: ShellAgentClient, script_path: str) -> dict[str, Any]:
    """Checks no run is already active, then launches - and only records a
    "running" row if the launch command actually succeeded. A blocked/failed
    launch must not leave a fake "running" row behind (previously it did,
    and that row would then sit looking like a real stuck run for up to
    STALE_RUN_TIMEOUT_SECONDS before self-clearing).

    The exec() network call deliberately happens outside any DB transaction -
    it can take up to its 15s timeout, and holding SQLite's write lock for
    that long would block every other writer (the 30s monitoring loop
    included). That leaves a small check-then-launch race against a
    concurrent call (scheduler vs. manual "Run Now"); the underlying script's
    own flock prevents it from actually running twice, so the only visible
    effect would be a harmless duplicate "running" row that the poll loop
    resolves like any other.
    """
    con = connect()
    try:
        if _active_run(con):
            return {"ok": False, "message": "A maintenance run is already in progress"}
    finally:
        con.close()

    launch_cmd = f"nohup {script_path} > /dev/null 2>&1 & disown"
    result = client.exec(launch_cmd, timeout=15)
    if result.get("blocked") or not result.get("ok"):
        return {"ok": False, "message": result.get("message") or "Launch command failed", "blocked": result.get("blocked", False)}

    def op(con) -> None:
        con.execute("INSERT INTO maintenance_runs(started_at,status) VALUES (?,?)", (datetime.now(timezone.utc).isoformat(), "running"))

    write_transaction(op)
    return {"ok": True}


def _summarize(cfg: dict[str, Any], log_text: str) -> str:
    key = get_secret("gemini_api_key") or ""
    if not _bool(cfg.get("ai_enabled")) or not key:
        return ""
    client = GeminiClient(key, str(cfg.get("ai_model") or "gemini-3.6-flash"))
    prompt = (
        "You are summarizing a home server's automated OS + Docker maintenance run for its owner. Summarize what "
        "happened in plain English, under 150 words: what was updated, any errors or warnings worth knowing about, "
        "whether a reboot is now required, and anything the owner should personally look at. Do not just restate the "
        "log verbatim.\n\nRaw log (tail):\n\n" + log_text[-8000:]
    )
    result = client.chat(prompt, max_tokens=700)
    return result.get("text", "") if result.get("ok") else ""


def _poll_active_run(client: ShellAgentClient, cfg: dict[str, Any], con, run: dict[str, Any]) -> None:
    tail = client.exec("tail -n 15 /var/log/server-maintenance.log 2>/dev/null || true", timeout=15)
    output = str(tail.get("stdout") or "")
    if "Maintenance completed" not in output:
        started = datetime.fromisoformat(run["started_at"])
        if (datetime.now(timezone.utc) - started).total_seconds() > STALE_RUN_TIMEOUT_SECONDS:
            con.execute("UPDATE maintenance_runs SET status='timeout', finished_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), run["id"]))
            con.commit()
            _log(f"maintenance:{run['id']}", "System", "newtiny", "scheduled_maintenance", False, "No completion marker seen within the timeout window — the run may have stalled or the log rotated.", source="schedule")
        return

    full = client.exec("tail -c 20000 /var/log/server-maintenance.log 2>/dev/null || true", timeout=20)
    log_text = str(full.get("stdout") or "")[-16000:]
    finished_at = datetime.now(timezone.utc).isoformat()
    summary = _summarize(cfg, log_text)
    con.execute(
        "UPDATE maintenance_runs SET status='completed', finished_at=?, log_excerpt=?, ai_summary=? WHERE id=?",
        (finished_at, log_text, summary, run["id"]),
    )
    con.commit()
    set_settings({"maintenance_last_run_at": finished_at})
    reboot_needed = "reboot is required" in output.lower()
    message = summary or "Scheduled maintenance completed."
    if reboot_needed:
        message += " A reboot is required but was not performed automatically."
    _log(f"maintenance:{run['id']}", "System", "newtiny", "scheduled_maintenance", True, message, source="schedule", explanation=summary)


def check_once() -> None:
    cfg = all_settings()
    client = _shell_client(cfg)
    if not client:
        return
    con = connect()
    try:
        run = _active_run(con)
    finally:
        con.close()
    if run:
        con = connect()
        try:
            _poll_active_run(client, cfg, con, run)
        finally:
            con.close()
    elif _due_for_scheduled_run(cfg):
        script_path = str(cfg.get("maintenance_script_path") or "/home/adam/smart_maintenance.sh").strip()
        _launch(client, script_path)


def _worker() -> None:
    while True:
        try:
            check_once()
        except Exception as exc:
            print(f"maintenance: check failed: {exc}")
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_maintenance_scheduler() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker, name="at-maintenance-scheduler", daemon=True).start()
        _worker_started = True


def run_now() -> dict[str, Any]:
    cfg = all_settings()
    client = _shell_client(cfg)
    if not client:
        return {"ok": False, "message": "Shell agent is not enabled/configured — required to run maintenance"}
    script_path = str(cfg.get("maintenance_script_path") or "/home/adam/smart_maintenance.sh").strip()
    result = _launch(client, script_path)
    if not result.get("ok"):
        return result
    return {"ok": True, "message": "Maintenance run launched — check back in a few minutes for the summary."}


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    con = connect()
    try:
        rows = con.execute(
            "SELECT id,started_at,finished_at,status,ai_summary FROM maintenance_runs ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
