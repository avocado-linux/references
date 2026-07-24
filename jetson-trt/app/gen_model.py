#!/usr/bin/env python3
"""Generate a tiny, valid ONNX model at build time.

We synthesize the model instead of committing a binary so the reference stays
source-only and reproducible. It is a trivial fully-connected classifier
(Gemm -> Relu): input `input` [1, 64] float32 -> output `output` [1, 16]
float32. Swap in your own .onnx to run a real workload -- the app is agnostic
to the graph as long as it has one float32 input and one float32 output.
"""
import sys

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

IN_DIM, OUT_DIM = 64, 16


def main(out_path):
    rng = np.random.default_rng(0)
    w = numpy_helper.from_array(
        rng.standard_normal((IN_DIM, OUT_DIM)).astype(np.float32), name="W")
    b = numpy_helper.from_array(
        rng.standard_normal((OUT_DIM,)).astype(np.float32), name="B")

    gemm = helper.make_node("Gemm", ["input", "W", "B"], ["gemm_out"])
    relu = helper.make_node("Relu", ["gemm_out"], ["output"])

    graph = helper.make_graph(
        [gemm, relu],
        "tiny-fc-classifier",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, IN_DIM])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, OUT_DIM])],
        initializer=[w, b],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, out_path)
    print(f"wrote {out_path} ({IN_DIM} -> {OUT_DIM})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "model.onnx")
