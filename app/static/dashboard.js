const dashEl = (id) => document.getElementById(id);

function stateText(item, disabledLabel = "DISABLED") {
  if (!item?.enabled) return disabledLabel;
  if (item.ok === true) return "ONLINE";
  if (item.ok === false) return "ATTENTION";
  return "CHECKING";
}

function setState(id, item, disabledLabel = "DISABLED") {
  const el = dashEl(id);
  if (!el) return;
  const text = stateText(item, disabledLabel);
  el.textContent = text;
  el.className = text === "ONLINE" ? "state-good" : text === "ATTENTION" ? "state-bad" : "state-muted";
}

async function loadDashboard() {
  try {
    const response = await fetch("/api/dashboard/summary", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    setState("internet_state", data.internet);
    setState("ups_state", data.ups);
    setState("unifi_state", data.unifi);
    setState("wifi_state", data.wifi);

    dashEl("isp_state").textContent = data.internet?.enabled ? (data.internet?.provider || "CONFIGURED") : "DISABLED";
    dashEl("internet_detail").textContent = data.internet?.enabled ? `Ping ${data.internet?.target || "—"}` : "Disabled in Settings";
    dashEl("isp_detail").textContent = data.internet?.provider || "No provider name set";
    dashEl("ups_detail").textContent = data.ups?.enabled
      ? (data.ups?.ok ? `${data.ups.status || "Connected"}${data.ups.load !== undefined && data.ups.load !== null ? ` · Load ${data.ups.load}%` : ""}` : (data.ups.message || "Connection failed"))
      : "Disabled in Settings";
    dashEl("unifi_detail").textContent = data.unifi?.enabled
      ? (data.unifi?.ok ? "Gateway connected" : (data.unifi.message || "Connection failed"))
      : "Disabled in Settings";
    dashEl("wifi_detail").textContent = data.wifi?.enabled ? (data.wifi?.ok ? "UniFi telemetry available" : "Waiting for UniFi") : "Disabled with UniFi";

    dashEl("setup_state").textContent = data.setup_complete ? "Complete ✓" : "Setup required";
    dashEl("internet_enabled").textContent = data.internet?.enabled ? "Enabled" : "Disabled";
    dashEl("unifi_enabled").textContent = data.unifi?.enabled ? "Enabled" : "Disabled";
    dashEl("ups_enabled").textContent = data.ups?.enabled ? "Enabled" : "Disabled";

    const enabled = [data.internet, data.unifi, data.ups].filter((x) => x?.enabled);
    const failed = enabled.filter((x) => x.ok === false);
    const overall = dashEl("overall_status");
    if (!data.setup_complete) {
      overall.textContent = "SETUP REQUIRED";
      overall.className = "status-pill warn";
      dashEl("dashboard_message").textContent = "Complete the Settings page and enable the integrations you want to monitor.";
    } else if (failed.length) {
      overall.textContent = "NEEDS ATTENTION";
      overall.className = "status-pill bad";
      dashEl("dashboard_message").textContent = `${failed.length} enabled integration${failed.length === 1 ? " needs" : "s need"} attention. Open Settings to run connection tests.`;
    } else if (enabled.length) {
      overall.textContent = "SYSTEM HEALTHY";
      overall.className = "status-pill good";
      dashEl("dashboard_message").textContent = "All enabled integrations responded successfully.";
    } else {
      overall.textContent = "NO MONITORS ENABLED";
      overall.className = "status-pill warn";
      dashEl("dashboard_message").textContent = "The application is running, but no monitoring integrations are enabled yet.";
    }
  } catch (error) {
    const overall = dashEl("overall_status");
    overall.textContent = "STATUS ERROR";
    overall.className = "status-pill bad";
    dashEl("dashboard_message").textContent = `Unable to load dashboard status: ${error}`;
  }
}

loadDashboard();
setInterval(loadDashboard, 30000);
