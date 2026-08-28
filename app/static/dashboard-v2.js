const $ = id => document.getElementById(id);
let rangeHours = 24;
const C = ['#00d7ff','#ff45ef','#58ff7d','#ffb000','#00efc2','#ff5a7d','#aebbd0','#43ffa0','#ffd84a','#7aa2ff'];
const states = new Map();
const hidden = new Set();
const n=(v,d=null)=>Number.isFinite(Number(v))?Number(v):d;
const fmt=(v,s='',d=1)=>n(v)===null?'—':`${n(v).toFixed(d)}${s}`;
const tm=v=>{const x=new Date(v).getTime();return Number.isFinite(x)?x:null};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const seriesKey=(chartId,name)=>`${chartId}::${name}`;
try{for(const k of JSON.parse(localStorage.getItem('at-chart-hidden')||'[]'))hidden.add(k)}catch(e){}
function saveHidden(){try{localStorage.setItem('at-chart-hidden',JSON.stringify([...hidden]))}catch(e){}}
function timeLabel(ms){const d=new Date(ms);if(rangeHours<=24)return d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});if(rangeHours<=336)return d.toLocaleDateString([],{weekday:'short',day:'2-digit'});return d.toLocaleDateString([],{day:'2-digit',month:'short'})}
function thin(a,max=1400){if(a.length<=max)return a;const step=(a.length-1)/(max-1);return Array.from({length:max},(_,i)=>a[Math.round(i*step)])}
function runtime(sec){const s=n(sec);if(s===null||s<=0)return'Not reported';const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);return h?`${h}h ${m}m`:`${m} min`}
function uniqueSpeedRows(rows){const m=new Map();for(const r of rows||[]){const k=r.epoch_ms||tm(r.ts);if(k)m.set(String(k),r)}return [...m.values()].sort((a,b)=>tm(a.ts)-tm(b.ts))}

function legend(id,chartId,series){
  const el=$(id);if(!el)return;
  el.innerHTML=series.map((s,i)=>{const off=hidden.has(seriesKey(chartId,s.name));return `<button type="button" class="legend-toggle ${off?'is-off':'is-on'}" data-series="${esc(s.name)}" aria-pressed="${off?'false':'true'}"><i style="background:${s.color||C[i%C.length]}"></i><span>${esc(s.label||s.name)}</span></button>`}).join('')+(series.length>2?'<button type="button" class="legend-show-all">Show all</button>':'');
  el.querySelectorAll('.legend-toggle').forEach(btn=>btn.addEventListener('click',()=>{const k=seriesKey(chartId,btn.dataset.series);hidden.has(k)?hidden.delete(k):hidden.add(k);saveHidden();load()}));
  const all=el.querySelector('.legend-show-all');if(all){const allOn=series.every(s=>!hidden.has(seriesKey(chartId,s.name)));all.classList.toggle('all-on',allOn);all.addEventListener('click',()=>{for(const s of series)hidden.delete(seriesKey(chartId,s.name));saveHidden();load()})}
}

function chart(canvasId,emptyId,series,o={}){
  const cv=$(canvasId),empty=$(emptyId),tip=$(`${canvasId}_tooltip`);if(!cv)return;
  const H=Number(cv.dataset.chartHeight||o.height||260),now=Date.now(),minT=now-rangeHours*3600000,maxT=now;
  const visible=series.filter(s=>!hidden.has(seriesKey(canvasId,s.name))).map((s,i)=>({...s,color:s.color||C[i%C.length],points:thin((s.points||[]).map(p=>({ts:p.ts,value:n(p.value)})).filter(p=>p.value!==null&&tm(p.ts)!==null&&tm(p.ts)>=minT&&tm(p.ts)<=maxT).sort((a,b)=>tm(a.ts)-tm(b.ts)))})).filter(s=>s.points.length);
  if(!visible.length){cv.style.display='none';if(empty){empty.style.display='flex';empty.style.minHeight=`${H}px`;empty.textContent=o.empty||'No visible data in this range.'}if(tip)tip.style.display='none';states.delete(canvasId);return}
  if(empty)empty.style.display='none';cv.style.display='block';
  const W=Math.max(500,Math.floor(cv.parentElement?.clientWidth||1000)),ratio=Math.min(2,window.devicePixelRatio||1);cv.width=W*ratio;cv.height=H*ratio;cv.style.width='100%';cv.style.height=`${H}px`;
  const ctx=cv.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,W,H);
  const hasR=visible.some(s=>s.axis==='right'),pad={left:60,right:hasR?66:20,top:16,bottom:34},pw=W-pad.left-pad.right,ph=H-pad.top-pad.bottom;
  const scaleLeft=visible.filter(s=>s.axis!=='right'&&s.affectsScale!==false).flatMap(s=>s.points.map(p=>p.value));
  const scaleRight=visible.filter(s=>s.axis==='right'&&s.affectsScale!==false).flatMap(s=>s.points.map(p=>p.value));
  let lmin=o.leftMin??(scaleLeft.length?Math.min(...scaleLeft):0),lmax=o.leftMax??(scaleLeft.length?Math.max(...scaleLeft):1);
  if(o.zoomLeft&&scaleLeft.length){const span=Math.max(o.minSpan||20,lmax-lmin),padv=span*(o.zoomPad??.15);lmin=Math.max(0,lmin-padv);lmax+=padv}else if(o.zeroBase!==false)lmin=Math.min(0,lmin);if(lmax===lmin)lmax=lmin+1;
  let rmin=o.rightMin??(scaleRight.length?Math.min(...scaleRight):0),rmax=o.rightMax??(scaleRight.length?Math.max(...scaleRight):1);
  if(o.zoomRight&&scaleRight.length){const span=Math.max(o.rightMinSpan||5,rmax-rmin);rmin=Math.max(0,rmin-span*.15);rmax+=span*.15}else rmin=Math.min(0,rmin);if(rmax===rmin)rmax=rmin+1;
  const X=t=>pad.left+((tm(t)-minT)/(maxT-minT))*pw,Y=(v,a)=>pad.top+(1-(v-(a==='right'?rmin:lmin))/Math.max(.00001,(a==='right'?rmax-rmin:lmax-lmin)))*ph;
  ctx.font='11px system-ui';
  for(let i=0;i<=5;i++){const y=pad.top+(ph/5)*i;ctx.strokeStyle='rgba(148,163,184,.14)';ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(W-pad.right,y);ctx.stroke();ctx.fillStyle='#8fa0b5';ctx.textAlign='left';ctx.fillText(`${(lmax-((lmax-lmin)/5)*i).toFixed(o.leftDecimals||0)}${o.leftUnit||''}`,5,y+4);if(hasR){ctx.textAlign='right';ctx.fillText(`${(rmax-((rmax-rmin)/5)*i).toFixed(o.rightDecimals||0)}${o.rightUnit||''}`,W-5,y+4)}}
  ctx.fillStyle='#8fa0b5';ctx.textAlign='center';for(let i=0;i<=6;i++)ctx.fillText(timeLabel(minT+((maxT-minT)/6)*i),pad.left+(pw/6)*i,H-9);
  const hits=[];
  for(const s of visible){
    ctx.save();
    if(s.dash)ctx.setLineDash(s.dash);
    ctx.strokeStyle=s.color;ctx.globalAlpha=s.opacity??1;ctx.lineWidth=s.width||2;ctx.lineJoin='round';ctx.lineCap='round';ctx.beginPath();
    let drawn=false;
    for(const p of s.points){const yy=Y(p.value,s.axis);if(yy<pad.top-1||yy>pad.top+ph+1)continue;const xx=X(p.ts);if(!drawn){ctx.moveTo(xx,yy);drawn=true}else ctx.lineTo(xx,yy)}
    if(drawn)ctx.stroke();ctx.restore();
    for(const p of s.points){const xx=X(p.ts),yy=Y(p.value,s.axis);if(yy<pad.top||yy>pad.top+ph)continue;if(s.showPoints){ctx.beginPath();ctx.fillStyle=s.color;ctx.arc(xx,yy,s.pointRadius||2.5,0,Math.PI*2);ctx.fill()}if(s.hover!==false)hits.push({x:xx,y:yy,ts:tm(p.ts),value:p.value,name:s.label||s.name,color:s.color,unit:s.unit||''})}
  }
  states.set(canvasId,{hits});
  if(!cv.dataset.bound){cv.dataset.bound='1';cv.addEventListener('mousemove',e=>{const st=states.get(canvasId);if(!st||!tip)return;const rr=cv.getBoundingClientRect(),mx=e.clientX-rr.left,my=e.clientY-rr.top;let q=null,d=1e9;for(const p of st.hits){const z=Math.hypot(p.x-mx,p.y-my);if(z<d){d=z;q=p}}if(!q||d>26){tip.style.display='none';return}const grouped=new Map();for(const p of st.hits){const delta=Math.abs(p.ts-q.ts);if(delta>120000)continue;const old=grouped.get(p.name);if(!old||delta<old.delta)grouped.set(p.name,{...p,delta})}const vals=[...grouped.values()];tip.innerHTML=`<strong>${new Date(q.ts).toLocaleString([],{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})}</strong>${vals.map(p=>`<span><i style="background:${p.color}"></i>${esc(p.name)} <b>${Number(p.value).toFixed(p.unit==='%'?1:p.unit.includes('V')?1:0)}${esc(p.unit)}</b></span>`).join('')}`;tip.style.display='grid';tip.style.left=`${Math.min(rr.width-tip.offsetWidth-8,Math.max(8,mx+12))}px`;tip.style.top=`${Math.max(8,my-tip.offsetHeight-10)}px`});cv.addEventListener('mouseleave',()=>{if(tip)tip.style.display='none'})}
}

async function j(url,opt={}){const r=await fetch(url,{cache:'no-store',...opt});if(r.status===401){location.href='/login';throw new Error('Authentication required')}if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}
async function runSpeed(){const b=$('run_speedtest_button'),s=$('run_speedtest_status');if(!b||!s)return;b.disabled=true;s.textContent='Starting…';s.className='test-status testing';try{const x=await j('/api/settings/test/speedtest',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});s.textContent=x.message||(x.ok?'Speed test started':'Failed');s.className=`test-status ${x.ok?'good':'bad'}`;if(x.ok)setTimeout(load,15000)}catch(e){s.textContent=e.message;s.className='test-status bad'}finally{b.disabled=false}}

async function load(){
  try{
    const [live,speedRaw,ping,gw,ups,wifi,wan,cfg]=await Promise.all([j('/api/monitoring/live'),j(`/api/monitoring/speedtests?hours=${rangeHours}`),j(`/api/monitoring/ping?hours=${rangeHours}`),j(`/api/monitoring/gateway?hours=${rangeHours}`),j(`/api/monitoring/ups?hours=${rangeHours}`),j(`/api/monitoring/wifi?hours=${rangeHours}`),j(`/api/monitoring/unifi-wan?hours=${rangeHours}`),j('/api/settings')]);
    const speed=uniqueSpeedRows(speedRaw),p=live.ping,sp=live.speedtest,u=live.ups,g=live.gateway,radios=live.wifi||[];
    if(p){$('internet_state').textContent=p.online?'ONLINE':'OFFLINE';$('internet_state').className=p.online?'state-good':'state-bad';$('internet_detail').textContent=`${fmt(p.latency,' ms')} · ${fmt(p.packet_loss,'%')} loss`}
    if(sp){$('speed_state').textContent=`${Math.round(n(sp.download,0))} ↓`;$('speed_detail').textContent=`${Math.round(n(sp.upload,0))} Mbps ↑ · ${fmt(sp.latency,' ms')}`}
    if(u){const mains=String(u.status||'').includes('OL');$('ups_state').textContent=u.connected?(mains?'ON MAINS':(u.status||'CONNECTED')):'DISCONNECTED';$('ups_state').className=u.connected&&mains?'state-good':'state-bad';$('ups_detail').textContent=`${fmt(u.load_pct,'%')} load · ${fmt(u.input_voltage,' V')}`;$('ups_input').textContent=fmt(u.input_voltage,' V');$('ups_output').textContent=fmt(u.output_voltage,' V');$('ups_battery').textContent=fmt(u.battery_voltage,' V');$('ups_load').textContent=fmt(u.load_pct,'%');$('ups_runtime').textContent=runtime(u.runtime_seconds);$('ups_status').textContent=mains?'ON MAINS':(u.status||'—');$('ups_status').className=mains?'state-good':''}
    if(g){$('gateway_cpu').textContent=fmt(g.cpu,'%');$('gateway_mem').textContent=fmt(g.memory,'%');$('gateway_cpu_detail').textContent=g.temperature!=null?`${fmt(g.temperature,' °C')} CPU temp`:'UniFi gateway';$('gateway_mem_detail').textContent=g.wan_up?'WAN online':'WAN offline'}
    if(radios.length){const worst=Math.max(...radios.map(r=>n(r.retries,0)));$('wifi_state').textContent=worst>=40?'ATTENTION':worst>=30?'WATCH':'HEALTHY';$('wifi_state').className=worst>=40?'state-bad':worst>=30?'state-warn':'state-good';$('wifi_detail').textContent=`Worst retries ${worst.toFixed(1)}% · ${radios.length} radios`}
    await new Promise(r=>requestAnimationFrame(r));

    const startIso=new Date(Date.now()-rangeHours*3600000).toISOString(),endIso=new Date().toISOString();
    const ref=(name,label,value,color,dash=[7,6])=>({name,label,color,unit:' Mbps',showPoints:false,hover:false,affectsScale:name==='Warning',dash,width:1.3,opacity:.75,points:value>0?[{ts:startIso,value},{ts:endIso,value}]:[]});
    const isp=[
      {name:'Download',color:C[0],unit:' Mbps',showPoints:false,width:2.3,points:speed.map(r=>({ts:r.ts,value:r.download}))},
      {name:'Upload',color:C[1],unit:' Mbps',showPoints:false,width:2.3,points:speed.map(r=>({ts:r.ts,value:r.upload}))},
      {name:'Latency',color:C[2],unit:' ms',axis:'right',showPoints:false,width:1.7,points:ping.map(r=>({ts:r.ts,value:r.latency}))},
      {name:'Packet Loss',color:C[3],unit:'%',axis:'right',showPoints:false,width:1.5,points:ping.map(r=>({ts:r.ts,value:r.packet_loss}))},
      ref('Expected Download',`Expected down ${n(cfg.expected_download,0)} Mbps`,n(cfg.expected_download,0),'#4da6ff',[10,6]),
      ref('Expected Upload',`Expected up ${n(cfg.expected_upload,0)} Mbps`,n(cfg.expected_upload,0),'#ff78f4',[10,6]),
      ref('Warning',`Warning ${n(cfg.warning_threshold,0)} Mbps`,n(cfg.warning_threshold,0),'#ffd43b',[5,5]),
      ref('Major',`Major ${n(cfg.major_threshold,0)} Mbps`,n(cfg.major_threshold,0),'#ff8a33',[5,5]),
      ref('Critical',`Critical ${n(cfg.critical_threshold,0)} Mbps`,n(cfg.critical_threshold,0),'#ff445e',[5,5])
    ].filter(s=>s.points.length);
    legend('isp_legend','isp_chart',isp);chart('isp_chart','isp_empty',isp,{zoomLeft:true,minSpan:60,zoomPad:.10,zeroBase:false,zoomRight:true,rightMin:0,rightUnit:' ms/%',empty:'No ISP monitoring data is stored in this selected range yet.'});

    const wanSeries=[{name:'WAN Receive',color:C[0],unit:' GB',showPoints:true,points:wan.map(r=>({ts:r.ts,value:n(r.rx_bytes,0)/1e9}))},{name:'WAN Transmit',color:C[4],unit:' GB',showPoints:true,points:wan.map(r=>({ts:r.ts,value:n(r.tx_bytes,0)/1e9}))}];legend('wan_legend','wan_chart',wanSeries);chart('wan_chart','wan_empty',wanSeries,{leftMin:0,leftUnit:' GB',leftDecimals:1});

    const gatewaySeries=[{name:'CPU',color:C[0],unit:'%',showPoints:false,points:gw.map(r=>({ts:r.ts,value:r.cpu}))},{name:'Memory',color:C[1],unit:'%',showPoints:false,points:gw.map(r=>({ts:r.ts,value:r.memory}))},{name:'Temperature',color:C[3],unit:' °C',showPoints:false,points:gw.map(r=>({ts:r.ts,value:r.temperature}))}];legend('gateway_legend','gateway_chart',gatewaySeries);chart('gateway_chart','gateway_empty',gatewaySeries,{leftMin:0,leftMax:100,leftUnit:'%'});
    const gl=gw.at(-1);$('gateway_stats').innerHTML=gl?`<div><span>WAN</span><strong>${gl.wan_up?'ONLINE':'OFFLINE'}</strong></div><div><span>WAN IP</span><strong>${esc(gl.wan_ip||'—')}</strong></div><div><span>Link</span><strong>${gl.link_speed?gl.link_speed+' Mbps':'—'}</strong></div><div><span>RX errors</span><strong>${gl.rx_errors??'—'}</strong></div><div><span>TX errors</span><strong>${gl.tx_errors??'—'}</strong></div><div><span>RX dropped</span><strong>${gl.rx_dropped??'—'}</strong></div>`:'';

    const upsRows=ups.filter(r=>r.connected);const upsSeries=[{name:'Input V',color:'#00d9ff',unit:' V',showPoints:false,points:upsRows.map(r=>({ts:r.ts,value:r.input_voltage}))},{name:'Output V',color:'#5b8cff',unit:' V',showPoints:false,points:upsRows.map(r=>({ts:r.ts,value:r.output_voltage}))},{name:'Battery V',color:'#ff3df2',unit:' V',axis:'right',showPoints:false,points:upsRows.map(r=>({ts:r.ts,value:r.battery_voltage}))},{name:'Load',color:'#00e6a8',unit:'%',axis:'right',showPoints:false,points:upsRows.map(r=>({ts:r.ts,value:r.load_pct}))},{name:'Runtime',color:'#ffd43b',unit:' min',axis:'right',showPoints:false,points:upsRows.filter(r=>n(r.runtime_seconds)>0).map(r=>({ts:r.ts,value:n(r.runtime_seconds)/60}))},{name:'Frequency',color:'#ff7a45',unit:' Hz',axis:'right',showPoints:false,points:upsRows.map(r=>({ts:r.ts,value:r.input_frequency}))}];legend('ups_legend','ups_chart',upsSeries);chart('ups_chart','ups_empty',upsSeries,{zoomLeft:true,minSpan:8,zeroBase:false,zoomRight:true,rightMin:0,empty:'No UPS samples are stored in this selected range yet.'});

    const keys=[...new Set(wifi.map(r=>`${r.device_id||r.ap_name}|${r.band}`))];const wifiSeries=keys.slice(0,12).map((k,i)=>{const [id,band]=k.split('|');const rows=wifi.filter(r=>`${r.device_id||r.ap_name}|${r.band}`===k);const name=rows.at(-1)?.ap_name||id;return{name:`${id}:${band}`,label:`${name} ${band} retries`,color:C[i%C.length],unit:'%',showPoints:false,points:rows.map(r=>({ts:r.ts,value:r.retries}))}});legend('wifi_legend','wifi_chart',wifiSeries);chart('wifi_chart','wifi_empty',wifiSeries,{leftMin:0,zoomLeft:true,minSpan:10,zoomPad:.18,leftUnit:'%',empty:'No Wi-Fi radio samples are stored in this selected range yet.'});
    $('wifi_cards').innerHTML=radios.map(r=>{const re=n(r.retries,0),st=re>=50?'bad':re>=35?'warn':'good';return`<article class="wifi-radio-card ${st}"><div class="wifi-card-title"><strong>${esc(r.ap_name)}</strong><span>${esc(r.band)}</span></div><div class="wifi-card-metrics"><div><span>Channel</span><strong>${esc(r.channel)}</strong></div><div><span>Width</span><strong>${esc(r.width)} MHz</strong></div><div><span>Retries</span><strong>${re.toFixed(1)}%</strong></div><div><span>Utilisation</span><strong>${n(r.utilization,0).toFixed(0)}%</strong></div><div><span>Clients</span><strong>${esc(r.clients)}</strong></div><div><span>TX Power</span><strong>${esc(r.tx_power)}</strong></div></div></article>`}).join('');

    const overallBad=(p&&!p.online)||(g&&!g.wan_up)||(u&&!u.connected);$('overall_status').textContent=overallBad?'NEEDS ATTENTION':'SYSTEM HEALTHY';$('overall_status').className=`status-pill ${overallBad?'warn':'good'}`;
  }catch(e){console.error(e);if($('overall_status')){$('overall_status').textContent='DATA ERROR';$('overall_status').className='status-pill bad'}}
}

document.querySelectorAll('[data-range-group] .range-button').forEach(b=>b.addEventListener('click',()=>{rangeHours=Number(b.dataset.hours)||24;document.querySelectorAll('[data-range-group] .range-button').forEach(x=>x.classList.toggle('active',x===b));load()}));
$('run_speedtest_button')?.addEventListener('click',runSpeed);
window.addEventListener('resize',()=>{clearTimeout(window.__atResize);window.__atResize=setTimeout(load,120)});
load();setInterval(load,30000);
