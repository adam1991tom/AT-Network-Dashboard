from __future__ import annotations

import hmac
import platform
import secrets
import subprocess
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.auth import COOKIE_NAME, change_password, create_admin, has_admin, login, logout, session_user
from app.config import CONFIG
from app.database import DB_PATH, initialise
from app.dev14_routes import router as dev14_router
from app.integrations.discord import DiscordNotifier
from app.integrations.nut import NutPiHttpClient
from app.integrations.unifi import UniFiClient
from app.integrations.uptime_kuma import UptimeKumaClient
from app.integrations.whatsapp import WhatsAppNotifier
from app.remediation import recent_actions
from app.docker_routes import router as docker_router
from app.media_routes import router as media_router
from app.infra_monitoring import start_infra_monitoring
from app.monitoring_v23 import start_monitoring
from app.monitoring_routes import router as monitoring_router
from app.security import is_locked, record_failure, reset as reset_login_attempts
from app.services import network_changes, unifi_import
from app.settings_store import SECRET_KEYS, all_settings, encryption_status, get_secret, set_secret, set_settings
from app.updater import check_updates, request_update, update_state
from app.version import APP_VERSION

VERSION = APP_VERSION
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AT Network Dashboard", version=VERSION)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(monitoring_router)
app.include_router(dev14_router)
app.include_router(media_router)
app.include_router(docker_router)
templates = Environment(loader=FileSystemLoader(BASE_DIR / "templates"), autoescape=select_autoescape(["html", "xml"]))

def _bool(value: object, default: bool = False) -> bool:
    if value is None: return default
    return str(value).lower() in {"1", "true", "yes", "on"}

def _ping(target: str) -> dict:
    target = target.strip()
    if not target: return {"ok": False, "message": "Enter a ping target"}
    try: result = subprocess.run(["ping", "-c", "3", "-W", "2", target], capture_output=True, text=True, timeout=10, check=False)
    except Exception as exc: return {"ok": False, "message": str(exc)}
    return {"ok": result.returncode == 0, "message": "Ping successful" if result.returncode == 0 else "Ping failed", "output": (result.stdout or result.stderr)[-1500:]}

def _unifi_from_payload(payload: dict) -> tuple[UniFiClient | None, dict | None]:
    cfg=all_settings(); url=str(payload.get("unifi_url") or cfg.get("unifi_url") or "").strip(); api_key=str(payload.get("unifi_api_key") or "").strip() or (get_secret("unifi_api_key") or ""); verify_ssl=_bool(payload.get("unifi_verify_ssl",cfg.get("unifi_verify_ssl")),False)
    if not url:return None,{"ok":False,"message":"Enter or save a UniFi gateway/controller URL"}
    if not api_key:return None,{"ok":False,"message":"Enter or save a UniFi API key"}
    return UniFiClient(url,api_key,verify_ssl),None

def _kuma_from_payload(payload: dict) -> tuple[UptimeKumaClient | None, dict | None]:
    cfg=all_settings(); url=str(payload.get("uptime_kuma_url") or cfg.get("uptime_kuma_url") or "").strip(); slug=str(payload.get("uptime_kuma_status_slug") or cfg.get("uptime_kuma_status_slug") or "").strip(); key=str(payload.get("uptime_kuma_api_key") or "").strip() or (get_secret("uptime_kuma_api_key") or ""); verify=_bool(payload.get("uptime_kuma_verify_ssl",cfg.get("uptime_kuma_verify_ssl")),False)
    if not url:return None,{"ok":False,"message":"Enter the Uptime Kuma URL / IP"}
    if not slug:return None,{"ok":False,"message":"Enter the Uptime Kuma status-page slug"}
    return UptimeKumaClient(url,slug,key,verify),None

@app.on_event("startup")
def startup() -> None: initialise(); start_monitoring(); start_infra_monitoring()

CSRF_COOKIE_NAME = "at_csrf"
_CSRF_EXEMPT_PATHS = {"/api/health", "/login", "/setup-admin"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True  # not all clients send Origin; treated as defense-in-depth only
    try:
        allowed_host = request.url.netloc
        origin_host = origin.split("://", 1)[-1]
        return origin_host == allowed_host
    except Exception:
        return False


@app.middleware("http")
async def authentication(request: Request, call_next):
    path=request.url.path; public=path.startswith("/static/") or path in {"/api/health","/login","/setup-admin"}
    if public:
        response=await call_next(request)
        if path.startswith("/static/"):
            response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0";response.headers["Pragma"]="no-cache";response.headers["Expires"]="0"
        return response
    if not has_admin():
        if path.startswith("/api/"):return JSONResponse({"detail":"Administrator setup required"},status_code=401)
        return RedirectResponse("/setup-admin",status_code=303)
    user=session_user(request.cookies.get(COOKIE_NAME))
    if not user:
        if path.startswith("/api/"):return JSONResponse({"detail":"Authentication required"},status_code=401)
        return RedirectResponse("/login",status_code=303)
    if request.method not in _SAFE_METHODS and path not in _CSRF_EXEMPT_PATHS:
        if not _origin_allowed(request):
            return JSONResponse({"detail":"Origin not allowed"},status_code=403)
        cookie_token=request.cookies.get(CSRF_COOKIE_NAME)
        header_token=request.headers.get("x-csrf-token")
        if not cookie_token or not header_token or not hmac.compare_digest(cookie_token,header_token):
            return JSONResponse({"detail":"CSRF token missing or invalid"},status_code=403)
    request.state.user=user; return await call_next(request)

@app.get("/api/health")
def api_health()->dict:return {"status":"ok","version":VERSION,"environment":CONFIG.environment,"database":str(DB_PATH)}
@app.get("/setup-admin",response_class=HTMLResponse)
def setup_admin_page(request:Request):
    if has_admin():return RedirectResponse("/login",status_code=303)
    return HTMLResponse(templates.get_template("setup-admin.html").render(request=request,version=VERSION))
@app.post("/setup-admin")
async def setup_admin(request:Request):
    if has_admin():return JSONResponse({"ok":False,"message":"Administrator already exists"},status_code=409)
    data=await request.json();ok,message=create_admin(str(data.get("username","")),str(data.get("password","")))
    if not ok:return JSONResponse({"ok":False,"message":message},status_code=400)
    return {"ok":True,"message":message}
@app.get("/login",response_class=HTMLResponse)
def login_page(request:Request):
    if not has_admin():return RedirectResponse("/setup-admin",status_code=303)
    if session_user(request.cookies.get(COOKIE_NAME)):return RedirectResponse("/dashboard",status_code=303)
    return HTMLResponse(templates.get_template("login.html").render(request=request,version=VERSION))
@app.post("/login")
async def login_api(request:Request):
    data=await request.json();username=str(data.get("username",""));ip=request.client.host if request.client else "unknown"
    if is_locked(ip,username):
        return JSONResponse({"ok":False,"message":"Too many attempts. Try again later."},status_code=429)
    cfg=all_settings();token=login(username,str(data.get("password","")),int(float(cfg.get("session_hours") or 8)))
    if not token:
        record_failure(ip,username)
        return JSONResponse({"ok":False,"message":"Invalid username or password"},status_code=401)
    reset_login_attempts(ip,username)
    max_age=int(float(cfg.get("session_hours") or 8))*3600
    response=JSONResponse({"ok":True})
    response.set_cookie(COOKIE_NAME,token,httponly=True,samesite="lax",secure=CONFIG.force_https,max_age=max_age)
    response.set_cookie(CSRF_COOKIE_NAME,secrets.token_urlsafe(32),httponly=False,samesite="lax",secure=CONFIG.force_https,max_age=max_age)
    return response
@app.post("/logout")
def logout_api(request:Request):logout(request.cookies.get(COOKIE_NAME));response=JSONResponse({"ok":True});response.delete_cookie(COOKIE_NAME);response.delete_cookie(CSRF_COOKIE_NAME);return response
@app.post("/api/security/change-password")
async def api_change_password(request:Request):
    data=await request.json();ok,message=change_password(int(request.state.user["id"]),str(data.get("current_password","")),str(data.get("new_password","")))
    if not ok:return JSONResponse({"ok":False,"message":message},status_code=400)
    response=JSONResponse({"ok":True,"message":message});response.delete_cookie(COOKIE_NAME);return response

@app.get("/api/settings")
def api_settings()->dict:return all_settings()
@app.post("/api/settings")
async def api_save_settings(request:Request)->dict:
    payload=await request.json();set_settings(payload)
    for key in SECRET_KEYS:
        if str(payload.get(key,"")).strip():set_secret(key,str(payload[key]).strip())
    set_settings({"setup_complete":"true"});return {"ok":True,"settings":all_settings()}
@app.post("/api/settings/test/unifi")
async def api_test_unifi(request:Request)->dict:payload=await request.json();client,error=_unifi_from_payload(payload);return error or client.test_connection()
@app.post("/api/settings/test/uptime-kuma")
async def api_test_uptime_kuma(request:Request)->dict:payload=await request.json();client,error=_kuma_from_payload(payload);return error or client.test_connection()
@app.get("/api/uptime-kuma/summary")
def api_uptime_kuma_summary()->dict:
    cfg=all_settings()
    if not _bool(cfg.get("uptime_kuma_enabled"),False):return {"ok":False,"enabled":False,"message":"Uptime Kuma integration is disabled"}
    client,error=_kuma_from_payload({})
    if error:return {**error,"enabled":True}
    try:return {**client.snapshot(),"enabled":True,"open_url":str(cfg.get("uptime_kuma_url") or "").rstrip("/")}
    except Exception as exc:return {"ok":False,"enabled":True,"message":str(exc),"open_url":str(cfg.get("uptime_kuma_url") or "").rstrip("/")}
@app.post("/api/settings/test/speedtest")
async def api_test_speedtest(request:Request)->dict:payload=await request.json();client,error=_unifi_from_payload(payload);return error or client.run_speedtest()
@app.post("/api/settings/test/unifi-history")
async def api_test_unifi_history(request:Request)->dict:
    payload=await request.json();client,error=_unifi_from_payload(payload)
    if error:return error
    try:days=int(payload.get("history_probe_days",365))
    except Exception:days=365
    return client.history_probe(days)
@app.post("/api/settings/import/unifi-history")
async def api_import_unifi_history(request:Request)->dict:
    payload=await request.json();client,error=_unifi_from_payload(payload)
    if error:return error
    try:days=int(payload.get("history_probe_days",365))
    except Exception:days=365
    return unifi_import.import_retained_history(client,days)
@app.post("/api/settings/test/ups")
async def api_test_ups(request:Request)->dict:
    payload=await request.json();host=str(payload.get("ups_host","")).strip();path=str(payload.get("nutpi_status_path","/api/nutpi/status.cgi")).strip()
    if not host:return {"ok":False,"message":"Enter the UPS/NUT host or IP address"}
    return NutPiHttpClient(host,path).test_connection()
@app.post("/api/settings/test/discord")
async def api_test_discord(request:Request)->dict:
    payload=await request.json();webhook=str(payload.get("discord_webhook","")).strip() or (get_secret("discord_webhook") or "")
    if not webhook:return {"ok":False,"message":"Enter or save a Discord webhook"}
    return DiscordNotifier(webhook).send("✅ AT Network Dashboard test notification")
@app.post("/api/settings/test/whatsapp")
async def api_test_whatsapp(request:Request)->dict:
    payload=await request.json();cfg=all_settings()
    base_url=str(payload.get("whatsapp_base_url") or cfg.get("whatsapp_base_url") or "").strip()
    session_id=str(payload.get("whatsapp_session_id") or cfg.get("whatsapp_session_id") or "").strip()
    chat_id=str(payload.get("whatsapp_chat_id") or cfg.get("whatsapp_chat_id") or "").strip()
    api_key=str(payload.get("whatsapp_api_key") or "").strip() or (get_secret("whatsapp_api_key") or "")
    if not base_url:return {"ok":False,"message":"Enter your OpenWA server URL"}
    if not session_id:return {"ok":False,"message":"Enter the OpenWA session ID"}
    if not chat_id:return {"ok":False,"message":"Enter the WhatsApp recipient (e.g. 447123456789@c.us)"}
    return WhatsAppNotifier(base_url,api_key,session_id,chat_id).send("✅ AT Network Dashboard test notification")
@app.get("/api/remediation-actions")
def api_remediation_actions()->dict:return {"items":recent_actions(100)}
@app.post("/api/settings/test/ping")
async def api_test_ping(request:Request)->dict:payload=await request.json();return _ping(str(payload.get("ping_target","")))
@app.get("/api/network-changes")
def api_network_changes()->dict:return network_changes.list_recent()
@app.post("/api/network-changes")
async def api_add_network_change(request:Request)->dict:
    p=await request.json();return network_changes.add(str(p.get("category","General")),str(p.get("summary","")),str(p.get("details","")))
@app.get("/api/system/info")
def api_system_info()->dict:return {"version":VERSION,"environment":CONFIG.environment,"database":str(DB_PATH),"database_exists":DB_PATH.exists(),"python":platform.python_version(),"platform":platform.system(),"hostname":platform.node(),"encryption":encryption_status(),"authentication":True}
@app.get("/api/system/update/check")
def api_update_check(channel:str="stable")->dict:return check_updates(VERSION,channel)
@app.get("/api/system/update/state")
def api_update_state()->dict:return update_state()
@app.post("/api/system/update/apply")
async def api_update_apply(request:Request)->dict:data=await request.json();return request_update(str(data.get("channel","stable")),str(data.get("target") or ""))
@app.get("/",response_class=HTMLResponse)
@app.get("/dashboard",response_class=HTMLResponse)
def dashboard(request:Request)->HTMLResponse:return HTMLResponse(templates.get_template("dashboard.html").render(request=request,version=VERSION,page="dashboard",title="Dashboard"))
@app.get("/settings",response_class=HTMLResponse)
def settings(request:Request)->HTMLResponse:return HTMLResponse(templates.get_template("settings.html").render(request=request,version=VERSION,page="settings",title="Settings"))
