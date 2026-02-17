# Shared include for NVIDIA proprietary .run driver installer
# Used by nvidia-gpu-userspace and nvidia-gpu-firmware recipes
#
# The .run file is a self-extracting archive containing precompiled
# userspace binaries (nvidia-smi, libcuda.so, etc.) and GSP firmware.
# The open kernel modules are built separately from GitHub.

NVIDIA_DRIVER_VERSION = "${PV}"
NVIDIA_ARCHIVE = "NVIDIA-Linux-x86_64-${NVIDIA_DRIVER_VERSION}"
NVIDIA_SRC = "${WORKDIR}/${NVIDIA_ARCHIVE}"

# unpack=0 prevents bitbake from trying to extract the .run file itself;
# we handle extraction in do_unpack:append below.
SRC_URI = "https://download.nvidia.com/XFree86/Linux-x86_64/${NVIDIA_DRIVER_VERSION}/${NVIDIA_ARCHIVE}-no-compat32.run;name=run;unpack=0"
SRC_URI[run.sha256sum] = "1c4623284d8d3c6b843eadc4a878bff6f894bf99fc48169945e19af470ca6d90"

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
    chmod +x ${DL_DIR}/${NVIDIA_ARCHIVE}-no-compat32.run
    rm -rf ${NVIDIA_SRC}
    ${DL_DIR}/${NVIDIA_ARCHIVE}-no-compat32.run -x --target ${NVIDIA_SRC}
}
do_unpack[postfuncs] += "nvidia_extract_run"

# Precompiled binaries -- skip QA checks that don't apply
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_SYSROOT_STRIP = "1"

# x86-64 only
COMPATIBLE_HOST = "x86_64.*-linux"
