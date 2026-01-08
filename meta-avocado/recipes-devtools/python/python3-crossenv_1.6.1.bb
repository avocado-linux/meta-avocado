SUMMARY = "Virtual environment for cross-compiling Python extension modules"
DESCRIPTION = "Crossenv creates a special virtual environment such that pip \
or setup.py will cross compile packages for you, often with no further work \
on your part. It can be used to build binary wheels for installation on target, \
or install packages to a directory for upload or inclusion in a firmware image."
HOMEPAGE = "https://crossenv.readthedocs.io/"
AUTHOR = "Benjamin Fogle <benfogle@gmail.com>"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE.txt;md5=8d2b8cfc57ab5730cd8380000474cb84"

SRC_URI[sha256sum] = "5b7e2f231d9a3c6ea56ce3b7fd7acbe0f1e310e44a8f699909910f1334db1a31"

inherit pypi python_hatchling

RDEPENDS:${PN} += " \
    python3-venv \
"

BBCLASSEXTEND = "native nativesdk"

