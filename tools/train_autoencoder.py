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

FEATURE_DIM = 64


def load_capture(path):
    """Load feature vectors from a capture JSONL file -> (N, 64) float32."""
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                vec = obj["vector"]
            except (json.JSONDecodeError, KeyError):
                print(f"warning: skipping malformed line {line_no}", file=sys.stderr)
                continue
            if len(vec) != FEATURE_DIM:
                print(f"warning: line {line_no} has {len(vec)} dims, expected "
                      f"{FEATURE_DIM}", file=sys.stderr)
                continue
            rows.append(vec)
    if not rows:
        raise SystemExit(f"no usable vectors in {path}")
    return np.asarray(rows, dtype=np.float32)


def synthetic_dataset(n=4096, seed=0):
    """Generate plausible 'normal' feature vectors resembling encoder output:
    sparse, small signed integer counts."""
    rng = np.random.default_rng(seed)
    data = np.zeros((n, FEATURE_DIM), dtype=np.float32)
    for i in range(n):
        # A handful of active bins per event, small +/- counts.
        active = rng.integers(3, 10)
        idx = rng.integers(0, FEATURE_DIM, size=active)
        vals = rng.integers(-3, 4, size=active).astype(np.float32)
        data[i, idx] = vals
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
    args = ap.parse_args()

    if args.capture:
        data = load_capture(args.capture)
        print(f"loaded {len(data)} vectors from {args.capture}")
    else:
        data = synthetic_dataset()
        print(f"using {len(data)} synthetic vectors")

    print(f"architecture: {args.arch}")
    model = build_autoencoder(args.latent, arch=args.arch)
    model.fit(data, data, epochs=args.epochs, batch_size=args.batch,
              shuffle=True, validation_split=0.1, verbose=2)

    size = export_int8_tflite(model, data, args.output)
    print(f"wrote {args.output} ({size} bytes)")


if __name__ == "__main__":
    main()
