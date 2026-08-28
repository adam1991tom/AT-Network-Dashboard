from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.database import connect

COOKIE_NAME = "at_network_session"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algo, salt_hex, digest_hex = encoded.split("$", 2)
        if algo != "scrypt":
            return False
        candidate = _hash_password(password, bytes.fromhex(salt_hex)).split("$", 2)[2]
        return hmac.compare_digest(candidate, digest_hex)
    except Exception:
        return False


def has_admin() -> bool:
    con = connect()
    try:
        return bool(con.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone())
    finally:
        con.close()


def create_admin(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(password) < 10:
        return False, "Password must be at least 10 characters"
    con = connect()
    try:
        if con.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
            return False, "Administrator already exists"
        con.execute("INSERT INTO admin_users(username,password_hash) VALUES (?,?)", (username, _hash_password(password)))
        con.commit()
        return True, "Administrator created"
    finally:
        con.close()


def login(username: str, password: str, session_hours: int = 8) -> str | None:
    con = connect()
    try:
        row = con.execute("SELECT id,password_hash FROM admin_users WHERE username=?", (username.strip(),)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        expiry = _now() + timedelta(hours=max(1, min(int(session_hours), 168)))
        con.execute("DELETE FROM sessions WHERE datetime(expires_at) <= datetime('now')")
        con.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (?,?,?)", (_hash_token(token), row["id"], _iso(expiry)))
        con.commit()
        return token
    finally:
        con.close()


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    con = connect()
    try:
        row = con.execute("""
            SELECT u.id,u.username,s.expires_at
            FROM sessions s JOIN admin_users u ON u.id=s.user_id
            WHERE s.token_hash=? AND datetime(s.expires_at) > datetime('now')
        """, (_hash_token(token),)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def logout(token: str | None) -> None:
    if not token:
        return
    con = connect()
    try:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))
        con.commit()
    finally:
        con.close()


def change_password(user_id: int, current_password: str, new_password: str) -> tuple[bool, str]:
    if len(new_password) < 10:
        return False, "New password must be at least 10 characters"
    con = connect()
    try:
        row = con.execute("SELECT password_hash FROM admin_users WHERE id=?", (user_id,)).fetchone()
        if not row or not _verify_password(current_password, row["password_hash"]):
            return False, "Current password is incorrect"
        con.execute("UPDATE admin_users SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (_hash_password(new_password), user_id))
        con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        con.commit()
        return True, "Password changed"
    finally:
        con.close()
