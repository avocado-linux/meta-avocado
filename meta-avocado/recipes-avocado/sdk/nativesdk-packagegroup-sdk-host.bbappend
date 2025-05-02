# The nativesdk builds "dummy" package to satisfy the dependency on things like
#  /bin/sh. For the SDK containers, we do not need these since our container image
# has these available and we are installing them in the container image. They actually
# cause conflicts for us since there are already other packages installed that do
# include /bin/sh etc.
# Removing the target dummy package was easy, we just don't include it, however
# the nativesdk-sdk-provides-dummy package is a dependency of the main sdk-host
# package group, so we need to remove it from the RDEPENDS list.
RDEPENDS:${PN}:remove = "nativesdk-sdk-provides-dummy"
