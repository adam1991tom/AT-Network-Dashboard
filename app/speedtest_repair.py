from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database import connect

_REPAIR_KEY = "speedtest_real_rundate_cleanup_v1"


def repair_legacy_speedtests() -> dict[str, int | bool]:
    """Remove legacy live rows created from UniFi's changing status timestamp.

    Historical UniFi rows are authoritative and are never deleted here.  Old
    live rows are removed because they were created by the pre-fix collector;
    the archive sync repopulates genuine tests with their actual run times.
    A short recent window is retained so a just-finished test can remain visible
    until the controller's history endpoint catches up.
    """
    con = connect()
    try:
        done = con.execute("SELECT setting_value FROM settings WHERE setting_key=?", (_REPAIR_KEY,)).fetchone()
        if done and str(done[0]).lower() == "true":
            return {"ok": True, "deleted": 0, "already_done": True}

        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        before = con.execute("SELECT COUNT(*) FROM speedtest_history WHERE source='unifi-live'").fetchone()[0]
        cur = con.execute(
            "DELETE FROM speedtest_history WHERE source='unifi-live' AND julianday(ts) < julianday(?)",
            (cutoff,),
        )
        deleted = max(cur.rowcount, 0)

        # Also collapse any remaining rapid duplicate live rows that share the
        # same measurements inside a five-minute window. Keep the oldest row in
        # each cluster. This catches recent leftovers without touching history.
        rows = con.execute(
            "SELECT id,ts,download,upload,latency FROM speedtest_history WHERE source='unifi-live' ORDER BY julianday(ts),id"
        ).fetchall()
        keep_id = None
        keep_ts = None
        keep_sig = None
        extra_ids: list[int] = []
        for row in rows:
            try:
                t = datetime.fromisoformat(str(row['ts']).replace('Z', '+00:00'))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            sig = (
                round(float(row['download'] or 0), 3),
                round(float(row['upload'] or 0), 3),
                round(float(row['latency'] or 0), 3),
            )
            if keep_sig == sig and keep_ts is not None and (t - keep_ts).total_seconds() <= 300:
                extra_ids.append(int(row['id']))
                continue
            keep_id = int(row['id'])
            keep_ts = t
            keep_sig = sig
        if extra_ids:
            con.executemany("DELETE FROM speedtest_history WHERE id=?", [(i,) for i in extra_ids])
            deleted += len(extra_ids)

        con.execute(
            "INSERT INTO settings(setting_key,setting_value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP",
            (_REPAIR_KEY, "true"),
        )
        con.commit()
        after = con.execute("SELECT COUNT(*) FROM speedtest_history WHERE source='unifi-live'").fetchone()[0]
        print(f"speedtest repair: removed {deleted} legacy live rows ({before} -> {after})")
        return {"ok": True, "deleted": deleted, "already_done": False}
    finally:
        con.close()
