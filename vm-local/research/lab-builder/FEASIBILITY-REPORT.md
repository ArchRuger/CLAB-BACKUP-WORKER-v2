# Visual lab builder — feasibility report (review + isolated prototype)

Scope: one independent review and a throwaway prototype, as approved. No production code, helper,
policy, release marker or service was changed. `~/projects/clab-manager` is clean at 398d726.
Tested in headless Chromium on loopback only; not against the real manager; no lab was deployed.

## 1. Independent review (Fable, read-only, verified model and scope) — `evidence/architecture-review.md`

Verdict: the proposal stands only with changes; decide the editor and the publish contract separately.

| # | Finding | Status after the prototype |
|---|---|---|
| A1 | A debounced flush can fire in the middle of the engine's tmp/.bak/rename sequence and store a draft with no YAML | Accepted. My prototype adapter has exactly this flaw. Flush only after `applyCommand`/`getSnapshot` resolves, serialise PUTs |
| A2 | 0.3.2 has no on-disk drift detection; two tabs overwrite each other | Accepted: drafts carry a revision, 409 -> reload |
| A3 | Page close after the editor's ack but before our flush loses an edit silently | Accepted: journal to localStorage before resolving, own `beforeunload` guard |
| A4 | `disabledTabIds` only hides tabs; Monaco still loads | **Confirmed by measurement**: 7.15 MB per load with tabs on or off |
| A5 | Deploy controls cannot be removed; one click froze the editor | **Confirmed** (dialog stuck "In Progress"), **resolved** in clean mode |
| A7 | Geo, Split view, Grafana export have no supported off switch | **Confirmed**; hidden from our stylesheet, which is unsupported |
| B2-B10 | Publish contract: fd-relative operations, fsync before link, `fchmod` on the descriptor, resume only from states our write order can produce, no "run retry" path exists, digest binds too little, request-size arithmetic wrong | All accepted into section 6 |
| B12 | A published lab whose `name:` equals a registered lab re-points that lab (`operations.js:231-233`) | Accepted: preview refuses |
| C1-C3 | Drafts in the single encrypted Store: whole-state re-encrypt per autosave, audit-log rotation, Start fresh deletes them | Accepted: drafts live in the browser |
| E1 | Refusing unparsable annotations at preview would refuse files clab-ui writes on purpose | Accepted: named warning, not refusal |
| G | Browser-held drafts beat Store drafts; vanilla builder does not clearly beat the embed; VS Code is not an answer for students | Agreed |

## 2. Demonstrated working (published 0.3.2, proposed policy, real mouse/keyboard input)

- Builds with esbuild on first attempt; mounts with seeded device templates (`initialData.customNodes`).
- Node creation by palette drag and Shift+click; node deletion by menu and Delete key; property
  editing (name, image version, management address) with Apply; rename propagates to links and annotations.
- Link creation from the node menu with automatic interface allocation following per-template
  patterns (`ptx1:et-0/0/0`, `et-0/0/1`); link edit (interface selection); link deletion.
- Undo / redo; bulk-link dialog; SVG export downloads a file; template set-default answered in memory.
- YAML + `<file>.annotations.json` export through a 2-document adapter; reload restores nodes, links, positions.
- Zero console errors, zero page errors, zero policy violations, zero external requests
  (`evidence/csp-first-load.json`, `clean-sweep.json`, `undo-templates.json`).
- Every file the editor wrote passes the manager's `parse_definition` and `parse_drawing`.

Not exercised: annotations tools (text, shapes, groups), network-node palette items, template
add/edit dialogs, keyboard shortcuts other than Delete, Firefox/Safari, large labs.

## 3. Unsupported or broken in 0.3.2

| Control | Behaviour | Supported switch | Prototype handling | Maintenance consequence |
|---|---|---|---|---|
| Geo layout | blob: worker refused, 4 errors, OpenStreetMap tiles refused | none (none at HEAD either) | hidden via `data-testid` in our CSS | breaks silently if upstream renames the id; needs a test |
| Split view | opens the YAML tab; dead when tabs are off | none | hidden | same |
| Deploy / Apply button and 9 menu items | call the host; with a passive host the editor freezes | none in 0.3.2 (`lifecycleActionsAvailable` is HEAD-only; `renderDeployMenuItems` only appends) | host answers `lifecycleStatus`; 8 items hidden, "Apply" remains and cannot be relabelled | same; label says "Apply", not "Save to VM" |
| Grafana export in the capture dialog | calls the host | none | hidden | same |
| YAML/JSON tabs under `script-src 'self'` | editor works, validation throws an uncaught error every cycle, no markers | `disabledTabIds` removes the tabs | see section 4 | — |
| Monaco download | 3.6 MB fetched 750 ms after mount regardless | none | not addressed (stubbing the chunk at bundle time is untested) | — |

## 4. Content-security policy (measured)

| Policy for the builder page | Result |
|---|---|
| Manager's policy today (`style-src 'self'`) | inline styles refused; unusable |
| **Proposed: `style-src 'self' 'unsafe-inline'`, everything else unchanged** | clean, once embedded fonts are moved to files at build time (2 fonts, done in `build.mjs`) |
| + YAML tab enabled | 1 `script-src` eval violation + uncaught page errors per validation; **fails the project's browser gate** |
| + `script-src 'unsafe-eval'` | works, 18 markers — not recommended, not needed |
| Proposed policy + **build-time precompiled validator** substituted for `ajv` at bundle time | **works: 18 markers, 0 errors, no eval** |

The precompiled validator is not a supported upstream hook. It relies on the editor calling
`new Ajv(opts).compile(schema)` (identical at HEAD and in 0.3.2) and must be guarded by a test.
No `worker-src`, `font-src`, `connect-src` or `script-src` change is needed.

## 5. Measurements

- Full build: 177 files, 13.1 MB, 4.5 MB gzip-equivalent. 86 packages.
- **One page load: 51 files, 7.15 MB, 2.0 MB gzip-equivalent.** The manager sends no compression
  and `Cache-Control: no-store`, so today that is 7.15 MB on every open.
- Canvas ready in 0.34 s on loopback. `node_modules` 465 MB (build time only).
- The manager's whole `static/` directory is 0.8 MB.

## 6. Topology compatibility

- Opening the fixture writes nothing (byte-identical). Custom image strings (registry:port, digest),
  ports, startup-delay, startup-config, binds, exec, labels, `mgmt:`, `defaults`, `kinds`, `groups`,
  extended links (mac, mtu, vars), `host:` / `mgmt-net:` endpoints, unknown node keys and unknown
  annotation keys (node-level and top-level) all survive every edit tested.
- Losses, none of them semantic: the comment on an edited brief link; the comment on a key the
  editor removes; a renamed node moves to the end of the mapping.
- Rewrites: editing a node removes `kind:` when it equals `defaults.kind`; editing a
  group-inherited node writes the group's `kind` and `image` onto the node.
- Manager restrictions and handling: anchors/aliases, template syntax and non-identifier names are
  refused by `parse_definition` with a message (never silent); the builder never emits them, and the
  publish preview runs the same check. Lab settings can rename `name:`, so the name is pinned at publish.
- **Existing manager defect found:** `parse_definition` ignores `topology.groups`, so a node whose
  kind comes from a group is identified from `defaults` instead (fixture: a vJunos spine treated as
  cEOS -> wrong driver). Independent of the builder; the builder never emits groups.
- Kind unsupported by the manager's NOS drivers: `platform` empty, node shows "Choose NOS", deploys
  normally, no login default/backup/readiness. Kind unsupported by the installed containerlab: only
  containerlab can tell, at deploy time; the editor's kind list comes from its bundled schema
  (65 kinds, tracked from containerlab main) and can be newer than the VM's containerlab. The manager
  has no source for the runtime's kinds or version today.

## 7. Proposed publication contract (design only)

State: draft = browser (localStorage journal + download/upload), identified by sha256 of both texts;
published = files on the VM; running = the existing lab record from the existing registration chain.

- Request: `root` (exactly a configured trusted root), `name` (`identity()`), `yaml`, optional
  `annotations`; the manager caps the *encoded* request (<= 1.5 MiB) with a clear message. The helper
  derives `dir`, `<name>.clab.yml`, `<yaml>.annotations.json`. Advertised through `capabilities()`;
  the control is disabled with a reason when the installed helper lacks it.
- Preview refuses: action not advertised; `name:` differs from `name`; `parse_definition` fails; the
  name is already registered under another path; the destination holds anything other than a
  resumable state. Preview warns (named, not silent) when the manager cannot parse the annotations.
- Digest binds: action, root, name, derived paths, sha256(yaml), annotations present/absent and its
  sha256, directory mode. Plan state is excluded so a lost-response confirm still matches.
- Run: exclusive `mkdir`; open it `O_NOFOLLOW`; `fchmod` (setgid inherited from the root); fsync the
  root; for each file: `O_EXCL` temp at 0600, write, fsync, `fchmod` 0664/0644, `linkat` relative to
  the directory descriptor; annotations first, **YAML last** (browse lists only `*.clab.y(a)ml`, so the
  lab appears complete or not at all); fsync the directory; unlink temps; fsync.
- Failure between writes: unlink a final path only if its inode is ours; `rmdir` only a folder this
  run created. A leftover has no `.clab.yml` and is invisible to browse.
- Resumable states: empty folder, annotations only, or both files, each root-owned, single-link,
  hash-equal to the request. A folder holding only the YAML was not made by us: refused.
- Existing destination with other content: refused, nothing touched. Never overwrites.
- Concurrency: helper flock + `operation_busy`; token single-use, 5 min, bound to host revision and
  the draft hashes; an edited draft invalidates it.
- Lost response / retry: there is no run retry in the manager. Recovery is a fresh preview, whose
  plan reports `new`, `resume` or `already_published`; confirming `already_published` does nothing.
- Discovery during publication: not affected; it reads deployed labs only.
- The single-file `create` guarantees do not carry over by themselves: multi-file atomicity comes
  from the YAML-last ordering plus the resume rule, not from `os.link` alone.

## 8. Minimum exceptions the embed needs

1. One more document path in `main.py`'s inline-style tuple, with a test. Nothing else in the policy.
2. The "no framework, no bundler" rule relaxed for one page; a build-time Node toolchain in the repo.
   No runtime dependency: the image only copies static files.
3. Controls hidden by `data-testid` (unsupported) — or wait for upstream switches.
4. Optional: the `ajv` substitution (unsupported) if editable YAML is wanted.
5. One new action in the existing operations helper (no new gateway name, no new sudoers line).
6. Recommended: compression or a caching exception for the builder's hashed assets.

## 9. Licensing and packaging (exact artifacts, `evidence/bundled-licenses.tsv`)

86 packages in the bundle: 54 MIT, 20 ISC, 6 BSD-3-Clause, 1 BSD-2-Clause, 1 MIT AND ISC,
**1 Apache-2.0 (`@containerlab/clab-ui` itself)**, 1 EPL-2.0 (elkjs 0.11.1), 1 OFL-1.1 (Roboto),
1 MPL-2.0 OR Apache-2.0 (dompurify; take Apache-2.0). No package ships a NOTICE file;
`@mui/x-charts-vendor` ships no licence file. Obligations: ship the Apache-2.0 text, generate a
third-party notices file from the metafile, ship the EPL-2.0 text with a source pointer and keep elkjs
unmodified. Nothing is modified, so Apache-2.0 §4(b) is not triggered — including by CSS hiding and
by the `ajv` substitution (a dependency is replaced, no upstream file is edited). Not legal advice.

| Packaging | Build-time tooling | Runtime | Installer effect |
|---|---|---|---|
| Committed prebuilt assets | Node on the maintainer's machine / CI only | static files | none; `COPY app/` ships them. ~4.5 MB compressed added to Git per upgrade; CI should rebuild from the lockfile and compare hashes; do not name the folder `dist/` (ignored), notices must not be `.md` (dropped from the image) |
| Built in CI, packaged in the image | Node in CI | static files | **requires a published image; the project publishes none and every VM builds from source** — a distribution-model change |
| Local multi-stage image build | Node image + `npm ci` (195 packages) on every VM, every install/upgrade, `--no-cache` | static files | needs the npm registry from every VM; first failure would be on a user's VM because CI never builds the image |

## 10. Revised recommendation

The embed is feasible on the published package with one policy exception, and the publish design
survives review with the corrections above. Recommended shape: clab-ui 0.3.2 pinned exactly on its
own page in clean mode; drafts in the browser; the corrected publish contract; committed prebuilt
assets with a CI reproducibility check; YAML tabs **off** in the first version with a plain read-only
YAML review in the manager's own publish dialog. Remaining uncertainty: upstream is days old and
three controls are hidden by an unsupported mechanism; both are contained by the exact pin and tests.
