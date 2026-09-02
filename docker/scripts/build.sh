#!/usr/bin/env bash
# Cross-compile the sentinel-imx daemon inside the dev container.
#
#   docker compose run --rm dev ./docker/scripts/build.sh [extra cmake args]
#
# Output binary is copied to ./out/ on the host (bind-mounted workdir).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../.." && pwd)"
# shellcheck source=docker/env.sh
source "${here}/../env.sh"

BUILD_DIR="${repo_root}/build-aarch64"
OUT_DIR="${repo_root}/out"

# Activate the Yocto cross environment (environment-setup-<arch>-poky-linux).
env_setup="$(ls "${SENTINEL_SDK_PREFIX}"/environment-setup-* 2>/dev/null | head -n1 || true)"
if [ -z "${env_setup}" ]; then
    echo "ERROR: no environment-setup script under ${SENTINEL_SDK_PREFIX}" >&2
    exit 1
fi
echo "Sourcing SDK environment: ${env_setup}"
# The SDK script trips over 'set -u'; relax it just for the source.
set +u
# shellcheck disable=SC1090
source "${env_setup}"
set -u

: "${CMAKE_TOOLCHAIN_FILE:=${OECORE_NATIVE_SYSROOT}/usr/share/cmake/OEToolchainConfig.cmake}"

echo "Configuring (${BUILD_DIR})"
cmake -S "${repo_root}" -B "${BUILD_DIR}" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="${CMAKE_TOOLCHAIN_FILE}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DSENTINEL_LIBSYSTEMD_ROOT="${SENTINEL_LIBSYSTEMD_ROOT:-/opt/sysroot-extra}" \
    -DSENTINEL_TFLITE_REPO="${SENTINEL_TFLITE_REPO}" \
    -DSENTINEL_TFLITE_TAG="${SENTINEL_TFLITE_TAG}" \
    "$@"

echo "Building"
cmake --build "${BUILD_DIR}" -j"$(nproc)"

mkdir -p "${OUT_DIR}"
cp -v "${BUILD_DIR}/sentinel-imxd" "${OUT_DIR}/sentinel-imxd"
echo "Done. Binary at out/sentinel-imxd"
file "${OUT_DIR}/sentinel-imxd" || true
