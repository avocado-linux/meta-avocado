"""PARTUUID pins: generation, command line, and the layout the GPT is written from.

Ports tests/test-rootfs-partuuid-pin.sh case by case.
"""

import hashlib
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from avocado_tegraflash import EngineError, partuuid

A = "11111111-2222-4333-8444-555555555555"
B = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
PINS = (A, B)

NV = Path(__file__).resolve().parents[3]
HELPERS = NV / "recipes-bsp/tegra-binaries/tegra-helper-scripts"
LAYOUTS = NV / "recipes-bsp/tegra-binaries/tegra-storage-layout"
LAYOUT_NAMES = ["external-flash.xml", "internal-flash-emmc.xml"]

# The fill tegraflash-bsp.bb's process_flash_xml applies, with small sizes,
# leaving APPUUID/APPUUID_b for provisioning.
_FILL = [
    ("LNXFILE_b", "boot.img"),
    ("LNXFILE", "boot.img"),
    ("LNXSIZE", "67108864"),
    ("APPSIZE", "67108864"),
    ("EXT_NUM_SECTORS", "4194304"),
    ("INT_NUM_SECTORS", "4194304"),
    ("RECNAME", "recovery"),
    ("RECSIZE", "1048576"),
    ("RECDTB-NAME", "recovery-dtb"),
    ("ESP_FILE", "esp.img"),
]


def filled_layout(name: str) -> str:
    lines = []
    for line in (LAYOUTS / name).read_text().splitlines(keepends=True):
        if "RECFILE" in line or "RECDTB-FILE" in line:
            continue
        for old, new in _FILL:
            line = line.replace(old, new)
        lines.append(line)
    return "".join(lines)


@pytest.fixture
def work(tmp_path):
    return tmp_path / "work"


def stage(work: Path, text: str) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    path = work / "external-flash.xml.in"
    path.write_text(text)
    return path


def guid_of(path: Path, name: str) -> str:
    for part in ET.parse(path).iter("partition"):
        if part.get("name") == name:
            guid = part.find("unique_guid")
            return "" if guid is None or guid.text is None else guid.text.strip()
    raise AssertionError(f"no partition {name}")


def reader(*values):
    it = iter(values)
    return lambda: next(it)


# ---- new_pins -----------------------------------------------------------


def test_new_pins_uppercases_the_kernel_uuid():
    pins = partuuid.new_pins(source=reader("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee\n", A.lower() + "\n"))
    assert pins == ("AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE", A)


def test_new_pins_default_source_yields_two_distinct_uppercase_uuids():
    a, b = partuuid.new_pins()
    pattern = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
    assert pattern.match(a) and pattern.match(b) and a != b


def test_new_pins_rereads_when_the_second_value_equals_the_first():
    pins = partuuid.new_pins(source=reader(A, A, B))
    assert pins == (A, B)


def test_new_pins_raises_when_the_source_never_yields_a_distinct_value():
    with pytest.raises(EngineError):
        partuuid.new_pins(source=lambda: A)


# ---- append_cmdline -----------------------------------------------------


def test_append_cmdline_with_nothing_existing_is_just_the_pins():
    assert partuuid.append_cmdline("", PINS) == (
        f"avocado.root_partuuid={A} avocado.root_partuuid_b={B}"
    )


def test_append_cmdline_appends_after_the_existing_extra_with_one_space():
    assert partuuid.append_cmdline("hugepages=2 console=ttyTCU0", PINS) == (
        f"hugepages=2 console=ttyTCU0 avocado.root_partuuid={A} avocado.root_partuuid_b={B}"
    )


# ---- apply_layout -------------------------------------------------------


@pytest.mark.parametrize("name", LAYOUT_NAMES)
def test_apply_layout_gives_app_slot_a_and_app_b_slot_b_with_no_placeholder_left(work, name):
    path = stage(work, filled_layout(name))
    partuuid.apply_layout(work, PINS)
    text = path.read_text()
    assert (guid_of(path, "APP"), guid_of(path, "APP_b"), "APPUUID" in text) == (A, B, False)


def test_apply_layout_counts_slot_a_per_line_like_grep_so_a_line_ending_placeholder_is_not_enough(work):
    stage(work, "<g>APPUUID_b</g>\n<h>APPUUID\n")
    with pytest.raises(EngineError, match=r"APPUUID\[\^_\]"):
        partuuid.apply_layout(work, PINS)


def test_apply_layout_writes_exactly_the_sed_result(work):
    text = "x APPUUID_b y\n  <unique_guid> APPUUID </unique_guid>\nno newline"
    path = stage(work, text)
    partuuid.apply_layout(work, PINS)
    assert path.read_text() == f"x {B} y\n  <unique_guid> {A} </unique_guid>\nno newline"


def test_apply_layout_rejects_a_layout_missing_only_the_slot_a_placeholder(work):
    text = filled_layout("external-flash.xml").replace("<unique_guid> APPUUID </unique_guid>", "<unique_guid> </unique_guid>")
    assert "APPUUID_b" in text and "APPUUID " not in text
    stage(work, text)
    with pytest.raises(EngineError, match=r"APPUUID\[\^_\]"):
        partuuid.apply_layout(work, PINS)


def test_apply_layout_rejects_a_layout_holding_only_slot_b_even_at_end_of_file(work):
    stage(work, "<g>APPUUID_b</g>")
    with pytest.raises(EngineError, match=r"APPUUID\[\^_\]"):
        partuuid.apply_layout(work, PINS)


def test_apply_layout_rejects_a_layout_missing_the_slot_b_placeholder(work):
    text = filled_layout("external-flash.xml").replace("APPUUID_b", "")
    stage(work, text)
    with pytest.raises(EngineError, match="APPUUID_b"):
        partuuid.apply_layout(work, PINS)


@pytest.mark.deviation("layout-placeholder-unique")
@pytest.mark.parametrize(
    "text, label",
    [
        ("<g>APPUUID_b</g>\n<h>APPUUID </h>\n<i>APPUUID </i>\n", "has 2 APPUUID placeholders"),
        ("<g>APPUUID_b</g>\n<g>APPUUID_bb</g>\n<h>APPUUID </h>\n", "APPUUID_b"),
        ("<g>APPUUID_b</g>\n<g>APPUUID_b</g>\n<h>APPUUID </h>\n", "APPUUID_b"),
    ],
)
def test_apply_layout_refuses_a_repeated_placeholder_and_leaves_the_file_alone(work, text, label):
    path = stage(work, text)
    with pytest.raises(EngineError, match=label):
        partuuid.apply_layout(work, PINS)
    assert path.read_text() == text


@pytest.mark.parametrize("name", LAYOUT_NAMES)
def test_the_stock_layouts_hold_each_placeholder_once(name):
    text = filled_layout(name)
    assert (text.count("APPUUID_b"), len(re.findall(r"APPUUID(?!_)", text))) == (1, 1)


def test_apply_layout_leaves_the_layout_untouched_when_a_placeholder_is_missing(work):
    text = "<g>APPUUID</g>"
    path = stage(work, text)
    with pytest.raises(EngineError):
        partuuid.apply_layout(work, PINS)
    assert path.read_text() == text


def test_apply_layout_refuses_when_the_layout_file_is_absent(work):
    work.mkdir()
    with pytest.raises(EngineError, match="external-flash.xml.in not found"):
        partuuid.apply_layout(work, PINS)


def test_apply_layout_raises_when_a_placeholder_survives_substitution(work):
    stage(work, "APPUUID_b APPUUID ")
    pins = ("APPUUIDX", B)  # a pin that reintroduces the placeholder
    with pytest.raises(EngineError, match="survived"):
        partuuid.apply_layout(work, pins)


# ---- blank_layout -------------------------------------------------------


def test_blank_layout_removes_both_placeholders_and_leaves_empty_guid_elements(work):
    path = stage(work, filled_layout("external-flash.xml"))
    partuuid.blank_layout(work)
    assert ("APPUUID" in path.read_text(), guid_of(path, "APP"), guid_of(path, "APP_b")) == (
        False,
        "",
        "",
    )


def test_blank_layout_without_a_layout_file_does_nothing(work):
    work.mkdir()
    partuuid.blank_layout(work)
    assert list(work.iterdir()) == []


# ---- the GPT, through nvflashxmlparse and make_partitions ---------------


# nvflashxmlparse.py ships with meta-tegra, not with this layer; point
# NVFLASHXMLPARSE at it when it is not beside make-sdcard.sh.
NVFLASHXMLPARSE = Path(os.environ.get("NVFLASHXMLPARSE") or HELPERS / "nvflashxmlparse.py")


@pytest.mark.skipif(
    not (shutil.which("sgdisk") and shutil.which("bash") and shutil.which("python3")),
    reason="sgdisk, bash or python3 not installed",
)
def test_gpt_carries_the_pinned_partuuids_for_app_and_app_b(work, tmp_path):
    if not NVFLASHXMLPARSE.is_file():
        # CI supplies the file; a silent skip there would hide the only GPT-level check.
        message = f"nvflashxmlparse.py not available at {NVFLASHXMLPARSE} (set NVFLASHXMLPARSE)"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    stage(work, filled_layout("external-flash.xml"))
    partuuid.apply_layout(work, PINS)
    mkparts = tmp_path / "mkparts.sh"
    out, in_func = [], False
    for line in (HELPERS / "make-sdcard.sh").read_text().splitlines():
        if re.match(r"^(find_finalpart|make_partitions)\(\) \{", line):
            in_func = True
        if in_func:
            out.append(line)
            if line == "}":
                in_func = False
    mkparts.write_text("\n".join(out) + "\n")
    disk = tmp_path / "disk.img"
    with open(disk, "wb") as fh:
        fh.truncate(2 * 1024**3)
    script = (
        '. "$1"; output="$2"; mapfile PARTS < <(python3 "$3" -t rootfs "$4"); '
        "find_finalpart && make_partitions"
    )
    log = tmp_path / "mk.out"
    with open(log, "wb") as fh:
        rc = subprocess.run(
            ["bash", "-c", script, "_", str(mkparts), str(disk), str(NVFLASHXMLPARSE),
             str(work / "external-flash.xml.in")],
            stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=False, timeout=120,
        ).returncode
    assert rc == 0, log.read_text()[-400:]

    def gpt_guid(label):
        listing = subprocess.run(["sgdisk", "-p", str(disk)], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
        for line in listing.splitlines():
            fields = line.split()
            if fields and fields[-1] == label and fields[0].isdigit():
                info = subprocess.run(["sgdisk", "-i", fields[0], str(disk)], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
                return next(l.split()[3] for l in info.splitlines() if "unique GUID" in l)
        raise AssertionError(f"no {label} in GPT")

    assert (gpt_guid("APP"), gpt_guid("APP_b")) == (A, B)


# ---- falsifiers: broken copies of the module must fail the contract -----


def test_falsifier_slot_a_check_dropped_accepts_a_line_ending_placeholder(tmp_path, mutant):
    mod = mutant("partuuid.py", '_SLOT_A = re.compile(r"APPUUID[^_]")', '_SLOT_A = re.compile(r"APPUUID")')
    layout = "<g>APPUUID_b</g>\n<h>APPUUID"
    path = stage(tmp_path / "w", layout)
    mod.apply_layout(tmp_path / "w", PINS)  # the mutant accepts it
    assert path.read_text() == f"<g>{B}</g>\n<h>{A}"
    # the real module refuses the same input
    stage(tmp_path / "w2", layout)
    with pytest.raises(EngineError):
        partuuid.apply_layout(tmp_path / "w2", PINS)


def test_falsifier_survivor_check_removed_lets_a_surviving_placeholder_through(tmp_path, mutant):
    mod = mutant("partuuid.py", 'if "APPUUID" in text:', "if False:")
    stage(tmp_path / "w", "APPUUID_b APPUUID ")
    mod.apply_layout(tmp_path / "w", ("APPUUIDX", B))  # the mutant does not raise
    stage(tmp_path / "w2", "APPUUID_b APPUUID ")
    with pytest.raises(EngineError):
        partuuid.apply_layout(tmp_path / "w2", ("APPUUIDX", B))


def test_falsifier_distinctness_check_removed_returns_equal_pins(tmp_path, mutant):
    mod = mutant("partuuid.py", "if b != a:", "if True:")
    assert mod.new_pins(source=reader(A, A)) == (A, A)
    assert partuuid.new_pins(source=reader(A, A, B)) == (A, B)


# ---- a symlinked layout is replaced, never written through ---------------


@pytest.mark.parametrize("fn", ["apply_layout", "blank_layout"])
def test_layout_symlink_is_replaced_and_the_staged_source_is_untouched(work, tmp_path, fn):
    outside = tmp_path / "outside.xml"
    outside.write_text(filled_layout("external-flash.xml"))
    before = hashlib.sha256(outside.read_bytes()).hexdigest()
    work.mkdir()
    link = work / "external-flash.xml.in"
    link.symlink_to(outside)
    args = (work, PINS) if fn == "apply_layout" else (work,)
    getattr(partuuid, fn)(*args)
    assert (
        hashlib.sha256(outside.read_bytes()).hexdigest() == before,
        link.is_symlink(),
        "APPUUID" in link.read_text(),
    ) == (True, False, False)


# ---- one codec policy: utf-8, surrogateescape, newline kept --------------

_RAW = b"<!-- caf\xe9 -->\r\n<g>APPUUID_b</g>\r\n<h>APPUUID </h>\r\n"


@pytest.mark.parametrize("fn", ["apply_layout", "blank_layout"])
def test_layout_with_a_non_utf8_byte_and_crlf_lines_keeps_every_other_byte(work, fn):
    work.mkdir()
    path = work / "external-flash.xml.in"
    path.write_bytes(_RAW)
    getattr(partuuid, fn)(*((work, PINS) if fn == "apply_layout" else (work,)))
    fill = (B, A) if fn == "apply_layout" else ("", "")
    assert path.read_bytes() == _RAW.replace(b"APPUUID_b", fill[0].encode()).replace(b"APPUUID", fill[1].encode())


def test_falsifier_strict_codec_read_fails_on_a_non_utf8_layout(tmp_path, mutant):
    mod = mutant(
        "files.py",
        'with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:\n        return fh.read()',
        "return Path(path).read_text(encoding='ascii')",
        module="partuuid",
    )
    work = tmp_path / "w"
    work.mkdir()
    (work / "external-flash.xml.in").write_bytes(_RAW)
    with pytest.raises(UnicodeDecodeError):
        mod.apply_layout(work, PINS)


def test_falsifier_count_check_removed_lets_a_repeated_placeholder_give_two_partitions_one_guid(tmp_path, mutant):
    mod = mutant("partuuid.py", "if count != 1:", "if False:")
    path = stage(tmp_path / "w", "<a>APPUUID_b</a><b>APPUUID_b</b><c>APPUUID </c>")
    mod.apply_layout(tmp_path / "w", PINS)  # the mutant fills both slot B placeholders
    assert path.read_text().count(B) == 2
