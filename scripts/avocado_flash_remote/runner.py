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

import hashlib
import json
import os
import sys
import zipfile

from .cmd_check import run_check
from .cmd_plan import run_plan
from .cmd_readback import run_readback
from .cmd_restore import run_restore
from .cmd_status import run_status
from .cmd_write import run_write
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
    state_dir, mount_dir, out_dir, ref = _need(req, "state_dir", "mount_dir", "out_dir", "reference_boot_order")
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


def _run_guarded(sub, profile, phash, req):
    try:
        real = RealOps(req.get("tool_dir"))
        result = _HANDLERS[sub](real, profile, phash, req)
        sys.stdout.flush()
        return int(result.exit_code)
    except _Exit as e:
        if e.message:
            print(e.message, file=e.stream or sys.stderr)
        return e.code
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except Exception as e:  # noqa: BLE001 - last line of defence, reported plainly
        print(f"runner error: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_ERROR


# ------------------------------------------------------------------ detach


def _detach(run_dir, run_id):
    """Classic double fork. Returns True in the grandchild, False in the parent."""
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    log = os.path.join(run_dir, "runner.log")
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
        if detach:
            run_dir, run_id = _need(req, "run_dir", "run_id")
            if not _detach(run_dir, run_id):
                return 0
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
