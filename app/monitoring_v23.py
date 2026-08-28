from __future__ import annotations

import threading
import time
from typing import Any

from app.database import connect
from app.integrations.nut import NutPiHttpClient
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings, get_secret
from app.monitoring import (
    _apply_ap_current_names,
    _bool,
    _evaluate_incidents,
    _float,
    _store_speedtest,
    live_snapshot,
    ping_sample,
    utc_now,
)

_worker_started = False
_worker_lock = threading.Lock()
_last_archive_sync = 0.0
_last_speedtest_epoch = 0


def _gather_archives(client: UniFiClient) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Fetch a small catch-up window without holding a SQLite transaction open."""
    try:
        speed = client.speedtest_history(2)
    except Exception as exc:
        print(f"monitoring: speed-test catch-up failed: {exc}")
        speed = []
    try:
        retained = client.retained_history(2)
    except Exception as exc:
        print(f"monitoring: UniFi retained-history catch-up failed: {exc}")
        retained = {}
    return speed or [], retained or {}


def _write_archives(con, speed_rows: list[dict[str, Any]], retained: dict[str, list[dict[str, Any]]]) -> tuple[int, int]:
    speed_added = 0
    wan_added = 0
    for row in speed_rows:
        if _store_speedtest(con, row, "unifi-history"):
            speed_added += 1
    for source in ("gateway_hourly", "site_hourly", "site_daily"):
        for row in retained.get(source, []):
            try:
                epoch_ms = int(float(row.get("time")))
            except (TypeError, ValueError):
                continue
            ts = str(row.get("datetime") or "").strip()
            if not ts:
                continue
            scope = "gateway" if source == "gateway_hourly" else "site"
            bucket = "daily" if source == "site_daily" else "hourly"
            object_id = str(row.get("gw") or row.get("site") or row.get("oid") or "").strip()
            if not object_id:
                continue
            cur = con.execute(
                "INSERT OR IGNORE INTO unifi_wan_history(ts,epoch_ms,bucket,scope,object_id,clients,rx_bytes,tx_bytes) VALUES (?,?,?,?,?,?,?,?)",
                (ts, epoch_ms, bucket, scope, object_id, row.get("num_sta"), row.get("wan-rx_bytes"), row.get("wan-tx_bytes")),
            )
            wan_added += max(cur.rowcount, 0)
    return speed_added, wan_added


def collect_once() -> None:
    """Collect remotely first, then perform one short SQLite transaction.

    Older builds inserted the ping row and then kept the write transaction open while
    waiting on UPS and UniFi HTTP calls and archive downloads. That could block the UI,
    speed-test sidecar and settings writes, causing the slow/glitchy/missing-data feel.
    """
    global _last_archive_sync, _last_speedtest_epoch
    cfg = all_settings()
    ts = utc_now()

    ping_data: dict[str, Any] | None = None
    ups_data: dict[str, Any] | None = None
    snapshot: dict[str, Any] = {}
    gateway_data: dict[str, Any] | None = None
    speed_data: dict[str, Any] | None = None
    radio_rows: list[dict[str, Any]] = []
    speed_archive: list[dict[str, Any]] = []
    retained_archive: dict[str, list[dict[str, Any]]] = {}

    # Network I/O: no SQLite write connection is held during this phase.
    if _bool(cfg.get("isp_enabled"), True):
        target = str(cfg.get("ping_target", "1.1.1.1")).strip() or "1.1.1.1"
        ping_data = ping_sample(target)

    if _bool(cfg.get("ups_enabled")) and str(cfg.get("ups_type", "nutpi_http")) == "nutpi_http":
        try:
            raw = NutPiHttpClient(str(cfg.get("ups_host", "")), str(cfg.get("nutpi_status_path", "/api/nutpi/status.cgi"))).status()
            runtime = _float(raw.get("battery.runtime"))
            if runtime is None or runtime <= 0:
                runtime = _float(raw.get("ups.runtime"))
            if runtime is not None and runtime <= 0:
                runtime = None
            ups_data = {
                "connected": 1, "status": raw.get("ups.status"), "load_pct": _float(raw.get("ups.load")),
                "input_voltage": _float(raw.get("input.voltage")), "output_voltage": _float(raw.get("output.voltage")),
                "battery_voltage": _float(raw.get("battery.voltage")), "input_frequency": _float(raw.get("input.frequency")),
                "runtime_seconds": runtime,
            }
        except Exception:
            ups_data = {"connected": 0, "status": None}

    if _bool(cfg.get("unifi_enabled")):
        api_key = get_secret("unifi_api_key") or ""
        url = str(cfg.get("unifi_url", "")).strip()
        if api_key and url:
            try:
                client = UniFiClient(url, api_key, _bool(cfg.get("unifi_verify_ssl")))
                snapshot = client.snapshot() or {}
                gateway_data = snapshot.get("gateway") or {}
                speed_data = gateway_data.get("speedtest") if isinstance(gateway_data.get("speedtest"), dict) else None
                for ap in snapshot.get("aps", []):
                    for radio in ap.get("radios", []):
                        radio_rows.append({
                            "device_id": ap.get("device_id"), "ap_name": ap.get("name"), "band": radio.get("band"),
                            "channel": radio.get("channel"), "width": radio.get("width"), "retries": radio.get("retries"),
                            "utilization": radio.get("utilization"), "clients": radio.get("clients"),
                            "satisfaction": radio.get("satisfaction"), "tx_power": radio.get("tx_power"),
                        })
                now_mono = time.monotonic()
                if _last_archive_sync == 0 or now_mono - _last_archive_sync >= 600:
                    speed_archive, retained_archive = _gather_archives(client)
                    _last_archive_sync = now_mono
            except Exception as exc:
                print(f"monitoring: UniFi collection failed: {exc}")

    # Short write phase.
    con = connect()
    try:
        if ping_data:
            con.execute(
                "INSERT INTO ping_history(ts,target,latency,packet_loss,online) VALUES (?,?,?,?,?)",
                (ts, ping_data["target"], ping_data["latency"], ping_data["packet_loss"], ping_data["online"]),
            )
        if ups_data is not None:
            con.execute(
                "INSERT INTO ups_history(ts,connected,status,load_pct,input_voltage,output_voltage,battery_voltage,input_frequency,runtime_seconds) VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, ups_data.get("connected", 0), ups_data.get("status"), ups_data.get("load_pct"), ups_data.get("input_voltage"),
                 ups_data.get("output_voltage"), ups_data.get("battery_voltage"), ups_data.get("input_frequency"), ups_data.get("runtime_seconds")),
            )
        if gateway_data is not None:
            _apply_ap_current_names(con, snapshot)
            con.execute(
                "INSERT INTO gateway_history(ts,uptime,cpu,memory,temperature,wan_up,wan_ip,link_speed,rx_errors,tx_errors,rx_dropped,tx_dropped,rx_rate,tx_rate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, gateway_data.get("uptime"), gateway_data.get("cpu"), gateway_data.get("memory"), gateway_data.get("temperature"),
                 1 if gateway_data.get("wan_up") else 0, gateway_data.get("wan_ip"), gateway_data.get("link_speed"), gateway_data.get("rx_errors"),
                 gateway_data.get("tx_errors"), gateway_data.get("rx_dropped"), gateway_data.get("tx_dropped"), gateway_data.get("rx_rate"), gateway_data.get("tx_rate")),
            )
        if speed_data:
            try:
                epoch_ms = int(speed_data.get("epoch_ms") or 0)
            except (TypeError, ValueError):
                epoch_ms = 0
            if epoch_ms and epoch_ms != _last_speedtest_epoch:
                _store_speedtest(con, speed_data, "unifi-live")
                _last_speedtest_epoch = epoch_ms
        for row in radio_rows:
            con.execute(
                "INSERT INTO wifi_history(ts,device_id,ap_name,band,channel,width,retries,utilization,clients,satisfaction,tx_power) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ts, row["device_id"], row["ap_name"], row["band"], row["channel"], row["width"], row["retries"], row["utilization"], row["clients"], row["satisfaction"], row["tx_power"]),
            )
        if speed_archive or retained_archive:
            speed_added, wan_added = _write_archives(con, speed_archive, retained_archive)
            if speed_added or wan_added:
                print(f"monitoring: catch-up +{speed_added} speed tests, +{wan_added} WAN buckets")
        _evaluate_incidents(con, cfg, ping_data, gateway_data, ups_data, radio_rows, speed_data)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _worker() -> None:
    while True:
        started = time.monotonic()
        try:
            collect_once()
        except Exception as exc:
            print(f"monitoring collection failed: {exc}")
        elapsed = time.monotonic() - started
        time.sleep(max(5.0, 30.0 - elapsed))


def start_monitoring() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker, name="at-network-monitor-v23", daemon=True).start()
        _worker_started = True
