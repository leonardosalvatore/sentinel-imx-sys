#pragma once
// Maps a sanitized log template to a fixed-size INT8 feature vector [1, 64]
// using signed feature hashing (the "hashing trick"). Deterministic and
// dependency-free so the daemon and the trainer produce identical vectors.

#include <array>
#include <cstdint>
#include <string>

namespace sentinel {

constexpr std::size_t kFeatureDim = 64;

using FeatureVector = std::array<int8_t, kFeatureDim>;

// Tokenize the template and hash each token into one of kFeatureDim signed bins,
// saturating to the int8 range.
FeatureVector encode(const std::string& tmpl);

}  // namespace sentinel
