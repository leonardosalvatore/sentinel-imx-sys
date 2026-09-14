#include "journal_source.hpp"

#include <systemd/sd-event.h>
#include <systemd/sd-journal.h>

#include <cstring>
#include <string>

#include "log.hpp"

namespace sentinel {

namespace {

// Our own unit; entries from it are skipped so the daemon never scores its own
// log output (belt-and-braces alongside the "sentinel-imx" substring drop in
// the pipeline).
constexpr char kSelfUnit[] = "sentinel-imx.service";

// Read one journal field for the current entry as a std::string. Journal data
// comes back as "FIELD=value" (not NUL-terminated); return just the value.
bool journal_field(sd_journal* j, const char* field, std::string& out) {
    const void* data = nullptr;
    std::size_t len = 0;
    if (sd_journal_get_data(j, field, &data, &len) < 0) return false;

    const char* base = static_cast<const char*>(data);
    const char* eq = static_cast<const char*>(std::memchr(data, '=', len));
    if (!eq) return false;

    const char* val = eq + 1;
    out.assign(val, len - static_cast<std::size_t>(val - base));
    return true;
}

}  // namespace

JournalSource::JournalSource(sd_event* event, EventHandler handler)
    : handler_(std::move(handler)) {
    int r = sd_journal_open(&journal_, SD_JOURNAL_LOCAL_ONLY | SD_JOURNAL_SYSTEM);
    if (r < 0) {
        SENTINEL_LOG_ERR("sd_journal_open failed: %s", std::strerror(-r));
        journal_ = nullptr;
        return;
    }

    // Only look at new entries, not the whole history: seek to the tail and
    // step back onto the last existing entry so the first drain starts after it.
    if ((r = sd_journal_seek_tail(journal_)) < 0) {
        SENTINEL_LOG_ERR("sd_journal_seek_tail failed: %s", std::strerror(-r));
        sd_journal_close(journal_);
        journal_ = nullptr;
        return;
    }
    sd_journal_previous(journal_);

    int fd = sd_journal_get_fd(journal_);
    if (fd < 0) {
        SENTINEL_LOG_ERR("sd_journal_get_fd failed: %s", std::strerror(-fd));
        sd_journal_close(journal_);
        journal_ = nullptr;
        return;
    }

    int events = sd_journal_get_events(journal_);
    if (events < 0) events = EPOLLIN;

    r = sd_event_add_io(event, &io_, fd, static_cast<uint32_t>(events), on_readable, this);
    if (r < 0) {
        SENTINEL_LOG_ERR("sd_event_add_io(journal) failed: %s", std::strerror(-r));
        sd_journal_close(journal_);
        journal_ = nullptr;
        return;
    }
    SENTINEL_LOG_INFO("journal source ready (fd=%d)", fd);
}

JournalSource::~JournalSource() {
    if (io_) sd_event_source_unref(io_);
    if (journal_) sd_journal_close(journal_);
}

void JournalSource::drain() {
    // Reset the wakeup state. Only APPEND/INVALIDATE mean there is new data;
    // draining unconditionally is harmless (next() just returns 0).
    if (sd_journal_process(journal_) < 0) return;

    for (;;) {
        int r = sd_journal_next(journal_);
        if (r < 0) {
            SENTINEL_LOG_WARN("sd_journal_next error: %s", std::strerror(-r));
            break;
        }
        if (r == 0) break;  // caught up

        std::string message;
        if (!journal_field(journal_, "MESSAGE", message) || message.empty()) continue;

        std::string unit;
        if (journal_field(journal_, "_SYSTEMD_UNIT", unit) && unit == kSelfUnit) continue;

        std::string transport;
        journal_field(journal_, "_TRANSPORT", transport);

        if (transport == "kernel") {
            // Same text a raw /dev/kmsg reader would see: MESSAGE only, tagged
            // as the kernel source so existing templates / model still apply.
            if (handler_) handler_(Source::Kmsg, message);
        } else {
            // Userspace log line: prefix with an identifier for context.
            std::string ident;
            if (!journal_field(journal_, "SYSLOG_IDENTIFIER", ident) || ident.empty()) {
                journal_field(journal_, "_SYSTEMD_UNIT", ident);
            }
            std::string raw;
            if (!ident.empty()) {
                raw = ident;
                raw += ": ";
            }
            raw += message;
            if (handler_) handler_(Source::Journal, raw);
        }
    }
}

int JournalSource::on_readable(sd_event_source* /*s*/, int /*fd*/, uint32_t /*revents*/,
                               void* ud) {
    static_cast<JournalSource*>(ud)->drain();
    return 0;
}

}  // namespace sentinel
