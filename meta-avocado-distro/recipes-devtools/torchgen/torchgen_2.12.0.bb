SUMMARY = "PyTorch operator code generator (torchgen)"
DESCRIPTION = "The pure-Python torchgen package extracted from the PyTorch \
2.12.0 CPU wheel: the ATen schema (native_functions.yaml, tags.yaml) and the \
codegen modules that ExecuTorch's build-time operator codegen (codegen.gen and \
codegen.tools.gen_oplist) consumes. Native-only build tool - no libtorch is \
built or installed. Pinned to 2.12.0 because ExecuTorch 1.3.1 requires \
torch>=2.12.0a0 and its functions.yaml references ATen overloads (e.g. \
mean.dtype_out) absent from older schemas."
HOMEPAGE = "https://github.com/pytorch/pytorch"
SECTION = "devel"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://LICENSE;md5=b114fbe63fdb5f7a91332a4aefb61ee5"

PV = "2.12.0"

# Source channel: the stable index (download.pytorch.org/whl/cpu), not the test
# (pre-release) channel. 2.12.0 has now promoted to stable, and the stable wheel
# is byte-identical to the test-channel one (same sha256 pinned below), so this
# is the durable home for it - PyTorch garbage-collects test/nightly wheels once
# a version ships, but stable wheels persist. The sha256 pin makes any future
# change/removal fail loudly rather than silently substitute. For extra defense
# against an upstream outage, mirror this wheel to the Avocado premirror.
#
# Why the whole wheel, not just the python module: a bare git checkout of
# pytorch's torchgen/ directory does NOT contain torchgen/packaged/ (the ATen
# schema - native_functions.yaml, tags.yaml, and the codegen templates). That
# subtree is assembled at wheel-build time, and it is exactly what ExecuTorch's
# gen_oplist/codegen.gen read. The wheel is the only artifact that ships torchgen
# together with its packaged schema, so we pull the full wheel and keep only the
# pure-Python torchgen package (do_install below); the bundled libtorch and
# everything else is discarded.
#
# Why the x86_64/cp312 wheel is safe on any build host: torchgen is pure Python
# (the staged package contains no compiled .so), and do_install copies only the
# torchgen/ subtree - none of the wheel's arch- or CPython-ABI-specific binaries
# are imported or shipped. So this single wheel works whatever the build host's
# arch or interpreter is. Do NOT "fix" the filename to be host-arch-conditional:
# it would gain nothing, multiply the pinned checksums per arch, and break the
# reproducibility this single pin gives us. The downloadfilename normalizes the
# unpack name so the arch tag never leaks into ${WORKDIR}.
#
# downloadfilename=*.zip makes BitBake treat the wheel (a zip) as an archive and
# unpack it, so ${WORKDIR}/torchgen is available to do_install.
SRC_URI = "\
    https://download.pytorch.org/whl/cpu/torch-${PV}%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl;downloadfilename=torch-${PV}-cp312.zip;name=wheel \
    https://raw.githubusercontent.com/pytorch/pytorch/v${PV}/LICENSE;name=license \
"
SRC_URI[wheel.sha256sum] = "5e3dc83725581fa38b7b2e45c58692e30b2a3cde19191af54b675ffcac3840a6"
SRC_URI[license.sha256sum] = "bd018feef8825e88181c84eb7e3aa4eafb8f08a20d9fd6ef948569610c4a3e43"

S = "${WORKDIR}"

inherit python3-dir

do_install() {
    install -d ${D}${PYTHON_SITEPACKAGES_DIR}
    cp -r ${S}/torchgen ${D}${PYTHON_SITEPACKAGES_DIR}/
}

# Claim the installed site-packages so the package ships them. The native
# variant skips the installed-vs-shipped QA, but the nativesdk variant produces
# a real SDK package and fails do_package without an explicit FILES entry.
FILES:${PN} += "${PYTHON_SITEPACKAGES_DIR}"

# Build-time codegen tool for ExecuTorch. The native variant is consumed during
# the image build; the nativesdk variant ships in the Avocado SDK so a developer
# can run the executorch codegen when cross-compiling against the runtime.
BBCLASSEXTEND = "native nativesdk"
