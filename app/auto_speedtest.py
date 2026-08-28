from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from app.database import connect
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings, get_secret

POLL_SECONDS = 15
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 1440


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _interval_minutes(cfg: dict) -> int:
    try:
        minutes = int(float(cfg.get("speedtest_minutes") or 15))
    except (TypeError, ValueError):
        minutes = 15
    return max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, minutes))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _set_runtime_state(**values: object) -> None:
    con = connect()
    try:
        for key, value in values.items():
            con.execute(
                """INSERT INTO settings(setting_key, setting_value, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(setting_key) DO UPDATE SET
                     setting_value=excluded.setting_value,
                     updated_at=CURRENT_TIMESTAMP""",
                (key, "" if value is None else str(value)),
            )
        con.commit()
    finally:
        con.close()


def _schedule_from(now: datetime, minutes: int) -> str:
    return (now + timedelta(minutes=minutes)).isoformat()


def run_forever() -> None:
    print("auto-speedtest: worker started")
    while True:
        try:
            cfg = all_settings()
            enabled = _bool(cfg.get("speedtest_auto_enabled"), True)
            isp_enabled = _bool(cfg.get("isp_enabled"), True)
            unifi_enabled = _bool(cfg.get("unifi_enabled"), False)
            minutes = _interval_minutes(cfg)
            now = datetime.now(timezone.utc)

            if not enabled:
                _set_runtime_state(speedtest_auto_state="disabled", speedtest_next_auto_at="", speedtest_auto_first_due_at="")
                time.sleep(POLL_SECONDS)
                continue

            if not isp_enabled or not unifi_enabled:
                _set_runtime_state(speedtest_auto_state="waiting for ISP/UniFi to be enabled", speedtest_next_auto_at="", speedtest_auto_first_due_at="")
                time.sleep(POLL_SECONDS)
                continue

            url = str(cfg.get("unifi_url") or "").strip()
            api_key = get_secret("unifi_api_key") or ""
            if not url or not api_key:
                _set_runtime_state(speedtest_auto_state="waiting for UniFi configuration", speedtest_next_auto_at="", speedtest_auto_first_due_at="")
                time.sleep(POLL_SECONDS)
                continue

            last_started = _parse_iso(cfg.get("speedtest_last_auto_at"))
            if last_started is None:
                first_due = _parse_iso(cfg.get("speedtest_auto_first_due_at"))
                if first_due is None:
                    first_due = now + timedelta(seconds=45)
                    _set_runtime_state(
                        speedtest_auto_state="scheduled",
                        speedtest_auto_first_due_at=first_due.isoformat(),
                        speedtest_next_auto_at=first_due.isoformat(),
                    )
                    time.sleep(POLL_SECONDS)
                    continue
                next_due = first_due
            else:
                next_due = last_started + timedelta(minutes=minutes)

            if now < next_due:
                _set_runtime_state(speedtest_auto_state="scheduled", speedtest_next_auto_at=next_due.isoformat())
                time.sleep(POLL_SECONDS)
                continue

            _set_runtime_state(speedtest_auto_state="starting", speedtest_next_auto_at="")
            client = UniFiClient(url, api_key, str(cfg.get("unifi_verify_ssl") or "false").lower() == "true")
            result = client.run_speedtest()
            if result.get("ok"):
                started_at = _iso_now()
                started_dt = _parse_iso(started_at) or now
                _set_runtime_state(
                    speedtest_last_auto_at=started_at,
                    speedtest_next_auto_at=_schedule_from(started_dt, minutes),
                    speedtest_auto_first_due_at="",
                    speedtest_auto_state="started successfully",
                    speedtest_auto_last_message=result.get("message") or "UniFi speed test started",
                )
                print(f"auto-speedtest: started UniFi test; next in {minutes} minutes")
            else:
                retry_at = now + timedelta(minutes=5)
                _set_runtime_state(
                    speedtest_auto_state="failed",
                    speedtest_next_auto_at=retry_at.isoformat(),
                    speedtest_auto_first_due_at=retry_at.isoformat(),
                    speedtest_auto_last_message=result.get("message") or "Unable to start UniFi speed test",
                )
                print(f"auto-speedtest: start failed: {result.get('message')}")
        except Exception as exc:
            try:
                _set_runtime_state(speedtest_auto_state="error", speedtest_auto_last_message=str(exc))
            except Exception:
                pass
            print(f"auto-speedtest: worker error: {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
