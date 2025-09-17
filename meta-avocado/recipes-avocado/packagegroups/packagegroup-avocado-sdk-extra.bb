DESCRIPTION = "Packagegroup for Avocado SDK Extra"
LICENSE = "Apache-2.0"

inherit packagegroup
PACKAGES = "${PN}"

SDK_TOOLCHAIN_DEPENDS = " \
  nativesdk-avocado-hitl \
  nativesdk-bmaptool \
  nativesdk-coreutils \
  nativesdk-util-linux \
  nativesdk-util-linux-agetty \
  nativesdk-util-linux-blkdiscard \
  nativesdk-util-linux-blkid \
  nativesdk-util-linux-blkzone \
  nativesdk-util-linux-blockdev \
  nativesdk-util-linux-cal \
  nativesdk-util-linux-cfdisk \
  nativesdk-util-linux-chfn-chsh \
  nativesdk-util-linux-chrt \
  nativesdk-util-linux-column \
  nativesdk-util-linux-dmesg \
  nativesdk-util-linux-eject \
  nativesdk-util-linux-fallocate \
  nativesdk-util-linux-fdisk \
  nativesdk-util-linux-findfs \
  nativesdk-util-linux-findmnt \
  nativesdk-util-linux-flock \
  nativesdk-util-linux-fsck \
  nativesdk-util-linux-fsck.cramfs \
  nativesdk-util-linux-fsfreeze \
  nativesdk-util-linux-fstrim \
  nativesdk-util-linux-getopt \
  nativesdk-util-linux-hardlink \
  nativesdk-util-linux-hexdump \
  nativesdk-util-linux-hwclock \
  nativesdk-util-linux-ionice \
  nativesdk-util-linux-ipcrm \
  nativesdk-util-linux-ipcs \
  nativesdk-util-linux-kill \
  nativesdk-util-linux-last \
  nativesdk-util-linux-logger \
  nativesdk-util-linux-look \
  nativesdk-util-linux-losetup \
  nativesdk-util-linux-lsblk \
  nativesdk-util-linux-lscpu \
  nativesdk-util-linux-lslocks \
  nativesdk-util-linux-lsns \
  nativesdk-util-linux-mcookie \
  nativesdk-util-linux-mesg \
  nativesdk-util-linux-mkfs \
  nativesdk-util-linux-mkfs.cramfs \
  nativesdk-util-linux-mkswap \
  nativesdk-util-linux-more \
  nativesdk-util-linux-mount \
  nativesdk-util-linux-mountpoint \
  nativesdk-util-linux-namei \
  nativesdk-util-linux-nologin \
  nativesdk-util-linux-nsenter \
  nativesdk-util-linux-partx \
  nativesdk-util-linux-pivot-root \
  nativesdk-util-linux-prlimit \
  nativesdk-util-linux-readprofile \
  nativesdk-util-linux-rename \
  nativesdk-util-linux-renice \
  nativesdk-util-linux-reset \
  nativesdk-util-linux-rev \
  nativesdk-util-linux-rfkill \
  nativesdk-util-linux-rtcwake \
  nativesdk-util-linux-runuser \
  nativesdk-util-linux-script \
  nativesdk-util-linux-scriptlive \
  nativesdk-util-linux-scriptreplay \
  nativesdk-util-linux-setarch \
  nativesdk-util-linux-setpriv \
  nativesdk-util-linux-setsid \
  nativesdk-util-linux-su \
  nativesdk-util-linux-sulogin \
  nativesdk-util-linux-swapoff \
  nativesdk-util-linux-swapon \
  nativesdk-util-linux-switch-root \
  nativesdk-util-linux-taskset \
  nativesdk-util-linux-uclampset \
  nativesdk-util-linux-umount \
  nativesdk-util-linux-unshare \
  nativesdk-util-linux-utmpdump \
  nativesdk-util-linux-uuidd \
  nativesdk-util-linux-uuidgen \
  nativesdk-util-linux-uuidparse \
  nativesdk-util-linux-wall \
  nativesdk-util-linux-wdctl \
  nativesdk-util-linux-whereis \
  nativesdk-util-linux-wipefs \
  nativesdk-util-linux-write \
  nativesdk-util-linux-zramctl \
  nativesdk-jq \
  nativesdk-findutils \
  nativesdk-grep \
  nativesdk-sed \
  nativesdk-gawk \
  nativesdk-tar \
  nativesdk-gzip \
  nativesdk-bash \
  nativesdk-fwup \
  nativesdk-ganesha \
  nativesdk-gptfdisk \
  nativesdk-mkfat \
  nativesdk-python3-pip \
  nativesdk-python3-pyyaml \
  nativesdk-qemu \
  nativesdk-qemu-helper \
  nativesdk-strace \
  nativesdk-openssh-scp \
  nativesdk-openssh-ssh \
  nativesdk-elixir \
  nativesdk-erlang \
  nativesdk-rebar3 \
  nativesdk-nodejs \
  nativesdk-git \
  nativesdk-ca-certificates \
  packagegroup-rust-cross-canadian-${MACHINE} \
  ${@bb.utils.contains('DISTRO_FEATURES', 'wayland', 'nativesdk-wayland-tools nativesdk-wayland-dev', '', d)} \
"

SDK_SYSROOT_DEPENDS = " \
  ${@multilib_pkg_extend(d, 'packagegroup-core-standalone-sdk-target')} \
  ${@multilib_pkg_extend(d, 'libstd-rs')} \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_DEPENDS} \
  ${SDK_SYSROOT_DEPENDS} \
"
