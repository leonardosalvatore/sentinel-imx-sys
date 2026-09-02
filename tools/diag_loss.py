#!/usr/bin/env python3
"""Diagnostic: reproduce the daemon's sanitize+encode+MSE pipeline and print the
reconstruction loss the model assigns to normal traffic vs. the demo anomalies.
Read-only: loads the model and (optionally) the capture; writes nothing. Run ON
the board (has tflite_runtime) or anywhere with tflite_runtime installed."""
import json
import os
import sys

import numpy as np

try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:  # fall back to full TF (dev container)
    import tensorflow as tf
    Interpreter = tf.lite.Interpreter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel_features import FEATURE_DIM, encode, sanitize

MODEL = os.environ.get("MODEL", "/usr/share/sentinel-imx/model_quant.tflite")
CAPTURE = os.environ.get("CAPTURE", "/var/lib/sentinel-imx/capture.jsonl")

ANOMALIES = [
    "sentinel-demo-inject: kernel BUG: unable to handle kernel paging request at 00000000",
    "sentinel-demo-inject: Out of memory: Killed process 4242 (rogue) total-vm:900000kB",
    "sentinel-demo-inject: EXT4-fs error (device mmcblk0p2): ext4_find_entry: reading directory lblock",
    "sentinel-demo-inject: usb 1-1: device descriptor read/64, error -110",
    "sentinel-demo-inject: watchdog: BUG: soft lockup - CPU#2 stuck for 22s!",
    'sentinel-demo-inject: audit: type=1400 avc: denied { execute } for pid=1337 comm="suspicious"',
]


def main():
    interp = Interpreter(model_path=MODEL)
    interp.allocate_tensors()
    ind = interp.get_input_details()[0]
    outd = interp.get_output_details()[0]
    in_scale, in_zp = ind["quantization"]
    out_scale, out_zp = outd["quantization"]
    in_scale = in_scale or 1.0
    out_scale = out_scale or 1.0
    print(f"model in q: scale={in_scale:.5f} zp={in_zp}  out q: scale={out_scale:.5f} zp={out_zp}")

    def loss_vec(vec):
        vec = np.asarray(vec, dtype=np.float32)
        q = np.round(vec / in_scale) + in_zp
        q = np.clip(q, -128, 127).astype(np.int8).reshape(ind["shape"])
        interp.set_tensor(ind["index"], q)
        interp.invoke()
        out = interp.get_tensor(outd["index"]).astype(np.float32).reshape(-1)
        out_real = out_scale * (out - out_zp)
        return float(np.mean((out_real[:FEATURE_DIM] - vec) ** 2))

    def loss(raw):
        return loss_vec(encode(sanitize(raw)))

    print("\n== DEMO ANOMALIES (injected via SPACE) ==")
    for a in ANOMALIES:
        print(f"  loss={loss(a):8.4f}   {sanitize(a)[:80]}")

    try:
        losses, seen = [], {}
        with open(CAPTURE) as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                t = rec.get("template", "")
                if not t or any(x in t for x in ("demo-inject", "npuload", "loadtest")):
                    continue
                lv = loss_vec(encode(t))
                losses.append(lv)
                seen[t] = lv
        if losses:
            arr = np.array(losses)
            print(f"\n== NORMAL capture ({len(arr)} events, spam excluded) ==")
            for p in (50, 90, 99, 99.9, 100):
                print(f"  p{p:<5} loss = {np.percentile(arr, p):.4f}")
            print("  highest-loss normal templates:")
            for t, l in sorted(seen.items(), key=lambda kv: -kv[1])[:6]:
                print(f"    loss={l:8.4f}  {t[:84]}")
    except OSError as e:
        print(f"(no capture: {e})")


if __name__ == "__main__":
    main()
