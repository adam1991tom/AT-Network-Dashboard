from __future__ import annotations

from fastapi import APIRouter, Query

from app.database import connect
from app.monitoring import (
    gateway_history,
    live_snapshot,
    ping_history,
    speedtest_history,
    ups_history,
    wifi_history,
)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/live")
def live() -> dict:
    return live_snapshot()


@router.get("/ping")
def ping(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return ping_history(hours)


@router.get("/speedtests")
def speedtests(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return speedtest_history(hours)


@router.get("/gateway")
def gateway(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return gateway_history(hours)


@router.get("/ups")
def ups(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return ups_history(hours)


@router.get("/wifi")
def wifi(hours: int = Query(24, ge=1, le=8760)) -> list[dict]:
    return wifi_history(hours)


@router.get("/unifi-wan")
def unifi_wan(hours: int = Query(24, ge=1, le=17520)) -> list[dict]:
    """Imported UniFi retained WAN report history.

    For longer views prefer the daily site buckets because the controller only
    retains hourly gateway data for roughly a week.
    """
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


@router.get("/unifi-ap-traffic")
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
