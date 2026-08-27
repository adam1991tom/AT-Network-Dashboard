from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import CONFIG
from app.database import DB_PATH, connect, initialise
from app.integrations.discord import DiscordNotifier
from app.integrations.nut import NutPiHttpClient
from app.integrations.unifi import UniFiClient
from app.monitoring import start_monitoring
from app.monitoring_routes import router as monitoring_router
from app.settings_store import (
    all_settings,
    encryption_status,
    get_secret,
    set_secret,
    set_settings,
)


VERSION = "2.0.0-dev5"
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AT Network Dashboard", version=VERSION)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(monitoring_router)

templates = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _ping(target: str) -> dict:
    target = target.strip()
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


@app.on_event("startup")
def startup() -> None:
    initialise()
    start_monitoring()


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
    set_settings({"setup_complete": "true"})
    return {"ok": True, "settings": all_settings()}


@app.post("/api/settings/test/unifi")
async def api_test_unifi(request: Request) -> dict:
    payload = await request.json()
    url = str(payload.get("unifi_url", "")).strip()
    api_key = str(payload.get("unifi_api_key", "")).strip() or (get_secret("unifi_api_key") or "")
    verify_ssl = _bool(payload.get("unifi_verify_ssl"), False)
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
    return {"ok": False, "message": "Direct NUT support is not connected yet"}


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
    return _ping(str(payload.get("ping_target", "")))


@app.get("/api/network-changes")
def api_network_changes() -> dict:
    con = connect()
    try:
        rows = con.execute(
            "SELECT id, ts, category, summary, details FROM network_changes ORDER BY id DESC LIMIT 25"
        ).fetchall()
        return {"items": [dict(row) for row in rows]}
    finally:
        con.close()


@app.post("/api/network-changes")
async def api_add_network_change(request: Request) -> dict:
    payload = await request.json()
    category = str(payload.get("category", "General")).strip() or "General"
    summary = str(payload.get("summary", "")).strip()
    details = str(payload.get("details", "")).strip()
    if not summary:
        return {"ok": False, "message": "Enter a summary of the change"}
    con = connect()
    try:
        cur = con.execute(
            "INSERT INTO network_changes(category, summary, details) VALUES (?, ?, ?)",
            (category, summary, details),
        )
        con.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        con.close()


@app.get("/api/system/info")
def api_system_info() -> dict:
    enc = encryption_status()
    return {
        "version": VERSION,
        "environment": CONFIG.environment,
        "database": str(DB_PATH),
        "database_exists": DB_PATH.exists(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "hostname": platform.node(),
        "encryption": enc,
    }


@app.get("/api/dashboard/summary")
def api_dashboard_summary() -> dict:
    cfg = all_settings()
    summary: dict[str, object] = {
        "version": VERSION,
        "setup_complete": _bool(cfg.get("setup_complete")),
        "internet": {"enabled": _bool(cfg.get("isp_enabled")), "ok": None},
        "unifi": {"enabled": _bool(cfg.get("unifi_enabled")), "ok": None},
        "ups": {"enabled": _bool(cfg.get("ups_enabled")), "ok": None},
        "wifi": {"enabled": _bool(cfg.get("unifi_enabled")), "ok": None},
    }
    if summary["internet"]["enabled"]:  # type: ignore[index]
        ping = _ping(str(cfg.get("ping_target", "1.1.1.1")))
        summary["internet"] = {
            "enabled": True,
            "ok": ping.get("ok", False),
            "target": cfg.get("ping_target", "1.1.1.1"),
            "provider": cfg.get("isp_provider", ""),
        }
    if summary["unifi"]["enabled"]:  # type: ignore[index]
        key = get_secret("unifi_api_key") or ""
        url = str(cfg.get("unifi_url", ""))
        if key and url:
            test = UniFiClient(url, key, _bool(cfg.get("unifi_verify_ssl"))).test_connection()
            summary["unifi"] = {"enabled": True, **test}
            summary["wifi"] = {"enabled": True, "ok": test.get("ok", False)}
        else:
            summary["unifi"] = {"enabled": True, "ok": False, "message": "Configuration required"}
            summary["wifi"] = {"enabled": True, "ok": False}
    if summary["ups"]["enabled"]:  # type: ignore[index]
        if str(cfg.get("ups_type", "nutpi_http")) == "nutpi_http":
            test = NutPiHttpClient(
                str(cfg.get("ups_host", "")),
                str(cfg.get("nutpi_status_path", "/api/nutpi/status.cgi")),
            ).test_connection()
            summary["ups"] = {"enabled": True, **test}
        else:
            summary["ups"] = {"enabled": True, "ok": False, "message": "Direct NUT not connected"}
    return summary


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return HTMLResponse(
        templates.get_template("dashboard.html").render(
            request=request, version=VERSION, page="dashboard", title="Dashboard"
        )
    )


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request) -> HTMLResponse:
    return HTMLResponse(
        templates.get_template("settings.html").render(
            request=request, version=VERSION, page="settings", title="Settings"
        )
    )
