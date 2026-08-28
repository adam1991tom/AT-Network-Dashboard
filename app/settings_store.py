from __future__ import annotations

import threading
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from app.config import CONFIG
from app.database import connect, write_transaction

DEFAULT_SETTINGS: dict[str, str] = {
    "application_name":"AT Network Dashboard","application_subtitle":"Network · ISP · Wi-Fi · Power","timezone":"Europe/London","theme":"dark","accent":"green","default_range_hours":"24",
    "site_name":"","site_address":"",
    "isp_enabled":"true","isp_provider":"","isp_account_number":"","isp_service_reference":"","isp_support_phone":"","isp_support_url":"","isp_notes":"",
    "expected_download":"0","expected_upload":"0","warning_threshold":"0","major_threshold":"0","critical_threshold":"0","ping_target":"1.1.1.1","speedtest_auto_enabled":"true","speedtest_minutes":"15",
    "unifi_enabled":"false","unifi_url":"","unifi_verify_ssl":"false","ups_enabled":"false","ups_type":"nutpi_http","ups_host":"","ups_port":"3493","ups_name":"","nutpi_status_path":"/api/nutpi/status.cgi","ups_estimate_runtime_enabled":"true","ups_runtime_at_50_load_minutes":"20","ups_runtime_exponent":"1.15","discord_enabled":"false",
    "wifi_warning_threshold":"35","wifi_major_threshold":"40","wifi_critical_threshold":"50","wifi_persist_minutes":"10","wifi_recovery_threshold":"20","wifi_recovery_minutes":"10",
    "notify_internet":"true","notify_wifi":"true","notify_power":"true","notify_gateway":"true","notify_system":"true","notification_min_severity":"warning","notification_cooldown_minutes":"15",
    "maintenance_mode":"false","retention_days":"365","session_hours":"8","update_channel":"stable","auto_update_check":"true","notify_update_available":"true","setup_complete":"false",
}
SECRET_KEYS={"unifi_api_key","discord_webhook"}; INSTALL_KEY_PATH=Path("/data/install.key")
_defaults_ready=False
_defaults_lock=threading.Lock()

def ensure_defaults():
    global _defaults_ready
    if _defaults_ready:return
    with _defaults_lock:
        if _defaults_ready:return
        def op(con):
            for k,v in DEFAULT_SETTINGS.items():
                con.execute("INSERT OR IGNORE INTO settings(setting_key,setting_value) VALUES (?,?)",(k,v))
        write_transaction(op)
        _defaults_ready=True

def all_settings():
    ensure_defaults(); con=connect()
    try:
        result={r["setting_key"]:r["setting_value"] for r in con.execute("SELECT setting_key,setting_value FROM settings").fetchall()}
        for k in SECRET_KEYS: result[f"{k}_configured"]=bool(con.execute("SELECT 1 FROM secrets WHERE secret_key=?",(k,)).fetchone())
        return result
    finally: con.close()

def set_settings(values):
    allowed=set(DEFAULT_SETTINGS)
    def op(con):
        for k,v in values.items():
            if k in allowed:
                con.execute("INSERT INTO settings(setting_key,setting_value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP WHERE settings.setting_value<>excluded.setting_value",(k,str(v).lower() if isinstance(v,bool) else str(v)))
    write_transaction(op)

def _installation_key():
    configured=(CONFIG.master_key or "").strip()
    if configured and configured!="CHANGE_ME": return configured.encode()
    INSTALL_KEY_PATH.parent.mkdir(parents=True,exist_ok=True)
    if INSTALL_KEY_PATH.exists(): return INSTALL_KEY_PATH.read_text().strip().encode()
    key=Fernet.generate_key(); INSTALL_KEY_PATH.write_text(key.decode()); INSTALL_KEY_PATH.chmod(0o600); return key

def encryption_status():
    try:
        Fernet(_installation_key()); source="environment" if (CONFIG.master_key or "").strip() not in {"","CHANGE_ME"} else "installation key"; return {"ok":True,"source":source}
    except Exception as exc:return {"ok":False,"source":"unavailable","message":str(exc)}

def _cipher():return Fernet(_installation_key())
def set_secret(key,value):
    if key not in SECRET_KEYS or not value:return
    encrypted=_cipher().encrypt(value.encode()).decode()
    def op(con):
        con.execute("INSERT INTO secrets(secret_key,encrypted_value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP) ON CONFLICT(secret_key) DO UPDATE SET encrypted_value=excluded.encrypted_value,updated_at=CURRENT_TIMESTAMP",(key,encrypted))
    write_transaction(op)
def get_secret(key):
    if key not in SECRET_KEYS:return None
    con=connect()
    try:row=con.execute("SELECT encrypted_value FROM secrets WHERE secret_key=?",(key,)).fetchone()
    finally:con.close()
    if not row:return None
    try:return _cipher().decrypt(row["encrypted_value"].encode()).decode()
    except (InvalidToken,RuntimeError,ValueError):return None
