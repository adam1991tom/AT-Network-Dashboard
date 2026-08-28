from __future__ import annotations

import csv
import io
import statistics
import zipfile
from datetime import datetime, timezone

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
    if not vals: return {"min":None,"max":None,"avg":None}
    return {"min":min(vals),"max":max(vals),"avg":statistics.fmean(vals)}


def _fmt(v, d=1):
    return "—" if v is None else f"{float(v):.{d}f}"


def build_pdf(start: str, end: str) -> bytes:
    cfg = all_settings()
    speed = _rows("speedtest_history", start, end)
    ping = _rows("ping_history", start, end)
    gw = _rows("gateway_history", start, end)
    incidents = _incidents(start, end)
    down = _stats([r.get("download") for r in speed]); up = _stats([r.get("upload") for r in speed]); lat = _stats([r.get("latency") for r in ping]); loss = _stats([r.get("packet_loss") for r in ping])
    target_down = float(cfg.get("expected_download") or 0); target_up = float(cfg.get("expected_upload") or 0)
    warning = float(cfg.get("warning_threshold") or 0); major = float(cfg.get("major_threshold") or 0); critical = float(cfg.get("critical_threshold") or 0)
    below_warning = sum(1 for r in speed if warning and (r.get("download") or 0) < warning)
    below_major = sum(1 for r in speed if major and (r.get("download") or 0) < major)
    below_critical = sum(1 for r in speed if critical and (r.get("download") or 0) < critical)
    offline = sum(1 for r in ping if not r.get("online"))

    buf = io.BytesIO(); styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=12*mm,leftMargin=12*mm,topMargin=12*mm,bottomMargin=12*mm)
    story=[]
    story.append(Paragraph("AT Network Dashboard — Internet Performance & Reliability Report", styles["Title"]))
    story.append(Paragraph(f"Provider: <b>{cfg.get('isp_provider') or 'Not specified'}</b> &nbsp;&nbsp; Period: <b>{start}</b> to <b>{end}</b>", styles["BodyText"]))
    story.append(Spacer(1,5*mm))
    summary=[
        ["Metric","Result","Configured reference"],
        ["Speed tests",str(len(speed)),f"Target {target_down:g}/{target_up:g} Mbps"],
        ["Download",f"Avg {_fmt(down['avg'])} · Min {_fmt(down['min'])} · Max {_fmt(down['max'])} Mbps",f"Warn {warning:g} · Major {major:g} · Critical {critical:g} Mbps"],
        ["Upload",f"Avg {_fmt(up['avg'])} · Min {_fmt(up['min'])} · Max {_fmt(up['max'])} Mbps",f"Target {target_up:g} Mbps"],
        ["Latency",f"Avg {_fmt(lat['avg'])} · Peak {_fmt(lat['max'])} ms",str(cfg.get('ping_target') or '1.1.1.1')],
        ["Packet loss",f"Avg {_fmt(loss['avg'])}% · Peak {_fmt(loss['max'])}% · Offline samples {offline}","Continuous samples"],
        ["Threshold breaches",f"Warning {below_warning} · Major {below_major} · Critical {below_critical}","Download speed"],
        ["Internet incidents",str(len(incidents)),"ISP / Internet / Gateway only"],
    ]
    t=Table(summary,colWidths=[50*mm,125*mm,90*mm]); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.35,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,0),(-1,-1),8),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f3f4f6')])]))
    story.append(t); story.append(Spacer(1,5*mm))
    if speed:
        story.append(Paragraph("Speed Test Evidence", styles["Heading2"]))
        data=[["Date / Time","Download Mbps","Upload Mbps","Latency ms","Source"]]
        for r in speed[-250:]: data.append([str(r.get('ts','')), _fmt(r.get('download')), _fmt(r.get('upload')), _fmt(r.get('latency')), str(r.get('source',''))])
        st=Table(data,repeatRows=1,colWidths=[65*mm,35*mm,35*mm,30*mm,35*mm]); st.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7)])); story.append(st)
    story.append(PageBreak())
    story.append(Paragraph("Internet Incidents / Fault Evidence", styles["Heading2"]))
    if incidents:
        data=[["Severity","Started","Ended","Summary","Details"]]
        for r in incidents: data.append([str(r.get('severity','')).upper(),str(r.get('started_at','')),str(r.get('ended_at') or 'ACTIVE'),str(r.get('summary','')),str(r.get('details',''))[:180]])
        it=Table(data,repeatRows=1,colWidths=[25*mm,45*mm,45*mm,70*mm,90*mm]); it.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1f2937')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'TOP')])); story.append(it)
    else: story.append(Paragraph("No ISP/Internet/Gateway incidents were recorded in this period.", styles["BodyText"]))
    story.append(Spacer(1,5*mm)); story.append(Paragraph("WAN / Gateway Evidence", styles["Heading2"]))
    if gw:
        latest=gw[-1]
        story.append(Paragraph(f"Latest WAN state: {'ONLINE' if latest.get('wan_up') else 'OFFLINE'} · Link {latest.get('link_speed') or '—'} Mbps · RX errors {latest.get('rx_errors') or 0} · TX errors {latest.get('tx_errors') or 0} · RX dropped {latest.get('rx_dropped') or 0} · TX dropped {latest.get('tx_dropped') or 0}.", styles["BodyText"]))
    story.append(Spacer(1,4*mm)); story.append(Paragraph("This report is generated from timestamped measurements stored by AT Network Dashboard. Raw ISP evidence is available in the matching evidence ZIP export.", styles["Italic"]))
    doc.build(story); return buf.getvalue()


def _csv_bytes(rows: list[dict]) -> bytes:
    out=io.StringIO()
    if not rows: return b""
    w=csv.DictWriter(out,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    return out.getvalue().encode()


def build_evidence_zip(start: str, end: str) -> bytes:
    pdf=build_pdf(start,end); buf=io.BytesIO()
    speed=_rows("speedtest_history",start,end); ping=_rows("ping_history",start,end); gw=_rows("gateway_history",start,end); inc=_incidents(start,end)
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("AT-Internet-Performance-Report.pdf",pdf)
        z.writestr("speedtests.csv",_csv_bytes(speed)); z.writestr("ping-packet-loss.csv",_csv_bytes(ping)); z.writestr("gateway-wan.csv",_csv_bytes(gw)); z.writestr("internet-incidents.csv",_csv_bytes(inc))
    return buf.getvalue()
