#!/usr/bin/env python3
"""NPU load generator for the sentinel-imx demo.

Loops inference on the Vivante NPU (via the VX external delegate) so the
accelerator load meter (/sys/kernel/debug/gc/load, core 1) visibly climbs during
a live demo. The production daemon uses a tiny INT8 model that finishes each
inference almost instantly and leaves the NPU ~0% busy (that's the efficiency
story); this stress tool drives the *large* showcase model in a tight loop to
prove the NPU is really doing the work.

Run standalone, or let sentinel-tui.py toggle it with the 'n' key:
    USE_GPU_INFERENCE=0 python3 npu-load.py [model.tflite]

Prints nothing on success (so the TUI can background it); errors go to stderr.
"""
import os
import sys
import time

# Steer the VX delegate to the NPU (VIPNano/VIP8000) rather than the 3D GPU.
os.environ.setdefault("USE_GPU_INFERENCE", "0")

MODEL = sys.argv[1] if len(sys.argv) > 1 else \
    "/usr/share/sentinel-imx/model_showcase.tflite"
DELEGATE = os.environ.get("SENTINEL_DELEGATE", "/usr/lib/libvx_delegate.so")


def main():
    import numpy as np
    try:
        from tflite_runtime.interpreter import Interpreter, load_delegate
    except ImportError:
        import tensorflow as tf
        Interpreter = tf.lite.Interpreter
        load_delegate = tf.lite.experimental.load_delegate

    delegates = []
    if os.path.exists(DELEGATE):
        try:
            delegates = [load_delegate(DELEGATE)]
        except Exception as e:  # noqa: BLE001
            print(f"npu-load: delegate unavailable ({e}); running on CPU",
                  file=sys.stderr)

    interp = Interpreter(model_path=MODEL, experimental_delegates=delegates)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    x = np.zeros(inp["shape"], dtype=inp["dtype"])

    n = 0
    t0 = time.time()
    last = t0
    while True:
        interp.set_tensor(inp["index"], x)
        interp.invoke()
        n += 1
        # Emit a heartbeat rate to stderr once a second for standalone use.
        now = time.time()
        if now - last >= 1.0:
            print(f"npu-load: {n / (now - t0):.0f} inf/s", file=sys.stderr)
            last = now


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
