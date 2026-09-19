from __future__ import annotations

import re
from typing import Any

import requests

# Kept in sync by hand with shell-agent/app.py's _DENYLIST_PATTERNS - that
# service is a separate deployable unit so this can't just be imported from
# it. This copy is defense in depth (reject obviously catastrophic commands
# before even making the network call); the sidecar's own copy is the real
# enforcement boundary and must never be relied on being skippable.
DENYLIST_PATTERNS = [
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\s+[^\n]*of=/dev/",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
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
    r"\bcurl\b[^\n]*\|\s*(bash|sh)\b",
    r"\bwget\b[^\n]*\|\s*(bash|sh)\b",
]
_DENYLIST = [re.compile(p, re.IGNORECASE) for p in DENYLIST_PATTERNS]

# See shell-agent/app.py for why rm/chmod/chown-on-root need this two-part
# check instead of one regex - a flags-then-path pattern only catches one
# exact flag spelling and misses every equally-valid equivalent order/form.
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


def blocked_reason(command: str) -> str | None:
    if _is_rm_root(command):
        return "Command blocked by safety denylist (rm --recursive --force targeting filesystem root, in any flag spelling/order)"
    if _is_recursive_chmod_chown_root(command):
        return "Command blocked by safety denylist (recursive chmod/chown targeting filesystem root)"
    for pattern in _DENYLIST:
        if pattern.search(command):
            return f"Command blocked by safety denylist (matched pattern: {pattern.pattern})"
    return None


class ShellAgentClient:
    """Talks to the shell-agent sidecar, which holds the actual ability to run
    commands on the host (via nsenter, pid:host, privileged) - the main app
    never runs commands directly, only this scoped HTTP API, authenticated
    with a shared token. See shell-agent/app.py for the denylist that
    sidecar enforces regardless of what this client sends it."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()

    def _headers(self) -> dict[str, str]:
        return {"X-Agent-Token": self.token}

    def exec(self, command: str, timeout: int = 30) -> dict[str, Any]:
        if not self.base_url:
            return {"ok": False, "message": "Shell agent URL not configured"}
        if not self.token:
            return {"ok": False, "message": "Shell agent token not configured"}
        reason = blocked_reason(command)
        if reason:
            return {"ok": False, "blocked": True, "message": reason, "command": command}
        try:
            response = requests.post(
                f"{self.base_url}/exec",
                headers=self._headers(),
                json={"command": command, "timeout": timeout},
                timeout=timeout + 10,
            )
        except requests.RequestException as exc:
            return {"ok": False, "message": str(exc)}
        if not response.ok:
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = None
            return {"ok": False, "message": detail or f"HTTP {response.status_code}"}
        return response.json()

    def test_connection(self) -> dict[str, Any]:
        if not self.base_url:
            return {"ok": False, "message": "Enter the shell agent URL"}
        try:
            response = requests.get(f"{self.base_url}/health", timeout=10)
            response.raise_for_status()
            data = response.json()
            return {"ok": True, "message": f"Connected · host {data.get('host', '?')}"}
        except requests.RequestException as exc:
            return {"ok": False, "message": str(exc)}
