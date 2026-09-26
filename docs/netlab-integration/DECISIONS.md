# netlab integration: architecture decisions

Each decision names its evidence (a file in this folder, a reconnaissance report under
`~/research/netlab-integration/`, a test, or a live observation). A decision without evidence is marked
*provisional* and is revisited when the evidence exists. Newer decisions supersede older ones where they
disagree.

## 0. Boundaries carried over from the assignment (not negotiable)

- Containerlab Node Manager stays what it is: lab creation, lifecycle, topology editing, discovery, readiness,
  terminals, capture, backup/restore and Git progress keep their behaviour and their tests. Nothing is
  replaced by `netlab up`, `netlab down`, `netlab connect`, `netlab capture` or a netlab Git flow. No Vagrant
  or libvirt management, no second topology editor, no generic shell runner, no Docker socket or host metrics
  in the manager, no telemetry or Grafana, no usage reporting.
- The shipped product keeps its controls: restricted container, exact host helpers, same-origin guard,
  review and confirmation before every device change, credential protection, `operation_busy`, native
  transactions with timed recovery, scrubbed public views and logs. Claude's unrestricted VM access is a
  development fact, not a product change.
- Existing labs, topology YAML, annotations, unknown-but-valid Containerlab fields, custom kinds and images,
  environment settings, startup delays, management settings, port mappings and user-chosen interface names are
  preserved. *Edit map* stays drawing-only; network design never edits a deployed lab's topology.
- The feature is opt-in: a workspace without network-intent data behaves exactly as before; no migration, no
  renumbering, no automatic configuration change, no replay of a saved design on deploy or redeploy.
- The student guide (`docs/student-quick-start/`) is not modified by this stream.

## 1. Engine: pinned `networklab` as a subprocess in a per-job working directory

*Status: decided for the engine identity; the exact argv and output contract are filled in from
`RECON-external-provider.md` (D1.3).*

- D1.1 The engine is the released PyPI distribution `networklab==26.9` (upstream tag `release_26.09`, commit
  `e2b636bd02`, released 2026-09-18, MIT licence, `Requires-Python >=3.10`), pinned exactly in
  `clab-backup-ui/requirements.txt` and installed into the same image as the manager (`python:3.12-slim`).
  Its runtime dependencies (Jinja2, PyYAML, netaddr, python-box, importlib_resources, typing-extensions,
  filelock, packaging, requests, rich) add about 78 MB to the image and do not touch the manager's pinned
  Ansible and collections stack. No floating `dev` branch, no Git install at startup, no global VM install,
  no Node build. A lab VM gets the engine with the image; nothing else is required.
- D1.2 The manager calls the CLI (`netlab create`) as a child process, never `netsim` internals in-process:
  the CLI is the documented contract, a child process gives a timeout, a kill, a private `HOME`, a private
  working directory, an empty environment and bounded output; and netlab's global state (Box defaults, cwd,
  `~/.netlab.yml`) never leaks into the manager process. A bounded reader of netlab's data-only outputs
  (`-o json`/`-o yaml` of the transformed topology and the per-node configuration files) is the only
  coupling; contract tests pin their shape for the pinned version.
- D1.3 Provider is `external` (compile-only; the manager's containerlab stays the lifecycle owner); every
  node carries an explicit management address (`mgmt.ipv4`) and every link endpoint an explicit `ifname`
  from the manager's endpoint mapping, so nothing is inferred from link order. Outputs are selected
  explicitly; the default outputs (provider file, Ansible inventory, pickle snapshot) are never requested,
  and a pickle is never read or accepted as an import.
- D1.4 A generation runs in `DATA_DIR/network-design/work/<job>/` (created 0700, removed after the artifacts
  are copied), with `HOME` set inside it, a minimal environment, `netlab`'s usage statistics disabled through
  its own supported setting, a wall-clock timeout, output caps and no network access needed. Tests assert
  that a compile-only job opens no socket and never runs `docker`, `containerlab`, `ansible-playbook` or
  `netlab up`.
- D1.5 Network-design YAML is never arbitrary netlab project content. Students edit a manager-owned intent
  document (D2); the manager builds the netlab topology itself from an allowlist of module attributes. Topology
  `include`, `plugin`, `defaults` paths, custom templates, `validate`, `tools`, `message`, hooks, provider
  options and output destinations are never taken from user input.

### Confirmed by the reconnaissance and the prototypes (2026-09-26)

Reports: `~/research/netlab-integration/RECON-external-provider.md` and `RECON-capabilities.md`; prototypes
`proto-external/` (the square under `provider: external`), `proto-mgmt/` (explicit ids, loopbacks, /31 link
prefixes and `mgmt.ifname`), the session's smoke runs of the adapter against the live topology file.

- `-o config` renders with Jinja2 only (no Ansible), writes `node_files/<node>/<module>` under the current
  directory after deleting any previous `node_files/`, in the order `normalize` (cEOS only), `initial`, then the
  node's module list; the per-node `[CONFIG]` progress line goes to stdout. Every engine failure exits 1 with
  class-tagged lines on stderr (`IncorrectValue in modules: Device type eos (node r1) does not support module
  eigrp`, ..., `Fatal error in netlab: ...`); nothing is written before the abort.
- Outside the working directory netlab writes only `$HOME/.netlab/` (usage counters, a pickled defaults cache
  it loads on later runs); it makes no network connection (static grep and `strace -f -e trace=network`: one
  loopback capability probe, no connect). Usage statistics are local files, disabled by netlab's own
  `_disabled: true` flag, which the runner seeds into the job's private HOME; there is no environment switch.
- Injection paths a compiler-only integration must close, all closed by D1.4/D1.5: `--defaults`, `-s`,
  `--plugin`, `-o yaml:<expr>` (Python `eval`), the topology keys `plugin`, `defaults.paths.*`,
  `defaults.sources.*`, `defaults.netlab.create.plugin`, `_include`, `config`, `tools`, `validate`; the
  auto-merged `./topology-defaults.yml`, `~/.netlab.yml`, `~/topology-defaults.yml`; and every `NETLAB_*`
  environment variable (turned into a topology default). The runner's fixed argv, fresh cwd and HOME and
  four-variable environment leave none of them reachable; the intent schema refuses those keys by name.
- Explicit `id`, `loopback.{ipv4,ipv6}`, link `prefix.{ipv4,ipv6}`, `mgmt.ipv4` and `mgmt.ifname` are
  honoured under `provider: external`; interface names given as `ifname` are used verbatim (Junos adds the
  `.0` unit in the rendered text). netlab has no profile for cJunosEvolved or XRv9k; `vptx` and `iosxr` are
  the stand-ins (D3.2) and the `external` provider never reads a profile's containerlab block.
- Reordering nodes or links in the input **renumbers** unpinned ids, loopbacks and p2p prefixes; a purely
  appended link changes nothing else. Hence the ledger (D2.4), and the adapter emits nodes (routers first,
  then hosts, by name) and links (by key) in a sorted order so the same semantic input gives byte-identical
  files whatever the file order.
- netlab's pool allocator does not skip statically pinned prefixes: with the first link pinned to
  `10.1.0.0/31`, a new unpinned link received `10.1.0.0/31` too. The generation therefore checks the plan
  for collisions (`design_adapter.collisions`), assigns the first free prefix of the same size from the same
  pool to each colliding new link (`fix_collisions`) and runs the engine a second time with those pins; a
  plan that still overlaps (`overlaps`) fails validation instead of being shown.
- The rendered fragments are merge fragments for a fresh device. They carry statements the design must not
  apply as they are: the management interface stanza (EOS `interface Management0` with LLDP off), `hostname`,
  EOS `aaa authorization exec default local`, `mac-address` lines, the cEOS `normalize` file (interfaces
  shut and re-addressed), and Junos `delete: <hierarchy>;` tags that wipe a whole protocol stanza before
  re-creating it. D4.4's provisioning layer filters those and manages removal through the ownership ledger.
- The Linux host's `initial`/`routing` artifacts are shell scripts: generation only, never applied by the
  design (a host driver, if ever, would be its own reviewed contract).

### Risk review of chunk 1 (Opus `risk-reviewer`, 2026-09-26)

The first pass proved two must-fix and nine should-fix findings, all applied before the commit and pinned
by the `ReviewRegression*` test classes: (1) VLAN and VRF bodies were unchecked because the named types were
looked up under a key the data file does not have, so `_include` file reads, a stored password, injected
lines and links inside a VRF passed validation: now a recursive guard (`design_intent.scan`) refuses
`_`-prefixed and denied keys and unsafe text at every depth, objects are checked against the engine's own
`vlan`/`vrf` schemas with wiring keys refused, and the tool keeps every named type; (2) `engine_status()`
ran `netlab version` with the manager's HOME under the store lock: now answered from metadata without a
process; (3) the second pass pins every first-pass prefix and explicit prefixes count as pinned; (4) the
management network is checked for link prefixes, loopbacks, endpoint addresses, the ledger and the plan;
(5) import needs the revision and keeps the server's ledger; (6) record and pin happen in one locked step;
(7) `stale` and `renumbering` compare against the previous plan; (8) compatibility resolves each device's
effective modules, settings at every level and prerequisites, and blocks; (9) a failed save restores the
list; (10) Remove lab and Start fresh take the plans along, files are 0600 in 0700 folders; (11) engine
lines are scrubbed of directory paths. A second pass verified the fixes (its findings are recorded in
VALIDATION.md for 1.30.43).

## 2. Data model: three layers, one owner each

- D2.1 *Topology and runtime identity* stay where they are: the lab's `definition_yaml`, its `nodes` (name,
  `definition_node`, kind, image, address, port, credentials precedence) and the deployment state from
  discovery. Design pools never replace management addressing or SSH endpoints.
- D2.2 *Network intent* is a schema-versioned, data-only document stored on the lab record under the private
  key `network_design` in the encrypted state (so it survives reload and restart like everything else) and
  exposed through its own public serialiser (`public_design`) that never carries secrets. It holds the
  requested addressing pools, per-node and per-link settings, protocols and services, target selection, the
  platform profile choices, the stable allocation ledger (D2.4) and the endpoint mapping (D2.5). A sidecar
  export `<lab>.network-intent.yml` (download, Git design export, later VM publication) is the portable form;
  browser storage keeps drafts only.
- D2.3 *Generations* are immutable: a bounded list `network_generations` on the lab record (metadata: input
  hashes of topology and intent, target identities, engine and profile versions, warnings, capability
  decisions, ordered artifact list with sizes and hashes, timestamps kept apart from the deterministic
  content) and artifact files under `DATA_DIR/network-design/<lab_id>/<generation_id>/` (0700). A generation
  is what a review token binds to (D4.2).
- D2.4 *Stable allocation*: allocated addresses, router ids, ASNs and ids are written back into the intent's
  allocation ledger after each successful plan and passed to the engine as explicit assignments on the next
  run, so adding or reordering an unrelated node or link does not renumber existing devices; the ledger is
  shown and a renumbering that cannot be avoided is listed for review, never silent.
- D2.5 *Endpoint mapping* is explicit and persisted per link end:
  `manager node ↔ containerlab node/kind/image ↔ netlab device profile ↔ containerlab endpoint ↔ NOS interface`.
  The candidate mapping comes from the kinds' documented port rules already in `topology.PORT_RULES`
  (cEOS `ethN = EthernetN`, vJunos-switch `eth1 = ge-0/0/0`, cJunosEvolved `eth4 = et-0/0/0`, XRv9k
  `eth1 = Gi0/0/0/0`) and is confirmed against the live interface list where the lab is deployed. An
  endpoint that cannot be resolved blocks generation and apply for that target; nothing falls back to a
  guessed port. Parallel links, dictionary endpoint syntax, `linux` support nodes and renamed nodes are
  handled explicitly (a support node is modelled as `linux` or excluded, never guessed as a router).

## 3. Capability model

- D3.1 One shared model (`design_capabilities.py`) serves backend validation and the UI. Three axes per
  (feature, platform profile): what netlab 26.09 can render (from the engine's own device feature data,
  read at build time of the model, not hand-copied), what the exact image accepts (integration-specific
  limits, narrowly scoped), and what this integration validated and at which level (`verified_on_image`,
  `generated_not_live_tested`, `unsupported`, `blocked_missing_prerequisite`). Nothing flattens to one
  green mark; an unsupported target is refused before any device is touched; a requested feature is never
  silently dropped or downgraded.
- D3.2 The kind → profile table is explicit and carries its evidence: `arista_ceos → eos`,
  `juniper_vjunosswitch → vjunos-switch`, `juniper_cjunosevolved → vptx` (Junos Evolved lineage; cJunosEvolved
  is **not** vPTX: interface names, management interface and image differ and are pinned by the adapter, not
  assumed), `cisco_xrv9k → iosxr` (netlab's profile targets XRd; XRv9k is **not** XRd: the adapter pins the
  interface and management names it needs and marks every feature as unverified until proven live).
  `linux` support nodes map to netlab `linux` or are excluded from the design; any other kind is
  `unsupported` with that reason.

## 4. Generation, review and apply

- D4.1 Planning, previewing and downloading configure nothing: no device connection, no helper call, no
  deploy or destroy, no Git change, no Docker. Tested positively and negatively.
- D4.2 A review token (expiring, single use) binds the generation id, the selected targets, the topology and
  intent hashes, the endpoint mapping digest and the live baseline digest per target taken at review time;
  apply rechecks drift before touching a device and never applies bytes other than the reviewed ones.
- D4.3 Provisioning is its own driver contract (`design_drivers.py`, provisional name), separate from
  `restore_drivers.py`. A netlab fragment is never sent to the whole-configuration replacement of *Apply to
  running lab*; replacement stays what it is. Each platform gets a native candidate or session transaction
  with the NOS's own timed recovery, a fresh reconnect before confirmation (IOS XR confirms only from the
  arming session), a mandatory pre-change backup through the Runner, per-node outcomes (confirmed, reverted,
  failed, interrupted, unknown) and restart reconciliation, reusing the direct node-SSH path, credential
  precedence, the shell helpers and the scrubbing that restore already has.
- D4.4 Ownership: the manager persists, per target, the exact statements a generation added (the set of
  design-owned statements in the platform's comparable form), so a later generation can remove what it no
  longer generates (an address, a BGP peer, a protocol instance, a VRF) statement by statement, and never
  deletes a whole hierarchy to simplify reconciliation. A manual statement that conflicts with a managed one
  blocks with an explanation or needs an explicit reviewed ownership decision. A full replacement route, if
  ever offered, needs an explicit choice, a complete candidate and the restore-grade contract.
- D4.5 The apply job joins the existing coordination: `operation_busy` (a new busy family), the Runner's
  single worker for its backups, lifespan close and interrupted-job reconciliation at startup, `Store.event`
  with controlled metadata only, and public serialisers that strip secrets and candidates.

## 5. UI

- D5.1 *Network design* is a section of the lab workspace (a tab beside Topology, Devices, Progress, Tools,
  Advanced), plain script `network-design.js` in house style, with clear states (no design, draft changed,
  generating, validation failed, ready to review, applying, verifying, applied and verified, partial failure,
  interrupted). Guided controls for the common workflow plus a schema-validated advanced intent editor that
  round-trips supported fields. Drafts survive navigation and reload; a stale tab cannot overwrite a newer
  edit (revision check).

## 6. Persistence and export

- D6.1 *Export network design* is a separate reviewed action with its own allowlisted artifact set (the
  intent document, the plan, the generated per-device files and a design manifest that names them as
  generated artifacts, never as backups); ordinary *Save progress* is unchanged. Imports validate schema,
  sizes, hashes and artifact types. Publication of a sidecar on the VM, if needed, goes through a bounded
  helper action with the same guarantees as `publish`/`revise` (D6.2, provisional).

## 7. Routing

- D7.1 Fable orchestrates and owns architecture, integration, acceptance and releases. Reconnaissance and
  bounded implementation go to Sonnet (explicit `model: sonnet`), mechanical work to Haiku, and the
  consequential designs and reviews (ownership and removal semantics, candidate transactions, security
  boundaries, host helper changes) to Opus (`claude-opus-5-5`, the project's `risk-reviewer`). Requested and
  observed models are recorded per task in TESTS.md.
