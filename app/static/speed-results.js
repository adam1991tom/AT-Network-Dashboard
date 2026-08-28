(()=>{
  if(!['/','/dashboard'].includes(location.pathname)) return;
  const $=id=>document.getElementById(id);
  const num=v=>Number.isFinite(Number(v))?Number(v):null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=(v,d=0)=>num(v)==null?'—':num(v).toFixed(d);
  const when=v=>{const d=new Date(v);return Number.isFinite(d.getTime())?d.toLocaleString([], {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—'};

  // Use the real UniFi run timestamp/epoch as identity. Similar consecutive speeds are still
  // separate tests; only rows that describe the same run are collapsed.
  window.uniqueSpeedRows=function(rows){
    const byEpoch=new Map();
    for(const r of rows||[]){
      const epoch=Number(r.epoch_ms||new Date(r.ts).getTime());
      if(!Number.isFinite(epoch)||epoch<=0) continue;
      const dl=num(r.download), ul=num(r.upload);
      if((dl==null||dl<=0)&&(ul==null||ul<=0)) continue;
      const prev=byEpoch.get(epoch);
      const score=x=>String(x?.source||'').includes('history')?3:String(x?.source||'').includes('live')?2:1;
      if(!prev||score(r)>=score(prev)) byEpoch.set(epoch,r);
    }
    return [...byEpoch.values()].sort((a,b)=>Number(a.epoch_ms||new Date(a.ts).getTime())-Number(b.epoch_ms||new Date(b.ts).getTime()));
  };

  const selectedHours=()=>Number(document.querySelector('[data-range-group] .range-button.active')?.dataset.hours||24)||24;
  let expanded=false;
  function render(rows){
    const body=$('speed_results_body'), count=$('speed_results_count'), empty=$('speed_results_empty'), toggle=$('speed_results_toggle');
    if(!body) return;
    const clean=window.uniqueSpeedRows(rows||[]).slice().reverse();
    if(count) count.textContent=`${clean.length} result${clean.length===1?'':'s'} in selected range`;
    if(empty) empty.style.display=clean.length?'none':'block';
    const shown=expanded?clean:clean.slice(0,20);
    body.innerHTML=shown.map(r=>`<tr>
      <td>${esc(when(r.ts))}</td>
      <td><strong>${fmt(r.download)} Mbps</strong></td>
      <td><strong>${fmt(r.upload)} Mbps</strong></td>
      <td>${fmt(r.latency,1)} ms</td>
      <td>${esc(r.source||'unifi')}</td>
    </tr>`).join('');
    if(toggle){
      toggle.style.display=clean.length>20?'inline-flex':'none';
      toggle.textContent=expanded?'Show latest 20':`View all ${clean.length}`;
    }
  }

  async function refresh(){
    try{
      const r=await fetch(`/api/monitoring/speedtests?hours=${selectedHours()}`,{cache:'no-store'});
      if(r.status===401){location.href='/login';return}
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      render(await r.json());
    }catch(e){
      const empty=$('speed_results_empty');
      if(empty){empty.style.display='block';empty.textContent=`Unable to load speed-test results: ${e.message}`;}
    }
  }

  $('speed_results_toggle')?.addEventListener('click',()=>{expanded=!expanded;refresh()});
  document.querySelectorAll('[data-range-group] .range-button').forEach(b=>b.addEventListener('click',()=>setTimeout(refresh,180)));
  $('run_speedtest_button')?.addEventListener('click',()=>{setTimeout(refresh,18000);setTimeout(refresh,35000)});
  refresh();
  setInterval(refresh,60000);
})();