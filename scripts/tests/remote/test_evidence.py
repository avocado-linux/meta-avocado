"""Evidence record tests (task 3.4)."""

from __future__ import annotations

import hashlib
import json
import threading

import pytest

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


_GOOD = {"image_hashes": {"boot": "a"}, "profile_hash": "p", "board_identity": {"s": 1}, "run_id": "r"}


@pytest.mark.parametrize("key", ["image_hashes", "profile_hash", "board_identity", "run_id"])
@pytest.mark.parametrize("empty", ["absent", {}, "", None])
def test_authorise_refuses_when_a_mandatory_key_is_absent_or_empty_in_either_record(key, empty):
    broken = dict(_GOOD)
    if empty == "absent":
        del broken[key]
    else:
        broken[key] = empty
    assert not ev.authorise(broken, broken)
    assert not ev.authorise(dict(_GOOD), broken)
    assert not ev.authorise(broken, dict(_GOOD))


def test_authorise_two_empty_records_is_false():
    assert not ev.authorise({}, {})


def test_authorise_complete_equal_records_is_true():
    assert ev.authorise(dict(_GOOD), json.loads(json.dumps(_GOOD)))


# ---- 5.31: manifest verification, clocks ----


def _manifest(run_dir):
    return json.loads((run_dir / "MANIFEST.json").read_text())


def _rewrite(run_dir, fn):
    m = _manifest(run_dir)
    fn(m)
    (run_dir / "MANIFEST.json").write_text(json.dumps(m))


def test_good_record_set_still_verifies(tmp_path):
    assert ev.verify_record_set(_build(tmp_path)).ok


# --- 5.41: which tool build wrote the disk -----------------------------------


def test_manifest_carries_the_bundle_digest_when_the_runner_knows_it(tmp_path):
    run_dir = ev.new_run_dir(tmp_path)
    rs = ev.RecordSet(run_dir, "1.0", "r2", "p" * 8, {"boot": "a" * 8}, {}, [], "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z")
    rs.bundle_json_sha256 = "d" * 64
    rs.add("plan.json", {"k": "v"})
    rs.finalize("runner-complete")
    assert _manifest(run_dir)["bundle_json_sha256"] == "d" * 64
    assert ev.verify_record_set(run_dir).ok


def test_a_record_set_from_before_the_field_existed_still_verifies(tmp_path):
    run_dir = _build(tmp_path)
    assert "bundle_json_sha256" not in _manifest(run_dir)
    assert ev.verify_record_set(run_dir).ok


@pytest.mark.parametrize("bad", ["", "xyz", "d" * 63, 7, None, ["d" * 64]])
def test_a_malformed_bundle_digest_in_the_manifest_fails_verification(tmp_path, bad):
    d = _build(tmp_path)
    _rewrite(d, lambda m: m.__setitem__("bundle_json_sha256", bad))
    res = ev.verify_record_set(d)
    assert not res.ok and any("bundle_json_sha256" in p for p in res.problems)


@pytest.mark.parametrize(
    "key",
    ["host_tool_version", "runner_version", "profile_hash", "image_hashes", "board_identity",
     "transition_log", "clocks", "run_status"],
)
def test_manifest_missing_a_required_field_fails_verification(tmp_path, key):
    d = _build(tmp_path)
    _rewrite(d, lambda m: m.pop(key))
    res = ev.verify_record_set(d)
    assert not res.ok and any(key in p for p in res.problems)


@pytest.mark.parametrize(
    "key,bad",
    [("host_tool_version", 3), ("runner_version", ""), ("profile_hash", None), ("image_hashes", []),
     ("image_hashes", {"boot": 1}), ("board_identity", "x"), ("transition_log", {}), ("clocks", []),
     ("run_status", "bogus"), ("run_status", 5)],
)
def test_manifest_field_of_the_wrong_type_fails_verification(tmp_path, key, bad):
    d = _build(tmp_path)
    _rewrite(d, lambda m: m.__setitem__(key, bad))
    assert not ev.verify_record_set(d).ok


def test_duplicate_artifact_names_fail_verification(tmp_path):
    d = _build(tmp_path)
    _rewrite(d, lambda m: m["artifacts"].append(dict(m["artifacts"][0])))
    res = ev.verify_record_set(d)
    assert not res.ok and any("duplicate" in p for p in res.problems)


@pytest.mark.parametrize("name", ["../x", "/etc/passwd", "a/b", "..", ".", "", "a\x00b"])
def test_artifact_names_outside_the_run_directory_fail_without_being_opened(tmp_path, name):
    d = _build(tmp_path)
    secret = tmp_path / "outside"
    secret.write_bytes(b"s")
    art = {"name": name, "size": 1, "sha256": _sha(b"s")}
    _rewrite(d, lambda m: m["artifacts"].append(art))
    res = ev.verify_record_set(d)
    assert not res.ok and any("bad artifact name" in p for p in res.problems)


def test_symlinked_artifact_fails_verification(tmp_path):
    d = _build(tmp_path)
    target = tmp_path / "elsewhere"
    target.write_bytes(b"line1\nline2\n")
    (d / "runner.log").unlink()
    (d / "runner.log").symlink_to(target)
    res = ev.verify_record_set(d)
    assert not res.ok and any("not a regular file" in p for p in res.problems)


def test_directory_artifact_fails_verification(tmp_path):
    d = _build(tmp_path)
    (d / "runner.log").unlink()
    (d / "runner.log").mkdir()
    assert not ev.verify_record_set(d).ok


def test_manifest_that_is_not_an_object_fails(tmp_path):
    d = _build(tmp_path)
    (d / "MANIFEST.json").write_text("[]")
    assert not ev.verify_record_set(d).ok


def test_zoneless_timestamp_is_utc():
    assert ev.clock_skew_seconds("2026-10-01T00:00:00", "2026-10-01T00:00:10Z") == 10


@pytest.mark.parametrize("bad", ["garbage", "", None, 5])
def test_malformed_or_missing_clock_still_writes_the_manifest_with_null_skew(tmp_path, bad):
    d = _build(tmp_path, board_utc=bad)
    m = _manifest(d)
    assert m["clocks"]["skew_seconds"] is None
    assert ev.verify_record_set(d).ok


# ---- 5.33: the clock record is evidence, but its two timestamps must be present ----


@pytest.mark.parametrize("key", ["host_utc", "board_utc"])
@pytest.mark.parametrize("bad", ["absent", None, "", 5])
def test_manifest_clocks_need_both_timestamps_as_non_empty_strings(tmp_path, key, bad):
    d = _build(tmp_path)

    def fn(m):
        if bad == "absent":
            del m["clocks"][key]
        else:
            m["clocks"][key] = bad

    _rewrite(d, fn)
    res = ev.verify_record_set(d)
    assert not res.ok and any(key in p for p in res.problems)


def test_a_null_skew_alone_still_verifies(tmp_path):
    d = _build(tmp_path)
    _rewrite(d, lambda m: m["clocks"].__setitem__("skew_seconds", None))
    assert ev.verify_record_set(d).ok


def test_a_missing_clock_is_recorded_as_unavailable_and_verifies(tmp_path):
    d = _build(tmp_path, board_utc=None)
    clocks = _manifest(d)["clocks"]
    assert clocks["board_utc"] == "unavailable" and clocks["skew_seconds"] is None
    assert ev.verify_record_set(d).ok
