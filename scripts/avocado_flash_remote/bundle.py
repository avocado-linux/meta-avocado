"""Host side: pack the runner modules and the exact profile into one zipapp.

The archive runs with the board's ``python3`` (3.10 or newer) and the
standard library only. Layout::

    #!/usr/bin/env python3
    __main__.py                       calls avocado_flash_remote.runner.main
    avocado_flash_remote/<module>.py  the runner modules
    profile.json                      the exact resolved profile bytes
    BUNDLE.json                       sha256 of every file, versions

The build is deterministic: sorted entries, fixed timestamps and
permissions, so the same inputs give byte-identical archives.
"""

import ast
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = "avocado_flash_remote"
SHEBANG = b"#!/usr/bin/env python3\n"
MAIN_SOURCE = (
    "import sys\n"
    "from avocado_flash_remote import runner\n"
    "sys.exit(runner.main(sys.argv[1:]))\n"
).encode()

# Everything the runner needs; the host-side modules (cli, host, bundle,
# profile_resolve) are deliberately absent.
ARCHIVE_MODULES = (
    "__init__",
    "arm",
    "cmd_check",
    "cmd_plan",
    "cmd_readback",
    "cmd_restore",
    "cmd_status",
    "cmd_write",
    "efi",
    "evidence",
    "images",
    "layout",
    "ops",
    "profile",
    "runner",
    "state",
    "strategies",
)

_DATE_TIME = (1980, 1, 1, 0, 0, 0)


class BundleError(Exception):
    pass


@dataclass
class BundleInfo:
    path: Path
    sha256: str
    modules: list = field(default_factory=list)
    profile_sha256: str = ""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _foreign_imports(source: bytes, filename: str) -> list:
    """Top-level names imported outside the stdlib and this package."""
    allowed = set(sys.stdlib_module_names)
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        raise BundleError(f"{filename}: syntax error: {e}")
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            names = [node.module or ""]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top not in allowed and top != PACKAGE:
                bad.append(name)
    return bad


def _stdlib_modules(source: bytes, filename: str) -> list:
    """Sorted top-level module names a source imports, minus this package.

    Relative imports are the package's own and are skipped.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        raise BundleError(f"{filename}: syntax error: {e}")
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module.split(".")[0])
    found.discard(PACKAGE)
    return sorted(found)


def required_stdlib(modules_dir=None) -> list:
    """Standard-library modules the archived runner modules import."""
    modules_dir = Path(modules_dir) if modules_dir is not None else Path(__file__).resolve().parent
    names = set()
    for mod in ARCHIVE_MODULES:
        src = modules_dir / f"{mod}.py"
        if not src.is_file():
            raise BundleError(f"required module missing: {mod} ({src})")
        names.update(_stdlib_modules(src.read_bytes(), str(src)))
    return sorted(names)


def _add(zf, name: str, data: bytes):
    info = zipfile.ZipInfo(name, _DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    info.create_system = 3
    zf.writestr(info, data)


def build_bundle(profile_bytes: bytes, out_path, tool_version: str, modules_dir=None) -> BundleInfo:
    modules_dir = Path(modules_dir) if modules_dir is not None else Path(__file__).resolve().parent
    out_path = Path(out_path)

    sources = {}
    stdlib = set()
    for mod in ARCHIVE_MODULES:
        src = modules_dir / f"{mod}.py"
        if not src.is_file():
            raise BundleError(f"required module missing: {mod} ({src})")
        data = src.read_bytes()
        bad = _foreign_imports(data, str(src))
        if bad:
            raise BundleError(f"{mod}.py imports outside the standard library: {', '.join(sorted(set(bad)))}")
        sources[f"{PACKAGE}/{mod}.py"] = data
        stdlib.update(_stdlib_modules(data, str(src)))

    from .runner import RUNNER_VERSION  # the version the archive's runner reports

    profile_sha = _sha(profile_bytes)
    meta = {
        "built_by": f"avocado-flash {tool_version}",
        "tool_version": tool_version,
        "runner_version": RUNNER_VERSION,
        "profile_sha256": profile_sha,
        "modules": {name: _sha(data) for name, data in sorted(sources.items())},
        "main_sha256": _sha(MAIN_SOURCE),
        "required_stdlib": sorted(stdlib),
    }
    meta_bytes = (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode()

    buf = io.BytesIO()
    buf.write(SHEBANG)
    with zipfile.ZipFile(buf, "w") as zf:
        _add(zf, "__main__.py", MAIN_SOURCE)
        for name in sorted(sources):
            _add(zf, name, sources[name])
        _add(zf, "BUNDLE.json", meta_bytes)
        _add(zf, "profile.json", profile_bytes)
    blob = buf.getvalue()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temporary file in the destination directory: two builds, or a stale name, never share one.
    fd, tmp_name = tempfile.mkstemp(prefix=f".{out_path.name}.", suffix=".tmp", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        # The runner bundle is a stdlib-only archive that must be executable and holds no secret.
        # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        os.chmod(tmp_name, 0o755)
        os.replace(tmp_name, out_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return BundleInfo(out_path, _sha(blob), sorted(sources), profile_sha)


def verify_bundle(path) -> list:
    """Re-hash every member against BUNDLE.json; return the problems found. Never raises on a bad archive."""
    try:
        return _verify_bundle(path)
    except (TypeError, OSError, zipfile.BadZipFile, ValueError, KeyError, EOFError, RuntimeError, zlib.error) as e:
        return [f"bundle unusable: {type(e).__name__}: {e}"]


def _verify_bundle(path) -> list:
    problems = []
    if not isinstance(path, (str, os.PathLike)):
        return [f"cannot open archive: {path!r} is not a path"]
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile, TypeError) as e:
        return [f"cannot open archive: {e}"]
    with zf:
        names = set(zf.namelist())
        try:
            meta = json.loads(zf.read("BUNDLE.json").decode("utf-8"))
        except (KeyError, ValueError) as e:
            return [f"BUNDLE.json unusable: {e}"]
        if not isinstance(meta, dict):
            return ["BUNDLE.json unusable: not an object"]
        modules = meta.get("modules", {})
        if not isinstance(modules, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in modules.items()):
            return ["BUNDLE.json unusable: modules is not a mapping of name to sha256"]
        expected = dict(modules)
        for name, digest in sorted(expected.items()):
            if name not in names:
                problems.append(f"{name}: missing from archive")
            elif _sha(zf.read(name)) != digest:
                problems.append(f"{name}: sha256 differs from BUNDLE.json")
        if "profile.json" not in names:
            problems.append("profile.json: missing from archive")
        elif _sha(zf.read("profile.json")) != meta.get("profile_sha256"):
            problems.append("profile.json: sha256 differs from BUNDLE.json")
        if "__main__.py" not in names:
            problems.append("__main__.py: missing from archive")
        elif _sha(zf.read("__main__.py")) != meta.get("main_sha256"):
            problems.append("__main__.py: sha256 differs from BUNDLE.json")
        extra = names - set(expected) - {"BUNDLE.json", "profile.json", "__main__.py"}
        for name in sorted(extra):
            problems.append(f"{name}: not listed in BUNDLE.json")
    return problems
