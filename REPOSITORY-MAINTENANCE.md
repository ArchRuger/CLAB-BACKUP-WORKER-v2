# Repository audit and release checks

Audited GitHub `main` at `b0389ba` (V1.15.1). The source `clab-backup-ui/VERSION`
contained `1.15.0`, while the app, discovery/operations/Git helpers, Compose image
tag and Docker image label contained `1.15.1`. This stopped fresh installation
at helper verification, before the image build or container creation.

Compared with the delivered 1.15.1 source ZIP, GitHub also lacked `.gitignore`
and `.gitattributes`, and had a different validation document. Other shared
files matched after normalizing line endings. A folder name or commit message
does not determine the running release.

## Cleanup performed

- Corrected VERSION to 1.15.1, matching the existing release contents.
- Removed unreferenced root `changes.patch` and `changes-1.2.0.patch` artifacts
  (154,457 bytes combined). They remain retrievable from Git history.
- Removed the unused `deploy/clab_manager_files.py` development entry point.
  The installer already uses `clab-backup-ui/app/host_files.py`; the installed
  `/usr/local/lib/clab-manager/clab_manager_files.py` path is unchanged.
- Restored ignore and line-ending rules. Added Docker context exclusions for
  local data, environment files, Python caches, tests and generated archives.
- Kept vendor JavaScript/licenses, test fixtures and migration/reference guides:
  those are intentional project content. Historical guides remain marked as such.

## Before packaging, publishing or starting the manager

Run from the source root; only Python's standard library is needed:

```bash
python3 deploy/verify-release.py
```

The check compares VERSION with the app, all helpers, image label/tag and browser
asset versions. `start-manager.sh` runs it before changing the host. The Docker
build also checks VERSION against the app. GitHub Actions runs the source check
and its regression tests on pushes and pull requests. Branch protection must
require the check if merges should be blocked on failure.

Commit the complete change with Git, including dotfiles, rather than replacing
selected files through a browser upload. Use `git status --short` to review the
changes. Keep source archives and patches in ignored `dist/` or release assets;
keep local VM data and credentials outside the source tree.

## Repair the affected fresh VM

For the audited 1.15.1 checkout whose only runtime-version mismatch is VERSION:

```bash
printf '1.15.1\n' > clab-backup-ui/VERSION
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
```

Do not change the version blindly for other mixed releases. Obtain complete,
matching source instead. The improved helper verifier now reports the expected
and actual numeric versions without printing deployment files or credentials.

These changes are prepared locally. No GitHub push, Docker publication or VM
deployment is implied by this audit.
