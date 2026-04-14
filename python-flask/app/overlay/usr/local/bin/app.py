#!/usr/bin/env python3

import sys
sys.path.insert(0, "/usr/lib/app/packages")

import json
import os
import time

from flask import Flask, jsonify, Response

app = Flask(__name__)

DEVICE_ID = os.uname().nodename


# ---------------------------------------------------------------------------
# System metrics (read from /proc and /sys)
# ---------------------------------------------------------------------------

def read_uptime():
    with open("/proc/uptime") as f:
        secs = float(f.read().split()[0])
    days = int(secs // 86400)
    hours = int((secs % 86400) // 3600)
    minutes = int((secs % 3600) // 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return {"seconds": int(secs), "formatted": " ".join(parts)}


def read_memory():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key = line.split(":")[0]
            if key in ("MemTotal", "MemFree", "MemAvailable", "Cached", "Buffers",
                        "SwapTotal", "SwapFree"):
                info[key] = int(line.split()[1])  # kB

    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    used = total - available
    return {
        "total_mb": total // 1024,
        "used_mb": used // 1024,
        "free_mb": info.get("MemFree", 0) // 1024,
        "available_mb": available // 1024,
        "cached_mb": info.get("Cached", 0) // 1024,
        "percent": round(used / total * 100, 1) if total else 0,
    }


_prev_cpu = None
_prev_cpu_time = 0


def read_cpu():
    global _prev_cpu, _prev_cpu_time

    with open("/proc/stat") as f:
        lines = f.readlines()

    def parse_cpu_line(line):
        parts = line.split()
        # user, nice, system, idle, iowait, irq, softirq, steal
        vals = list(map(int, parts[1:9]))
        total = sum(vals)
        idle = vals[3] + vals[4]  # idle + iowait
        return total, idle

    total, idle = parse_cpu_line(lines[0])

    # Per-core stats
    cores = []
    for line in lines[1:]:
        if not line.startswith("cpu"):
            break
        ct, ci = parse_cpu_line(line)
        cores.append((ct, ci))

    now = time.monotonic()
    percent = 0.0
    core_percents = [0.0] * len(cores)

    if _prev_cpu is not None:
        dt = total - _prev_cpu[0]
        di = idle - _prev_cpu[1]
        percent = round((1 - di / dt) * 100, 1) if dt else 0.0

        for i, (ct, ci) in enumerate(cores):
            pt, pi = _prev_cpu[2][i]
            cdt = ct - pt
            cdi = ci - pi
            core_percents[i] = round((1 - cdi / cdt) * 100, 1) if cdt else 0.0

    _prev_cpu = (total, idle, cores)
    _prev_cpu_time = now

    return {"percent": percent, "cores": core_percents}


def read_load():
    with open("/proc/loadavg") as f:
        parts = f.read().split()
    running, total_procs = parts[3].split("/")
    return {
        "load1": float(parts[0]),
        "load5": float(parts[1]),
        "load15": float(parts[2]),
        "running_processes": int(running),
    }


def read_disk():
    try:
        st = os.statvfs("/var")
        total = st.f_blocks * st.f_frsize
        free = st.f_bfree * st.f_frsize
        used = total - free
        return {
            "total_mb": total // (1024 * 1024),
            "used_mb": used // (1024 * 1024),
            "free_mb": free // (1024 * 1024),
            "percent": round(used / total * 100, 1) if total else 0,
        }
    except OSError:
        return None


def read_network():
    interfaces = []
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if ":" not in line:
                    continue
                parts = line.split()
                iface = parts[0].rstrip(":")
                if iface == "lo":
                    continue
                interfaces.append({
                    "name": iface,
                    "rx_bytes": int(parts[1]),
                    "rx_packets": int(parts[2]),
                    "tx_bytes": int(parts[9]),
                    "tx_packets": int(parts[10]),
                })
    except (OSError, IndexError, ValueError):
        pass
    return interfaces


def read_temperature():
    try:
        for zone in sorted(os.listdir("/sys/class/thermal")):
            temp_path = f"/sys/class/thermal/{zone}/temp"
            if os.path.exists(temp_path):
                with open(temp_path) as f:
                    c = int(f.read().strip()) / 1000.0
                    return {"celsius": round(c, 1), "fahrenheit": round(c * 9 / 5 + 32, 1)}
    except (OSError, ValueError):
        pass
    return None


def read_os_release():
    info = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
    except OSError:
        pass
    return {
        "name": info.get("NAME", ""),
        "version": info.get("VERSION_ID", ""),
        "pretty_name": info.get("PRETTY_NAME", ""),
    }


def read_processes(limit=15):
    procs = []
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            try:
                with open(f"/proc/{pid_dir}/comm") as f:
                    name = f.read().strip()
                rss = 0
                status_state = "unknown"
                with open(f"/proc/{pid_dir}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            rss = int(line.split()[1])  # kB
                        elif line.startswith("State:"):
                            status_state = line.split()[1]
                procs.append({
                    "pid": int(pid_dir),
                    "name": name,
                    "memory_mb": round(rss / 1024, 1),
                    "status": status_state,
                })
            except (OSError, IndexError, ValueError):
                continue
    except OSError:
        pass
    procs.sort(key=lambda p: p["memory_mb"], reverse=True)
    return procs[:limit]


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/stats")
def api_stats():
    return jsonify({
        "timestamp": int(time.time()),
        "hostname": DEVICE_ID,
        "kernel": os.uname().release,
        "os": read_os_release(),
        "cpu": read_cpu(),
        "memory": read_memory(),
        "load": read_load(),
        "uptime": read_uptime(),
        "disk": read_disk(),
        "network": read_network(),
        "temperature": read_temperature(),
    })


@app.route("/api/processes")
def api_processes():
    return jsonify(read_processes())


# ---------------------------------------------------------------------------
# Dashboard (single-page HTML served at /)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
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

  /* Header */
  header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  header h1 { font-size: 20px; font-weight: 600; }
  header h1 span { color: var(--green); }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 9999px; background: var(--green-dim); color: var(--green); font-weight: 500; }
  .meta { margin-left: auto; font-size: 12px; color: var(--muted); text-align: right; }

  /* Grid */
  .grid { display: grid; gap: 16px; margin-bottom: 16px; }
  .grid-3 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .grid-2 { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }

  /* Cards */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  .card-value { font-size: 28px; font-weight: 700; margin-bottom: 4px; }
  .card-sub { font-size: 12px; color: var(--muted); }

  /* Progress bar */
  .bar-track { width: 100%; height: 8px; background: var(--border); border-radius: 4px; margin: 10px 0; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width 0.6s ease; }
  .bar-green .bar-fill { background: var(--green); }
  .bar-blue .bar-fill { background: var(--blue); }
  .bar-purple .bar-fill { background: var(--purple); }

  /* Mini chart */
  .chart-wrap { margin-top: 12px; }
  .chart-wrap svg { width: 100%; height: 60px; display: block; }

  /* Table */
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: none; }

  /* Network */
  .net-label { font-size: 11px; color: var(--muted); }
  .net-val { font-size: 14px; font-weight: 600; }

  /* Tabs */
  .tabs { display: flex; gap: 4px; margin-bottom: 20px; }
  .tab { padding: 8px 16px; font-size: 13px; border: none; background: none; color: var(--muted); cursor: pointer; border-radius: 8px; font-family: inherit; }
  .tab.active { background: var(--surface); color: var(--text); }

  /* Error */
  .error { text-align: center; padding: 60px 20px; }
  .error h2 { color: var(--red); margin-bottom: 8px; }
  .error button { margin-top: 16px; padding: 8px 20px; background: var(--green); color: var(--bg); border: none; border-radius: 8px; cursor: pointer; font-family: inherit; font-weight: 600; }

  /* Loading */
  .loading { text-align: center; padding: 80px; color: var(--muted); }
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
  const POLL_MS = 2000;
  const HISTORY_MAX = 60;
  const cpuHistory = [];
  const memHistory = [];
  let error = false;

  // Tab switching
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
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

  function barHTML(percent, color) {
    return '<div class="bar-track bar-' + color + '"><div class="bar-fill" style="width:' + percent + '%"></div></div>';
  }

  function chartSVG(data, color) {
    if (data.length < 2) return "";
    const w = 400, h = 60, max = 100;
    const step = w / (HISTORY_MAX - 1);
    const pts = data.map((v, i) => {
      const x = (i + HISTORY_MAX - data.length) * step;
      const y = h - (v / max) * h;
      return x + "," + y;
    });
    const area = "0," + h + " " + pts.join(" ") + " " + w + "," + h;
    return '<div class="chart-wrap"><svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polygon points="' + area + '" fill="' + color + '" opacity="0.15"/>' +
      '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + color + '" stroke-width="1.5"/>' +
      '</svg></div>';
  }

  function card(title, value, sub, extra) {
    return '<div class="card"><div class="card-title">' + title + '</div>' +
      '<div class="card-value">' + value + '</div>' +
      '<div class="card-sub">' + sub + '</div>' +
      (extra || "") + '</div>';
  }

  function renderStats(s) {
    document.getElementById("hostname").textContent = s.hostname;
    document.getElementById("os-info").textContent = s.os ? s.os.pretty_name : s.kernel;
    const badge = document.getElementById("live-badge");
    badge.textContent = "live";
    badge.style.background = "var(--green-dim)";
    badge.style.color = "var(--green)";

    cpuHistory.push(s.cpu.percent);
    if (cpuHistory.length > HISTORY_MAX) cpuHistory.shift();
    memHistory.push(s.memory.percent);
    if (memHistory.length > HISTORY_MAX) memHistory.shift();

    // Primary cards: CPU, Memory, Disk
    let html = "";
    html += card("CPU Usage", s.cpu.percent + "%",
      s.cpu.cores.length + " cores",
      barHTML(s.cpu.percent, "green") + chartSVG(cpuHistory, "#84cc16"));
    html += card("Memory", s.memory.percent + "%",
      s.memory.used_mb + " / " + s.memory.total_mb + " MB",
      barHTML(s.memory.percent, "blue") + chartSVG(memHistory, "#38bdf8"));
    if (s.disk) {
      html += card("Disk (/var)", s.disk.percent + "%",
        s.disk.used_mb + " / " + s.disk.total_mb + " MB",
        barHTML(s.disk.percent, "purple"));
    }
    document.getElementById("primary-cards").innerHTML = html;

    // Secondary cards: Load, Uptime, Temperature
    html = "";
    html += card("Load Average",
      s.load.load1.toFixed(2),
      "5m: " + s.load.load5.toFixed(2) + " &middot; 15m: " + s.load.load15.toFixed(2) +
      " &middot; " + s.load.running_processes + " running");
    html += card("Uptime", s.uptime.formatted, s.uptime.seconds.toLocaleString() + " seconds");
    if (s.temperature) {
      html += card("Temperature", s.temperature.celsius + " &deg;C",
        s.temperature.fahrenheit + " &deg;F");
    } else {
      html += card("Temperature", "&mdash;", "sensor unavailable");
    }
    document.getElementById("secondary-cards").innerHTML = html;

    // Network interfaces
    if (s.network && s.network.length) {
      html = '<div class="grid grid-2" style="margin-top:16px">';
      s.network.forEach(n => {
        html += '<div class="card">' +
          '<div class="card-title">' + n.name + '</div>' +
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
    const tbody = document.getElementById("proc-body");
    tbody.innerHTML = procs.map(p =>
      "<tr><td>" + p.pid + "</td><td>" + p.name + "</td><td>" +
      p.memory_mb + " MB</td><td>" + p.status + "</td></tr>"
    ).join("");
  }

  function renderError(msg) {
    const badge = document.getElementById("live-badge");
    badge.textContent = "offline";
    badge.style.background = "#7f1d1d";
    badge.style.color = "var(--red)";
  }

  async function poll() {
    try {
      const [statsRes, procRes] = await Promise.all([
        fetch("/api/stats"),
        fetch("/api/processes"),
      ]);
      if (!statsRes.ok || !procRes.ok) throw new Error("bad response");
      const stats = await statsRes.json();
      const procs = await procRes.json();
      renderStats(stats);
      renderProcesses(procs);
      error = false;
    } catch (e) {
      if (!error) { renderError(e.message); error = true; }
    }
    setTimeout(poll, POLL_MS);
  }

  poll();
})();
</script>
</body>
</html>"""


@app.route("/")
def dashboard():
    return Response(DASHBOARD_HTML, content_type="text/html")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"app starting", flush=True)
    print(f"  device: {DEVICE_ID}", flush=True)
    print(f"  dashboard: http://0.0.0.0:5000", flush=True)

    # Prime CPU stats so first /api/stats call has data
    read_cpu()

    app.run(host="0.0.0.0", port=5000)
