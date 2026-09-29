#!/usr/bin/env bash
#
# Report which ops Vela leaves on the CPU for the INT8 model, and fail the build
# when the CPU share of operators is over a limit. Vela only exists in the SDK on
# targets that add it through a target-<name>: override in avocado.yaml, so this
# is a no-op everywhere else (the 8M Plus runs through the VX delegate, which has
# no Vela step).
#
# MoveNet's decode (ArgMax, GatherNd, Sigmoid, casts and the quantize/dequantize
# boundaries) stays on the CPU by design. Measured with Vela 5.2.0 on this
# model: 29 CPU operators of 221 (13.1%). The default limit is a regression guard
# just above that, not a target; raise it with MAX_CPU_PCT if the model changes.

set -euo pipefail

MODEL="${1:?usage: check-op-placement.sh <model.tflite>}"
MAX_CPU_PCT="${MAX_CPU_PCT:-15}"
OUT_DIR="$(dirname "$MODEL")/vela"
SUMMARY="$OUT_DIR/vela-summary.txt"

if ! command -v vela >/dev/null 2>&1; then
    echo "vela not in this SDK; skipping op-placement report"
    exit 0
fi

# awk falls back to string comparison on a non-number (5% would never fail).
if ! [[ "$MAX_CPU_PCT" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    echo "ERROR: MAX_CPU_PCT must be a number, got '$MAX_CPU_PCT'" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"
vela --accelerator-config ethos-u65-256 --show-cpu-operations \
    --output-dir "$OUT_DIR" "$MODEL" >"$SUMMARY"

# The full per-op listing (NPU ops included) stays in $SUMMARY; the build log
# gets the counts and the CPU ops only.
grep -E '^(CPU|NPU) operators = |^   CPU: ' "$SUMMARY" || true

cpu_line="$(grep -E '^CPU operators = ' "$SUMMARY")" || {
    echo "ERROR: no operator summary in Vela output; see $SUMMARY" >&2
    exit 1
}
cpu_pct="$(sed -E 's/.*\( *([0-9.]+)%\).*/\1/' <<<"$cpu_line")"

echo ""
echo "Op placement: $cpu_line (limit ${MAX_CPU_PCT}%)"
if awk -v p="$cpu_pct" -v m="$MAX_CPU_PCT" 'BEGIN { exit !(p > m) }'; then
    echo "ERROR: CPU op share ${cpu_pct}% is over ${MAX_CPU_PCT}%; see $SUMMARY" >&2
    exit 1
fi
