"""Carrier-BSP overlay: copy, label, knob rewrites, warnings."""

import hashlib
from pathlib import Path

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash import carrier as carrier_mod
from avocado_tegraflash.carrier import apply_carrier

SLOT = "carrier-bsp"


def _setup(tmp_path, files, flashvars="ODMDATA=old\nDTBFILE=a.dtb\n", initrd="NO_OTHER=1\nROOTFS=x\n"):
    data = tmp_path / "data"
    slot = data / SLOT
    slot.mkdir(parents=True)
    for name, content in files.items():
        (slot / name).write_text(content)
    work = tmp_path / "work"
    work.mkdir()
    (work / "flashvars").write_text(flashvars)
    (work / ".env.initrd-flash").write_text(initrd)
    return str(data), str(work)


def _run(data, work):
    out = []
    apply_carrier(data, SLOT, work, log=out.append)
    return out


def _fv(work):
    return (Path(work) / "flashvars").read_text()


def _env(work):
    return (Path(work) / ".env.initrd-flash").read_text()


def test_missing_source_directory_skips_with_message(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    out = []
    apply_carrier(str(tmp_path / "nodata"), SLOT, str(work), log=out.append)
    assert out == [f"Carrier-BSP source not found: {tmp_path}/nodata/{SLOT} (skipping overlay)"]


def test_placeholder_only_slot_reports_empty_and_copies_nothing(tmp_path):
    data, work = _setup(tmp_path, {".placeholder": ""})
    out = _run(data, work)
    assert out == ["Carrier-BSP slot empty (no overrides; using MACHINE-baked defaults)"]
    assert not (Path(work) / ".placeholder").exists()


def test_empty_directory_reports_empty(tmp_path):
    data, work = _setup(tmp_path, {})
    assert _run(data, work) == ["Carrier-BSP slot empty (no overrides; using MACHINE-baked defaults)"]


def test_files_are_copied_over_work_dir_and_counted_excluding_placeholder(tmp_path):
    data, work = _setup(tmp_path, {".placeholder": "", "a.dtb": "NEW", ".hidden": "h"})
    (Path(work) / "a.dtb").write_text("OLD")
    out = _run(data, work)
    assert out[0] == f"Carrier-BSP overlay: {data}/{SLOT} (2 file(s))"
    assert (Path(work) / "a.dtb").read_text() == "NEW"
    assert (Path(work) / ".hidden").read_text() == "h"


def test_symlink_is_kept_as_symlink(tmp_path):
    data, work = _setup(tmp_path, {"real": "r"})
    (Path(data) / SLOT / "link").symlink_to("real")
    _run(data, work)
    assert (Path(work) / "link").is_symlink()


def test_label_is_printed_with_quotes_stripped(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": 'CARRIER_LABEL="My Board"\n'})
    assert "  Carrier: My Board" in _run(data, work)


def test_empty_label_prints_nothing(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": 'CARRIER_LABEL=""\n'})
    assert not any("Carrier:" in line for line in _run(data, work))


@pytest.mark.deviation("carrier-label-optional")
def test_carrier_env_without_a_label_line_prints_no_label_and_still_applies_knobs(tmp_path):
    # Oracle line 191: grep finds no CARRIER_LABEL, and pipefail plus set -e abort.
    data, work = _setup(tmp_path, {"carrier.env": 'CARRIER_FV_DTBFILE="b.dtb"\n'})
    out = _run(data, work)
    assert not any("Carrier:" in line for line in out)
    assert _fv(work) == 'ODMDATA=old\nDTBFILE="b.dtb"\n'


def test_fv_knob_rewrites_whole_flashvars_line_and_logs_it(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": 'CARRIER_FV_DTBFILE="b.dtb"\n'})
    out = _run(data, work)
    assert _fv(work) == 'ODMDATA=old\nDTBFILE="b.dtb"\n'
    assert "  flashvars: DTBFILE=b.dtb" in out


def test_env_knob_rewrites_initrd_env_and_not_flashvars(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_ENV_ROOTFS=y\n"})
    out = _run(data, work)
    assert _env(work) == 'NO_OTHER=1\nROOTFS="y"\n'
    assert _fv(work) == "ODMDATA=old\nDTBFILE=a.dtb\n"
    assert "  .env.initrd-flash: ROOTFS=y" in out


def test_single_quoted_value_loses_its_quotes(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_FV_DTBFILE='b.dtb'\n"})
    _run(data, work)
    assert 'DTBFILE="b.dtb"' in _fv(work)


@pytest.mark.deviation("carrier-values-literal")
def test_special_characters_in_value_are_written_literally(tmp_path):
    data, work = _setup(
        tmp_path, {"carrier.env": 'CARRIER_FV_ODMDATA="0x91&|x"\nCARRIER_ENV_NO_SUCH_KEY=1\n'}
    )
    out = _run(data, work)
    assert _fv(work) == 'ODMDATA="0x91&|x"\nDTBFILE=a.dtb\n'
    assert _fv(work).count("ODMDATA=") == 1
    assert "NO_SUCH_KEY=" not in _env(work)
    assert any("NO_SUCH_KEY" in line and "WARNING" in line for line in out)


@pytest.mark.deviation("carrier-values-literal")
@pytest.mark.parametrize(
    "value",
    ["a&b", "p|q", "with space", "", "&&", "0x91+1.2-b_c", "a;b", "it's"],
)
def test_value_is_written_byte_for_byte(tmp_path, value):
    data, work = _setup(tmp_path, {"carrier.env": f'CARRIER_FV_ODMDATA="{value}"\n'})
    _run(data, work)
    assert _fv(work) == f'ODMDATA="{value}"\nDTBFILE=a.dtb\n'


@pytest.mark.deviation("carrier-value-shell-safe")
@pytest.mark.parametrize("value", ['a"b', "$HOME", "$(id)", "`id`", "back\\slash", "x\\1y", '"$(id)"x'])
@pytest.mark.parametrize("prefix, target", [("CARRIER_FV_ODMDATA", "flashvars"), ("CARRIER_ENV_ROOTFS", ".env.initrd-flash")])
def test_a_value_the_shell_would_act_on_is_refused_naming_the_key_and_file(tmp_path, prefix, target, value):
    data, work = _setup(tmp_path, {"carrier.env": f"{prefix}={value}\n"})
    with pytest.raises(EngineError) as info:
        _run(data, work)
    assert prefix in str(info.value) and target in str(info.value)
    assert _fv(work) == "ODMDATA=old\nDTBFILE=a.dtb\n" and _env(work) == "NO_OTHER=1\nROOTFS=x\n"


@pytest.mark.deviation("carrier-value-shell-safe")
@pytest.mark.parametrize("key", ["CARRIER_FV_", "CARRIER_ENV_", "CARRIER_FV_A-B", "CARRIER_FV_1A", "CARRIER_ENV_A B", "CARRIER_FV_A$(id)"])
def test_a_key_that_is_not_a_shell_identifier_is_refused(tmp_path, key):
    data, work = _setup(tmp_path, {"carrier.env": f"{key}=v\n"})
    with pytest.raises(EngineError, match="not a shell variable name"):
        _run(data, work)
    assert _fv(work) == "ODMDATA=old\nDTBFILE=a.dtb\n"


@pytest.mark.deviation("carrier-value-shell-safe")
def test_a_refused_value_is_refused_even_when_the_target_line_is_missing(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_FV_NOPE=$(id)\n"})
    with pytest.raises(EngineError, match="CARRIER_FV_NOPE"):
        _run(data, work)


@pytest.mark.deviation("carrier-value-shell-safe")
def test_the_safe_check_removed_mutation_is_caught(tmp_path, mutant):
    mod = mutant("carrier.py", "        _require_shell_safe(key, name, val, target)\n", "")
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_FV_ODMDATA=$(id)\n"})
    mod.apply_carrier(data, SLOT, work, log=lambda _t: None)
    assert _fv(work) == 'ODMDATA="$(id)"\nDTBFILE=a.dtb\n'


def test_missing_target_line_warns_and_appends_nothing(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_FV_NOPE=1\n"})
    out = _run(data, work)
    assert _fv(work) == "ODMDATA=old\nDTBFILE=a.dtb\n"
    assert "  WARNING: CARRIER_FV_NOPE target not found in flashvars; skipped" in out


def test_missing_target_file_warns(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_ENV_X=1\n"})
    (Path(work) / ".env.initrd-flash").unlink()
    out = _run(data, work)
    assert "  WARNING: CARRIER_ENV_X target not found in .env.initrd-flash; skipped" in out
    assert not (Path(work) / ".env.initrd-flash").exists()


def test_every_matching_line_is_replaced(tmp_path):
    data, work = _setup(
        tmp_path, {"carrier.env": "CARRIER_FV_K=v\n"}, flashvars="K=1\nOTHER=2\nK=3\n"
    )
    _run(data, work)
    assert _fv(work) == 'K="v"\nOTHER=2\nK="v"\n'


def test_name_must_match_whole_prefix_not_a_longer_name(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_FV_K=v\n"}, flashvars="KEY=1\n")
    out = _run(data, work)
    assert _fv(work) == "KEY=1\n"
    assert any("WARNING" in line for line in out)


def test_file_without_trailing_newline_stays_without(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_FV_K=v\n"}, flashvars="A=1\nK=2")
    _run(data, work)
    assert _fv(work) == 'A=1\nK="v"'


def test_indented_knob_line_is_ignored_like_the_oracle(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "  CARRIER_FV_DTBFILE=z\n"})
    out = _run(data, work)
    assert _fv(work) == "ODMDATA=old\nDTBFILE=a.dtb\n"
    assert not any("WARNING" in line for line in out)


def test_value_keeps_inner_equals_signs(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": 'CARRIER_FV_ODMDATA="a=b=c"\n'})
    _run(data, work)
    assert 'ODMDATA="a=b=c"' in _fv(work)


def test_unicode_value_round_trips(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_FV_ODMDATA=café\n"})
    _run(data, work)
    assert 'ODMDATA="café"' in _fv(work)


def test_unrelated_carrier_env_keys_are_ignored(tmp_path):
    data, work = _setup(tmp_path, {"carrier.env": "CARRIER_SIGNED_X=1\nFOO=2\n"})
    out = _run(data, work)
    assert _fv(work) == "ODMDATA=old\nDTBFILE=a.dtb\n"
    assert not any("WARNING" in line for line in out)


def test_slot_without_carrier_env_only_copies(tmp_path):
    data, work = _setup(tmp_path, {"a.dtb": "x"})
    out = _run(data, work)
    assert len(out) == 1


# Mutation proofs: break a copy of the module and show the expectations fail.
def _mut_run(mod, tmp_path):
    data, work = _setup_nested(tmp_path)
    mod.apply_carrier(data, SLOT, work, log=lambda s: None)
    return _fv(work), _env(work)


def _setup_nested(tmp_path):
    base = tmp_path / "t"
    base.mkdir()
    return _setup(
        base, {"carrier.env": 'CARRIER_FV_ODMDATA="0x91&|x"\nCARRIER_ENV_NO_SUCH_KEY=1\n'}
    )


def test_mutation_unmutated_module_passes_the_end_to_end_spec(tmp_path):
    fv, env = _mut_run(carrier_mod, tmp_path)
    assert fv == 'ODMDATA="0x91&|x"\nDTBFILE=a.dtb\n' and "NO_SUCH_KEY=" not in env


def test_mutation_sed_style_ampersand_expansion_is_detected(tmp_path, mutant):
    mod = mutant("carrier.py", "lines[i] = f'{name}=\"{val}\"'", "lines[i] = f'{name}=\"{val.replace(chr(38), line)}\"'")
    fv, _ = _mut_run(mod, tmp_path)
    assert fv != 'ODMDATA="0x91&|x"\nDTBFILE=a.dtb\n'


def test_mutation_appending_missing_target_is_detected(tmp_path, mutant):
    mod = mutant(
        "carrier.py",
        "    if hit:\n",
        "    if not hit:\n        lines.append(f'{name}=\"{val}\"')\n        hit = True\n    if hit:\n",
    )
    _, env = _mut_run(mod, tmp_path)
    assert "NO_SUCH_KEY=" in env


@pytest.mark.parametrize("target", ["flashvars", ".env.initrd-flash"])
def test_rewritten_symlink_is_replaced_and_the_source_it_pointed_at_is_untouched(tmp_path, target):
    data, work = _setup(tmp_path, {"carrier.env": 'CARRIER_FV_ODMDATA="new"\nCARRIER_ENV_ROOTFS="y"\n'})
    outside = tmp_path / "outside.txt"
    outside.write_text("ODMDATA=old\nROOTFS=x\n")
    before = hashlib.sha256(outside.read_bytes()).hexdigest()
    link = Path(work) / target
    link.unlink()
    link.symlink_to(outside)
    _run(data, work)
    expected = 'ODMDATA="new"\nROOTFS=x\n' if target == "flashvars" else 'ODMDATA=old\nROOTFS="y"\n'
    assert (hashlib.sha256(outside.read_bytes()).hexdigest() == before, link.is_symlink(), link.read_text()) == (
        True,
        False,
        expected,
    )


@pytest.mark.deviation("symlink-destination-replaced")
def test_overlay_symlink_over_an_existing_file_is_replaced(tmp_path):
    data, work = _setup(tmp_path, {"real": "r"})
    (Path(data) / SLOT / "a.dtb").symlink_to("real")
    (Path(work) / "a.dtb").write_text("OLD")
    _run(data, work)
    assert (Path(work) / "a.dtb").is_symlink()


@pytest.mark.deviation("symlink-destination-replaced")
def test_overlay_file_over_a_destination_link_never_modifies_the_target(tmp_path):
    data, work = _setup(tmp_path, {"a.dtb": "NEW"})
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    (Path(work) / "a.dtb").symlink_to(outside)
    _run(data, work)
    assert outside.read_text() == "untouched" and (Path(work) / "a.dtb").read_text() == "NEW"


@pytest.mark.deviation("symlink-destination-replaced")
def test_overlay_file_over_a_dangling_destination_link_creates_no_target(tmp_path):
    data, work = _setup(tmp_path, {"a.dtb": "NEW"})
    victim = tmp_path / "victim"
    (Path(work) / "a.dtb").symlink_to(victim)
    _run(data, work)
    assert not victim.exists() and (Path(work) / "a.dtb").read_text() == "NEW"


def test_overlay_over_a_symlinked_destination_directory_is_refused(tmp_path):
    data, work = _setup(tmp_path, {"a.dtb": "x"})
    (Path(data) / SLOT / "d").mkdir()
    (Path(data) / SLOT / "d" / "f").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (Path(work) / "d").symlink_to(outside)
    with pytest.raises(EngineError):
        _run(data, work)
    assert list(outside.iterdir()) == []


def test_absolute_carrier_name_stays_inside_the_data_dir(tmp_path):
    data, work = _setup(tmp_path, {"a.dtb": "x"})
    apply_carrier(data, f"/{SLOT}", work, log=lambda _m: None)
    assert (Path(work) / "a.dtb").read_text() == "x"
    out = []
    apply_carrier(data, str(Path(data) / SLOT), work, log=out.append)
    assert out[0].startswith("Carrier-BSP source not found:")
