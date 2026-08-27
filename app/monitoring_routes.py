from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.database import connect
from app.monitoring import (
    gateway_history,
    live_snapshot,
    ping_history,
    speedtest_history,
    ups_history,
    wifi_history,
)

router = APIRouter(tags=["monitoring"])
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"]))
VERSION = "2.0.0-dev8"


@router.get("/api/monitoring/live")
def live() -> dict:
    return live_snapshot()


@router.get("/api/monitoring/ping")
def ping(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return ping_history(hours)


@router.get("/api/monitoring/speedtests")
def speedtests(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return speedtest_history(hours)


@router.get("/api/monitoring/gateway")
def gateway(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return gateway_history(hours)


@router.get("/api/monitoring/ups")
def ups(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return ups_history(hours)


@router.get("/api/monitoring/wifi")
def wifi(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return wifi_history(hours)


@router.get("/api/monitoring/unifi-wan")
def unifi_wan(hours: int = Query(24, ge=1, le=17520)) -> list[dict]:
    con = connect()
    try:
        if hours > 24 * 14:
            rows = con.execute(
                """SELECT ts,bucket,scope,object_id,clients,rx_bytes,tx_bytes
                   FROM unifi_wan_history
                   WHERE bucket='daily' AND scope='site'
                     AND datetime(ts) >= datetime('now', ?)
                   ORDER BY datetime(ts) ASC""",
                (f"-{hours} hours",),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT ts,bucket,scope,object_id,clients,rx_bytes,tx_bytes
                   FROM unifi_wan_history
                   WHERE bucket='hourly' AND scope='gateway'
                     AND datetime(ts) >= datetime('now', ?)
                   ORDER BY datetime(ts) ASC""",
                (f"-{hours} hours",),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


@router.get("/api/monitoring/unifi-ap-traffic")
def unifi_ap_traffic(hours: int = Query(24, ge=1, le=17520)) -> list[dict]:
    con = connect()
    try:
        rows = con.execute(
            """SELECT ts,device_id,clients,bytes,rx_bytes,tx_bytes
               FROM unifi_ap_traffic_history
               WHERE datetime(ts) >= datetime('now', ?)
               ORDER BY datetime(ts) ASC""",
            (f"-{hours} hours",),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


@router.get("/incidents", response_class=HTMLResponse)
def incidents_page(request: Request) -> HTMLResponse:
    con = connect()
    try:
        rows = con.execute(
            "SELECT id,incident_type,severity,started_at,ended_at,summary,details,active FROM incidents ORDER BY active DESC,id DESC LIMIT 250"
        ).fetchall()
        incidents = [dict(row) for row in rows]
    finally:
        con.close()
    return HTMLResponse(templates.get_template("incidents.html").render(request=request, version=VERSION, page="incidents", title="Incidents", incidents=incidents))


@router.get("/wifi", response_class=HTMLResponse)
def wifi_page(request: Request) -> HTMLResponse:
    return HTMLResponse(templates.get_template("wifi.html").render(request=request, version=VERSION, page="wifi", title="Wi-Fi"))


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request) -> HTMLResponse:
    con = connect()
    try:
        def count(table: str) -> int:
            try:
                return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except Exception:
                return 0
        counts = {
            "speedtests": count("speedtest_history"),
            "ping": count("ping_history"),
            "gateway": count("gateway_history"),
            "ups": count("ups_history"),
            "wifi": count("wifi_history"),
            "wan": count("unifi_wan_history"),
        }
    finally:
        con.close()
    return HTMLResponse(templates.get_template("reports.html").render(request=request, version=VERSION, page="reports", title="Reports", counts=counts))


def _csv_response(table: str, filename: str) -> Response:
    con = connect()
    try:
        rows = con.execute(f"SELECT * FROM {table} ORDER BY id ASC").fetchall()
        headers = [d[0] for d in con.execute(f"SELECT * FROM {table} LIMIT 0").description]
    finally:
        con.close()
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row[h] for h in headers])
    return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/api/reports/export/speedtests.csv")
def export_speedtests() -> Response:
    return _csv_response("speedtest_history", "at-network-speedtests.csv")


@router.get("/api/reports/export/ping.csv")
def export_ping() -> Response:
    return _csv_response("ping_history", "at-network-ping.csv")


@router.get("/api/reports/export/gateway.csv")
def export_gateway() -> Response:
    return _csv_response("gateway_history", "at-network-gateway.csv")


@router.get("/api/reports/export/ups.csv")
def export_ups() -> Response:
    return _csv_response("ups_history", "at-network-ups.csv")


@router.get("/api/reports/export/wifi.csv")
def export_wifi() -> Response:
    return _csv_response("wifi_history", "at-network-wifi.csv")


@router.get("/api/reports/export/wan.csv")
def export_wan() -> Response:
    return _csv_response("unifi_wan_history", "at-network-unifi-wan.csv")
