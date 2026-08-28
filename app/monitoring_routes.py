from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.database import connect
from app.isp_report import build_evidence_zip, build_pdf
from app.monitoring import live_snapshot
from app.version import APP_VERSION

router = APIRouter(tags=["monitoring"])
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"]))
VERSION = APP_VERSION


def _cutoff(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _rows(table: str, columns: str, hours: int, where: str = "", params: tuple = ()) -> list[dict]:
    con = connect()
    try:
        sql = f"SELECT {columns} FROM {table} WHERE julianday(ts)>=julianday(?)"
        values: list[object] = [_cutoff(hours)]
        if where:
            sql += f" AND {where}"
            values.extend(params)
        sql += " ORDER BY julianday(ts), id"
        return [dict(r) for r in con.execute(sql, tuple(values)).fetchall()]
    finally:
        con.close()


def _preserve_extremes(rows: list[dict], fields: tuple[str, ...], max_rows: int = 1800) -> list[dict]:
    if len(rows) <= max_rows:
        return rows
    bucket_count = max(1, max_rows // max(2, len(fields) * 2))
    size = max(1, (len(rows) + bucket_count - 1) // bucket_count)
    chosen: dict[int, dict] = {0: rows[0], len(rows) - 1: rows[-1]}
    for start in range(0, len(rows), size):
        chunk = rows[start : start + size]
        if not chunk:
            continue
        chosen[start] = chunk[0]
        chosen[min(len(rows) - 1, start + len(chunk) - 1)] = chunk[-1]
        for field in fields:
            vals = [(i, r.get(field)) for i, r in enumerate(chunk) if isinstance(r.get(field), (int, float))]
            if vals:
                lo = min(vals, key=lambda x: x[1])[0]
                hi = max(vals, key=lambda x: x[1])[0]
                chosen[start + lo] = chunk[lo]
                chosen[start + hi] = chunk[hi]
    return [chosen[i] for i in sorted(chosen)]


def _wifi_rows(hours: int, limit: int = 0) -> list[dict]:
    rows = _rows("wifi_history", "id,ts,device_id,ap_name,band,channel,width,retries,utilization,clients,satisfaction,tx_power", hours)
    if limit:
        return rows[-limit:]
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("device_id") or row.get("ap_name") or ""), str(row.get("band") or ""))].append(row)
    out: list[dict] = []
    per_series = max(180, min(900, 5000 // max(1, len(grouped))))
    for series in grouped.values():
        out.extend(_preserve_extremes(series, ("retries", "utilization", "clients", "satisfaction"), per_series))
    out.sort(key=lambda r: str(r.get("ts") or ""))
    return out


@router.get("/api/monitoring/live")
def live(): return live_snapshot()

@router.get("/api/monitoring/ping")
def ping(hours: int = Query(24, ge=1, le=8760)):
    return _preserve_extremes(_rows("ping_history", "id,ts,target,latency,packet_loss,online", hours), ("latency", "packet_loss"), 1800)

@router.get("/api/monitoring/speedtests")
def speedtests(hours: int = Query(24, ge=1, le=8760)):
    rows = _rows("speedtest_history", "id,ts,epoch_ms,download,upload,latency,interface_name,wan_group,source", hours)
    return _preserve_extremes(rows, ("download", "upload", "latency"), 5000)

@router.get("/api/monitoring/gateway")
def gateway(hours: int = Query(24, ge=1, le=8760)):
    rows = _rows("gateway_history", "id,ts,uptime,cpu,memory,temperature,wan_up,wan_ip,link_speed,rx_errors,tx_errors,rx_dropped,tx_dropped,rx_rate,tx_rate", hours)
    return _preserve_extremes(rows, ("cpu", "memory", "temperature", "rx_rate", "tx_rate"), 1800)

@router.get("/api/monitoring/ups")
def ups(hours: int = Query(24, ge=1, le=8760)):
    rows = _rows("ups_history", "id,ts,connected,status,load_pct,input_voltage,output_voltage,battery_voltage,input_frequency,runtime_seconds", hours)
    return _preserve_extremes(rows, ("load_pct", "input_voltage", "output_voltage", "battery_voltage"), 1800)

@router.get("/api/monitoring/wifi")
def wifi(hours: int = Query(24, ge=1, le=8760), limit: int = Query(0, ge=0, le=10000)):
    return _wifi_rows(hours, limit)

@router.get("/api/monitoring/unifi-wan")
def unifi_wan(hours: int = Query(24, ge=1, le=17520)):
    if hours > 24 * 14:
        rows = _rows("unifi_wan_history", "id,ts,bucket,scope,object_id,clients,rx_bytes,tx_bytes", hours, "bucket='daily' AND scope='site'")
    else:
        rows = _rows("unifi_wan_history", "id,ts,bucket,scope,object_id,clients,rx_bytes,tx_bytes", hours, "bucket='hourly' AND scope='gateway'")
    return _preserve_extremes(rows, ("rx_bytes", "tx_bytes", "clients"), 1800)

@router.get("/api/monitoring/unifi-ap-traffic")
def unifi_ap_traffic(hours: int = Query(24, ge=1, le=17520)):
    rows = _rows("unifi_ap_traffic_history", "id,ts,device_id,clients,bytes,rx_bytes,tx_bytes", hours)
    return _preserve_extremes(rows, ("clients", "bytes", "rx_bytes", "tx_bytes"), 2200)

@router.get("/api/incidents")
def incidents_api(limit: int = Query(1000, ge=1, le=5000)):
    con = connect()
    try:
        return {"items": [dict(r) for r in con.execute("SELECT id,incident_type,incident_key,category,device,severity,started_at,ended_at,last_seen_at,summary,details,active,operator_note,fault_reference FROM incidents ORDER BY active DESC,id DESC LIMIT ?", (limit,)).fetchall()]}
    finally: con.close()

@router.get("/incidents", response_class=HTMLResponse)
def incidents_page(request: Request):
    con = connect()
    try:
        items = [dict(r) for r in con.execute("SELECT id,incident_type,incident_key,category,device,severity,started_at,ended_at,last_seen_at,summary,details,active,operator_note,fault_reference FROM incidents ORDER BY active DESC,id DESC LIMIT 2000").fetchall()]
    finally: con.close()
    return HTMLResponse(templates.get_template("incidents.html").render(request=request, version=VERSION, page="incidents", title="Incidents", incidents=items))

@router.get("/wifi", response_class=HTMLResponse)
def wifi_page(request: Request):
    return HTMLResponse(templates.get_template("wifi.html").render(request=request, version=VERSION, page="wifi", title="Wi-Fi"))

@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    con = connect()
    try:
        def count(table):
            try: return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except Exception: return 0
        incident_count = int(con.execute("SELECT COUNT(*) FROM incidents WHERE category IN ('ISP','Internet','Gateway')").fetchone()[0])
        counts = {"speedtests": count("speedtest_history"), "ping": count("ping_history"), "gateway": count("gateway_history"), "wan": count("unifi_wan_history"), "incidents": incident_count}
    finally: con.close()
    return HTMLResponse(templates.get_template("reports.html").render(request=request, version=VERSION, page="reports", title="Reports", counts=counts))


def _range(start, end, hours=None):
    now = datetime.now(timezone.utc)
    if start and end:
        try:
            s = datetime.fromisoformat(start.replace("Z", "+00:00")); e = datetime.fromisoformat(end.replace("Z", "+00:00"))
            s = s if s.tzinfo else s.replace(tzinfo=timezone.utc); e = e if e.tzinfo else e.replace(tzinfo=timezone.utc)
            return s.astimezone(timezone.utc).isoformat(), e.astimezone(timezone.utc).isoformat()
        except Exception: pass
    h = max(1, min(int(hours or 168), 2160))
    return (now - timedelta(hours=h)).isoformat(), now.isoformat()

@router.get("/api/reports/isp.pdf")
def isp_pdf(start: str | None = None, end: str | None = None, hours: int | None = Query(None, ge=1, le=2160)):
    s, e = _range(start, end, hours)
    return Response(build_pdf(s, e), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="AT-Internet-Performance-Report.pdf"'})

@router.get("/api/reports/isp-evidence.zip")
def isp_evidence(start: str | None = None, end: str | None = None, hours: int | None = Query(None, ge=1, le=2160)):
    s, e = _range(start, end, hours)
    return Response(build_evidence_zip(s, e), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="AT-Internet-Evidence.zip"'})


def _csv_response(table, filename):
    con = connect()
    try:
        cur = con.execute(f"SELECT * FROM {table} ORDER BY id")
        headers = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally: con.close()
    stream = io.StringIO(); w = csv.writer(stream); w.writerow(headers)
    for row in rows: w.writerow([row[h] for h in headers])
    return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@router.get("/api/reports/export/speedtests.csv")
def export_speedtests(): return _csv_response("speedtest_history", "at-network-speedtests.csv")
@router.get("/api/reports/export/ping.csv")
def export_ping(): return _csv_response("ping_history", "at-network-ping.csv")
@router.get("/api/reports/export/gateway.csv")
def export_gateway(): return _csv_response("gateway_history", "at-network-gateway.csv")
@router.get("/api/reports/export/wan.csv")
def export_wan(): return _csv_response("unifi_wan_history", "at-network-unifi-wan.csv")
