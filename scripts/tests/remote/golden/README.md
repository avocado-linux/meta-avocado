# Remote eMMC backend goldens

These files pin the bash eMMC install kit that the Python remote backend is
ported from. They are the reference the port is measured against, not
fixtures the port may adjust.

## Never regenerate a golden to make the port pass

When the port disagrees with a golden, the port is wrong until shown
otherwise. Do not re-capture, re-hash or hand-edit a file here to turn a
failing test green. Moving the baseline is a decision in its own right: it
needs its own reviewed change that says why the old reference was wrong and
where the new one came from.

## Files

| File | What it is |
|------|------------|
| `kit-manifest.sha256` | sha256 of the four kit scripts (`stage.sh`, `preflight.sh`, `install.sh`, `readback.sh`) and the three kit test scripts (`test-install.sh`, `test-stage.sh`, `test-window-scripts.sh`), in `sha256sum` format with bare file names |
| `real-board-dry-run.txt` | Output of the kit's `install.sh` dry run on the real board, including its `DRYRUN-RC=` trailer |

### kit-manifest.sha256

The kit itself is not copied into this repository. It lives in the bring-up
change's evidence directory (the `emmc/` folder of the carrier-board BSP
bring-up change), outside any repo. The manifest records the kit's hashes as
they stood when it was pinned, which includes the SecureBoot fix in
`preflight.sh` that reads the efivarfs file sequentially instead of seeking it.

Nothing in this repository can be checked against the manifest, because the
scripts it names are not here. To confirm the kit has not moved, run from the
kit directory:

```sh
sha256sum -c /path/to/scripts/tests/remote/golden/kit-manifest.sha256
```

The manifest uses relative file names only, so it carries no home directory
or host path.

### real-board-dry-run.txt

Byte-for-byte copy of the kit's recorded dry-run output from the bring-up
change's `first-boot/` evidence. It ends with
`dry run complete: no mutating tool was called`.

## Scrubbing

Every file copied into this directory is scrubbed of customer names, end-user
names and host names (SSH aliases, hostnames) before it lands, and any such
token is replaced with a neutral one such as `target-board`. This repository is
public.

For the files present now, no replacement was needed: the dry-run output names
only device nodes, partition labels, image file names and `/run` staging paths,
and the manifest names only the seven script files. The dry run is therefore an
unmodified copy.
