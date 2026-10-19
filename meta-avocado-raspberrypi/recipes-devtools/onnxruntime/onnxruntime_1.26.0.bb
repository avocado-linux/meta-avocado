SUMMARY = "ONNX Runtime: cross-platform, high performance ML inferencing and training accelerator"
HOMEPAGE = "https://github.com/microsoft/onnxruntime"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=0f7e3b1308cb5c00b372a6e78835732d"

# CPU-only build. Derived from the OE4T meta-tegra-community recipe, which
# builds the CUDA flavour for Jetson. Both flavours share the name, so this one
# lives in the Raspberry Pi layer: a Jetson build never sees it and keeps
# picking the CUDA recipe.

SRC_URI = " \
    git://github.com/microsoft/onnxruntime.git;protocol=https;nobranch=1;tag=v${PV} \
    file://0001-Use-external-library-dependencies.patch \
    file://0002-Skip-redundant-ONNX-opset-registration-when-static-r.patch \
"
SRCREV = "8c546c37b43caaca1fa25db430dab94b901cf277"

inherit cmake setuptools3

B = "${S}"

DEPENDS += " \
    boost \
    abseil-cpp \
    date \
    flatbuffers \
    flatbuffers-native \
    nlohmann-json \
    nsync \
    onnx-ort \
    microsoft-gsl \
    protobuf \
    protobuf-native \
    re2 \
    safeint \
    dlpack \
    libeigen \
    python3-pybind11 \
"

# onnxruntime sets COMPILE_WARNING_AS_ERROR on every target. The tree's compiler
# and its Eigen turn two diagnostics into hard errors that the code does not
# trigger in a way that matters: C++20 implicit 'this' capture in Eigen's thread
# pool, and -mcpu=cortex-a76 versus the -march=armv8.2-a+i8mm of the MLAS i8mm
# kernels. A per-flag -Wno-error cannot reach the second one, which carries no
# warning name, so the property is ignored at configure time instead.
EXTRA_OECMAKE = " \
    --compile-no-warning-as-error \
    -DONNX_CUSTOM_PROTOC_EXECUTABLE=${STAGING_BINDIR_NATIVE}/protoc \
    -Donnxruntime_BUILD_SHARED_LIB=ON \
    -Donnxruntime_BUILD_UNIT_TESTS=OFF \
    -Donnxruntime_CROSS_COMPILING=ON \
    -Donnxruntime_ENABLE_CPUINFO=OFF \
    -DFETCHCONTENT_TRY_FIND_PACKAGE_MODE=ALWAYS \
    -Donnxruntime_USE_PREINSTALLED_EIGEN=OFF \
    -DCMAKE_SKIP_RPATH=ON \
    -DCMAKE_CXX_STANDARD=20 \
    ${@bb.utils.contains('PACKAGECONFIG', 'python', '-Donnxruntime_ENABLE_PYTHON=ON -DPython_NumPy_INCLUDE_DIR=${STAGING_DIR_TARGET}${PYTHON_SITEPACKAGES_DIR}/numpy/_core/include', '', d)} \
"

# onnx-ort installs its private, static, registration-disabled ONNX under
# ${prefix}/onnx-ort. Add that prefix to CMAKE_FIND_ROOT_PATH so ORT's
# find_package(ONNX) (FETCHCONTENT_TRY_FIND_PACKAGE_MODE=ALWAYS) resolves to it
# instead of building ONNX from source or finding a shared system onnx.
OECMAKE_EXTRA_ROOT_PATH = "${RECIPE_SYSROOT}${prefix}/onnx-ort"

OECMAKE_CXX_FLAGS:append = " -Wno-array-bounds -Wno-deprecated-declarations -Wno-unused-variable -Wno-template-id-cdtor -Wno-range-loop-construct -Wno-maybe-uninitialized -Wno-error=cpp -Wno-error=uninitialized -Wno-error=unused-but-set-parameter"
OECMAKE_SOURCEPATH = "${S}/cmake"

PACKAGECONFIG ?= "python"
# FindPython would import numpy with the build-host interpreter to locate its
# headers, and the native numpy links whatever BLAS the builder happens to have,
# so the headers are taken from the target numpy instead.
PACKAGECONFIG[python] = ",,python3-numpy python3-numpy-native,python3-coloredlogs python3-flatbuffers python3-numpy python3-packaging python3-protobuf python3-sympy"

do_configure() {
    cmake_do_configure
}

do_compile() {
    cmake_do_compile
    if "${@bb.utils.contains('PACKAGECONFIG', 'python', 'true', 'false', d)}"; then
        setuptools3_do_compile
    fi
}

do_install() {
    cmake_do_install
    if "${@bb.utils.contains('PACKAGECONFIG', 'python', 'true', 'false', d)}"; then
        setuptools3_do_install
    fi
}

SOLIBS = ".so"
FILES_SOLIBSDEV = ""

PACKAGES += "python3-${PN}"
FILES:${PN} = "${bindir} ${libdir}/libonnxruntime*.so*"
FILES:${PN}-dev = " \
    ${includedir}/onnxruntime \
    ${libdir}/pkgconfig \
    ${libdir}/cmake \
"
FILES:python3-${PN} = "${PYTHON_SITEPACKAGES_DIR}"
RDEPENDS:python3-${PN} = "${PN}"

INSANE_SKIP:${PN} = "buildpaths dev-so"
INSANE_SKIP:python3-${PN} = "buildpaths"
INSANE_SKIP:${PN}-dev = "buildpaths"
INSANE_SKIP:${PN}-dbg = "buildpaths"
