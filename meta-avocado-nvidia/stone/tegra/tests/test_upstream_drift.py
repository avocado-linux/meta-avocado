"""Upstream meta-tegra drift guard.

Reads each tracked upstream file by revision from $VENDOR_META_TEGRA and compares
its sha256 with the record. Every way of being unable to look is a failure
("could not evaluate"), never a skip or a pass.
"""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from avocado_tegraflash import usb

REPO_ROOT = Path(__file__).resolve().parents[4]
RECORD_PATH = Path(__file__).resolve().parents[1] / "upstream-tracking.json"
KAS_PIN_PATH = REPO_ROOT / "kas" / "vendor" / "nvidia.yml"
USB_SCRIPT = "recipes-bsp/tegra-binaries/tegra-helper-scripts/find-jetson-usb.sh"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PID_CASE_RE = re.compile(r'case\s+"\$idProduct"\s+in\b(.*?)\besac\b', re.DOTALL)
PID_ARM_RE = re.compile(r"^\s*([0-9a-fA-F]{4}(?:\|[0-9a-fA-F]{4})*)\)", re.MULTILINE)
GIT_TIMEOUT = 30
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "flash-tools-tests.yml"
PIN_AWK = "/^  meta-tegra:$/{f=1;next} /^  [^ ]/{f=0} f&&/^    commit:/{print $2;exit}"


class CouldNotEvaluate(Exception):
    pass


def parse_kas_pin(text: str, repo: str = "meta-tegra") -> str | None:
    """Commit of the exact top-level repo key `repo:` (never `repo-community:`)."""
    in_repo = False
    for line in text.splitlines():
        if re.match(r"^  \S", line):
            in_repo = line.strip() == f"{repo}:"
            continue
        if re.match(r"^\S", line):
            in_repo = False
        m = re.match(r"^    commit:\s*([0-9a-fA-F]+)\s*$", line)
        if in_repo and m:
            return m.group(1)
    return None


def check_record_complete(record: dict) -> list[str]:
    errors = []
    rev = record.get("revision")
    files = record.get("files")
    if not isinstance(rev, str) or not re.fullmatch(r"[0-9a-f]{40}", rev):
        errors.append(f"record revision is not a 40-hex commit: {rev!r}")
    if not isinstance(files, dict) or not files:
        return errors + ["record lists no files"]
    for path, entry in files.items():
        sha = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
            errors.append(f"{path}: sha256 is not 64 lowercase hex: {sha!r}")
        if isinstance(entry, dict) and "forked_as" not in entry:
            errors.append(f"{path}: forked_as key is missing (use null for an unforked file)")
        file_rev = entry.get("revision", rev) if isinstance(entry, dict) else None
        if file_rev != rev:
            errors.append(f"{path}: revision {file_rev!r} differs from record revision {rev!r}")
    return errors


def check_revision_matches_pin(record: dict, pin: str | None) -> list[str]:
    if pin is None:
        return ["could not evaluate: no meta-tegra commit found in the kas pin"]
    if record.get("revision") != pin:
        return [f"recorded revision {record.get('revision')} differs from kas pin {pin}"]
    return []


def git_show(vendor: str, revision: str, path: str) -> bytes:
    if not vendor:
        raise CouldNotEvaluate("could not evaluate: VENDOR_META_TEGRA is unset or empty")
    if not Path(vendor).is_dir():
        raise CouldNotEvaluate(f"could not evaluate: {vendor} is not a directory")
    try:
        proc = subprocess.run(
            ["git", "-C", vendor, "show", f"{revision}:{path}"],
            capture_output=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CouldNotEvaluate(f"could not evaluate: git failed in {vendor}: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        raise CouldNotEvaluate(
            f"could not evaluate: cannot read {revision}:{path} in {vendor}: {err}"
        )
    return proc.stdout


def check_hashes(record: dict, reader, revision: str) -> list[str]:
    """Hash each tracked file at `revision`, the kas pin, so a changed upstream file
    is reported with both hashes before anyone has edited the record."""
    errors = []
    for path, entry in record["files"].items():
        data = reader(revision, path)
        actual = hashlib.sha256(data).hexdigest()
        if actual != entry["sha256"]:
            errors.append(f"{path}: recorded sha256 {entry['sha256']} but upstream is {actual}")
    return errors


def extract_recovery_pids(script: str) -> list[str]:
    m = PID_CASE_RE.search(script)
    arms = PID_ARM_RE.findall(m.group(1)) if m else []
    if not arms:
        raise CouldNotEvaluate("could not evaluate: no idProduct case line in find-jetson-usb.sh")
    return [p.lower() for arm in arms for p in arm.split("|")]


def check_pids(script: str, recovery_pids) -> list[str]:
    known = {p.lower() for p in recovery_pids}
    missing = [p for p in extract_recovery_pids(script) if p not in known]
    return [f"upstream recovery id {p} is absent from RECOVERY_PIDS" for p in missing]


def load_record() -> dict:
    return json.loads(RECORD_PATH.read_text())


def vendor_reader():
    vendor = os.environ.get("VENDOR_META_TEGRA", "")
    return lambda rev, path: git_show(vendor, rev, path)


# --- pure-function proofs on mutated inputs -------------------------------

GOOD_SHA = "a" * 64
GOOD_REV = "b" * 40
SCRIPT = 'x\ncase "$idProduct" in\n    7019|7819|7E19)\n        ok\n        ;;\nesac\n'


def good_record():
    return {"revision": GOOD_REV, "files": {"f": {"sha256": GOOD_SHA, "forked_as": None}}}


def test_complete_record_passes():
    assert check_record_complete(good_record()) == []


def test_incomplete_record_fails():
    r = good_record()
    r["files"]["f"]["sha256"] = "abc"
    assert check_record_complete(r) == ["f: sha256 is not 64 lowercase hex: 'abc'"]
    r = good_record()
    r["files"]["f"]["revision"] = "c" * 40
    assert check_record_complete(r) == [
        f"f: revision {'c' * 40!r} differs from record revision {GOOD_REV!r}"
    ]
    r = good_record()
    r["files"] = {}
    assert check_record_complete(r) == ["record lists no files"]


def test_a_sha256_with_a_trailing_newline_is_refused():
    r = good_record()
    r["files"]["f"]["sha256"] = GOOD_SHA + "\n"
    assert check_record_complete(r) == [f"f: sha256 is not 64 lowercase hex: {GOOD_SHA + chr(10)!r}"]


def test_pin_parse_ignores_community():
    text = (
        "repos:\n  meta-tegra-community:\n    commit: " + "1" * 40 + "\n"
        "  meta-tegra:\n    commit: " + "2" * 40 + "\n"
    )
    assert parse_kas_pin(text) == "2" * 40
    assert parse_kas_pin("repos:\n  meta-tegra-community:\n    commit: " + "1" * 40 + "\n") is None


def test_revision_pin_mismatch_fails():
    assert check_revision_matches_pin(good_record(), GOOD_REV) == []
    errs = check_revision_matches_pin(good_record(), "d" * 40)
    assert len(errs) == 1 and GOOD_REV in errs[0] and "d" * 40 in errs[0]
    assert "could not evaluate" in check_revision_matches_pin(good_record(), None)[0]


def test_hash_mismatch_names_file_and_both_hashes():
    errs = check_hashes(good_record(), lambda rev, path: b"changed", GOOD_REV)
    assert len(errs) == 1
    actual = hashlib.sha256(b"changed").hexdigest()
    assert "f:" in errs[0] and GOOD_SHA in errs[0] and actual in errs[0]


def test_hash_match_passes():
    rec = {"revision": GOOD_REV, "files": {"f": {"sha256": hashlib.sha256(b"x").hexdigest()}}}
    assert check_hashes(rec, lambda rev, path: b"x", GOOD_REV) == []


def test_hashes_are_read_at_the_given_revision_not_the_recorded_one():
    seen = []

    def reader(rev, path):
        seen.append(rev)
        return b"x"

    check_hashes(good_record(), reader, "d" * 40)
    assert seen == ["d" * 40]


def test_missing_forked_as_key_is_a_failure():
    r = good_record()
    del r["files"]["f"]["forked_as"]
    assert check_record_complete(r) == ["f: forked_as key is missing (use null for an unforked file)"]


def test_pids_in_every_case_arm_are_checked():
    script = (
        'case "$idProduct" in\n    7019|7819)\n        ok\n        ;;\n'
        '    7E19|7C18)\n        ok\n        ;;\n    *)\n        no\n        ;;\nesac\n'
        '7777)\n'
    )
    assert extract_recovery_pids(script) == ["7019", "7819", "7e19", "7c18"]
    errs = check_pids(script, ("7019", "7819", "7e19"))
    assert len(errs) == 1 and "7c18" in errs[0]


def test_workflow_has_no_literal_ref_that_can_drift():
    text = WORKFLOW_PATH.read_text()
    assert not re.search(r"\b[0-9a-f]{40}\b", text)
    assert "727633de" not in text
    assert "ref: ${{ steps.pin.outputs.sha }}" in text
    assert PIN_AWK in text


def test_workflow_pin_extraction_yields_the_kas_pin():
    out = subprocess.run(
        ["awk", PIN_AWK, str(KAS_PIN_PATH)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == parse_kas_pin(KAS_PIN_PATH.read_text())


def test_removed_recovery_pid_fails():
    assert check_pids(SCRIPT, ("7019", "7819", "7e19")) == []
    errs = check_pids(SCRIPT, ("7019", "7e19"))
    assert len(errs) == 1 and "7819" in errs[0]


def test_pid_case_line_missing_could_not_evaluate():
    with pytest.raises(CouldNotEvaluate, match="could not evaluate"):
        extract_recovery_pids("nothing here")


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "vendor"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    (repo / "a.txt").write_text("hello\n")
    for argv in (
        ["init", "-q"],
        ["add", "a.txt"],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c"],
    ):
        subprocess.run(["git", "-C", str(repo), *argv], check=True, env=env, capture_output=True)
    rev = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, env=env,
    ).stdout.strip()
    return repo, rev


def test_git_show_reads_by_revision(tmp_repo):
    repo, rev = tmp_repo
    assert git_show(str(repo), rev, "a.txt") == b"hello\n"


@pytest.mark.parametrize("case", ["unset", "not_dir", "not_git", "bad_rev", "bad_file"])
def test_git_show_unevaluable_cases_fail(tmp_repo, tmp_path, case):
    repo, rev = tmp_repo
    notgit = tmp_path / "plain"
    notgit.mkdir()
    args = {
        "unset": ("", rev, "a.txt"),
        "not_dir": (str(tmp_path / "missing"), rev, "a.txt"),
        "not_git": (str(notgit), rev, "a.txt"),
        "bad_rev": (str(repo), "e" * 40, "a.txt"),
        "bad_file": (str(repo), rev, "nope.txt"),
    }[case]
    with pytest.raises(CouldNotEvaluate, match="could not evaluate"):
        git_show(*args)


# --- the live checks ------------------------------------------------------


def test_record_is_complete():
    assert check_record_complete(load_record()) == []


def test_record_revision_matches_kas_pin():
    pin = parse_kas_pin(KAS_PIN_PATH.read_text())
    assert check_revision_matches_pin(load_record(), pin) == []


def test_forked_as_paths_exist():
    for path, entry in load_record()["files"].items():
        forked = entry.get("forked_as")
        if forked:
            assert (REPO_ROOT / forked).is_file(), f"{path}: forked_as {forked} missing"


def test_upstream_files_match_record():
    try:
        pin = parse_kas_pin(KAS_PIN_PATH.read_text())
        if pin is None:
            raise CouldNotEvaluate("could not evaluate: no meta-tegra commit found in the kas pin")
        errors = check_hashes(load_record(), vendor_reader(), pin)
    except CouldNotEvaluate as exc:
        pytest.fail(str(exc))
    assert errors == []


def test_upstream_recovery_ids_covered():
    try:
        pin = parse_kas_pin(KAS_PIN_PATH.read_text())
        if pin is None:
            raise CouldNotEvaluate("could not evaluate: no meta-tegra commit found in the kas pin")
        script = vendor_reader()(pin, USB_SCRIPT).decode()
        errors = check_pids(script, usb.RECOVERY_PIDS)
    except CouldNotEvaluate as exc:
        pytest.fail(str(exc))
    assert errors == []
