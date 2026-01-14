# Shared utility functions for Avocado architecture handling and repository path mapping.
# This class provides common logic used by both the SDK metadata package generation
# and the repo map file generation.

# Known SDK architecture names that map to the SDK repository path
# These are the hyphen versions as they appear in PACKAGE_ARCHS
AVOCADO_SDK_REPO_ARCHS = "x86_64-avocadosdk aarch64-avocadosdk"
# The underscore versions as they appear in deploy directory names
AVOCADO_SDK_REPO_ARCHS_UNDERSCORE = "x86_64_avocadosdk aarch64_avocadosdk"

def avocado_determine_repo_paths(d, arch, arch_dir):
    """
    Determines repository paths and names based on architecture rules.

    Args:
        d: BitBake data store
        arch: Architecture name (may contain hyphens, from PACKAGE_ARCHS)
        arch_dir: Architecture directory name (underscores instead of hyphens)

    Returns:
        dict with keys: map_value_path, repo_url_path, repo_name, repo_section_name
    """
    import bb

    machine = d.getVar('MACHINE')
    machine_short_name = machine.replace('avocado-', '')
    sdk_repo_archs = (d.getVar('AVOCADO_SDK_REPO_ARCHS') or "").split()
    sdk_repo_archs_underscore = (d.getVar('AVOCADO_SDK_REPO_ARCHS_UNDERSCORE') or "").split()

    map_value_path = None
    repo_url_path = None
    repo_name = None
    repo_section_name = None

    # --- Apply Rules ---
    # Check for all_avocadosdk (both hyphen and underscore versions)
    if arch == "all_avocadosdk" or arch == "all-avocadosdk" or arch_dir == "all_avocadosdk":
        # Rule: all_avocadosdk -> DISTRO/sdk/all
        map_value_path = "$releasever/sdk/all"
        bb.note(f"Mapping arch '{arch}' (dir: {arch_dir}) to map path '{map_value_path}' (no repo entry)")

    # Check for dedicated SDK archs (both hyphen and underscore versions)
    elif arch in sdk_repo_archs or arch_dir in sdk_repo_archs_underscore:
        # Rule: Dedicated SDK arch -> DISTRO/sdk/MACHINE_SHORT
        map_value_path = f"$releasever/sdk/{machine_short_name}"
        repo_url_path = map_value_path
        repo_name = f"{machine_short_name}-sdk"
        repo_section_name = repo_name
        bb.note(f"Mapping dedicated SDK arch '{arch}' (dir: {arch_dir}) to path '{map_value_path}', repo name '{repo_name}'")

    elif arch_dir == machine.replace('-', '_'):
        # Rule: MACHINE -> DISTRO/target/MACHINE_SHORT
        # Compare underscore versions to handle potential input mismatch
        map_value_path = f"$releasever/target/{machine_short_name}"
        repo_url_path = map_value_path
        repo_name = f"{machine_short_name}-target"
        repo_section_name = repo_name
        bb.note(f"Mapping machine arch '{arch}' (dir: {arch_dir}) to path '{map_value_path}', repo name '{repo_name}'")

    else:
        # Rule: other -> DISTRO/target/arch_dir
        map_value_path = f"$releasever/target/{arch_dir}"
        repo_url_path = map_value_path
        # Use original arch (with hyphens) for naming consistency
        repo_name = f"{machine_short_name}-{arch}"
        repo_section_name = repo_name
        bb.note(f"Mapping target arch '{arch}' (dir: {arch_dir}) to path '{map_value_path}', repo name '{repo_name}'")

    return {
        "map_value_path": map_value_path,
        "repo_url_path": repo_url_path,
        "repo_name": repo_name,
        "repo_section_name": repo_section_name,
    }

def avocado_get_ordered_archs(d, arch_set):
    """
    Returns a list of architectures ordered with machine arch first,
    then reverse-sorted others (most specific tune first).

    Args:
        d: BitBake data store
        arch_set: Set or list of architecture names

    Returns:
        list of ordered architecture names
    """
    import bb

    machine = d.getVar('MACHINE')
    machine_arch = machine.replace('-', '_')
    sorted_archs = sorted(list(arch_set))

    ordered_archs = []
    machine_arch_found = None

    # Find the machine arch and put it first
    for arch in sorted_archs:
        arch_dir = arch.replace('-', '_')
        if arch_dir == machine_arch:
            machine_arch_found = arch
            break

    if machine_arch_found:
        ordered_archs.append(machine_arch_found)
        # Add all others except the machine arch, in reverse order (most specific first)
        other_archs = [arch for arch in sorted_archs if arch != machine_arch_found]
        ordered_archs.extend(reversed(other_archs))
    else:
        # If machine arch not found, just use reverse-sorted order
        ordered_archs = list(reversed(sorted_archs))
        bb.note(f"Machine arch '{machine_arch}' not found in available architectures")

    return ordered_archs

def avocado_filter_target_archs(d, arch_list):
    """
    Filters an architecture list to only include target architectures,
    excluding SDK-specific architectures.

    Args:
        d: BitBake data store
        arch_list: List of architecture names

    Returns:
        Sorted list of target architectures (with underscores)
    """
    sdk_repo_archs = (d.getVar('AVOCADO_SDK_REPO_ARCHS') or "").split()
    sdk_archs_underscore = [arch.replace('-', '_') for arch in sdk_repo_archs] + ['all_avocadosdk']
    target_archs = [a.replace('-', '_') for a in arch_list if a.replace('-', '_') not in sdk_archs_underscore]
    return sorted(list(set(target_archs)))
