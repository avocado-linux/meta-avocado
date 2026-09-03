# This Yocto recipe generates repository configuration files for the Avocado SDK.
# It creates the following outputs that get packaged into the resulting SDK:
# 1. avocado-sdk-{machine}.repo: A yum/dnf repository configuration file
# 2. /etc/dnf/vars/arch: Target architecture list for dnf
# 3. /etc/rpm/platform: Platform identifier for rpm
# 4. /etc/rpmrc: RPM architecture compatibility configuration
#
# This recipe checks DEPLOY_DIR_RPM for existing directories and only includes
# repo entries for target architectures that have packages deployed. SDK
# repository entries are always included regardless of whether SDK directories
# exist, ensuring distro builds produce complete repo configurations.
#
# The map file (avocado-repo.map) is generated separately by the
# avocado-repo-map bbclass, which is inherited by the meta-target recipes
# (avocado-distro and avocado-sdk).

DESCRIPTION = "Avocado SDK machine repository configuration"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PV = "${SDK_VERSION}"

PN = "${VIRTUAL-RUNTIME_avocado-sdk-metadata}"
PACKAGES = "${PN}"

RDEPENDS:${PN} = ""

MACHINEARCH = "${@d.getVar('MACHINE_SHORT_NAME').replace('-', '_')}"
PLATFORM = "${MACHINEARCH}-avocado-linux"

# Skip QA checks like ldflags, alreadyinstalled, etc. that are not relevant for this config package
INSANE_SKIP:${PN} = "ldflags alreadyinstalled"

inherit avocado-arch-utils

# The repo file is packaged
FILES:${PN} = " \
    ${SDKPATH}/target-repoconf${sysconfdir}/rpmrc \
    ${SDKPATH}/target-repoconf${sysconfdir}/rpm/platform \
    ${SDKPATH}/target-repoconf${sysconfdir}/dnf/vars/arch \
    ${SDKPATH}/target-repoconf${sysconfdir}/yum.repos.d \
"

# Set package arch so it deploys to a specific directory
PACKAGE_ARCH = "all_avocadosdk"

python do_compile() {
    import os
    import bb
    # Imported and called fully qualified, not aliased. BitBake records the
    # literal call spelling and matches it against the registered name
    # avocado_sdk_metadata.repoconf.<func>; an alias never matches, so the
    # renderer's source would drop out of this task's hash.
    import avocado_sdk_metadata.repoconf

    deploy_dir_rpm = d.getVar('DEPLOY_DIR_RPM')
    machine = d.getVar('MACHINE')
    pkg_archs = (d.getVar('PACKAGE_ARCHS') or "").split()
    sdk_pkg_archs = (d.getVar('SDK_PACKAGE_ARCHS') or "").split()
    # Package signatures. Distinct from AVOCADO_REPO_METADATA_GPGCHECK below,
    # which is the one a signed repomd.xml needs. See
    # meta-avocado/lib/avocado_sdk_metadata/repoconf.py for why they differ.
    gpg_check = d.getVar('AVOCADO_REPO_GPGCHECK') or '0'
    repo_metadata_gpg_check = d.getVar('AVOCADO_REPO_METADATA_GPGCHECK') or '0'
    sdk_repo_archs = (d.getVar('AVOCADO_SDK_REPO_ARCHS') or "").split()
    sdk_repo_archs_underscore = (d.getVar('AVOCADO_SDK_REPO_ARCHS_UNDERSCORE') or "").split()

    # --- Precompute values ---
    machine_short_name = machine.replace('avocado-', '')

    # Track archs for which repo entries are written (for dnf/vars/arch file)
    repo_archs = []
    # Section names already emitted. Under W1 (AVOCADO_PERTARGET_REPOS=1) several archs
    # (machine arch, shared tunes, noarch) collapse to the SAME per-machine repo section
    # ([<machine>-target]); emit that section once but still record every arch so dnf's
    # arch list stays complete. No collapses occur in the legacy 2024 layout, so this is
    # a no-op there.
    written_sections = set()

    def _write_repo_entry(repo_f, repo_url_path, repo_name, repo_section_name, priority, arch):
        """Writes a repository section to the repo file. Appends arch to repo_archs (always,
        for the dnf arch list); the section block itself is written once per section name."""
        nonlocal repo_archs, written_sections
        if repo_url_path and repo_name and repo_section_name:
            repo_archs.append(arch)
            if repo_section_name in written_sections:
                # Same per-machine repo already emitted (another arch); don't duplicate the
                # section or bump priority, but the arch is tracked above.
                return False
            written_sections.add(repo_section_name)
            repo_f.write(avocado_sdk_metadata.repoconf.render_repo_section(
                section=repo_section_name,
                name=repo_name,
                baseurl_path=repo_url_path,
                priority=priority,
                gpgcheck=gpg_check,
                repo_gpgcheck=repo_metadata_gpg_check,
            ))
            return True
        elif arch != "all_avocadosdk":
            bb.warn(f"Repo entry details not fully determined for arch '{arch}'. Skipping repo entry.")
        return False

    def _process_arch(arch, repo_f, priority, deploy_dir_rpm):
        """Process a single architecture and write its repo entry."""
        # Skip sdk-provides-dummy architectures
        if arch.startswith('sdk-provides-dummy'):
            return priority

        # Skip the special arch and dedicated SDK archs (handled separately)
        if arch == "all_avocadosdk" or arch in sdk_repo_archs:
            return priority

        arch_dir = arch.replace('-', '_')

        # Only include archs that have directories in DEPLOY_DIR_RPM
        check_dir = os.path.join(deploy_dir_rpm, arch_dir)
        if not os.path.isdir(check_dir):
            bb.note(f"Skipping arch '{arch}' - directory '{check_dir}' does not exist")
            return priority

        repo_details = avocado_determine_repo_paths(d, arch, arch_dir)

        if _write_repo_entry(
            repo_f,
            repo_details["repo_url_path"],
            repo_details["repo_name"],
            repo_details["repo_section_name"],
            priority, arch
        ):
            priority += 1
        return priority

    def _process_sdk_archs(repo_f, priority, deploy_dir_rpm):
        """Handle SDK architectures - write single shared repo entry.

        Always writes the SDK repo entry regardless of whether the directory
        exists, ensuring distro builds include SDK repository configuration.
        """
        nonlocal repo_archs
        sdk_repo_written = False
        for arch in sdk_repo_archs:
            arch_dir = arch.replace('-', '_')

            repo_details = avocado_determine_repo_paths(d, arch, arch_dir)

            # Write repo entry only once for the first SDK arch
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
                    sdk_repo_written = True
            else:
                # For subsequent SDK archs, just track them
                repo_archs.append(arch)
        return priority

    def _write_additional_target_repo(repo_f, priority):
        """Write the target-ext repo entry at the end."""
        repo_f.write(avocado_sdk_metadata.repoconf.render_repo_section(
            section=f"{machine_short_name}-target-ext",
            name=f"{machine_short_name}-target-ext",
            baseurl_path=f"$releasever/target/{machine_short_name}-ext",
            priority=priority,
            gpgcheck=gpg_check,
            repo_gpgcheck=repo_metadata_gpg_check,
        ))
        bb.note(f"Added additional target repo '{machine_short_name}-target-ext' at priority {priority}")

    # Get SDKPATH for the repo file
    sdk_path = d.getVar('SDKPATH')
    sdk_prefix_stripped = sdk_path.lstrip('/')

    # Create directories in WORKDIR for generated files
    work_dir = d.getVar('WORKDIR')
    repo_work_dir = os.path.join(work_dir, 'generated-files', sdk_prefix_stripped, 'target-repoconf', 'etc', 'yum.repos.d')
    arch_vars_work_dir = os.path.join(work_dir, 'generated-files', sdk_prefix_stripped, 'target-repoconf', 'etc', 'dnf', 'vars')
    platform_work_dir = os.path.join(work_dir, 'generated-files', sdk_prefix_stripped, 'target-repoconf', 'etc', 'rpm')
    rpmrc_work_dir = os.path.join(work_dir, 'generated-files', sdk_prefix_stripped, 'target-repoconf', 'etc')

    os.makedirs(repo_work_dir, exist_ok=True)
    os.makedirs(arch_vars_work_dir, exist_ok=True)
    os.makedirs(platform_work_dir, exist_ok=True)
    os.makedirs(rpmrc_work_dir, exist_ok=True)

    # Define file paths
    repo_filename = d.getVar('VIRTUAL-RUNTIME_avocado-sdk-metadata') + '.repo'
    repo_file_path = os.path.join(repo_work_dir, repo_filename)

    # Combine architectures into a unique set (deterministic - based on PACKAGE_ARCHS)
    all_archs = set(pkg_archs + sdk_pkg_archs + sdk_repo_archs)
    priority = 1

    # Generate repo file
    with open(repo_file_path, 'w') as repo_f:
        # Process SDK architectures first (priority 1)
        priority = _process_sdk_archs(repo_f, priority, deploy_dir_rpm)

        # Get ordered architectures
        ordered_archs = avocado_get_ordered_archs(d, all_archs)

        # Process all architectures
        for arch in ordered_archs:
            priority = _process_arch(arch, repo_f, priority, deploy_dir_rpm)

        # Add the target-ext repo last
        _write_additional_target_repo(repo_f, priority)

    bb.note(f"Generated repo file: {repo_file_path}")

    # --- Write /etc/dnf/vars/arch file ---
    sdk_arch_vars_path = os.path.join(arch_vars_work_dir, 'arch')
    # Arch COMPATIBILITY (this dnf arch list + the /etc/rpmrc arch_compat below)
    # must reflect every valid target package arch for this MACHINE -- i.e.
    # PACKAGE_ARCHS -- NOT just arches that happen to have a DEPLOY_DIR_RPM dir
    # when this recipe builds. The repo entries above are intentionally gated on
    # deploy-dir existence (don't advertise empty repos), but reusing that gated
    # set here drops valid arches whose packages are built after this recipe or
    # only via a packagegroup the image doesn't pull -- e.g. the NXP-BSP SoC arch
    # (MACHINE_SOCARCH, cortexa53-crypto-mx8mp). When that arch is missing, rpm
    # rejects every SoC-arch package ("does not have a compatible architecture")
    # at `avocado ext install`. Source from PACKAGE_ARCHS so the list is complete
    # and stable regardless of build order or which packagegroups are enabled.
    final_archs = avocado_filter_target_archs(d, pkg_archs)
    with open(sdk_arch_vars_path, 'w') as arch_f:
        arch_f.write(':'.join(final_archs))
        bb.note(f"Wrote {len(final_archs)} target archs to {sdk_arch_vars_path}: {':'.join(final_archs)}")

    # --- Write /etc/rpm/platform file ---
    platform_var = d.getVar('PLATFORM')
    sdk_platform_file_path = os.path.join(platform_work_dir, 'platform')
    with open(sdk_platform_file_path, 'w') as platform_f:
        platform_f.write(platform_var + '\n')
        bb.note(f"Wrote platform '{platform_var}' to {sdk_platform_file_path}")

    # --- Write /etc/rpmrc file ---
    sdk_rpmrc_file_path = os.path.join(rpmrc_work_dir, "rpmrc")
    machine_short_name_us = d.getVar('MACHINEARCH')
    all_arches_space_sep = ' '.join(final_archs)
    rpmrc_content = f"arch_compat: {machine_short_name_us}: {all_arches_space_sep}\n"
    with open(sdk_rpmrc_file_path, 'w') as rpmrc_f:
        rpmrc_f.write(rpmrc_content)
        bb.note(f"Wrote rpmrc content to {sdk_rpmrc_file_path}")
}

python do_install() {
    import os
    import shutil

    work_dir = d.getVar('WORKDIR')
    d_dir = d.getVar('D')

    # Copy all generated files from WORKDIR to D
    generated_files_dir = os.path.join(work_dir, 'generated-files')
    if os.path.exists(generated_files_dir):
        for root, dirs, files in os.walk(generated_files_dir):
            rel_path = os.path.relpath(root, generated_files_dir)
            if rel_path == '.':
                dest_dir = d_dir
            else:
                dest_dir = os.path.join(d_dir, rel_path)

            os.makedirs(dest_dir, exist_ok=True)

            for file in files:
                src_file = os.path.join(root, file)
                dest_file = os.path.join(dest_dir, file)
                shutil.copy2(src_file, dest_file)
                bb.note(f"Installed {src_file} to {dest_file}")
}
