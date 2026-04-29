# Avocado-side overrides on top of upstream meta-qt5's qtwebengine_git.bb.
#
# Wrynose: dropped the local copy of `qtwebengine_git.bb` and its
# `0001-configure.json-remove-python2-dependency.patch`. The local recipe
# was a scarthgap-era copy of upstream meta-qt5; among other staleness
# its chromium SRC_URI used `destsuffix=git/src/3rdparty`, while wrynose
# git fetcher unpacks to `${BB_GIT_DEFAULT_DESTSUFFIX}` (= `${BP}`),
# so the upstream patches couldn't find their target tree at
# `${S}/src/3rdparty`. Upstream master fixed the destsuffix and added
# gcc-15 / glibc-2.43 patches we were missing. This bbappend keeps just
# the avocado-specific deltas.

DEPENDS:append = " python3-html5lib-native"

inherit python3native

# Some chromium scripts expect Python3_EXECUTABLE to be set explicitly.
export Python3_EXECUTABLE = "${PYTHON}"
