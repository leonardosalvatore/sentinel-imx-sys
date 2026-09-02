#pragma once
// TensorFlow Lite autoencoder wrapper. Loads model_quant.tflite, applies the
// NXP Vivante VX external delegate for NPU acceleration when available, and
// computes the reconstruction MSE for an INT8 [1, 64] feature vector.
//
// When built without TFLite (SENTINEL_WITH_TFLITE undefined), this degrades to
// a stub so the daemon still runs in capture-only mode.

#include <memory>
#include <optional>
#include <string>

#include "encoder.hpp"

namespace sentinel {

class Inferencer {
public:
    // Loads 'model_path' and tries to attach the delegate at 'delegate_path'.
    Inferencer(const std::string& model_path, const std::string& delegate_path);
    ~Inferencer();

    Inferencer(const Inferencer&) = delete;
    Inferencer& operator=(const Inferencer&) = delete;

    // True if a model is loaded and ready to run.
    bool ready() const;

    // Run the model and return the reconstruction MSE (dequantized), or
    // std::nullopt on failure / when not ready.
    std::optional<float> reconstruction_mse(const FeatureVector& input);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace sentinel
