from __future__ import annotations
import csv,io
from datetime import datetime,timedelta,timezone
from pathlib import Path
from fastapi import APIRouter,Query,Request
from fastapi.responses import HTMLResponse,Response
from jinja2 import Environment,FileSystemLoader,select_autoescape
from app.database import connect
from app.isp_report import build_evidence_zip,build_pdf
from app.monitoring import gateway_history,live_snapshot,ping_history,speedtest_history,ups_history,wifi_history
from app.dev14_routes import router as dev14_router
router=APIRouter(tags=['monitoring']);router.include_router(dev14_router)
TEMPLATE_DIR=Path(__file__).resolve().parent/'templates';templates=Environment(loader=FileSystemLoader(TEMPLATE_DIR),autoescape=select_autoescape(['html','xml']));VERSION='2.0.0-dev14'
@router.get('/api/monitoring/live')
def live():return live_snapshot()
@router.get('/api/monitoring/ping')
def ping(hours:int=Query(24,ge=1,le=8760)):return ping_history(hours)
@router.get('/api/monitoring/speedtests')
def speedtests(hours:int=Query(24,ge=1,le=8760)):return speedtest_history(hours)
@router.get('/api/monitoring/gateway')
def gateway(hours:int=Query(24,ge=1,le=8760)):return gateway_history(hours)
@router.get('/api/monitoring/ups')
def ups(hours:int=Query(24,ge=1,le=8760)):return ups_history(hours)
@router.get('/api/monitoring/wifi')
def wifi(hours:int=Query(24,ge=1,le=8760),limit:int=Query(0,ge=0,le=10000)):
 rows=wifi_history(hours);return rows[-limit:] if limit else rows
@router.get('/api/monitoring/unifi-wan')
def unifi_wan(hours:int=Query(24,ge=1,le=17520)):
 con=connect()
 try:
  if hours>24*14:rows=con.execute("SELECT ts,bucket,scope,object_id,clients,rx_bytes,tx_bytes FROM unifi_wan_history WHERE bucket='daily' AND scope='site' AND datetime(ts)>=datetime('now',?) ORDER BY datetime(ts)",(f'-{hours} hours',)).fetchall()
  else:rows=con.execute("SELECT ts,bucket,scope,object_id,clients,rx_bytes,tx_bytes FROM unifi_wan_history WHERE bucket='hourly' AND scope='gateway' AND datetime(ts)>=datetime('now',?) ORDER BY datetime(ts)",(f'-{hours} hours',)).fetchall()
  return [dict(r) for r in rows]
 finally:con.close()
@router.get('/api/monitoring/unifi-ap-traffic')
def unifi_ap_traffic(hours:int=Query(24,ge=1,le=17520)):
 con=connect()
 try:return [dict(r) for r in con.execute("SELECT ts,device_id,clients,bytes,rx_bytes,tx_bytes FROM unifi_ap_traffic_history WHERE datetime(ts)>=datetime('now',?) ORDER BY datetime(ts)",(f'-{hours} hours',)).fetchall()]
 finally:con.close()
@router.get('/api/incidents')
def incidents_api(limit:int=Query(1000,ge=1,le=5000)):
 con=connect()
 try:return {'items':[dict(r) for r in con.execute("SELECT id,incident_type,incident_key,category,device,severity,started_at,ended_at,last_seen_at,summary,details,active,operator_note,fault_reference FROM incidents ORDER BY active DESC,id DESC LIMIT ?",(limit,)).fetchall()]}
 finally:con.close()
@router.get('/incidents',response_class=HTMLResponse)
def incidents_page(request:Request):
 con=connect()
 try:items=[dict(r) for r in con.execute("SELECT id,incident_type,incident_key,category,device,severity,started_at,ended_at,last_seen_at,summary,details,active,operator_note,fault_reference FROM incidents ORDER BY active DESC,id DESC LIMIT 2000").fetchall()]
 finally:con.close()
 return HTMLResponse(templates.get_template('incidents.html').render(request=request,version=VERSION,page='incidents',title='Incidents',incidents=items))
@router.get('/wifi',response_class=HTMLResponse)
def wifi_page(request:Request):return HTMLResponse(templates.get_template('wifi.html').render(request=request,version=VERSION,page='wifi',title='Wi-Fi'))
@router.get('/reports',response_class=HTMLResponse)
def reports_page(request:Request):
 con=connect()
 try:
  def count(t):
   try:return int(con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
   except Exception:return 0
  incidents=int(con.execute("SELECT COUNT(*) FROM incidents WHERE category IN ('ISP','Internet','Gateway')").fetchone()[0]);counts={'speedtests':count('speedtest_history'),'ping':count('ping_history'),'gateway':count('gateway_history'),'wan':count('unifi_wan_history'),'incidents':incidents}
 finally:con.close()
 return HTMLResponse(templates.get_template('reports.html').render(request=request,version=VERSION,page='reports',title='Reports',counts=counts))
def _range(start,end,hours=None):
 now=datetime.now(timezone.utc)
 if start and end:
  try:
   s=datetime.fromisoformat(start.replace('Z','+00:00'));e=datetime.fromisoformat(end.replace('Z','+00:00'));s=s if s.tzinfo else s.replace(tzinfo=timezone.utc);e=e if e.tzinfo else e.replace(tzinfo=timezone.utc);return s.astimezone(timezone.utc).isoformat(),e.astimezone(timezone.utc).isoformat()
  except Exception:pass
 h=max(1,min(int(hours or 168),2160));return (now-timedelta(hours=h)).isoformat(),now.isoformat()
@router.get('/api/reports/isp.pdf')
def isp_pdf(start:str|None=None,end:str|None=None,hours:int|None=Query(None,ge=1,le=2160)):
 s,e=_range(start,end,hours);return Response(build_pdf(s,e),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="AT-Internet-Performance-Report.pdf"'})
@router.get('/api/reports/isp-evidence.zip')
def isp_evidence(start:str|None=None,end:str|None=None,hours:int|None=Query(None,ge=1,le=2160)):
 s,e=_range(start,end,hours);return Response(build_evidence_zip(s,e),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="AT-Internet-Evidence.zip"'})
def _csv_response(table,filename):
 con=connect()
 try:cur=con.execute(f'SELECT * FROM {table} ORDER BY id');headers=[d[0] for d in cur.description];rows=cur.fetchall()
 finally:con.close()
 stream=io.StringIO();w=csv.writer(stream);w.writerow(headers)
 for row in rows:w.writerow([row[h] for h in headers])
 return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{filename}"'})
@router.get('/api/reports/export/speedtests.csv')
def export_speedtests():return _csv_response('speedtest_history','at-network-speedtests.csv')
@router.get('/api/reports/export/ping.csv')
def export_ping():return _csv_response('ping_history','at-network-ping.csv')
@router.get('/api/reports/export/gateway.csv')
def export_gateway():return _csv_response('gateway_history','at-network-gateway.csv')
@router.get('/api/reports/export/wan.csv')
def export_wan():return _csv_response('unifi_wan_history','at-network-unifi-wan.csv')
