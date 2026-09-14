// sentinel-imxd: log-anomaly detection daemon for i.MX 8M Plus.
//
// Pipeline: journald (kernel + userspace) + D-Bus  ->  sanitize
//           ->  INT8[1,64] encode  ->  capture (JSONL)
//           ->  TFLite autoencoder (NPU)  ->  MSE
//           ->  alert script when loss > threshold.

#include <memory>
#include <string>

#include "alerter.hpp"
#include "capture.hpp"
#include "config.hpp"
#include "dbus_source.hpp"
#include "encoder.hpp"
#include "event_loop.hpp"
#include "inferencer.hpp"
#include "journal_source.hpp"
#include "log.hpp"
#include "sanitizer.hpp"

namespace {

using namespace sentinel;

// Ties the stages together and is invoked for every ingested event.
class Pipeline {
public:
    Pipeline(const Config& cfg, CaptureWriter& capture, Inferencer* inferencer,
             Alerter& alerter)
        : cfg_(cfg), capture_(capture), inferencer_(inferencer), alerter_(alerter) {}

    void process(Source source, const std::string& raw) {
        // Don't feed our own log output back into the model.
        if (raw.find("sentinel-imx") != std::string::npos) return;

        std::string tmpl = sanitize(raw);
        if (tmpl.empty()) return;

        FeatureVector vec = encode(tmpl);

        capture_.write(source, tmpl, vec);

        if (inferencer_ && inferencer_->ready()) {
            if (auto loss = inferencer_->reconstruction_mse(vec)) {
                if (*loss > cfg_.threshold) {
                    alerter_.fire(source, tmpl, raw, *loss);
                }
            }
        }
    }

private:
    const Config& cfg_;
    CaptureWriter& capture_;
    Inferencer* inferencer_;
    Alerter& alerter_;
};

void print_usage(const char* argv0) {
    std::fprintf(stderr,
                 "Usage: %s [--config PATH]\n"
                 "  --config PATH   configuration file "
                 "(default /etc/sentinel-imx/sentinel-imx.conf)\n"
                 "  --help          show this help\n",
                 argv0);
}

}  // namespace

int main(int argc, char** argv) {
    std::string config_path = "/etc/sentinel-imx/sentinel-imx.conf";

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if ((arg == "--config" || arg == "-c") && i + 1 < argc) {
            config_path = argv[++i];
        } else if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            return 0;
        } else {
            SENTINEL_LOG_ERR("unknown argument '%s'", arg.c_str());
            print_usage(argv[0]);
            return 2;
        }
    }

    Config cfg = Config::load(config_path);
    SENTINEL_LOG_INFO("starting (mode=%s, threshold=%.3f)", cfg.mode_name(), cfg.threshold);

    // Inference is set up unless we're in pure capture mode.
    std::unique_ptr<Inferencer> inferencer;
    if (cfg.mode != Mode::Capture) {
        inferencer = std::make_unique<Inferencer>(cfg.model_path, cfg.delegate_path);
        if (cfg.mode == Mode::Infer && !inferencer->ready()) {
            SENTINEL_LOG_WARN("infer mode requested but model not ready; capturing only");
        }
        if (cfg.mode == Mode::Auto) {
            SENTINEL_LOG_INFO("auto mode: inference %s",
                              inferencer->ready() ? "enabled" : "disabled (capture-only)");
        }
    } else {
        SENTINEL_LOG_INFO("capture-only mode");
    }

    CaptureWriter capture(cfg.capture_path);
    Alerter alerter(cfg.alert_script, cfg.alert_cooldown_sec, cfg.threshold);
    Pipeline pipeline(cfg, capture, inferencer.get(), alerter);

    EventLoop loop;
    if (!loop.valid()) {
        SENTINEL_LOG_ERR("failed to create event loop");
        return 1;
    }

    EventHandler handler = [&pipeline](Source src, const std::string& raw) {
        pipeline.process(src, raw);
    };

    std::unique_ptr<JournalSource> journal;
    std::unique_ptr<DbusSource> dbus;

    if (cfg.journal) {
        journal = std::make_unique<JournalSource>(loop.get(), handler);
        if (!journal->ok()) {
            SENTINEL_LOG_WARN("journal source unavailable");
            journal.reset();
        }
    }
    if (cfg.dbus) {
        dbus = std::make_unique<DbusSource>(loop.get(), handler, cfg.dbus_matches);
        if (!dbus->ok()) {
            SENTINEL_LOG_WARN("dbus source unavailable");
            dbus.reset();
        }
    }

    if (!journal && !dbus) {
        SENTINEL_LOG_ERR("no event sources available; exiting");
        return 1;
    }

    SENTINEL_LOG_INFO("running");
    return loop.run();
}
