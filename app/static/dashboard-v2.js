const $ = (id) => document.getElementById(id);
let rangeHours = 24;
const COLORS = ["#38bdf8", "#c084fc", "#67e8f9", "#f59e0b", "#2dd4bf", "#fb7185", "#94a3b8", "#4ade80"];
const chartState = new Map();

function num(v,d=null){const n=Number(v);return Number.isFinite(n)?n:d;}
function fmt(v,suffix="",digits=1){const n=num(v);return n===null?"—":`${n.toFixed(digits)}${suffix}`;}
function tms(v){const n=new Date(v).getTime();return Number.isFinite(n)?n:null;}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function labelTime(ms){const d=new Date(ms);if(rangeHours<=24)return d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});if(rangeHours<=336)return d.toLocaleDateString([],{weekday:"short",day:"2-digit"});return d.toLocaleDateString([],{day:"2-digit",month:"short"});}
function tooltipTime(ms){return new Date(ms).toLocaleString([], {day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"});}
function thin(points,max=1200){if(points.length<=max)return points;const step=(points.length-1)/(max-1);return Array.from({length:max},(_,i)=>points[Math.round(i*step)]);}
function setLegend(id,series){const el=$(id);if(el)el.innerHTML=series.map((s,i)=>`<span><i style="background:${s.color||COLORS[i%COLORS.length]}"></i>${esc(s.name)}</span>`).join("");}
function formatRuntime(seconds){const s=num(seconds);if(s===null||s<0)return "—";const total=Math.round(s);const h=Math.floor(total/3600),m=Math.floor((total%3600)/60);if(h>0)return `${h}h ${m}m`;return `${m} min`;}

function drawChart(canvasId,emptyId,series,options={}){
  const canvas=$(canvasId), empty=$(emptyId), tooltip=$(`${canvasId}_tooltip`);
  if(!canvas)return;
  const height=Number(canvas.dataset.chartHeight||options.height||280);
  const now=Date.now(), minT=now-rangeHours*3600000, maxT=now;
  const prepared=series.map((s,i)=>({...s,color:s.color||COLORS[i%COLORS.length],points:thin((s.points||[]).map(p=>({ts:p.ts,value:num(p.value)})).filter(p=>p.value!==null&&tms(p.ts)!==null&&tms(p.ts)>=minT&&tms(p.ts)<=maxT).sort((a,b)=>tms(a.ts)-tms(b.ts)))}));
  const valid=prepared.filter(s=>s.points.length);
  if(!valid.length){canvas.style.display="none";if(empty){empty.style.display="flex";empty.style.minHeight=`${height}px`;empty.textContent=options.emptyMessage||"No data in this range.";}if(tooltip)tooltip.style.display="none";chartState.delete(canvasId);return;}
  if(empty)empty.style.display="none";
  canvas.style.display="block";canvas.style.width="100%";canvas.style.height=`${height}px`;
  const width=Math.max(500,Math.floor(canvas.parentElement?.clientWidth||canvas.clientWidth||1000));
  const ratio=Math.min(2,window.devicePixelRatio||1);canvas.width=Math.floor(width*ratio);canvas.height=Math.floor(height*ratio);
  const ctx=canvas.getContext("2d");ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
  const hasRight=valid.some(s=>s.axis==="right");
  const pad={left:58,right:hasRight?58:18,top:16,bottom:34},plotW=width-pad.left-pad.right,plotH=height-pad.top-pad.bottom;
  const leftVals=valid.filter(s=>s.axis!=="right").flatMap(s=>s.points.map(p=>p.value));
  const rightVals=valid.filter(s=>s.axis==="right").flatMap(s=>s.points.map(p=>p.value));
  let leftMin=options.leftMin??0,leftMax=options.leftMax??(leftVals.length?Math.max(...leftVals):1);
  if(options.leftMax===undefined)leftMax+=Math.max(1,(leftMax-leftMin)*.08);if(leftMax===leftMin)leftMax=leftMin+1;
  let rightMin=options.rightMin??0,rightMax=options.rightMax??(rightVals.length?Math.max(...rightVals):100);
  if(options.rightMax===undefined)rightMax+=Math.max(1,(rightMax-rightMin)*.12);if(rightMax===rightMin)rightMax=rightMin+1;
  const x=t=>pad.left+((tms(t)-minT)/(maxT-minT))*plotW;
  const yLeft=v=>pad.top+(1-((v-leftMin)/Math.max(.000001,leftMax-leftMin)))*plotH;
  const yRight=v=>pad.top+(1-((v-rightMin)/Math.max(.000001,rightMax-rightMin)))*plotH;
  ctx.font="11px system-ui";ctx.lineWidth=1;
  for(let i=0;i<=5;i++){
    const yy=pad.top+(plotH/5)*i;ctx.strokeStyle="rgba(148,163,184,.14)";ctx.beginPath();ctx.moveTo(pad.left,yy);ctx.lineTo(width-pad.right,yy);ctx.stroke();
    ctx.fillStyle="#8fa0b5";ctx.textAlign="left";const lv=leftMax-((leftMax-leftMin)/5)*i;ctx.fillText(`${lv.toFixed(options.leftDecimals||0)}${options.leftUnit||""}`,5,yy+4);
    if(hasRight){ctx.textAlign="right";const rv=rightMax-((rightMax-rightMin)/5)*i;ctx.fillText(`${rv.toFixed(options.rightDecimals||0)}${options.rightUnit||""}`,width-5,yy+4);}
  }
  ctx.textAlign="center";ctx.fillStyle="#8fa0b5";for(let i=0;i<=6;i++){const xx=pad.left+(plotW/6)*i;ctx.fillText(labelTime(minT+((maxT-minT)/6)*i),xx,height-9);}ctx.textAlign="start";
  const hitPoints=[];
  valid.forEach((s,i)=>{
    const y=s.axis==="right"?yRight:yLeft;ctx.strokeStyle=s.color;ctx.lineWidth=s.width||2;ctx.lineJoin="round";ctx.lineCap="round";ctx.beginPath();
    s.points.forEach((p,j)=>{const px=x(p.ts),py=y(p.value);j?ctx.lineTo(px,py):ctx.moveTo(px,py);});ctx.stroke();
    s.points.forEach(p=>{const px=x(p.ts),py=y(p.value);ctx.beginPath();ctx.fillStyle=s.color;ctx.arc(px,py,s.pointRadius||2.8,0,Math.PI*2);ctx.fill();ctx.strokeStyle="#0e1116";ctx.lineWidth=1;ctx.stroke();hitPoints.push({x:px,y:py,ts:tms(p.ts),value:p.value,name:s.name,color:s.color,unit:s.unit||""});});
  });
  chartState.set(canvasId,{hitPoints,width,height});
  if(!canvas.dataset.hoverBound){canvas.dataset.hoverBound="1";canvas.addEventListener("mousemove",ev=>handleChartHover(canvasId,ev));canvas.addEventListener("mouseleave",()=>{const tip=$(`${canvasId}_tooltip`);if(tip)tip.style.display="none";});}
}

function handleChartHover(canvasId,ev){
  const state=chartState.get(canvasId), canvas=$(canvasId), tip=$(`${canvasId}_tooltip`);if(!state||!canvas||!tip)return;
  const rect=canvas.getBoundingClientRect(), mx=ev.clientX-rect.left, my=ev.clientY-rect.top;
  let nearest=null,dist=Infinity;for(const p of state.hitPoints){const d=Math.hypot(p.x-mx,p.y-my);if(d<dist){dist=d;nearest=p;}}
  if(!nearest||dist>20){tip.style.display="none";return;}
  const sameTime=state.hitPoints.filter(p=>Math.abs(p.ts-nearest.ts)<=60000);
  tip.innerHTML=`<strong>${tooltipTime(nearest.ts)}</strong>${sameTime.map(p=>`<span><i style="background:${p.color}"></i>${esc(p.name)} <b>${Number(p.value).toFixed(p.unit==='%'?1:0)}${esc(p.unit)}</b></span>`).join("")}`;
  tip.style.display="grid";const maxLeft=Math.max(8,rect.width-tip.offsetWidth-8);tip.style.left=`${Math.min(maxLeft,Math.max(8,mx+12))}px`;tip.style.top=`${Math.max(8,my-tip.offsetHeight-10)}px`;
}

async function getJson(url,opts){const r=await fetch(url,{cache:"no-store",...(opts||{})});if(!r.ok)throw new Error(`${url}: HTTP ${r.status}`);return r.json();}
function latest(rows){return rows?.length?rows[rows.length-1]:null;}

async function runSpeedTest(){const btn=$("run_speedtest_button"),status=$("run_speedtest_status");if(!btn)return;btn.disabled=true;if(status){status.textContent="Starting…";status.className="test-status testing";}try{const result=await getJson('/api/settings/test/speedtest',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(status){status.textContent=result.ok?(result.message||'Speed test started'):(result.message||'Failed');status.className=`test-status ${result.ok?'good':'bad'}`;}if(result.ok)setTimeout(loadDashboard,12000);}catch(e){if(status){status.textContent=e.message;status.className='test-status bad';}}finally{btn.disabled=false;}}

async function loadDashboard(){
  try{
    const [live,speed,ping,gateway,ups,wifi,wan]=await Promise.all([
      getJson('/api/monitoring/live'),getJson(`/api/monitoring/speedtests?hours=${rangeHours}`),getJson(`/api/monitoring/ping?hours=${rangeHours}`),getJson(`/api/monitoring/gateway?hours=${rangeHours}`),getJson(`/api/monitoring/ups?hours=${rangeHours}`),getJson(`/api/monitoring/wifi?hours=${rangeHours}`),getJson(`/api/monitoring/unifi-wan?hours=${rangeHours}`)
    ]);
    const p=live.ping;if(p){$('internet_state').textContent=p.online?'ONLINE':'OFFLINE';$('internet_state').className=p.online?'state-good':'state-bad';$('internet_detail').textContent=`${fmt(p.latency,' ms')} · ${fmt(p.packet_loss,'%')} loss`;}
    const s=live.speedtest;if(s){$('speed_state').textContent=`${Math.round(num(s.download,0))} ↓`;$('speed_detail').textContent=`${Math.round(num(s.upload,0))} Mbps ↑ · ${fmt(s.latency,' ms')}`;}
    const u=live.ups;if(u){const mains=String(u.status||'').includes('OL');$('ups_state').textContent=u.connected?(mains?'ON MAINS':(u.status||'CONNECTED')):'DISCONNECTED';$('ups_state').className=u.connected&&mains?'state-good':'state-bad';$('ups_detail').textContent=`${fmt(u.load_pct,'%')} load · ${fmt(u.input_voltage,' V')}`;$('ups_input').textContent=fmt(u.input_voltage,' V');$('ups_output').textContent=fmt(u.output_voltage,' V');$('ups_battery').textContent=fmt(u.battery_voltage,' V');$('ups_load').textContent=fmt(u.load_pct,'%');$('ups_runtime').textContent=formatRuntime(u.runtime_seconds);$('ups_status').textContent=mains?'ON MAINS':(u.status||'—');$('ups_status').className=mains?'state-good':'';}
    const g=live.gateway;if(g){$('gateway_cpu').textContent=fmt(g.cpu,'%');$('gateway_mem').textContent=fmt(g.memory,'%');$('gateway_cpu_detail').textContent=g.temperature!=null?`${fmt(g.temperature,' °C')} CPU temp`:'UniFi gateway';$('gateway_mem_detail').textContent=g.wan_up?'WAN online':'WAN offline';}
    const radios=live.wifi||[];if(radios.length){const worst=Math.max(...radios.map(r=>num(r.retries,0)));$('wifi_state').textContent=worst>=40?'ATTENTION':worst>=30?'WATCH':'HEALTHY';$('wifi_state').className=worst>=40?'state-bad':worst>=30?'state-warn':'state-good';$('wifi_detail').textContent=`Worst retries ${worst.toFixed(1)}% · ${radios.length} radios`;}
    await new Promise(r=>requestAnimationFrame(r));
    const ispSeries=[
      {name:'Download',color:COLORS[0],unit:' Mbps',points:speed.map(r=>({ts:r.ts,value:r.download}))},
      {name:'Upload',color:COLORS[1],unit:' Mbps',points:speed.map(r=>({ts:r.ts,value:r.upload}))},
      {name:'Ping',color:COLORS[2],unit:' ms',axis:'right',points:ping.map(r=>({ts:r.ts,value:r.latency}))},
      {name:'Packet Loss',color:COLORS[3],unit:'%',axis:'right',points:ping.map(r=>({ts:r.ts,value:r.packet_loss}))}
    ];
    setLegend('speed_legend',ispSeries);drawChart('speed_chart','speed_empty',ispSeries,{leftMin:0,leftUnit:'',rightMin:0,rightUnit:' ms/%',emptyMessage:'No ISP monitoring data is stored in this selected range yet.'});
    setLegend('wan_legend',[{name:'WAN Receive GB',color:COLORS[0]},{name:'WAN Transmit GB',color:COLORS[4]}]);drawChart('wan_chart','wan_empty',[{name:'Receive',color:COLORS[0],unit:' GB',points:wan.map(r=>({ts:r.ts,value:num(r.rx_bytes,0)/1e9}))},{name:'Transmit',color:COLORS[4],unit:' GB',points:wan.map(r=>({ts:r.ts,value:num(r.tx_bytes,0)/1e9}))}],{leftMin:0,leftUnit:' GB',leftDecimals:1,emptyMessage:'No imported UniFi WAN history is available in this selected range.'});
    setLegend('gateway_legend',[{name:'CPU %',color:COLORS[0]},{name:'Memory %',color:COLORS[1]},{name:'Temperature °C',color:COLORS[3]}]);drawChart('gateway_chart','gateway_empty',[{name:'CPU',color:COLORS[0],unit:'%',points:gateway.map(r=>({ts:r.ts,value:r.cpu}))},{name:'Memory',color:COLORS[1],unit:'%',points:gateway.map(r=>({ts:r.ts,value:r.memory}))},{name:'Temperature',color:COLORS[3],unit:' °C',points:gateway.map(r=>({ts:r.ts,value:r.temperature}))}],{leftMin:0,leftMax:100,leftUnit:'%',emptyMessage:'No gateway samples are stored in this selected range yet.'});
    const gw=latest(gateway);$('gateway_stats').innerHTML=gw?`<div><span>WAN</span><strong>${gw.wan_up?'ONLINE':'OFFLINE'}</strong></div><div><span>WAN IP</span><strong>${esc(gw.wan_ip||'—')}</strong></div><div><span>Link</span><strong>${gw.link_speed?`${gw.link_speed} Mbps`:'—'}</strong></div><div><span>RX errors</span><strong>${gw.rx_errors??'—'}</strong></div><div><span>TX errors</span><strong>${gw.tx_errors??'—'}</strong></div><div><span>RX dropped</span><strong>${gw.rx_dropped??'—'}</strong></div>`:'';
    setLegend('ups_legend',[{name:'UPS Load %',color:COLORS[4]}]);drawChart('ups_chart','ups_empty',[{name:'UPS Load',color:COLORS[4],unit:'%',points:ups.filter(r=>r.connected).map(r=>({ts:r.ts,value:r.load_pct}))}],{leftMin:0,leftMax:100,leftUnit:'%',emptyMessage:'No UPS samples are stored in this selected range yet.'});
    const keys=[...new Set(wifi.map(r=>`${r.ap_name}|${r.band}`))],ws=keys.slice(0,8).map((k,i)=>{const [ap,band]=k.split('|');return{name:`${ap} ${band} retries`,color:COLORS[i%COLORS.length],unit:'%',points:wifi.filter(r=>`${r.ap_name}|${r.band}`===k).map(r=>({ts:r.ts,value:r.retries}))};});setLegend('wifi_legend',ws);drawChart('wifi_chart','wifi_empty',ws,{leftMin:0,leftMax:100,leftUnit:'%',emptyMessage:'No Wi-Fi retry samples are stored in this selected range yet.'});
    $('wifi_cards').innerHTML=radios.map(r=>{const retries=num(r.retries,0),st=retries>=40?'bad':retries>=30?'warn':'good';return`<article class="wifi-radio-card ${st}"><div class="wifi-card-title"><strong>${esc(r.ap_name)}</strong><span>${esc(r.band)}</span></div><div class="wifi-card-metrics"><div><span>Channel</span><strong>${esc(r.channel)}</strong></div><div><span>Width</span><strong>${esc(r.width)} MHz</strong></div><div><span>Retries</span><strong>${retries.toFixed(1)}%</strong></div><div><span>Utilisation</span><strong>${num(r.utilization,0).toFixed(0)}%</strong></div><div><span>Clients</span><strong>${esc(r.clients)}</strong></div><div><span>TX Power</span><strong>${esc(r.tx_power)}</strong></div></div></article>`}).join('');
    const overall=$('overall_status'),bad=(p&&!p.online)||(u&&!u.connected)||(g&&!g.wan_up);overall.textContent=bad?'NEEDS ATTENTION':'SYSTEM HEALTHY';overall.className=`status-pill ${bad?'warn':'good'}`;
  }catch(e){console.error(e);$('overall_status').textContent='DATA ERROR';$('overall_status').className='status-pill bad';}
}

document.querySelectorAll('[data-range-group] .range-button').forEach(btn=>btn.addEventListener('click',async()=>{rangeHours=Number(btn.dataset.hours||24);document.querySelectorAll('[data-range-group] .range-button').forEach(b=>b.classList.toggle('active',b===btn));await loadDashboard();}));
$('run_speedtest_button')?.addEventListener('click',runSpeedTest);
window.addEventListener('resize',()=>{clearTimeout(window.__chartResize);window.__chartResize=setTimeout(loadDashboard,180);});
loadDashboard();setInterval(loadDashboard,30000);
