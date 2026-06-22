#!/usr/bin/env bash
#
# Post-build helper: inject a FIT signing pubkey into the U-Boot
# control DTB and rebuild flash.bin so the bootloader will only verify
# FIT images signed by the matching private key.
#
# Workflow:
#   1. Generate (or reuse) an RSA-2048 dev key under keys/.
#   2. Build a placeholder FIT image referencing key-name-hint=dev.
#   3. mkimage -K populates the placeholder /signature/key-rt-prod node
#      in the U-Boot DTB at $AVOCADO_BUILD_DIR/uboot-imx/u-boot.dtb.
#   4. Re-run imx-mkimage to fold the patched DTB back into flash.bin.
#   5. Re-run uboot-install.sh to refresh the runtime build dir.
#
# Run this OUTSIDE of `avocado build` (i.e., from the host shell after
# `avocado sdk compile uboot` has produced the initial flash.bin):
#
#     avocado sdk run -E -- bash insert-fit-pubkey.sh
#
# `-E` keeps the SDK env so mkimage / openssl from the SDK toolchain
# resolve, and bind-mounts the project dir as /opt/src.
#
set -euo pipefail

UBOOT_DEFCONFIG="imx8mp_evk_defconfig"
MKIMAGE_SOC="iMX8MP"
MKIMAGE_TARGET="flash_evk"

KEY_NAME="dev"
KEYS_DIR="$(pwd)/keys"
BUILD_ROOT="${AVOCADO_BUILD_DIR:-$AVOCADO_SDK_PREFIX/build/uboot}"
UBOOT_DIR="${BUILD_ROOT}/uboot-imx"
MKIMAGE_DIR="${BUILD_ROOT}/imx-mkimage"
STAGE="${MKIMAGE_DIR}/iMX8M"

if [ ! -d "${UBOOT_DIR}" ]; then
  echo "[ERROR] No U-Boot build at ${UBOOT_DIR}." >&2
  echo "        Run 'avocado sdk compile uboot' first." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. Generate the dev RSA key if missing. Production keys are HSM-backed;
#    this helper only handles the dev workflow.
# ---------------------------------------------------------------------------
mkdir -p "${KEYS_DIR}"
if [ ! -f "${KEYS_DIR}/${KEY_NAME}.key" ]; then
  echo "Generating dev RSA-2048 key at ${KEYS_DIR}/${KEY_NAME}.key"
  openssl genpkey -algorithm RSA -out "${KEYS_DIR}/${KEY_NAME}.key" \
    -pkeyopt rsa_keygen_bits:2048
  openssl req -batch -new -x509 \
    -key "${KEYS_DIR}/${KEY_NAME}.key" \
    -out "${KEYS_DIR}/${KEY_NAME}.crt" \
    -subj "/CN=Avocado FIT Dev/"
fi

# ---------------------------------------------------------------------------
# 2. Build a minimal FIT image with a dummy payload referenced by a
#    `signed-config` node. mkimage -K reads the FIT, signs the config,
#    and copies the resulting pubkey into the U-Boot DTB's signature
#    node. The signed FIT itself is throwaway here; the real FIT comes
#    later (e.g. a kernel + dtb + ramdisk image).
# ---------------------------------------------------------------------------
ITS="${BUILD_ROOT}/avocado-fit-pubkey.its"
ITB="${BUILD_ROOT}/avocado-fit-pubkey.itb"

cat > "${ITS}" << EOF
/dts-v1/;

/ {
	description = "Pubkey-injection placeholder";
	#address-cells = <1>;

	images {
		blob {
			data = /incbin/("/dev/null");
			type = "kernel";
			arch = "arm64";
			os = "linux";
			compression = "none";
			load = <0x80200000>;
			entry = <0x80200000>;
			hash-1 { algo = "sha256"; };
		};
	};

	configurations {
		default = "conf-1";
		conf-1 {
			description = "Avocado pubkey-injection config";
			kernel = "blob";
			signature {
				algo = "sha256,rsa2048";
				key-name-hint = "${KEY_NAME}";
				sign-images = "kernel";
			};
		};
	};
};
EOF

# `mkimage -f` builds the .itb. `mkimage -F -K` re-signs and writes the
# pubkey into the target DTB (-K).
"${UBOOT_DIR}/tools/mkimage" -f "${ITS}" -r "${ITB}"
"${UBOOT_DIR}/tools/mkimage" -F -k "${KEYS_DIR}" -K "${UBOOT_DIR}/u-boot.dtb" -r "${ITB}"

echo "Patched ${UBOOT_DIR}/u-boot.dtb with pubkey '${KEY_NAME}'."

# ---------------------------------------------------------------------------
# 3. Re-stage and rebuild flash.bin so the patched DTB takes effect.
# ---------------------------------------------------------------------------
echo "Re-staging u-boot artifacts..."
cp -f "${UBOOT_DIR}/u-boot-nodtb.bin" "${STAGE}/"
cp -f "${UBOOT_DIR}/u-boot.dtb"       "${STAGE}/"
cp -f "${UBOOT_DIR}/u-boot.bin"       "${STAGE}/"

echo "Rebuilding flash.bin..."
make -C "${MKIMAGE_DIR}" SOC="${MKIMAGE_SOC}" "${MKIMAGE_TARGET}"
cp -f "${MKIMAGE_DIR}/iMX8M/flash.bin" "${BUILD_ROOT}/flash.bin"

echo ""
echo "================================================================"
echo "Updated flash.bin: ${BUILD_ROOT}/flash.bin"
echo ""
echo "Next:"
echo "  - 'avocado build' to refresh the runtime build dir."
echo "  - Sign your real FIT image with:"
echo "      mkimage -F -k keys -r <fit-image.itb>"
echo "  - The bootloader will only load FITs signed by '${KEY_NAME}'."
echo "================================================================"
