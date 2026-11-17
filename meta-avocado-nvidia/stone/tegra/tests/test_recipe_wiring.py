"""Text-level wiring checks for the engine deploy recipe and the stone bbappend.

BitBake is not available here, so these read the recipe files as text.
"""

import re
from pathlib import Path

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
