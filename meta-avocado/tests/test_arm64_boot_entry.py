# SPDX-License-Identifier: Apache-2.0
"""arm64 UEFI boot entry: kernel console arguments from SERIAL_CONSOLES.

The systemd-bootconf bbappend builds the delivered avocado.conf (the root
filesystem copy and the stone deploy copy) from the shipped entry with one
POSIX shell function, avocado_arm64_boot_entry. These tests extract that
function from the bbappend and run it under `sh -e`, so they exercise the same
code BitBake runs, without BitBake: an empty list must give the shipped entry
byte for byte, and each `<baud>;<tty>` entry appends `console=<tty>,<baud>n8`
to the options line.

BitBake cannot run in CI, so two things are pinned structurally rather than
executed: the arm64-uefi install and deploy steps both call the function with
"${SERIAL_CONSOLES}", and the machine include assigns SERIAL_CONSOLES weakly,
because BitBake parses local.conf before the machine file and a hard assignment
there would silently overwrite a kas overlay's value.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARM64 = ROOT / "meta-avocado-arm64"
BBAPPEND = ARM64 / "recipes-core" / "systemd" / "systemd-bootconf_%.bbappend"
SHIPPED = ARM64 / "recipes-core" / "systemd" / "files" / "avocado-boot.conf"
INCLUDE = ARM64 / "conf" / "machine" / "include" / "avocado-arm64-uefi.inc"
MACHINE = ARM64 / "conf" / "machine" / "avocado-arm64-uefi-v9.conf"

FUNC = "avocado_arm64_boot_entry"
OPTIONS = b"options root=PARTLABEL=rootfs-a ro console=tty0 earlycon pci=pcie_bus_safe"

# Any assignment form BitBake accepts, including override-qualified ones.
ASSIGN = re.compile(r"^\s*(?:export\s+)?SERIAL_CONSOLES(?::[\w:-]+)?\s*(\?\?=|\?=|:=|\+=|=\+|\.=|=\.|=)", re.M)


def function_source(text):
    """The whole `avocado_arm64_boot_entry() { ... }` definition, or None."""
    m = re.search(r"^%s\(\)\s*\{\n.*?^\}$" % FUNC, text, re.M | re.S)
    return m.group(0) if m else None


def function_body(text):
    src = function_source(text)
    return src[src.index("{") + 1 : src.rindex("}")] if src else None


def task_body(text, task):
    m = re.search(r"^%s\(\)\s*\{\n(.*?)^\}$" % re.escape(task), text, re.M | re.S)
    return m.group(1) if m else None


class ShippedEntry(unittest.TestCase):
    def test_shipped_options_line_is_pinned(self):
        lines = SHIPPED.read_bytes().split(b"\n")
        self.assertEqual([line for line in lines if line.startswith(b"options ")], [OPTIONS])
        self.assertTrue(SHIPPED.read_bytes().endswith(OPTIONS + b"\n"))


class BootEntryFunction(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        src = function_source(BBAPPEND.read_text())
        self.assertIsNotNone(src, "%s() is not defined in %s" % (FUNC, BBAPPEND.name))
        self.script = self.tmp / "run.sh"
        self.script.write_text(src + '\n%s "$1" "$2" "$3"\n' % FUNC)

    def run_func(self, consoles, src=SHIPPED, out=None):
        out = out or self.tmp / "out.conf"
        log = self.tmp / "stderr.log"
        with open(log, "wb") as err, open(self.tmp / "stdout.log", "wb") as stdout:
            proc = subprocess.run(
                ["sh", "-e", str(self.script), str(src), consoles, str(out)],
                stdout=stdout,
                stderr=err,
                timeout=30,
                start_new_session=True,
            )
        return proc.returncode, out, log.read_text()

    def expected(self, *args):
        """The shipped entry with `args` appended to its options line."""
        suffix = b"".join(b" " + a.encode() for a in args)
        return SHIPPED.read_bytes().replace(OPTIONS + b"\n", OPTIONS + suffix + b"\n")

    def test_empty_and_whitespace_only_lists_give_the_shipped_entry(self):
        for consoles in ["", " ", "\t", "  \t \n "]:
            with self.subTest(consoles=consoles):
                rc, out, err = self.run_func(consoles)
                self.assertEqual(rc, 0, err)
                self.assertEqual(out.read_bytes(), SHIPPED.read_bytes())

    def test_one_console_is_appended_to_the_options_line(self):
        rc, out, err = self.run_func("115200;ttyAMA0")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.read_bytes(), self.expected("console=ttyAMA0,115200n8"))

    def test_two_consoles_keep_their_order(self):
        rc, out, err = self.run_func("115200;ttyAMA0 9600;ttyS1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(
            out.read_bytes(),
            self.expected("console=ttyAMA0,115200n8", "console=ttyS1,9600n8"),
        )

    def test_third_field_ignored_and_mixed_whitespace_splits(self):
        rc, out, err = self.run_func("115200;ttyAMA0;vt102\t   9600;ttyS1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(
            out.read_bytes(),
            self.expected("console=ttyAMA0,115200n8", "console=ttyS1,9600n8"),
        )

    def test_malformed_entry_fails_names_it_and_leaves_no_output(self):
        for bad in ["ttyAMA0", "115200;", ";ttyAMA0"]:
            with self.subTest(entry=bad):
                out = self.tmp / ("bad-%d.conf" % len(bad))
                rc, out, err = self.run_func("9600;ttyS1 " + bad, out=out)
                self.assertNotEqual(rc, 0)
                self.assertIn(bad, err)
                self.assertFalse(out.exists())

    def test_shipped_file_is_never_written(self):
        before = SHIPPED.read_bytes()
        rc, _, err = self.run_func("115200;ttyAMA0 9600;ttyS1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(SHIPPED.read_bytes(), before)

    def test_missing_final_newline_is_preserved(self):
        src = self.tmp / "no-newline.conf"
        src.write_bytes(b"title X\n# options in a comment\noptions root=/dev/vda ro")
        rc, out, err = self.run_func("115200;ttyAMA0", src=src)
        self.assertEqual(rc, 0, err)
        self.assertEqual(
            out.read_bytes(),
            b"title X\n# options in a comment\noptions root=/dev/vda ro console=ttyAMA0,115200n8",
        )


class FunctionSource(unittest.TestCase):
    def body(self):
        body = function_body(BBAPPEND.read_text())
        self.assertIsNotNone(body, "%s() is not defined in %s" % (FUNC, BBAPPEND.name))
        return body

    def test_body_has_no_braced_expansion(self):
        # BitBake expands ${name} in shell bodies, so a braced local would be
        # replaced at parse time instead of reaching the shell.
        self.assertNotIn("${", self.body())

    def test_shellcheck_posix(self):
        self.body()
        if shutil.which("shellcheck") is None:
            self.skipTest("shellcheck not installed; POSIX lint not run")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "func.sh"
            script.write_text(function_source(BBAPPEND.read_text()) + "\n")
            log = Path(tmp) / "shellcheck.log"
            with open(log, "wb") as out:
                rc = subprocess.run(
                    ["shellcheck", "-s", "sh", str(script)],
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    timeout=60,
                    start_new_session=True,
                ).returncode
            self.assertEqual(rc, 0, log.read_text())

    def test_install_and_deploy_call_the_function_with_the_variable(self):
        text = BBAPPEND.read_text()
        for task, dest in [
            ("do_install:arm64-uefi", "${D}/boot/loader/entries/avocado.conf"),
            ("do_deploy:arm64-uefi", "${DEPLOYDIR}/avocado.conf"),
        ]:
            with self.subTest(task=task):
                body = task_body(text, task)
                self.assertIsNotNone(body, task)
                call = re.compile(
                    r'^\s*%s\s+\$\{S\}/avocado-boot\.conf\s+"\$\{SERIAL_CONSOLES\}"\s+%s\s*$'
                    % (FUNC, re.escape(dest)),
                    re.M,
                )
                self.assertRegex(body, call)
                self.assertNotIn("avocado-boot.conf " + dest, body.replace("${S}/", ""))

    def test_install_sets_mode_0644(self):
        body = task_body(BBAPPEND.read_text(), "do_install:arm64-uefi")
        self.assertIsNotNone(body)
        self.assertRegex(body, r"(?m)^\s*chmod 0644 \$\{D\}/boot/loader/entries/avocado\.conf\s*$")


class WeakDefault(unittest.TestCase):
    def test_include_assigns_serial_consoles_once_weakly_and_empty(self):
        hits = []
        for path in sorted(ARM64.rglob("*")):
            if path.is_file() and path.suffix in {".conf", ".inc", ".bb", ".bbappend", ".bbclass"}:
                for m in ASSIGN.finditer(path.read_text()):
                    line = path.read_text()[m.start() :].split("\n", 1)[0].strip()
                    hits.append((path.relative_to(ARM64).as_posix(), line))
        self.assertEqual(
            hits,
            [("conf/machine/include/avocado-arm64-uefi.inc", 'SERIAL_CONSOLES ?= ""')],
        )

    def test_v9_machine_does_not_assign_serial_consoles(self):
        self.assertIsNone(ASSIGN.search(MACHINE.read_text()))


class Pl011ConsoleOverlay(unittest.TestCase):
    """kas/feature/pl011-console.yml opts a device-tree platform into a PL011 console."""

    KAS = ROOT / "kas"
    OVERLAY = KAS / "feature" / "pl011-console.yml"

    def test_overlay_assigns_only_serial_consoles(self):
        text = self.OVERLAY.read_text()
        assigned = re.findall(r"^\s*([A-Za-z_][\w:.-]*)\s*(?:\?\?=|\?=|:=|\+=|=\+|\.=|=\.|=)\s*(.*)$", text, re.M)
        self.assertEqual(assigned, [("SERIAL_CONSOLES", '"115200;ttyAMA0"')])

    def test_overlay_is_not_referenced_by_any_other_kas_file(self):
        for path in sorted(self.KAS.rglob("*")):
            if path.is_file() and path != self.OVERLAY:
                self.assertNotIn("pl011-console", path.read_text(), path.relative_to(self.KAS).as_posix())

    def test_header_names_pl011_and_a_build_command_including_the_overlay(self):
        header = [ln for ln in self.OVERLAY.read_text().splitlines() if ln.startswith("#")]
        text = "\n".join(header)
        self.assertIn("PL011", text)
        self.assertRegex(text, r"bakar build \S*kas/machine/\S+\.yml:\S*kas/feature/pl011-console\.yml")


if __name__ == "__main__":
    unittest.main()
