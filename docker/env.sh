# Shared build configuration for the sentinel-imx dev container.
# Sourced by docker/scripts/*.sh and referenced by docker-compose.yml.
#
# The daemon targets an i.MX 8M Plus (aarch64) board. We cross-compile with a
# generic Scarthgap (Yocto 5.0 LTS) aarch64 SDK, which shares the same series as
# NXP LF 6.6.52. NXP's own EVK downloads are flashable .wic images, not an
# application SDK installer, so we use the publicly downloadable poky toolchain.

# ---- Scarthgap poky aarch64 SDK -------------------------------------------
# Override SENTINEL_SDK_URL / SENTINEL_SDK_SHA256 to pin a different toolchain,
# or drop a real NXP fsl-imx-*-toolchain-*.sh into docker/sdk/ (preferred if
# present, see Dockerfile.dev).
export SENTINEL_YOCTO_VERSION="${SENTINEL_YOCTO_VERSION:-5.0.19}"
export SENTINEL_SDK_ARCH="${SENTINEL_SDK_ARCH:-cortexa57-qemuarm64}"
# Use the STANDARD (non-extensible) toolchain: it installs non-interactively as
# root and provides a ready-to-use cross toolchain + target sysroot. The poky
# reference standard SDK is built from core-image-sato. (The -ext- extensible
# SDK refuses to install as root, so we do not use it here.)
export SENTINEL_SDK_INSTALLER="poky-glibc-x86_64-core-image-sato-${SENTINEL_SDK_ARCH}-toolchain-${SENTINEL_YOCTO_VERSION}.sh"
export SENTINEL_SDK_URL="${SENTINEL_SDK_URL:-https://downloads.yoctoproject.org/releases/yocto/yocto-${SENTINEL_YOCTO_VERSION}/toolchain/x86_64/${SENTINEL_SDK_INSTALLER}}"

# Where the SDK gets installed inside the image.
export SENTINEL_SDK_PREFIX="${SENTINEL_SDK_PREFIX:-/opt/poky/${SENTINEL_YOCTO_VERSION}}"

# ---- TensorFlow Lite source (NXP fork, Scarthgap era) ----------------------
export SENTINEL_TFLITE_REPO="${SENTINEL_TFLITE_REPO:-https://github.com/nxp-imx/tensorflow-imx.git}"
export SENTINEL_TFLITE_TAG="${SENTINEL_TFLITE_TAG:-lf-6.6.52_2.2.0}"

# ---- Target device runtime paths (documented, used by config/systemd) ------
export SENTINEL_DELEGATE_PATH="${SENTINEL_DELEGATE_PATH:-/usr/lib/libvx_delegate.so}"
