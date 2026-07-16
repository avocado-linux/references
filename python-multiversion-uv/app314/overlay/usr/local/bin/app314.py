#!/usr/bin/env python3
"""Fleet aggregator/coordinator on its own pinned Python 3.14 interpreter.

Proves two things at runtime: the process runs on the exact CPython version this
app was built against, and it can import its own native dependencies from the
per-app package directory. It closes the NATS pipeline -- it consumes the
processor's (app312) statistics, uses scipy to fit a trend across a rolling
window, and logs a pipeline_complete event whose chain names all three
interpreters that touched the data. That single line is the fleet's proof that
three independently pinned Pythons collaborated on one result.
"""

import json
import os
import sys
import time

# --- per-app configuration (the only lines that differ between apps) ---------
APP = "app314"
PKG_DIR = "/usr/lib/app314/packages"
EXPECT = "3.14"
ROLE = "aggregator"
NATIVE = [("numpy", "numpy"), ("scipy", "scipy"), ("nats", "nats-py")]
# -----------------------------------------------------------------------------

sys.path.insert(0, PKG_DIR)

NATS_URL = os.environ.get("FLEET_NATS_URL", "nats://127.0.0.1:4222")
PROCESSED_SUBJECT = "fleet.pipeline.processed"
WINDOW_N = 3  # fit a trend across this many processed windows


def dep_versions():
    import importlib
    import importlib.metadata as meta

    out = {}
    for module, dist in NATIVE:
        try:
            importlib.import_module(module)  # proves the native wheel loads
            out[dist] = meta.version(dist)
        except Exception as exc:  # ABI mismatch or missing wheel surfaces here
            out[dist] = f"IMPORT FAILED: {exc}"
    return out


def identity():
    v = sys.version_info
    return {
        "app": APP,
        "role": ROLE,
        "python": f"{v.major}.{v.minor}.{v.micro}",
        "executable": sys.executable,
        "deps": dep_versions(),
    }


def log(obj):
    print(json.dumps(obj), flush=True)


def main():
    me = identity()
    log({"event": "startup", **me})

    short = f"{sys.version_info.major}.{sys.version_info.minor}"
    if short != EXPECT:
        log({"event": "version_mismatch", "expected": EXPECT, "got": short})

    # NATS is optional. The interpreter-and-deps proof above already stands, so
    # a missing broker must not take the service down.
    try:
        import asyncio
        import nats  # noqa: F401
    except Exception as exc:
        log({"event": "nats_unavailable", "error": str(exc)})
        while True:
            time.sleep(3600)

    asyncio.run(run(me))


async def connect():
    import asyncio

    import nats

    while True:
        try:
            nc = await nats.connect(
                NATS_URL, connect_timeout=5, max_reconnect_attempts=-1
            )
        except Exception as exc:
            log({"event": "nats_connect_retry", "error": str(exc)})
            await asyncio.sleep(3)
            continue
        log({"event": "nats_connected", "url": NATS_URL})
        return nc


async def run(me):
    import asyncio

    import numpy as np
    from scipy import stats as sps

    nc = await connect()
    window = []
    completed = False

    async def on_processed(msg):
        nonlocal completed
        try:
            processed = json.loads(msg.data.decode())
        except Exception:
            return
        window.append(processed)
        log({"event": "aggregating", "seq": processed["seq"], "have": len(window)})
        if len(window) < WINDOW_N:
            return

        batch = window[-WINDOW_N:]
        rms = np.array([b["stats"]["rms"] for b in batch], dtype=float)
        idx = np.arange(rms.size, dtype=float)
        fit = sps.linregress(idx, rms)  # scipy: trend across the window
        last = batch[-1]
        chain = {
            "producer": {"app": last["producer"], "python": last["producer_python"]},
            "processor": {"app": last["processor"], "python": last["processor_python"]},
            "aggregator": {"app": APP, "python": me["python"]},
        }
        result = {
            "window": WINDOW_N,
            "rms_mean": round(float(rms.mean()), 6),
            "rms_trend_slope": round(float(fit.slope), 6),
            "peak_hz": last["stats"]["peak_hz"],
        }
        # The first full window is the headline proof; later windows keep
        # logging so the pipeline visibly stays live.
        event = "pipeline_complete" if not completed else "pipeline_result"
        completed = True
        log({"event": event, "seq": last["seq"], "chain": chain, "result": result})

    await nc.subscribe(PROCESSED_SUBJECT, cb=on_processed)
    log({"event": "subscribed", "subject": PROCESSED_SUBJECT})
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    main()
