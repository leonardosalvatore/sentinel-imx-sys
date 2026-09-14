#!/usr/bin/env bash
# Deploy sentinel-imx to an i.MX 8M Plus board over SSH.
#
#   scripts/deploy.sh [board-ip]        # default 192.168.100.2, user root
#
# Copies the cross-built daemon, model(s), config, service unit, alert hook, and
# the demo tools to the board, installs them to their FHS paths, then (re)starts
# the systemd service. Safe to re-run for redeploys.
#
# Env:
#   SENTINEL_THRESHOLD=<val>  override the MSE alert threshold in the deployed
#                             conf (model-specific; see out/threshold.txt after
#                             training). Empty = keep config/sentinel-imx.conf.
#   SENTINEL_COOLDOWN=<sec>   override alert_cooldown_sec in the deployed conf
#                             (e.g. 3 for a livelier live demo; default keeps
#                             whatever config/sentinel-imx.conf ships).
#
# Build the artifacts first:
#   docker compose run --rm dev ./docker/scripts/build.sh
#   docker compose run --rm dev ./docker/scripts/train.sh data/capture.jsonl
set -euo pipefail

BOARD_IP="${1:-192.168.100.2}"
BOARD="root@${BOARD_IP}"
SSH_OPTS=(-o StrictHostKeyChecking=no -o ConnectTimeout=8)
COOLDOWN="${SENTINEL_COOLDOWN:-}"
THRESHOLD="${SENTINEL_THRESHOLD:-}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "${here}/.." && pwd)"
cd "${repo}"

BIN="out/sentinel-imxd"
MODEL="out/model_quant.tflite"
SHOWCASE="out/model_showcase.tflite"   # optional (large NPU-stress model)

# Fail early with a clear message if a required artifact is missing.
for f in "${BIN}" "${MODEL}" \
         config/sentinel-imx.conf systemd/sentinel-imx.service \
         scripts/on-alert.sh scripts/sentinel-tui.py scripts/npu-load.py; do
    if [ ! -f "${f}" ]; then
        echo "ERROR: missing ${f} (build with docker/scripts/build.sh + train.sh)" >&2
        exit 1
    fi
done

echo ">> staging on ${BOARD_IP}:/tmp/sentinel-deploy"
ssh "${SSH_OPTS[@]}" "${BOARD}" 'rm -rf /tmp/sentinel-deploy && mkdir -p /tmp/sentinel-deploy'

files=("${BIN}" "${MODEL}"
       config/sentinel-imx.conf systemd/sentinel-imx.service
       scripts/on-alert.sh scripts/sentinel-tui.py scripts/npu-load.py)
[ -f "${SHOWCASE}" ] && files+=("${SHOWCASE}")
scp "${SSH_OPTS[@]}" "${files[@]}" "${BOARD}:/tmp/sentinel-deploy/"

echo ">> installing + (re)starting service on ${BOARD_IP}"
ssh "${SSH_OPTS[@]}" "${BOARD}" bash -s -- "${COOLDOWN}" "${THRESHOLD}" <<'REMOTE'
set -euo pipefail
COOLDOWN="${1:-}"
THRESHOLD="${2:-}"
d=/tmp/sentinel-deploy

install -Dm0755 "$d/sentinel-imxd"        /usr/bin/sentinel-imxd
install -Dm0644 "$d/sentinel-imx.conf"    /etc/sentinel-imx/sentinel-imx.conf
install -Dm0644 "$d/sentinel-imx.service" /usr/lib/systemd/system/sentinel-imx.service
install -Dm0755 "$d/on-alert.sh"          /usr/libexec/sentinel-imx/on-alert.sh
install -Dm0644 "$d/model_quant.tflite"   /usr/share/sentinel-imx/model_quant.tflite
if [ -f "$d/model_showcase.tflite" ]; then
    install -Dm0644 "$d/model_showcase.tflite" /usr/share/sentinel-imx/model_showcase.tflite
fi
install -Dm0755 "$d/sentinel-tui.py"      /usr/local/bin/sentinel-tui.py
install -Dm0755 "$d/npu-load.py"          /usr/local/bin/npu-load.py

if [ -n "${THRESHOLD}" ]; then
    sed -i "s/^threshold=.*/threshold=${THRESHOLD}/" \
        /etc/sentinel-imx/sentinel-imx.conf
    echo "set threshold=${THRESHOLD}"
fi
if [ -n "${COOLDOWN}" ]; then
    sed -i "s/^alert_cooldown_sec=.*/alert_cooldown_sec=${COOLDOWN}/" \
        /etc/sentinel-imx/sentinel-imx.conf
    echo "set alert_cooldown_sec=${COOLDOWN}"
fi

systemctl daemon-reload
systemctl enable sentinel-imx.service
# restart (not just enable --now): on a redeploy the service is already running,
# and enable --now would leave the OLD binary/model/config loaded.
systemctl restart sentinel-imx.service
sleep 2
echo "--- status ---"
systemctl is-active sentinel-imx.service || true
echo "--- startup log ---"
journalctl -u sentinel-imx -n 12 -o cat --no-pager || true
rm -rf "$d"
REMOTE

echo ">> deploy complete."
