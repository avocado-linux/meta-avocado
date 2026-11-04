# SPDX-License-Identifier: Apache-2.0

"""The pkgdata packages that have no RPM, so the manifest can leave them out.

At image scope pkgdata also names packages built only as build-time
dependencies, which package_rpm never wrote. rpms.build_manifest fails on any
package it cannot find, and it is kept identical to scarthgap's, so the task
takes these out first and warns about them.

Leaving one out is safe. A package with no RPM was never shipped, so it is on
no device. If one that should have an RPM goes missing, it is not listed and
gets no verdict downstream, never a wrong one.
"""

from avocado_sbom import rpms

def drop_rpmless(packages, rpm_dir):
    """(kept, dropped): packages without those that have no RPM under rpm_dir,
    and the sorted names taken out.

    The file is looked for under the name build_manifest gives it: PKGV with
    "+" for "-", then PKGR, in any arch directory. Whatever build_manifest
    refuses for another reason is kept, so it still fails there: a directory
    that cannot be listed, a path separator, a version with no release. An
    empty package (PKGSIZE 0) is kept too, because build_manifest already
    excuses it without a word.
    """
    try:
        index = rpms._index_rpm_dir(rpm_dir)
    except OSError:
        return packages, []

    kept = {}
    dropped = []
    for name, info in packages.items():
        version = info["version"]
        pkgv, _sep, pkgr = version.rpartition("-")
        if (info.get("size") == 0 or "/" in name or "/" in version
                or not pkgv or not pkgr):
            kept[name] = info
            continue
        stem = "%s-%s-%s" % (name, pkgv.replace("-", "+"), pkgr)
        if any("%s.%s.rpm" % (stem, arch) in files for arch, files in index.items()):
            kept[name] = info
        else:
            dropped.append(name)
    return kept, sorted(dropped)
