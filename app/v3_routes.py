from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.database import connect, DB_PATH
from app.config import CONFIG
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings, get_secret

router=APIRouter(tags=['v3'])
templates=Environment(loader=FileSystemLoader(Path(__file__).resolve().parent/'templates'),autoescape=select_autoescape(['html','xml']))
VERSION='3.0.0'

def _page(request:Request,name:str,page:str,title:str):
 return HTMLResponse(templates.get_template(name).render(request=request,version=VERSION,page=page,title=title))

@router.get('/api/health')
def v3_health():return {'status':'ok','version':VERSION,'environment':CONFIG.environment,'database':str(DB_PATH)}
@router.get('/',response_class=HTMLResponse)
@router.get('/dashboard',response_class=HTMLResponse)
def v3_dashboard(request:Request):return _page(request,'dashboard.html','dashboard','Dashboard')
@router.get('/isp',response_class=HTMLResponse)
def isp_page(request:Request): return _page(request,'isp.html','isp','ISP')
@router.get('/gateway',response_class=HTMLResponse)
def gateway_page(request:Request): return _page(request,'gateway.html','gateway','Gateway')
@router.get('/ups',response_class=HTMLResponse)
def ups_page(request:Request): return _page(request,'ups.html','ups','UPS / Power')

@router.get('/api/isp/speedtest-sync/status')
def speed_sync_status(days:int=Query(365,ge=1,le=730)):
 cfg=all_settings(); url=str(cfg.get('unifi_url') or '').strip(); key=get_secret('unifi_api_key') or ''
 if not url or not key:return JSONResponse({'ok':False,'message':'UniFi is not configured'},status_code=400)
 client=UniFiClient(url,key,str(cfg.get('unifi_verify_ssl') or 'false').lower()=='true')
 try:controller=client.speedtest_history(days)
 except Exception as exc:return JSONResponse({'ok':False,'message':str(exc)},status_code=502)
 epochs=[int(r.get('epoch_ms') or 0) for r in controller if int(r.get('epoch_ms') or 0)>0]
 con=connect()
 try:db={int(r[0]) for r in con.execute('SELECT epoch_ms FROM speedtest_history WHERE epoch_ms IS NOT NULL').fetchall()}
 finally:con.close()
 missing=[e for e in epochs if e not in db]
 return {'ok':True,'controller_count':len(epochs),'dashboard_count':len(db),'missing_count':len(missing),'missing_epochs':missing[:100],'oldest':controller[0].get('ts') if controller else None,'newest':controller[-1].get('ts') if controller else None}

@router.post('/api/isp/speedtest-sync')
async def speed_sync(request:Request):
 p=await request.json(); days=max(1,min(730,int(p.get('days') or 365))); rebuild=bool(p.get('rebuild'))
 cfg=all_settings(); url=str(cfg.get('unifi_url') or '').strip(); key=get_secret('unifi_api_key') or ''
 if not url or not key:return JSONResponse({'ok':False,'message':'UniFi is not configured'},status_code=400)
 client=UniFiClient(url,key,str(cfg.get('unifi_verify_ssl') or 'false').lower()=='true')
 try:rows=client.speedtest_history(days)
 except Exception as exc:return JSONResponse({'ok':False,'message':str(exc)},status_code=502)
 con=connect(); inserted=0
 try:
  if rebuild:con.execute("DELETE FROM speedtest_history WHERE source IN ('unifi-history','unifi-live','unifi')")
  for r in rows:
   epoch=int(r.get('epoch_ms') or 0)
   if not epoch:continue
   ts=str(r.get('ts') or datetime.fromtimestamp(epoch/1000,tz=timezone.utc).isoformat())
   cur=con.execute('INSERT OR IGNORE INTO speedtest_history(ts,epoch_ms,download,upload,latency,interface_name,wan_group,source) VALUES (?,?,?,?,?,?,?,?)',(ts,epoch,r.get('download'),r.get('upload'),r.get('latency'),r.get('interface_name'),r.get('wan_group') or 'WAN','unifi-history'))
   inserted+=max(cur.rowcount,0)
  con.commit(); total=con.execute('SELECT COUNT(*) FROM speedtest_history').fetchone()[0]
 finally:con.close()
 return {'ok':True,'inserted':inserted,'controller_count':len(rows),'dashboard_count':total,'message':f'Synchronised {inserted} missing speed tests'}

@router.get('/api/gateway/live-extra')
def gateway_extra():
 cfg=all_settings(); url=str(cfg.get('unifi_url') or '').strip(); key=get_secret('unifi_api_key') or ''
 if not url or not key:return JSONResponse({'ok':False,'message':'UniFi is not configured'},status_code=400)
 try:
  snap=UniFiClient(url,key,str(cfg.get('unifi_verify_ssl') or 'false').lower()=='true').snapshot(); return {'ok':True,'gateway':snap.get('gateway') or {}}
 except Exception as exc:return JSONResponse({'ok':False,'message':str(exc)},status_code=502)

@router.get('/api/dashboard/summary')
def dashboard_summary():
 con=connect()
 try:
  active=con.execute('SELECT COUNT(*) FROM incidents WHERE active=1').fetchone()[0]
  speed=con.execute('SELECT ts,download,upload,latency FROM speedtest_history ORDER BY epoch_ms DESC LIMIT 1').fetchone()
  gateway=con.execute('SELECT ts,cpu,memory,temperature,wan_up FROM gateway_history ORDER BY id DESC LIMIT 1').fetchone()
  ups=con.execute('SELECT ts,connected,status,load_pct,input_voltage FROM ups_history ORDER BY id DESC LIMIT 1').fetchone()
  wifi=con.execute("SELECT MAX(retries),COUNT(DISTINCT COALESCE(device_id,'')||band) FROM wifi_history WHERE datetime(ts)>=datetime('now','-5 minutes')").fetchone()
  ping=con.execute('SELECT ts,latency,packet_loss,online FROM ping_history ORDER BY id DESC LIMIT 1').fetchone()
  return {'active_incidents':active,'speed':dict(speed) if speed else None,'gateway':dict(gateway) if gateway else None,'ups':dict(ups) if ups else None,'wifi':{'worst_retries':wifi[0] or 0,'radios':wifi[1] or 0},'ping':dict(ping) if ping else None}
 finally:con.close()
