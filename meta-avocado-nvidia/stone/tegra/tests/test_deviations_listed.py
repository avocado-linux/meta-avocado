"""The listed deviations, the engine README and the tests must agree.

Three checks, each a small function over paths so the tests at the bottom can
prove it fails on a mutated copy (the expected names come from the registry,
never from a count kept here):

- the README's deviation list equals parity.deviations.DEVIATIONS;
- every deviation is carried by a @pytest.mark.deviation(name) test;
- no marker names a deviation that is not listed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from parity.deviations import DEVIATIONS

TESTS = Path(__file__).resolve().parent
README = TESTS.parent / "avocado_tegraflash" / "README.md"
HEADING = "## Deviations from the legacy script"
_ITEM = re.compile(r"^- `([^`]+)`:", re.MULTILINE)


def readme_names(readme: Path) -> list[str]:
    text = readme.read_text()
    assert HEADING in text, f"{readme} has no {HEADING!r} section"
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    return _ITEM.findall(section)


def marker_names(tests_dir: Path, exclude: Path | None = None) -> list[str]:
    """Names given to pytest.mark.deviation on any function under tests_dir."""
    found = []
    for path in sorted(tests_dir.rglob("*.py")):
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        if "legacy" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr == "deviation"
                    and deco.args
                    and isinstance(deco.args[0], ast.Constant)
                ):
                    found.append(deco.args[0].value)
    return found


def readme_problems(readme: Path) -> list[str]:
    names = readme_names(readme)
    problems = []
    if len(names) != len(set(names)):
        problems.append(f"duplicate names in the README list: {sorted(names)}")
    if set(names) != set(DEVIATIONS):
        problems.append(
            f"README list differs: missing {sorted(set(DEVIATIONS) - set(names))}, "
            f"unknown {sorted(set(names) - set(DEVIATIONS))}"
        )
    return problems


def unmarked_problems(tests_dir: Path, exclude: Path | None = None) -> list[str]:
    marked = set(marker_names(tests_dir, exclude))
    return [f"no test carries the marker for {n!r}" for n in sorted(set(DEVIATIONS) - marked)]


def unlisted_problems(tests_dir: Path, exclude: Path | None = None) -> list[str]:
    marked = set(marker_names(tests_dir, exclude))
    return [f"marker names unlisted deviation {n!r}" for n in sorted(marked - set(DEVIATIONS))]


def test_readme_list_equals_the_registry():
    assert readme_problems(README) == []


def test_every_deviation_has_a_marked_test():
    assert unmarked_problems(TESTS, exclude=Path(__file__)) == []


def test_no_marker_names_an_unlisted_deviation():
    assert unlisted_problems(TESTS, exclude=Path(__file__)) == []


def _readme_copy(tmp_path: Path, old: str, new: str) -> Path:
    text = README.read_text()
    assert text.count(old) == 1, f"anchor matches {text.count(old)} places: {old!r}"
    copy = tmp_path / "README.md"
    copy.write_text(text.replace(old, new))
    return copy


def _tests_copy(tmp_path: Path, extra: dict[str, str] | None = None, strip: str | None = None) -> Path:
    root = tmp_path / "tests"
    root.mkdir()
    # The parity tests carry markers too, so the copy keeps their sub-directory.
    for path in [*TESTS.glob("test_*.py"), *(TESTS / "parity").glob("test_*.py")]:
        if path.name == Path(__file__).name:
            continue
        text = path.read_text()
        if strip:
            text = text.replace(f'@pytest.mark.deviation("{strip}")', "")
        target = root / path.relative_to(TESTS)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    for name, body in (extra or {}).items():
        (root / name).write_text(body)
    return root


def test_readme_check_fails_when_a_name_is_removed(tmp_path):
    copy = _readme_copy(tmp_path, "- `prepare-only`:", "- `x-prepare-only-x`:")
    assert readme_problems(copy)


def test_readme_check_fails_when_an_item_is_duplicated(tmp_path):
    copy = _readme_copy(tmp_path, "- `prepare-only`:", "- `one-board-only`:")
    assert any("duplicate" in p for p in readme_problems(copy))


def test_readme_check_fails_when_an_item_is_dropped(tmp_path):
    text = README.read_text()
    lines = [ln for ln in text.splitlines() if not ln.startswith("- `prepare-only`:")]
    copy = tmp_path / "README.md"
    copy.write_text("\n".join(lines) + "\n")
    assert any("missing ['prepare-only']" in p for p in readme_problems(copy))


def test_marker_check_fails_when_one_deviation_loses_its_marker(tmp_path):
    root = _tests_copy(tmp_path, strip="prepare-only")
    assert unmarked_problems(root) == ["no test carries the marker for 'prepare-only'"]


def test_marker_check_fails_on_a_marker_naming_an_unlisted_deviation(tmp_path):
    body = 'import pytest\n\n\n@pytest.mark.deviation("not-a-deviation")\ndef test_x():\n    pass\n'
    root = _tests_copy(tmp_path, extra={"test_extra.py": body})
    assert unlisted_problems(root) == ["marker names unlisted deviation 'not-a-deviation'"]


def test_the_copied_sources_are_clean_without_mutation(tmp_path):
    root = _tests_copy(tmp_path)
    assert unmarked_problems(root) == [] and unlisted_problems(root) == []


def test_readme_without_the_section_is_an_error(tmp_path):
    copy = tmp_path / "README.md"
    copy.write_text("# nothing here\n")
    with pytest.raises(AssertionError, match="has no '## Deviations"):
        readme_names(copy)
