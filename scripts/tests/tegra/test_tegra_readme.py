"""The package README documents what the code defines, not a copy of it."""

import pathlib

import pytest

from avocado_flash_tegra import cli, inputs

README = pathlib.Path(__file__).resolve().parents[2] / "avocado_flash_tegra" / "README.md"

REQUIRED_HEADINGS = (
    "What it does",
    "Build the flash inputs",
    "Enter recovery mode",
    "Run it",
    "After the flash",
    "If it fails",
    "Branch note",
)


def _text() -> str:
    assert README.is_file(), f"{README} does not exist"
    return README.read_text(encoding="utf-8")


def _options() -> list[str]:
    opts = []
    for action in cli.build_parser()._actions:
        opts.extend(o for o in action.option_strings if o.startswith("--") and o != "--help")
    return opts


def _headings(text: str) -> set[str]:
    return {line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")}


@pytest.mark.parametrize("option", _options())
def test_readme_documents_every_parser_option(option):
    assert option in _text()


def test_parser_options_are_discovered():
    assert {"--machine", "--deploy", "--dry-run", "--assume-yes", "--workdir", "--rcm-id"} <= set(_options())


def test_readme_names_the_default_build_target():
    assert inputs.DEFAULT_TARGET in _text()


@pytest.mark.parametrize("target", sorted(set(inputs.BUILD_TARGETS.values())))
def test_readme_names_every_build_target(target):
    assert target in _text()


@pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
def test_readme_has_required_section(heading):
    assert heading in _headings(_text())


def test_readme_has_no_em_or_en_dash():
    text = _text()
    assert "\u2014" not in text
    assert "\u2013" not in text
