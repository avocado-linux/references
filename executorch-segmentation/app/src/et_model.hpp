// Thin RAII wrapper around ExecuTorch's high-level Module API (load + run a
// .pte). Every ExecuTorch call in this project lives here, so there is exactly
// one place to reconcile if the installed executorch 1.3.1 headers differ.
//
// IMPORTANT: this uses ONLY what Avocado's portable-only `executorch` package
// ships -- the core tensor types + `extension_module`/`portable_ops`. In
// particular it does NOT use `extension_tensor` (from_blob / TensorPtr), which
// that package does not build, so this reference needs no meta-avocado changes.
// Input tensors are built directly on the core TensorImpl over borrowed data.
#pragma once

#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <executorch/extension/module/module.h>
#include <executorch/runtime/core/exec_aten/exec_aten.h>

namespace etm {

using ::executorch::aten::DimOrderType;
using ::executorch::aten::ScalarType;
using ::executorch::aten::SizesType;
using ::executorch::aten::StridesType;
using ::executorch::aten::Tensor;
using ::executorch::aten::TensorImpl;
using ::executorch::extension::Module;
using ::executorch::runtime::Error;
using ::executorch::runtime::EValue;

// A float input tensor: borrowed data pointer + its shape.
struct Input {
  const float* data;
  std::vector<int32_t> shape;
};

// Owns the metadata backing one borrowed-data Tensor for a forward() call.
// The Tensor references `data` and this object's arrays, so it must outlive
// the call (EtModel::forward keeps the holders alive for exactly that long).
struct TensorHolder {
  std::vector<SizesType> sizes;
  std::vector<DimOrderType> dim_order;
  std::vector<StridesType> strides;
  std::unique_ptr<TensorImpl> impl;
  Tensor tensor;

  TensorHolder(const float* data, const std::vector<int32_t>& shape)
      : tensor(nullptr) {
    const size_t n = shape.size();
    sizes.assign(shape.begin(), shape.end());
    dim_order.resize(n);
    strides.resize(n);
    for (size_t i = 0; i < n; ++i)
      dim_order[i] = static_cast<DimOrderType>(i);
    if (n > 0) {
      strides[n - 1] = 1;
      for (size_t i = n - 1; i > 0; --i)
        strides[i - 1] = strides[i] * sizes[i];  // contiguous (row-major)
    }
    impl = std::make_unique<TensorImpl>(
        ScalarType::Float, static_cast<ssize_t>(n), sizes.data(),
        const_cast<float*>(data), dim_order.data(), strides.data());
    tensor = Tensor(impl.get());
  }
};

class EtModel {
 public:
  explicit EtModel(const std::string& pte_path) : module_(pte_path) {
    if (module_.load() != Error::Ok)
      throw std::runtime_error("ExecuTorch: failed to load " + pte_path);
  }

  // Run forward and return each output tensor's contents copied out row-major.
  // The input `data` pointers must stay valid for the duration of this call.
  std::vector<std::vector<float>> forward(const std::vector<Input>& inputs) {
    std::vector<std::unique_ptr<TensorHolder>> holders;
    std::vector<EValue> evalues;
    holders.reserve(inputs.size());
    evalues.reserve(inputs.size());
    for (const auto& in : inputs) {
      holders.push_back(std::make_unique<TensorHolder>(in.data, in.shape));
      evalues.emplace_back(holders.back()->tensor);
    }

    auto result = module_.forward(evalues);
    if (!result.ok())
      throw std::runtime_error("ExecuTorch: forward() failed");

    std::vector<std::vector<float>> outputs;
    outputs.reserve(result->size());
    for (const auto& ev : *result) {
      const auto tensor = ev.toTensor();
      const float* p = tensor.const_data_ptr<float>();
      outputs.emplace_back(p, p + tensor.numel());
    }
    return outputs;
  }

 private:
  Module module_;
};

}  // namespace etm
