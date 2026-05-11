#pragma once

#include <opencv2/core.hpp>
#include <string>
#include <vector>

struct Detection {
    int class_id;
    float confidence;
    cv::Rect box;  // in source-frame coordinates
};

// Constants for the YOLOv3 (Darknet) model published in Renesas's
// rzv_ai_sdk R01_object_detection (RZ/V2N AI SDK v6.30).
//
// The DRP-AI TVM-compiled bundle expects 416x416 RGB float32 NCHW input
// (already normalized to 0..1 in the preprocess stage) and emits three
// FP16 output tensors at strides 32/16/8 (grids 13/26/52). The R01
// reference code concatenates the three outputs into a single FP32 array
// — we follow that convention so the decoder indexing stays simple.

constexpr int YOLOV3_INPUT_SIZE = 416;
constexpr int YOLOV3_NUM_BB = 3;
constexpr int YOLOV3_NUM_LAYERS = 3;
constexpr int YOLOV3_NUM_CLASS = 80;  // COCO

// Grids per output layer, ordered by decreasing stride (32, 16, 8).
extern const int yolov3_grids[YOLOV3_NUM_LAYERS];

// Anchor boxes (w, h) in 416x416 pixel space, three per stride.
// Order matches Darknet YOLOv3: small/medium/large grouped.
extern const float yolov3_anchors[YOLOV3_NUM_BB * YOLOV3_NUM_LAYERS * 2];

// Total flattened output element count — sum over layers of
//   NUM_BB * (NUM_CLASS + 5) * grid * grid
constexpr int YOLOV3_OUTPUT_SIZE =
    YOLOV3_NUM_BB * (YOLOV3_NUM_CLASS + 5) *
    (13 * 13 + 26 * 26 + 52 * 52);

// Decode the concatenated YOLOv3 output into NMS-filtered detections in
// source-frame coordinates. `letterbox_scale` and `(letterbox_dx, dy)`
// describe the resize+pad applied during preprocessing so the decoder
// can map 416x416 anchors back into the original frame.
std::vector<Detection> decode_yolov3(
    const float* output, int frame_w, int frame_h,
    float confidence_threshold, float nms_threshold,
    float letterbox_scale, int letterbox_dx, int letterbox_dy);

std::vector<std::string> load_labels(const std::string& path);
