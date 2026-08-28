"""Run the one-time speed-test cleanup immediately before monitoring starts."""
from __future__ import annotations

from app import monitoring_v23
from app.speedtest_repair import repair_legacy_speedtests

_original_start_monitoring = monitoring_v23.start_monitoring


def _start_monitoring_with_speedtest_repair() -> None:
    try:
        repair_legacy_speedtests()
    except Exception as exc:
        # Never stop monitoring just because an old database cannot be repaired.
        print(f"speedtest repair failed: {exc}")
    _original_start_monitoring()


monitoring_v23.start_monitoring = _start_monitoring_with_speedtest_repair
