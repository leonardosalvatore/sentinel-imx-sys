#!/bin/sh
# sentinel-imx alert hook.
#
# Invoked by the daemon when the model's reconstruction loss exceeds the
# configured threshold. This is intentionally a stub: put your real response
# here (GPIO/LED, restart a unit, notify a fleet backend, etc).
#
# The daemon passes context through the environment:
#   SENTINEL_LOSS       - reconstruction MSE for this event
#   SENTINEL_THRESHOLD  - configured threshold
#   SENTINEL_SOURCE     - "kmsg" or "dbus"
#   SENTINEL_TEMPLATE   - sanitized log template
#   SENTINEL_RAW        - raw (truncated) log line
#
# Keep it quick: the daemon runs this with a timeout and a cooldown.
set -eu

logger -t sentinel-imx \
    "ANOMALY loss=${SENTINEL_LOSS:-?} threshold=${SENTINEL_THRESHOLD:-?} \
source=${SENTINEL_SOURCE:-?} template=[${SENTINEL_TEMPLATE:-}]"

# Example follow-up actions (uncomment / adapt):
#   echo 1 > /sys/class/leds/status:red/brightness
#   systemctl restart my-watched-unit.service

exit 0
