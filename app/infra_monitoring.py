from __future__ import annotations

import threading
import time
from typing import Any

from app.database import connect
from app.docker_routes import _HOSTS as DOCKER_HOSTS
from app.docker_routes import _client_from_payload as _docker_client_from_payload
from app.docker_routes import _plexmania_from_payload
from app.media_routes import _SERVICES as MEDIA_SERVICES
from app.monitoring import _set_incident
from app.settings_store import all_settings

# Separate, slower loop from the main 30s monitoring.collect_once: the 11
# services here (8 media integrations + 2 docker agents + plexmania) are all
# external HTTP calls, several across the LAN to other hosts. Folding them
# into the tight core loop would mean every collection cycle waits on
# whichever of them is slowest to respond (or times out).
CHECK_INTERVAL_SECONDS = 120

_worker_started = False
_worker_lock = threading.Lock()


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _check_media(con, cfg: dict[str, Any]) -> None:
    for name, builder in MEDIA_SERVICES.items():
        if not _bool(cfg.get(f"{name}_enabled"), False):
            continue
        client, error = builder({})
        if error:
            bad, detail = True, error.get("message", "")
        else:
            try:
                result = client.test_connection()
                bad, detail = not result.get("ok"), result.get("message", "")
            except Exception as exc:
                bad, detail = True, str(exc)
        label = name.title()
        _set_incident(con, cfg, f"media-{name}-down", bad, "warning", "Media", label, f"{label} unreachable", detail, 60, 60)


def _check_docker(con, cfg: dict[str, Any]) -> None:
    for host in DOCKER_HOSTS:
        if not _bool(cfg.get(f"docker_agent_{host}_enabled"), False):
            continue
        client, error = _docker_client_from_payload(host, {})
        if error:
            _set_incident(con, cfg, f"docker-agent-{host}-down", True, "warning", "System", host, f"Docker agent on {host} unreachable", error.get("message", ""), 60, 60)
            continue
        try:
            data = client.containers()
            _set_incident(con, cfg, f"docker-agent-{host}-down", False, "warning", "System", host, "", "", 60, 60)
            for c in data.get("containers", []):
                bad = c.get("status") in {"exited", "dead"}
                _set_incident(
                    con, cfg, f"docker-container-{host}-{c.get('name')}", bad, "warning", "System", str(c.get("name")),
                    f"Container {c.get('name')} on {host} is {c.get('status')}", f"status={c.get('status')}", 120, 60,
                )
        except Exception as exc:
            _set_incident(con, cfg, f"docker-agent-{host}-down", True, "warning", "System", host, f"Docker agent on {host} unreachable", str(exc), 60, 60)


def _check_plexmania(con, cfg: dict[str, Any]) -> None:
    if not _bool(cfg.get("plexmania_agent_enabled"), False):
        return
    client, error = _plexmania_from_payload({})
    if error:
        _set_incident(con, cfg, "plexmania-agent-down", True, "warning", "Media", "plexmania", "Plexmania agent unreachable", error.get("message", ""), 60, 60)
        return
    try:
        data = client.processes()
        _set_incident(con, cfg, "plexmania-agent-down", False, "warning", "Media", "plexmania", "", "", 60, 60)
        for p in data.get("processes", []):
            bad = not (p.get("running") and p.get("port_open"))
            name = str(p.get("name"))
            _set_incident(
                con, cfg, f"plexmania-{name}-down", bad, "warning", "Media", name,
                f"{name.title()} is down on plexmania", f"running={p.get('running')} port_open={p.get('port_open')}", 120, 60,
            )
    except Exception as exc:
        _set_incident(con, cfg, "plexmania-agent-down", True, "warning", "Media", "plexmania", "Plexmania agent unreachable", str(exc), 60, 60)


def check_once() -> None:
    cfg = all_settings()
    con = connect()
    try:
        _check_media(con, cfg)
        _check_docker(con, cfg)
        _check_plexmania(con, cfg)
        con.commit()
    finally:
        con.close()


def _worker() -> None:
    while True:
        try:
            check_once()
        except Exception as exc:
            print(f"infra_monitoring: check failed: {exc}")
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_infra_monitoring() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker, name="at-infra-monitor", daemon=True).start()
        _worker_started = True
