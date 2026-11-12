"""Contract between the engine's declared manifest keys and the template.

The wrapper builds its inputs from the template, so a key the engine reads
that the template does not define would surface only on hardware. These
checks carry over the retired script contract test, one counterpart per case,
and each is proven on a mutated copy so it can fail.

"Read" for an optional key means the engine has somewhere to put it: a
Manifest field of that name, filled by read_manifest. A KEYS entry with no
such field is declared but never read, and its optional flag would hide a
template break.
"""

import ast
import dataclasses
import json
import pathlib
import re

from avocado_tegraflash.manifest import KEYS, Key, Manifest, read_manifest

TEGRA = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = TEGRA.parent / "stone-jetson-orin-nano.json"
ORACLE = TEGRA / "tests" / "parity" / "legacy" / "stone-provision-tegraflash.sh"

_JQ_READ = re.compile(r"jq\s+-r\s+'\.storage_devices\.rootdisk\.(images|tegraflash)\.([A-Za-z0-9_]+)")


def template_doc():
    return json.loads(TEMPLATE.read_text())


def check_contract(keys, doc):
    """Return sorted 'section.name' of non-optional keys the template lacks."""
    rootdisk = doc["storage_devices"]["rootdisk"]
    missing = []
    for key in keys:
        section = rootdisk.get(key.section)
        if not key.optional and (not isinstance(section, dict) or key.name not in section):
            missing.append(f"{key.section}.{key.name}")
    return sorted(missing)


def unread_optional(keys, fields):
    """Return optional keys with no Manifest field of that name."""
    return sorted(f"{k.section}.{k.name}" for k in keys if k.optional and k.name not in fields)


def manifest_fields():
    return {f.name for f in dataclasses.fields(Manifest)}


def test_extraction_finds_the_known_oracle_reads():
    reads = {(m.group(1), m.group(2)) for m in _JQ_READ.finditer(ORACLE.read_text())}
    assert {("images", "rootfs"), ("images", "tegraflash_bsp"), ("tegraflash", "sd_device"), ("tegraflash", "overlays")} <= reads


# Keys the engine reads that the frozen oracle script never did.
ENGINE_ONLY_KEYS = {("tegraflash", "rcm_ids")}

# The Orin Nano template (TEMPLATE) deliberately defines rcm_ids: 7523 was seen on
# the bench and it is the only id declared; every other optional key stays undefined.
DEFINED_IN_TEMPLATE = {("tegraflash", "rcm_ids")}


def oracle_reads():
    return {(m.group(1), m.group(2)) for m in _JQ_READ.finditer(ORACLE.read_text())}


def key_set_differences(keys):
    """Declared keys nobody allowed, and allowed keys nobody declared."""
    declared = {(k.section, k.name) for k in keys}
    allowed = oracle_reads() | ENGINE_ONLY_KEYS
    return sorted(declared - allowed), sorted(allowed - declared)


def test_keys_are_exactly_the_keys_the_oracle_reads():
    assert key_set_differences(KEYS) == ([], [])


def test_an_undeclared_extra_key_still_fails_the_exact_set_check():
    mutated = KEYS + (Key("images", "invented_key", True, "test"),)
    assert key_set_differences(mutated) == ([("images", "invented_key")], [])


def test_every_declared_key_is_defined_or_optional():
    assert check_contract(KEYS, template_doc()) == []


def test_optional_keys_are_really_undefined_in_the_template():
    # A stale optional flag on a key the template now defines would mask a future break.
    rootdisk = template_doc()["storage_devices"]["rootdisk"]
    for key in KEYS:
        if key.optional and (key.section, key.name) not in DEFINED_IN_TEMPLATE:
            assert key.name not in rootdisk[key.section]


def test_every_optional_key_is_read():
    assert unread_optional(KEYS, manifest_fields()) == []


def test_every_key_declares_a_known_section():
    assert {k.section for k in KEYS} == {"images", "tegraflash"}


def test_added_non_optional_key_absent_from_template_fails_naming_it():
    mutated = KEYS + (Key("images", "invented_key", False, ""),)
    assert check_contract(mutated, template_doc()) == ["images.invented_key"]


def test_added_optional_key_absent_from_template_does_not_fail_the_template_check():
    mutated = KEYS + (Key("images", "invented_key", True, "test"),)
    assert check_contract(mutated, template_doc()) == []


def test_renamed_template_rootfs_key_fails_naming_it():
    doc = template_doc()
    images = doc["storage_devices"]["rootdisk"]["images"]
    images["root_fs"] = images.pop("rootfs")
    assert check_contract(KEYS, doc) == ["images.rootfs"]


def test_removed_template_key_fails_naming_it():
    doc = template_doc()
    del doc["storage_devices"]["rootdisk"]["tegraflash"]["sd_device"]
    assert check_contract(KEYS, doc) == ["tegraflash.sd_device"]


def test_missing_section_fails_every_key_of_that_section():
    doc = template_doc()
    del doc["storage_devices"]["rootdisk"]["tegraflash"]
    assert check_contract(KEYS, doc) == ["tegraflash.sd_device"]


def test_optional_key_with_no_manifest_field_is_detected_as_never_read():
    mutated = KEYS + (Key("images", "orphan", True, "test"),)
    assert unread_optional(mutated, manifest_fields()) == ["images.orphan"]


def test_optional_key_with_a_manifest_field_passes():
    assert unread_optional(KEYS, manifest_fields() | {"orphan"}) == []


def test_template_reads_without_defaulting_any_required_value(tmp_path):
    m = read_manifest(TEMPLATE)
    required = [k.name for k in KEYS if not k.optional]
    assert all(getattr(m, name) for name in required)


# ---- reads: only manifest.py parses the manifest ------------------------


def _engine_sources():
    pkg = TEGRA / "avocado_tegraflash"
    return {p.name: ast.parse(p.read_text()) for p in sorted(pkg.glob("*.py"))}


def _imports_json(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "json" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "json":
            return True
    return False


def _manifest_path_uses(tree):
    """Each `.manifest` attribute with the node that holds it."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    return [(n, parents[n]) for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "manifest"]


def test_only_manifest_py_imports_json():
    assert [name for name, tree in _engine_sources().items() if _imports_json(tree)] == ["manifest.py"]


def test_the_manifest_path_is_only_printed_and_handed_to_read_manifest_outside_manifest_py():
    uses = {name: _manifest_path_uses(tree) for name, tree in _engine_sources().items() if name != "manifest.py"}
    assert {name for name, found in uses.items() if found} == {"cli.py"}
    for node, parent in uses["cli.py"]:
        handed_over = isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id == "read_manifest"
        assert handed_over or isinstance(parent, ast.FormattedValue), ast.dump(parent)


def test_json_scan_catches_a_module_that_parses_the_manifest_itself():
    assert _imports_json(ast.parse("import json\n")) and _imports_json(ast.parse("from json import loads\n"))
    assert not _imports_json(ast.parse("import jsonschema_free\n"))


def test_manifest_path_scan_catches_a_direct_open_of_the_manifest():
    (node, parent), = _manifest_path_uses(ast.parse("open(cfg.manifest)\n"))
    assert not (isinstance(parent, ast.Call) and getattr(parent.func, "id", "") == "read_manifest")


def test_the_orin_nano_manifest_pins_only_the_bench_observed_recovery_id():
    assert read_manifest(TEMPLATE).rcm_ids == ("0955:7523",)


def test_every_stone_manifest_reads_with_valid_nvidia_rcm_ids():
    # A board gains rcm_ids when someone observes one on hardware, so this checks
    # the contract (readable, NVIDIA vendor), not which boards carry ids today.
    paths = sorted(TEMPLATE.parent.glob("stone-*.json"))
    assert len(paths) >= 7
    for path in paths:
        ids = read_manifest(path).rcm_ids
        assert all(re.fullmatch(r"0955:[0-9a-f]{4}", i) for i in ids), path.name
