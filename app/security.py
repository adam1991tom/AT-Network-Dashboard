from __future__ import annotations
import time

# In-process sliding-window login throttle. Resets on container restart -
# acceptable for a single-instance deployment; not shared across replicas.
WINDOW_SECONDS = 900  # 15 minutes
MAX_ATTEMPTS_PER_KEY = 5  # per (ip, username)
MAX_ATTEMPTS_PER_IP = 20  # per ip, across all usernames - blunts distributed guessing

_by_key: dict[str, list[float]] = {}
_by_ip: dict[str, list[float]] = {}


def _prune(hist: list[float], now: float) -> list[float]:
    return [t for t in hist if now - t < WINDOW_SECONDS]


def is_locked(ip: str, username: str) -> bool:
    now = time.time()
    key = f"{ip}:{username.strip().lower()}"
    key_hist = _prune(_by_key.get(key, []), now)
    ip_hist = _prune(_by_ip.get(ip, []), now)
    _by_key[key] = key_hist
    _by_ip[ip] = ip_hist
    return len(key_hist) >= MAX_ATTEMPTS_PER_KEY or len(ip_hist) >= MAX_ATTEMPTS_PER_IP


def record_failure(ip: str, username: str) -> None:
    now = time.time()
    key = f"{ip}:{username.strip().lower()}"
    _by_key.setdefault(key, []).append(now)
    _by_ip.setdefault(ip, []).append(now)


def reset(ip: str, username: str) -> None:
    key = f"{ip}:{username.strip().lower()}"
    _by_key.pop(key, None)
    _by_ip.pop(ip, None)
