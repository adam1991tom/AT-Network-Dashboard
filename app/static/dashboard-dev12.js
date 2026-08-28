// dev12 ISP graph cleanup: collapse historical duplicate live snapshots while
// preserving genuine timestamped UniFi speed-test archive rows.
(function(){
  const old = window.uniqueSpeedRows;
  window.uniqueSpeedRows = function(rows){
    const sorted = [...(rows || [])].sort((a,b)=>new Date(a.ts)-new Date(b.ts));
    const byTime = new Map();
    for(const r of sorted){
      const t = Number(r.epoch_ms || new Date(r.ts).getTime());
      if(!Number.isFinite(t) || t <= 0) continue;
      const existing = byTime.get(t);
      // Prefer the retained UniFi archive row when the same run exists from
      // both the archive and the live gateway snapshot.
      if(!existing || String(r.source || '').includes('history')) byTime.set(t,r);
    }

    const sourceRows = [...byTime.values()].sort((a,b)=>new Date(a.ts)-new Date(b.ts));
    const out = [];
    let lastLiveSignature = null;
    for(const r of sourceRows){
      const source = String(r.source || '');
      const signature = [r.download,r.upload,r.latency].map(v=>{
        const x = Number(v); return Number.isFinite(x) ? x.toFixed(3) : '';
      }).join('|');

      // Old dev builds stored the same speedtest-status result every 30 sec
      // because UniFi's status timestamp changes.  Collapse only those live
      // snapshots.  Archive/history rows are always retained as real tests.
      if(source.includes('unifi-live')){
        if(signature && signature === lastLiveSignature) continue;
        lastLiveSignature = signature;
      } else {
        lastLiveSignature = null;
      }
      out.push(r);
    }
    return out;
  };

  // Redraw immediately using the corrected speed-test points.
  if(typeof window.load === 'function') window.load();
})();
