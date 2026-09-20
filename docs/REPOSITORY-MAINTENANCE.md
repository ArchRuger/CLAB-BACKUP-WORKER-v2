# Repository maintenance and release rules

How a release is cut, what must stay in lockstep, what the documentation may and
may not say, and what CI checks. The history of the audit that introduced these
checks is in the [archive](archive/REPOSITORY-AUDIT-1.15.1.md).

## One release number, everywhere it matters

`clab-backup-ui/VERSION` is the release. Every other place that carries the number
must agree with it, because the launcher, the health check and the VM helpers all
compare them and refuse a mixed tree:

| Where | Checked by |
|---|---|
| `clab-backup-ui/app/__init__.py` (`__version__`, shown by the API and the footer) | `verify-release.py` |
| `clab-backup-ui/app/host_files.py` (`helper_version`), `host_operations.py` and `host_git.py` (`VERSION`) | `verify-release.py`; the launcher compares the installed helpers with it |
| `clab-backup-ui/Dockerfile` OCI label and `compose.yml` image tag | `verify-release.py`; the Docker build asserts the label |
| `deploy/compose.capture.yml` session-service image tag | `verify-release.py` |
| The `?v=` on every `/static/...` asset in the HTML pages, and the footer fallback in `app.js` | `verify-release.py` (stale browser assets hide new controls after an upgrade) |
| `Current release: **x.y.z**` in the README | `verify-release.py` (documentation check) |
| The first `## Changes in x.y.z` of `docs/CHANGELOG.md`, the first `# … — x.y.z` of `clab-backup-ui/VALIDATION.md` and of `agent instructions.md` | `verify-release.py` (documentation check) |

Run the check from any directory; only Python's standard library is needed:

```bash
python3 "$HOME/projects/clab-manager/deploy/verify-release.py"
```

It prints `Source release verified: x.y.z` and `Documentation names only release
x.y.z.`, or lists every mismatch with its file and line. The VM scripts run the
runtime half (`--runtime`) before touching the host; `--docs` runs the
documentation half alone. `tests/test_release_consistency.py` runs both against
the checkout, and the CI workflow runs the script on every push and pull request.

## What the documentation may say about versions

The guides describe the current release and name no version of their own. A
guide that says "this guide targets release X", clones into `~/projects/vX.Y.Z` or
builds `clab-backup:X.Y.Z` goes stale at the next release and sends users to
folders and images that do not exist; that is exactly what the documentation check
refuses. The rules, enforced by `verify_docs()` in `deploy/verify-release.py`:

- **Living guides** (`README.md`, `docs/*.md`, `deploy/*.md`, the app README,
  `NODE-FEATURES.md`, the VM connection and capture setup pages) may name the
  manager's release only where they mean the current one, for example the
  installer's closing line `Manager 1.30.5: running`. Those mentions are moved by
  the bump tool.
- **Release history** is written with a relational phrase, which is allowed
  anywhere: `since 1.23.0`, `before 1.21.1`, `introduced in 1.19.4`, `as of 1.22.0`,
  `upgrading from 1.20.1`, `1.22.0 or later`, `1.18.0 and earlier`. Anything else
  that names another release is reported with its file and line.
- **A third-party version** that shares the manager's major number (the Flow panel
  plugin, for example) is fine when the component is named shortly before it
  (`andrewbmchugh-flow-panel 1.20.1`).
- **Versioned source folders** (`projects/vX.Y.Z`) and **versioned image tags**
  (`clab-backup:X.Y.Z`, `clab-capture-service:X.Y.Z`) are refused in the living
  guides outright. The source folder is `~/projects/clab-manager`; an image tag is
  the value of `clab-backup-ui/VERSION`.
- **History files** may name any release: `docs/CHANGELOG.md`,
  `clab-backup-ui/VALIDATION.md`, `agent instructions.md` and everything under
  `docs/archive/`, `docs/redesign/` and `docs/ui-review-001/` (design notes and a per-release
  review log). Each of the first three must lead with the current release.
- **Every documented command works from any directory.** Scripts locate the
  checkout themselves; the guides write `bash "$HOME/projects/clab-manager/deploy/…"`
  and the health check's `Next:` lines print absolute paths. A command that needs a
  working directory (the unit tests) changes into it itself.

## Cutting a release

1. Decide the number from the current checkout: patch for a compatible fix, minor
   for a compatible feature, major for a breaking change.
2. Move every marker at once and let the tool list what it touched:

   ```bash
   python3 "$HOME/projects/clab-manager/deploy/set-release.py" X.Y.Z
   ```

   It rewrites `VERSION`, the runtime lockstep files and every current-release
   mention in the living guides; history phrases and third-party versions are left
   alone.
3. Write the release history by hand: a `## Changes in X.Y.Z` section at the top
   of `docs/CHANGELOG.md`, a `# <title> — X.Y.Z` section at the top of
   `clab-backup-ui/VALIDATION.md` with what was actually tested (never claim a build,
   VM deployment, live-device test or push that did not happen), and the same at the
   top of `agent instructions.md` with what the next agent must preserve.
4. Run the checks and the tests, then commit everything with Git, dotfiles
   included; never replace selected files through a browser upload. Deploy scripts
   and `VERSION` stay LF (`.gitattributes` enforces it).
5. Push and open a pull request; CI runs the release check, the unit and browser
   tests, the shell syntax check and the real capture and Grafana smoke tests.

Do not overwrite an existing numbered release with different contents. A Git tag
identifies source; a Docker tag identifies a built image; neither implies a
deployment.

## What stays out of the repository

Generated archives, patches, runtime data, `.env` files, keys and credentials are
ignored (`.gitignore`, `.dockerignore`). Keep source archives in an ignored `dist/`
or in release assets, and local VM data outside the source tree. Vendor JavaScript
and its licences, test fixtures and the archived guides are intentional content.

## CI

`.github/workflows/release-check.yml` runs on every push and pull request:

1. `python3 deploy/verify-release.py` (runtime and documentation).
2. The release, installer, Git onboarding, APT and health-check regression tests.
3. `bash -n` on every deploy shell script.
4. The application test suites in a virtual environment, the telemetry suites, the
   browser test files under `node --test`, and the capture suites.
5. `docker compose config` for both stacks, then the real Grafana stack against a
   fixture manager (`deploy/telemetry/smoke.py`) and real browser Wireshark with
   loopback packets (`deploy/capture/smoke.py`).

Branch protection must require the workflow if merges are to be blocked on a red
check.
