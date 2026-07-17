#!/usr/bin/env python3
"""Fleet producer on its own pinned Python 3.11 interpreter.

Proves two things at runtime: the process runs on the exact CPython version this
app was built against, and it can import its own native dependencies from the
per-app package directory. It then drives a NATS data pipeline -- it generates a
window of samples with numpy and publishes it on fleet.pipeline.raw for the
processor (app312) to consume.
"""

import json
import os
import sys
import time

# --- per-app configuration (the only lines that differ between apps) ---------
APP = "app311"
PKG_DIR = "/usr/lib/app311/packages"
EXPECT = "3.11"
ROLE = "producer"
NATIVE = [("numpy", "numpy"), ("nats", "nats-py")]
# -----------------------------------------------------------------------------

sys.path.insert(0, PKG_DIR)

NATS_URL = os.environ.get("FLEET_NATS_URL", "nats://127.0.0.1:4222")
RAW_SUBJECT = "fleet.pipeline.raw"

PERIOD_S = 2.0  # publish a fresh window this often
WINDOW = 64  # samples per window
SAMPLE_RATE = 64.0  # Hz -- one window is one second of signal
SIGNAL_HZ = 5.0  # the tone buried in the noise


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

    nc = await connect()

    t = np.arange(WINDOW) / SAMPLE_RATE
    seq = 0
    while True:
        seq += 1
        rng = np.random.default_rng(seq)  # seeded per window -> reproducible
        samples = np.sin(2 * np.pi * SIGNAL_HZ * t) + 0.3 * rng.standard_normal(WINDOW)
        payload = {
            "seq": seq,
            "producer": APP,
            "producer_python": me["python"],
            "sample_rate": SAMPLE_RATE,
            "samples": np.round(samples, 6).tolist(),
        }
        try:
            await nc.publish(RAW_SUBJECT, json.dumps(payload).encode())
            await nc.flush(timeout=5)
        except Exception as exc:
            log({"event": "nats_lost", "error": str(exc)})
            try:
                await nc.close()  # release the dropped client's reconnect tasks
            except Exception:
                pass
            nc = await connect()
            continue
        log({"event": "produced", "seq": seq, "n": WINDOW})
        await asyncio.sleep(PERIOD_S)


if __name__ == "__main__":
    main()
