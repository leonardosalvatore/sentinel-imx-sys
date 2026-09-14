#pragma once
// Thin wrapper around sd-event. Owns the loop, wires SIGINT/SIGTERM to a clean
// exit, and hands out the raw sd_event* so sources can attach themselves.

#include <functional>
#include <string>

struct sd_event;

namespace sentinel {

enum class Source { Kmsg, Dbus, Journal };

inline const char* source_name(Source s) {
    switch (s) {
        case Source::Kmsg: return "kmsg";
        case Source::Dbus: return "dbus";
        case Source::Journal: return "journal";
    }
    return "?";
}

// Called for every ingested log line, from any source. 'raw' is the unsanitized
// text of a single event.
using EventHandler = std::function<void(Source, const std::string& raw)>;

class EventLoop {
public:
    EventLoop();
    ~EventLoop();

    EventLoop(const EventLoop&) = delete;
    EventLoop& operator=(const EventLoop&) = delete;

    sd_event* get() const { return event_; }

    // Blocks until a signal (or a source) requests exit. Returns process code.
    int run();

    bool valid() const { return event_ != nullptr; }

private:
    sd_event* event_ = nullptr;
};

}  // namespace sentinel
