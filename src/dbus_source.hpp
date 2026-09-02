#pragma once
// Subscribes to selected D-Bus system-bus signals and forwards a serialized
// text form of each message to the pipeline, integrated into the sd-event loop.

#include <string>
#include <vector>

#include <systemd/sd-bus.h>

#include "event_loop.hpp"

namespace sentinel {

class DbusSource {
public:
    // 'matches' are D-Bus match rules. If empty, a set of sensible defaults
    // (systemd unit changes + logind signals) is installed.
    DbusSource(sd_event* event, EventHandler handler,
               const std::vector<std::string>& matches);
    ~DbusSource();

    DbusSource(const DbusSource&) = delete;
    DbusSource& operator=(const DbusSource&) = delete;

    bool ok() const { return bus_ != nullptr; }

private:
    static int on_message(sd_bus_message* m, void* ud, sd_bus_error* err);

    sd_bus* bus_ = nullptr;
    EventHandler handler_;
};

// Serialize a D-Bus message to a single line: header fields plus any string
// arguments found in the body (best-effort, depth-limited).
std::string serialize_dbus_message(sd_bus_message* m);

}  // namespace sentinel
