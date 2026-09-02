SUMMARY = "Automagic shell tab completion for Python CLI applications"
HOMEPAGE = "https://github.com/iterative/shtab"
LICENSE = "MPL-2.0"
LIC_FILES_CHKSUM = "file://LICENCE;md5=ce309b747f3c978ff61cbec85c8430d9"

SRC_URI[sha256sum] = "76d9b980cb7fca90b808380f9f1d251f37891d1abc30e1d63f6bde030f804c02"

inherit pypi python_setuptools_build_meta

# shtab pins setuptools>=77 (PEP 639) in build-system.requires; scarthgap's
# setuptools-native is older. Relax it — shtab already uses the classic license
# table form, so the older backend builds it fine. Drop once SDK has >= 77.
do_configure:prepend() {
    sed -i 's/setuptools>=77/setuptools>=68/' ${S}/pyproject.toml
}

# shtab builds with setuptools_scm; the released sdist has no VCS, so pin the
# version explicitly to avoid "unable to detect version" during do_compile.
DEPENDS += "python3-setuptools-scm-native"
export SETUPTOOLS_SCM_PRETEND_VERSION = "${PV}"

RDEPENDS:${PN} += "python3-core"

BBCLASSEXTEND = "native nativesdk"
