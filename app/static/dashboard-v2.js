const $ = id => document.getElementById(id);
let rangeHours = 24;
const C = ['#38bdf8','#c084fc','#67e8f9','#f59e0b','#2dd4bf','#fb7185','#94a3b8','#4ade80'];
const states = new Map();

const n = (v,d=null) => Number.isFinite(Number(v)) ? Number(v) : d;
const fmt = (v,s='',d=1) => n(v) === null ? '—' : `${n(v).toFixed(d)}${s}`;
const tm = v => { const x = new Date(v).getTime(); return Number.isFinite(x) ? x : null; };
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function timeLabel(ms){
  const d = new Date(ms);
  if(rangeHours <= 24) return d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  if(rangeHours <= 336) return d.toLocaleDateString([],{weekday:'short',day:'2-digit'});
  return d.toLocaleDateString([],{day:'2-digit',month:'short'});
}

function legend(id,series){
  const el = $(id);
  if(el) el.innerHTML = series.map((s,i)=>`<span><i style="background:${s.color||C[i%C.length]}"></i>${esc(s.name)}</span>`).join('');
}

function thin(a,max=1200){
  if(a.length <= max) return a;
  const step = (a.length-1)/(max-1);
  return Array.from({length:max},(_,i)=>a[Math.round(i*step)]);
}

function runtime(sec){
  const s = n(sec);
  if(s === null || s < 0) return '—';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h ? `${h}h ${m}m` : `${m} min`;
}

function cleanSpeedRows(rows){
  const out = [];
  const seen = new Set();
  for(const r of [...(rows||[])].sort((a,b)=>tm(a.ts)-tm(b.ts))){
    const key = r.epoch_ms ? `e:${r.epoch_ms}` : `t:${r.ts}|${r.download}|${r.upload}|${r.latency}`;
    if(seen.has(key)) continue;
    seen.add(key);
    out.push(r);
  }
  return out;
}

function chart(canvasId,emptyId,series,o={}){
  const cv=$(canvasId), empty=$(emptyId), tip=$(`${canvasId}_tooltip`);
  if(!cv) return;

  const H=Number(cv.dataset.chartHeight||o.height||260);
  const now=Date.now(), minT=now-rangeHours*3600000, maxT=now;
  const S=series.map((s,i)=>({
    ...s,
    color:s.color||C[i%C.length],
    points:thin((s.points||[])
      .map(p=>({ts:p.ts,value:n(p.value)}))
      .filter(p=>p.value!==null && tm(p.ts)!==null && tm(p.ts)>=minT && tm(p.ts)<=maxT)
      .sort((a,b)=>tm(a.ts)-tm(b.ts)))
  })).filter(s=>s.points.length);

  if(!S.length){
    cv.style.display='none';
    if(empty){empty.style.display='flex';empty.style.minHeight=`${H}px`;empty.textContent=o.empty||'No data in this range.';}
    if(tip) tip.style.display='none';
    states.delete(canvasId);
    return;
  }

  if(empty) empty.style.display='none';
  cv.style.display='block';
  const W=Math.max(500,Math.floor(cv.parentElement?.clientWidth||1000));
  const ratio=Math.min(2,window.devicePixelRatio||1);
  cv.width=W*ratio; cv.height=H*ratio; cv.style.width='100%'; cv.style.height=`${H}px`;
  const ctx=cv.getContext('2d');
  ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,W,H);

  const hasRight=S.some(s=>s.axis==='right');
  const pad={left:58,right:hasRight?62:18,top:16,bottom:34};
  const pw=W-pad.left-pad.right, ph=H-pad.top-pad.bottom;
  const lv=S.filter(s=>s.axis!=='right').flatMap(s=>s.points.map(p=>p.value));
  const rv=S.filter(s=>s.axis==='right').flatMap(s=>s.points.map(p=>p.value));

  let lmin=o.leftMin??(lv.length?Math.min(...lv):0), lmax=o.leftMax??(lv.length?Math.max(...lv):1);
  if(o.zoomLeft && lv.length>1){
    const span=Math.max(o.minSpan||20,lmax-lmin);
    lmin=Math.max(0,lmin-span*.25);
    lmax=lmax+span*.25;
  } else if(o.zeroBase!==false) lmin=Math.min(0,lmin);
  if(lmax===lmin) lmax=lmin+1;

  let rmin=o.rightMin??0, rmax=o.rightMax??(rv.length?Math.max(...rv):100);
  if(o.zoomRight && rv.length>1){
    const span=Math.max(o.rightMinSpan||5,rmax-rmin);
    rmin=Math.max(0,rmin-span*.15);
    rmax+=span*.15;
  }
  if(rmax===rmin) rmax=rmin+1;

  const X=t=>pad.left+((tm(t)-minT)/(maxT-minT))*pw;
  const Y=(v,a)=>pad.top+(1-(v-(a==='right'?rmin:lmin))/Math.max(.00001,(a==='right'?rmax-rmin:lmax-lmin)))*ph;

  ctx.font='11px system-ui';
  for(let i=0;i<=5;i++){
    const y=pad.top+(ph/5)*i;
    ctx.strokeStyle='rgba(148,163,184,.13)'; ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(W-pad.right,y); ctx.stroke();
    ctx.fillStyle='#8fa0b5'; ctx.textAlign='left';
    ctx.fillText(`${(lmax-((lmax-lmin)/5)*i).toFixed(o.leftDecimals||0)}${o.leftUnit||''}`,5,y+4);
    if(hasRight){
      ctx.textAlign='right';
      ctx.fillText(`${(rmax-((rmax-rmin)/5)*i).toFixed(o.rightDecimals||0)}${o.rightUnit||''}`,W-5,y+4);
    }
  }

  ctx.fillStyle='#8fa0b5'; ctx.textAlign='center';
  for(let i=0;i<=6;i++) ctx.fillText(timeLabel(minT+((maxT-minT)/6)*i),pad.left+(pw/6)*i,H-9);

  const hits=[];
  for(const s of S){
    const pts=s.points;
    const yFor=p=>Y(p.value,s.axis);

    if(s.fill && pts.length>1){
      ctx.beginPath();
      pts.forEach((p,j)=>{const xx=X(p.ts),yy=yFor(p);j?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy);});
      ctx.lineTo(X(pts[pts.length-1].ts),pad.top+ph);
      ctx.lineTo(X(pts[0].ts),pad.top+ph);
      ctx.closePath();
      const grad=ctx.createLinearGradient(0,pad.top,0,pad.top+ph);
      grad.addColorStop(0,s.fillColor||`${s.color}28`);
      grad.addColorStop(1,'rgba(0,0,0,0)');
      ctx.fillStyle=grad; ctx.fill();
    }

    ctx.strokeStyle=s.color; ctx.lineWidth=s.width||2; ctx.lineJoin='round'; ctx.lineCap='round';
    ctx.beginPath();
    pts.forEach((p,j)=>{const xx=X(p.ts),yy=yFor(p);j?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy);});
    ctx.stroke();

    pts.forEach(p=>{
      const xx=X(p.ts),yy=yFor(p);
      if(s.showPoints!==false){
        ctx.beginPath();ctx.fillStyle=s.color;ctx.arc(xx,yy,s.pointRadius||3,0,Math.PI*2);ctx.fill();
        ctx.strokeStyle='#0e1116';ctx.lineWidth=1;ctx.stroke();
      }
      hits.push({x:xx,y:yy,ts:tm(p.ts),value:p.value,name:s.name,color:s.color,unit:s.unit||''});
    });
  }

  states.set(canvasId,{hits});
  if(!cv.dataset.bound){
    cv.dataset.bound='1';
    cv.addEventListener('mousemove',e=>{
      const st=states.get(canvasId); if(!st||!tip) return;
      const rect=cv.getBoundingClientRect(), mx=e.clientX-rect.left, my=e.clientY-rect.top;
      let q=null,dist=1e9;
      for(const p of st.hits){const d=Math.hypot(p.x-mx,p.y-my);if(d<dist){dist=d;q=p;}}
      if(!q||dist>24){tip.style.display='none';return;}
      const grouped=new Map();
      for(const p of st.hits){
        const delta=Math.abs(p.ts-q.ts);
        if(delta>120000) continue;
        const old=grouped.get(p.name);
        if(!old||delta<old.delta) grouped.set(p.name,{...p,delta});
      }
      const vals=[...grouped.values()];
      tip.innerHTML=`<strong>${new Date(q.ts).toLocaleString([],{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})}</strong>${vals.map(p=>`<span><i style="background:${p.color}"></i>${esc(p.name)} <b>${Number(p.value).toFixed(p.unit==='%'?1:0)}${esc(p.unit)}</b></span>`).join('')}`;
      tip.style.display='grid';
      tip.style.left=`${Math.min(rect.width-tip.offsetWidth-8,Math.max(8,mx+12))}px`;
      tip.style.top=`${Math.max(8,my-tip.offsetHeight-10)}px`;
    });
    cv.addEventListener('mouseleave',()=>{if(tip)tip.style.display='none';});
  }
}

async function j(url,opt={}){const r=await fetch(url,{cache:'no-store',...opt});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();}

async function runSpeed(){
  const b=$('run_speedtest_button'),s=$('run_speedtest_status'); if(!b||!s)return;
  b.disabled=true;s.textContent='Starting…';s.className='test-status testing';
  try{
    const x=await j('/api/settings/test/speedtest',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    s.textContent=x.message||(x.ok?'Speed test started':'Failed');s.className=`test-status ${x.ok?'good':'bad'}`;
    if(x.ok)setTimeout(load,15000);
  }catch(e){s.textContent=e.message;s.className='test-status bad';}
  finally{b.disabled=false;}
}

async function load(){
  try{
    const [live,speedRaw,ping,gw,ups,wifi,wan]=await Promise.all([
      j('/api/monitoring/live'),
      j(`/api/monitoring/speedtests?hours=${rangeHours}`),
      j(`/api/monitoring/ping?hours=${rangeHours}`),
      j(`/api/monitoring/gateway?hours=${rangeHours}`),
      j(`/api/monitoring/ups?hours=${rangeHours}`),
      j(`/api/monitoring/wifi?hours=${rangeHours}`),
      j(`/api/monitoring/unifi-wan?hours=${rangeHours}`)
    ]);
    const speed=cleanSpeedRows(speedRaw);

    const p=live.ping;
    if(p){$('internet_state').textContent=p.online?'ONLINE':'OFFLINE';$('internet_state').className=p.online?'state-good':'state-bad';$('internet_detail').textContent=`${fmt(p.latency,' ms')} · ${fmt(p.packet_loss,'%')} loss`;}
    const sp=live.speedtest;
    if(sp){$('speed_state').textContent=`${Math.round(n(sp.download,0))} ↓`;$('speed_detail').textContent=`${Math.round(n(sp.upload,0))} Mbps ↑ · ${fmt(sp.latency,' ms')}`;}
    const u=live.ups;
    if(u){const mains=String(u.status||'').includes('OL');$('ups_state').textContent=u.connected?(mains?'ON MAINS':(u.status||'CONNECTED')):'DISCONNECTED';$('ups_state').className=u.connected&&mains?'state-good':'state-bad';$('ups_detail').textContent=`${fmt(u.load_pct,'%')} load · ${fmt(u.input_voltage,' V')}`;$('ups_input').textContent=fmt(u.input_voltage,' V');$('ups_output').textContent=fmt(u.output_voltage,' V');$('ups_battery').textContent=fmt(u.battery_voltage,' V');$('ups_load').textContent=fmt(u.load_pct,'%');$('ups_runtime').textContent=runtime(u.runtime_seconds);$('ups_status').textContent=mains?'ON MAINS':(u.status||'—');$('ups_status').className=mains?'state-good':'';}
    const g=live.gateway;
    if(g){$('gateway_cpu').textContent=fmt(g.cpu,'%');$('gateway_mem').textContent=fmt(g.memory,'%');$('gateway_cpu_detail').textContent=g.temperature!=null?`${fmt(g.temperature,' °C')} CPU temp`:'UniFi gateway';$('gateway_mem_detail').textContent=g.wan_up?'WAN online':'WAN offline';}
    const radios=live.wifi||[];
    if(radios.length){const worst=Math.max(...radios.map(r=>n(r.retries,0)));$('wifi_state').textContent=worst>=40?'ATTENTION':worst>=30?'WATCH':'HEALTHY';$('wifi_state').className=worst>=40?'state-bad':worst>=30?'state-warn':'state-good';$('wifi_detail').textContent=`Worst retries ${worst.toFixed(1)}% · ${radios.length} radios`;}

    await new Promise(r=>requestAnimationFrame(r));

    const ispSeries=[
      {name:'Download',color:C[0],unit:' Mbps',fill:true,pointRadius:3.2,points:speed.map(r=>({ts:r.ts,value:r.download}))},
      {name:'Upload',color:C[1],unit:' Mbps',pointRadius:3.2,points:speed.map(r=>({ts:r.ts,value:r.upload}))},
      {name:'Latency',color:C[2],unit:' ms',axis:'right',showPoints:false,width:1.8,points:ping.map(r=>({ts:r.ts,value:r.latency}))},
      {name:'Packet Loss',color:C[3],unit:'%',axis:'right',showPoints:false,width:1.4,points:ping.map(r=>({ts:r.ts,value:r.packet_loss}))}
    ];
    legend('speed_legend',ispSeries);
    chart('speed_chart','speed_empty',ispSeries,{zoomLeft:true,minSpan:35,zeroBase:false,rightMin:0,rightUnit:' ms/%',zoomRight:true,rightMinSpan:10,empty:'No ISP monitoring data is stored in this selected range yet.'});

    legend('wan_legend',[{name:'WAN Receive GB',color:C[0]},{name:'WAN Transmit GB',color:C[4]}]);
    chart('wan_chart','wan_empty',[
      {name:'Receive',color:C[0],unit:' GB',points:wan.map(r=>({ts:r.ts,value:n(r.rx_bytes,0)/1e9}))},
      {name:'Transmit',color:C[4],unit:' GB',points:wan.map(r=>({ts:r.ts,value:n(r.tx_bytes,0)/1e9}))}
    ],{leftMin:0,leftUnit:' GB',leftDecimals:1});

    legend('gateway_legend',[{name:'CPU %',color:C[0]},{name:'Memory %',color:C[1]},{name:'Temperature °C',color:C[3]}]);
    chart('gateway_chart','gateway_empty',[
      {name:'CPU',color:C[0],unit:'%',showPoints:false,points:gw.map(r=>({ts:r.ts,value:r.cpu}))},
      {name:'Memory',color:C[1],unit:'%',showPoints:false,points:gw.map(r=>({ts:r.ts,value:r.memory}))},
      {name:'Temperature',color:C[3],unit:' °C',showPoints:false,points:gw.map(r=>({ts:r.ts,value:r.temperature}))}
    ],{leftMin:0,leftMax:100,leftUnit:'%'});

    const gl=gw.at(-1);
    $('gateway_stats').innerHTML=gl?`<div><span>WAN</span><strong>${gl.wan_up?'ONLINE':'OFFLINE'}</strong></div><div><span>WAN IP</span><strong>${esc(gl.wan_ip||'—')}</strong></div><div><span>Link</span><strong>${gl.link_speed?gl.link_speed+' Mbps':'—'}</strong></div><div><span>RX errors</span><strong>${gl.rx_errors??'—'}</strong></div><div><span>TX errors</span><strong>${gl.tx_errors??'—'}</strong></div><div><span>RX dropped</span><strong>${gl.rx_dropped??'—'}</strong></div>`:'';

    legend('ups_legend',[{name:'UPS Load %',color:C[4]}]);
    chart('ups_chart','ups_empty',[{name:'UPS Load',color:C[4],unit:'%',showPoints:false,points:ups.filter(r=>r.connected).map(r=>({ts:r.ts,value:r.load_pct}))}],{leftMin:0,leftMax:100,leftUnit:'%'});

    const keys=[...new Set(wifi.map(r=>`${r.ap_name}|${r.band}`))];
    const ws=keys.slice(0,8).map((k,i)=>{const [a,b]=k.split('|');return{name:`${a} ${b} retries`,color:C[i%C.length],unit:'%',showPoints:false,points:wifi.filter(r=>`${r.ap_name}|${r.band}`===k).map(r=>({ts:r.ts,value:r.retries}))};});
    legend('wifi_legend',ws);chart('wifi_chart','wifi_empty',ws,{leftMin:0,leftMax:100,leftUnit:'%'});

    $('wifi_cards').innerHTML=radios.map(r=>{const re=n(r.retries,0),st=re>=40?'bad':re>=30?'warn':'good';return`<article class="wifi-radio-card ${st}"><div class="wifi-card-title"><strong>${esc(r.ap_name)}</strong><span>${esc(r.band)}</span></div><div class="wifi-card-metrics"><div><span>Channel</span><strong>${esc(r.channel)}</strong></div><div><span>Width</span><strong>${esc(r.width)} MHz</strong></div><div><span>Retries</span><strong>${re.toFixed(1)}%</strong></div><div><span>Utilisation</span><strong>${n(r.utilization,0).toFixed(0)}%</strong></div><div><span>Clients</span><strong>${esc(r.clients)}</strong></div><div><span>TX Power</span><strong>${esc(r.tx_power)}</strong></div></div></article>`;}).join('');

    const bad=(p&&!p.online)||(u&&!u.connected)||(g&&!g.wan_up),ov=$('overall_status');
    ov.textContent=bad?'NEEDS ATTENTION':'SYSTEM HEALTHY';ov.className=`status-pill ${bad?'warn':'good'}`;
  }catch(e){console.error(e);$('overall_status').textContent='DATA ERROR';$('overall_status').className='status-pill bad';}
}

document.querySelectorAll('[data-range-group] .range-button').forEach(b=>b.addEventListener('click',()=>{rangeHours=Number(b.dataset.hours||24);document.querySelectorAll('[data-range-group] .range-button').forEach(x=>x.classList.toggle('active',x===b));load();}));
$('run_speedtest_button')?.addEventListener('click',runSpeed);
window.addEventListener('resize',()=>{clearTimeout(window.__rz);window.__rz=setTimeout(load,180);});
load();setInterval(load,30000);
