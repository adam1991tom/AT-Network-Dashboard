from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import CONFIG


DB_PATH: Path = CONFIG.data_dir / "network.db"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
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

            CREATE TABLE IF NOT EXISTS ping_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                target TEXT NOT NULL,
                latency REAL,
                packet_loss REAL NOT NULL DEFAULT 100,
                online INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_ping_history_ts ON ping_history(ts);

            CREATE TABLE IF NOT EXISTS speedtest_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                epoch_ms INTEGER UNIQUE,
                download REAL,
                upload REAL,
                latency REAL,
                interface_name TEXT,
                wan_group TEXT,
                source TEXT NOT NULL DEFAULT 'unifi'
            );
            CREATE INDEX IF NOT EXISTS idx_speedtest_history_ts ON speedtest_history(ts);

            CREATE TABLE IF NOT EXISTS gateway_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                uptime INTEGER,
                cpu REAL,
                memory REAL,
                temperature REAL,
                wan_up INTEGER,
                wan_ip TEXT,
                link_speed INTEGER,
                rx_errors INTEGER,
                tx_errors INTEGER,
                rx_dropped INTEGER,
                tx_dropped INTEGER,
                rx_rate REAL,
                tx_rate REAL
            );
            CREATE INDEX IF NOT EXISTS idx_gateway_history_ts ON gateway_history(ts);

            CREATE TABLE IF NOT EXISTS ups_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                connected INTEGER NOT NULL DEFAULT 0,
                status TEXT,
                load_pct REAL,
                input_voltage REAL,
                output_voltage REAL,
                battery_voltage REAL,
                input_frequency REAL
            );
            CREATE INDEX IF NOT EXISTS idx_ups_history_ts ON ups_history(ts);

            CREATE TABLE IF NOT EXISTS wifi_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                device_id TEXT,
                ap_name TEXT NOT NULL,
                band TEXT NOT NULL,
                channel INTEGER,
                width INTEGER,
                retries REAL,
                utilization REAL,
                clients INTEGER,
                satisfaction REAL,
                tx_power REAL
            );
            CREATE INDEX IF NOT EXISTS idx_wifi_history_ts ON wifi_history(ts);
            CREATE INDEX IF NOT EXISTS idx_wifi_history_ap ON wifi_history(ap_name, band, ts);

            CREATE TABLE IF NOT EXISTS unifi_wan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                epoch_ms INTEGER NOT NULL,
                bucket TEXT NOT NULL,
                scope TEXT NOT NULL,
                object_id TEXT NOT NULL,
                clients INTEGER,
                rx_bytes REAL,
                tx_bytes REAL,
                UNIQUE(epoch_ms, bucket, scope, object_id)
            );
            CREATE INDEX IF NOT EXISTS idx_unifi_wan_history_ts ON unifi_wan_history(ts);

            CREATE TABLE IF NOT EXISTS unifi_ap_traffic_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                epoch_ms INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                clients INTEGER,
                bytes REAL,
                rx_bytes REAL,
                tx_bytes REAL,
                UNIQUE(epoch_ms, device_id)
            );
            CREATE INDEX IF NOT EXISTS idx_unifi_ap_traffic_history_ts ON unifi_ap_traffic_history(ts);
            """
        )
        con.commit()
    finally:
        con.close()
