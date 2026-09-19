from __future__ import annotations

import re

import requests

# Kept in sync by hand with plexmania-agent/agent.ps1's $DenylistPatterns -
# that script is a separate deployable unit (runs on the Windows host, not in
# this codebase's Python process) so this can't just be imported from it.
# This copy is defense in depth (reject obviously catastrophic commands
# before even making the network call); the agent's own copy on the Windows
# host is the real enforcement boundary.
DENYLIST_PATTERNS = [
    r"Format-Volume",
    r"Clear-Disk",
    r"\bdiskpart\b",
    r"\bsdelete\b",
    r"cipher\s+/w",
    r"Stop-Computer",
    r"Restart-Computer",
    r"shutdown(\.exe)?\s+/[rs]\b",
    r"Set-MpPreference\s+.*-DisableRealtimeMonitoring",
    r"netsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off",
    r"reg(\.exe)?\s+delete\s+HKLM\\SAM",
    r"net(\.exe)?\s+user\s+administrator",
    r"(iwr|Invoke-WebRequest)\b.*\|\s*(iex|Invoke-Expression)\b",
    r"wevtutil\s+cl\b",
    r"vssadmin\s+delete\s+shadows",
]
_DENYLIST = [re.compile(p, re.IGNORECASE) for p in DENYLIST_PATTERNS]

# A single "flags-then-path" regex only catches one exact spelling and misses
# equally-valid equivalents (PowerShell parameters can come before or after
# the path). Check root-targeting and -Recurse independently instead.
_ROOT_TARGET_REMOVE_ITEM = re.compile(r"Remove-Item\b[^\n;]*?(?:^|\s)[A-Za-z]:\\?(?:\s|;|$)", re.IGNORECASE)
_RECURSE_FLAG = re.compile(r"-Recurse\b", re.IGNORECASE)


def _is_recursive_remove_root(command: str) -> bool:
    return bool(_ROOT_TARGET_REMOVE_ITEM.search(command)) and bool(_RECURSE_FLAG.search(command))


def blocked_reason(command: str) -> str | None:
    if _is_recursive_remove_root(command):
        return "Command blocked by safety denylist (Remove-Item -Recurse targeting a drive root, regardless of parameter order)"
    for pattern in _DENYLIST:
        if pattern.search(command):
            return f"Command blocked by safety denylist (matched pattern: {pattern.pattern})"
    return None


class PlexmaniaAgentClient:
    """Talks to the plexmania-agent PowerShell HTTP listener (see
    plexmania-agent/agent.ps1). No Docker on that host - Plex, ErsatzTV and
    NeXroll run as bare Windows processes, so this offers process
    status + restart instead of container start/stop/restart, but uses the
    same shared-token auth shape as DockerAgentClient."""

    def __init__(self, base_url: str, token: str):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()

    def _headers(self) -> dict:
        return {"X-Agent-Token": self.token}

    def processes(self, timeout: int = 10) -> dict:
        if not self.base_url:
            raise ValueError("Enter the agent URL")
        if not self.token:
            raise ValueError("Enter the agent token")
        response = requests.get(f"{self.base_url}/processes", headers=self._headers(), timeout=timeout)
        response.raise_for_status()
        return response.json()

    def restart(self, name: str, timeout: int = 40) -> dict:
        if not self.base_url:
            raise ValueError("Enter the agent URL")
        if not self.token:
            raise ValueError("Enter the agent token")
        response = requests.post(f"{self.base_url}/processes/{name}/restart", headers=self._headers(), timeout=timeout)
        response.raise_for_status()
        return response.json()

    def exec(self, command: str, timeout: int = 30) -> dict:
        """Runs a PowerShell command on the plexmania host via agent.ps1's
        /exec endpoint (same denylist-protected contract as the Linux
        shell-agent: ok/blocked/command/exit_code/stdout/stderr)."""
        if not self.base_url:
            return {"ok": False, "message": "Enter the agent URL"}
        if not self.token:
            return {"ok": False, "message": "Enter the agent token"}
        reason = blocked_reason(command)
        if reason:
            return {"ok": False, "blocked": True, "message": reason, "command": command}
        try:
            response = requests.post(
                f"{self.base_url}/exec", headers=self._headers(),
                json={"command": command, "timeout": timeout}, timeout=timeout + 10,
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

    def test_connection(self) -> dict:
        try:
            data = self.processes()
            return {"ok": True, "message": f"Connected · {len(data.get('processes', []))} apps on {data.get('host', '')}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
