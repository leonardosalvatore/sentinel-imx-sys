#pragma once
// Tails the systemd journal (kernel + userspace) and forwards each new entry's
// text to the pipeline via an EventHandler, integrated into the sd-event loop.
//
// journald is already the canonical /dev/kmsg consumer, so this single source
// covers both kernel messages (_TRANSPORT=kernel, tagged Source::Kmsg) and
// userspace logs (everything else, tagged Source::Journal). There is no need
// for a separate raw /dev/kmsg reader.

#include <cstdint>

#include "event_loop.hpp"

struct sd_event;
struct sd_event_source;
struct sd_journal;

namespace sentinel {

class JournalSource {
public:
    JournalSource(sd_event* event, EventHandler handler);
    ~JournalSource();

    JournalSource(const JournalSource&) = delete;
    JournalSource& operator=(const JournalSource&) = delete;

    bool ok() const { return journal_ != nullptr; }

private:
    static int on_readable(sd_event_source* s, int fd, uint32_t revents, void* ud);
    void drain();

    sd_journal* journal_ = nullptr;
    sd_event_source* io_ = nullptr;
    EventHandler handler_;
};

}  // namespace sentinel
