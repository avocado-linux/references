// executorch-segmentation: live semantic segmentation on the portable
// ExecuTorch CPU runtime. A committed DeepLabV3-MobileNetV3 .pte classifies
// every pixel (21 PASCAL VOC classes); the colorized mask is blended over the
// camera feed and streamed to a browser. The same binary + .pte run unchanged
// on Jetson, i.MX8MP and i.MX93 -- no accelerator, no PyTorch on the device.

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include <opencv2/opencv.hpp>

#include "et_model.hpp"
#include "mjpeg_server.hpp"

namespace {

constexpr int kInputSize = 256;  // keep in sync with INPUT_SIZE in tools/export_model.py
constexpr int kNumClasses = 21;  // PASCAL VOC
const float kMean[3] = {0.485f, 0.456f, 0.406f};
const float kStd[3] = {0.229f, 0.224f, 0.225f};

// PASCAL VOC 21-class colormap, stored RGB.
const unsigned char kPalette[kNumClasses][3] = {
    {0, 0, 0},      {128, 0, 0},    {0, 128, 0},    {128, 128, 0},
    {0, 0, 128},    {128, 0, 128},  {0, 128, 128},  {128, 128, 128},
    {64, 0, 0},     {192, 0, 0},    {64, 128, 0},   {192, 128, 0},
    {64, 0, 128},   {192, 0, 128},  {64, 128, 128}, {192, 128, 128},
    {0, 64, 0},     {128, 64, 0},   {0, 192, 0},    {128, 192, 0},
    {0, 64, 128}};

struct Args {
  int port = 8080;
  std::string camera = "0";
  std::string model = "/usr/lib/executorch-segmentation/segmentation.pte";
  bool selftest = false;
};

Args parse_args(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string f = argv[i];
    auto next = [&]() { return (i + 1 < argc) ? argv[++i] : ""; };
    if (f == "--selftest") a.selftest = true;
    else if (f == "--port") a.port = std::atoi(next());
    else if (f == "--camera") a.camera = next();
    else if (f == "--model") a.model = next();
  }
  return a;
}

// BGR uint8 (resized to kInputSize) -> normalized RGB CHW float buffer.
void to_chw(const cv::Mat& bgr, std::vector<float>& out) {
  out.resize(3 * kInputSize * kInputSize);
  for (int y = 0; y < kInputSize; ++y) {
    for (int x = 0; x < kInputSize; ++x) {
      const cv::Vec3b& px = bgr.at<cv::Vec3b>(y, x);
      for (int c = 0; c < 3; ++c) {
        const float v = px[2 - c] / 255.0f;  // BGR -> RGB
        out[c * kInputSize * kInputSize + y * kInputSize + x] =
            (v - kMean[c]) / kStd[c];
      }
    }
  }
}

// logits (kNumClasses, H, W) row-major -> BGR mask (HxW, CV_8UC3) via per-pixel argmax.
void colorize(const std::vector<float>& logits, cv::Mat& mask) {
  const int hw = kInputSize * kInputSize;
  mask.create(kInputSize, kInputSize, CV_8UC3);
  for (int y = 0; y < kInputSize; ++y) {
    for (int x = 0; x < kInputSize; ++x) {
      const int p = y * kInputSize + x;
      int best = 0;
      float bestv = logits[p];
      for (int c = 1; c < kNumClasses; ++c) {
        const float v = logits[c * hw + p];
        if (v > bestv) { bestv = v; best = c; }
      }
      cv::Vec3b& out = mask.at<cv::Vec3b>(y, x);
      out[0] = kPalette[best][2];  // B
      out[1] = kPalette[best][1];  // G
      out[2] = kPalette[best][0];  // R
    }
  }
}

int run_selftest(const Args& a) {
  etm::EtModel model(a.model);
  std::vector<float> input(3 * kInputSize * kInputSize, 0.5f);
  auto out = model.forward({{input.data(), {1, 3, kInputSize, kInputSize}}});
  const size_t expected = static_cast<size_t>(kNumClasses) * kInputSize * kInputSize;
  const bool ok = !out.empty() && out[0].size() == expected;
  std::cout << "[selftest] output size = " << (out.empty() ? 0 : out[0].size())
            << " (expected " << expected << ") " << (ok ? "PASS" : "FAIL") << "\n";
  return ok ? 0 : 1;
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = parse_args(argc, argv);
  if (a.selftest) return run_selftest(a);

  etm::EtModel model(a.model);

  cv::VideoCapture cap;
  try {
    cap.open(std::stoi(a.camera), cv::CAP_V4L2);
  } catch (...) {
    cap.open(a.camera, cv::CAP_V4L2);
  }
  if (!cap.isOpened()) {
    std::cerr << "[seg] cannot open camera '" << a.camera << "'\n";
    return 1;
  }
  cap.set(cv::CAP_PROP_FRAME_WIDTH, 640);
  cap.set(cv::CAP_PROP_FRAME_HEIGHT, 480);

  MjpegServer server(a.port);
  if (!server.start()) {
    std::cerr << "[seg] cannot bind port " << a.port << "\n";
    return 1;
  }
  std::cout << "[seg] dashboard on http://0.0.0.0:" << a.port << "/\n";

  cv::Mat frame, small, mask, mask_full, blended;
  std::vector<float> input;
  auto last = std::chrono::steady_clock::now();

  while (true) {
    if (!cap.read(frame) || frame.empty()) continue;

    cv::resize(frame, small, cv::Size(kInputSize, kInputSize));
    to_chw(small, input);

    auto out = model.forward({{input.data(), {1, 3, kInputSize, kInputSize}}});
    colorize(out[0], mask);

    // Upscale the mask to the frame and blend it over the live video.
    cv::resize(mask, mask_full, frame.size(), 0, 0, cv::INTER_NEAREST);
    cv::addWeighted(frame, 0.55, mask_full, 0.45, 0.0, blended);

    const auto now = std::chrono::steady_clock::now();
    const double fps = 1.0 / std::chrono::duration<double>(now - last).count();
    last = now;
    cv::putText(blended, cv::format("ExecuTorch CPU  %.1f fps", fps), {12, 30},
                cv::FONT_HERSHEY_SIMPLEX, 0.8, {255, 255, 255}, 2);

    std::vector<unsigned char> jpeg;
    cv::imencode(".jpg", blended, jpeg, {cv::IMWRITE_JPEG_QUALITY, 80});
    server.set_frame(std::move(jpeg));
  }
  return 0;
}
