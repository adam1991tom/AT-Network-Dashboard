"""Runtime fixes for UniFi speed-test timestamps.

UniFi's speedtest-status object can expose a changing status timestamp alongside
an actual test run time.  Only the real run time is safe to use as a database
identity.  Falling back to the status timestamp creates hundreds of duplicate
rows for one real test.
"""
from __future__ import annotations

from typing import Any

from app.integrations.unifi import UniFiClient

_original_gateway_stats = UniFiClient._gateway_stats


def _real_speedtest_epoch(speed: dict[str, Any]) -> int:
    # Deliberately DO NOT use speed["timestamp"] here. On UniFi gateways that
    # value can change while the same speed-test result remains published.
    value = speed.get("rundate") or speed.get("runDate") or speed.get("run_date") or speed.get("last_run") or speed.get("time") or 0
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
        # Zero means "do not persist this live result". The historical UniFi
        # endpoint will still import it using its genuine run timestamp.
        current["epoch_ms"] = _real_speedtest_epoch(raw)
    return result


UniFiClient._gateway_stats = _gateway_stats_with_real_speedtest_time
