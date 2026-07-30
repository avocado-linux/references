#!/usr/bin/env python3
"""x86 RTX GPU inference dashboard.

Builds a TensorRT-RTX engine from a bundled ONNX model, runs continuous
inference on the discrete NVIDIA GPU, and serves live throughput/latency stats.

Stack exercised end to end:
    nvidia.ko + libcuda (base image driver)
      -> CUDA runtime (from avocado-ext-nvidia-tensorrt-rtx)
        -> TensorRT-RTX engine build (JIT for this GPU's arch, e.g. Ada sm_89)
          -> execution with cuda-python device buffers

This is a reference/starting point: swap MODEL_PATH for your own ONNX and the
worker will run it as long as it has a single float32 input and output.
"""
import os
import shutil
import subprocess
import sys
import threading
import time

# pip-installed deps (flask, cuda-python) are staged here by app-install.sh.
sys.path.insert(0, "/usr/lib/app/packages")

import numpy as np
import tensorrt_rtx as trt

# cuda-python moved the runtime API across versions; support both spellings.
try:
    from cuda import cudart
except ImportError:  # newer cuda-python (cuda-core)
    from cuda.bindings import runtime as cudart

MODEL_PATH = os.environ.get("APP_MODEL", "/usr/lib/app/models/model.onnx")
ENGINE_CACHE = os.environ.get("APP_ENGINE_CACHE", "/var/cache/app/engine.plan")
HOST = "0.0.0.0"
PORT = int(os.environ.get("APP_PORT", "8080"))

TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

STATS = {
    "gpu": "unknown",
    "trt_version": getattr(trt, "__version__", "?"),
    "engine_build_ms": None,
    "engine_cached": False,
    "infers_per_sec": 0.0,
    "mean_latency_ms": 0.0,
    "total_infers": 0,
    "status": "starting",
    "error": None,
}
_LOCK = threading.Lock()


def cuda_check(ret):
    """Unwrap a cuda-python call: (err, *vals) -> vals, raising on error."""
    if isinstance(ret, tuple):
        err, *rest = ret
    else:
        err, rest = ret, []
    if int(err) != 0:
        raise RuntimeError(f"CUDA error {err}")
    return rest[0] if len(rest) == 1 else tuple(rest)


def query_gpu_name():
    smi = shutil.which("nvidia-smi")
    if not smi:
        return "unknown (nvidia-smi missing)"
    try:
        return subprocess.check_output(
            [smi, "--query-gpu=name", "--format=csv,noheader"],
            text=True, timeout=15).strip().splitlines()[0]
    except Exception as e:  # noqa: BLE001
        return f"unavailable ({e})"


def build_engine():
    """Return a serialized TensorRT-RTX engine, using an on-disk cache."""
    if os.path.exists(ENGINE_CACHE):
        with open(ENGINE_CACHE, "rb") as f:
            STATS["engine_cached"] = True
            return f.read()

    builder = trt.Builder(TRT_LOGGER)
    network = builder.create_network(0)
    parser = trt.OnnxParser(network, TRT_LOGGER)
    with open(MODEL_PATH, "rb") as f:
        if not parser.parse(f.read()):
            msgs = "; ".join(str(parser.get_error(i)) for i in range(parser.num_errors))
            raise RuntimeError(f"ONNX parse failed: {msgs}")

    config = builder.create_builder_config()
    if hasattr(config, "set_memory_pool_limit"):
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 30)

    plan = builder.build_serialized_network(network, config)
    if plan is None:
        raise RuntimeError("build_serialized_network returned None")

    os.makedirs(os.path.dirname(ENGINE_CACHE), exist_ok=True)
    with open(ENGINE_CACHE, "wb") as f:
        f.write(bytes(plan))
    return bytes(plan)


def worker():
    try:
        STATS["gpu"] = query_gpu_name()

        t0 = time.perf_counter()
        plan = build_engine()
        runtime = trt.Runtime(TRT_LOGGER)
        engine = runtime.deserialize_cuda_engine(plan)
        if engine is None:
            raise RuntimeError("deserialize_cuda_engine returned None")
        STATS["engine_build_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        context = engine.create_execution_context()
        stream = cuda_check(cudart.cudaStreamCreate())

        # Allocate host + device buffers for every IO tensor.
        bufs = {}
        for i in range(engine.num_io_tensors):
            name = engine.get_tensor_name(i)
            dtype = trt.nptype(engine.get_tensor_dtype(name))
            shape = tuple(engine.get_tensor_shape(name))
            host = np.zeros(shape, dtype=dtype)
            dev = cuda_check(cudart.cudaMalloc(host.nbytes))
            context.set_tensor_address(name, int(dev))
            bufs[name] = {
                "host": host,
                "dev": dev,
                "nbytes": host.nbytes,
                "mode": engine.get_tensor_mode(name),
            }

        inputs = [n for n, b in bufs.items() if b["mode"] == trt.TensorIOMode.INPUT]
        outputs = [n for n, b in bufs.items() if b["mode"] == trt.TensorIOMode.OUTPUT]

        STATS["status"] = "running"
        rng = np.random.default_rng(0)
        window, wt0, count = 0, time.perf_counter(), 0
        lat_ewma = None

        while True:
            it0 = time.perf_counter()
            for n in inputs:
                bufs[n]["host"][...] = rng.standard_normal(
                    bufs[n]["host"].shape).astype(bufs[n]["host"].dtype)
                cuda_check(cudart.cudaMemcpyAsync(
                    bufs[n]["dev"], bufs[n]["host"].ctypes.data, bufs[n]["nbytes"],
                    cudart.cudaMemcpyKind.cudaMemcpyHostToDevice, stream))

            context.execute_async_v3(stream_handle=int(stream))

            for n in outputs:
                cuda_check(cudart.cudaMemcpyAsync(
                    bufs[n]["host"].ctypes.data, bufs[n]["dev"], bufs[n]["nbytes"],
                    cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, stream))
            cuda_check(cudart.cudaStreamSynchronize(stream))

            dt = time.perf_counter() - it0
            lat_ewma = dt if lat_ewma is None else 0.98 * lat_ewma + 0.02 * dt
            count += 1
            window += 1
            now = time.perf_counter()
            if now - wt0 >= 1.0:
                with _LOCK:
                    STATS["infers_per_sec"] = round(window / (now - wt0), 1)
                    STATS["mean_latency_ms"] = round(lat_ewma * 1000, 3)
                    STATS["total_infers"] = count
                window, wt0 = 0, now
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            STATS["status"] = "error"
            STATS["error"] = str(e)
        raise


PAGE = """<!doctype html><html><head><meta charset=utf-8>
<title>x86 RTX Inference</title><meta http-equiv=refresh content=2>
<style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:2rem}
h1{font-weight:600}.g{display:grid;grid-template-columns:max-content 1fr;gap:.4rem 1.5rem;font-size:1.1rem}
.k{color:#8fd}.v{font-variant-numeric:tabular-nums}.err{color:#f77}</style></head><body>
<h1>x86 RTX GPU Inference</h1><div class=g>%s</div>
<p style="color:#777;margin-top:2rem">JSON: <code>/api/stats</code> &middot; refreshes every 2s</p>
</body></html>"""


def render():
    with _LOCK:
        s = dict(STATS)
    rows = [
        ("GPU", s["gpu"]),
        ("TensorRT-RTX", s["trt_version"]),
        ("Status", s["status"]),
        ("Engine build", f'{s["engine_build_ms"]} ms'
            + (" (cached)" if s["engine_cached"] else "")),
        ("Inferences/sec", s["infers_per_sec"]),
        ("Mean latency", f'{s["mean_latency_ms"]} ms'),
        ("Total inferences", s["total_infers"]),
    ]
    body = "".join(f'<div class=k>{k}</div><div class=v>{v}</div>' for k, v in rows)
    if s["error"]:
        body += f'<div class=k>Error</div><div class="v err">{s["error"]}</div>'
    return PAGE % body


def main():
    threading.Thread(target=worker, daemon=True).start()

    from flask import Flask, jsonify
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render()

    @app.get("/api/stats")
    def stats():
        with _LOCK:
            return jsonify(dict(STATS))

    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
