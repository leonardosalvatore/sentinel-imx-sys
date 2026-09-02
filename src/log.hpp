#pragma once
// Minimal logging helper. Prefixes lines with syslog-style "<N>" severities so
// that when the daemon runs under systemd, journald assigns the right priority.

#include <cstdio>
#include <cstdarg>

namespace sentinel {

enum class LogLevel { Debug = 7, Info = 6, Warning = 4, Error = 3 };

inline void log_msg(LogLevel level, const char* fmt, ...) {
    std::fprintf(stderr, "<%d>sentinel-imx: ", static_cast<int>(level));
    va_list ap;
    va_start(ap, fmt);
    std::vfprintf(stderr, fmt, ap);
    va_end(ap);
    std::fputc('\n', stderr);
}

#define SENTINEL_LOG_INFO(...)  ::sentinel::log_msg(::sentinel::LogLevel::Info, __VA_ARGS__)
#define SENTINEL_LOG_WARN(...)  ::sentinel::log_msg(::sentinel::LogLevel::Warning, __VA_ARGS__)
#define SENTINEL_LOG_ERR(...)   ::sentinel::log_msg(::sentinel::LogLevel::Error, __VA_ARGS__)
#define SENTINEL_LOG_DEBUG(...) ::sentinel::log_msg(::sentinel::LogLevel::Debug, __VA_ARGS__)

}  // namespace sentinel
