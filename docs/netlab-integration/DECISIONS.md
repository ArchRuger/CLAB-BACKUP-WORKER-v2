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
lines are scrubbed of directory paths. The second pass verified six fixes and found two more must-fix items
(prefixes hidden inside module settings and VRF loopbacks were not checked against the management network;
Remove lab and Start fresh did not wait for a running generation) and a regression (a VRF could no longer be
attached to a link), all fixed and pinned (`SecondPassRegression*`). The third pass verified those and found
one more must-fix: a topology with no `mgmt` block left containerlab's default management network
(`172.20.20.0/24`, `3fff:172:20:20::/64`) and its gateway unguarded; `management_networks()` now falls back
to those defaults (and to the /24 or /64 around each device address for `auto`), interface addresses are
guarded by their whole subnet, dict-form VRF loopbacks are checked, `False` and a VRF name are accepted only
at the link and interface levels (the node and global forms crash the engine), and an engine traceback
becomes one controlled line naming the exception class (`ThirdPassRegression*`, `CrashContractTests`). The
first pass' outcome is in VALIDATION.md for 1.30.43, the second and third in the entry for 1.30.44.

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
  precedence, the shell helpers and the scrubbing that restore already has. *Superseded in its naming and
  filled in with the mechanics by §8 (milestone D, implemented and live-proven 2026-09-27): the provisional
  `design_drivers.py` became `design_provision.py` (filtering) plus one module per platform (`design_eos.py`,
  `design_junos.py`, `design_iosxr.py`) and the pure algebra `design_ownership.py`, orchestrated by
  `design_apply.py`.*
- D4.4 Ownership: the manager persists, per target, the exact statements a generation added (the set of
  design-owned statements in the platform's comparable form), so a later generation can remove what it no
  longer generates (an address, a BGP peer, a protocol instance, a VRF) statement by statement, and never
  deletes a whole hierarchy to simplify reconciliation. A manual statement that conflicts with a managed one
  blocks with an explanation or needs an explicit reviewed ownership decision. A full replacement route, if
  ever offered, needs an explicit choice, a complete candidate and the restore-grade contract. *Refined by
  §8.2–§8.4: ownership is computed as set differences between device-rendered snapshots, never by parsing the
  fragment or a NOS diff, and removal happens at the highest created ancestor whose subtree is entirely owned
  and stale, not leaf by leaf.*
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

## 8. Provisioning: milestone D (safe apply to devices, implemented and live-proven 2026-09-27)

The full contract with every rule, its platform shapes and the review findings is
[PROVISIONING.md](PROVISIONING.md); this section records only the decisions and why, each with the evidence
that settled it. Live evidence: `evidence/live-apply-{ceos,junos,iosxr}.md`, run on `restore-square`. These
decisions refine D4.3 and D4.4 (noted there) rather than replace them.

- D8.1 A generated fragment is merged into the running configuration inside the NOS's own transaction
  (EOS configuration session, Junos exclusive candidate, IOS XR exclusive session), never sent through the
  whole-configuration replacement of *Apply to running lab* (`restore.py`/`restore_drivers.py`). Reason: a
  design fragment is partial by construction (management, AAA, logins, hostname and identity are filtered out,
  §1 of PROVISIONING.md) and must coexist with whatever manual configuration and containerlab defaults are
  already on the device; a replacement candidate has to be complete and would discard both. Evidence: manual
  `Loopback99` and the manual BGP peer `192.0.2.200` on cEOS survive every create/modify/remove cycle
  (`evidence/live-apply-ceos.md` steps 3–10); the two features keep separate job lists, drivers and words
  (PROVISIONING.md §1, "Nothing here replaces *Apply to running lab*").
- D8.2 Ownership is computed as set differences between device-rendered snapshots (EOS/IOS XR: running-config
  lines with parents; Junos: `display set` statements), never by parsing the generated fragment and never by
  reading a NOS's own diff view. Reason: the fragment text is not what lands on the device (the device adds its
  own defaults, moves statements, renders differently), and a NOS diff can actively mislead. Evidence:
  cEOS `show session-config` already carries `max-lsa 12000` under a fresh OSPF process that the fragment never
  mentioned (PROVISIONING.md §7); IOS XR `show configuration changes diff` prints a merge as if the whole
  running configuration were replaced (§7, verified, review S7). This is the *(review M5)* fix and refines
  D4.4.
- D8.3 The desired set is the candidate alone, rendered by the device itself on an empty base, not the parsed
  input text (the parsed fragment is kept only as a fallback where the device cannot render it). Reason: only
  the device's own renderer normalises syntax exactly the way the merge will store it (Junos unit shorthand,
  EOS moved `network` lines, device defaults); computing "desired" from our own text would drift from what the
  device actually considers present. Evidence: the throwaway-session/private-candidate/plain-`configure`
  mechanics per platform, each verified live (PROVISIONING.md §2 row "Desired set"; review M1).
- D8.4 Removal happens at the highest created ancestor whose current subtree is entirely owned and stale (one
  `no router ospf 1` rather than every leaf under it), refined per platform from live failures rather than
  assumed:
  - **EOS BGP neighbours are one object.** Per-line negation left orphaned `no neighbor X activate` lines in
    the running configuration when every line of a neighbour was actually stale. Fixed: a neighbour removed
    whole is one `no neighbor X`; a neighbour with a manual line under it still comes off leaf by leaf.
    Evidence: `evidence/live-apply-ceos.md` step 5.
  - **EOS `network` statements move to the process level when an address family is removed**, they are not
    deleted with it. Fixed: an address family removed whole has its `network` statements removed by name
    first. Evidence: `evidence/live-apply-ceos.md` step 6 (four relocated `network` lines found owned and
    stale after the family was gone).
  - **Junos created ancestors are limited to the device's own blocks.** The raw word-prefixes of an added
    `set` statement include keyword-only levels Junos cannot `delete` (`set protocols bgp group X neighbor`);
    taking every prefix as an "ancestor" produced 158–173 unusable entries. Fixed: the driver also returns the
    device's own hierarchical `show` of the would-be configuration, and `design_ownership.junos_blocks` limits
    ancestors to that rendering (`X.N {` interface shorthand becomes `X` and `X unit N`). Evidence:
    `evidence/live-apply-junos.md` step 3 and finding (b); PROVISIONING.md §8, review M2.
  - **IOS XR typed negations are verified as the absence of their positive form.** `show configuration merge`
    never prints `no shutdown` or `no management enable`; a read-back that expected to see them literally
    reported four correct statements as missing. Fixed: verification checks absence, not a literal negated
    line. Evidence: `evidence/live-apply-iosxr.md` facts and step 2 (the first apply's `verify_mismatch`
    defect).
  - **A vanishing `shutdown` under a design-configured interface is an expected change, not a conflict.**
    IOS XR data ports ship `shutdown`; the design's `no shutdown` removes an unowned line, but doing so is the
    point of a first apply. Fixed: named as an *expected change* and never re-applied on later removal of the
    same interface. Evidence: `evidence/live-apply-iosxr.md` step 1 (reported as 2 conflicts before the rule,
    0 after); PROVISIONING.md §3, review S3.
- D8.5 A conflict (an unowned statement the candidate would touch) blocks the apply outright; the only way
  through is the student's explicit, reviewed *Take over these settings* choice for that device, which
  re-runs the review and whose token then carries the exact take-over list (the apply refuses a body whose
  list differs). Reason: a manual setting must never be silently overwritten, but the student needs a
  deliberate way to reclaim it, and that decision must be re-reviewed like any other apply. Evidence:
  `evidence/live-apply-ceos.md` steps 3/3b (a manual `description` on the owned `Ethernet1` blocks with
  `applicable: []` until `takeover: [ceos]` is given, after which it applies and the design's description
  comes back while the untouched manual `Loopback99` and peer stay put). Review S6.
- D8.6 The review token binds the generation id, the selected targets, the intent revision, the topology and
  endpoint-mapping digests, and each target's `before` digest and take-over list; it is single-use, expires in
  ten minutes, and is checked once at submit rather than on every later read. Reason: apply must never touch
  bytes other than the ones the student reviewed, and drift or a plan change between review and apply must be
  refused rather than silently re-applied. Evidence: PROVISIONING.md §4; review O1. This is the filled-in form
  of D4.2, which named "topology and intent hashes… and the live baseline digest" without the take-over list
  or the once-at-submit rule.
- D8.7 A pre-change backup of every target through the Runner (`source='design-pre'`) is mandatory before any
  device is touched; a device whose backup fails is not changed. Reason: parity with *Apply to running lab*'s
  own invariant, and it gives every changed device a restore path independent of the design feature. Evidence:
  PROVISIONING.md §4 step 2; `design-pre`/`design-post` backups recorded as succeeded in
  `evidence/live-apply-ceos.md` step 1 and `evidence/live-apply-junos.md` step 2.
- D8.8 Settle rules mirror the restore's caution: a device is reported `rolled_back` only after the `before`
  snapshot has actually been read back from a fresh connection; anything else the manager cannot positively
  confirm is `uncertain`, with a pending ledger entry that blocks the next review of that device until a later
  read-back resolves it. Reason: declaring a rollback that was never independently verified is worse than
  admitting the outcome is unknown. Evidence: `evidence/live-apply-ceos.md` step 7 ("The change was not
  confirmed in time and the device undid it; the configuration from before is active.", stated only after the
  independent read-back matched); PROVISIONING.md §3.
- D8.9 On IOS XR, only the session that armed `commit confirmed` can confirm it; unlike EOS (identified by its
  named session with a pending timer) and Junos (identified by the commit comment on entry 0), a fresh
  connection cannot confirm an IOS XR trial by name alone. A manager restart therefore keeps the persisted
  deadline and waits for the device's own timer to resolve the trial (auto-rollback) before reading the device
  back, instead of attempting one immediate pass with a new session. Reason: there is no safe way to confirm
  from outside the arming session, and starting a new session while one is armed is itself a conflict the
  driver refuses; waiting for the device's own timed recovery is the only action that cannot make things
  worse. Evidence: PROVISIONING.md §8 ("the recheck keeps the persisted deadline and waits for the device's
  own timer… instead of one immediate pass"); the driver's `_HELD` table and held-session design in
  `design_iosxr.py`.
- D8.10 An interrupted job states, per device, what the read-back actually came to ("Read back afterwards:
  ceos applied and verified" / "… undone by the device"), not a blanket "undone by the device". Reason: after
  a restart the manager may still confirm its own pending change (EOS/Junos) and the device ends up matching
  the design; a fixed "undone" wording would misreport that case. Evidence: `evidence/live-apply-ceos.md`
  step 8 (killed after arming, restarted inside the window, the recheck confirmed the manager's own pending
  session and read back `verified`); PROVISIONING.md §8.
- D8.11 A BGP AS (or OSPF process id) change on IOS XR that IOS XR itself refuses to commit in one step (remove
  `router bgp 65000`, add `router bgp 65100` together) is reported as a clean failure with the device's own
  reason, and the way through is left to two separate applies (drop the module, then add it back with the new
  AS) rather than built as an orchestrated two-commit transaction. Reason: a two-commit transaction would need
  its own recovery and confirmation semantics on top of the existing per-apply ones, doubling the failure
  surface for a case the device itself will not accept atomically anyway; two ordinary applies reuse every
  existing safety mechanism unchanged. Evidence: `evidence/live-apply-iosxr.md` step 4 ("IOS XR refuses to
  remove `router bgp 65000` and create `router bgp 65100` in one commit… the way through is two applies"); the
  driver surfaces the device's own `show configuration failed` reasons in the failure message.
- D8.12 `send-community` is no longer masked in a review's diff; only genuine secrets (for example
  `snmp-server community`) stay redacted. Reason: it is a well-known BGP capability keyword, not a secret, and
  the restore masker's substring match on "community" was hiding legitimate, non-sensitive configuration from
  the student in every review. Evidence: `evidence/live-apply-ceos.md`, "Words the students see"; PROVISIONING.md
  §8.
- D8.13 The cEOSLab management-interface LLDP-off lines (`no lldp transmit` / `no lldp receive`) are left out
  of the candidate entirely on cEOS, and the whole management block is named among the protected settings,
  rather than sent and handled as a failure. Reason: this is a proven image limitation (cEOSLab 4.35.0F refuses
  the lines with `% Invalid input`), not a design choice to negotiate; `lldp run` therefore also covers the
  management port on cEOS, which is recorded as a known limit rather than worked around. Evidence:
  PROVISIONING.md §1, verified through the driver on 2026-09-27.
- D8.14 The apply page reuses the restore dialog's shape (review → recovery-window acknowledgement → live
  per-device progress with stages and outcomes → an ownership view under Advanced) instead of a new
  interaction pattern, and defines one specific word per outcome (`verified`, `applied_unverified`,
  `verify_mismatch`, `kept_manual`, `failed`, `rolled_back`, `uncertain`, `interrupted`, `ineligible`,
  `drifted`, `conflict`, `no_op`). Reason: students already know the restore dialog; reusing it keeps *Apply
  to running lab* and *Apply to devices* consistent, and a job-level "healthy" label must never be allowed to
  hide one failed or unverified device behind it. Evidence: `docs/NETWORK-DESIGN.md` "Applying a plan to
  devices" step 4; PROVISIONING.md §5 ("the live progress per device (the restore dialog's shape…)") and §4
  (the outcome list).
- D8.15 A fourth risk-review pass (Opus) ran after the live proof and before the release; its nine findings are
  applied and listed in PROVISIONING.md §8 "Fourth review pass". The decisions it forced: a held IOS XR session is
  released on every path that does not confirm; a refused commit's reasons reach the job only as fixed phrases
  (job messages never carry device text); a pending ledger entry is resolved by the next review's read-back rather
  than blocking the device; a plan is applied only while it is the current design's and topology's plan; an armed
  change the manager could not compare with the review is compared with the would-be digest before confirming;
  the busy guard is manager-wide for applies and restores because the Runner is.
