"""Evidence record tests (task 3.4)."""

from __future__ import annotations

import hashlib
import json
import threading

from avocado_flash_remote import evidence as ev


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _build(tmp_path, board_utc="2026-10-01T00:00:00Z"):
    run_dir = ev.new_run_dir(tmp_path)
    rs = ev.RecordSet(
        run_dir,
        host_tool_version="1.0",
        runner_version="r2",
        profile_hash="p" * 8,
        image_hashes={"boot": "a" * 8, "rootfs": "b" * 8},
        board_identity={"serial": "abc"},
        transition_log=["preflight", "armed", "complete"],
        host_utc="2026-10-01T00:00:00Z",
        board_utc=board_utc,
    )
    rs.add("runner.log", b"line1\nline2\n")
    rs.add("plan.json", {"k": "v"})
    rs.finalize("runner-complete")
    return run_dir


def test_new_run_dirs_unique_under_concurrency(tmp_path):
    out = []
    lock = threading.Lock()

    def go():
        d = ev.new_run_dir(tmp_path)
        with lock:
            out.append(d)

    ts = [threading.Thread(target=go) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(out)) == 32
    assert all(d.is_dir() for d in out)


def test_write_record_returns_sha_and_leaves_no_temp(tmp_path):
    d = ev.new_run_dir(tmp_path)
    h = ev.write_record(d, "a.bin", b"hello")
    assert h == _sha(b"hello")
    assert (d / "a.bin").read_bytes() == b"hello"
    assert [p.name for p in d.iterdir()] == ["a.bin"]


def test_manifest_fields_and_recomputed_hashes(tmp_path):
    d = _build(tmp_path)
    m = json.loads((d / "MANIFEST.json").read_text())
    assert m["host_tool_version"] == "1.0"
    assert m["runner_version"] == "r2"
    assert m["profile_hash"] == "p" * 8
    assert m["image_hashes"] == {"boot": "a" * 8, "rootfs": "b" * 8}
    assert m["board_identity"] == {"serial": "abc"}
    assert m["transition_log"] == ["preflight", "armed", "complete"]
    assert m["run_status"] == "runner-complete"
    names = {a["name"] for a in m["artifacts"]}
    assert names == {"runner.log", "plan.json"}
    for a in m["artifacts"]:
        assert a["sha256"] == _sha((d / a["name"]).read_bytes())
        assert a["size"] == (d / a["name"]).stat().st_size
    assert ev.verify_record_set(d).ok


def test_truncated_file_not_verified(tmp_path):
    d = _build(tmp_path)
    (d / "runner.log").write_bytes(b"line1")
    r = ev.verify_record_set(d)
    assert not r.ok and r.problems
    assert ev.final_status("complete", r) == "not-verified"


def test_missing_file_and_missing_manifest_not_ok(tmp_path):
    d = _build(tmp_path)
    (d / "plan.json").unlink()
    assert not ev.verify_record_set(d).ok
    d2 = _build(tmp_path)
    (d2 / "MANIFEST.json").unlink()
    assert not ev.verify_record_set(d2).ok


def test_unparseable_manifest_not_ok(tmp_path):
    d = _build(tmp_path)
    (d / "MANIFEST.json").write_bytes(b"{trunc")
    assert not ev.verify_record_set(d).ok


def test_extra_file_not_ok(tmp_path):
    d = _build(tmp_path)
    (d / "stray").write_bytes(b"x")
    assert not ev.verify_record_set(d).ok


def test_final_status_matrix(tmp_path):
    d = _build(tmp_path)
    good = ev.verify_record_set(d)
    assert ev.final_status("complete", good) == "complete"
    assert ev.final_status("flashing", good) == "incomplete"
    bad = ev.VerifyResult(False, ["x"])
    assert ev.final_status("complete", bad) == "not-verified"
    assert ev.final_status("flashing", bad) == "incomplete"


def test_clock_skew_recorded_not_authorising(tmp_path):
    d = _build(tmp_path, board_utc="2031-10-01T00:00:00Z")
    m = json.loads((d / "MANIFEST.json").read_text())
    assert m["clocks"]["skew_seconds"] > 4 * 365 * 86400
    plan = {
        "image_hashes": {"boot": "a"},
        "profile_hash": "p",
        "board_identity": {"s": 1},
        "run_id": "r",
    }
    cur = json.loads(json.dumps(plan))
    assert ev.authorise(plan, cur)
    cur["host_utc"] = "1999-01-01T00:00:00Z"
    cur["board_utc"] = "2099-01-01T00:00:00Z"
    cur["skew_seconds"] = 10**9
    assert ev.authorise(plan, cur)
    cur["profile_hash"] = "other"
    assert not ev.authorise(plan, cur)
