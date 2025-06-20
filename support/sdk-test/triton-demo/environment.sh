MODEL_NAME=peoplenet
BASE_DIR="ngc_models/$MODEL_NAME"

# Map versions to the download files available
# at https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/peoplenet/version
declare -A versions=(
    [2.6.3]="deployable_quantized_onnx_v2.6.3"
    [2.3.4]="pruned_quantized_decrypted_v2.3.4"
)

# Map the versions above to version directories used by triton server
declare -A version_dir=(
    [2.6.3]="3"
    [2.3.4]="2"
)

TRITON_REPO_DIR=/var/local/triton_model_repo
TRITON_MODEL_REPO_DIR=/var/local/triton_model_repo/$MODEL_NAME
