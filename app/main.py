from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import CONFIG
from app.database import DB_PATH, initialise
from app.integrations.discord import DiscordNotifier
from app.integrations.nut import NutPiHttpClient
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings, get_secret, set_secret, set_settings


VERSION = "2.0.0-dev3"
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="AT Network Dashboard",
    version=VERSION,
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


@app.on_event("startup")
def startup() -> None:
    initialise()


@app.get("/api/health")
def api_health() -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "environment": CONFIG.environment,
        "database": str(DB_PATH),
    }


@app.get("/api/settings")
def api_settings() -> dict:
    return all_settings()


@app.post("/api/settings")
async def api_save_settings(request: Request) -> dict:
    payload = await request.json()
    set_settings(payload)

    unifi_api_key = str(payload.get("unifi_api_key", "")).strip()
    discord_webhook = str(payload.get("discord_webhook", "")).strip()

    if unifi_api_key:
        set_secret("unifi_api_key", unifi_api_key)
    if discord_webhook:
        set_secret("discord_webhook", discord_webhook)

    return {
        "ok": True,
        "settings": all_settings(),
    }


@app.post("/api/settings/test/unifi")
async def api_test_unifi(request: Request) -> dict:
    payload = await request.json()
    url = str(payload.get("unifi_url", "")).strip()
    api_key = str(payload.get("unifi_api_key", "")).strip() or (get_secret("unifi_api_key") or "")
    verify_ssl = str(payload.get("unifi_verify_ssl", "false")).lower() == "true"

    if not url:
        return {"ok": False, "message": "Enter a UniFi gateway/controller URL"}
    if not api_key:
        return {"ok": False, "message": "Enter or save a UniFi API key"}

    return UniFiClient(url, api_key, verify_ssl).test_connection()


@app.post("/api/settings/test/ups")
async def api_test_ups(request: Request) -> dict:
    payload = await request.json()
    ups_type = str(payload.get("ups_type", "nutpi_http"))
    host = str(payload.get("ups_host", "")).strip()
    status_path = str(payload.get("nutpi_status_path", "/api/nutpi/status.cgi")).strip()

    if not host:
        return {"ok": False, "message": "Enter the UPS/NUT host or IP address"}

    if ups_type == "nutpi_http":
        return NutPiHttpClient(host, status_path).test_connection()

    return {
        "ok": False,
        "message": "Direct NUT testing is not connected yet; use NUTPI HTTP API for now",
    }


@app.post("/api/settings/test/discord")
async def api_test_discord(request: Request) -> dict:
    payload = await request.json()
    webhook = str(payload.get("discord_webhook", "")).strip() or (get_secret("discord_webhook") or "")
    if not webhook:
        return {"ok": False, "message": "Enter or save a Discord webhook"}
    return DiscordNotifier(webhook).send("✅ AT Network Dashboard v2 test notification")


@app.post("/api/settings/test/ping")
async def api_test_ping(request: Request) -> dict:
    payload = await request.json()
    target = str(payload.get("ping_target", "")).strip()
    if not target:
        return {"ok": False, "message": "Enter a ping target"}

    try:
        result = subprocess.run(
            ["ping", "-c", "3", "-W", "2", target],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "message": str(exc)}

    return {
        "ok": result.returncode == 0,
        "message": "Ping successful" if result.returncode == 0 else "Ping failed",
        "output": (result.stdout or result.stderr)[-1500:],
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    template = templates.get_template("dashboard.html")
    return HTMLResponse(
        template.render(
            request=request,
            version=VERSION,
            page="dashboard",
            title="Dashboard",
        )
    )


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request) -> HTMLResponse:
    template = templates.get_template("settings.html")
    return HTMLResponse(
        template.render(
            request=request,
            version=VERSION,
            page="settings",
            title="Settings",
        )
    )
