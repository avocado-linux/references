#!/usr/bin/env bash
#
# Cross-compile imx-boot (TF-A BL31 + U-Boot SPL/proper + DDR firmware,
# bundled by imx-mkimage) for the i.MX 8M Plus EVK using the Avocado SDK.
#
# Components match nxp-imx/meta-imx @ scarthgap-6.6.36-2.1.0 (the layer
# avocado-os pulls into its imx8mp-evk build):
#   - uboot-imx        nxp-imx/uboot-imx       branch lf_v2024.04
#   - imx-atf          nxp-imx/imx-atf         branch lf_v2.10
#   - imx-mkimage      nxp-imx/imx-mkimage     branch lf-6.6.36_2.1.0
#   - firmware-imx     NXP redistributable     8.25-27879f8
#
# SRCREVs are pinned for reproducibility — bump together when bumping the
# avocado-os scarthgap pin.
#
# The SDK entrypoint sources the OE environment, so CROSS_COMPILE / ARCH /
# OECORE_NATIVE_SYSROOT / OECORE_TARGET_SYSROOT are already set. As with
# the Linux kernel build, the userspace CC/CFLAGS/LDFLAGS that the SDK
# also exports collide with U-Boot's and TF-A's internal build systems —
# we save what we need and unset the rest.
#
# Output: $AVOCADO_BUILD_DIR/flash.bin (the i.MX boot bundle, == imx-boot)
#
set -euo pipefail

UBOOT_BRANCH="lf_v2024.04"
UBOOT_SRCREV="de16f4f17221b2ff72b8cb18c28cd8a29f3c2710"
ATF_BRANCH="lf_v2.10"
ATF_SRCREV="28affcae957cb8194917b5246276630f9e6343e1"
MKIMAGE_BRANCH="lf-6.6.36_2.1.0"
MKIMAGE_SRCREV="4622115cbc037f79039c4522faeced4aabea986b"

FIRMWARE_IMX_VERSION="8.25"
FIRMWARE_IMX_SRCREV_ABBREV="27879f8"
FIRMWARE_IMX_TARBALL="firmware-imx-${FIRMWARE_IMX_VERSION}-${FIRMWARE_IMX_SRCREV_ABBREV}.bin"
FIRMWARE_IMX_DIR_NAME="firmware-imx-${FIRMWARE_IMX_VERSION}-${FIRMWARE_IMX_SRCREV_ABBREV}"
FIRMWARE_IMX_URL="https://www.nxp.com/lgfiles/NMG/MAD/YOCTO/${FIRMWARE_IMX_TARBALL}"

UBOOT_DEFCONFIG="imx8mp_evk_defconfig"
ATF_PLATFORM="imx8mp"
MKIMAGE_SOC="iMX8MP"
MKIMAGE_TARGET="flash_evk"

echo "================================================================"
echo "Compiling imx-boot for i.MX 8M Plus EVK"
echo "================================================================"

# ---------------------------------------------------------------------------
# Validate AVOCADO_BUILD_DIR (per-section dir set by `sdk compile`).
# ---------------------------------------------------------------------------
if [ -z "${AVOCADO_BUILD_DIR:-}" ]; then
  echo "[ERROR] AVOCADO_BUILD_DIR is not set." >&2
  exit 1
fi
mkdir -p "${AVOCADO_BUILD_DIR}"

# Cache downloads under the source dir so they survive `sdk clean` and
# don't re-fetch on every run. Source-tree clones live inside
# AVOCADO_BUILD_DIR so `sdk clean uboot` discards them.
HOST_SRC="$(pwd)"
DOWNLOADS="${HOST_SRC}/.downloads"
mkdir -p "${DOWNLOADS}"

UBOOT_DIR="${AVOCADO_BUILD_DIR}/uboot-imx"
ATF_DIR="${AVOCADO_BUILD_DIR}/imx-atf"
MKIMAGE_DIR="${AVOCADO_BUILD_DIR}/imx-mkimage"
FIRMWARE_DIR="${AVOCADO_BUILD_DIR}/${FIRMWARE_IMX_DIR_NAME}"
PATCHES_DIR="${HOST_SRC}/patches"

# ---------------------------------------------------------------------------
# Cross-compile environment.
#
# As with the kernel reference, the SDK exports a userspace toolchain
# (CC, CFLAGS, LDFLAGS, ...). U-Boot and TF-A derive their own toolchain
# from CROSS_COMPILE; the userspace exports fight that and produce
# linker errors. Save CROSS_COMPILE + a target sysroot for HOSTCC, then
# clear the rest.
# ---------------------------------------------------------------------------
_CROSS_COMPILE="${CROSS_COMPILE:-}"
if [ -z "${_CROSS_COMPILE}" ]; then
  echo "[ERROR] CROSS_COMPILE not exported by SDK env." >&2
  exit 1
fi
_TARGET_SYSROOT="${OECORE_TARGET_SYSROOT:-}"

unset CC CXX CPP LD AR AS NM STRIP OBJCOPY OBJDUMP READELF RANLIB
unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS

export CROSS_COMPILE="${_CROSS_COMPILE}"
export ARCH=arm64

# Derive HOSTCC from the SDK env. The Avocado SDK only ships the
# target-prefixed cross-canadian compiler (${CROSS_COMPILE}gcc); there
# is no separate native host gcc. The container has qemu-user
# registered via binfmt_misc, so the aarch64 host tools that U-Boot /
# TF-A produce (fixdep, mkimage, etc.) execute transparently on the
# x86_64 build host.
#
# This is the same trick the kernel reference uses, except there it
# works because qemux86-64 is same-arch. Here it works because of
# qemu-user emulation.
#
# The bare cross-compiler has no default sysroot; pass the SDK's
# target sysroot so #include <sys/types.h> and friends resolve.
HOSTCC="${CROSS_COMPILE}gcc --sysroot=${_TARGET_SYSROOT}"
HOSTCXX="${CROSS_COMPILE}g++ --sysroot=${_TARGET_SYSROOT}"
HOSTLD="${CROSS_COMPILE}ld"
HOSTAR="${CROSS_COMPILE}ar"

echo "ARCH=${ARCH}"
echo "CROSS_COMPILE=${CROSS_COMPILE}"
echo "HOSTCC=${HOSTCC}"
echo "HOSTCXX=${HOSTCXX}"

# ---------------------------------------------------------------------------
# Fetch sources.
# ---------------------------------------------------------------------------
# Pin to a specific SRCREV on the named branch. shallow-clone with
# --revision avoids fetching unrelated history while keeping the build
# reproducible — `--branch` alone would float on whatever HEAD is.
clone_pinned() {
  local url="$1" branch="$2" srcrev="$3" dest="$4"
  if [ ! -d "${dest}/.git" ]; then
    echo "Cloning ${url} (${branch} @ ${srcrev}) -> ${dest}"
    git -c advice.detachedHead=false clone --branch "${branch}" "${url}" "${dest}"
    git -C "${dest}" -c advice.detachedHead=false checkout "${srcrev}"
  else
    local current
    current="$(git -C "${dest}" rev-parse HEAD)"
    if [ "${current}" != "${srcrev}" ]; then
      echo "Updating ${dest} from ${current} to pinned ${srcrev}"
      git -C "${dest}" fetch --tags origin "${branch}"
      git -C "${dest}" -c advice.detachedHead=false checkout "${srcrev}"
    else
      echo "Reusing ${dest} (already at ${srcrev})"
    fi
  fi
}

clone_pinned "https://github.com/nxp-imx/uboot-imx.git"   "${UBOOT_BRANCH}"   "${UBOOT_SRCREV}"   "${UBOOT_DIR}"
clone_pinned "https://github.com/nxp-imx/imx-atf.git"     "${ATF_BRANCH}"     "${ATF_SRCREV}"     "${ATF_DIR}"
clone_pinned "https://github.com/nxp-imx/imx-mkimage.git" "${MKIMAGE_BRANCH}" "${MKIMAGE_SRCREV}" "${MKIMAGE_DIR}"

# firmware-imx is a self-extracting NXP installer. Cache the tarball on
# the host side; extract once into AVOCADO_BUILD_DIR.
if [ ! -f "${DOWNLOADS}/${FIRMWARE_IMX_TARBALL}" ]; then
  echo "Downloading ${FIRMWARE_IMX_URL}..."
  curl -fL --retry 3 -o "${DOWNLOADS}/${FIRMWARE_IMX_TARBALL}" "${FIRMWARE_IMX_URL}"
fi
if [ ! -d "${FIRMWARE_DIR}" ]; then
  echo "Extracting ${FIRMWARE_IMX_TARBALL}..."
  # The .bin is a shell-script-prefixed cpio archive. --auto-accept skips
  # the EULA prompt; the user is responsible for accepting NXP terms.
  (cd "${AVOCADO_BUILD_DIR}" && \
    sh "${DOWNLOADS}/${FIRMWARE_IMX_TARBALL}" --auto-accept --force >/dev/null)
fi

# ---------------------------------------------------------------------------
# Layer Avocado patches onto the U-Boot defconfig and DTS.
#
# patches/avocado.cfg     — adds CONFIG_IMX_HAB=y, FIT signature support,
#                           Avocado partition recognition.
# patches/env-mmc.cfg     — wires ENV_IS_IN_MMC + redundant env layout.
# patches/avocado-imx8mp-evk.txt
#                         — A/B boot env script (matches Avocado's
#                           rootdisk layout).
# patches/avocado-fit-signature.dtsi
#                         — placeholder /signature node in the U-Boot
#                           control DTB. mkimage -K populates it
#                           post-build with the FIT signing pubkey.
# ---------------------------------------------------------------------------
echo "Applying Avocado config overlay to ${UBOOT_DEFCONFIG}..."
cat "${PATCHES_DIR}/avocado.cfg"   >> "${UBOOT_DIR}/configs/${UBOOT_DEFCONFIG}"
cat "${PATCHES_DIR}/env-mmc.cfg"  >> "${UBOOT_DIR}/configs/${UBOOT_DEFCONFIG}"

# Inject the FIT signature placeholder into the board DTS via an #include.
# The dtsi declares /signature/key-rt-prod with required-conf=true but
# leaves rsa,n / rsa,e / rsa,modulus empty so mkimage -K fills them in
# from the dev key after the bootloader image is signed.
EVK_DTS="${UBOOT_DIR}/arch/arm/dts/imx8mp-evk-u-boot.dtsi"
if ! grep -q "avocado-fit-signature" "${EVK_DTS}"; then
  cp "${PATCHES_DIR}/avocado-fit-signature.dtsi" \
     "${UBOOT_DIR}/arch/arm/dts/avocado-fit-signature.dtsi"
  printf '\n#include "avocado-fit-signature.dtsi"\n' >> "${EVK_DTS}"
fi

# Boot env. The MKENVIMAGE_EXTRA_ARGS=-r flag in Yocto produces a
# redundant env image; we use mkenvimage from the U-Boot tools tree.
cp "${PATCHES_DIR}/avocado-imx8mp-evk.txt" "${UBOOT_DIR}/avocado-boot-env.txt"

# ---------------------------------------------------------------------------
# Build TF-A (BL31).
# ---------------------------------------------------------------------------
echo "Building TF-A BL31 for ${ATF_PLATFORM}..."
make -C "${ATF_DIR}" -j"$(nproc)" \
  PLAT="${ATF_PLATFORM}" \
  IMX_BOOT_UART_BASE=0x30890000 \
  bl31

# ---------------------------------------------------------------------------
# Build U-Boot.
# ---------------------------------------------------------------------------
UBOOT_MAKE_ARGS=(
  HOSTCC="${HOSTCC}"
  HOSTCXX="${HOSTCXX}"
  HOSTLD="${HOSTLD}"
  HOSTAR="${HOSTAR}"
)

echo "Configuring U-Boot with ${UBOOT_DEFCONFIG}..."
make -C "${UBOOT_DIR}" -j"$(nproc)" "${UBOOT_MAKE_ARGS[@]}" "${UBOOT_DEFCONFIG}"

echo "Building U-Boot..."
make -C "${UBOOT_DIR}" -j"$(nproc)" "${UBOOT_MAKE_ARGS[@]}" all

# Build the redundant env image for the uboot-env partition. fwsetenv
# on-device reads/writes this format.
echo "Generating u-boot redundant env image..."
"${UBOOT_DIR}/tools/mkenvimage" -r -s 0x20000 -o "${AVOCADO_BUILD_DIR}/uboot.env" \
  "${UBOOT_DIR}/avocado-boot-env.txt"

# ---------------------------------------------------------------------------
# Stage TF-A, U-Boot, and DDR firmware blobs into imx-mkimage's iMX8M dir.
#
# imx-mkimage's iMX8M/Makefile expects fixed filenames in iMX8M/. See
# https://github.com/nxp-imx/imx-mkimage/blob/master/iMX8M/soc.mak for
# the full list per SoC.
# ---------------------------------------------------------------------------
STAGE="${MKIMAGE_DIR}/iMX8M"
echo "Staging boot blobs into ${STAGE}..."
cp -f "${UBOOT_DIR}/tools/mkimage"        "${STAGE}/mkimage_uboot"
cp -f "${UBOOT_DIR}/spl/u-boot-spl.bin"   "${STAGE}/"
cp -f "${UBOOT_DIR}/u-boot-nodtb.bin"     "${STAGE}/"
cp -f "${UBOOT_DIR}/arch/arm/dts/imx8mp-evk.dtb" "${STAGE}/"
cp -f "${UBOOT_DIR}/u-boot.bin"           "${STAGE}/"
cp -f "${ATF_DIR}/build/${ATF_PLATFORM}/release/bl31.bin" "${STAGE}/"
cp -f "${FIRMWARE_DIR}/firmware/ddr/synopsys/lpddr4_pmu_train_1d_imem_202006.bin" "${STAGE}/"
cp -f "${FIRMWARE_DIR}/firmware/ddr/synopsys/lpddr4_pmu_train_1d_dmem_202006.bin" "${STAGE}/"
cp -f "${FIRMWARE_DIR}/firmware/ddr/synopsys/lpddr4_pmu_train_2d_imem_202006.bin" "${STAGE}/"
cp -f "${FIRMWARE_DIR}/firmware/ddr/synopsys/lpddr4_pmu_train_2d_dmem_202006.bin" "${STAGE}/"

# ---------------------------------------------------------------------------
# Build flash.bin (== imx-boot).
# ---------------------------------------------------------------------------
echo "Building flash.bin via imx-mkimage SOC=${MKIMAGE_SOC} flash_evk..."
make -C "${MKIMAGE_DIR}" \
  SOC="${MKIMAGE_SOC}" \
  "${MKIMAGE_TARGET}"

cp -f "${MKIMAGE_DIR}/iMX8M/flash.bin" "${AVOCADO_BUILD_DIR}/flash.bin"

echo ""
echo "================================================================"
echo "imx-boot build complete:"
echo "  ${AVOCADO_BUILD_DIR}/flash.bin"
echo "  ${AVOCADO_BUILD_DIR}/uboot.env"
echo ""
echo "Bootloader is HAB-enabled. To produce a signed flash.bin you must"
echo "generate a CSF block with NXP's CST and append it; see"
echo "patches/avocado-fit-signature.dtsi and the README for the"
echo "post-build pubkey insertion / signing workflow."
echo "================================================================"
