#!/usr/bin/env python3
"""Build a TensorRT engine from the YOLO ONNX model.

A TensorRT engine is specific to the exact GPU and TensorRT version, so it
cannot be prebuilt on a workstation and shipped — it must be built on the
device. This runs once at first boot (via yolo-engine-build.service) and
caches the result under /var/lib/app. app.py imports build_engine() as a
fallback so a manual `python3 app.py` works too.

The engine filename embeds the model basename, so swapping the ONNX (e.g.
yolo11n -> yolo11s) produces a different engine path and triggers a rebuild.
"""

import logging
import os
import sys

import tensorrt as trt

MODEL_PATH = os.environ.get("MODEL_PATH", "/usr/lib/app/models/yolo11n.onnx")
ENGINE_DIR = os.environ.get("ENGINE_DIR", "/var/lib/app")
# Read-only directory where a prebuilt engine is shipped in the image. Letting
# the reference embed an engine here means users never wait for the on-device
# build. It is GPU- and TensorRT-version-specific, so app.py rebuilds on-device
# if it ever fails to load (e.g. after a TensorRT bump in the feed).
PREBUILT_DIR = os.environ.get("PREBUILT_ENGINE_DIR", "/usr/lib/app/engines")
# 1 GiB workspace — plenty for yolo11n on the Orin Nano's shared memory.
WORKSPACE_BYTES = int(os.environ.get("TRT_WORKSPACE_BYTES", str(1 << 30)))

log = logging.getLogger("engine-build")


def engine_path_for(model_path, engine_dir=ENGINE_DIR):
    """Deterministic on-device cache path for a given ONNX model."""
    return os.path.join(engine_dir, os.path.basename(model_path) + ".fp16.engine")


def prebuilt_engine_for(model_path, prebuilt_dir=PREBUILT_DIR):
    """Path where a prebuilt engine for this model would ship in the image."""
    return os.path.join(prebuilt_dir, os.path.basename(model_path) + ".fp16.engine")


def build_engine(model_path=MODEL_PATH, engine_dir=ENGINE_DIR, fp16=True, force=False):
    """Build (or reuse) a TensorRT engine in the on-device cache. Returns the
    engine path.

    Idempotent unless ``force``: if the cached engine already exists it is
    returned untouched. ``force`` rebuilds even over an existing file (used by
    app.py when a shipped prebuilt engine fails to deserialize).
    """
    engine_path = engine_path_for(model_path, engine_dir)

    if os.path.exists(engine_path) and not force:
        log.info("engine already present: %s", engine_path)
        return engine_path

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"ONNX model not found: {model_path}")

    logger = trt.Logger(trt.Logger.INFO)
    builder = trt.Builder(logger)

    # TensorRT 10 networks are always explicit-batch; guard the flag so this
    # keeps working if the enum is dropped in a future release.
    flags = 0
    if hasattr(trt.NetworkDefinitionCreationFlag, "EXPLICIT_BATCH"):
        flags = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    network = builder.create_network(flags)

    parser = trt.OnnxParser(network, logger)
    log.info("parsing ONNX: %s", model_path)
    with open(model_path, "rb") as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                log.error("onnx parse error: %s", parser.get_error(i))
            raise RuntimeError("failed to parse ONNX model")

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, WORKSPACE_BYTES)

    if fp16 and builder.platform_has_fast_fp16:
        config.set_flag(trt.BuilderFlag.FP16)
        log.info("FP16 enabled")
    else:
        log.warning("FP16 not enabled (unsupported or disabled) — building FP32")

    log.info("building TensorRT engine — this can take a minute or two...")
    serialized = builder.build_serialized_network(network, config)
    if serialized is None:
        raise RuntimeError("engine build failed (build_serialized_network returned None)")

    os.makedirs(engine_dir, exist_ok=True)
    # Write atomically so a crash mid-write never leaves a truncated engine.
    tmp_path = engine_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(serialized)
    os.replace(tmp_path, engine_path)

    size_mb = os.path.getsize(engine_path) / (1024 * 1024)
    log.info("engine written: %s (%.1f MB)", engine_path, size_mb)
    return engine_path


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    try:
        # If a prebuilt engine ships in the image, the app loads it directly —
        # there's nothing to build here, so the oneshot service finishes
        # instantly and the user never waits. Only build (into the /var cache)
        # when no prebuilt exists for this model, e.g. after a model swap. If a
        # shipped prebuilt is stale (TensorRT bump), app.py rebuilds at startup.
        prebuilt = prebuilt_engine_for(MODEL_PATH)
        if os.path.exists(prebuilt):
            log.info("prebuilt engine present (%s) — skipping on-device build", prebuilt)
        else:
            build_engine()
    except Exception as e:
        log.error("engine build failed: %s", e)
        sys.exit(1)
