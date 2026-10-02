# Independent architecture and security review (Fable, read-only)

I wrote no file, because this session's read-only rule overrides the single-file allowance; the full review is below. Nothing was executed, so every finding comes from reading code.

**Verdict:** the proposal stands only with changes, and the editor and the publish contract should be decided separately.

References marked 0.3.2 point into `inputs/npm-0.3.2/package/dist/chunks/`. W is `chunk-WM5ZW3ZW.js`, Y is `chunk-YWKQISCS.js`, M is `MonacoCodeEditor-7TVK3SAJ.js`. These chunks are not minified, so I did not need HEAD source for challenge A. HEAD references are under `containerlab-app/packages/clab-ui/src`.

## A. Editor assumptions (0.3.2)

**A1. The adapter's in-memory file map is briefly missing the target file during every write. Must be designed around.**
- Evidence (0.3.2):
  - The commit order is write tmp, rename original to `.bak`, rename tmp to original, unlink `.bak` (Y:3636-3648).
  - The core wraps whatever base adapter it is given (Y:3739).
  - Snapshot-time migrations write outside any transaction (Y:4162-4175).
  - Annotations are deleted when empty (Y:2062).
- Why: a debounce timer that fires mid-sequence would PUT a draft with no YAML in it.
- Change: flush only after `applyCommand` or `getSnapshot` resolves, serialise the PUTs, and send a missing annotations file as an explicit null. Ignore dot-prefixed tmp and bak names. Throw errors that carry `code: 'ENOENT'` (Y:2029, Y:4406).

**A2. 0.3.2 has no on-disk drift detection at all. Must be designed around.**
- Evidence (0.3.2):
  - `applyCommand` compares only the in-memory `baseRevision` (Y:3770-3785).
  - The revision restarts at 1 on every page load (Y:3715).
  - `documentKey` and `invalidateCache` do not appear in dist.
- Why: two tabs or two students on one draft silently overwrite each other.
- Change: the draft PUT carries an If-Match on the manager's draft revision. On a 409, reload the page rather than calling `onExternalChange`, which wipes undo (Y:3841-3843).

**A3. A page close after the core's ack but before our flush loses the edit silently. Must be designed around.**
- Evidence:
  - The ack is returned once the adapter resolves (Y:3800-3838).
  - The research found no `beforeunload` handler in clab-ui (up-editor-core.md:47).
  - The manager rejects bodies over 2.5 MB and requires a content length (main.py:98-102).
  - The 64 KiB limit on keepalive and beacon bodies is general browser knowledge, not something I tested.
- Why: a draft of up to 1 MiB cannot be flushed at unload, and the UI already showed it as saved.
- Change: have `writeFile` persist synchronously to `localStorage` before it resolves, as a journal, and add our own `beforeunload` guard while unflushed (see G).

**A4. `disabledTabIds` only filters tabs; Monaco still loads 750 ms after mount. Must be designed around.**
- Evidence (0.3.2):
  - The only reader of `disabledTabIds` is the tab filter (W:14861-14882).
  - An unconditional effect preloads Monaco (W:14902-14921, W:14603).
  - Monaco and ajv are imported only by the source tabs (W:14608-14628, M:29).
  - `new Ajv` runs at module scope (M:222), but `compile` runs only when the validator is first used (M:225-229).
  - Monaco also injects a `<style>` element (M:100-111).
- Why: hiding the tabs avoids `unsafe-eval` but not the 3.8 MB fetch and parse.
- Change: replace the Monaco chunk with a stub at bundle time when the YAML and JSON tabs are off. Treat "editable YAML" as a separate deliverable.

**A5. `renderDeployMenuItems` only appends menu items; the built-in deploy controls stay. Blocks the proposal as written.**
- Evidence (0.3.2):
  - The extra items are added to the existing menu (W:13731-13734).
  - The Play button and the Apply and Deploy (cleanup) items are hard-coded and enabled while the lab is undeployed (W:13851-13915, W:13698).
  - A click sets processing to true, and only a host `lifecycleStatus` event clears it (W:13735-13744, W:7670-7685).
  - `App` accepts only `initialData`, `runtime` and `chrome` (App.d.ts:13-17); `chrome: 'viewer'` removes the palette as well.
  - I found no keyboard shortcut for deploy.
- Why: with a do-nothing host, one click freezes the editor. There is no supported way to remove these controls.
- Change: the host's `runLifecycle` must open the manager's Publish flow and always emit `lifecycleStatus`. Deploy (cleanup) cannot be honoured, so either hide it by its `data-testid` and record that as unsupported, or wait for 0.4.0's `lifecycleActionsAvailable`.

**A6. Custom node templates: checked, the supported path is `initialData.customNodes`.**
- Evidence (0.3.2): `hooks/app/useInitialGraphData.d.ts:12`, `chunk-BBTDNLBI.js:450-459`, W:7425-7433.
- Note: the palette's edit, delete and set-default buttons call host methods (W:6447-6450, W:15300-15305). Implement those in memory, or the buttons fail.

**A7. Navbar features that would predictably fail with a minimal host:**

| Feature | What happens | Supported way to remove it in 0.3.2 |
|---|---|---|
| Geo layout (W:14142) | Needs OSM tiles (W:2901) and a blob worker (W:2946-3002); the manager's CSP sets `connect-src 'self'`, `img-src 'self' data:` and no `worker-src` | None. Stubbing `maplibre-gl` still leaves the menu item |
| Split view (W:14079, W:22169-22174) | Opens the YAML tab. With that tab disabled the click does nothing (W:14886-14889) | None |
| SVG capture | Runs in the browser through a blob | Not needed |
| Grafana export | Calls the host (`SvgExportModal-PQULR2XO.js:3480`) | None |
| Packet capture, SSH, link impairments | Offered only when the lab is deployed (W:8711-8753); I read the gate but did not run it | Not needed if the host fixes the state to undeployed |
| Icon upload (W:15797-15805) | Calls the host | The host must implement it |
| Image manager | `host.images` is optional in the contract (up-public-api-license.md:35, as reported); I did not check the UI's behaviour in dist | Not traced |

Three controls cannot work and have no supported off switch. That conflicts with the maintainer's condition on controls that predictably fail.

## B. The publication contract

**B1. The trust boundary first.** The engineer account is root-equivalent by design, through the docker and `clab_admins` groups (`setup-engineer-access.sh:43-46`). Races inside the setgid root are therefore a correctness risk, not privilege escalation.

**B2. `mkdir` with mode 2775 loses group write. Must be designed around.**
- Evidence: the helper runs under `sudo env -i` (`setup-operations.sh:50`). sudo's default umask would strip group write; I did not confirm the umask on the VM.
- Change: open the new directory with `O_NOFOLLOW` and `fchmod` that descriptor. Inherit the setgid bit from the root.

**B3. Path-based `chmod` after `link` is racy (`host_operations.py:283-289`). Must be designed around.**
- Change: write, fsync, then `fchmod` the temp file's descriptor, and only then link. Do every step relative to a directory descriptor, following `host_files.py:61-86`.

**B4. The "only a subset of {ann, yaml}" rule strands names. Must be designed around.**
- A helper crash mid-run leaves `.clab-manager-<hex>` in the folder (`host_operations.py:277`).
- A delete leaves `.clab-manager-history/` and the annotations file (`host_operations.py:269-275`).
- A deploy leaves a `clab-<name>/` directory (`host_operations.py:252`).
- Each of these makes a later publish under the same name fail permanently.
- Change: tolerate and remove our own root-owned, single-link 0600 temp files. Report every other leftover as a named refusal with guidance. Decide separately whether `delete` should also remove the companion annotations file.

**B5. Resume accepts states our write order cannot produce. Must be designed around.**
- Evidence: the proposal writes the annotations file first and the YAML last (proposal.md:70-73).
- Why: a folder holding only the YAML, when annotations were requested, was made by something else. Resuming it would add the annotations after the lab is already visible.
- Change: resume only from an empty folder, from annotations alone, or from both files. Hash through `O_NOFOLLOW` reads of regular files, and require root ownership with a single link. Otherwise refuse as "existing destination".

**B6. There is no fsync anywhere today (`host_operations.py:277-291`, `store.py:34-39`), and the proposal's order puts it last. Must be designed around.**
- Why: after a power loss the annotations file can exist with zero length. Its hash then mismatches and the retry is refused for good (see B4).
- Change: fsync each temp file before linking it, fsync the new directory after each link, and fsync the root after `mkdir`.

**B7. Rollback by path can delete a file that someone else swapped in. Worth noting.**
- Change: keep the temp link until the end and unlink the final path only if its inode matches. Never remove a directory that this run did not create.

**B8. The size arithmetic is wrong. Must be designed around.**
- Evidence: the helper's `LIMIT` is 1 MiB and the request line limit is `2*LIMIT` (`host_operations.py:24`, `:310-311`). The manager sends `json.dumps` with the default ASCII escaping (`lab_operations.py:72`).
- Why: non-ASCII note text expands up to three times and control characters six times, so two 512 KiB texts can exceed the line limit. The failure appears at preview, which is safe but opaque.
- Change: cap the encoded request in the manager, for example at 1.5 MiB, with a clear message. Or send `ensure_ascii=False`, which the helper already reads as bytes.

**B9. The "retry run" path in the contract does not exist. Must be designed around.**
- Evidence: the token is popped before the job is submitted (`lab_operations.py:253`), and a failed job says "Inspect the VM before retrying" (`lab_operations.py:383`).
- Change: make recovery a fresh preview. The plan reports `state: new`, `resume` or `already_published`, and the confirm of an already-published plan does nothing.

**B10. The digest binds too little. Must be designed around.**
- Evidence: `host_operations.py:258-260` builds the digest from a small base record.
- Change: also bind the derived paths, whether annotations are present at all (none versus an empty string), and the chosen directory mode. Exclude the plan state, so a lost-response confirm still matches.

**B11. Discovery: checked, nothing found.** `host_files.py:106-150` reads only deployed labs.

**B12. A publish can re-point an existing lab. Must be designed around.**
- Evidence: `opSaveWorkspace` matches on `deployment_name===parsed.name` and then PUTs the new path onto that lab (`operations.js:231-233`).
- Why: a published lab whose name equals a registered lab's name moves that lab to the new folder.
- Change: the publish preview refuses, or clearly warns, when the name is already registered under another path.

**B13. An old helper on the VM lacks `publish`. Must be designed around.**
- Evidence: `host_operations.py:139-149` (capabilities), `:189` (action list).
- Why: without a gate, this is a clickable control that predictably fails.
- Change: advertise the action in `capabilities` and disable the control with a reason when it is absent.

## C. Drafts in the Store

**C1. Every autosave rewrites and re-encrypts the whole state under one lock. Must be designed around.**
- Evidence: `store.py:40-42`. The document already holds up to 200 operation records of up to 512 KiB each (`lab_operations.py:249`, `:371`). Running jobs also save every 0.25 s (`lab_operations.py:372-375`), and `atomic()` has no fsync.

**C2. Every non-GET API call writes an audit line. Must be designed around.**
- Evidence: `main.py:106-116`. The audit log is capped at four files of 5 MiB (`store.py:113-117`).
- Why: a classroom's autosaves would rotate real audit events out.
- Change: keep drafts in the browser and have the server see only the publish (see G). If drafts stay on the server, exempt that route from the audit log and keep them in a separate file.

**C3. "Start fresh" silently deletes drafts. Must be designed around.**
- Evidence: reset rebuilds the state from a fixed list of keys (`store.py:96-97`).
- Change: state this on the reset screen. Older state files also have no `drafts` key (`store.py:26`).

**C4. `/api/state` leakage: checked, unfounded.**
- Evidence: the top level is a whitelist (`main.py:182-187`). Job records hold no YAML (`lab_operations.py:246-247`), and preview text lives only in memory.
- I did not trace the diagnostics bundle (`diagnostics.py:81`).

## D. Rules the proposal understates

**D1. The design addendum binds the entry point. Must be designed around.**
- Evidence (`DESIGN-SPEC-ADDENDUM.md`):
  - Home's second row carries only "Deploy a new lab".
  - All three deploy buttons call `openDeploy()` (:75).
  - Shared controls use the proxy pattern (:9).
  - Text glyphs are banned, and dark surfaces are allowed only for the toast and the terminal (:143).
  - New pages join the release file table (:58).
- Change: put the entry inside the Deploy dialog beside `#op-create`. List the Material look, theme and Roboto as explicit exceptions.

**D2. Release and CI mechanics. Must be designed around.**
- Evidence:
  - `verify-release.py:38` names eight pages, so `lab-builder.html` must be added.
  - CI runs an explicit test list (`release-check.yml:17-71`), so new tests need their own lines.
  - `.gitignore:4` ignores every `dist/` folder.
  - `.dockerignore` drops `*.md`, `*.tgz`, `*.tar` and `*.zip`.
- Change: name notices `*.LICENSE` or `.txt` and do not call the bundle folder `dist`. CI cannot rebuild or verify the bundle, so specify a reproducibility check.

**D3. The CSP blocks more than inline styles. Worth noting.**
- Evidence: `worker-src` and `font-src` are unset and fall back to `'self'`, and `img-src` is `'self' data:` (`main.py:122-123`).
- Why: blob workers and data-URI fonts are blocked.
- Change: bundle fonts as files, and add a third CSP test for the new page.

**D4. Tests pinning the `write` refusal: checked, they survive a new action name.** Evidence: `test_lab_operations.py:120`, `:140`, `:264`. Add a test that `publish` never replaces content.

## E. Non-regression

**E1. Validating annotations with `parse_drawing` at preview would refuse files clab-ui writes on purpose. Must be designed around.**
- Evidence:
  - The manager concatenates both arrays and requires unique ids (`topology.py:90-92`).
  - HEAD keeps the same id in both arrays deliberately (`core/io/TopologyIO.ts:192-199`).
  - 0.3.2 drops the network node's `nodeAnnotations` entry instead (Y:3038-3065); whether the manager still rejects the result was not run.
  - The registration chain falls back to the grid without telling the user (`operations.js:221-224`).
- Change: make this a named warning at preview, not a refusal and not silent.

**E2. `#op-create`, Sync, the stale-map rule and the telemetry map: checked, nothing found.**
- Registration and Sync replace the map only when annotations accompany the YAML, so a first registration behaves correctly (`discovery.py:631`, `vm_files.py:128-129`, as reported in mgr-topology-backend.md:25-27; I did not open those lines).
- `telemetry_map.py:194-197` and `:237` tolerate unknown nodes.
- Single-endpoint links are counted as skipped (`topology.py:121-123`).
- `fixture_manager.py:270-288` drives the real app, but it has no helper fake for a publish.

## F. Topology fidelity (HEAD serializer)

1. On edit, node keys equal to the value inherited from defaults, kinds or groups are deleted (`NodePersistenceIO.ts:298-302`). The manager never reads `topology.groups` (mgr-topology-backend.md:39). A kind inherited from a group therefore reaches the manager as an empty kind, shown as "Choose NOS" with no default login (mgr-topology-backend.md:41, :127). This is reachable only through the YAML tab or a seeded starter file, so seed no defaults.
2. Link and scalar comments are lost when a link is edited, per the research probe. Links become extended form only when they carry extended properties (`LinkPersistenceIO.ts:76`, `:378-400`), and the manager parses that form (`topology.py:120-127`).
3. Annotations that fail to parse load as empty, and the next save overwrites them (Y:2022-2034). Unknown top-level keys survive (Y:1949-1953). The file is deleted when empty.
4. Lab settings can rename `name:` (Y:4041-4043), and node names are free text. Either breaks the proposal's "name equals folder" rule or the manager's name rule at publish. Validate at draft save and pin the name.
5. Unknown node keys: checked, preserved (`NodePersistenceIO.ts:281-289`). Anchors, aliases and `${ENV}` placeholders were not tested. The manager refuses anchors explicitly, so that case is not silent.

## G. Simpler alternatives

- **Relying on the VS Code extension:** no. It requires a root-equivalent account for a single owner.
- **A vanilla builder on the existing diagram editor:** complies with every project rule, but the backend edits only positions and decorations (`layout.py:1`). It is a large build and does not clearly beat the proposal.
- **Drafts held only in the browser:** yes, this beats Store drafts. It removes all of C, closes A3 because the ack then means the draft is durable, and keeps the three states separate.
  - Costs: drafts are tied to one browser, so add draft download and upload. The research says `shell.js` owns `localStorage` on the main pages (mgr-frontend.md:15); this is a separate page.

## Corrected publication contract

Only the differences from proposal section 2 are listed.

- **Request:** cap the encoded request at 1.5 MiB or under. Bind into the digest whether annotations are present, the derived paths and the directory mode.
- **Preview refuses when:**
  - the helper does not advertise `publish`;
  - the name is already registered under another path;
  - the folder holds anything beyond the resumable states. Our own crashed temp files, root-owned with a single link, are removed during the run.
- **Preview warns when:** the manager cannot parse the annotations.
- **Run order:**
  1. `mkdir`, then open the folder with `O_NOFOLLOW`.
  2. `fchmod` the folder, then fsync the root.
  3. For each file in the folder: temp `O_EXCL`, write, fsync, `fchmod`, `linkat`.
  4. fsync the folder.
  5. Link the YAML last.
  6. Unlink the temp files, then fsync the folder.
- **Rollback:** unlink a final path only when its inode matches, and `rmdir` only when this run made the folder.
- **Recovery:** there is no run retry. A fresh preview returns `already_published` and its confirm does nothing.
- **Drafts:** held in the browser, and the preview binds their sha256 values.

## Biggest remaining uncertainty

Can the 0.3.2 `<App>` be made free of dead controls without patching dist? The controls in question are Deploy (cleanup), Geo, Split view and the Grafana export. Patching would trigger Apache-2.0 §4(b) and add upkeep on every upstream bump. The alternatives are hiding by `data-testid`, which is unsupported, or waiting for 0.4.0. The prototype should answer this before the backend work starts.

### Critical Files for Implementation
- /home/clabllm/projects/clab-manager/clab-backup-ui/app/host_operations.py
- /home/clabllm/projects/clab-manager/clab-backup-ui/app/lab_operations.py
- /home/clabllm/projects/clab-manager/clab-backup-ui/app/main.py
- /home/clabllm/projects/clab-manager/clab-backup-ui/app/static/operations.js
- /home/clabllm/research/lab-builder/inputs/npm-0.3.2/package/dist/chunks/chunk-WM5ZW3ZW.js
