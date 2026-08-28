from __future__ import annotations
from fastapi import APIRouter,Query
from app.database import connect
router=APIRouter(tags=['speedtest-audit'])
@router.get('/api/isp/scheduler-audit')
def scheduler_audit(limit:int=Query(20,ge=1,le=200)):
 con=connect()
 try:
  exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='speedtest_schedule_audit'").fetchone()
  if not exists:return {'items':[]}
  return {'items':[dict(r) for r in con.execute('SELECT id,due_at,attempted_at,status,message,interval_minutes FROM speedtest_schedule_audit ORDER BY id DESC LIMIT ?',(limit,)).fetchall()]}
 finally:con.close()
