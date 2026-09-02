#pragma once
// Reads kernel log records from /dev/kmsg and forwards their text to the
// pipeline via an EventHandler, integrated into the sd-event loop.

#include <cstddef>
#include <cstdint>

#include "event_loop.hpp"

struct sd_event;
struct sd_event_source;

namespace sentinel {

class KmsgSource {
public:
    KmsgSource(sd_event* event, EventHandler handler);
    ~KmsgSource();

    KmsgSource(const KmsgSource&) = delete;
    KmsgSource& operator=(const KmsgSource&) = delete;

    bool ok() const { return fd_ >= 0; }

private:
    static int on_readable(sd_event_source* s, int fd, uint32_t revents, void* ud);
    void drain();

    int fd_ = -1;
    sd_event_source* io_ = nullptr;
    EventHandler handler_;
};

// Extract the human-readable message from a raw /dev/kmsg record.
// Format: "prio,seq,ts_usec,flags[,...];message". Returns empty for
// continuation/metadata lines.
std::string parse_kmsg_record(const char* buf, std::size_t len);

}  // namespace sentinel
