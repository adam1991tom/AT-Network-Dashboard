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
_last_speed_history_sync = 0.0
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


def _sync_unifi_speed_history(client: UniFiClient, con) -> int:
    inserted = 0
    for row in client.speedtest_history(365):
        if _store_speedtest(con, row, "unifi-history"):
            inserted += 1
    return inserted


def _active_incident(con, incident_type: str):
    return con.execute("SELECT id FROM incidents WHERE incident_type=? AND active=1 ORDER BY id DESC LIMIT 1", (incident_type,)).fetchone()


def _set_incident(
    con,
    incident_type: str,
    bad: bool,
    severity: str,
    summary: str,
    details: str,
    persist_seconds: float = 60.0,
    recover_seconds: float = 60.0,
) -> None:
    now = time.monotonic()
    active = _active_incident(con, incident_type)
    if bad:
        _recovery_since.pop(incident_type, None)
        if active:
            _condition_since.pop(incident_type, None)
            return
        started = _condition_since.setdefault(incident_type, now)
        if now - started >= max(0.0, persist_seconds):
            con.execute(
                "INSERT INTO incidents(incident_type,severity,started_at,summary,details,active) VALUES (?,?,?,?,?,1)",
                (incident_type, severity, utc_now(), summary, details),
            )
            _condition_since.pop(incident_type, None)
    else:
        _condition_since.pop(incident_type, None)
        if not active:
            _recovery_since.pop(incident_type, None)
            return
        recovered = _recovery_since.setdefault(incident_type, now)
        if now - recovered >= max(0.0, recover_seconds):
            con.execute("UPDATE incidents SET active=0, ended_at=? WHERE id=?", (utc_now(), active["id"]))
            _recovery_since.pop(incident_type, None)


def _apply_ap_current_names(con, snapshot: dict[str, Any]) -> None:
    """Keep history attached to permanent UniFi device IDs when APs are renamed."""
    for ap in snapshot.get("aps", []):
        device_id = str(ap.get("device_id") or "").strip()
        current_name = str(ap.get("name") or "").strip()
        if device_id and current_name:
            con.execute("UPDATE wifi_history SET ap_name=? WHERE device_id=? AND ap_name<>?", (current_name, device_id, current_name))


def _evaluate_incidents(con, cfg: dict[str, Any], ping: dict[str, Any] | None, gateway: dict[str, Any] | None, ups: dict[str, Any] | None, radios: list[dict[str, Any]], speed: dict[str, Any] | None) -> None:
    if ping:
        _set_incident(con, "isp_offline", not bool(ping.get("online")), "critical", "Internet connection offline", f"Ping target {ping.get('target')} is unreachable.", 30, 60)
        loss = _float(ping.get("packet_loss"), 0) or 0
        _set_incident(con, "isp_packet_loss", loss >= 10, "major" if loss >= 25 else "warning", "High packet loss", f"Packet loss is {loss:.1f}% to {ping.get('target')}.", 120, 120)
        latency = _float(ping.get("latency"))
        _set_incident(con, "isp_latency", latency is not None and latency >= 80, "warning", "High internet latency", f"Latency is {latency:.1f} ms to {ping.get('target')}." if latency is not None else "", 120, 120)

    if gateway:
        _set_incident(con, "gateway_wan", not bool(gateway.get("wan_up")), "critical", "UniFi WAN offline", "The UniFi gateway reports the WAN interface as offline.", 30, 60)
        cpu = _float(gateway.get("cpu"), 0) or 0
        temp = _float(gateway.get("temperature"), 0) or 0
        _set_incident(con, "gateway_cpu", cpu >= 90, "major", "Gateway CPU very high", f"Gateway CPU is {cpu:.1f}%.", 180, 180)
        _set_incident(con, "gateway_temp", temp >= 80, "major", "Gateway temperature high", f"Gateway CPU temperature is {temp:.1f} °C.", 180, 180)

    if ups:
        connected = bool(ups.get("connected"))
        status = str(ups.get("status") or "")
        on_mains = "OL" in status
        _set_incident(con, "ups_disconnected", not connected, "major", "UPS monitoring disconnected", "The configured UPS/NUT source is not responding.", 30, 60)
        if connected:
            _set_incident(con, "ups_on_battery", not on_mains, "critical", "UPS running on battery", f"UPS status is {status or 'unknown'}.", 0, 60)

    wifi_persist = max(1, int(_float(cfg.get("wifi_persist_minutes"), 10) or 10)) * 60
    wifi_recover = max(1, int(_float(cfg.get("wifi_recovery_minutes"), 10) or 10)) * 60
    major = _float(cfg.get("wifi_major_retries"), 40) or 40
    warning = _float(cfg.get("wifi_warning_retries"), 35) or 35
    for radio in radios:
        retries = _float(radio.get("retries"), 0) or 0
        key = f"wifi_retries:{radio.get('device_id')}:{radio.get('band')}"
        bad = retries >= warning
        sev = "major" if retries >= major else "warning"
        _set_incident(con, key, bad, sev, f"High Wi-Fi retries: {radio.get('ap_name')} {radio.get('band')}", f"TX retries are {retries:.1f}% on channel {radio.get('channel')}.", wifi_persist, wifi_recover)

    if speed and speed.get("download") is not None:
        download = _float(speed.get("download"), 0) or 0
        upload = _float(speed.get("upload"), 0) or 0
        warning_speed = _float(cfg.get("warning_threshold"), 0) or 0
        major_speed = _float(cfg.get("major_threshold"), 0) or 0
        if warning_speed > 0:
            bad = download < warning_speed or upload < warning_speed
            sev = "major" if major_speed > 0 and (download < major_speed or upload < major_speed) else "warning"
            _set_incident(con, "isp_speed", bad, sev, "ISP speed below configured threshold", f"Latest UniFi speed test: {download:.0f} Mbps down / {upload:.0f} Mbps up.", 0, 0)


def collect_once() -> None:
    global _last_speedtest_epoch, _last_speed_history_sync
    cfg = all_settings()
    ts = utc_now()
    con = connect()
    ping_data: dict[str, Any] | None = None
    gateway_data: dict[str, Any] | None = None
    ups_data: dict[str, Any] | None = None
    radio_rows: list[dict[str, Any]] = []
    speed_data: dict[str, Any] | None = None
    try:
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
                ups_data = {
                    "connected": 1,
                    "status": raw.get("ups.status"),
                    "load_pct": _float(raw.get("ups.load")),
                    "input_voltage": _float(raw.get("input.voltage")),
                    "output_voltage": _float(raw.get("output.voltage")),
                    "battery_voltage": _float(raw.get("battery.voltage")),
                    "input_frequency": _float(raw.get("input.frequency")),
                    "runtime_seconds": runtime,
                }
                con.execute(
                    "INSERT INTO ups_history(ts,connected,status,load_pct,input_voltage,output_voltage,battery_voltage,input_frequency,runtime_seconds) VALUES (?,?,?,?,?,?,?,?,?)",
                    (ts, 1, ups_data["status"], ups_data["load_pct"], ups_data["input_voltage"], ups_data["output_voltage"], ups_data["battery_voltage"], ups_data["input_frequency"], runtime),
                )
            except Exception:
                ups_data = {"connected": 0, "status": None}
                con.execute("INSERT INTO ups_history(ts,connected) VALUES (?,0)", (ts,))

        if _bool(cfg.get("unifi_enabled")):
            key = get_secret("unifi_api_key") or ""
            url = str(cfg.get("unifi_url", "")).strip()
            if key and url:
                try:
                    client = UniFiClient(url, key, _bool(cfg.get("unifi_verify_ssl")))
                    now_mono = time.monotonic()
                    if _last_speed_history_sync == 0 or now_mono - _last_speed_history_sync >= 900:
                        inserted = _sync_unifi_speed_history(client, con)
                        _last_speed_history_sync = now_mono
                        if inserted:
                            print(f"monitoring: imported {inserted} UniFi speed-test history rows")

                    snapshot = client.snapshot()
                    _apply_ap_current_names(con, snapshot)
                    gateway_data = snapshot.get("gateway") or {}
                    con.execute(
                        "INSERT INTO gateway_history(ts,uptime,cpu,memory,temperature,wan_up,wan_ip,link_speed,rx_errors,tx_errors,rx_dropped,tx_dropped,rx_rate,tx_rate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, gateway_data.get("uptime"), gateway_data.get("cpu"), gateway_data.get("memory"), gateway_data.get("temperature"), 1 if gateway_data.get("wan_up") else 0, gateway_data.get("wan_ip"), gateway_data.get("link_speed"), gateway_data.get("rx_errors"), gateway_data.get("tx_errors"), gateway_data.get("rx_dropped"), gateway_data.get("tx_dropped"), gateway_data.get("rx_rate"), gateway_data.get("tx_rate")),
                    )

                    speed_data = gateway_data.get("speedtest") if isinstance(gateway_data.get("speedtest"), dict) else None
                    if speed_data:
                        epoch_ms = int(speed_data.get("epoch_ms") or 0)
                        if epoch_ms and epoch_ms != _last_speedtest_epoch:
                            _store_speedtest(con, speed_data, "unifi-live")
                            _last_speedtest_epoch = epoch_ms

                    for ap in snapshot.get("aps", []):
                        for radio in ap.get("radios", []):
                            row = {
                                "device_id": ap.get("device_id"), "ap_name": ap.get("name"), "band": radio.get("band"),
                                "channel": radio.get("channel"), "width": radio.get("width"), "retries": radio.get("retries"),
                                "utilization": radio.get("utilization"), "clients": radio.get("clients"), "satisfaction": radio.get("satisfaction"), "tx_power": radio.get("tx_power"),
                            }
                            radio_rows.append(row)
                            con.execute(
                                "INSERT INTO wifi_history(ts,device_id,ap_name,band,channel,width,retries,utilization,clients,satisfaction,tx_power) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (ts, row["device_id"], row["ap_name"], row["band"], row["channel"], row["width"], row["retries"], row["utilization"], row["clients"], row["satisfaction"], row["tx_power"]),
                            )
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
        aps = con.execute(
            """SELECT w.* FROM wifi_history w
            JOIN (
              SELECT COALESCE(NULLIF(device_id,''),ap_name) AS identity,band,MAX(id) AS max_id
              FROM wifi_history GROUP BY COALESCE(NULLIF(device_id,''),ap_name),band
            ) x ON w.id=x.max_id ORDER BY w.ap_name,w.band"""
        ).fetchall()
        return {"ping": one("ping_history"), "speedtest": one("speedtest_history"), "gateway": one("gateway_history"), "ups": one("ups_history"), "wifi": [dict(row) for row in aps]}
    finally:
        con.close()
