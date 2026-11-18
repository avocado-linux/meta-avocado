"""Text-level wiring checks for the engine deploy recipe and the stone bbappend.

BitBake is not available here, so these read the recipe files as text.
"""

import os
import re
from pathlib import Path

import pytest

LAYER = Path(__file__).resolve().parents[3]
RECIPE = LAYER / "recipes-bsp" / "tegraflash" / "tegraflash-engine.bb"
BBAPPEND = LAYER / "recipes-avocado" / "distro" / "avocado-stone.bbappend"
IMG_BOOTFILES = LAYER / "recipes-avocado" / "packages" / "avocado-img-bootfiles.bbappend"

DEPENDS_LINE = 'do_compile[depends] += "tegraflash-engine:do_deploy"'
BYTECODE_EXCLUDE = "-name __pycache__ -prune -exec rm -rf {} +"
PYC_EXCLUDE = "-name '*.pyc' -delete"
REQUIRED_RECIPE_TEXT = (
    'COMPATIBLE_MACHINE = "(tegra)"',
    "inherit deploy",
    'S = "${UNPACKDIR}"',
    'do_compile[noexec] = "1"',
    'do_install[noexec] = "1"',
    "file://avocado_tegraflash",
    'FILESEXTRAPATHS:prepend := "${THISDIR}/../../stone/tegra:"',
    "${DEPLOYDIR}/tegraflash-engine",
)


def _recipe_text() -> str:
    assert RECIPE.is_file(), f"recipe moved or missing: {RECIPE}"
    return RECIPE.read_text()


def _bbappend_text() -> str:
    assert BBAPPEND.is_file(), f"bbappend moved or missing: {BBAPPEND}"
    return BBAPPEND.read_text()


def _missing_recipe_items(text: str) -> list[str]:
    return [item for item in REQUIRED_RECIPE_TEXT if item not in text]


def _has_bytecode_exclusion(text: str) -> bool:
    return BYTECODE_EXCLUDE in text and PYC_EXCLUDE in text


def _has_dependency(text: str) -> bool:
    return DEPENDS_LINE in text.splitlines()


def test_recipe_carries_every_required_line():
    assert _missing_recipe_items(_recipe_text()) == []


def test_recipe_deploys_to_no_other_directory_name():
    text = _recipe_text()
    dirs = set(re.findall(r"\$\{DEPLOYDIR\}/([^/\s\"]+)", text))
    assert dirs == {"tegraflash-engine"}


def test_recipe_copies_only_the_package_directory():
    copies = [ln for ln in _recipe_text().splitlines() if ln.strip().startswith("cp ")]
    assert len(copies) == 1
    assert "${UNPACKDIR}/avocado_tegraflash " in copies[0]
    assert copies[0].rstrip().endswith("${DEPLOYDIR}/tegraflash-engine/")


def test_recipe_prevents_bytecode_deployment():
    text = _recipe_text()
    assert _has_bytecode_exclusion(text)


def test_bbappend_depends_on_the_engine_deploy():
    assert _has_dependency(_bbappend_text())


def test_bbappend_keeps_the_existing_tegraflash_dependencies():
    text = _bbappend_text()
    assert 'do_compile[depends] += "tegraflash-tools-deploy:do_deploy"' in text
    assert 'do_compile[depends] += "tegraflash-bsp:do_deploy"' in text


def test_img_bootfiles_bbappend_depends_on_the_engine_deploy():
    assert IMG_BOOTFILES.is_file(), f"bbappend moved or missing: {IMG_BOOTFILES}"
    assert _has_dependency(IMG_BOOTFILES.read_text())


def test_mutated_img_bootfiles_bbappend_without_dependency_is_detected():
    text = IMG_BOOTFILES.read_text()
    assert text.count(DEPENDS_LINE) == 1
    assert not _has_dependency(text.replace(DEPENDS_LINE, ""))


def test_mutated_recipe_deploying_to_tools_dir_fails_required_items():
    text = _recipe_text()
    old = "${DEPLOYDIR}/tegraflash-engine"
    assert text.count(old) >= 1
    mutated = text.replace(old, "${DEPLOYDIR}/tegraflash-tools")
    assert _missing_recipe_items(mutated) == [old]


def test_mutated_recipe_without_bytecode_exclusion_is_detected():
    text = _recipe_text()
    assert text.count(BYTECODE_EXCLUDE) == 1
    mutated = text.replace(BYTECODE_EXCLUDE, "")
    assert not _has_bytecode_exclusion(mutated)


def test_mutated_bbappend_without_dependency_is_detected():
    text = _bbappend_text()
    assert text.count(DEPENDS_LINE) == 1
    assert not _has_dependency(text.replace(DEPENDS_LINE, ""))


# The engine runs avocado-tegra-bootimg and mkbootimg out of the staged
# tegraflash-tools directory (the manifest's "tegraflash_tools" key), so the
# tools deploy recipe has to put both there.
TOOLS_RECIPE = LAYER / "recipes-bsp" / "tegraflash" / "tegraflash-tools-deploy.bb"
HELPER = "avocado-tegra-bootimg"
HELPER_SRC_DIR = LAYER / "recipes-avocado" / "sdk" / "avocado-sdk-target"
HELPER_EXTRAPATH = 'FILESEXTRAPATHS:prepend := "${THISDIR}/../../recipes-avocado/sdk/avocado-sdk-target:"'
HELPER_INSTALL = f"install -m 0755 ${{UNPACKDIR}}/{HELPER} ${{DEPLOYDIR}}/tegraflash-tools/{HELPER}"
FLASH_COPY = 'cp -a "$FLASH_SRC"/. ${DEPLOYDIR}/tegraflash-tools/'
FLASH_SRC = 'FLASH_SRC="${STAGING_BINDIR_NATIVE}/tegra-flash"'


def _tools_recipe_text() -> str:
    assert TOOLS_RECIPE.is_file(), f"recipe moved or missing: {TOOLS_RECIPE}"
    return TOOLS_RECIPE.read_text()


def _installs_helper(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines()]
    return HELPER_INSTALL in lines and f"file://{HELPER}" in text and HELPER_EXTRAPATH in lines


def _flashtools_recipe() -> Path:
    vendor = os.environ.get("VENDOR_META_TEGRA")
    if not vendor:
        pytest.skip("VENDOR_META_TEGRA not set; cannot read the pinned meta-tegra")
    found = sorted((Path(vendor) / "recipes-bsp" / "tegra-binaries").glob("tegra-flashtools_*.bb"))
    assert len(found) == 1, f"expected one tegra-flashtools recipe, found {found}"
    return found[0]


def test_tools_recipe_installs_the_bootimg_helper_executable():
    assert _installs_helper(_tools_recipe_text())


def test_tools_recipe_helper_extrapath_resolves_to_the_sdk_target_file():
    # ${THISDIR}/../../recipes-avocado/sdk/avocado-sdk-target, from the recipe's directory.
    resolved = (TOOLS_RECIPE.parent / ".." / ".." / "recipes-avocado" / "sdk" / "avocado-sdk-target").resolve()
    assert resolved == HELPER_SRC_DIR.resolve()
    assert (resolved / HELPER).is_file()


def test_mutated_tools_recipe_without_helper_install_is_detected():
    text = _tools_recipe_text()
    assert text.count(HELPER_INSTALL) == 1
    assert not _installs_helper(text.replace(HELPER_INSTALL, ""))
    assert not _installs_helper(text.replace("0755", "0644"))


def test_mkbootimg_reaches_the_tools_dir_through_the_flashtools_copy():
    # mkbootimg is not installed by the deploy recipe itself: tegra-flashtools
    # installs it into ${bindir}/tegra-flash, and the deploy recipe copies that
    # whole native directory into tegraflash-tools.
    flashtools = _flashtools_recipe().read_text()
    flash_lines = [ln.strip() for ln in flashtools.splitlines()]
    assert 'BINDIR = "${bindir}/tegra-flash"' in flash_lines
    assert "install -m 0755 ${S}/bootloader/mkbootimg ${D}${BINDIR}" in flash_lines
    assert re.search(r'^BBCLASSEXTEND = "[^"]*\bnative\b', flashtools, re.M)
    deploy = _tools_recipe_text()
    deploy_lines = [ln.strip() for ln in deploy.splitlines()]
    assert FLASH_SRC in deploy_lines
    assert FLASH_COPY in deploy_lines
    assert re.search(r'^DEPENDS = "[^"]*\btegra-flashtools-native\b', deploy, re.M)
