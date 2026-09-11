# Repository audit and release checks

Rechecked GitHub `main` at `77d3c76` on 11 September 2026. VERSION now agrees
with the 1.15.1 runtime metadata, and all seven release-consistency and four
helper-preflight tests pass locally against that published source.

The earlier `b0389ba` upload had source `clab-backup-ui/VERSION` that
contained `1.15.0`, while the app, discovery/operations/Git helpers, Compose image
tag and Docker image label contained `1.15.1`. This stopped fresh installation
at helper verification, before the image build or container creation.

Compared with the delivered 1.15.1 source ZIP, GitHub also lacked `.gitignore`
and `.gitattributes`, and had a different validation document. Other shared
files matched after normalizing line endings. A folder name or commit message
does not determine the running release.

## Published changes and remaining web-upload items

- Corrected VERSION to 1.15.1, matching the existing release contents.
- Removed unreferenced root `changes.patch` and `changes-1.2.0.patch` artifacts
  (154,457 bytes combined). They remain retrievable from Git history.
- Still to delete: the unused `deploy/clab_manager_files.py` development entry point.
  The installer already uses `clab-backup-ui/app/host_files.py`; the installed
  `/usr/local/lib/clab-manager/clab_manager_files.py` path is unchanged.
- Still to upload: `.gitignore`, `.gitattributes`, `.github/workflows/release-check.yml`
  and `clab-backup-ui/.dockerignore`. They were omitted from the web upload. The
  completion bundle contains them at their exact repository paths.
- Restore `LAB-OPERATIONS.md`: it was deleted, but current guides still link to
  it. An updated 1.15.1 copy is included. The historical LAB-COMMANDS-PLAN.md is
  not required for the running application and can remain deleted.
- Kept vendor JavaScript/licenses, test fixtures and migration/reference guides:
  those are intentional project content. Historical guides remain marked as such.

## Before packaging, publishing or starting the manager

Run from the source root; only Python's standard library is needed:

```bash
python3 deploy/verify-release.py
```

The check compares VERSION with the app, all helpers, image label/tag and browser
asset versions. `start-manager.sh` runs it before changing the host. The Docker
build also checks VERSION against the app. After the missing workflow is uploaded,
GitHub Actions will run the source check and its regression tests on pushes and
pull requests. No successful Actions run is claimed for the current upload. Branch protection must
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

The version repair and obsolete-patch deletions are published. The additional
completion files and updated documentation are prepared locally for web upload.
No Docker publication or VM deployment is implied by this audit.
