#include "encoder.hpp"

#include <cstdint>

namespace sentinel {

namespace {

// 32-bit FNV-1a.
uint32_t fnv1a(const char* data, std::size_t len) {
    uint32_t h = 2166136261u;
    for (std::size_t i = 0; i < len; ++i) {
        h ^= static_cast<uint8_t>(data[i]);
        h *= 16777619u;
    }
    return h;
}

bool is_token_char(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '<' || c == '>' || c == '_';
}

}  // namespace

FeatureVector encode(const std::string& tmpl) {
    int32_t acc[kFeatureDim] = {0};

    std::size_t i = 0;
    const std::size_t n = tmpl.size();
    while (i < n) {
        if (!is_token_char(tmpl[i])) {
            ++i;
            continue;
        }
        std::size_t start = i;
        while (i < n && is_token_char(tmpl[i])) ++i;

        uint32_t h = fnv1a(tmpl.data() + start, i - start);
        std::size_t bin = h % kFeatureDim;
        // Signed hashing: a second bit picks +/- to reduce bias from collisions.
        int sign = (h & 0x10000u) ? 1 : -1;
        acc[bin] += sign;
    }

    FeatureVector out{};
    for (std::size_t k = 0; k < kFeatureDim; ++k) {
        int32_t v = acc[k];
        if (v > 127) v = 127;
        if (v < -127) v = -127;
        out[k] = static_cast<int8_t>(v);
    }
    return out;
}

}  // namespace sentinel
