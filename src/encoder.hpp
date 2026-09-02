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
// then L2-normalize the histogram and rescale to the int8 range. Normalizing
// decouples the reconstruction loss from the token count so the model scores
// events by pattern novelty rather than length. The trainer applies the exact
// same transform (see tools/sentinel_features.py).
FeatureVector encode(const std::string& tmpl);

}  // namespace sentinel
