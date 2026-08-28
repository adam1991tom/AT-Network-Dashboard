"""One-time v3 speed-test reconciliation against the UniFi controller archive."""
from __future__ import annotations
from app import monitoring_v23
from app.database import connect
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings,get_secret

_KEY='speedtest_authoritative_reconcile_v3'
_original=monitoring_v23.start_monitoring

def _reconcile():
 cfg=all_settings()
 if str(cfg.get(_KEY,'')).lower()=='true':return
 if str(cfg.get('unifi_enabled','false')).lower()!='true':return
 url=str(cfg.get('unifi_url') or '').strip();key=get_secret('unifi_api_key') or ''
 if not url or not key:return
 try:days=max(90,min(730,int(float(cfg.get('retention_days') or 365)) or 365))
 except Exception:days=365
 client=UniFiClient(url,key,str(cfg.get('unifi_verify_ssl') or 'false').lower()=='true')
 rows=client.speedtest_history(days)
 if not rows:
  print('speedtest reconcile: controller returned no archive rows; database left unchanged');return
 con=connect()
 try:
  before=con.execute("SELECT COUNT(*) FROM speedtest_history WHERE source LIKE 'unifi%'").fetchone()[0]
  con.execute("DELETE FROM speedtest_history WHERE source LIKE 'unifi%'")
  inserted=0
  for r in rows:
   epoch=int(r.get('epoch_ms') or 0)
   if not epoch:continue
   cur=con.execute('INSERT OR IGNORE INTO speedtest_history(ts,epoch_ms,download,upload,latency,interface_name,wan_group,source) VALUES (?,?,?,?,?,?,?,?)',(r.get('ts'),epoch,r.get('download'),r.get('upload'),r.get('latency'),r.get('interface_name'),r.get('wan_group') or 'WAN','unifi-history'))
   inserted+=max(cur.rowcount,0)
  con.execute("INSERT INTO settings(setting_key,setting_value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP",(_KEY,'true'))
  con.commit();print(f'speedtest reconcile: rebuilt UniFi history {before} -> {inserted} authoritative rows')
 finally:con.close()

def _start():
 try:_reconcile()
 except Exception as exc:print(f'speedtest reconcile failed: {exc}')
 _original()
monitoring_v23.start_monitoring=_start
