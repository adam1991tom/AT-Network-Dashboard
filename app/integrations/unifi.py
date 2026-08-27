from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class UniFiClient:
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl

    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key, "Accept": "application/json", "Content-Type": "application/json"}

    def _get(self, path: str) -> requests.Response:
        return requests.get(self.base_url + path, headers=self.headers, timeout=15, verify=self.verify_ssl)

    def _post(self, path: str, payload: dict[str, Any]) -> requests.Response:
        return requests.post(self.base_url + path, headers=self.headers, json=payload, timeout=20, verify=self.verify_ssl)

    def test_connection(self) -> dict:
        for path in ("/proxy/network/api/s/default/stat/device", "/proxy/network/integration/v1/info", "/integration/v1/info", "/proxy/network/integration/v1/sites"):
            try:
                response = self._get(path)
                if response.ok:
                    return {"ok": True, "endpoint": path, "status_code": response.status_code}
            except requests.RequestException:
                continue
        return {"ok": False, "message": "Unable to connect to UniFi"}

    def run_speedtest(self) -> dict[str, Any]:
        """Ask the UniFi gateway to run its built-in WAN speed test."""
        attempts = [
            ("/proxy/network/api/s/default/cmd/devmgr", {"cmd": "speedtest", "wan": "WAN"}),
            ("/proxy/network/api/s/default/cmd/devmgr", {"cmd": "speedtest"}),
            ("/api/s/default/cmd/devmgr", {"cmd": "speedtest", "wan": "WAN"}),
        ]
        errors: list[str] = []
        for path, payload in attempts:
            try:
                response = self._post(path, payload)
                if response.ok:
                    return {"ok": True, "message": "UniFi speed test started", "endpoint": path, "status_code": response.status_code}
                errors.append(f"{path}: HTTP {response.status_code}")
            except requests.RequestException as exc:
                errors.append(f"{path}: {exc}")
        return {"ok": False, "message": "Unable to start UniFi speed test", "details": errors[-3:]}

    def history_probe(self, days: int = 365) -> dict[str, Any]:
        """Probe retained UniFi report endpoints without importing or changing data."""
        days = max(1, min(int(days), 730))
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (days * 86400 * 1000)
        attrs = ["bytes", "num_sta", "wan-rx_bytes", "wan-tx_bytes", "rx_bytes", "tx_bytes"]
        candidates = {
            "site_daily": "/proxy/network/api/s/default/stat/report/daily.site",
            "gateway_hourly": "/proxy/network/api/s/default/stat/report/hourly.gw",
            "ap_hourly": "/proxy/network/api/s/default/stat/report/hourly.ap",
            "site_hourly": "/proxy/network/api/s/default/stat/report/hourly.site",
        }
        results: dict[str, Any] = {}
        oldest: int | None = None
        newest: int | None = None
        total = 0

        for name, path in candidates.items():
            rows: list[dict[str, Any]] = []
            error = ""
            payload = {"attrs": attrs, "start": start_ms, "end": end_ms}
            try:
                response = self._post(path, payload)
                if response.ok:
                    body = response.json()
                    data = body.get("data", []) if isinstance(body, dict) else []
                    if isinstance(data, list):
                        rows = [r for r in data if isinstance(r, dict)]
                else:
                    error = f"HTTP {response.status_code}"
            except Exception as exc:
                error = str(exc)

            timestamps: list[int] = []
            for row in rows:
                value = row.get("time") or row.get("timestamp")
                try:
                    number = int(float(value))
                    if number < 10_000_000_000:
                        number *= 1000
                    timestamps.append(number)
                except (TypeError, ValueError):
                    continue
            if timestamps:
                row_oldest, row_newest = min(timestamps), max(timestamps)
                oldest = row_oldest if oldest is None else min(oldest, row_oldest)
                newest = row_newest if newest is None else max(newest, row_newest)
            total += len(rows)
            results[name] = {
                "available": bool(rows),
                "records": len(rows),
                "oldest": self._iso_ms(min(timestamps)) if timestamps else None,
                "newest": self._iso_ms(max(timestamps)) if timestamps else None,
                "error": error or None,
                "endpoint": path,
            }

        return {
            "ok": total > 0,
            "requested_days": days,
            "total_records": total,
            "oldest": self._iso_ms(oldest) if oldest else None,
            "newest": self._iso_ms(newest) if newest else None,
            "sources": results,
            "message": f"Found {total} retained UniFi history records" if total else "No retained history returned by the probed UniFi report endpoints",
        }

    @staticmethod
    def _iso_ms(value: int) -> str:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()

    def devices(self) -> list[dict[str, Any]]:
        response = self._get("/proxy/network/api/s/default/stat/device")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            data = payload.get("data", [])
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
        return []

    def snapshot(self) -> dict[str, Any]:
        devices = self.devices()
        gateway: dict[str, Any] | None = None
        aps: list[dict[str, Any]] = []
        for device in devices:
            dtype = str(device.get("type", "")).lower()
            if dtype in {"ugw", "udm", "uxg", "gateway"} or "speedtest-status" in device or "wan1" in device:
                gateway = device
            if dtype == "uap" or device.get("is_access_point") is True:
                aps.append(device)
        if gateway is None:
            for device in devices:
                if isinstance(device.get("system-stats"), dict) and device.get("ip"):
                    gateway = device
                    break
        return {"gateway": self._gateway_stats(gateway or {}), "aps": [self._ap_stats(ap) for ap in aps]}

    @staticmethod
    def _number(value: Any, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _gateway_stats(self, device: dict[str, Any]) -> dict[str, Any]:
        system = device.get("system-stats") if isinstance(device.get("system-stats"), dict) else {}
        speed = device.get("speedtest-status") if isinstance(device.get("speedtest-status"), dict) else {}
        wan = device.get("wan1") if isinstance(device.get("wan1"), dict) else {}
        temperatures = device.get("temperatures") if isinstance(device.get("temperatures"), list) else []
        temp = None
        for item in temperatures:
            if isinstance(item, dict) and str(item.get("type", "")).lower() == "cpu":
                temp = self._number(item.get("value")); break
        wan_ip = wan.get("ip") or device.get("wan_ip") or device.get("ip")
        wan_up = str(device.get("last_wan_status", {}).get("WAN", "online")).lower() == "online" if isinstance(device.get("last_wan_status"), dict) else True
        link_speed = wan.get("speed") or (device.get("uplink", {}).get("speed") if isinstance(device.get("uplink"), dict) else None)
        speedtest = None
        if speed:
            speedtest = {"epoch_ms": int(speed.get("timestamp") or (float(speed.get("rundate", 0)) * 1000) or 0), "download": self._number(speed.get("xput_download")), "upload": self._number(speed.get("xput_upload")), "latency": self._number(speed.get("latency")), "interface_name": str(speed.get("interface", "")), "wan_group": str(speed.get("wan_group", "WAN"))}
        return {"name": device.get("name") or device.get("model") or "Gateway", "uptime": int(self._number(system.get("uptime") or device.get("uptime"), 0) or 0), "cpu": self._number(system.get("cpu")), "memory": self._number(system.get("mem")), "temperature": temp, "wan_up": bool(wan_up), "wan_ip": wan_ip, "link_speed": int(self._number(link_speed, 0) or 0), "rx_errors": int(self._number(device.get("rx_errors") or wan.get("rx_errors"), 0) or 0), "tx_errors": int(self._number(device.get("tx_errors") or wan.get("tx_errors"), 0) or 0), "rx_dropped": int(self._number(device.get("rx_dropped") or wan.get("rx_dropped"), 0) or 0), "tx_dropped": int(self._number(device.get("tx_dropped") or wan.get("tx_dropped"), 0) or 0), "rx_rate": self._number(device.get("rx_rate"), 0), "tx_rate": self._number(device.get("tx_rate"), 0), "speedtest": speedtest}

    def _ap_stats(self, device: dict[str, Any]) -> dict[str, Any]:
        radios = device.get("radio_table_stats") if isinstance(device.get("radio_table_stats"), list) else []
        rows: list[dict[str, Any]] = []
        for radio in radios:
            if not isinstance(radio, dict): continue
            code = str(radio.get("radio", ""))
            band = "2.4 GHz" if code in {"ng", "g"} else "5 GHz" if code in {"na", "a"} else code or "Unknown"
            rows.append({"band": band, "channel": int(self._number(radio.get("channel"), 0) or 0), "width": int(self._number(radio.get("bw"), 0) or 0), "retries": self._number(radio.get("tx_retries_pct"), 0), "utilization": self._number(radio.get("cu_total"), 0), "clients": int(self._number(radio.get("num_sta"), 0) or 0), "satisfaction": self._number(radio.get("satisfaction"), device.get("satisfaction")), "tx_power": self._number(radio.get("tx_power"), 0)})
        return {"device_id": device.get("external_id") or device.get("device_id") or device.get("mac"), "name": device.get("name") or device.get("model") or "Access Point", "uptime": int(self._number(device.get("uptime"), 0) or 0), "cpu": self._number((device.get("system-stats") or {}).get("cpu") if isinstance(device.get("system-stats"), dict) else None), "memory": self._number((device.get("system-stats") or {}).get("mem") if isinstance(device.get("system-stats"), dict) else None), "radios": rows}
