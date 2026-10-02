"""Host-side transport for the ssh-emmc backend.

Runs on the operator's machine. Standard library only, Python 3.10 compatible.

Everything that talks to the board goes through a ``Transport``. The real
one (``SshTransport``) builds one ``ssh -- HOST 'remote command'`` invocation
per call; ``StubTransport`` records calls for tests so no ssh is ever started
by the default suite.

ssh authentication: ``BatchMode=no`` is the default so the operator can type
an ssh password through their own agent/askpass. Pass ``batch_mode=True`` for
key-only setups where a prompt must fail instead of hang.

sudo: ``acquire_sudo`` first tries ``sudo -n``. Only if that fails does it
ask for the password locally, and the password then travels solely as the
first line of the standard input of each privileged ssh invocation
(``sudo -S -p ''``). It is never placed in an argument list, the environment,
a log, an exception message, a record or any ``repr()``.
"""

from __future__ import annotations

import getpass
import hashlib
import io
import json
import math
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import evidence
from .bundle import verify_bundle
from .images import scan

SUBCOMMANDS = ("check", "plan", "write", "restore", "readback", "status")

_HOST_RE = re.compile(
    r"^(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9_][A-Za-z0-9_.-]*\Z"
)
_NAME_RE = re.compile(r"^[A-Za-z0-9_+][A-Za-z0-9._+-]*\Z")
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*\Z")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}\Z")

_PYTHON_RE = re.compile(r"^[A-Za-z0-9_./+-]+\Z")
DEFAULT_PYTHON = "python3"

DEFAULT_TIMEOUT = 600
TAR_TIMEOUT = 3600
_KILL_GRACE = 5


class HostError(Exception):
    """A host-side failure. Messages never contain credentials."""


class HostTimeout(HostError):
    pass


class Secret:
    """Holds a credential; every textual form is redacted."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<Secret hidden>"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("Secret cannot be serialised")

    def __setattr__(self, name, value):
        raise AttributeError("Secret is immutable")


@dataclass
class RunResult:
    rc: int
    stdout: bytes = b""
    stderr: bytes = b""

    @property
    def out(self) -> str:
        return self.stdout.decode("utf-8", "replace")

    @property
    def err(self) -> str:
        return self.stderr.decode("utf-8", "replace")


def _check_host(host: str) -> str:
    if not isinstance(host, str) or not _HOST_RE.match(host):
        raise HostError(f"invalid ssh host: {host!r}")
    return host


def validate_remote_python(path) -> str:
    """The interpreter path is spliced into a remote command line; keep it plain."""
    if (
        not isinstance(path, str)
        or not _PYTHON_RE.match(path)
        or path.startswith("-")
        or ".." in path.split("/")
    ):
        raise HostError(f"invalid --remote-python: {path!r}")
    return path


class _TransportBase:
    """Shared sudo wrapping so the stub exercises the same bytes as ssh."""

    sudo_password: Optional[Secret] = None
    # Decided only from the remote ``id -u`` answer (see acquire_sudo); the one
    # place _wrap consults, so no call site can bypass the mode.
    root_direct: bool = False

    def set_root_direct(self, value: bool) -> None:
        self.root_direct = bool(value)

    def set_password(self, secret: Optional[Secret]) -> None:
        self.sudo_password = secret

    def _wrap(self, argv_remote, stdin, sudo: bool):
        argv = list(argv_remote)
        if not sudo or self.root_direct:
            return argv, stdin
        if self.sudo_password is None:
            return ["sudo", "-n"] + argv, stdin
        if callable(stdin):
            raise HostError("a streamed payload cannot be combined with a sudo password")
        if isinstance(stdin, Path):
            stdin = stdin.read_bytes()
        body = stdin or b""
        prefix = self.sudo_password.reveal().encode("utf-8") + b"\n"
        return ["sudo", "-S", "-p", ""] + argv, prefix + body


def _terminate(proc) -> None:
    """TERM then KILL the child's own process group, only if it leads one."""
    try:
        if os.getpgid(proc.pid) != proc.pid:
            proc.kill()
            return
    except OSError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            return
        try:
            proc.wait(timeout=_KILL_GRACE)
            return
        except subprocess.TimeoutExpired:
            continue


def _tar_writer(files: dict, modes: dict) -> Callable[[Any], None]:
    def write(fileobj) -> None:
        with tarfile.open(fileobj=fileobj, mode="w|") as tf:
            for name, src in files.items():
                ti = tarfile.TarInfo(name)
                ti.mode = modes.get(name, 0o644)
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                ti.mtime = 0
                if isinstance(src, (bytes, bytearray)):
                    ti.size = len(src)
                    tf.addfile(ti, io.BytesIO(bytes(src)))
                else:
                    with open(src, "rb") as fh:
                        ti.size = os.fstat(fh.fileno()).st_size
                        tf.addfile(ti, fh)

    return write


class SshTransport(_TransportBase):
    def __init__(self, host: str, ssh_bin: str = "ssh", extra_opts=None, batch_mode: bool = False):
        self.host = _check_host(host)
        self.ssh_bin = ssh_bin
        self.extra_opts = list(extra_opts or [])
        self.batch_mode = batch_mode

    def command_line(self, remote_argv) -> list:
        mode = "yes" if self.batch_mode else "no"
        return [
            self.ssh_bin,
            "-o",
            f"BatchMode={mode}",
            *self.extra_opts,
            "--",
            self.host,
            shlex.join(list(remote_argv)),
        ]

    def run(self, argv_remote, stdin=None, *, sudo: bool = False, timeout: float = DEFAULT_TIMEOUT) -> RunResult:
        remote, payload = self._wrap(argv_remote, stdin, sudo)
        return self._spawn(self.command_line(remote), payload, timeout)

    def put_tar(self, files: dict, dest_dir: str, modes: Optional[dict] = None, *, timeout: float = TAR_TIMEOUT) -> RunResult:
        writer = _tar_writer(files, dict(modes or {}))
        return self.run(["tar", "-C", dest_dir, "-xf", "-"], writer, sudo=False, timeout=timeout)

    def _spawn(self, cmd, payload, timeout) -> RunResult:
        with tempfile.TemporaryDirectory(prefix="afr-ssh-") as tmp:
            out_path = Path(tmp) / "out"
            err_path = Path(tmp) / "err"
            opened = []
            try:
                outf = open(out_path, "wb")
                opened.append(outf)
                errf = open(err_path, "wb")
                opened.append(errf)
                if payload is None:
                    stdin_arg = subprocess.DEVNULL
                elif isinstance(payload, Path):
                    stdin_arg = open(payload, "rb")
                    opened.append(stdin_arg)
                else:
                    stdin_arg = subprocess.PIPE
                proc = subprocess.Popen(
                    cmd,
                    stdin=stdin_arg,
                    stdout=outf,
                    stderr=errf,
                    start_new_session=True,
                )
                writer = None
                if stdin_arg is subprocess.PIPE:
                    writer = threading.Thread(target=self._feed, args=(proc, payload), daemon=True)
                    writer.start()
                try:
                    rc = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _terminate(proc)
                    raise HostTimeout(f"ssh to {self.host} timed out after {timeout}s") from None
                except BaseException:
                    # An interrupted wait must not leave the ssh child (and the remote command) running.
                    _terminate(proc)
                    raise
                if writer is not None:
                    writer.join(timeout=_KILL_GRACE)
            finally:
                for fh in opened:
                    try:
                        fh.close()
                    except OSError:
                        pass
            return RunResult(rc, out_path.read_bytes(), err_path.read_bytes())

    @staticmethod
    def _feed(proc, payload) -> None:
        try:
            if callable(payload):
                payload(proc.stdin)
            else:
                proc.stdin.write(payload)
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass


@dataclass
class Call:
    kind: str  # 'run' | 'put_tar'
    argv: list
    sudo: bool = False
    stdin_len: Optional[int] = None
    # Held for password-hygiene assertions; excluded from repr on purpose.
    stdin_bytes: Optional[bytes] = field(default=None, repr=False)
    env: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    modes: dict = field(default_factory=dict)
    dest_dir: Optional[str] = None


class StubTransport(_TransportBase):
    """Records every call and returns scripted results. Never connects."""

    def __init__(self, handler: Optional[Callable[[list, Any, bool], RunResult]] = None):
        self.handler = handler
        self.calls: list = []

    def _answer(self, argv, stdin, sudo) -> RunResult:
        if self.handler is None:
            return RunResult(0)
        return self.handler(argv, stdin, sudo)

    def run(self, argv_remote, stdin=None, *, sudo: bool = False, timeout: float = DEFAULT_TIMEOUT) -> RunResult:
        remote, payload = self._wrap(argv_remote, stdin, sudo)
        raw = payload if isinstance(payload, (bytes, bytearray)) else None
        self.calls.append(
            Call("run", remote, sudo, len(raw) if raw is not None else None, bytes(raw) if raw is not None else None)
        )
        return self._answer(remote, payload, sudo)

    def put_tar(self, files: dict, dest_dir: str, modes: Optional[dict] = None, *, timeout: float = TAR_TIMEOUT) -> RunResult:
        argv = ["tar", "-C", dest_dir, "-xf", "-"]
        self.calls.append(Call("put_tar", argv, False, files=dict(files), modes=dict(modes or {}), dest_dir=dest_dir))
        return self._answer(argv, None, False)


# --- sudo -----------------------------------------------------------------


def sudo_probe(transport) -> bool:
    """True when non-interactive sudo works on the board."""
    return transport.run(["sudo", "-n", "true"], None, sudo=False, timeout=60).rc == 0


def default_ask_password() -> str:
    if not sys.stdin.isatty():
        raise HostError("sudo needs a password but there is no terminal to ask on; configure sudo -n access or run from a terminal")
    return getpass.getpass("sudo password on the board: ")


PRIVILEGE_ROOT = "root (no sudo)"
PRIVILEGE_SUDO_NOPASS = "sudo (password not needed)"
PRIVILEGE_SUDO_PASSWORD = "sudo (password supplied)"


def remote_is_root(transport) -> bool:
    """True only when the board itself says the login uid is 0.

    Rule: a call that fails or prints nothing is "cannot tell" and is treated
    as not root (the sudo path follows, which is never less safe). Output that
    is present but is not a plain decimal uid is malformed and refuses, so a
    garbled answer is never guessed into root.
    """
    res = transport.run(["id", "-u"], None, sudo=False, timeout=60)
    text = res.out.strip()
    if res.rc != 0 or not text:
        return False
    if not re.fullmatch(r"[0-9]+", text):
        raise HostError("cannot determine the privilege mode: unexpected output from 'id -u' on the board")
    return int(text) == 0


def acquire_sudo(transport, ask_password: Callable[[], str] = default_ask_password) -> str:
    """Make privileged calls work and return the privilege mode.

    Root login: privileged commands run as given, no sudo, no prompt. Otherwise
    sudo -n if possible, else a prompted password.
    """
    # SSH transport sudo password setter, not a Django account password; never stored.
    # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password
    transport.set_password(None)
    transport.set_root_direct(False)
    if remote_is_root(transport):
        transport.set_root_direct(True)
        return PRIVILEGE_ROOT
    if sudo_probe(transport):
        return PRIVILEGE_SUDO_NOPASS
    password = ask_password()
    if not password:
        raise HostError("empty sudo password")
    # SSH transport sudo password setter, not a Django account password; never stored.
    # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password
    transport.set_password(Secret(password))
    res = transport.run(["true"], None, sudo=True, timeout=60)
    if res.rc != 0:
        # SSH transport sudo password setter, not a Django account password; never stored.
        # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password
        transport.set_password(None)
        raise HostError("sudo authentication failed on the board")
    return PRIVILEGE_SUDO_PASSWORD


# --- remote interpreter -----------------------------------------------------

# The probe uses only ``sys`` and ``__import__`` (present in every Python) so a
# stripped interpreter can still say what it lacks. The module tuple is
# computed by the bundle builder, never taken from user input.
def _probe_code(modules) -> str:
    return (
        "import sys\n"
        "def _ok(n):\n"
        "    try:\n"
        "        __import__(n)\n"
        "    except Exception:\n"
        "        return False\n"
        "    return True\n"
        f"m = [n for n in {tuple(modules)!r} if not _ok(n)]\n"
        "print('MISSING ' + ' '.join(m) if m else 'OK ' + sys.version.split()[0])\n"
    )


def probe_interpreter(transport, python: str, modules) -> str:
    """Return the board interpreter's version, or refuse naming what is missing."""
    python = validate_remote_python(python)
    hint = f"install a full python3 on the board or name one with --remote-python (interpreter: {python})"
    res = transport.run([python, "-c", _probe_code(modules)], None, sudo=False, timeout=60)
    if res.rc == 127:
        raise HostError(f"interpreter not found on the board: {python}; {hint}")
    lines = res.out.strip().splitlines()
    last = lines[-1].strip() if lines else ""
    if res.rc != 0:
        raise HostError(f"the interpreter {python} failed on the board (rc={res.rc}); {hint}")
    if last.startswith("OK ") and len(last.split()) == 2:
        return last.split()[1]
    if last.startswith("MISSING "):
        names = " ".join(last.split()[1:])
        raise HostError(f"the board's python lacks standard-library modules the runner needs: {names}; {hint}")
    raise HostError(f"unexpected output from the interpreter probe on the board; {hint}")


# --- board tools ------------------------------------------------------------

# Runs with plain sh before the runner exists. Each tool must start under ``--version`` and not announce
# BusyBox; the loop prints what it cannot confirm. Read-only: it names no path and no write verb.
_TOOL_PROBE = (
    'm=""; for t in install sha256sum dd; do '
    'o=$("$t" --version 2>&1) && case "$o" in *[Bb]usy[Bb]ox*) false;; esac || m="$m $t"; done; '
    '[ -z "$m" ] && echo OK || echo "MISSING$m"'
)
_PROBE_TOOLS = ("install", "sha256sum", "dd")


def probe_board_tools(transport) -> None:
    """Refuse a board whose install, sha256sum or dd is missing or not GNU, naming what is wrong."""
    res = transport.run(["sh", "-c", _TOOL_PROBE], None, sudo=False, timeout=60)
    last = (res.out.strip().splitlines() or [""])[-1].strip()
    if res.rc == 0 and last == "OK":
        return
    parts = last.split()
    if res.rc == 0 and parts[:1] == ["MISSING"] and parts[1:] and set(parts[1:]) <= set(_PROBE_TOOLS):
        raise HostError(
            f"the board lacks GNU {', '.join(parts[1:])}: this tool needs GNU coreutils "
            "(install -d, sha256sum --strict, dd conv=fsync), not a busybox userland"
        )
    raise HostError("could not confirm GNU install, sha256sum and dd on the board; this tool needs GNU coreutils")


# --- staging --------------------------------------------------------------


@dataclass
class StageResult:
    staging_dir: str
    bundle_remote_path: str
    profile_remote_path: str


def _parse_manifest(images_dir: Path) -> list:
    """Return [(name, expected_sha256)] named in MANIFEST.hashes."""
    manifest = images_dir / "MANIFEST.hashes"
    try:
        text = manifest.read_text()
    except OSError as exc:
        raise HostError(f"cannot read {manifest}: {exc}") from None
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([0-9a-fA-F]{64})[ ]([ *])(.+)$", line)
        if not m:
            raise HostError(f"unparseable line in MANIFEST.hashes: {line[:80]!r}")
        name = m.group(3)
        if not _NAME_RE.match(name):
            raise HostError(f"unsafe file name in MANIFEST.hashes: {name!r}")
        if not (images_dir / name).is_file():
            raise HostError(f"listed in MANIFEST.hashes but missing: {name}")
        entries.append((name, m.group(1).lower()))
    if not entries:
        raise HostError("MANIFEST.hashes names no images")
    return entries


def _plan_files(image_dir, bundle_path, resolved):
    image_dir = Path(image_dir)
    bundle_path = Path(bundle_path)
    rows = []  # (name, path_or_bytes, size, sha)
    for name, expected in _parse_manifest(image_dir):
        res = scan(image_dir / name)
        if res.sha256 != expected:
            raise HostError(f"{name}: sha256 differs from MANIFEST.hashes")
        rows.append((name, image_dir / name, res.size, res.sha256))
    mh = image_dir / "MANIFEST.hashes"
    rows.append(("MANIFEST.hashes", mh, mh.stat().st_size, hashlib.sha256(mh.read_bytes()).hexdigest()))
    rows.append(("profile.json", bytes(resolved.data), len(resolved.data), resolved.sha256))
    problems = verify_bundle(bundle_path)
    if problems:
        raise HostError("bundle failed verification: " + "; ".join(problems[:3]))
    br = scan(bundle_path)
    rows.append((bundle_path.name, bundle_path, br.size, br.sha256))
    return rows


_DF_SCRIPT = 'd="$1"; while [ ! -d "$d" ]; do d=$(dirname "$d"); done; LC_ALL=C df -Pk "$d"'


def check_staging_space(transport, profile, payload_bytes: int = 0) -> int:
    """Refuse unless the staging filesystem has room. Returns free KiB."""
    res = transport.run(["sh", "-c", _DF_SCRIPT, "sh", profile.staging.dir], None, sudo=False, timeout=60)
    if res.rc != 0:
        raise HostError("cannot read free space on the board (df failed)")
    lines = [ln for ln in res.out.splitlines() if ln.strip()]
    try:
        fields = lines[-1].split()
        if len(lines) < 2 or len(fields) < 6:
            raise ValueError("short df output")
        int(fields[1])
        int(fields[2])
        avail = int(fields[3])
    except (IndexError, ValueError):
        raise HostError("cannot parse df output from the board; refusing to stage") from None
    need = profile.staging.min_free_kib + math.ceil(payload_bytes / 1024)
    if avail < need:
        raise HostError(
            f"insufficient staging space on the board: {avail} KiB free, "
            f"{need} KiB needed ({profile.staging.min_free_kib} reserve + images)"
        )
    return avail


def stage(transport, profile, resolved, image_dir, bundle_path, dry_run: bool = False, out=print, python: str = DEFAULT_PYTHON) -> StageResult:
    staging_dir = profile.staging.dir
    rows = _plan_files(image_dir, bundle_path, resolved)
    result = StageResult(
        staging_dir,
        f"{staging_dir}/{Path(bundle_path).name}",
        f"{staging_dir}/profile.json",
    )
    if dry_run:
        out("stage dry run: no connection is made")
        out(f"destination: {staging_dir}")
        for name, _src, size, sha in rows:
            out(f"  {name}  {size}  {sha}")
        out("nothing was copied")
        return result

    resolved.recheck()
    total = sum(r[2] for r in rows)
    probe_board_tools(transport)
    check_staging_space(transport, profile, total)

    who = transport.run(["id", "-un"], None, sudo=False, timeout=60)
    user = who.out.strip()
    if who.rc != 0 or not _USER_RE.match(user):
        raise HostError("cannot determine the remote user")
    mk = transport.run(["install", "-d", "-o", user, "-m", "0755", staging_dir], None, sudo=True, timeout=60)
    if mk.rc != 0:
        raise HostError("cannot create the staging directory on the board")

    files = {name: src for name, src, _s, _h in rows}
    bundle_name = Path(bundle_path).name
    modes = {name: (0o755 if name == bundle_name else 0o644) for name in files}
    put = transport.put_tar(files, staging_dir, modes)
    if put.rc != 0:
        raise HostError(f"copy to the board failed (rc={put.rc})")

    check = transport.run(
        ["sh", "-c", 'cd "$1" && sha256sum --strict -c MANIFEST.hashes', "sh", staging_dir],
        None, sudo=False, timeout=TAR_TIMEOUT,
    )
    if check.rc != 0:
        raise HostError("remote hash verification of the images failed")
    unzip = "import sys, zipfile; sys.exit(1 if zipfile.ZipFile(sys.argv[1]).testzip() else 0)"
    zcheck = transport.run([python, "-c", unzip, result.bundle_remote_path], None, sudo=False, timeout=120)
    if zcheck.rc != 0:
        raise HostError(f"the board's interpreter {python} cannot open the staged bundle (rc={zcheck.rc})")
    sums = {n: h for n, _s, _z, h in rows if n in (bundle_name, "profile.json")}
    listing = "".join(f"{h}  {n}\n" for n, h in sorted(sums.items())).encode()
    check = transport.run(
        ["sh", "-c", 'cd "$1" && sha256sum --strict -c -', "sh", staging_dir],
        listing, sudo=False, timeout=120,
    )
    if check.rc != 0:
        raise HostError("remote hash verification of the bundle or profile failed")
    return result


# --- run, reconcile, collect ----------------------------------------------


def run_remote(transport, subcommand: str, request: dict, bundle_remote_path: str, *, detach: bool = False, timeout: float = DEFAULT_TIMEOUT, python: str = DEFAULT_PYTHON) -> RunResult:
    if subcommand not in SUBCOMMANDS:
        raise HostError(f"unknown subcommand: {subcommand!r}")
    staging = request.get("staging_dir")
    if not isinstance(staging, str) or not staging.startswith("/"):
        raise HostError("request needs an absolute staging_dir")
    # The invocation's own tag names its request and its temp file: two workstations (or two
    # invocations) never share a path, so neither can overwrite or truncate the other's request
    # before its runner reads it, and each removes only the file it wrote.
    tag = request.get("invocation_nonce")
    if not isinstance(tag, str) or not re.fullmatch(r"[0-9a-f]{16,64}", tag):
        tag = secrets.token_hex(8)
    req_path = f"{staging}/request-{subcommand}-{tag}.json"
    body = json.dumps(request, sort_keys=True).encode("utf-8")
    put = transport.run(
        ["sh", "-c", 'cat > "$1.tmp" && mv "$1.tmp" "$1"', "sh", req_path],
        body, sudo=False, timeout=60,
    )
    if put.rc != 0:
        _remove_request(transport, req_path, req_path + ".tmp")  # the put may have died mid-write
        raise HostError("cannot write the request file on the board")
    argv = [validate_remote_python(python), bundle_remote_path, subcommand, "--request", req_path]
    if detach or subcommand == "write":
        argv.append("--detach")
    try:
        return transport.run(argv, None, sudo=True, timeout=timeout)
    finally:
        # The runner reads its request before it forks, so the file is spent once the call returns.
        # A dropped connection skips nothing here: the removal is a separate, best-effort call.
        _remove_request(transport, req_path)


def _remove_request(transport, *paths: str) -> None:
    try:
        transport.run(["rm", "-f", "--", *paths], None, sudo=False, timeout=60)
    except HostError:
        pass


@dataclass
class Reconciled:
    ok: bool
    phase: Optional[str] = None
    run_id: Optional[str] = None
    recovery: Optional[str] = None
    raw: str = ""


_STATUS_RE = re.compile(r"^status: (\S+) run=(\S+) recovery=(.*)$")


def reconcile(transport, state_dir: str, bundle_remote_path: str, staging_dir: str, python: str = DEFAULT_PYTHON, run_id: Optional[str] = None) -> Reconciled:
    """Ask the board's runner for its recorded phase (used after a drop).

    With ``run_id`` the answer is that run's own record, not whichever run ``current`` names: another
    run's create_run can move ``current`` after this host's run completed.
    """
    request = {"staging_dir": staging_dir, "state_dir": state_dir}
    if run_id is not None:
        request["run_id"] = run_id
    res = run_remote(transport, "status", request, bundle_remote_path, timeout=120, python=python)
    text = res.out.strip()
    if res.rc != 0:
        return Reconciled(False, raw=text)
    for line in text.splitlines():
        m = _STATUS_RE.match(line.strip())
        if m:
            return Reconciled(True, m.group(1), m.group(2), m.group(3).strip(), text)
    if "no run recorded" in text:
        return Reconciled(True, raw=text)
    return Reconciled(False, raw=text)


ACCEPTED_MARKER = "accepted"
OUTCOME_MARKER = "outcome"

_ALIVE_PROBE = 'if test -d "/proc/$1"; then echo alive; else echo gone; fi'
# Exit 3 is this probe's own "the marker is not there": the verdict rides on the exit code,
# never on the wording of a localised error message.
_ABSENT_RC = 3
_MARKER_READ = 'test -e "$1" || exit 3; exec cat -- "$1"'


def _read_marker(transport, remote_run_dir: str, name: str):
    """(state, text): state is 'ok', 'absent' or 'unknown'. Only the probe's own exit code means absent."""
    res = transport.run(["sh", "-c", _MARKER_READ, "sh", f"{remote_run_dir}/{name}"], None, sudo=True, timeout=60)
    if res.rc == _ABSENT_RC:
        return "absent", ""
    if res.rc != 0:
        return "unknown", ""
    return "ok", res.out


def _accepted_parts(text: str):
    """(pid, nonce) from an ``accepted`` marker; either is None when absent or malformed."""
    lines = text.split("\n")
    pid = lines[0].strip()
    nonce = lines[1][len("nonce="):] if len(lines) > 1 and lines[1].startswith("nonce=") else ""
    return (pid if pid.isdigit() else None), (nonce or None)


def runner_presence(transport, remote_run_dir: str) -> str:
    """Has a detached runner taken this run: 'alive', 'exited', 'absent' or 'unknown'.

    The runner writes ``accepted`` (its pid) into run_dir before any pre-check
    or hashing, so the marker exists long before state.json does. 'absent' and
    'exited' are firm answers and come only from a clean not-found and a clean
    "no such process" respectively. Anything else the host cannot read (a
    dropped ssh, a sudo failure, an unexpected answer) is 'unknown', which
    callers must treat as possibly started and possibly alive.
    """
    try:
        state, text = _read_marker(transport, remote_run_dir, ACCEPTED_MARKER)
        if state == "absent":
            return "absent"
        if state != "ok":
            return "unknown"
        pid, _nonce = _accepted_parts(text)
        if pid is None:
            return "unknown"
        alive = transport.run(["sh", "-c", _ALIVE_PROBE, "sh", pid], None, sudo=True, timeout=60)
    except HostError:
        return "unknown"
    if alive.rc != 0:
        return "unknown"
    word = alive.out.strip()
    if word == "alive":
        return "alive"
    if word == "gone":
        return "exited"
    return "unknown"


def runner_outcome(transport, remote_run_dir: str, run_id: str, nonce: str) -> tuple:
    """What the runner recorded when it ended: (kind, text).

    kind is 'refused' (text is the board's refusal, verbatim), 'finished',
    'none' (no marker: the runner has not ended, or died before recording) or
    'unknown' (unreadable, unrecognised, or written for another run id or by
    another invocation). Only a marker naming both this run id and this
    invocation's nonce is honoured; only 'none' is a firm absence.
    """
    try:
        state, text = _read_marker(transport, remote_run_dir, OUTCOME_MARKER)
    except HostError:
        return ("unknown", "")
    if state == "absent":
        return ("none", "")
    if state != "ok":
        return ("unknown", "")
    lines = text.split("\n")
    if len(lines) < 3 or lines[1] != f"run={run_id}" or not nonce or lines[2] != f"nonce={nonce}":
        return ("unknown", "")
    if lines[0] == "finished":
        return ("finished", "")
    if lines[0] == "refused":
        return ("refused", "\n".join(lines[3:]).strip("\n"))
    return ("unknown", "")


def invocation_owner(transport, remote_run_dir: str, run_id: str, nonce: str) -> str:
    """Whose runner holds this run's records: 'ours', 'other', 'none' or 'unknown'.

    'ours' needs the ``accepted`` marker to carry this invocation's nonce and
    the outcome to be absent or finished, never refused or unreadable. A run another invocation (or an earlier
    attempt) wrote, or that this invocation never started, is 'other' or 'none';
    anything unreadable is 'unknown'. Only 'ours' may be reported as this
    invocation's own completed write.
    """
    try:
        state, text = _read_marker(transport, remote_run_dir, ACCEPTED_MARKER)
        if state == "absent":
            return "none"
        if state != "ok":
            return "unknown"
        _pid, found = _accepted_parts(text)
        if found is None or not nonce:
            return "unknown"
        if found != nonce:
            return "other"
        kind, _ = runner_outcome(transport, remote_run_dir, run_id, nonce)
    except HostError:
        return "unknown"
    if kind == "refused":
        return "other"
    # 'none' is expected: the phase turns complete a moment before the runner writes its verdict.
    return "ours" if kind in ("none", "finished") else "unknown"


def final_outcome(phase: Optional[str], verify: evidence.VerifyResult) -> str:
    """'complete' only when the board says so AND the records verify."""
    return evidence.final_status(phase or "", verify)


# devtool-debt: collect holds every collected record in memory (the whole tar). Ceiling: a run whose
# records total more than a few tens of MiB. Upgrade trigger: readback logs copied by default, or a
# larger record set; stream the tar to disk instead.
def collect(transport, run_id: str, local_run_dir, *, remote_run_dir: str) -> evidence.VerifyResult:
    """Fetch the on-board record directory and verify it. Raises on a bad stream."""
    if not _NAME_RE.match(run_id or ""):
        raise HostError("invalid run id")
    dest = Path(local_run_dir)
    if dest.exists() and any(dest.iterdir()):
        raise HostError(f"{dest} is not empty")
    res = transport.run(["tar", "-C", remote_run_dir, "-cf", "-", "."], None, sudo=True, timeout=TAR_TIMEOUT)
    if res.rc != 0:
        raise HostError(f"collecting records failed (rc={res.rc})")
    members = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(res.stdout), mode="r:") as tf:
            for m in tf:
                name = m.name[2:] if m.name.startswith("./") else m.name
                if m.isdir() and name in ("", "."):
                    continue
                if not m.isreg() or not name or "/" in name or name in (".", ".."):
                    raise HostError(f"unsafe member in record stream: {m.name!r}")
                fh = tf.extractfile(m)
                data = fh.read()
                if len(data) != m.size:
                    raise HostError("record stream truncated")
                members[name] = data
    except (tarfile.TarError, EOFError) as exc:
        raise HostError(f"record stream unreadable: {type(exc).__name__}") from None
    dest.mkdir(parents=True, exist_ok=True)
    for name, data in members.items():
        evidence.write_record(dest, name, data)
    return evidence.verify_record_set(dest)
