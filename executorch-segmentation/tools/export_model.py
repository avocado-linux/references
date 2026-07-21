#!/usr/bin/env python3
"""Export DeepLabV3-MobileNetV3 to a PORTABLE ExecuTorch .pte -- run ONCE, offline.

This is NOT run by `avocado build`. Phase 1 keeps the build pip-free and fast by
committing the resulting `app/models/segmentation.pte` to the repo. Re-run this
only when you want to regenerate or swap the model.

    # one-time, on any machine with Python >= 3.10:
    python -m venv .venv && . .venv/bin/activate
    # Pin torch to the version executorch 1.3.1 was built against (2.12), or the
    # runtime pybindings hit an ABI mismatch (materialize_cow_storage).
    pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        "torch==2.12.*" "torchvision==0.27.*" "executorch==1.3.*"
    python tools/export_model.py

We lower with plain `to_edge()` and NO backend partitioner, so every operator
is a portable CPU kernel -- matching Avocado's portable-only `executorch`
package. The runner in app/src/ preprocesses to INPUT_SIZE and reads the
(1, 21, H, W) class-logit output; keep INPUT_SIZE in sync with kInputSize in
app/src/main.cpp.
"""

import os

import torch
import torchvision
from executorch.exir import to_edge

INPUT_SIZE = 256  # keep in sync with kInputSize in app/src/main.cpp
OUT = os.path.join(os.path.dirname(__file__), "..", "app", "models", "segmentation.pte")


def main() -> None:
    weights = torchvision.models.segmentation.DeepLabV3_MobileNet_V3_Large_Weights.DEFAULT
    model = torchvision.models.segmentation.deeplabv3_mobilenet_v3_large(
        weights=weights
    ).eval()

    # torchvision segmentation models return a dict {"out": logits, ...};
    # expose just the class-logit tensor so the .pte has a single tensor output.
    class SegOnly(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, x):
            return self.m(x)["out"]

    example = (torch.rand(1, 3, INPUT_SIZE, INPUT_SIZE),)
    exported = torch.export.export(SegOnly(model), example)
    program = to_edge(exported).to_executorch()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(program.buffer)
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB), input {INPUT_SIZE}x{INPUT_SIZE}")


if __name__ == "__main__":
    main()
