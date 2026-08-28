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

    def diagnostics(self) -> dict[str, Any]:
        """Probe the UniFi sources the dashboard relies on without exposing secrets."""
        probes: list[dict[str, Any]] = []
        for path in (
            "/proxy/network/api/s/default/stat/device",
            "/proxy/network/integration/v1/info",
            "/proxy/network/integration/v1/sites",
        ):
            started=time.monotonic()
            try:
                r=self._get(path); count=None
                if r.ok:
                    try: count=len(self._extract_rows(r.json()))
                    except Exception: count=None
                probes.append({"endpoint":path,"ok":r.ok,"status":r.status_code,"records":count,"elapsed_ms":round((time.monotonic()-started)*1000)})
            except Exception as exc:
                probes.append({"endpoint":path,"ok":False,"status":None,"records":None,"error":str(exc),"elapsed_ms":round((time.monotonic()-started)*1000)})
        now_ms=int(time.time()*1000); start_ms=now_ms-2*86400000
        for label,path in (
            ("gateway_hourly","/proxy/network/api/s/default/stat/report/hourly.gw"),
            ("site_hourly","/proxy/network/api/s/default/stat/report/hourly.site"),
            ("ap_hourly","/proxy/network/api/s/default/stat/report/hourly.ap"),
            ("speedtest_archive","/proxy/network/api/s/default/stat/report/archive.speedtest"),
        ):
            started=time.monotonic()
            try:
                r=self._post(path,{"start":start_ms,"end":now_ms}); rows=self._extract_rows(r.json()) if r.ok else []
                probes.append({"name":label,"endpoint":path,"ok":r.ok,"status":r.status_code,"records":len(rows),"elapsed_ms":round((time.monotonic()-started)*1000)})
            except Exception as exc:
                probes.append({"name":label,"endpoint":path,"ok":False,"status":None,"records":None,"error":str(exc),"elapsed_ms":round((time.monotonic()-started)*1000)})
        return {"ok":any(p.get("ok") for p in probes),"probes":probes}

    def run_speedtest(self) -> dict[str, Any]:
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

    @staticmethod
    def _extract_rows(body: Any) -> list[dict[str, Any]]:
        if isinstance(body, list):
            return [x for x in body if isinstance(x, dict)]
        if not isinstance(body, dict):
            return []
        for key in ("data", "results", "items"):
            value = body.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("results", "items", "speedtests"):
                value = data.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
        return []

    @staticmethod
    def _speed_mbps(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number > 100_000:
            number /= 1_000_000.0
        return number

    def speedtest_history(self, days: int = 365) -> list[dict[str, Any]]:
        days = max(1, min(int(days), 730))
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - days * 86400 * 1000
        attrs = ["time", "datetime", "timestamp", "rundate", "runDate", "xput_download", "xput_upload", "download", "upload", "latency", "latency_avg", "ping", "interface", "wan_group"]
        raw_rows: list[dict[str, Any]] = []
        post_attempts = (
            "/proxy/network/api/s/default/stat/report/archive.speedtest",
            "/proxy/network/api/s/default/stat/report/daily.speedtest",
            "/api/s/default/stat/report/archive.speedtest",
            "/api/s/default/stat/report/daily.speedtest",
        )
        payloads = (
            {"attrs": attrs, "start": start_ms, "end": end_ms},
            {"attrs": attrs, "start": int(start_ms / 1000), "end": int(end_ms / 1000)},
            {"start": start_ms, "end": end_ms},
        )
        for path in post_attempts:
            for payload in payloads:
                try:
                    response = self._post(path, payload)
                    if response.ok:
                        rows = self._extract_rows(response.json())
                        if rows:
                            raw_rows = rows; break
                except Exception:
                    continue
            if raw_rows: break
        if not raw_rows:
            for path in ("/proxy/network/v2/api/site/default/speedtest", "/proxy/network/api/s/default/stat/speedtest", "/api/s/default/stat/speedtest"):
                try:
                    response = self._get(path)
                    if response.ok:
                        rows = self._extract_rows(response.json())
                        if rows:
                            raw_rows = rows; break
                except Exception:
                    continue
        output: list[dict[str, Any]] = []; seen: set[int] = set()
        for row in raw_rows:
            # rundate/runDate are the actual test execution time. A changing status
            # timestamp must never create duplicate speed-test records.
            value = row.get("rundate") or row.get("runDate") or row.get("time") or row.get("timestamp")
            if value is None and row.get("datetime"):
                try: value = datetime.fromisoformat(str(row["datetime"]).replace("Z", "+00:00")).timestamp() * 1000
                except Exception: value = None
            try: epoch_ms = int(float(value))
            except (TypeError, ValueError): continue
            if epoch_ms < 10_000_000_000: epoch_ms *= 1000
            if epoch_ms < start_ms - 86400000 or epoch_ms > end_ms + 86400000 or epoch_ms in seen: continue
            download = self._speed_mbps(row.get("xput_download") or row.get("download") or row.get("download_mbps") or row.get("downloadMbps"))
            upload = self._speed_mbps(row.get("xput_upload") or row.get("upload") or row.get("upload_mbps") or row.get("uploadMbps"))
            latency = self._number(row.get("latency") or row.get("latency_avg") or row.get("ping"))
            if download is None and upload is None: continue
            seen.add(epoch_ms)
            output.append({"epoch_ms":epoch_ms,"ts":self._iso_ms(epoch_ms),"download":download,"upload":upload,"latency":latency,"interface_name":str(row.get("interface") or row.get("interface_name") or ""),"wan_group":str(row.get("wan_group") or row.get("wan_networkgroup") or row.get("wanNetworkGroup") or "WAN")})
        output.sort(key=lambda x: x["epoch_ms"])
        return output

    def retained_history(self, days: int = 365) -> dict[str, list[dict[str, Any]]]:
        days = max(1, min(int(days), 730)); end_ms = int(time.time() * 1000); start_ms = end_ms - (days * 86400 * 1000)
        attrs = ["time", "datetime", "bytes", "num_sta", "wan-rx_bytes", "wan-tx_bytes", "rx_bytes", "tx_bytes"]
        candidates = {"site_daily":"/proxy/network/api/s/default/stat/report/daily.site","gateway_hourly":"/proxy/network/api/s/default/stat/report/hourly.gw","ap_hourly":"/proxy/network/api/s/default/stat/report/hourly.ap","site_hourly":"/proxy/network/api/s/default/stat/report/hourly.site"}
        output: dict[str, list[dict[str, Any]]] = {}
        for name, path in candidates.items():
            rows: list[dict[str, Any]] = []
            try:
                response = self._post(path, {"attrs": attrs, "start": start_ms, "end": end_ms})
                if response.ok: rows = self._extract_rows(response.json())
            except Exception: rows = []
            output[name] = rows
        return output

    def history_probe(self, days: int = 365) -> dict[str, Any]:
        rows_by_source = self.retained_history(days); results: dict[str, Any] = {}; oldest=None; newest=None; total=0
        endpoints={"site_daily":"/proxy/network/api/s/default/stat/report/daily.site","gateway_hourly":"/proxy/network/api/s/default/stat/report/hourly.gw","ap_hourly":"/proxy/network/api/s/default/stat/report/hourly.ap","site_hourly":"/proxy/network/api/s/default/stat/report/hourly.site"}
        for name, rows in rows_by_source.items():
            timestamps=[]
            for row in rows:
                value=row.get("time") or row.get("timestamp")
                try:
                    number=int(float(value)); number=number*1000 if number<10_000_000_000 else number; timestamps.append(number)
                except (TypeError,ValueError): continue
            if timestamps:
                row_oldest,row_newest=min(timestamps),max(timestamps); oldest=row_oldest if oldest is None else min(oldest,row_oldest); newest=row_newest if newest is None else max(newest,row_newest)
            total+=len(rows); results[name]={"available":bool(rows),"records":len(rows),"oldest":self._iso_ms(min(timestamps)) if timestamps else None,"newest":self._iso_ms(max(timestamps)) if timestamps else None,"error":None,"endpoint":endpoints[name]}
        return {"ok":total>0,"requested_days":max(1,min(int(days),730)),"total_records":total,"oldest":self._iso_ms(oldest) if oldest else None,"newest":self._iso_ms(newest) if newest else None,"sources":results,"message":f"Found {total} retained UniFi history records" if total else "No retained history returned by the probed UniFi report endpoints"}

    @staticmethod
    def _iso_ms(value: int) -> str:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()

    def devices(self) -> list[dict[str, Any]]:
        response = self._get("/proxy/network/api/s/default/stat/device"); response.raise_for_status(); payload=response.json()
        if isinstance(payload, dict):
            data=payload.get("data", [])
            if isinstance(data,list): return [row for row in data if isinstance(row,dict)]
        return []

    def snapshot(self) -> dict[str, Any]:
        devices=self.devices(); gateway=None; aps=[]
        for device in devices:
            dtype=str(device.get("type","")).lower()
            if dtype in {"ugw","udm","uxg","gateway"} or "speedtest-status" in device or "wan1" in device: gateway=device
            if dtype=="uap" or device.get("is_access_point") is True: aps.append(device)
        if gateway is None:
            for device in devices:
                if isinstance(device.get("system-stats"),dict) and device.get("ip"): gateway=device; break
        return {"gateway":self._gateway_stats(gateway or {}),"aps":[self._ap_stats(ap) for ap in aps]}

    @staticmethod
    def _number(value: Any, default: float | None = None) -> float | None:
        try:return float(value)
        except (TypeError,ValueError):return default

    def _gateway_stats(self, device: dict[str, Any]) -> dict[str, Any]:
        system=device.get("system-stats") if isinstance(device.get("system-stats"),dict) else {}
        speed=device.get("speedtest-status") if isinstance(device.get("speedtest-status"),dict) else {}
        wan=device.get("wan1") if isinstance(device.get("wan1"),dict) else {}
        uplink=device.get("uplink") if isinstance(device.get("uplink"),dict) else {}
        temperatures=device.get("temperatures") if isinstance(device.get("temperatures"),list) else []
        temp=None
        for item in temperatures:
            if isinstance(item,dict) and str(item.get("type","")).lower()=="cpu": temp=self._number(item.get("value")); break
        wan_ip=wan.get("ip") or uplink.get("ip") or device.get("wan_ip") or device.get("ip")
        if isinstance(device.get("last_wan_status"),dict): wan_up=str(device["last_wan_status"].get("WAN","online")).lower()=="online"
        else: wan_up=bool(wan.get("up",uplink.get("up",True)))
        link_speed=wan.get("speed") or uplink.get("speed")
        speedtest=None
        if speed:
            run=speed.get("rundate") or speed.get("runDate")
            try: epoch_ms=int(float(run)*1000) if run is not None else 0
            except (TypeError,ValueError): epoch_ms=0
            if epoch_ms:
                speedtest={"epoch_ms":epoch_ms,"download":self._number(speed.get("xput_download")),"upload":self._number(speed.get("xput_upload")),"latency":self._number(speed.get("latency")),"interface_name":str(speed.get("source_interface") or speed.get("interface") or ""),"wan_group":str(speed.get("wan_group","WAN"))}
        gateways=uplink.get("gateways") if isinstance(uplink.get("gateways"),list) else []
        wan_dns=wan.get("dns") or uplink.get("dns") or device.get("wan_dns")
        return {
            "name":device.get("name") or device.get("model") or "Gateway",
            "uptime":int(self._number(system.get("uptime") or device.get("uptime"),0) or 0),
            "cpu":self._number(system.get("cpu")),"memory":self._number(system.get("mem")),"temperature":temp,
            "wan_up":bool(wan_up),"wan_ip":wan_ip,"link_speed":int(self._number(link_speed,0) or 0),
            "rx_errors":int(self._number(wan.get("rx_errors",uplink.get("rx_errors",device.get("rx_errors"))),0) or 0),
            "tx_errors":int(self._number(wan.get("tx_errors",uplink.get("tx_errors",device.get("tx_errors"))),0) or 0),
            "rx_dropped":int(self._number(wan.get("rx_dropped",uplink.get("rx_dropped",device.get("rx_dropped"))),0) or 0),
            "tx_dropped":int(self._number(wan.get("tx_dropped",uplink.get("tx_dropped",device.get("tx_dropped"))),0) or 0),
            "rx_rate":self._number(wan.get("rx_rate",uplink.get("rx_rate",device.get("rx_rate"))),0),
            "tx_rate":self._number(wan.get("tx_rate",uplink.get("tx_rate",device.get("tx_rate"))),0),
            "rx_bytes":self._number(wan.get("rx_bytes",uplink.get("rx_bytes"))),"tx_bytes":self._number(wan.get("tx_bytes",uplink.get("tx_bytes"))),
            "wan_interface":wan.get("ifname") or wan.get("name") or uplink.get("name"),"wan_gateway":gateways[0] if gateways else uplink.get("gateway"),"wan_dns":wan_dns,
            "model":device.get("model"),"version":device.get("version"),"mac":device.get("mac"),"lan_ip":device.get("lan_ip") or device.get("ip"),"site":device.get("site_id"),
            "load_average":device.get("load_average"),"clients":device.get("num_sta"),"adopted":device.get("adopted"),"state":device.get("state"),"speedtest":speedtest,
        }

    def _ap_stats(self, device: dict[str, Any]) -> dict[str, Any]:
        radios=device.get("radio_table_stats") if isinstance(device.get("radio_table_stats"),list) else []; rows=[]
        for radio in radios:
            if not isinstance(radio,dict):continue
            code=str(radio.get("radio","")); band="2.4 GHz" if code in {"ng","g"} else "5 GHz" if code in {"na","a"} else code or "Unknown"
            rows.append({"band":band,"channel":int(self._number(radio.get("channel"),0) or 0),"width":int(self._number(radio.get("bw"),0) or 0),"retries":self._number(radio.get("tx_retries_pct"),0),"utilization":self._number(radio.get("cu_total"),0),"clients":int(self._number(radio.get("num_sta"),0) or 0),"satisfaction":self._number(radio.get("satisfaction"),device.get("satisfaction")),"tx_power":self._number(radio.get("tx_power"),0)})
        return {"device_id":device.get("external_id") or device.get("device_id") or device.get("mac"),"name":device.get("name") or device.get("model") or "Access Point","uptime":int(self._number(device.get("uptime"),0) or 0),"cpu":self._number((device.get("system-stats") or {}).get("cpu") if isinstance(device.get("system-stats"),dict) else None),"memory":self._number((device.get("system-stats") or {}).get("mem") if isinstance(device.get("system-stats"),dict) else None),"radios":rows}
