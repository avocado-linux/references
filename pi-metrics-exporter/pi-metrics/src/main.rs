use std::fs;
use tiny_http::{Header, Response, Server};

fn read_cpu_temp() -> f64 {
    fs::read_to_string("/sys/class/thermal/thermal_zone0/temp")
        .unwrap_or_default()
        .trim()
        .parse::<f64>()
        .unwrap_or(0.0)
        / 1000.0
}

fn read_uptime() -> f64 {
    fs::read_to_string("/proc/uptime")
        .unwrap_or_default()
        .split_whitespace()
        .next()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.0)
}

fn read_meminfo(key: &str) -> u64 {
    fs::read_to_string("/proc/meminfo")
        .unwrap_or_default()
        .lines()
        .find(|line| line.starts_with(key))
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
}

fn read_loadavg() -> (String, String, String) {
    let content = fs::read_to_string("/proc/loadavg").unwrap_or_default();
    let mut parts = content.split_whitespace();
    let load1 = parts.next().unwrap_or("0.00").to_string();
    let load5 = parts.next().unwrap_or("0.00").to_string();
    let load15 = parts.next().unwrap_or("0.00").to_string();
    (load1, load5, load15)
}

fn prometheus_metrics() -> String {
    let cpu_temp = read_cpu_temp();
    let uptime = read_uptime();
    let mem_total_kb = read_meminfo("MemTotal:");
    let mem_available_kb = read_meminfo("MemAvailable:");
    let mem_free_kb = read_meminfo("MemFree:");
    let mem_buffers_kb = read_meminfo("Buffers:");
    let mem_cached_kb = read_meminfo("Cached:");
    let (load1, load5, load15) = read_loadavg();

    let mem_used_kb = mem_total_kb.saturating_sub(mem_available_kb);

    format!(
        "\
# HELP pi_cpu_temperature_celsius CPU temperature in degrees Celsius
# TYPE pi_cpu_temperature_celsius gauge
pi_cpu_temperature_celsius {cpu_temp:.1}
# HELP pi_memory_total_bytes Total memory in bytes
# TYPE pi_memory_total_bytes gauge
pi_memory_total_bytes {mem_total_bytes}
# HELP pi_memory_used_bytes Used memory in bytes
# TYPE pi_memory_used_bytes gauge
pi_memory_used_bytes {mem_used_bytes}
# HELP pi_memory_free_bytes Free memory in bytes
# TYPE pi_memory_free_bytes gauge
pi_memory_free_bytes {mem_free_bytes}
# HELP pi_memory_buffers_bytes Buffer memory in bytes
# TYPE pi_memory_buffers_bytes gauge
pi_memory_buffers_bytes {mem_buffers_bytes}
# HELP pi_memory_cached_bytes Cached memory in bytes
# TYPE pi_memory_cached_bytes gauge
pi_memory_cached_bytes {mem_cached_bytes}
# HELP pi_uptime_seconds System uptime in seconds
# TYPE pi_uptime_seconds gauge
pi_uptime_seconds {uptime:.1}
# HELP pi_load_average Load average
# TYPE pi_load_average gauge
pi_load_average{{interval=\"1m\"}} {load1}
pi_load_average{{interval=\"5m\"}} {load5}
pi_load_average{{interval=\"15m\"}} {load15}
",
        cpu_temp = cpu_temp,
        mem_total_bytes = mem_total_kb * 1024,
        mem_used_bytes = mem_used_kb * 1024,
        mem_free_bytes = mem_free_kb * 1024,
        mem_buffers_bytes = mem_buffers_kb * 1024,
        mem_cached_bytes = mem_cached_kb * 1024,
        uptime = uptime,
        load1 = load1,
        load5 = load5,
        load15 = load15,
    )
}

fn json_status() -> String {
    let cpu_temp = read_cpu_temp();
    let uptime = read_uptime();
    let mem_total_kb = read_meminfo("MemTotal:");
    let mem_available_kb = read_meminfo("MemAvailable:");
    let mem_free_kb = read_meminfo("MemFree:");
    let (load1, load5, load15) = read_loadavg();

    let mem_used_kb = mem_total_kb.saturating_sub(mem_available_kb);

    format!(
        concat!(
            "{{",
            "\"cpu_temperature_celsius\":{cpu_temp:.1},",
            "\"memory_total_bytes\":{mem_total},",
            "\"memory_used_bytes\":{mem_used},",
            "\"memory_free_bytes\":{mem_free},",
            "\"uptime_seconds\":{uptime:.1},",
            "\"load_average\":{{\"1m\":{load1},\"5m\":{load5},\"15m\":{load15}}}",
            "}}"
        ),
        cpu_temp = cpu_temp,
        mem_total = mem_total_kb * 1024,
        mem_used = mem_used_kb * 1024,
        mem_free = mem_free_kb * 1024,
        uptime = uptime,
        load1 = load1,
        load5 = load5,
        load15 = load15,
    )
}

fn main() {
    let server = Server::http("0.0.0.0:9100").expect("Failed to bind to 0.0.0.0:9100");
    eprintln!("Pi metrics exporter listening on 0.0.0.0:9100");

    for request in server.incoming_requests() {
        let (status, content_type, body) = match request.url() {
            "/metrics" => (
                200,
                "text/plain; version=0.0.4; charset=utf-8",
                prometheus_metrics(),
            ),
            "/healthz" => (200, "text/plain; charset=utf-8", "ok\n".to_string()),
            "/status" => (200, "application/json; charset=utf-8", json_status()),
            _ => (
                404,
                "text/plain; charset=utf-8",
                "not found\n".to_string(),
            ),
        };

        let response = Response::from_string(&body)
            .with_status_code(status)
            .with_header(
                Header::from_bytes(b"Content-Type", content_type.as_bytes()).unwrap(),
            );

        let _ = request.respond(response);
    }
}
