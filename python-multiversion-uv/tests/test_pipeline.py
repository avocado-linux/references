"""Host-side pipeline smoke test for the multiversion-uv reference.

Runs the three fleet apps against a local nats-server and asserts the data
pipeline completes end to end: a sample window produced by app311 is processed
by app312 and aggregated by app314, which emits a single `pipeline_complete`
event naming all three contributing apps plus the aggregate result.

This validates the pipeline LOGIC only. All three apps run on the host's single
interpreter here, so it does NOT prove per-app Python version isolation -- that
is proven at boot, where each app runs on its own pinned CPython (see
getting_started.md). The two proofs are deliberately separate: this test is the
fast iteration loop, the boot is the isolation gate.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
NATS_SERVER = REPO / "broker" / "bin" / "nats-server"
APPS = {
    "app311": REPO / "app311" / "overlay" / "usr" / "local" / "bin" / "app311.py",
    "app312": REPO / "app312" / "overlay" / "usr" / "local" / "bin" / "app312.py",
    "app314": REPO / "app314" / "overlay" / "usr" / "local" / "bin" / "app314.py",
}
DEPS = ["nats-py", "numpy", "scipy"]
TIMEOUT_S = 45


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def broker():
    if not NATS_SERVER.exists():
        pytest.skip(f"nats-server not vendored at {NATS_SERVER}; run broker-compile.sh")
    port = _free_port()
    proc = subprocess.Popen(
        [str(NATS_SERVER), "-a", "127.0.0.1", "-p", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)
    try:
        yield f"nats://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _run_app(path: Path, nats_url: str) -> subprocess.Popen:
    env = {**os.environ, "FLEET_NATS_URL": nats_url}
    cmd = ["uv", "run", "--quiet"]
    for dep in DEPS:
        cmd += ["--with", dep]
    cmd += ["python", str(path)]
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def test_pipeline_completes(broker):
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH")

    procs = {name: _run_app(path, broker) for name, path in APPS.items()}
    coordinator = procs["app314"]
    complete = None
    deadline = time.monotonic() + TIMEOUT_S
    try:
        while time.monotonic() < deadline:
            line = coordinator.stdout.readline()
            if not line:
                if coordinator.poll() is not None:
                    break
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("event") == "pipeline_complete":
                complete = obj
                break
    finally:
        for proc in procs.values():
            proc.send_signal(signal.SIGINT)
        for proc in procs.values():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    assert complete is not None, "app314 never emitted a pipeline_complete event"

    chain = complete.get("chain", {})
    assert set(chain) == {"producer", "processor", "aggregator"}, chain
    assert chain["producer"]["app"] == "app311"
    assert chain["processor"]["app"] == "app312"
    assert chain["aggregator"]["app"] == "app314"
    # The aggregate must carry a real numeric result, not an empty stub.
    assert complete.get("result"), complete
