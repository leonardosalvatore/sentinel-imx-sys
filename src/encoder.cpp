#include "encoder.hpp"

#include <cmath>
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

    // L2-normalize the histogram, then rescale to the int8 range. This is the
    // key to meaningful anomaly scores: without it the reconstruction MSE grows
    // with the raw token count, so the model ends up ranking events by *length*
    // rather than novelty (a short line always looks "normal"). Projecting every
    // event onto the unit sphere removes that magnitude bias, so the loss
    // reflects which token *pattern* occurred, not how many tokens there were.
    double norm2 = 0.0;
    for (std::size_t k = 0; k < kFeatureDim; ++k) {
        norm2 += static_cast<double>(acc[k]) * acc[k];
    }

    FeatureVector out{};
    if (norm2 > 0.0) {
        const double scale = 127.0 / std::sqrt(norm2);
        for (std::size_t k = 0; k < kFeatureDim; ++k) {
            long q = std::lround(acc[k] * scale);
            if (q > 127) q = 127;
            if (q < -127) q = -127;
            out[k] = static_cast<int8_t>(q);
        }
    }
    return out;
}

}  // namespace sentinel
