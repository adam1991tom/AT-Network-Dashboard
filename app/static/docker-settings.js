(() => {
  const HOSTS = [
    { key: 'newtiny', label: 'newtiny (this server)', hint: 'Local docker-agent sidecar, no host port needed.', placeholder: 'http://docker-agent:8199' },
    { key: 'beast', label: 'beast (QNAP)', hint: 'Remote docker-agent deployed in Container Station.', placeholder: 'http://10.0.0.3:8199' },
  ];

  document.addEventListener('DOMContentLoaded', async () => {
    const panel = document.getElementById('integrations');
    if (!panel) return;
    const $ = (id) => document.getElementById(id);

    for (const host of HOSTS) {
      const key = `docker_agent_${host.key}`;
      const block = document.createElement('div');
      block.className = 'integration-block';
      block.innerHTML = `<div class="integration-title"><div><strong>Docker - ${host.label}</strong><span class="muted">${host.hint}</span></div><input id="${key}_enabled" type="checkbox"></div><div class="field-grid"><label>Agent URL<input id="${key}_url" placeholder="${host.placeholder}"></label><label>Agent token<input id="${key}_token" type="password" placeholder="Leave blank to keep saved token"><span class="secret-status" id="${key}_status"></span></label></div><div class="test-row"><button type="button" class="secondary-button" id="test_${key}">Test connection</button><span class="test-status" id="${key}_test_status">Not tested</span></div>`;
      panel.appendChild(block);
    }

    const payloadFor = (host) => {
      const key = `docker_agent_${host.key}`;
      return { [`${key}_enabled`]: $(`${key}_enabled`).checked ? 'true' : 'false', [`${key}_url`]: $(`${key}_url`).value.trim(), [`${key}_token`]: $(`${key}_token`).value.trim() };
    };

    try {
      const response = await fetch('/api/settings', { cache: 'no-store' });
      const data = await response.json();
      for (const host of HOSTS) {
        const key = `docker_agent_${host.key}`;
        $(`${key}_enabled`).checked = String(data[`${key}_enabled`]).toLowerCase() === 'true';
        $(`${key}_url`).value = data[`${key}_url`] || '';
        $(`${key}_status`).textContent = data[`${key}_token_configured`] ? 'Token configured ✓' : 'No token stored';
      }
    } catch (e) { /* leave fields blank on failure */ }

    for (const host of HOSTS) {
      const key = `docker_agent_${host.key}`;
      $(`test_${key}`).addEventListener('click', async () => {
        const status = $(`${key}_test_status`);
        status.textContent = 'Testing…';
        status.className = 'test-status testing';
        try {
          const response = await fetch(`/api/settings/test/docker-agent-${host.key}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payloadFor(host)) });
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
        const merged = Object.assign({}, ...HOSTS.map(payloadFor));
        await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(merged) });
        for (const host of HOSTS) { $(`docker_agent_${host.key}_token`).value = ''; }
      } catch (e) { /* the main save button already reports failures */ }
    });
  });
})();
