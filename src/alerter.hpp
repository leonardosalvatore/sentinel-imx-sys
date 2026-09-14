#pragma once
// Runs an external alert script when an anomaly is detected. Passes context via
// the environment, enforces a per-invocation timeout, and rate-limits with a
// cooldown so a burst of anomalies can't fork-bomb the board.

#include <chrono>
#include <string>

#include "event_loop.hpp"

namespace sentinel {

class Alerter {
public:
    Alerter(std::string script_path, int cooldown_sec, double threshold);

    // Fire the alert for one event. Respects the cooldown. Returns true if the
    // script was launched.
    bool fire(Source source, const std::string& tmpl, const std::string& raw, float loss);

private:
    std::string script_path_;
    int cooldown_sec_;
    double threshold_;
    // Cooldown is tracked per source: a stream of routine events on one source
    // must not mask an anomaly arriving on another. Index by Source's
    // underlying value (kmsg, dbus, journal).
    std::chrono::steady_clock::time_point last_fire_[3]{};
    bool fired_once_[3]{false, false, false};
};

}  // namespace sentinel
