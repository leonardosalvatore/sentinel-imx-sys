#include "config.hpp"

#include <cctype>
#include <cstdlib>
#include <fstream>
#include <sstream>

#include "log.hpp"

namespace sentinel {

namespace {

std::string trim(const std::string& s) {
    std::size_t b = 0;
    std::size_t e = s.size();
    while (b < e && std::isspace(static_cast<unsigned char>(s[b]))) ++b;
    while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) --e;
    return s.substr(b, e - b);
}

bool parse_bool(const std::string& v, bool fallback) {
    std::string s;
    for (char c : v) s.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    if (s == "1" || s == "true" || s == "yes" || s == "on") return true;
    if (s == "0" || s == "false" || s == "no" || s == "off") return false;
    return fallback;
}

Mode parse_mode(const std::string& v, Mode fallback) {
    if (v == "auto") return Mode::Auto;
    if (v == "capture") return Mode::Capture;
    if (v == "infer") return Mode::Infer;
    return fallback;
}

// Apply a single key=value pair to the config.
void apply(Config& c, const std::string& key, const std::string& value) {
    if (key == "mode") {
        c.mode = parse_mode(value, c.mode);
    } else if (key == "model_path") {
        c.model_path = value;
    } else if (key == "delegate_path") {
        c.delegate_path = value;
    } else if (key == "threshold") {
        try {
            c.threshold = std::stod(value);
        } catch (...) {
            SENTINEL_LOG_WARN("invalid threshold '%s', keeping %.3f", value.c_str(), c.threshold);
        }
    } else if (key == "alert_script") {
        c.alert_script = value;
    } else if (key == "alert_cooldown_sec") {
        try {
            c.alert_cooldown_sec = std::stoi(value);
        } catch (...) {
            SENTINEL_LOG_WARN("invalid alert_cooldown_sec '%s'", value.c_str());
        }
    } else if (key == "capture_path") {
        c.capture_path = value;
    } else if (key == "kmsg") {
        c.kmsg = parse_bool(value, c.kmsg);
    } else if (key == "dbus") {
        c.dbus = parse_bool(value, c.dbus);
    } else if (key == "dbus_match") {
        if (!value.empty()) c.dbus_matches.push_back(value);
    } else {
        SENTINEL_LOG_WARN("unknown config key '%s' (ignored)", key.c_str());
    }
}

// Environment override for a given key, e.g. mode -> SENTINEL_MODE.
const char* env_for(const std::string& key) {
    std::string name = "SENTINEL_";
    for (char c : key) name.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(c))));
    return std::getenv(name.c_str());
}

}  // namespace

Config Config::load(const std::string& path) {
    Config c;

    if (!path.empty()) {
        std::ifstream in(path);
        if (in) {
            std::string line;
            while (std::getline(in, line)) {
                std::string t = trim(line);
                if (t.empty() || t[0] == '#') continue;
                auto eq = t.find('=');
                if (eq == std::string::npos) continue;
                std::string key = trim(t.substr(0, eq));
                std::string value = trim(t.substr(eq + 1));
                apply(c, key, value);
            }
        } else {
            SENTINEL_LOG_WARN("config file '%s' not found, using defaults", path.c_str());
        }
    }

    // Environment overrides for scalar keys.
    for (const char* key : {"mode", "model_path", "delegate_path", "threshold",
                            "alert_script", "alert_cooldown_sec", "capture_path",
                            "kmsg", "dbus"}) {
        if (const char* v = env_for(key)) apply(c, key, v);
    }

    return c;
}

const char* Config::mode_name() const {
    switch (mode) {
        case Mode::Auto: return "auto";
        case Mode::Capture: return "capture";
        case Mode::Infer: return "infer";
    }
    return "?";
}

}  // namespace sentinel
