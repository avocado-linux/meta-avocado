"""Entry point for the ssh-emmc medium of avocado-flash.

Runs on the operator's machine. Standard library only, Python 3.10 compatible.

``main(argv)`` receives everything after the ``ssh-emmc`` word. Every board
operation goes through ``host.run_remote`` into the staged runner bundle; this
module only parses arguments, enforces the lifecycle gates (plan record
required, retyped device confirmation, one writer per host), collects and
verifies the on-board records and maps outcomes to exit codes.

Exit codes: 0 ok; 1 refusal or failure; 2 not examined (check) or the
connection to the board dropped (ssh 255 is never passed through); 3 profile
mismatch; 64 usage; 70 unexpected error; 130 interrupted.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, List, Optional

from . import evidence, host
from .bundle import BundleError, build_bundle, required_stdlib
from .profile import ProfileError, write_identity_problem
from .profile_resolve import (
    InvalidBoard,
    ProfileChanged,
    UnknownBoard,
    UnsafeProfilePath,
    describe,
    resolve_profile,
)
from .state import TERMINAL, HostLock, LockHeld

SUBCOMMANDS = ("stage", "check", "plan", "write", "readback", "restore", "status")
PREFIX = "avocado-flash ssh-emmc"
TOOL_VERSION = "avocado-flash-ssh-emmc"
BUNDLE_NAME = "runner.pyz"
DEFAULT_WAIT_SECONDS = 7200
SSH_FAILURE = 255
EXIT_DROPPED = 2
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_+][A-Za-z0-9._+-]*\Z")

HELP = f"""\
usage: avocado-flash ssh-emmc <subcommand> --board NAME --images DIR --host HOST [options]

subcommands:
  stage     copy the verified images and the runner bundle to the board
            (--dry-run lists what would be copied and makes no connection)
  check     read-only preflight on the board
  plan      record what a write would do; creates the run id and plan record
  write     write the planned run (needs --run-id of a collected plan)
  readback  read back what the test image left behind (needs --reference-boot-order unless the board's arm strategy is none)
  restore   undo a run (--ack-run RUN_ID, or --emergency-disarm)
  status    print the board's recorded phase

gates:
  write refuses without a collected, verified plan record for --run-id
  write asks you to retype the target device and refuses on any mismatch
  write and restore take a per-host lock and refuse while another holds it
  a run is COMPLETE only when the board says so and the collected records verify

options:
  --board NAME             board profile name (required)
  --images DIR             image directory with MANIFEST.hashes (stage)
  --host HOST              [user@]host, never starting with '-' (required except stage --dry-run)
  --extension-dir DIR      board-support extension profile directory
  --evidence-dir DIR       where per-run records are collected (default ./ssh-emmc-evidence)
  --dry-run                stage only: make no connection
  --assume-yes             let the runner skip its own interactive prompt
  --ack-run RUN_ID         acknowledge a run (write, restore)
  --emergency-disarm       restore: disarm without a run acknowledgement
  --expected-boot-order V  check, write
  --reference-boot-order V readback
  --run-id RUN_ID          write, restore, readback, status: which run
  --ssh-opt=OPT            extra ssh option, repeatable (use the = form: --ssh-opt=-p2222)
  --batch                  ssh BatchMode=yes
  --remote-python PATH     interpreter on the board (default python3); probed before any runner call
  --wait-seconds N         write: how long to follow the run (default {DEFAULT_WAIT_SECONDS})

exit codes: 0 ok, 1 refusal or failure, 2 not examined or connection dropped,
3 profile mismatch, 64 usage, 70 unexpected error, 130 interrupted
"""


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D401 - argparse hook
        raise _Usage(message)


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog=PREFIX, add_help=False)
    p.add_argument("subcommand")
    p.add_argument("--board", required=True)
    p.add_argument("--images")
    p.add_argument("--host")
    p.add_argument("--extension-dir")
    p.add_argument("--evidence-dir", default="./ssh-emmc-evidence")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--assume-yes", action="store_true")
    p.add_argument("--ack-run")
    p.add_argument("--emergency-disarm", action="store_true")
    p.add_argument("--expected-boot-order")
    p.add_argument("--reference-boot-order")
    p.add_argument("--run-id")
    p.add_argument("--ssh-opt", action="append", default=[])
    p.add_argument("--batch", action="store_true")
    p.add_argument("--remote-python", default=host.DEFAULT_PYTHON)
    p.add_argument("--wait-seconds", type=int, default=DEFAULT_WAIT_SECONDS)
    return p


def _err(text: str) -> None:
    print(text, file=sys.stderr)


class _Ctx:
    def __init__(self, args, resolved, out, factory, ask_password, confirm, sleep, poll_interval):
        self.args = args
        self.resolved = resolved
        self.profile = resolved.profile
        self.out = out
        self.factory = factory
        self.ask_password = ask_password
        self.confirm = confirm
        self.sleep = sleep
        self.poll_interval = poll_interval
        self.transport = None
        self.evidence_dir = Path(args.evidence_dir)
        staging = self.profile.staging.dir
        self.staging_dir = staging
        self.state_dir = self.profile.state_dir
        self.bundle_remote = f"{staging}/{BUNDLE_NAME}"
        self.remote_python = args.remote_python

    # -- board access ------------------------------------------------------
    def connect(self, need_staged: bool) -> Optional[int]:
        """Open the transport. Returns an exit code to stop with, else None."""
        self.transport = self.factory(self.args.host, list(self.args.ssh_opt), self.args.batch)
        if need_staged:
            probe = self.transport.run(["test", "-f", self.bundle_remote], None, sudo=False, timeout=60)
            if probe.rc != 0:
                _err(f"{PREFIX}: the runner bundle is not on the board: run stage first")
                return 1
        mode = host.acquire_sudo(self.transport, self.ask_password or host.default_ask_password)
        self.out(f"privilege: {mode}")
        try:
            version = host.probe_interpreter(self.transport, self.remote_python, required_stdlib())
        except host.HostError as exc:
            _err(f"{PREFIX}: {exc}")
            return 1
        self.out(f"remote python: {self.remote_python} {version}")
        return None

    def invoke(self, sub: str, request: dict, detach: bool = False):
        request = dict(request)
        request["profile_hash"] = self.resolved.sha256
        if "run_dir" in request:
            # Evidence provenance: the tool that asked, and the host clock read just before the call, so the
            # record set computes skew from two real observations.
            request["tool_version"] = TOOL_VERSION
            request["host_utc"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = host.run_remote(self.transport, sub, request, self.bundle_remote, detach=detach, python=self.remote_python)
        if res.out.strip():
            self.out(res.out.rstrip("\n"))
        if res.err.strip():
            _err(res.err.rstrip("\n"))
        return res

    def collect(self, run_id: str, remote_run_dir: str, local_dir: Path) -> evidence.VerifyResult:
        try:
            return host.collect(self.transport, run_id, local_dir, remote_run_dir=remote_run_dir)
        except host.HostError as exc:
            return evidence.VerifyResult(False, [str(exc)])

    def remote_run_dir(self, run_id: str) -> str:
        return f"{self.state_dir}/{run_id}/records"

    def lock(self, run_id: str) -> HostLock:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.args.host)
        return HostLock(self.evidence_dir / f".lock-{safe}", self.args.host, run_id)


# --- subcommands -----------------------------------------------------------


def _do_stage(ctx: _Ctx) -> int:
    args = ctx.args
    if not args.images:
        raise _Usage("stage needs --images DIR")
    with tempfile.TemporaryDirectory(prefix="afr-bundle-") as tmp:
        info = build_bundle(ctx.resolved.data, Path(tmp) / BUNDLE_NAME, TOOL_VERSION)
        if args.dry_run:
            host.stage(None, ctx.profile, ctx.resolved, args.images, info.path, dry_run=True, out=ctx.out)
            return 0
        rc = ctx.connect(need_staged=False)
        if rc is not None:
            return rc
        result = host.stage(ctx.transport, ctx.profile, ctx.resolved, args.images, info.path, out=ctx.out, python=ctx.remote_python)
    ctx.out(f"staged to {result.staging_dir}")
    return 0


def _dropped(sub: str, exc: Exception) -> int:
    """A runner call whose ssh wait expired: the runner may have acted before the host gave up."""
    _err(f"{PREFIX}: {exc}")
    _err(
        f"{PREFIX}: the connection to the board timed out during {sub}; the runner may have acted "
        "before the timeout: run the status subcommand to see the recorded phase"
    )
    return EXIT_DROPPED


def _exit_code(sub: str, rc: int) -> int:
    """Map a runner call's exit status; ssh's 255 (transport failure) becomes 2."""
    if rc != SSH_FAILURE:
        return rc
    _err(
        f"{PREFIX}: the connection to the board dropped during {sub}; the runner may have acted "
        "before the drop: run the status subcommand to see the recorded phase"
    )
    return EXIT_DROPPED


def _do_simple(ctx: _Ctx, sub: str, request: dict) -> int:
    rc = ctx.connect(need_staged=True)
    if rc is not None:
        return rc
    try:
        res = ctx.invoke(sub, request)
    except host.HostTimeout as exc:
        return _dropped(sub, exc)
    return _exit_code(sub, res.rc)


def _do_check(ctx: _Ctx) -> int:
    return _do_simple(
        ctx,
        "check",
        {"staging_dir": ctx.staging_dir, "expected_boot_order": ctx.args.expected_boot_order},
    )


def _do_status(ctx: _Ctx) -> int:
    request = {"staging_dir": ctx.staging_dir, "state_dir": ctx.state_dir}
    if ctx.args.run_id:
        # That run's own record, whichever run `current` names now.
        request["run_id"] = _need_run_id(ctx)
    return _do_simple(ctx, "status", request)


def _do_plan(ctx: _Ctx) -> int:
    local = evidence.new_run_dir(ctx.evidence_dir)
    run_id = local.name
    rc = ctx.connect(need_staged=True)
    if rc is not None:
        _rmdir(local)
        return rc
    remote_dir = ctx.remote_run_dir(run_id)
    try:
        res = ctx.invoke(
            "plan",
            {"staging_dir": ctx.staging_dir, "run_dir": remote_dir, "run_id": run_id},
        )
    except host.HostTimeout as exc:
        # The plan dir stays: the runner may have written records into it.
        return _dropped("plan", exc)
    if res.rc != 0:
        _rmdir(local)
        return res.rc
    ctx.out(f"plan run id: {run_id}")
    return _verify_or_fail(ctx, ctx.collect(run_id, remote_dir, local), local)


def _rmdir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _verify_or_fail(ctx: _Ctx, result: evidence.VerifyResult, local: Path) -> int:
    if result.ok:
        ctx.out(f"records collected and verified: {local}")
        return 0
    _err(f"{PREFIX}: records not verified: " + "; ".join(result.problems[:5]))
    return 1


def _need_run_id(ctx: _Ctx) -> str:
    run_id = ctx.args.run_id
    if not run_id:
        raise _Usage("write needs --run-id of an existing plan")
    if not _RUN_ID_RE.match(run_id):
        raise _Usage(f"invalid run id: {run_id!r}")
    return run_id


def _unique_dir(base: Path) -> Path:
    cand, n = base, 1
    while cand.exists() and any(cand.iterdir()):
        n += 1
        cand = base.with_name(f"{base.name}-{n}")
    return cand


def _do_write(ctx: _Ctx) -> int:
    args = ctx.args
    run_id = _need_run_id(ctx)
    plan_dir = ctx.evidence_dir / run_id
    if not (plan_dir / "plan.json").is_file():
        _err(f"{PREFIX}: no plan record for run {run_id}: run plan first")
        return 1
    plan_check = evidence.verify_record_set(plan_dir)
    if not plan_check.ok:
        _err(f"{PREFIX}: plan record for run {run_id} failed verification: " + "; ".join(plan_check.problems[:3]))
        return 1

    problem = write_identity_problem(ctx.profile)
    if problem:
        _err(f"{PREFIX}: write refused: {problem}; nothing was written to the board")
        return 1

    device = ctx.profile.target.device
    ctx.out(f"target device: {device}")
    for role, image in sorted(ctx.profile.images.items()):
        ctx.out(f"  image {role}: {image.file} -> partition {image.partition}")
    ask = ctx.confirm or input
    typed = ask(f"This erases and rewrites {device} on {args.host}. Retype the device to continue: ")
    if str(typed).strip() != device:
        _err(f"{PREFIX}: confirmation does not match {device}: refusing; nothing was written to the board")
        return 1

    with ctx.lock(run_id):
        rc = ctx.connect(need_staged=True)
        if rc is not None:
            return rc
        remote_dir = ctx.remote_run_dir(run_id)
        # One tag per invocation: the board's markers carry it, so this host never mistakes another
        # invocation's verdict or finished run for its own.
        nonce = secrets.token_hex(8)
        request = {
            "staging_dir": ctx.staging_dir,
            "state_dir": ctx.state_dir,
            "run_dir": remote_dir,
            "plan_path": f"{remote_dir}/plan.json",
            "run_id": run_id,
            "confirmed_device": str(typed).strip(),
            "assume_yes": bool(args.assume_yes),
            "expected_boot_order": args.expected_boot_order,
            "ack_run_id": args.ack_run,
            "invocation_nonce": nonce,
        }
        try:
            res = ctx.invoke("write", request, detach=True)
        except host.HostTimeout as exc:
            # The request may have been sent and the runner forked before the
            # timeout: never assume nothing happened.
            _err(f"{PREFIX}: {exc}")
            ctx.out("connection lost after the write request was sent; reconciling with the board")
            return _follow_write(ctx, run_id, remote_dir, nonce)
        if res.rc == SSH_FAILURE:
            ctx.out("connection dropped after the write request was sent; reconciling with the board")
            return _follow_write(ctx, run_id, remote_dir, nonce)
        if res.rc != 0:
            return res.rc
        return _follow_write(ctx, run_id, remote_dir, nonce)


def _tail_log(ctx: _Ctx, remote_dir: str) -> None:
    try:
        res = ctx.transport.run(["tail", "-n", "40", f"{remote_dir}/runner.log"], None, sudo=True, timeout=60)
    except host.HostError:
        return
    if res.rc == 0 and res.out.strip():
        ctx.out("runner log (tail):")
        ctx.out(res.out.rstrip("\n"))


def _judge_runner(ctx: _Ctx, run_id: str, remote_dir: str, nonce: str) -> tuple:
    """What the board says about the detached runner: (verdict, refusal text).

    verdict is 'refused' (the runner recorded a refusal for THIS run), 'finished',
    'alive', 'exited', 'absent' or 'unknown'. The runner's own outcome marker is
    read before the pid is judged, and anything the host could not read is
    'unknown': a dropped ssh or a sudo failure never becomes a firm verdict.
    """
    kind, text = host.runner_outcome(ctx.transport, remote_dir, run_id, nonce)
    if kind in ("refused", "finished"):
        return kind, text
    if kind == "unknown":
        return "unknown", ""
    return host.runner_presence(ctx.transport, remote_dir), ""


def _reconcile_phase(ctx: _Ctx, run_id: str):
    """(reconciled record or None, this run's phase or None)."""
    try:
        rec = host.reconcile(ctx.transport, ctx.state_dir, ctx.bundle_remote, ctx.staging_dir, python=ctx.remote_python, run_id=run_id)
    except host.HostError as exc:
        ctx.out(f"connection problem, will retry: {exc}")
        return None, None
    if rec.ok and rec.run_id == run_id:
        return rec, rec.phase
    return rec, None


OWNER_PROBE_TRIES = 6
COLLECT_RETRIES = 4


def _confirm_owner(ctx: _Ctx, run_id: str, remote_dir: str, nonce: str, polls: int) -> str:
    """Whose runner holds the run's records. One dropped ssh must not read as "not ours".

    'unknown' is retried, up to the polls --wait-seconds allows (at most OWNER_PROBE_TRIES), and only
    firm answers ('ours', 'other', 'none') end it early.
    """
    tries = max(1, min(polls, OWNER_PROBE_TRIES))
    owner = "unknown"
    for attempt in range(tries):
        owner = host.invocation_owner(ctx.transport, remote_dir, run_id, nonce)
        if owner != "unknown":
            break
        if attempt + 1 < tries:
            ctx.sleep(ctx.poll_interval)
    return owner


_VERDICT_WORDS = {"exited": "gone", "absent": "not present", "finished": "gone"}


def _unreadable_text(run_id: str, runner: str) -> str:
    return (
        f"the board's state record for run {run_id} is unreadable and {runner}; the board may have been "
        f"changed and this is not a finished write. Run the status subcommand with --run-id {run_id} and read "
        "the runner log before anything else"
    )


def _in_marker_window(ctx: _Ctx, verify, remote_dir: str, run_id: str, nonce: str) -> bool:
    """True when a failed verification may only be the runner's last two writes landing apart.

    The runner publishes its outcome marker and then the manifest that lists it. A collect before the
    marker sees no outcome; a collect between the two sees the marker present but unlisted, or a
    manifest that is not there yet. Any other problem (a changed or missing artifact) is not waited out.
    """
    if host.runner_outcome(ctx.transport, remote_dir, run_id, nonce)[0] == "none":
        return True
    return any(p == "unlisted file: outcome" or p.startswith("manifest unreadable") for p in verify.problems)


WRITE_ARTIFACTS = ("plan.json", "write.json")


def _collect_write(ctx: _Ctx, run_id: str, remote_dir: str, local: Path) -> evidence.VerifyResult:
    """Collect a write's records; a set that verifies but is not a finished write's does not count.

    verify_record_set only proves the files agree with their manifest, so a set that lacks write.json or
    that the runner never marked runner-complete would otherwise read as a completed write.
    """
    verify = ctx.collect(run_id, remote_dir, local)
    if not verify.ok:
        return verify
    try:
        manifest = json.loads((local / evidence.MANIFEST).read_bytes())
        listed = {a.get("name") for a in manifest["artifacts"]}
        status = manifest.get("run_status")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return evidence.VerifyResult(False, [f"manifest unreadable after verification: {exc}"])
    problems = [f"verified record set does not list {n}" for n in WRITE_ARTIFACTS if n not in listed]
    if status != "runner-complete":
        problems.append(f"manifest run_status is {status!r}, not 'runner-complete'")
    return evidence.VerifyResult(not problems, problems)


def _follow_write(ctx: _Ctx, run_id: str, remote_dir: str, nonce: str) -> int:
    polls = max(1, math.ceil(ctx.args.wait_seconds / max(ctx.poll_interval, 0.001)))
    phase = None
    unstarted = 0
    last_phase = None
    noted_unknown = False
    unreadable = 0  # consecutive polls where the board said this run's record cannot be read
    for _ in range(polls):
        rec, phase = _reconcile_phase(ctx, run_id)
        if rec is not None and rec.ok:
            unstarted = unstarted + 1 if phase is None else 0
            unreadable = 0
        elif rec is not None and "state unreadable" in rec.raw:
            unreadable += 1
            if unreadable >= 2:
                verdict, _reason = _judge_runner(ctx, run_id, remote_dir, nonce)
                if verdict not in ("alive", "unknown"):
                    ctx.out(_unreadable_text(run_id, f"the runner is {_VERDICT_WORDS.get(verdict, verdict)}"))
                    _tail_log(ctx, remote_dir)
                    return 1
        if phase in TERMINAL:
            break
        if phase is None and rec is not None and rec.ok:
            # No state for this run yet: a refusal before the lock leaves exactly this picture,
            # and the board's own words for it beat any guess from a pid.
            verdict, reason = _judge_runner(ctx, run_id, remote_dir, nonce)
            if verdict == "refused":
                ctx.out("the board refused the write and changed nothing:")
                ctx.out(reason)
                return 1
        elif phase is not None and phase == last_phase:
            # A non-terminal phase that did not move: a runner that ended normally is always
            # terminal, so an exited runner here died (or stopped on a handled failure) mid-run.
            verdict, _reason = _judge_runner(ctx, run_id, remote_dir, nonce)
            if verdict in ("exited", "finished"):
                # The run may have finished between the poll and the probe: ask once more.
                rec, now = _reconcile_phase(ctx, run_id)
                if now in TERMINAL:
                    phase = now
                    break
                if now is not None and now == phase:
                    ctx.out(
                        f"the runner exited while the board is still recorded in the non-terminal phase {phase}; "
                        "it will not advance"
                    )
                    ctx.out(f"recovery: {rec.recovery}")
                    _tail_log(ctx, remote_dir)
                    return 1
                phase = now if now is not None else phase
            elif verdict == "unknown" and not noted_unknown:
                noted_unknown = True
                ctx.out("cannot read the runner's state from the board; still following (this is not a failure)")
        last_phase = phase
        if unstarted >= 3:
            verdict, reason = _judge_runner(ctx, run_id, remote_dir, nonce)
            if verdict == "refused":
                ctx.out("the board refused the write and changed nothing:")
                ctx.out(reason)
                return 1
            if verdict in ("alive", "unknown"):
                # Accepted and still hashing or checking, or unreadable: keep waiting.
                unstarted = 0
            elif verdict in ("exited", "finished"):
                # Ended while the board shows no state for this run: look once more before judging.
                rec, now = _reconcile_phase(ctx, run_id)
                if now is not None:
                    unstarted = 0
                    phase = now
                    if now in TERMINAL:
                        break
                else:
                    ctx.out(
                        "the runner accepted the write and exited without recording state; the board may have "
                        f"been changed: run the status subcommand with --run-id {run_id} and read the runner log before anything else"
                    )
                    _tail_log(ctx, remote_dir)
                    return 1
            else:
                ctx.out(
                    "the board has no marker, no state and no runner process for this run: the write did not "
                    f"start. Run the status subcommand with --run-id {run_id} before assuming nothing happened"
                )
                _tail_log(ctx, remote_dir)
                return 1
        ctx.sleep(ctx.poll_interval)
    else:
        if unreadable >= 2:
            ctx.out(_unreadable_text(run_id, "the runner is still running"))
            return 1
        ctx.out(
            f"write still in progress after {ctx.args.wait_seconds}s; follow it with the status subcommand "
            f"with --run-id {run_id}"
        )
        return 1

    local = _unique_dir(ctx.evidence_dir / f"{run_id}-write")
    verify = _collect_write(ctx, run_id, remote_dir, local)
    outcome = host.final_outcome(phase, verify)
    # The phase turns complete a moment before the runner writes its manifest and outcome marker: a
    # collection in that window is retried while the runner has not recorded its own end.
    for _ in range(COLLECT_RETRIES):
        if outcome != "not-verified" or not _in_marker_window(ctx, verify, remote_dir, run_id, nonce):
            break
        ctx.sleep(ctx.poll_interval)
        local = _unique_dir(ctx.evidence_dir / f"{run_id}-write")
        verify = _collect_write(ctx, run_id, remote_dir, local)
        outcome = host.final_outcome(phase, verify)
    if outcome == "complete":
        owner = _confirm_owner(ctx, run_id, remote_dir, nonce, polls)
        if owner != "ours":
            # A terminal phase on the board is the run's, not necessarily this invocation's: a replay
            # that was turned away and then followed after a dropped connection lands here.
            if owner == "unknown":
                who = (
                    f"could not confirm which invocation wrote it (the board's markers stayed unreadable); "
                    "not reporting COMPLETE"
                )
            else:
                who = (
                    "this invocation did not write it (another invocation's runner holds the run's records, "
                    "or this invocation's runner never recorded itself); not reporting COMPLETE"
                )
            ctx.out(
                f"the board records run {run_id} in phase {phase}; {who}. Records collected in {local}. "
                f"Run the status subcommand with --run-id {run_id} and read the runner log before anything else"
            )
            _tail_log(ctx, remote_dir)
            return 1
        ctx.out(f"write COMPLETE (run {run_id}); records verified: {local}")
        return 0
    if outcome == "not-verified":
        _err(f"{PREFIX}: records not verified: " + "; ".join(verify.problems[:5]))
    else:
        ctx.out(f"write NOT COMPLETE: the board ended in phase {phase}")
        _tail_log(ctx, remote_dir)
    return 1


def _do_restore(ctx: _Ctx) -> int:
    args = ctx.args
    with ctx.lock(args.run_id or ""):
        rc = ctx.connect(need_staged=True)
        if rc is not None:
            return rc
        request = {
            "staging_dir": ctx.staging_dir,
            "state_dir": ctx.state_dir,
            "ack_run_id": args.ack_run,
            "emergency_disarm": bool(args.emergency_disarm),
        }
        if args.run_id:
            request["run_id"] = _need_run_id(ctx)
        try:
            res = ctx.invoke("restore", request)
        except host.HostTimeout as exc:
            return _dropped("restore", exc)
        return _exit_code("restore", res.rc)


# The runner refuses a readback whose output is not on tmpfs; /run is tmpfs on every target and the state
# directory is not, so the logs and the mount point live here and vanish at reboot.
READBACK_RUN_BASE = "/run/avocado-flash"


def _do_readback(ctx: _Ctx) -> int:
    args = ctx.args
    arm_none = ctx.profile.arm.strategy == "none"
    if not arm_none and not args.reference_boot_order:
        raise _Usage("readback needs --reference-boot-order")
    run_id = _need_run_id(ctx) if args.run_id else f"readback-{secrets.token_hex(4)}"
    request = {
        "staging_dir": ctx.staging_dir,
        "state_dir": ctx.state_dir,
        "mount_dir": f"{READBACK_RUN_BASE}/readback-mnt",
        "out_dir": f"{READBACK_RUN_BASE}/{run_id}/readback",
    }
    if arm_none:
        if args.reference_boot_order:
            ctx.out("--reference-boot-order ignored (arm strategy none)")
    else:
        request["reference_boot_order"] = args.reference_boot_order
    return _do_simple(ctx, "readback", request)


_HANDLERS = {
    "stage": _do_stage,
    "check": _do_check,
    "plan": _do_plan,
    "write": _do_write,
    "readback": _do_readback,
    "restore": _do_restore,
    "status": _do_status,
}


def _valid_subcommands() -> str:
    return f"valid subcommands: {', '.join(SUBCOMMANDS)}"


def _run(argv, factory, ask_password, confirm, sleep, out, poll_interval) -> int:
    argv = list(argv)
    if any(a in ("-h", "--help") for a in argv):
        out(HELP.rstrip("\n"))
        return 0
    if not argv or argv[0].startswith("-") or argv[0] not in SUBCOMMANDS:
        what = f"unknown subcommand {argv[0]!r}" if argv and not argv[0].startswith("-") else "no subcommand"
        _err(f"{PREFIX}: {what}")
        _err(_valid_subcommands())
        return 64
    args = _parser().parse_args(argv)
    sub = args.subcommand

    if not (sub == "stage" and args.dry_run):
        if not args.host:
            raise _Usage(f"--host is required for {sub}")
    if args.host:
        host._check_host(args.host)
    try:
        host.validate_remote_python(args.remote_python)
    except host.HostError as exc:
        raise _Usage(f"{exc} (an absolute path or a plain command name)") from None

    resolved = resolve_profile(args.board, Path(args.extension_dir) if args.extension_dir else None)
    out(describe(resolved))
    ctx = _Ctx(args, resolved, out, factory, ask_password, confirm, sleep, poll_interval)
    try:
        return _HANDLERS[sub](ctx)
    except LockHeld as exc:
        _err(f"{PREFIX}: refusing: {exc}")
        return 1


def main(
    argv: List[str],
    *,
    transport_factory: Optional[Callable] = None,
    ask_password: Optional[Callable[[], str]] = None,
    confirm: Optional[Callable[[str], str]] = None,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable = print,
    poll_interval: float = 5.0,
) -> int:
    """Run the ssh-emmc medium; argv is everything after the `ssh-emmc` word."""
    factory = transport_factory or (
        lambda host_arg, opts, batch: host.SshTransport(host_arg, extra_opts=opts, batch_mode=batch)
    )
    try:
        return _run(argv, factory, ask_password, confirm, sleep, out, poll_interval)
    except _Usage as exc:
        _err(f"{PREFIX}: {exc}")
        return 64
    except KeyboardInterrupt:
        _err(f"{PREFIX}: interrupted; a started write keeps running on the board, follow it with status")
        return 130
    except (InvalidBoard, UnknownBoard, ProfileError) as exc:
        _err(f"{PREFIX}: {exc}")
        return 64
    except host.HostError as exc:
        _err(f"{PREFIX}: {exc}")
        return 64 if str(exc).startswith("invalid ssh host") else 1
    except (ProfileChanged, UnsafeProfilePath, BundleError) as exc:
        _err(f"{PREFIX}: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - last line of defence, never a traceback
        _err(f"{PREFIX}: error: {type(exc).__name__}: {exc}")
        return 70
