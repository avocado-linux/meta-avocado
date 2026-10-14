# Enable ModemManager integration and package the wwan device plugin.
#
# Without modemmanager in PACKAGECONFIG, NM is built with -Dmodem_manager=false
# and libnm-device-plugin-wwan.so is not compiled.  NM then marks any wwan
# interface as a generic unmanaged device and cannot autoconnect GSM/LTE
# profiles even when ModemManager is running.
#
# modemmanager — passes -Dmodem_manager=true to meson, builds the wwan plugin,
#                adds build/runtime deps on modemmanager and
#                mobile-broadband-provider-info.
# wwan         — packaging flag: puts libnm-device-plugin-wwan.so and
#                libnm-wwan.so into the networkmanager-wwan package and
#                adds it to RRECOMMENDS of the meta networkmanager package.

PACKAGECONFIG:append = " modemmanager wwan"

# The vala API needs GObject introspection data, which OE drops on machines
# without qemu-usermode (x86-64-v4). meta-oe only checks the distro feature.
PACKAGECONFIG:remove = "${@'' if d.getVar('GI_DATA_ENABLED') == 'True' else 'vala'}"
