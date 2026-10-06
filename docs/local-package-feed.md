# Local Package Feed (Dev Repo)

This guide covers the developer inner loop for serving a **local package feed**
from your Yocto build outputs: turning `build-<target>/` deploy artifacts into a
browsable, `avocado`-installable repository, packaging extensions against it, and
serving it over HTTP — all from one command.

It is the local mirror of the production render/serve pipeline. Everything runs
out of `meta-avocado/scripts/` and `meta-avocado/support/`; no other checkout is
required except the broken-out extension repos (see Prerequisites).

---

## Table of Contents

1. [TL;DR](#1-tldr)
2. [Prerequisites](#2-prerequisites)
3. [The feed codename (year / channel)](#3-the-feed-codename-year--channel)
4. [`dev-repo.sh` — the one command](#4-dev-reposh--the-one-command)
5. [Cleaning a target](#5-cleaning-a-target)
6. [Connecting the avocado CLI](#6-connecting-the-avocado-cli)
7. [What the feed looks like on disk](#7-what-the-feed-looks-like-on-disk)
8. [The two repo-server images](#8-the-two-repo-server-images)
9. [Lower-level scripts](#9-lower-level-scripts)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. TL;DR

```bash
# From the meta-avocado checkout, after building build-imx8mp-evk/:
./scripts/dev-repo.sh 2024 imx8mp-evk
```

That single command will:

1. (optional) reset just the named target's artifacts — see [Cleaning](#5-cleaning-a-target)
2. sync the target's RPMs from `build-imx8mp-evk/` into `_repo/` under the
   `2024/edge` feed
3. package the target's extensions (from the sibling `extensions/` checkout)
4. (re)start the repo server, serving the feed at `http://localhost:8080/`

Re-run it as often as you like — it reuses a stable release id (`dev`), so it
overwrites in place instead of piling up. You do **not** need to `rm -rf _repo`
between runs.

---

## 2. Prerequisites

- **Docker** — runs the repo server and the extension build/package containers.
- **`avocado` CLI** — packages extensions and installs from the feed.
  ```bash
  curl -fsSL https://github.com/avocadolinux/avocado/releases/latest/download/avocado-linux-amd64 -o /usr/local/bin/avocado
  chmod +x /usr/local/bin/avocado
  ```
- **A completed Yocto build** for each target, i.e. `build-<target>/build/tmp/deploy/rpm/`
  with an `avocado-repo.map`.
- **SDK container images loaded locally**, tagged `avocadolinux/sdk:<year>-<channel>`
  (e.g. `avocadolinux/sdk:2026-edge`). Extension packaging selects its SDK image by
  this tag. Load them with `scripts/sdk-load-containers-local.sh <year>-<channel>`.
- **The extension repos** checked out as a sibling of this repo
  (`../extensions`, holding the `bsp-*` and `ext-*` repos). Auto-detected; override
  with `-E <dir>` or `$AVOCADO_EXTENSIONS_DIR`.

---

## 3. The feed codename (year / channel)

A feed is addressed by a **codename** of the form `<year>/<channel>`, e.g.
`2026/edge`. `dev-repo.sh` builds it from the positional `<year>` argument and the
`--channel` option (default `edge`).

The codename is independent of the Yocto branch. `scarthgap`/`wrynose` is the
**Yocto base**; `2026/edge` is the **Avocado release/channel** that is *built on*
that base. The codename also selects the SDK image tag used to package extensions:
`<year>/<channel>` → `avocadolinux/sdk:<year>-<channel>`. So `2026/edge` packages
against `avocadolinux/sdk:2026-edge`, which must be loaded locally (see
Prerequisites).

---

## 4. `dev-repo.sh` — the one command

```
./scripts/dev-repo.sh [OPTIONS] <year> <target> [target2 ...]
```

| Option | Default | Meaning |
|---|---|---|
| `<year>` | (required) | Feed year / release, 4 digits (e.g. `2026`). |
| `<target>` | (required) | One or more targets (e.g. `imx8mp-evk`). |
| `-c, --channel` | `edge` | Feed channel → codename `<year>/<channel>`. |
| `-r, --repo-dir` | `<repo-root>/_repo` | Where the feed is built/served. |
| `-E, --extensions-dir` | `$AVOCADO_EXTENSIONS_DIR` or `../extensions` | Combined `bsp-*`/`ext-*` repos. |
| `-p, --port` | `8080` | Host port for the repo server. |
| `-i, --release-id` | `dev` | Release id under the feed. Stable id = overwrite in place. |
| `--build-ext` | off | Build extensions before packaging (default: package only). |
| `--clean` | off | Reset just the named target(s) before syncing — see below. |
| `--no-serve` | off | Don't (re)start the server when done. |

Examples:

```bash
./scripts/dev-repo.sh 2026 imx8mp-evk                 # incremental sync + serve
./scripts/dev-repo.sh --clean 2026 imx8mp-evk         # reset imx8mp-evk first
./scripts/dev-repo.sh 2026 imx8mp-evk raspberrypi5    # multiple targets, one feed
./scripts/dev-repo.sh -c stable 2026 imx8mp-evk       # 2026/stable channel
```

---

## 5. Cleaning a target

`--clean` is **target-scoped**: it removes only the dirs that belong exclusively
to the named target(s) and leaves everything else alone. Concretely it deletes,
under both `packages/<codename>/` and `releases/<codename>/<release-id>/`:

- `target/<target>/`
- `target/<target>-ext/`
- `sdk/<target>/`

plus the target's `staging/<release-id>/fragments/<target>-fragment.json`.

It deliberately does **not** touch:

- the content-addressed `_pkgs/` pool (shared by every target),
- shared package-arch dirs (`noarch`, `cortexa53_crypto`, ...) used by sibling
  targets — these self-heal on re-sync because staging overwrites by filename,
- any other target's dirs.

This is what lets you keep several targets in one `_repo` and reset just the one
you're working on. For a full wipe of everything (all targets, content pool
included) just `rm -rf _repo` — that is the only thing `dev-repo.sh` won't do for
you.

---

## 6. Connecting the avocado CLI

The server publishes the same env vars the avocado CLI expects. Print them any
time with:

```bash
./scripts/dev-start-repo.sh --status      # human-readable summary + URLs
./scripts/dev-start-repo.sh --env         # writes .avocado-dev-env you can source
```

Two access paths:

- **From the host** (e.g. `avocado install` on your workstation): use the host
  port. The CLI reads `AVOCADO_REPO_URL`.
  ```bash
  export AVOCADO_REPO_URL="http://localhost:8080"
  avocado install -f
  ```
- **From avocado CLI build/package containers** (which run on the Docker network,
  not on `localhost`): use the **container name as hostname** and join the network.
  ```bash
  export AVOCADO_SDK_REPO_URL="http://avocado-dev-repo"
  export AVOCADO_CONTAINER_NETWORK="avocado-dev-network"
  avocado ext package -e avocado-ext-<name> --target <target> --out-dir out \
      --container-arg "--network" --container-arg "avocado-dev-network"
  ```

> `dev-repo.sh` already sets the SDK release/channel env for the packaging step it
> runs; the variables above are only needed when you invoke the CLI yourself.

The feed is browsable in a web browser at `http://<host>:8080/` — useful for
confirming `repodata/repomd.xml` exists under `/<codename>/sdk/...` and
`/<codename>/target/...`.

### Signature verification

The generated `.repo` files carry two independent switches, and they verify
different things. Setting the wrong one is the common mistake, because the older
variable is named as though it covered metadata and does not.

| Build variable | dnf option written | Verifies | Default |
|---|---|---|---|
| `AVOCADO_REPO_GPGCHECK` | `gpgcheck` | Package signatures | `0` |
| `AVOCADO_REPO_METADATA_GPGCHECK` | `repo_gpgcheck` | The repository index, against a detached `repomd.xml.asc` | `0` |

Enabling `AVOCADO_REPO_METADATA_GPGCHECK` also emits a `gpgkey=` pointing at
`<repo>/repodata/repomd.xml.key`, the public half published beside the signature.

Do not turn either on before the feed you are pointing at actually publishes what
it promises. Whether a client hard-fails or quietly skips the repository depends
on its own `skip_if_unavailable`, so do not rely on a particular failure mode -
confirm the artifact is there first:

```bash
# 200 = the index is signed and metadata verification can be enabled.
# 404 = it is not; leave AVOCADO_REPO_METADATA_GPGCHECK at 0.
curl -s -o /dev/null -w '%{http_code}\n' \
    "${AVOCADO_REPO_URL}/<codename>/sdk/all/repodata/repomd.xml.asc"
```

Package signing is a separate question and no part of the build signs RPMs today,
so `AVOCADO_REPO_GPGCHECK` stays at `0` regardless of what the index does.

Both variables reach every `.repo` section the build installs: the per-target
sections generated by `avocado-sdk-metadata.bb`, and the `[avocado-sdk]` section
the SDK container itself reads, generated by `avocado-sdk-repos.bb`. Both render
through `meta-avocado/lib/avocado_sdk_metadata/repoconf.py`, so setting one
variable is enough - no `.repo` section holds a hardcoded value.

One hardcoded value sits outside that set. `[main] gpgcheck=True` in
`avocado-sdk-repos`' `dnf.conf` is the container-wide default for a repo that
sets nothing. Every section rendered above sets `gpgcheck` explicitly and the
per-repo value wins, so it changes nothing today - but a `.repo` file added to
the container by someone else inherits it, and no build variable reaches it.

The `[avocado-sdk]` section writes no `priority`, so it sits at dnf's default of
99. That is deliberate: `avocado-cli` points `reposdir` at both this file and
the per-target config, and dnf ranks priority across that merged set rather than
per file. The per-target sections hold 1 through N, so 99 keeps `[avocado-sdk]`
below them - where the static file this replaced effectively sat.

---

## 7. What the feed looks like on disk

```
_repo/
├── packages/<codename>/
│   ├── target/<arch-or-target>/      # imx8mp-evk, cortexa53_crypto, noarch, <target>-ext
│   └── sdk/<target-or-all>/
├── releases/<codename>/<release-id>/
│   ├── _pkgs/00..ff/                 # content-addressed RPM pool (shared)
│   ├── target/...   sdk/...          # rendered repodata pointing into _pkgs
│   └── targets.json
└── staging/<release-id>/fragments/   # transient per-target fragments
```

The server mounts three things into the container: `packages/` and `releases/`
roots, plus the **specific release** `releases/<codename>/<release-id>/` as the
"latest" at `/<codename>/`. So the CLI's request for
`/<codename>/sdk/all/repodata/repomd.xml` maps to the rendered metadata for the
release you just built. `dev-repo.sh` passes the exact codename and release id to
the server, so the right release is always the one served.

---

## 8. The two repo-server images

There are intentionally **two** server images — don't confuse them:

| | Dev (`support/package-repo-local/`) | Production (`support/package-repo/`) |
|---|---|---|
| Image tag | `avocadolinux/package-repo:dev-local` | `avocadolinux/package-repo:local` (when built locally) |
| Base | `nginx:alpine` | `fedora` |
| nginx root | `/avocado-repo` (where volumes mount) | `/var/www/html` |
| Metadata | pre-rendered (served as-is) | regenerated in-container (`createrepo_c` + `inotify`) |
| Used by | `dev-start-repo.sh` / `dev-repo.sh` | production serving |

The dev flow pre-renders metadata, so it needs the dumb static server rooted at
`/avocado-repo`. The two use **different tags** so building/tagging the production
image as `:local` never gets picked up by the dev server. `dev-start-repo.sh`
builds `:dev-local` from `support/package-repo-local/` on first use.

---

## 9. Lower-level scripts

`dev-repo.sh` is a thin wrapper. The pieces it orchestrates can be run directly:

| Script | Role |
|---|---|
| `dev-build.sh` | Orchestrates sync + extension packaging for one or more targets. |
| `dev-sync-packages.sh` | Stages a target's RPMs into the feed and renders pooled repodata. |
| `dev-package-extensions.sh` | Packages extensions for a target (`avocado ext package`). |
| `dev-build-extensions.sh` | Builds **then** packages extensions (`--build-ext` path). |
| `dev-start-repo.sh` | Manages the repo server container: start / `--restart` / `--stop` / `--logs` / `--status` / `--env`. |
| `dev-prserv.sh` | Runs a local bitbake PR service for reproducible package revisions. |

All accept `-h/--help`. The extension scripts take `-E/--extensions-dir` (default
`$AVOCADO_EXTENSIONS_DIR`) for the broken-out `bsp-*`/`ext-*` layout.

---

## 10. Troubleshooting

**`404 ... /<codename>/sdk/all/repodata/repomd.xml` on `avocado install`**
The server mounted a different codename/release than you built. Make sure you
restarted via `dev-repo.sh` (which passes `-d <codename> -i <release-id>` to the
server) and not a bare `dev-start-repo.sh --restart` that falls back to its default
codename.

**Browser shows an empty page / nothing served**
The `:dev-local` image isn't the one running — most likely a `package-repo:local`
(production, rooted at `/var/www/html`) was picked up. The dev server roots at
`/avocado-repo`. Confirm with:
```bash
docker ps --format '{{.Image}} {{.Names}}'   # want avocadolinux/package-repo:dev-local
```
Stop and re-run: `./scripts/dev-start-repo.sh --stop && ./scripts/dev-repo.sh <year> <target>`.

**`Error: No release directories found ... Expected directories with format: dev-YYYYMMDD-HHMMSS`**
The extension packager wasn't told which release dir to use. `dev-repo.sh`/`dev-build.sh`
forward `--release-dir`, so use them rather than calling `dev-package-extensions.sh`
bare without `--release-dir`.

**`docker: invalid reference format` during extension packaging**
The SDK image tag resolved empty (`sdk:-`). The codename drives the tag
(`<year>/<channel>` → `sdk:<year>-<channel>`); make sure that image is loaded
(`scripts/sdk-load-containers-local.sh <year>-<channel>`).

**`avocado-sdk-<target>` not found / SDK bootstrap fails with 404**
Same root cause as the first item — the feed for that codename/release isn't being
served at `/<codename>/`. Re-run `dev-repo.sh` and verify with
`curl -sI http://localhost:8080/<codename>/sdk/all/repodata/repomd.xml`.

**`--logs` shows nothing after the server stopped**
The dev container runs with `--rm`, so stopping it removes it (and its logs). Logs
only exist while the server is running.
