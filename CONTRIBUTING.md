# Contributing to sentinel-imx-sys

Thanks for your interest! This is a small, focused project — an on-device
log-anomaly detection daemon for the NXP i.MX 8M Plus. Contributions that keep
it lean and dependency-light are very welcome.

## Ground rules

- **Keep dependencies minimal.** The daemon links only `libsystemd` and
  (statically) TensorFlow Lite. Please don't pull in Boost, a JSON library, etc.
- **C++17, no exceptions-for-control-flow.** Match the existing style in `src/`.
- **Everything builds in the container.** If it doesn't build via
  `docker compose run --rm dev ./docker/scripts/build.sh`, it's not ready.
- **Explain *why* in commit messages,** not just *what*.

## Development workflow

```bash
# Build the cross-compile + training image (once)
docker compose build

# Cross-compile the daemon -> ./out/sentinel-imxd (aarch64)
docker compose run --rm dev ./docker/scripts/build.sh

# Train a model -> ./out/model_quant.tflite
docker compose run --rm dev ./docker/scripts/train.sh data/capture.jsonl
```

For a quick host-side compile check of the C++ (TFLite disabled), you can build
natively with `-DSENTINEL_ENABLE_TFLITE=OFF`.

## Before opening a pull request

1. The daemon cross-compiles cleanly.
2. New config keys are documented in `config/sentinel-imx.conf` and the README
   table, and wired through `src/config.cpp` (including the `SENTINEL_<KEY>` env
   override).
3. No secrets, board IPs, or captured logs committed (see `.gitignore`).

## Licensing

By contributing, you agree that your contributions are licensed under the
Apache License 2.0 (see `LICENSE`).
