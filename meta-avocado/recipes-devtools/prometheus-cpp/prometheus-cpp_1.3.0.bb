DESCRIPTION = "Prometheus Client Library for Modern C++"
HOMEPAGE = "https://github.com/jupp0r/prometheus-cpp"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=f203962b7b283e1e356c14312b4f6211"

PV = "1.3.0"

SRC_URI = "https://github.com/jupp0r/prometheus-cpp/releases/download/v${PV}/prometheus-cpp-with-submodules.tar.gz"
SRC_URI[sha256sum] = "62bc2cc9772db2314dbaae506ae2a75c8ee897dab053d8729e86a637b018fdb6"

S = "${WORKDIR}/prometheus-cpp-with-submodules"

# Build dependencies
DEPENDS = "curl zlib"

inherit cmake pkgconfig

# Enable optional features via PACKAGECONFIG
PACKAGECONFIG ??= "push compression"
PACKAGECONFIG[push] = "-DENABLE_PUSH=ON,-DENABLE_PUSH=OFF,curl"
PACKAGECONFIG[compression] = "-DENABLE_COMPRESSION=ON,-DENABLE_COMPRESSION=OFF,zlib"

# Always build shared libraries and disable tests by default
EXTRA_OECMAKE = "-DBUILD_SHARED_LIBS=ON -DENABLE_TESTING=OFF -Dcivetweb-3rdparty_DIR=${S}/cmake"
