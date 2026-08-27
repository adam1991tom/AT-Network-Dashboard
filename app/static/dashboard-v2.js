const $ = (id) => document.getElementById(id);
let rangeHours = 24;
const COLORS = ["#38bdf8", "#fb7185", "#f59e0b", "#a78bfa", "#2dd4bf", "#facc15", "#94a3b8", "#4ade80"];

function num(v, d = null) { const n = Number(v); return Number.isFinite(n) ? n : d; }
function fmt(v, suffix = "", digits = 1) { const n = num(v); return n === null ? "—" : `${n.toFixed(digits)}${suffix}`; }
function ts(v) { const n = new Date(v).getTime(); return Number.isFinite(n) ? n : null; }
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}

function labelTime(ms) {
  const d = new Date(ms);
  if (rangeHours <= 24) return d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
  if (rangeHours <= 24 * 14) return d.toLocaleDateString([], {weekday:"short", day:"2-digit"});
  return d.toLocaleDateString([], {day:"2-digit", month:"short"});
}

function thin(points, max = 1200) {
  if (points.length <= max) return points;
  const step = (points.length - 1) / (max - 1);
  return Array.from({length:max}, (_,i) => points[Math.round(i * step)]);
}

function setLegend(id, series) {
  const el = $(id); if (!el) return;
  el.innerHTML = series.map((s,i)=>`<span><i style="background:${s.color || COLORS[i % COLORS.length]}"></i>${esc(s.name)}</span>`).join("");
}

function drawChart(canvasId, emptyId, series, options = {}) {
  const canvas = $(canvasId), empty = $(emptyId); if (!canvas) return;
  const height = Number(canvas.dataset.chartHeight || options.height || 280);
  const prepared = series.map((s)=>({...s, points: thin((s.points||[]).map(p=>({ts:p.ts,value:num(p.value)})).filter(p=>p.value!==null && ts(p.ts)!==null).sort((a,b)=>ts(a.ts)-ts(b.ts)))}));
  const valid = prepared.filter(s=>s.points.length);
  if (!valid.length) {
    canvas.style.display="none";
    if (empty) { empty.style.display="flex"; empty.style.minHeight=`${height}px`; empty.textContent=options.emptyMessage||"No data in this range."; }
    return;
  }
  if (empty) empty.style.display="none";
  canvas.style.display="block";
  canvas.style.width="100%";
  canvas.style.height=`${height}px`;
  const width = Math.max(500, Math.floor(canvas.parentElement?.clientWidth || canvas.clientWidth || 1000));
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.floor(width * ratio); canvas.height = Math.floor(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,width,height);
  const pad={left:58,right:18,top:16,bottom:34}, plotW=width-pad.left-pad.right, plotH=height-pad.top-pad.bottom;
  const now=Date.now();
  const minT=now-(rangeHours*3600000), maxT=now;
  const all=valid.flatMap(s=>s.points).filter(p=>ts(p.ts)>=minT && ts(p.ts)<=maxT);
  if (!all.length) { canvas.style.display="none"; if(empty){empty.style.display="flex";empty.style.minHeight=`${height}px`;empty.textContent=options.emptyMessage||"No data in this range.";} return; }
  let values=all.map(p=>p.value); let minV=options.min ?? Math.min(...values), maxV=options.max ?? Math.max(...values);
  if (options.zeroBase !== false) minV=Math.min(0,minV);
  if (maxV===minV) maxV=minV+1;
  if (options.max===undefined) maxV += Math.max(.5,(maxV-minV)*.08);
  const x=(t)=>pad.left+((ts(t)-minT)/(maxT-minT))*plotW;
  const y=(v)=>pad.top+(1-((v-minV)/Math.max(.000001,maxV-minV)))*plotH;
  ctx.strokeStyle="rgba(148,163,184,.14)"; ctx.fillStyle="#8fa0b5"; ctx.font="11px system-ui"; ctx.lineWidth=1;
  for(let i=0;i<=5;i++){const yy=pad.top+(plotH/5)*i;ctx.beginPath();ctx.moveTo(pad.left,yy);ctx.lineTo(width-pad.right,yy);ctx.stroke();const val=maxV-((maxV-minV)/5)*i;ctx.fillText(`${val.toFixed(options.decimals||0)}${options.unit||""}`,5,yy+4);}
  ctx.textAlign="center";
  for(let i=0;i<=6;i++){const xx=pad.left+(plotW/6)*i;const t=minT+((maxT-minT)/6)*i;ctx.fillText(labelTime(t),xx,height-9);}
  ctx.textAlign="start";
  valid.forEach((s,i)=>{const pts=s.points.filter(p=>ts(p.ts)>=minT&&ts(p.ts)<=maxT);if(!pts.length)return;ctx.strokeStyle=s.color||COLORS[i%COLORS.length];ctx.lineWidth=2;ctx.lineJoin="round";ctx.lineCap="round";ctx.beginPath();pts.forEach((p,j)=>{const px=x(p.ts),py=y(p.value);if(j===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);});ctx.stroke();if(pts.length===1){ctx.beginPath();ctx.arc(x(pts[0].ts),y(pts[0].value),3,0,Math.PI*2);ctx.fillStyle=s.color||COLORS[i%COLORS.length];ctx.fill();}});
}

async function getJson(url){const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw new Error(`${url}: HTTP ${r.status}`);return r.json();}
function latest(rows){return rows?.length?rows[rows.length-1]:null;}

async function loadDashboard(){
  try{
    const [live,speed,ping,gateway,ups,wifi,wan]=await Promise.all([
      getJson('/api/monitoring/live'),
      getJson(`/api/monitoring/speedtests?hours=${rangeHours}`),
      getJson(`/api/monitoring/ping?hours=${rangeHours}`),
      getJson(`/api/monitoring/gateway?hours=${rangeHours}`),
      getJson(`/api/monitoring/ups?hours=${rangeHours}`),
      getJson(`/api/monitoring/wifi?hours=${rangeHours}`),
      getJson(`/api/monitoring/unifi-wan?hours=${rangeHours}`)
    ]);

    const p=live.ping;if(p){$('internet_state').textContent=p.online?'ONLINE':'OFFLINE';$('internet_state').className=p.online?'state-good':'state-bad';$('internet_detail').textContent=`${fmt(p.latency,' ms')} · ${fmt(p.packet_loss,'%')} loss`;}
    const s=live.speedtest;if(s){$('speed_state').textContent=`${Math.round(num(s.download,0))} ↓`;$('speed_detail').textContent=`${Math.round(num(s.upload,0))} Mbps ↑ · ${fmt(s.latency,' ms')}`;}
    const u=live.ups;if(u){const mains=String(u.status||'').includes('OL');$('ups_state').textContent=u.connected?(mains?'ON MAINS':(u.status||'CONNECTED')):'DISCONNECTED';$('ups_state').className=u.connected&&mains?'state-good':'state-bad';$('ups_detail').textContent=`${fmt(u.load_pct,'%')} load · ${fmt(u.input_voltage,' V')}`;}
    const g=live.gateway;if(g){$('gateway_cpu').textContent=fmt(g.cpu,'%');$('gateway_mem').textContent=fmt(g.memory,'%');$('gateway_cpu_detail').textContent=g.temperature!=null?`${fmt(g.temperature,' °C')} CPU temp`:'UniFi gateway';$('gateway_mem_detail').textContent=g.wan_up?'WAN online':'WAN offline';}
    const radios=live.wifi||[];if(radios.length){const worst=Math.max(...radios.map(r=>num(r.retries,0)));$('wifi_state').textContent=worst>=40?'ATTENTION':worst>=30?'WATCH':'HEALTHY';$('wifi_state').className=worst>=40?'state-bad':worst>=30?'state-warn':'state-good';$('wifi_detail').textContent=`Worst retries ${worst.toFixed(1)}% · ${radios.length} radios`;}

    await new Promise(r=>requestAnimationFrame(r));
    setLegend('speed_legend',[{name:'Download Mbps',color:COLORS[0]},{name:'Upload Mbps',color:COLORS[1]}]);
    drawChart('speed_chart','speed_empty',[{name:'Download',color:COLORS[0],points:speed.map(r=>({ts:r.ts,value:r.download}))},{name:'Upload',color:COLORS[1],points:speed.map(r=>({ts:r.ts,value:r.upload}))}],{emptyMessage:'No ISP speed-test results are stored in this selected range yet.'});
    setLegend('quality_legend',[{name:'Ping ms',color:COLORS[0]},{name:'Packet Loss %',color:COLORS[2]}]);
    drawChart('quality_chart','quality_empty',[{name:'Ping',color:COLORS[0],points:ping.map(r=>({ts:r.ts,value:r.latency}))},{name:'Packet Loss',color:COLORS[2],points:ping.map(r=>({ts:r.ts,value:r.packet_loss}))}],{min:0,emptyMessage:'No internet-quality samples are stored in this selected range yet.'});
    setLegend('wan_legend',[{name:'WAN Receive GB',color:COLORS[0]},{name:'WAN Transmit GB',color:COLORS[4]}]);
    drawChart('wan_chart','wan_empty',[{name:'Receive',color:COLORS[0],points:wan.map(r=>({ts:r.ts,value:num(r.rx_bytes,0)/1e9}))},{name:'Transmit',color:COLORS[4],points:wan.map(r=>({ts:r.ts,value:num(r.tx_bytes,0)/1e9}))}],{min:0,unit:' GB',decimals:1,emptyMessage:'No imported UniFi WAN history is available in this selected range.'});
    setLegend('gateway_legend',[{name:'CPU %',color:COLORS[0]},{name:'Memory %',color:COLORS[3]},{name:'Temperature °C',color:COLORS[2]}]);
    drawChart('gateway_chart','gateway_empty',[{name:'CPU',color:COLORS[0],points:gateway.map(r=>({ts:r.ts,value:r.cpu}))},{name:'Memory',color:COLORS[3],points:gateway.map(r=>({ts:r.ts,value:r.memory}))},{name:'Temperature',color:COLORS[2],points:gateway.map(r=>({ts:r.ts,value:r.temperature}))}],{min:0,max:100,unit:'%',emptyMessage:'No gateway samples are stored in this selected range yet.'});
    const gw=latest(gateway);$('gateway_stats').innerHTML=gw?`<div><span>WAN</span><strong>${gw.wan_up?'ONLINE':'OFFLINE'}</strong></div><div><span>WAN IP</span><strong>${esc(gw.wan_ip||'—')}</strong></div><div><span>Link</span><strong>${gw.link_speed?`${gw.link_speed} Mbps`:'—'}</strong></div><div><span>RX errors</span><strong>${gw.rx_errors??'—'}</strong></div><div><span>TX errors</span><strong>${gw.tx_errors??'—'}</strong></div><div><span>RX dropped</span><strong>${gw.rx_dropped??'—'}</strong></div>`:'';
    setLegend('ups_legend',[{name:'UPS Load %',color:COLORS[4]}]);
    drawChart('ups_chart','ups_empty',[{name:'UPS Load',color:COLORS[4],points:ups.filter(r=>r.connected).map(r=>({ts:r.ts,value:r.load_pct}))}],{min:0,max:100,unit:'%',emptyMessage:'No UPS samples are stored in this selected range yet.'});
    const up=latest(ups);if(up)$('ups_legend').insertAdjacentHTML('beforeend',`<span class="current-values">Input ${fmt(up.input_voltage,' V')} · Output ${fmt(up.output_voltage,' V')} · Battery ${fmt(up.battery_voltage,' V')} · ${fmt(up.input_frequency,' Hz')}</span>`);
    const keys=[...new Set(wifi.map(r=>`${r.ap_name}|${r.band}`))];const wifiSeries=keys.slice(0,8).map((k,i)=>{const [ap,band]=k.split('|');return{name:`${ap} ${band} retries`,color:COLORS[i%COLORS.length],points:wifi.filter(r=>`${r.ap_name}|${r.band}`===k).map(r=>({ts:r.ts,value:r.retries}))};});setLegend('wifi_legend',wifiSeries);drawChart('wifi_chart','wifi_empty',wifiSeries,{min:0,max:100,unit:'%',emptyMessage:'No Wi-Fi retry samples are stored in this selected range yet.'});
    $('wifi_cards').innerHTML=radios.map(r=>{const retries=num(r.retries,0),st=retries>=40?'bad':retries>=30?'warn':'good';return`<article class="wifi-radio-card ${st}"><div class="wifi-card-title"><strong>${esc(r.ap_name)}</strong><span>${esc(r.band)}</span></div><div class="wifi-card-metrics"><div><span>Channel</span><strong>${esc(r.channel)}</strong></div><div><span>Width</span><strong>${esc(r.width)} MHz</strong></div><div><span>Retries</span><strong>${retries.toFixed(1)}%</strong></div><div><span>Utilisation</span><strong>${num(r.utilization,0).toFixed(0)}%</strong></div><div><span>Clients</span><strong>${esc(r.clients)}</strong></div><div><span>TX Power</span><strong>${esc(r.tx_power)}</strong></div></div></article>`}).join('');
    const overall=$('overall_status');const bad=(p&&!p.online)||(u&&!u.connected)||(g&&!g.wan_up);overall.textContent=bad?'NEEDS ATTENTION':'SYSTEM HEALTHY';overall.className=`status-pill ${bad?'warn':'good'}`;
  }catch(e){console.error('Dashboard load failed',e);$('overall_status').textContent='DATA ERROR';$('overall_status').className='status-pill bad';}
}

document.querySelectorAll('[data-range-group] .range-button').forEach(btn=>btn.addEventListener('click',async()=>{rangeHours=Number(btn.dataset.hours||24);document.querySelectorAll('[data-range-group] .range-button').forEach(b=>b.classList.toggle('active',b===btn));await loadDashboard();}));
window.addEventListener('resize',()=>{clearTimeout(window.__chartResize);window.__chartResize=setTimeout(loadDashboard,180);});
loadDashboard();setInterval(loadDashboard,30000);
