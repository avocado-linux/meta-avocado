# Wrynose: freeze DUMMYARCH at parse time. dummy-sdk-package.inc does
# `inherit allarch`, whose finalize-time anon python sets SDK_ARCH="none"
# (the SDK arch baseline gets clobbered for recipes with PACKAGE_ARCH=all
# at the moment the handler fires). With lazy `=`, ${SDKPKGARCH} =
# ${SDK_ARCH}-avocadosdk evaluates AFTER that clobber, leaving us with
# `none-avocadosdk` — a phantom arch that doesn't appear in PACKAGE_ARCHS
# / SDK_PACKAGE_ARCHS, so avocado-sdk-metadata.bb generates no dnf repo
# entry for it and dnf can never see the dummy's RPROVIDES (/bin/sh, etc).
# `:=` immediate-expands at recipe parse time, before the allarch handler
# fires, capturing the real ${SDK_ARCH} (e.g. "x86_64") as a literal.
DUMMYARCH := "${SDKPKGARCH}"

DUMMYSDK_PKGDATA_VARNAME = "PKGDATA_DIR_SDK"
DUMMYSDK_EXTRASTAMP_VARNAME = "SDK_SYS"

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

inherit nativesdk nospdx
