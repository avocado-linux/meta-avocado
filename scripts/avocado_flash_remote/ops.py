"""Operations interface for every board action.

Every command the remote backend runs on a board goes through an ``Ops``
object, so plan and check code can be tested without a board and a
read-only run can be proven not to mutate anything.

Three implementations share the interface:

* ``RealOps`` runs the tools with the bash kit's exact argument vectors.
* ``RecordingOps`` records each call in the kit's STUB_LOG line format
  (tool basename followed by its argv, space separated) and returns
  scripted results; an unscripted read is an explicit error.
* ``ReadOnlyOps`` wraps another ``Ops`` and refuses every mutating verb
  before anything is launched.

Each verb has a pure ``vec_<verb>`` static method that builds the argument
vector, so tests assert vectors without executing. The comment on each
builder names the kit script the vector comes from (the bring-up change's
``emmc/`` evidence directory: install.sh, preflight.sh, readback.sh).

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import tempfile
from dataclasses import dataclass

DEFAULT_TIMEOUT = 60.0
DD_WRITE_TIMEOUT = 1800.0
TERM_GRACE = 2.0
# PATH is not trusted: without an explicit tool directory these fixed
# system directories are searched, never the inherited PATH.
DEFAULT_TOOL_DIRS = ("/usr/sbin", "/usr/bin", "/sbin", "/bin")

_BOOT_ENTRY_RE = re.compile(r"^[0-9A-Fa-f]{4}$")


class OpsError(Exception):
    """Base class for operations-layer failures."""


class MutationRefused(OpsError):
    """A read-only Ops was asked to mutate; raised before any launch."""


class UnscriptedCall(OpsError):
    """RecordingOps was asked for a read it has no scripted result for."""


class OpFailed(OpsError):
    """A tool exited non-zero, timed out or could not be started."""

    def __init__(self, vector, rc, stderr=""):
        self.vector = list(vector)
        self.rc = rc
        self.stderr = stderr
        super().__init__(f"{' '.join(self.vector)} failed (rc={rc}): {stderr.strip()[:300]}")


@dataclass
class OpResult:
    rc: int = 0
    stdout: bytes = b""
    stderr: str = ""
    digest: str = ""

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")


@dataclass
class Call:
    """One recorded call: the vector plus anything fed on stdin."""

    vector: list
    stdin: bytes | None = None
    kind: str = "exec"

    @property
    def line(self) -> str:
        return " ".join(self.vector)


# ---------------------------------------------------------------- classify

_BLOCKDEV_READ = {"--getsz", "--getro", "--getsize64", "--getss", "--getbsz", "--getsize", "--report"}
_SFDISK_READ = {"--dump", "-d", "-l", "--list", "-J", "--json", "-F", "--list-free", "-V", "--verify"}
_SFDISK_WRITE = {
    "--delete", "-D", "--force", "-f", "--part-attrs", "--part-label", "--part-type",
    "--part-uuid", "--relocate", "--reorder", "-r", "--activate", "-A", "--wipe", "-w",
    "--wipe-partitions", "-W", "--append", "-N", "--move-data", "--backup", "-O",
}  # fmt: skip
_EFIBOOTMGR_READ = {"-v", "--verbose", "-h", "--help", "-V", "--version"}
# Filesystem seam kinds that only read; everything else through ``_fs`` mutates.
FS_READ_KINDS = ("read_file", "realpath", "listdir")
_PLAIN_READ_TOOLS = {"findmnt", "lsblk", "sha256sum", "stat", "od", "df", "uname", "ls"}


def vector_mutates(vec) -> bool:
    """True when the vector may change state; unknown tools count as mutating."""
    if not vec:
        return True
    tool = os.path.basename(vec[0])
    args = list(vec[1:])
    if tool == "blockdev":
        return not (args and all(a in _BLOCKDEV_READ or a.startswith("/") for a in args) and any(a in _BLOCKDEV_READ for a in args))
    if tool == "sfdisk":
        return not (any(a in _SFDISK_READ for a in args) and not any(a in _SFDISK_WRITE for a in args))
    if tool == "efibootmgr":
        return not all(a in _EFIBOOTMGR_READ for a in args)
    if tool == "blkid":
        return any(a in ("-g", "--garbage-collect", "-w", "--write-cache") for a in args)
    if tool == "dd":
        return any(a.startswith("of=") for a in args)
    if tool == "docker":
        return args[:1] != ["ps"]
    if tool in _PLAIN_READ_TOOLS:
        return False
    return True


# -------------------------------------------------------------------- Ops


class Ops:
    """Interface every board action goes through.

    Verbs build their vector via ``vec_<verb>`` and run it through
    ``_run``. Mutating verbs call ``_gate`` first so a read-only wrapper
    refuses before anything is launched.
    """

    # ------------------------------------------------------------ plumbing

    def _gate(self, verb: str, mutating: bool) -> None:
        """Hook: ReadOnlyOps raises here for mutating verbs."""

    def _exec(self, vec, *, stdin=None, timeout=None, cwd=None, digest=False) -> OpResult:
        raise NotImplementedError

    def _fs(self, kind: str, path: str, data=None):
        raise NotImplementedError

    def _run(self, vec, *, check=True, stdin=None, timeout=None, cwd=None, digest=False) -> OpResult:
        res = self._exec(vec, stdin=stdin, timeout=timeout, cwd=cwd, digest=digest)
        if check and res.rc != 0:
            raise OpFailed(vec, res.rc, res.stderr)
        return res

    # ------------------------------------------------------ vector builders

    @staticmethod
    def vec_blockdev_getsz(dev):  # install.sh:262, preflight.sh:121
        return ["blockdev", "--getsz", dev]

    @staticmethod
    def vec_blockdev_getro(dev):  # preflight.sh:115
        return ["blockdev", "--getro", dev]

    @staticmethod
    def vec_blockdev_getsize64(dev):  # install.sh:600
        return ["blockdev", "--getsize64", dev]

    @staticmethod
    def vec_findmnt_source():  # install.sh mounted-check, preflight.sh:141
        return ["findmnt", "-rn", "-o", "SOURCE"]

    @staticmethod
    def vec_findmnt_options(path):  # preflight.sh:188
        return ["findmnt", "-no", "OPTIONS", path]

    @staticmethod
    def vec_findmnt_fstype(path):  # preflight.sh:273, readback.sh:222
        return ["findmnt", "-no", "FSTYPE", "-T", path]

    @staticmethod
    def vec_lsblk(dev, columns=None):  # install.sh foreign-lsblk: -rn -o NAME,TYPE; readback.sh:192 plain
        if columns is None:
            return ["lsblk", dev]
        return ["lsblk", "-rn", "-o", columns, dev]

    @staticmethod
    def vec_lsblk_disks():  # readback.sh:181
        return ["lsblk", "-dn", "-o", "NAME"]

    @staticmethod
    def vec_sfdisk_dump(disk):  # install.sh:216, preflight.sh:127
        return ["sfdisk", "--dump", disk]

    @staticmethod
    def vec_blkid(dev):  # install.sh:638
        return ["blkid", "-p", "-s", "TYPE", "-o", "value", dev]

    @staticmethod
    def vec_efibootmgr_list():  # install.sh:487, preflight.sh:104, readback.sh:110
        return ["efibootmgr", "-v"]

    @staticmethod
    def vec_efibootmgr_help():  # install.sh:545, preflight.sh:161
        return ["efibootmgr", "--help"]

    @staticmethod
    def vec_sha256sum_check(manifest="MANIFEST.hashes"):  # preflight.sh:253 (run with cwd=stage dir)
        return ["sha256sum", "--strict", "-c", manifest]

    @staticmethod
    def vec_stat_size(path):  # install.sh:412
        return ["stat", "-c", "%s", path]

    @staticmethod
    def vec_od_bytes(path, fmt="u1", skip=None, count=None, endian=None, verbose=True):
        # preflight.sh:210 (-An -v -tu1 FILE); install.sh:434 (-An -tu4 --endian=little -j40 -N4 FILE)
        vec = ["od", "-An"]
        if verbose:
            vec.append("-v")
        vec.append(f"-t{fmt}")
        if endian:
            vec.append(f"--endian={endian}")
        if skip is not None:
            vec.append(f"-j{skip}")
        if count is not None:
            vec.append(f"-N{count}")
        vec.append(path)
        return vec

    @staticmethod
    def vec_df_free(path):  # preflight.sh:264
        return ["df", "-Pk", path]

    @staticmethod
    def vec_uname_r():  # preflight.sh
        return ["uname", "-r"]

    @staticmethod
    def vec_docker_ps():  # preflight.sh
        return ["docker", "ps", "-q"]

    @staticmethod
    def vec_dd_read(src, bs, count=None, skip=None, iflag=None, of=None):
        # install.sh:430 (if= of=FILE bs=2048 count=1), :439 (if= bs=1 skip=64 count=512),
        # :633 (if= bs=4M iflag=count_bytes count=N); every one ends with status=none
        vec = ["dd", f"if={src}"]
        if of is not None:
            vec.append(f"of={of}")
        vec.append(f"bs={bs}")
        if skip is not None:
            vec.append(f"skip={skip}")
        if iflag is not None:
            vec.append(f"iflag={iflag}")
        if count is not None:
            vec.append(f"count={count}")
        vec.append("status=none")
        return vec

    @staticmethod
    def vec_sfdisk_write(disk):  # install.sh:575 (layout on stdin)
        return ["sfdisk", disk]

    @staticmethod
    def vec_sfdisk_delete(disk, nums):  # install.sh:754
        return ["sfdisk", "--delete", disk, *[str(n) for n in nums]]

    @staticmethod
    def vec_wipefs(disk):  # install.sh:762
        return ["wipefs", "-a", disk]

    @staticmethod
    def vec_udevadm_settle():  # install.sh:577
        return ["udevadm", "settle"]

    @staticmethod
    def vec_dd_write(src, dst, bs="1M"):  # install.sh:611
        return ["dd", f"if={src}", f"of={dst}", f"bs={bs}", "conv=fsync", "status=none"]

    @staticmethod
    def vec_efibootmgr_create(disk, part, label, loader, opts):  # install.sh:657
        return ["efibootmgr", "-C", "-d", disk, "-p", str(part), "-L", label, "-l", loader, "-u", opts]

    @staticmethod
    def vec_efibootmgr_next(entry):  # install.sh:672
        return ["efibootmgr", "-n", str(entry)]

    @staticmethod
    def vec_efibootmgr_delete_next():  # install.sh:739, readback.sh:126
        return ["efibootmgr", "-N"]

    @staticmethod
    def vec_efibootmgr_delete(entry):  # install.sh:747, readback.sh:132
        if not _BOOT_ENTRY_RE.match(str(entry)):
            raise ValueError(f"boot entry must be four hex digits, got {entry!r}")
        return ["efibootmgr", "-B", "-b", str(entry)]

    @staticmethod
    def vec_mount(src, target, options="ro", fstype=None):  # readback.sh:226
        vec = ["mount", "-o", options]
        if fstype:
            vec += ["-t", fstype]
        return vec + [src, target]

    @staticmethod
    def vec_umount(target):  # readback.sh:199
        return ["umount", target]

    # --------------------------------------------------------- read verbs

    def blockdev_getsz(self, dev, **kw) -> int:
        return int(self._run(self.vec_blockdev_getsz(dev), **kw).text.strip())

    def blockdev_getro(self, dev, **kw) -> int:
        return int(self._run(self.vec_blockdev_getro(dev), **kw).text.strip())

    def blockdev_getsize64(self, dev, **kw) -> int:
        return int(self._run(self.vec_blockdev_getsize64(dev), **kw).text.strip())

    def findmnt_source(self, **kw) -> list:
        return self._run(self.vec_findmnt_source(), **kw).text.splitlines()

    def findmnt_options(self, path, check=False, **kw) -> OpResult:
        return self._run(self.vec_findmnt_options(path), check=check, **kw)

    def findmnt_fstype(self, path, check=False, **kw) -> OpResult:
        return self._run(self.vec_findmnt_fstype(path), check=check, **kw)

    def lsblk(self, dev, columns=None, check=False, **kw) -> OpResult:
        return self._run(self.vec_lsblk(dev, columns), check=check, **kw)

    def lsblk_disks(self, **kw) -> list:
        return self._run(self.vec_lsblk_disks(), **kw).text.split()

    def sfdisk_dump(self, disk, check=False, **kw) -> OpResult:
        return self._run(self.vec_sfdisk_dump(disk), check=check, **kw)

    def blkid(self, dev, check=False, **kw) -> OpResult:
        return self._run(self.vec_blkid(dev), check=check, **kw)

    def efibootmgr_list(self, **kw) -> str:
        return self._run(self.vec_efibootmgr_list(), **kw).text

    def efibootmgr_help(self, check=False, **kw) -> OpResult:
        return self._run(self.vec_efibootmgr_help(), check=check, **kw)

    def sha256sum_check(self, cwd, manifest="MANIFEST.hashes", check=False, **kw) -> OpResult:
        return self._run(self.vec_sha256sum_check(manifest), cwd=cwd, check=check, **kw)

    def stat_size(self, path, **kw) -> int:
        return int(self._run(self.vec_stat_size(path), **kw).text.strip())

    def od_bytes(self, path, fmt="u1", skip=None, count=None, endian=None, **kw) -> list:
        vec = self.vec_od_bytes(path, fmt, skip, count, endian)
        return [int(x) for x in self._run(vec, **kw).text.split()]

    def df_free(self, path, **kw) -> int:
        """Available space in KiB, from the last line of ``df -Pk``."""
        out = self._run(self.vec_df_free(path), **kw).text.strip().splitlines()
        return int(out[-1].split()[3])

    def uname_r(self, **kw) -> str:
        return self._run(self.vec_uname_r(), **kw).text.strip()

    def docker_ps(self, check=False, **kw) -> OpResult:
        return self._run(self.vec_docker_ps(), check=check, **kw)

    def dd_read(self, src, bs, count=None, skip=None, iflag=None, of=None, **kw) -> bytes:
        """Read via dd; bytes on stdout. ``of=`` writes a file, so it is a mutation."""
        if of is not None:
            self._gate("dd_read(of=)", True)
            if str(of).startswith("/dev/"):
                raise MutationRefused(f"dd_read must not write to a device ({of}); use dd_write")
        return self._run(self.vec_dd_read(src, bs, count, skip, iflag, of), **kw).stdout

    def dd_sha256(self, src, bs, count, iflag="count_bytes", **kw) -> str:
        """sha256 hex of ``dd`` output, hashed as it streams (kit install.sh:633)."""
        vec = self.vec_dd_read(src, bs, count=count, iflag=iflag)
        return self._run(vec, digest=True, **kw).digest

    def read_file(self, path) -> bytes:
        return self._fs("read_file", path)

    def realpath(self, path) -> str:
        """Canonical path with every symlink resolved; raises OSError when the path does not exist."""
        return self._fs("realpath", path)

    def listdir(self, path) -> list:
        """Entry names of a directory (sysfs ``slaves``), sorted; raises OSError when unreadable."""
        return self._fs("listdir", path)

    def run_read(self, vec, check=True, **kw) -> OpResult:
        """Run any other read tool; a vector that could mutate is refused."""
        vec = list(vec)
        if vector_mutates(vec):
            self._gate("run_read", True)  # ReadOnlyOps raises MutationRefused
            raise MutationRefused(f"run_read refuses a vector that may mutate: {' '.join(vec)}")
        return self._run(vec, check=check, **kw)

    # ----------------------------------------------------- mutating verbs

    def sfdisk_write(self, disk, layout: str, **kw) -> OpResult:
        self._gate("sfdisk_write", True)
        return self._run(self.vec_sfdisk_write(disk), stdin=layout.encode(), **kw)

    def sfdisk_delete(self, disk, nums, **kw) -> OpResult:
        self._gate("sfdisk_delete", True)
        return self._run(self.vec_sfdisk_delete(disk, nums), **kw)

    def wipefs(self, disk, **kw) -> OpResult:
        self._gate("wipefs", True)
        return self._run(self.vec_wipefs(disk), **kw)

    def udevadm_settle(self, **kw) -> OpResult:
        self._gate("udevadm_settle", True)
        return self._run(self.vec_udevadm_settle(), **kw)

    def dd_write(self, src, dst, bs="1M", timeout=DD_WRITE_TIMEOUT, **kw) -> OpResult:
        self._gate("dd_write", True)
        return self._run(self.vec_dd_write(src, dst, bs), timeout=timeout, **kw)

    def efibootmgr_create(self, disk, part, label, loader, opts, **kw) -> OpResult:
        self._gate("efibootmgr_create", True)
        return self._run(self.vec_efibootmgr_create(disk, part, label, loader, opts), **kw)

    def efibootmgr_next(self, entry, **kw) -> OpResult:
        self._gate("efibootmgr_next", True)
        return self._run(self.vec_efibootmgr_next(entry), **kw)

    def efibootmgr_delete_next(self, **kw) -> OpResult:
        self._gate("efibootmgr_delete_next", True)
        return self._run(self.vec_efibootmgr_delete_next(), **kw)

    def efibootmgr_delete(self, entry, **kw) -> OpResult:
        self._gate("efibootmgr_delete", True)
        return self._run(self.vec_efibootmgr_delete(entry), **kw)

    def mount(self, src, target, options="ro", fstype=None, **kw) -> OpResult:
        self._gate("mount", True)
        return self._run(self.vec_mount(src, target, options, fstype), **kw)

    def umount(self, target, **kw) -> OpResult:
        self._gate("umount", True)
        return self._run(self.vec_umount(target), **kw)

    def write_file(self, path, data: bytes) -> None:
        self._gate("write_file", True)
        self._fs("write_file", path, data)

    def efivar_write(self, path, data: bytes) -> None:
        self._gate("efivar_write", True)
        self._fs("efivar_write", path, data)

    def sysfs_write(self, path, value: str) -> None:
        self._gate("sysfs_write", True)
        self._fs("sysfs_write", path, value)


# ---------------------------------------------------------------- read-only


class ReadOnlyOps(Ops):
    """Exposes read verbs only; every mutating verb raises first."""

    def __init__(self, inner: Ops):
        self._inner = inner

    def _gate(self, verb, mutating):
        if mutating:
            raise MutationRefused(f"read-only ops refuse {verb}")

    def _exec(self, vec, **kw):
        # Defence in depth: a vector reaching here must itself be a read.
        if vector_mutates(vec):
            raise MutationRefused(f"read-only ops refuse {' '.join(vec)}")
        return self._inner._exec(vec, **kw)

    def _fs(self, kind, path, data=None):
        if kind not in FS_READ_KINDS:
            raise MutationRefused(f"read-only ops refuse {kind}")
        return self._inner._fs(kind, path, data)


# ---------------------------------------------------------------- recording


class RecordingOps(Ops):
    """Records calls and returns scripted results; never runs anything.

    ``script`` maps a recorded line (e.g. ``"blockdev --getsz /dev/x"``) to
    a result or a list used as a queue. A result is an ``OpResult``, str,
    bytes, int (an rc) or an exception instance (raised). Unscripted reads
    raise ``UnscriptedCall``; unscripted mutations succeed with rc 0.
    ``replacements`` is a list of (old, new) applied to recorded lines, to
    normalise temp directories as the golden log does.
    """

    def __init__(self, script=None, replacements=()):
        self.script = {k: (list(v) if isinstance(v, list) else v) for k, v in (script or {}).items()}
        self.replacements = list(replacements)
        self.calls: list = []
        self.written: dict = {}

    def _norm(self, text: str) -> str:
        for old, new in self.replacements:
            text = text.replace(old, new)
        return text

    @property
    def log(self) -> list:
        """Recorded lines in call order, in the kit's STUB_LOG format."""
        return [self._norm(c.line) for c in self.calls]

    def _scripted(self, line):
        if line not in self.script:
            return None
        val = self.script[line]
        if isinstance(val, list):
            if not val:
                raise UnscriptedCall(f"scripted queue exhausted for: {line}")
            val = val.pop(0)
        return val if val is not None else OpResult()

    @staticmethod
    def _coerce(val) -> OpResult:
        if isinstance(val, BaseException):
            raise val
        if isinstance(val, OpResult):
            return val
        if isinstance(val, str):
            return OpResult(stdout=val.encode())
        if isinstance(val, bytes):
            return OpResult(stdout=val)
        if isinstance(val, int):
            return OpResult(rc=val)
        raise TypeError(f"unsupported scripted result {val!r}")

    def _exec(self, vec, *, stdin=None, timeout=None, cwd=None, digest=False):
        call = Call(list(vec), stdin)
        self.calls.append(call)
        val = self._scripted(self._norm(call.line))
        if val is None:
            if vector_mutates(vec):
                return OpResult()
            raise UnscriptedCall(f"no scripted result for read: {self._norm(call.line)}")
        return self._coerce(val)

    def _fs(self, kind, path, data=None):
        if kind in FS_READ_KINDS:
            line = f"{kind} {path}"
            self.calls.append(Call([kind, path], kind="fs"))
            val = self._scripted(self._norm(line))
            if val is None:
                raise UnscriptedCall(f"no scripted result for read: {self._norm(line)}")
            res = self._coerce(val)
            if kind == "realpath":
                return res.text.strip()
            if kind == "listdir":
                return sorted(res.text.split())
            return res.stdout
        vec = [kind, path] + ([data] if kind == "sysfs_write" else [])
        self.calls.append(Call(vec, kind="fs"))
        self.written[path] = data


# --------------------------------------------------------------------- real


class RealOps(Ops):
    """Runs the tools. Each child gets its own session; output goes to files."""

    def __init__(self, tool_dir=None, default_timeout=DEFAULT_TIMEOUT, term_grace=TERM_GRACE):
        if tool_dir is None:
            dirs = list(DEFAULT_TOOL_DIRS)
        elif isinstance(tool_dir, (str, os.PathLike)):
            dirs = [os.fspath(tool_dir)]
        else:
            dirs = [os.fspath(d) for d in tool_dir]
        self.tool_dirs = dirs
        self.default_timeout = default_timeout
        self.term_grace = term_grace

    def resolve_tool(self, name):
        for d in self.tool_dirs:
            cand = os.path.join(d, name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        return None

    def _env(self):
        # Explicit tool dirs first, then the fixed system dirs (never the
        # inherited PATH) so wrapper scripts can find coreutils.
        dirs = self.tool_dirs + [d for d in DEFAULT_TOOL_DIRS if d not in self.tool_dirs]
        return {"PATH": os.pathsep.join(dirs), "LC_ALL": "C"}

    def _kill_group(self, child):
        """TERM then KILL the child's own group, only if it leads it."""
        try:
            pgid = os.getpgid(child.pid)
        except ProcessLookupError:
            return
        if pgid != child.pid:
            # Not the group leader we created: never signal a group.
            child.kill()
            child.wait()
            return
        for sig, wait in ((signal.SIGTERM, self.term_grace), (signal.SIGKILL, None)):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                break
            try:
                child.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
        child.wait()
        # SIGTERM may have ended the leader while members linger; sweep once.
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _exec(self, vec, *, stdin=None, timeout=None, cwd=None, digest=False):
        vec = list(vec)
        exe = self.resolve_tool(os.path.basename(vec[0]))
        if exe is None:
            raise OpFailed(vec, None, f"tool {vec[0]!r} not found in {self.tool_dirs}")
        timeout = self.default_timeout if timeout is None else timeout
        # devtool-debt: dd_sha256 read-back spools each full partition to a TemporaryFile in the default temp
        # directory before hashing, so a tmpfs /tmp smaller than the biggest image fails after the image was written.
        # Ceiling: images larger than free /tmp. Upgrade trigger: the first ENOSPC at read-back; hash the stream instead.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            inp = None
            try:
                if stdin is not None:
                    inp = tempfile.TemporaryFile()
                    inp.write(stdin)
                    inp.seek(0)
                try:
                    child = subprocess.Popen(
                        [exe, *vec[1:]],
                        stdin=inp if inp is not None else subprocess.DEVNULL,
                        stdout=out,
                        stderr=err,
                        cwd=cwd,
                        env=self._env(),
                        start_new_session=True,
                    )
                except OSError as exc:
                    raise OpFailed(vec, None, f"cannot start: {exc}") from exc
                timed_out = False
                try:
                    rc = child.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._kill_group(child)
                    rc = child.returncode
                except BaseException:
                    # An interrupt must not leave a writer alive in its own session.
                    self._kill_group(child)
                    raise
            finally:
                if inp is not None:
                    inp.close()
            err.seek(0)
            stderr = err.read().decode("utf-8", errors="replace")
            if timed_out:
                raise OpFailed(vec, None, f"timed out after {timeout}s; {stderr}")
            out.seek(0)
            if digest:
                h = hashlib.sha256()
                for chunk in iter(lambda: out.read(1 << 20), b""):
                    h.update(chunk)
                return OpResult(rc=rc, stderr=stderr, digest=h.hexdigest())
            return OpResult(rc=rc, stdout=out.read(), stderr=stderr)

    def _fs(self, kind, path, data=None):
        if kind == "read_file":
            with open(path, "rb") as f:
                return f.read()
        if kind == "realpath":
            return os.path.realpath(path, strict=True)
        if kind == "listdir":
            return sorted(os.listdir(path))
        if kind == "sysfs_write":
            with open(path, "w") as f:
                f.write(data)
            return None
        with open(path, "wb") as f:  # write_file, efivar_write
            f.write(data)
        return None


__all__ = [
    "FS_READ_KINDS", "Call", "MutationRefused", "OpFailed", "OpResult", "Ops", "OpsError", "ReadOnlyOps",
    "RealOps", "RecordingOps", "UnscriptedCall", "vector_mutates",
]  # fmt: skip

