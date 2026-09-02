#!/usr/bin/env bash
# Train the INT8 autoencoder and export model_quant.tflite inside the container.
#
#   docker compose run --rm dev ./docker/scripts/train.sh [capture.jsonl]
#
# With no argument (or a missing file) a synthetic dataset is used so you get a
# placeholder model_quant.tflite to validate the pipeline before real captures.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../.." && pwd)"

CAPTURE="${1:-}"
OUT_DIR="${repo_root}/out"
mkdir -p "${OUT_DIR}"

args=(--output "${OUT_DIR}/model_quant.tflite")
if [ -n "${CAPTURE}" ] && [ -f "${CAPTURE}" ]; then
    args+=(--capture "${CAPTURE}")
else
    echo "No capture file given; training on synthetic data (placeholder model)."
    args+=(--synthetic)
fi

python3 "${repo_root}/tools/train_autoencoder.py" "${args[@]}"
echo "Wrote ${OUT_DIR}/model_quant.tflite"
