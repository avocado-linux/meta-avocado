import json
import subprocess
from pathlib import Path

import pytest

from avocado_flash_launch import boards

REAL_STONE = Path(__file__).resolve().parents[3] / "meta-avocado-nvidia" / "stone"


def manifest(platform="avocado-jetson-x", ids=None, evidence=None, with_key=True):
    tf = {"sd_device": "mmcblk0"}
    if ids is not None:
        tf["rcm_ids"] = ids
    if evidence is not None:
        tf["rcm_evidence"] = evidence
    return {
        "runtime": {"platform": platform, "provision_default": "tegraflash"},
        "provision": {"profiles": {"tegraflash": {}}},
        "storage_devices": {"rootdisk": {"tegraflash": tf}},
    }


def write(d, name, data):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def no_subprocess(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("boards started a subprocess")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)


def run(tmp_path, capsys, deploy=None):
    launcher = tmp_path / "scripts" / "avocado-flash"
    rc = boards.boards(launcher, deploy)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def stone(tmp_path):
    return tmp_path / "meta-avocado-nvidia" / "stone"


def test_real_tree_lists_exactly_seven_jetsons(no_subprocess, capsys):
    launcher = REAL_STONE.parents[1] / "scripts" / "avocado-flash"
    rc = boards.boards(launcher, None)
    out = capsys.readouterr().out
    assert rc == 0
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 7
    assert any("jetson-orin-nano" in ln and "0955:7523" in ln for ln in lines)
    assert sum("none recorded" in ln for ln in lines) == 6


def test_lists_machine_family_and_ids(tmp_path, capsys, no_subprocess):
    write(
        stone(tmp_path),
        "stone-jetson-x.json",
        manifest(ids=["0955:7523", "0955:7019"], evidence={"0955:7523": "a", "0955:7019": "b"}),
    )
    rc, out, _ = run(tmp_path, capsys)
    assert rc == 0
    assert out.split() == ["jetson-x", "tegra", "0955:7523,0955:7019"]


def test_no_ids_prints_none_recorded(tmp_path, capsys, no_subprocess):
    write(stone(tmp_path), "stone-jetson-x.json", manifest())
    rc, out, _ = run(tmp_path, capsys)
    assert rc == 0
    assert out.split() == ["jetson-x", "tegra", "none", "recorded"]


def test_manifest_without_tegraflash_is_not_listed(tmp_path, capsys, no_subprocess):
    write(stone(tmp_path), "stone-other.json", {"runtime": {"platform": "avocado-other"}})
    rc, out, _ = run(tmp_path, capsys)
    assert rc == 0
    assert out.strip() == ""


def test_deploy_tree_manifests_are_included(tmp_path, capsys, no_subprocess):
    write(stone(tmp_path), "stone-jetson-a.json", manifest("avocado-jetson-a"))
    write(tmp_path / "deploy", "stone-jetson-b.json", manifest("avocado-jetson-b"))
    rc, out, _ = run(tmp_path, capsys, deploy=tmp_path / "deploy")
    assert rc == 0
    assert len(out.strip().splitlines()) == 2


@pytest.mark.parametrize(
    "ids,evidence",
    [
        (["1234:7523"], {"1234:7523": "x"}),
        (["0955:7523 "], {"0955:7523 ": "x"}),
        (["0955:75G3"], {"0955:75G3": "x"}),
        (["0955:7A23"], {"0955:7A23": "x"}),
        (["0955:752"], {"0955:752": "x"}),
    ],
)
def test_bad_rcm_id_fails_naming_manifest(tmp_path, capsys, no_subprocess, ids, evidence):
    write(stone(tmp_path), "stone-jetson-bad.json", manifest(ids=ids, evidence=evidence))
    rc, out, err = run(tmp_path, capsys)
    assert rc != 0
    assert "stone-jetson-bad.json" in err
    assert out.strip() == ""


def test_id_without_evidence_fails(tmp_path, capsys, no_subprocess):
    write(stone(tmp_path), "stone-jetson-bad.json", manifest(ids=["0955:7523"], evidence={}))
    rc, _, err = run(tmp_path, capsys)
    assert rc != 0
    assert "stone-jetson-bad.json" in err and "0955:7523" in err


def test_id_with_evidence_key_missing_entirely_fails(tmp_path, capsys, no_subprocess):
    write(stone(tmp_path), "stone-jetson-bad.json", manifest(ids=["0955:7523"]))
    rc, _, err = run(tmp_path, capsys)
    assert rc != 0
    assert "stone-jetson-bad.json" in err


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_evidence_fails(tmp_path, capsys, no_subprocess, text):
    write(
        stone(tmp_path),
        "stone-jetson-bad.json",
        manifest(ids=["0955:7523"], evidence={"0955:7523": text}),
    )
    rc, _, err = run(tmp_path, capsys)
    assert rc != 0
    assert "stone-jetson-bad.json" in err


def test_evidence_for_undeclared_id_fails(tmp_path, capsys, no_subprocess):
    write(
        stone(tmp_path),
        "stone-jetson-bad.json",
        manifest(ids=["0955:7523"], evidence={"0955:7523": "a", "0955:7019": "b"}),
    )
    rc, _, err = run(tmp_path, capsys)
    assert rc != 0
    assert "stone-jetson-bad.json" in err and "0955:7019" in err


def test_duplicate_runtime_platform_fails(tmp_path, capsys, no_subprocess):
    write(stone(tmp_path), "stone-jetson-a.json", manifest("avocado-jetson-dup"))
    write(stone(tmp_path), "stone-jetson-b.json", manifest("avocado-jetson-dup"))
    rc, out, err = run(tmp_path, capsys)
    assert rc != 0
    assert "stone-jetson-b.json" in err and "avocado-jetson-dup" in err
    assert out.strip() == ""


def test_unparseable_json_fails_naming_manifest(tmp_path, capsys, no_subprocess):
    d = stone(tmp_path)
    d.mkdir(parents=True)
    (d / "stone-jetson-bad.json").write_text("{not json")
    rc, _, err = run(tmp_path, capsys)
    assert rc != 0
    assert "stone-jetson-bad.json" in err


def test_missing_platform_fails(tmp_path, capsys, no_subprocess):
    data = manifest()
    del data["runtime"]["platform"]
    write(stone(tmp_path), "stone-jetson-bad.json", data)
    rc, _, err = run(tmp_path, capsys)
    assert rc != 0
    assert "stone-jetson-bad.json" in err


def test_same_platform_in_tree_and_deploy_lists_once_from_deploy(tmp_path, capsys, no_subprocess):
    write(stone(tmp_path), "stone-jetson-a.json", manifest("avocado-jetson-a"))
    ids = ["0955:7523"]
    write(
        tmp_path / "deploy",
        "stone-jetson-a.json",
        manifest("avocado-jetson-a", ids=ids, evidence={"0955:7523": "bench"}),
    )
    rc, out, _ = run(tmp_path, capsys, deploy=tmp_path / "deploy")
    assert rc == 0
    assert out.split() == ["jetson-a", "tegra", "0955:7523"]


def test_duplicate_platform_inside_deploy_dir_fails(tmp_path, capsys, no_subprocess):
    write(tmp_path / "deploy", "stone-jetson-a.json", manifest("avocado-jetson-dup"))
    write(tmp_path / "deploy", "stone-jetson-b.json", manifest("avocado-jetson-dup"))
    rc, out, err = run(tmp_path, capsys, deploy=tmp_path / "deploy")
    assert rc != 0
    assert "stone-jetson-b.json" in err
    assert out.strip() == ""


def test_malformed_deploy_copy_fails_naming_it(tmp_path, capsys, no_subprocess):
    write(stone(tmp_path), "stone-jetson-a.json", manifest("avocado-jetson-a"))
    write(
        tmp_path / "deploy",
        "stone-jetson-a.json",
        manifest("avocado-jetson-a", ids=["1234:7523"], evidence={"1234:7523": "x"}),
    )
    rc, _, err = run(tmp_path, capsys, deploy=tmp_path / "deploy")
    assert rc != 0
    assert "stone-jetson-a.json" in err and "1234:7523" in err
