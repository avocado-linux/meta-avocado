SUMMARY = "PyTorch portable inference runtime for edge devices"
DESCRIPTION = "ExecuTorch runs .pte model files on resource-constrained hardware. \
Provides a C++ API and portable CPU operator kernels with no dependency on PyTorch \
at inference time."
HOMEPAGE = "https://github.com/pytorch/executorch"
SECTION = "libs"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://LICENSE;md5=da6742972636cd56d418bee2df32b873"

PV = "1.3.1"
SRCREV = "e2f18eb23c45bd22ca332b0b8b49a81de304b472"
SRC_URI = "gitsm://github.com/pytorch/executorch.git;protocol=https;branch=release/1.3;destsuffix=executorch \
           file://0001-build-bundled-flatc-flatcc-for-the-build-host.patch"

# ExecuTorch's CMakeLists.txt hard-requires the source tree be named exactly
# `executorch` (upstream issue 6475), so override the fetcher's default `git`
# checkout dir with destsuffix to match.
S = "${WORKDIR}/executorch"

inherit cmake python3native

# Build-time code generation needs these host tools, none of which can be the
# target build:
#   python3-native      - runs the codegen scripts
#   torchgen-native     - the ATen schema + codegen modules gen_oplist/codegen.gen
#                         import. Pinned to torch 2.12.0 (the version ExecuTorch
#                         1.3.1 requires); the packaged python3-pytorch is 2.4.1,
#                         too old - its schema lacks ops like mean.dtype_out.
#   python3-pyyaml-native, python3-typing-extensions-native - torchgen's only
#                         third-party imports.
# No flatbuffers-native: flatc (and flatcc) are built for the build host from
# the bundled third-party sources by the SRC_URI patch, so the generator always
# matches the bundled flatbuffers headers. Depending on an ambient
# flatbuffers-native instead reintroduces a version skew that breaks the schema
# version static_assert on targets whose layers pin a different flatbuffers
# (e.g. the i.MX/meta-ml stack ships 23.5.26 vs ExecuTorch's bundled 24.3.25).
DEPENDS = "python3-native torchgen-native python3-pyyaml-native python3-typing-extensions-native"

# gen_oplist runs as `python3 -m codegen.tools.gen_oplist`, and cmake resolves
# that `python3` to the build container's interpreter, not the OE native one -
# so it ignores the native sysroot's site-packages where torchgen is staged.
# Put both import roots on PYTHONPATH explicitly: ${WORKDIR} for the executorch
# package (this source tree, named `executorch` via destsuffix) and the native
# site-packages for torchgen (pure-python, no torch C-extension, so the
# container interpreter loads it fine).
export PYTHONPATH = "${WORKDIR}:${STAGING_LIBDIR_NATIVE}/python${PYTHON_BASEVERSION}/site-packages"

# Minimal portable C++ runtime.  All backends (XNNPACK, CUDA, Vulkan, QNN,
# OpenVINO, ARM Ethos-U), Python bindings, tests, and devtools are disabled
# so the recipe cross-compiles without host-side PyTorch or GPU toolchains.
# The MODULE extension is the high-level load-and-run API we want; DATA_LOADER,
# FLAT_TENSOR, and NAMED_DATA_MAP are its transitive preset requirements
# (tools/cmake/preset/default.cmake), not independently selected.
EXTRA_OECMAKE = "\
    -DEXECUTORCH_BUILD_TESTS=OFF \
    -DEXECUTORCH_BUILD_PYBIND=OFF \
    -DEXECUTORCH_BUILD_XNNPACK=OFF \
    -DEXECUTORCH_BUILD_CUDA=OFF \
    -DEXECUTORCH_BUILD_VULKAN=OFF \
    -DEXECUTORCH_BUILD_QNN=OFF \
    -DEXECUTORCH_BUILD_OPENVINO=OFF \
    -DEXECUTORCH_BUILD_ARM_BAREMETAL=OFF \
    -DEXECUTORCH_BUILD_ARM_ETHOSU_LINUX=OFF \
    -DEXECUTORCH_BUILD_DEVTOOLS=OFF \
    -DEXECUTORCH_BUILD_EXECUTOR_RUNNER=OFF \
    -DEXECUTORCH_BUILD_PORTABLE_OPS=ON \
    -DEXECUTORCH_BUILD_EXTENSION_DATA_LOADER=ON \
    -DEXECUTORCH_BUILD_EXTENSION_MODULE=ON \
    -DEXECUTORCH_BUILD_EXTENSION_FLAT_TENSOR=ON \
    -DEXECUTORCH_BUILD_EXTENSION_NAMED_DATA_MAP=ON \
    -DEXECUTORCH_OPTIMIZE_SIZE=ON \
"

# ExecuTorch installs libflatccrt_d.a and libextension_evalue_util.a to an
# absolute build-dir path (${B}/lib) instead of ${libdir}; relocate them so
# they ship in -staticdev, then drop the leaked DESTDIR tree. The exported
# cmake targets record that same absolute path in IMPORTED_LOCATION, which both
# trips the buildpaths QA and would break find_package(ExecuTorch); rewrite it
# to the install-prefix-relative location to match the relocated lib.
do_install:append() {
    if [ -d "${D}${B}/lib" ]; then
        install -m 0644 ${D}${B}/lib/*.a ${D}${libdir}/
    fi
    # ExecuTorch installs the two static libs above to ${B}/lib - an absolute
    # in-build path - which leaks that whole directory chain into DESTDIR. It
    # must be removed or do_package fails the installed-vs-shipped QA on every
    # leaked dir. Do NOT hardcode the leaf (the old `rm -rf ${D}/work` only
    # cleaned it when TOPDIR happened to be /work; under a different TOPDIR,
    # e.g. /avocado-build, the leaked tree survived and broke the build). ${B}
    # is absolute, so ${D}${B} is the leaked build dir regardless of TOPDIR;
    # drop it, then rmdir -p walks the now-empty parent chain up to ${D} (which
    # stops it, being non-empty). nativesdk builds hit this same path.
    rm -rf "${D}${B}"
    rmdir -p "$(dirname "${D}${B}")" 2>/dev/null || true
    find ${D}${libdir}/cmake -name '*.cmake' -exec \
        sed -i "s#${B}/lib/#"'${_IMPORT_PREFIX}/lib/#g' {} +
}

# This configuration produces only static libraries and headers. The bundled
# cpuinfo installs its cmake package files under ${datadir} and a stray header
# directly in ${libdir}; route both to -dev. The lib*.a land in ${libdir} and
# ship in -staticdev via the default packaging split.
FILES:${PN}-dev += "${libdir}/cmake ${libdir}/pkgconfig ${libdir}/cpuinfo.h ${datadir}/cpuinfo"
ALLOW_EMPTY:${PN} = "1"

# Build a nativesdk variant too so the executorch headers and static runtime are
# staged in the Avocado SDK host sysroot (per the 6/17 SDK-integration
# decision); pairs with nativesdk-torchgen for host-side executorch work.
BBCLASSEXTEND = "nativesdk"
