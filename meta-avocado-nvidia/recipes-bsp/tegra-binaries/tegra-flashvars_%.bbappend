# Add DCE_OVERLAY to flashvars for tegraflash
# The upstream recipe generates OVERLAY_DTB_FILE but not DCE_OVERLAY
# tegra-flash-helper.sh expects DCE_OVERLAY for --dce_overlay_dtb argument

# Override generate_flashvar_settings to include DCE_OVERLAY
def generate_flashvar_settings(d):
    vars = sorted([v for v in d.getVar('TEGRA_FLASHVARS').split() if d.getVar('TEGRA_FLASHVAR_' + v)])
    need_subst = ' '.join([v for v in vars if '@' in d.getVar('TEGRA_FLASHVAR_' + v)])
    result = 'FLASHVARS="{}"\nOVERLAY_DTB_FILE="{}"\n'.format(need_subst, d.getVar('OVERLAY_DTB_FILE'))
    # Add DCE_OVERLAY from TEGRA_DCE_OVERLAY variable
    dce_overlay = d.getVar('TEGRA_DCE_OVERLAY') or ""
    if dce_overlay:
        result += 'DCE_OVERLAY="{}"\n'.format(dce_overlay)
    result += 'CHIPID={}\nPLUGIN_MANAGER_OVERLAYS="{}"\n'.format(d.getVar('NVIDIA_CHIP'), ','.join(d.getVar('TEGRA_PLUGIN_MANAGER_OVERLAYS').split()))
    flashvar_values = '\n'.join(['{}="{}"'.format(v, d.getVar('TEGRA_FLASHVAR_' + v)) for v in d.getVar('TEGRA_FLASHVARS').split() if d.getVar('TEGRA_FLASHVAR_' + v)])
    if flashvar_values:
        result += flashvar_values + '\n'
    result += '\n'.join(['CHECK_{}="{}"'.format(v, d.getVar('TEGRA_FLASH_CHECK_' + v)) for v in d.getVar('TEGRA_FLASH_CHECK_VARS').split() if d.getVar('TEGRA_FLASH_CHECK_' + v)])
    return result

# Add TEGRA_DCE_OVERLAY to vardeps to ensure rebuild when it changes
do_compile[vardeps] += "TEGRA_DCE_OVERLAY OVERLAY_DTB_FILE"
