# Visual lab builder — proposal under review (NOT approved for implementation)

Maintainer has approved only: one independent review and an isolated feasibility prototype.
No production code, helper, CSP or release change is authorised.

## Requirements

- Create a new containerlab topology from the manager's browser UI (nodes, kinds/images, links,
  properties, YAML review), save it onto the VM, optionally deploy through the existing reviewed
  operation; the lab then appears in the normal workflow. Students are a primary audience.
- Prefer reusing SR Labs `@containerlab/clab-ui` if a clean, maintainable seam exists.
- Keep the security boundary: no Docker socket/root in the manager; one forced-command SSH
  account; three sudoers helpers (root, stdlib-only copies of app/host_*.py); trusted roots;
  preview -> confirm with a helper digest; host flock; `operation_busy`. No clab-api-server.
- Standing rules: frontend "plain scripts, no build step, no framework, no CDN"; self-only CSP,
  `style-src 'unsafe-inline'` only for two xterm pages, script-src never relaxed, two tests pin
  "/" without unsafe-inline; every existing test keeps its behavioural claim; VM YAML `write`
  was removed in 1.12.0 and its refusal is pinned by tests; image built from source on every
  user VM; CI never builds the manager image.
- Maintainer's added conditions: no silent loss of topology fields or annotations; no clickable
  controls that predictably fail; draft state, published topology and running lab state stay
  separate; the single-file `create` guarantees must not be assumed to cover a multi-file folder.

## Evidence (condensed reader results, recovered from the workflow journal)

reports/mgr-host-ops.md, mgr-topology-backend.md, mgr-frontend.md,
mgr-install-security-git.md, up-public-api-license.md, up-editor-core.md,
up-host-backend.md, up-apps-build-theme.md. The long-form versions were lost when /tmp was
wiped; the condensed results keep every load-bearing claim with its citation.
Sources: manager `main` 398d726 (1.29.1); upstream be0ec244 (clab-ui 0.4.0, unpublished) in
inputs/containerlab-app; PUBLISHED @containerlab/clab-ui 0.3.2 (shasum e153aad0…) unpacked in
inputs/npm-0.3.2/package. Claims about what we can consume must be checked against 0.3.2.

## Proposal

### 1. Editor: clab-ui 0.3.2 `<App>` on its own page, our own host

- Dedicated document (`lab-builder.html`), never an island in index.html.
- Custom `ClabUiHost`; `TopologySessionCore` runs in the page over a `FileSystemAdapter` that
  is NOT a filesystem: an in-memory two-document store (YAML + `<yaml>.annotations.json`) that
  absorbs the core's tmp-write / rename-to-.bak / rename / unlink sequence and flushes the
  settled pair to a manager *draft* with a debounced PUT.
- Seeded custom node templates for the manager's supported kinds (+ linux); deploy/destroy
  controls replaced or removed; features that cannot work under the manager's policy (Geo
  layout: blob worker + external tiles) must be removed, not left to fail.
- CSP for that page only: `style-src 'self' 'unsafe-inline'`; script-src stays 'self'. Editable
  YAML only if it can be had without 'unsafe-eval'.
- Bundle built outside user VMs, exact version pin, Apache-2.0 text and third-party notices
  shipped beside it (elkjs EPL-2.0 unmodified).

### 2. Backend: drafts + one reviewed multi-file publish (design only)

State separation
- Draft: manager Store, `{id, name, root, yaml, annotations, revision, status}`; never exposed
  through /api/state beyond id/name/status; the only thing the editor writes.
- Published topology: files on the VM; written only by the publish operation below.
- Running lab: the existing lab record, created only by the existing registration chain
  (read -> parse-yaml -> /api/lab-definitions -> operations-settings -> deploy review).

Publish action (new action of the existing operations helper, preview/run, under the flock)
- Request: `root` (must equal a configured trusted root exactly), `name` (helper `identity()`),
  `yaml` text, optional `annotations` text, each <= 512 KiB (helper request line is 2 MiB).
  The helper derives every path: `dir=<root>/<name>`, `yaml=<dir>/<name>.clab.yml`,
  `ann=<yaml>.annotations.json`. No client-supplied path components.
- Manager preview runs `parse_definition` on the YAML, checks `name:` equals `name`, checks the
  annotations parse with `parse_drawing`, binds the draft revision into the preview token.
- Helper plan: every component symlink-free; `dir` must not exist, OR exist containing only a
  subset of {ann, yaml} whose sha256 equal the request (resume / lost-response case). Digest
  binds action, root, name, sha256(yaml), sha256(annotations).
- Helper run, in order: exclusive `mkdir(dir)` (mode from the root: 2775 if setgid else 0755);
  annotations via 0600 temp + os.link; YAML LAST via 0600 temp + os.link; chmod 0664/0644 by
  the setgid rule; fsync files and directory. Browse lists only `*.clab.y(a)ml`, so the lab
  becomes visible only when the final link lands, with its annotations already in place.
- Failure between writes: remove what this run created (files it linked, then the dir if
  empty); if cleanup itself fails, the leftover has no `.clab.yml`, is invisible to browse, and
  a retry with identical content resumes it; with different content it is refused with the
  path named.
- Existing destination with other content: refused, nothing touched. Never overwrites.
- Concurrency: helper flock + manager `operation_busy`; preview token single-use, 5 min, bound
  to host revision and draft revision; a draft edit after preview invalidates the token; a
  changed request fails the digest.
- Lost response: the manager retries `run` with the same request; the helper finds `dir` with
  both files matching the request hashes and answers success with `already_published: true`.
- Discovery: inspects deployed labs only; an undeployed folder is not imported. After publish
  the UI continues with the existing registration chain, as "Deploy lab" does today.
- Update-in-place of a published topology is NOT part of this contract (separate decision).

### 3. Known risks

Browser behaviour under the CSP, bundle size with `Cache-Control: no-store`, upstream 0.x
churn, Material look, Playwright-only testability, the framework/build-step rule change.
A prototype is being built in parallel to measure the first two.
