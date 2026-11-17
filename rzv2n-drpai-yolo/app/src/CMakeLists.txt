cmake_minimum_required(VERSION 3.16)
project(rzv2n-drpai-yolo CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT DEFINED RUHMI_DIR)
    message(FATAL_ERROR
        "RUHMI_DIR is not set. app-compile.sh clones renesas-rz/rzv_drp-ai_tvm "
        "and passes its path via -DRUHMI_DIR=...")
endif()

# RUHMI / DRP-AI TVM glue built directly from the upstream tag.
# These are Apache-2.0 licensed (see RUHMI repo).
set(RUHMI_APPS "${RUHMI_DIR}/apps")
set(RUHMI_TVM "${RUHMI_DIR}/tvm")
if(NOT DEFINED ASIO_DIR)
    message(FATAL_ERROR "ASIO_DIR is not set (app-compile.sh clones asio).")
endif()

# TVM runtime headers (from RUHMI's tvm/ submodule).
# compiler-rt isn't a git submodule — it ships in-tree under apache/tvm and
# is where PreRuntime.h finds builtin_fp16.h.
include_directories(SYSTEM
    ${RUHMI_TVM}/include
    ${RUHMI_TVM}/3rdparty/dlpack/include
    ${RUHMI_TVM}/3rdparty/dmlc-core/include
    ${RUHMI_TVM}/3rdparty/compiler-rt
)

# Renesas's wrapper around the MERA2 runtime that handles DRP-AI3 buffer
# mgmt, plus the MERA2 runtime headers and their deps (asio, spdlog).
include_directories(SYSTEM
    ${RUHMI_APPS}
    ${RUHMI_APPS}/include
    ${ASIO_DIR}/asio/include
    ${RUHMI_DIR}/how-to/sample_app_v2h/common_files/package
)

# Locate target-side dependencies via pkg-config.
find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET
    gstreamer-1.0
    gstreamer-app-1.0
    gstreamer-video-1.0
)
find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs dnn)
# Yocto's OpenCVConfig.cmake doesn't always populate ${OpenCV_LIBS} from the
# COMPONENTS list — link the dnn module by its imported target so cv::dnn::NMSBoxes
# resolves at link time. Other modules ride along via ${OpenCV_LIBS}.
if(NOT TARGET opencv_dnn)
    message(FATAL_ERROR
        "OpenCV DNN module not found in sysroot. Add `opencv-dnn` to the runtime "
        "(or its rootfs sysext) so libopencv_dnn lands in the SDK target sysroot.")
endif()

add_executable(rzv2n-drpai-yolo
    main.cpp
    yolov3.cpp
    ${RUHMI_APPS}/MeraDrpRuntimeWrapper.cpp
)

target_compile_options(rzv2n-drpai-yolo PRIVATE
    -O3 -mtune=cortex-a55 -Wall -Wno-unused-result
)

# V2N is in the V2H code path inside RUHMI's wrapper.
target_compile_definitions(rzv2n-drpai-yolo PRIVATE V2H V2N MERA_DRP_RUNTIME)

target_include_directories(rzv2n-drpai-yolo PRIVATE
    ${OpenCV_INCLUDE_DIRS}
)

target_link_libraries(rzv2n-drpai-yolo PRIVATE
    PkgConfig::GST
    ${OpenCV_LIBS}
    opencv_dnn
    mera2_runtime
    mera2_plan_io
    drp_tvm_rt
    mmngr
    mmngrbuf
    pthread
    dl
)
