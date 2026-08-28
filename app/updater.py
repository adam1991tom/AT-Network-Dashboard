from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import requests

DATA_DIR = Path("/data")
STATE_FILE = DATA_DIR / "update-state.json"
REQUEST_FILE = DATA_DIR / "update-request.json"
PREVIOUS_FILE = DATA_DIR / "update-previous.txt"
REPO = "adam1991tom/AT-Network-Dashboard"


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def update_state() -> dict[str, Any]:
    data = _read_json(STATE_FILE, {"status": "idle", "message": "No update has been run yet"})
    data["rollback_available"] = PREVIOUS_FILE.exists() and bool(PREVIOUS_FILE.read_text(encoding="utf-8").strip())
    return data


def _same_version(a: str, b: str) -> bool:
    return a.strip().lstrip("vV") == b.strip().lstrip("vV")


def check_updates(current_version: str, channel: str) -> dict[str, Any]:
    channel = "beta" if str(channel).lower() == "beta" else "stable"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        if channel == "stable":
            r = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=10, headers=headers)
            if r.status_code == 404:
                return {"ok": True, "channel": channel, "current": current_version, "available": False, "message": "No stable GitHub release has been published yet"}
            r.raise_for_status()
            data = r.json()
            target = str(data.get("tag_name") or "").strip()
            notes = str(data.get("body") or "")[:8000]
            return {"ok": True, "channel": channel, "current": current_version, "latest": target, "available": bool(target and not _same_version(target, current_version)), "notes": notes, "published_at": data.get("published_at")}

        commit_r = requests.get(f"https://api.github.com/repos/{REPO}/commits/main", timeout=10, headers=headers)
        commit_r.raise_for_status()
        commit = commit_r.json()
        target = str(commit.get("sha") or "")
        message = str(((commit.get("commit") or {}).get("message") or "")).splitlines()[0]

        version_r = requests.get(f"https://api.github.com/repos/{REPO}/contents/VERSION?ref=main", timeout=10, headers=headers)
        version_r.raise_for_status()
        version_data = version_r.json()
        latest_version = ""
        encoded = str(version_data.get("content") or "").replace("\n", "")
        if encoded:
            latest_version = base64.b64decode(encoded).decode("utf-8").strip()
        return {"ok": True, "channel": channel, "current": current_version, "latest": latest_version or target[:12], "target": target, "available": bool(target and (not latest_version or not _same_version(latest_version, current_version))), "notes": message}
    except Exception as exc:
        return {"ok": False, "channel": channel, "current": current_version, "available": False, "message": str(exc)}


def request_update(channel: str, target: str | None = None) -> dict[str, Any]:
    channel = "beta" if str(channel).lower() == "beta" else "stable"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"channel": channel, "target": target or "", "requested": True}
    REQUEST_FILE.write_text(json.dumps(payload), encoding="utf-8")
    STATE_FILE.write_text(json.dumps({"status":"queued","message":f"{channel.title()} update queued","channel":channel}), encoding="utf-8")
    return {"ok": True, "status": "queued", "message": "Update request queued. The updater service will apply it and restart the dashboard."}


def request_rollback() -> dict[str, Any]:
    if not PREVIOUS_FILE.exists() or not PREVIOUS_FILE.read_text(encoding="utf-8").strip():
        return {"ok": False, "message": "No previous version is available to roll back to"}
    REQUEST_FILE.write_text(json.dumps({"channel":"rollback","target":"","requested":True}), encoding="utf-8")
    STATE_FILE.write_text(json.dumps({"status":"queued","message":"Rollback queued","channel":"rollback"}), encoding="utf-8")
    return {"ok": True, "status":"queued", "message":"Rollback request queued"}
