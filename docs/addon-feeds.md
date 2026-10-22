# Add-on feeds

An add-on feed is a set of packages built alongside the base feed and
published beside it, never inside it. A project opts in by name:

```yaml
distro:
  release: 2026
  channel: next
  feeds: [ros2-jazzy]
```

`ros2-jazzy` is the first add-on. This page describes the contract, how the
layer builds and publishes an add-on, and how to roll one out to more targets
or add a new one.

## Why add-ons exist

Some stacks change the build they join. Including meta-ros alone changed 179
base recipes on a Raspberry Pi 5 build:
- conf files its `layer.conf` requires;
- bbappends to python3, bash, boost, yaml-cpp and others;
- its own copy of libyaml.

Every base package in the feed would then differ because of ROS, for every
project, whether it uses ROS or not. And two variants of one stack (ROS Jazzy
and Humble) ship the same package names at different versions, so one repo
can only ever carry one of them.

An add-on keeps the base feed exactly as it is without the stack, and gives
each variant a repo of its own that a project enables explicitly.

## The contract

For every target `<m>` that publishes add-on `<a>`:

- **Two repos, always both.**
  - `target/<m>-<a>` holds the target packages.
  - `sdk/<m>-<a>` holds the SDK (`*_avocadosdk`) packages, and is empty when
    the add-on has none.

  A client enables both halves of every add-on it is asked for, so an add-on
  that later ships SDK tools needs no change in any project.
- **Listed in the channel's `targets.json`** under `<m>`, beside the base repos.
  Clients read it to check that a requested add-on exists for the target.
- **Disjoint from the base feed.** An add-on never carries a package name the
  base repos ship. A base package the add-on's build rebuilt from the same
  sstate is left out of the add-on, and must be byte-identical to the base copy.
  `scripts/addon-feed-stage.sh` enforces both rules and fails the publish
  otherwise.
- **Built in the same build as the base.** Same layers, same sstate, same base
  packages: an add-on package is always linked against exactly the base
  packages a device installs.

Because of the disjointness rule, an add-on's position in `distro.feeds`
never changes which package wins against the base feed. Position only matters
against other feeds a project lists, such as its own private feed.

## How the layer builds one

An add-on is a multiconfig with the add-on's name. `ros2-jazzy` is declared in
`kas/feature/robotics.yml`:

```
BBMULTICONFIG:append:avocado-raspberrypi5 = " ros2-jazzy"
AVOCADO_ADDON_FEEDS:append:avocado-raspberrypi5 = " ros2-jazzy"
AVOCADO_ADDON_RECIPES[ros2-jazzy] = "packagegroup-avocado-feature-robotics ..."
```

The first two lines are per machine, for the machines the add-on has been
verified on (see "Rolling an add-on out to more targets").

The multiconfig itself is `meta-avocado-distro/conf/multiconfig/ros2-jazzy.conf`.
It sets its own `TMPDIR`, so its deploy tree is separate from the base's.

`avocado-distro` inherits `avocado-addon-feeds`, which adds a multiconfig
dependency on every `AVOCADO_ADDON_RECIPES[<a>]` recipe. A normal build
therefore produces the add-on too:

```sh
kas build kas/machine/<m>.yml:kas/feature/complete.yml
```

Nothing from the add-on enters the base deploy tree, unlike the alternate
kernels of `avocado-multikernel`.

### Keeping the base untouched

The default config must build exactly as it would without the add-on:

1. **Mask the stack's layers in the default config.** `ros.yml` adds
   `/meta-ros/` to `BBMASK` through `AVOCADO_ROS_BBMASK`; the multiconfig
   replaces that variable to unmask them.
2. **Mask, in the multiconfig, anything that changes a base recipe:** bbappends
   to base recipes, and recipes that replace a base recipe under the same
   name (meta-ros's libyaml). Keep one only if the base feed does not ship
   that recipe. meta-ros's libeigen bbappend stays: the base feed has no
   libeigen, and ROS needs the package it creates.
3. **Replace conf-level changes through BBPATH.** Global settings a layer's
   `layer.conf` requires apply to every multiconfig and cannot be masked. When
   the base already provides what they set, put an empty file at the same
   path in `meta-avocado-distro`, and list the path in
   `AVOCADO_ADDON_CONF_SHADOWS`. Example:
   `conf/ros-distro/include/enable-fortran.inc`. The replacement works only
   while `meta-avocado-distro` is ahead of the add-on's layers in BBPATH, so
   `avocado-addon-feeds` fails the parse if a listed file resolves anywhere else.

To check the result, dump task signatures for the default config with and
without the feature:

```sh
kas shell <chain> -c 'bitbake -S none avocado-complete'
```

Compare the `tmp/stamps/**/*.sigdata.*` sets the two runs write. Every base
task must hash the same. Any recipe that changes is a leak; trace it to its
variable with the two sigdata files.

The publish guard is the second line of defense. At publish time it catches a
recipe-level difference between the two configs, as drift or shadow. It
cannot see a conf-level leak, which changes the base and the add-on alike;
only the signature comparison against a build without the add-on shows that.

## How it is published

`scripts/addon-feed-stage.sh` selects one half of an add-on from the
multiconfig's deploy tree and applies the guard:

```sh
scripts/addon-feed-stage.sh --base build-<m>/build/tmp/deploy/rpm \
    --addon build-<m>/build/tmp-<a>/deploy/rpm --role target --out <dir>
```

It writes `<dir>/<arch_dir>/` with repodata, the same shape as the base feed's
arch dirs after `bitbake package-index`. The target half must have packages;
the SDK half may be empty. Package names come from repodata it generates with
`createrepo_c`, so it needs `createrepo_c` and `python3`, not `rpm`. A package
that obsoletes a base package counts as shadowing it. On any failure `<dir>`
is left as it was. The feed pipeline runs it once per role for each machine's
build, and publishes the result as `target/<m>-<a>` and `sdk/<m>-<a>`.

In CI every multiconfig shares the default config's sstate and download
directories (`kas/ci/mirrors.yml`), so an add-on's multiconfig reuses the
base's objects, and the byte-identity check holds there as it does locally.

For a local feed, `scripts/dev-sync-addon-feed.sh` does the same into a dev
repo after `dev-sync-packages.sh`, and lists the add-on in `targets.json`:

```sh
./scripts/dev-sync-addon-feed.sh -r _repo -d 2026/next -i dev \
    -b build-<m> -a ros2-jazzy <m>
```

Tests: `scripts/test-addon-feed-stage.sh`.

## Rolling an add-on out to more targets

An add-on is built only for the machines its feature declares it for, with a
machine override on `BBMULTICONFIG` and `AVOCADO_ADDON_FEEDS`.
`kas/feature/complete.yml` includes `kas/feature/robotics.yml` for every
machine, but `ros2-jazzy` is declared for `avocado-raspberrypi5` only; every
other machine builds as if ROS were absent.

For each new target, before adding its override:
1. **Build it once and run the signature check above** for that machine's
   layer set. BSP layers can carry their own bbappends to recipes the add-on
   rebuilds, which shows up as drift or shadow.
2. **Publish it to a local feed** with `dev-sync-addon-feed.sh` and install it
   from a project (`distro.feeds: [<a>]`).
3. **Boot it on the hardware** and run something from the add-on.

Then add the machine's override:

```
BBMULTICONFIG:append:avocado-<m> = " ros2-jazzy"
AVOCADO_ADDON_FEEDS:append:avocado-<m> = " ros2-jazzy"
```

A target that does not publish the add-on refuses it in the CLI by name,
listing the targets that do.

## Adding another add-on

Any stack that would change the base build, or that comes in mutually
exclusive variants, fits the same pattern: a browser or web stack, Qt5 next
to Qt6, another ROS distribution.

1. **Write a kas feature** that adds the stack's layers, masks them for the
   default config, and declares the add-on (`BBMULTICONFIG`,
   `AVOCADO_ADDON_FEEDS`, `AVOCADO_ADDON_RECIPES[<a>]`).
2. **Write `meta-avocado-distro/conf/multiconfig/<a>.conf`** with its own
   `TMPDIR` and `BUILDHISTORY_DIR`, and the masks for its bbappends to base
   recipes.
3. **Run the signature check**, then a local publish, then a project install.

An add-on's name is its multiconfig's name, its repo suffix, and the name
projects write. It must match `[A-Za-z0-9][A-Za-z0-9._-]*`, must not be `ext`
or end in `-ext` (the extension feed) or `-sdk` (an add-on's SDK half), and
must not make `<m>-<a>` the name of another machine.

### Variants of one stack

Two variants of one stack (Jazzy and Humble) are two add-ons, but not
necessarily in one build. meta-ros's per-distribution layers require their
own global configuration from `layer.conf`, and BBLAYERS is shared by every
multiconfig, so two ROS distributions cannot share one bitbake run. A second
variant needs its own kas build of the same machine, published the same way.

## The SDK half

The SDK half exists from the start, and is empty while an add-on has no
SDK packages. Building SDK packages for an add-on (for example ROS host
tools) is not wired yet. It takes the same two steps on the SDK side:
`avocado-sdk` inherits `avocado-addon-feeds` with its own recipe list, and the
SDK builds stage with `--role sdk`. Projects need no change: they already
enable both halves.
