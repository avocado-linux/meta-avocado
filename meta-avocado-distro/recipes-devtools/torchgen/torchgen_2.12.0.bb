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

# The wheel is a zip; downloadfilename=*.zip makes BitBake unpack it so
# ${WORKDIR}/torchgen (with its packaged ATen yamls) is available. Only the
# pure-Python torchgen package is installed; the bundled libtorch is ignored.
SRC_URI = "\
    https://download.pytorch.org/whl/test/cpu/torch-${PV}%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl;downloadfilename=torch-${PV}-cp312.zip;name=wheel \
    https://raw.githubusercontent.com/pytorch/pytorch/release/2.12/LICENSE;name=license \
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
