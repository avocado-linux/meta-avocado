# Systemd Recipe Backport Changes

This document describes the changes made to the systemd recipes in
`meta-avocado-distro/recipes-core/systemd/` relative to the upstream
`openembedded-core/meta/recipes-core/systemd/` (OE-Core) recipes.

All changes target compatibility with the Yocto version / BitBake conventions
used by the Avocado distro layer. The upstream OE-Core recipes use newer
BitBake features (`UNPACKDIR`, `FILESYSTEM_PERMS_TABLES`, `tag=` in SRC_URI,
and the `meson` class with install-tag support) that are not yet available or
behave differently in the Avocado build environment.

---

## Summary of Change Categories

| # | Category | Affected Files |
|---|----------|---------------|
| 1 | `UNPACKDIR` → `WORKDIR` | `systemd_258.1.bb`, `systemd-conf_1.0.bb`, `systemd-compat-units.bb` |
| 2 | `FILESYSTEM_PERMS_TABLES` → `VOLATILE_LOG_DIR` / `VOLATILE_TMP_DIR` | `systemd_258.1.bb` |
| 3 | SRC_URI `tag=` removal + explicit `S` definition | `systemd.inc` |
| 4 | `meson` → `meson_tags` class | `systemd-systemctl-native_258.1.bb` |

---

## 1. `UNPACKDIR` → `WORKDIR`

**Files:** `systemd_258.1.bb`, `systemd-conf_1.0.bb`, `systemd-compat-units.bb`

### Rationale

Upstream OE-Core has migrated to using the `UNPACKDIR` variable to reference
the directory where `SRC_URI` files are unpacked. This variable was introduced
in newer versions of BitBake / OE-Core to separate the unpack directory from
the general working directory. In the Avocado build environment, `UNPACKDIR` is
not available, so all references are reverted to the traditional `WORKDIR`.

### Changes in `systemd_258.1.bb`

Eight `install` commands and one `find` loop were updated:

```diff
-	for rule in $(find ${UNPACKDIR} -maxdepth 1 -type f -name "*.rules"); do
+	for rule in $(find ${WORKDIR} -maxdepth 1 -type f -name "*.rules"); do

-	install -m 0644 ${UNPACKDIR}/00-create-volatile.conf ${D}${nonarch_libdir}/tmpfiles.d/
+	install -m 0644 ${WORKDIR}/00-create-volatile.conf ${D}${nonarch_libdir}/tmpfiles.d/

-	install -m 0755 ${UNPACKDIR}/init ${D}${sysconfdir}/init.d/systemd-udevd
+	install -m 0755 ${WORKDIR}/init ${D}${sysconfdir}/init.d/systemd-udevd

-	install -m 0644 ${UNPACKDIR}/00-hostnamed-network-user.conf ${D}${systemd_system_unitdir}/systemd-hostnamed.service.d/
+	install -m 0644 ${WORKDIR}/00-hostnamed-network-user.conf ${D}${systemd_system_unitdir}/systemd-hostnamed.service.d/

-	install -m 0644 ${UNPACKDIR}/org.freedesktop.hostname1_no_polkit.conf ${D}${datadir}/dbus-1/system.d/
+	install -m 0644 ${WORKDIR}/org.freedesktop.hostname1_no_polkit.conf ${D}${datadir}/dbus-1/system.d/

-	install -Dm 0644 ${UNPACKDIR}/99-default.preset ${D}${systemd_unitdir}/system-preset/99-default.preset
+	install -Dm 0644 ${WORKDIR}/99-default.preset ${D}${systemd_unitdir}/system-preset/99-default.preset

-	install -Dm 0644 ${UNPACKDIR}/systemd-pager.sh ${D}${sysconfdir}/profile.d/systemd-pager.sh
+	install -Dm 0644 ${WORKDIR}/systemd-pager.sh ${D}${sysconfdir}/profile.d/systemd-pager.sh
```

### Changes in `systemd-conf_1.0.bb`

The `S = "${UNPACKDIR}"` assignment was removed (not needed when using
`WORKDIR` directly), and five `install` commands were updated:

```diff
-S = "${UNPACKDIR}"
-
 do_install() {
-	install -D -m0644 ${S}/journald.conf ...
-	install -D -m0644 ${S}/logind.conf ...
-	install -D -m0644 ${S}/system.conf ...
+	install -D -m0644 ${WORKDIR}/journald.conf ...
+	install -D -m0644 ${WORKDIR}/logind.conf ...
+	install -D -m0644 ${WORKDIR}/system.conf ...

-	install -D -m0644 ${S}/wired.network ...
+	install -D -m0644 ${WORKDIR}/wired.network ...

-	install -D -m0644 ${S}/system.conf-qemuall ...
+	install -D -m0644 ${WORKDIR}/system.conf-qemuall ...
```

### Changes in `systemd-compat-units.bb`

```diff
-S = "${UNPACKDIR}"
+S = "${WORKDIR}"
```

---

## 2. `FILESYSTEM_PERMS_TABLES` → `VOLATILE_LOG_DIR` / `VOLATILE_TMP_DIR`

**File:** `systemd_258.1.bb`

### Rationale

Upstream OE-Core uses `FILESYSTEM_PERMS_TABLES` to determine whether volatile
log and tmp directories are configured. This mechanism checks for the presence
of specific permission table files (`files/fs-perms-volatile-log.txt` and
`files/fs-perms-volatile-tmp.txt`). The Avocado layer uses the more direct
boolean variables `VOLATILE_LOG_DIR` and `VOLATILE_TMP_DIR` instead, which is
the convention used in older OE-Core releases.

### Changes

**Volatile log directory check (line 308):**

```diff
-	if ${@bb.utils.contains('FILESYSTEM_PERMS_TABLES', 'files/fs-perms-volatile-log.txt', 'true', 'false', d)}; then
+	if "${@'true' if oe.types.boolean(d.getVar('VOLATILE_LOG_DIR')) else 'false'}"; then
```

**Volatile tmp directory check (line 322):**

```diff
-	if ! ${@bb.utils.contains('FILESYSTEM_PERMS_TABLES', 'files/fs-perms-volatile-tmp.txt', 'true', 'false', d)}; then
+	if [ "${VOLATILE_TMP_DIR}" != "yes" ]; then
```

---

## 3. SRC_URI `tag=` Removal and Explicit `S` Definition

**File:** `systemd.inc`

### Rationale

Upstream OE-Core's `SRC_URI` includes `tag=v${PV}` as a parameter on the git
fetcher URI. This feature requires a BitBake version that supports the `tag=`
parameter for git sources. The Avocado layer removes this parameter (relying
solely on `SRCREV` for source pinning) and explicitly sets `S = "${WORKDIR}/git"`
to define the source directory, which is the traditional convention for git
fetcher recipes.

### Changes

```diff
-SRC_URI = "git://github.com/systemd/systemd.git;protocol=https;branch=${SRCBRANCH};tag=v${PV}"
+SRC_URI = "git://github.com/systemd/systemd.git;protocol=https;branch=${SRCBRANCH}"
+
+S = "${WORKDIR}/git"
```

---

## 4. `meson` → `meson_tags` Class Inheritance

**File:** `systemd-systemctl-native_258.1.bb`

### Rationale

Upstream OE-Core uses the standard `meson` bbclass which, in newer versions,
includes built-in support for `MESON_TARGET` and `MESON_INSTALL_TAGS`. The
Avocado layer does not have this support in its version of the `meson` class,
so it inherits a custom `meson_tags` class that provides the tag-based install
functionality.

### Changes

```diff
-inherit pkgconfig meson native
+inherit pkgconfig meson_tags native
```

---

## Files with No Changes (Identical to Upstream)

The following files are identical between the Avocado layer and upstream
OE-Core:

- `dlopen-deps.inc`
- `systemd-boot_258.1.bb`
- `systemd-bootconf_1.00.bb`
- `systemd-boot-native_258.1.bb`
- `systemd-machine-units_1.0.bb`
- `systemd-serialgetty.bb`
- `systemd/` subdirectory (all files except `zram-generator.conf`)
- `systemd-conf/` subdirectory (all files)

## Avocado-Only Files (Not Present in Upstream)

The following files exist only in the Avocado layer and are not backported from
upstream:

- `nativesdk-systemd-systemctl_257.6.bb` — nativesdk variant of systemctl
- `systemd_%.bbappend` — bbappend for distro-specific customizations
- `systemd-zram-generator_1.2.1.bb` — zram-generator recipe
- `systemd-zram-generator-crates.inc` — Rust crate dependencies for zram-generator
- `systemd/zram-generator.conf` — zram-generator configuration file
