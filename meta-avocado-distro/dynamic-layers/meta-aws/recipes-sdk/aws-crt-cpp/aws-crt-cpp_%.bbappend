# By default meta-aws builds aws-crt-cpp and aws-iot-device-sdk-cpp-v2 each
# with its own copy of the AWS C runtime (PACKAGECONFIG build-deps), and both
# ship /usr/lib/libaws-crt-cpp.so. Extensions all merge into one /usr, so the
# copy that wins breaks the other's users: on an AGX Orin FleetWise, built
# against this one, failed on a symbol missing from the SDK's copy. Link
# both against the shared aws-c-* recipes, so a feed carries one runtime.
PACKAGECONFIG:remove = "build-deps"
