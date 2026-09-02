#include "dbus_source.hpp"

#include <systemd/sd-bus.h>
#include <systemd/sd-event.h>

#include <cstring>

#include "log.hpp"

namespace sentinel {

namespace {

const std::vector<std::string>& default_matches() {
    static const std::vector<std::string> kDefaults = {
        // systemd unit lifecycle (jobs completing, units appearing).
        "type='signal',sender='org.freedesktop.systemd1',"
        "interface='org.freedesktop.systemd1.Manager'",
        // logind session/seat events.
        "type='signal',interface='org.freedesktop.login1.Manager'",
    };
    return kDefaults;
}

// Recursively pull readable strings out of a message body. Depth-limited so a
// pathological nested message can't run away.
void collect_strings(sd_bus_message* m, std::string& out, int depth) {
    if (depth > 8) return;

    for (;;) {
        char type = 0;
        const char* contents = nullptr;
        int r = sd_bus_message_peek_type(m, &type, &contents);
        if (r <= 0) break;

        switch (type) {
            case SD_BUS_TYPE_STRING:
            case SD_BUS_TYPE_OBJECT_PATH:
            case SD_BUS_TYPE_SIGNATURE: {
                const char* s = nullptr;
                if (sd_bus_message_read_basic(m, type, &s) > 0 && s && *s) {
                    if (!out.empty()) out.push_back(' ');
                    out += s;
                }
                break;
            }
            case SD_BUS_TYPE_ARRAY:
            case SD_BUS_TYPE_STRUCT:
            case SD_BUS_TYPE_VARIANT:
            case SD_BUS_TYPE_DICT_ENTRY: {
                if (sd_bus_message_enter_container(m, type, contents) > 0) {
                    collect_strings(m, out, depth + 1);
                    sd_bus_message_exit_container(m);
                }
                break;
            }
            default: {
                // Skip non-string basic types (numbers, booleans, fds).
                if (sd_bus_message_skip(m, nullptr) <= 0) return;
                break;
            }
        }
    }
}

}  // namespace

std::string serialize_dbus_message(sd_bus_message* m) {
    std::string out;

    const char* iface = sd_bus_message_get_interface(m);
    const char* member = sd_bus_message_get_member(m);
    const char* path = sd_bus_message_get_path(m);
    const char* sender = sd_bus_message_get_sender(m);

    if (sender) { out += sender; out.push_back(' '); }
    if (iface) { out += iface; out.push_back('.'); }
    if (member) out += member;
    if (path) { out.push_back(' '); out += path; }

    std::string body;
    collect_strings(m, body, 0);
    if (!body.empty()) {
        out.push_back(' ');
        out += body;
    }
    return out;
}

DbusSource::DbusSource(sd_event* event, EventHandler handler,
                       const std::vector<std::string>& matches)
    : handler_(std::move(handler)) {
    int r = sd_bus_open_system(&bus_);
    if (r < 0) {
        SENTINEL_LOG_ERR("sd_bus_open_system failed: %s", std::strerror(-r));
        bus_ = nullptr;
        return;
    }

    r = sd_bus_attach_event(bus_, event, SD_EVENT_PRIORITY_NORMAL);
    if (r < 0) {
        SENTINEL_LOG_ERR("sd_bus_attach_event failed: %s", std::strerror(-r));
        sd_bus_unref(bus_);
        bus_ = nullptr;
        return;
    }

    const std::vector<std::string>& rules = matches.empty() ? default_matches() : matches;
    int installed = 0;
    for (const std::string& rule : rules) {
        r = sd_bus_add_match(bus_, nullptr, rule.c_str(), on_message, this);
        if (r < 0) {
            SENTINEL_LOG_WARN("sd_bus_add_match failed for [%s]: %s", rule.c_str(),
                              std::strerror(-r));
        } else {
            ++installed;
        }
    }

    if (installed == 0) {
        SENTINEL_LOG_ERR("no D-Bus matches installed");
        sd_bus_unref(bus_);
        bus_ = nullptr;
        return;
    }
    SENTINEL_LOG_INFO("dbus source ready (%d match rules)", installed);
}

DbusSource::~DbusSource() {
    if (bus_) {
        sd_bus_flush(bus_);
        sd_bus_unref(bus_);
    }
}

int DbusSource::on_message(sd_bus_message* m, void* ud, sd_bus_error* /*err*/) {
    auto* self = static_cast<DbusSource*>(ud);
    std::string line = serialize_dbus_message(m);
    if (!line.empty() && self->handler_) self->handler_(Source::Dbus, line);
    return 0;  // let other handlers for the same rule run
}

}  // namespace sentinel
