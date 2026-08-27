const $ = (id) => document.getElementById(id);

const textFields = [
  "application_name", "application_subtitle", "timezone", "theme", "accent", "default_range_hours",
  "isp_provider", "expected_download", "expected_upload", "warning_threshold", "major_threshold",
  "critical_threshold", "ping_target", "speedtest_minutes", "unifi_url", "unifi_verify_ssl",
  "ups_type", "ups_host", "ups_port", "ups_name", "nutpi_status_path",
  "wifi_warning_threshold", "wifi_major_threshold", "wifi_critical_threshold", "wifi_persist_minutes",
  "wifi_recovery_threshold", "wifi_recovery_minutes", "notification_cooldown_minutes",
];
const checkboxFields = ["isp_enabled", "unifi_enabled", "ups_enabled", "discord_enabled", "notify_internet", "notify_wifi", "notify_power"];

function boolValue(value) { return String(value).toLowerCase() === "true"; }
function applyAccent(accent) {
  const palette = {green:{hex:"#22c55e",rgb:"34,197,94"},blue:{hex:"#3b82f6",rgb:"59,130,246"},purple:{hex:"#a855f7",rgb:"168,85,247"},amber:{hex:"#f59e0b",rgb:"245,158,11"}};
  const selected = palette[accent] || palette.green; const root = document.documentElement;
  root.style.setProperty("--accent", selected.hex); root.style.setProperty("--accent-rgb", selected.rgb); root.style.setProperty("--accent-soft", `rgba(${selected.rgb},.12)`); root.style.setProperty("--accent-border", `rgba(${selected.rgb},.28)`);
}
function applyTheme(theme) { document.documentElement.dataset.theme = theme || "dark"; }
function activatePanel(panelId) {
  document.querySelectorAll(".settings-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.panel === panelId));
  document.querySelectorAll(".settings-panel").forEach((panel) => panel.classList.toggle("active", panel.id === panelId));
  history.replaceState(null, "", `#${panelId}`);
}
document.querySelectorAll(".settings-tab").forEach((tab) => tab.addEventListener("click", () => activatePanel(tab.dataset.panel)));

function collectPayload(includeSecrets = true) {
  const payload = {};
  textFields.forEach((id) => { if ($(id)) payload[id] = $(id).value; });
  checkboxFields.forEach((id) => { if ($(id)) payload[id] = $(id).checked ? "true" : "false"; });
  if (includeSecrets && $("unifi_api_key")?.value.trim()) payload.unifi_api_key = $("unifi_api_key").value.trim();
  if (includeSecrets && $("discord_webhook")?.value.trim()) payload.discord_webhook = $("discord_webhook").value.trim();
  return payload;
}

function installExtraControls() {
  const pingButton = $("test_ping");
  if (pingButton && !$("test_speedtest")) {
    const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button"; button.id = "test_speedtest"; button.textContent = "Run ISP Speed Test";
    const status = document.createElement("span"); status.className = "test-status"; status.id = "speedtest_test_status"; status.textContent = "Not tested";
    pingButton.parentElement.append(button, status);
    button.addEventListener("click", runSpeedTest);
  }

  const system = $("system");
  if (system && !$("history_probe")) {
    const block = document.createElement("div"); block.className = "integration-block"; block.style.marginTop = "18px";
    block.innerHTML = `
      <div class="integration-title"><div><strong>Historical Data Import</strong><span class="muted">Read-only check of history still retained by the configured UniFi controller.</span></div></div>
      <div class="field-grid"><label>Look back<select id="history_probe_days"><option value="90">90 Days</option><option value="180">180 Days</option><option value="365" selected>1 Year</option><option value="730">2 Years</option></select></label></div>
      <div class="test-row"><button type="button" class="secondary-button" id="history_probe">Check UniFi History</button><span class="test-status" id="history_probe_status">Not checked</span></div>
      <div id="history_probe_results" class="info-banner" style="display:none"></div>`;
    system.appendChild(block); $("history_probe").addEventListener("click", probeHistory);
  }
}

async function loadSystemInfo() {
  try { const response = await fetch("/api/system/info", {cache:"no-store"}); if (!response.ok) return; const data = await response.json();
    $("system_environment").textContent = data.environment || "—"; $("system_host").textContent = data.hostname || "—"; $("system_python").textContent = data.python || "—"; $("system_database").textContent = data.database || "—"; $("security_encryption").textContent = data.encryption?.ok ? `Active ✓ · ${data.encryption.source}` : "Problem detected";
  } catch (_) {}
}

async function loadSettings() {
  const status = $("save_status");
  try { const response = await fetch("/api/settings", {cache:"no-store"}); if (!response.ok) throw new Error(`HTTP ${response.status}`); const data = await response.json();
    textFields.forEach((id) => { if ($(id) && data[id] !== undefined) $(id).value = data[id]; }); checkboxFields.forEach((id) => { if ($(id) && data[id] !== undefined) $(id).checked = boolValue(data[id]); });
    $("unifi_key_status").textContent = data.unifi_api_key_configured ? "API key configured ✓" : "No API key stored"; $("discord_status").textContent = data.discord_webhook_configured ? "Webhook configured ✓" : "No webhook stored"; $("security_unifi").textContent = data.unifi_api_key_configured ? "Encrypted / configured ✓" : "Not configured"; $("security_discord").textContent = data.discord_webhook_configured ? "Encrypted / configured ✓" : "Not configured"; $("setup_state").textContent = boolValue(data.setup_complete) ? "Complete ✓" : "Setup required"; $("settings_health").textContent = boolValue(data.setup_complete) ? "CONFIGURED" : "SETUP REQUIRED"; $("settings_health").className = `status-pill ${boolValue(data.setup_complete) ? "good" : "warn"}`;
    applyAccent(data.accent || "green"); applyTheme(data.theme || "dark"); status.textContent = "Settings loaded"; await loadSystemInfo();
  } catch (error) { status.textContent = `Failed to load settings: ${error}`; }
}

async function saveSettings() {
  const status = $("save_status"); status.textContent = "Saving…";
  try { const response = await fetch("/api/settings", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collectPayload(true))}); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(body.detail || body.message || `HTTP ${response.status}`); if ($("unifi_api_key")) $("unifi_api_key").value = ""; if ($("discord_webhook")) $("discord_webhook").value = ""; status.textContent = "Saved ✓"; await loadSettings(); } catch (error) { status.textContent = `Save failed: ${error}`; }
}

async function runTest(kind, statusId) {
  const status = $(statusId); status.textContent = "Testing…"; status.className = "test-status testing";
  try { const response = await fetch(`/api/settings/test/${kind}`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collectPayload(true))}); const result = await response.json(); let extra = "";
    if (kind === "ups" && result.ok) { const bits=[]; if(result.status)bits.push(result.status); if(result.load!==undefined&&result.load!==null)bits.push(`Load ${result.load}%`); if(result.input_voltage)bits.push(`Input ${result.input_voltage} V`); extra=bits.length?` · ${bits.join(" · ")}`:""; } else if (result.status) extra=` · ${result.status}`;
    status.textContent = result.ok ? `Connected ✓${extra}` : `Failed · ${result.message || "Connection test failed"}`; status.className = `test-status ${result.ok ? "good" : "bad"}`; status.title = result.output || result.message || "";
  } catch (error) { status.textContent=`Error · ${error}`; status.className="test-status bad"; }
}

async function runSpeedTest() {
  const status=$("speedtest_test_status"); status.textContent="Starting gateway speed test…"; status.className="test-status testing";
  try { const response=await fetch("/api/settings/test/speedtest",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collectPayload(true))}); const result=await response.json(); status.textContent=result.ok?"Started ✓ · Results will appear on the Dashboard when UniFi completes the test":`Failed · ${result.message || "Could not start test"}`; status.className=`test-status ${result.ok?"good":"bad"}`; } catch(error){status.textContent=`Error · ${error}`;status.className="test-status bad";}
}

async function probeHistory() {
  const status=$("history_probe_status"), results=$("history_probe_results"); status.textContent="Checking retained UniFi history…"; status.className="test-status testing"; results.style.display="none";
  const payload=collectPayload(true); payload.history_probe_days=$("history_probe_days").value;
  try { const response=await fetch("/api/settings/test/unifi-history",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); const data=await response.json(); status.textContent=data.ok?`Found history ✓ · ${data.total_records} records`:`No history found · ${data.message || "Probe failed"}`; status.className=`test-status ${data.ok?"good":"bad"}`;
    const sources=Object.entries(data.sources||{}).map(([name,s])=>`<div><strong>${escapeHtml(name)}</strong>: ${s.records||0} records${s.oldest?` · ${escapeHtml(s.oldest)} → ${escapeHtml(s.newest)}`:""}${s.error?` · ${escapeHtml(s.error)}`:""}</div>`).join(""); results.innerHTML=`<strong>UniFi retained-history probe</strong><div style="margin-top:8px">Overall: ${escapeHtml(data.oldest||"—")} → ${escapeHtml(data.newest||"—")}</div>${sources}`; results.style.display="block";
  } catch(error){status.textContent=`Error · ${error}`;status.className="test-status bad";}
}

async function loadChanges() { if(!$("changes_body"))return; try{const response=await fetch("/api/network-changes",{cache:"no-store"});const data=await response.json();$("changes_body").innerHTML=data.items?.length?data.items.map((item)=>`<tr><td>${escapeHtml(item.ts)}</td><td>${escapeHtml(item.category)}</td><td><strong>${escapeHtml(item.summary)}</strong>${item.details?`<small>${escapeHtml(item.details)}</small>`:""}</td></tr>`).join(""):'<tr><td colspan="3" class="muted">No network changes recorded yet.</td></tr>';}catch(_){$("changes_body").innerHTML='<tr><td colspan="3" class="bad-text">Unable to load changes.</td></tr>';}}
function escapeHtml(value){return String(value??"").replace(/[&<>'"]/g,(char)=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));}
async function recordChange(){const status=$("change_status");const payload={category:$("change_category").value,summary:$("change_summary").value.trim(),details:$("change_details").value.trim()};status.textContent="Recording…";try{const response=await fetch("/api/network-changes",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.message||`HTTP ${response.status}`);$("change_summary").value="";$("change_details").value="";status.textContent="Recorded ✓";status.className="test-status good";await loadChanges();}catch(error){status.textContent=`Failed · ${error}`;status.className="test-status bad";}}

installExtraControls();
$("save_settings")?.addEventListener("click",saveSettings); $("test_unifi")?.addEventListener("click",()=>runTest("unifi","unifi_test_status")); $("test_ups")?.addEventListener("click",()=>runTest("ups","ups_test_status")); $("test_discord")?.addEventListener("click",()=>runTest("discord","discord_test_status")); $("test_ping")?.addEventListener("click",()=>runTest("ping","ping_test_status")); $("record_change")?.addEventListener("click",recordChange); $("accent")?.addEventListener("change",()=>applyAccent($("accent").value)); $("theme")?.addEventListener("change",()=>applyTheme($("theme").value));
const requestedPanel=location.hash.replace("#",""); if(requestedPanel&&document.getElementById(requestedPanel))activatePanel(requestedPanel); loadSettings(); loadChanges();
