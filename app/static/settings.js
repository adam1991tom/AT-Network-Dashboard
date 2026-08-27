const $ = (id) => document.getElementById(id);

const textFields = [
  "application_name",
  "application_subtitle",
  "timezone",
  "theme",
  "accent",
  "default_range_hours",
  "isp_provider",
  "expected_download",
  "expected_upload",
  "warning_threshold",
  "major_threshold",
  "critical_threshold",
  "ping_target",
  "speedtest_minutes",
  "unifi_url",
  "unifi_verify_ssl",
  "ups_type",
  "ups_host",
  "ups_port",
  "ups_name",
  "nutpi_status_path",
];

const checkboxFields = [
  "isp_enabled",
  "unifi_enabled",
  "ups_enabled",
  "discord_enabled",
];

function boolValue(value) {
  return String(value).toLowerCase() === "true";
}

function applyAccent(accent) {
  const palette = {
    green: { hex: "#22c55e", rgb: "34,197,94" },
    blue: { hex: "#3b82f6", rgb: "59,130,246" },
    purple: { hex: "#a855f7", rgb: "168,85,247" },
    amber: { hex: "#f59e0b", rgb: "245,158,11" },
  };

  const selected = palette[accent] || palette.green;
  const root = document.documentElement;
  root.style.setProperty("--accent", selected.hex);
  root.style.setProperty("--accent-rgb", selected.rgb);
  root.style.setProperty("--accent-soft", `rgba(${selected.rgb},.12)`);
  root.style.setProperty("--accent-border", `rgba(${selected.rgb},.28)`);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme || "dark";
}

function activatePanel(panelId) {
  document.querySelectorAll(".settings-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.panel === panelId);
  });

  document.querySelectorAll(".settings-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === panelId);
  });
}

document.querySelectorAll(".settings-tab").forEach((tab) => {
  tab.addEventListener("click", () => activatePanel(tab.dataset.panel));
});

async function loadSettings() {
  const status = $("save_status");
  try {
    const response = await fetch("/api/settings", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    textFields.forEach((id) => {
      if ($(id) && data[id] !== undefined) $(id).value = data[id];
    });

    checkboxFields.forEach((id) => {
      if ($(id) && data[id] !== undefined) $(id).checked = boolValue(data[id]);
    });

    $("unifi_key_status").textContent = data.unifi_api_key_configured
      ? "API key configured ✓"
      : "No API key stored";

    $("discord_status").textContent = data.discord_webhook_configured
      ? "Webhook configured ✓"
      : "No webhook stored";

    $("setup_state").textContent = boolValue(data.setup_complete)
      ? "Complete ✓"
      : "Setup required";

    applyAccent(data.accent || "green");
    applyTheme(data.theme || "dark");
    status.textContent = "Settings loaded";
  } catch (error) {
    status.textContent = `Failed to load settings: ${error}`;
  }
}

async function saveSettings() {
  const status = $("save_status");
  const payload = {};

  textFields.forEach((id) => {
    if ($(id)) payload[id] = $(id).value;
  });

  checkboxFields.forEach((id) => {
    if ($(id)) payload[id] = $(id).checked ? "true" : "false";
  });

  if ($("unifi_api_key").value.trim()) {
    payload.unifi_api_key = $("unifi_api_key").value.trim();
  }
  if ($("discord_webhook").value.trim()) {
    payload.discord_webhook = $("discord_webhook").value.trim();
  }

  status.textContent = "Saving…";

  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    $("unifi_api_key").value = "";
    $("discord_webhook").value = "";
    status.textContent = "Saved ✓";
    await loadSettings();
  } catch (error) {
    status.textContent = `Save failed: ${error}`;
  }
}

$("save_settings").addEventListener("click", saveSettings);

if ($("accent")) {
  $("accent").addEventListener("change", () => applyAccent($("accent").value));
}

if ($("theme")) {
  $("theme").addEventListener("change", () => applyTheme($("theme").value));
}

loadSettings();
