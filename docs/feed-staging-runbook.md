# Manual Feed-Pipeline Runbook

This runbook captures the exact manual sequence for taking a package from a
fresh build all the way to a local feed that `avocado` tooling can search and
install from. It is the procedural template for the package-feed bringup
(`zeromq` was the first package run through it) and the reference the
`yocto-engineer` skill follows when it later automates this workflow.

The pipeline has four phases:

```text
produce  ->  stage  ->  render-pool  ->  consume
```

- **produce**: build the target matrix so each machine's `tmp/deploy/rpm`
  holds the package RPM.
- **stage**: copy the per-machine RPMs into a target-shaped deploy tree and
  build `targets.json`.
- **render-pool**: render the production-served shape (content-addressed
  `_pkgs/` pool + per-machine repodata) with `render-pool-local.py`.
- **consume**: serve the channel root over HTTP and verify discovery + install.

---

> ## WARNING: `update-rpm-repos.sh` is STALE/BROKEN - DO NOT USE IT
>
> `meta-avocado/scripts/update-rpm-repos.sh` is **stale** and must not be used.
> It calls two helper scripts that no longer exist in `meta-avocado/scripts/`:
>
> - `copy-rpm-files.sh` (invoked at `update-rpm-repos.sh` line 19)
> - `update-repo-metadata.sh` (invoked at `update-rpm-repos.sh` line 22)
>
> Running it fails immediately when the first missing helper is invoked. Even
> if those helpers existed, the flat-createrepo path it implements does NOT
> produce the content-addressed `_pkgs/` pool that production serves, so it
> cannot validate the real layout. Use the `render-pool-local.py` pipeline in
> section 4 instead.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Produce: build the target matrix](#2-produce-build-the-target-matrix)
3. [Stage: copy RPMs and build targets.json](#3-stage-copy-rpms-and-build-targetsjson)
4. [Render-pool: render the production-served shape](#4-render-pool-render-the-production-served-shape)
5. [Serve: serve the rendered channel root over HTTP](#5-serve-serve-the-rendered-channel-root-over-http)
6. [Consume: search and install from the local feed](#6-consume-search-and-install-from-the-local-feed)
7. [Script reference](#7-script-reference)
8. [Automated local validation](#8-automated-local-validation)

---

## 1. Prerequisites

- A kas-capable build environment for the produce phase. The full matrix is
  heavy - run `build-all-machines.sh` on the shared build box, not a dev laptop.
- `createrepo_c` on `PATH` (used by `render-pool-local.py`); install from your
  distro, e.g. `pacman -S createrepo_c` (Arch) or `dnf install createrepo_c` (Fedora).
- `python3` (stdlib only - `render-pool-local.py` has no third-party deps).
- `docker`/`podman` + `compose` for the serve phase.
- `jq` is optional but recommended (`repo-aggregate-targets.sh` validates the
  output JSON with it when present).

Throughout this runbook `<releasever>` is the release/channel path segment. The
suite uses `2024/edge` to match the Yocto scarthgap LTS (release 2024) and the
`avocadolinux/sdk:2024-edge` SDK image; the feed must be served under that same
release path so the SDK's target repo config resolves against it.

---

## 2. Produce: build the target matrix

You almost never need the full matrix to validate the pipeline. One target
(qemux86-64) exercises produce -> stage -> render-pool -> consume end to end.
For that local path, jump to [section 8](#8-automated-local-validation) or build
a single machine by hand:

```bash
. meta-avocado/scripts/init-build meta-avocado/kas/machine/qemux86-64.yml
SDKMACHINE=x86_64 kas build meta-avocado/kas/machine/qemux86-64.yml --target avocado-complete
```

Build the `avocado-complete` target, not `avocado-distro`. `avocado-complete`
builds the distro AND one SDK (host arch by default, set via `SDKMACHINE`), which
produces the SDK-side packages (`avocado-sdk-bootstrap`, nativesdk toolchain) that
`avocado sdk install` needs during consume. `avocado-distro` alone omits them, so
the feed can't satisfy `avocado sdk install`. For an aarch64 target on an x86_64
host, set `SDKMACHINE=aarch64`.

The build output lands under `<workspace>/build-qemux86-64/build/tmp/deploy/rpm`:
kas nests the build dir at `build-<machine>/build/` (`KAS_BUILD_DIR` defaults to
`<work>/build`). The validation scripts resolve this layout automatically.

The all-targets sweep is for the build farm, not a dev laptop.
`build-all-machines.sh` globs every `kas/machine/*.yml` (27 machine configs
today) and runs a kas build of the `avocado-distro` target per machine; each
machine's RPMs land in that build's `tmp/deploy/rpm/<tune-arch>/`. The farm's CI
does not use this script directly: `pr-build-labeled.yml` builds each machine on
a self-hosted runner via a matrix job (`kas build .../machine/<m>.yml:kas/ci/mirrors.yml
--target avocado-complete`). Use `build-all-machines.sh` only for a manual
all-targets sweep on a host with the disk and time to spare.

```bash
bash meta-avocado/scripts/build-all-machines.sh
```

Useful flags (passed through to kas):

- `--clean` - remove the build directory before each machine build.
- `--sdkmachine=<arch>` - SDK host arch (defaults to `x86_64`).

The script does **not** stop on the first failure; it builds every machine and
prints a `BUILD SUMMARY` listing successful and failed machines, then exits
non-zero if any machine failed.

**Verify** the package was produced for each machine:

```bash
# For each machine build, confirm the package RPM exists, e.g. zeromq:
find <machine-build>/tmp/deploy/rpm -name 'zeromq-*.rpm'
```

If a machine's `tmp/deploy/rpm` has no RPM for the package, the shared
packagegroup did not reach that target - record a corpus case and switch that
target to an explicit dependency.

---

## 3. Stage: copy RPMs and build targets.json

Staging takes a machine's `tmp/deploy/rpm` (the source deploy dir) and copies
the RPMs into a target-shaped deploy tree, then builds the per-target
`targets.json` from per-target fragments. Staging reads the build's
`avocado-repo.map` file (`<source-deploy-dir>/avocado-repo.map`) to map source
package dirs to target repo paths.

### 3.1 Stage the RPMs

```bash
bash meta-avocado/scripts/repo-stage-rpms.sh \
  [--metadata-only] \
  <source-deploy-directory> <target-deploy-directory> <releasever>
```

- `<source-deploy-directory>` - the build's `tmp/deploy/rpm` (must contain
  `avocado-repo.map`).
- `<target-deploy-directory>` - the staged deploy tree root.
- `<releasever>` - release/channel path, e.g. `latest/apollo/edge`.
- `--metadata-only` - validate the map and per-entry source dirs but skip the
  bulk tar-pipe of RPMs (use when RPMs are uploaded directly from the build).

Example:

```bash
bash meta-avocado/scripts/repo-stage-rpms.sh \
  /path/to/build/tmp/deploy/rpm /path/to/target/repo latest/apollo/edge
```

### 3.2 Generate a per-target fragment

Run once per machine to emit that target's `targets.json` fragment (a compact
JSON listing the target's repo roots).

```bash
bash meta-avocado/scripts/repo-generate-target-fragment.sh \
  <source-deploy-directory> <target-name> <output-directory> <releasever>
```

- `<source-deploy-directory>` - the build's `tmp/deploy/rpm`.
- `<target-name>` - the machine name, e.g. `qemux86-64`.
- `<output-directory>` - the fragments directory; the script writes
  `<output-directory>/<target-name>-fragment.json`.
- `<releasever>` - release/channel path, e.g. `latest/apollo/edge`.

Example:

```bash
bash meta-avocado/scripts/repo-generate-target-fragment.sh \
  /path/to/build/tmp/deploy/rpm qemux86-64 /path/to/staging latest/apollo/edge
```

### 3.3 Aggregate fragments into targets.json

Combine all `*-fragment.json` files in the fragments directory into a single
`targets.json`. Supports merging with an existing `targets.json` so a partial
matrix rebuild updates only its own targets.

```bash
bash meta-avocado/scripts/repo-aggregate-targets.sh \
  <fragments-directory> <output-file> [existing-targets-json]
```

- `<fragments-directory>` - directory holding the `*-fragment.json` files.
- `<output-file>` - destination `targets.json`.
- `[existing-targets-json]` - optional existing `targets.json` to merge with
  (defaults to `<output-file>` if it already exists).

Example:

```bash
bash meta-avocado/scripts/repo-aggregate-targets.sh \
  /path/to/staging/fragments /path/to/releases/targets.json
```

---

## 4. Render-pool: render the production-served shape

`render-pool-local.py` is the dev mirror of the production render
(`render_pool.py` in avocado-package). It renders **one repo per invocation**
from a staged RPM tree into the content-addressed layout production serves:

```text
<channel-root>/_pkgs/<aa>/<sha256>.rpm        # every package ONCE, content-addressed
<channel-root>/<subpath>/repodata/            # per-repo metadata, gzip
    primary.xml -> location_href ../../_pkgs/<aa>/<sha256>.rpm
```

```bash
python3 meta-avocado/scripts/render-pool-local.py \
  --staged <staged-dir> \
  --channel-root <channel-root> \
  --subpath target/<machine>
```

- `--staged <staged-dir>` - the staged RPM tree for this repo (may contain
  arch subdirs); recursed by `createrepo_c`.
- `--channel-root <channel-root>` - the served channel root; `_pkgs/` and
  `<subpath>/` live under here.
- `--subpath target/<machine>` - the repo subpath under the channel root, e.g.
  `target/qemux86-64`.

Run it once per machine repo (and once per `sdk/<machine>` repo as needed). The
pool is content-addressed, so a package shared across two targets that share a
tune-arch is copied into `_pkgs/` only once - the second invocation references
the same `<sha256>.rpm`.

**Verify the pool shape:**

```bash
# The pool exists and holds each RPM once:
ls <channel-root>/_pkgs/*/*.rpm

# A per-machine primary.xml location_href resolves into the pool:
zcat <channel-root>/target/qemux86-64/repodata/*-primary.xml.gz \
  | grep -o 'location href="[^"]*"'
# -> ../../_pkgs/<aa>/<sha256>.rpm

# Two same-tune-arch targets reference the SAME pooled file (de-dup proof):
# render target/qemux86-64 and target/intel-x86-64-v2, then compare the
# location_href sha in each per-machine primary.xml - they must match.
```

If the channel root lacks `_pkgs/`, or a `primary.xml` location_href does not
resolve into the pool, or two same-tune-arch targets reference different pooled
RPMs, the local feed is not production-representative - do not trust the
validation.

---

## 5. Serve: serve the rendered channel root over HTTP

The render phase (section 4) already produced the production-served shape
(`repodata` + the `_pkgs` pool), so the channel root only needs a plain static
HTTP server:

```bash
python3 -m http.server 8080 --bind 0.0.0.0 --directory <channel-root>
```

- The repo is reachable at `http://localhost:8080`; with the releasever-prefixed
  layout from section 4, the qemux86-64 metadata is at
  `http://localhost:8080/<releasever>/target/qemux86-64/repodata/repomd.xml`.
- The SDK container reaches this host port via avocado's `--network=host` (Linux).

> The `support/sdk-test` compose `package-repo` container is a DIFFERENT path:
> it mounts a raw `<deploy>/rpm` and runs its own flat `createrepo_c` (no `_pkgs`
> pool), so it serves a raw Yocto deploy, not the render-pool output. Use the
> static server above to serve the pool the render phase produced.

---

## 6. Consume: search and install from the local feed

Point avocado tooling at the local feed and verify discovery, then install.

```bash
export AVOCADO_REPO_URL=http://localhost:8080
# The feed must be served under the same release path the SDK resolves to.
# For the scarthgap LTS / sdk:2024-edge SDK that is 2024/edge.
export AVOCADO_RELEASEVER=2024/edge
```

### 6.1 Discover the package

```bash
avocado-mcp search-packages
# query a package across targets, e.g. zeromq on qemux86-64 + qemuarm64
```

A green result returns a match for the package per target queried. If
`search-packages` does not return the package for more than one target, the
feed index is incomplete.

### 6.2 Install into an extension

```bash
avocado ext dnf -e <ext> install zeromq
```

On qemux86-64 a green install exits 0 and leaves the shared library in the
extension sysroot:

```bash
ls <ext-sysroot>/usr/lib/libzmq.so*
# -> libzmq.so.5*
```

If the install exits non-zero, or `libzmq.so*` is absent after a green
build+stage, or the package resolves from a mismatched repo / the default
upstream host instead of `target/<machine>`, the consume path is broken. Never
point the local install at the production `repo.avocadolinux.org` host.

---

## 7. Script reference

| Phase | Script | Signature |
|-------|--------|-----------|
| produce (all targets) | `build-all-machines.sh` | `build-all-machines.sh [--clean] [--sdkmachine=<arch>]` |
| local (one target) | `validate-feed-local.sh` | `validate-feed-local.sh [MACHINE] [PACKAGE] [EXTENSION]` |
| stage | `repo-stage-rpms.sh` | `repo-stage-rpms.sh [--metadata-only] <source-deploy-directory> <target-deploy-directory> <releasever>` |
| stage | `repo-generate-target-fragment.sh` | `repo-generate-target-fragment.sh <source-deploy-directory> <target-name> <output-directory> <releasever>` |
| stage | `repo-aggregate-targets.sh` | `repo-aggregate-targets.sh <fragments-directory> <output-file> [existing-targets-json]` |
| render-pool | `render-pool-local.py` | `render-pool-local.py --staged <dir> --channel-root <dir> --subpath target/<machine>` |
| serve | `python3 -m http.server` | `python3 -m http.server 8080 --bind 0.0.0.0 --directory <channel-root>` |
| consume | `avocado-mcp` / `avocado` | `avocado-mcp search-packages`; `avocado ext dnf -e <ext> install zeromq` (`AVOCADO_REPO_URL=http://localhost:8080`) |

> Do NOT use `update-rpm-repos.sh` - it is stale/broken (see the warning at the
> top of this runbook). The `render-pool-local.py` pipeline above is the only
> supported path to the production-served shape.

---

## 8. Automated local validation (test suite)

Three scripts in `meta-avocado/scripts/` turn the manual sequence above into a
reusable test suite: validating a package set is one command, and adding a test
is one line.

- `feed-validation-cases` - the suite data. One case per line:
  `name | packages | expected-libs | boot`. Adding a test = adding a line.
- `feed-validation-lib.sh` - the shared steps (build, stage, render, serve,
  install, verify, boot), so cases reuse one pipeline.
- `validate-feed-local.sh` - the engine for ONE package set.
- `run-feed-validation.sh` - the runner: does the expensive setup (build +
  stage + render + serve) once, runs every case, and reports PASS/FAIL with a
  summary and a non-zero exit on any failure.

Run the whole suite (build + feed done once; cases reuse it):

```bash
bash meta-avocado/scripts/run-feed-validation.sh            # qemux86-64
```

Or validate a single package set directly:

```bash
bash meta-avocado/scripts/validate-feed-local.sh zeromq                       # SDK tier
bash meta-avocado/scripts/validate-feed-local.sh -b -l libzmq.so.5 zeromq     # + boot e2e
bash meta-avocado/scripts/validate-feed-local.sh foo bar baz                  # multiple packages
```

Two tiers run from the same cases:

- **SDK tier** (fast): host-side `avocado ext dnf install` into an extension,
  asserting each package is in the ext rpmdb (and any expected libs present).
- **Boot e2e** (heavy, opt-in per case via `boot=yes`): provision qemux86-64,
  boot it, assert the extension is merged and the libs are present on the
  running target, reboot, and re-assert (persistence). The package is delivered
  the way a user ships it - bundled into an extension from the feed at build
  time; there is no on-device package install on Avocado OS.

The build front-end is parameterized. The engine invokes it as
`$AVOCADO_LOCAL_BUILD_CMD build <machine.yml>`, so the default `kas` runs
`kas build ...`; set `AVOCADO_LOCAL_BUILD_CMD` to a local builder that shares the
`build` subcommand and owns its own build directory. The build output is located
under `<workspace>/build-<machine>` (override with `AVOCADO_LOCAL_BUILD_DIR`).
Set `AVOCADO_LOCAL_BUILD_CMD=true` to skip the build when the target is already
built.

| Variable | Default | Purpose |
|----------|---------|---------|
| `AVOCADO_LOCAL_BUILD_CMD` | `kas` | Build front-end; invoked as `<cmd> build <machine.yml>` |
| `AVOCADO_LOCAL_BUILD_DIR` | `<workspace>/build-<machine>` | Where to find the build's `tmp/deploy/rpm` |
| `AVOCADO_RELEASEVER` | `2024/edge` | Release/channel the feed serves (match the SDK: scarthgap LTS = 2024/edge) |
| `AVOCADO_REPO_URL` | `http://localhost:8080` | Local feed URL |
| `FVL_QGA_PORT` | `4445` | Host TCP port for the QEMU guest-agent channel (`vm --qga-port`); the boot tier asserts over it without ssh |
| `FVL_BOOT_WAIT` | `180` | Seconds to wait for the QEMU guest agent to respond |

Package names are the real feed names (e.g. `zeromq`, not `libzmq` - debian
renaming is not active here). The runner leaves the `package-repo` container
running; stop it with
`docker compose -f meta-avocado/support/sdk-test/compose.yml down`.

> Note: the default local target `qemux86-64` does not enable `opengl wayland`
> (its `DISTRO_FEATURES` add only `seccomp virtualization`), so it never pulls
> chromium and local validation stays light - independent of whether the
> chromium-drop PR has landed on `scarthgap`. The chromium build weight only
> affects machines that enable `opengl wayland`.
