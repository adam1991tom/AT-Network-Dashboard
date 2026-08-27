const $d = (id) => document.getElementById(id);
let rangeHours = 24;

const COLORS = ["#38bdf8", "#fb7185", "#f59e0b", "#a78bfa", "#2dd4bf", "#facc15", "#94a3b8", "#4ade80"];

function fmt(value, suffix = "", digits = 1) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(digits)}${suffix}` : "—";
}

function parseTime(ts) {
  const d = new Date(ts);
  return Number.isFinite(d.getTime()) ? d.getTime() : 0;
}

function timeLabel(ts) {
  const d = new Date(ts);
  if (!Number.isFinite(d.getTime())) return "";
  return rangeHours <= 24
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { day: "2-digit", month: "short" });
}

function legend(id, series) {
  const el = $d(id);
  if (!el) return;
  el.innerHTML = series.map((s, i) => `<span><i style="background:${s.color || COLORS[i % COLORS.length]}"></i>${s.name}</span>`).join("");
}

function drawChart(canvasId, emptyId, series, options = {}) {
  const canvas = $d(canvasId);
  const empty = $d(emptyId);
  if (!canvas) return;
  const validSeries = series.filter((s) => s.points.some((p) => Number.isFinite(Number(p.value))));
  if (!validSeries.length) {
    canvas.style.display = "none";
    if (empty) empty.style.display = "block";
    return;
  }
  canvas.style.display = "block";
  if (empty) empty.style.display = "none";

  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 1000;
  const height = Number(canvas.getAttribute("height")) || 280;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);

  const pad = { left: 52, right: 18, top: 14, bottom: 30 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const all = validSeries.flatMap((s) => s.points.filter((p) => Number.isFinite(Number(p.value))));
  const times = all.map((p) => parseTime(p.ts)).filter(Boolean);
  if (!times.length) return;
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const rawValues = all.map((p) => Number(p.value));
  let minV = options.min ?? Math.min(...rawValues);
  let maxV = options.max ?? Math.max(...rawValues);
  if (options.zeroBase !== false) minV = Math.min(0, minV);
  if (maxV === minV) maxV = minV + 1;
  const margin = (maxV - minV) * 0.08;
  if (options.max === undefined) maxV += margin;

  const x = (ts) => pad.left + ((parseTime(ts) - minT) / Math.max(1, maxT - minT)) * plotW;
  const y = (v) => pad.top + (1 - (Number(v) - minV) / (maxV - minV)) * plotH;

  ctx.strokeStyle = "rgba(148,163,184,.14)";
  ctx.fillStyle = "#8fa0b5";
  ctx.font = "11px system-ui";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const yy = pad.top + (plotH / 5) * i;
    ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(width - pad.right, yy); ctx.stroke();
    const val = maxV - ((maxV - minV) / 5) * i;
    ctx.fillText(`${Math.round(val)}${options.unit || ""}`, 5, yy + 4);
  }
  for (let i = 0; i <= 6; i++) {
    const xx = pad.left + (plotW / 6) * i;
    const t = minT + ((maxT - minT) / 6) * i;
    ctx.fillText(timeLabel(new Date(t).toISOString()), Math.max(pad.left, xx - 24), height - 8);
  }

  validSeries.forEach((s, index) => {
    const points = s.points.filter((p) => Number.isFinite(Number(p.value))).sort((a, b) => parseTime(a.ts) - parseTime(b.ts));
    if (!points.length) return;
    ctx.strokeStyle = s.color || COLORS[index % COLORS.length];
    ctx.lineWidth = s.width || 2;
    ctx.beginPath();
    points.forEach((p, i) => {
      const px = x(p.ts), py = y(p.value);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.stroke();
  });
}

function latest(rows) { return rows?.length ? rows[rows.length - 1] : null; }

async function json(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function loadDashboard() {
  try {
    const [live, speed, ping, gateway, ups, wifi] = await Promise.all([
      json("/api/monitoring/live"),
      json(`/api/monitoring/speedtests?hours=${rangeHours}`),
      json(`/api/monitoring/ping?hours=${rangeHours}`),
      json(`/api/monitoring/gateway?hours=${rangeHours}`),
      json(`/api/monitoring/ups?hours=${rangeHours}`),
      json(`/api/monitoring/wifi?hours=${rangeHours}`),
    ]);

    const lp = live.ping;
    if (lp) {
      $d("internet_state").textContent = lp.online ? "ONLINE" : "OFFLINE";
      $d("internet_state").className = lp.online ? "state-good" : "state-bad";
      $d("internet_detail").textContent = `${fmt(lp.latency, " ms")} · ${fmt(lp.packet_loss, "%")} loss`;
    }

    const ls = live.speedtest;
    if (ls) {
      $d("speed_state").textContent = `${Math.round(Number(ls.download || 0))} ↓`;
      $d("speed_detail").textContent = `${Math.round(Number(ls.upload || 0))} Mbps ↑ · ${fmt(ls.latency, " ms")}`;
    }

    const lu = live.ups;
    if (lu) {
      const onMains = String(lu.status || "").includes("OL");
      $d("ups_state").textContent = lu.connected ? (onMains ? "ON MAINS" : (lu.status || "CONNECTED")) : "DISCONNECTED";
      $d("ups_state").className = lu.connected && onMains ? "state-good" : "state-bad";
      $d("ups_detail").textContent = `${fmt(lu.load_pct, "%")} load · ${fmt(lu.input_voltage, " V")}`;
    }

    const lg = live.gateway;
    if (lg) {
      $d("gateway_cpu").textContent = fmt(lg.cpu, "%");
      $d("gateway_mem").textContent = fmt(lg.memory, "%");
      $d("gateway_cpu_detail").textContent = lg.temperature != null ? `${fmt(lg.temperature, " °C")} CPU temp` : "UniFi gateway";
      $d("gateway_mem_detail").textContent = lg.wan_up ? "WAN online" : "WAN offline";
    }

    const radios = live.wifi || [];
    if (radios.length) {
      const worst = Math.max(...radios.map((r) => Number(r.retries || 0)));
      $d("wifi_state").textContent = worst >= 40 ? "ATTENTION" : worst >= 30 ? "WATCH" : "HEALTHY";
      $d("wifi_state").className = worst >= 40 ? "state-bad" : worst >= 30 ? "state-warn" : "state-good";
      $d("wifi_detail").textContent = `Worst retries ${worst.toFixed(1)}% · ${radios.length} radios`;
    }

    legend("speed_legend", [{name:"Download Mbps",color:COLORS[0]},{name:"Upload Mbps",color:COLORS[1]}]);
    drawChart("speed_chart", "speed_empty", [
      { name: "Download", color: COLORS[0], points: speed.map((r) => ({ ts: r.ts, value: r.download })) },
      { name: "Upload", color: COLORS[1], points: speed.map((r) => ({ ts: r.ts, value: r.upload })) },
    ], { unit: "" });

    legend("quality_legend", [{name:"Ping ms",color:COLORS[0]},{name:"Packet Loss %",color:COLORS[2]}]);
    drawChart("quality_chart", "quality_empty", [
      { name: "Ping", color: COLORS[0], points: ping.map((r) => ({ ts: r.ts, value: r.latency })) },
      { name: "Packet Loss", color: COLORS[2], points: ping.map((r) => ({ ts: r.ts, value: r.packet_loss })) },
    ], { min: 0 });

    legend("gateway_legend", [{name:"CPU %",color:COLORS[0]},{name:"Memory %",color:COLORS[3]},{name:"Temperature °C",color:COLORS[2]}]);
    drawChart("gateway_chart", "gateway_empty", [
      { name: "CPU", color: COLORS[0], points: gateway.map((r) => ({ ts: r.ts, value: r.cpu })) },
      { name: "Memory", color: COLORS[3], points: gateway.map((r) => ({ ts: r.ts, value: r.memory })) },
      { name: "Temperature", color: COLORS[2], points: gateway.map((r) => ({ ts: r.ts, value: r.temperature })) },
    ], { min: 0, max: 100, unit: "%" });

    const gw = latest(gateway);
    $d("gateway_stats").innerHTML = gw ? `
      <div><span>WAN</span><strong>${gw.wan_up ? "ONLINE" : "OFFLINE"}</strong></div>
      <div><span>WAN IP</span><strong>${gw.wan_ip || "—"}</strong></div>
      <div><span>Link</span><strong>${gw.link_speed ? `${gw.link_speed} Mbps` : "—"}</strong></div>
      <div><span>RX errors</span><strong>${gw.rx_errors ?? "—"}</strong></div>
      <div><span>TX errors</span><strong>${gw.tx_errors ?? "—"}</strong></div>
      <div><span>RX dropped</span><strong>${gw.rx_dropped ?? "—"}</strong></div>` : "";

    legend("ups_legend", [{name:"UPS Load %",color:COLORS[4]}]);
    drawChart("ups_chart", "ups_empty", [
      { name: "UPS Load", color: COLORS[4], points: ups.filter((r) => r.connected).map((r) => ({ ts: r.ts, value: r.load_pct })) },
    ], { min: 0, max: 100, unit: "%" });

    const up = latest(ups);
    if (up) {
      $d("ups_legend").insertAdjacentHTML("beforeend", `<span class="current-values">Input ${fmt(up.input_voltage," V")} · Output ${fmt(up.output_voltage," V")} · Battery ${fmt(up.battery_voltage," V")} · ${fmt(up.input_frequency," Hz")}</span>`);
    }

    const wifiKeys = [...new Set(wifi.map((r) => `${r.ap_name}|${r.band}`))];
    const wifiSeries = wifiKeys.slice(0, 8).map((key, i) => {
      const [ap, band] = key.split("|");
      return { name: `${ap} ${band} retries`, color: COLORS[i % COLORS.length], points: wifi.filter((r) => `${r.ap_name}|${r.band}` === key).map((r) => ({ ts: r.ts, value: r.retries })) };
    });
    legend("wifi_legend", wifiSeries);
    drawChart("wifi_chart", "wifi_empty", wifiSeries, { min: 0, max: 100, unit: "%" });

    $d("wifi_cards").innerHTML = radios.map((r) => {
      const retries = Number(r.retries || 0);
      const status = retries >= 40 ? "bad" : retries >= 30 ? "warn" : "good";
      return `<article class="wifi-radio-card ${status}">
        <div class="wifi-card-title"><strong>${r.ap_name}</strong><span>${r.band}</span></div>
        <div class="wifi-card-metrics">
          <div><span>Channel</span><strong>${r.channel || "—"}</strong></div>
          <div><span>Width</span><strong>${r.width || "—"} MHz</strong></div>
          <div><span>Retries</span><strong>${fmt(r.retries,"%")}</strong></div>
          <div><span>Utilisation</span><strong>${fmt(r.utilization,"%")}</strong></div>
          <div><span>Clients</span><strong>${r.clients ?? "—"}</strong></div>
          <div><span>TX Power</span><strong>${fmt(r.tx_power,"",0)}</strong></div>
        </div>
      </article>`;
    }).join("");

    const failures = [lp && !lp.online, lu && !lu.connected, lg && !lg.wan_up].filter(Boolean).length;
    const overall = $d("overall_status");
    overall.textContent = failures ? "NEEDS ATTENTION" : "SYSTEM HEALTHY";
    overall.className = failures ? "status-pill bad" : "status-pill good";
  } catch (error) {
    console.error(error);
    const overall = $d("overall_status");
    overall.textContent = "COLLECTOR ERROR";
    overall.className = "status-pill bad";
  }
}

document.querySelectorAll("[data-range-group] .range-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-range-group] .range-button").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    rangeHours = Number(button.dataset.hours || 24);
    loadDashboard();
  });
});

loadDashboard();
setInterval(loadDashboard, 30000);
window.addEventListener("resize", () => loadDashboard());
