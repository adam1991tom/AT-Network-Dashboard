(() => {
  const SERVICES = [
    { key: 'sonarr', label: 'Sonarr', hint: 'TV show management.', placeholder: 'http://10.0.0.55:8989', needsKey: true },
    { key: 'radarr', label: 'Radarr', hint: 'Movie management.', placeholder: 'http://10.0.0.54:7878', needsKey: true },
    { key: 'prowlarr', label: 'Prowlarr', hint: 'Indexer management.', placeholder: 'http://10.0.0.53:9696', needsKey: true },
    { key: 'sabnzbd', label: 'SABnzbd', hint: 'Usenet downloader.', placeholder: 'http://10.0.0.50:8080', needsKey: true },
    { key: 'tautulli', label: 'Tautulli', hint: 'Plex activity and stats.', placeholder: 'http://10.0.0.2:8181', needsKey: true },
    { key: 'plex', label: 'Plex', hint: 'Direct Plex Media Server API.', placeholder: 'http://10.0.0.6:32400', needsKey: true, keyLabel: 'Plex token' },
    { key: 'ersatztv', label: 'ErsatzTV', hint: 'Virtual live TV channels.', placeholder: 'http://10.0.0.6:8409', needsKey: false },
    { key: 'nexroll', label: 'NeXroll', hint: 'Plex pre-roll manager.', placeholder: 'http://10.0.0.6:9393', needsKey: true, keyLabel: 'API key' },
  ];

  document.addEventListener('DOMContentLoaded', async () => {
    const panel = document.getElementById('integrations');
    if (!panel) return;
    const $ = (id) => document.getElementById(id);

    for (const svc of SERVICES) {
      const block = document.createElement('div');
      block.className = 'integration-block';
      const keyField = svc.needsKey
        ? `<label>${svc.keyLabel || 'API key'}<input id="${svc.key}_api_key" type="password" placeholder="Leave blank to keep saved key"><span class="secret-status" id="${svc.key}_key_status"></span></label>`
        : '';
      block.innerHTML = `<div class="integration-title"><div><strong>${svc.label}</strong><span class="muted">${svc.hint}</span></div><input id="${svc.key}_enabled" type="checkbox"></div><div class="field-grid"><label>URL<input id="${svc.key}_url" placeholder="${svc.placeholder}"></label>${keyField}</div><div class="test-row"><button type="button" class="secondary-button" id="test_${svc.key}">Test ${svc.label}</button><span class="test-status" id="${svc.key}_test_status">Not tested</span></div>`;
      panel.appendChild(block);
    }

    const secretKeyName = (svc) => svc.key === 'plex' ? 'plex_token' : `${svc.key}_api_key`;

    const payloadFor = (svc) => {
      const out = { [`${svc.key}_enabled`]: $(`${svc.key}_enabled`).checked ? 'true' : 'false', [`${svc.key}_url`]: $(`${svc.key}_url`).value.trim() };
      if (svc.needsKey) out[secretKeyName(svc)] = $(`${svc.key}_api_key`).value.trim();
      return out;
    };

    try {
      const response = await fetch('/api/settings', { cache: 'no-store' });
      const data = await response.json();
      for (const svc of SERVICES) {
        $(`${svc.key}_enabled`).checked = String(data[`${svc.key}_enabled`]).toLowerCase() === 'true';
        $(`${svc.key}_url`).value = data[`${svc.key}_url`] || '';
        if (svc.needsKey) {
          $(`${svc.key}_key_status`).textContent = data[`${secretKeyName(svc)}_configured`] ? 'Key configured ✓' : 'No key stored';
        }
      }
    } catch (e) { /* leave fields blank on failure */ }

    for (const svc of SERVICES) {
      $(`test_${svc.key}`).addEventListener('click', async () => {
        const status = $(`${svc.key}_test_status`);
        status.textContent = 'Testing…';
        status.className = 'test-status testing';
        try {
          const response = await fetch(`/api/settings/test/${svc.key}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payloadFor(svc)) });
          const data = await response.json();
          status.textContent = data.ok ? `${data.message} ✓` : `Failed · ${data.message || 'Connection failed'}`;
          status.className = `test-status ${data.ok ? 'good' : 'bad'}`;
        } catch (e) {
          status.textContent = `Error · ${e.message || e}`;
          status.className = 'test-status bad';
        }
      });
    }

    $('save_settings')?.addEventListener('click', async () => {
      try {
        const merged = Object.assign({}, ...SERVICES.map(payloadFor));
        await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(merged) });
        for (const svc of SERVICES) { if (svc.needsKey) $(`${svc.key}_api_key`).value = ''; }
      } catch (e) { /* the main save button already reports failures */ }
    });
  });
})();
