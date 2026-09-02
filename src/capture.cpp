#include "capture.hpp"

#include <ctime>
#include <filesystem>

#include "log.hpp"

namespace sentinel {

namespace {

void append_json_string(std::string& out, const std::string& s) {
    out.push_back('"');
    for (char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out.push_back(c);
                }
        }
    }
    out.push_back('"');
}

}  // namespace

CaptureWriter::CaptureWriter(std::string path) : path_(std::move(path)) {
    std::error_code ec;
    std::filesystem::path p(path_);
    if (p.has_parent_path()) {
        std::filesystem::create_directories(p.parent_path(), ec);
        if (ec) {
            SENTINEL_LOG_WARN("could not create capture dir '%s': %s",
                              p.parent_path().c_str(), ec.message().c_str());
        }
    }
    out_.open(path_, std::ios::out | std::ios::app);
    if (!out_) {
        SENTINEL_LOG_ERR("could not open capture file '%s'", path_.c_str());
    } else {
        SENTINEL_LOG_INFO("capturing to %s", path_.c_str());
    }
}

void CaptureWriter::write(Source source, const std::string& tmpl,
                          const FeatureVector& vec) {
    if (!out_) return;

    std::string line = "{\"ts\":";
    line += std::to_string(static_cast<long long>(std::time(nullptr)));
    line += ",\"source\":\"";
    line += source_name(source);
    line += "\",\"template\":";
    append_json_string(line, tmpl);
    line += ",\"vector\":[";
    for (std::size_t i = 0; i < vec.size(); ++i) {
        if (i) line.push_back(',');
        line += std::to_string(static_cast<int>(vec[i]));
    }
    line += "]}\n";

    out_ << line;
    out_.flush();
}

}  // namespace sentinel
