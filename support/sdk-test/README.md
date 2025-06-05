# SDK Container Test
This podman compose setup enables testing of an SDK container with the package repo.

## Setup

### Building an SDK Container

You will need to build an sdk container that is compatible with your host. Do this by building for either

* avocado-container-x86_64
* avocado-container-arm64

Once the container image is built, you can import the image from the build directory

```bash
podman import build-container-x86_64/build/tmp/deploy/images/avocado-container-x86_64/avocado-image-container-avocado-container-x86_64.rootfs.tar.bz2 avocadolinux/sdk:dev
```

### Building target package repos

You will also need to build for a target to populate the package repos needed to start the package-repo container. The remainder of the document will assume the use of qemux86_64 as the target type.

Refer to the main documentation for information on how to configure the system to build Avocado OS for a target machine type.

## Testing

Export the path to the rpms for your chosen platform

```bash
export DEPLOY_DIR=./build-qemux86-64/build/tmp/deploy
```

You can start the package-repo container and get a bash prompt in the sdk container with the following `podman-compose` command

```bash
podman-compose -f support/sdk-test/compose.yml run sdk-test /bin/bash
```

Running for a different target:

```bash
export DEPLOY_DIR=./build-imx93-frdm/build/tmp/deploy
AVOCADO_SDK_TARGET=imx93-frdm podman-compose -f support/sdk-test/compose.yml run sdk-test /bin/bash
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

## Building a system extension

Let's build a system extension that adds peridiod to the runtime. Start by installing the package contents for the peridiod package to the sysext sysroot:

```bash
avocado-repo sysext install peridiod -y
```

Then build the system extension

```bash
avocado-build sysext peridiod
```

This will output the `peridiod` system extension raw file to the output dir at

```bash
/opt/_avocado/extensions/sysext/peridiod.raw
```

## Building and booting the image in qemu

Download the necessary images for the bootchain and the core rootfs for use when building the image

```bash
avocado-repo images
```

Build the final image

```bash
avocado-build image
```

This will place files into the folder

```bash
/opt/_avocado/output
```

## Booting the image in qemu

Extends the toolchain with qemu-system-x86-64

```bash
avocado-repo sdk install nativesdk-qemu-system-x86-64
```

Run the VM

```bash
avocado-run-qemu
```

## Making changes

If you make changes to the contents of the extensions, you will need to force the var partition to be recreated

```bash
avocado-build var
```
