inherit cuda

# Inject CUDA configuration into the ExternalProject CMAKE_ARGS
# This ensures the inner MRPT build can find CUDA libraries
do_configure:prepend() {
    # Add CUDA toolkit root directory for legacy FindCUDA.cmake
    sed -i "/CMAKE_ARGS/a\\    -DCUDA_TOOLKIT_ROOT_DIR=${STAGING_DIR_TARGET}/usr/local/cuda" ${S}/CMakeLists.txt
    # Also add modern CUDAToolkit for newer CMake versions
    sed -i "/CMAKE_ARGS/a\\    -DCUDAToolkit_ROOT=${STAGING_DIR_TARGET}/usr/local/cuda" ${S}/CMakeLists.txt
}
