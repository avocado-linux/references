#!/usr/bin/env python3
"""Fleet app running on its own pinned Python interpreter.

Proves two things at runtime: the process runs on the exact CPython version this
app was built against, and it can import its own native dependencies from the
per-app package directory. As the coordinator it also tallies the fleet: once it
has seen a hello from all three interpreters it logs a fleet_complete event.
"""

import json
import os
import sys
import time

# --- per-app configuration (the only lines that differ between apps) ---------
APP = "app314"
PKG_DIR = "/usr/lib/app314/packages"
EXPECT = "3.14"
ROLE = "coordinator"
NATIVE = [("numpy", "numpy"), ("scipy", "scipy"), ("nats", "nats-py")]
# -----------------------------------------------------------------------------

sys.path.insert(0, PKG_DIR)

NATS_URL = os.environ.get("FLEET_NATS_URL", "nats://127.0.0.1:4222")
SUBJECT = "fleet.hello"
EXPECTED_VERSIONS = {"3.11", "3.12", "3.14"}


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

    asyncio.run(run_nats(me))


async def run_nats(me):
    import asyncio

    import nats

    seen = {}  # major.minor -> app name (coordinator only)

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

        async def on_hello(msg):
            try:
                peer = json.loads(msg.data.decode())
            except Exception:
                return
            if ROLE != "coordinator":
                return
            seen[peer["python"].rsplit(".", 1)[0]] = peer["app"]
            log({"event": "roster", "seen": seen})
            if EXPECTED_VERSIONS <= set(seen):
                log({"event": "fleet_complete", "interpreters": sorted(seen)})

        await nc.subscribe(SUBJECT, cb=on_hello)

        try:
            while True:
                await nc.publish(SUBJECT, json.dumps(me).encode())
                await nc.flush(timeout=5)
                await asyncio.sleep(5)
        except Exception as exc:
            log({"event": "nats_lost", "error": str(exc)})
            try:
                await nc.close()
            except Exception:
                pass
            await asyncio.sleep(3)


if __name__ == "__main__":
    main()
