(() => {
  const path = location.pathname;

  // Dashboard: reference values are permanent horizontal guide lines. They
  // must participate in the left-axis range so Expected/Warning/Major/
  // Critical lines remain visible even when there are few/no speed tests.
  if (path === '/' || path === '/dashboard') {
    const originalChart = window.chart;
    if (typeof originalChart === 'function' && !window.__atDev13ChartPatched) {
      const references = new Set(['Expected Download', 'Expected Upload', 'Warning', 'Major', 'Critical']);
      window.chart = function(canvasId, emptyId, series, options = {}) {
        if (canvasId === 'isp_chart') {
          series = (series || []).map(item => references.has(item.name)
            ? { ...item, affectsScale: true, hover: true, showPoints: false }
            : item);
          options = { ...options, zeroBase: false };
        }
        return originalChart(canvasId, emptyId, series, options);
      };
      window.__atDev13ChartPatched = true;
      if (typeof window.load === 'function') window.load();
    }
  }

  if (path !== '/settings') return;

  const $ = id => document.getElementById(id);
  const interval = $('speedtest_minutes');
  if (!interval || $('speedtest_auto_enabled')) return;

  interval.min = '5';
  interval.max = '1440';
  interval.step = '1';
  const intervalLabel = interval.closest('label');
  if (intervalLabel) {
    intervalLabel.firstChild.textContent = 'Automatic speed-test interval minutes';
  }

  const autoLabel = document.createElement('label');
  autoLabel.className = 'switch-line';
  autoLabel.innerHTML = '<span><strong>Automatic ISP speed tests</strong><small style="display:block;margin-top:3px">Run a UniFi gateway speed test automatically at the interval below.</small></span><input id="speedtest_auto_enabled" type="checkbox">';
  intervalLabel?.parentElement?.insertBefore(autoLabel, intervalLabel);

  const status = document.createElement('div');
  status.className = 'info-grid system-grid';
  status.style.marginTop = '12px';
  status.innerHTML = `
    <div class="info-tile"><span>Automatic testing</span><strong id="speedtest_auto_state">Loading…</strong></div>
    <div class="info-tile"><span>Last automatic test</span><strong id="speedtest_last_auto">—</strong></div>
    <div class="info-tile"><span>Next scheduled test</span><strong id="speedtest_next_auto">—</strong></div>
  `;
  const isp = $('isp');
  const testRow = $('test_ping')?.closest('.test-row');
  if (isp && testRow) isp.insertBefore(status, testRow);

  const formatWhen = value => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
  };

  async function getSettings() {
    const r = await fetch('/api/settings', { cache: 'no-store' });
    if (r.status === 401) { location.href = '/login'; return null; }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async function saveAuto(enabled) {
    const state = $('speedtest_auto_state');
    if (state) state.textContent = 'Saving…';
    const r = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speedtest_auto_enabled: enabled ? 'true' : 'false' })
    });
    if (r.status === 401) { location.href = '/login'; return; }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    await refresh();
  }

  async function refresh() {
    try {
      const data = await getSettings();
      if (!data) return;
      const enabled = String(data.speedtest_auto_enabled ?? 'true').toLowerCase() === 'true';
      const checkbox = $('speedtest_auto_enabled');
      if (checkbox) checkbox.checked = enabled;
      if ($('speedtest_auto_state')) $('speedtest_auto_state').textContent = enabled ? (data.speedtest_auto_state || 'Scheduled') : 'Disabled';
      if ($('speedtest_last_auto')) $('speedtest_last_auto').textContent = formatWhen(data.speedtest_last_auto_at);
      if ($('speedtest_next_auto')) $('speedtest_next_auto').textContent = enabled ? formatWhen(data.speedtest_next_auto_at) : '—';
    } catch (e) {
      if ($('speedtest_auto_state')) $('speedtest_auto_state').textContent = `Error · ${e.message}`;
    }
  }

  $('speedtest_auto_enabled')?.addEventListener('change', e => saveAuto(e.target.checked).catch(err => {
    if ($('speedtest_auto_state')) $('speedtest_auto_state').textContent = `Save failed · ${err.message}`;
  }));

  refresh();
  setInterval(refresh, 15000);
})();
