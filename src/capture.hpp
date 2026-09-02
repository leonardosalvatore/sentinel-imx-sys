#pragma once
// Append-only JSONL writer for sanitized+encoded events. Used to gather
// training data on the target. No JSON library: records are emitted by hand.

#include <fstream>
#include <string>

#include "encoder.hpp"
#include "event_loop.hpp"

namespace sentinel {

class CaptureWriter {
public:
    explicit CaptureWriter(std::string path);

    bool ok() const { return static_cast<bool>(out_); }

    // Append one record: {"ts",...,"source",...,"template",...,"vector":[...]}
    void write(Source source, const std::string& tmpl, const FeatureVector& vec);

private:
    std::string path_;
    std::ofstream out_;
};

}  // namespace sentinel
