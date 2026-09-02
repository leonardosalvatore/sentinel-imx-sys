#!/usr/bin/env python3
"""Convert a sentinel-imx capture.jsonl into a NumPy (N, 64) int8 array.

Usage:
    export_capture.py data/capture.jsonl -o features.npy
    export_capture.py data/capture.jsonl --stats
"""
import argparse
import json
import sys

import numpy as np

FEATURE_DIM = 64


def load(path):
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                vec = json.loads(line)["vector"]
            except (json.JSONDecodeError, KeyError):
                print(f"warning: skipping malformed line {line_no}", file=sys.stderr)
                continue
            if len(vec) == FEATURE_DIM:
                rows.append(vec)
    return np.asarray(rows, dtype=np.int8)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", help="capture.jsonl path")
    ap.add_argument("-o", "--output", help="output .npy file")
    ap.add_argument("--stats", action="store_true", help="print basic statistics")
    args = ap.parse_args()

    data = load(args.capture)
    print(f"{len(data)} vectors x {FEATURE_DIM} dims")

    if args.stats and len(data):
        print(f"  min={data.min()} max={data.max()} "
              f"mean={data.mean():.3f} nonzero/row={np.count_nonzero(data) / len(data):.2f}")

    if args.output:
        np.save(args.output, data)
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
