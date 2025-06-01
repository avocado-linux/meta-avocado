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
podman-compose -f support/sdk-test/docker-compose.yml run sdk-test /bin/bash
```

Running for a different target:

```bash
export DEPLOY_DIR=./build-imx93-frdm/build/tmp/deploy
AVOCADO_SDK_TARGET=imx93-frdm podman-compose -f support/sdk-test/docker-compose.yml run sdk-test /bin/bash
```

## Runtime Environment

The container will come up with the environment script sourced and you can begin extending the sdk components. The environment is decorated with several additional env vars:

### Adding Native SDK Packages

Exmaple adding qemu to the nativesdk

```bash
avocado-repo sdk install nativesdk-qemu
```

### Adding target dev packages

Example adding libcryptoauth3-dev to the target-dev sysroot for cross compile header and library support

```bash
avocado-repo target-dev install libcryptoauth-dev
```

### Adding sysext packages

Example adding libcryptoauth3 to the sysext sysroot. The sysext sysroot has been prepopulated with the package database of the rootfilesystem and therefore anything that already exists in the root will not be installed into the sysroot for the sysext.

```bash
avocado-repo sysext install libcryptoauth3
```

