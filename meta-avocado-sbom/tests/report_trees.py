# SPDX-License-Identifier: Apache-2.0

"""Package data trees and scanner manifests for the report tests.

A Tree is one build's pkgdata: the default multiconfig's machine and SDK
directories under tmp/, and an alternate multiconfig's under tmp-<mc>/, laid
out as bitbake writes them. The fixtures below are the builds several test
files share; tests/fixtures/report-v1 holds the version 1 reports the
previous generator wrote for two of them.
"""

import json
import os
import random

from avocado_sbom.report import MANIFEST_SUFFIX, write_report

GENERATED = "2000-01-01T00:00:00Z"
MACHINE = "raspberrypi5"
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "report-v1")


def issue(cve, status="Unpatched", **extra):
    item = {"id": cve, "status": status, "summary": "s " + cve,
            "description": "d " + cve, "scorev3": "7.5", "link": "l"}
    item.update(extra)
    return item


def entry(name, version, *issues):
    return {"name": name, "version": version, "issue": list(issues)}


class Tree:

    def __init__(self, root, machine=MACHINE):
        self.root = root
        self.machine_name = machine
        self.machine = os.path.join(root, "tmp", "pkgdata", machine)
        self.sdk = os.path.join(root, "tmp", "pkgdata", "x86_64-avocadosdk-linux")
        for d in (self.machine, self.sdk):
            os.makedirs(os.path.join(d, "runtime-reverse"))
        self.dirs = [self.machine, self.sdk]
        # {mc: (pkgdata dir, recipes or None)}, in the order they were declared.
        self.alts = {}

    def alt(self, mc, recipes=None):
        """Declare an alternate multiconfig and the recipes the feed takes
        from it; None takes every recipe."""
        if mc not in self.alts:
            path = os.path.join(self.root, "tmp-" + mc, "pkgdata", self.machine_name)
            os.makedirs(os.path.join(path, "runtime-reverse"))
            self.alts[mc] = (path, None)
        if recipes is not None:
            self.alts[mc] = (self.alts[mc][0], set(recipes))
        return self.alts[mc][0]

    @property
    def alt_trees(self):
        return [(mc, path, recipes) for mc, (path, recipes) in self.alts.items()]

    def write(self, name, text, mc="", sdk=False):
        base = self.alt(mc) if mc else self.sdk if sdk else self.machine
        with open(os.path.join(base, "runtime-reverse", name), "w") as f:
            f.write(text)

    def pkg(self, name, recipe, pv, pkgv=None, pkgr="r0", mc="", sdk=False):
        self.write(name, "PN: %s\nPV: %s\nPKGV: %s\nPKGR: %s\n" % (recipe, pv, pkgv or pv, pkgr),
                   mc=mc, sdk=sdk)

    def manifest(self, name, data):
        path = os.path.join(self.root, name + MANIFEST_SUFFIX)
        with open(path, "w") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f)
        return path


def normalized(doc):
    doc = dict(doc)
    doc["generated"] = GENERATED
    return doc


def as_bytes(doc, root):
    path = os.path.join(root, "out-%d.json" % random.getrandbits(64))
    write_report(normalized(doc), path)
    with open(path, "rb") as f:
        data = f.read()
    os.unlink(path)
    return data


def round_trip(doc, root):
    """The report as a rescan gets it: the file the build uploaded."""
    path = os.path.join(root, "anchor-%d.json" % random.getrandbits(64))
    write_report(doc, path)
    with open(path) as f:
        return json.load(f)


def load_fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


# --- one tree: every pkgdata and manifest path a single-kernel build takes ---

def one_tree(tree):
    """A single-kernel build: PV and PKGV apart (glibc, the kernel), a
    package with its own PKGV, one with no version and one unreadable, and a
    name the SDK directory claims for another recipe. Returns the scan the
    build was reported with."""
    t = tree
    t.write("libc6", "PN: glibc\nPV: 2.43+git\nPKGV: 2.43+git1+562cd7badd\nPKGR: r0\n")
    t.write("glibc-utils", "PN: glibc\nPV: 2.43+git\nPKGV: 2.43+git0+562cd7badd\nPKGR: r0\n")
    t.write("kernel-image", "PN: linux-raspberrypi\nPV: 6.12.87+git\n"
            "PKGV: 6.12.87+git0+abc\nPKGR: r0\n")
    t.write("libssl3", "PN: openssl\nPV: 3.5.7\nPKGV: 3.5.7\nPKGR: r0\n")
    t.write("libz1", "PN: zlib\nPV: 1.3.1\nPKGV: 1.3.1\nPKGR: r0\n")
    t.write("libattr1", "PN: attr\nPV: 2.5.2\nPKGV: 2.5.2\nPKGR: r0\n")
    t.write("libdevmapper", "PN: lvm2\nPV: 2.03.39\nPKGV:libdevmapper: 1.02.213\n"
            "PKGR:libdevmapper: r0.3\n")
    t.write("dbus", "PN: dbus\nPV: 1.16.2\nPKGV: 1.16.2\nPKGR: r0\n")
    # No version at all: no version keys, still packaged.
    t.write("packagegroup-x", "PN: packagegroup-x\n")
    # Unreadable, and a name the SDK directory claims for another recipe.
    t.write("broken", "garbage\n")
    t.write("libssl3", "PN: openssl-vendor\nPV: 1.1.1w\nPKGV: 1.1.1w\nPKGR: r0\n", sdk=True)
    t.write("nativesdk-libz1", "PN: nativesdk-zlib\nPV: 1.3.1\nPKGV: 1.3.1\nPKGR: r0\n", sdk=True)
    return t.manifest("build", {"package": [
        entry("glibc", "2.43+git", issue("CVE-2026-1"), issue("CVE-2025-9", "Patched")),
        entry("linux-raspberrypi", "6.12.87+git", issue("CVE-2026-10")),
        entry("openssl", "3.5.7", issue("CVE-2026-2", "Ignored")),
        entry("zlib", "1.3.1"),
        entry("openssl-vendor", "1.1.1w"),
        entry("dbus", "1_1.16.2", issue("CVE-2026-20")),
    ]})


def one_tree_rescan(tree):
    """A later scan of one_tree: new CVEs, changed statuses, a newly scanned
    recipe, a stale entry, an EXTENDPE prefix, an unpackaged recipe and its
    CVEs, an unknown status, a malformed entry, a repeat across two manifests
    and an unreadable third one."""
    t = tree
    return [
        t.manifest("rescan-a", {"package": [
            entry("glibc", "2.43+git", issue("CVE-2026-1", "Patched"),
                  issue("CVE-2026-30"), issue("CVE-2026-31", "Ignored")),
            entry("linux-raspberrypi", "6.12.87+git", issue("CVE-2026-10"),
                  issue("CVE-2026-11"), issue("CVE-2026-12", "Patched")),
            entry("openssl", "3.5.6", issue("CVE-2026-40")),
            entry("zlib", "1.3.1", issue("CVE-2026-50", "Foo")),
            entry("attr", "2.5.2", issue("CVE-2026-60")),
            entry("openssl-vendor", "1.1.1w", issue("CVE-2026-70")),
            entry("dbus", "1_1.16.2", issue("CVE-2026-20"), issue("CVE-2026-21")),
            entry("packagegroup-x", "1.0", issue("CVE-2026-80")),
            entry("busybox-native", "1.37", issue("CVE-2026-90")),
            {"name": 7, "version": "1"},
            entry("lvm2", "2.03.39", {"id": "CVE-2026-91"}),
        ]}),
        t.manifest("rescan-b", {"package": [
            entry("glibc", "2.43+git", issue("CVE-2026-30"), issue("CVE-2026-32")),
        ]}),
        t.manifest("rescan-c", "{not json"),
    ]


# --- two kernels of one recipe, the 6.6 one in an alternate multiconfig ------

RPI_MC = "raspberrypi-6_6"
DEFAULT_KERNEL = "6.12.87+git"
ALT_KERNEL = "6.6.78+git"


def rpi_kernels(tree):
    """Raspberry Pi: linux-raspberrypi at 6.12 in the default multiconfig and
    at 6.6 in RPI_MC, which the feed takes linux-raspberrypi and kernel-devsrc
    from. Both kernels package "kernel" and "kernel-dev"; the module and image
    names carry the kernel version."""
    tree.alt(RPI_MC, {"linux-raspberrypi", "kernel-devsrc"})
    for mc, pv in (("", DEFAULT_KERNEL), (RPI_MC, ALT_KERNEL)):
        short = pv.split("+")[0]
        tree.pkg("kernel", "linux-raspberrypi", pv, mc=mc)
        tree.pkg("kernel-dev", "linux-raspberrypi", pv, mc=mc)
        tree.pkg("kernel-image-image-%s" % short, "linux-raspberrypi", pv, mc=mc)
        tree.pkg("kernel-module-foo-%s" % short, "linux-raspberrypi", pv, mc=mc)
        tree.pkg("kernel-devsrc-%s" % short, "kernel-devsrc", pv, mc=mc)
    # The alternate multiconfig builds the rest of the image too; none of it
    # reaches the feed.
    tree.pkg("base-files", "base-files", "3.0.14", mc=RPI_MC)
    tree.pkg("alt-only-tool", "alt-only-tool", "1.0", mc=RPI_MC)
    tree.pkg("base-files", "base-files", "3.0.14")
    tree.pkg("libssl3", "openssl", "3.5.7")
