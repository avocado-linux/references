// rzv2n-drpai-yolo
//
// Object-detection demo for the SolidRun RZ/V2N HummingBoard. Pulls frames
// from either a video file (default, looping on EOS) or the on-board IMX678
// MIPI CSI-2 camera, runs YOLOv3 (Darknet/COCO) inference on the on-chip
// DRP-AI3 accelerator using Renesas's RZ/V2N AI SDK v6.30 prebuilt model,
// and renders the annotated feed full-screen on Wayland/Weston.
//
// The IMX678 path is currently broken upstream: the rzg2l-cru driver
// misreports its V4L2 format for 4K (claims 3840x2160 8-bit RGGB, actually
// streams 1920x2160 12-bit-in-16-bit-BE Bayer at half the advertised
// horizontal resolution). Frames come out as orange/cyan vertical stripes.
// Until the driver is fixed, the demo defaults to a looping video file —
// set VIDEO_PATH="" and CAMERA_DEVICE=/dev/video0 to flip back.
//
// Why YOLOv3 (not YOLOX-S): the only TVM-compiled object-detection bundle
// Renesas publishes for V2N is YOLOv3 — see fetch-model.sh.

#include "yolov3.h"

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <tuple>
#include <vector>

#include <gst/app/gstappsink.h>
#include <gst/app/gstappsrc.h>
#include <gst/gst.h>

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

#include "MeraDrpRuntimeWrapper.h"

namespace {

struct Config {
    // VIDEO_PATH=/path/to/file.mp4 picks file mode (default). Set to empty
    // string and configure CAMERA_DEVICE to use the IMX678 camera.
    std::string video_path   = "/usr/lib/rzv2n-drpai-yolo/sample.mp4";
    std::string device       = "/dev/video0";
    int width                = 1920;
    int height               = 1080;
    int framerate            = 30;
    std::string model_dir    = "/usr/lib/rzv2n-drpai-yolo/model/yolov3";
    std::string labels_path  = "/usr/lib/rzv2n-drpai-yolo/labels.txt";
    float confidence         = 0.5f;
    float nms                = 0.5f;
    // DRP-AI reserved-region physical start address. SolidRun rzv2n DTSI
    // puts `drp_reserved` at 0xD0000000. Override via env DRP_START_ADDR.
    uint64_t drp_start_addr  = 0xD0000000ULL;
};

Config load_config() {
    Config c;
    auto env = [](const char* k, const char* dflt) {
        const char* v = std::getenv(k);
        return v ? std::string(v) : std::string(dflt);
    };
    c.video_path  = env("VIDEO_PATH", c.video_path.c_str());
    c.device      = env("CAMERA_DEVICE", c.device.c_str());
    c.width       = std::stoi(env("WIDTH", std::to_string(c.width).c_str()));
    c.height      = std::stoi(env("HEIGHT", std::to_string(c.height).c_str()));
    c.framerate   = std::stoi(env("FRAMERATE", std::to_string(c.framerate).c_str()));
    c.model_dir   = env("MODEL_DIR", c.model_dir.c_str());
    c.labels_path = env("LABELS_PATH", c.labels_path.c_str());
    c.confidence  = std::stof(env("CONFIDENCE_THRESHOLD", std::to_string(c.confidence).c_str()));
    c.nms         = std::stof(env("NMS_THRESHOLD", std::to_string(c.nms).c_str()));
    if (const char* v = std::getenv("DRP_START_ADDR")) {
        c.drp_start_addr = std::strtoull(v, nullptr, 0);
    }
    return c;
}

std::atomic<bool> g_running{true};

void on_signal(int) { g_running = false; }

// IEEE-754 half (binary16) to float (binary32). The V2N TVM YOLOv3 model
// emits FP16 outputs.
inline float fp16_to_float(uint16_t h) {
    const uint32_t sign = (uint32_t)(h & 0x8000u) << 16;
    const uint32_t exp  = (h >> 10) & 0x1Fu;
    const uint32_t mant = h & 0x3FFu;
    uint32_t f;
    if (exp == 0) {
        if (mant == 0) {
            f = sign;
        } else {
            uint32_t m = mant;
            int e = -1;
            do { m <<= 1; e--; } while ((m & 0x400u) == 0);
            f = sign | ((127u + e) << 23) | ((m & 0x3FFu) << 13);
        }
    } else if (exp == 0x1F) {
        f = sign | 0x7F800000u | (mant << 13);
    } else {
        f = sign | ((exp + 112u) << 23) | (mant << 13);
    }
    float out;
    std::memcpy(&out, &f, sizeof(out));
    return out;
}

struct Letterbox {
    cv::Mat resized;
    float scale;
    int dx;
    int dy;
};

Letterbox letterbox(const cv::Mat& src, int size) {
    Letterbox lb;
    const float r = std::min(size / static_cast<float>(src.cols),
                             size / static_cast<float>(src.rows));
    const int new_w = static_cast<int>(src.cols * r);
    const int new_h = static_cast<int>(src.rows * r);
    lb.scale = r;
    lb.dx = (size - new_w) / 2;
    lb.dy = (size - new_h) / 2;

    cv::Mat resized;
    cv::resize(src, resized, cv::Size(new_w, new_h), 0, 0, cv::INTER_LINEAR);
    lb.resized = cv::Mat(size, size, src.type(), cv::Scalar(114, 114, 114));
    resized.copyTo(lb.resized(cv::Rect(lb.dx, lb.dy, new_w, new_h)));
    return lb;
}

// BGR uint8 → RGB float32 NCHW, scaled to 0..1. Matches Darknet YOLOv3 +
// the V2N TVM bundle's preprocess (RGB / 255).
void to_chw_rgb_float32(const cv::Mat& src_bgr, float* dst, int size) {
    const int hw = size * size;
    const float scale = 1.0f / 255.0f;
    for (int y = 0; y < size; ++y) {
        const cv::Vec3b* row = src_bgr.ptr<cv::Vec3b>(y);
        for (int x = 0; x < size; ++x) {
            dst[0 * hw + y * size + x] = row[x][2] * scale;  // R
            dst[1 * hw + y * size + x] = row[x][1] * scale;  // G
            dst[2 * hw + y * size + x] = row[x][0] * scale;  // B
        }
    }
}

void draw_boxes(cv::Mat& frame,
                const std::vector<Detection>& dets,
                const std::vector<std::string>& labels) {
    for (const auto& d : dets) {
        cv::rectangle(frame, d.box, cv::Scalar(0, 255, 0), 2);
        const std::string text =
            (d.class_id < static_cast<int>(labels.size()) ? labels[d.class_id]
                                                          : std::to_string(d.class_id)) +
            " " + cv::format("%.0f%%", d.confidence * 100);
        int baseline = 0;
        const cv::Size sz = cv::getTextSize(text, cv::FONT_HERSHEY_SIMPLEX,
                                            0.5, 1, &baseline);
        cv::rectangle(frame,
                      cv::Point(d.box.x, d.box.y - sz.height - 6),
                      cv::Point(d.box.x + sz.width, d.box.y),
                      cv::Scalar(0, 255, 0), cv::FILLED);
        cv::putText(frame, text, cv::Point(d.box.x, d.box.y - 4),
                    cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(0, 0, 0), 1);
    }
}

// Source pipelines normalize whatever the input gives us (any container /
// codec via decodebin, or raw Bayer from v4l2) into BGR at (cfg.width x
// cfg.height x cfg.framerate) so the rest of the loop sees a single shape.
GstElement* build_capture_pipeline(const Config& c, GError** err) {
    std::string desc;
    if (!c.video_path.empty()) {
        desc =
            "filesrc location=" + c.video_path + ""
            " ! decodebin"
            " ! videoconvert"
            " ! videoscale"
            " ! videorate"
            " ! video/x-raw,format=BGR,width=" + std::to_string(c.width) +
            ",height=" + std::to_string(c.height) +
            ",framerate=" + std::to_string(c.framerate) + "/1"
            " ! appsink name=sink emit-signals=true sync=false drop=true max-buffers=2";
    } else {
        desc =
            "v4l2src device=" + c.device + " io-mode=mmap"
            " ! video/x-bayer,format=rggb,width=" + std::to_string(c.width) +
            ",height=" + std::to_string(c.height) +
            ",framerate=" + std::to_string(c.framerate) + "/1"
            " ! bayer2rgb"
            " ! videoconvert"
            " ! video/x-raw,format=BGR"
            " ! appsink name=sink emit-signals=true sync=false drop=true max-buffers=2";
    }
    return gst_parse_launch(desc.c_str(), err);
}

GstElement* build_display_pipeline(const Config& c, GError** err) {
    const std::string desc =
        "appsrc name=src is-live=true format=time"
        " caps=video/x-raw,format=BGR,width=" + std::to_string(c.width) +
        ",height=" + std::to_string(c.height) +
        ",framerate=" + std::to_string(c.framerate) + "/1"
        " ! videoconvert"
        " ! waylandsink fullscreen=true sync=false";
    return gst_parse_launch(desc.c_str(), err);
}

bool collect_output(MeraDrpRuntimeWrapper& runtime, std::vector<float>& buf) {
    const int n = runtime.GetNumOutput();
    if (n <= 0) return false;
    size_t total = 0;
    std::vector<std::tuple<InOutDataType, void*, int64_t>> chunks;
    chunks.reserve(n);
    for (int i = 0; i < n; ++i) {
        auto t = runtime.GetOutput(i);
        chunks.push_back(t);
        total += static_cast<size_t>(std::get<2>(t));
    }
    buf.resize(total);
    size_t offset = 0;
    for (const auto& [type, data, sz] : chunks) {
        const int64_t count = sz;
        if (type == InOutDataType::FLOAT32) {
            std::memcpy(buf.data() + offset, data, count * sizeof(float));
        } else if (type == InOutDataType::FLOAT16) {
            const uint16_t* p = static_cast<const uint16_t*>(data);
            for (int64_t j = 0; j < count; ++j) {
                buf[offset + j] = fp16_to_float(p[j]);
            }
        } else {
            g_printerr("ERROR: unsupported output dtype\n");
            return false;
        }
        offset += count;
    }
    return true;
}

// Bus watch: on EOS from the capture pipeline (i.e. the video file ended),
// seek back to position 0 so the demo loops indefinitely. No-op for the
// camera pipeline (live sources don't reach EOS).
gboolean on_capture_bus_message(GstBus* /*bus*/, GstMessage* msg, gpointer data) {
    GstElement* capture = static_cast<GstElement*>(data);
    if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_EOS) {
        gst_element_seek_simple(
            capture, GST_FORMAT_TIME,
            static_cast<GstSeekFlags>(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_KEY_UNIT),
            0);
    } else if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ERROR) {
        GError* err = nullptr;
        gchar* dbg = nullptr;
        gst_message_parse_error(msg, &err, &dbg);
        g_printerr("capture pipeline ERROR: %s (%s)\n",
                   err ? err->message : "?", dbg ? dbg : "");
        if (err) g_error_free(err);
        g_free(dbg);
        g_running = false;
    }
    return TRUE;
}

}  // namespace

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;

    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    const Config cfg = load_config();
    g_print("rzv2n-drpai-yolo starting\n");
    if (!cfg.video_path.empty()) {
        g_print("  source: video file %s\n", cfg.video_path.c_str());
    } else {
        g_print("  source: camera %s (%dx%d@%dfps RGGB)\n",
                cfg.device.c_str(), cfg.width, cfg.height, cfg.framerate);
    }
    g_print("  model: %s\n", cfg.model_dir.c_str());
    g_print("  drp_start_addr: 0x%lx\n",
            static_cast<unsigned long>(cfg.drp_start_addr));

    const auto labels = load_labels(cfg.labels_path);
    if (labels.empty()) {
        g_printerr("WARNING: no labels loaded from %s — using numeric IDs\n",
                   cfg.labels_path.c_str());
    }

    MeraDrpRuntimeWrapper runtime;
    if (!runtime.LoadModel(cfg.model_dir, cfg.drp_start_addr)) {
        g_printerr("ERROR: failed to load DRP-AI model from %s\n",
                   cfg.model_dir.c_str());
        return 1;
    }
    g_print("  model loaded — outputs=%d\n", runtime.GetNumOutput());

    const int input_elems = 3 * YOLOV3_INPUT_SIZE * YOLOV3_INPUT_SIZE;
    std::vector<float> input_buf(input_elems);
    std::vector<float> output_buf;

    gst_init(nullptr, nullptr);

    GError* err = nullptr;
    GstElement* capture = build_capture_pipeline(cfg, &err);
    if (!capture) {
        g_printerr("ERROR: capture pipeline build failed: %s\n",
                   err ? err->message : "unknown");
        if (err) g_error_free(err);
        return 1;
    }
    err = nullptr;
    GstElement* display = build_display_pipeline(cfg, &err);
    if (!display) {
        g_printerr("ERROR: display pipeline build failed: %s\n",
                   err ? err->message : "unknown");
        if (err) g_error_free(err);
        gst_object_unref(capture);
        return 1;
    }

    GstAppSink* sink = GST_APP_SINK(gst_bin_get_by_name(GST_BIN(capture), "sink"));
    GstAppSrc* src = GST_APP_SRC(gst_bin_get_by_name(GST_BIN(display), "src"));

    // Bus watch for EOS-loop / error reporting.
    GstBus* bus = gst_element_get_bus(capture);
    gst_bus_add_watch(bus, on_capture_bus_message, capture);
    gst_object_unref(bus);

    if (gst_element_set_state(capture, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE ||
        gst_element_set_state(display, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        g_printerr("ERROR: failed to start GStreamer pipelines\n");
        return 1;
    }
    g_print("  pipelines running\n");

    using clock = std::chrono::steady_clock;
    auto last_log = clock::now();
    int frames = 0;
    double infer_ms_total = 0.0;
    int infer_count = 0;

    // Pump the GLib main context periodically so bus messages (EOS, errors)
    // get dispatched to our watch without a separate thread.
    GMainContext* ctx = g_main_context_default();

    while (g_running) {
        while (g_main_context_iteration(ctx, FALSE)) { /* drain */ }

        GstSample* sample = gst_app_sink_try_pull_sample(sink, 100 * GST_MSECOND);
        if (!sample) continue;

        GstBuffer* buf = gst_sample_get_buffer(sample);
        GstMapInfo map;
        if (!gst_buffer_map(buf, &map, GST_MAP_READ)) {
            gst_sample_unref(sample);
            continue;
        }

        cv::Mat frame(cfg.height, cfg.width, CV_8UC3, map.data);

        Letterbox lb = letterbox(frame, YOLOV3_INPUT_SIZE);
        to_chw_rgb_float32(lb.resized, input_buf.data(), YOLOV3_INPUT_SIZE);

        const auto t0 = clock::now();
        runtime.SetInput(0, input_buf.data());
        runtime.Run();
        if (!collect_output(runtime, output_buf)) {
            gst_buffer_unmap(buf, &map);
            gst_sample_unref(sample);
            continue;
        }
        const double infer_ms =
            std::chrono::duration<double, std::milli>(clock::now() - t0).count();
        infer_ms_total += infer_ms;
        ++infer_count;

        const auto detections = decode_yolov3(
            output_buf.data(), cfg.width, cfg.height,
            cfg.confidence, cfg.nms,
            lb.scale, lb.dx, lb.dy);

        cv::Mat annotated = frame.clone();
        gst_buffer_unmap(buf, &map);
        gst_sample_unref(sample);
        draw_boxes(annotated, detections, labels);

        const gsize bytes = annotated.total() * annotated.elemSize();
        GstBuffer* out_buf = gst_buffer_new_allocate(nullptr, bytes, nullptr);
        gst_buffer_fill(out_buf, 0, annotated.data, bytes);
        GST_BUFFER_PTS(out_buf) = gst_util_uint64_scale(
            frames, GST_SECOND, cfg.framerate);
        GST_BUFFER_DURATION(out_buf) =
            gst_util_uint64_scale(1, GST_SECOND, cfg.framerate);
        const GstFlowReturn fr = gst_app_src_push_buffer(src, out_buf);
        if (fr != GST_FLOW_OK) {
            g_printerr("appsrc push returned %s\n", gst_flow_get_name(fr));
        }
        ++frames;

        const auto now = clock::now();
        if (now - last_log >= std::chrono::seconds(5)) {
            const double avg = infer_count ? (infer_ms_total / infer_count) : 0.0;
            g_print("frames=%d inference_avg=%.1fms detections_last=%zu\n",
                    frames, avg, detections.size());
            last_log = now;
            infer_ms_total = 0.0;
            infer_count = 0;
        }
    }

    g_print("shutting down\n");
    gst_app_src_end_of_stream(src);
    gst_element_set_state(capture, GST_STATE_NULL);
    gst_element_set_state(display, GST_STATE_NULL);
    gst_object_unref(sink);
    gst_object_unref(src);
    gst_object_unref(capture);
    gst_object_unref(display);
    return 0;
}
