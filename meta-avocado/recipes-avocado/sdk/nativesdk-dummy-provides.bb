DUMMYARCH = "${SDKPKGARCH}"

DUMMYPROVIDES = "\
    /bin/bash \
    /bin/sh \
    /usr/bin/env \
    /usr/bin/perl \
    pkgconfig \
    libGL.so()(64bit) \
    libGL.so \
"

require recipes-core/meta/dummy-sdk-package.inc

inherit nativesdk
