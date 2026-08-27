from __future__ import annotations

from fastapi import APIRouter, Query

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
