(() => {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const row = (main, small) => `<div class="setting-row"><span>${esc(main)}${small ? `<small>${esc(small)}</small>` : ''}</span></div>`;
  const empty = (text) => `<div class="setting-row"><span class="muted">${esc(text)}</span></div>`;

  function setPill(el, text, state) {
    el.textContent = text;
    el.className = `status-pill ${state}`;
  }

  async function loadIncidents() {
    const list = document.getElementById('ov_incidents_list'), pill = document.getElementById('ov_incidents_pill');
    try {
      const r = await fetch('/api/incidents?limit=5', { cache: 'no-store' });
      const j = await r.json();
      const items = j.items || [];
      const active = items.filter(i => i.active);
      setPill(pill, active.length ? `${active.length} ACTIVE` : 'CLEAR', active.length ? 'bad' : 'good');
      list.innerHTML = items.length ? items.slice(0, 5).map(i => row(i.summary, `${i.category || 'System'} · ${i.active ? 'Active' : 'Resolved'}`)).join('') : empty('No incidents recorded');
    } catch (e) {
      setPill(pill, 'ERROR', 'bad');
      list.innerHTML = empty('Could not load incidents');
    }
  }

  async function loadMediaWidgets() {
    const streamsList = document.getElementById('ov_streams_list'), streamsPill = document.getElementById('ov_streams_pill');
    const queueList = document.getElementById('ov_queue_list'), queuePill = document.getElementById('ov_queue_pill');
    try {
      const r = await fetch('/api/media/summary', { cache: 'no-store' });
      const d = await r.json();
      const sessions = [...((d.plex && d.plex.sessions) || []), ...((d.tautulli && d.tautulli.sessions) || [])];
      setPill(streamsPill, String(sessions.length), sessions.length ? 'good' : 'disabled');
      streamsList.innerHTML = sessions.length ? sessions.slice(0, 5).map(s => row(s.title, `${s.user || ''} · ${s.progress_percent ?? 0}%`)).join('') : empty('Nothing playing');

      const queueItems = [
        ...((d.sonarr && d.sonarr.queue) || []).map(q => ({ title: q.title, detail: `Sonarr · ${q.timeleft || q.status || ''}` })),
        ...((d.radarr && d.radarr.queue) || []).map(q => ({ title: q.title, detail: `Radarr · ${q.timeleft || q.status || ''}` })),
        ...((d.sabnzbd && d.sabnzbd.queue) || []).map(q => ({ title: q.name, detail: `SABnzbd · ${q.percentage ?? 0}%` })),
      ];
      setPill(queuePill, String(queueItems.length), queueItems.length ? 'good' : 'disabled');
      queueList.innerHTML = queueItems.length ? queueItems.slice(0, 5).map(q => row(q.title, q.detail)).join('') : empty('Queue is empty');
    } catch (e) {
      setPill(streamsPill, 'ERROR', 'bad');
      streamsList.innerHTML = empty('Could not load media');
      setPill(queuePill, 'ERROR', 'bad');
      queueList.innerHTML = empty('Could not load media');
    }
  }

  async function loadDockerHealth() {
    const list = document.getElementById('ov_docker_health_list'), pill = document.getElementById('ov_docker_health_pill');
    try {
      const r = await fetch('/api/docker/summary', { cache: 'no-store' });
      const d = await r.json();
      const hosts = ['newtiny', 'beast'].map(h => d[h]).filter(Boolean);
      const unhealthy = [];
      hosts.forEach(h => (h.containers || []).forEach(c => {
        if (c.status !== 'running' || (c.health && c.health !== 'healthy' && c.health !== 'none')) {
          unhealthy.push({ title: c.name, detail: `${c.status}${c.health && c.health !== 'none' ? ' · ' + c.health : ''}` });
        }
      }));
      setPill(pill, unhealthy.length ? `${unhealthy.length} ISSUE${unhealthy.length === 1 ? '' : 'S'}` : 'ALL HEALTHY', unhealthy.length ? 'warn' : 'good');
      list.innerHTML = unhealthy.length ? unhealthy.slice(0, 5).map(c => row(c.title, c.detail)).join('') : empty('All containers running normally');
    } catch (e) {
      setPill(pill, 'ERROR', 'bad');
      list.innerHTML = empty('Could not load Docker status');
    }
  }

  function loadAll() { loadIncidents(); loadMediaWidgets(); loadDockerHealth(); }
  loadAll();
  setInterval(loadAll, 30000);
})();
