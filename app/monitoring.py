from __future__ import annotations

import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.database import connect
from app.integrations.nut import NutPiHttpClient
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings, get_secret

_worker_started = False
_worker_lock = threading.Lock()
_last_speedtest_epoch = 0
_last_unifi_archive_sync = 0.0
_history_backfilled = False
_condition_since: dict[str, float] = {}
_recovery_since: dict[str, float] = {}


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ping_sample(target: str) -> dict[str, Any]:
    try:
        result = subprocess.run(["ping", "-c", "3", "-W", "2", target], capture_output=True, text=True, timeout=10, check=False)
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        loss_match = re.search(r"([0-9.]+)% packet loss", output)
        latency_match = re.search(r"(?:rtt|round-trip).*?=\s*[0-9.]+/([0-9.]+)/", output)
        loss = float(loss_match.group(1)) if loss_match else (0.0 if result.returncode == 0 else 100.0)
        latency = float(latency_match.group(1)) if latency_match else None
        return {"target": target, "latency": latency, "packet_loss": loss, "online": 1 if result.returncode == 0 else 0}
    except Exception:
        return {"target": target, "latency": None, "packet_loss": 100.0, "online": 0}


def _store_speedtest(con, row: dict[str, Any], source: str = "unifi") -> bool:
    try:
        epoch_ms = int(row.get("epoch_ms") or 0)
    except (TypeError, ValueError):
        return False
    if not epoch_ms or row.get("download") is None:
        return False
    ts = str(row.get("ts") or "").strip() or datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()
    cur = con.execute(
        "INSERT OR IGNORE INTO speedtest_history(ts,epoch_ms,download,upload,latency,interface_name,wan_group,source) VALUES (?,?,?,?,?,?,?,?)",
        (ts, epoch_ms, row.get("download"), row.get("upload"), row.get("latency"), row.get("interface_name"), row.get("wan_group") or "WAN", source),
    )
    return cur.rowcount > 0


def _sync_unifi_archives(client: UniFiClient, con) -> tuple[int, int]:
    speed_inserted = 0
    wan_inserted = 0
    for row in client.speedtest_history(365):
        if _store_speedtest(con, row, "unifi-history"):
            speed_inserted += 1

    history = client.retained_history(7)
    for source in ("gateway_hourly", "site_hourly", "site_daily"):
        for row in history.get(source, []):
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
            wan_inserted += max(cur.rowcount, 0)
    return speed_inserted, wan_inserted


def _active_incident(con, incident_key: str):
    return con.execute("SELECT id FROM incidents WHERE incident_key=? AND active=1 ORDER BY id DESC LIMIT 1", (incident_key,)).fetchone()


def _set_incident(
    con,
    incident_key: str,
    bad: bool,
    severity: str,
    category: str,
    device: str,
    summary: str,
    details: str,
    persist_seconds: float = 0,
    recover_seconds: float = 0,
) -> None:
    now_mono = time.monotonic()
    active = _active_incident(con, incident_key)
    if bad:
        _recovery_since.pop(incident_key, None)
        if active:
            con.execute(
                "UPDATE incidents SET severity=?,category=?,device=?,summary=?,details=?,last_seen_at=? WHERE id=?",
                (severity, category, device, summary, details, utc_now(), active["id"]),
            )
            _condition_since.pop(incident_key, None)
            return
        since = _condition_since.setdefault(incident_key, now_mono)
        if now_mono - since >= max(0.0, persist_seconds):
            now = utc_now()
            con.execute(
                "INSERT INTO incidents(incident_type,severity,started_at,summary,details,active,incident_key,category,device,last_seen_at) VALUES (?,?,?,?,?,1,?,?,?,?)",
                (incident_key, severity, now, summary, details, incident_key, category, device, now),
            )
            _condition_since.pop(incident_key, None)
    else:
        _condition_since.pop(incident_key, None)
        if not active:
            _recovery_since.pop(incident_key, None)
            return
        since = _recovery_since.setdefault(incident_key, now_mono)
        if now_mono - since >= max(0.0, recover_seconds):
            con.execute("UPDATE incidents SET active=0,ended_at=?,last_seen_at=? WHERE id=?", (utc_now(), utc_now(), active["id"]))
            _recovery_since.pop(incident_key, None)


def _apply_ap_current_names(con, snapshot: dict[str, Any]) -> None:
    for ap in snapshot.get("aps", []):
        device_id = str(ap.get("device_id") or "").strip()
        current_name = str(ap.get("name") or "").strip()
        if device_id and current_name:
            con.execute("UPDATE wifi_history SET ap_name=? WHERE device_id=? AND ap_name<>?", (current_name, device_id, current_name))


def _speed_severity(download: float, upload: float, cfg: dict[str, Any]) -> tuple[str | None, float | None]:
    critical = _float(cfg.get("critical_threshold"), 0) or 0
    major = _float(cfg.get("major_threshold"), 0) or 0
    warning = _float(cfg.get("warning_threshold"), 0) or 0
    worst = min(download, upload)
    if critical > 0 and worst < critical:
        return "critical", critical
    if major > 0 and worst < major:
        return "major", major
    if warning > 0 and worst < warning:
        return "warning", warning
    return None, None


def _backfill_historical_incidents(con, cfg: dict[str, Any]) -> None:
    global _history_backfilled
    if _history_backfilled:
        return
    rows = con.execute("SELECT ts,epoch_ms,download,upload,latency FROM speedtest_history WHERE datetime(ts)>=datetime('now','-90 days') ORDER BY datetime(ts)").fetchall()
    for row in rows:
        down = _float(row["download"], 0) or 0
        up = _float(row["upload"], 0) or 0
        severity, threshold = _speed_severity(down, up, cfg)
        if not severity:
            continue
        key = f"history-speed:{row['epoch_ms']}"
        if con.execute("SELECT 1 FROM incidents WHERE incident_key=? LIMIT 1", (key,)).fetchone():
            continue
        detail = f"UniFi speed test recorded {down:.0f} Mbps down / {up:.0f} Mbps up; configured {severity} threshold {threshold:.0f} Mbps."
        con.execute(
            "INSERT INTO incidents(incident_type,severity,started_at,ended_at,summary,details,active,incident_key,category,device,last_seen_at) VALUES (?,?,?,?,?,?,0,?,?,?,?)",
            ("isp_speed_test", severity, row["ts"], row["ts"], "Historical ISP speed threshold breach", detail, key, "ISP", "WAN", row["ts"]),
        )
    _history_backfilled = True


def _evaluate_incidents(con, cfg: dict[str, Any], ping: dict[str, Any] | None, gateway: dict[str, Any] | None, ups: dict[str, Any] | None, radios: list[dict[str, Any]], speed: dict[str, Any] | None) -> None:
    if ping:
        target = str(ping.get("target") or cfg.get("ping_target") or "Internet")
        online = bool(ping.get("online"))
        _set_incident(con, "internet-offline", not online, "critical", "Internet", target, "Internet connection offline", f"Ping target {target} is unreachable.", 30, 60)
        loss = _float(ping.get("packet_loss"), 0) or 0
        loss_sev = "critical" if loss >= 50 else "major" if loss >= 10 else "warning"
        _set_incident(con, "internet-packet-loss", loss > 0, loss_sev, "Internet", target, "Packet loss detected", f"Packet loss is {loss:.1f}% to {target}.", 60, 60)
        latency = _float(ping.get("latency"))
        if latency is not None:
            lat_sev = "critical" if latency >= 150 else "major" if latency >= 80 else "warning"
            _set_incident(con, "internet-latency", latency >= 40, lat_sev, "Internet", target, "High internet latency", f"Latency is {latency:.1f} ms to {target}.", 120, 120)

    if gateway:
        _set_incident(con, "gateway-wan-offline", not bool(gateway.get("wan_up")), "critical", "Gateway", "WAN", "UniFi WAN offline", "The UniFi gateway reports the WAN interface as offline.", 30, 60)
        cpu = _float(gateway.get("cpu"), 0) or 0
        mem = _float(gateway.get("memory"), 0) or 0
        temp = _float(gateway.get("temperature"), 0) or 0
        _set_incident(con, "gateway-cpu", cpu >= 85, "major" if cpu >= 95 else "warning", "Gateway", "UCG", "Gateway CPU high", f"Gateway CPU is {cpu:.1f}%.", 180, 180)
        _set_incident(con, "gateway-memory", mem >= 90, "major" if mem >= 97 else "warning", "Gateway", "UCG", "Gateway memory high", f"Gateway memory is {mem:.1f}%.", 180, 180)
        _set_incident(con, "gateway-temperature", temp >= 75, "critical" if temp >= 90 else "major", "Gateway", "UCG", "Gateway temperature high", f"Gateway CPU temperature is {temp:.1f} °C.", 180, 180)
        errors = int(_float(gateway.get("rx_errors"), 0) or 0) + int(_float(gateway.get("tx_errors"), 0) or 0) + int(_float(gateway.get("rx_dropped"), 0) or 0) + int(_float(gateway.get("tx_dropped"), 0) or 0)
        _set_incident(con, "gateway-interface-errors", errors > 0, "warning", "Gateway", "WAN", "WAN interface errors/drops detected", f"Combined RX/TX errors and drops currently total {errors}.", 0, 300)

    if ups:
        connected = bool(ups.get("connected"))
        status = str(ups.get("status") or "")
        _set_incident(con, "ups-disconnected", not connected, "major", "UPS", "Power", "UPS monitoring disconnected", "The configured UPS/NUT source is not responding.", 30, 60)
        if connected:
            on_mains = "OL" in status
            _set_incident(con, "ups-on-battery", not on_mains, "critical", "UPS", "Power", "UPS running on battery", f"UPS status is {status or 'unknown'}.", 0, 60)
            load = _float(ups.get("load_pct"), 0) or 0
            _set_incident(con, "ups-high-load", load >= 85, "major" if load >= 95 else "warning", "UPS", "Power", "UPS load high", f"UPS load is {load:.1f}%.", 120, 120)

    warning = _float(cfg.get("wifi_warning_threshold"), 35) or 35
    major = _float(cfg.get("wifi_major_threshold"), 40) or 40
    critical = _float(cfg.get("wifi_critical_threshold"), 50) or 50
    persist = max(0, int(_float(cfg.get("wifi_persist_minutes"), 10) or 10)) * 60
    recovery = max(0, int(_float(cfg.get("wifi_recovery_minutes"), 10) or 10)) * 60
    for radio in radios:
        retries = _float(radio.get("retries"), 0) or 0
        sev = "critical" if retries >= critical else "major" if retries >= major else "warning"
        key = f"wifi-retries:{radio.get('device_id')}:{radio.get('band')}"
        _set_incident(con, key, retries >= warning, sev, "Wi-Fi", str(radio.get("ap_name") or "Access Point"), f"High Wi-Fi retries: {radio.get('ap_name')} {radio.get('band')}", f"TX retries are {retries:.1f}% on channel {radio.get('channel')}; utilisation {(_float(radio.get('utilization'),0) or 0):.0f}%.", persist, recovery)

    if speed and speed.get("download") is not None:
        down = _float(speed.get("download"), 0) or 0
        up = _float(speed.get("upload"), 0) or 0
        severity, threshold = _speed_severity(down, up, cfg)
        _set_incident(con, "isp-speed-current", bool(severity), severity or "warning", "ISP", "WAN", "ISP speed below configured threshold", f"Latest UniFi speed test: {down:.0f} Mbps down / {up:.0f} Mbps up; threshold {threshold or 0:.0f} Mbps.", 0, 0)


def collect_once() -> None:
    global _last_speedtest_epoch, _last_unifi_archive_sync
    cfg = all_settings()
    ts = utc_now()
    con = connect()
    ping_data: dict[str, Any] | None = None
    gateway_data: dict[str, Any] | None = None
    ups_data: dict[str, Any] | None = None
    radio_rows: list[dict[str, Any]] = []
    speed_data: dict[str, Any] | None = None
    try:
        _backfill_historical_incidents(con, cfg)

        if _bool(cfg.get("isp_enabled"), True):
            target = str(cfg.get("ping_target", "1.1.1.1")).strip() or "1.1.1.1"
            ping_data = ping_sample(target)
            con.execute("INSERT INTO ping_history(ts,target,latency,packet_loss,online) VALUES (?,?,?,?,?)", (ts, target, ping_data["latency"], ping_data["packet_loss"], ping_data["online"]))

        if _bool(cfg.get("ups_enabled")) and str(cfg.get("ups_type", "nutpi_http")) == "nutpi_http":
            try:
                raw = NutPiHttpClient(str(cfg.get("ups_host", "")), str(cfg.get("nutpi_status_path", "/api/nutpi/status.cgi"))).status()
                runtime = _float(raw.get("battery.runtime"))
                if runtime is None or runtime <= 0:
                    runtime = _float(raw.get("ups.runtime"))
                if runtime is not None and runtime <= 0:
                    runtime = None
                ups_data = {"connected": 1, "status": raw.get("ups.status"), "load_pct": _float(raw.get("ups.load")), "input_voltage": _float(raw.get("input.voltage")), "output_voltage": _float(raw.get("output.voltage")), "battery_voltage": _float(raw.get("battery.voltage")), "input_frequency": _float(raw.get("input.frequency")), "runtime_seconds": runtime}
                con.execute("INSERT INTO ups_history(ts,connected,status,load_pct,input_voltage,output_voltage,battery_voltage,input_frequency,runtime_seconds) VALUES (?,?,?,?,?,?,?,?,?)", (ts, 1, ups_data["status"], ups_data["load_pct"], ups_data["input_voltage"], ups_data["output_voltage"], ups_data["battery_voltage"], ups_data["input_frequency"], runtime))
            except Exception:
                ups_data = {"connected": 0, "status": None}
                con.execute("INSERT INTO ups_history(ts,connected) VALUES (?,0)", (ts,))

        if _bool(cfg.get("unifi_enabled")):
            api_key = get_secret("unifi_api_key") or ""
            url = str(cfg.get("unifi_url", "")).strip()
            if api_key and url:
                try:
                    client = UniFiClient(url, api_key, _bool(cfg.get("unifi_verify_ssl")))
                    now_mono = time.monotonic()
                    if _last_unifi_archive_sync == 0 or now_mono - _last_unifi_archive_sync >= 900:
                        speed_added, wan_added = _sync_unifi_archives(client, con)
                        _last_unifi_archive_sync = now_mono
                        if speed_added or wan_added:
                            print(f"monitoring: UniFi archive sync +{speed_added} speed tests, +{wan_added} WAN buckets")

                    snapshot = client.snapshot()
                    _apply_ap_current_names(con, snapshot)
                    gateway_data = snapshot.get("gateway") or {}
                    con.execute("INSERT INTO gateway_history(ts,uptime,cpu,memory,temperature,wan_up,wan_ip,link_speed,rx_errors,tx_errors,rx_dropped,tx_dropped,rx_rate,tx_rate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (ts, gateway_data.get("uptime"), gateway_data.get("cpu"), gateway_data.get("memory"), gateway_data.get("temperature"), 1 if gateway_data.get("wan_up") else 0, gateway_data.get("wan_ip"), gateway_data.get("link_speed"), gateway_data.get("rx_errors"), gateway_data.get("tx_errors"), gateway_data.get("rx_dropped"), gateway_data.get("tx_dropped"), gateway_data.get("rx_rate"), gateway_data.get("tx_rate")))

                    speed_data = gateway_data.get("speedtest") if isinstance(gateway_data.get("speedtest"), dict) else None
                    if speed_data:
                        epoch_ms = int(speed_data.get("epoch_ms") or 0)
                        if epoch_ms and epoch_ms != _last_speedtest_epoch:
                            _store_speedtest(con, speed_data, "unifi-live")
                            _last_speedtest_epoch = epoch_ms

                    for ap in snapshot.get("aps", []):
                        for radio in ap.get("radios", []):
                            row = {"device_id": ap.get("device_id"), "ap_name": ap.get("name"), "band": radio.get("band"), "channel": radio.get("channel"), "width": radio.get("width"), "retries": radio.get("retries"), "utilization": radio.get("utilization"), "clients": radio.get("clients"), "satisfaction": radio.get("satisfaction"), "tx_power": radio.get("tx_power")}
                            radio_rows.append(row)
                            con.execute("INSERT INTO wifi_history(ts,device_id,ap_name,band,channel,width,retries,utilization,clients,satisfaction,tx_power) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (ts, row["device_id"], row["ap_name"], row["band"], row["channel"], row["width"], row["retries"], row["utilization"], row["clients"], row["satisfaction"], row["tx_power"]))
                except Exception as exc:
                    print(f"monitoring: UniFi collection failed: {exc}")

        _evaluate_incidents(con, cfg, ping_data, gateway_data, ups_data, radio_rows, speed_data)
        con.commit()
    finally:
        con.close()


def _worker() -> None:
    while True:
        started = time.monotonic()
        try:
            collect_once()
        except Exception as exc:
            print(f"monitoring collection failed: {exc}")
        time.sleep(max(5.0, 30.0 - (time.monotonic() - started)))


def start_monitoring() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker, name="at-network-monitor", daemon=True).start()
        _worker_started = True


def _history(table: str, hours: int, columns: str = "*") -> list[dict[str, Any]]:
    hours = max(1, min(int(hours), 24 * 365))
    con = connect()
    try:
        rows = con.execute(f"SELECT {columns} FROM {table} WHERE datetime(ts) >= datetime('now', ?) ORDER BY datetime(ts) ASC", (f"-{hours} hours",)).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def ping_history(hours: int) -> list[dict[str, Any]]:
    return _history("ping_history", hours, "ts,target,latency,packet_loss,online")


def speedtest_history(hours: int) -> list[dict[str, Any]]:
    return _history("speedtest_history", hours, "ts,epoch_ms,download,upload,latency,interface_name,wan_group,source")


def gateway_history(hours: int) -> list[dict[str, Any]]:
    return _history("gateway_history", hours, "ts,uptime,cpu,memory,temperature,wan_up,wan_ip,link_speed,rx_errors,tx_errors,rx_dropped,tx_dropped,rx_rate,tx_rate")


def ups_history(hours: int) -> list[dict[str, Any]]:
    return _history("ups_history", hours, "ts,connected,status,load_pct,input_voltage,output_voltage,battery_voltage,input_frequency,runtime_seconds")


def wifi_history(hours: int) -> list[dict[str, Any]]:
    return _history("wifi_history", hours, "ts,device_id,ap_name,band,channel,width,retries,utilization,clients,satisfaction,tx_power")


def live_snapshot() -> dict[str, Any]:
    con = connect()
    try:
        def one(table: str) -> dict[str, Any] | None:
            row = con.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None
        aps = con.execute("""
            SELECT w.* FROM wifi_history w
            JOIN (SELECT COALESCE(device_id,ap_name) ident,band,MAX(id) max_id FROM wifi_history GROUP BY COALESCE(device_id,ap_name),band) x
              ON w.id=x.max_id
            ORDER BY w.ap_name,w.band
        """).fetchall()
        return {"ping": one("ping_history"), "speedtest": one("speedtest_history"), "gateway": one("gateway_history"), "ups": one("ups_history"), "wifi": [dict(row) for row in aps]}
    finally:
        con.close()
