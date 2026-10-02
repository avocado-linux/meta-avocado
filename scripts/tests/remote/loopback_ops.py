"""Board side of the loopback harness: the ops the real runner.pyz is given (task 5.23).

Imported by the entry script inside the runner process, next to the bundled
``avocado_flash_remote`` package, so it may import nothing host-side.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import time

from avocado_flash_remote import layout
from avocado_flash_remote.ops import Call, OpResult, RecordingOps

PKG = pathlib.Path(__file__).resolve().parent.parent.parent / "avocado_flash_remote"
FIXTURE_PROFILE = PKG / "profiles" / "fixture-none.json"
MACHINE_ID = "0123456789abcdef0123456789abcdef"
DEVICE = "/dev/vdz"  # the shipped fixture names /dev/loop-fixture, which the runner's own device check refuses
HOLD_FILE = "hold-dd"
IN_DD_FILE = "in-dd"
HOLD_TIMEOUT = 60.0


def loopback_profile(stage, state):
    """The fixture-none profile retargeted at a virtio-style node and at paths under the board root."""
    prof = json.loads(FIXTURE_PROFILE.read_text())
    prof["target"]["device"] = DEVICE
    prof["target"]["identity"]["value"] = DEVICE.rsplit("/", 1)[1]
    prof["checks"] = [
        "emmc-exists", "emmc-not-read-only", "emmc-sector-count", "emmc-no-partition-table",
        "emmc-not-mounted", "staged-images-present", "staged-image-checksums", "staging-space-free",
    ]  # the fixture's own names have no implementation behind them
    prof["staging"]["dir"] = str(stage)
    prof["state_dir"] = str(state)
    return prof


class LoopOps(RecordingOps):
    """Answers the fixture-none board's reads; raises on anything it was not taught."""

    def __init__(self, root):
        super().__init__({})
        self.root = pathlib.Path(root)
        profile = json.loads(FIXTURE_PROFILE.read_text())
        self.sectors = profile["target"]["sectors"]
        self.layout_params = profile["layout"]["params"]
        self.table = self.layout_params["table"]
        self.images = {i["partition"]: i["file"] for i in profile["images"].values()}
        self.stage = self.root / "stage"
        self.partitioned = False  # flips when this process runs sfdisk; plan and write are separate processes

    def _check_manifest(self):
        lines = []
        for row in (self.stage / "MANIFEST.hashes").read_text().splitlines():
            digest, name = row.split(None, 1)
            ok = hashlib.sha256((self.stage / name).read_bytes()).hexdigest() == digest
            lines.append(f"{name}: {'OK' if ok else 'FAILED'}\n")
        return "".join(lines)

    def _image_sha(self, number):
        data = (self.stage / self.images[number]).read_bytes()
        return hashlib.sha256(data).hexdigest()

    def _exec(self, vec, *, stdin=None, timeout=None, cwd=None, digest=False):
        res = self._answer(list(vec), stdin)
        if res is not None:
            self.calls.append(_call(vec, stdin))
            return res
        return super()._exec(vec, stdin=stdin, timeout=timeout, cwd=cwd, digest=digest)

    def _answer(self, vec, stdin):
        line = " ".join(vec)
        node = lambda n: f"{DEVICE}{n}"  # noqa: E731 - same naming the layout module uses for this device
        if vec[:3] == ["lsblk", "-rn", "-o"] and vec[-1] == DEVICE:
            return OpResult(stdout=b"loop-fixture disk\n" if vec[3] == "NAME,TYPE" else b"disk\n")
        if line == f"blockdev --getro {DEVICE}":
            return OpResult(stdout=b"0\n")
        if line == f"blockdev --getsz {DEVICE}":
            return OpResult(stdout=f"{self.sectors}\n".encode())
        if vec[:3] == ["sha256sum", "--strict", "-c"]:
            return OpResult(stdout=self._check_manifest().encode())
        if vec[:2] == ["df", "-Pk"]:
            # The one read-only tool run for real: the staging path is under the board root.
            done = subprocess.run(vec, capture_output=True, check=False)
            return OpResult(rc=done.returncode, stdout=done.stdout, stderr=done.stderr.decode())
        if vec[:3] == ["stat", "-c", "%s"]:
            return OpResult(stdout=f"{pathlib.Path(vec[3]).stat().st_size}\n".encode())
        if vec[:3] == ["findmnt", "-no", "FSTYPE"]:
            return OpResult(stdout=b"tmpfs\n")
        if vec[:3] == ["findmnt", "-no", "SOURCE"]:
            return OpResult(stdout=b"tmpfs\n")
        if line == "findmnt -rn -o SOURCE":
            return OpResult(stdout=b"/dev/sda1\n")
        if vec[:2] == ["blockdev", "--getsize64"]:
            for part in self.table:
                if vec[2] == node(part["number"]):
                    return OpResult(stdout=f"{part['size'] * 512}\n".encode())
        if line == f"sfdisk --dump {DEVICE}":
            if self.partitioned:
                return OpResult(stdout=layout.sfdisk_input(self.layout_params, DEVICE).encode())
            return OpResult(rc=1, stderr=f"sfdisk: {DEVICE}: does not contain a recognized partition table\n")
        if vec[0] == "sfdisk" and vec[1:2] != ["--dump"]:
            self.partitioned = True
            return OpResult()
        if vec[0] == "dd" and any(a.startswith("of=") for a in vec):
            self._hold()
            return OpResult()
        if vec[0] == "dd" and any(a.startswith("if=" + DEVICE) for a in vec):
            number = int(next(a for a in vec if a.startswith("if=")).split(DEVICE)[1])
            return OpResult(digest=self._image_sha(number))
        return None

    def _hold(self):
        hold = self.root / HOLD_FILE
        if not hold.exists():
            return
        (self.root / IN_DD_FILE).write_text("in dd")
        end = time.monotonic() + HOLD_TIMEOUT
        while hold.exists() and time.monotonic() < end:
            time.sleep(0.02)

    def _fs(self, kind, path, data=None):
        if kind == "read_file" and path.startswith(str(self.root)):
            self.calls.append(_call([kind, path], None, kind="fs"))
            return pathlib.Path(path).read_bytes()
        if kind == "read_file" and path == "/etc/machine-id":
            self.calls.append(_call([kind, path], None, kind="fs"))
            return (MACHINE_ID + "\n").encode()
        return super()._fs(kind, path, data)


def _call(vec, stdin, kind="exec"):
    return Call(list(vec), stdin, kind=kind)
