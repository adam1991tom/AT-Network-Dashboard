from __future__ import annotations
import csv,io,os,platform,sqlite3,zipfile
from datetime import datetime,timezone
from fastapi import APIRouter,Request,Query
from fastapi.responses import Response,JSONResponse
from app.config import CONFIG
from app.database import DB_PATH,connect
from app.settings_store import all_settings,encryption_status
from app.system_tools import status,apply_retention,backup_bytes

router=APIRouter(tags=['dev14']);VERSION='2.0.0-dev14.1'
@router.get('/api/system/info')
def system_info():return {'version':VERSION,'environment':CONFIG.environment,'database':str(DB_PATH),'database_exists':DB_PATH.exists(),'python':platform.python_version(),'platform':platform.system(),'hostname':platform.node(),'encryption':encryption_status(),'authentication':True,'schema':'dev14.1'}
@router.get('/api/system/monitoring-status')
def monitoring_status():return status()
@router.post('/api/system/retention/apply')
def retention_apply():
 cfg=all_settings()
 try:days=int(float(cfg.get('retention_days') or 365))
 except Exception:days=365
 return apply_retention(days)
@router.get('/api/system/backup')
def system_backup():
 stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S');return Response(backup_bytes(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="AT-Network-Dashboard-backup-{stamp}.zip"'})
@router.post('/api/system/restore')
async def system_restore(request:Request):
 data=await request.body()
 if not data:return JSONResponse({'ok':False,'message':'No backup uploaded'},status_code=400)
 try:
  z=zipfile.ZipFile(io.BytesIO(data),'r')
  if 'network-dashboard.sql' not in set(z.namelist()):return JSONResponse({'ok':False,'message':'Invalid AT Network Dashboard backup'},status_code=400)
  sql=z.read('network-dashboard.sql').decode('utf-8');tmp=DB_PATH.with_suffix('.restore.tmp')
  if tmp.exists():tmp.unlink()
  con=sqlite3.connect(tmp)
  try:con.executescript(sql);con.commit()
  finally:con.close()
  os.replace(tmp,DB_PATH);return {'ok':True,'message':'Backup restored. Restart the dashboard containers to complete restore.'}
 except Exception as exc:return JSONResponse({'ok':False,'message':str(exc)},status_code=400)
@router.get('/api/export/{dataset}.csv')
def export_csv(dataset:str,hours:int=Query(168,ge=1,le=8760)):
 tables={'speedtests':'speedtest_history','ping':'ping_history','gateway':'gateway_history','wifi':'wifi_history','ups':'ups_history','incidents':'incidents'};table=tables.get(dataset)
 if not table:return JSONResponse({'detail':'Unknown dataset'},status_code=404)
 con=connect()
 try:
  if table=='incidents':rows=con.execute("SELECT * FROM incidents WHERE datetime(started_at)>=datetime('now',?) ORDER BY datetime(started_at)",(f'-{hours} hours',)).fetchall()
  else:rows=con.execute(f"SELECT * FROM {table} WHERE datetime(ts)>=datetime('now',?) ORDER BY datetime(ts)",(f'-{hours} hours',)).fetchall()
  data=[dict(r) for r in rows]
 finally:con.close()
 out=io.StringIO()
 if data:
  w=csv.DictWriter(out,fieldnames=list(data[0].keys()));w.writeheader();w.writerows(data)
 return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{dataset}-{hours}h.csv"'})
@router.post('/api/incidents/{incident_id}/note')
async def incident_note(incident_id:int,request:Request):
 p=await request.json();note=str(p.get('note') or '').strip();reference=str(p.get('reference') or '').strip();con=connect()
 try:
  if not con.execute('SELECT id FROM incidents WHERE id=?',(incident_id,)).fetchone():return JSONResponse({'ok':False,'message':'Incident not found'},status_code=404)
  con.execute('UPDATE incidents SET operator_note=?,fault_reference=? WHERE id=?',(note,reference,incident_id));con.commit()
 finally:con.close()
 return {'ok':True}
@router.get('/api/system/build-info')
def build_info():
 cfg=all_settings();return {'version':VERSION,'schema':'dev14.1','update_channel':cfg.get('update_channel','stable'),'theme':cfg.get('theme','dark'),'accent':cfg.get('accent','green')}
