"""Use UniFi's real speed-test run time for archive reconciliation."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Any
from app.integrations.unifi import UniFiClient


def _rows(body:Any):
 if isinstance(body,list):return [x for x in body if isinstance(x,dict)]
 if not isinstance(body,dict):return []
 for k in ('data','results','items'):
  v=body.get(k)
  if isinstance(v,list):return [x for x in v if isinstance(x,dict)]
  if isinstance(v,dict):
   for q in ('results','items','speedtests'):
    z=v.get(q)
    if isinstance(z,list):return [x for x in z if isinstance(x,dict)]
 return []

def _epoch(row:dict)->int:
 # rundate/runDate identify the actual execution. Generic status timestamps are last-resort
 # only for archive rows that have no explicit run field.
 v=row.get('rundate') or row.get('runDate') or row.get('run_date') or row.get('last_run') or row.get('time')
 if v is None and row.get('datetime'):
  try:v=datetime.fromisoformat(str(row['datetime']).replace('Z','+00:00')).timestamp()*1000
  except Exception:v=None
 if v is None:return 0
 try:e=int(float(v))
 except Exception:return 0
 if 0<e<10_000_000_000:e*=1000
 return e

def fixed_speedtest_history(self:UniFiClient,days:int=365):
 days=max(1,min(int(days),730));end=int(time.time()*1000);start=end-days*86400000
 attrs=['time','datetime','timestamp','rundate','runDate','xput_download','xput_upload','download','upload','latency','latency_avg','ping','interface','wan_group']
 raw=[]
 for path in ('/proxy/network/api/s/default/stat/report/archive.speedtest','/proxy/network/api/s/default/stat/report/daily.speedtest','/api/s/default/stat/report/archive.speedtest','/api/s/default/stat/report/daily.speedtest'):
  for payload in ({'attrs':attrs,'start':start,'end':end},{'attrs':attrs,'start':start//1000,'end':end//1000},{'start':start,'end':end}):
   try:
    r=self._post(path,payload)
    if r.ok:
     q=_rows(r.json())
     if q:raw=q;break
   except Exception:pass
  if raw:break
 if not raw:
  for path in ('/proxy/network/v2/api/site/default/speedtest','/proxy/network/api/s/default/stat/speedtest','/api/s/default/stat/speedtest'):
   try:
    r=self._get(path)
    if r.ok:
     q=_rows(r.json())
     if q:raw=q;break
   except Exception:pass
 out=[];seen=set()
 for row in raw:
  e=_epoch(row)
  if not e or e in seen or e<start-86400000 or e>end+86400000:continue
  dl=self._speed_mbps(row.get('xput_download') or row.get('download') or row.get('download_mbps') or row.get('downloadMbps'))
  ul=self._speed_mbps(row.get('xput_upload') or row.get('upload') or row.get('upload_mbps') or row.get('uploadMbps'))
  lat=self._number(row.get('latency') or row.get('latency_avg') or row.get('ping'))
  if dl is None and ul is None:continue
  seen.add(e);out.append({'epoch_ms':e,'ts':datetime.fromtimestamp(e/1000,tz=timezone.utc).isoformat(),'download':dl,'upload':ul,'latency':lat,'interface_name':str(row.get('interface') or row.get('interface_name') or ''),'wan_group':str(row.get('wan_group') or row.get('wan_networkgroup') or row.get('wanNetworkGroup') or 'WAN')})
 out.sort(key=lambda x:x['epoch_ms']);return out

UniFiClient.speedtest_history=fixed_speedtest_history
