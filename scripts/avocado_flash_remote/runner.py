"""Board-side entry point: dispatches one subcommand of the ssh-emmc runner.

The host ships this package inside a single zipapp (see ``bundle.py``) and
runs it with the board's ``python3``. Standard library only, and valid on
Python 3.10 as well as newer interpreters.

Usage::

    runner.pyz --version
    runner.pyz <check|plan|write|restore|readback|status> --request FILE [--detach]

``FILE`` is a JSON object the host staged next to the images. The runner
never reads stdin: sudo is fed its password by the host before it execs us.

Exit codes: the subcommand's own code; 3 profile/request mismatch; 64 usage;
70 unexpected runner error; 130 interrupted.
"""

import datetime
import hashlib
import json
import os
import stat
import sys
import zipfile

from .cmd_check import run_check
from .cmd_plan import run_plan
from .cmd_readback import run_readback
from .cmd_restore import run_restore
from .cmd_status import run_status
from .cmd_write import run_write
from . import evidence, state as runstate
from .ops import ReadOnlyOps, RealOps
from .profile import ProfileError, load_profile_bytes

RUNNER_VERSION = "1"

SUBCOMMANDS = ("check", "plan", "write", "restore", "readback", "status")

EXIT_PROFILE = 3
EXIT_USAGE = 64
EXIT_ERROR = 70
EXIT_INTERRUPTED = 130


class _Exit(Exception):
    def __init__(self, code, message=None, stream=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stream = stream


def _archive_path():
    # <archive>/avocado_flash_remote/runner.py -> <archive>
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_bundle(archive):
    """Return (profile_bytes, bundle_meta, bundle_json_sha256) from the archive."""
    try:
        with zipfile.ZipFile(archive) as z:
            raw = z.read("BUNDLE.json")
            profile = z.read("profile.json")
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        raise _Exit(EXIT_ERROR, f"runner error: cannot read bundle {archive}: {e}", sys.stderr)
    return profile, json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def _print_version(archive):
    print(f"avocado-flash-runner {RUNNER_VERSION}")
    try:
        _profile, _meta, digest = _read_bundle(archive)
    except _Exit:
        print("bundle sha256 unavailable")
    else:
        print(f"bundle sha256 {digest}")
    return 0


def _usage_error(message):
    return _Exit(EXIT_USAGE, f"{message}\nvalid subcommands: {', '.join(SUBCOMMANDS)}", sys.stderr)


def _parse_args(argv):
    """Return (subcommand, request_path, detach)."""
    if not argv:
        raise _usage_error("avocado-flash-runner: no subcommand")
    sub = argv[0]
    if sub not in SUBCOMMANDS:
        raise _usage_error(f"avocado-flash-runner: unknown subcommand {sub!r}")
    request = None
    detach = False
    rest = list(argv[1:])
    while rest:
        arg = rest.pop(0)
        if arg == "--request" and rest:
            request = rest.pop(0)
        elif arg == "--detach":
            detach = True
        else:
            raise _usage_error(f"avocado-flash-runner: unexpected argument {arg!r}")
    if request is None:
        raise _usage_error("avocado-flash-runner: --request FILE is required")
    if detach and sub != "write":
        raise _usage_error("avocado-flash-runner: --detach applies to write only")
    return sub, request, detach


def _load_request(path):
    try:
        with open(path, "rb") as f:
            req = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        raise _Exit(EXIT_USAGE, f"runner error: cannot read request {path}: {e}", sys.stderr)
    if not isinstance(req, dict):
        raise _Exit(EXIT_USAGE, f"runner error: request {path} is not a JSON object", sys.stderr)
    return req


def _need(req, *keys):
    missing = [k for k in keys if k not in req]
    if missing:
        raise _Exit(EXIT_USAGE, f"runner error: request lacks {', '.join(missing)}", sys.stderr)
    return [req[k] for k in keys]


# --------------------------------------------------------------- run dir

# Subcommands that write into run_dir. check and status stay free of side effects.
_RUN_DIR_SUBS = ("plan", "write", "restore", "readback")


def _prepare_run_dir(sub, profile, req):
    """Create run_dir (0700, parents included) under the profile's state_dir.

    Refuses a run_dir that is not under state_dir, or that is, or passes
    through, a symlink or a non-directory. Existing directories are reused
    untouched. Nothing is created outside state_dir.
    """
    if sub not in _RUN_DIR_SUBS or req.get("run_dir") is None:
        return
    run_dir = req["run_dir"]

    def refuse(why):
        return _Exit(EXIT_USAGE, f"runner error: run_dir {run_dir!r} refused: {why}", sys.stderr)

    if not isinstance(run_dir, str) or not os.path.isabs(run_dir):
        raise refuse("not an absolute path")
    state_dir = os.path.normpath(profile.state_dir)
    target = os.path.normpath(run_dir)
    if os.path.commonpath([state_dir, target]) != state_dir:
        raise refuse(f"not under state_dir {state_dir!r}")
    parts = [] if target == state_dir else os.path.relpath(target, state_dir).split(os.sep)
    # Validate every existing component before creating anything.
    chain = [state_dir]
    for part in parts:
        chain.append(os.path.join(chain[-1], part))
    for i, path in enumerate(chain):
        if i and os.path.islink(path):
            raise refuse(f"{path!r} is a symlink")
        if os.path.lexists(path) and not os.path.isdir(path):
            raise refuse(f"{path!r} exists and is not a directory")
    for path in chain:
        if os.path.lexists(path):
            continue
        try:
            os.mkdir(path, 0o700)
            os.chmod(path, 0o700)  # independent of umask
        except OSError as e:
            raise _Exit(EXIT_ERROR, f"runner error: cannot create {path}: {e}", sys.stderr)


# ---------------------------------------------------------------- dispatch


def _do_check(real, profile, phash, req):
    (staging,) = _need(req, "staging_dir")
    kw = {"staging_dir": staging}
    if req.get("efivars_dir") is not None:
        kw["efivars_dir"] = req["efivars_dir"]
    kw["expected_boot_order"] = req.get("expected_boot_order")
    return run_check(ReadOnlyOps(real), profile, **kw)


def _do_plan(real, profile, phash, req):
    staging, run_dir, run_id = _need(req, "staging_dir", "run_dir", "run_id")
    kw = {"staging_dir": staging, "run_dir": run_dir, "run_id": run_id}
    if req.get("board_identity") is not None:
        kw["board_identity"] = req["board_identity"]
    return run_plan(ReadOnlyOps(real), profile, phash, **kw)


def _do_write(real, profile, phash, req):
    staging, state_dir, run_dir = _need(req, "staging_dir", "state_dir", "run_dir")
    plan_path = req.get("plan_path") or os.path.join(run_dir, "plan.json")
    confirmed = req.get("confirmed_device")

    def plan_loader():
        with open(plan_path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))

    def confirm(_device):
        return confirmed

    kw = {
        "staging_dir": staging,
        "state_dir": state_dir,
        "run_dir": run_dir,
        "plan_loader": plan_loader,
        "confirm": confirm,
        "assume_yes": bool(req.get("assume_yes", False)),
        "expected_boot_order": req.get("expected_boot_order"),
        "ack_run_id": req.get("ack_run_id"),
    }
    if req.get("efivars_dir") is not None:
        kw["efivars_dir"] = req["efivars_dir"]
    return run_write(real, profile, phash, **kw)


def _do_restore(real, profile, phash, req):
    state_dir, staging = _need(req, "state_dir", "staging_dir")
    return run_restore(
        real,
        profile,
        state_dir=state_dir,
        staging_dir=staging,
        ack_run_id=req.get("ack_run_id"),
        emergency_disarm=bool(req.get("emergency_disarm", False)),
    )


def _do_readback(real, profile, phash, req):
    state_dir, mount_dir, out_dir = _need(req, "state_dir", "mount_dir", "out_dir")
    if profile.arm.strategy != "none":
        (ref,) = _need(req, "reference_boot_order")
    else:
        ref = req.get("reference_boot_order")
    kw = {"state_dir": state_dir, "mount_dir": mount_dir, "out_dir": out_dir, "reference_boot_order": ref}
    for key in ("data_partition_name", "fstype"):
        if req.get(key) is not None:
            kw[key] = req[key]
    return run_readback(real, profile, **kw)


def _do_status(real, profile, phash, req):
    (state_dir,) = _need(req, "state_dir")
    return run_status(state_dir)


_HANDLERS = {
    "check": _do_check,
    "plan": _do_plan,
    "write": _do_write,
    "restore": _do_restore,
    "readback": _do_readback,
    "status": _do_status,
}


def _read_json(path):
    try:
        with open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _finished_manifest(run_dir):
    """True when run_dir already holds a complete or host-verified record set."""
    manifest = _read_json(os.path.join(run_dir, evidence.MANIFEST))
    if not manifest or manifest.get("run_status") not in ("runner-complete", "host-verified"):
        return False
    return evidence.verify_record_set(run_dir).ok


def _finalize_records(sub, profile, phash, req, rc, refused_early=False):
    """Write MANIFEST.json (atomically, last) over the files present in run_dir.

    Rebuilt from scratch on every call so a re-run never lists a file that is
    gone. check and status write nothing. A write refused before it did any
    work leaves an already complete or verified manifest as it is: marking a
    finished run incomplete because a replay was turned away would destroy its
    evidence. Never raises: a missing manifest is reported by the host as not
    verified, which is the honest outcome.
    """
    run_dir = req.get("run_dir")
    if sub not in _RUN_DIR_SUBS or not isinstance(run_dir, str) or not os.path.isdir(run_dir):
        return
    if refused_early and _finished_manifest(run_dir):
        return
    try:
        plan = _read_json(os.path.join(run_dir, "plan.json")) or {}
        st = {}
        loaded = runstate.load_state(profile.state_dir)
        if loaded.status == "ok" and req.get("run_id") in (None, loaded.state.run_id):
            st = loaded.state.data
        identity = plan.get("board_identity") or st.get("board_identity")
        hashes = plan.get("image_hashes")
        if not isinstance(hashes, dict):
            hashes = {
                r: i["expected_sha256"]
                for r, i in (st.get("images") or {}).items()
                if isinstance(i, dict) and i.get("expected_sha256")
            }
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rs = evidence.RecordSet(
            run_dir=run_dir,
            host_tool_version=str(req.get("tool_version") or "unknown"),
            runner_version=RUNNER_VERSION,
            profile_hash=phash,
            image_hashes=hashes,
            board_identity=identity,
            transition_log=list(st.get("phases_done") or []),
            host_utc=str(req.get("host_utc") or now),
            board_utc=now,
        )
        for name in sorted(os.listdir(run_dir)):
            path = os.path.join(run_dir, name)
            if name == evidence.MANIFEST or name.endswith(".tmp"):
                continue
            if not stat.S_ISREG(os.lstat(path).st_mode):
                continue
            with open(path, "rb") as f:
                data = f.read()
            rs.artifacts.append(
                {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            )
        rs.finalize("runner-complete" if rc == 0 else "incomplete")
    except Exception as e:  # noqa: BLE001 - evidence is best-effort, rc stays the subcommand's
        print(f"runner error: cannot write {evidence.MANIFEST}: {type(e).__name__}: {e}", file=sys.stderr)


def _run_guarded(sub, profile, phash, req):
    rc, refused_early = _run_sub(sub, profile, phash, req)
    _finalize_records(sub, profile, phash, req, rc, refused_early)
    return rc


def _run_sub(sub, profile, phash, req):
    """Return (exit code, refused_early); refused_early is only ever true for a write
    that returned without creating any run state (it did no work)."""
    try:
        real = RealOps(req.get("tool_dir"))
        result = _HANDLERS[sub](real, profile, phash, req)
        sys.stdout.flush()
        rc = int(result.exit_code)
        return rc, sub == "write" and rc != 0 and getattr(result, "final_phase", "unset") is None
    except _Exit as e:
        if e.message:
            print(e.message, file=e.stream or sys.stderr)
        return e.code, False
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED, False
    except Exception as e:  # noqa: BLE001 - last line of defence, reported plainly
        print(f"runner error: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_ERROR, False


# ------------------------------------------------------------------ detach

ACCEPTED_MARKER = "accepted"


def _write_accepted(run_dir):
    """Record that the detached runner took the request, before any real work.

    The host reads this to tell a runner that is still hashing (no state.json
    yet) from one that never started. Written atomically; advisory, so a
    failure is logged and does not stop the write.
    """
    final = os.path.join(run_dir, ACCEPTED_MARKER)
    tmp = final + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)
    except OSError as e:
        print(f"runner error: cannot write {ACCEPTED_MARKER} marker: {e}", file=sys.stderr)


def _already_written(run_dir):
    """A run_dir that holds write.json belongs to a write that already finished."""
    return os.path.isfile(os.path.join(run_dir, "write.json"))


def _detach(run_dir, run_id, replay=False):
    """Classic double fork. Returns True in the grandchild, False in the parent.

    ``replay`` sends the log outside run_dir: appending to the log of a write
    that already finished would invalidate that run's manifest.
    """
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    log = os.path.join(run_dir, "runner.log")
    if replay:
        log = os.path.join(os.path.dirname(os.path.normpath(run_dir)), f"refused-{os.getpid()}.log")
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid:
        os.waitpid(pid, 0)
        print(f"detached: run={run_id} log={log}")
        sys.stdout.flush()
        return False
    try:
        os.setsid()
        if os.fork():
            os._exit(0)
        devnull = os.open(os.devnull, os.O_RDONLY)
        logfd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.dup2(devnull, 0)
        os.dup2(logfd, 1)
        os.dup2(logfd, 2)
        for fd in (devnull, logfd):
            if fd > 2:
                os.close(fd)
    except BaseException:
        os._exit(EXIT_ERROR)
    return True


# -------------------------------------------------------------------- main


def main(argv, *, archive=None):
    archive = os.fspath(archive) if archive is not None else _archive_path()
    try:
        if list(argv) == ["--version"]:
            return _print_version(archive)
        sub, request_path, detach = _parse_args(list(argv))
        req = _load_request(request_path)
        profile_bytes, meta, _digest = _read_bundle(archive)
        phash = hashlib.sha256(profile_bytes).hexdigest()
        wanted = {meta.get("profile_sha256"), req.get("profile_hash")} - {None}
        if wanted != {phash}:
            raise _Exit(
                EXIT_PROFILE,
                f"runner error: profile hash mismatch: bundled {phash}, "
                f"BUNDLE.json {meta.get('profile_sha256')}, request {req.get('profile_hash')}",
                sys.stderr,
            )
        try:
            profile = load_profile_bytes(profile_bytes)
        except ProfileError as e:
            raise _Exit(EXIT_PROFILE, f"runner error: bundled profile invalid: {e}", sys.stderr)
        _prepare_run_dir(sub, profile, req)
        if detach:
            run_dir, run_id = _need(req, "run_dir", "run_id")
            replay = _already_written(run_dir)
            if not _detach(run_dir, run_id, replay=replay):
                return 0
            if not replay:
                _write_accepted(run_dir)
            rc = _run_guarded(sub, profile, phash, req)
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(rc)
        return _run_guarded(sub, profile, phash, req)
    except _Exit as e:
        if e.message:
            print(e.message, file=e.stream or sys.stderr)
        return e.code
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except Exception as e:  # noqa: BLE001
        print(f"runner error: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_ERROR
