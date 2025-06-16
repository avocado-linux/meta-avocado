# Hardware in the Loop

## Setup

Run through the main instructions for setting up the SDK in the README.md file
Install additional sdk packages necessary to run.

```bash
avocado-repo sdk install nativesdk-ganesha -y
```

## Running The HITL Server

Start a rootful docker container using the sdk image. For development, you will need to `sudo docker import` the image. Docker will need a full path to the image. For example:

```bash
sudo docker import /path/to/build-container-x86_64/build/tmp/deploy/images/avocado-container-x86_64/avocado-image-container-avocado-container-x86_64.rootfs-*.tar.bz2" avocadolinux/sdk:dev
```

Run the HitL nfs server container

```bash
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
```

Run a HitL client container

```bash
sudo docker run -it --rm \
  --name avocado-hitl-client \
  -e AVOCADO_SDK_MACHINE=qemux86-64 \
  --net=host \
  -v ./:/opt \
  avocadolinux/sdk:dev \
  avocado-run-qemu
```

Make a directory for the extension and mount it to the sysroot

```bash
mkdir -p /var/lib/extensions/peridiod
mount -t nfs4 -o port=12049,proto=tcp,vers=4 10.0.2.2:/avocado-hitl /var/lib/extensions/peridiod
```

In this example we assume the extension to be named peridiod. You will need to `avocado-build sysext peridiod` to generate the extension release data.

After making changes to the extension you need to `systemd-sysext refresh` to reload the extension changes into the os tree.
