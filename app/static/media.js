(() => {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const LABELS = { sonarr: 'Sonarr', radarr: 'Radarr', prowlarr: 'Prowlarr', sabnzbd: 'SABnzbd', tautulli: 'Tautulli', plex: 'Plex', ersatztv: 'ErsatzTV', nexroll: 'NeXroll' };

  function pill(state, text) {
    return `<span class="status-pill ${state}">${esc(text)}</span>`;
  }

  function arrBody(d) {
    const health = (d.health || []).map(h => `<div class="setting-row"><span>${esc(h.message)}</span></div>`).join('');
    const queue = (d.queue || []).slice(0, 5).map(q => `<div class="setting-row"><span>${esc(q.title)}<small>${esc(q.status)} · ${esc(q.timeleft || '')}</small></span></div>`).join('');
    return `<p class="muted">${esc(d.app_name)} ${esc(d.version)}</p><p>Queue: <strong>${d.queue_count ?? 0}</strong></p>${health}${queue}`;
  }

  function prowlarrBody(d) {
    const failing = (d.failing || []).map(f => `<div class="setting-row"><span>${esc(f.name)}<small>Failing</small></span></div>`).join('');
    return `<p class="muted">${esc(d.app_name)} ${esc(d.version)}</p><p>Indexers: <strong>${d.enabled_count ?? 0}</strong> / ${d.indexer_count ?? 0} enabled</p>${failing}`;
  }

  function sabnzbdBody(d) {
    const queue = (d.queue || []).slice(0, 5).map(q => `<div class="setting-row"><span>${esc(q.name)}<small>${esc(q.status)} · ${esc(q.size_mb)} MB · ${esc(q.percentage)}%</small></span></div>`).join('');
    return `<p>Status: <strong>${esc(d.status)}</strong>${d.paused ? ' (paused)' : ''}</p><p>Speed: ${esc(d.speed_kbps)} KB/s · ${d.queue_count ?? 0} in queue</p>${queue}`;
  }

  function sessionsBody(d) {
    const sessions = (d.sessions || []).map(s => `<div class="setting-row"><span>${esc(s.title)}<small>${esc(s.user)} · ${esc(s.state)} · ${esc(s.progress_percent)}%</small></span></div>`).join('');
    const libs = (d.libraries || []).map(l => `<span class="status-pill">${esc(l.name)}${l.count ? ': ' + esc(l.count) : ''}</span>`).join(' ');
    return `<p>Active streams: <strong>${d.stream_count ?? 0}</strong></p>${sessions}<p>${libs}</p>`;
  }

  function ersatztvBody(d) {
    return `<p>Channels: <strong>${d.channel_count ?? 0}</strong></p>` + (d.channels || []).map(c => `<span class="status-pill">${esc(c.number)} ${esc(c.name)}</span>`).join(' ');
  }

  function nexrollBody(d) {
    return `<p>Plex connected: <strong>${d.plex_connected ? 'Yes' : 'No'}</strong></p><p>Prerolls: ${d.preroll_count ?? 0} · Categories: ${d.category_count ?? 0} · Schedules: ${d.schedule_count ?? 0}</p>`;
  }

  const BODY = { sonarr: arrBody, radarr: arrBody, prowlarr: prowlarrBody, sabnzbd: sabnzbdBody, tautulli: sessionsBody, plex: sessionsBody, ersatztv: ersatztvBody, nexroll: nexrollBody };

  function card(name, d) {
    const label = LABELS[name] || name;
    if (!d.enabled) {
      return `<article class="card info-tile severity-disabled"><div class="panel-heading"><h2>${label}</h2>${pill('disabled', 'OFF')}</div><p class="muted">${esc(d.message)}</p></article>`;
    }
    if (!d.ok) {
      return `<article class="card info-tile severity-critical"><div class="panel-heading"><h2>${label}</h2>${pill('bad', 'ERROR')}</div><p class="muted">${esc(d.message)}</p></article>`;
    }
    const body = (BODY[name] || (() => ''))(d);
    return `<article class="card info-tile"><div class="panel-heading"><h2>${label}</h2>${pill('good', 'OK')}</div>${body}</article>`;
  }

  async function load() {
    try {
      const response = await fetch('/api/media/summary', { cache: 'no-store' });
      if (response.status === 401) { location.href = '/login'; return; }
      const data = await response.json();
      const container = document.getElementById('media_cards');
      container.innerHTML = Object.keys(LABELS).map(name => card(name, data[name] || { enabled: false, message: 'No data' })).join('');
      document.getElementById('media_refresh_state').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    } catch (e) {
      document.getElementById('media_refresh_state').textContent = 'Refresh failed: ' + e.message;
    }
  }
  load();
  setInterval(load, 30000);
})();
