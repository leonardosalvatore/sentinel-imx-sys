#include "inferencer.hpp"

#include <filesystem>

#include "log.hpp"

#ifdef SENTINEL_WITH_TFLITE

#include "tensorflow/lite/interpreter.h"
#include "tensorflow/lite/interpreter_builder.h"
#include "tensorflow/lite/kernels/register.h"
#include "tensorflow/lite/model_builder.h"
#include "tensorflow/lite/delegates/external/external_delegate.h"
#include "tensorflow/lite/c/common.h"

#include <cmath>
#include <vector>

namespace sentinel {

struct Inferencer::Impl {
    std::unique_ptr<tflite::FlatBufferModel> model;
    std::unique_ptr<tflite::Interpreter> interpreter;
    TfLiteDelegate* delegate = nullptr;
    bool ready = false;
    int in_idx = -1;
    int out_idx = -1;

    ~Impl() {
        // Interpreter must die before the delegate it references.
        interpreter.reset();
        if (delegate) TfLiteExternalDelegateDelete(delegate);
    }
};

Inferencer::Inferencer(const std::string& model_path, const std::string& delegate_path)
    : impl_(std::make_unique<Impl>()) {
    if (!std::filesystem::exists(model_path)) {
        SENTINEL_LOG_WARN("model '%s' not found; inference disabled", model_path.c_str());
        return;
    }

    impl_->model = tflite::FlatBufferModel::BuildFromFile(model_path.c_str());
    if (!impl_->model) {
        SENTINEL_LOG_ERR("failed to load model '%s'", model_path.c_str());
        return;
    }

    tflite::ops::builtin::BuiltinOpResolver resolver;
    tflite::InterpreterBuilder builder(*impl_->model, resolver);
    if (builder(&impl_->interpreter) != kTfLiteOk || !impl_->interpreter) {
        SENTINEL_LOG_ERR("failed to build interpreter");
        return;
    }

    // Attach the Vivante VX external delegate for NPU acceleration.
    if (std::filesystem::exists(delegate_path)) {
        auto opts = TfLiteExternalDelegateOptionsDefault(delegate_path.c_str());
        impl_->delegate = TfLiteExternalDelegateCreate(&opts);
        if (impl_->delegate &&
            impl_->interpreter->ModifyGraphWithDelegate(impl_->delegate) == kTfLiteOk) {
            SENTINEL_LOG_INFO("using external delegate %s (NPU)", delegate_path.c_str());
        } else {
            SENTINEL_LOG_WARN("delegate %s unavailable; running on CPU", delegate_path.c_str());
            if (impl_->delegate) {
                TfLiteExternalDelegateDelete(impl_->delegate);
                impl_->delegate = nullptr;
            }
        }
    } else {
        SENTINEL_LOG_WARN("delegate '%s' not found; running on CPU", delegate_path.c_str());
    }

    if (impl_->interpreter->AllocateTensors() != kTfLiteOk) {
        SENTINEL_LOG_ERR("AllocateTensors failed");
        return;
    }

    if (impl_->interpreter->inputs().empty() || impl_->interpreter->outputs().empty()) {
        SENTINEL_LOG_ERR("model has no inputs/outputs");
        return;
    }
    impl_->in_idx = impl_->interpreter->inputs()[0];
    impl_->out_idx = impl_->interpreter->outputs()[0];

    const TfLiteTensor* in = impl_->interpreter->tensor(impl_->in_idx);
    if (in->type != kTfLiteInt8) {
        SENTINEL_LOG_ERR("model input is not INT8 (type=%d)", in->type);
        return;
    }
    if (in->bytes < kFeatureDim) {
        SENTINEL_LOG_ERR("model input smaller than %zu bytes", kFeatureDim);
        return;
    }

    impl_->ready = true;
    SENTINEL_LOG_INFO("model '%s' ready", model_path.c_str());
}

Inferencer::~Inferencer() = default;

bool Inferencer::ready() const { return impl_ && impl_->ready; }

std::optional<float> Inferencer::reconstruction_mse(const FeatureVector& input) {
    if (!ready()) return std::nullopt;

    auto* interp = impl_->interpreter.get();
    const TfLiteTensor* in_t = interp->tensor(impl_->in_idx);
    const TfLiteTensor* out_t = interp->tensor(impl_->out_idx);

    const float in_scale = in_t->params.scale != 0.0f ? in_t->params.scale : 1.0f;
    const int in_zp = in_t->params.zero_point;
    const float out_scale = out_t->params.scale != 0.0f ? out_t->params.scale : 1.0f;
    const int out_zp = out_t->params.zero_point;

    // The feature values are the real-domain input. Quantize them into the
    // model's INT8 input tensor using its scale/zero-point (identity when
    // scale==1, zp==0). This keeps the daemon consistent with a model trained
    // on the same feature counts.
    int8_t* in_data = interp->typed_tensor<int8_t>(impl_->in_idx);
    if (!in_data) return std::nullopt;
    for (std::size_t i = 0; i < kFeatureDim; ++i) {
        float real = static_cast<float>(input[i]);
        long q = std::lround(real / in_scale) + in_zp;
        if (q > 127) q = 127;
        if (q < -128) q = -128;
        in_data[i] = static_cast<int8_t>(q);
    }

    if (interp->Invoke() != kTfLiteOk) {
        SENTINEL_LOG_WARN("Invoke failed");
        return std::nullopt;
    }

    const int8_t* out_data = interp->typed_tensor<int8_t>(impl_->out_idx);
    if (!out_data) return std::nullopt;

    // Reconstruction MSE in the real (dequantized) domain.
    std::size_t out_len = out_t->bytes;  // int8 => 1 byte per element
    std::size_t len = std::min<std::size_t>(kFeatureDim, out_len);
    if (len == 0) return std::nullopt;

    double sse = 0.0;
    for (std::size_t i = 0; i < len; ++i) {
        float in_real = static_cast<float>(input[i]);
        float out_real = out_scale * (static_cast<int>(out_data[i]) - out_zp);
        float d = out_real - in_real;
        sse += static_cast<double>(d) * d;
    }
    return static_cast<float>(sse / static_cast<double>(len));
}

}  // namespace sentinel

#else  // !SENTINEL_WITH_TFLITE

namespace sentinel {

struct Inferencer::Impl {};

Inferencer::Inferencer(const std::string& /*model_path*/, const std::string& /*delegate_path*/) {
    SENTINEL_LOG_WARN("built without TensorFlow Lite; inference disabled (capture-only)");
}

Inferencer::~Inferencer() = default;

bool Inferencer::ready() const { return false; }

std::optional<float> Inferencer::reconstruction_mse(const FeatureVector& /*input*/) {
    return std::nullopt;
}

}  // namespace sentinel

#endif  // SENTINEL_WITH_TFLITE
