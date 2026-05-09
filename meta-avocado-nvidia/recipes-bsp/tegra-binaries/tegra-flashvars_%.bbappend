# Add DCE_OVERLAY to flashvars for tegraflash.
# The upstream recipe generates OVERLAY_DTB_FILE but does not emit a separate
# DCE_OVERLAY shell var into flashvars. tegra-flash-helper.sh (our copy)
# reads DCE_OVERLAY and adds --dce_overlay_dtb to tegraflash.py.
#
# Variable namespace: meta-tegra commit 7090c134 (R36.5+ era) renamed
# TEGRA_DCE_OVERLAY -> TEGRA_FLASHVAR_DCE_OVERLAY (promotion into the
# standard TEGRA_FLASHVAR_* namespace). Upstream image_types_tegra.bbclass's
# copy_dtb_overlays now reads the new name to know which dtbo to copy into
# the BSP tarball. We follow the same name here so machines that use the
# upstream confs (jetson-agx-orin-devkit, jetson-orin-nano-devkit etc.) get
# DCE_OVERLAY into flashvars. Avocado-specific machine confs (icam-540) were
# updated to set the new name as well.

# Override generate_flashvar_settings to include DCE_OVERLAY
def generate_flashvar_settings(d):
    vars = sorted([v for v in d.getVar('TEGRA_FLASHVARS').split() if d.getVar('TEGRA_FLASHVAR_' + v)])
    need_subst = ' '.join([v for v in vars if '@' in d.getVar('TEGRA_FLASHVAR_' + v)])
    result = 'FLASHVARS="{}"\nOVERLAY_DTB_FILE="{}"\n'.format(need_subst, d.getVar('OVERLAY_DTB_FILE'))
    # Add DCE_OVERLAY from TEGRA_FLASHVAR_DCE_OVERLAY variable
    dce_overlay = d.getVar('TEGRA_FLASHVAR_DCE_OVERLAY') or ""
    if dce_overlay:
        result += 'DCE_OVERLAY="{}"\n'.format(dce_overlay)
    result += 'CHIPID={}\nPLUGIN_MANAGER_OVERLAYS="{}"\n'.format(d.getVar('NVIDIA_CHIP'), ','.join(d.getVar('TEGRA_PLUGIN_MANAGER_OVERLAYS').split()))
    flashvar_values = '\n'.join(['{}="{}"'.format(v, d.getVar('TEGRA_FLASHVAR_' + v)) for v in d.getVar('TEGRA_FLASHVARS').split() if d.getVar('TEGRA_FLASHVAR_' + v)])
    if flashvar_values:
        result += flashvar_values + '\n'
    result += '\n'.join(['CHECK_{}="{}"'.format(v, d.getVar('TEGRA_FLASH_CHECK_' + v)) for v in d.getVar('TEGRA_FLASH_CHECK_VARS').split() if d.getVar('TEGRA_FLASH_CHECK_' + v)])
    return result

# Rebuild flashvars when the DCE overlay or extra overlays change.
do_compile[vardeps] += "TEGRA_FLASHVAR_DCE_OVERLAY OVERLAY_DTB_FILE"
