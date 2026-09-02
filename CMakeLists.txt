cmake_minimum_required(VERSION 3.16)
project(sentinel-imx-sys
    VERSION 0.1.0
    DESCRIPTION "Log-anomaly detection daemon for i.MX 8M Plus"
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

option(SENTINEL_ENABLE_TFLITE "Build with TensorFlow Lite inference support" ON)
set(SENTINEL_LIBSYSTEMD_ROOT "" CACHE PATH
    "Optional sysroot containing libsystemd headers/libs (for cross builds). \
Empty = use pkg-config.")
set(SENTINEL_TFLITE_REPO "https://github.com/nxp-imx/tensorflow-imx.git"
    CACHE STRING "Git repository for the TensorFlow Lite sources")
set(SENTINEL_TFLITE_TAG "lf-6.6.52_2.2.0"
    CACHE STRING "Git tag/branch for the TensorFlow Lite sources")

# ---------------------------------------------------------------------------
# libsystemd (sd-event, sd-bus)
# ---------------------------------------------------------------------------
add_library(sentinel_systemd INTERFACE)

if(SENTINEL_LIBSYSTEMD_ROOT)
    message(STATUS "libsystemd: using sysroot ${SENTINEL_LIBSYSTEMD_ROOT}")
    # NO_CMAKE_FIND_ROOT_PATH: the OE toolchain sets FIND_ROOT_PATH_MODE=ONLY,
    # which would otherwise re-root these explicit paths under the target
    # sysroot. This side sysroot lives outside it, so search the paths verbatim.
    find_path(SENTINEL_SD_INCLUDE_DIR
        NAMES systemd/sd-bus.h systemd/sd-event.h
        PATHS "${SENTINEL_LIBSYSTEMD_ROOT}/usr/include"
        NO_DEFAULT_PATH
        NO_CMAKE_FIND_ROOT_PATH)
    find_library(SENTINEL_SD_LIBRARY
        NAMES systemd
        PATHS "${SENTINEL_LIBSYSTEMD_ROOT}/usr/lib"
              "${SENTINEL_LIBSYSTEMD_ROOT}/usr/lib/aarch64-linux-gnu"
        NO_DEFAULT_PATH
        NO_CMAKE_FIND_ROOT_PATH)
    if(NOT SENTINEL_SD_INCLUDE_DIR OR NOT SENTINEL_SD_LIBRARY)
        message(FATAL_ERROR
            "Could not find libsystemd under ${SENTINEL_LIBSYSTEMD_ROOT}. "
            "Run docker/scripts/fetch-libsystemd.sh or unset SENTINEL_LIBSYSTEMD_ROOT.")
    endif()
    get_filename_component(SENTINEL_SD_LIBDIR "${SENTINEL_SD_LIBRARY}" DIRECTORY)
    target_include_directories(sentinel_systemd INTERFACE "${SENTINEL_SD_INCLUDE_DIR}")
    target_link_libraries(sentinel_systemd INTERFACE "${SENTINEL_SD_LIBRARY}")
    # Let the linker follow libsystemd's DT_NEEDED deps from the side sysroot
    # without forcing us to link every transitive library explicitly.
    target_link_options(sentinel_systemd INTERFACE
        "-Wl,-rpath-link,${SENTINEL_SD_LIBDIR}"
        "-Wl,--allow-shlib-undefined")
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(SYSTEMD REQUIRED IMPORTED_TARGET libsystemd)
    target_link_libraries(sentinel_systemd INTERFACE PkgConfig::SYSTEMD)
    message(STATUS "libsystemd: ${SYSTEMD_VERSION} via pkg-config")
endif()

# ---------------------------------------------------------------------------
# TensorFlow Lite (optional, fetched from the NXP fork)
# ---------------------------------------------------------------------------
set(SENTINEL_HAVE_TFLITE FALSE)
if(SENTINEL_ENABLE_TFLITE)
    include(FetchContent)
    message(STATUS "TensorFlow Lite: fetching ${SENTINEL_TFLITE_REPO}@${SENTINEL_TFLITE_TAG}")
    FetchContent_Declare(tensorflow_imx
        GIT_REPOSITORY "${SENTINEL_TFLITE_REPO}"
        GIT_TAG "${SENTINEL_TFLITE_TAG}"
        GIT_SHALLOW TRUE
        GIT_PROGRESS TRUE)
    FetchContent_GetProperties(tensorflow_imx)
    if(NOT tensorflow_imx_POPULATED)
        FetchContent_Populate(tensorflow_imx)
    endif()

    # Build settings aligned with NXP UG10166 "Build details".
    set(TFLITE_ENABLE_RUY ON CACHE BOOL "" FORCE)
    set(TFLITE_ENABLE_XNNPACK ON CACHE BOOL "" FORCE)
    set(TFLITE_ENABLE_EXTERNAL_DELEGATE ON CACHE BOOL "" FORCE)
    set(TFLITE_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)

    add_subdirectory(
        "${tensorflow_imx_SOURCE_DIR}/tensorflow/lite"
        "${CMAKE_BINARY_DIR}/tflite-build"
        EXCLUDE_FROM_ALL)
    set(SENTINEL_HAVE_TFLITE TRUE)
endif()

# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------
add_executable(sentinel-imxd
    src/main.cpp
    src/config.cpp
    src/event_loop.cpp
    src/kmsg_source.cpp
    src/dbus_source.cpp
    src/sanitizer.cpp
    src/encoder.cpp
    src/capture.cpp
    src/inferencer.cpp
    src/alerter.cpp)

target_include_directories(sentinel-imxd PRIVATE src)
target_link_libraries(sentinel-imxd PRIVATE sentinel_systemd)
target_compile_options(sentinel-imxd PRIVATE -Wall -Wextra -Wpedantic)

if(SENTINEL_HAVE_TFLITE)
    target_compile_definitions(sentinel-imxd PRIVATE SENTINEL_WITH_TFLITE=1)
    target_link_libraries(sentinel-imxd PRIVATE tensorflow-lite)
    message(STATUS "sentinel-imxd: TensorFlow Lite inference ENABLED")
else()
    message(STATUS "sentinel-imxd: TensorFlow Lite inference DISABLED (capture-only)")
endif()

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
include(GNUInstallDirs)
install(TARGETS sentinel-imxd RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(FILES config/sentinel-imx.conf DESTINATION ${CMAKE_INSTALL_SYSCONFDIR}/sentinel-imx)
install(FILES systemd/sentinel-imx.service DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/systemd/system)
install(PROGRAMS scripts/on-alert.sh DESTINATION ${CMAKE_INSTALL_PREFIX}/libexec/sentinel-imx)
