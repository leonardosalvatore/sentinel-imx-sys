#!/usr/bin/env bash
# CPU vs NPU latency comparison for a TFLite model on the i.MX 8M Plus.
# Run this ON the board:
#   ./npu-bench.sh [model.tflite]
#
# It runs the NXP `benchmark_model` tool twice - once on the CPU (XNNPACK) and
# once on the NPU (Vivante VX external delegate) - and reports both average
# inference times plus the speedup ratio.
#
# WHY THIS EXISTS (read the results honestly):
#   The i.MX NPU (VIP8000) is optimized for large convolutional/vision models.
#   Small INT8 MLP/autoencoder inferences are dominated by per-invoke dispatch
#   and weight-DMA overhead, so the CPU is often *faster* for them. This tool
#   lets you measure that for your model instead of assuming. For the tiny
#   production model, expect the CPU to win by a wide margin; the NPU path is
#   there for when you deploy a heavier (e.g. conv) model.
set -euo pipefail

MODEL="${1:-/usr/share/sentinel-imx/model_quant.tflite}"
DELEGATE="${SENTINEL_DELEGATE_PATH:-/usr/lib/libvx_delegate.so}"
RUNS="${RUNS:-500}"
THREADS="${THREADS:-4}"

BENCH="$(command -v benchmark_model 2>/dev/null || true)"
if [ -z "${BENCH}" ]; then
    BENCH="$(ls -1 /usr/bin/tensorflow-lite-*/examples/benchmark_model 2>/dev/null | head -n1 || true)"
fi
[ -n "${BENCH}" ] || { echo "benchmark_model not found on this image" >&2; exit 1; }

avg_us() {  # parse "Inference (avg): N" from benchmark_model output
    grep -oE 'Inference \(avg\): [0-9.e+]+' | awk '{print $3}'
}

echo "model    : ${MODEL}"
echo "bench    : ${BENCH}"
echo "runs     : ${RUNS}"
echo

echo "Running on CPU (${THREADS} threads, XNNPACK)..."
CPU_US=$("${BENCH}" --graph="${MODEL}" --num_threads="${THREADS}" \
    --num_runs="${RUNS}" --warmup_runs=10 2>&1 | avg_us)

echo "Running on NPU (VX delegate)..."
NPU_US=$("${BENCH}" --graph="${MODEL}" --external_delegate_path="${DELEGATE}" \
    --num_runs="${RUNS}" --warmup_runs=10 2>&1 | avg_us)

echo
printf 'CPU  average inference: %s us\n' "${CPU_US:-?}"
printf 'NPU  average inference: %s us\n' "${NPU_US:-?}"
if [ -n "${CPU_US:-}" ] && [ -n "${NPU_US:-}" ]; then
    awk -v c="${CPU_US}" -v n="${NPU_US}" 'BEGIN{
        if (n>0 && c>0) {
            if (c<=n) printf "=> CPU is %.1fx faster than the NPU for this model\n", n/c;
            else      printf "=> NPU is %.1fx faster than the CPU for this model\n", c/n;
        }
    }'
fi
echo
echo "Note: the NPU also pays a one-time graph-compile cost on the FIRST"
echo "inference (seconds for large models). It wins only for large conv/vision"
echo "workloads, not small dense autoencoders like the production model."
