#!/usr/bin/env bash
# Cross-compile the guest demo and pack it as the guests' initramfs.
#
# Runs inside the SDK container during `avocado build`. The SDK entrypoint has
# already sourced the OE environment, so $CC is the Avocado aarch64 cross
# compiler with the target sysroot attached. Use it as-is -- do not substitute
# a host gcc or a toolchain out of a Yocto build tree; those are different
# compilers against different sysroots and building against them proves
# nothing about what ships.
#
# Output: $AVOCADO_BUILD_DIR/guest-initramfs.cpio.gz, consumed by
# guest-install.sh.
set -euo pipefail

: "${AVOCADO_BUILD_DIR:?AVOCADO_BUILD_DIR not set}"
: "${CC:?CC not set -- the SDK environment was not sourced}"

ROOT="${AVOCADO_BUILD_DIR}/root"
rm -rf "$ROOT"
mkdir -p "$ROOT/proc" "$ROOT/sys" "$ROOT/dev"

echo "Cross-compiling shmdemo with: $CC"
# -static: the initramfs holds exactly one file, so there is no loader and no
# libc in it to find.
#
# -O3, and it has to come after the -O2 the SDK's CC already carries (gcc takes
# the last -O it sees). This is not cargo-culted: at -O2 gcc's "very-cheap"
# vectoriser cost model refuses to vectorise a loop whose trip count is a
# runtime value, which every payload loop in this demo is, so the 4096-byte
# payload compiled to 512 discrete single-word stores. -O3 raises the cost
# model and the same loops come out as NEON pair stores. Verified by
# disassembling the result, not assumed -- see the stp q count in the build log.
# shellcheck disable=SC2086
$CC -static -O3 -Wall -Wextra -o "$ROOT/init" guest/shmdemo.c

# Fail the build if the payload loops did not vectorise. The whole point of
# devolatilising them was to let this happen; if a toolchain change silently
# takes it away, the demo would still pass and just get slower, which is the
# kind of regression that never gets noticed.
if command -v "${CC%% *}"-objdump >/dev/null 2>&1 || command -v aarch64-avocado-linux-objdump >/dev/null 2>&1; then
    neon=$(aarch64-avocado-linux-objdump -d "$ROOT/init" | grep -cE 'st[pr][[:space:]]+q[0-9]' || true)
    echo "NEON payload stores: $neon"
    if [ "$neon" -eq 0 ]; then
        echo "ERROR: payload loops did not vectorise -- expected NEON stores" >&2
        exit 1
    fi
fi
chmod 0755 "$ROOT/init"

file "$ROOT/init" 2>/dev/null || true

echo "Packing initramfs..."
# No device nodes: an unprivileged cpio cannot create them, which is exactly
# why the demo mounts devtmpfs and opens /dev/console itself.
( cd "$ROOT" && find . -print0 | cpio --null --create --format=newc --quiet ) \
    | gzip -9 > "${AVOCADO_BUILD_DIR}/guest-initramfs.cpio.gz"

ls -l "${AVOCADO_BUILD_DIR}/guest-initramfs.cpio.gz"
echo "Compile step complete."
