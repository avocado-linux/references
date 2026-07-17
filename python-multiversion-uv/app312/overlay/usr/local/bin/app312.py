#!/usr/bin/env python3
"""Fleet processor on its own pinned Python 3.12 interpreter.

Proves two things at runtime: the process runs on the exact CPython version this
app was built against, and it can import its own native dependencies from the
per-app package directory. It sits in the middle of the NATS pipeline -- it
consumes raw sample windows from the producer (app311), reduces each one to a
handful of numpy statistics, and republishes the result on
fleet.pipeline.processed for the aggregator (app314).
"""

import json
import os
import sys
import time

# --- per-app configuration (the only lines that differ between apps) ---------
APP = "app312"
PKG_DIR = "/usr/lib/app312/packages"
EXPECT = "3.12"
ROLE = "processor"
NATIVE = [("numpy", "numpy"), ("nats", "nats-py"), ("mcap", "mcap")]
# -----------------------------------------------------------------------------

sys.path.insert(0, PKG_DIR)

NATS_URL = os.environ.get("FLEET_NATS_URL", "nats://127.0.0.1:4222")
RAW_SUBJECT = "fleet.pipeline.raw"
PROCESSED_SUBJECT = "fleet.pipeline.processed"


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

    async def on_raw(msg):
        try:
            raw = json.loads(msg.data.decode())
        except Exception:
            return
        x = np.asarray(raw["samples"], dtype=float)
        spectrum = np.abs(np.fft.rfft(x))
        freqs = np.fft.rfftfreq(x.size, d=1.0 / raw["sample_rate"])
        # skip the DC bin (index 0) when locating the dominant tone
        peak_hz = float(freqs[1 + int(np.argmax(spectrum[1:]))]) if x.size > 1 else 0.0
        out = {
            "seq": raw["seq"],
            "producer": raw["producer"],
            "producer_python": raw["producer_python"],
            "processor": APP,
            "processor_python": me["python"],
            "stats": {
                "mean": round(float(x.mean()), 6),
                "std": round(float(x.std()), 6),
                "rms": round(float(np.sqrt(np.mean(x**2))), 6),
                "peak_hz": round(peak_hz, 3),
            },
        }
        try:
            await nc.publish(PROCESSED_SUBJECT, json.dumps(out).encode())
            await nc.flush(timeout=5)
        except Exception as exc:
            log({"event": "nats_lost", "error": str(exc)})
            return
        log({"event": "processed", "seq": out["seq"], "peak_hz": out["stats"]["peak_hz"]})

    await nc.subscribe(RAW_SUBJECT, cb=on_raw)
    log({"event": "subscribed", "subject": RAW_SUBJECT})
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    main()
