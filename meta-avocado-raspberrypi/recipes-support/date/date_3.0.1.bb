SUMMARY = "A date and time library based on C++11/14/17."
HOMEPAGE = "https://github.com/HowardHinnant/date.git"
SECTION = "libs"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE.txt;md5=b5d973344b3c7bbf7535f0e6e002d017"

SRC_URI = "git://github.com/HowardHinnant/date.git;protocol=https;nobranch=1;tag=v${PV}"
SRCREV = "6e921e1b1d21e84a5c82416ba7ecd98e33a436d0"

inherit cmake

EXTRA_OECMAKE += " \
    -DENABLE_DATE_TESTING=OFF \
    -DUSE_SYSTEM_TZ_DB=ON \
"
