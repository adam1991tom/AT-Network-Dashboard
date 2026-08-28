from __future__ import annotations
import time
from datetime import datetime,timedelta,timezone
from app.database import connect, write_transaction
from app.integrations.unifi import UniFiClient
from app.settings_store import all_settings,get_secret

POLL_SECONDS=15;MIN_INTERVAL_MINUTES=5;MAX_INTERVAL_MINUTES=1440

def _bool(v,default=False):return default if v is None else str(v).lower() in {'1','true','yes','on'}
def _interval(cfg):
 try:m=int(float(cfg.get('speedtest_minutes') or 15))
 except Exception:m=15
 return max(MIN_INTERVAL_MINUTES,min(MAX_INTERVAL_MINUTES,m))
def _now():return datetime.now(timezone.utc)
def _parse(v):
 if not v:return None
 try:return datetime.fromisoformat(str(v).replace('Z','+00:00')).astimezone(timezone.utc)
 except Exception:return None

def _ensure_audit():
 def op(con):
  con.execute('CREATE TABLE IF NOT EXISTS speedtest_schedule_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,due_at TEXT NOT NULL,attempted_at TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL DEFAULT \'\',interval_minutes INTEGER NOT NULL)')
  con.execute('CREATE INDEX IF NOT EXISTS idx_speedtest_schedule_due ON speedtest_schedule_audit(due_at)')
 write_transaction(op)
def _audit(due,attempt,status,message,minutes):
 write_transaction(lambda con: con.execute('INSERT INTO speedtest_schedule_audit(due_at,attempted_at,status,message,interval_minutes) VALUES (?,?,?,?,?)',(due.isoformat(),attempt.isoformat(),status,str(message or ''),minutes)))
def _state(**values):
 # Avoid taking a write lock every 15 seconds when the state has not changed.
 con=connect()
 try:
  current={r['setting_key']:r['setting_value'] for r in con.execute("SELECT setting_key,setting_value FROM settings WHERE setting_key LIKE 'speedtest_%'").fetchall()}
 finally:con.close()
 changed={k:('' if v is None else str(v)) for k,v in values.items() if current.get(k)!=('' if v is None else str(v))}
 if not changed:return
 def op(con):
  for k,v in changed.items():
   con.execute('INSERT INTO settings(setting_key,setting_value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP WHERE settings.setting_value<>excluded.setting_value',(k,v))
 write_transaction(op)
def _advance(due,now,minutes):
 step=timedelta(minutes=minutes);nxt=due+step
 while nxt<=now:nxt+=step
 return nxt

def run_forever():
 print('auto-speedtest: v3.2.1 worker started');_ensure_audit()
 while True:
  try:
   cfg=all_settings();enabled=_bool(cfg.get('speedtest_auto_enabled'),True);minutes=_interval(cfg);now=_now()
   if not enabled:_state(speedtest_auto_state='disabled',speedtest_next_auto_at='');time.sleep(POLL_SECONDS);continue
   if not _bool(cfg.get('isp_enabled'),True) or not _bool(cfg.get('unifi_enabled'),False):_state(speedtest_auto_state='waiting for ISP/UniFi to be enabled',speedtest_next_auto_at='');time.sleep(POLL_SECONDS);continue
   url=str(cfg.get('unifi_url') or '').strip();key=get_secret('unifi_api_key') or ''
   if not url or not key:_state(speedtest_auto_state='waiting for UniFi configuration',speedtest_next_auto_at='');time.sleep(POLL_SECONDS);continue
   due=_parse(cfg.get('speedtest_next_auto_at'))
   if due is None:
    due=now+timedelta(seconds=45);_state(speedtest_auto_state='scheduled',speedtest_next_auto_at=due.isoformat());time.sleep(POLL_SECONDS);continue
   if now<due:_state(speedtest_auto_state='scheduled',speedtest_next_auto_at=due.isoformat());time.sleep(POLL_SECONDS);continue
   attempt=_now();_state(speedtest_auto_state='starting')
   result=UniFiClient(url,key,str(cfg.get('unifi_verify_ssl') or 'false').lower()=='true').run_speedtest();ok=bool(result.get('ok'));message=result.get('message') or ('UniFi speed test started' if ok else 'Unable to start UniFi speed test')
   _audit(due,attempt,'accepted' if ok else 'failed',message,minutes);nxt=_advance(due,attempt,minutes)
   _state(speedtest_last_auto_at=attempt.isoformat(),speedtest_next_auto_at=nxt.isoformat(),speedtest_auto_state='started successfully' if ok else 'failed',speedtest_auto_last_message=message)
   print(f"auto-speedtest: {'accepted' if ok else 'failed'} due={due.isoformat()} attempted={attempt.isoformat()} next={nxt.isoformat()}")
  except Exception as exc:
   try:_state(speedtest_auto_state='error',speedtest_auto_last_message=str(exc))
   except Exception:pass
   print(f'auto-speedtest: worker error: {exc}')
  time.sleep(POLL_SECONDS)

if __name__=='__main__':run_forever()
