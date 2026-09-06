(() => {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // category controls which grid a card lands in, keeping "Streaming" and
  // "Downloads & Automation" as separate row groups so one tall card (e.g.
  // Sonarr's queue) doesn't stretch every other card in its row via CSS
  // grid's default row-height-matches-tallest-item behaviour.
  const SERVICES = {
    plex: { label: 'Plex', category: 'streaming' },
    tautulli: { label: 'Tautulli', category: 'streaming' },
    ersatztv: { label: 'ErsatzTV', category: 'streaming' },
    nexroll: { label: 'NeXroll', category: 'streaming' },
    sonarr: { label: 'Sonarr', category: 'downloads' },
    radarr: { label: 'Radarr', category: 'downloads' },
    prowlarr: { label: 'Prowlarr', category: 'downloads' },
    sabnzbd: { label: 'SABnzbd', category: 'downloads' },
  };

  function pill(state, text) {
    return `<span class="status-pill ${state}">${esc(text)}</span>`;
  }

  function list(rows) {
    if (!rows.length) return '';
    return `<div class="media-card-list">${rows.join('')}</div>`;
  }

  function btn(service, action, params, text, extraClass) {
    return `<button type="button" class="icon-action media-run ${extraClass || ''}" data-service="${esc(service)}" data-action="${esc(action)}" data-params='${esc(JSON.stringify(params || {}))}'>${esc(text)}</button>`;
  }

  // A <details>/<summary> dropdown needs no JS to open/close - just a click
  // handler on its items to run the action and close it again afterwards.
  function menu(label, items) {
    if (!items.length) return '';
    const rows = items.map(it => `<button type="button" class="media-menu-item media-run" data-service="${esc(it.service)}" data-action="${esc(it.action)}" data-params='${esc(JSON.stringify(it.params || {}))}'>${esc(it.text)}</button>`).join('');
    return `<details class="media-actions"><summary class="secondary-button compact-action">${esc(label)} &#9662;</summary><div class="media-menu">${rows}</div></details>`;
  }

  function headerActions(name, d) {
    if (name === 'sonarr' || name === 'radarr') {
      return `${btn(name, 'rss_sync', {}, 'RSS Sync')}${btn(name, 'missing_search', {}, 'Search Missing')}`;
    }
    if (name === 'prowlarr') {
      return btn(name, 'test_all', {}, 'Test All Indexers');
    }
    if (name === 'sabnzbd') {
      return d.paused ? btn(name, 'resume_queue', {}, 'Resume Queue') : btn(name, 'pause_queue', {}, 'Pause Queue');
    }
    if (name === 'plex') {
      const libs = (d.libraries || []).filter(l => l.key).map(l => ({ service: name, action: 'refresh_section', params: { key: l.key }, text: `Refresh ${l.name || l.key}` }));
      return menu('Refresh Library', libs);
    }
    if (name === 'nexroll') {
      const cats = (d.categories || []).map(c => ({ service: name, action: 'apply_category', params: { category_id: c.id }, text: c.name }));
      return `${btn(name, 'sync_plex', {}, 'Sync with Plex')}${menu('Apply Category', cats)}`;
    }
    return '';
  }

  function arrBody(d, name) {
    const health = (d.health || []).map(h => `<div class="setting-row"><span>${esc(h.message)}</span></div>`);
    const queue = (d.queue || []).slice(0, 8).map(q => `<div class="setting-row"><span>${esc(q.title)}<small>${esc(q.status)} · ${esc(q.timeleft || '')}</small></span>${btn(name, 'remove_queue_item', { queue_id: q.id }, '✕', 'media-danger')}</div>`);
    return `<p class="muted">${esc(d.app_name)} ${esc(d.version)}</p><p>Queue: <strong>${d.queue_count ?? 0}</strong></p>${list([...health, ...queue])}`;
  }

  function prowlarrBody(d) {
    const failing = (d.failing || []).map(f => `<div class="setting-row"><span>${esc(f.name)}<small>Failing</small></span></div>`);
    return `<p class="muted">${esc(d.app_name)} ${esc(d.version)}</p><p>Indexers: <strong>${d.enabled_count ?? 0}</strong> / ${d.indexer_count ?? 0} enabled</p>${list(failing)}`;
  }

  function sabnzbdBody(d, name) {
    const queue = (d.queue || []).slice(0, 8).map(q => {
      const paused = String(q.status || '').toLowerCase() === 'paused';
      const toggle = btn(name, paused ? 'resume_job' : 'pause_job', { nzo_id: q.nzo_id }, paused ? '▶' : '⏸');
      const del = btn(name, 'delete_job', { nzo_id: q.nzo_id }, '✕', 'media-danger');
      return `<div class="setting-row"><span>${esc(q.name)}<small>${esc(q.status)} · ${esc(q.size_mb)} MB · ${esc(q.percentage)}%</small></span><span class="media-row-actions">${toggle}${del}</span></div>`;
    });
    return `<p>Status: <strong>${esc(d.status)}</strong>${d.paused ? ' (paused)' : ''}</p><p>Speed: ${esc(d.speed_kbps)} KB/s · ${d.queue_count ?? 0} in queue</p>${list(queue)}`;
  }

  function sessionsBody(d, name) {
    const sessions = (d.sessions || []).map(s => `<div class="setting-row"><span>${esc(s.title)}<small>${esc(s.user)} · ${esc(s.state)} · ${esc(s.progress_percent)}%</small></span>${s.session_id ? btn(name, 'terminate_session', { session_id: s.session_id }, 'Stop', 'media-danger') : ''}</div>`);
    const libs = (d.libraries || []).map(l => `<span class="status-pill">${esc(l.name)}${l.count ? ': ' + esc(l.count) : ''}</span>`).join(' ');
    return `<p>Active streams: <strong>${d.stream_count ?? 0}</strong></p>${list(sessions)}<p class="media-card-footer">${libs}</p>`;
  }

  function ersatztvBody(d) {
    const chips = (d.channels || []).map(c => `<span class="status-pill">${esc(c.number)} ${esc(c.name)}</span>`).join(' ');
    return `<p>Channels: <strong>${d.channel_count ?? 0}</strong></p><p class="media-card-footer">${chips}</p>`;
  }

  function nexrollBody(d) {
    return `<p>Plex connected: <strong>${d.plex_connected ? 'Yes' : 'No'}</strong></p><p>Prerolls: ${d.preroll_count ?? 0} · Categories: ${d.category_count ?? 0} · Schedules: ${d.schedule_count ?? 0}</p>`;
  }

  const BODY = { sonarr: arrBody, radarr: arrBody, prowlarr: prowlarrBody, sabnzbd: sabnzbdBody, tautulli: sessionsBody, plex: sessionsBody, ersatztv: ersatztvBody, nexroll: nexrollBody };

  function card(name, d) {
    const label = SERVICES[name].label;
    if (!d.enabled) {
      return `<article class="card info-tile media-card severity-disabled"><div class="panel-heading"><h2>${label}</h2>${pill('disabled', 'OFF')}</div><p class="muted">${esc(d.message)}</p></article>`;
    }
    if (!d.ok) {
      return `<article class="card info-tile media-card severity-critical"><div class="panel-heading"><h2>${label}</h2>${pill('bad', 'ERROR')}</div><p class="muted">${esc(d.message)}</p></article>`;
    }
    const body = (BODY[name] || (() => ''))(d, name);
    const actions = headerActions(name, d);
    return `<article class="card info-tile media-card"><div class="panel-heading"><h2>${label}</h2><div class="media-card-actions">${actions}${pill('good', 'OK')}</div></div>${body}</article>`;
  }

  function updateMetrics(data) {
    const enabled = Object.values(data).filter(d => d.enabled);
    const healthy = enabled.filter(d => d.ok).length;
    document.getElementById('media_healthy').textContent = enabled.length ? `${healthy}/${enabled.length}` : 'OFF';
    document.getElementById('media_healthy_detail').textContent = enabled.length ? `${enabled.length - healthy} unavailable` : 'No services enabled';
    const streams = (data.plex?.stream_count || 0) + (data.tautulli?.stream_count || 0);
    document.getElementById('media_streams').textContent = streams;
    const queue = (data.sonarr?.queue_count || 0) + (data.radarr?.queue_count || 0) + (data.sabnzbd?.queue_count || 0);
    document.getElementById('media_queue').textContent = queue;
    const p = data.prowlarr || {};
    document.getElementById('media_indexers').textContent = p.enabled ? `${p.enabled_count ?? 0}/${p.indexer_count ?? 0}` : '—';
  }

  const DESTRUCTIVE = new Set(['remove_queue_item', 'delete_job', 'terminate_session']);

  async function runAction(button) {
    const service = button.dataset.service, action = button.dataset.action;
    const params = JSON.parse(button.dataset.params || '{}');
    if (DESTRUCTIVE.has(action) && !confirm('Are you sure?')) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/media/${service}/action`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, ...params }) });
      const data = await response.json();
      if (!data.ok) alert(`Failed: ${data.message || 'unknown error'}`);
      document.querySelectorAll('details.media-actions[open]').forEach(d => d.removeAttribute('open'));
      await load();
    } catch (e) {
      alert(`Failed: ${e.message}`);
    } finally {
      button.disabled = false;
    }
  }

  async function load() {
    try {
      const response = await fetch('/api/media/summary', { cache: 'no-store' });
      if (response.status === 401) { location.href = '/login'; return; }
      const data = await response.json();
      for (const cat of ['streaming', 'downloads']) {
        const names = Object.keys(SERVICES).filter(name => SERVICES[name].category === cat);
        const container = document.getElementById(`media_cards_${cat === 'downloads' ? 'downloads' : 'streaming'}`);
        container.innerHTML = names.map(name => card(name, data[name] || { enabled: false, message: 'No data' })).join('');
      }
      document.querySelectorAll('.media-run').forEach(b => b.addEventListener('click', () => runAction(b)));
      updateMetrics(data);
      document.getElementById('media_refresh_state').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    } catch (e) {
      document.getElementById('media_refresh_state').textContent = 'Refresh failed: ' + e.message;
    }
  }
  load();
  setInterval(load, 30000);
})();
