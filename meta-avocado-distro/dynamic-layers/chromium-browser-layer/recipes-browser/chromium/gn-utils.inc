# GN host architecture helpers.
#
# BUILD_ARCH's value corresponds to what uname returns as the machine name.
# The mapping in gn_host_arch_name() tries to match several possible values
# returned by the Linux kernel in uname(2) into the corresponding values GN
# understands.
def gn_host_arch_name(d):
    """Returns a GN architecture name corresponding to the build host's machine
    architecture."""
    import re
    arch_translations = {
        r'aarch64.*': 'arm64',
        r'arm.*': 'arm',
        r'i[3456]86$': 'x86',
        r'x86_64$': 'x64',
    }
    build_arch = d.getVar("BUILD_ARCH")
    for arch_regexp, gn_arch_name in arch_translations.items():
        if re.match(arch_regexp, build_arch):
            return gn_arch_name
    bb.fatal('Unsuported BUILD_ARCH value: "%s"' % build_arch)

# GN target architecture helpers.
#
# Determining the target architecture is more difficult, as there are many
# different values we can use on the Yocto side (e.g. TUNE_ARCH, TARGET_ARCH,
# MACHINEOVERRIDES etc). What we do is define the mapping with regular,
# non-Python variables with overrides that are generic enough (i.e. "x86"
# instead of "i586") and then use gn_target_arch_name() to return the right
# value with some validation.
GN_TARGET_ARCH_NAME:aarch64 = "arm64"
GN_TARGET_ARCH_NAME:arm = "arm"
GN_TARGET_ARCH_NAME:x86 = "x86"
GN_TARGET_ARCH_NAME:x86-64 = "x64"

def clang_install_path(d):
    """Return clang compiler install path."""
    import os
    return os.path.join(d.getVar("STAGING_DIR_NATIVE"), "usr")

def gn_target_arch_name(d):
    """Returns a GN architecture name corresponding to the target machine's
    architecture."""
    name = d.getVar("GN_TARGET_ARCH_NAME")
    if name is None:
        bb.fatal('Unsupported target architecture. A valid override for the '
                 'GN_TARGET_ARCH_NAME variable could not be found.')
    return name

def write_toolchain_file(d, file_path):
    """Creates a complete GN toolchain file in |file_path|."""
    import string
    # Even though we always use clang, the "clang_toolchain" GN template is too
    # restrictive in the way it sets variables such as |cxx|. Since it is just
    # a wrapper on top of the "gcc_toolchain" template, we keep using the
    # latter directly to accommodate our cross-compilation needs.
    toolchain_tmpl = string.Template(
        'gcc_toolchain("${toolchain_name}") {\n'
        '  cc = "${cc}"\n'
        '  cxx = "${cxx}"\n'
        '  ar = "${ar}"\n'
        '  ld = cxx  # GN expects a compiler, not a linker.\n'
        '  nm = "${nm}"\n'
        '  readelf = "${readelf}"\n'
        '  extra_cflags = "${extra_cflags}"\n'
        '  extra_cppflags = "${extra_cppflags}"\n'
        '  extra_cxxflags = "${extra_cxxflags}"\n'
        '  extra_ldflags = "${extra_ldflags}"\n'
        '  toolchain_args = {\n'
        '    current_cpu = "${current_cpu}"\n'
        '    current_os = "linux"\n'
        '    is_clang = true\n'
        '    cc_wrapper = "${cc_wrapper}"\n'
        '  }\n'
        '}\n'
    )

    # OE bakes a compiler launcher (ccache.bbclass sets CCACHE="ccache ") into
    # CC/CXX/BUILD_CC/BUILD_CXX as a prefix. GN's gcc_toolchain feeds cxx to
    # rustc as -Clinker, and rustc treats -Clinker as a single binary, so a
    # prefixed "ccache clang++" makes rustc fail with 'linker `ccache clang++`
    # not found'. Chromium's own mechanism for a launcher is toolchain_args
    # cc_wrapper, which GN prepends to C/C++ compiles only, never to the rust
    # linker. Lift the launcher out of cc/cxx and pass it as cc_wrapper so both
    # the C++ compiles stay cached and the rust link step gets a bare compiler.
    ccache = d.getVar('CCACHE') or ''

    def strip_launcher(value):
        stripped = value[len(ccache):] if ccache and value.startswith(ccache) else value
        # rustc execs the -Clinker value (ld = cxx) as a single program, so a
        # trailing space left by an empty BUILD_CC_ARCH ("clang++ ") makes it
        # fail with 'linker `clang++ ` not found'. Trim it; GN word-splits the
        # C/C++ compile command anyway, so trailing whitespace is meaningless
        # there.
        return stripped.rstrip()

    cc_wrapper = ccache.strip()

    native_toolchain = {
        'toolchain_name': 'yocto_native',
        'current_cpu': gn_host_arch_name(d),
        'cc': strip_launcher(d.expand('${BUILD_CC}')),
        'cxx': strip_launcher(d.expand('${BUILD_CXX}')),
        'ar': d.expand('${BUILD_AR}'),
        'nm': d.expand('${BUILD_NM}'),
        'readelf': d.expand('${BUILD_PREFIX}readelf'),
        'extra_cflags': d.expand('${BUILD_CFLAGS}'),
        'extra_cppflags': d.expand('${BUILD_CPPFLAGS}'),
        'extra_cxxflags': d.expand('${BUILD_CXXFLAGS}'),
        'extra_ldflags': d.expand('${BUILD_LDFLAGS}'),
        'cc_wrapper': cc_wrapper,
    }
    target_toolchain = {
        'toolchain_name': 'yocto_target',
        'current_cpu': gn_target_arch_name(d),
        'cc': strip_launcher(d.expand('${CC}')),
        'cxx': strip_launcher(d.expand('${CXX}')),
        'ar': d.expand('${AR}'),
        'nm': d.expand('${NM}'),
        'readelf': d.expand('${READELF}'),
        'extra_cflags': d.expand('${CFLAGS}'),
        'extra_cppflags': d.expand('${CPPFLAGS}'),
        'extra_cxxflags': d.expand('${CXXFLAGS}'),
        'extra_ldflags': d.expand('${LDFLAGS}'),
        'cc_wrapper': cc_wrapper,
    }

    with open(file_path, 'w') as toolchain_file:
        toolchain_file.write(
            '# This file has been generated automatically.\n'
            '\n'
            'import("//build/toolchain/gcc_toolchain.gni")\n'
            '\n'
        )
        toolchain_file.write(toolchain_tmpl.substitute(native_toolchain))
        toolchain_file.write(toolchain_tmpl.substitute(target_toolchain))
