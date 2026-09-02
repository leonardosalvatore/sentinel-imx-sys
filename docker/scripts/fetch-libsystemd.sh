#!/usr/bin/env bash
# Download Ubuntu arm64 libsystemd (+ link-time deps) and extract them into a
# side sysroot so the aarch64 cross toolchain can compile and link against
# sd-bus / sd-event. At runtime the i.MX board provides its own libsystemd.
#
# Usage: fetch-libsystemd.sh <sysroot-dir>
set -euo pipefail

SYSROOT="${1:?usage: fetch-libsystemd.sh <sysroot-dir>}"

# Packages needed to link a libsystemd consumer. libsystemd-dev provides the
# headers, pkgconfig and the linker symlink; the rest satisfy DT_NEEDED.
PACKAGES=(
    libsystemd-dev
    libsystemd0
    libcap2
    libcap-dev
    liblzma5
    liblzma-dev
    libzstd1
    liblz4-1
    libgcrypt20
    libgpg-error0
)

mkdir -p "${SYSROOT}"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

# Configure arm64 via Ubuntu ports without breaking the amd64 host repos.
# archive.ubuntu.com / security.ubuntu.com do NOT carry arm64, so the default
# host repos must be pinned to amd64; arm64 comes from ports.ubuntu.com below.
dpkg --add-architecture arm64

# Ubuntu 24.04 ships the deb822 format (/etc/apt/sources.list.d/ubuntu.sources).
# Pin every stanza to amd64 by inserting an Architectures field after Types:.
for src in /etc/apt/sources.list.d/*.sources; do
    [ -f "${src}" ] || continue
    if ! grep -q '^Architectures:' "${src}"; then
        sed -i '/^Types:/a Architectures: amd64' "${src}"
    fi
done

# Legacy one-line format, if present.
sed -i 's/^deb /deb [arch=amd64] /' /etc/apt/sources.list.d/*.list 2>/dev/null || true
if [ -f /etc/apt/sources.list ]; then
    sed -i 's/^deb /deb [arch=amd64] /' /etc/apt/sources.list || true
fi

cat > /etc/apt/sources.list.d/arm64-ports.list <<'EOF'
deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports noble main universe
deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports noble-updates main universe
deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports noble-security main universe
EOF

apt-get update

cd "${workdir}"
for pkg in "${PACKAGES[@]}"; do
    apt-get download "${pkg}:arm64"
done

for deb in ./*.deb; do
    echo "Extracting ${deb}"
    dpkg-deb -x "${deb}" "${SYSROOT}"
done

# Normalise the pkgconfig prefix so a manual sysroot works predictably.
echo "libsystemd sysroot populated at ${SYSROOT}"
find "${SYSROOT}" -name 'libsystemd*' -maxdepth 6 -print
