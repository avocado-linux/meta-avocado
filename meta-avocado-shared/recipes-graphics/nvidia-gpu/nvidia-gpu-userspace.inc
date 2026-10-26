# Shared include for NVIDIA proprietary .run driver installer
# Used by nvidia-gpu-userspace and nvidia-gpu-firmware recipes
#
# The .run file is a self-extracting archive containing precompiled
# userspace binaries (nvidia-smi, libcuda.so, etc.) and GSP firmware.
# The open kernel modules are built separately from GitHub.

NVIDIA_DRIVER_VERSION = "${PV}"
# NVIDIA names its installers by TARGET_ARCH (x86_64, aarch64). Only x86_64
# has a -no-compat32 variant; aarch64 ships no 32-bit libraries at all.
NVIDIA_ARCHIVE = "NVIDIA-Linux-${TARGET_ARCH}-${NVIDIA_DRIVER_VERSION}"
NVIDIA_RUN_SUFFIX = ""
NVIDIA_RUN_SUFFIX:x86-64 = "-no-compat32"
NVIDIA_RUN = "${NVIDIA_ARCHIVE}${NVIDIA_RUN_SUFFIX}.run"
NVIDIA_SRC = "${UNPACKDIR}/${NVIDIA_ARCHIVE}"

# unpack=0 prevents bitbake from trying to extract the .run file itself;
# we handle extraction in do_unpack:append below.
SRC_URI = "https://download.nvidia.com/XFree86/Linux-${TARGET_ARCH}/${NVIDIA_DRIVER_VERSION}/${NVIDIA_RUN};name=run-${TARGET_ARCH};unpack=0"
SRC_URI[run-x86_64.sha256sum] = "9e4f5d56e74e1ec12a05b2b0afda893c3187da71cbd8fb14c1a394bbeeeb4148"
SRC_URI[run-aarch64.sha256sum] = "1a5a0d74315f997155bb814094d364daacea2cebb0d8de4229ab4a91c4ab4319"

LICENSE = "NVIDIA-Proprietary"
# NOTE: The md5 below must match the LICENSE file extracted from the .run archive.
# If it does not match, bitbake will report the expected md5 in the error message.
# Update this value accordingly after the first build attempt.
LIC_FILES_CHKSUM = "file://LICENSE;md5=92aa2e2af6aa0bcba1c3fe49da021937"
LICENSE_FLAGS = "commercial"
NO_GENERIC_LICENSE[NVIDIA-Proprietary] = "LICENSE"

S = "${NVIDIA_SRC}"

# The .run file is a self-extracting shell script. The base do_unpack handles
# file:// URIs (local files), then nvidia_extract_run extracts the .run archive.
# (do_unpack is a Python function, so we use postfuncs to add a shell step.)
nvidia_extract_run() {
    chmod +x ${DL_DIR}/${NVIDIA_RUN}
    rm -rf ${NVIDIA_SRC}
    ${DL_DIR}/${NVIDIA_RUN} -x --target ${NVIDIA_SRC}
}
do_unpack[postfuncs] += "nvidia_extract_run"

# Precompiled binaries -- skip QA checks that don't apply
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_SYSROOT_STRIP = "1"

COMPATIBLE_HOST = "(x86_64|aarch64).*-linux"
# Jetson's GPU stack comes from meta-tegra (nvidia-kernel-oot, tegra-libraries),
# which provides the same kernel-module-nvidia* and libcuda.so.1 names.
COMPATIBLE_MACHINE:tegra = "^$"
