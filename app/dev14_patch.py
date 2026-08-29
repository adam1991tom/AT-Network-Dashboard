from __future__ import annotations
import time
from app import monitoring as m
from app.settings_store import all_settings,get_secret
from app.integrations.discord import DiscordNotifier
from app.system_tools import apply_retention
_original_set=m._set_incident
_original_collect=m.collect_once
_last_notice={};_last_retention=0.0
_rank={'warning':1,'major':2,'critical':3}
def _b(v,default=False):
 if v is None:return default
 return str(v).lower() in {'1','true','yes','on'}
def _notify_allowed(cfg,category,severity):
 if not _b(cfg.get('discord_enabled')):return False
 if _rank.get(severity,1)<_rank.get(str(cfg.get('notification_min_severity') or 'warning'),1):return False
 c=str(category or '').lower()
 key='notify_internet' if c in {'isp','internet'} else 'notify_wifi' if c=='wi-fi' else 'notify_power' if c=='ups' else 'notify_gateway' if c=='gateway' else 'notify_system'
 return _b(cfg.get(key),True)
def patched_set(con,incident_key,bad,severity,category,device,summary,details,persist_seconds=0,recover_seconds=0):
 cfg=all_settings()
 if _b(cfg.get('maintenance_mode')):return
 before=m._active_incident(con,incident_key)
 _original_set(con,incident_key,bad,severity,category,device,summary,details,persist_seconds,recover_seconds)
 after=m._active_incident(con,incident_key)
 transition=('open' if not before and after else 'resolved' if before and not after else None)
 if not transition:return
 try:
  if not _notify_allowed(cfg,category,severity):return
  cooldown=max(1,int(float(cfg.get('notification_cooldown_minutes') or 15)))*60;key=f'{incident_key}:{transition}';now=time.monotonic()
  if now-_last_notice.get(key,0)<cooldown:return
  hook=get_secret('discord_webhook') or ''
  if hook:
   icon='🚨' if transition=='open' else '✅';DiscordNotifier(hook).send(f'{icon} {summary}\n{category} · {device} · {severity.upper()} · {transition.upper()}\n{details}');_last_notice[key]=now
 except Exception as exc:print(f'dev14 notification failed: {exc}')
def patched_collect():
 global _last_retention
 _original_collect();now=time.monotonic()
 if now-_last_retention>=21600:
  try:
   cfg=all_settings();days=int(float(cfg.get('retention_days') or 365));apply_retention(days);_last_retention=now
  except Exception as exc:print(f'dev14 retention failed: {exc}')
m._set_incident=patched_set
m.collect_once=patched_collect
