# Committed model

`segmentation.pte` (DeepLabV3-MobileNetV3, portable ExecuTorch) is committed here
so `avocado build` stays pip-free and fast. It is **not** produced by the build.

Regenerate it once, offline, only when you want to change/refresh the model:

```sh
# torch pinned to 2.12 to match executorch 1.3.1 (else the runtime pybindings
# hit an ABI mismatch). Validated on this pairing.
pip install --extra-index-url https://download.pytorch.org/whl/cpu \
    "torch==2.12.*" "torchvision==0.27.*" "executorch==1.3.*"
python tools/export_model.py   # writes app/models/segmentation.pte
```
