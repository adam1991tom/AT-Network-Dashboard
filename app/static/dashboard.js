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
  if (rangeHours <= 24) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (rangeHours <= 24 * 14) return d.toLocaleDateString([], { weekday: "short", day: "2-digit" });
  return d.toLocaleDateString([], { day: "2-digit", month: "short" });
}

function legend(id, series) {
  const el = $d(id);
  if (!el) return;
  el.innerHTML = series.map((s, i) => `<span><i style="background:${s.color || COLORS[i % COLORS.length]}"></i>${s.name}</span>`).join("");
}

function thinPoints(points, maxPoints = 1400) {
  if (points.length <= maxPoints) return points;
  const step = (points.length - 1) / (maxPoints - 1);
  const output = [];
  for (let i = 0; i < maxPoints; i++) output.push(points[Math.round(i * step)]);
  return output;
}

function showEmpty(canvas, empty, height, message) {
  canvas.style.display = "none";
  if (empty) {
    if (message) empty.textContent = message;
    empty.style.display = "flex";
    empty.style.minHeight = `${height}px`;
  }
}

function drawChart(canvasId, emptyId, series, options = {}) {
  const canvas = $d(canvasId);
  const empty = $d(emptyId);
  if (!canvas) return;

  const height = Math.max(180, Number(canvas.dataset.chartHeight || options.height || 280));
  const prepared = series.map((s) => ({
    ...s,
    points: thinPoints(
      (s.points || [])
        .filter((p) => Number.isFinite(Number(p.value)) && parseTime(p.ts))
        .sort((a, b) => parseTime(a.ts) - parseTime(b.ts))
    ),
  }));
  const validSeries = prepared.filter((s) => s.points.length);

  if (!validSeries.length) {
    showEmpty(canvas, empty, height, options.emptyMessage);
    return;
  }

  canvas.style.display = "block";
  canvas.style.width = "100%";
  canvas.style.height = `${height}px`;
  if (empty) empty.style.display = "none";

  const containerWidth = canvas.parentElement?.clientWidth || canvas.getBoundingClientRect().width || 1000;
  const width = Math.max(320, Math.floor(containerWidth));
  const ratio = Math.min(2, window.devicePixelRatio || 1);

  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);

  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const pad = { left: 58, right: 18, top: 16, bottom: 34 };
  const plotW = Math.max(1, width - pad.left - pad.right);
  const plotH = Math.max(1, height - pad.top - pad.bottom);
  const all = validSeries.flatMap((s) => s.points);
  const times = all.map((p) => parseTime(p.ts)).filter(Boolean);
  if (!times.length) {
    showEmpty(canvas, empty, height, "No timestamped data is available in this range.");
    return;
  }

  let minT = Math.min(...times);
  let maxT = Math.max(...times);
  if (maxT === minT) {
    minT -= 30 * 60 * 1000;
    maxT += 30 * 60 * 1000;
  }

  const rawValues = all.map((p) => Number(p.value)).filter(Number.isFinite);
  let minV = options.min ?? Math.min(...rawValues);
  let maxV = options.max ?? Math.max(...rawValues);
  if (options.zeroBase !== false) minV = Math.min(0, minV);
  if (maxV === minV) maxV = minV + 1;
  const margin = Math.max(0.5, (maxV - minV) * 0.08);
  if (options.max === undefined) maxV += margin;
  if (options.min === undefined && options.zeroBase === false) minV -= margin;

  const x = (ts) => pad.left + ((parseTime(ts) - minT) / Math.max(1, maxT - minT)) * plotW;
  const y = (v) => pad.top + (1 - (Number(v) - minV) / Math.max(0.000001, maxV - minV)) * plotH;

  ctx.strokeStyle = "rgba(148,163,184,.14)";
  ctx.fillStyle = "#8fa0b5";
  ctx.font = "11px system-ui";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const yy = pad.top + (plotH / 5) * i;
    ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(width - pad.right, yy); ctx.stroke();
    const val = maxV - ((maxV - minV) / 5) * i;
    const digits = Math.abs(val) < 10 && options.decimals ? options.decimals : 0;
    ctx.fillText(`${val.toFixed(digits)}${options.unit || ""}`, 5, yy + 4);
  }

  ctx.textAlign = "center";
  for (let i = 0; i <= 6; i++) {
    const xx = pad.left + (plotW / 6) * i;
    const t = minT + ((maxT - minT) / 6) * i;
    ctx.fillText(timeLabel(new Date(t).toISOString()), xx, height - 9);
  }
  ctx.textAlign = "start";

  validSeries.forEach((s, index) => {
    const points = s.points;
    ctx.strokeStyle = s.color || COLORS[index % COLORS.length];
    ctx.lineWidth = s.width || 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
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
    const [live, speed, ping, gateway, ups, wifi, wan] = await Promise.all([
      json("/api/monitoring/live"),
      json(`/api/monitoring/speedtests?hours=${rangeHours}`),
      json(`/api/monitoring/ping?hours=${rangeHours}`),
      json(`/api/monitoring/gateway?hours=${rangeHours}`),
      json(`/api/monitoring/ups?hours=${rangeHours}`),
      json(`/api/monitoring/wifi?hours=${rangeHours}`),
      json(`/api/monitoring/unifi-wan?hours=${rangeHours}`),
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

    await new Promise((resolve) => requestAnimationFrame(resolve));

    legend("speed_legend", [{name:"Download Mbps",color:COLORS[0]},{name:"Upload Mbps",color:COLORS[1]}]);
    drawChart("speed_chart", "speed_empty", [
      { name: "Download", color: COLORS[0], points: speed.map((r) => ({ ts: r.ts, value: r.download })) },
      { name: "Upload", color: COLORS[1], points: speed.map((r) => ({ ts: r.ts, value: r.upload })) },
    ], { emptyMessage: "No ISP speed-test results are stored in this selected range yet." });

    legend("quality_legend", [{name:"Ping ms",color:COLORS[0]},{name:"Packet Loss %",color:COLORS[2]}]);
    drawChart("quality_chart", "quality_empty", [
      { name: "Ping", color: COLORS[0], points: ping.map((r) => ({ ts: r.ts, value: r.latency })) },
      { name: "Packet Loss", color: COLORS[2], points: ping.map((r) => ({ ts: r.ts, value: r.packet_loss })) },
    ], { min: 0, emptyMessage: "No internet-quality samples are stored in this selected range yet." });

    legend("wan_legend", [{name:"WAN Receive GB",color:COLORS[0]},{name:"WAN Transmit GB",color:COLORS[4]}]);
    drawChart("wan_chart", "wan_empty", [
      { name: "Receive", color: COLORS[0], points: wan.map((r) => ({ ts: r.ts, value: Number(r.rx_bytes || 0) / 1e9 })) },
      { name: "Transmit", color: COLORS[4], points: wan.map((r) => ({ ts: r.ts, value: Number(r.tx_bytes || 0) / 1e9 })) },
    ], { min: 0, unit: " GB", decimals: 1, emptyMessage: "No imported UniFi WAN history is available. Use Settings → System → Historical Data Import." });

    legend("gateway_legend", [{name:"CPU %",color:COLORS[0]},{name:"Memory %",color:COLORS[3]},{name:"Temperature °C",color:COLORS[2]}]);
    drawChart("gateway_chart", "gateway_empty", [
      { name: "CPU", color: COLORS[0], points: gateway.map((r) => ({ ts: r.ts, value: r.cpu })) },
      { name: "Memory", color: COLORS[3], points: gateway.map((r) => ({ ts: r.ts, value: r.memory })) },
      { name: "Temperature", color: COLORS[2], points: gateway.map((r) => ({ ts: r.ts, value: r.temperature })) },
    ], { min: 0, max: 100, unit: "%", emptyMessage: "No gateway system-stat samples are stored in this selected range yet." });

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
    ], { min: 0, max: 100, unit: "%", emptyMessage: "No UPS samples are stored in this selected range yet." });

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
    drawChart("wifi_chart", "wifi_empty", wifiSeries, { min: 0, max: 100, unit: "%", emptyMessage: "No Wi-Fi retry samples are stored in this selected range yet." });

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
  button.addEventListener("click", async () => {
    document.querySelectorAll("[data-range-group] .range-button").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    rangeHours = Number(button.dataset.hours || 24);
    await loadDashboard();
  });
});

loadDashboard();
setInterval(loadDashboard, 30000);
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(loadDashboard, 180);
});
