from __future__ import annotations

import json
import ssl
from urllib.parse import quote
from urllib.request import Request, urlopen


class UptimeKumaClient:
    """Read-only Uptime Kuma integration using the public status-page API.

    This deliberately does not touch Kuma's database. A status-page slug exposes
    monitor metadata and heartbeats; an optional API key is sent as Bearer auth
    for installations/proxies that require it.
    """

    def __init__(self, base_url: str, status_slug: str = "", api_key: str = "", verify_ssl: bool = False):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.status_slug = (status_slug or "").strip().strip("/")
        self.api_key = (api_key or "").strip()
        self.verify_ssl = bool(verify_ssl)

    def _get(self, path: str, timeout: int = 10):
        headers={"Accept":"application/json","User-Agent":"AT-Network-Dashboard/3.4"}
        if self.api_key: headers["Authorization"] = f"Bearer {self.api_key}"
        context=None
        if self.base_url.lower().startswith("https://") and not self.verify_ssl:
            context=ssl._create_unverified_context()
        req=Request(f"{self.base_url}{path}",headers=headers,method="GET")
        with urlopen(req,timeout=timeout,context=context) as response:
            return json.loads(response.read().decode("utf-8"))

    def _slug(self) -> str:
        if not self.status_slug: raise ValueError("Enter the Uptime Kuma status-page slug")
        return quote(self.status_slug,safe="")

    def snapshot(self) -> dict:
        if not self.base_url: raise ValueError("Enter the Uptime Kuma URL / IP")
        slug=self._slug()
        page=self._get(f"/api/status-page/{slug}")
        beats=self._get(f"/api/status-page/heartbeat/{slug}")
        heartbeat_list=beats.get("heartbeatList") or {}
        uptime_list=beats.get("uptimeList") or {}
        monitors=[]
        for group in page.get("publicGroupList") or []:
            for monitor in group.get("monitorList") or []:
                mid=str(monitor.get("id") or "")
                history=heartbeat_list.get(mid) or heartbeat_list.get(int(mid) if mid.isdigit() else mid) or []
                latest=history[-1] if history else {}
                status=int(latest.get("status") or 0) if latest else 0
                uptime=None
                for key,value in uptime_list.items():
                    if str(key).startswith(f"{mid}_"):
                        try: uptime=float(value)*100
                        except Exception: pass
                        if str(key).endswith("_24"): break
                monitors.append({
                    "id":monitor.get("id"),"name":monitor.get("name") or f"Monitor {mid}","type":monitor.get("type"),"url":monitor.get("url"),
                    "status":status,"status_text":"UP" if status==1 else ("PENDING" if status==2 else "DOWN"),
                    "ping":latest.get("ping"),"message":latest.get("msg") or "","time":latest.get("time"),"uptime_24h":uptime,
                })
        counts={"up":sum(1 for m in monitors if m["status"]==1),"down":sum(1 for m in monitors if m["status"]==0),"pending":sum(1 for m in monitors if m["status"]==2)}
        return {"ok":True,"title":page.get("config",{}).get("title") or "Uptime Kuma","slug":self.status_slug,"counts":counts,"total":len(monitors),"monitors":monitors}

    def test_connection(self) -> dict:
        try:
            data=self.snapshot(); c=data["counts"]
            return {"ok":True,"message":f"Connected · {data['total']} monitors · {c['up']} up · {c['down']} down","total":data["total"],"counts":c}
        except Exception as exc:
            return {"ok":False,"message":str(exc)}
