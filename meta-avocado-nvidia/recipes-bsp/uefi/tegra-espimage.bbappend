# Ensure ESP image is deployed to images directory for stone validation
# The base recipe inherits core-image which handles deployment
# This bbappend exists to ensure the recipe is built for Avocado Jetson machines

# Ensure the image is deployed to DEPLOY_DIR_IMAGE
# The .esp file will be named: tegra-espimage-${MACHINE}.esp
