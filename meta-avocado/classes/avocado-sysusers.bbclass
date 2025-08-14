# avocado-sysusers.bbclass
#
# Goal: For any recipe that declares USERADD_*/GROUPADD_*,
#       emit /usr/lib/sysusers.d/<pkg>.conf with equivalent rules.
#
# Notes:
# - This does not *remove* useradd's postinsts by default; see the
#   "Disable useradd postinsts" section at bottom if you want that.
# - We only translate a commonly used subset of options (-u, -g, -G, -d, -s, -r, -c).
#   Extend as needed.

python sysusers_emit() {
    import os, shlex

    # Only generate sysusers files if systemd is in DISTRO_FEATURES
    distro_features = d.getVar('DISTRO_FEATURES') or ""
    if 'systemd' not in distro_features:
        return

    dvar = d.getVar
    pkgs = (dvar('USERADD_PACKAGES') or "").split()
    if not pkgs:
        return

    # Log package names being processed
    bb.note("avocado-sysusers: Generating sysusers.d files for packages: %s" % ", ".join(pkgs))

    libdir = dvar('libdir') or '/usr/lib'
    destroot = dvar('D') or ''
    if not destroot:
        bb.note("D variable not set, skipping sysusers file generation")
        return

    sysusers_dir = os.path.join(destroot, libdir.lstrip('/'), 'sysusers.d')
    bb.utils.mkdirhier(sysusers_dir)

    for pkg in pkgs:
        ua = dvar('USERADD_PARAM:%s' % pkg) or ""
        ga = dvar('GROUPADD_PARAM:%s' % pkg) or ""

        # Split on semicolons to handle multiple entries in same variable
        # Example: "-r -u 450 user1; -r -u 451 user2"
        useradd_entries = [entry.strip() for entry in ua.split(';') if entry.strip()]
        groupadd_entries = [entry.strip() for entry in ga.split(';') if entry.strip()]

        # Build sysusers lines for all entries
        lines = []

        # Process all groupadd entries first
        for ga_entry in groupadd_entries:
            if not ga_entry:
                continue

            gparts = shlex.split(ga_entry)
            if not gparts:
                continue

            # Find group name (last non-flag token)
            g_name = None
            for p in reversed(gparts):
                if not p.startswith('-'):
                    g_name = p
                    break

            if not g_name:
                continue

            # Find '-g <gid>'
            g_gid = '-'
            for j, p in enumerate(gparts):
                if p == '-g' and j+1 < len(gparts):
                    g_gid = gparts[j+1]
                    break

            lines.append("g %-16s %-6s -" % (g_name, g_gid))

        # Process all useradd entries
        for ua_entry in useradd_entries:
            if not ua_entry:
                continue

            parts = shlex.split(ua_entry)
            if not parts:
                continue

            # Extract the username (last token that doesn't start with "-")
            username = None
            for p in reversed(parts):
                if not p.startswith('-'):
                    username = p
                    break
            if not username:
                continue

            # Defaults
            uid = '-'
            primary_group = '-'
            suppl_groups = []
            home = '-'
            shell = '-'
            gecos = '-'
            system = False

            # Walk flags
            i = 0
            while i < len(parts):
                tok = parts[i]
                if tok == '-u':
                    uid = parts[i+1]; i += 2; continue
                if tok == '-g':
                    primary_group = parts[i+1]; i += 2; continue
                if tok == '-G':
                    suppl_groups = parts[i+1].split(','); i += 2; continue
                if tok == '-d':
                    home = parts[i+1]; i += 2; continue
                if tok == '-s':
                    shell = parts[i+1]; i += 2; continue
                if tok == '-c':
                    gecos = parts[i+1]; i += 2; continue
                if tok == '-r':
                    system = True; i += 1; continue
                i += 1

            # System users are usually locked; if you want login-capable, drop the '!' below.
            user_type = "u!" if system else "u"

            # Empty fields must be '-' in sysusers format
            def dash(x): return x if x and x != "" else '-'
            uid = dash(uid)
            primary_group = dash(primary_group)
            home = dash(home)
            shell = dash(shell)
            gecos = dash(gecos)

            lines.append("%s %-16s %-6s %s %s %s" % (user_type, username, uid, gecos, home, shell))

            # Supplementary groups
            for g in suppl_groups:
                if g:
                    lines.append("m %-16s %s" % (username, g))

        # Skip if no lines generated
        if not lines:
            continue

        # Write file only if it doesn't already exist
        out = os.path.join(sysusers_dir, "%s.conf" % pkg)
        if os.path.exists(out):
            bb.note("avocado-sysusers: Skipping %s - file already exists" % out)
            continue

        try:
            # Ensure the directory exists again just before writing
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, 'w', encoding='utf-8') as f:
                f.write("# Auto-generated from Yocto USERADD_/GROUPADD_ by avocado-sysusers.bbclass\n")
                for l in lines:
                    f.write(l + "\n")
            bb.note("avocado-sysusers: Generated sysusers.d config: %s" % out)
        except Exception as e:
            bb.warn("Failed to write sysusers.d config for %s: %s" % (pkg, str(e)))
            continue

        # Ensure runtime deps so the file is honored at boot
        d.appendVar("RDEPENDS:%s" % pkg, " systemd")
}

python sysusers_package_files() {
    """
    Run before do_package to dynamically add any created sysusers.d files to FILES variables
    """
    import os, glob

    dvar = d.getVar
    destroot = dvar('D') or ''
    libdir = dvar('libdir') or '/usr/lib'

    if not destroot:
        return

    # Look for any sysusers.d files that were actually created
    sysusers_dir = os.path.join(destroot, libdir.lstrip('/'), 'sysusers.d')

    if not os.path.exists(sysusers_dir):
        return

    # Find all .conf files in the sysusers.d directory
    conf_files = glob.glob(os.path.join(sysusers_dir, '*.conf'))
    if not conf_files:
        return

    # Get package info
    useradd_packages = (dvar('USERADD_PACKAGES') or "").split()
    pn = dvar('PN')

    bb.note("sysusers_package_files: Adding %d sysusers.d files to package manifests" % len(conf_files))

    for conf_file in conf_files:
        # Extract filename (e.g., "openssh-sshd.conf" -> "openssh-sshd")
        basename = os.path.basename(conf_file)
        pkg_name = basename.replace('.conf', '')

        # Determine which FILES variable to update
        files_var = None
        if pkg_name == pn:
            files_var = "FILES:%s" % pn  # Use actual package name, not ${PN}
        elif pkg_name in useradd_packages:
            files_var = "FILES:%s" % pkg_name
        else:
            # Default to main package
            files_var = "FILES:%s" % pn  # Use actual package name, not ${PN}

        # Add to FILES variable - use relative path from DESTDIR
        rel_path = "${libdir}/sysusers.d/%s" % basename
        current = d.getVar(files_var) or ""

        if rel_path not in current:
            # Use appendVar to properly append instead of setVar
            d.appendVar(files_var, " " + rel_path)
            bb.note("sysusers_package_files: Added %s to %s" % (basename, files_var))
}

# Only run for recipes that actually have USERADD_PACKAGES
python __anonymous() {
    # Prevent multiple runs on the same recipe
    if d.getVar('AVOCADO_SYSUSERS_PROCESSED'):
        return
    d.setVar('AVOCADO_SYSUSERS_PROCESSED', '1')

    useradd_packages = d.getVar('USERADD_PACKAGES')
    distro_features = d.getVar('DISTRO_FEATURES') or ""

    if useradd_packages and 'systemd' in distro_features:
        # Only append to do_install for recipes that need it
        d.appendVarFlag('do_install', 'postfuncs', ' sysusers_emit')

        # Hook into do_package to add FILES dynamically before QA checks
        d.prependVarFlag('do_package', 'prefuncs', 'sysusers_package_files ')
}
