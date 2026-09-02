#!/usr/bin/env bash
# One-screen live demo of sentinel-imx on the i.MX 8M Plus. Run this ON the board.
#
# Splits the terminal into four tmux panes that tell the whole story at a glance:
#   [0] live detections   (journal)
#   [1] NPU proof         (daemon is a registered NPU-driver client + its model
#                          tensors are resident in NPU video memory)
#   [2] CPU stays tiny    (top, filtered to the daemon)
#   [3] fault injector    (a ready-to-run anomaly; just press Enter)
#
# Note: /sys/kernel/debug/gc/load stays ~0% here on purpose - a tiny INT8
# autoencoder finishes each inference almost instantly, so the "busy cycles"
# gauge never rises. The honest proof of NPU use is the driver-client binding
# and resident model memory shown in pane [1] (plus the delegate lines in the
# journal). For a latency comparison, run scripts/npu-bench.sh.
#
# Usage:  ./demo.sh
set -euo pipefail

SVC=sentinel-imx.service
SESSION=sentinel-demo

command -v tmux >/dev/null 2>&1 || {
    cat >&2 <<'EOF'
tmux is not installed on this image. Either add it, or run these four commands
in four terminals manually:

  1) journalctl -u sentinel-imx -f -o cat
  2) watch -n1 'cat /sys/kernel/debug/gc/load; echo; \
        grep -A4 sentinel-imxd /sys/kernel/debug/gc/database'
  3) top -d1 -p "$(systemctl show -p MainPID --value sentinel-imx)"
  4) echo "kernel BUG: unable to handle kernel paging request" > /dev/kmsg
EOF
    exit 1
}

PID="$(systemctl show -p MainPID --value "${SVC}" 2>/dev/null || true)"
if [ -z "${PID}" ] || [ "${PID}" = "0" ]; then
    echo "warning: ${SVC} does not appear to be running (systemctl start it first)" >&2
fi
if [ -n "${PID}" ] && [ "${PID}" != "0" ]; then
    TOPCMD="top -d1 -p ${PID}"
else
    TOPCMD="top -d1"
fi

tmux kill-session -t "${SESSION}" 2>/dev/null || true
tmux new-session -d -s "${SESSION}"

# [0] detections
tmux send-keys -t "${SESSION}:0.0" "journalctl -u ${SVC} -f -o cat" C-m

# [1] NPU proof
tmux split-window -h -t "${SESSION}:0"
tmux send-keys -t "${SESSION}:0.1" \
    "watch -n1 'echo \"== registered NPU-driver clients ==\"; cat /sys/kernel/debug/gc/clients; echo; echo \"== model tensors resident in NPU memory ==\"; grep -A4 sentinel-imxd /sys/kernel/debug/gc/database 2>/dev/null'" C-m

# [2] CPU
tmux select-pane -t "${SESSION}:0.0"
tmux split-window -v -t "${SESSION}:0"
tmux send-keys -t "${SESSION}:0.2" "${TOPCMD}" C-m

# [3] injector - pre-typed, presenter just hits Enter
tmux select-pane -t "${SESSION}:0.1"
tmux split-window -v -t "${SESSION}:0"
tmux send-keys -t "${SESSION}:0.3" \
    'echo "kernel BUG: unable to handle kernel paging request at 00000000" > /dev/kmsg'

tmux select-layout -t "${SESSION}:0" tiled
tmux select-pane -t "${SESSION}:0.3"
tmux attach -t "${SESSION}"
