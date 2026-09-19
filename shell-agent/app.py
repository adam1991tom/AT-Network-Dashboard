from __future__ import annotations

import hmac
import os
import re
import subprocess
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
HOST_LABEL = os.environ.get("AGENT_HOST_LABEL", "host")

app = FastAPI(title="AT Shell Agent")

# Commands matching any of these are refused outright regardless of who or what
# asked for them. These all share the same shape: no legitimate "fix an
# incident" use case, and a catastrophic, usually irreversible blast radius
# (wiping the disk, bricking the host, locking out every admin account).
# Everything else is allowed to run — the audit log (every command, its
# output and exit code, returned to and stored by the caller) is the safety
# net for that, not a second layer of guessing what's "safe enough".
_DENYLIST_PATTERNS = [
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\s+[^\n]*of=/dev/",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",   # classic fork bomb
    r"\bwipefs\b",
    r"[>]\s*/dev/sd[a-z][0-9]*\b",
    r"[>]\s*/dev/nvme\d+n\d+",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\binit\s+0\b",
    r"\b(userdel|deluser)\b[^\n]*\broot\b",
    r"\bpasswd\s+root\b",
    r"[>]\s*/etc/passwd\b",
    r"[>]\s*/etc/shadow\b",
    r"\biptables\s+(-F|--flush)\b",
    r"\bufw\s+disable\b",
    r"\bcurl\b[^\n]*\|\s*(bash|sh)\b",   # piping a remote download straight into a shell
    r"\bwget\b[^\n]*\|\s*(bash|sh)\b",
]
_DENYLIST = [re.compile(p, re.IGNORECASE) for p in _DENYLIST_PATTERNS]

# rm/chmod/chown targeting the filesystem root need their own check rather
# than a single regex: a flags-then-path regex only catches one exact spelling
# (e.g. "-rf") and silently misses every equally-valid equivalent - separate
# short flags in either order ("-r -f"), long flags ("--recursive --force"),
# or a mix. This checks for a root-targeting invocation and a recursive *and*
# force-like flag appearing anywhere in it, independent of order or spelling.
_ROOT_TARGET_RM = re.compile(r"\brm\s+([^;&|\n]*?)(?:^|\s)/\*?(?:\s|;|&&|\|\||$)", re.IGNORECASE)
_ROOT_TARGET_CHOWN_CHMOD = re.compile(r"\b(chmod|chown)\s+([^;&|\n]*?)(?:^|\s)/(?:\s|;|&&|\|\||$)", re.IGNORECASE)
_RECURSIVE_FLAG = re.compile(r"(--recursive\b|-[a-zA-Z]*[rR][a-zA-Z]*\b)")
_FORCE_FLAG = re.compile(r"(--force\b|-[a-zA-Z]*f[a-zA-Z]*\b)")


def _is_rm_root(command: str) -> bool:
    for m in _ROOT_TARGET_RM.finditer(command):
        flags = m.group(1)
        if _RECURSIVE_FLAG.search(flags) and _FORCE_FLAG.search(flags):
            return True
    return False


def _is_recursive_chmod_chown_root(command: str) -> bool:
    for m in _ROOT_TARGET_CHOWN_CHMOD.finditer(command):
        flags = m.group(2)
        if _RECURSIVE_FLAG.search(flags):
            return True
    return False


class ExecRequest(BaseModel):
    command: str
    timeout: int = 30


def verify_token(x_agent_token: str | None = Header(default=None)) -> None:
    if not AGENT_TOKEN:
        raise HTTPException(status_code=503, detail="Agent token not configured")
    if not x_agent_token or not hmac.compare_digest(x_agent_token, AGENT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing agent token")


def blocked_reason(command: str) -> str | None:
    if _is_rm_root(command):
        return "Command blocked by safety denylist (rm --recursive --force targeting filesystem root, in any flag spelling/order)"
    if _is_recursive_chmod_chown_root(command):
        return "Command blocked by safety denylist (recursive chmod/chown targeting filesystem root)"
    for pattern in _DENYLIST:
        if pattern.search(command):
            return f"Command blocked by safety denylist (matched pattern: {pattern.pattern})"
    return None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "host": HOST_LABEL}


@app.post("/exec", dependencies=[Depends(verify_token)])
def exec_command(req: ExecRequest) -> dict:
    command = req.command.strip()
    if not command:
        raise HTTPException(status_code=400, detail="Empty command")
    reason = blocked_reason(command)
    if reason:
        return {"ok": False, "blocked": True, "message": reason, "command": command}

    timeout = max(1, min(int(req.timeout or 30), 120))
    # -t 1 joins PID 1's (the host init's) namespaces, so this genuinely runs
    # on the host, not inside this container - that's the whole point of the
    # container running pid:host + privileged.
    full_cmd = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "bash", "-lc", command]
    started = time.time()
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "blocked": False,
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-4000:],
            "elapsed_seconds": round(time.time() - started, 2),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "blocked": False, "command": command, "message": f"Command timed out after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "blocked": False, "command": command, "message": str(exc)}
