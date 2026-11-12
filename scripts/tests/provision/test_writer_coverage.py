"""Every script a stone manifest names is classified as a writer or a non-writer.

The enumeration walks every stone-*.json, takes each provision.profiles entry
and locates its script. The CLASSIFICATION table below puts every script in one
of four kinds:

  library   sources avocado-safe-disk.sh; a profile that declares dry_run has no
            raw dd / fwup / uuu write outside the library's write choke point
            (avocado_safe_disk_write / avocado_safe_disk_run), a profile that does
            not declare it refuses dry run through avocado_safe_disk_modes
  engine    the Jetson tegraflash shim; the Python engine owns the dry run
  exempt    a protocol writer (fastboot, rkdeveloptool, qdl, dfu-util, serial,
            astra-update) outside this change; carries a reason that names both
            front doors
  nonwriter builds an image file or does nothing to a target

The checker is a plain function over (entries, table, read) so the negative
tests can hand it synthetic tables and prove it fails.
"""

import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

# The two places a dry run of an exempt writer is refused before stone starts:
# avocado provision (check 6.2b) and the launcher (7.2).
DOORS = ("avocado provision", "avocado-flash launcher")

LIBRARY = "avocado-safe-disk.sh"

_LAYER = "meta-avocado-"


def _rel(p):
    return str(Path(p).relative_to(ROOT))


def find_script(manifest, name):
    """Locate the script a profile names inside the manifest's layer stone tree."""
    board = manifest.stem[len("stone-") :]
    base = manifest.parent
    hits = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in ("tests", "node_modules")]
        if name in filenames:
            hits.append(Path(dirpath) / name)
    named = [h for h in hits if h.parent.name == board]
    if named:
        hits = named
    if len(hits) != 1:
        raise AssertionError(
            f"{_rel(manifest)}: script {name} resolves to {len(hits)} files: "
            f"{[_rel(h) for h in hits]}"
        )
    return _rel(hits[0])


def enumerate_entries():
    entries = []
    for manifest in sorted(ROOT.glob("meta-avocado-*/stone/stone-*.json")):
        data = json.loads(manifest.read_text())
        profiles = data.get("provision", {}).get("profiles", {})
        for profile, spec in profiles.items():
            entries.append(
                {
                    "manifest": _rel(manifest),
                    "profile": profile,
                    "script": find_script(manifest, spec["script"]),
                    "dry_run": bool(spec.get("config", {}).get("dry_run", False)),
                }
            )
    return entries


def _reason(tool):
    return (
        f"{tool}; a protocol writer outside this change that never reads "
        "AVOCADO_PROVISION_DRY_RUN. Its profile declares no dry_run, so "
        "'avocado provision' (check 6.2b) and the 'avocado-flash launcher' (7.2) "
        "refuse its dry run before stone starts"
    )


_STONE_DIRS = {
    "alif": "meta-avocado-alif/stone/alif-e8-devkit",
    "imx": "meta-avocado-nxp/stone/avocado-imx",
    "rpi": "meta-avocado-raspberrypi/stone/rpi",
    "rzv2n": "meta-avocado-renesas/stone/rzv2n-sr-som",
    "nanopi": "meta-avocado-rockchip/stone/nanopi-r5s",
    "opi5": "meta-avocado-rockchip/stone/orangepi-5-plus",
    "stm": "meta-avocado-stm/stone/stm32mp25-dk",
    "syna": "meta-avocado-synaptics/stone/avocado",
    "rb3": "meta-avocado-qcom/stone/rb3gen2",
    "rubik": "meta-avocado-qcom/stone/rubikpi3",
    "amd": "meta-avocado-amd-x86-64/stone/amd-x86-64-v4",
    "arm64": "meta-avocado-arm64/stone/arm64-uefi-v9",
    "i2": "meta-avocado-x86-64/stone/intel-x86-64-v2",
    "i3": "meta-avocado-x86-64/stone/intel-x86-64-v3",
    "i4": "meta-avocado-x86-64/stone/intel-x86-64-v4",
    "qa": "meta-avocado-qemu/stone/qemuarm64",
    "qx": "meta-avocado-qemu/stone/qemux86-64",
    "tegra": "meta-avocado-nvidia/stone/tegra",
}


def _p(key, name):
    return f"{_STONE_DIRS[key]}/{name}"


# A library entry may allow a raw write line the scan would flag, keyed by a
# substring of that line with the reason it is not a target write. The scan
# reports an allow that matches no line, so an allow cannot go stale.
_ARCHIVE_TO_FILE = (
    '-d "${archive_image}"',
    "converts the fwup archive into an image file under the build dir, not a device",
)
_UUU_AFTER_DRY = (
    'uuu -v -m "$usb_path" "$uuu_script"',
    "real run only: the dry-run branch above prints this same command line through "
    "avocado_safe_disk_write and exits before reaching it",
)

CLASSIFICATION = {
    # library-covered block-device writers
    _p("alif", "stone-provision-sd.sh"): ("library", ()),
    _p("rzv2n", "stone-provision-sd.sh"): ("library", ()),
    _p("nanopi", "stone-provision-sd.sh"): ("library", ()),
    _p("nanopi", "stone-provision-ums.sh"): ("library", ()),
    _p("opi5", "stone-provision-sd.sh"): ("library", ()),
    _p("stm", "stone-provision-sd.sh"): ("library", ()),
    _p("imx", "stone-provision-sd.sh"): ("library", (_ARCHIVE_TO_FILE,)),
    _p("imx", "stone-provision-ums.sh"): ("library", ()),
    _p("imx", "stone-provision-uuu-emmc.sh"): (
        "library",
        (_ARCHIVE_TO_FILE, _UUU_AFTER_DRY),
    ),
    _p("rpi", "stone-provision-sd.sh"): ("library", (_ARCHIVE_TO_FILE,)),
    _p("rpi", "stone-provision-usb.sh"): ("library", ()),
    _p("amd", "stone-provision-usb.sh"): ("library", ()),
    _p("arm64", "stone-provision-usb.sh"): ("library", ()),
    _p("i2", "stone-provision-usb.sh"): ("library", ()),
    _p("i3", "stone-provision-usb.sh"): ("library", ()),
    _p("i4", "stone-provision-usb.sh"): ("library", ()),
    # the Jetson tegraflash engine owns its dry run
    _p("tegra", "stone-provision-tegraflash.sh"): ("engine", ()),
    # non-writers: build an image file or leave the target alone
    **{
        _p(k, "stone-provision-img.sh"): ("nonwriter", "builds an image file only")
        for k in (
            "alif",
            "imx",
            "rpi",
            "nanopi",
            "opi5",
            "syna",
            "amd",
            "arm64",
            "i2",
            "i3",
            "i4",
            "qa",
            "qx",
        )
    },
    _p("tegra", "stone-provision-noop.sh"): ("nonwriter", "does nothing"),
    _p("rb3", "stone-provision-noop.sh"): ("nonwriter", "does nothing"),
    _p("rubik", "stone-provision-noop.sh"): ("nonwriter", "does nothing"),
    _p("qa", "stone-provision-direct.sh"): ("nonwriter", "boots the image in qemu"),
    _p("qx", "stone-provision-direct.sh"): ("nonwriter", "boots the image in qemu"),
    _p("syna", "stone-provision-synaimg.sh"): (
        "nonwriter",
        "builds SYNAIMG files only",
    ),
    # protocol writers outside this change
    _p("alif", "stone-provision-serial.sh"): ("exempt", _reason("serial download")),
    _p("rzv2n", "stone-provision-serial.sh"): ("exempt", _reason("serial download")),
    _p("stm", "stone-provision-serial.sh"): (
        "exempt",
        _reason("dfu-util serial download"),
    ),
    _p("rzv2n", "stone-provision-emmc.sh"): (
        "exempt",
        _reason("fastboot flash over USB-OTG"),
    ),
    _p("stm", "stone-provision-emmc.sh"): (
        "exempt",
        _reason("fastboot flash over USB-OTG"),
    ),
    _p("nanopi", "stone-provision-emmc.sh"): (
        "exempt",
        _reason("rkdeveloptool MaskROM write"),
    ),
    _p("opi5", "stone-provision-emmc.sh"): (
        "exempt",
        _reason("rkdeveloptool MaskROM write"),
    ),
    _p("rb3", "stone-provision-ufs.sh"): ("exempt", _reason("qdl EDL flash")),
    _p("rubik", "stone-provision-ufs.sh"): ("exempt", _reason("qdl EDL flash")),
    _p("syna", "stone-provision-usb-emmc.sh"): (
        "exempt",
        _reason("astra-update USB eMMC write"),
    ),
}

_WRITE_TOOLS = re.compile(
    r"(?<![\w./-])(fastboot|rkdeveloptool|qdl|dfu-util|astra-update)\b"
)
_CHOKE = re.compile(
    r"avocado_safe_disk_(write|run)\s+(timeout\s+\d+\s+)?(dd|fwup|uuu)\b"
)
_RAW_DD = re.compile(r"(?<![\w./-])dd\s[^|;]*\bof=(?!/dev/null\b)")
_RAW_FWUP_APPLY = re.compile(r"(?<![\w./-])fwup\s[^|;]*-a\b")
_RAW_UUU = re.compile(r"(?<![\w./-])uuu\s+-v\b")
_MODES = re.compile(r"^\s*avocado_safe_disk_modes\s+(\S+)\s+([01])\s+([01])\b", re.M)


def code_lines(text):
    """Logical lines with continuations joined, minus comments, echo and printf."""
    joined = re.sub(r"\\\n\s*", " ", text)
    out = []
    for line in joined.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or re.match(r"(echo|printf)\b", s):
            continue
        out.append(s)
    return out


def sources_library(text):
    return any(
        LIBRARY in ln and re.search(r"(^|\s)(\.|source)\s", ln)
        for ln in code_lines(text)
    )


def modes_call(text):
    m = _MODES.search(text)
    return (m.group(1), m.group(2) == "1", m.group(3) == "1") if m else None


def raw_writes(text, allows):
    """Raw dd/fwup/uuu write lines outside the choke point, and unused allows."""
    flagged, used = [], set()
    for ln in code_lines(text):
        if _CHOKE.search(ln):
            continue
        if _RAW_DD.search(ln) or _RAW_FWUP_APPLY.search(ln) or _RAW_UUU.search(ln):
            hit = next((a for a in allows if a[0] in ln), None)
            if hit:
                used.add(hit[0])
            else:
                flagged.append(ln)
    unused = [a[0] for a in allows if a[0] not in used]
    return flagged, unused


def check_writers(entries, table, read, doors=DOORS):
    """Return failure strings; empty means every entry is accounted for."""
    fails = []
    seen = set()
    by_script = {}
    for e in entries:
        by_script.setdefault(e["script"], []).append(e)
    for e in entries:
        who = f"{e['manifest']} profile {e['profile']} script {e['script']}"
        cls = table.get(e["script"])
        if cls is None:
            fails.append(f"unclassified writer: {who}")
            continue
        seen.add(e["script"])
        kind = cls[0]
        text = read(e["script"])
        if text is None:
            fails.append(f"stale exemption: {who} names a script that does not exist")
            continue
        if kind == "library":
            if not sources_library(text):
                fails.append(
                    f"stale classification: {who} is library-covered but does not source {LIBRARY}"
                )
            elif modes_call(text) is None:
                fails.append(f"library script without avocado_safe_disk_modes: {who}")
            else:
                _, dry_ok, _ = modes_call(text)
                if e["dry_run"] and not dry_ok:
                    fails.append(
                        f"profile declares dry_run but its script refuses it: {who}"
                    )
                if not e["dry_run"] and dry_ok:
                    fails.append(
                        f"script supports dry_run but its profile does not declare it: {who}"
                    )
                if e["dry_run"]:
                    flagged, _ = raw_writes(text, cls[1])
                    for ln in flagged:
                        fails.append(f"raw write outside the choke point: {who}: {ln}")
        elif kind == "engine":
            if not e["dry_run"]:
                fails.append(f"engine profile does not declare dry_run: {who}")
        elif kind == "exempt":
            reason = cls[1]
            if not reason or not reason.strip():
                fails.append(f"exempt writer with an empty reason: {who}")
            else:
                missing = [d for d in doors if d not in reason]
                if missing:
                    fails.append(
                        f"exempt writer reason names no front door {missing}: {who}"
                    )
            if e["dry_run"]:
                fails.append(f"exempt protocol writer declares dry_run: {who}")
            if sources_library(text):
                fails.append(f"stale exemption: {who} now sources {LIBRARY}")
            if "AVOCADO_PROVISION_DRY_RUN" in text:
                fails.append(f"exempt writer reads AVOCADO_PROVISION_DRY_RUN: {who}")
        elif kind == "nonwriter":
            if sources_library(text) or any(
                _WRITE_TOOLS.search(ln) for ln in code_lines(text)
            ):
                fails.append(
                    f"stale classification: {who} is a non-writer but sources the library or runs a protocol writer"
                )
        else:
            fails.append(f"unknown kind {kind!r}: {who}")
    for script in table:
        if script not in seen:
            fails.append(f"stale exemption: table entry {script} matches no profile")
    for script, cls in table.items():
        if cls[0] == "library" and script in by_script:
            text = read(script)
            if text and any(e["dry_run"] for e in by_script[script]):
                _, unused = raw_writes(text, cls[1])
                for a in unused:
                    fails.append(
                        f"stale allow {a!r} in {script}: matches no raw write line"
                    )
    return fails


def _read(rel):
    p = ROOT / rel
    return p.read_text() if p.is_file() else None


@pytest.fixture(scope="module")
def entries():
    return enumerate_entries()


def test_enumeration_finds_profiles(entries):
    assert len({e["manifest"] for e in entries}) >= 30
    assert len(entries) >= 100


def test_every_manifest_script_is_classified(entries):
    fails = check_writers(entries, CLASSIFICATION, _read)
    assert not fails, "\n".join(fails)


# --- the checker itself, against synthetic inputs ------------------------------

_LIB_SD = (
    "#!/bin/bash\n. ./avocado-safe-disk.sh\n"
    "avocado_safe_disk_modes sd 1 0 || exit 1\n"
    'avocado_safe_disk_write dd if="$i" of="$t"\n'
)


def _e(script="x/a.sh", dry_run=True, profile="sd"):
    return {
        "manifest": "m/stone-b.json",
        "profile": profile,
        "script": script,
        "dry_run": dry_run,
    }


def _run(entry, table, text):
    return check_writers([entry], table, lambda rel: text)


def test_checker_passes_a_clean_library_writer():
    assert _run(_e(), {"x/a.sh": ("library", ())}, _LIB_SD) == []


def test_checker_flags_an_unclassified_writer_naming_manifest_profile_script():
    fails = _run(_e(), {}, _LIB_SD)
    assert fails == ["unclassified writer: m/stone-b.json profile sd script x/a.sh"]


def test_checker_flags_a_dd_writer_not_sourcing_the_library():
    text = "#!/bin/bash\ndd if=a of=/dev/sdb\n"
    fails = _run(_e(), {"x/a.sh": ("library", ())}, text)
    assert any("does not source" in f and "x/a.sh" in f for f in fails)


def test_checker_flags_a_raw_dd_outside_the_choke_point():
    text = _LIB_SD + 'dd if="$i" of="$t" bs=4M\n'
    fails = _run(_e(), {"x/a.sh": ("library", ())}, text)
    assert any("raw write outside the choke point" in f for f in fails)


def test_checker_flags_raw_fwup_apply_and_raw_uuu():
    for raw in ('fwup -a -i a -d "$dev" -t complete', "uuu -v -m 1 s"):
        fails = _run(_e(), {"x/a.sh": ("library", ())}, _LIB_SD + raw + "\n")
        assert any("raw write outside the choke point" in f for f in fails), raw


def test_checker_allows_a_dd_read_probe_to_dev_null():
    text = _LIB_SD + 'dd if="$d" of=/dev/null bs=512 count=1\n'
    assert _run(_e(), {"x/a.sh": ("library", ())}, text) == []


def test_checker_flags_an_empty_reason():
    for reason in ("", "   ", None):
        fails = _run(
            _e(dry_run=False), {"x/a.sh": ("exempt", reason)}, "fastboot flash\n"
        )
        assert any("empty reason" in f for f in fails), reason


def test_checker_flags_a_reason_naming_no_front_door():
    fails = _run(
        _e(dry_run=False), {"x/a.sh": ("exempt", "fastboot writer")}, "fastboot flash\n"
    )
    assert any("names no front door" in f for f in fails)
    only_one = "refused by avocado provision only"
    fails = _run(
        _e(dry_run=False), {"x/a.sh": ("exempt", only_one)}, "fastboot flash\n"
    )
    assert any("avocado-flash launcher" in f for f in fails)


def test_checker_flags_an_exempt_writer_whose_profile_declares_dry_run():
    fails = _run(
        _e(dry_run=True),
        {"x/a.sh": ("exempt", _reason("fastboot"))},
        "fastboot flash\n",
    )
    assert any(
        "declares dry_run" in f and "m/stone-b.json" in f and "x/a.sh" in f
        for f in fails
    )


def test_checker_flags_an_exempt_writer_that_reads_the_variable():
    text = 'fastboot flash\n[ "$AVOCADO_PROVISION_DRY_RUN" = 1 ]\n'
    fails = _run(_e(dry_run=False), {"x/a.sh": ("exempt", _reason("fastboot"))}, text)
    assert any("reads AVOCADO_PROVISION_DRY_RUN" in f for f in fails)


def test_checker_flags_a_stale_exemption_for_a_script_now_sourcing_the_library():
    fails = _run(
        _e(dry_run=False), {"x/a.sh": ("exempt", _reason("fastboot"))}, _LIB_SD
    )
    assert any("stale exemption" in f and "now sources" in f for f in fails)


def test_checker_flags_a_stale_exemption_for_a_script_that_no_longer_exists():
    fails = check_writers(
        [_e(dry_run=False)], {"x/a.sh": ("exempt", _reason("fastboot"))}, lambda r: None
    )
    assert any("stale exemption" in f and "does not exist" in f for f in fails)


def test_checker_flags_a_table_entry_matching_no_profile():
    fails = check_writers(
        [], {"x/gone.sh": ("exempt", _reason("fastboot"))}, lambda r: ""
    )
    assert fails == ["stale exemption: table entry x/gone.sh matches no profile"]


def test_checker_flags_an_allow_that_matches_no_line():
    table = {"x/a.sh": ("library", (("no such line", "r"),))}
    fails = _run(_e(), table, _LIB_SD)
    assert any("stale allow" in f for f in fails)


def test_checker_flags_dry_run_declaration_disagreeing_with_the_script():
    refusing = _LIB_SD.replace("sd 1 0", "usb 0 0")
    fails = _run(_e(dry_run=True), {"x/a.sh": ("library", ())}, refusing)
    assert any("declares dry_run but its script refuses" in f for f in fails)
    fails = _run(_e(dry_run=False), {"x/a.sh": ("library", ())}, _LIB_SD)
    assert any("supports dry_run but its profile does not declare" in f for f in fails)


def test_checker_flags_a_nonwriter_that_runs_a_protocol_writer():
    fails = _run(
        _e(dry_run=False), {"x/a.sh": ("nonwriter", "image")}, "fastboot flash gpt x\n"
    )
    assert any("non-writer" in f for f in fails)


def test_every_exempt_reason_in_the_table_names_both_doors():
    for script, cls in CLASSIFICATION.items():
        if cls[0] == "exempt":
            for door in DOORS:
                assert door in cls[1], f"{script}: reason omits {door!r}"
