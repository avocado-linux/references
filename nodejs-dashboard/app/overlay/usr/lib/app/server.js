const express = require("express");
const fs = require("fs");
const os = require("os");

const app = express();
const PORT = 5000;

// ---------------------------------------------------------------------------
// System metrics (read from /proc and /sys)
// ---------------------------------------------------------------------------

let prevCpu = null;

function readCpu() {
  const lines = fs.readFileSync("/proc/stat", "utf8").split("\n");

  function parse(line) {
    const p = line.trim().split(/\s+/).slice(1, 9).map(Number);
    const total = p.reduce((a, b) => a + b, 0);
    const idle = p[3] + p[4]; // idle + iowait
    return { total, idle };
  }

  const all = parse(lines[0]);
  const cores = [];
  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].startsWith("cpu")) break;
    cores.push(parse(lines[i]));
  }

  let percent = 0;
  const corePercents = cores.map(() => 0);

  if (prevCpu) {
    const dt = all.total - prevCpu.total;
    const di = all.idle - prevCpu.idle;
    percent = dt ? Math.round((1 - di / dt) * 1000) / 10 : 0;

    for (let i = 0; i < cores.length; i++) {
      const cdt = cores[i].total - prevCpu.cores[i].total;
      const cdi = cores[i].idle - prevCpu.cores[i].idle;
      corePercents[i] = cdt ? Math.round((1 - cdi / cdt) * 1000) / 10 : 0;
    }
  }

  prevCpu = { total: all.total, idle: all.idle, cores };
  return { percent, cores: corePercents };
}

function readMemory() {
  const info = {};
  const lines = fs.readFileSync("/proc/meminfo", "utf8").split("\n");
  for (const line of lines) {
    const m = line.match(/^(\w+):\s+(\d+)/);
    if (m) info[m[1]] = parseInt(m[2], 10);
  }
  const total = info.MemTotal || 0;
  const available = info.MemAvailable || 0;
  const used = total - available;
  return {
    total_mb: Math.floor(total / 1024),
    used_mb: Math.floor(used / 1024),
    free_mb: Math.floor((info.MemFree || 0) / 1024),
    available_mb: Math.floor(available / 1024),
    cached_mb: Math.floor((info.Cached || 0) / 1024),
    percent: total ? Math.round((used / total) * 1000) / 10 : 0,
  };
}

function readLoad() {
  const parts = fs.readFileSync("/proc/loadavg", "utf8").split(/\s+/);
  const [running] = parts[3].split("/");
  return {
    load1: parseFloat(parts[0]),
    load5: parseFloat(parts[1]),
    load15: parseFloat(parts[2]),
    running_processes: parseInt(running, 10),
  };
}

function readUptime() {
  const secs = parseFloat(fs.readFileSync("/proc/uptime", "utf8").split(/\s+/)[0]);
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const parts = [];
  if (d) parts.push(d + "d");
  if (h) parts.push(h + "h");
  parts.push(m + "m");
  return { seconds: Math.floor(secs), formatted: parts.join(" ") };
}

function readDisk() {
  try {
    const st = fs.statfsSync("/var");
    const total = st.blocks * st.bsize;
    const free = st.bfree * st.bsize;
    const used = total - free;
    return {
      total_mb: Math.floor(total / (1024 * 1024)),
      used_mb: Math.floor(used / (1024 * 1024)),
      free_mb: Math.floor(free / (1024 * 1024)),
      percent: total ? Math.round((used / total) * 1000) / 10 : 0,
    };
  } catch {
    return null;
  }
}

function readNetwork() {
  const interfaces = [];
  try {
    const lines = fs.readFileSync("/proc/net/dev", "utf8").split("\n");
    for (const line of lines) {
      if (!line.includes(":")) continue;
      const parts = line.trim().split(/\s+/);
      const name = parts[0].replace(":", "");
      if (name === "lo") continue;
      interfaces.push({
        name,
        rx_bytes: parseInt(parts[1], 10),
        rx_packets: parseInt(parts[2], 10),
        tx_bytes: parseInt(parts[9], 10),
        tx_packets: parseInt(parts[10], 10),
      });
    }
  } catch {}
  return interfaces;
}

function readTemperature() {
  try {
    const zones = fs.readdirSync("/sys/class/thermal").sort();
    for (const zone of zones) {
      const p = `/sys/class/thermal/${zone}/temp`;
      if (fs.existsSync(p)) {
        const c = parseInt(fs.readFileSync(p, "utf8").trim(), 10) / 1000;
        return { celsius: Math.round(c * 10) / 10, fahrenheit: Math.round((c * 9 / 5 + 32) * 10) / 10 };
      }
    }
  } catch {}
  return null;
}

function readOsRelease() {
  const info = {};
  try {
    const lines = fs.readFileSync("/etc/os-release", "utf8").split("\n");
    for (const line of lines) {
      const i = line.indexOf("=");
      if (i > 0) info[line.slice(0, i)] = line.slice(i + 1).replace(/"/g, "");
    }
  } catch {}
  return {
    name: info.NAME || "",
    version: info.VERSION_ID || "",
    pretty_name: info.PRETTY_NAME || "",
  };
}

function readProcesses(limit = 15) {
  const procs = [];
  try {
    for (const d of fs.readdirSync("/proc")) {
      if (!/^\d+$/.test(d)) continue;
      try {
        const name = fs.readFileSync(`/proc/${d}/comm`, "utf8").trim();
        let rss = 0;
        let state = "?";
        const status = fs.readFileSync(`/proc/${d}/status`, "utf8");
        for (const line of status.split("\n")) {
          if (line.startsWith("VmRSS:")) rss = parseInt(line.split(/\s+/)[1], 10);
          if (line.startsWith("State:")) state = line.split(/\s+/)[1];
        }
        procs.push({ pid: parseInt(d, 10), name, memory_mb: Math.round(rss / 1024 * 10) / 10, status: state });
      } catch {}
    }
  } catch {}
  procs.sort((a, b) => b.memory_mb - a.memory_mb);
  return procs.slice(0, limit);
}

// ---------------------------------------------------------------------------
// API endpoints
// ---------------------------------------------------------------------------

app.get("/api/stats", (req, res) => {
  res.json({
    timestamp: Math.floor(Date.now() / 1000),
    hostname: os.hostname(),
    kernel: os.release(),
    os: readOsRelease(),
    cpu: readCpu(),
    memory: readMemory(),
    load: readLoad(),
    uptime: readUptime(),
    disk: readDisk(),
    network: readNetwork(),
    temperature: readTemperature(),
  });
});

app.get("/api/processes", (req, res) => {
  res.json(readProcesses());
});

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

const DASHBOARD_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Avocado Device Dashboard</title>
<style>
  :root {
    --bg: #09090b; --surface: #18181b; --border: #27272a; --text: #fafafa;
    --muted: #a1a1aa; --green: #84cc16; --green-dim: #3f6212;
    --blue: #38bdf8; --purple: #a78bfa; --red: #f87171; --amber: #fbbf24;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: ui-monospace, "SF Mono", Menlo, monospace; background: var(--bg); color: var(--text); min-height: 100vh; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }

  header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  header h1 { font-size: 20px; font-weight: 600; }
  header h1 span { color: var(--green); }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 9999px; background: var(--green-dim); color: var(--green); font-weight: 500; }
  .meta { margin-left: auto; font-size: 12px; color: var(--muted); text-align: right; }

  .grid { display: grid; gap: 16px; margin-bottom: 16px; }
  .grid-3 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .grid-2 { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }

  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  .card-value { font-size: 28px; font-weight: 700; margin-bottom: 4px; }
  .card-sub { font-size: 12px; color: var(--muted); }

  .bar-track { width: 100%; height: 8px; background: var(--border); border-radius: 4px; margin: 10px 0; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width 0.6s ease; }
  .bar-green .bar-fill { background: var(--green); }
  .bar-blue .bar-fill { background: var(--blue); }
  .bar-purple .bar-fill { background: var(--purple); }

  .chart-wrap { margin-top: 12px; }
  .chart-wrap svg { width: 100%; height: 60px; display: block; }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: none; }

  .net-label { font-size: 11px; color: var(--muted); }
  .net-val { font-size: 14px; font-weight: 600; }

  .tabs { display: flex; gap: 4px; margin-bottom: 20px; }
  .tab { padding: 8px 16px; font-size: 13px; border: none; background: none; color: var(--muted); cursor: pointer; border-radius: 8px; font-family: inherit; }
  .tab.active { background: var(--surface); color: var(--text); }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1><span>avocado</span> device dashboard</h1>
    <span class="badge" id="live-badge">connecting</span>
    <div class="meta">
      <div id="hostname"></div>
      <div id="os-info"></div>
    </div>
  </header>

  <div class="tabs">
    <button class="tab active" data-tab="overview">Overview</button>
    <button class="tab" data-tab="processes">Processes</button>
  </div>

  <div id="tab-overview">
    <div class="grid grid-3" id="primary-cards"></div>
    <div class="grid grid-3" id="secondary-cards"></div>
    <div id="network-section"></div>
  </div>

  <div id="tab-processes" style="display:none">
    <div class="card">
      <div class="card-title">Processes (by memory)</div>
      <table>
        <thead><tr><th>PID</th><th>Name</th><th>Memory</th><th>Status</th></tr></thead>
        <tbody id="proc-body"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
(function() {
  var POLL_MS = 2000, HISTORY_MAX = 60;
  var cpuHistory = [], memHistory = [];
  var hasError = false;

  document.querySelectorAll(".tab").forEach(function(btn) {
    btn.addEventListener("click", function() {
      document.querySelectorAll(".tab").forEach(function(b) { b.classList.remove("active"); });
      btn.classList.add("active");
      document.getElementById("tab-overview").style.display = btn.dataset.tab === "overview" ? "" : "none";
      document.getElementById("tab-processes").style.display = btn.dataset.tab === "processes" ? "" : "none";
    });
  });

  function fmt(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
    return (bytes / 1073741824).toFixed(2) + " GB";
  }

  function bar(pct, color) {
    return '<div class="bar-track bar-' + color + '"><div class="bar-fill" style="width:' + pct + '%"></div></div>';
  }

  function chart(data, color) {
    if (data.length < 2) return "";
    var w = 400, h = 60;
    var step = w / (HISTORY_MAX - 1);
    var pts = data.map(function(v, i) {
      var x = (i + HISTORY_MAX - data.length) * step;
      var y = h - (v / 100) * h;
      return x + "," + y;
    });
    var area = "0," + h + " " + pts.join(" ") + " " + w + "," + h;
    return '<div class="chart-wrap"><svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polygon points="' + area + '" fill="' + color + '" opacity="0.15"/>' +
      '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + color + '" stroke-width="1.5"/>' +
      '</svg></div>';
  }

  function card(title, value, sub, extra) {
    return '<div class="card"><div class="card-title">' + title + '</div>' +
      '<div class="card-value">' + value + '</div>' +
      '<div class="card-sub">' + sub + '</div>' + (extra || "") + '</div>';
  }

  function renderStats(s) {
    document.getElementById("hostname").textContent = s.hostname;
    document.getElementById("os-info").textContent = s.os ? s.os.pretty_name : s.kernel;
    var badge = document.getElementById("live-badge");
    badge.textContent = "live"; badge.style.background = "var(--green-dim)"; badge.style.color = "var(--green)";

    cpuHistory.push(s.cpu.percent);
    if (cpuHistory.length > HISTORY_MAX) cpuHistory.shift();
    memHistory.push(s.memory.percent);
    if (memHistory.length > HISTORY_MAX) memHistory.shift();

    var html = "";
    html += card("CPU Usage", s.cpu.percent + "%", s.cpu.cores.length + " cores",
      bar(s.cpu.percent, "green") + chart(cpuHistory, "#84cc16"));
    html += card("Memory", s.memory.percent + "%", s.memory.used_mb + " / " + s.memory.total_mb + " MB",
      bar(s.memory.percent, "blue") + chart(memHistory, "#38bdf8"));
    if (s.disk) html += card("Disk (/var)", s.disk.percent + "%",
      s.disk.used_mb + " / " + s.disk.total_mb + " MB", bar(s.disk.percent, "purple"));
    document.getElementById("primary-cards").innerHTML = html;

    html = "";
    html += card("Load Average", s.load.load1.toFixed(2),
      "5m: " + s.load.load5.toFixed(2) + " &middot; 15m: " + s.load.load15.toFixed(2) +
      " &middot; " + s.load.running_processes + " running");
    html += card("Uptime", s.uptime.formatted, s.uptime.seconds.toLocaleString() + " seconds");
    html += s.temperature
      ? card("Temperature", s.temperature.celsius + " &deg;C", s.temperature.fahrenheit + " &deg;F")
      : card("Temperature", "&mdash;", "sensor unavailable");
    document.getElementById("secondary-cards").innerHTML = html;

    if (s.network && s.network.length) {
      html = '<div class="grid grid-2" style="margin-top:16px">';
      s.network.forEach(function(n) {
        html += '<div class="card"><div class="card-title">' + n.name + '</div>' +
          '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">' +
          '<div><div class="net-label">RX</div><div class="net-val">' + fmt(n.rx_bytes) + '</div></div>' +
          '<div><div class="net-label">TX</div><div class="net-val">' + fmt(n.tx_bytes) + '</div></div>' +
          '</div></div>';
      });
      html += '</div>';
      document.getElementById("network-section").innerHTML = html;
    }
  }

  function renderProcesses(procs) {
    document.getElementById("proc-body").innerHTML = procs.map(function(p) {
      return "<tr><td>" + p.pid + "</td><td>" + p.name + "</td><td>" +
        p.memory_mb + " MB</td><td>" + p.status + "</td></tr>";
    }).join("");
  }

  async function poll() {
    try {
      var [statsRes, procRes] = await Promise.all([fetch("/api/stats"), fetch("/api/processes")]);
      if (!statsRes.ok || !procRes.ok) throw new Error("bad response");
      renderStats(await statsRes.json());
      renderProcesses(await procRes.json());
      hasError = false;
    } catch (e) {
      if (!hasError) {
        var badge = document.getElementById("live-badge");
        badge.textContent = "offline"; badge.style.background = "#7f1d1d"; badge.style.color = "var(--red)";
        hasError = true;
      }
    }
    setTimeout(poll, POLL_MS);
  }

  poll();
})();
</script>
</body>
</html>`;

app.get("/", (req, res) => {
  res.type("html").send(DASHBOARD_HTML);
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

// Prime CPU stats so first request has data
readCpu();

app.listen(PORT, "0.0.0.0", () => {
  console.log("app starting");
  console.log("  device:", os.hostname());
  console.log("  dashboard: http://0.0.0.0:" + PORT);
});
