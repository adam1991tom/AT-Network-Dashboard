from __future__ import annotations

import hmac
import os
from concurrent.futures import ThreadPoolExecutor

import docker
from docker.errors import NotFound
from fastapi import Depends, FastAPI, Header, HTTPException

AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
HOST_LABEL = os.environ.get("AGENT_HOST_LABEL", "host")

app = FastAPI(title="AT Docker Agent")
client = docker.from_env()


def verify_token(x_agent_token: str | None = Header(default=None)) -> None:
    if not AGENT_TOKEN:
        raise HTTPException(status_code=503, detail="Agent token not configured")
    if not x_agent_token or not hmac.compare_digest(x_agent_token, AGENT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing agent token")


def _cpu_percent(stats: dict) -> float | None:
    try:
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        online_cpus = stats["cpu_stats"].get("online_cpus") or len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage") or [1])
        if system_delta > 0 and cpu_delta >= 0:
            return round((cpu_delta / system_delta) * online_cpus * 100, 1)
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return None


def _container_info(c) -> dict:
    info = {
        "id": c.short_id,
        "name": c.name,
        "image": (c.image.tags[0] if c.image and c.image.tags else (c.image.short_id if c.image else "")),
        "status": c.status,
        "cpu_percent": None,
        "mem_usage_mb": None,
        "mem_limit_mb": None,
    }
    if c.status == "running":
        try:
            stats = c.stats(stream=False)
            info["cpu_percent"] = _cpu_percent(stats)
            mem = stats.get("memory_stats") or {}
            usage = mem.get("usage")
            limit = mem.get("limit")
            if usage is not None:
                info["mem_usage_mb"] = round(usage / (1024 * 1024), 1)
            if limit:
                info["mem_limit_mb"] = round(limit / (1024 * 1024), 1)
        except Exception:
            pass
    return info


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "host": HOST_LABEL}


@app.get("/containers", dependencies=[Depends(verify_token)])
def list_containers() -> dict:
    containers = client.containers.list(all=True)
    # Each stats(stream=False) call takes ~1-2s (Docker samples twice
    # internally to compute deltas), so fetching them sequentially for a
    # host with 20+ containers can take the better part of a minute.
    # Fetching a container's own stats is independent I/O, so run them
    # concurrently instead.
    if not containers:
        return {"host": HOST_LABEL, "containers": []}
    with ThreadPoolExecutor(max_workers=min(16, len(containers))) as pool:
        results = list(pool.map(_container_info, containers))
    return {"host": HOST_LABEL, "containers": results}


def _get_container(container_id: str):
    try:
        return client.containers.get(container_id)
    except NotFound:
        raise HTTPException(status_code=404, detail="Container not found")


@app.post("/containers/{container_id}/start", dependencies=[Depends(verify_token)])
def start_container(container_id: str) -> dict:
    _get_container(container_id).start()
    return {"ok": True}


@app.post("/containers/{container_id}/stop", dependencies=[Depends(verify_token)])
def stop_container(container_id: str) -> dict:
    _get_container(container_id).stop(timeout=15)
    return {"ok": True}


@app.post("/containers/{container_id}/restart", dependencies=[Depends(verify_token)])
def restart_container(container_id: str) -> dict:
    _get_container(container_id).restart(timeout=15)
    return {"ok": True}
