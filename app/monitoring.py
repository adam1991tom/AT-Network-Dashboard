from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from app.database import connect
from app.notifications import notify_incident_transition
from app import remediation

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


def _active_incident(con, incident_key: str):
    return con.execute("SELECT id FROM incidents WHERE incident_key=? AND active=1 ORDER BY id DESC LIMIT 1", (incident_key,)).fetchone()


def _set_incident(
    con,
    cfg: dict[str, Any],
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
    before_active = bool(active)
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

    after_active = bool(_active_incident(con, incident_key))
    transition = "open" if not before_active and after_active else "resolved" if before_active and not after_active else None
    if transition:
        if transition == "open":
            try:
                remediation.maybe_fix(incident_key, category, device)
            except Exception as exc:
                print(f"auto-remediation failed: {exc}")
        notify_incident_transition(cfg, incident_key, transition, severity, category, device, summary, details)


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
        _set_incident(con, cfg, "internet-offline", not online, "critical", "Internet", target, "Internet connection offline", f"Ping target {target} is unreachable.", 30, 60)
        loss = _float(ping.get("packet_loss"), 0) or 0
        loss_sev = "critical" if loss >= 50 else "major" if loss >= 10 else "warning"
        _set_incident(con, cfg, "internet-packet-loss", loss > 0, loss_sev, "Internet", target, "Packet loss detected", f"Packet loss is {loss:.1f}% to {target}.", 60, 60)
        latency = _float(ping.get("latency"))
        if latency is not None:
            lat_sev = "critical" if latency >= 150 else "major" if latency >= 80 else "warning"
            _set_incident(con, cfg, "internet-latency", latency >= 40, lat_sev, "Internet", target, "High internet latency", f"Latency is {latency:.1f} ms to {target}.", 120, 120)

    if gateway:
        _set_incident(con, cfg, "gateway-wan-offline", not bool(gateway.get("wan_up")), "critical", "Gateway", "WAN", "UniFi WAN offline", "The UniFi gateway reports the WAN interface as offline.", 30, 60)
        cpu = _float(gateway.get("cpu"), 0) or 0
        mem = _float(gateway.get("memory"), 0) or 0
        temp = _float(gateway.get("temperature"), 0) or 0
        _set_incident(con, cfg, "gateway-cpu", cpu >= 85, "major" if cpu >= 95 else "warning", "Gateway", "UCG", "Gateway CPU high", f"Gateway CPU is {cpu:.1f}%.", 180, 180)
        _set_incident(con, cfg, "gateway-memory", mem >= 90, "major" if mem >= 97 else "warning", "Gateway", "UCG", "Gateway memory high", f"Gateway memory is {mem:.1f}%.", 180, 180)
        _set_incident(con, cfg, "gateway-temperature", temp >= 75, "critical" if temp >= 90 else "major", "Gateway", "UCG", "Gateway temperature high", f"Gateway CPU temperature is {temp:.1f} °C.", 180, 180)
        errors = int(_float(gateway.get("rx_errors"), 0) or 0) + int(_float(gateway.get("tx_errors"), 0) or 0) + int(_float(gateway.get("rx_dropped"), 0) or 0) + int(_float(gateway.get("tx_dropped"), 0) or 0)
        _set_incident(con, cfg, "gateway-interface-errors", errors > 0, "warning", "Gateway", "WAN", "WAN interface errors/drops detected", f"Combined RX/TX errors and drops currently total {errors}.", 0, 300)

    if ups:
        connected = bool(ups.get("connected"))
        status = str(ups.get("status") or "")
        _set_incident(con, cfg, "ups-disconnected", not connected, "major", "UPS", "Power", "UPS monitoring disconnected", "The configured UPS/NUT source is not responding.", 30, 60)
        if connected:
            on_mains = "OL" in status
            _set_incident(con, cfg, "ups-on-battery", not on_mains, "critical", "UPS", "Power", "UPS running on battery", f"UPS status is {status or 'unknown'}.", 0, 60)
            load = _float(ups.get("load_pct"), 0) or 0
            _set_incident(con, cfg, "ups-high-load", load >= 85, "major" if load >= 95 else "warning", "UPS", "Power", "UPS load high", f"UPS load is {load:.1f}%.", 120, 120)

    warning = _float(cfg.get("wifi_warning_threshold"), 35) or 35
    major = _float(cfg.get("wifi_major_threshold"), 40) or 40
    critical = _float(cfg.get("wifi_critical_threshold"), 50) or 50
    persist = max(0, int(_float(cfg.get("wifi_persist_minutes"), 10) or 10)) * 60
    recovery = max(0, int(_float(cfg.get("wifi_recovery_minutes"), 10) or 10)) * 60
    for radio in radios:
        retries = _float(radio.get("retries"), 0) or 0
        sev = "critical" if retries >= critical else "major" if retries >= major else "warning"
        key = f"wifi-retries:{radio.get('device_id')}:{radio.get('band')}"
        _set_incident(con, cfg, key, retries >= warning, sev, "Wi-Fi", str(radio.get("ap_name") or "Access Point"), f"High Wi-Fi retries: {radio.get('ap_name')} {radio.get('band')}", f"TX retries are {retries:.1f}% on channel {radio.get('channel')}; utilisation {(_float(radio.get('utilization'),0) or 0):.0f}%.", persist, recovery)

    if speed and speed.get("download") is not None:
        down = _float(speed.get("download"), 0) or 0
        up = _float(speed.get("upload"), 0) or 0
        severity, threshold = _speed_severity(down, up, cfg)
        _set_incident(con, cfg, "isp-speed-current", bool(severity), severity or "warning", "ISP", "WAN", "ISP speed below configured threshold", f"Latest UniFi speed test: {down:.0f} Mbps down / {up:.0f} Mbps up; threshold {threshold or 0:.0f} Mbps.", 0, 0)


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
