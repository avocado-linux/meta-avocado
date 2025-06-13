#!/bin/bash

set -e

RELEASE=$1

docker import --platform linux/arm64 build-container-arm64/build/tmp/deploy/images/avocado-container-arm64/avocado-image-container-avocado-container-arm64.rootfs.tar.bz2 avocadolinux/sdk:${RELEASE}-arm64
docker import --platform linux/amd64 build-container-x86_64/build/tmp/deploy/images/avocado-container-x86_64/avocado-image-container-avocado-container-x86_64.rootfs.tar.bz2 avocadolinux/sdk:${RELEASE}-amd64

docker push avocadolinux/sdk:${RELEASE}-amd64
docker push avocadolinux/sdk:${RELEASE}-arm64

docker manifest rm avocadolinux/sdk:${RELEASE} || true

docker manifest create avocadolinux/sdk:${RELEASE} \
  avocadolinux/sdk:${RELEASE}-amd64 \
  avocadolinux/sdk:${RELEASE}-arm64

docker manifest annotate avocadolinux/sdk:${RELEASE} \
  avocadolinux/sdk:${RELEASE}-amd64 --os linux --arch amd64 

docker manifest annotate avocadolinux/sdk:${RELEASE} \
  avocadolinux/sdk:${RELEASE}-arm64 --os linux --arch arm64

docker manifest push avocadolinux/sdk:${RELEASE}
