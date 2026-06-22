#include "yolov3.h"

#include <cfloat>
#include <cmath>
#include <fstream>
#include <opencv2/dnn.hpp>
#include <opencv2/imgproc.hpp>

const int yolov3_grids[YOLOV3_NUM_LAYERS] = {13, 26, 52};

// Darknet YOLOv3 anchor set (COCO weights).
// Renesas's R01_object_detection sample uses the same nine anchors,
// grouped small / medium / large.
const float yolov3_anchors[YOLOV3_NUM_BB * YOLOV3_NUM_LAYERS * 2] = {
     10.f,  13.f,    16.f,  30.f,    33.f,  23.f,   // small
     30.f,  61.f,    62.f,  45.f,    59.f, 119.f,   // medium
    116.f,  90.f,   156.f, 198.f,   373.f, 326.f,   // large
};

namespace {

inline float sigmoid(float x) {
    return 1.0f / (1.0f + std::exp(-x));
}

// Channel-major offset within a YOLOv3 layer: each (NUM_CLASS+5) channel
// occupies grid*grid contiguous floats, then the next channel follows.
// This matches the layout produced by Renesas's TVM-compiled YOLOv3.
inline int yolo_offset(int n, int b, int y, int x) {
    int prev = 0;
    for (int i = 0; i < n; ++i) {
        prev += YOLOV3_NUM_BB * (YOLOV3_NUM_CLASS + 5) *
                yolov3_grids[i] * yolov3_grids[i];
    }
    int grid = yolov3_grids[n];
    return prev + b * (YOLOV3_NUM_CLASS + 5) * grid * grid + y * grid + x;
}

inline int yolo_index(int n, int offs, int channel) {
    int grid = yolov3_grids[n];
    return offs + channel * grid * grid;
}

}  // namespace

std::vector<Detection> decode_yolov3(
    const float* output, int frame_w, int frame_h,
    float confidence_threshold, float nms_threshold,
    float letterbox_scale, int letterbox_dx, int letterbox_dy) {
    std::vector<cv::Rect> boxes;
    std::vector<float> scores;
    std::vector<int> class_ids;

    const float input_size = static_cast<float>(YOLOV3_INPUT_SIZE);

    for (int n = 0; n < YOLOV3_NUM_LAYERS; ++n) {
        const int grid = yolov3_grids[n];
        // Anchor offset per layer: stride 32 (grid 13) uses anchors 6..8
        // (the largest), stride 16 (grid 26) uses 3..5, stride 8 (grid 52)
        // uses 0..2. Same convention as Darknet / Renesas's R01.
        const int anchor_base =
            2 * YOLOV3_NUM_BB * (YOLOV3_NUM_LAYERS - (n + 1));

        for (int b = 0; b < YOLOV3_NUM_BB; ++b) {
            const float anchor_w = yolov3_anchors[anchor_base + 2 * b + 0];
            const float anchor_h = yolov3_anchors[anchor_base + 2 * b + 1];

            for (int y = 0; y < grid; ++y) {
                for (int x = 0; x < grid; ++x) {
                    const int offs = yolo_offset(n, b, y, x);

                    const float tc = output[yolo_index(n, offs, 4)];
                    const float objectness = sigmoid(tc);
                    if (objectness < confidence_threshold) continue;

                    // Find argmax class without applying sigmoid to the
                    // whole vector — sigmoid is monotonic so the argmax
                    // index is unchanged. Apply sigmoid only to the max.
                    int best_class = 0;
                    float best_raw = -FLT_MAX;
                    for (int c = 0; c < YOLOV3_NUM_CLASS; ++c) {
                        const float v = output[yolo_index(n, offs, 5 + c)];
                        if (v > best_raw) {
                            best_raw = v;
                            best_class = c;
                        }
                    }
                    const float class_prob = sigmoid(best_raw);
                    const float prob = objectness * class_prob;
                    if (prob < confidence_threshold) continue;

                    const float tx = output[yolo_index(n, offs, 0)];
                    const float ty = output[yolo_index(n, offs, 1)];
                    const float tw = output[yolo_index(n, offs, 2)];
                    const float th = output[yolo_index(n, offs, 3)];

                    // YOLOv3 box decode in 416x416-space (0..1 normalized
                    // with respect to input_size).
                    const float cx_n = (static_cast<float>(x) + sigmoid(tx)) /
                                       static_cast<float>(grid);
                    const float cy_n = (static_cast<float>(y) + sigmoid(ty)) /
                                       static_cast<float>(grid);
                    const float bw_n = std::exp(tw) * anchor_w / input_size;
                    const float bh_n = std::exp(th) * anchor_h / input_size;

                    // Convert to 416x416 pixel coords.
                    const float cx_in = cx_n * input_size;
                    const float cy_in = cy_n * input_size;
                    const float bw_in = bw_n * input_size;
                    const float bh_in = bh_n * input_size;

                    // Undo letterbox to land in the source frame.
                    const float fx = (cx_in - letterbox_dx) / letterbox_scale;
                    const float fy = (cy_in - letterbox_dy) / letterbox_scale;
                    const float fw = bw_in / letterbox_scale;
                    const float fh = bh_in / letterbox_scale;

                    int x0 = static_cast<int>(std::round(fx - fw / 2));
                    int y0 = static_cast<int>(std::round(fy - fh / 2));
                    int w  = static_cast<int>(std::round(fw));
                    int h  = static_cast<int>(std::round(fh));

                    // Clamp to frame.
                    if (x0 < 0) { w += x0; x0 = 0; }
                    if (y0 < 0) { h += y0; y0 = 0; }
                    if (x0 + w > frame_w) w = frame_w - x0;
                    if (y0 + h > frame_h) h = frame_h - y0;
                    if (w <= 0 || h <= 0) continue;

                    boxes.emplace_back(x0, y0, w, h);
                    scores.push_back(prob);
                    class_ids.push_back(best_class);
                }
            }
        }
    }

    std::vector<int> keep;
    cv::dnn::NMSBoxes(boxes, scores, confidence_threshold, nms_threshold, keep);

    std::vector<Detection> out;
    out.reserve(keep.size());
    for (int idx : keep) {
        out.push_back({class_ids[idx], scores[idx], boxes[idx]});
    }
    return out;
}

std::vector<std::string> load_labels(const std::string& path) {
    std::vector<std::string> labels;
    std::ifstream f(path);
    std::string line;
    while (std::getline(f, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (!line.empty()) labels.push_back(line);
    }
    return labels;
}
