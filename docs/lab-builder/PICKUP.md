# Visual lab builder: pickup file

Branch `claude/visual-lab-builder`. The maintainer approved the build on 2026-09-20 with every
recommended default. This file is the single place that says what is decided, what is done and what is
next; update it with every committed chunk.

Research, the independent review, the feasibility report and the throwaway prototype live outside the
repository in `~/research/lab-builder/` (`FEASIBILITY-REPORT.md`, `README.md`, `evidence/`, `prototype/`).

## Decisions (binding)

- Editor: `@containerlab/clab-ui` pinned exactly, on its own page `static/lab-builder.html`, our own
  host adapter, `TopologySessionCore` in the page. Inline-style CSP exception for that one document;
  script-src untouched. YAML/JSON tabs off; the publish review shows the YAML read-only.
- Controls that cannot work (Geo layout, Split view, Grafana export, all deploy items but one) are hidden
  by `data-testid` from our stylesheet, with a test that fails when upstream renames them. The remaining
  deploy button opens the manager's save review.
- Drafts live in the browser (journal before ack, revision check, download/upload). Never in the Store.
- Assets are prebuilt and committed; never built on a user VM. CI rebuilds and compares hashes.
  Caching exception for the builder's asset path.
- Destination `<trusted root>/<lab>/<lab>.clab.yml` (+ `.annotations.json`), default root
  `/srv/containerlab-node-manager/projects`. No Git destination, no startup-configs in this version.
- Saving again (`revise`) only while the lab is not deployed: recovery copies, opened-version hashes.
- After saving: the existing Topology file dialog (Deploy lab / Add to My labs). No new lifecycle path.
- Entry: beside `#op-create` in the Deploy dialog; "Edit visually" on an existing topology file.
- Curated device templates + free-text images; blank and starter topologies.
- The `topology.groups` kind-resolution defect in `parse_definition` is fixed as a separate change.
- The maintainer allows live testing on the dev VM `clab-llm-dev2` (helper refresh, container rebuild,
  lab deploys). Record in VALIDATION only what actually ran.

## Publication contract

See `~/research/lab-builder/FEASIBILITY-REPORT.md` section 7. Helper actions `publish` and `revise`
in `app/host_operations.py`; annotations first, YAML last; descriptor-relative writes; fsync before
link; resume only from states that write order can produce; recovery is a fresh preview.

## Progress

- [x] helper: `publish`, `revise`, capabilities; helper and API tests
- [x] manager routes: preview checks (parse, name pin, size cap, name collision, layout warning, diff), `known-images`
- [x] `main.py` inline-style exception for the page, caching exception for its assets; tests
- [x] `clab-backup-ui/lab-builder/` build project (exact pins, lockfile), committed assets + manifest,
      `--check` rebuild comparison, generated third-party notices, Monaco chunk stubbed
- [x] `static/lab-builder.html`, `lab-builder-page.js`, `lab-builder.css`; entry points and review copy in `operations.js`
- [x] fixture manager support; `docs/lab-builder/tools/student_workflow.py` (38 checks) passes
- [x] `parse_definition` groups fix (own commit)
- [x] release markers moved with `set-release.py`
- [x] live validation on the dev VM: 38 of 38 workflow checks through the real gateway and helper, Linux hosts,
      real deploy and destroy; delete / name reuse / refusals through the API (see VALIDATION)
- [x] docs, CHANGELOG, VALIDATION, agent instructions; CI list and asset rebuild check
- [x] branch pushed, pull request opened

## Open after this release

- Deploy a builder-made lab with router images (cEOS, cJunosEvolved, vJunos-switch, XRv9k) and check the
  interface patterns against the running devices.
- Watch upstream for a published `lifecycleActionsAvailable` prop and a switch for Geo layout; both would
  retire a `data-testid` rule in `lab-builder.css`.
- Not in this version by decision: startup-config files, Git destinations, image management, editable YAML.

How to rebuild the editor assets: `cd clab-backup-ui/lab-builder && npm ci && node build.mjs` with Node 24
(a portable one is in `~/research/lab-builder/tooling/`). `node build.mjs --check` compares a fresh build
with the committed manifest.
