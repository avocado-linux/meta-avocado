DESCRIPTION = "nsync is a C library that exports various synchronization primitives, such as mutexes"
HOMEPAGE = "https://github.com/google/nsync"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=3b83ef96387f14655fc854ddc3c6bd57"

SRC_URI = " \
    git://github.com/google/nsync.git;protocol=https;branch=master;tag=${PV} \
    file://0001-Export-cmake-config-file.patch \
    file://0002-cmake-Set-minimum-required-version-to-3.5-for-CMake-.patch \
"
SRCREV = "13de152c2a1cd73ff4df97bd2c406b6d15d34af3"

inherit cmake
