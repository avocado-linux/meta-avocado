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

PV = "${SDK_VERSION}"

PN = "${VIRTUAL-RUNTIME_avocado-sdk-metadata}"
PACKAGES = "${PN}"

RDEPENDS:${PN} = ""

MACHINEARCH = "${@d.getVar('MACHINE_SHORT_NAME').replace('-', '_')}"
PLATFORM = "${MACHINEARCH}-avocado-linux"

# Skip QA checks likeldflags, alreadyinstalled, etc. that are not relevant for this config package
INSANE_SKIP:${PN} = "ldflags alreadyinstalled"

inherit deploy

# The repo file is packaged, the map file is deployed directly
FILES:${PN} = " \
    ${SDKPATHNATIVE}/target-repoconf${sysconfdir}/rpmrc \
    ${SDKPATHNATIVE}/target-repoconf${sysconfdir}/rpm/platform \
    ${SDKPATHNATIVE}/target-repoconf${sysconfdir}/dnf/vars/arch \
    ${SDKPATHNATIVE}/target-repoconf${sysconfdir}/yum.repos.d \
"

# Set package arch so it deploys to a specific directory
PACKAGE_ARCH = "all_avocadosdk"

python do_compile() {
    import os
    import bb

    deploy_dir_rpm = d.getVar('DEPLOY_DIR_RPM')
    bb.note(f"DEPLOY_DIR_RPM value: {deploy_dir_rpm}")
    machine = d.getVar('MACHINE')
    sdk_pkg_suffix = d.getVar('SDKPKGSUFFIX') or ""
    pkg_archs = (d.getVar('PACKAGE_ARCHS') or "").split()
    sdk_pkg_archs = (d.getVar('SDK_PACKAGE_ARCHS') or "").split()
    gpg_check = d.getVar('AVOCADO_REPO_GPGCHECK') or '0'
    repo_archs = [] # List to store archs for which repo entries are written
    sdk_repo_archs = ['x86_64-avocadosdk', 'aarch64-avocadosdk']

    # --- Precompute values ---
    machine_short_name = machine.replace('avocado-', '')
    sdk_suffix_us = sdk_pkg_suffix.replace('-', '_')

    # --- Helper Functions ---
    def _determine_repo_paths(arch, arch_dir):
        """Determines repository paths and names based on architecture rules."""
        map_value_path = None
        repo_url_path = None
        repo_name = None
        repo_section_name = None

        # --- Apply Rules ---
        if arch == "all_avocadosdk":
            # Rule: all_avocadosdk -> DISTRO/sdk/all
            map_value_path = f"$releasever/sdk/all"
            bb.note(f"Mapping arch '{arch}' (dir: {arch_dir}) to map path '{map_value_path}' (no repo entry)")

        elif arch in sdk_repo_archs:
            # Rule: Dedicated SDK arch -> DISTRO/sdk/MACHINE_SHORT
            map_value_path = f"$releasever/sdk/{machine_short_name}"
            repo_url_path = map_value_path
            repo_name = f"{machine_short_name}-sdk"
            repo_section_name = repo_name
            bb.note(f"Mapping dedicated SDK arch '{arch}' to path '{map_value_path}', repo name '{repo_name}'")

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

    def _write_map_entry(map_f, arch_dir, map_value_path):
        """Writes a single entry to the map file."""
        if map_value_path:
             map_f.write(f"{arch_dir}={map_value_path}\n")
        else:
             bb.warn(f"No map path determined for arch_dir '{arch_dir}'")

    def _write_repo_entry(repo_f, repo_url_path, repo_name, repo_section_name, priority, arch):
        """Writes a repository section to the repo file. Appends arch to repo_archs on success."""
        nonlocal repo_archs # Allow modification of the outer scope list
        if repo_url_path and repo_name and repo_section_name:
            repo_f.write(f"[{repo_section_name}]\n")
            repo_f.write(f"name={repo_name}\n")
            # Base URL for repo file uses the main repo server base
            repo_f.write(f"baseurl=${{repo_url}}/{repo_url_path}\n")
            repo_f.write(f"enabled=1\n")
            repo_f.write(f"gpgcheck={gpg_check}\n")
            repo_f.write(f"priority={priority}\n")
            repo_f.write("\n")

            repo_archs.append(arch) # Append arch if written successfully
            return True # Indicate success for priority increment
        elif arch != "all_avocadosdk": # Only log warning if it wasn't the explicitly excluded arch
            bb.warn(f"Repo entry details not fully determined for arch '{arch}'. Skipping repo entry.")
        return False # Indicate failure

    def _process_arch(arch):
        nonlocal priority, map_f, repo_f

        # Skip sdk-provides-dummy architectures
        if arch.startswith('sdk-provides-dummy'):
            return

        # Skip the special arch handled unconditionally above and the dedicated SDK archs
        if arch == "all_avocadosdk" or arch in sdk_repo_archs:
            return

        # arch_dir calculated for directory check and potential map key
        arch_dir = arch.replace('-', '_')

        # --- For all other arches, check directory FIRST ---
        check_dir = os.path.join(deploy_dir_rpm, arch_dir)
        if os.path.isdir(check_dir):
            # --- Determine Paths and Names ---
            repo_details = _determine_repo_paths(arch, arch_dir)

            # --- Write to Map File ---
            # Note: We still call write_map_entry even for all_avocadosdk case inside _determine_repo_paths,
            # but it won't write to the repo file.
            _write_map_entry(map_f, arch_dir, repo_details["map_value_path"])

            # --- Write to Repo File ---
            # Pass arch to helper for accurate warnings
            if _write_repo_entry(
                repo_f,
                repo_details["repo_url_path"],
                repo_details["repo_name"],
                repo_details["repo_section_name"],
                priority, arch
            ):
                priority += 1 # Increment priority only if repo entry was written
        else:
            bb.note(f"Skipping arch '{arch}' as directory '{check_dir}' does not exist")

    def _process_sdk_archs():
        """
        Handles the special-case SDK architectures to ensure they always have
        a map entry and a single, shared repo configuration.
        """
        nonlocal priority, map_f, repo_f
        sdk_repo_written = False
        for arch in sdk_repo_archs:
            arch_dir = arch.replace('-', '_')
            repo_details = _determine_repo_paths(arch, arch_dir)

            # Always write the map entry for these SDK archs
            _write_map_entry(map_f, arch_dir, repo_details["map_value_path"])

            # Write the repo entry only once for the first SDK arch encountered
            if not sdk_repo_written:
                if _write_repo_entry(
                    repo_f,
                    repo_details["repo_url_path"],
                    repo_details["repo_name"],
                    repo_details["repo_section_name"],
                    priority,
                    arch
                ):
                    priority += 1
                    sdk_repo_written = True # Mark as written
            else:
                # For subsequent SDK archs, just ensure they are in the list
                # for the dnf/vars/arch file without writing a new repo section.
                repo_archs.append(arch)

    def _write_additional_target_repo():
        """
        Writes the additional target-ext repo entry at the end with highest priority number.
        """
        nonlocal repo_f, priority
        repo_f.write(f"[{machine_short_name}-target-ext]\n")
        repo_f.write(f"name={machine_short_name}-target-ext\n")
        repo_f.write(f"baseurl=${{repo_url}}/$releasever/target/{machine_short_name}-ext\n")
        repo_f.write(f"enabled=1\n")
        repo_f.write(f"gpgcheck={gpg_check}\n")
        repo_f.write(f"priority={priority}\n")
        repo_f.write("\n")
        bb.note(f"Added additional target repo '{machine_short_name}-target-ext' at priority {priority}")

    # Get SDKPATHNATIVE for the repo file
    sdk_path_native = d.getVar('SDKPATHNATIVE')
    # Construct the path for the repo file within the work directory
    # by stripping the leading '/' from SDKPATHNATIVE.
    sdk_native_prefix_stripped = sdk_path_native.lstrip('/')

    # Create directories in WORKDIR for generated files
    work_dir = d.getVar('WORKDIR')
    repo_work_dir = os.path.join(work_dir, 'generated-files', sdk_native_prefix_stripped, 'target-repoconf', 'etc', 'yum.repos.d')
    arch_vars_work_dir = os.path.join(work_dir, 'generated-files', sdk_native_prefix_stripped, 'target-repoconf', 'etc', 'dnf', 'vars')
    platform_work_dir = os.path.join(work_dir, 'generated-files', sdk_native_prefix_stripped, 'target-repoconf', 'etc', 'rpm')
    rpmrc_work_dir = os.path.join(work_dir, 'generated-files', sdk_native_prefix_stripped, 'target-repoconf', 'etc')

    # Ensure directories exist
    os.makedirs(deploy_dir_rpm, exist_ok=True)
    os.makedirs(repo_work_dir, exist_ok=True)
    os.makedirs(arch_vars_work_dir, exist_ok=True)
    os.makedirs(platform_work_dir, exist_ok=True)
    os.makedirs(rpmrc_work_dir, exist_ok=True)

    # Define file paths in WORKDIR
    repo_filename = d.getVar('VIRTUAL-RUNTIME_avocado-sdk-metadata') + '.repo'
    repo_file_path = os.path.join(repo_work_dir, repo_filename)

    # Create temporary directory for map file
    map_dir = os.path.join(work_dir, 'map')
    os.makedirs(map_dir, exist_ok=True)
    map_file_path = os.path.join(map_dir, 'avocado-repo.map')
    bb.note(f"Constructed map file path: {map_file_path}")

    # Combine architectures into a unique set
    all_archs = set(pkg_archs + sdk_pkg_archs + sdk_repo_archs)
    priority = 1  # Start at 1 for SDK repos

    # Overwrite map file and repo file initially
    with open(map_file_path, 'w') as map_f:
        map_f.write('')
    with open(repo_file_path, 'w') as repo_f:
        repo_f.write('')
    bb.note(f"Initial write/clear done for map file: {map_file_path}")

    # --- Unconditionally add the mapping for this recipe's own arch ---
    map_value_path_for_all = f"$releasever/sdk/all"
    with open(map_file_path, 'a') as map_f:
        bb.note(f"Appending unconditional map entry to: {map_file_path}")
        bb.note(f"Adding unconditional map entry: all_avocadosdk={map_value_path_for_all}")
        map_f.write(f"all_avocadosdk={map_value_path_for_all}\n")
    bb.note(f"Finished appending unconditional map entry.")

    # Append to files for other architectures found
    with open(map_file_path, 'a') as map_f, open(repo_file_path, 'a') as repo_f:
        bb.note(f"Opening map file for arch loop append: {map_file_path}")
        # Process the dedicated SDK architectures first to ensure single repo entry (priority 1)
        _process_sdk_archs()

        # Sort architectures with machine arch first, then reverse-sorted tune archs (most specific first)
        machine_arch = machine.replace('-', '_')
        sorted_archs = sorted(list(all_archs))

        # Reorder: machine arch first, then reverse-sorted others (most specific tune first)
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

        # Process all architectures in the correct order (machine first, then most specific tunes first)
        for arch in ordered_archs:
            _process_arch(arch)

        # Add the additional target-ext repo last with highest priority number
        _write_additional_target_repo()
    bb.note(f"Finished arch loop append for map file.")

    # --- Write the SDK-prefixed /etc/dnf/vars/arch file ---
    sdk_arch_vars_path = os.path.join(arch_vars_work_dir, 'arch')
    # Filter out SDK architectures - only include target architectures
    sdk_archs_underscore = [arch.replace('-', '_') for arch in sdk_repo_archs] + ['all_avocadosdk']
    target_archs = [a.replace('-', '_') for a in repo_archs if a.replace('-', '_') not in sdk_archs_underscore]
    final_archs = sorted(list(set(target_archs)))
    with open(sdk_arch_vars_path, 'w') as arch_f:
        arch_f.write(':'.join(final_archs))
        bb.note(f"Wrote {len(final_archs)} target archs to SDK-prefixed {sdk_arch_vars_path}: {':'.join(final_archs)}")

    # --- Write the SDK-prefixed /etc/rpm/platform file ---
    platform_var = d.getVar('PLATFORM') # Get the PLATFORM variable value
    sdk_platform_file_path = os.path.join(platform_work_dir, 'platform')
    with open(sdk_platform_file_path, 'w') as platform_f:
        platform_f.write(platform_var + '\n')
        bb.note(f"Wrote platform '{platform_var}' to SDK-prefixed {sdk_platform_file_path}")

    # --- Write the SDK-prefixed /etc/rpmrc file ---
    sdk_rpmrc_file_path = os.path.join(rpmrc_work_dir, "rpmrc")
    # Get MACHINE_SHORT_NAME with hyphens replaced by underscores
    machine_short_name_us = d.getVar('MACHINEARCH')
    # Join the final_archs list (already contains underscore versions) with spaces
    all_arches_space_sep = ' '.join(final_archs)
    rpmrc_content = f"arch_compat: {machine_short_name_us}: {all_arches_space_sep}\n"
    with open(sdk_rpmrc_file_path, 'w') as rpmrc_f:
        rpmrc_f.write(rpmrc_content)
        bb.note(f"Wrote rpmrc content to SDK-prefixed {sdk_rpmrc_file_path}")
}

python do_install() {
    import os
    import shutil

    work_dir = d.getVar('WORKDIR')
    d_dir = d.getVar('D')

    # Copy all generated files from WORKDIR to D
    generated_files_dir = os.path.join(work_dir, 'generated-files')
    if os.path.exists(generated_files_dir):
        # Copy the entire generated-files directory structure to D
        for root, dirs, files in os.walk(generated_files_dir):
            # Calculate relative path from generated-files
            rel_path = os.path.relpath(root, generated_files_dir)
            if rel_path == '.':
                dest_dir = d_dir
            else:
                dest_dir = os.path.join(d_dir, rel_path)

            # Ensure destination directory exists
            os.makedirs(dest_dir, exist_ok=True)

            # Copy all files
            for file in files:
                src_file = os.path.join(root, file)
                dest_file = os.path.join(dest_dir, file)
                shutil.copy2(src_file, dest_file)
                bb.note(f"Installed {src_file} to {dest_file}")
}

do_deploy() {
    install -d ${DEPLOY_DIR_RPM}
    install -m 0644 ${WORKDIR}/map/avocado-repo.map ${DEPLOY_DIR_RPM}/avocado-repo.map
}

do_deploy[nostamp] = "1"
addtask deploy after do_install
