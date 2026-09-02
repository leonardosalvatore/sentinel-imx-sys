#include "event_loop.hpp"

#include <systemd/sd-event.h>

#include <csignal>
#include <cstring>

#include "log.hpp"

namespace sentinel {

namespace {

int on_signal(sd_event_source* s, const struct signalfd_siginfo* si, void* /*ud*/) {
    SENTINEL_LOG_INFO("received signal %u, exiting", si->ssi_signo);
    sd_event_exit(sd_event_source_get_event(s), 0);
    return 0;
}

}  // namespace

EventLoop::EventLoop() {
    int r = sd_event_default(&event_);
    if (r < 0) {
        SENTINEL_LOG_ERR("sd_event_default failed: %s", std::strerror(-r));
        event_ = nullptr;
        return;
    }

    // Block the signals so they are delivered through the event loop, then
    // register handlers that exit the loop cleanly.
    sigset_t ss;
    sigemptyset(&ss);
    sigaddset(&ss, SIGINT);
    sigaddset(&ss, SIGTERM);
    sigprocmask(SIG_BLOCK, &ss, nullptr);

    sd_event_add_signal(event_, nullptr, SIGINT, on_signal, nullptr);
    sd_event_add_signal(event_, nullptr, SIGTERM, on_signal, nullptr);
}

EventLoop::~EventLoop() {
    if (event_) {
        sd_event_unref(event_);
        event_ = nullptr;
    }
}

int EventLoop::run() {
    if (!event_) return 1;
    int r = sd_event_loop(event_);
    if (r < 0) {
        SENTINEL_LOG_ERR("event loop failed: %s", std::strerror(-r));
        return 1;
    }
    return 0;
}

}  // namespace sentinel
