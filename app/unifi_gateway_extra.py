"""Augment normalised gateway data with additional fields when UniFi exposes them."""
from __future__ import annotations
from typing import Any
from app.integrations.unifi import UniFiClient

_original=UniFiClient._gateway_stats

def _num(v):
 try:return float(v)
 except Exception:return None

def _extra(self:UniFiClient,device:dict[str,Any]):
 out=_original(self,device)
 sys=device.get('system-stats') if isinstance(device.get('system-stats'),dict) else {}
 wan=device.get('wan1') if isinstance(device.get('wan1'),dict) else {}
 uplink=device.get('uplink') if isinstance(device.get('uplink'),dict) else {}
 load=sys.get('loadavg_1') or sys.get('load_average') or device.get('loadavg_1')
 out.update({
  'model':device.get('model') or device.get('shortname'),
  'version':device.get('version') or device.get('firmware_version'),
  'mac':device.get('mac'),
  'lan_ip':device.get('ip'),
  'site':device.get('site_name') or device.get('site_id') or device.get('site'),
  'load_average':load,
  'clients':device.get('num_sta') or device.get('user-num_sta') or device.get('num_user'),
  'rx_bytes':_num(wan.get('rx_bytes') or device.get('rx_bytes') or uplink.get('rx_bytes')),
  'tx_bytes':_num(wan.get('tx_bytes') or device.get('tx_bytes') or uplink.get('tx_bytes')),
  'wan_interface':wan.get('name') or wan.get('ifname') or device.get('wan_interface'),
  'wan_gateway':wan.get('gateway') or wan.get('gw'),
  'wan_dns':wan.get('dns') or wan.get('nameservers'),
  'adopted':device.get('adopted'),
  'state':device.get('state'),
 })
 return out

UniFiClient._gateway_stats=_extra
