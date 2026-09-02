# sentinel-imx-sys

A lightweight log-anomaly detection daemon for the **NXP i.MX 8M Plus** (Yocto /
Debian), plus a self-contained Docker build + model-training environment.

The daemon (`sentinel-imxd`) listens to kernel messages (`/dev/kmsg`) and D-Bus
system-bus signals, sanitizes each line into a stable *template*, encodes it into
a fixed **INT8 `[1, 64]`** vector, optionally runs a TensorFlow Lite autoencoder
on the **Vivante NPU** via the VX external delegate, and — when the reconstruction
loss (MSE) exceeds a threshold — runs an external alert script.

```mermaid
flowchart LR
  kmsg["/dev/kmsg"] --> loop
  dbus["D-Bus system bus"] --> loop
  loop["sd-event loop"] --> clean["Sanitize + template"]
  clean --> enc["INT8 vector [1,64]"]
  enc --> cap["JSONL capture"]
  enc --> inf["TFLite + VX NPU"]
  inf --> mse["Dequant MSE"]
  mse -->|"loss > threshold"| script["on-alert.sh"]
```

## What it does, in plain terms

Embedded Linux boxes are noisy: the kernel and system services emit a constant
stream of log lines. Most are routine; a few (a failing eMMC, an OOM kill, a USB
device misbehaving, an unexpected service crash) are early warnings. Watching
those by hand doesn't scale, and shipping every log to the cloud is often
impossible or undesirable on an edge device.

`sentinel-imx-sys` learns what *normal* logs look like for **your** device, then
flags the abnormal ones **on the device**, in real time, at near-zero cost — and
runs a script of your choosing when something looks wrong. No cloud, no log
shipping, data stays local.

It's an **autoencoder for logs**: it's trained only on normal traffic, so when it
sees something unfamiliar it reconstructs it poorly (high error = anomaly).

## Design highlights

- **Capture-first.** With no model present (`mode=auto`), the daemon just records
  sanitized/encoded events to a JSONL file — use it to collect training data on
  the real board, then train and drop in `model_quant.tflite`.
- **Actions are yours.** Alerts don't do anything hard-coded; they exec a
  configurable bash script with rich context in the environment.
- **Minimal dependencies.** Only `libsystemd` (sd-event + sd-bus) and TensorFlow
  Lite. No Boost, no JSON library (JSON is written/parsed by hand).
- **NPU acceleration.** Uses `/usr/lib/libvx_delegate.so` as a TFLite *external
  delegate*; `USE_GPU_INFERENCE=0` steers it to the NPU rather than the 3D GPU.

## Repository layout

```
CMakeLists.txt            Cross/native build
docker-compose.yml        One-command dev environment
docker/                   SDK download + cross-build + training image
config/sentinel-imx.conf  Runtime configuration
systemd/                  Service unit
scripts/on-alert.sh       Alert hook stub (customize this)
scripts/demo.sh           One-screen live demo (tmux, run on the board)
scripts/npu-bench.sh      CPU-vs-NPU latency benchmark (run on the board)
tools/                    Host-side training + capture export
src/                      Daemon sources
LICENSE / NOTICE          Apache-2.0
```

## Build (self-contained, via Docker)

NXP's public EVK downloads are flashable `.wic` images, not an application SDK.
The container instead installs the public **standard Scarthgap (Yocto 5.0 LTS)
aarch64 SDK** — the same Yocto series as NXP LF 6.6.52 — giving the cross
toolchain in the familiar board-SDK layout. (The *standard* toolchain is used
rather than the extensible `-ext-` one, which refuses to install as root.)
TensorFlow Lite is fetched from the NXP git fork at configure time;
`libvx_delegate.so` lives on the target at runtime.

```bash
# 1. Build the image (downloads the SDK + libsystemd, installs TF for training)
docker compose build

# 2. Cross-compile the daemon -> ./out/sentinel-imxd (aarch64)
docker compose run --rm dev ./docker/scripts/build.sh

# 3. Train a model from captured data -> ./out/model_quant.tflite
docker compose run --rm dev ./docker/scripts/train.sh data/capture.jsonl

# ...or, with no capture file, train on synthetic data (placeholder model):
docker compose run --rm dev ./docker/scripts/train.sh
```

> Build outputs land in `./out/` owned by root (the container runs as root). Run
> `sudo chown -R "$USER:$USER" out build-aarch64` if you need to edit them from
> the host.

If you have a real NXP SDK installer, drop it in `docker/sdk/*.sh`; it takes
precedence over the public poky toolchain (and already contains `libtensorflow-lite`
and the i.MX tuning).

To skip the heavy TensorFlow Lite build (capture-only daemon):

```bash
docker compose run --rm dev ./docker/scripts/build.sh -DSENTINEL_ENABLE_TFLITE=OFF
```

### Native build on the board

On an i.MX image that already ships `libsystemd` and `libtensorflow-lite`:

```bash
cmake -S . -B build -DSENTINEL_ENABLE_TFLITE=ON
cmake --build build -j
sudo cmake --install build
```

## Deploy

```bash
# Copy the cross-built binary + assets to the board, then:
sudo install -m0755 out/sentinel-imxd /usr/bin/sentinel-imxd
sudo install -Dm0644 config/sentinel-imx.conf /etc/sentinel-imx/sentinel-imx.conf
sudo install -Dm0644 systemd/sentinel-imx.service /usr/lib/systemd/system/sentinel-imx.service
sudo install -Dm0755 scripts/on-alert.sh /usr/libexec/sentinel-imx/on-alert.sh
sudo install -Dm0644 out/model_quant.tflite /usr/share/sentinel-imx/model_quant.tflite   # optional
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel-imx.service
```

## Configuration

See [`config/sentinel-imx.conf`](config/sentinel-imx.conf). Every key can be
overridden by a `SENTINEL_<KEY>` environment variable. Key options:

| Key                  | Default                                       | Meaning                                   |
|----------------------|-----------------------------------------------|-------------------------------------------|
| `mode`               | `auto`                                         | `auto` / `capture` / `infer`              |
| `model_path`         | `/usr/share/sentinel-imx/model_quant.tflite`   | TFLite autoencoder                        |
| `delegate_path`      | `/usr/lib/libvx_delegate.so`                   | Vivante VX external delegate              |
| `threshold`          | `0.5`                                          | MSE anomaly threshold                     |
| `alert_script`       | `/usr/libexec/sentinel-imx/on-alert.sh`        | Program run on anomaly                    |
| `alert_cooldown_sec` | `10`                                           | Min seconds between alerts                |
| `capture_path`       | `/var/lib/sentinel-imx/capture.jsonl`          | JSONL training data                       |
| `kmsg` / `dbus`      | `true` / `true`                                | Enable event sources                      |
| `dbus_match`         | (built-in defaults)                            | Repeatable D-Bus match rule               |

### Alert script environment

`on-alert.sh` receives: `SENTINEL_LOSS`, `SENTINEL_THRESHOLD`, `SENTINEL_SOURCE`
(`kmsg`/`dbus`), `SENTINEL_TEMPLATE`, `SENTINEL_RAW` (truncated).

## Live demo (on the board)

`scripts/demo.sh` splits your terminal into a single screen that tells the whole
story — run it on the board (needs `tmux`):

```bash
./demo.sh
```

- **top-left** — live detections (`journalctl -u sentinel-imx -f`)
- **top-right** — NPU proof: the daemon is a registered client of the Vivante
  NPU driver and its model tensors are resident in NPU video memory
- **bottom-left** — `top` filtered to the daemon (CPU stays tiny)
- **bottom-right** — a pre-typed fault injector; press Enter to fire one:

```bash
echo "kernel BUG: unable to handle kernel paging request at 00000000" > /dev/kmsg
```

The narrative: inject a scary kernel message → an alert fires instantly → CPU
barely moves → because the model is running through the NPU delegate.

### Proving the NPU is engaged

The i.MX NPU load gauge (`/sys/kernel/debug/gc/load`) stays near 0% for this
workload — a tiny INT8 autoencoder finishes each inference almost instantly, so
there are no sustained "busy cycles" to show. That's expected; the honest proof
of NPU use is:

```bash
# 1. The daemon is bound to the Vivante NPU/GPU driver:
cat /sys/kernel/debug/gc/clients            # -> lists sentinel-imxd

# 2. Its model tensors are resident in NPU (VIP) video memory:
grep -A5 sentinel-imxd /sys/kernel/debug/gc/database

# 3. The journal shows the graph was delegated:
journalctl -u sentinel-imx | grep -i delegate
#   -> using external delegate /usr/lib/libvx_delegate.so (NPU)
```

## Performance: CPU vs NPU (measured on i.MX 8M Plus)

Measured with NXP's `benchmark_model` (INT8), and via the running daemon:

| Metric | Value |
|---|---|
| Daemon idle CPU | ~0.3% |
| End-to-end CPU per event (parse → encode → infer → capture) | ~0.25 ms |
| Resident memory (RSS) | ~37 MB |
| Production model (4.1K MACs) — **CPU** (1× A53) | **~2.3 µs / inference** |
| Production model (4.1K MACs) — NPU (VX delegate) | ~110 µs / inference |
| Showcase model (8.8M MACs) — CPU (4 threads) | ~1130 µs / inference |
| Showcase model (8.8M MACs) — NPU (VX delegate) | ~1180 µs / inference (+3.35 s first-run compile) |

**Honest takeaway:** for this workload the **CPU is the right choice**. The i.MX
NPU (VIP8000) is built for large convolutional/vision tensors; small INT8
MLP/autoencoder inferences are dominated by per-invoke dispatch and weight-DMA
overhead, so the NPU is far slower for the tiny production model and only
break-even for a deliberately heavy one. The daemon supports the NPU delegate
(and it works — the graph is fully delegated) so you can drop in a heavier model
later, but out of the box the anomaly signal simply doesn't need it, which is
*why the daemon is so cheap to run*.

Reproduce the comparison on your board:

```bash
# tiny production model (CPU wins big)
./npu-bench.sh /usr/share/sentinel-imx/model_quant.tflite

# heavy showcase model (train it first: train.sh --arch large)
./npu-bench.sh /tmp/model_showcase.tflite
```

## Training your own model

1. Run in `capture` (or `auto` without a model) to collect `capture.jsonl`.
2. Copy it off the board into `./data/capture.jsonl`.
3. `docker compose run --rm dev ./docker/scripts/train.sh data/capture.jsonl`.
4. Copy `out/model_quant.tflite` to the board and restart the service.

The model is a small autoencoder (`64 -> 32 -> 64`, INT8 in/out) trained on the
same feature vectors the daemon produces, so training matches inference exactly.

Training runs under the Keras 2 API (`tf-keras`, selected via
`TF_USE_LEGACY_KERAS=1`): TensorFlow 2.16 defaults to Keras 3, whose graph the
full-int8 TFLite quantizer cannot lower. The dev image installs `tf-keras` and
the training script sets the flag automatically — no action needed.

Pass `--arch large` for a deliberately heavy (~8.8M MAC) autoencoder with the
same INT8 `[1,64]` interface — useful only for the NPU-vs-CPU benchmark, not for
production:

```bash
docker compose run --rm dev ./docker/scripts/train.sh   # small (default)
docker compose run --rm --entrypoint bash dev -lc \
  'python3 tools/train_autoencoder.py --synthetic --arch large --output out/model_showcase.tflite'
```

### Capture file format

One JSON object per line:

```json
{"ts":1725270000,"source":"kmsg","template":"usb <NUM>-<NUM> new high-speed usb device number <NUM> using <HEX>","vector":[3,-1,0, ...]}
```

`tools/export_capture.py` converts this to a NumPy `(N, 64)` int8 array.

### Log rotation

The daemon appends forever. Add a `logrotate` snippet if needed:

```
/var/lib/sentinel-imx/capture.jsonl {
    weekly
    rotate 4
    missingok
    notifempty
    copytruncate
}
```

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Contributions
welcome; see [`CONTRIBUTING.md`](CONTRIBUTING.md).

TensorFlow Lite (NXP fork) is fetched at build time and the Vivante VX delegate
lives on the target device; neither is redistributed here.
