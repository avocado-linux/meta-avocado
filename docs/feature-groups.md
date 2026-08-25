# Feature Groups: Composing a Build from Minimal to Full

Avocado OS image content is opt-in. `packagegroup-avocado-extra` is a composing
packagegroup: it carries a small always-on base set, then pulls one
`packagegroup-avocado-feature-<group>` for each token listed in the kas-set
`AVOCADO_FEATURE_GROUPS` variable. You select content by stacking
`kas/feature/<group>.yml` fragments onto a machine; each fragment pulls the
vendor layer that group needs and appends its token.

This guide is for maintainers composing builds. It covers the build mechanics,
the available groups, and worked recipes from bare minimal to full featured.

---

## 1. How composition works

A build is a machine file plus any number of feature fragments, combined with
kas colon-overlay syntax:

```bash
kas build kas/machine/<machine>.yml:kas/feature/<group>.yml:kas/feature/<group>.yml
```

- `kas/machine/<machine>.yml` selects the board, base layers, and the
  `avocado-distro` target.
- Each `kas/feature/<group>.yml` does two things: it includes the group's vendor
  layer (if any) and appends the group's token to `AVOCADO_FEATURE_GROUPS`.
- At parse time `packagegroup-avocado-extra` expands every token into a
  `packagegroup-avocado-feature-<token>` runtime dependency.

Boards are **minimal by default**: with no feature fragment appended,
`AVOCADO_FEATURE_GROUPS` is empty and the image gets the always-on base content
only.

`kas/feature/complete.yml` is an umbrella that includes every group fragment
except `ai`. No board file includes it; append it explicitly to ship the full
set (see §3).

## 2. Feature groups

| Group        | Token         | Adds                                            | Vendor layer            | Requires |
|--------------|---------------|-------------------------------------------------|-------------------------|----------|
| system-base  | `system-base` | core utilities, cockpit, redis, uv, vim         | (none, oe-core/meta-oe) | -        |
| networking   | `networking`  | NetworkManager, openssh, bluez5, wireguard      | (none)                  | -        |
| multimedia   | `multimedia`  | GStreamer, opencv, v4l-utils                    | (none)                  | -        |
| python       | `python`      | python3 runtime set (flask, requests, etc.)     | (none)                  | -        |
| graphics     | `graphics`    | weston, wayland                                 | meta-wayland            | DISTRO_FEATURES opengl |
| qt           | `qt`          | Qt5 stack incl. qtwebengine                     | meta-qt5                | DISTRO_FEATURES opengl (wayland) |
| browsers     | `browsers`    | chromium-ozone-wayland                          | meta-browser            | DISTRO_FEATURES opengl wayland |
| cameras      | `cameras`     | librealsense2, Basler pylon                     | meta-intel-realsense, meta-basler-tools | **unavailable on wrynose** |
| cloud-aws    | `cloud-aws`   | greengrass-bin, aws-iot-device-client           | meta-aws                | **unavailable on wrynose** |
| java         | `java`        | openjdk-17 jdk/jre                              | meta-openjdk-temurin (base) | aarch64/x86_64 |
| containers   | `containers`  | docker, podman, podman-compose, k3s             | meta-virtualization     | DISTRO_FEATURES virtualization |

Layer-only fragments add a vendor layer but no token (they provide recipes other
content builds against, not image packages directly): `clang.yml`,
`python-ai.yml`, `ros.yml`, `virtualization.yml`.

### Container Dev Mode

`avocado container dev up` needs two groups in the feed, and neither is in the
base: `docker` comes from `containers`, and `sshd-dev`'s `openssh` comes from
`networking`. A board built without them boots and is then unreachable - `up`
fails at the SSH bootstrap, before the dev loop exists.

`kas/feature/container-dev.yml` aggregates both so this stays one append:

```bash
kas build kas/machine/imx93-frdm.yml:kas/feature/container-dev.yml
```

It appends no token of its own and has no packagegroup - it is a convenience
include, like `complete.yml`. When a container-dev extension starts needing a
third group, add it there rather than widening the base packagegroup.

### Groups this branch cannot build

`cameras`, `cloud-aws` and `ros` are in tree but not wired into
`complete.yml`. Their vendor layers - meta-basler-tools,
meta-intel-realsense, meta-aws and meta-ros - have no wrynose branch, and each
declares a `LAYERSERIES_COMPAT` that predates wrynose, so provisioning one fails
the compatibility check and takes the whole build down rather than skipping a
group. The fragments keep their scarthgap pins deliberately: including one fails
loudly at parse rather than silently shipping less than asked for. Repin the
fragment and add its `complete.yml` line back in the same commit.

Two members are missing from groups for the same reason: `graphics` drops
wpewebkit, wpebackend-fdo and cog (meta-webkit), and `system-base` drops
cryptoauthlib (meta-atmel) and livebook (meta-erlang). See
[migrations/scarthgap-to-wrynose.md](migrations/scarthgap-to-wrynose.md) for the
per-layer condition each one is waiting on.

## 3. Build recipes

### Bare minimal (base content only)

Any machine with no feature fragment. This is now the default for every board.

```bash
kas build kas/machine/qemux86-64.yml
```

### Minimal plus a few groups

Stack only the groups you want. Always-on groups need no vendor layer. A
workflow that needs a booted, reachable board (networking, ssh, python) composes
those essentials explicitly:

```bash
kas build kas/machine/raspberrypi5.yml:kas/feature/system-base.yml:kas/feature/networking.yml:kas/feature/python.yml
```

### Adding graphics / Qt / browsers

These resolve to empty unless the machine sets the matching `DISTRO_FEATURES`.
A machine that already sets `opengl wayland` only needs the fragments:

```bash
kas build kas/machine/<gpu-machine>.yml:kas/feature/graphics.yml:kas/feature/qt.yml:kas/feature/browsers.yml
```

### Full featured

Every board is minimal by default, so ship the full set by appending the
umbrella explicitly:

```bash
kas build kas/machine/imx8mp-evk.yml:kas/feature/complete.yml
```

The same append works on any machine:

```bash
kas build kas/machine/qemuarm64.yml:kas/feature/complete.yml
```

## 4. Notes for maintainers

- Adding a fragment a machine cannot satisfy is harmless: the group's
  packagegroup resolves to an empty set (the guards are preserved from the
  original monolith), though the vendor layer is still fetched and parsed.
- The SDK mirrors the target: `avocado-pkg-sdk-extra` pulls the Qt5 nativesdk
  toolchain only when the `qt` token is present, so an SDK build that opts out
  of `qt` does not require meta-qt5.
- Board files do not include the umbrella; a board is minimal by default. To
  ship the full set, append `:kas/feature/complete.yml` at build time rather
  than adding an include.
