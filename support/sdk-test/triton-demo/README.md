
avocado-repo sdk install nativesdk-ganesha -y
avocado-build sysext triton-demo
avocado-build confext triton-demo
mkdir -p _avocado/sdk/sysroots/sysext/etc/extension-release.d
cp _avocado/sdk/sysroots/confext/etc/extension-release.d/extension-release.triton-demo _avocado/sdk/sysroots/sysext/etc/extension-release.d/extension-release.triton-demo

avocado-repo sysext install -y \
  xserver-xorg xserver-xorg-video-nvidia \
  nv-kernel-module-tegra-drm kernel-module-dw-hdmi-cec \
  triton-server triton-client triton-python-backend triton-tensorrt-backend \
  weston weston-init l4t-graphics-demos-wayland weston-examples \
  deepstream-7.1 deepstream-7.1-samples \
  nv-kernel-module-tegra-camera tegra-libraries-camera

mkdir -p /var/lib/extensions/triton-demo /var/lib/confexts/triton-demo
mount -t nfs4 -o port=12049,vers=4 192.168.1.10:/avocado-hitl /var/lib/extensions/triton-demo
mount -t nfs4 -o port=12049,vers=4 192.168.1.10:/avocado-hitl /var/lib/confexts/triton-demo

insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/kernel/drivers/gpu/drm/drm.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/kernel/drivers/gpu/drm/drm_kms_helper.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/updates/drivers/platform/tegra/dce/tegra-dce.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/updates/drivers/video/tegra/tsec/tsecriscv.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/updates/drivers/gpu/host1x-nvhost/host1x-nvhost.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/updates/nvidia.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/updates/nvidia-modeset.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/updates/nvidia-drm.ko modeset=1
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/kernel/drivers/media/cec/core/cec.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/kernel/drivers/gpu/drm/bridge/synopsys/dw-hdmi-cec.ko
insmod /usr/lib/modules/5.15.148-l4t-r36.4-1012.12+g8dc079d5c8c4/updates/drivers/gpu/drm/tegra/tegra-drm.ko

mkdir /tmp/.X11-unix
weston --backend=drm-backend.so

mkdir -p /var/lib/triton
tritonserver --model-repository=/var/lib/triton

