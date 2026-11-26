# Same packaging as the sibling tegra-libraries-multimedia: ship the
# unversioned .so links in the runtime package. Upstream's multimedia-utils
# recipe creates libnvbufsurface.so and libnvbufsurface_nvsci.so but leaves the
# default solib split, which moves both into -dev. The NVIDIA container runtime
# lists /usr/lib/libnvbufsurface.so as a host symlink and skips it silently when
# absent, so a container link with -lnvbufsurface fails. The common include
# already skips the dev-so QA check.
FILES_SOLIBSDEV = ""
SOLIBS = ".so*"
