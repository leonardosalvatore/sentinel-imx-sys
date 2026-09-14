#pragma once
// Runtime configuration: parsed from a key=value file, overridable via
// SENTINEL_<KEY> environment variables.

#include <string>
#include <vector>

namespace sentinel {

enum class Mode { Auto, Capture, Infer };

struct Config {
    Mode mode = Mode::Auto;
    std::string model_path = "/usr/share/sentinel-imx/model_quant.tflite";
    std::string delegate_path = "/usr/lib/libvx_delegate.so";
    double threshold = 0.5;
    std::string alert_script = "/usr/libexec/sentinel-imx/on-alert.sh";
    int alert_cooldown_sec = 10;
    std::string capture_path = "/var/lib/sentinel-imx/capture.jsonl";
    bool journal = true;
    bool dbus = true;
    std::vector<std::string> dbus_matches;

    // Load from file (missing file is not an error: defaults are used), then
    // apply environment overrides. 'path' may be empty to use only defaults+env.
    static Config load(const std::string& path);

    const char* mode_name() const;
};

}  // namespace sentinel
