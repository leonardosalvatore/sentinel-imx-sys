#include "alerter.hpp"

#include <sys/wait.h>
#include <unistd.h>

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "log.hpp"

namespace sentinel {

namespace {
constexpr unsigned kAlertTimeoutSec = 5;
constexpr std::size_t kRawMax = 256;
}  // namespace

Alerter::Alerter(std::string script_path, int cooldown_sec, double threshold)
    : script_path_(std::move(script_path)),
      cooldown_sec_(cooldown_sec),
      threshold_(threshold) {}

bool Alerter::fire(Source source, const std::string& tmpl, const std::string& raw,
                   float loss) {
    const int si = static_cast<int>(source);
    auto now = std::chrono::steady_clock::now();
    if (fired_once_[si] &&
        now - last_fire_[si] < std::chrono::seconds(cooldown_sec_)) {
        SENTINEL_LOG_DEBUG("alert suppressed by cooldown (source=%s loss=%.4f)",
                           source_name(source), loss);
        return false;
    }
    last_fire_[si] = now;
    fired_once_[si] = true;

    // Precompute environment values (copied into the child on fork).
    char loss_buf[32];
    char thr_buf[32];
    std::snprintf(loss_buf, sizeof(loss_buf), "%.6f", loss);
    std::snprintf(thr_buf, sizeof(thr_buf), "%.6f", threshold_);
    std::string raw_trunc = raw.size() > kRawMax ? raw.substr(0, kRawMax) : raw;

    // Double-fork: the grandchild runs the script and is reparented to init, so
    // we never block the event loop and never leak zombies.
    pid_t pid = fork();
    if (pid < 0) {
        SENTINEL_LOG_ERR("fork for alert failed: %s", std::strerror(errno));
        return false;
    }

    if (pid == 0) {
        pid_t gc = fork();
        if (gc == 0) {
            setenv("SENTINEL_LOSS", loss_buf, 1);
            setenv("SENTINEL_THRESHOLD", thr_buf, 1);
            setenv("SENTINEL_SOURCE", source_name(source), 1);
            setenv("SENTINEL_TEMPLATE", tmpl.c_str(), 1);
            setenv("SENTINEL_RAW", raw_trunc.c_str(), 1);

            // Self-terminate if the script runs too long (SIGALRM => default
            // disposition after exec is to kill the process).
            alarm(kAlertTimeoutSec);

            execl(script_path_.c_str(), script_path_.c_str(),
                  static_cast<char*>(nullptr));
            // Fall back to a shell if the script isn't directly executable.
            execl("/bin/sh", "sh", script_path_.c_str(),
                  static_cast<char*>(nullptr));
            _exit(127);
        }
        _exit(0);  // intermediate exits immediately
    }

    // Reap the short-lived intermediate.
    waitpid(pid, nullptr, 0);
    SENTINEL_LOG_INFO("alert fired: source=%s loss=%.4f > %.4f",
                      source_name(source), loss, threshold_);
    return true;
}

}  // namespace sentinel
