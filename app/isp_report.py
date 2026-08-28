from __future__ import annotations

import csv
import io
import statistics
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from app.database import connect
from app.settings_store import all_settings


def _rows(table: str, start: str, end: str) -> list[dict]:
    con = connect()
    try:
        rows = con.execute(f"SELECT * FROM {table} WHERE datetime(ts) BETWEEN datetime(?) AND datetime(?) ORDER BY datetime(ts)", (start, end)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _incidents(start: str, end: str) -> list[dict]:
    con = connect()
    try:
        rows = con.execute("""
            SELECT * FROM incidents
            WHERE category IN ('ISP','Internet','Gateway')
              AND datetime(started_at) <= datetime(?)
              AND (ended_at IS NULL OR datetime(ended_at) >= datetime(?))
            ORDER BY datetime(started_at)
        """, (end, start)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _num(values):
    return [float(v) for v in values if v is not None]


def _stats(values):
    vals = _num(values)
    if not vals:
        return {"min":None,"max":None,"avg":None}
    return {"min":min(vals),"max":max(vals),"avg":statistics.fmean(vals)}


def _fmt(v, d=1):
    return "—" if v is None else f"{float(v):.{d}f}"


def _as_dt(value: str) -> datetime:
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _speed_chart(speed: list[dict], cfg: dict, start: str, end: str) -> Drawing:
    width,height=740,190; left,right,top,bottom=46,18,16,28
    d=Drawing(width,height)
    d.add(String(0,height-10,"ISP Speed Performance",fontSize=11,fillColor=colors.HexColor('#111827')))
    if not speed:
        d.add(String(left,height/2,"No speed-test data in this period",fontSize=9,fillColor=colors.grey)); return d
    start_dt=_as_dt(start); end_dt=_as_dt(end); total=max(1,(end_dt-start_dt).total_seconds())
    values=[float(r.get('download') or 0) for r in speed]+[float(r.get('upload') or 0) for r in speed]
    refs=[float(cfg.get(k) or 0) for k in ('expected_download','expected_upload','warning_threshold','major_threshold','critical_threshold')]
    ymax=max([1000.0,*values,*refs])*1.05; plot_w=width-left-right; plot_h=height-top-bottom
    def x(ts): return left+max(0,min(1,(_as_dt(ts)-start_dt).total_seconds()/total))*plot_w
    def y(v): return bottom+max(0,min(1,float(v)/ymax))*plot_h
    for i in range(6):
        yy=bottom+(plot_h/5)*i; val=(ymax/5)*i; d.add(Line(left,yy,width-right,yy,strokeColor=colors.HexColor('#d1d5db'),strokeWidth=.5)); d.add(String(2,yy-3,f"{val:.0f}",fontSize=7,fillColor=colors.HexColor('#6b7280')))
    refs_spec=[('expected_download','#2563eb','Target'),('warning_threshold','#d4a017','Warning'),('major_threshold','#ea580c','Major'),('critical_threshold','#dc2626','Critical')]
    for key,color,label in refs_spec:
        val=float(cfg.get(key) or 0)
        if val<=0:continue
        yy=y(val);d.add(Line(left,yy,width-right,yy,strokeColor=colors.HexColor(color),strokeWidth=.8,strokeDashArray=[4,3]));d.add(String(width-right-68,yy+2,f"{label} {val:g}",fontSize=6.5,fillColor=colors.HexColor(color)))
    down=[(x(r['ts']),y(r.get('download') or 0)) for r in speed if r.get('download') is not None]
    up=[(x(r['ts']),y(r.get('upload') or 0)) for r in speed if r.get('upload') is not None]
    if len(down)>1:d.add(PolyLine(down,strokeColor=colors.HexColor('#00aeea'),strokeWidth=1.4))
    if len(up)>1:d.add(PolyLine(up,strokeColor=colors.HexColor('#d946ef'),strokeWidth=1.4))
    d.add(String(left,bottom-16,"Download",fontSize=7,fillColor=colors.HexColor('#00aeea')));d.add(String(left+54,bottom-16,"Upload",fontSize=7,fillColor=colors.HexColor('#d946ef')))
    return d


def _daily_summary(speed: list[dict], ping: list[dict]) -> list[list[str]]:
    sdays: dict[str,list[dict]]=defaultdict(list); pdays: dict[str,list[dict]]=defaultdict(list)
    for r in speed:
        try:sdays[_as_dt(r['ts']).date().isoformat()].append(r)
        except Exception:pass
    for r in ping:
        try:pdays[_as_dt(r['ts']).date().isoformat()].append(r)
        except Exception:pass
    days=sorted(set(sdays)|set(pdays))
    rows=[["Date","Tests","Avg Down","Min Down","Avg Up","Avg Latency","Peak Loss","Reachability"]]
    for day in days:
        sr=sdays[day]; pr=pdays[day]; ds=_stats([r.get('download') for r in sr]); us=_stats([r.get('upload') for r in sr]); ls=_stats([r.get('latency') for r in pr]); loss=_stats([r.get('packet_loss') for r in pr]); online=sum(1 for r in pr if r.get('online')); reach=(online/len(pr)*100) if pr else None
        rows.append([day,str(len(sr)),_fmt(ds['avg']),_fmt(ds['min']),_fmt(us['avg']),_fmt(ls['avg']),_fmt(loss['max']),"—" if reach is None else f"{reach:.1f}%"])
    return rows


def build_pdf(start: str, end: str) -> bytes:
    cfg = all_settings()
    speed = _rows("speedtest_history", start, end)
    ping = _rows("ping_history", start, end)
    gw = _rows("gateway_history", start, end)
    incidents = _incidents(start, end)
    down = _stats([r.get("download") for r in speed]); up = _stats([r.get("upload") for r in speed]); lat = _stats([r.get("latency") for r in ping]); loss = _stats([r.get("packet_loss") for r in ping])
    target_down = float(cfg.get("expected_download") or 0); target_up = float(cfg.get("expected_upload") or 0)
    warning = float(cfg.get("warning_threshold") or 0); major = float(cfg.get("major_threshold") or 0); critical = float(cfg.get("critical_threshold") or 0)
    below_warning = sum(1 for r in speed if warning and min(float(r.get("download") or 0),float(r.get("upload") or 0)) < warning)
    below_major = sum(1 for r in speed if major and min(float(r.get("download") or 0),float(r.get("upload") or 0)) < major)
    below_critical = sum(1 for r in speed if critical and min(float(r.get("download") or 0),float(r.get("upload") or 0)) < critical)
    offline = sum(1 for r in ping if not r.get("online"))
    reachability=((len(ping)-offline)/len(ping)*100) if ping else None
    compliance=(sum(1 for r in speed if target_down<=0 or float(r.get('download') or 0)>=target_down)/len(speed)*100) if speed else None

    buf = io.BytesIO(); styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=12*mm,leftMargin=12*mm,topMargin=12*mm,bottomMargin=12*mm)
    story=[]
    story.append(Paragraph("AT Network Dashboard — Internet Performance & Reliability Report", styles["Title"]))
    story.append(Paragraph(f"Provider: <b>{cfg.get('isp_provider') or 'Not specified'}</b> &nbsp;&nbsp; Period: <b>{start}</b> to <b>{end}</b>", styles["BodyText"]))
    story.append(Spacer(1,4*mm))
    summary=[
        ["Metric","Result","Configured reference"],
        ["Speed tests",str(len(speed)),f"Package target {target_down:g}/{target_up:g} Mbps"],
        ["Download",f"Avg {_fmt(down['avg'])} · Min {_fmt(down['min'])} · Max {_fmt(down['max'])} Mbps",f"Target compliance {'—' if compliance is None else f'{compliance:.1f}%'}"],
        ["Upload",f"Avg {_fmt(up['avg'])} · Min {_fmt(up['min'])} · Max {_fmt(up['max'])} Mbps",f"Target {target_up:g} Mbps"],
        ["Latency",f"Avg {_fmt(lat['avg'])} · Peak {_fmt(lat['max'])} ms",str(cfg.get('ping_target') or '1.1.1.1')],
        ["Packet loss / reachability",f"Avg {_fmt(loss['avg'])}% · Peak {_fmt(loss['max'])}% · Reachability {'—' if reachability is None else f'{reachability:.2f}%'}",f"Offline samples {offline}"],
        ["Threshold breaches",f"Warning {below_warning} · Major {below_major} · Critical {below_critical}",f"Warn {warning:g} · Major {major:g} · Critical {critical:g} Mbps"],
        ["Internet incidents",str(len(incidents)),"ISP / Internet / Gateway only"],
    ]
    t=Table(summary,colWidths=[50*mm,125*mm,90*mm]); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.35,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,0),(-1,-1),8),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f3f4f6')])]))
    story.append(t); story.append(Spacer(1,4*mm)); story.append(_speed_chart(speed,cfg,start,end)); story.append(Spacer(1,4*mm))

    daily=_daily_summary(speed,ping)
    if len(daily)>1:
        story.append(Paragraph("Daily Internet Summary", styles["Heading2"]))
        dt=Table(daily,repeatRows=1,colWidths=[31*mm,17*mm,28*mm,28*mm,28*mm,30*mm,25*mm,28*mm]);dt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),6.8),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f8fafc')])]))
        story.append(dt);story.append(PageBreak())

    if speed:
        story.append(Paragraph("Speed Test Evidence", styles["Heading2"]))
        story.append(Paragraph(f"Showing the most recent {min(250,len(speed))} tests in the PDF. The Evidence ZIP contains all {len(speed)} raw speed-test records.",styles["BodyText"]))
        data=[["Date / Time","Download Mbps","Upload Mbps","Latency ms","Source"]]
        for r in speed[-250:]: data.append([str(r.get('ts','')), _fmt(r.get('download')), _fmt(r.get('upload')), _fmt(r.get('latency')), str(r.get('source',''))])
        st=Table(data,repeatRows=1,colWidths=[65*mm,35*mm,35*mm,30*mm,35*mm]);st.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7)]));story.append(st)
    story.append(PageBreak())
    story.append(Paragraph("Internet Incidents / Fault Evidence", styles["Heading2"]))
    if incidents:
        data=[["Severity","Started","Ended","Summary","Details"]]
        for r in incidents:data.append([str(r.get('severity','')).upper(),str(r.get('started_at','')),str(r.get('ended_at') or 'ACTIVE'),Paragraph(str(r.get('summary','')),styles['BodyText']),Paragraph(str(r.get('details',''))[:350],styles['BodyText'])])
        it=Table(data,repeatRows=1,colWidths=[25*mm,45*mm,45*mm,70*mm,90*mm]);it.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'TOP')]));story.append(it)
    else:story.append(Paragraph("No ISP/Internet/Gateway incidents were recorded in this period.", styles["BodyText"]))
    story.append(Spacer(1,5*mm));story.append(Paragraph("WAN / Gateway Evidence", styles["Heading2"]))
    if gw:
        latest=gw[-1];story.append(Paragraph(f"Latest WAN state: {'ONLINE' if latest.get('wan_up') else 'OFFLINE'} · Link {latest.get('link_speed') or '—'} Mbps · RX errors {latest.get('rx_errors') or 0} · TX errors {latest.get('tx_errors') or 0} · RX dropped {latest.get('rx_dropped') or 0} · TX dropped {latest.get('tx_dropped') or 0}.", styles["BodyText"]))
    story.append(Spacer(1,4*mm));story.append(Paragraph("This report is generated from timestamped measurements stored by AT Network Dashboard. Raw ISP evidence is included in the matching Evidence ZIP export.", styles["Italic"]))
    doc.build(story); return buf.getvalue()


def _csv_bytes(rows: list[dict]) -> bytes:
    out=io.StringIO()
    if not rows:return b""
    w=csv.DictWriter(out,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows);return out.getvalue().encode()


def build_evidence_zip(start: str, end: str) -> bytes:
    pdf=build_pdf(start,end);buf=io.BytesIO();speed=_rows("speedtest_history",start,end);ping=_rows("ping_history",start,end);gw=_rows("gateway_history",start,end);inc=_incidents(start,end)
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("AT-Internet-Performance-Report.pdf",pdf);z.writestr("speedtests.csv",_csv_bytes(speed));z.writestr("ping-packet-loss.csv",_csv_bytes(ping));z.writestr("gateway-wan.csv",_csv_bytes(gw));z.writestr("internet-incidents.csv",_csv_bytes(inc))
    return buf.getvalue()
