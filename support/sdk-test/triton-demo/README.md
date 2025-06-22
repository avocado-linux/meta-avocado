mkdir -p /opt/_avocado/sdk/usr/var/lib/nfs
ln -s /tmp /opt/_avocado/sdk/usr/var/lib/nfs/ganesha
avocado-repo sdk install nativesdk-ganesha -y
avocado-build sysext triton-demo
avocado-build confext triton-demo
mkdir -p _avocado/sdk/sysroots/sysext/etc/extension-release.d
cp _avocado/sdk/sysroots/confext/etc/extension-release.d/extension-release.triton-demo _avocado/sdk/sysroots/sysext/etc/extension-release.d/extension-release.triton-demo

avocado-repo sysext install -y \
  xserver-xorg xserver-xorg-video-nvidia \
  nv-kernel-module-tegra-drm kernel-module-dw-hdmi-cec \
  triton-server triton-client triton-python-backend \
  triton-tensorrt-backend triton-onnxruntime-backend \
  weston weston-init weston-examples \
  deepstream-7.1 deepstream-7.1-samples \
  nv-kernel-module-tegra-camera tegra-libraries-camera \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  kernel-module-uvcvideo nvgstapps


mkdir -p /var/lib/extensions/triton-demo /var/lib/confexts/triton-demo
mount -t nfs4 -o port=12049,vers=4,hard,timeo=600,retrans=2,acregmin=0,acregmax=1,acdirmin=0,acdirmax=1,lookupcache=none 192.168.1.10:/avocado-hitl /var/lib/confexts/triton-demo
mount -t nfs4 -o port=12049,vers=4,hard,timeo=600,retrans=2,acregmin=0,acregmax=1,acdirmin=0,acdirmax=1,lookupcache=none 192.168.1.10:/avocado-hitl /var/lib/extensions/triton-demo

systemd-sysext refresh --mutable=ephemeral
systemd-confext merge --mutable=ephemeral

ldconfig
depmod

modprobe tegra-drm
modprobe tegra-camera
modprobe nvidia-drm modeset=1
modprobe uvcvideo

mkdir -p /tmp/.X11-unix
weston --backend=drm-backend.so --idle-time=0

mkdir -p _avocado/sdk/sysroots/sysext/opt

cp -rf triton-demo _avocado/sdk/sysroots/sysext/opt
tritonserver --model-repository /opt/triton-demo/ --model-control-mode=explicit --load-model peoplenet --http-port=8000 --backend-directory /usr/lib --metrics-port=8002 &

deepstream-app -c /opt/triton-demo/deepstream/source1_primary_detector_peoplenet.txt

gst-launch-1.0 v4l2src device=/dev/video0 ! \
  'image/jpeg,width=1920,height=1080,framerate=30/1' ! \
  jpegdec ! \
  videoconvert ! \
  autovideosink


sudo docker run --rm \
  --name avocado-hitl-server \
  --net=host \
  --cap-add DAC_READ_SEARCH \
  -v ./:/opt \
  -v ./nfs.conf:/etc/ganesha/ganesha.conf \
  -v ./hitl.sh:/hitl.sh \
  --entrypoint /hitl.sh \
  avocadolinux/sdk:dev \
  ganesha.nfsd -F -L /dev/stdout -f /etc/ganesha/ganesha.conf -p /var/run/ganesha.pid

export DEPLOY_DIR=$(pwd)/build-jetson-orin-nano-devkit-nvme/build/tmp/deploy
podman-compose -f support/sdk-test/compose.yml down --remove-orphans
AVOCADO_SDK_TARGET=jetson-orin-nano-devkit-nvme podman-compose -f support/sdk-test/compose.yml run sdk /bin/bash
