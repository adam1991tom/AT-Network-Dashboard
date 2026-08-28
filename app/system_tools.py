from __future__ import annotations
import io,sqlite3,zipfile
from datetime import datetime,timedelta,timezone
from app.database import DB_PATH,connect

TABLES=('speedtest_history','ping_history','gateway_history','wifi_history','ups_history','incidents','unifi_wan_history','unifi_ap_traffic_history')
def _exists(con,t):return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone())
def status():
 con=connect();out={"database_bytes":DB_PATH.stat().st_size if DB_PATH.exists() else 0,"tables":{}}
 try:
  for t in TABLES:
   if not _exists(con,t):continue
   cols={r[1] for r in con.execute(f'PRAGMA table_info({t})')};tc='ts' if 'ts' in cols else ('started_at' if 'started_at' in cols else None);count=con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0];old=new=None
   if tc:old,new=con.execute(f'SELECT MIN({tc}),MAX({tc}) FROM {t}').fetchone()
   out['tables'][t]={"count":count,"oldest":old,"newest":new}
  return out
 finally:con.close()
def apply_retention(days:int):
 days=max(0,int(days));
 if not days:return {"ok":True,"deleted":0}
 cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat();con=connect();deleted=0
 try:
  for t in ('speedtest_history','ping_history','gateway_history','wifi_history','ups_history','unifi_wan_history','unifi_ap_traffic_history'):
   if _exists(con,t):
    cur=con.execute(f'DELETE FROM {t} WHERE datetime(ts)<datetime(?)',(cutoff,));deleted+=max(cur.rowcount,0)
  con.commit();return {"ok":True,"deleted":deleted,"cutoff":cutoff}
 finally:con.close()
def backup_bytes():
 memory=io.BytesIO();snap=sqlite3.connect(':memory:');src=sqlite3.connect(DB_PATH);src.backup(snap);src.close();dump='\n'.join(snap.iterdump());snap.close()
 with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('network-dashboard.sql',dump);z.writestr('README.txt','AT Network Dashboard backup. Contains local settings/history and may contain encrypted integration secrets. Store securely.')
 return memory.getvalue()
