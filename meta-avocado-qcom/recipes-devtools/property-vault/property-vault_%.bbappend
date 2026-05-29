# property-vault's do_install runs `chown system:system ${D}/etc/build.prop`,
# then do_package_write_rpm calls pwd.getpwuid(<system uid>) and falls back to
# ${RECIPE_SYSROOT}/etc/passwd, which doesn't exist — the upstream recipe
# DEPENDS on useradd-qcom but never inherits useradd, so base-passwd is not
# pulled into DEPENDS and nothing seeds /etc/passwd into the recipe-sysroot.
#
# Inherit useradd here and redeclare the system user/group with the same
# parameters useradd-qcom uses. useradd_base treats already-existing names as
# a no-op (perform_groupadd / perform_useradd in useradd_base.bbclass), so
# this only triggers the recipe-sysroot seeding — no collision with
# useradd-qcom's own group/user creation in the target rootfs.
inherit useradd

USERADD_PACKAGES = "${PN}"
GROUPADD_PARAM:${PN} = "--system system"
USERADD_PARAM:${PN} = "--system --no-create-home --groups system --gid system --shell /sbin/nologin system"
