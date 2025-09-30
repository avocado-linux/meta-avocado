# Disable xcomposite-glx feature to avoid build failures
# The xcomposite-glx feature requires desktop OpenGL and X11, but we're building
# with OpenGL ES and Wayland, which doesn't meet the pre-conditions
PACKAGECONFIG:remove = "xcomposite-glx"

