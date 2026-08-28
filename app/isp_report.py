from __future__ import annotations
import csv,io,statistics,uuid,zipfile
from collections import defaultdict
from datetime import datetime,timezone
from reportlab.graphics.shapes import Drawing,Line,PolyLine,String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
from app.database import connect
from app.settings_store import all_settings

def _rows(table,start,end):
 con=connect()
 try:return [dict(r) for r in con.execute(f"SELECT * FROM {table} WHERE datetime(ts) BETWEEN datetime(?) AND datetime(?) ORDER BY datetime(ts)",(start,end)).fetchall()]
 finally:con.close()
def _incidents(start,end):
 con=connect()
 try:return [dict(r) for r in con.execute("SELECT * FROM incidents WHERE category IN ('ISP','Internet','Gateway') AND datetime(started_at)<=datetime(?) AND (ended_at IS NULL OR datetime(ended_at)>=datetime(?)) ORDER BY datetime(started_at)",(end,start)).fetchall()]
 finally:con.close()
def _num(v):return [float(x) for x in v if x is not None]
def _stats(v):
 vals=_num(v);return {'min':min(vals),'max':max(vals),'avg':statistics.fmean(vals)} if vals else {'min':None,'max':None,'avg':None}
def _fmt(v,d=1):return '—' if v is None else f'{float(v):.{d}f}'
def _as_dt(v):
 dt=datetime.fromisoformat(str(v).replace('Z','+00:00'));return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
def _duration_seconds(start,end):
 try:return max(0,(_as_dt(end)-_as_dt(start)).total_seconds())
 except Exception:return 0
def _speed_chart(speed,cfg,start,end):
 width,height=740,190;left,right,top,bottom=46,18,16,28;d=Drawing(width,height);d.add(String(0,height-10,'ISP Speed Performance',fontSize=11,fillColor=colors.HexColor('#111827')))
 if not speed:d.add(String(left,height/2,'No speed-test data in this period',fontSize=9,fillColor=colors.grey));return d
 sd,ed=_as_dt(start),_as_dt(end);total=max(1,(ed-sd).total_seconds());vals=[float(r.get('download') or 0) for r in speed]+[float(r.get('upload') or 0) for r in speed];refs=[float(cfg.get(k) or 0) for k in ('expected_download','expected_upload','warning_threshold','major_threshold','critical_threshold')];ymax=max([100,*vals,*refs])*1.05;pw=width-left-right;ph=height-top-bottom
 x=lambda ts:left+max(0,min(1,(_as_dt(ts)-sd).total_seconds()/total))*pw;y=lambda v:bottom+max(0,min(1,float(v)/ymax))*ph
 for i in range(6):
  yy=bottom+ph/5*i;d.add(Line(left,yy,width-right,yy,strokeColor=colors.HexColor('#d1d5db'),strokeWidth=.5));d.add(String(2,yy-3,f'{ymax/5*i:.0f}',fontSize=7,fillColor=colors.HexColor('#6b7280')))
 for key,color,label in [('expected_download','#2563eb','Expected down'),('expected_upload','#a855f7','Expected up'),('warning_threshold','#d4a017','Warning'),('major_threshold','#ea580c','Major'),('critical_threshold','#dc2626','Critical')]:
  val=float(cfg.get(key) or 0)
  if val>0:yy=y(val);d.add(Line(left,yy,width-right,yy,strokeColor=colors.HexColor(color),strokeWidth=.8,strokeDashArray=[4,3]));d.add(String(width-right-80,yy+2,f'{label} {val:g}',fontSize=6.2,fillColor=colors.HexColor(color)))
 down=[(x(r['ts']),y(r['download'])) for r in speed if r.get('download') is not None];up=[(x(r['ts']),y(r['upload'])) for r in speed if r.get('upload') is not None]
 if len(down)>1:d.add(PolyLine(down,strokeColor=colors.HexColor('#00aeea'),strokeWidth=1.4))
 if len(up)>1:d.add(PolyLine(up,strokeColor=colors.HexColor('#d946ef'),strokeWidth=1.4))
 return d
def _daily(speed,ping):
 sd=defaultdict(list);pd=defaultdict(list)
 for r in speed:
  try:sd[_as_dt(r['ts']).date().isoformat()].append(r)
  except:pass
 for r in ping:
  try:pd[_as_dt(r['ts']).date().isoformat()].append(r)
  except:pass
 out=[['Date','Tests','Avg Down','Min Down','Avg Up','Avg Latency','Peak Loss','Reachability']]
 for day in sorted(set(sd)|set(pd)):
  sr,pr=sd[day],pd[day];ds=_stats([r.get('download') for r in sr]);us=_stats([r.get('upload') for r in sr]);ls=_stats([r.get('latency') for r in pr]);loss=_stats([r.get('packet_loss') for r in pr]);reach=(sum(1 for r in pr if r.get('online'))/len(pr)*100) if pr else None;out.append([day,str(len(sr)),_fmt(ds['avg']),_fmt(ds['min']),_fmt(us['avg']),_fmt(ls['avg']),_fmt(loss['max']),'—' if reach is None else f'{reach:.1f}%'])
 return out
def build_pdf(start,end):
 cfg=all_settings();speed=_rows('speedtest_history',start,end);ping=_rows('ping_history',start,end);gw=_rows('gateway_history',start,end);inc=_incidents(start,end);report_id='AT-'+uuid.uuid4().hex[:10].upper();generated=datetime.now(timezone.utc).isoformat()
 down=_stats([r.get('download') for r in speed]);up=_stats([r.get('upload') for r in speed]);lat=_stats([r.get('latency') for r in ping]);loss=_stats([r.get('packet_loss') for r in ping]);td=float(cfg.get('expected_download') or 0);tu=float(cfg.get('expected_upload') or 0);warning=float(cfg.get('warning_threshold') or 0);major=float(cfg.get('major_threshold') or 0);critical=float(cfg.get('critical_threshold') or 0)
 beloww=sum(1 for r in speed if warning and min(float(r.get('download') or 0),float(r.get('upload') or 0))<warning);belowm=sum(1 for r in speed if major and min(float(r.get('download') or 0),float(r.get('upload') or 0))<major);belowc=sum(1 for r in speed if critical and min(float(r.get('download') or 0),float(r.get('upload') or 0))<critical);offline=[r for r in ping if not r.get('online')];reach=((len(ping)-len(offline))/len(ping)*100) if ping else None;sample_seconds=30;total_down=len(offline)*sample_seconds
 outages=[]
 for r in inc:
  if not r.get('ended_at') or 'offline' in str(r.get('summary','')).lower() or 'outage' in str(r.get('summary','')).lower():outages.append(_duration_seconds(r.get('started_at'),r.get('ended_at') or end))
 longest=max(outages) if outages else 0
 buf=io.BytesIO();styles=getSampleStyleSheet();doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=12*mm,leftMargin=12*mm,topMargin=12*mm,bottomMargin=12*mm);story=[]
 story.append(Paragraph('AT Network Dashboard — Internet Performance & Reliability Report',styles['Title']));identity=f"Report ID: <b>{report_id}</b> &nbsp; Generated: <b>{generated}</b><br/>Site: <b>{cfg.get('site_name') or 'Not specified'}</b> &nbsp; Address: <b>{cfg.get('site_address') or 'Not specified'}</b><br/>Provider: <b>{cfg.get('isp_provider') or 'Not specified'}</b> &nbsp; Account / Customer No: <b>{cfg.get('isp_account_number') or 'Not specified'}</b> &nbsp; Service Ref: <b>{cfg.get('isp_service_reference') or 'Not specified'}</b><br/>Support: <b>{cfg.get('isp_support_phone') or '—'}</b> &nbsp; {cfg.get('isp_support_url') or ''}<br/>Period: <b>{start}</b> to <b>{end}</b>";story.append(Paragraph(identity,styles['BodyText']));story.append(Spacer(1,4*mm))
 summary=[['Metric','Result','Configured reference'],['Speed tests',str(len(speed)),f'Package {td:g}/{tu:g} Mbps'],['Download',f"Avg {_fmt(down['avg'])} · Min {_fmt(down['min'])} · Max {_fmt(down['max'])} Mbps",f'Expected {td:g} Mbps'],['Upload',f"Avg {_fmt(up['avg'])} · Min {_fmt(up['min'])} · Max {_fmt(up['max'])} Mbps",f'Expected {tu:g} Mbps'],['Latency',f"Avg {_fmt(lat['avg'])} · Peak {_fmt(lat['max'])} ms",str(cfg.get('ping_target') or '1.1.1.1')],['Packet loss / reachability',f"Avg {_fmt(loss['avg'])}% · Peak {_fmt(loss['max'])}% · Reachability {'—' if reach is None else f'{reach:.2f}%'}",f'Approx downtime {total_down//60:.0f} min'],['Threshold breaches',f'Warning {beloww} · Major {belowm} · Critical {belowc}',f'Warn {warning:g} · Major {major:g} · Critical {critical:g} Mbps'],['Incidents',str(len(inc)),f'Longest outage {longest/60:.1f} min']]
 t=Table(summary,colWidths=[50*mm,125*mm,90*mm]);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.35,colors.grey),('FONTSIZE',(0,0),(-1,-1),8),('VALIGN',(0,0),(-1,-1),'TOP')]));story+=[t,Spacer(1,4*mm),_speed_chart(speed,cfg,start,end),Spacer(1,4*mm)]
 daily=_daily(speed,ping)
 if len(daily)>1:
  story.append(Paragraph('Daily Internet Summary',styles['Heading2']));dt=Table(daily,repeatRows=1,colWidths=[31*mm,17*mm,28*mm,28*mm,28*mm,30*mm,25*mm,28*mm]);dt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),6.8)]));story+=[dt,PageBreak()]
 if speed:
  story.append(Paragraph('Speed Test Evidence',styles['Heading2']));data=[['Date / Time','Download Mbps','Upload Mbps','Latency ms','Source']]+[[str(r.get('ts','')),_fmt(r.get('download')),_fmt(r.get('upload')),_fmt(r.get('latency')),str(r.get('source',''))] for r in speed[-250:]];st=Table(data,repeatRows=1,colWidths=[65*mm,35*mm,35*mm,30*mm,35*mm]);st.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7)]));story.append(st)
 story+=[PageBreak(),Paragraph('Internet Incidents / Fault Evidence',styles['Heading2'])]
 if inc:
  data=[['Severity','Started','Ended','Summary','Fault Ref / Notes']]
  for r in inc:data.append([str(r.get('severity','')).upper(),str(r.get('started_at','')),str(r.get('ended_at') or 'ACTIVE'),Paragraph(str(r.get('summary','')),styles['BodyText']),Paragraph((str(r.get('fault_reference') or '')+' '+str(r.get('operator_note') or '')).strip() or str(r.get('details',''))[:300],styles['BodyText'])])
  it=Table(data,repeatRows=1,colWidths=[25*mm,45*mm,45*mm,70*mm,90*mm]);it.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'TOP')]));story.append(it)
 else:story.append(Paragraph('No ISP/Internet/Gateway incidents were recorded in this period.',styles['BodyText']))
 if cfg.get('isp_notes'):story+=[Spacer(1,4*mm),Paragraph('ISP Notes',styles['Heading2']),Paragraph(str(cfg.get('isp_notes')),styles['BodyText'])]
 doc.build(story);return buf.getvalue()
def _csv_bytes(rows):
 out=io.StringIO()
 if not rows:return b''
 w=csv.DictWriter(out,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows);return out.getvalue().encode()
def build_evidence_zip(start,end):
 pdf=build_pdf(start,end);buf=io.BytesIO();speed=_rows('speedtest_history',start,end);ping=_rows('ping_history',start,end);gw=_rows('gateway_history',start,end);inc=_incidents(start,end);cfg=all_settings()
 with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('AT-Internet-Performance-Report.pdf',pdf);z.writestr('speedtests.csv',_csv_bytes(speed));z.writestr('ping-packet-loss.csv',_csv_bytes(ping));z.writestr('gateway-wan.csv',_csv_bytes(gw));z.writestr('internet-incidents.csv',_csv_bytes(inc));z.writestr('report-identity.txt',f"Site: {cfg.get('site_name','')}\nProvider: {cfg.get('isp_provider','')}\nAccount: {cfg.get('isp_account_number','')}\nService reference: {cfg.get('isp_service_reference','')}\n")
 return buf.getvalue()
