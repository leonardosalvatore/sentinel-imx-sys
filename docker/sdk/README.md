# Optional: bundle a real NXP i.MX SDK installer here

If you have generated an NXP application SDK with
`bitbake imx-image-full -c populate_sdk`, drop the resulting installer here, e.g.:

```
docker/sdk/fsl-imx-xwayland-glibc-x86_64-imx-image-full-armv8a-imx8mpevk-toolchain-6.6-scarthgap.sh
```

Any `*.sh` in this directory takes precedence over the public poky Scarthgap
toolchain that `docker/Dockerfile.dev` downloads by default. This gives you a
sysroot that already contains `libtensorflow-lite`, `libsystemd`, and the exact
i.MX 8M Plus tuning.

Installers are large and license-restricted, so nothing here is committed
(see `.gitignore`).
