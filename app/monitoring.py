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

def collect_once() -> None:
    global _last_speedtest_epoch
    cfg = all_settings()
    ts = utc_now()
    con = connect()
    try:
        if _bool(cfg.get("isp_enabled"), True):
            target = str(cfg.get("ping_target", "1.1.1.1")).strip() or "1.1.1.1"
            ping = ping_sample(target)
            con.execute("INSERT INTO ping_history(ts,target,latency,packet_loss,online) VALUES (?,?,?,?,?)", (ts, target, ping["latency"], ping["packet_loss"], ping["online"]))

        if _bool(cfg.get("ups_enabled")) and str(cfg.get("ups_type", "nutpi_http")) == "nutpi_http":
            try:
                data = NutPiHttpClient(str(cfg.get("ups_host", "")), str(cfg.get("nutpi_status_path", "/api/nutpi/status.cgi"))).status()
                runtime = _float(data.get("battery.runtime"))
                if runtime is None:
                    runtime = _float(data.get("ups.runtime"))
                con.execute(
                    "INSERT INTO ups_history(ts,connected,status,load_pct,input_voltage,output_voltage,battery_voltage,input_frequency,runtime_seconds) VALUES (?,?,?,?,?,?,?,?,?)",
                    (ts, 1, data.get("ups.status"), _float(data.get("ups.load")), _float(data.get("input.voltage")), _float(data.get("output.voltage")), _float(data.get("battery.voltage")), _float(data.get("input.frequency")), runtime),
                )
            except Exception:
                con.execute("INSERT INTO ups_history(ts,connected) VALUES (?,0)", (ts,))

        if _bool(cfg.get("unifi_enabled")):
            key = get_secret("unifi_api_key") or ""
            url = str(cfg.get("unifi_url", "")).strip()
            if key and url:
                try:
                    client = UniFiClient(url, key, _bool(cfg.get("unifi_verify_ssl")))
                    snapshot = client.snapshot()
                    gw = snapshot.get("gateway") or {}
                    con.execute(
                        "INSERT INTO gateway_history(ts,uptime,cpu,memory,temperature,wan_up,wan_ip,link_speed,rx_errors,tx_errors,rx_dropped,tx_dropped,rx_rate,tx_rate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, gw.get("uptime"), gw.get("cpu"), gw.get("memory"), gw.get("temperature"), 1 if gw.get("wan_up") else 0, gw.get("wan_ip"), gw.get("link_speed"), gw.get("rx_errors"), gw.get("tx_errors"), gw.get("rx_dropped"), gw.get("tx_dropped"), gw.get("rx_rate"), gw.get("tx_rate")),
                    )
                    speed = gw.get("speedtest")
                    if isinstance(speed, dict):
                        epoch_ms = int(speed.get("epoch_ms") or 0)
                        if epoch_ms and epoch_ms != _last_speedtest_epoch and speed.get("download") is not None:
                            speed_ts = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()
                            con.execute(
                                "INSERT OR IGNORE INTO speedtest_history(ts,epoch_ms,download,upload,latency,interface_name,wan_group,source) VALUES (?,?,?,?,?,?,?,'unifi')",
                                (speed_ts, epoch_ms, speed.get("download"), speed.get("upload"), speed.get("latency"), speed.get("interface_name"), speed.get("wan_group") or "WAN"),
                            )
                            _last_speedtest_epoch = epoch_ms
                    for ap in snapshot.get("aps", []):
                        for radio in ap.get("radios", []):
                            con.execute(
                                "INSERT INTO wifi_history(ts,device_id,ap_name,band,channel,width,retries,utilization,clients,satisfaction,tx_power) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (ts, ap.get("device_id"), ap.get("name"), radio.get("band"), radio.get("channel"), radio.get("width"), radio.get("retries"), radio.get("utilization"), radio.get("clients"), radio.get("satisfaction"), radio.get("tx_power")),
                            )
                except Exception as exc:
                    print(f"monitoring: UniFi collection failed: {exc}")
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
    return _history("speedtest_history", hours, "ts,download,upload,latency,interface_name,wan_group,source")

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
        aps = con.execute("SELECT w.* FROM wifi_history w JOIN (SELECT ap_name,band,MAX(id) AS max_id FROM wifi_history GROUP BY ap_name,band) x ON w.id=x.max_id ORDER BY w.ap_name,w.band").fetchall()
        return {"ping": one("ping_history"), "speedtest": one("speedtest_history"), "gateway": one("gateway_history"), "ups": one("ups_history"), "wifi": [dict(row) for row in aps]}
    finally:
        con.close()
