from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.auth import COOKIE_NAME, change_password, create_admin, has_admin, login, logout, session_user
from app.config import CONFIG
from app.database import DB_PATH, connect, initialise
from app.dev14_routes import router as dev14_router
from app.integrations.discord import DiscordNotifier
from app.integrations.nut import NutPiHttpClient
from app.integrations.unifi import UniFiClient
from app.monitoring_v23 import start_monitoring
from app.monitoring_routes import router as monitoring_router
from app.settings_store import all_settings, encryption_status, get_secret, set_secret, set_settings
from app.updater import check_updates, request_update, update_state

VERSION = "3.1.0"
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AT Network Dashboard", version=VERSION)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(monitoring_router)
app.include_router(dev14_router)
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

@app.on_event("startup")
def startup() -> None: initialise(); start_monitoring()

@app.middleware("http")
async def authentication(request: Request, call_next):
    path=request.url.path; public=path.startswith("/static/") or path in {"/api/health","/login","/setup-admin"}
    if public:
        response=await call_next(request)
        if path.startswith("/static/"):
            response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"]="no-cache"
            response.headers["Expires"]="0"
        return response
    if not has_admin():
        if path.startswith("/api/"):return JSONResponse({"detail":"Administrator setup required"},status_code=401)
        return RedirectResponse("/setup-admin",status_code=303)
    user=session_user(request.cookies.get(COOKIE_NAME))
    if not user:
        if path.startswith("/api/"):return JSONResponse({"detail":"Authentication required"},status_code=401)
        return RedirectResponse("/login",status_code=303)
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
    if not has_admin():return RedirectResponse("/login",status_code=303)
    if session_user(request.cookies.get(COOKIE_NAME)):return RedirectResponse("/dashboard",status_code=303)
    return HTMLResponse(templates.get_template("login.html").render(request=request,version=VERSION))
@app.post("/login")
async def login_api(request:Request):
    data=await request.json();cfg=all_settings();token=login(str(data.get("username","")),str(data.get("password","")),int(float(cfg.get("session_hours") or 8)))
    if not token:return JSONResponse({"ok":False,"message":"Invalid username or password"},status_code=401)
    response=JSONResponse({"ok":True});response.set_cookie(COOKIE_NAME,token,httponly=True,samesite="lax",secure=False,max_age=int(float(cfg.get("session_hours") or 8))*3600);return response
@app.post("/logout")
def logout_api(request:Request):logout(request.cookies.get(COOKIE_NAME));response=JSONResponse({"ok":True});response.delete_cookie(COOKIE_NAME);return response
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
    if str(payload.get("unifi_api_key","")).strip():set_secret("unifi_api_key",str(payload["unifi_api_key"]).strip())
    if str(payload.get("discord_webhook","")).strip():set_secret("discord_webhook",str(payload["discord_webhook"]).strip())
    set_settings({"setup_complete":"true"});return {"ok":True,"settings":all_settings()}
@app.post("/api/settings/test/unifi")
async def api_test_unifi(request:Request)->dict:payload=await request.json();client,error=_unifi_from_payload(payload);return error or client.test_connection()
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
    history=client.retained_history(days);inserted_wan=0;inserted_ap=0;con=connect()
    try:
        for source,rows in history.items():
            for row in rows:
                try:epoch_ms=int(float(row.get("time")))
                except Exception:continue
                ts=str(row.get("datetime") or "").strip()
                if not ts:continue
                if source=="ap_hourly":
                    device_id=str(row.get("ap") or row.get("oid") or "").strip()
                    if not device_id:continue
                    cur=con.execute("INSERT OR IGNORE INTO unifi_ap_traffic_history(ts,epoch_ms,device_id,clients,bytes,rx_bytes,tx_bytes) VALUES (?,?,?,?,?,?,?)",(ts,epoch_ms,device_id,row.get("num_sta"),row.get("bytes"),row.get("rx_bytes"),row.get("tx_bytes")));inserted_ap+=max(cur.rowcount,0)
                elif source in {"gateway_hourly","site_hourly","site_daily"}:
                    scope="gateway" if source=="gateway_hourly" else "site";bucket="daily" if source=="site_daily" else "hourly";object_id=str(row.get("gw") or row.get("site") or row.get("oid") or "").strip()
                    if not object_id:continue
                    cur=con.execute("INSERT OR IGNORE INTO unifi_wan_history(ts,epoch_ms,bucket,scope,object_id,clients,rx_bytes,tx_bytes) VALUES (?,?,?,?,?,?,?,?)",(ts,epoch_ms,bucket,scope,object_id,row.get("num_sta"),row.get("wan-rx_bytes"),row.get("wan-tx_bytes")));inserted_wan+=max(cur.rowcount,0)
        con.commit();totals={"wan":con.execute("SELECT COUNT(*) FROM unifi_wan_history").fetchone()[0],"ap":con.execute("SELECT COUNT(*) FROM unifi_ap_traffic_history").fetchone()[0]}
    finally:con.close()
    return {"ok":True,"message":f"Imported {inserted_wan+inserted_ap} new UniFi history records","inserted":{"wan":inserted_wan,"ap":inserted_ap},"totals":totals}
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
@app.post("/api/settings/test/ping")
async def api_test_ping(request:Request)->dict:payload=await request.json();return _ping(str(payload.get("ping_target","")))
@app.get("/api/network-changes")
def api_network_changes()->dict:
    con=connect()
    try:return {"items":[dict(r) for r in con.execute("SELECT id,ts,category,summary,details FROM network_changes ORDER BY id DESC LIMIT 25").fetchall()]}
    finally:con.close()
@app.post("/api/network-changes")
async def api_add_network_change(request:Request)->dict:
    p=await request.json();category=str(p.get("category","General")).strip() or "General";summary=str(p.get("summary","")).strip();details=str(p.get("details","")).strip()
    if not summary:return {"ok":False,"message":"Enter a summary of the change"}
    con=connect()
    try:cur=con.execute("INSERT INTO network_changes(category,summary,details) VALUES (?,?,?)",(category,summary,details));con.commit();return {"ok":True,"id":cur.lastrowid}
    finally:con.close()
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
