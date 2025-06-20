#!/bin/bash
set -e
source $(dirname $0)/environment.sh

/opt/tritonserver/bin/tritonserver --model-repository /opt/triton-demo/ --model-control-mode=explicit --load-model $MODEL_NAME --http-port=8000 --grpc-port=10001 --metrics-port=8002
