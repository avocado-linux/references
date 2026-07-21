#!/usr/bin/env bash
#
# Install hook: stage the cross-compiled runner and the committed model into the
# extension sysroot. The systemd unit rides in app/overlay (merged automatically).

set -euo pipefail

BIN="app/src/build/executorch-segmentation"
MODEL="app/models/segmentation.pte"
DEST_BIN="$AVOCADO_BUILD_EXT_SYSROOT/usr/bin"
DEST_SHARE="$AVOCADO_BUILD_EXT_SYSROOT/usr/lib/executorch-segmentation"

if [ ! -f "$BIN" ]; then
    echo "ERROR: $BIN missing -- did app-compile.sh run?" >&2
    exit 1
fi

echo "Installing runner + model into the app extension"
install -D -m 0755 "$BIN" "$DEST_BIN/executorch-segmentation"
install -D -m 0644 "$MODEL" "$DEST_SHARE/segmentation.pte"

echo "Installed:"
ls -lh "$DEST_BIN/executorch-segmentation" "$DEST_SHARE/segmentation.pte"
