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

from avocado_flash_remote.ops import Call, OpResult, RecordingOps, UnscriptedCall, vector_mutates

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
    prof["checks"] = [
        "emmc-exists", "emmc-not-read-only", "emmc-sector-count", "emmc-no-partition-table",
        "emmc-not-mounted", "staged-images-present", "staged-image-checksums", "staging-space-free",
        "target-identity",
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
        self.sfdisk_input = b""  # what sfdisk was last given, which is all a later --dump can truthfully return
        self.written_dir = self.root / "written"  # bytes each partition holds, kept on disk: readback is another process

    def _fault(self, name):
        path = self.root / f"fault-{name}"
        return path.read_text().strip() if path.exists() else None

    def _partition_number(self, node):
        for part in self.table:
            if node == f"{DEVICE}{part['number']}":
                return part["number"]
        return None

    def _write_partition(self, vec):
        src = next(a[3:] for a in vec if a.startswith("if="))
        dst = next(a[3:] for a in vec if a.startswith("of="))
        if not self.partitioned:
            raise UnscriptedCall(f"dd to {dst} but no partition table exists on {DEVICE}")
        number = self._partition_number(dst)
        if number is None:
            raise UnscriptedCall(f"dd of={dst} is not a partition of the table on {DEVICE}")
        skip = self._fault("skip-dd")
        if skip is not None and int(skip) == number:
            return  # a dd that reported success and wrote nothing
        mis = self._fault("misdirect-dd")
        if mis is not None and int(mis.split(":")[0]) == number:
            number = int(mis.split(":")[1])
        self.written_dir.mkdir(exist_ok=True)
        (self.written_dir / str(number)).write_bytes(pathlib.Path(src).read_bytes())

    def _read_partition_sha(self, vec):
        number = int(next(a for a in vec if a.startswith("if=")).split(DEVICE)[1])
        path = self.written_dir / str(number)
        count = next((int(a.split("=")[1]) for a in vec if a.startswith("count=")), None)
        data = path.read_bytes() if path.exists() else b"\0" * (count or 0) + b"unwritten"
        if count is not None and path.exists():
            data = data[:count]
        return hashlib.sha256(data).hexdigest()

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
        if vector_mutates(vec):
            raise UnscriptedCall(f"loopback board was not taught this mutating command: {' '.join(vec)}")
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
        if len(vec) == 2 and vec[1] == "--version" and vec[0] in ("install", "sha256sum", "dd"):
            return OpResult(stdout=f"{vec[0]} (GNU coreutils) 9.4\n".encode())
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
                return OpResult(stdout=self.sfdisk_input)
            return OpResult(rc=1, stderr=f"sfdisk: {DEVICE}: does not contain a recognized partition table\n")
        if vec[0] == "sfdisk" and vec[1:2] != ["--dump"]:
            if self._fault("skip-sfdisk") is None:
                self.partitioned = True
                self.sfdisk_input = bytes(stdin or b"")
            return OpResult()
        if vec == ["udevadm", "settle"]:
            return OpResult()  # waits for device events; changes nothing on the board
        if vec[:2] == ["blockdev", "--flushbufs"] and len(vec) == 3 and vec[2].startswith(DEVICE):
            return OpResult()  # the fixture's read-back reads its backing files directly: no cache to drop
        if vec[0] == "dd" and any(a.startswith("of=") for a in vec):
            self._write_partition(vec)
            self._hold()
            return OpResult()
        if vec[0] == "dd" and any(a.startswith("if=" + DEVICE) for a in vec):
            return OpResult(digest=self._read_partition_sha(vec))
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
        graph = self._block_graph(kind, path)
        if graph is not None:
            self.calls.append(_call([kind, path], None, kind="fs"))
            if isinstance(graph, BaseException):
                raise graph
            return graph
        if kind == "read_file" and path == f"/sys/block/{DEVICE.rsplit('/', 1)[1]}/device/serial":
            self.calls.append(_call([kind, path], None, kind="fs"))
            return b"0x0fixture\n"
        if kind == "read_file" and path == "/etc/machine-id":
            self.calls.append(_call([kind, path], None, kind="fs"))
            return (MACHINE_ID + "\n").encode()
        return super()._fs(kind, path, data)


    def _block_graph(self, kind, path):
        """The sysfs reads the root-backing guard makes, for this board's two disks (the target and a foreign sda)."""
        disks = {DEVICE.rsplit("/", 1)[1]: (), "sda": ()}
        parts = {"sda1": "sda"}
        if kind == "realpath" and path.startswith("/dev/"):
            name = path[len("/dev/"):]
            return path if name in disks or name in parts else FileNotFoundError(path)
        if kind == "realpath" and path.startswith("/sys/class/block/"):
            name = path[len("/sys/class/block/"):]
            if name in disks:
                return f"/sys/devices/virtual/block/{name}"
            if name in parts:
                return f"/sys/devices/virtual/block/{parts[name]}/{name}"
            return FileNotFoundError(path)
        if kind == "read_file" and path.startswith("/sys/class/block/") and path.endswith("/partition"):
            name = path[len("/sys/class/block/"):-len("/partition")]
            return b"1\n" if name in parts else FileNotFoundError(path)
        if kind == "read_file" and path.startswith("/sys/class/block/") and path.endswith("/loop/backing_file"):
            return FileNotFoundError(path)
        if kind == "listdir" and path.startswith("/sys/class/block/") and path.endswith("/slaves"):
            return [] if path[len("/sys/class/block/"):-len("/slaves")] in disks else FileNotFoundError(path)
        return None


def _call(vec, stdin, kind="exec"):
    return Call(list(vec), stdin, kind=kind)
