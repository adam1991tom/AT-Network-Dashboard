from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.integrations.docker_agent import DockerAgentClient
from app.integrations.plexmania_agent import PlexmaniaAgentClient
from app.settings_store import all_settings, get_secret
from app.version import APP_VERSION

router = APIRouter(tags=["docker"])
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"]))
VERSION = APP_VERSION

_HOSTS = ("newtiny", "beast")


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _client_from_payload(host: str, payload: dict):
    if host not in _HOSTS:
        return None, {"ok": False, "message": f"Unknown host {host}"}
    cfg = all_settings()
    url = str(payload.get(f"docker_agent_{host}_url") or cfg.get(f"docker_agent_{host}_url") or "").strip()
    token = str(payload.get(f"docker_agent_{host}_token") or "").strip() or (get_secret(f"docker_agent_{host}_token") or "")
    if not url:
        return None, {"ok": False, "message": f"Enter the {host} agent URL"}
    if not token:
        return None, {"ok": False, "message": f"Enter the {host} agent token"}
    return DockerAgentClient(url, token), None


def _make_test_route(host: str):
    async def handler(request: Request) -> dict:
        payload = await request.json()
        client, error = _client_from_payload(host, payload)
        return error or client.test_connection()
    return handler


for _host in _HOSTS:
    router.add_api_route(f"/api/settings/test/docker-agent-{_host}", _make_test_route(_host), methods=["POST"])


def _plexmania_from_payload(payload: dict):
    cfg = all_settings()
    url = str(payload.get("plexmania_agent_url") or cfg.get("plexmania_agent_url") or "").strip()
    token = str(payload.get("plexmania_agent_token") or "").strip() or (get_secret("plexmania_agent_token") or "")
    if not url:
        return None, {"ok": False, "message": "Enter the plexmania agent URL"}
    if not token:
        return None, {"ok": False, "message": "Enter the plexmania agent token"}
    return PlexmaniaAgentClient(url, token), None


async def _plexmania_test_route(request: Request) -> dict:
    payload = await request.json()
    client, error = _plexmania_from_payload(payload)
    return error or client.test_connection()


router.add_api_route("/api/settings/test/plexmania-agent", _plexmania_test_route, methods=["POST"])


@router.get("/api/docker/summary")
def docker_summary() -> dict:
    cfg = all_settings()
    out: dict[str, dict] = {}
    for host in _HOSTS:
        enabled = _bool(cfg.get(f"docker_agent_{host}_enabled"), False)
        if not enabled:
            out[host] = {"ok": False, "enabled": False, "message": f"Docker agent on {host} is disabled", "containers": []}
            continue
        client, error = _client_from_payload(host, {})
        if error:
            out[host] = {**error, "enabled": True, "containers": []}
            continue
        try:
            data = client.containers()
            out[host] = {"ok": True, "enabled": True, "containers": data.get("containers", [])}
        except Exception as exc:
            out[host] = {"ok": False, "enabled": True, "message": str(exc), "containers": []}

    enabled = _bool(cfg.get("plexmania_agent_enabled"), False)
    if not enabled:
        out["plexmania"] = {"ok": False, "enabled": False, "message": "Plexmania agent is disabled", "processes": []}
    else:
        client, error = _plexmania_from_payload({})
        if error:
            out["plexmania"] = {**error, "enabled": True, "processes": []}
        else:
            try:
                data = client.processes()
                out["plexmania"] = {"ok": True, "enabled": True, "processes": data.get("processes", [])}
            except Exception as exc:
                out["plexmania"] = {"ok": False, "enabled": True, "message": str(exc), "processes": []}
    return out


@router.post("/api/docker/{host}/containers/{container_id}/{action}")
def docker_action(host: str, container_id: str, action: str) -> JSONResponse:
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=400, detail="Unknown action")
    client, error = _client_from_payload(host, {})
    if error:
        return JSONResponse(error, status_code=400)
    try:
        result = getattr(client, action)(container_id)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)


@router.post("/api/plexmania/processes/{name}/restart")
def plexmania_restart(name: str) -> JSONResponse:
    client, error = _plexmania_from_payload({})
    if error:
        return JSONResponse(error, status_code=400)
    try:
        result = client.restart(name)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=502)


@router.get("/docker", response_class=HTMLResponse)
def docker_page(request: Request):
    return HTMLResponse(templates.get_template("docker.html").render(request=request, version=VERSION, title="Docker", page="docker"))
