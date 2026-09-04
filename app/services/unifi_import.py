from __future__ import annotations
from typing import Any

from app.database import connect
from app.integrations.unifi import UniFiClient


def import_retained_history(client: UniFiClient, days: int) -> dict[str, Any]:
    history = client.retained_history(days)
    inserted_wan = 0
    inserted_ap = 0
    con = connect()
    try:
        for source, rows in history.items():
            for row in rows:
                try:
                    epoch_ms = int(float(row.get("time")))
                except Exception:
                    continue
                ts = str(row.get("datetime") or "").strip()
                if not ts:
                    continue
                if source == "ap_hourly":
                    device_id = str(row.get("ap") or row.get("oid") or "").strip()
                    if not device_id:
                        continue
                    cur = con.execute(
                        "INSERT OR IGNORE INTO unifi_ap_traffic_history(ts,epoch_ms,device_id,clients,bytes,rx_bytes,tx_bytes) VALUES (?,?,?,?,?,?,?)",
                        (ts, epoch_ms, device_id, row.get("num_sta"), row.get("bytes"), row.get("rx_bytes"), row.get("tx_bytes")),
                    )
                    inserted_ap += max(cur.rowcount, 0)
                elif source in {"gateway_hourly", "site_hourly", "site_daily"}:
                    scope = "gateway" if source == "gateway_hourly" else "site"
                    bucket = "daily" if source == "site_daily" else "hourly"
                    object_id = str(row.get("gw") or row.get("site") or row.get("oid") or "").strip()
                    if not object_id:
                        continue
                    cur = con.execute(
                        "INSERT OR IGNORE INTO unifi_wan_history(ts,epoch_ms,bucket,scope,object_id,clients,rx_bytes,tx_bytes) VALUES (?,?,?,?,?,?,?,?)",
                        (ts, epoch_ms, bucket, scope, object_id, row.get("num_sta"), row.get("wan-rx_bytes"), row.get("wan-tx_bytes")),
                    )
                    inserted_wan += max(cur.rowcount, 0)
        con.commit()
        totals = {
            "wan": con.execute("SELECT COUNT(*) FROM unifi_wan_history").fetchone()[0],
            "ap": con.execute("SELECT COUNT(*) FROM unifi_ap_traffic_history").fetchone()[0],
        }
    finally:
        con.close()
    return {
        "ok": True,
        "message": f"Imported {inserted_wan + inserted_ap} new UniFi history records",
        "inserted": {"wan": inserted_wan, "ap": inserted_ap},
        "totals": totals,
    }
