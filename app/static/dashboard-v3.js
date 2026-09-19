(()=>{
const $=id=>document.getElementById(id);
const f=(v,s='',d=1)=>Number.isFinite(Number(v))?`${Number(v).toFixed(d)}${s}`:'—';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const chips=pairs=>pairs.map(([label,value])=>`<span class="overview-chip"><span class="overview-chip-label">${esc(label)}</span><span class="overview-chip-value">${esc(value)}</span></span>`).join('');
const CARDS=['internet','speed','gateway','wifi','ups'];

function setCard(name,state,text,detail){
  const el=$(`ov_${name}`),detailEl=$(`ov_${name}_detail`);
  if(!el)return;
  el.textContent=text;
  el.className=`state-${state}`;
  el.closest('.metric')?.classList.remove('severity-warning','severity-major','severity-critical','severity-disabled');
  if(state==='bad')el.closest('.metric')?.classList.add('severity-critical');
  if(detailEl&&detail!==undefined)detailEl.textContent=detail;
}

function setAllError(message){
  for(const name of CARDS)setCard(name,'bad','ERROR',message||'Could not reach the dashboard API');
  $('ov_incidents').textContent='—';$('ov_incidents').className='state-bad';
  $('overview_state').textContent='ERROR';
  $('overview_detail').textContent=message||'Could not reach the dashboard API';
}

async function load(){
  let response;
  try{
    response=await fetch('/api/dashboard/summary',{cache:'no-store'});
  }catch(e){
    setAllError(e.message||'Network error');
    return;
  }
  if(response.status===401){location.href='/login';return}
  if(!response.ok){setAllError(`API returned ${response.status}`);return}
  let d;
  try{d=await response.json()}catch(e){setAllError('Invalid response from API');return}

  const p=d.ping||{},s=d.speed,g=d.gateway,u=d.ups,w=d.wifi||{};

  if(p.online===undefined){setCard('internet','muted','NO DATA','Waiting for the first sample')}
  else{setCard('internet',p.online?'good':'bad',p.online?'ONLINE':'OFFLINE',`${f(p.latency,' ms')} · ${f(p.packet_loss,'%')} loss`)}

  if(!s){setCard('speed','muted','—','No stored test yet')}
  else{setCard('speed','good',s.download!=null?`${Math.round(s.download)} ↓`:'—',s.upload!=null?`${Math.round(s.upload)} Mbps ↑ · ${f(s.latency,' ms')}`:'No stored test')}

  if(!g){setCard('gateway','muted','NO DATA','Waiting for the first sample')}
  else{setCard('gateway',g.wan_up?'good':'bad',g.wan_up?'HEALTHY':'WAN DOWN',`CPU ${f(g.cpu,'%')} · RAM ${f(g.memory,'%')} · ${f(g.temperature,' °C')}`)}

  const worst=Number(w.worst_retries||0);
  if(!w.radios){setCard('wifi','muted','NO DATA','No radios reporting')}
  else{setCard('wifi',worst>=40?'bad':worst>=30?'warn':'good',worst>=40?'ATTENTION':worst>=30?'WATCH':'HEALTHY',`Worst retries ${worst.toFixed(1)}% · ${w.radios||0} radios`)}

  if(!u){setCard('ups','muted','NO DATA','Waiting for the first sample')}
  else{const mains=String(u.status||'').includes('OL');setCard('ups',u.connected&&mains?'good':'bad',u.connected?(mains?'ON MAINS':'ON BATTERY'):'DISCONNECTED',`${f(u.load_pct,'%')} load · ${f(u.input_voltage,' V')}`)}

  $('ov_incidents').textContent=d.active_incidents||0;
  $('ov_incidents').className=d.active_incidents?'state-warn':'state-good';
  $('overview_state').textContent=d.active_incidents?'ATTENTION':'HEALTHY';
  $('overview_detail').innerHTML=chips([
    ['Internet',p.online?'Online':'Offline'],
    ['Latest speed',s&&s.download?`${Math.round(s.download)}/${Math.round(s.upload||0)} Mbps`:'—'],
    ['Gateway CPU',g?f(g.cpu,'%'):'—'],
    ['Wi-Fi worst retries',`${worst.toFixed(1)}%`],
    ['UPS',u&&u.status||'—'],
  ]);
}
load();setInterval(load,30000);
})();
