const $ = id => document.getElementById(id);
const boolValue = value => String(value).toLowerCase() === 'true';
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const setText = (id, value) => { const el=$(id); if(el) el.textContent=value; };
const setClass = (id, value) => { const el=$(id); if(el) el.className=value; };

const textFields = [
  'application_name','application_subtitle','site_name','site_address','timezone','theme','accent','default_range_hours',
  'isp_provider','isp_account_number','isp_service_reference','isp_support_phone','isp_support_url','isp_notes',
  'expected_download','expected_upload','warning_threshold','major_threshold','critical_threshold','ping_target','speedtest_minutes',
  'unifi_url','unifi_verify_ssl','ups_type','ups_host','ups_port','ups_name','nutpi_status_path',
  'wifi_warning_threshold','wifi_major_threshold','wifi_critical_threshold','wifi_persist_minutes','wifi_recovery_threshold','wifi_recovery_minutes',
  'notification_min_severity','notification_cooldown_minutes','retention_days','session_hours','update_channel'
];
const checkboxFields = [
  'isp_enabled','speedtest_auto_enabled','unifi_enabled','ups_enabled','discord_enabled','notify_internet','notify_wifi','notify_power','notify_gateway','notify_system',
  'maintenance_mode','auto_update_check','notify_update_available'
];

function activatePanel(panelId){
  document.querySelectorAll('.settings-tab').forEach(tab=>tab.classList.toggle('active',tab.dataset.panel===panelId));
  document.querySelectorAll('.settings-panel').forEach(panel=>panel.classList.toggle('active',panel.id===panelId));
  history.replaceState(null,'',`#${panelId}`);
}
document.querySelectorAll('.settings-tab').forEach(tab=>tab.addEventListener('click',()=>activatePanel(tab.dataset.panel)));

async function api(url,opt={}){
  const response=await fetch(url,{cache:'no-store',...opt});
  if(response.status===401){location.href='/login';throw new Error('Authentication required');}
  const type=response.headers.get('content-type')||'';
  const data=type.includes('application/json')?await response.json().catch(()=>({})):{};
  if(!response.ok)throw new Error(data.detail||data.message||`HTTP ${response.status}`);
  return data;
}

function collectPayload(includeSecrets=true){
  const payload={};
  textFields.forEach(id=>{const el=$(id);if(el)payload[id]=el.value;});
  checkboxFields.forEach(id=>{const el=$(id);if(el)payload[id]=el.checked?'true':'false';});
  if(includeSecrets){
    const key=$('unifi_api_key')?.value.trim(); if(key)payload.unifi_api_key=key;
    const hook=$('discord_webhook')?.value.trim(); if(hook)payload.discord_webhook=hook;
  }
  return payload;
}

function applyAppearance(){
  const theme=$('theme')?.value||'dark',accent=$('accent')?.value||'green';
  localStorage.setItem('at-theme',JSON.stringify({theme,accent}));
  window.ATApplyTheme?.({theme,accent});
}
$('theme')?.addEventListener('change',applyAppearance);
$('accent')?.addEventListener('change',applyAppearance);

async function loadSettings(){
  const save=$('save_status');
  try{
    const data=await api('/api/settings');
    textFields.forEach(id=>{const el=$(id);if(el&&data[id]!==undefined)el.value=data[id];});
    checkboxFields.forEach(id=>{const el=$(id);if(el&&data[id]!==undefined)el.checked=boolValue(data[id]);});
    setText('unifi_key_status',data.unifi_api_key_configured?'API key configured ✓':'No API key stored');
    setText('discord_status',data.discord_webhook_configured?'Webhook configured ✓':'No webhook stored');
    setText('security_unifi',data.unifi_api_key_configured?'Encrypted / configured ✓':'Not configured');
    setText('security_discord',data.discord_webhook_configured?'Encrypted / configured ✓':'Not configured');
    setText('settings_health',boolValue(data.setup_complete)?'CONFIGURED':'SETUP REQUIRED');
    setClass('settings_health',`status-pill ${boolValue(data.setup_complete)?'good':'warn'}`);
    applyAppearance();
    if(save)save.textContent='Settings loaded';
    await Promise.allSettled([loadSystemInfo(),loadMonitoringStatus(),loadBuildInfo(),loadChanges()]);
  }catch(error){if(save)save.textContent=`Failed to load settings: ${error.message||error}`;}
}

async function saveSettings(){
  const status=$('save_status'); if(status)status.textContent='Saving…';
  try{
    const result=await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collectPayload(true))});
    if($('unifi_api_key'))$('unifi_api_key').value=''; if($('discord_webhook'))$('discord_webhook').value='';
    applyAppearance(); if(status)status.textContent='Saved ✓';
    const saved=result.settings||{};
    setText('settings_health','CONFIGURED');setClass('settings_health','status-pill good');
    setText('unifi_key_status',saved.unifi_api_key_configured?'API key configured ✓':'No API key stored');
    setText('discord_status',saved.discord_webhook_configured?'Webhook configured ✓':'No webhook stored');
    setTimeout(()=>{if(status&&status.textContent==='Saved ✓')status.textContent='All changes saved';},1800);
  }catch(error){if(status)status.textContent=`Save failed: ${error.message||error}`;}
}
$('save_settings')?.addEventListener('click',saveSettings);

async function runTest(kind,statusId){
  const status=$(statusId); if(status){status.textContent='Testing…';status.className='test-status testing';}
  try{
    const result=await api(`/api/settings/test/${kind}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collectPayload(true))});
    let message=result.message||result.status||'Connected';
    if(kind==='ups'&&result.ok){const bits=[];if(result.status)bits.push(result.status);if(result.load!=null)bits.push(`Load ${result.load}%`);if(result.input_voltage!=null)bits.push(`Input ${result.input_voltage} V`);if(bits.length)message=bits.join(' · ');}
    if(status){status.textContent=result.ok?`${message} ✓`:`Failed · ${message}`;status.className=`test-status ${result.ok?'good':'bad'}`;}
  }catch(error){if(status){status.textContent=`Error · ${error.message||error}`;status.className='test-status bad';}}
}
$('test_ping')?.addEventListener('click',()=>runTest('ping','ping_test_status'));
$('test_unifi')?.addEventListener('click',()=>runTest('unifi','unifi_test_status'));
$('test_ups')?.addEventListener('click',()=>runTest('ups','ups_test_status'));
$('test_discord')?.addEventListener('click',()=>runTest('discord','discord_test_status'));

async function runSpeedTest(){
  let status=$('speedtest_test_status');
  if(!status){status=document.createElement('span');status.id='speedtest_test_status';status.className='test-status';$('test_ping')?.closest('.test-row')?.appendChild(status);}
  if(status){status.textContent='Starting gateway speed test…';status.className='test-status testing';}
  try{const result=await api('/api/settings/test/speedtest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collectPayload(true))});if(status){status.textContent=result.ok?'Started ✓ · Results will appear when UniFi completes the test':`Failed · ${result.message||'Could not start test'}`;status.className=`test-status ${result.ok?'good':'bad'}`;}}
  catch(error){if(status){status.textContent=`Error · ${error.message||error}`;status.className='test-status bad';}}
}
if($('test_ping')&&!$('test_speedtest')){const b=document.createElement('button');b.type='button';b.id='test_speedtest';b.className='secondary-button';b.textContent='Run ISP Speed Test';$('test_ping').closest('.test-row')?.appendChild(b);b.addEventListener('click',runSpeedTest);}

async function loadSystemInfo(){
  try{const d=await api('/api/system/info');setText('system_version',d.version||'—');setText('system_environment',d.environment||'—');setText('system_host',d.hostname||'—');setText('system_python',d.python||'—');setText('system_database',d.database||'—');setText('security_encryption',d.encryption?.ok?`Active ✓ · ${d.encryption.source}`:'Problem detected');setText('update_installed',d.version||'—');}
  catch(_){}
}

async function loadMonitoringStatus(){
  const target=$('system_monitoring_status');if(!target)return;
  try{
    const d=await api('/api/system/monitoring-status');
    const labels={speedtest_history:'Speed tests',ping_history:'Ping',gateway_history:'Gateway',wifi_history:'Wi-Fi',ups_history:'UPS',incidents:'Incidents',unifi_wan_history:'UniFi WAN',unifi_ap_traffic_history:'UniFi AP traffic'};
    const rows=Object.entries(d.tables||{}).map(([k,v])=>`<div class="monitor-status-row"><span>${escapeHtml(labels[k]||k)}</span><strong>${Number(v.count||0).toLocaleString()}</strong><small>Latest: ${escapeHtml(v.newest||'No samples')}</small></div>`).join('');
    target.innerHTML=`<div class="monitor-summary"><strong>Database ${(Number(d.database_bytes||0)/1048576).toFixed(2)} MB</strong><span>${Object.values(d.tables||{}).reduce((n,v)=>n+Number(v.count||0),0).toLocaleString()} stored records</span></div><div class="monitor-status-grid">${rows||'<span>No monitoring tables found.</span>'}</div>`;
  }catch(error){target.textContent=`Unable to load monitoring status · ${error.message||error}`;}
}
$('system_refresh')?.addEventListener('click',loadMonitoringStatus);

$('retention_apply')?.addEventListener('click',async()=>{
  const status=$('retention_status');
  if(!confirm('Delete monitoring samples older than the selected retention period?'))return;
  if(status)status.textContent='Applying…';
  try{await saveSettings();const d=await api('/api/system/retention/apply',{method:'POST'});if(status){status.textContent=`Complete ✓ · ${d.deleted||0} old samples removed`;status.className='test-status good';}await loadMonitoringStatus();}
  catch(error){if(status){status.textContent=`Failed · ${error.message||error}`;status.className='test-status bad';}}
});

$('backup_download')?.addEventListener('click',()=>{window.location.href='/api/system/backup';});
$('restore_file')?.addEventListener('change',e=>{const file=e.target.files?.[0];$('restore_backup').disabled=!file;setText('restore_status',file?file.name:'No backup selected');});
$('restore_backup')?.addEventListener('click',async()=>{
  const file=$('restore_file')?.files?.[0],status=$('restore_status');if(!file)return;
  if(!confirm('Restore this backup? The current dashboard database will be replaced.'))return;
  if(status){status.textContent='Restoring…';status.className='test-status testing';}
  try{const r=await fetch('/api/system/restore',{method:'POST',headers:{'Content-Type':'application/zip'},body:file});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.message||`HTTP ${r.status}`);if(status){status.textContent=d.message||'Restore complete';status.className='test-status good';}}
  catch(error){if(status){status.textContent=`Restore failed · ${error.message||error}`;status.className='test-status bad';}}
});

function renderHistory(data,extra=''){
  const results=$('history_probe_results');if(!results)return;
  const sources=Object.entries(data.sources||{}).map(([name,s])=>`<div><strong>${escapeHtml(name)}</strong>: ${s.records||0} records${s.oldest?` · ${escapeHtml(s.oldest)} → ${escapeHtml(s.newest)}`:''}</div>`).join('');
  results.innerHTML=`<strong>UniFi retained history</strong><div>Overall: ${escapeHtml(data.oldest||'—')} → ${escapeHtml(data.newest||'—')}</div>${sources}${extra?`<div><strong>${escapeHtml(extra)}</strong></div>`:''}`;results.style.display='block';
}
async function probeHistory(){const status=$('history_probe_status');if(status)status.textContent='Checking…';const p=collectPayload(true);p.history_probe_days=$('history_probe_days')?.value||'365';try{const d=await api('/api/settings/test/unifi-history',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});if(status){status.textContent=d.ok?`Found ${d.total_records||0} records ✓`:(d.message||'No history found');status.className=`test-status ${d.ok?'good':'bad'}`;}renderHistory(d);}catch(error){if(status){status.textContent=`Error · ${error.message||error}`;status.className='test-status bad';}}}
async function importHistory(){const status=$('history_probe_status');if(status)status.textContent='Importing…';const p=collectPayload(true);p.history_probe_days=$('history_probe_days')?.value||'365';try{const d=await api('/api/settings/import/unifi-history',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});if(status){status.textContent=`Imported ${d.inserted.wan+d.inserted.ap} new records ✓`;status.className='test-status good';}renderHistory(await api('/api/settings/test/unifi-history',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)}),`Database totals: ${d.totals.wan} WAN · ${d.totals.ap} AP`);await loadMonitoringStatus();}catch(error){if(status){status.textContent=`Import failed · ${error.message||error}`;status.className='test-status bad';}}}
$('history_probe')?.addEventListener('click',probeHistory);$('history_import')?.addEventListener('click',importHistory);

async function changePassword(){const status=$('password_status'),a=$('new_password')?.value||'',b=$('confirm_password')?.value||'';if(a!==b){if(status){status.textContent='New passwords do not match';status.className='test-status bad';}return;}if(status)status.textContent='Changing…';try{const d=await api('/api/security/change-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_password:$('current_password')?.value||'',new_password:a})});if(status){status.textContent=`${d.message} · Sign in again`;status.className='test-status good';}setTimeout(()=>location.href='/login',1200);}catch(error){if(status){status.textContent=error.message||String(error);status.className='test-status bad';}}}
$('change_password')?.addEventListener('click',changePassword);

async function loadChanges(){const body=$('changes_body');if(!body)return;try{const d=await api('/api/network-changes');body.innerHTML=(d.items||[]).length?(d.items||[]).map(x=>`<tr><td>${escapeHtml(x.ts)}</td><td>${escapeHtml(x.category)}</td><td><strong>${escapeHtml(x.summary)}</strong><small>${escapeHtml(x.details||'')}</small></td></tr>`).join(''):'<tr><td colspan="3" class="muted">No recorded changes yet.</td></tr>';}catch(_){}}
$('record_change')?.addEventListener('click',async()=>{const status=$('change_status'),summary=$('change_summary')?.value.trim()||'';if(!summary){if(status)status.textContent='Enter a summary';return;}try{await api('/api/network-changes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:$('change_category')?.value||'Other',summary,details:$('change_details')?.value||''})});if(status){status.textContent='Recorded ✓';status.className='test-status good';}$('change_summary').value='';$('change_details').value='';await loadChanges();}catch(error){if(status){status.textContent=`Failed · ${error.message||error}`;status.className='test-status bad';}}});

let updateTarget='';
async function checkUpdate(){const status=$('update_status'),channel=$('update_channel')?.value||'stable';if(status)status.textContent='Checking…';try{const d=await api(`/api/system/update/check?channel=${encodeURIComponent(channel)}`);setText('update_installed',d.current||'—');setText('update_latest',d.latest||'No release');updateTarget=d.target||d.latest||'';if($('update_apply'))$('update_apply').disabled=!d.available;if(status){status.textContent=d.available?'Update available ✓':(d.message||'Up to date');status.className=`test-status ${d.available?'good':''}`;}const notes=$('update_notes');if(notes){notes.textContent=d.notes||'';notes.style.display=d.notes?'block':'none';}await pollUpdateState();}catch(error){if(status){status.textContent=`Check failed · ${error.message||error}`;status.className='test-status bad';}}}
async function applyUpdate(){const status=$('update_status');if(status)status.textContent='Queueing update…';try{const d=await api('/api/system/update/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel:$('update_channel')?.value||'stable',target:updateTarget})});if(status)status.textContent=d.message||'Update queued';if($('update_apply'))$('update_apply').disabled=true;setTimeout(pollUpdateState,1200);}catch(error){if(status){status.textContent=`Update failed · ${error.message||error}`;status.className='test-status bad';}}}
async function pollUpdateState(){try{const d=await api('/api/system/update/state');setText('update_state',String(d.status||'idle').toUpperCase());if(d.message)setText('update_status',d.message);}catch(_){}}
$('update_check')?.addEventListener('click',checkUpdate);$('update_apply')?.addEventListener('click',applyUpdate);

async function loadBuildInfo(){try{const d=await api('/api/system/build-info');setText('about_version',d.version||'—');setText('about_schema',d.schema||'—');setText('about_channel',d.update_channel||'—');}catch(_){} }

const initialHash=location.hash.replace('#','');if(initialHash&&$(initialHash)?.classList.contains('settings-panel'))activatePanel(initialHash);
loadSettings();
