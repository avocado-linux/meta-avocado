# SDK Container Test
This docker compose setup enables testing of an SDK container with the package repo.

## Setup

### Building an SDK Container

You will need to build an sdk container that is compatible with your host. Do this by building for either

* avocado-container-x86_64
* avocado-container-arm64

Once the container image is built, you can import the image from the build directory

```bash
docker import build-container-x86_64/build/tmp/deploy/images/avocado-container-x86_64/avocado-image-container-avocado-container-x86_64.rootfs.tar.bz2 avocadolinux/sdk:dev
```

### Building target package repos

You will also need to build for a target to populate the package repos needed to start the package-repo container. The remainder of the document will assume the use of qemux86_64 as the target type.

Refer to the main documentation for information on how to configure the system to build Avocado OS for a target machine type.

## Testing

Export the path to the rpms for your chosen platform

```bash
export DEPLOY_DIR=./build-qemux86-64-secureboot/build/tmp/deploy
```

You can start the package-repo container and get a bash prompt in the sdk container with the following docker compose command

```bash
docker compose -f support/sdk-test/docker-compose.yml run sdk-test /bin/bash
```

Once you have a bash prompt for the sdk container, you can run the following commands to install the required packages and set up the container for use with a toolchain

```bash
dnf update && dnf install -y avocado-sdk-qemux86-64
dnf update && dnf install -y --setopt=tsflags=noscripts avocado-sdk-toolchain
```

Once the toolchain is installed, you can install the target sysroot with the following:

```bash
mkdir -p /opt/avocado/sdk/avocado-qemux86-64/0.1.0/sysroots/core2-64-avocado-linux/var
dnf -y --setopt=tsflags=noscripts --installroot /opt/avocado/sdk/avocado-qemux86-64/0.1.0/sysroots/core2-64-avocado-linux/ install packagegroup-core-standalone-sdk-target
```
