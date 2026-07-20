// Intel RealSense Web Visualizer
//
// Streams Color, Depth (colorized) and Infrared as MJPEG over HTTP, plus a
// small JSON API for device info and per-pixel distance measurement.
//
// This is a fully native Avocado build: it links the packaged librealsense2
// C++ SDK directly (no Python binding / pip wheel), serves over libmicrohttpd
// and encodes frames with libjpeg-turbo. Every dependency is an Avocado
// package resolved into the extension and SDK sysroot.

#include <librealsense2/rs.hpp>
#include <librealsense2/rsutil.h>
#include <microhttpd.h>
#include <jpeglib.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <csetjmp>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

// ---------------------------------------------------------------------------
// Shared frame state (single producer: capture thread; many consumers: feeds)
// ---------------------------------------------------------------------------

namespace {

struct Image {
    std::vector<uint8_t> data;
    int width = 0;
    int height = 0;
    int channels = 0;  // 3 = RGB, 1 = grayscale
    bool valid = false;
};

std::mutex g_lock;
Image g_color;
Image g_depth;  // colorized depth (RGB)
Image g_ir;
std::vector<uint16_t> g_depth_raw;
int g_depth_w = 0;
int g_depth_h = 0;
rs2_intrinsics g_intrin{};
bool g_intrin_valid = false;
float g_depth_scale = 0.001f;
std::string g_device_json = "{}";
uint64_t g_frame_seq = 0;  // bumped on each new frame set so feeds skip duplicates

std::atomic<bool> g_running{true};

// 15 fps keeps all three streams within USB 2.0 bandwidth. At 30 fps the depth
// frames silently freeze (duplicate data) on bus-limited hosts.
constexpr int kWidth = 640;
constexpr int kHeight = 480;
constexpr int kFps = 15;
constexpr int kPort = 5000;

// ---------------------------------------------------------------------------
// JPEG encoding (libjpeg-turbo, in-memory)
// ---------------------------------------------------------------------------

// libjpeg's default error_exit calls exit(); route fatals back here instead so
// a bad frame drops the JPEG rather than killing the whole server.
struct JpegErrorMgr {
    jpeg_error_mgr pub;
    jmp_buf setjmp_buffer;
};

void jpeg_on_error(j_common_ptr cinfo) {
    std::longjmp(reinterpret_cast<JpegErrorMgr*>(cinfo->err)->setjmp_buffer, 1);
}

std::string jpeg_encode(const uint8_t* data, int width, int height, int channels) {
    jpeg_compress_struct cinfo;
    JpegErrorMgr jerr;
    // volatile: jpeg_mem_dest/jpeg_finish_compress write these after the setjmp
    // recovery point, and a non-volatile automatic changed between setjmp and
    // longjmp is indeterminate after the longjmp (C11 7.13.2.1) — and we free
    // out in the recovery path, so a stale value there would be a bad free.
    unsigned char* volatile out = nullptr;
    unsigned long volatile out_size = 0;
    volatile bool created = false;

    // Wire the error handler, then establish the recovery point *before* any
    // libjpeg call that can error (including jpeg_create_compress itself), so a
    // longjmp always lands on an initialized buffer.
    cinfo.err = jpeg_std_error(&jerr.pub);
    jerr.pub.error_exit = jpeg_on_error;

    if (setjmp(jerr.setjmp_buffer)) {
        if (created) jpeg_destroy_compress(&cinfo);
        if (out != nullptr) free(out);
        return {};  // encode failed; caller treats an empty result as "no frame"
    }

    jpeg_create_compress(&cinfo);
    created = true;
    // Cast away volatile only to hand the addresses to libjpeg's C API; the
    // qualifier's job is to keep the values live across the setjmp/longjmp.
    jpeg_mem_dest(&cinfo, const_cast<unsigned char**>(&out),
                  const_cast<unsigned long*>(&out_size));

    cinfo.image_width = width;
    cinfo.image_height = height;
    cinfo.input_components = channels;
    cinfo.in_color_space = (channels == 1) ? JCS_GRAYSCALE : JCS_RGB;

    jpeg_set_defaults(&cinfo);
    jpeg_set_quality(&cinfo, 80, TRUE);
    jpeg_start_compress(&cinfo, TRUE);

    const int stride = width * channels;
    while (cinfo.next_scanline < cinfo.image_height) {
        JSAMPROW row = const_cast<JSAMPROW>(&data[cinfo.next_scanline * stride]);
        jpeg_write_scanlines(&cinfo, &row, 1);
    }

    jpeg_finish_compress(&cinfo);
    std::string result(reinterpret_cast<char*>(out), out_size);
    jpeg_destroy_compress(&cinfo);
    free(out);
    return result;
}

// Snapshot one stream's pixels under lock, then encode outside the lock.
// `seq` is set to the current frame sequence so callers can skip duplicates.
bool snapshot(const std::string& key, Image& out, uint64_t& seq) {
    std::lock_guard<std::mutex> guard(g_lock);
    seq = g_frame_seq;
    const Image* src = nullptr;
    if (key == "color") src = &g_color;
    else if (key == "depth") src = &g_depth;
    else if (key == "infrared") src = &g_ir;
    if (src == nullptr || !src->valid) return false;
    out = *src;
    return true;
}

std::string json_escape(const std::string& s) {
    std::string out;
    for (unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            default:
                if (c < 0x20) {
                    char u[8];
                    std::snprintf(u, sizeof(u), "\\u%04x", c);
                    out += u;
                } else {
                    out += static_cast<char>(c);
                }
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// RealSense capture loop
// ---------------------------------------------------------------------------

void capture_loop() {
    rs2::config cfg;
    cfg.enable_stream(RS2_STREAM_COLOR, kWidth, kHeight, RS2_FORMAT_RGB8, kFps);
    cfg.enable_stream(RS2_STREAM_DEPTH, kWidth, kHeight, RS2_FORMAT_Z16, kFps);
    cfg.enable_stream(RS2_STREAM_INFRARED, 1, kWidth, kHeight, RS2_FORMAT_Y8, kFps);

    // Mark all streams stale (so feeds/API stop serving a frame from a camera
    // that's gone) and back off before retrying. Shared by every catch below.
    auto recover = []() {
        {
            std::lock_guard<std::mutex> guard(g_lock);
            g_color.valid = false;
            g_depth.valid = false;
            g_ir.valid = false;
            g_intrin_valid = false;
        }
        for (int i = 0; i < 10 && g_running.load(); ++i)
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
    };

    // Outer loop: (re)start the pipeline and stream frames. librealsense throws
    // rs2::error on a hardware fault (e.g. USB unplug mid-stream); the per-frame
    // body also allocates ~1MB, which can throw std::bad_alloc under memory
    // pressure on constrained targets. Catching both here — rather than letting
    // either escape the thread and call std::terminate — keeps the HTTP server
    // up so it can reconnect when conditions recover.
    while (g_running.load()) {
        try {
            rs2::pipeline pipe;
            rs2::pipeline_profile profile = pipe.start(cfg);

            rs2::align aligner(RS2_STREAM_COLOR);
            rs2::colorizer colorizer;
            colorizer.set_option(RS2_OPTION_COLOR_SCHEME, 0);  // Jet

            rs2::device dev = profile.get_device();
            std::string name = dev.get_info(RS2_CAMERA_INFO_NAME);
            std::string serial = dev.get_info(RS2_CAMERA_INFO_SERIAL_NUMBER);
            std::string firmware = dev.get_info(RS2_CAMERA_INFO_FIRMWARE_VERSION);
            std::string usb = dev.supports(RS2_CAMERA_INFO_USB_TYPE_DESCRIPTOR)
                                  ? dev.get_info(RS2_CAMERA_INFO_USB_TYPE_DESCRIPTOR)
                                  : "N/A";

            rs2::depth_sensor depth_sensor = dev.first<rs2::depth_sensor>();
            float scale = depth_sensor.get_depth_scale();

            {
                std::lock_guard<std::mutex> guard(g_lock);
                g_depth_scale = scale;
                char scale_buf[32];
                std::snprintf(scale_buf, sizeof(scale_buf), "%g", scale);
                // Build with std::string (not a fixed buffer) so an unusually
                // long device string can never truncate the JSON.
                g_device_json = "{\"name\":\"" + json_escape(name) +
                                "\",\"serial\":\"" + json_escape(serial) +
                                "\",\"firmware\":\"" + json_escape(firmware) +
                                "\",\"usb\":\"" + json_escape(usb) +
                                "\",\"depth_scale\":" + scale_buf + "}";
            }

            std::printf("RealSense started: %s (S/N %s)\n", name.c_str(), serial.c_str());
            std::fflush(stdout);

            while (g_running.load()) {
                rs2::frameset frames;
                if (!pipe.try_wait_for_frames(&frames, 5000)) continue;

                rs2::frameset aligned = aligner.process(frames);
                rs2::video_frame color = aligned.get_color_frame();
                rs2::depth_frame depth = aligned.get_depth_frame();
                rs2::video_frame ir = frames.get_infrared_frame(1);

                if (!color || !depth) continue;

                rs2::video_frame colormap = colorizer.colorize(depth);

                const auto* color_px = static_cast<const uint8_t*>(color.get_data());
                const auto* depth_map_px = static_cast<const uint8_t*>(colormap.get_data());
                const auto* depth_raw_px = static_cast<const uint16_t*>(depth.get_data());
                const int dw = depth.get_width();
                const int dh = depth.get_height();

                rs2_intrinsics intrin =
                    depth.get_profile().as<rs2::video_stream_profile>().get_intrinsics();

                std::lock_guard<std::mutex> guard(g_lock);

                g_color.data.assign(color_px, color_px + color.get_width() * color.get_height() * 3);
                g_color.width = color.get_width();
                g_color.height = color.get_height();
                g_color.channels = 3;
                g_color.valid = true;

                g_depth.data.assign(depth_map_px,
                                    depth_map_px + colormap.get_width() * colormap.get_height() * 3);
                g_depth.width = colormap.get_width();
                g_depth.height = colormap.get_height();
                g_depth.channels = 3;
                g_depth.valid = true;

                if (ir) {
                    const auto* ir_px = static_cast<const uint8_t*>(ir.get_data());
                    g_ir.data.assign(ir_px, ir_px + ir.get_width() * ir.get_height());
                    g_ir.width = ir.get_width();
                    g_ir.height = ir.get_height();
                    g_ir.channels = 1;
                    g_ir.valid = true;
                }

                g_depth_raw.assign(depth_raw_px, depth_raw_px + dw * dh);
                g_depth_w = dw;
                g_depth_h = dh;
                g_intrin = intrin;
                g_intrin_valid = true;
                ++g_frame_seq;
            }
        } catch (const rs2::error& e) {
            std::fprintf(stderr, "RealSense error: %s - reconnecting\n", e.what());
            std::fflush(stderr);
            recover();
        } catch (const std::exception& e) {
            // e.g. std::bad_alloc from the per-frame buffers under memory
            // pressure — not an rs2::error, but must not escape the thread.
            std::fprintf(stderr, "Capture loop error: %s - reconnecting\n", e.what());
            std::fflush(stderr);
            recover();
        }
    }
}

// ---------------------------------------------------------------------------
// HTTP handlers
// ---------------------------------------------------------------------------

// Per-connection MJPEG state. The content reader is called repeatedly to fill
// MHD's buffer; we hold the current multipart chunk and hand it out in slices,
// fetching+encoding the next frame once the previous chunk is drained.
struct FeedState {
    std::string key;
    std::string chunk;
    size_t offset = 0;
    uint64_t last_seq = 0;  // sequence of the frame we last encoded
};

ssize_t feed_reader(void* cls, uint64_t /*pos*/, char* buf, size_t max) {
    auto* st = static_cast<FeedState*>(cls);

    // Returning 0 from an MHD content reader signals end-of-stream, so we must
    // never return 0 mid-stream: loop until we have bytes to hand out (or the
    // server is shutting down, in which case we end the stream cleanly).
    while (st->offset >= st->chunk.size()) {
        if (!g_running.load()) return MHD_CONTENT_READER_END_OF_STREAM;

        Image img;
        uint64_t seq = 0;
        // Only encode when a genuinely new frame is available; this paces the
        // feed to the capture rate instead of re-encoding the same frame. Poll
        // at half the frame interval so we pick up each new frame promptly.
        if (!snapshot(st->key, img, seq) || seq == st->last_seq) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1000 / (kFps * 2)));
            continue;  // no frame, or no new frame since last encode
        }
        st->last_seq = seq;

        std::string jpeg = jpeg_encode(img.data.data(), img.width, img.height, img.channels);
        if (jpeg.empty()) continue;  // encode failed; try the next frame

        st->chunk = "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                    std::to_string(jpeg.size()) + "\r\n\r\n" + jpeg + "\r\n";
        st->offset = 0;
    }

    const size_t n = std::min(max, st->chunk.size() - st->offset);
    std::memcpy(buf, st->chunk.data() + st->offset, n);
    st->offset += n;
    return static_cast<ssize_t>(n);
}

void feed_free(void* cls) { delete static_cast<FeedState*>(cls); }

MHD_Result send_buffer(struct MHD_Connection* conn, unsigned int status,
                       const std::string& body, const char* content_type) {
    struct MHD_Response* resp = MHD_create_response_from_buffer(
        body.size(), const_cast<char*>(body.data()), MHD_RESPMEM_MUST_COPY);
    if (resp == nullptr) return MHD_NO;
    MHD_add_response_header(resp, "Content-Type", content_type);
    MHD_add_response_header(resp, "Cache-Control", "no-cache, no-store, must-revalidate");
    MHD_Result ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

MHD_Result send_feed(struct MHD_Connection* conn, const std::string& key) {
    auto* st = new FeedState();
    st->key = key;
    struct MHD_Response* resp =
        MHD_create_response_from_callback(MHD_SIZE_UNKNOWN, 64 * 1024, &feed_reader, st, &feed_free);
    if (resp == nullptr) {
        delete st;  // MHD didn't take ownership, so feed_free won't run
        return MHD_NO;
    }
    MHD_add_response_header(resp, "Content-Type",
                            "multipart/x-mixed-replace; boundary=frame");
    MHD_add_response_header(resp, "Cache-Control", "no-cache, no-store, must-revalidate");
    MHD_Result ret = MHD_queue_response(conn, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);
    return ret;
}

// Fills `body` with a JSON response and returns the HTTP status to send.
unsigned int api_distance(struct MHD_Connection* conn, std::string& body) {
    const char* xs = MHD_lookup_connection_value(conn, MHD_GET_ARGUMENT_KIND, "x");
    const char* ys = MHD_lookup_connection_value(conn, MHD_GET_ARGUMENT_KIND, "y");
    if (xs == nullptr || ys == nullptr) {
        body = "{\"error\":\"x and y query params required\"}";
        return MHD_HTTP_BAD_REQUEST;
    }

    // Parse strictly: strtol lets us reject non-numeric input rather than
    // silently treating "foo" as 0 like atoi would.
    char* x_end = nullptr;
    char* y_end = nullptr;
    long xl = std::strtol(xs, &x_end, 10);
    long yl = std::strtol(ys, &y_end, 10);
    if (x_end == xs || *x_end != '\0' || y_end == ys || *y_end != '\0') {
        body = "{\"error\":\"x and y must be integers\"}";
        return MHD_HTTP_BAD_REQUEST;
    }
    // Reject out-of-int-range values before narrowing so the cast stays
    // well-defined (long is wider than int on 64-bit targets).
    if (xl < std::numeric_limits<int>::min() || xl > std::numeric_limits<int>::max() ||
        yl < std::numeric_limits<int>::min() || yl > std::numeric_limits<int>::max()) {
        body = "{\"error\":\"x and y out of range\"}";
        return MHD_HTTP_BAD_REQUEST;
    }
    int x = static_cast<int>(xl);
    int y = static_cast<int>(yl);

    std::lock_guard<std::mutex> guard(g_lock);
    if (!g_intrin_valid || g_depth_raw.empty()) {
        body = "{\"error\":\"no depth data available\"}";
        return MHD_HTTP_SERVICE_UNAVAILABLE;
    }

    // Clamp against the raw buffer's own dimensions (which back the index
    // below), not the intrinsics, so the read stays in bounds even if the two
    // ever diverge.
    x = std::max(0, std::min(x, g_depth_w - 1));
    y = std::max(0, std::min(y, g_depth_h - 1));

    float distance = static_cast<float>(g_depth_raw[y * g_depth_w + x]) * g_depth_scale;
    float pixel[2] = {static_cast<float>(x), static_cast<float>(y)};
    float point[3] = {0, 0, 0};
    rs2_deproject_pixel_to_point(point, &g_intrin, pixel, distance);

    char buf[256];
    std::snprintf(buf, sizeof(buf),
                  "{\"x\":%d,\"y\":%d,\"distance_m\":%.3f,"
                  "\"point_3d\":[%.4f,%.4f,%.4f]}",
                  x, y, distance, point[0], point[1], point[2]);
    body = buf;
    return MHD_HTTP_OK;
}

std::string api_stream_info() {
    std::lock_guard<std::mutex> guard(g_lock);
    int w = g_intrin_valid ? g_intrin.width : kWidth;
    int h = g_intrin_valid ? g_intrin.height : kHeight;
    return "{\"width\":" + std::to_string(w) + ",\"height\":" + std::to_string(h) + "}";
}

const char kDashboardHtml[] = R"HTML(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RealSense Visualizer</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0b0d11;--card:#13161d;--card2:#191c25;--border:#252835;
  --text:#e2e5ef;--muted:#7a7f95;--accent:#4a9eff;--accent2:#7c4dff;
  --green:#22c55e;--orange:#f59e0b;--red:#ef4444;
}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}

header{background:var(--card);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;gap:14px}
header h1{font-size:18px;font-weight:700;letter-spacing:-.3px}
.badge{font-size:10px;padding:3px 10px;border-radius:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.badge-live{background:var(--green);color:#fff}
.badge-err{background:var(--red);color:#fff}

.device-bar{background:var(--card);border-bottom:1px solid var(--border);padding:8px 24px;display:flex;gap:24px;font-size:12px;color:var(--muted);flex-wrap:wrap}
.device-bar b{color:var(--text);font-weight:600}

.toggle-bar{background:var(--card2);border-bottom:1px solid var(--border);padding:10px 24px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.toggle-bar .label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-right:8px;font-weight:600}
.tbtn{
  border:1px solid var(--border);background:transparent;color:var(--muted);
  font-size:12px;font-weight:600;padding:6px 16px;border-radius:6px;cursor:pointer;
  transition:all .15s ease;display:flex;align-items:center;gap:6px;
}
.tbtn:hover{border-color:var(--accent);color:var(--text)}
.tbtn.active{background:var(--accent);border-color:var(--accent);color:#fff}
.tbtn .dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot-color{background:var(--green)}.dot-depth{background:var(--accent)}.dot-ir{background:var(--orange)}.dot-dist{background:var(--red)}

.grid{display:grid;gap:14px;padding:14px 24px;max-width:1600px;margin:0 auto;transition:all .2s ease}
.grid.cols-1{grid-template-columns:1fr}
.grid.cols-2{grid-template-columns:1fr 1fr}
.grid.cols-3{grid-template-columns:1fr 1fr 1fr}

.panel{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden;display:none}
.panel.visible{display:block}
.panel-head{padding:8px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:7px}
.panel img{width:100%;display:block;cursor:crosshair;background:#000;aspect-ratio:4/3;object-fit:contain}

.measure-bar{
  background:var(--card);border-bottom:1px solid var(--border);
  padding:12px 24px;display:none;align-items:center;gap:28px;
}
.measure-bar.visible{display:flex}
.measure-bar .ml{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}
.measure-bar .mv{font-size:32px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--accent);min-width:130px;line-height:1.1}
.measure-bar .mc{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.measure-bar .m3{color:var(--muted);font-size:13px;font-family:'SF Mono',SFMono-Regular,Consolas,monospace}
.measure-hint{color:var(--muted);font-size:11px;margin-left:auto;opacity:.7}

@media(max-width:900px){.grid{grid-template-columns:1fr!important}}
</style>
</head>
<body>

<header>
  <h1>RealSense Visualizer</h1>
  <div class="badge badge-err" id="status">CONNECTING</div>
</header>

<div class="device-bar" id="deviceBar">Waiting for camera&hellip;</div>

<div class="toggle-bar">
  <span class="label">Views</span>
  <button class="tbtn active" data-panel="color"   onclick="toggle('color')">  <span class="dot dot-color"></span>Color</button>
  <button class="tbtn active" data-panel="depth"   onclick="toggle('depth')">  <span class="dot dot-depth"></span>Depth</button>
  <button class="tbtn active" data-panel="ir"      onclick="toggle('ir')">     <span class="dot dot-ir"></span>Infrared</button>
  <button class="tbtn active" data-panel="dist"    onclick="toggle('dist')">   <span class="dot dot-dist"></span>Distance</button>
</div>

<div class="measure-bar visible" id="p-dist">
  <div>
    <div class="ml">Distance</div>
    <div class="mv" id="distVal">&mdash;</div>
  </div>
  <div>
    <div class="ml">Pixel</div>
    <div class="mc" id="distCoords">&mdash;</div>
  </div>
  <div>
    <div class="ml">3D Point (m)</div>
    <div class="m3" id="dist3d">&mdash;</div>
  </div>
  <div class="measure-hint">Click any feed to measure depth</div>
</div>

<div class="grid cols-3" id="grid">

  <div class="panel visible" id="p-color">
    <div class="panel-head"><span class="dot dot-color"></span>Color Stream</div>
    <img data-src="/feed/color" src="/feed/color" alt="Color" onclick="measure(event,this)">
  </div>

  <div class="panel visible" id="p-depth">
    <div class="panel-head"><span class="dot dot-depth"></span>Depth Colormap</div>
    <img data-src="/feed/depth" src="/feed/depth" alt="Depth" onclick="measure(event,this)">
  </div>

  <div class="panel visible" id="p-ir">
    <div class="panel-head"><span class="dot dot-ir"></span>Infrared</div>
    <img data-src="/feed/infrared" src="/feed/infrared" alt="Infrared" onclick="measure(event,this)">
  </div>

</div>

<script>
const panels = ['color','depth','ir','dist'];
const state  = {};
panels.forEach(p => state[p] = true);

let streamW = 640, streamH = 480;

function toggle(id) {
  state[id] = !state[id];

  document.querySelector('[data-panel="'+id+'"]').classList.toggle('active', state[id]);
  var el = document.getElementById('p-'+id);
  el.classList.toggle('visible', state[id]);

  if (id !== 'dist') {
    var img = el.querySelector('img');
    if (state[id]) {
      img.src = img.dataset.src;
    } else {
      img.src = '';
    }
  }

  reflow();
}

function reflow() {
  var visible = ['color','depth','ir'].filter(k => state[k]).length;
  var g = document.getElementById('grid');
  g.classList.remove('cols-1','cols-2','cols-3');
  if (visible <= 1)      g.classList.add('cols-1');
  else if (visible <= 2) g.classList.add('cols-2');
  else                   g.classList.add('cols-3');
}

async function loadDevice() {
  try {
    var r = await fetch('/api/device');
    var d = await r.json();
    var bar = document.getElementById('deviceBar');
    bar.textContent = '';
    var fields = [
      ['Camera: ', d.name],
      ['Serial: ', d.serial],
      ['FW: ', d.firmware],
      ['USB: ', d.usb],
      ['Depth scale: ', String(d.depth_scale)]
    ];
    // Use textContent (not innerHTML) so device-reported strings can never be
    // interpreted as HTML.
    fields.forEach(function(f, i) {
      if (i > 0) bar.appendChild(document.createTextNode('  |  '));
      bar.appendChild(document.createTextNode(f[0]));
      var b = document.createElement('b');
      b.textContent = (f[1] == null) ? '' : f[1];
      bar.appendChild(b);
    });
    var s = document.getElementById('status');
    s.textContent = 'LIVE';
    s.className = 'badge badge-live';
  } catch(e) {
    var s = document.getElementById('status');
    s.textContent = 'ERROR';
    s.className = 'badge badge-err';
  }
}

async function loadStreamInfo() {
  try {
    var r = await fetch('/api/stream_info');
    var d = await r.json();
    streamW = d.width;
    streamH = d.height;
  } catch(e) {}
}

async function measure(ev, img) {
  if (!state.dist) return;
  var rect = img.getBoundingClientRect();
  var x = Math.round((ev.clientX - rect.left) * (streamW / rect.width));
  var y = Math.round((ev.clientY - rect.top)  * (streamH / rect.height));
  try {
    var r = await fetch('/api/distance?x='+x+'&y='+y);
    var d = await r.json();
    if (d.error) return;
    var dist = d.distance_m;
    document.getElementById('distVal').textContent =
      dist < 1 ? (dist*100).toFixed(1)+' cm' : dist.toFixed(3)+' m';
    document.getElementById('distCoords').textContent = '('+d.x+', '+d.y+')';
    document.getElementById('dist3d').textContent =
      'X='+d.point_3d[0]+'  Y='+d.point_3d[1]+'  Z='+d.point_3d[2];
  } catch(e){}
}

loadDevice();
loadStreamInfo();
</script>
</body>
</html>)HTML";

MHD_Result handle_request(void* /*cls*/, struct MHD_Connection* conn, const char* url,
                          const char* method, const char* /*version*/,
                          const char* /*upload_data*/, size_t* /*upload_data_size*/,
                          void** /*con_cls*/) {
    if (std::strcmp(method, "GET") != 0) {
        return send_buffer(conn, MHD_HTTP_METHOD_NOT_ALLOWED, "method not allowed", "text/plain");
    }

    const std::string path = url;

    if (path == "/") {
        // kDashboardHtml has static storage, so serve it as a persistent buffer
        // (no per-request allocation or copy of the whole page).
        struct MHD_Response* resp = MHD_create_response_from_buffer(
            sizeof(kDashboardHtml) - 1, const_cast<char*>(kDashboardHtml),
            MHD_RESPMEM_PERSISTENT);
        if (resp == nullptr) return MHD_NO;
        MHD_add_response_header(resp, "Content-Type", "text/html");
        MHD_Result ret = MHD_queue_response(conn, MHD_HTTP_OK, resp);
        MHD_destroy_response(resp);
        return ret;
    }
    if (path == "/feed/color") return send_feed(conn, "color");
    if (path == "/feed/depth") return send_feed(conn, "depth");
    if (path == "/feed/infrared") return send_feed(conn, "infrared");

    if (path == "/api/device") {
        std::lock_guard<std::mutex> guard(g_lock);
        return send_buffer(conn, MHD_HTTP_OK, g_device_json, "application/json");
    }
    if (path == "/api/stream_info") {
        return send_buffer(conn, MHD_HTTP_OK, api_stream_info(), "application/json");
    }
    if (path == "/api/distance") {
        std::string body;
        unsigned int status = api_distance(conn, body);
        return send_buffer(conn, status, body, "application/json");
    }

    return send_buffer(conn, MHD_HTTP_NOT_FOUND, "not found", "text/plain");
}

void on_signal(int /*sig*/) { g_running.store(false); }

}  // namespace

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

int main() {
    std::printf("RealSense Visualizer starting...\n");
    std::fflush(stdout);

    // Clear g_running on SIGTERM (systemd stop) / SIGINT so the capture loop
    // exits and we shut down cleanly. Writing an atomic flag is signal-safe.
    std::signal(SIGTERM, on_signal);
    std::signal(SIGINT, on_signal);

    // Start the HTTP server first so the dashboard is reachable while we wait
    // for the camera to appear.
    struct MHD_Daemon* daemon = MHD_start_daemon(
        MHD_USE_THREAD_PER_CONNECTION | MHD_USE_INTERNAL_POLLING_THREAD, kPort, nullptr,
        nullptr, &handle_request, nullptr, MHD_OPTION_END);

    if (daemon == nullptr) {
        std::fprintf(stderr, "Failed to start HTTP server on port %d\n", kPort);
        return 1;
    }

    std::printf("  Dashboard: http://0.0.0.0:%d\n", kPort);
    std::fflush(stdout);

    // Camera init + capture happen in the worker thread so the HTTP server
    // stays up even before the camera is connected.
    std::thread worker(capture_loop);

    worker.join();  // runs until g_running is cleared (service stop / signal)
    MHD_stop_daemon(daemon);
    return 0;
}
