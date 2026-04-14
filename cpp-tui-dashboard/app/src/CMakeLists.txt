cmake_minimum_required(VERSION 3.14)
project(syslog-dashboard VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include(FetchContent)
set(FETCHCONTENT_UPDATES_DISCONNECTED ON)
set(FTXUI_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(FTXUI_BUILD_DOCS OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
  ftxui
  URL https://github.com/ArthurSonzogni/FTXUI/archive/refs/tags/v5.0.0.tar.gz
)
FetchContent_MakeAvailable(ftxui)

add_executable(syslog-dashboard main.cpp)
target_link_libraries(syslog-dashboard
  PRIVATE ftxui::screen
  PRIVATE ftxui::dom
  PRIVATE ftxui::component
)

install(TARGETS syslog-dashboard RUNTIME DESTINATION bin)
