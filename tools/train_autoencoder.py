#!/usr/bin/env python3
"""Train an INT8 autoencoder for the sentinel-imx daemon.

Reads capture.jsonl (produced by the daemon), trains a small autoencoder on the
64-dim feature vectors, and exports a fully int8-quantized model_quant.tflite
with input/output shape [1, 64] and INT8 type - matching what the daemon feeds.

Usage:
    train_autoencoder.py --capture data/capture.jsonl --output out/model_quant.tflite
    train_autoencoder.py --synthetic --output out/model_quant.tflite
"""
import argparse
import json
import os
import sys

# Route tf.keras to the Keras 2 API (tf-keras). TF 2.16's default Keras 3 graph
# cannot be lowered by the full-int8 TFLite quantizer. Must be set before TF is
# imported anywhere.
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel_features import FEATURE_DIM, encode  # noqa: E402

# Substrings that mark synthetic/demo traffic which must NOT be learned as
# "normal": the load generators used for NPU benchmarking and the demo fault
# injector. Training on these would teach the model that the very anomalies we
# inject are normal (exactly the bug that made SPACE-injections undetectable).
DEFAULT_EXCLUDE = ("demo-inject", "npuload", "loadtest")


def load_capture(path, exclude=DEFAULT_EXCLUDE, dedupe=False):
    """Load a capture JSONL and RE-ENCODE each stored (already-sanitized)
    template with the current encoder -> (N, 64) float32. Re-encoding (rather
    than trusting the stored 'vector') guarantees the training vectors match
    whatever the daemon computes today, even across encoder changes.

    Rows whose template contains any 'exclude' substring are dropped. With
    dedupe=True, each distinct template is kept once: this stops a few very
    frequent patterns (e.g. session churn) from dominating training and leaving
    rare-but-normal boot messages under-learned (and thus falsely high-loss).
    """
    rows = []
    kept_templates = []
    skipped = 0
    seen = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                tmpl = obj["template"]
            except (json.JSONDecodeError, KeyError):
                print(f"warning: skipping malformed line {line_no}", file=sys.stderr)
                continue
            if not tmpl or any(x in tmpl for x in exclude):
                skipped += 1
                continue
            if dedupe:
                if tmpl in seen:
                    continue
                seen.add(tmpl)
            rows.append(encode(tmpl))
            kept_templates.append(tmpl)
    if not rows:
        raise SystemExit(f"no usable templates in {path}")
    if skipped:
        print(f"excluded {skipped} synthetic/demo rows ({', '.join(exclude)})")
    return np.asarray(rows, dtype=np.float32), kept_templates


def synthetic_dataset(n=4096, seed=0):
    """Generate plausible 'normal' feature vectors resembling encoder output:
    sparse signed counts, then L2-normalized to the int8 range to match the
    real encoder (src/encoder.cpp / sentinel_features.encode)."""
    rng = np.random.default_rng(seed)
    data = np.zeros((n, FEATURE_DIM), dtype=np.float32)
    for i in range(n):
        active = rng.integers(3, 10)
        idx = rng.integers(0, FEATURE_DIM, size=active)
        vals = rng.integers(-3, 4, size=active).astype(np.float32)
        v = np.zeros(FEATURE_DIM, dtype=np.float32)
        v[idx] = vals
        norm = np.linalg.norm(v)
        if norm > 0:
            v = np.clip(np.round(v * 127.0 / norm), -127, 127)
        data[i] = v
    return data


def build_autoencoder(latent, arch="small"):
    """Build the autoencoder. Both architectures keep the same INT8 [1, 64]
    input/output contract, so either is a drop-in for the daemon.

    - small: 64 -> latent -> 64. Tiny (~few thousand MACs). This is what you
      want in production: the anomaly signal doesn't need a big net, and it
      keeps CPU/power near zero.
    - large: 64 -> 2048 -> 2048 -> latent -> 2048 -> 2048 -> 64 (~10M MACs).
      A deliberately heavy "showcase" net for demonstrating/benchmarking NPU
      offload (see scripts/npu-bench.sh). Same [1,64] INT8 interface.
    """
    import tensorflow as tf

    inputs = tf.keras.Input(shape=(FEATURE_DIM,), name="features")
    if arch == "large":
        x = tf.keras.layers.Dense(2048, activation="relu")(inputs)
        x = tf.keras.layers.Dense(2048, activation="relu")(x)
        x = tf.keras.layers.Dense(latent, activation="relu")(x)
        x = tf.keras.layers.Dense(2048, activation="relu")(x)
        x = tf.keras.layers.Dense(2048, activation="relu")(x)
    else:
        x = tf.keras.layers.Dense(latent, activation="relu")(inputs)
    outputs = tf.keras.layers.Dense(FEATURE_DIM, activation="linear")(x)
    model = tf.keras.Model(inputs, outputs, name="sentinel_autoencoder")
    model.compile(optimizer="adam", loss="mse")
    return model


def export_int8_tflite(model, representative, output):
    import tensorflow as tf

    def rep_gen():
        for i in range(min(len(representative), 512)):
            yield [representative[i:i + 1].astype(np.float32)]

    # Convert from a concrete function pinned to a static [1, 64] input. The
    # from_keras_model path keeps a dynamic (None) batch dim, which triggers an
    # MLIR shape-inference crash in the TF 2.16 full-int8 quantizer
    # ("Failed to infer result type(s)"). A fixed batch of 1 avoids it and
    # matches how the daemon runs inference (one event at a time).
    infer = tf.function(
        lambda x: model(x, training=False)
    ).get_concrete_function(
        tf.TensorSpec([1, FEATURE_DIM], tf.float32, name="features")
    )

    converter = tf.lite.TFLiteConverter.from_concrete_functions([infer], model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = rep_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    tflite_model = converter.convert()

    with open(output, "wb") as fh:
        fh.write(tflite_model)
    return len(tflite_model)


def tflite_losses(model_path, vectors):
    """Reconstruction MSE per row, computed through the quantized tflite model
    exactly like the daemon (src/inferencer.cpp): quantize -> invoke ->
    dequantize -> MSE in the real domain."""
    import tensorflow as tf

    interp = tf.lite.Interpreter(model_path=model_path)
    interp.allocate_tensors()
    ind = interp.get_input_details()[0]
    outd = interp.get_output_details()[0]
    in_scale, in_zp = ind["quantization"]
    out_scale, out_zp = outd["quantization"]
    in_scale = in_scale or 1.0
    out_scale = out_scale or 1.0

    losses = np.empty(len(vectors), dtype=np.float32)
    for i, vec in enumerate(vectors):
        q = np.round(vec / in_scale) + in_zp
        q = np.clip(q, -128, 127).astype(np.int8).reshape(ind["shape"])
        interp.set_tensor(ind["index"], q)
        interp.invoke()
        out = interp.get_tensor(outd["index"]).astype(np.float32).reshape(-1)
        out_real = out_scale * (out - out_zp)
        losses[i] = np.mean((out_real[:FEATURE_DIM] - vec) ** 2)
    return losses


def calibrate_threshold(model_path, data):
    """Suggest an alert threshold from the trained model's loss on the (normal)
    training data. We place it above the noisiest normal event with headroom so
    routine traffic stays quiet while genuinely novel patterns cross it."""
    losses = tflite_losses(model_path, data)
    p = {q: float(np.percentile(losses, q)) for q in (50, 90, 95, 99, 99.9, 100)}
    # Target ~3x the p90 "steady-state noise floor". This sits well above routine
    # recurring traffic but below genuinely novel patterns, and it does not chase
    # the rare boot-time tail (one-off messages that won't recur during a run).
    suggested = max(p[90] * 3.0, p[95] * 1.5, 0.05)
    print("normal-loss distribution (through quantized model):")
    for q, v in p.items():
        print(f"  p{q:<6} = {v:.4f}")
    print(f"suggested threshold = {suggested:.4f}")
    for cand in (suggested * 0.8, suggested, suggested * 1.25):
        fp = float(np.mean(losses > cand)) * 100.0
        print(f"  at threshold {cand:7.2f} -> {fp:5.2f}% of normal events alert")
    return suggested, p


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--capture", help="capture.jsonl to train on")
    src.add_argument("--synthetic", action="store_true",
                     help="train on synthetic data (placeholder model)")
    ap.add_argument("--output", default="model_quant.tflite", help="output .tflite")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--latent", type=int, default=32, help="bottleneck size")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--arch", choices=["small", "large"], default="small",
                    help="'small' for production (default); 'large' is a heavy "
                         "showcase net for NPU benchmarking (same [1,64] I/O)")
    ap.add_argument("--keep-all", action="store_true",
                    help="do NOT drop demo/load-test rows (default excludes "
                         f"templates containing: {', '.join(DEFAULT_EXCLUDE)})")
    ap.add_argument("--dedupe", action="store_true",
                    help="train on each distinct template once (recommended: "
                         "stops frequent patterns from dominating and leaving "
                         "rare-but-normal messages under-learned)")
    args = ap.parse_args()

    calib = None
    if args.capture:
        exclude = () if args.keep_all else DEFAULT_EXCLUDE
        data, _ = load_capture(args.capture, exclude=exclude, dedupe=args.dedupe)
        print(f"trained on {len(data)} templates from {args.capture}"
              f"{' (deduped)' if args.dedupe else ''}")
        # Calibrate against the full-frequency normal stream so the threshold
        # reflects how often each pattern actually occurs at run time.
        calib, _ = load_capture(args.capture, exclude=exclude, dedupe=False)
    else:
        data = synthetic_dataset()
        print(f"using {len(data)} synthetic vectors")

    print(f"architecture: {args.arch}")
    model = build_autoencoder(args.latent, arch=args.arch)
    model.fit(data, data, epochs=args.epochs, batch_size=args.batch,
              shuffle=True, validation_split=0.1, verbose=2)

    size = export_int8_tflite(model, data, args.output)
    print(f"wrote {args.output} ({size} bytes)")

    threshold, _ = calibrate_threshold(args.output, calib if calib is not None else data)
    thr_path = os.path.join(os.path.dirname(args.output) or ".", "threshold.txt")
    with open(thr_path, "w") as fh:
        fh.write(f"{threshold:.4f}\n")
    print(f"wrote {thr_path} (set 'threshold={threshold:.4f}' in the daemon conf)")


if __name__ == "__main__":
    main()
