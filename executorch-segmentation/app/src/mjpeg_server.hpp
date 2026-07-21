// Minimal dependency-free MJPEG server (POSIX sockets only -- no third-party
// HTTP library, so the build stays feed-only with no FetchContent download).
// One background thread accepts connections; each client streaming /stream gets
// the latest JPEG frame as multipart/x-mixed-replace.
#pragma once

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

class MjpegServer {
 public:
  explicit MjpegServer(int port) : port_(port) {}

  ~MjpegServer() {
    running_ = false;
    if (listen_fd_ >= 0) ::close(listen_fd_);
    if (accept_thread_.joinable()) accept_thread_.join();
  }

  // Thread-safe: publish the newest JPEG-encoded frame.
  void set_frame(std::vector<unsigned char> jpeg) {
    std::lock_guard<std::mutex> lk(mtx_);
    frame_ = std::move(jpeg);
  }

  bool start() {
    listen_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd_ < 0) return false;
    int one = 1;
    ::setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(static_cast<uint16_t>(port_));
    if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
      return false;
    if (::listen(listen_fd_, 8) < 0) return false;
    running_ = true;
    accept_thread_ = std::thread([this] { accept_loop(); });
    return true;
  }

 private:
  void accept_loop() {
    while (running_) {
      const int fd = ::accept(listen_fd_, nullptr, nullptr);
      if (fd < 0) continue;
      std::thread([this, fd] { serve(fd); }).detach();
    }
  }

  static bool send_all(int fd, const char* p, size_t n) {
    while (n > 0) {
      const ssize_t s = ::send(fd, p, n, MSG_NOSIGNAL);
      if (s <= 0) return false;
      p += s;
      n -= static_cast<size_t>(s);
    }
    return true;
  }

  void serve(int fd) {
    char buf[1024];
    const ssize_t n = ::recv(fd, buf, sizeof(buf) - 1, 0);
    if (n <= 0) { ::close(fd); return; }
    buf[n] = '\0';
    const bool stream = std::strncmp(buf, "GET /stream", 11) == 0;

    if (!stream) {
      static const char* kHtml =
          "<!doctype html><title>executorch-segmentation</title>"
          "<style>body{margin:0;background:#111;text-align:center}"
          "img{max-width:100%;height:auto}"
          "h3{color:#eee;font-family:system-ui;margin:.6rem}</style>"
          "<h3>ExecuTorch DeepLabV3 &mdash; portable CPU segmentation</h3>"
          "<img src=\"/stream\">";
      std::string body = kHtml;
      std::string resp = "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n"
                         "Content-Length: " + std::to_string(body.size()) +
                         "\r\nConnection: close\r\n\r\n" + body;
      send_all(fd, resp.data(), resp.size());
      ::close(fd);
      return;
    }

    const char* hdr =
        "HTTP/1.0 200 OK\r\n"
        "Cache-Control: no-cache\r\n"
        "Connection: close\r\n"
        "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n";
    if (!send_all(fd, hdr, std::strlen(hdr))) { ::close(fd); return; }

    while (running_) {
      std::vector<unsigned char> jpeg;
      {
        std::lock_guard<std::mutex> lk(mtx_);
        jpeg = frame_;
      }
      if (!jpeg.empty()) {
        const std::string part =
            "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
            std::to_string(jpeg.size()) + "\r\n\r\n";
        if (!send_all(fd, part.data(), part.size())) break;
        if (!send_all(fd, reinterpret_cast<const char*>(jpeg.data()), jpeg.size()))
          break;
        if (!send_all(fd, "\r\n", 2)) break;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(66));
    }
    ::close(fd);
  }

  int port_;
  int listen_fd_ = -1;
  std::atomic<bool> running_{false};
  std::thread accept_thread_;
  std::mutex mtx_;
  std::vector<unsigned char> frame_;
};
