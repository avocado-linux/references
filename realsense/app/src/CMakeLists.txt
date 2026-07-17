cmake_minimum_required(VERSION 3.14)
project(realsense-visualizer VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# All three dependencies are Avocado packages resolved into the target sysroot
# by the SDK compile step (librealsense2-dev, libmicrohttpd-dev, libjpeg-dev).
# Find them in the sysroot rather than fetching or building anything.
find_path(REALSENSE2_INCLUDE_DIR librealsense2/rs.hpp REQUIRED)
find_library(REALSENSE2_LIB realsense2 REQUIRED)

find_path(MHD_INCLUDE_DIR microhttpd.h REQUIRED)
find_library(MHD_LIB microhttpd REQUIRED)

find_path(JPEG_INCLUDE_DIR jpeglib.h REQUIRED)
find_library(JPEG_LIB jpeg REQUIRED)

find_package(Threads REQUIRED)

add_executable(realsense-visualizer app.cpp)

target_include_directories(realsense-visualizer PRIVATE
  ${REALSENSE2_INCLUDE_DIR}
  ${MHD_INCLUDE_DIR}
  ${JPEG_INCLUDE_DIR}
)

target_link_libraries(realsense-visualizer PRIVATE
  ${REALSENSE2_LIB}
  ${MHD_LIB}
  ${JPEG_LIB}
  Threads::Threads
)

install(TARGETS realsense-visualizer RUNTIME DESTINATION bin)
