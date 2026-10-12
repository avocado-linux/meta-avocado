# Turns DEPLOY_DIR_RPM into a directly servable avocado feed.
#
# avocado-repo.map already says which deploy/rpm arch dir belongs to which
# repo root (sdk/all, sdk/<machine>, target/<machine>). This class makes that
# real under AVOCADO_FEED_DIR: one relative symlink per arch dir, then
# createrepo_c --update once per root. Nothing is copied, so an RPM that
# sstate removes from deploy/rpm leaves the feed too.
#
# Serve the whole DEPLOY_DIR (the symlinks point at ../rpm) with
# scripts/feed-serve.sh and point the CLI at it with AVOCADO_REPO_URL.
# target/<machine>-ext is created empty for `avocado ext package --out-dir`.

inherit avocado-repo-map

AVOCADO_FEED_DIR ?= "${DEPLOY_DIR}/avocado-feed"

python avocado_feed_index() {
    import os
    import shutil
    import subprocess

    bb.build.exec_func('do_create_repo_map', d)

    rpm_dir = d.getVar('DEPLOY_DIR_RPM')
    feed_dir = d.getVar('AVOCADO_FEED_DIR')
    createrepo = bb.utils.which(os.environ['PATH'], 'createrepo_c')
    if not createrepo:
        bb.fatal("createrepo_c not in PATH; add createrepo-c-native to DEPENDS")

    entries = []
    with open(os.path.join(rpm_dir, 'avocado-repo.map')) as f:
        for line in f:
            key, _, path = line.strip().partition('=')
            entries.append((key, path.replace('$releasever/', '', 1)))
    roots = [path for key, path in entries if key == 'repo']

    links = {}
    for key, path in entries:
        if key == 'repo' or not os.path.isdir(os.path.join(rpm_dir, key)):
            continue
        # Flat repos (sdk/<machine>) take several arch dirs, so the arch dir
        # always becomes a leaf under its package path. A package path that is
        # itself a repo root (the pooled layout, AVOCADO_PERTARGET_REPOS=0, maps
        # noarch=target/noarch and repo=target/noarch) keeps the link below the
        # root, or the root would be a link into deploy/rpm and createrepo_c
        # would write repodata there.
        if os.path.basename(path) == key and path not in roots:
            leaf = path
        else:
            leaf = os.path.join(path, key)
        links[os.path.join(feed_dir, leaf)] = os.path.join(rpm_dir, key)

    # Drop links the map no longer names (arch dir gone, layout changed).
    for top, dirs, files in os.walk(feed_dir):
        for name in dirs + files:
            p = os.path.join(top, name)
            if os.path.islink(p) and p not in links:
                os.unlink(p)

    for link, target in links.items():
        bb.utils.mkdirhier(os.path.dirname(link))
        rel = os.path.relpath(target, os.path.dirname(link))
        if os.path.islink(link) and os.readlink(link) == rel:
            continue
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(rel, link)

    roots += [r + '-ext' for r in roots if r.startswith('target/')]

    # A root the map no longer names lost its links above, so its repodata now
    # lists packages that are gone. Drop that repodata so the server stops
    # offering them. -ext roots hold real extension RPMs, not links, so their
    # metadata still matches what is on disk and is kept.
    active = {os.path.join(feed_dir, r) for r in roots}
    for top, dirs, files in os.walk(feed_dir):
        if 'repodata' in dirs and top not in active and not top.endswith('-ext'):
            shutil.rmtree(os.path.join(top, 'repodata'))
            dirs.remove('repodata')

    for root in roots:
        repo = os.path.join(feed_dir, root)
        bb.utils.mkdirhier(repo)
        bb.note(f"Indexing {repo}")
        subprocess.run([createrepo, '--update', '-q', '--general-compress-type', 'gz', repo],
                       check=True)
}
