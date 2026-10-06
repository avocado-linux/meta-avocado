SUMMARY = "Cross-platform system monitoring and telemetry tool"
DESCRIPTION = "Glances is a cross-platform monitoring tool that surfaces a large \
amount of system information (CPU, memory, disk, network, sensors, containers, \
GPU, processes, …) and can export it to many services and time-series DBs. In \
Avocado it is the user-configurable device-telemetry collector: the set of \
metrics gathered is controlled by /etc/glances/glances.conf."
HOMEPAGE = "https://nicolargo.github.io/glances/"
LICENSE = "LGPL-3.0-only"
LIC_FILES_CHKSUM = "file://COPYING;md5=852ecadc0ac7e6f4d7144d5544a3815b"

SRC_URI[sha256sum] = "8a26329f0a25e878d53c2558f1eb0615b09acc1dce2ba523cab32dbe175fe8bf"

# Fix MQTT exporter paho-v2 connect race (on_connect uses self.client before it
# is assigned -> AttributeError -> dead network thread -> no metrics).
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += "file://0001-mqtt-use-local-client-in-callbacks.patch"

inherit pypi python_setuptools_build_meta

# scarthgap's setuptools-native predates PEP 639, which rejects the SPDX string
# form `license = "LGPL-3.0-only"`. Rewrite it to the classic table form so the
# build backend accepts it. Drop once the SDK ships setuptools >= 77.
do_configure:prepend() {
    sed -i 's/license = "LGPL-3.0-only"/license = {text = "LGPL-3.0-only"}/' ${S}/pyproject.toml
}

# Core runtime deps (glances pyproject: psutil, defusedxml, packaging, jinja2,
# shtab, pyinstrument). windows-curses is Windows-only and omitted.
# Exporter deps: python3-requests (RESTful exporter — the Avocado default path,
# glances -> avocado-conn bridge) and python3-paho-mqtt (direct-MQTT fallback).
# python3-modules pulls the full stdlib so no import fails on first boot;
# TODO: trim to the specific python3-* stdlib subpackages once profiled.
RDEPENDS:${PN} += " \
    python3-psutil \
    python3-defusedxml \
    python3-packaging \
    python3-jinja2 \
    python3-shtab \
    python3-pyinstrument \
    python3-requests \
    python3-paho-mqtt \
    python3-modules \
"
