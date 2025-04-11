# This Yocto recipe generates repository configuration files for the Avocado SDK.
# It creates two primary outputs based on the build environment variables:
# 1. avocado-sdk.repo: A yum/dnf repository configuration file that gets
#    packaged into the resulting SDK or image. This file allows the target
#    system to find and install packages from the Avocado repositories.
# 2. avocado-repo.map: A mapping file placed in the build's deployment
#    directory (DEPLOY_DIR_RPM). This file likely assists the build system
#    or related tooling in associating specific package architectures with
#    their corresponding repository paths on the server defined by
#    AVOCADO_REPO_BASE.
#
# The do_install task dynamically generates these files by inspecting the
# available package architectures (PACKAGE_ARCHS, SDK_PACKAGE_ARCHS) in
# DEPLOY_DIR_RPM, applying specific rules based on DISTRO_CODENAME, MACHINE,
# and SDK suffixes to determine the correct repository sub-paths.

DESCRIPTION = "Avocado SDK machine repository configuration"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PN = "${VIRTUAL-RUNTIME_avocado-sdk-metadata}"
PACKAGES = "${PN}"

RDEPENDS:${PN} = ""

# Skip QA checks likeldflags, alreadyinstalled, etc. that are not relevant for this config package
INSANE_SKIP:${PN} = "ldflags alreadyinstalled"

# The repo file is packaged, the map file is deployed directly
FILES:${PN} = "/avocado-sdk.repo"

# Set package arch so it deploys to a specific directory
PACKAGE_ARCH = "all_avocadosdk"

AVOCADO_REPO_BASE ?= "http://localhost:8080"

python do_install() {
    import os
    import bb

    d_dir = d.getVar('D')
    deploy_dir_rpm = d.getVar('DEPLOY_DIR_RPM')
    base_repo_url = d.getVar('AVOCADO_REPO_BASE') # Base URL for the repo server
    distro_codename = d.getVar('DISTRO_CODENAME')
    machine = d.getVar('MACHINE')
    sdk_pkg_suffix = d.getVar('SDKPKGSUFFIX') or ""
    pkg_archs = (d.getVar('PACKAGE_ARCHS') or "").split()
    sdk_pkg_archs = (d.getVar('SDK_PACKAGE_ARCHS') or "").split()
    gpg_check = d.getVar('AVOCADO_REPO_GPGCHECK') or '0'

    # --- Precompute values ---
    machine_short_name = machine.replace('avocado-', '')
    sdk_suffix_us = sdk_pkg_suffix.replace('-', '_')

    # --- Helper Functions ---
    def _determine_repo_paths(arch, arch_dir, distro_codename, machine_short_name, sdk_suffix_us, machine, bb):
        """Determines repository paths and names based on architecture rules."""
        map_value_path = None
        repo_url_path = None
        repo_name = None
        repo_section_name = None

        # --- Apply Rules ---
        if arch == "all_avocadosdk":
            # Rule: all_avocadosdk -> DISTRO/sdk/all
            map_value_path = f"{distro_codename}/sdk/all"
            bb.note(f"Mapping arch '{arch}' (dir: {arch_dir}) to map path '{map_value_path}' (no repo entry)")

        elif sdk_suffix_us and arch_dir.endswith(sdk_suffix_us):
            # Rule: other *avocadosdk -> DISTRO/sdk/MACHINE_SHORT
            map_value_path = f"{distro_codename}/sdk/{machine_short_name}"
            repo_url_path = map_value_path
            repo_name = f"{machine_short_name}-sdk"
            repo_section_name = repo_name # Use cleaned name for section too
            bb.note(f"Mapping SDK arch '{arch}' (dir: {arch_dir}) to path '{map_value_path}', repo name '{repo_name}'")

        elif arch_dir == machine.replace('-', '_'):
            # Rule: MACHINE -> DISTRO/target/MACHINE_SHORT
            # Compare underscore versions to handle potential input mismatch
            map_value_path = f"{distro_codename}/target/{machine_short_name}"
            repo_url_path = map_value_path
            repo_name = f"{machine_short_name}-target"
            repo_section_name = repo_name
            bb.note(f"Mapping machine arch '{arch}' (dir: {arch_dir}) to path '{map_value_path}', repo name '{repo_name}'")

        else:
            # Rule: other -> DISTRO/target/arch_dir
            map_value_path = f"{distro_codename}/target/{arch_dir}"
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

    def _write_map_entry(map_f, arch_dir, map_value_path, bb):
        """Writes a single entry to the map file."""
        if map_value_path:
             map_f.write(f"{arch_dir}={map_value_path}\n")
        else:
             # Use arch_dir here as arch is not passed to this helper
             bb.warn(f"No map path determined for arch_dir '{arch_dir}'")

    def _write_repo_entry(repo_f, base_repo_url, repo_url_path, repo_name, repo_section_name, gpg_check, priority, arch, bb):
        """Writes a repository section to the repo file. Returns True if written, False otherwise."""
        if repo_url_path and repo_name and repo_section_name:
            repo_f.write(f"[{repo_section_name}]\n")
            repo_f.write(f"name={repo_name}\n")
            # Base URL for repo file uses the main repo server base
            repo_f.write(f"baseurl={base_repo_url}/{repo_url_path}\n")
            repo_f.write(f"enabled=1\n")
            repo_f.write(f"gpgcheck={gpg_check}\n")
            repo_f.write(f"priority={priority}\n")
            repo_f.write("\n")
            return True # Indicate success for priority increment
        elif arch != "all_avocadosdk": # Only log warning if it wasn't the explicitly excluded arch
            bb.warn(f"Repo entry details not fully determined for arch '{arch}'. Skipping repo entry.")
        return False # Indicate failure

    # Ensure directories exist
    os.makedirs(d_dir, exist_ok=True)
    os.makedirs(deploy_dir_rpm, exist_ok=True)

    # Define file paths
    repo_file_path = os.path.join(d_dir, 'avocado-sdk.repo')
    map_file_path = os.path.join(deploy_dir_rpm, 'avocado-repo.map')

    # Combine architectures into a unique set
    all_archs = set(pkg_archs + sdk_pkg_archs)

    priority = 1

    # Overwrite map file and repo file initially
    with open(map_file_path, 'w') as map_f:
        map_f.write('')
    with open(repo_file_path, 'w') as repo_f:
        repo_f.write('')

    # --- Unconditionally add the mapping for this recipe's own arch ---
    # Note: This specific logic remains outside the loop as it's unconditional
    # and slightly different (doesn't add to repo file).
    map_value_path_for_all = f"{distro_codename}/sdk/all"
    with open(map_file_path, 'a') as map_f:
        bb.note(f"Adding unconditional map entry: all_avocadosdk={map_value_path_for_all}")
        map_f.write(f"all_avocadosdk={map_value_path_for_all}\n")

    # Append to files for other architectures found
    with open(map_file_path, 'a') as map_f, open(repo_file_path, 'a') as repo_f:
        for arch in sorted(list(all_archs)): # Sort for consistent output order
            # Skip only dummy architectures
            if arch.startswith('sdk-provides-dummy'):
                continue

            # Skip the special arch handled unconditionally above
            if arch == "all_avocadosdk":
                 continue

            # arch_dir calculated for directory check and potential map key
            arch_dir = arch.replace('-', '_')

            # --- For all other arches, check directory FIRST ---
            check_dir = os.path.join(deploy_dir_rpm, arch_dir)
            if os.path.isdir(check_dir):
                # --- Determine Paths and Names ---
                repo_details = _determine_repo_paths(
                    arch, arch_dir, distro_codename, machine_short_name, sdk_suffix_us, machine, bb
                )

                # --- Write to Map File ---
                # Note: We still call write_map_entry even for all_avocadosdk case inside _determine_repo_paths,
                # but it won't write to the repo file.
                _write_map_entry(
                    map_f, arch_dir, repo_details["map_value_path"], bb
                )

                # --- Write to Repo File ---
                # Pass arch to helper for accurate warnings
                if _write_repo_entry(
                    repo_f, base_repo_url,
                    repo_details["repo_url_path"],
                    repo_details["repo_name"],
                    repo_details["repo_section_name"],
                    gpg_check, priority, arch, bb
                ):
                    priority += 1 # Increment priority only if repo entry was written
            else:
                bb.note(f"Skipping arch '{arch}' as directory '{check_dir}' does not exist")
}
