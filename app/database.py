from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import CONFIG


DB_PATH: Path = CONFIG.data_dir / "network.db"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def initialise() -> None:
    con = connect()
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS secrets (
                secret_key TEXT PRIMARY KEY,
                encrypted_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                summary TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS network_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT ''
            );
            """
        )
        con.commit()
    finally:
        con.close()
