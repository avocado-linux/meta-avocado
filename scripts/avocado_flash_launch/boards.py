"""`avocado-flash boards`: list the Jetson stone manifests and their recovery ids.

Reads the manifests directly and starts no subprocess. A manifest is a Jetson
when it carries a tegraflash profile or a tegraflash storage key.

Public API:

    boards(launcher_file, deploy_dir=None) -> exit status (0 ok, 1 malformed manifest)
    validate_manifest(name, data) -> list of problem strings
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

__all__ = ["boards", "validate_manifest"]

RCM_ID_RE = re.compile(r"^0955:[0-9a-f]{4}$")


def _is_jetson(data: dict) -> bool:
    profiles = data.get("provision", {}).get("profiles", {})
    if isinstance(profiles, dict) and "tegraflash" in profiles:
        return True
    return any(
        isinstance(dev, dict) and "tegraflash" in dev
        for dev in (data.get("storage_devices") or {}).values()
    )


def _tegraflash_sections(data: dict) -> list[dict]:
    return [
        dev["tegraflash"]
        for dev in (data.get("storage_devices") or {}).values()
        if isinstance(dev, dict) and isinstance(dev.get("tegraflash"), dict)
    ]


def _rcm_ids(data: dict) -> list[str]:
    ids: list[str] = []
    for tf in _tegraflash_sections(data):
        for rid in tf.get("rcm_ids") or []:
            if rid not in ids:
                ids.append(rid)
    return ids


def validate_manifest(name: str, data: dict) -> list[str]:
    problems: list[str] = []
    platform = data.get("runtime", {}).get("platform")
    if not isinstance(platform, str) or not platform:
        problems.append(f"{name}: runtime.platform missing")
    for tf in _tegraflash_sections(data):
        ids = tf.get("rcm_ids") or []
        evidence = tf.get("rcm_evidence") or {}
        if not isinstance(ids, list) or not isinstance(evidence, dict):
            problems.append(f"{name}: rcm_ids must be a list and rcm_evidence an object")
            continue
        for rid in ids:
            if not isinstance(rid, str) or not RCM_ID_RE.match(rid):
                problems.append(f"{name}: rcm id {rid!r} is not a lowercase 0955:xxxx pair")
            ev = evidence.get(rid)
            if not isinstance(ev, str) or not ev.strip():
                problems.append(f"{name}: rcm id {rid!r} has no rcm_evidence")
        for key in evidence:
            if key not in ids:
                problems.append(f"{name}: rcm_evidence for undeclared id {key!r}")
    return problems


def _stone_dirs(launcher_file: Path, deploy_dir: Path | None) -> list[Path]:
    dirs = [Path(launcher_file).resolve().parent.parent / "meta-avocado-nvidia" / "stone"]
    if deploy_dir is not None:
        dirs.append(Path(deploy_dir))
    return dirs


def boards(launcher_file: Path, deploy_dir: Path | None = None) -> int:
    problems: list[str] = []
    rows: dict[str, tuple[str, str]] = {}
    for d in _stone_dirs(launcher_file, deploy_dir):
        seen: dict[str, str] = {}
        for path in sorted(d.glob("stone-*.json")) if d.is_dir() else []:
            try:
                data = json.loads(path.read_text())
                if not isinstance(data, dict):
                    raise ValueError("top level is not an object")
            except (OSError, ValueError) as exc:
                problems.append(f"{path.name}: unreadable manifest: {exc}")
                continue
            if not _is_jetson(data):
                continue
            problems.extend(validate_manifest(path.name, data))
            platform = data.get("runtime", {}).get("platform")
            if isinstance(platform, str) and platform:
                if platform in seen:
                    problems.append(
                        f"{path.name}: runtime platform {platform!r} already named within this source by {seen[platform]}"
                    )
                    continue
                seen[platform] = path.name
                machine = platform.removeprefix("avocado-")
                # A later source (the deploy tree) supersedes an earlier one.
                rows[platform] = (machine, ",".join(_rcm_ids(data)) or "none recorded")
    if problems:
        for p in problems:
            print(f"avocado-flash: malformed manifest: {p}", file=sys.stderr)
        return 1
    for machine, ids in rows.values():
        print(f"{machine:<24} tegra  {ids}")
    return 0
