#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import tempfile

import yaml

"""
kas2bitbake-setup.py

Generate bitbake-setup configuration templates (.conf.json) and OpenEmbedded
config fragments from the authoritative kas configuration in kas/.

kas remains the single source of truth: for every kas/machine/<name>.yml this
script asks kas itself to resolve the include/merge tree (`kas dump`) and then
translates the flattened result into the equivalent bitbake-setup inputs. Run
it whenever the kas configs change; the generated files are committed so users
do not need kas (or this script) to consume the bitbake-setup workflow.

For each machine it writes:
  - bitbake-setup/avocado-<machine>.conf.json
        A bitbake-setup Configuration Template: `sources` (the layer/tool repos
        with their pinned revisions), one `configurations` entry listing the
        enabled `bb-layers`, the `bb-env-passthrough-additions`, and a reference
        to the machine's `oe-fragments`.
  - meta-avocado/conf/fragments/avocado-build/<machine>.conf
        An OE config fragment carrying MACHINE, DISTRO, the env defaults and the
        flattened kas local_conf_header text. Enabled via the conf.json above.

kas -> bitbake-setup mapping
  repos.<r>.url/branch/commit  -> sources.<r>.git-remote {uri, branch, rev}
  repos.<r>.path               -> sources.<r>.path
  repos.<r>.layers (enabled)   -> configuration.bb-layers
  env.<V> = <default>          -> fragment 'V ?= "<default>"' + passthrough name V
  machine / distro             -> fragment 'MACHINE = ...' / 'DISTRO = ...'
  local_conf_header.<k>        -> fragment body (in kas merge order)
  target                       -> recorded as a build note (bitbake-setup does
                                  not build; the user still runs `bitbake <t>`)

Requirements:
  - Python 3 with PyYAML
  - kas (used read-only via `kas dump`, fully offline — no repos are fetched)
"""

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KAS_MACHINE_DIR = os.path.join(REPO_ROOT, "kas", "machine")
BBSETUP_DIR = os.path.join(REPO_ROOT, "bitbake-setup")
# Fragments live in the always-present meta-avocado base layer (collection name
# "meta-avocado"); they are referenced as "<collection>/<path-under-fragments>".
FRAGMENT_LAYER_DIR = os.path.join(REPO_ROOT, "meta-avocado")
FRAGMENT_COLLECTION = "meta-avocado"
FRAGMENT_SUBDIR = "avocado-build"
FRAGMENT_NAME_PREFIX = "{}/{}".format(FRAGMENT_COLLECTION, FRAGMENT_SUBDIR)

# Steps to skip so `kas dump` only resolves/merges the config (which needs the
# local meta-avocado includes) without fetching or checking out any repo.
KAS_SKIP_STEPS = [
    "finish_setup_repos",
    "repos_checkout",
    "repos_check_signatures",
    "repos_apply_patches",
    "setup_environ",
    "write_bbconfig",
]


def kas_dump(work_dir, machine_basename):
    """Return the flattened kas config for kas/machine/<basename>.yml."""
    cmd = ["kas", "dump", "--format", "yaml"]
    for step in KAS_SKIP_STEPS:
        cmd += ["--skip", step]
    cmd.append("meta-avocado/kas/machine/{}.yml".format(machine_basename))
    env = dict(os.environ, KAS_WORK_DIR=work_dir)
    out = subprocess.run(
        cmd, cwd=work_dir, env=env, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return yaml.safe_load(out.stdout)


def enabled_layers(repo_path, layers):
    """Yield bb-layers paths for the non-disabled layers of one repo."""
    if not layers:
        # kas treats a repo with no `layers:` key as a single layer at its root.
        yield repo_path
        return
    for sub, value in layers.items():
        if value == "disabled":
            continue
        if sub == ".":
            yield repo_path
        else:
            yield "{}/{}".format(repo_path, sub)


def is_local_repo(repo):
    """The url-less repo is meta-avocado itself (the local checkout in kas)."""
    return not repo.get("url")


def build_sources(repos):
    """Translate the url-bearing kas `repos` into bitbake-setup `sources`.

    meta-avocado (the local checkout) is intentionally excluded: it is consumed
    in place via bb-layers-file-relative (see build_local_layers) so the live
    working tree is used, matching kas and avoiding a push/clone round-trip.
    """
    sources = {}
    for name, repo in repos.items():
        if is_local_repo(repo):
            continue
        git_remote = {"uri": repo["url"]}
        if repo.get("branch"):
            git_remote["branch"] = repo["branch"]
        # Pin to the exact commit kas pins to; fall back to the branch ref.
        git_remote["rev"] = repo.get("commit") or repo.get("branch")
        sources[name] = {"git-remote": git_remote, "path": repo.get("path", name)}
    return sources


def build_bb_layers(repos):
    """Cloned (url-bearing) layers, as paths under the setup's layers/ dir."""
    layers = []
    for name, repo in repos.items():
        if is_local_repo(repo):
            continue
        layers.extend(enabled_layers(repo.get("path", name), repo.get("layers")))
    return layers


def build_local_layers(repos):
    """meta-avocado layers as paths relative to the bitbake-setup config dir.

    bitbake-setup resolves bb-layers-file-relative against the directory of the
    .conf.json, so these point straight at the live working-tree layers (the
    same checkout the config ships in) without cloning anything.
    """
    layers = []
    for name, repo in repos.items():
        if not is_local_repo(repo):
            continue
        repo_layers = repo.get("layers")
        items = repo_layers.items() if repo_layers else [(".", None)]
        for sub, value in items:
            if value == "disabled":
                continue
            target = REPO_ROOT if sub == "." else os.path.join(REPO_ROOT, sub)
            if not os.path.isdir(target):
                raise SystemExit(
                    "Local layer {!r} for repo {!r} not found at {}".format(
                        sub, name, target
                    )
                )
            layers.append(os.path.relpath(target, BBSETUP_DIR))
    return layers


def render_fragment(basename, dump):
    """Render the OE config fragment text for one machine."""
    machine = dump.get("machine")
    distro = dump.get("distro")
    env = dump.get("env") or {}
    targets = dump.get("target") or []
    headers = dump.get("local_conf_header") or {}

    lines = []
    summary = "AvocadoOS {} build configuration (generated from kas)".format(
        machine or basename
    )
    note = "Build with: bitbake {}".format(" ".join(targets)) if targets else ""
    description = (
        "MACHINE, DISTRO, environment defaults and local.conf settings for the "
        "{} target. Generated by scripts/kas2bitbake-setup.py from "
        "kas/machine/{}.yml -- do not edit by hand. {}"
    ).format(machine or basename, basename, note).strip()
    lines.append('BB_CONF_FRAGMENT_SUMMARY = "{}"'.format(summary))
    lines.append('BB_CONF_FRAGMENT_DESCRIPTION = "{}"'.format(_bb_escape(description)))
    lines.append("")

    if machine:
        lines.append('MACHINE = "{}"'.format(machine))
    if distro:
        lines.append('DISTRO = "{}"'.format(distro))

    if env:
        lines.append("")
        lines.append("# Environment defaults (from kas `env`). These are also")
        lines.append("# listed in bb-env-passthrough-additions so the invoking")
        lines.append("# shell environment can still override them; `?=` defers")
        lines.append("# to a value imported from the environment when present.")
        for key, value in env.items():
            lines.append('{} ?= "{}"'.format(key, _bb_escape(_scalar(value))))

    for key, body in headers.items():
        if not body or not str(body).strip():
            continue
        lines.append("")
        lines.append("# --- kas local_conf_header: {} ---".format(key))
        lines.append(str(body).rstrip("\n"))

    return "\n".join(lines) + "\n"


def _scalar(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    return "" if value is None else str(value)


def _bb_escape(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def build_conf_json(basename, dump, sources, bb_layers, local_layers):
    machine = dump.get("machine") or "avocado-{}".format(basename)
    targets = dump.get("target") or []
    env = dump.get("env") or {}
    name = "avocado-{}".format(basename)
    note = "Build with: bitbake {}".format(" ".join(targets)) if targets else ""
    fragment = "{}/{}".format(FRAGMENT_NAME_PREFIX, basename)

    configuration = {
        "name": name,
        "description": "AvocadoOS {} target. {}".format(machine, note).strip(),
        "setup-dir-name": name,
        "bb-layers": bb_layers,
        # meta-avocado's own layers, used in place from the live working tree
        # (resolved relative to this .conf.json). Requires init from a local
        # path, which is the normal usage.
        "bb-layers-file-relative": local_layers,
        "oe-fragments": [fragment],
    }
    if env:
        configuration["bb-env-passthrough-additions"] = list(env.keys())

    return {
        "version": "1.0",
        "description": "AvocadoOS -- {} (generated from kas/machine/{}.yml)".format(
            machine, basename
        ),
        "sources": sources,
        "bitbake-setup": {"configurations": [configuration]},
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate bitbake-setup configs + fragments from kas."
    )
    parser.add_argument(
        "--machine",
        action="append",
        help="Only generate the named machine(s) (basename without .yml). "
        "May be repeated; default is every kas/machine/*.yml.",
    )
    args = parser.parse_args()

    machines = args.machine or sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(KAS_MACHINE_DIR)
        if f.endswith(".yml")
    )

    os.makedirs(BBSETUP_DIR, exist_ok=True)
    fragment_dir = os.path.join(FRAGMENT_LAYER_DIR, "conf", "fragments", FRAGMENT_SUBDIR)
    os.makedirs(fragment_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="kas2bbsetup-") as work_dir:
        os.symlink(REPO_ROOT, os.path.join(work_dir, "meta-avocado"))
        for basename in machines:
            dump = kas_dump(work_dir, basename)
            repos = dump.get("repos") or {}
            sources = build_sources(repos)
            bb_layers = build_bb_layers(repos)
            local_layers = build_local_layers(repos)
            conf = build_conf_json(basename, dump, sources, bb_layers, local_layers)

            conf_path = os.path.join(BBSETUP_DIR, "avocado-{}.conf.json".format(basename))
            with open(conf_path, "w") as f:
                json.dump(conf, f, indent=2)
                f.write("\n")

            fragment_path = os.path.join(fragment_dir, "{}.conf".format(basename))
            with open(fragment_path, "w") as f:
                f.write(render_fragment(basename, dump))

            print("generated {} ({} cloned + {} local layers, {} sources)".format(
                os.path.relpath(conf_path, REPO_ROOT),
                len(bb_layers), len(local_layers), len(sources),
            ))

    print("\nGenerated {} machine configuration(s) into {}/ and {}/".format(
        len(machines),
        os.path.relpath(BBSETUP_DIR, REPO_ROOT),
        os.path.relpath(fragment_dir, REPO_ROOT),
    ))


if __name__ == "__main__":
    sys.exit(main())
