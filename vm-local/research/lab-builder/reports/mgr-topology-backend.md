# mgr-topology-backend (condensed reader result recovered from the workflow journal)

Full report: /tmp/claude-1000/-home-clabllm-projects-clab-manager/2b0e597f-39bf-4403-8d37-3e4a96f0a0a9/scratchpad/reports/mgr-topology-backend.md

I read the listed backend files in full, plus `host_files.py` and `host_operations.py`. Two read-only probes are in `scratchpad/work/` (`probe_annotations.py`, `probe_register.py`). They ran in-process on a scratch data directory. No server, VM or live lab was touched, and both repositories are unchanged.

Path legend: A = clab-backup-ui/app, S = app/static, T = clab-backup-ui/tests, U = containerlab-app/packages/clab-ui.

**1. How a lab becomes known to the manager**

- **Register from YAML.** `POST /api/lab-definitions` (A/discovery.py:592-634) takes a multipart `definition`, optional `annotations`, `lab_id` and `deployed_name`.
  - It runs `parse_definition` and `parse_drawing`. Any parser error returns 400 (:602-603).
  - It persists `nodes`, `deployment_name`, `container_prefix`, the verbatim `definition_yaml`, `source` (the file name only) and `drawing`.
  - Existing nodes keep their identity, logins and profile (:621-627).
- **Discovery import.** The inspect helper returns four files per deployed lab: the YAML, `<yaml>.annotations.json` (A/host_files.py:143), `ansible-inventory.yml` and `topology-data.json`.
  - The background poll only advertises `pending_imports` (A/discovery.py:370-371).
  - `POST /api/discovery/import-preview` returns a 5-minute token (:479-497).
  - `POST /api/discovery/import` saves the result of `prepare_lab` (:502-526, A/vm_files.py:54-136).
- **Sync topology from VM.** `POST /api/labs/{id}/sync` (A/discovery.py:546-565) is atomic. It keeps saved logins and endpoints.
- **Other routes.**
  - `POST /api/inventory` creates a legacy unlinked lab with no YAML and no map.
  - `POST /api/labs/{id}/topology` uploads a map onto an existing lab.
  - `PUT /api/labs/{id}/deployment` links a legacy workspace to a deployment.
- **What stays private.** `/api/state` never exposes `drawing` or `definition_yaml` (A/main.py:134). Raw VM file bundles are held in memory only.
- **Stale-map rule.** Both register and Sync replace the drawing only when an annotations file is supplied or no drawing exists yet (A/discovery.py:631, A/vm_files.py:128-129).
  - Probe: re-registering with one more node and link, without annotations, gave 4 lab nodes but the map kept 3 nodes and 1 link.
  - An explicit Sync that does find a VM annotations file replaces the hand-made manager layout. The `placed` flag only guards the automatic poll (A/discovery.py:376-384).

**2. `POST /api/operations/parse-yaml` and validation**

- The route is A/lab_operations.py:176-195. It runs entirely in the manager, makes no helper call and persists nothing. It returns `{name, drawing, annotations_used}`. A bad annotations file falls back silently to the grid.
- I found no containerlab schema validation anywhere. There is no `jsonschema` dependency and no schema file in `app/`, `requirements.txt`, `deploy/` or `docs/`.
- `parse_definition` (A/discovery.py:43-77) checks only:
  - size ≤ 1 MiB, and no YAML anchors or aliases (A/inventory.py:68-69);
  - `name` and node names match `[A-Za-z0-9_][A-Za-z0-9_.-]*`, with no `{{`;
  - `nodes` is non-empty and has at most 2000 entries;
  - `kind` is any string up to 120 characters;
  - `mgmt-ipv4` or `mgmt-ipv6` is a valid address.
- It does not read `topology.groups`, and it does not validate links. Probe: a link to an undefined node `ghost` returned 200 and created a drawing node.
- Supported platforms are the three Junos kinds, `cisco_xrv9k` and `arista_ceos`, plus their aliases (A/inventory.py:17-39). `DEFAULT_CREDENTIALS` covers the same five.
- An unknown kind gets `platform=''` and `enabled=False`, shows "Choose NOS" and has no default login (A/discovery.py:71-74, A/runner.py:47-49). Such nodes still deploy, because the helper runs `containerlab deploy -t <path>` without looking at kinds (A/host_operations.py:235-237).
- A YAML that `parse_definition` rejects cannot be created or deployed through the manager at all (A/lab_operations.py:211-220).

**3. Drawing model and annotations format**

- **Stored drawing.** It is schema 3 (A/topology.py:185-189): `nodes`, `links`, `decorations`, `placed`, `skipped_links` and `settings`.
  - Links are `[{node, interface, label_offset?}]` pairs. Wiring comes only from the topology file.
  - Decorations are `text`, `group`, `rectangle`, `circle` or `line`.
  - Coordinates are the top-left of a 40 px icon. clab-ui uses the same convention: it sets no `nodeOrigin`, and `ICON_SIZE` is 40.
- **Format parsed.** Yes, it is the TopoViewer file. The parser detects any of `nodeAnnotations`, `networkNodeAnnotations`, `freeTextAnnotations`, `groupStyleAnnotations` or `freeShapeAnnotations` (A/topology.py:87). NODE-FEATURES.md:141 cites the vscode-containerlab types as the reference.
- **Keys read per node.** `id`, `position`, `yamlNodeId`, `copyFrom`, `label`, `icon`, `iconColor`, `labelPosition`, `labelBackgroundColor`, `iconCornerRadius`, `interfacePattern` and `direction` (:90-103). It also reads `edgeAnnotations`, shape, text and group styles, and four `viewerSettings` keys.
- **Keys ignored.** `trafficRateAnnotations`, `aliasEndpointAnnotations`, `groupId`, `parentId`, `level`, geo fields, line arrows and `yamlInterface`.
- **Compatibility with clab-ui.** clab-ui writes the same nine top-level keys (U/src/core/types/topology.ts:246-271) to `basename + ".annotations.json"` (U/src/core/io/AnnotationsIO.ts:56-61).
  - Probe: 11 of the 12 sample YAML + annotations pairs in containerlab-app parse unchanged.
  - `network.clab.yml` fails with "Drawing node IDs must be unique" (A/topology.py:90-92). Its id `bridge0` appears in both `nodeAnnotations` and `networkNodeAnnotations`. clab-ui keeps that shape on purpose (U/src/core/io/TopologyIO.ts:193-198).
  - What each entry point does with such a file:
    - `parse-yaml` falls back to the grid;
    - `/api/lab-definitions` returns 400;
    - discovery import imports with a warning on the grid;
    - Sync is refused.
  - `host:`, `mgmt-net:` and `macvlan:` endpoints become fake devices.
  - clab-ui icon names degrade to router, switch or server symbols.
- **Writing back to the VM.** The manager never writes annotations to the VM. It offers only a manager-side layout and browser downloads: `POST /api/labs/{id}/annotations` and the draw.io export (A/lab_operations.py:344-360).
  - `write` is an unsupported action (T/test_lab_operations.py:120, :262-267).
  - `create` requires a new `.yaml` or `.yml` path, so a `.json` file is refused (A/host_operations.py:211-213).

**4. Diagram editor backend**

- `PUT /api/labs/{id}/layout` accepts `positions`, `decorations` and `revision`, with extra fields forbidden (A/lab_operations.py:308-342).
- Editable:
  - node x and y only;
  - the full decorations list (A/layout.py:11-47);
  - a stale `revision` returns 409.
- Not editable:
  - node icon, label or colour;
  - links and interfaces;
  - YAML.
- A/layout.py:1 says it "never alters deployed nodes or topology wiring". Tests assert that nodes and links are unchanged and that no VM call is made (T/test_diagram_editor.py:33-38).
- The UI states: "Existing files can't be edited here" (S/operations.js:282).

**5. `scaffold-lab.py` and `lab-template`**

- `deploy/scaffold-lab.py` is a stdlib CLI. The instructor runs it on the build box against `http://127.0.0.1:8081`, after the lab is deployed and connected to a Git repository.
- `init` registers `<slug>/reference/{start,solution,broken-01}` and `<slug>/work`, then binds saves to `work`.
- `snapshot` rebinds to `reference/<state>`, saves and pushes, then rebinds to `work`.
- It creates no topology file and deploys nothing. `lab-template/bgp-core.clab.yaml` is a hand-copied example that no code references.
- Git folders hold device configurations and a manifest. The topology appears there only as `topology_digest` (A/git_progress.py:204-208, :695).
- Naming rule (docs/NAMING.md): slug = `name:` = file name = Git folder, and nodes are never renamed.

**6. Call sequence behind "New topology" → save → deploy**

Each helper call goes over SSH through the gateway to `clab-manager-operate`. `preview` and `run` take a host-wide lock.

- **Flow 1: write the file.**
  1. `POST /api/operations/browse` (helper mode `browse`) and `GET /api/operations/capabilities` (mode `capabilities`).
  2. The editor opens with a static starter text and makes no backend call. The optional preview calls `parse-yaml`.
  3. `POST /api/operations/preview` with `action: 'create'`. The manager runs `parse_definition`; the helper plans the write. The path must be inside a trusted root and must not exist, the suffix must be `.yaml` or `.yml`, and the parent folder must already exist.
  4. `POST /api/operations/confirm` with the token. The helper (mode `run`) writes the file with `os.link`, and the manager then refreshes discovery.
  - At this point no lab is registered. The helper has no mkdir.
- **Flow 2: deploy the file.**
  1. `POST /api/operations/read` with the YAML path.
  2. `POST /api/operations/read` with `path + '.annotations.json'`. Errors are ignored.
  3. `POST /api/operations/parse-yaml`.
  4. `POST /api/lab-definitions`. This is skipped when a lab already matches (S/operations.js:231-239).
  5. `PUT /api/labs/{id}/operations-settings {path}`. The helper reads the file, and its `name:` must match the lab's.
  6. `POST /api/operations/preview` with `action: 'deploy'`. The manager reads and parses the file; the helper plans the run with sha256, `containerlab inspect --all` and `containerlab deploy --help`.
  7. `POST /api/operations/confirm`. The helper (mode `run`) runs `containerlab deploy -t <path> [--name]`.
  8. The manager refreshes discovery and reconciles. It places the map from the annotations file if the map is still on the grid. Readiness then uses the default logins.

**Constraints on any builder design**

- Foreign `Origin` headers get 403.
- Every POST and PUT needs a body of at most 2.5 MB.
- CSP is `script-src 'self'; style-src 'self'; frame-ancestors 'none'`, with `X-Frame-Options: DENY` (A/main.py:93-123).
- The clab-ui `FileSystemAdapter` expects `writeFile`, `rename` and `unlink` on every edit (U/src/core/io/types.ts:42-82). The helper offers only read, create-new and delete.

## Load-bearing claims

- **[verified-in-code]** The manager parses the vscode-containerlab TopoViewer / clab-ui `.annotations.json` format, from the same file name and location clab-ui writes. Positions, icon fields, shapes, notes, groups, edge label offsets and four viewerSettings keys are read; trafficRate, aliasEndpoint, groupId/parentId/level, geo fields and line arrows are ignored.
  - Evidence: Manager: A/topology.py:87-103 (detection keys and node keys), :135-189 (edges, decorations, settings); A/host_files.py:143 (`str(definition) + '.annotations.json'`); S/operations.js:218; NODE-FEATURES.md:141 (format reference is the vscode-containerlab topology.ts). clab-ui: U/src/core/types/topology.ts:199-271; U/src/core/annotations/types.ts:13-24; U/src/core/io/AnnotationsIO.ts:56-61. Probe scratchpad/work/probe_annotations.py: 11 of 12 containerlab-app sample pairs parse (for example ai-fabric gives 38 nodes and 148 links).
- **[verified-in-code]** A clab-ui annotations file with the same id in both nodeAnnotations and networkNodeAnnotations (a bridge or network node) is rejected by the manager, and clab-ui keeps that shape deliberately. The effect differs per entry point: parse-yaml silently falls back to the grid, POST /api/lab-definitions returns 400, discovery import warns and uses the grid, and Sync is refused.
  - Evidence: A/topology.py:90-92 (the two arrays are concatenated, then the unique-id check runs); U/src/core/io/TopologyIO.ts:193-198 (positions belong to networkNodeAnnotations, metadata stays in nodeAnnotations); A/lab_operations.py:187-194; A/discovery.py:601-603; A/vm_files.py:61-64, :95-102. Probe: clab-ui fixture network.clab.yml failed with 'ValueError Drawing node IDs must be unique and nonempty'; probe_register.py step 4 returned 400 and step 5 returned 200 with annotations_used=False.
- **[verified-in-code]** The manager's only write path to the VM's lab files is 'create a new .yaml/.yml that does not exist yet, in an existing folder inside a trusted root'. There is no overwrite, no write of an annotations file, no mkdir and no rename. delete exists only while the lab is not deployed and keeps a recovery copy. Every write needs preview plus a confirm token.
  - Evidence: A/host_operations.py:25, :189 (action list), :211-213 (path must not exist, suffix yaml/yml, parent must exist), :227-228, :268-291 (os.link publish, recovery copy), :316-328 (modes are capabilities, read, browse, popular, grafana, preview, run). T/test_lab_operations.py:120 ('write' is Unsupported in the helper), :126-129 (create never overwrites), :262-267 (the API rejects 'write' with 400). agent instructions.md:734-735 (VM YAML editing removed in 1.12.0). S/operations.js:282 (UI text).
- **[verified-in-code]** The manager has no containerlab schema validation. parse_definition is a small structural check, any kind string is accepted, and unknown kinds become nodes with platform='' and enabled=False that still deploy. Links and endpoint references are not validated.
  - Evidence: A/discovery.py:43-77 (checks), :63 (kind is a literal of at most 120 chars), :71-74 (platform = ALIASES.get(kind,''), enabled = bool(platform)); A/inventory.py:17-39, :62-75; A/runner.py:47-49; A/host_operations.py:235-237 (argv is containerlab deploy -t path). grep for jsonschema / clab.schema across app, requirements.txt, deploy and docs returned no hits. Probe: linux and nokia_srlinux nodes gave platform '' and enabled False; a YAML with kind not_a_kind and a link to the undefined node 'ghost' returned 200 with drawing nodes ['r1','ghost'].
- **[verified-in-code]** A YAML that parse_definition rejects cannot be created or deployed through the manager: YAML anchors or aliases, template syntax in name or kind, lab or node names outside [A-Za-z0-9_][A-Za-z0-9_.-]*, empty nodes, more than 2000 nodes, or an invalid mgmt-ipv4. Builder output must satisfy it. topology.groups is not read, so a kind inherited from a group gives kind ''.
  - Evidence: A/lab_operations.py:211-214 (every non-create preview reads the VM file and parses it, else 400), :216-220 (create parses the new text), :282-289 (operations-settings parses too); A/inventory.py:42-48, :68-69; A/discovery.py:36-40, :47-66. Probe step 6: anchors, template, node name with a space, and empty nodes all returned 400.
- **[verified-in-code]** The stored map is replaced only when an annotations file accompanies the YAML, or when no drawing exists yet. Re-registering or syncing a changed topology without annotations leaves a stale map with the old nodes and links. Conversely, an explicit Sync that finds a VM annotations file overwrites a hand-made manager layout. The `placed` flag only guards the automatic poll.
  - Evidence: A/discovery.py:631 (`if ann or not lab.get('drawing')`); A/vm_files.py:128-129; A/discovery.py:376-384 with A/topology.py:72-81; docs/LAB-OPERATIONS.md:147-148; T/test_vm_files.py:125-134, :156-180. Probe steps 2-3: re-registering plus one node and one link without annotations gave lab nodes=4, drawing nodes=3, links=1; with annotations it gave drawing nodes=4, links=2, placed=True.
- **[verified-in-code]** The diagram editor backend can change only node x/y and the decorations list (text, rectangle, circle, line, group), with a revision conflict check. It cannot change node icon, label or colour, links, interfaces or YAML, and it makes no VM call.
  - Evidence: A/lab_operations.py:308-312 (the Layout model forbids extra fields and accepts positions, decorations, revision), :314-329, :331-342; A/layout.py:1 (docstring), :11-47; T/test_diagram_editor.py:33-38 (remote.assert_not_called, nodes and links unchanged); T/test_lab_operations.py:269-281; docs/LAB-OPERATIONS.md:126-127; NODE-FEATURES.md:111-113; agent instructions.md:695.
- **[verified-in-code]** 'New topology' through deploy is two separate flows. Creating the file (preview create, then confirm, then helper run) registers nothing. The lab appears only when Deploy lab or Add to My labs runs read, then read of the annotations file, then parse-yaml, then POST /api/lab-definitions (skipped if a lab already matches by deployment name or VM path), then PUT operations-settings, then preview deploy and confirm, which runs `containerlab deploy -t <path> [--name]`. The manager then refreshes discovery, which reconciles runtime state and places the map from the VM annotations file if the map is still on the grid.
  - Evidence: S/operations.js:263, :279, :285 (create), :143-144 (confirm, editor closed), :216-239 (opReadAnnotations, opParse, opWorkspaceForm, opSaveWorkspace), :286-300 (add and deploy handlers); A/lab_operations.py:167-171, :176-195, :197-258, :276-297, :362-399 (the refresh is at :395); A/host_operations.py:187-299; A/discovery.py:174-187, :373-384; deploy/clab-manager-gateway:4-8.
- **[verified-in-code]** The manager API and pages are same-origin only. A browser request with a foreign Origin or sec-fetch-site: cross-site gets 403. CSP is script-src 'self' and style-src 'self', with inline styles allowed only on the two xterm pages, plus connect-src 'self', frame-ancestors 'none' and X-Frame-Options DENY. Every POST and PUT needs a body of at most 2.5 MB. Server-side callers that send no Origin header pass, which is how scaffold-lab.py works. There is no UI login.
  - Evidence: A/main.py:90-102 (origin guard and content-length rule), :116-123 (headers and CSP), :52 (login disabled); deploy/scaffold-lab.py:35-41 (urllib request with no Origin header).
- **[verified-in-code]** The manager persists the original YAML verbatim (`definition_yaml`) but keeps only a normalised, lossy schema-3 `drawing`, not the original annotations JSON. Git save folders, including reference/<state>, contain device configurations and a manifest with `topology_digest` only, never the topology YAML or the map. scaffold-lab.py drives only the Git folder and save routes; it creates no topology file and deploys nothing.
  - Evidence: A/discovery.py:600, :629; A/vm_files.py:131; A/topology.py:185-189 (whitelisted output; tests T/test_topology.py:53-56); A/git_progress.py:204-208, :695 (the only uses of definition_yaml, by grep); deploy/scaffold-lab.py:96-156; deploy/lab-template/README.md:8-10; a grep for 'lab-template' finds no code references. Probe: stored lab keys include definition_yaml and drawing, and /api/state exposes neither.

## Open questions

- Does clab-ui 0.3.2 write the same id into both nodeAnnotations and networkNodeAnnotations during normal editing (bridges with group membership), or only in older files? The save code keeps that shape by design (U/src/core/io/TopologyIO.ts:193-198), but I saw it in only one test fixture and did not run clab-ui.
- Does clab-ui read the manager's exported annotations cleanly (A/layout.py:50-82 sets yamlNodeId on every node)? I inferred it is harmless from U/src/core/parsing/AliasNodeHandler.ts:82-86; it was not executed in clab-ui.
- Can clab-ui's YAML writer produce output that parse_definition rejects: anchors or aliases kept from an imported file, kinds inherited through topology.groups, or node names outside [A-Za-z0-9_.-]? I did not read the clab-ui YAML writer and node-name rules in depth.
- I did not read the frontend diagram editor payload (S/diagram-editor.js) in full. An imported decoration outside the layout.py ranges (for example rotation beyond ±360, which parse_drawing accepts up to ±100000) might block a later PUT /layout save. I did not verify this.
- I did not read A/telemetry_map.py; the statement that the Grafana map derives from the same drawing rests on CLAUDE.md and the agent instructions. How it treats builder-made drawings with fake 'host' or 'mgmt-net' nodes is unknown.
- Would the maintainer accept a new helper action (overwrite YAML, write the annotations file, mkdir)? It changes the security-sensitive host_operations.py, reverses the 1.12.0 removal of VM YAML editing, and needs a helper refresh on every VM. This is a product decision, not something the code answers.
- None of the helper behaviour was exercised on a VM. The create, deploy and discovery facts come from code and unit tests only, including whether the installed containerlab supports `deploy --name` and how a redeploy treats the annotations file.
- I found no evidence of a second writer of the VM annotations file on a standard install, but I did not search for one. The manager only reads that file, so conflict behaviour with the engineer's VS Code extension is whatever clab-ui or vscode do on their own.
