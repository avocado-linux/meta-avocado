# Uploads each recipe's RPMs to Pulp as orphan content as soon as they are
# written, overlapping the upload work with the build. A separate post-build
# step (pulp-upload-distro Tekton task, finalize path) reads the per-recipe
# manifests this class emits and performs the single modify/publication/
# distribution update per repo.
#
# Activation: set AVOCADO_PULP_UPLOAD=1 in the environment (via a kas CI
# overlay). Also requires PULP_BASE_URL, PULP_USERNAME, PULP_PASSWORD, and
# DISTRO_CODENAME to be set. Nothing is hardcoded - all endpoints come from
# the environment.
#
# Failure mode: fail-closed. Any upload or lookup error raises bb.fatal, which
# fails the recipe and the build.

inherit avocado-arch-utils

# For recipes that actually build, run the upload as a separate task AFTER
# do_package_write_rpm — so the sstate-outputdirs copy from ${WORKDIR}/
# deploy-rpms to ${DEPLOY_DIR_RPM} has completed by the time we scan.
addtask pulp_rpm_push after do_package_write_rpm before do_build
do_pulp_rpm_push[nostamp] = "1"
# Bitbake sandboxes tasks in a network-restricted namespace by default for
# reproducibility. This task legitimately needs to reach Pulp.
do_pulp_rpm_push[network] = "1"

# For recipes satisfied entirely by sstate, the separate task gets pruned
# by the scheduler. Hook the same logic as a postfunc on the setscene
# task, which extracts RPMs directly to DEPLOY_DIR_RPM during its run —
# so the postfunc fires after files are in place. Gated by
# AVOCADO_PULP_UPLOAD so non-CI builds don't need Pulp access.
python() {
    if d.getVar('AVOCADO_PULP_UPLOAD') == '1':
        d.appendVarFlag('do_package_write_rpm_setscene', 'postfuncs', ' do_pulp_rpm_push')
}

def _avocado_pulp_env(d):
    # Read via the bitbake datastore rather than os.environ: bitbake filters
    # task-subprocess env per BB_ENV_PASSTHROUGH, which drops these vars, but
    # the datastore always has them (set via kas env -> bitbake).
    import bb
    base = (d.getVar('PULP_BASE_URL') or '').rstrip('/')
    user = d.getVar('PULP_USERNAME') or ''
    pw = d.getVar('PULP_PASSWORD') or ''
    if not base:
        bb.fatal("avocado-pulp-upload: AVOCADO_PULP_UPLOAD=1 but PULP_BASE_URL is empty")
    return base, user, pw

def _avocado_pulp_http(url, method='GET', data=None, content_type=None, user='', pw='', timeout=120):
    import urllib.request, urllib.error, base64, time, random
    attempts = 8
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            if content_type:
                req.add_header('Content-Type', content_type)
            if user:
                token = base64.b64encode(f"{user}:{pw}".encode()).decode()
                req.add_header('Authorization', f'Basic {token}')
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if 400 <= e.code < 500:
                raise
        except (urllib.error.URLError, OSError) as e:
            last_err = e
        if i < attempts - 1:
            # Exponential backoff with jitter. DNS rate-limits under many
            # parallel bitbake task subprocesses; spread retries out.
            time.sleep(min(30, 2 ** i) + random.uniform(0, 1))
    raise last_err

def _avocado_pulp_lookup(base, user, pw, sha256_hex):
    import json
    url = f"{base}/pulp/api/v3/content/rpm/packages/?sha256={sha256_hex}&fields=pulp_href,sha256"
    _, body = _avocado_pulp_http(url, user=user, pw=pw)
    data = json.loads(body)
    if data.get('count', 0) > 0:
        return data['results'][0]['pulp_href']
    return None

def _avocado_pulp_wait_task(base, user, pw, task_href):
    import json, time, bb
    url = f"{base}{task_href}"
    deadline = time.time() + 600
    while time.time() < deadline:
        _, body = _avocado_pulp_http(url, user=user, pw=pw)
        data = json.loads(body)
        state = data.get('state', '')
        if state == 'completed':
            created = data.get('created_resources', [])
            if not created:
                bb.fatal(f"avocado-pulp-upload: task {task_href} completed with no resources")
            return created[0]
        if state in ('failed', 'canceled'):
            bb.fatal(f"avocado-pulp-upload: task {task_href} {state}: {data.get('error')}")
        time.sleep(0.5)
    bb.fatal(f"avocado-pulp-upload: task {task_href} did not complete within 600s")

def _avocado_pulp_upload(base, user, pw, rpm_path):
    import os, uuid, json, bb
    boundary = f"----avocado{uuid.uuid4().hex}"
    with open(rpm_path, 'rb') as f:
        filedata = f.read()
    filename = os.path.basename(rpm_path)
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b'Content-Type: application/x-rpm\r\n\r\n',
        filedata,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b''.join(parts)
    url = f"{base}/pulp/api/v3/content/rpm/packages/"
    _, resp_body = _avocado_pulp_http(
        url, method='POST', data=body,
        content_type=f'multipart/form-data; boundary={boundary}',
        user=user, pw=pw, timeout=600,
    )
    resp = json.loads(resp_body)
    task_href = resp.get('task', '')
    if not task_href:
        bb.fatal(f"avocado-pulp-upload: POST returned no task href: {resp}")
    return _avocado_pulp_wait_task(base, user, pw, task_href)

def _avocado_rpms_for_recipe(d):
    # Read bitbake's own sstate manifest for this recipe's
    # do_package_write_rpm task. ${SSTATE_MANFILEPREFIX} expands to the exact
    # per-recipe file prefix (no globbing needed), so sibling recipes with
    # similar names (native, nativesdk variants) don't get their manifests
    # mis-attributed to this one. Populated for both real and setscene paths
    # before any task depending on do_package_write_rpm runs.
    import os
    manfile = d.expand('${SSTATE_MANFILEPREFIX}.package_write_rpm')
    if not manfile or not os.path.isfile(manfile):
        return []

    results = []
    with open(manfile) as f:
        for line in f:
            line = line.strip()
            if not line or not line.endswith('.rpm'):
                continue
            if not os.path.exists(line):
                continue
            arch_dir = os.path.basename(os.path.dirname(line))
            pkg_arch = arch_dir.replace('_', '-')
            results.append((pkg_arch, arch_dir, line))
    return results

python do_pulp_rpm_push() {
    import os, hashlib, json, bb

    if d.getVar('AVOCADO_PULP_UPLOAD') != '1':
        return

    distro_codename = d.getVar('DISTRO_CODENAME') or ''
    if '/' not in distro_codename:
        bb.fatal("avocado-pulp-upload: DISTRO_CODENAME must be set as 'release/channel'")
    release, channel = distro_codename.split('/', 1)

    deploy_dir = d.getVar('DEPLOY_DIR')
    pn = d.getVar('PN')
    pv = d.getVar('PV')
    pr = d.getVar('PR')
    machine = d.getVar('MACHINE') or ''
    sdkmachine = d.getVar('SDKMACHINE') or ''

    # When the same MACHINE is used across multiconfigs (e.g. jetson-l4t shares
    # MACHINE with the default mc), manifests would collide on the same filename.
    # TMPDIR is per-mc by convention (tmp-<mc> vs tmp), so derive the mc name
    # from it to produce unique filenames without any new variable plumbing.
    tmpdir = d.getVar('TMPDIR') or ''
    topdir = d.getVar('TOPDIR') or ''
    _rel = tmpdir[len(topdir):].lstrip('/')
    _mc_name = _rel[4:] if _rel.startswith('tmp-') else ''
    mc_suffix = f"-{_mc_name}" if _mc_name else ''

    # Recipes in AVOCADO_PULP_UPLOAD_EXCLUDE (e.g. aggregator metapackages
    # whose binary bytes are machine-dependent) still get manifest entries
    # so the parity check's disk-count matches; those entries are marked
    # excluded=true and the finalize step skips them.
    exclude_list = (d.getVar('AVOCADO_PULP_UPLOAD_EXCLUDE') or '').split()
    excluded = pn in exclude_list

    rpms = _avocado_rpms_for_recipe(d)
    if not rpms:
        return

    # Look up Pulp creds only when we actually need them (not for excluded
    # recipes, so those can't fail on missing env either).
    base = user = pw = None
    if not excluded:
        base, user, pw = _avocado_pulp_env(d)

    manifest_dir = os.path.join(deploy_dir, 'pulp-uploads')
    bb.utils.mkdirhier(manifest_dir)
    manifest_path = os.path.join(manifest_dir, f"{pn}-{pv}-{pr}-{machine}{mc_suffix}.jsonl")

    # Truncate on open: the addtask task and the setscene postfunc may both
    # fire for setscene-satisfied recipes, and both produce the same set of
    # entries. Last writer wins — either is authoritative and the content is
    # identical, so no data loss.
    with open(manifest_path, 'w') as mf:
        for pkg_arch, arch_dir, path in rpms:
            if arch_dir.startswith('sdk_provides_dummy') or pkg_arch.startswith('sdk-provides-dummy'):
                continue

            repo_details = avocado_determine_repo_paths(d, pkg_arch, arch_dir)
            map_value_path = repo_details.get('map_value_path')
            if not map_value_path:
                continue

            repo_path = map_value_path.replace('$releasever', f"{release}/{channel}")
            prefix = f"{release}/{channel}/"
            tail = repo_path[len(prefix):] if repo_path.startswith(prefix) else repo_path
            repo_name = f"{release}-{channel}-" + tail.replace('/', '-')

            if excluded:
                entry = {
                    "rpm_name": os.path.basename(path),
                    "sha256": "",
                    "arch_dir": arch_dir,
                    "repo_name": repo_name,
                    "repo_path": repo_path,
                    "pulp_href": "",
                    "machine": machine,
                    "sdkmachine": sdkmachine,
                    "uploaded": False,
                    "excluded": True,
                }
                mf.write(json.dumps(entry) + "\n")
                mf.flush()
                bb.note(f"avocado-pulp-upload: {entry['rpm_name']} (excluded, not published)")
                continue

            h = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
            sha256_hex = h.hexdigest()

            existing = _avocado_pulp_lookup(base, user, pw, sha256_hex)
            if existing:
                pulp_href = existing
                uploaded = False
            else:
                pulp_href = _avocado_pulp_upload(base, user, pw, path)
                uploaded = True

            entry = {
                "rpm_name": os.path.basename(path),
                "sha256": sha256_hex,
                "arch_dir": arch_dir,
                "repo_name": repo_name,
                "repo_path": repo_path,
                "pulp_href": pulp_href,
                "machine": machine,
                "sdkmachine": sdkmachine,
                "uploaded": uploaded,
                "excluded": False,
            }
            mf.write(json.dumps(entry) + "\n")
            mf.flush()
            bb.note(f"avocado-pulp-upload: {entry['rpm_name']} -> {pulp_href} ({'uploaded' if uploaded else 'reused'})")
}
