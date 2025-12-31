#!/usr/bin/env bash

set -e

RELEASE=$1

echo "Loading containers into local Docker repository..."

docker import --platform linux/arm64 build-container-arm64/build/tmp/deploy/images/avocado-container-arm64/avocado-image-container-avocado-container-arm64.rootfs.tar.bz2 avocadolinux/sdk:${RELEASE}-arm64
docker import --platform linux/amd64 build-container-x86_64/build/tmp/deploy/images/avocado-container-x86_64/avocado-image-container-avocado-container-x86_64.rootfs.tar.bz2 avocadolinux/sdk:${RELEASE}-amd64

# Tag native arch as main tag for local testing
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
  echo "Tagging amd64 image as ${RELEASE} for local use..."
  docker tag avocadolinux/sdk:${RELEASE}-amd64 avocadolinux/sdk:${RELEASE}
elif [ "$ARCH" = "aarch64" ]; then
  echo "Tagging arm64 image as ${RELEASE} for local use..."
  docker tag avocadolinux/sdk:${RELEASE}-arm64 avocadolinux/sdk:${RELEASE}
fi

echo "Removing existing manifest if present..."
docker manifest rm avocadolinux/sdk:${RELEASE} 2>/dev/null || true

echo "Creating multi-platform manifest for deployment..."
docker manifest create avocadolinux/sdk:${RELEASE} \
  avocadolinux/sdk:${RELEASE}-amd64 \
  avocadolinux/sdk:${RELEASE}-arm64

docker manifest annotate avocadolinux/sdk:${RELEASE} \
  avocadolinux/sdk:${RELEASE}-amd64 --os linux --arch amd64 

docker manifest annotate avocadolinux/sdk:${RELEASE} \
  avocadolinux/sdk:${RELEASE}-arm64 --os linux --arch arm64

echo "Done! Images loaded locally:"
echo "  - avocadolinux/sdk:${RELEASE}-amd64"
echo "  - avocadolinux/sdk:${RELEASE}-arm64"
echo "  - avocadolinux/sdk:${RELEASE} (local tag for testing)"
echo ""
echo "Local testing:  docker run -it avocadolinux/sdk:${RELEASE}"
echo "Push to Hub:    ./sdk-push-containers.sh ${RELEASE}"

