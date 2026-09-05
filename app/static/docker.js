(() => {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const HOST_LABELS = { newtiny: 'newtiny', beast: 'beast (QNAP)' };

  function statusPill(status) {
    const state = status === 'running' ? 'good' : status === 'exited' ? 'bad' : 'warn';
    return `<span class="status-pill ${state}">${esc(status).toUpperCase()}</span>`;
  }

  function containerRow(host, c) {
    const disabled = c.status === 'running' ? '' : 'style="display:none"';
    const startDisabled = c.status === 'running' ? 'style="display:none"' : '';
    return `<tr data-id="${esc(c.id)}" data-host="${esc(host)}">
      <td><strong>${esc(c.name)}</strong><br><small class="muted">${esc(c.image)}</small></td>
      <td>${statusPill(c.status)}</td>
      <td>${c.cpu_percent != null ? c.cpu_percent + '%' : '—'}</td>
      <td>${c.mem_usage_mb != null ? c.mem_usage_mb.toFixed(0) + ' / ' + (c.mem_limit_mb ? c.mem_limit_mb.toFixed(0) : '∞') + ' MB' : '—'}</td>
      <td class="docker-actions">
        <button type="button" class="secondary-button compact-action docker-action" data-action="start" ${startDisabled}>Start</button>
        <button type="button" class="secondary-button compact-action docker-action" data-action="restart" ${disabled}>Restart</button>
        <button type="button" class="secondary-button compact-action docker-action" data-action="stop" ${disabled}>Stop</button>
      </td>
    </tr>`;
  }

  function hostSection(host, data) {
    const label = HOST_LABELS[host] || host;
    if (!data.enabled) {
      return `<section class="card dashboard-card"><div class="panel-heading"><h2>${esc(label)}</h2><span class="status-pill disabled">OFF</span></div><p class="muted">${esc(data.message)}</p></section>`;
    }
    if (!data.ok) {
      return `<section class="card dashboard-card"><div class="panel-heading"><h2>${esc(label)}</h2><span class="status-pill bad">ERROR</span></div><p class="muted">${esc(data.message)}</p></section>`;
    }
    const rows = (data.containers || []).map(c => containerRow(host, c)).join('');
    return `<section class="card dashboard-card"><div class="panel-heading"><h2>${esc(label)}</h2><span class="status-pill good">${(data.containers || []).length} containers</span></div>
      <div class="table-wrap"><table class="settings-table docker-table"><thead><tr><th>Container</th><th>Status</th><th>CPU</th><th>Memory</th><th>Actions</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">No containers</td></tr>'}</tbody></table></div>
    </section>`;
  }

  async function doAction(host, id, action, button) {
    const verbs = { start: 'start', stop: 'stop', restart: 'restart' };
    if (action !== 'start' && !confirm(`${verbs[action]} this container?`)) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/docker/${host}/containers/${id}/${action}`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) alert(`Failed: ${data.message || 'unknown error'}`);
    } catch (e) {
      alert(`Failed: ${e.message}`);
    } finally {
      button.disabled = false;
      load();
    }
  }

  const PROCESS_LABELS = { plex: 'Plex', ersatztv: 'ErsatzTV', nexroll: 'NeXroll' };

  function processRow(p) {
    const state = p.running && p.port_open ? 'good' : p.running ? 'warn' : 'bad';
    const text = p.running && p.port_open ? 'RUNNING' : p.running ? 'STARTING' : 'DOWN';
    return `<tr data-name="${esc(p.name)}">
      <td><strong>${esc(PROCESS_LABELS[p.name] || p.name)}</strong></td>
      <td><span class="status-pill ${state}">${text}</span></td>
      <td>${p.process_count ?? 0}</td>
      <td class="docker-actions"><button type="button" class="secondary-button compact-action plexmania-restart">Restart</button></td>
    </tr>`;
  }

  function plexmaniaSection(data) {
    if (!data.enabled) {
      return `<section class="card dashboard-card"><div class="panel-heading"><h2>plexmania (Windows)</h2><span class="status-pill disabled">OFF</span></div><p class="muted">${esc(data.message)}</p></section>`;
    }
    if (!data.ok) {
      return `<section class="card dashboard-card"><div class="panel-heading"><h2>plexmania (Windows)</h2><span class="status-pill bad">ERROR</span></div><p class="muted">${esc(data.message)}</p></section>`;
    }
    const rows = (data.processes || []).map(processRow).join('');
    return `<section class="card dashboard-card"><div class="panel-heading"><h2>plexmania (Windows)</h2><span class="status-pill good">${(data.processes || []).length} apps</span></div>
      <div class="table-wrap"><table class="settings-table docker-table"><thead><tr><th>App</th><th>Status</th><th>Processes</th><th>Actions</th></tr></thead><tbody>${rows || '<tr><td colspan="4" class="muted">No data</td></tr>'}</tbody></table></div>
    </section>`;
  }

  async function doPlexmaniaRestart(name, button) {
    if (!confirm(`Restart ${PROCESS_LABELS[name] || name} on plexmania?`)) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/plexmania/processes/${name}/restart`, { method: 'POST' });
      const data = await response.json();
      if (!data.ok) alert(`Failed: ${data.message || 'unknown error'}`);
    } catch (e) {
      alert(`Failed: ${e.message}`);
    } finally {
      button.disabled = false;
      load();
    }
  }

  function updateMetrics(data) {
    const hosts = Object.keys(HOST_LABELS).map(h => data[h] || { enabled: false });
    const running = hosts.reduce((n, h) => n + (h.containers || []).filter(c => c.status === 'running').length, 0);
    const total = hosts.reduce((n, h) => n + (h.containers || []).length, 0);
    document.getElementById('docker_running').textContent = total ? `${running}/${total}` : '—';
    document.getElementById('docker_running_detail').textContent = total ? `${total} total across ${hosts.filter(h => h.enabled).length} host(s)` : 'No agents enabled';
    const enabledHosts = hosts.filter(h => h.enabled);
    const onlineHosts = enabledHosts.filter(h => h.ok).length;
    document.getElementById('docker_hosts_online').textContent = enabledHosts.length ? `${onlineHosts}/${enabledHosts.length}` : '—';
    const pm = data.plexmania || {};
    const pmRunning = (pm.processes || []).filter(p => p.running).length;
    document.getElementById('docker_plexmania').textContent = pm.enabled ? `${pmRunning}/${(pm.processes || []).length}` : 'OFF';
  }

  async function load() {
    try {
      const response = await fetch('/api/docker/summary', { cache: 'no-store' });
      if (response.status === 401) { location.href = '/login'; return; }
      const data = await response.json();
      const container = document.getElementById('docker_hosts');
      const sections = Object.keys(HOST_LABELS).map(host => hostSection(host, data[host] || { enabled: false, message: 'No data' }));
      sections.push(plexmaniaSection(data.plexmania || { enabled: false, message: 'No data' }));
      container.innerHTML = sections.join('');
      updateMetrics(data);
      container.querySelectorAll('.docker-action').forEach(btn => {
        btn.addEventListener('click', () => {
          const row = btn.closest('tr');
          doAction(row.dataset.host, row.dataset.id, btn.dataset.action, btn);
        });
      });
      container.querySelectorAll('.plexmania-restart').forEach(btn => {
        btn.addEventListener('click', () => {
          const row = btn.closest('tr');
          doPlexmaniaRestart(row.dataset.name, btn);
        });
      });
      document.getElementById('docker_refresh_state').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    } catch (e) {
      document.getElementById('docker_refresh_state').textContent = 'Refresh failed: ' + e.message;
    }
  }
  load();
  setInterval(load, 20000);
})();
