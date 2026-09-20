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

- [x] helper: `publish`, `revise`, capabilities (code written)
- [ ] helper tests
- [ ] manager routes (`lab_operations.py` preview for publish/revise, size cap, name collision, diff)
- [ ] `main.py` CSP + caching exception, tests
- [ ] `lab-builder/` TypeScript project, committed assets, licences/notices
- [ ] `static/lab-builder.html`, `lab-builder-page.js`, `lab-builder.css`, entry points in `operations.js`
- [ ] fixture manager support + Playwright student workflow
- [ ] `parse_definition` groups fix (separate commit)
- [ ] docs, CHANGELOG, VALIDATION, agent instructions, CI list, release
- [ ] live validation on the dev VM
