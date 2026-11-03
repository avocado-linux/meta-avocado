"""Contract between the provisioning script and the manifest template.

The wrapper builds its inputs from the template, so a key the script reads
that the template does not define would surface only on hardware. The check
works on text, so the tests run it on mutated copies to prove it can fail.
"""

import json
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "meta-avocado-nvidia" / "stone" / "tegra" / "stone-provision-tegraflash.sh"
TEMPLATE = REPO_ROOT / "meta-avocado-nvidia" / "stone" / "stone-jetson-orin-nano.json"

# Reads in the script are of the form
#   jq -r '.storage_devices.rootdisk.images.<key> // empty' ...
#   jq -r '.storage_devices.rootdisk.tegraflash.<key> // [] | join(",")' ...
# Only jq lines count; error-message text naming a key is not a read.
_JQ_READ = re.compile(
    r"jq\s+-r\s+'\.storage_devices\.rootdisk\.(images|tegraflash)\.([A-Za-z0-9_]+)"
)

# Keys the script reads as optional (// empty or // []) and this template
# leaves undefined. Each needs a reason.
OPTIONAL_UNDEFINED = {
    # The script falls back to the DTB baked into the BSP when no override
    # image is named, and the Orin Nano template ships none.
    ("images", "dtb"),
    # Same fallback for the BPMP device tree.
    ("images", "bpmp_dtb"),
    # Overlay lists are opt-in per carrier board; the stock template applies
    # none, and the script treats absence as an empty list.
    ("tegraflash", "overlays"),
    # Same as overlays, for the DCE device tree overlays.
    ("tegraflash", "dce_overlays"),
}


def extract_reads(script_text):
    """Return the set of (section, key) the script reads from the manifest."""
    return {(m.group(1), m.group(2)) for m in _JQ_READ.finditer(script_text)}


def check_contract(script_text, template_text, allowlist=OPTIONAL_UNDEFINED):
    """Return the sorted 'section.key' names read but not defined."""
    rootdisk = json.loads(template_text)["storage_devices"]["rootdisk"]
    missing = []
    for section, key in sorted(extract_reads(script_text)):
        if (section, key) in allowlist:
            continue
        defined = rootdisk.get(section)
        if not isinstance(defined, dict) or key not in defined:
            missing.append(f"{section}.{key}")
    return missing


def test_extraction_finds_the_known_reads():
    reads = extract_reads(SCRIPT.read_text())
    assert ("images", "rootfs") in reads
    assert ("images", "tegraflash_bsp") in reads
    assert ("tegraflash", "sd_device") in reads
    assert ("tegraflash", "overlays") in reads


def test_every_script_read_is_defined_or_allowlisted():
    assert check_contract(SCRIPT.read_text(), TEMPLATE.read_text()) == []


def test_allowlist_keys_are_really_read_and_really_undefined():
    # A stale allowlist entry would mask a future contract break.
    reads = extract_reads(SCRIPT.read_text())
    rootdisk = json.loads(TEMPLATE.read_text())["storage_devices"]["rootdisk"]
    for section, key in OPTIONAL_UNDEFINED:
        assert (section, key) in reads
        assert key not in rootdisk[section]


def test_invented_image_key_fails_naming_it():
    mutated = (
        SCRIPT.read_text()
        + "\nx=$(jq -r '.storage_devices.rootdisk.images.invented_key // empty' \"$M\")\n"
    )
    assert check_contract(mutated, TEMPLATE.read_text()) == ["images.invented_key"]


def test_renamed_template_rootfs_key_fails_naming_it():
    template = json.loads(TEMPLATE.read_text())
    images = template["storage_devices"]["rootdisk"]["images"]
    images["rootfs_renamed"] = images.pop("rootfs")
    assert check_contract(SCRIPT.read_text(), json.dumps(template)) == ["images.rootfs"]
