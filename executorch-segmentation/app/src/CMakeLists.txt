cmake_minimum_required(VERSION 3.19)
project(executorch-segmentation VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Threads REQUIRED)

# ExecuTorch: `executorch-dev` installs the exported CMake config into the target
# sysroot; `executorch-staticdev` provides the portable runtime archives (.a).
find_package(executorch CONFIG REQUIRED)

# Camera + JPEG encode from the target sysroot (opencv-dev). Use pkg-config, NOT
# find_package(OpenCV): the Jetson opencv is built WITH_CUDA, so its
# OpenCVConfig.cmake hard-requires the CUDA 12.6 toolkit at configure time, which
# the cross SDK doesn't have. opencv4.pc gives the headers/libs without that.
find_package(PkgConfig REQUIRED)
pkg_check_modules(OPENCV REQUIRED IMPORTED_TARGET opencv4)

add_executable(executorch-segmentation main.cpp)

target_link_libraries(executorch-segmentation PRIVATE
  # --- ExecuTorch portable runtime, linked statically. Exactly the components
  #     Avocado's portable-only executorch package builds -- no extension_tensor
  #     (we construct tensors on the core TensorImpl), so no recipe change. ---
  executorch
  extension_module_static     # high-level Module load-and-run API
  extension_data_loader
  extension_flat_tensor

  # CRITICAL: link the portable ops archive WHOLE so the kernels self-register
  # at static-init. Otherwise the archive is pruned and forward() fails at
  # runtime with "operator not found". ExecuTorch's own
  # executorch_target_link_options_shared_lib() helper isn't exported by this
  # package, so we use CMake's built-in WHOLE_ARCHIVE link feature (>=3.24;
  # nativesdk-cmake is 3.28), which keeps the target's transitive deps.
  "$<LINK_LIBRARY:WHOLE_ARCHIVE,portable_ops_lib>"

  PkgConfig::OPENCV
  Threads::Threads
)

# OpenCV's libopencv_videoio.so is built against FFmpeg (libavcodec/format/util/
# swscale), which isn't staged in every target's SDK sysroot (e.g. imx93). We
# don't call FFmpeg ourselves, and those libraries are present on the device as
# OpenCV's own runtime dependencies, so let the linker defer those shared-lib
# symbols to runtime instead of failing at link time. Only affects symbols
# referenced by shared libraries -- our own undefined symbols still error.
target_link_options(executorch-segmentation PRIVATE -Wl,--allow-shlib-undefined)

install(TARGETS executorch-segmentation RUNTIME DESTINATION bin)
