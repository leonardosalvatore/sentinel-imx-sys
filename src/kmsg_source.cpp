#include "kmsg_source.hpp"

#include <systemd/sd-event.h>

#include <fcntl.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <string>

#include "log.hpp"

namespace sentinel {

namespace {
constexpr std::size_t kRecordMax = 8192;
}

std::string parse_kmsg_record(const char* buf, std::size_t len) {
    // A record is "prefix;message\n". Continuation lines (from a multi-line
    // record) start with a space and carry only metadata: ignore them.
    if (len == 0 || buf[0] == ' ') return {};

    const char* sep = static_cast<const char*>(std::memchr(buf, ';', len));
    if (!sep) return {};

    const char* msg = sep + 1;
    std::size_t msg_len = len - (msg - buf);

    // Message ends at the first newline (the rest is continuation metadata).
    if (const char* nl = static_cast<const char*>(std::memchr(msg, '\n', msg_len))) {
        msg_len = nl - msg;
    }

    // The kernel escapes non-printable bytes as \xNN; decode the common ones.
    std::string out;
    out.reserve(msg_len);
    for (std::size_t i = 0; i < msg_len; ++i) {
        if (msg[i] == '\\' && i + 3 < msg_len && msg[i + 1] == 'x') {
            auto hex = [](char c) -> int {
                if (c >= '0' && c <= '9') return c - '0';
                if (c >= 'a' && c <= 'f') return c - 'a' + 10;
                if (c >= 'A' && c <= 'F') return c - 'A' + 10;
                return -1;
            };
            int hi = hex(msg[i + 2]);
            int lo = hex(msg[i + 3]);
            if (hi >= 0 && lo >= 0) {
                out.push_back(static_cast<char>((hi << 4) | lo));
                i += 3;
                continue;
            }
        }
        out.push_back(msg[i]);
    }
    return out;
}

KmsgSource::KmsgSource(sd_event* event, EventHandler handler)
    : handler_(std::move(handler)) {
    fd_ = ::open("/dev/kmsg", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd_ < 0) {
        SENTINEL_LOG_ERR("open /dev/kmsg failed: %s", std::strerror(errno));
        return;
    }

    // Start from the end so we only see new messages, not the whole ring.
    ::lseek(fd_, 0, SEEK_END);

    int r = sd_event_add_io(event, &io_, fd_, EPOLLIN, on_readable, this);
    if (r < 0) {
        SENTINEL_LOG_ERR("sd_event_add_io(kmsg) failed: %s", std::strerror(-r));
        ::close(fd_);
        fd_ = -1;
        return;
    }
    SENTINEL_LOG_INFO("kmsg source ready (fd=%d)", fd_);
}

KmsgSource::~KmsgSource() {
    if (io_) sd_event_source_unref(io_);
    if (fd_ >= 0) ::close(fd_);
}

void KmsgSource::drain() {
    char buf[kRecordMax];
    for (;;) {
        ssize_t n = ::read(fd_, buf, sizeof(buf) - 1);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) break;
            if (errno == EPIPE) continue;  // fell behind; kernel advanced us
            if (errno == EINTR) continue;
            SENTINEL_LOG_WARN("kmsg read error: %s", std::strerror(errno));
            break;
        }
        if (n == 0) break;
        std::string text = parse_kmsg_record(buf, static_cast<std::size_t>(n));
        if (!text.empty() && handler_) handler_(Source::Kmsg, text);
    }
}

int KmsgSource::on_readable(sd_event_source* /*s*/, int /*fd*/, uint32_t /*revents*/,
                            void* ud) {
    static_cast<KmsgSource*>(ud)->drain();
    return 0;
}

}  // namespace sentinel
