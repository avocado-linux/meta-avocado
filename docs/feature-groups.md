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

With no feature fragment, `AVOCADO_FEATURE_GROUPS` is empty and the image gets
the always-on base content only.

`kas/feature/complete.yml` is an umbrella that includes every group fragment
except `ai`. Client vendor and machine files include it to ship the full set.

## 2. Feature groups

| Group        | Token         | Adds                                            | Vendor layer            | Requires |
|--------------|---------------|-------------------------------------------------|-------------------------|----------|
| system-base  | `system-base` | core utilities, cockpit, redis, uv, vim         | (none, oe-core/meta-oe) | -        |
| networking   | `networking`  | NetworkManager, openssh, bluez5, wireguard      | (none)                  | -        |
| multimedia   | `multimedia`  | GStreamer, opencv, v4l-utils                    | (none)                  | -        |
| python       | `python`      | python3 runtime set (flask, requests, etc.)     | (none)                  | -        |
| graphics     | `graphics`    | weston, wayland, wpewebkit                      | meta-wayland, meta-webkit | DISTRO_FEATURES opengl |
| qt           | `qt`          | Qt5 stack incl. qtwebengine                     | meta-qt5                | DISTRO_FEATURES opengl (wayland) |
| browsers     | `browsers`    | chromium-ozone-wayland                          | meta-browser            | DISTRO_FEATURES opengl wayland |
| cameras      | `cameras`     | librealsense2, Basler pylon                     | meta-intel-realsense, meta-basler-tools | DISTRO_FEATURES opengl; Basler aarch64 only |
| cloud-aws    | `cloud-aws`   | greengrass-bin, aws-iot-device-client           | meta-aws                | aarch64/x86_64 |
| java         | `java`        | openjdk-17 jdk/jre                              | meta-openjdk-temurin (base) | aarch64/x86_64 |
| containers   | `containers`  | docker, podman, podman-compose, k3s             | meta-virtualization     | DISTRO_FEATURES virtualization |
| ai           | `ai`          | DeepX NPU runtime (dx-driver, dx-rt, dx-stream) | meta-deepx-m1           | MACHINE_FEATURES deepx |

Layer-only fragments add a vendor layer but no token (they provide recipes other
content builds against, not image packages directly): `clang.yml`,
`python-ai.yml`, `ros.yml`.

## 3. Build recipes

### Bare minimal (base content only)

A machine with no feature fragment. The smallest bring-up image.

```bash
kas build kas/machine/qemux86-64.yml
```

### Minimal plus a few groups

Stack only the groups you want. Always-on groups need no vendor layer:

```bash
kas build kas/machine/qemuarm64.yml:kas/feature/system-base.yml:kas/feature/networking.yml:kas/feature/multimedia.yml
```

### Adding graphics / Qt / browsers

These resolve to empty unless the machine sets the matching `DISTRO_FEATURES`.
A machine that already sets `opengl wayland` only needs the fragments:

```bash
kas build kas/machine/<gpu-machine>.yml:kas/feature/graphics.yml:kas/feature/qt.yml:kas/feature/browsers.yml
```

### Full featured

Pull every group through the umbrella (this is what client targets do):

```bash
kas build kas/machine/imx8mp-evk.yml
```

To compose it onto a bare machine manually:

```bash
kas build kas/machine/qemuarm64.yml:kas/feature/complete.yml
```

### DeepX (NPU) boards

`ai` is excluded from `complete.yml` because it is `MACHINE_FEATURES`-gated. A
deepx board stacks both (the grinn-astra machine file already includes
`complete.yml` and `ai.yml`):

```bash
kas build kas/machine/grinn-astra-1680-sbc.yml
```

To compose it manually onto another deepx machine:

```bash
kas build kas/machine/<deepx-machine>.yml:kas/feature/complete.yml:kas/feature/ai.yml
```

## 4. Notes for maintainers

- Adding a fragment a machine cannot satisfy is harmless: the group's
  packagegroup resolves to an empty set (the guards are preserved from the
  original monolith), though the vendor layer is still fetched and parsed.
- `complete.yml` deliberately omits `ai`; including it on non-deepx hardware
  would pull an unbuildable `dx-*` recipe. Add `ai.yml` only on deepx boards.
- The SDK mirrors the target: `avocado-pkg-sdk-extra` pulls the Qt5 nativesdk
  toolchain only when the `qt` token is present, so an SDK build that opts out
  of `qt` does not require meta-qt5.
- When adding a new client machine that should ship the full set, include
  `kas/feature/complete.yml` (and `ai.yml` if it is a deepx board) rather than
  listing groups individually.
