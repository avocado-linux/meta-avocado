"""Partition fit check against the staged layout."""

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.fit import require_fit
from avocado_tegraflash.manifest import Manifest


def layout(app="8192", esp="4096", extra=""):
    parts = ""
    if app is not None:
        parts += f'<partition name="APP" type="data"><size>{app}</size></partition>\n'
    if esp is not None:
        parts += f'<partition name="esp" type="data"><size>{esp}</size></partition>\n'
    return f'<?xml version="1.0"?>\n<partition_layout>\n<device>\n{parts}{extra}</device>\n</partition_layout>\n'


def stage(tmp_path, xml=None, rootfs=4096, esp=2048, name="rootfs.img"):
    if xml is not None:
        data = xml if isinstance(xml, bytes) else xml.encode()
        (tmp_path / "external-flash.xml.in").write_bytes(data)
    if rootfs is not None:
        (tmp_path / name).write_bytes(b"\0" * rootfs)
    if esp is not None:
        (tmp_path / "esp.img").write_bytes(b"\0" * esp)
    return Manifest(rootfs=f"images/{name}", tegraflash_esp="esp.bin")


def run(tmp_path, manifest):
    logs = []
    require_fit(tmp_path, manifest, logs.append)
    return logs


def refusal(tmp_path, manifest):
    with pytest.raises(EngineError) as exc:
        run(tmp_path, manifest)
    return str(exc.value)


def test_pass_logs_one_line_per_pair(tmp_path):
    m = stage(tmp_path, layout())
    assert run(tmp_path, m) == ["fit: rootfs 4096 <= APP 8192", "fit: tegraflash_esp 2048 <= esp 4096"]


def test_exact_fit_passes(tmp_path):
    m = stage(tmp_path, layout(app="4096", esp="2048"))
    assert len(run(tmp_path, m)) == 2


def test_one_byte_over_refused_with_names_and_sizes(tmp_path):
    m = stage(tmp_path, layout(app="4095"))
    msg = refusal(tmp_path, m)
    assert "rootfs image rootfs.img (4096 bytes) does not fit partition APP (4095 bytes)" in msg


def test_emmc_shaped_layout_same_file_name(tmp_path):
    m = stage(tmp_path, layout(extra='<partition name="other"><size>1</size></partition>\n'), name="rootfs.ext4")
    assert run(tmp_path, m)[0] == "fit: rootfs 4096 <= APP 8192"


def test_hex_size_parsed(tmp_path):
    m = stage(tmp_path, layout(app="0x2000"))
    assert run(tmp_path, m)[0] == "fit: rootfs 4096 <= APP 8192"


def test_unparseable_layout_refused(tmp_path):
    m = stage(tmp_path, "<partition_layout><oops>")
    assert "unreadable" in refusal(tmp_path, m)


def test_doctype_refused(tmp_path):
    m = stage(tmp_path, '<!DOCTYPE x [<!ELEMENT x ANY>]>\n' + layout())
    assert "DOCTYPE or entity" in refusal(tmp_path, m)


def test_entity_refused(tmp_path):
    m = stage(tmp_path, layout(extra='<!ENTITY a "b">'))
    assert "DOCTYPE or entity" in refusal(tmp_path, m)


def test_utf16_refused(tmp_path):
    m = stage(tmp_path, layout().encode("utf-16"))
    assert "UTF-16" in refusal(tmp_path, m)


def test_oversize_layout_refused(tmp_path):
    m = stage(tmp_path, layout(extra="<!-- " + "x" * (4 * 1024 * 1024) + " -->"))
    assert "larger than" in refusal(tmp_path, m)


def test_duplicate_app_refused(tmp_path):
    m = stage(tmp_path, layout(extra='<partition name="APP"><size>1</size></partition>\n'))
    assert "partition APP is listed more than once" in refusal(tmp_path, m)


def test_absent_esp_refused(tmp_path):
    m = stage(tmp_path, layout(esp=None))
    assert "partition esp is absent" in refusal(tmp_path, m)


def test_non_numeric_size_refused(tmp_path):
    m = stage(tmp_path, layout(app="big"))
    assert "'big', not a number" in refusal(tmp_path, m)


def test_absent_layout_file_refused_naming_it(tmp_path):
    m = stage(tmp_path, None)
    assert "external-flash.xml.in is absent" in refusal(tmp_path, m)


def test_unnamed_image_skipped(tmp_path):
    stage(tmp_path, layout(esp=None))
    m = Manifest(rootfs="images/rootfs.img")
    assert run(tmp_path, m) == ["fit: rootfs 4096 <= APP 8192"]


def test_several_problems_in_one_error(tmp_path):
    m = stage(tmp_path, layout(app="10", esp="20"))
    msg = refusal(tmp_path, m)
    assert "partition APP (10 bytes)" in msg and "partition esp (20 bytes)" in msg


def test_nothing_logged_when_refused(tmp_path):
    m = stage(tmp_path, layout(app="10"))
    logs = []
    with pytest.raises(EngineError):
        require_fit(tmp_path, m, logs.append)
    assert logs == []
