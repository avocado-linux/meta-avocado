# SPDX-License-Identifier: Apache-2.0

"""The RPMs a build produced, each with the digest of its header.

A correlation service that keys verdicts on a build's packages needs more than
a name and a version: two builds of one NEVRA are different files with
different headers. Pulp keeps neither the header digest nor which build a file
came from, so the build writes the list itself.

The digest is the sha256 of the main header section. That is the value rpm
records as SHA256HEADER and the range Pulp reports as rpm_header_start to
rpm_header_end, so a consumer can recompute it from either side. It is read
from the files directly rather than by running rpm: no rpm-native dependency,
and the digest is computed here instead of trusted from a tag.
"""

import datetime
import hashlib
import os
import re
import struct

MANIFEST_VERSION = "1"

_LEAD_SIZE = 96
_LEAD_MAGIC = 0xEDABEEDB
_HEADER_MAGIC = b"\x8e\xad\xe8\x01"
# rpm's own bounds (lib/header.c): more than this is corruption, and reading
# it would allocate whatever a damaged file claims.
_MAX_INDEX = 0x10000
_MAX_DATA = 256 * 1024 * 1024

_TYPE_INT32 = 4
_TYPE_STRING = 6

_TAG_SIG_SHA256 = 273
_TAG_NAME = 1000
_TAG_VERSION = 1001
_TAG_RELEASE = 1002
_TAG_EPOCH = 1003
_TAG_ARCH = 1022

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_GENERATED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_ENTRY_FIELDS = ("name", "version", "release", "arch", "sha256header", "file")

class ManifestError(Exception):
    """Everything wrong with the package set, not only the first thing.

    A build that names forty missing files should say so once; one failure per
    rebuild is a day.
    """

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))

def _read_exact(f, size, what):
    data = f.read(size)
    if len(data) != size:
        raise ValueError("truncated: %s needs %d bytes and the file ends after %d"
                         % (what, size, len(data)))
    return data

def _read_section(f, what):
    """One header section. Returns its tags and its bytes, magic included."""
    head = _read_exact(f, 16, what + " header")
    if head[:4] != _HEADER_MAGIC:
        raise ValueError("not an RPM: no header magic at the start of the %s"
                         % what)
    nindex, hsize = struct.unpack(">II", head[8:16])
    if nindex > _MAX_INDEX or hsize > _MAX_DATA:
        raise ValueError("the %s claims %d tags and %d bytes of data, which "
                         "no RPM carries" % (what, nindex, hsize))
    index = _read_exact(f, 16 * nindex, what + " index")
    data = _read_exact(f, hsize, what + " data")

    tags = {}
    for i in range(nindex):
        tag, kind, offset, _count = struct.unpack(">IIII", index[16 * i:16 * i + 16])
        if offset >= hsize:
            continue
        if kind == _TYPE_STRING:
            end = data.find(b"\0", offset)
            if end < 0:
                raise ValueError("tag %d in the %s is not terminated" % (tag, what))
            tags[tag] = data[offset:end].decode("utf-8", "replace")
        elif kind == _TYPE_INT32 and offset + 4 <= hsize:
            tags[tag] = struct.unpack(">I", data[offset:offset + 4])[0]
    return tags, head + index + data

def read_rpm_header(path):
    """name, epoch, version, release, arch and sha256header of one RPM file.

    Raises OSError when the file cannot be opened and ValueError when it is not
    an intact RPM. Only the lead and the two headers are read, never the
    payload, so a 100 MB firmware package costs a few kilobytes.
    """
    with open(path, "rb") as f:
        lead = f.read(_LEAD_SIZE)
        if len(lead) < 4 or struct.unpack(">I", lead[:4])[0] != _LEAD_MAGIC:
            raise ValueError("not an RPM: %s has no lead magic" % path)
        if len(lead) != _LEAD_SIZE:
            raise ValueError("truncated: %s ends inside the lead" % path)

        sig_tags, sig_raw = _read_section(f, "signature header")
        pad = -len(sig_raw) % 8
        if pad:
            _read_exact(f, pad, "signature header padding")
        main_tags, main_raw = _read_section(f, "main header")

    digest = hashlib.sha256(main_raw).hexdigest()
    recorded = sig_tags.get(_TAG_SIG_SHA256)
    if recorded is not None and recorded.lower() != digest:
        raise ValueError("the signature header of %s disagrees with its main "
                         "header: it records SHA256HEADER %s and the main header "
                         "hashes to %s; the file is damaged or was edited after "
                         "it was built" % (path, recorded, digest))

    for tag, label in ((_TAG_NAME, "NAME"), (_TAG_VERSION, "VERSION"),
                       (_TAG_RELEASE, "RELEASE"), (_TAG_ARCH, "ARCH")):
        if not main_tags.get(tag):
            raise ValueError("the header of %s carries no %s" % (path, label))

    return {
        "name": main_tags[_TAG_NAME],
        "epoch": main_tags.get(_TAG_EPOCH),
        "version": main_tags[_TAG_VERSION],
        "release": main_tags[_TAG_RELEASE],
        "arch": main_tags[_TAG_ARCH],
        "sha256header": digest,
    }

def _index_rpm_dir(rpm_dir):
    """{arch: set of file names} for each arch directory under rpm_dir.

    Listed once per directory: a lookup per package against a directory of
    thousands of files would list it thousands of times.
    """
    index = {}
    with os.scandir(rpm_dir) as arches:
        for arch in arches:
            if arch.is_dir():
                with os.scandir(arch.path) as files:
                    index[arch.name] = {f.name for f in files}
    return index

def read_package_sizes(pkgdata_dir):
    """{package: PKGSIZE} from a pkgdata directory's runtime-reverse files.

    Kept apart from report.read_pkgdata, whose result is published: a field
    added there would reach the report's "packages" map. A file with no size
    line contributes nothing, so a size of 0 always means pkgdata said so.
    """
    sizes = {}
    reverse = os.path.join(pkgdata_dir, "runtime-reverse")
    try:
        names = os.listdir(reverse)
    except OSError:
        return sizes
    for name in names:
        key = "PKGSIZE:%s: " % name
        try:
            with open(os.path.join(reverse, name), errors="ignore") as f:
                for line in f:
                    if line.startswith(key):
                        value = line[len(key):].strip()
                        if value.isdigit():
                            sizes[name] = int(value)
                        break
        except OSError:
            continue
    return sizes

def build_manifest(sources, machine=None, distro_version=None, now=None):
    """The document: every package the build produced, with its header digest.

    sources is a list of (packages, rpm_dir): packages is
    report.read_pkgdata()'s first return for one pkgdata directory, rpm_dir the
    deploy directory holding that build's RPMs. A second pair covers a second
    multiconfig, whose kernel is built at another version into its own tree.

    pkgdata says which version and release of each package this build made, and
    the deploy directory keeps every release ever built, so the file is named
    from pkgdata's PKGV-PKGR instead of globbed. Its arch is the directory it
    sits in. The header found there must then name the same package, or the
    digest would describe someone else's file.

    Raises ManifestError listing every package that cannot be listed. A gap is
    never skipped: a package missing here reads as unassessed downstream, which
    is a claim about the build and not a note about this file.
    """
    if not any(packages for packages, _rpm_dir in sources):
        raise ManifestError(["pkgdata names no package, so there is nothing to "
                             "list"])

    entries = {}
    problems = []
    for packages, rpm_dir in sources:
        try:
            index = _index_rpm_dir(rpm_dir)
        except OSError as e:
            problems.append("cannot list %s: %s" % (rpm_dir, e))
            continue

        for name in sorted(packages):
            version = packages[name]["version"]
            # The two become a path under rpm_dir. pkgdata is the build's own,
            # but a separator in one would read some other file's header, so it
            # is refused rather than assumed absent.
            if "/" in name or "/" in version:
                problems.append("%s: a path separator in the name or version %r"
                                % (name, version))
                continue

            pkgv, _sep, pkgr = version.rpartition("-")
            if not pkgv or not pkgr:
                problems.append("%s: pkgdata gives version %r with no release"
                                % (name, version))
                continue
            # rpm refuses "-" in a Version, so package_rpm writes "+" for it.
            # The file name carries the rpm's spelling, pkgdata the upstream one.
            rpm_version = pkgv.replace("-", "+")
            stem = "%s-%s-%s" % (name, rpm_version, pkgr)

            found = [arch for arch, files in sorted(index.items())
                     if "%s.%s.rpm" % (stem, arch) in files]
            if not found:
                # package_rpm writes no RPM for a package that holds nothing
                # unless ALLOW_EMPTY, while pkgdata still names it: PKGSIZE 0
                # and FILES_INFO {} is how avocado-core-dbg reads. That is a
                # fact about the build, not a gap in it. A size that is absent
                # says nothing, so only an explicit zero is excused, and an
                # empty package that does have an RPM (a packagegroup) is
                # still listed above.
                if packages[name].get("size") == 0:
                    continue
                problems.append("%s: no %s.<arch>.rpm under %s"
                                % (name, stem, rpm_dir))
                continue
            if len(found) > 1:
                problems.append("%s: %s.rpm exists in more than one arch "
                                "directory (%s) under %s"
                                % (name, stem, ", ".join(found), rpm_dir))
                continue

            arch = found[0]
            relative = "%s/%s.%s.rpm" % (arch, stem, arch)
            path = os.path.join(rpm_dir, relative)
            try:
                header = read_rpm_header(path)
            except (OSError, ValueError) as e:
                problems.append("%s: cannot read %s: %s" % (name, path, e))
                continue

            wrong = [
                "%s %r, expected %r" % (field, header[field], want)
                for field, want in (("name", name),
                                    ("version", rpm_version),
                                    ("release", pkgr), ("arch", arch))
                if header[field] != want
            ]
            if wrong:
                problems.append("%s: %s holds a different package (%s)"
                                % (name, path, "; ".join(wrong)))
                continue

            entry = {
                "name": header["name"],
                "epoch": header["epoch"],
                "version": header["version"],
                "release": header["release"],
                "arch": header["arch"],
                "sha256header": header["sha256header"],
                "file": relative,
            }
            key = (entry["name"], entry["arch"], entry["version"], entry["release"])
            seen = entries.get(key)
            if seen is None:
                entries[key] = entry
            elif (seen["sha256header"], seen["epoch"]) != (entry["sha256header"],
                                                          entry["epoch"]):
                problems.append("%s: two trees built %s-%s-%s.%s with different "
                                "headers (%s and %s), so the list cannot name one"
                                % (name, key[0], key[2], key[3], key[1],
                                   seen["sha256header"], entry["sha256header"]))

    if problems:
        raise ManifestError(problems)

    generated = (now or datetime.datetime.now(datetime.timezone.utc)
                 ).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"version": MANIFEST_VERSION, "generated": generated}
    if machine:
        doc["machine"] = machine
    if distro_version:
        doc["distro_version"] = distro_version
    doc["packages"] = [entries[key] for key in sorted(entries)]
    return doc

def check_manifest(doc):
    """Contract failures of a manifest document; empty when it holds.

    The same shape meta-avocado-sbom/schema/avocado-rpm-manifest-v1.schema.json
    states, checked without jsonschema so a build can run it. Unknown keys are
    allowed, as for the report.
    """
    if not isinstance(doc, dict):
        return ["the manifest is not an object"]

    failures = []
    if doc.get("version") != MANIFEST_VERSION:
        failures.append("version is %r, this checker implements %r"
                        % (doc.get("version"), MANIFEST_VERSION))
    generated = doc.get("generated")
    if not isinstance(generated, str) or not _GENERATED.match(generated):
        failures.append("generated %r is not a UTC second-resolution timestamp"
                        % (generated,))

    packages = doc.get("packages")
    if not isinstance(packages, list) or not packages:
        failures.append("the manifest lists no packages")
        return failures

    seen = set()
    keys = []
    for i, entry in enumerate(packages):
        where = "packages[%d]" % i
        if not isinstance(entry, dict):
            failures.append("%s is not an object" % where)
            continue
        for field in _ENTRY_FIELDS:
            if not isinstance(entry.get(field), str) or not entry.get(field):
                failures.append("%s.%s is missing or not a string" % (where, field))
        epoch = entry.get("epoch", "absent")
        if epoch == "absent" or not (epoch is None or (
                isinstance(epoch, int) and not isinstance(epoch, bool) and epoch >= 0)):
            failures.append("%s.epoch %r is not a non-negative integer or null"
                            % (where, epoch))
        digest = entry.get("sha256header")
        if isinstance(digest, str) and not _DIGEST.match(digest):
            failures.append("%s.sha256header %r is not 64 lowercase hex digits"
                            % (where, digest))
        path = entry.get("file")
        if isinstance(path, str) and path and (
                path.startswith("/") or ".." in path.split("/")):
            failures.append("%s.file %r must be relative and stay under the rpm "
                            "directory" % (where, path))

        # A second multiconfig builds a second kernel under the same name, so
        # the name and arch alone are not an identity: two versions are two
        # packages.
        key = (entry.get("name"), entry.get("arch"), entry.get("version"),
               entry.get("release"))
        if key in seen:
            failures.append("%s duplicates %s %s-%s" % (where, key[0], key[2], key[3]))
        seen.add(key)
        keys.append(key)

    if all(isinstance(part, str) for key in keys for part in key) \
            and keys != sorted(keys):
        failures.append("packages are not in (name, arch, version, release) order")
    return failures
