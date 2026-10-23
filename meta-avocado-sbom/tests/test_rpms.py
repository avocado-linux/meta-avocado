#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""The RPM manifest names every package of an image with its header digest.

The RPMs here are built byte by byte, so the suite needs neither rpmbuild nor a
build. One test compares the reader with the real `rpm` where it is installed.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sbom import rpms  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "avocado-rpm-manifest.json")
SCHEMA = os.path.join(HERE, "..", "schema", "avocado-rpm-manifest-v1.schema.json")

MAGIC = b"\x8e\xad\xe8\x01\x00\x00\x00\x00"
STRING, INT32 = 6, 4

def header(tags):
    """An RPM header section: (tag, type, value) triples in, bytes out."""
    index = b""
    data = b""
    for tag, kind, value in tags:
        if kind == INT32:
            data += b"\0" * (-len(data) % 4)
            index += struct.pack(">IIII", tag, kind, len(data), 1)
            data += struct.pack(">i", value)
        else:
            index += struct.pack(">IIII", tag, kind, len(data), 1)
            data += value.encode() + b"\0"
    return MAGIC + struct.pack(">II", len(tags), len(data)) + index + data

def main_header(name, version, release, arch, epoch=None):
    tags = [(1000, STRING, name), (1001, STRING, version), (1002, STRING, release)]
    if epoch is not None:
        tags.append((1003, INT32, epoch))
    tags.append((1022, STRING, arch))
    return header(tags)

def rpm_bytes(name="foo", version="1.0", release="r0.1", arch="cortexa76",
              epoch=None, sig_digest="auto", payload=b"payload"):
    """A whole RPM. sig_digest "auto" signs the main header correctly, None
    leaves the signature header without a SHA256HEADER, anything else is
    written as given."""
    main = main_header(name, version, release, arch, epoch)
    sig_tags = [(1000, INT32, len(main) + len(payload))]
    if sig_digest == "auto":
        sig_tags.append((273, STRING, hashlib.sha256(main).hexdigest()))
    elif sig_digest is not None:
        sig_tags.append((273, STRING, sig_digest))
    sig = header(sig_tags)
    sig += b"\0" * (-len(sig) % 8)
    lead = struct.pack(">IBBHH66sHH16s", 0xEDABEEDB, 3, 0, 0, 1, b"x", 1, 5, b"")
    return lead + sig + main + payload

def main_bytes(*args, **kwargs):
    return main_header(*args, **kwargs)

class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="avocado-rpms-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, relpath, content, mode="wb"):
        path = os.path.join(self.tmp, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(content)
        return path

class ReadHeaderTests(Tree):
    def read(self, **kwargs):
        return rpms.read_rpm_header(self.write("x.rpm", rpm_bytes(**kwargs)))

    def test_fields_without_an_epoch(self):
        got = self.read(name="busybox", version="1.36.1", release="r0.4",
                        arch="cortexa76")
        self.assertEqual(
            {k: got[k] for k in ("name", "epoch", "version", "release", "arch")},
            {"name": "busybox", "epoch": None, "version": "1.36.1",
             "release": "r0.4", "arch": "cortexa76"})

    def test_epoch_is_an_integer(self):
        self.assertEqual(self.read(epoch=2)["epoch"], 2)

    def test_epoch_zero_is_not_absent(self):
        self.assertEqual(self.read(epoch=0)["epoch"], 0)

    def test_digest_is_sha256_of_the_main_header_alone(self):
        want = hashlib.sha256(main_bytes("foo", "1.0", "r0.1", "cortexa76")).hexdigest()
        self.assertEqual(self.read()["sha256header"], want)

    def test_payload_does_not_move_the_digest(self):
        a = self.read(payload=b"one")["sha256header"]
        b = self.read(payload=b"a much longer payload")["sha256header"]
        self.assertEqual(a, b)

    def test_header_content_moves_the_digest(self):
        a = self.read(release="r0.1")["sha256header"]
        b = self.read(release="r0.2")["sha256header"]
        self.assertNotEqual(a, b)

    def test_digest_is_lowercase_hex_of_64(self):
        digest = self.read()["sha256header"]
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_signature_header_that_disagrees_is_refused(self):
        path = self.write("x.rpm", rpm_bytes(sig_digest="0" * 64))
        with self.assertRaisesRegex(ValueError, "disagrees"):
            rpms.read_rpm_header(path)

    def test_signature_header_without_a_digest_is_accepted(self):
        got = self.read(sig_digest=None)
        want = hashlib.sha256(main_bytes("foo", "1.0", "r0.1", "cortexa76")).hexdigest()
        self.assertEqual(got["sha256header"], want)

    def test_a_file_that_is_not_an_rpm_is_refused(self):
        path = self.write("x.rpm", b"not an rpm at all" * 20)
        with self.assertRaisesRegex(ValueError, "not an RPM"):
            rpms.read_rpm_header(path)

    def test_a_truncated_file_is_refused(self):
        whole = rpm_bytes()
        path = self.write("x.rpm", whole[:len(whole) - 60])
        with self.assertRaises(ValueError):
            rpms.read_rpm_header(path)

    def test_an_empty_file_is_refused(self):
        with self.assertRaises(ValueError):
            rpms.read_rpm_header(self.write("x.rpm", b""))

    def test_a_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            rpms.read_rpm_header(os.path.join(self.tmp, "absent.rpm"))

    def test_a_header_without_a_name_is_refused(self):
        main = header([(1001, STRING, "1.0"), (1002, STRING, "r0.1"),
                       (1022, STRING, "noarch")])
        sig = header([(1000, INT32, 1)])
        sig += b"\0" * (-len(sig) % 8)
        lead = struct.pack(">IBBHH66sHH16s", 0xEDABEEDB, 3, 0, 0, 1, b"x", 1, 5, b"")
        path = self.write("x.rpm", lead + sig + main)
        with self.assertRaisesRegex(ValueError, "NAME"):
            rpms.read_rpm_header(path)

    @unittest.skipUnless(shutil.which("rpm"), "rpm not installed")
    def test_reader_agrees_with_rpm(self):
        path = self.write("x.rpm", rpm_bytes(epoch=3))
        out = subprocess.run(
            ["rpm", "--dbpath", self.tmp, "-qp", "--nosignature", "--nodigest",
             "--qf", "%{NAME}\t%{EPOCH}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SHA256HEADER}",
             path],
            capture_output=True, text=True, check=True).stdout.split("\t")
        got = rpms.read_rpm_header(path)
        self.assertEqual(out, [got["name"], str(got["epoch"]), got["version"],
                               got["release"], got["arch"], got["sha256header"]])

class ManifestTests(Tree):
    def setUp(self):
        super().setUp()
        self.rpm_dir = os.path.join(self.tmp, "deploy", "rpm")

    def rpm(self, name="foo", version="1.0", release="r0.1", arch="cortexa76",
            epoch=None, filename=None, rpm_dir=None):
        filename = filename or "%s-%s-%s.%s.rpm" % (name, version, release, arch)
        rpm_dir = rpm_dir or self.rpm_dir
        path = os.path.join(rpm_dir, arch, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(rpm_bytes(name, version, release, arch, epoch))

    @staticmethod
    def pkgdata(**names):
        return {n: {"recipe": n, "version": v, "origin": "x"} for n, v in names.items()}

    def build(self, packages, **kwargs):
        return rpms.build_manifest([(packages, self.rpm_dir)], machine="avocado-test",
                                   **kwargs)

    def test_one_entry_per_package(self):
        self.rpm("foo")
        self.rpm("bar", version="2.5", arch="noarch")
        doc = self.build(self.pkgdata(foo="1.0-r0.1", bar="2.5-r0.1"))
        self.assertEqual([p["name"] for p in doc["packages"]], ["bar", "foo"])

    def test_entry_carries_every_agreed_field(self):
        self.rpm("foo", epoch=1)
        entry = self.build(self.pkgdata(foo="1.0-r0.1"))["packages"][0]
        self.assertEqual(sorted(entry), sorted(
            ["name", "epoch", "version", "release", "arch", "sha256header", "file"]))
        self.assertEqual(entry["epoch"], 1)
        self.assertEqual(entry["version"], "1.0")
        self.assertEqual(entry["release"], "r0.1")
        self.assertEqual(entry["arch"], "cortexa76")

    def test_arch_comes_from_the_directory_the_file_is_in(self):
        self.rpm("a", arch="noarch")
        self.rpm("b", arch="cortexa76")
        doc = self.build(self.pkgdata(a="1.0-r0.1", b="1.0-r0.1"))
        self.assertEqual({p["name"]: p["arch"] for p in doc["packages"]},
                         {"a": "noarch", "b": "cortexa76"})

    def test_file_is_the_path_under_the_rpm_directory(self):
        self.rpm("foo")
        entry = self.build(self.pkgdata(foo="1.0-r0.1"))["packages"][0]
        self.assertEqual(entry["file"], "cortexa76/foo-1.0-r0.1.cortexa76.rpm")

    def test_digest_matches_the_file_on_disk(self):
        self.rpm("foo")
        entry = self.build(self.pkgdata(foo="1.0-r0.1"))["packages"][0]
        path = os.path.join(self.rpm_dir, entry["file"])
        self.assertEqual(entry["sha256header"], rpms.read_rpm_header(path)["sha256header"])

    def test_output_does_not_depend_on_dict_order(self):
        self.rpm("foo")
        self.rpm("bar", version="2.5", arch="noarch")
        a = self.build(self.pkgdata(foo="1.0-r0.1", bar="2.5-r0.1"))["packages"]
        b = self.build(self.pkgdata(bar="2.5-r0.1", foo="1.0-r0.1"))["packages"]
        self.assertEqual(a, b)

    def test_the_release_in_pkgdata_picks_between_releases_on_disk(self):
        self.rpm("foo", release="r0.1")
        self.rpm("foo", release="r0.2")
        entry = self.build(self.pkgdata(foo="1.0-r0.2"))["packages"][0]
        self.assertEqual(entry["release"], "r0.2")

    def test_a_hyphen_in_the_upstream_version_is_a_plus_in_the_rpm(self):
        # rpm refuses "-" in a Version, so package_rpm writes "+". pkgdata
        # still carries the upstream PKGV, and joining it to the PKGR with a
        # hyphen leaves two of them (observed: libedit 20230828-3.1).
        self.rpm("libedit0", version="20230828+3.1")
        entry = self.build(self.pkgdata(libedit0="20230828-3.1-r0.1"))["packages"][0]
        self.assertEqual((entry["version"], entry["release"]), ("20230828+3.1", "r0.1"))
        self.assertEqual(entry["file"], "cortexa76/libedit0-20230828+3.1-r0.1.cortexa76.rpm")

    def test_envelope_names_the_machine_and_the_version(self):
        self.rpm("foo")
        doc = self.build(self.pkgdata(foo="1.0-r0.1"), distro_version="2026.0+1.gabc")
        self.assertEqual((doc["version"], doc["machine"], doc["distro_version"]),
                         ("1", "avocado-test", "2026.0+1.gabc"))
        self.assertRegex(doc["generated"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_distro_version_is_absent_when_not_given(self):
        self.rpm("foo")
        self.assertNotIn("distro_version", self.build(self.pkgdata(foo="1.0-r0.1")))

    def test_missing_rpm_is_an_error_naming_the_package(self):
        os.makedirs(os.path.join(self.rpm_dir, "cortexa76"))
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.pkgdata(foo="1.0-r0.1"))
        self.assertIn("foo", str(caught.exception))
        self.assertIn("foo-1.0-r0.1", str(caught.exception))

    def test_every_problem_is_reported_not_the_first(self):
        self.rpm("ok")
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.pkgdata(ok="1.0-r0.1", foo="1.0-r0.1", bar="2.5-r0.1",
                                    baz="3.0-r0.1"))
        self.assertEqual(len(caught.exception.problems), 3)

    def test_pkgdata_version_without_a_release_is_an_error(self):
        self.rpm("other")
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.pkgdata(foo="1.0"))
        self.assertIn("release", str(caught.exception))

    def test_file_whose_header_names_another_package_is_an_error(self):
        self.rpm("other", filename="foo-1.0-r0.1.cortexa76.rpm")
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.pkgdata(foo="1.0-r0.1"))
        self.assertIn("other", str(caught.exception))

    def test_unreadable_rpm_is_an_error(self):
        path = os.path.join(self.rpm_dir, "cortexa76", "foo-1.0-r0.1.cortexa76.rpm")
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as f:
            f.write(b"junk" * 50)
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.pkgdata(foo="1.0-r0.1"))
        self.assertIn("foo", str(caught.exception))

    def test_one_package_in_two_arch_directories_is_ambiguous(self):
        self.rpm("foo", arch="cortexa76")
        self.rpm("foo", arch="noarch", filename="foo-1.0-r0.1.noarch.rpm")
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.pkgdata(foo="1.0-r0.1"))
        self.assertIn("more than one", str(caught.exception))

    def test_a_package_name_with_a_path_separator_is_refused(self):
        self.rpm("foo")
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.pkgdata(**{"../../etc/passwd": "1.0-r0.1"}))
        self.assertIn("path separator", str(caught.exception))

    def sized(self, **sizes):
        """pkgdata entries carrying PKGSIZE, as the recipe passes them."""
        return {n: {"recipe": n, "version": "1.0-r0.1", "origin": "x", "size": s}
                for n, s in sizes.items()}

    def test_a_package_with_no_files_and_no_rpm_was_never_built(self):
        # package_rpm writes no RPM for a package that holds nothing unless
        # ALLOW_EMPTY, while pkgdata still names it: avocado-core-dbg, with
        # PKGSIZE 0 and FILES_INFO {}.
        self.rpm("real")
        doc = self.build(self.sized(real=1234, avocado_core_dbg=0))
        self.assertEqual([p["name"] for p in doc["packages"]], ["real"])

    def test_a_package_with_no_files_that_does_have_an_rpm_is_listed(self):
        # ALLOW_EMPTY: a packagegroup is an RPM that holds nothing but depends.
        self.rpm("packagegroup-x")
        doc = self.build(self.sized(**{"packagegroup-x": 0}))
        self.assertEqual([p["name"] for p in doc["packages"]], ["packagegroup-x"])

    def test_a_package_with_files_and_no_rpm_is_still_an_error(self):
        self.rpm("other")
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.sized(other=10, foo=4096))
        self.assertIn("foo", str(caught.exception))

    def test_a_package_of_unknown_size_and_no_rpm_is_still_an_error(self):
        # Nothing says it is empty, so its absence is a gap and not a fact.
        self.rpm("other")
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.sized(other=10, foo=None))
        self.assertIn("foo", str(caught.exception))

    def test_a_package_with_no_files_and_no_rpm_in_one_tree_does_not_hide_a_real_one(self):
        alt = os.path.join(self.tmp, "alt", "rpm")
        self.rpm("kernel", version="6.6", rpm_dir=alt)
        doc = rpms.build_manifest(
            [(self.sized(dbg=0), self.rpm_dir_with_something()),
             ({"kernel": {"recipe": "kernel", "version": "6.6-r0.1", "origin": "x",
                          "size": 5}}, alt)])
        self.assertEqual([p["name"] for p in doc["packages"]], ["kernel"])

    def rpm_dir_with_something(self):
        self.rpm("filler")
        return self.rpm_dir

    def test_no_packages_is_an_error_not_an_empty_list(self):
        with self.assertRaises(rpms.ManifestError):
            self.build({})

    def test_a_missing_rpm_directory_is_an_error_naming_it(self):
        with self.assertRaises(rpms.ManifestError) as caught:
            self.build(self.pkgdata(foo="1.0-r0.1"))
        self.assertIn(self.rpm_dir, str(caught.exception))

    def test_second_source_lists_what_a_second_multiconfig_built(self):
        alt = os.path.join(self.tmp, "alt", "rpm")
        self.rpm("kernel", version="6.12", release="r0.1")
        self.rpm("kernel", version="6.6", release="r0.1", rpm_dir=alt)
        doc = rpms.build_manifest(
            [(self.pkgdata(kernel="6.12-r0.1"), self.rpm_dir),
             (self.pkgdata(kernel="6.6-r0.1"), alt)], machine="avocado-test")
        self.assertEqual([(p["name"], p["version"]) for p in doc["packages"]],
                         [("kernel", "6.12"), ("kernel", "6.6")])
        self.assertEqual(rpms.check_manifest(doc), [])

    def test_output_does_not_depend_on_source_order(self):
        alt = os.path.join(self.tmp, "alt", "rpm")
        self.rpm("kernel", version="6.12", release="r0.1")
        self.rpm("kernel", version="6.6", release="r0.1", rpm_dir=alt)
        main = (self.pkgdata(kernel="6.12-r0.1"), self.rpm_dir)
        other = (self.pkgdata(kernel="6.6-r0.1"), alt)
        a = rpms.build_manifest([main, other])["packages"]
        b = rpms.build_manifest([other, main])["packages"]
        self.assertEqual(a, b)

    def test_the_same_package_from_both_sources_is_listed_once(self):
        alt = os.path.join(self.tmp, "alt", "rpm")
        self.rpm("foo")
        self.rpm("foo", rpm_dir=alt)
        doc = rpms.build_manifest(
            [(self.pkgdata(foo="1.0-r0.1"), self.rpm_dir),
             (self.pkgdata(foo="1.0-r0.1"), alt)], machine="avocado-test")
        self.assertEqual(len(doc["packages"]), 1)

    def test_the_same_package_with_different_headers_is_an_error(self):
        alt = os.path.join(self.tmp, "alt", "rpm")
        self.rpm("foo", epoch=1)
        self.rpm("foo", rpm_dir=alt)
        with self.assertRaises(rpms.ManifestError) as caught:
            rpms.build_manifest(
                [(self.pkgdata(foo="1.0-r0.1"), self.rpm_dir),
                 (self.pkgdata(foo="1.0-r0.1"), alt)], machine="avocado-test")
        self.assertIn("different", str(caught.exception))

class PackageSizesTests(Tree):
    def write_pkgdata(self, name, size_line):
        directory = os.path.join(self.tmp, "pkgdata", "runtime-reverse")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, name), "w") as f:
            f.write("PN: x\nPKGV: 1.0\nPKGR: r0.1\n%s\n" % size_line)
        return os.path.join(self.tmp, "pkgdata")

    def test_the_size_is_read_off_the_packages_own_key(self):
        d = self.write_pkgdata("busybox", "PKGSIZE:busybox: 767309")
        self.assertEqual(rpms.read_package_sizes(d), {"busybox": 767309})

    def test_zero_is_a_size(self):
        d = self.write_pkgdata("avocado-core-dbg", "PKGSIZE:avocado-core-dbg: 0")
        self.assertEqual(rpms.read_package_sizes(d), {"avocado-core-dbg": 0})

    def test_a_file_without_a_size_is_absent_not_zero(self):
        d = self.write_pkgdata("odd", "LICENSE: MIT")
        self.assertEqual(rpms.read_package_sizes(d), {})

    def test_another_packages_size_in_the_file_is_not_this_ones(self):
        d = self.write_pkgdata("foo", "PKGSIZE:foo-dev: 12")
        self.assertEqual(rpms.read_package_sizes(d), {})

    def test_a_missing_directory_reads_nothing(self):
        self.assertEqual(rpms.read_package_sizes(os.path.join(self.tmp, "none")), {})

class CheckTests(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE) as f:
            self.doc = json.load(f)

    def assertCaught(self, substring):
        failures = rpms.check_manifest(self.doc)
        self.assertTrue(any(substring in f for f in failures),
                        "not caught (%r): %s" % (substring, failures))

    def test_fixture_passes(self):
        self.assertEqual(rpms.check_manifest(self.doc), [])

    def test_unknown_major_is_caught(self):
        self.doc["version"] = "2"
        self.assertCaught("version")

    def test_empty_package_list_is_caught(self):
        self.doc["packages"] = []
        self.assertCaught("no packages")

    def test_missing_field_is_caught(self):
        del self.doc["packages"][0]["sha256header"]
        self.assertCaught("sha256header")

    def test_short_digest_is_caught(self):
        self.doc["packages"][0]["sha256header"] = "abc"
        self.assertCaught("sha256header")

    def test_uppercase_digest_is_caught(self):
        self.doc["packages"][0]["sha256header"] = self.doc["packages"][0]["sha256header"].upper()
        self.assertCaught("sha256header")

    def test_string_epoch_is_caught(self):
        self.doc["packages"][0]["epoch"] = "1"
        self.assertCaught("epoch")

    def test_boolean_epoch_is_caught(self):
        self.doc["packages"][0]["epoch"] = True
        self.assertCaught("epoch")

    def test_duplicate_package_is_caught(self):
        self.doc["packages"].append(dict(self.doc["packages"][0]))
        self.assertCaught("duplicate")

    def test_unsorted_packages_are_caught(self):
        self.doc["packages"].reverse()
        self.assertCaught("order")

    def test_absolute_file_path_is_caught(self):
        self.doc["packages"][0]["file"] = "/" + self.doc["packages"][0]["file"]
        self.assertCaught("file")

    def test_file_that_climbs_out_is_caught(self):
        self.doc["packages"][0]["file"] = "../" + self.doc["packages"][0]["file"]
        self.assertCaught("file")

    def test_added_key_is_allowed(self):
        self.doc["packages"][0]["extra"] = 1
        self.doc["note"] = "x"
        self.assertEqual(rpms.check_manifest(self.doc), [])

class SchemaTests(unittest.TestCase):
    def setUp(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed")
        with open(SCHEMA) as f:
            self.schema = json.load(f)
        with open(FIXTURE) as f:
            self.doc = json.load(f)

    def test_fixture_validates(self):
        import jsonschema
        jsonschema.validate(self.doc, self.schema)

    def test_schema_refuses_a_missing_digest(self):
        import jsonschema
        del self.doc["packages"][0]["sha256header"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.doc, self.schema)

    def test_schema_refuses_a_string_epoch(self):
        import jsonschema
        self.doc["packages"][0]["epoch"] = "1"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.doc, self.schema)

    def test_schema_and_checker_agree_on_the_fixture_mutations(self):
        import jsonschema
        for mutate in (
            lambda d: d.update(version="2"),
            lambda d: d["packages"][0].update(sha256header="abc"),
            lambda d: d["packages"][0].update(epoch=True),
        ):
            doc = json.loads(json.dumps(self.doc))
            mutate(doc)
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(doc, self.schema)
            self.assertTrue(rpms.check_manifest(doc))

if __name__ == "__main__":
    unittest.main()
