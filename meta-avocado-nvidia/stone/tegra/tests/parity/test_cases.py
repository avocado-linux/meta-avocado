"""Tests for the parity case matrix."""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
from pathlib import Path

import pytest

from parity import cases, fixtures, stubs

STONE = Path(__file__).resolve().parents[3]
SCRIPT = "stone-provision-tegraflash.sh"
SCENARIO_KEYS = {"lsusb", "boardctl_rc", "adb_rc", "dtbo_priority", "fdtput_takes", "flash_rc"}
TREE_KEYS = {"carrier", "kernel", "drop", "shadow_link", "absolute_images", "tos_name"}


def _profiles(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    return [n for n, p in data["provision"]["profiles"].items() if p.get("script") == SCRIPT]


def test_profile_cases_total_32_from_manifest_data():
    expected = sum(len(_profiles(m)) for m in sorted(STONE.glob("*.json")) if _profiles(m))
    assert expected == 32
    base = [c for c in cases.all_cases() if c.id.endswith("/base")]
    assert len(base) == 32


def test_every_manifest_naming_the_script_is_covered():
    stems = {m.stem for m in STONE.glob("*.json") if _profiles(m)}
    assert len(stems) == 7
    assert {c.manifest.stem for c in cases.all_cases()} == stems


def test_base_case_shape():
    for c in cases.all_cases():
        if not c.id.endswith("/base"):
            continue
        assert dict(c.env)["AVOCADO_PROVISION_PROFILE"] in _profiles(c.manifest)
        assert c.tree["kernel"] is True
        assert c.scenario["lsusb"] == [["Bus 001 Device 005: ID 0955:7523 NVIDIA Corp. APX"]]


def test_ids_unique_and_descriptive():
    ids = [c.id for c in cases.all_cases()]
    assert len(ids) == len(set(ids))
    for c in cases.all_cases():
        assert c.id.startswith(c.manifest.stem + "/" + dict(c.env)["AVOCADO_PROVISION_PROFILE"] + "/")


def test_case_is_frozen_and_hashable():
    c = cases.all_cases()[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.id = "x"  # type: ignore[misc]
    assert isinstance(hash(c), int)


def test_scenario_and_tree_keys_match_schemas():
    for c in cases.all_cases():
        assert set(c.scenario) <= SCENARIO_KEYS, c.id
        assert set(c.tree) <= TREE_KEYS, c.id
        assert all(isinstance(o, list) for o in c.scenario["lsusb"]), c.id


def _variants(suffix: str):
    return [c for c in cases.all_cases() if c.id.endswith("/" + suffix)]


@pytest.mark.parametrize(
    "suffix",
    [
        "no-kernel",
        "carrier",
        "erase-emmc",
        "erase-only",
        "sd-env",
        "sd-malformed",
        "boardctl-ok",
        "boardctl-fail",
        "third-poll",
        "missing-bsp",
        "missing-emmc-layout",
        "missing-appuuid",
        "flash-exit-7",
    ],
)
def test_variant_present(suffix):
    assert _variants(suffix), suffix


def test_variant_contents():
    assert all(c.tree["kernel"] is False for c in _variants("no-kernel"))
    assert all(c.tree["carrier"] for c in _variants("carrier"))
    assert all(dict(c.env)["ERASE_EMMC"] == "1" for c in _variants("erase-emmc"))
    assert all(dict(c.env)["ERASE_ONLY"] == "1" for c in _variants("erase-only"))
    assert all(dict(c.env)["AVOCADO_PROVISION_SD_DEVICE"] == "mmcblk1" for c in _variants("sd-env"))
    assert all("/" in dict(c.env)["AVOCADO_PROVISION_SD_DEVICE"] for c in _variants("sd-malformed"))
    assert all(c.scenario["boardctl_rc"] == 0 for c in _variants("boardctl-ok"))
    assert all(c.scenario["boardctl_rc"] == 1 for c in _variants("boardctl-fail"))
    assert all(dict(c.env)["BOARDCTL_TARGET"] for c in _variants("boardctl-ok") + _variants("boardctl-fail"))
    assert all(len(c.scenario["lsusb"]) == 3 and c.scenario["lsusb"][:2] == [[], []] for c in _variants("third-poll"))
    assert all(c.scenario["flash_rc"] == 7 for c in _variants("flash-exit-7"))
    assert all(c.tree["drop"] for c in _variants("missing-bsp"))


def test_sd_undeclared_only_where_manifest_declares_none():
    undeclared = _variants("sd-undeclared")
    assert undeclared
    for c in undeclared:
        assert "sd_device" not in json.dumps(json.loads(c.manifest.read_text()))
        assert "AVOCADO_PROVISION_SD_DEVICE" not in dict(c.env)


def test_no_cases_rely_on_refusal_deviations():
    for c in cases.all_cases():
        assert dict(c.env)["AVOCADO_PROVISION_PROFILE"] in {
            "tegraflash",
            "tegraflash-nvme",
            "tegraflash-mmc",
            "tegraflash-emmc",
            "tegraflash-sd",
        }
        if c.id.endswith("/no-board"):
            assert c.scenario["lsusb"] == [[]], c.id  # no board ever appears
        else:
            assert len(c.scenario["lsusb"][-1]) == 1, c.id  # one board only


def test_new_variants_exist_for_every_manifest_and_name_listed_deviations_only():
    from parity.deviations import DEVIATIONS

    assert len(_variants("no-board")) == 1
    for suffix in ("absolute-image-name", "absolute-tos-name", "priority-trailing-comma"):
        assert len(_variants(suffix)) == len({c.manifest for c in cases.all_cases()}), suffix
    named = {
        "shadow-link": "symlink-destination-replaced",
        "carrier-no-label": "carrier-label-optional",
        "no-env-file": "env-file-missing-status",
        "absolute-tos-name": "tos-name-bare-filename",
    }
    for suffix, deviation in named.items():
        found = _variants(suffix)
        assert found and all(c.deviation == deviation for c in found), suffix
    assert set(named.values()) <= set(DEVIATIONS)
    assert all(not c.deviation for c in cases.all_cases() if c.id.rsplit("/", 1)[1] not in named)


def test_added_manifest_adds_profile_cases(tmp_path):
    for m in STONE.glob("*.json"):
        shutil.copy(m, tmp_path / m.name)
    before = len([c for c in cases.all_cases(tmp_path) if c.id.endswith("/base")])
    extra = json.loads((STONE / "stone-jetson-orin-nano.json").read_text())
    (tmp_path / "zz-extra.json").write_text(json.dumps(extra))
    after = [c for c in cases.all_cases(tmp_path) if c.id.endswith("/base")]
    assert before == 32
    assert len(after) == 37
    assert any(c.manifest.stem == "zz-extra" for c in after)


def test_no_hardcoded_manifest_names():
    src = Path(cases.__file__).read_text()
    assert not re.search(r"stone-(jetson|icam|recomputer)", src)


def test_report_format_and_shortfall():
    assert cases.report(32, 32) == "cases: 32/32 run"
    assert cases.report(30, 32) == "cases: 30/32 run"
    assert cases.shortfall(30, 32) is True
    assert cases.shortfall(32, 32) is False


def test_every_case_builds_a_tree(tmp_path):
    # fixtures.build_tree must recognise every drop/carrier name; once it raises
    # on unknown names this fails for a stale one.
    stub_dir = tmp_path / "stubs"
    stubs.write_stubs(stub_dir, tmp_path / "calls.log", tmp_path / "scenario.json")
    for i, c in enumerate(cases.all_cases()):
        fixtures.build_tree(c.manifest, tmp_path / f"t{i}", stub_dir, **c.tree)


def _images(c):
    return json.loads(c.manifest.read_text())["storage_devices"]["rootdisk"]["images"]


def test_missing_bsp_and_emmc_layout_are_absent_from_tree(tmp_path):
    stub_dir = tmp_path / "stubs"
    stubs.write_stubs(stub_dir, tmp_path / "calls.log", tmp_path / "scenario.json")
    for i, c in enumerate(_variants("missing-bsp")):
        t = fixtures.build_tree(c.manifest, tmp_path / f"b{i}", stub_dir, **c.tree)
        assert not (t.data_dir / _images(c)["tegraflash_bsp"]).exists(), c.id
    for i, c in enumerate(_variants("missing-emmc-layout")):
        t = fixtures.build_tree(c.manifest, tmp_path / f"e{i}", stub_dir, **c.tree)
        bsp = t.data_dir / _images(c)["tegraflash_bsp"]
        assert bsp.is_dir() and not (bsp / "internal-flash-emmc.xml").exists(), c.id


def test_every_carrier_case_declares_a_label():
    carrier_cases = _variants("carrier")
    assert carrier_cases
    for c in carrier_cases:
        assert c.tree["carrier"].get("CARRIER_LABEL"), c.id
    assert cases.CARRIER.get("CARRIER_LABEL")
