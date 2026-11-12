# update-alternatives in the SDK serves two kinds of root. avocado-cli runs it
# on target sysroots (rootfs, initramfs, extensions) with OPKG_OFFLINE_ROOT set,
# and there the registry must stay at the root's /usr/lib, where the target's
# own update-alternatives reads it. nativesdk scriptlets run it in place with no
# offline root, and upstream's path then names the host's /usr/lib, outside the
# SDK. Keep the registry in the SDK for that case only. Drop this once oe-core's
# opkg-utils recipe handles the nativesdk registry itself.
do_install:append:class-nativesdk() {
	if [ -e "${D}${bindir}/update-alternatives" ]; then
		sed -i ${D}${bindir}/update-alternatives \
			-e 's,^ad="$OPKG_OFFLINE_ROOT/usr/lib/opkg/alternatives"$,&\n[ -n "$OPKG_OFFLINE_ROOT" ] || ad="${nonarch_libdir}/opkg/alternatives",'
		grep -qxF '[ -n "$OPKG_OFFLINE_ROOT" ] || ad="${nonarch_libdir}/opkg/alternatives"' ${D}${bindir}/update-alternatives
	fi
}
