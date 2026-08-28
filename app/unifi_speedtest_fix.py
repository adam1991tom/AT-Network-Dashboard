"""Runtime fixes for UniFi speed-test timestamps.

UniFi's speedtest-status object can contain both a status timestamp that changes
while the same result remains published and a rundate that identifies the real
test execution time.  AT Network Dashboard must key stored tests by rundate or
it creates a new copy of the same speed-test result every monitoring cycle.
"""
from __future__ import annotations

from typing import Any

from app.integrations.unifi import UniFiClient

_original_gateway_stats = UniFiClient._gateway_stats


def _real_speedtest_epoch(speed: dict[str, Any]) -> int:
    value = (
        speed.get("rundate")
        or speed.get("runDate")
        or speed.get("time")
        or speed.get("timestamp")
        or 0
    )
    try:
        epoch = int(float(value))
    except (TypeError, ValueError):
        return 0
    if 0 < epoch < 10_000_000_000:
        epoch *= 1000
    return epoch


def _gateway_stats_with_real_speedtest_time(self: UniFiClient, device: dict[str, Any]) -> dict[str, Any]:
    result = _original_gateway_stats(self, device)
    raw = device.get("speedtest-status") if isinstance(device.get("speedtest-status"), dict) else {}
    current = result.get("speedtest") if isinstance(result.get("speedtest"), dict) else None
    if current and raw:
        epoch = _real_speedtest_epoch(raw)
        if epoch:
            current["epoch_ms"] = epoch
    return result


UniFiClient._gateway_stats = _gateway_stats_with_real_speedtest_time
