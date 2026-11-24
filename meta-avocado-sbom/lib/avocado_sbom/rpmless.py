# SPDX-License-Identifier: Apache-2.0

"""The pkgdata packages that have no RPM and that the scanned image does not
ship, so the manifest can leave them out.

At image scope pkgdata also names packages the image does not install, some
built only as build-time dependencies, which package_rpm may never have
written. rpms.build_manifest fails on any package it cannot find, and it is
kept identical to scarthgap's, so the task takes these out first and warns
about them.

A package the image ships is never taken out. If its RPM is missing, pkgdata
names a version whose RPM was not written (pkgdata refreshed at a new PKGR by
another target's build, say), and build_manifest fails on it. Where there is no
image to ask, at world scope, nothing is taken out and every missing RPM fails,
as on scarthgap.
"""

from avocado_sbom import rpms

def read_image_manifest(path):
    """The package names an image's installed-package manifest lists.

    The manifest is write_image_manifest's: one "name arch version" line per
    installed package. Raises OSError if it cannot be read.
    """
    with open(path) as f:
        return {line.split()[0] for line in f if line.strip()}

def drop_rpmless(packages, rpm_dir, shipped):
    """(kept, dropped): packages without those that have no RPM under rpm_dir
    and are not in shipped, and the sorted names taken out.

    shipped is the set of package names the scanned image installs, or None
    where there is no image to ask; then nothing is taken out.

    The file is looked for under the name build_manifest gives it: PKGV with
    "+" for "-", then PKGR, in any arch directory. Whatever build_manifest
    refuses for another reason is kept, so it still fails there: a directory
    that cannot be listed, a path separator, a version with no release. An
    empty package (PKGSIZE 0) is kept too, because build_manifest already
    excuses it without a word.
    """
    if shipped is None:
        return packages, []
    try:
        index = rpms._index_rpm_dir(rpm_dir)
    except OSError:
        return packages, []

    kept = {}
    dropped = []
    for name, info in packages.items():
        version = info["version"]
        pkgv, _sep, pkgr = version.rpartition("-")
        if (name in shipped or info.get("size") == 0 or "/" in name
                or "/" in version or not pkgv or not pkgr):
            kept[name] = info
            continue
        stem = "%s-%s-%s" % (name, pkgv.replace("-", "+"), pkgr)
        if any("%s.%s.rpm" % (stem, arch) in files for arch, files in index.items()):
            kept[name] = info
        else:
            dropped.append(name)
    return kept, sorted(dropped)
