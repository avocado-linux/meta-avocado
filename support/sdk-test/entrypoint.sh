#!/bin/bash

# Wait for package-repo to become healthy
REPO_HOST=package-repo
REPO_PORT=80

echo "Waiting for package-repo at $REPO_HOST:$REPO_PORT..."
until wget -qO- "http://${REPO_HOST}:${REPO_PORT}/" > /dev/null; do
  echo "Waiting for package-repo..."
  sleep 2
done


echo "package-repo is up. Continuing with sdk setup..."
entrypoint.sh "$@"
