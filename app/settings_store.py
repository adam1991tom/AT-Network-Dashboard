from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import CONFIG
from app.database import connect


DEFAULT_SETTINGS: dict[str, str] = {
    "application_name": "AT Network Dashboard",
    "application_subtitle": "Network · ISP · Wi-Fi · Power",
    "timezone": "Europe/London",
    "theme": "dark",
    "accent": "green",
    "default_range_hours": "24",
    "isp_enabled": "true",
    "isp_provider": "",
    "expected_download": "0",
    "expected_upload": "0",
    "warning_threshold": "0",
    "major_threshold": "0",
    "critical_threshold": "0",
    "ping_target": "1.1.1.1",
    "speedtest_minutes": "30",
    "unifi_enabled": "false",
    "unifi_url": "",
    "unifi_verify_ssl": "false",
    "ups_enabled": "false",
    "ups_type": "nutpi_http",
    "ups_host": "",
    "ups_port": "3493",
    "ups_name": "",
    "nutpi_status_path": "/api/nutpi/status.cgi",
    "discord_enabled": "false",
    "setup_complete": "false",
}

SECRET_KEYS = {"unifi_api_key", "discord_webhook"}


def ensure_defaults() -> None:
    con = connect()
    try:
        for key, value in DEFAULT_SETTINGS.items():
            con.execute(
                "INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES (?, ?)",
                (key, value),
            )
        con.commit()
    finally:
        con.close()


def all_settings() -> dict[str, str | bool]:
    ensure_defaults()
    con = connect()
    try:
        rows = con.execute("SELECT setting_key, setting_value FROM settings").fetchall()
        result: dict[str, str | bool] = {row["setting_key"]: row["setting_value"] for row in rows}
        for key in SECRET_KEYS:
            result[f"{key}_configured"] = bool(
                con.execute("SELECT 1 FROM secrets WHERE secret_key=?", (key,)).fetchone()
            )
        return result
    finally:
        con.close()


def set_settings(values: dict[str, object]) -> None:
    allowed = set(DEFAULT_SETTINGS)
    con = connect()
    try:
        for key, value in values.items():
            if key not in allowed:
                continue
            con.execute(
                """
                INSERT INTO settings(setting_key, setting_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(setting_key) DO UPDATE SET
                  setting_value=excluded.setting_value,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (key, str(value)),
            )
        con.commit()
    finally:
        con.close()


def _cipher() -> Fernet:
    if not CONFIG.master_key or CONFIG.master_key == "CHANGE_ME":
        raise RuntimeError("AT_MASTER_KEY must be generated for this installation")
    return Fernet(CONFIG.master_key.encode())


def set_secret(key: str, value: str) -> None:
    if key not in SECRET_KEYS or not value:
        return
    encrypted = _cipher().encrypt(value.encode()).decode()
    con = connect()
    try:
        con.execute(
            """
            INSERT INTO secrets(secret_key, encrypted_value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(secret_key) DO UPDATE SET
              encrypted_value=excluded.encrypted_value,
              updated_at=CURRENT_TIMESTAMP
            """,
            (key, encrypted),
        )
        con.commit()
    finally:
        con.close()


def get_secret(key: str) -> str | None:
    if key not in SECRET_KEYS:
        return None
    con = connect()
    try:
        row = con.execute("SELECT encrypted_value FROM secrets WHERE secret_key=?", (key,)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    try:
        return _cipher().decrypt(row["encrypted_value"].encode()).decode()
    except (InvalidToken, RuntimeError):
        return None
