from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.integrations.arr import ArrClient, ProwlarrClient
from app.integrations.ersatztv import ErsatzTvClient
from app.integrations.nexroll import NexrollClient
from app.integrations.plex import PlexClient
from app.integrations.sabnzbd import SabnzbdClient
from app.integrations.tautulli import TautulliClient
from app.settings_store import all_settings, get_secret
from app.version import APP_VERSION

router = APIRouter(tags=["media"])
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"]))
VERSION = APP_VERSION


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _sonarr_from_payload(payload: dict):
    cfg = all_settings(); url = str(payload.get("sonarr_url") or cfg.get("sonarr_url") or "").strip(); key = str(payload.get("sonarr_api_key") or "").strip() or (get_secret("sonarr_api_key") or "")
    if not url: return None, {"ok": False, "message": "Enter the Sonarr URL"}
    if not key: return None, {"ok": False, "message": "Enter the Sonarr API key"}
    return ArrClient(url, key, "v3"), None


def _radarr_from_payload(payload: dict):
    cfg = all_settings(); url = str(payload.get("radarr_url") or cfg.get("radarr_url") or "").strip(); key = str(payload.get("radarr_api_key") or "").strip() or (get_secret("radarr_api_key") or "")
    if not url: return None, {"ok": False, "message": "Enter the Radarr URL"}
    if not key: return None, {"ok": False, "message": "Enter the Radarr API key"}
    return ArrClient(url, key, "v3"), None


def _prowlarr_from_payload(payload: dict):
    cfg = all_settings(); url = str(payload.get("prowlarr_url") or cfg.get("prowlarr_url") or "").strip(); key = str(payload.get("prowlarr_api_key") or "").strip() or (get_secret("prowlarr_api_key") or "")
    if not url: return None, {"ok": False, "message": "Enter the Prowlarr URL"}
    if not key: return None, {"ok": False, "message": "Enter the Prowlarr API key"}
    return ProwlarrClient(url, key), None


def _sabnzbd_from_payload(payload: dict):
    cfg = all_settings(); url = str(payload.get("sabnzbd_url") or cfg.get("sabnzbd_url") or "").strip(); key = str(payload.get("sabnzbd_api_key") or "").strip() or (get_secret("sabnzbd_api_key") or "")
    if not url: return None, {"ok": False, "message": "Enter the SABnzbd URL"}
    if not key: return None, {"ok": False, "message": "Enter the SABnzbd API key"}
    return SabnzbdClient(url, key), None


def _tautulli_from_payload(payload: dict):
    cfg = all_settings(); url = str(payload.get("tautulli_url") or cfg.get("tautulli_url") or "").strip(); key = str(payload.get("tautulli_api_key") or "").strip() or (get_secret("tautulli_api_key") or "")
    if not url: return None, {"ok": False, "message": "Enter the Tautulli URL"}
    if not key: return None, {"ok": False, "message": "Enter the Tautulli API key"}
    return TautulliClient(url, key), None


def _plex_from_payload(payload: dict):
    cfg = all_settings(); url = str(payload.get("plex_url") or cfg.get("plex_url") or "").strip(); token = str(payload.get("plex_token") or "").strip() or (get_secret("plex_token") or "")
    if not url: return None, {"ok": False, "message": "Enter the Plex server URL"}
    if not token: return None, {"ok": False, "message": "Enter the Plex token"}
    return PlexClient(url, token), None


def _ersatztv_from_payload(payload: dict):
    cfg = all_settings(); url = str(payload.get("ersatztv_url") or cfg.get("ersatztv_url") or "").strip()
    if not url: return None, {"ok": False, "message": "Enter the ErsatzTV URL"}
    return ErsatzTvClient(url), None


def _nexroll_from_payload(payload: dict):
    cfg = all_settings(); url = str(payload.get("nexroll_url") or cfg.get("nexroll_url") or "").strip(); key = str(payload.get("nexroll_api_key") or "").strip() or (get_secret("nexroll_api_key") or "")
    if not url: return None, {"ok": False, "message": "Enter the NeXroll URL"}
    if not key: return None, {"ok": False, "message": "Enter the NeXroll API key"}
    return NexrollClient(url, key), None


_SERVICES = {
    "sonarr": _sonarr_from_payload,
    "radarr": _radarr_from_payload,
    "prowlarr": _prowlarr_from_payload,
    "sabnzbd": _sabnzbd_from_payload,
    "tautulli": _tautulli_from_payload,
    "plex": _plex_from_payload,
    "ersatztv": _ersatztv_from_payload,
    "nexroll": _nexroll_from_payload,
}


def _make_test_route(name: str, builder):
    async def handler(request: Request) -> dict:
        payload = await request.json()
        client, error = builder(payload)
        return error or client.test_connection()
    return handler


for _name, _builder in _SERVICES.items():
    router.add_api_route(f"/api/settings/test/{_name}", _make_test_route(_name, _builder), methods=["POST"])


@router.get("/api/media/summary")
def media_summary() -> dict:
    cfg = all_settings()
    out: dict[str, dict] = {}
    for name, builder in _SERVICES.items():
        enabled = _bool(cfg.get(f"{name}_enabled"), False)
        if not enabled:
            out[name] = {"ok": False, "enabled": False, "message": f"{name.title()} integration is disabled"}
            continue
        client, error = builder({})
        if error:
            out[name] = {**error, "enabled": True}
            continue
        try:
            out[name] = {**client.summary(), "enabled": True}
        except Exception as exc:
            out[name] = {"ok": False, "enabled": True, "message": str(exc)}
    return out


@router.get("/media", response_class=HTMLResponse)
def media_page(request: Request):
    return HTMLResponse(templates.get_template("media.html").render(request=request, version=VERSION, title="Media", page="media"))
