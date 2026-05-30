# Uploads each recipe's RPMs to Pulp as orphan content as soon as they are
# written, overlapping the upload work with the build. A separate post-build
# step (pulp-upload-distro Tekton task, finalize path) reads the per-recipe
# manifests this class emits and performs the single modify/publication/
# distribution update per repo.
#
# Modes:
#   AVOCADO_PULP_UPLOAD=1   real upload + manifest. Requires PULP_BASE_URL,
#                           PULP_USERNAME, PULP_PASSWORD, DISTRO_CODENAME.
#                           Activated by distro/kas/ci/pulp-upload.yml.
#   anything else           dry run: manifest only, no HTTP, no sha256. Lets
#                           local developers run distro/scripts/check-pulp-parity.sh
#                           against the same shape of manifests CI produces,
#                           without needing Pulp credentials.
#
# Hook point: do_package_write_rpm[postfuncs] (+ the _setscene twin). This is the
# mechanism OE mandates since SSTATEPOSTINSTFUNCS was removed in oe-core
# 74e08170a5 ("sstate: Drop SSTATEPOSTINSTFUNC support" — deprecated by general
# task postfunc support; buildhistory, its last user, migrated the same way).
# The class previously used SSTATEPOSTINSTFUNCS specifically because it fired
# AFTER files were in DEPLOY_DIR_RPM and the sstate manifest was written, on both
# the live and setscene paths. With postfuncs the timing differs per path, so we
# read the RPMs from the right place for each:
#
#   * Live build (do_package_write_rpm): sstate.bbclass orders non-"buildhistory"
#     postfuncs AHEAD of sstate_task_postfunc, so this fires BEFORE the RPMs are
#     moved PKGWRITEDIRRPM -> DEPLOY_DIR_RPM and before any sstate manifest is
#     written. We read this recipe's freshly written RPMs straight from
#     PKGWRITEDIRRPM (${WORKDIR}/deploy-rpms/<arch>).
#   * Setscene (do_package_write_rpm_setscene): this fires AFTER the sstate
#     unpack, so the RPMs are in DEPLOY_DIR_RPM and the per-recipe sstate manifest
#     exists; we read that manifest to select exactly this recipe's RPMs
#     (DEPLOY_DIR_RPM is shared across recipes).
#
# Both paths upload + record the pulp_href, with a sha256 lookup first so a
# setscene-restored recipe that was already uploaded in a prior build is reused,
# not re-pushed. addtask is still NOT viable: kernel.bbclass's task-graph
# manipulation makes bitbake silently skip a separately-added task.
#
# Failure mode: fail-closed. Any upload or lookup error in real-upload mode
# raises bb.fatal, which fails the recipe and the build. The build/finalize
# Tekton task additionally parity-checks RPMs-on-disk against manifest entries,
# so a silently-disconnected hook fails the pipeline rather than shipping a
# partial feed (this is the regression guard for exactly the SSTATEPOSTINSTFUNCS
# removal that broke the first wrynose build).

inherit avocado-arch-utils

do_package_write_rpm[postfuncs] += "avocado_pulp_postinst"
do_package_write_rpm_setscene[postfuncs] += "avocado_pulp_postinst"

# avocado_pulp_postinst is a side-effect-only emitter (uploads to Pulp + writes a
# manifest under DEPLOY_DIR); it must NOT influence task signatures, or toggling
# AVOCADO_PULP_UPLOAD — or merely inheriting this class — would invalidate sstate
# and rebuild the world. Exclude it from both tasks' dependency calculation, the
# same pattern buildhistory uses for buildhistory_list_pkg_files.
do_package_write_rpm[vardepsexclude] += "avocado_pulp_postinst"
do_package_write_rpm_setscene[vardepsexclude] += "avocado_pulp_postinst"

# Pulp credentials and the upload-mode toggle are environment, not build
# inputs. Excluding them from vardeps keeps the function body stable when creds
# rotate or when toggling between dev (AVOCADO_PULP_UPLOAD=0) and CI
# (AVOCADO_PULP_UPLOAD=1) builds.
avocado_pulp_postinst[vardepsexclude] = "AVOCADO_PULP_UPLOAD AVOCADO_PULP_UPLOAD_EXCLUDE PULP_BASE_URL PULP_USERNAME PULP_PASSWORD PULP_CA_BUNDLE SSL_CERT_FILE AVOCADO_PULP_CHUNK_SIZE AVOCADO_PULP_UPLOAD_PARALLEL AVOCADO_PULP_RECIPE_PARALLEL AVOCADO_PULP_UPLOAD_SDK_ONLY"

def _avocado_pulp_env(d):
    # Read via the bitbake datastore rather than os.environ: bitbake filters
    # task-subprocess env per BB_ENV_PASSTHROUGH, which drops these vars, but
    # the datastore always has them (set via kas env -> bitbake).
    import bb
    base = (d.getVar('PULP_BASE_URL') or '').rstrip('/')
    user = d.getVar('PULP_USERNAME') or ''
    pw = d.getVar('PULP_PASSWORD') or ''
    # CA bundle for TLS verification. The same env-filtering that drops the creds
    # also drops SSL_CERT_FILE from the bitbake worker, and urllib runs INSIDE the
    # worker — so we cannot rely on the ambient default trust store (it lacks the
    # internal package-ca and TLS verification fails). Read the bundle path from
    # the datastore and hand it to ssl explicitly. Prefer an explicit
    # PULP_CA_BUNDLE, fall back to SSL_CERT_FILE if the build exported it.
    ca = d.getVar('PULP_CA_BUNDLE') or d.getVar('SSL_CERT_FILE') or ''
    if not base:
        bb.fatal("avocado-pulp-upload: AVOCADO_PULP_UPLOAD=1 but PULP_BASE_URL is empty")
    return base, user, pw, ca

def _avocado_pulp_http(url, method='GET', data=None, content_type=None, user='', pw='', timeout=120, ca='', headers=None):
    import urllib.request, urllib.error, base64, time, random, ssl
    # Verify against the supplied CA bundle (package-ca + system roots) when
    # given; otherwise fall back to urllib's default context. Built once,
    # outside the retry loop.
    ctx = ssl.create_default_context(cafile=ca) if ca else None
    attempts = 8
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            if content_type:
                req.add_header('Content-Type', content_type)
            for hk, hv in (headers or {}).items():
                req.add_header(hk, hv)
            if user:
                token = base64.b64encode(f"{user}:{pw}".encode()).decode()
                req.add_header('Authorization', f'Basic {token}')
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
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

def _avocado_pulp_lookup(base, user, pw, sha256_hex, ca=''):
    import json
    url = f"{base}/pulp/api/v3/content/rpm/packages/?sha256={sha256_hex}&fields=pulp_href,sha256"
    _, body = _avocado_pulp_http(url, user=user, pw=pw, ca=ca)
    data = json.loads(body)
    if data.get('count', 0) > 0:
        return data['results'][0]['pulp_href']
    return None

def _avocado_pulp_wait_task(base, user, pw, task_href, ca=''):
    import json, time, bb
    url = f"{base}{task_href}"
    deadline = time.time() + 600
    while time.time() < deadline:
        _, body = _avocado_pulp_http(url, user=user, pw=pw, ca=ca)
        data = json.loads(body)
        state = data.get('state', '')
        if state == 'completed':
            created = data.get('created_resources', [])
            if not created:
                bb.fatal(f"avocado-pulp-upload: task {task_href} completed with no resources")
            return created[0]
        if state in ('failed', 'canceled'):
            err = data.get('error') or {}
            reason = ' '.join(str(err.get(k, '')) for k in ('reason', 'description', 'traceback')).lower()
            # Transient infra failures — a Pulp worker that died / was OOM-killed /
            # was scaled-down mid-task ("Worker has gone missing"), a cancellation,
            # or a lock/deadlock — are RETRYABLE: the caller re-submits rather than
            # failing the whole recipe (and the build). A canceled task is ~always
            # worker churn. Signalled via a RuntimeError prefix the dispatcher
            # catches; real failures still bb.fatal. See _avocado_pulp_upload.
            markers = ('gone missing', 'worker shutting down', 'connection reset',
                       'temporarily unavailable', 'timed out', 'deadlock', 'lock timeout')
            if state == 'canceled' or any(m in reason for m in markers):
                raise RuntimeError(f"AVOCADO_PULP_TRANSIENT: task {task_href} {state}: {err}")
            bb.fatal(f"avocado-pulp-upload: task {task_href} {state}: {err}")
        time.sleep(0.5)
    # A task that never completes within the window is most likely a wedged/lost
    # worker — treat as transient so the caller retries instead of failing.
    raise RuntimeError(f"AVOCADO_PULP_TRANSIENT: task {task_href} did not complete within 600s")

def _avocado_multipart(file_field, filename, filebytes, extra_fields=None):
    # Build a multipart/form-data body: optional plain fields + one file part.
    import uuid
    boundary = f"----avocado{uuid.uuid4().hex}"
    parts = []
    for k, v in (extra_fields or {}).items():
        parts += [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode(),
            f"{v}\r\n".encode(),
        ]
    parts += [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(),
        b'Content-Type: application/octet-stream\r\n\r\n',
        filebytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'

def _avocado_pulp_upload_singleshot(base, user, pw, rpm_path, ca=''):
    # One multipart POST with the whole file. Fine for small RPMs; avoids the
    # 3-extra-requests + 2-tasks overhead of the chunked path.
    import os, json, bb
    with open(rpm_path, 'rb') as f:
        filedata = f.read()
    body, ctype = _avocado_multipart('file', os.path.basename(rpm_path), filedata)
    _, resp_body = _avocado_pulp_http(
        f"{base}/pulp/api/v3/content/rpm/packages/", method='POST', data=body,
        content_type=ctype, user=user, pw=pw, timeout=600, ca=ca,
    )
    task_href = json.loads(resp_body).get('task', '')
    if not task_href:
        bb.fatal(f"avocado-pulp-upload: POST returned no task href")
    return _avocado_pulp_wait_task(base, user, pw, task_href, ca=ca)

def _avocado_pulp_upload_chunked(base, user, pw, rpm_path, sha256_hex, ca='', chunk_size=16 << 20, parallel=4):
    # Resilient large-file upload via Pulp's chunked uploads API:
    #   POST /uploads/ {size} -> PUT each Content-Range chunk (in parallel) ->
    #   commit {sha256} -> create the rpm package from the resulting artifact.
    # Each request is bounded (one chunk), so the gunicorn worker timeout is
    # never at risk; parallel chunks fill the VPN's bandwidth-delay product that
    # a single stream leaves idle; and only `parallel` chunks are ever held in
    # memory at once (vs. the whole file + a copy in the single-shot path).
    import os, json, bb, urllib.parse
    import concurrent.futures as cf
    size = os.path.getsize(rpm_path)
    _, body = _avocado_pulp_http(
        f"{base}/pulp/api/v3/uploads/", method='POST',
        data=json.dumps({"size": size}).encode(), content_type='application/json',
        user=user, pw=pw, ca=ca,
    )
    upload_href = json.loads(body)['pulp_href']

    ranges = []
    off = 0
    while off < size:
        end = min(off + chunk_size, size) - 1
        ranges.append((off, end))
        off = end + 1

    fname = os.path.basename(rpm_path)
    def _put(rng):
        start, end = rng
        with open(rpm_path, 'rb') as f:
            f.seek(start)
            chunk = f.read(end - start + 1)
        cbody, ctype = _avocado_multipart('file', fname, chunk)
        _avocado_pulp_http(
            f"{base}{upload_href}", method='PUT', data=cbody, content_type=ctype,
            user=user, pw=pw, timeout=600, ca=ca,
            headers={'Content-Range': f'bytes {start}-{end}/{size}'},
        )
    if parallel > 1 and len(ranges) > 1:
        with cf.ThreadPoolExecutor(max_workers=parallel) as ex:
            list(ex.map(_put, ranges))   # re-raises the first chunk failure
    else:
        for rng in ranges:
            _put(rng)

    # commit (assemble + verify the full sha256) -> artifact href
    _, body = _avocado_pulp_http(
        f"{base}{upload_href}commit/", method='POST',
        data=json.dumps({"sha256": sha256_hex}).encode(), content_type='application/json',
        user=user, pw=pw, ca=ca,
    )
    artifact_href = _avocado_pulp_wait_task(base, user, pw, json.loads(body)['task'], ca=ca)

    # create the rpm package from the committed artifact
    form = urllib.parse.urlencode({'artifact': artifact_href, 'relative_path': fname}).encode()
    _, body = _avocado_pulp_http(
        f"{base}/pulp/api/v3/content/rpm/packages/", method='POST', data=form,
        content_type='application/x-www-form-urlencoded', user=user, pw=pw, timeout=600, ca=ca,
    )
    task_href = json.loads(body).get('task', '')
    if not task_href:
        bb.fatal(f"avocado-pulp-upload: package create returned no task href")
    return _avocado_pulp_wait_task(base, user, pw, task_href, ca=ca)

def _avocado_pulp_upload(base, user, pw, rpm_path, sha256_hex='', ca='', chunk_size=16 << 20, parallel=4):
    import os, time, random, bb
    # Chunk only files large enough to benefit; small RPMs stay single-request
    # (1 task) to avoid multiplying load on the Pulp workers.
    big = os.path.getsize(rpm_path) > chunk_size
    # Retry the whole upload on TRANSIENT task failures — a Pulp worker that was
    # scaled-down / OOM-killed / restarted mid content-create surfaces as "Worker
    # has gone missing" and would otherwise fail the recipe (and a 12k-task build)
    # over one infra blip. The artifact is content-addressed, so a re-upload
    # dedups; and before each retry we check whether the content actually landed
    # despite the worker error (the task can fail *after* creating the package).
    attempts = 4
    last = None
    for i in range(attempts):
        try:
            if big:
                return _avocado_pulp_upload_chunked(base, user, pw, rpm_path, sha256_hex, ca=ca,
                                                    chunk_size=chunk_size, parallel=parallel)
            return _avocado_pulp_upload_singleshot(base, user, pw, rpm_path, ca=ca)
        except RuntimeError as e:
            if not str(e).startswith("AVOCADO_PULP_TRANSIENT"):
                raise           # real failure (or bb.fatal) — propagate
            last = e
            if sha256_hex:
                href = _avocado_pulp_lookup(base, user, pw, sha256_hex, ca=ca)
                if href:
                    bb.warn(f"avocado-pulp-upload: transient task error but content is present, "
                            f"using it ({sha256_hex[:12]})")
                    return href
            if i < attempts - 1:
                bb.warn(f"avocado-pulp-upload: transient Pulp failure, retry {i + 1}/{attempts} "
                        f"for {os.path.basename(rpm_path)}: {e}")
                time.sleep(min(30, 2 ** i) + random.uniform(0, 1))
    bb.fatal(f"avocado-pulp-upload: gave up after {attempts} transient Pulp failures "
             f"for {os.path.basename(rpm_path)}: {last}")

def _avocado_rpms_from_pkgwrite(d):
    # Live-build path. Our postfunc runs before sstate moves the RPMs out of
    # PKGWRITEDIRRPM (sstate.bbclass orders non-"buildhistory" postfuncs ahead of
    # sstate_task_postfunc), so no sstate manifest exists yet. PKGWRITEDIRRPM
    # (${WORKDIR}/deploy-rpms) is per-recipe, so everything under it belongs to
    # this recipe — no risk of mis-attributing a sibling's RPMs. RPMs are laid
    # out as <PKGWRITEDIRRPM>/<PACKAGE_ARCH_EXTEND>/<name>.rpm, the same
    # arch-subdir shape they keep once moved to DEPLOY_DIR_RPM.
    import os, glob
    base = d.getVar('PKGWRITEDIRRPM')
    if not base or not os.path.isdir(base):
        return []
    results = []
    for path in sorted(glob.glob(os.path.join(base, '*', '*.rpm'))):
        arch_dir = os.path.basename(os.path.dirname(path))
        pkg_arch = arch_dir.replace('_', '-')
        results.append((pkg_arch, arch_dir, path))
    return results

def _avocado_rpms_from_manifest(d):
    # Setscene path. Our postfunc runs after the sstate unpack, so the RPMs are
    # in DEPLOY_DIR_RPM and bitbake's per-recipe sstate manifest is present.
    # ${SSTATE_MANFILEPREFIX} expands to the exact per-recipe file prefix (no
    # globbing), so sibling recipes with similar names (native, nativesdk
    # variants) sharing DEPLOY_DIR_RPM don't get their RPMs mis-attributed here.
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

def _avocado_rpms_for_recipe(d):
    # Pick the source by which task we're a postfunc of: the live build writes
    # to PKGWRITEDIRRPM (read it before sstate relocates it); the setscene task
    # unpacks into DEPLOY_DIR_RPM and writes the sstate manifest (read that).
    task = d.getVar('BB_CURRENTTASK') or ''
    if task == 'package_write_rpm_setscene':
        return _avocado_rpms_from_manifest(d)
    return _avocado_rpms_from_pkgwrite(d)

python avocado_pulp_postinst() {
    import os, hashlib, json, bb

    # Defensive guard: we are only attached as a postfunc of do_package_write_rpm
    # and its _setscene twin, but assert it so a stray attachment can't run this
    # against an unexpected task. BB_CURRENTTASK is the do_-stripped task name.
    task = d.getVar('BB_CURRENTTASK') or ''
    if task not in ('package_write_rpm', 'package_write_rpm_setscene'):
        return

    do_upload = d.getVar('AVOCADO_PULP_UPLOAD') == '1'

    distro_codename = d.getVar('DISTRO_CODENAME') or ''
    if '/' in distro_codename:
        release, channel = distro_codename.split('/', 1)
    elif do_upload:
        bb.fatal("avocado-pulp-upload: AVOCADO_PULP_UPLOAD=1 but DISTRO_CODENAME must be set as 'release/channel'")
    else:
        # Dry-run path: tolerate a non-canonical DISTRO_CODENAME (or none) so
        # local dev builds without the CI overlay still emit manifests for the
        # parity check. The repo_path/repo_name fields end up with placeholder
        # values, which is fine — dry-run entries are flagged dry_run=true and
        # the parity check only counts lines.
        release, channel = (distro_codename or 'dev'), 'local'

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

    # SDK-build mode: an `avocado-sdk` build also packages target/cross RPMs as
    # deps, but those belong to the distro feed (and re-uploading them risks
    # variant duplicates in the target repo). When AVOCADO_PULP_UPLOAD_SDK_ONLY=1
    # we publish ONLY the SDK-arch packages (the *-avocadosdk arches + the
    # all_avocadosdk noarch SDK packages); target-arch RPMs are skipped entirely.
    sdk_only = d.getVar('AVOCADO_PULP_UPLOAD_SDK_ONLY') == '1'
    sdk_archs = set(
        (d.getVar('AVOCADO_SDK_REPO_ARCHS') or '').split()
        + (d.getVar('AVOCADO_SDK_REPO_ARCHS_UNDERSCORE') or '').split()
        + ['all_avocadosdk', 'all-avocadosdk'])

    rpms = _avocado_rpms_for_recipe(d)
    if not rpms:
        return

    # Look up Pulp creds only when we actually need them (real upload + not
    # excluded), so dry-run and excluded-only paths can't fail on missing env.
    base = user = pw = ca = None
    if do_upload and not excluded:
        base, user, pw, ca = _avocado_pulp_env(d)
    # Chunked-upload tuning (large files only): chunk size + parallel streams.
    chunk_size = int(d.getVar('AVOCADO_PULP_CHUNK_SIZE') or (16 << 20))
    parallel = int(d.getVar('AVOCADO_PULP_UPLOAD_PARALLEL') or 4)
    # Per-recipe parallelism: how many of THIS recipe's RPMs to dedup+upload
    # concurrently. Fan-out recipes (glibc-locale emits ~1900 tiny RPMs, kernel
    # modules, *-locale) otherwise serialize thousands of small WAN round-trips
    # and dominate the build tail; running them concurrently is the biggest win.
    recipe_parallel = int(d.getVar('AVOCADO_PULP_RECIPE_PARALLEL') or 8)

    manifest_dir = os.path.join(deploy_dir, 'pulp-uploads')
    bb.utils.mkdirhier(manifest_dir)
    manifest_path = os.path.join(manifest_dir, f"{pn}-{pv}-{pr}-{machine}{mc_suffix}.jsonl")

    # Phase 1 (serial, local only): build a manifest entry per RPM. Resolve the
    # per-machine Pulp repo and skip dummies / unmapped arches. No network here.
    items = []
    for pkg_arch, arch_dir, path in rpms:
        if arch_dir.startswith('sdk_provides_dummy') or pkg_arch.startswith('sdk-provides-dummy'):
            continue
        # In SDK-only mode, publish only the SDK-arch packages; skip target/cross RPMs.
        if sdk_only and arch_dir not in sdk_archs and pkg_arch not in sdk_archs:
            continue
        repo_details = avocado_determine_repo_paths(d, pkg_arch, arch_dir)
        # Key the Pulp repo off repo_url_path (the repo root / repomd baseurl), NOT
        # map_value_path (the per-arch package dir). They are identical in the legacy
        # 2024 layout, but under W1 (AVOCADO_PERTARGET_REPOS=1) repo_url_path is the
        # single per-machine root ($releasever/target/<machine>) while map_value_path
        # is the arch subdir beneath it -- so all of a machine's arches (machine arch,
        # shared tunes, noarch) land in ONE Pulp repo + ONE repomd. Falls back to
        # map_value_path if repo_url_path is unset.
        repo_root = repo_details.get('repo_url_path') or repo_details.get('map_value_path')
        if not repo_root:
            continue
        repo_path = repo_root.replace('$releasever', f"{release}/{channel}")
        prefix = f"{release}/{channel}/"
        tail = repo_path[len(prefix):] if repo_path.startswith(prefix) else repo_path
        repo_name = f"{release}-{channel}-" + tail.replace('/', '-')
        items.append({
            "rpm_name": os.path.basename(path),
            "sha256": "",
            "arch_dir": arch_dir,
            "repo_name": repo_name,
            "repo_path": repo_path,
            "pulp_href": "",
            "machine": machine,
            "sdkmachine": sdkmachine,
            "uploaded": False,
            "excluded": excluded,
            "dry_run": not do_upload,
            "_path": path,
        })

    # Phase 2 (concurrent): hash + dedup + upload each publishable RPM. Workers
    # mutate their own entry dict (no shared state). Fail-closed: the first
    # worker error re-raises out of the map and fails the task. Skipped for
    # excluded recipes and dry runs (no network in either).
    def _process(entry):
        path = entry["_path"]
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        sha256_hex = h.hexdigest()
        existing = _avocado_pulp_lookup(base, user, pw, sha256_hex, ca=ca)
        if existing:
            entry["pulp_href"], entry["uploaded"] = existing, False
        else:
            entry["pulp_href"] = _avocado_pulp_upload(
                base, user, pw, path, sha256_hex=sha256_hex, ca=ca,
                chunk_size=chunk_size, parallel=parallel)
            entry["uploaded"] = True
        entry["sha256"] = sha256_hex

    if do_upload and not excluded and items:
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(max_workers=min(recipe_parallel, len(items))) as ex:
            list(ex.map(_process, items))   # re-raises the first failure

    # Phase 3: write the manifest (drop the private _path key) + emit notes.
    # Last writer wins on re-fire (live + setscene) -- identical content.
    with open(manifest_path, 'w') as mf:
        for e in items:
            mf.write(json.dumps({k: v for k, v in e.items() if not k.startswith('_')}) + "\n")
        mf.flush()
    for e in items:
        if e["excluded"]:
            bb.note(f"avocado-pulp-upload: {e['rpm_name']} (excluded, not published)")
        elif do_upload:
            bb.note(f"avocado-pulp-upload: {e['rpm_name']} -> {e['pulp_href']} ({'uploaded' if e['uploaded'] else 'reused'})")
}
