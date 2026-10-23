# C08 design: builder YAML checks against the VM's containerlab, and stage validation

Rows R071 (YAML editing with schema validation, completion and hover) and R072 (stages: boot order with `wait-for`
and exec commands). Written against `claude/parity-campaign` at `1f901c7` (release 1.31.2, containerlab 0.79.0 on
the VM, editor `@containerlab/clab-ui` 0.3.2 pinned). This is the interim that needs no editor upgrade: C11 (the
blocked 0.4.0 upgrade) brings the Stages tab, the Kind tab and Monaco; everything here stays useful after it as the
check of the manager's own YAML panel. No helper change, no helper `VERSION` bump, no new route: the whole check runs
in the browser over the text the panel already holds. Code read: `lab-builder-yaml.js`, `lab-builder-page.js`,
`lab-builder.html`, `lab-builder.css`, `lab-builder/src/main.tsx` (`yamlFlaw`, the `YamlEditorHandle`, `mount`),
`monaco-stub.ts`, `build.mjs`, `patches.mjs`, `host_operations.py` (`capabilities`, `plan` for `publish`/`revise`,
`publish`, `revise`), `lab_operations.py` (`capabilities`, `parse_yaml`, the `publish`/`revise` branch of `preview`),
`discovery.parse_definition`, `main.py` (caching and CSP of the builder page), `deploy/verify-release.py`,
`tests/test_lab_builder_yaml_ui.js`, `tests/test_lab_builder_ui.js`, `tests/test_lab_operations.py` (the publish and
revise tests), `docs/lab-builder/tools/student_workflow.py`, `docs/redesign/tools/fixture_manager.py` (its
`capabilities` answer carries `containerlab: '0.79.0'`), and upstream `containerlab-app` (`packages/clab-ui/src/yaml/index.ts`,
`core/utilities/nodeStages.ts`, `components/panels/node-editor/StagesTab.tsx`, `scripts/sync-clab-schema.mjs`,
`docs/guides/topologies.md` "Set the boot order").

## 0. Facts established in this session (read-only on the development VM, nothing deployed)

| Fact | How |
|---|---|
| containerlab 0.79.0 (commit `5ae50094a`, 2026-08-21) is installed at `/usr/bin/containerlab`; `/etc/containerlab` holds only `lab-examples/` and `suid_setup_done`; the binary embeds no JSON schema (`strings` finds no `schema.json`); nothing else on the VM carries one. | `containerlab version`, `ls /etc/containerlab`, `find / -iname 'clab.schema.json'` (only the research clone under the scratchpad), `strings` |
| containerlab publishes `schemas/clab.schema.json` in its repository. At tag `v0.79.0` it is **104,931 bytes** (11.4 KB gzipped), SHA-256 `51a7025041d90fcded90911d4947773794464ccd903f01c03d5b2ff988f58d02`, `$id https://containerlab.dev/clab.schema.json`, draft-07. `v0.78.0`: 103,912 B; `v0.80.0`: 153,065 B; `main` (2026-10-23): 167,491 B. The repository's licence is **BSD-3-Clause** (Copyright 2021 Nokia); the schema has no licence header of its own. | `curl` of `raw.githubusercontent.com/srl-labs/containerlab/<ref>/schemas/clab.schema.json` and `/LICENSE` into the scratchpad; `sha256sum`, `gzip -c \| wc -c` |
| The 0.79.0 schema differs from `main`: 50 node keys against 66 (`main` adds `bootstrap-config`, `breakouts`, `config-mode`, `copy-to-flash`, `daemons`, `mgmt-intf`, `mgmt-net`, `port-count`, `sfm`, `wait`, …; 0.79.0 alone has `extras`), 63 kinds against 66 (`main` adds `frr`, `frrouting`, `fortinet_fortiproxy`; drops `border0`, `mikrotik_chr`), and `main` carries per-kind `kind-specific-config-*` definitions 0.79.0 lacks. The upstream editor syncs `main` daily; **the schema the editor bundles is not the schema of the VM's binary**, which is why the schema must be vendored per containerlab release and chosen by the version the helper reports. | `python3 -I` diff of the two files |
| Keywords the 0.79.0 schema uses: `type`, `properties`, `additionalProperties` (38, always `false`), `patternProperties`, `required`, `enum`, `const`, `pattern` (26), `$ref` (155, all local `#/definitions/…`), `items`, `prefixItems` (1), `additionalItems` (1), `minItems`, `maxItems`, `uniqueItems`, `minimum`, `maximum`, `minLength`, `minProperties` (1), `anyOf` (13), `oneOf` (4), `allOf` (2), `if`/`then`/`else` (the per-kind `type` enums), `not` (2), `default`, `description`, `markdownDescription`. Four patterns use `\p{N}\p{L}` (need the JavaScript `u` flag); none uses a construct JavaScript lacks. | keyword inventory script |
| `containerlab validate` exists on 0.79.0 ("parse and validate a topology definition file without deploying it", `-t` takes a path or `stdin`), runs unprivileged, and `containerlab deploy --dry-run` creates nothing (no container, no lab folder, verified after every run). | `containerlab validate --help`, runs below, `docker ps -a`, `ls` |
| The two-node Juniper stage example of §4.5 is accepted: `validate` answers `Topology is valid name=c08stage nodes=2 links=1`, `deploy --dry-run` prints the plan `deploy lab c08stage`, exit 0 both. | run on `/tmp/…/scratchpad/c08-dry/c08stage.clab.yml` |
| **What 0.79.0 refuses at parse time** (exit 1, `Failed to read topology file: yaml: unmarshal errors: line N: …`): an unknown key at the top level (`field foo not found in type core.Config`), under `mgmt` (`…MgmtNetWithDeprecatedFields`), on a node (`…NodeDefinitionWithDeprecatedFields`), inside `stages` (`field boot not found in type types.Stages`), inside a `wait-for` entry (`field until not found in type types.WaitFor`); a repeated key (`key "a" already set in map`); a wrong value type (`env: [A=1]` → `cannot unmarshal !!seq into map[string]string`); the **object form of stage `exec`** (`exec: {on-enter: [...]}` → `cannot unmarshal !!map into types.Execs`) and a bare string command (`exec: [ls -l]` → `cannot unmarshal !!str into types.Exec`), although the 0.79.0 schema allows both forms; an unknown or missing `kind` (`kind "nosuchkind" is not supported. Supported kinds are "…"`, a list of 108 names that includes the `vr-*` aliases and short aliases `ceos`, `srl`, `xrd`, `cvx`, `crpd`, `cjunosevolved`, `c8000`, `cumulus_cvx`, `host`, `linux`, `bridge`, `ovs-bridge`, `ext-container` the schema's 63-name enum does not list); a brief link with one endpoint (`endpoint definition should consist of exactly 2 entries`); a link endpoint naming an unknown node (`Unable to find node zz`); a bad port string (`Invalid containerPort: abc`); a numeric bind (`Bind "1" looks like an anonymous volume target`). | sixteen scratch files through `containerlab validate` |
| **What 0.79.0's `validate` accepts** (exit 0, "Topology is valid") although a deploy cannot use it: a `wait-for` naming a node that does not exist, a node waiting for itself, two nodes waiting for each other, a `wait-for` `stage` outside the five stages (`ready`), a `wait-for` entry without `stage`, a vrnetlab node without `image`, `network-mode: bogus`, `stages` under `topology.defaults`, kind aliases (`vr-vjunosswitch`, `ceos`, `srl`), the list form of `exec` with and without `phase`, long-form `veth` and `host` links. `deploy --dry-run` accepts the loop and the unknown target too: **the stage graph is not checked before deploy on 0.79.0**, which is what R072 is for. | same runs; `deploy --dry-run` on `waitloop` and `waitunknown` |
| On this VM the vrnetlab kinds define a container healthcheck (`clab-parity-vsw`, `-vrt`, `-xrv9k` show `(healthy)`); `clab-parity-cjunos` and `clab-parity-ceos` show none, so a `wait-for … stage: healthy` on a cEOS or cJunosEvolved node never completes. | `docker ps` |
| The pinned `@containerlab/clab-ui` 0.3.2 package ships `dist/yaml/index.js` (Monaco YAML language support, `ajv`), `dist/core/schema/bundledSchema` and Monaco workers; the manager's build stubs the Monaco chunk because its worker needs script evaluation the CSP refuses (`monaco-stub.ts`). Its bundled schema is a `main` snapshot of 2026-09, not 0.79.0. | `npm pack @containerlab/clab-ui@0.3.2` into the scratchpad, `tar tzf` |
| Memory now: 72 GB total, 26 GB available with the five-node `parity` lab up (owned by the lead); a vJunos-switch plus vJunos-router pair needs about 10 GB and the router boots only on the local nested-virtualization image (C00). | `free -g`, `docker ps`, PICKUP.md |
| Not established: how `containerlab deploy` (not `validate`) ends on a wait-for loop or an unknown target. Upstream's `nodeStages.ts` states "containerlab refuses to deploy a lab when nodes wait on each other in a loop"; no small local image exists on this VM for a disposable `linux` lab (only cEOS at 2 GB each), so this is an assumption the live pass verifies (§7.4). | `docker images` |

## 1. Decisions in one place

1. **The check runs in the browser, in a plain house-style script, over the text the panel already holds.** No helper
   mode, no manager route, no bundle-side validator. `containerlab validate -t stdin` would be the authoritative check,
   but a helper round trip per keystroke (SSH, gateway, `sudo`) cannot answer within the panel's 400 ms, every helper
   change is a release with a helper refresh on every VM and one owner on `host_operations.py` (C05 holds it), and
   §0 shows `validate` does not check the one thing students break (the stage graph). A `validate` mode outside the
   host lock stays an option for a later chunk (not pursued here).
2. **The schema is vendored verbatim per containerlab release, chosen by the version the helper reports.**
   `clab-backup-ui/app/static/clab-schema/0.79.0.json` is byte-for-byte the file at tag `v0.79.0` (digest in §0 and in
   `SOURCES.txt`), beside containerlab's BSD-3-Clause `LICENSE`; a refresh is one Node script in the build project
   (`lab-builder/fetch-schema.mjs <tag>`), never a hand edit, and a stdlib test pins every digest. Verbatim beats a
   pruned extract: a reviewer can `sha256sum` it against upstream, and nothing of ours can drift inside it. The browser
   fetches it once per page load (105 KB, `no-store` like every static file outside the bundle), only when the panel
   first validates, so a student who never opens YAML downloads nothing.
3. **The validator is a small JSON-schema walker plus hand-written rules, not a port of ajv.** The walker covers
   exactly the keyword set of §0 (about 120 lines); the rules in §3 encode what `containerlab validate` proved and what
   the schema cannot say (the stage graph, the exec form the binary reads, healthchecks, inheritance). Where the schema
   and the binary disagree (`exec`), **the binary wins** and the design says so in the rule's wording. Where neither
   the schema nor `validate` refuses but a deploy cannot use the text (a wait-for loop, a missing image), the finding
   is an error or a warning by the evidence table of §3, never by guess: a severity the session could not prove is a
   warning with a sentence that says what will happen.
4. **Diagnostics never block Apply, and nothing here blocks Save.** Apply keeps refusing exactly what it refuses
   today (a syntax error, a repeated key, a shape the engine cannot draw: `main.tsx` `yamlFlaw`), because that text
   would replace the graph with nothing. Everything new is advisory: a vendored schema can be wrong or behind the VM
   (§0 shows the 0.79.0 schema is wrong about `exec`), and a block without an override would be a dead end with no way
   out. The findings are visible in three places instead (§4): the list under the editor, the gutter, and one line in
   the builder bar on the stored draft, so a student who never opens the panel still learns before saving. The
   manager's review and containerlab at deploy keep their own refusals.
5. **Unknown keys and enum values are errors only when the vendored schema matches the VM's version exactly.** With
   an exact match the binary provably refuses them (§0). When the VM's version is newer than every vendored schema,
   unknown, or older than the oldest, the same findings are warnings and the caption names both versions (§2.3): a
   key added in 0.81 must not be called an error on a 0.81 VM because the manager carries 0.79.
6. **The adapter gives the panel a located tree; it does not validate.** `main.tsx` gains one handle method,
   `locateYaml(text)`, that turns the `yaml` library's document into a plain tree with a line per node (§2.1). One
   parser for the whole page (no second YAML parser in plain JavaScript), and the validator stays a pure function of
   plain data that `node:test` exercises without the bundle, without `lab-builder/node_modules`, and without a browser.
   `checkYaml` and `applyYaml` are unchanged (pinned by `test_lab_builder_yaml_ui.js`).
7. **Stage validation follows upstream's wording and adds inheritance.** "There is no node named X", "A node cannot
   wait for itself", "Nodes wait for each other in a loop (a → b → a). containerlab will not deploy the lab." are the
   upstream sentences (`StagesTab.tsx`). The graph includes the `wait-for` entries containerlab adds from
   `topology.defaults`, `kinds` and `groups` (so a `defaults` entry naming node `a` is a self-wait on `a`), and each
   finding points at the line of the entry that causes it.
8. **Hover becomes key help on the caret; completion is deferred to C11 with the reason.** A textarea has no token
   hover, but it has a caret: the help line under the list shows the schema `description` of the key on the caret's
   line, resolved by indentation, with a *More* link to the containerlab.dev page the schema's `markdownDescription`
   names (an external link, no asset). A completion popup over a textarea (positioning, keyboard, screen reader,
   dismiss) is a second editor; Monaco gives it for free when C11 lands, and the two typo cases completion would cure
   (a key, a kind) get a *did you mean* suggestion in their finding instead. Image names stay where the editor offers
   them (the node editor's Image field, fed from the VM).
9. **The Juniper stage example is in the panel's help and in the guide, with Copy.** A `<details>` "Boot order
   (stages): switch before router" holds the two-node YAML of §4.5 and a Copy button (C02's `clipboard.js` is on the
   page). It is the practical answer to a 72 GB VM: the router container is created only after the switch reports
   healthy, so the two 5 GB boots never overlap.
10. **Everything student-facing that depends on the VM's version degrades to the same panel.** Without capabilities
    (VM not connected, older manager tools) the check still runs against the newest vendored schema with warnings and
    says why; without the schema file (fetch failed) the panel is today's panel plus one sentence. Nothing waits on the
    fetch: the status line and Apply work as before while it is on its way.
11. **Not changed here**: the editor bundle's behaviour except the one handle method (no new `patches.mjs` entry);
    `host_operations.py`, `lab_operations.py`, the gateway; the review dialog in `operations.js`; `map-editor.html`
    (it loads neither the YAML panel nor the new script; `MAP_COMMANDS` untouched).

## 2. Contracts

### 2.1 The located tree (`main.tsx` → `lab-builder-yaml.js` → `lab-builder-check.js`)

`YamlEditorHandle` gains:

```ts
// The parsed text as plain data with a 1-based line per node, for the panel's validator; `error` is the
// parser's first error (as checkYaml reports it) and `tree` is then absent. Never an engine call.
locateYaml(text: string): { tree?: Located; error?: YamlFlaw };
```

```ts
type Located =
  | { kind: "map";    line: number; items: Array<{ key: string; keyLine: number; value: Located }> }
  | { kind: "seq";    line: number; items: Located[] }
  | { kind: "scalar"; line: number; value: string | number | boolean | null; tag?: "str" | "int" | "float" | "bool" | "null" };
```

Built from `parseDocument(text, { lineCounter })` with `isMap`/`isSeq`/`isScalar` and `lines.linePos(node.range[0]).line`
(the pattern `yamlFlaw` already uses). Rules: a map key is `String(key.value)`; a key that is not a scalar (a `? [a, b]`
complex key) becomes the string the `yaml` library prints and the validator reports it as an unknown key; aliases
(`*x`) are resolved to their anchor's value by the library and carry the alias's line; a document whose root is not a
map returns the tree as is (the shape rule R0 reports it). `tag` is set from the resolved scalar type so the validator
can tell `"1"` from `1` (a `type: number` key with a quoted number is a wrong type for the Go unmarshaller). The tree
is bounded by the text size (`BUILDER_DROP_LIMIT` 1 MiB already caps a draft), no cycles (aliases are copied).

The panel passes `tree` to the validator together with the schema and the context; the fake editor in the tests
builds trees by hand or with the test helper of §6.

### 2.2 Diagnostics (`lab-builder-check.js` → the panel and the page)

```js
// builderCheck(tree, schema, context) → [{severity:'error'|'warning', line:number, message:string, code:string, path:string[], help?:string}]
// context: {version:'0.79.0'|'' (the VM's containerlab), schemaVersion:'0.79.0', exact:boolean, images?:string[]}
```

Pure, synchronous, no DOM, no fetch; sorted by line then severity (errors first on a line); at most
`BUILDER_CHECK_LIMIT = 200` items (then one closing item "… and N more"); `message` is one sentence a student can act
on, never a JSON pointer or a Go type name; `code` is a stable short word (`unknown-key`, `wait-loop`, …) for the
tests and the suppression of duplicates; `path` is the key path for the tests. `builderCheckSummary(list)` →
`{errors, warnings, text}` with `text` = "2 errors, 1 warning" / "1 warning" / "No problems found" (the count sentence
for the `role=status` element). `builderKeyHelp(tree, schema, line)` → `{key, path, description, url}` or null for the
key on a line (the caret help, §4.3). `builderSchemaChoice(vmVersion, available)` → `{schemaVersion, exact, reason}`
(§2.3). All four are top-level functions of the script, prefixed `builderCheck`/`builderSchema`/`builderKeyHelp`, so
`test_page_load_ui.js` (which loads every builder script in one context) finds no clash.

### 2.3 Which schema, and what the mismatch means

`BUILDER_SCHEMA_VERSIONS = ['0.79.0']` in `lab-builder-check.js` lists the vendored files; the stdlib test of §6 pins
the list to the files present. `builderSchemaChoice(vm, list)`:

| VM version (`builderCaps.containerlab`, from C03's `capabilities`) | Choice | `exact` | Caption under the list |
|---|---|---|---|
| equals a vendored version | that one | true | *Checked against containerlab 0.79.0, the version on this VM.* |
| newer than every vendored one | the newest vendored | false | *Checked against the containerlab 0.79.0 schema; this VM runs 0.81.0. A setting added since then is shown as a warning, not an error.* |
| between two vendored versions | the greatest vendored not above it | false | *Checked against the containerlab 0.79.0 schema; this VM runs 0.79.3.* (same patch line: findings are still warnings, because the lead has not proven the patch releases equal) |
| older than the oldest vendored | the oldest vendored | false | *Checked against the containerlab 0.79.0 schema; this VM runs 0.70.0, older than any schema the manager carries. containerlab itself reports settings it does not know when the lab is deployed.* |
| unknown (`''`: no capabilities yet, VM away, a helper older than C03) | the newest vendored | false | *The VM's containerlab version is not known yet (not connected, or the VM's manager tools are older), so the text is checked against the containerlab 0.79.0 schema; unknown settings are shown as warnings.* |

Versions compare as three integers (`^(\d+)\.(\d+)\.(\d+)`); anything else is "unknown". `exact` makes R1 and R4
errors; otherwise they are warnings. The schema file is fetched by the panel (`fetch('/static/clab-schema/' + v +
'.json')`, same origin, `connect-src 'self'`) the first time a validation needs it and kept for the page's life; a
failed fetch sets `builderYaml.schema = 'failed'` and the list shows one sentence: *The topology schema could not be
loaded from the manager, so only syntax and shape are checked.* with a *Try again* button. The choice is re-made when
`builderCaps` arrives after the panel opened (the page calls `builderYamlContext(caps)`), so a slow VM answer upgrades
the caption and the severities on the next validation without a reload.

## 3. The rules (`lab-builder-check.js`)

Evidence: **P** = `containerlab validate` refused it in §0 (parse-time refusal, error when `exact`); **M** = the
manager's review refuses it (`parse_definition`, error always); **U** = upstream's Stages tab calls it an error and
says containerlab will not deploy it (error; the live pass of §7.4 verifies the deploy behaviour); **D** = a deploy
cannot use it but neither `validate` nor the manager refuses it (warning, with the consequence in the sentence);
**S** = the schema says so and the binary was not probed (warning when the schema alone is the source). `<k>` is the
key, `<n>` the node name, `<v>` the value, `<L>` a line.

| Code | Where | Rule | Severity | Wording (one example) |
|---|---|---|---|---|
| `shape` (R0) | root, `topology`, `nodes`, `links` | The shape rules `yamlFlaw` already applies; repeated here so the list and the status line agree. The panel suppresses the list item when the status line shows the same blocking error. | error (M) | as `yamlFlaw` |
| `unknown-key` (R1) | every map the schema closes (`additionalProperties: false`): root, `mgmt`, `settings`, `topology`, each node, `defaults`, each `kinds` entry, each `groups` entry, `stages`, each stage, each `wait-for` entry, each `exec` entry, `healthcheck`, `dns`, `certificate`, `config`, `extras`, each long-form link, each long-form endpoint | A key the level does not list. Suggestion: the listed key with Damerau-Levenshtein distance ≤ 2, or the one that differs only in `-`/`_`/case. | error when `exact` (P), else warning | *Line 7: `imge` is not a device setting containerlab 0.79.0 knows. Did you mean `image`?* / *Line 2: `foo` is not a top-level section (name, prefix, mgmt, topology, settings, debug).* |
| `kind-missing` (R2a) | each node, after inheritance (`node → group → kind section → defaults`, the order `parse_definition` uses) | No `kind` resolves. | error (P, M) | *Line 4: `vrt` has no kind. Add `kind:` to the device (or to topology.defaults).* |
| `kind-unknown` (R2b) | the resolved `kind` | Not in the schema's `kind` enum and not in `BUILDER_KIND_ALIASES` (the aliases 0.79.0 printed in §0: `^vr-` plus `ceos`, `srl`, `xrd`, `cvx`, `cumulus_cvx`, `crpd`, `cjunosevolved`, `c8000`; a constant with its source line). Suggestion as R1. | error when `exact` (P), else warning | *Line 5: containerlab 0.79.0 knows no kind `juniper_vjunos_switch`. Did you mean `juniper_vjunosswitch`?* |
| `kind-alias` (R2c) | the resolved `kind` | An alias (`vr-xrv9k`, `ceos`, `srl`): accepted, named once. | warning | *Line 5: `vr-xrv9k` is an old name containerlab still accepts; the current name is `cisco_xrv9k`.* (the current name from `inventory.ALIASES` mirrored in the constant where known, else the sentence ends after "accepts") |
| `image-missing` (R3) | each node, after inheritance | No `image` resolves and the kind is not in `BUILDER_NO_IMAGE_KINDS = {bridge, ovs-bridge, host, ext-container}`. | warning (D) | *Line 4: `vsw` has no image. containerlab needs one to create the container; the deploy fails without it.* |
| `enum` (R4) | `restart-policy`, `image-pull-policy`, `runtime`, the stage names (keys of `stages`), `phase`, and `type` where the schema's `if kind … then type enum` applies (nokia_srlinux, nokia_sros, nokia_srsim, cisco_iol) | Value outside the enum. Suggestion as R1. | error when `exact` (P for stage names), else warning; `type` enums: warning (S) | *Line 9: `boot` is not a stage. The stages are create, create-links, configure, healthy and exit.* |
| `wait-stage` (R4b) | `wait-for[].stage` | Outside the five stages, or missing. | warning (D; `validate` accepts `ready` and a missing stage, the wait then has nothing to complete) | *Line 12: `ready` is not a stage, so this wait may never end. Use create, create-links, configure, healthy or exit.* / *Line 11: this wait-for entry has no `stage:`.* |
| `type` (R5) | every scalar or collection the schema types | Wrong YAML type for the key (`env` as a list, `ports` as a map, a quoted number where `type: number`, a map where a string is expected). | error (P: the Go unmarshaller refuses type mismatches; `env` proven) | *Line 7: `env` must be a mapping of NAME: value, not a list.* |
| `pattern-hard` (R6a) | `name`, `prefix`, node names (`^[a-zA-Z0-9][a-zA-Z0-9-._|]*$`), `ports[]` | The schema pattern fails. | error (M for names, P for ports) | *Line 1: the lab name `my lab` can only use letters, digits, dot, dash and underscore.* / *Line 8: `abc` is not a port mapping (host:container, e.g. 8080:80).* |
| `pattern-soft` (R6b) | `network-mode`, `mgmt-ipv4/6`, `shm-size`, link `mac`, `ipv4`/`ipv6`, `mgmt.ipv4-subnet` and the other mgmt patterns | The schema pattern fails. | warning (S; `network-mode: bogus` passed `validate`) | *Line 6: `bogus` is not a network mode containerlab documents (host, none, container:<name>); Docker refuses it when the lab is deployed.* |
| `binds` (R6c) | `binds[]` | Not a string, or a string without `:`. | error (P for a number) / warning (S) | *Line 8: a bind is `host-path:container-path[:ro]`; `1` is not one.* |
| `link-brief` (R7a) | a link without `type` | `endpoints` missing, not two items, an item not `node:interface`, the two items equal. | error (P) | *Line 14: a link needs exactly two endpoints as `device:interface`.* |
| `link-type` (R7b) | a link with `type` | `type` outside veth, veth-stitch, mgmt-net, host, macvlan, vxlan, vxlan-stitch, dummy; a required key of that form missing (`endpoint`, `host-interface`, `remote`, `vni`, `dst-port` per form); a key the form does not take (R1 at that level). | error when `exact` (P/S), else warning | *Line 16: a `host` link needs `endpoint` and `host-interface`.* |
| `link-node` (R7c) | each endpoint `node` (brief `node:iface` or long `node:`), except `host`, `mgmt-net`, `macvlan`, `vxlan`, `vxlan-stitch`, `dummy`, `bridge` | Not in `topology.nodes`. | error (P: `Unable to find node zz`) | *Line 15: the link endpoint `zz` is not a device in topology.nodes.* (the existing `checkYaml` warning stays the panel's non-blocking status word; the list carries this error; §4.1 says how the two agree) |
| `link-duplicate` (R7d) | all endpoints | The same `node:interface` used twice in the lab. | warning (S) | *Line 17: `vsw:ge-0/0/0` is already used by the link on line 14.* |
| `wait-node` (R8a) | each effective `wait-for` entry (own and inherited) | `node` not in `topology.nodes`. | error (U) | *Line 12: There is no node named `vws`. Did you mean `vsw`?* |
| `wait-self` (R8b) | same | `node` equals the waiting node (also through `defaults`/`kinds`/`groups`). | error (U) | *Line 12: A node cannot wait for itself (`vsw` waits for `vsw` through topology.defaults).* |
| `wait-loop` (R8c) | the whole graph (edges `waiting → waited-for`, whatever the stages; upstream's `findWaitForCycle`) | A cycle. Reported once per cycle at the first entry of the cycle in text order. | error (U) | *Line 12: Nodes wait for each other in a loop (vsw → vrt → vsw). containerlab will not deploy the lab.* |
| `wait-health` (R8d) | `wait-for … stage: healthy` | The waited-for node's kind is in `BUILDER_NO_HEALTHCHECK_KINDS = {arista_ceos, ceos, juniper_cjunosevolved, cjunosevolved, linux}` and it has no `healthcheck:` key (own or inherited). | warning (D, from §0's `docker ps`) | *Line 13: `ceos` has no health check, so it never reports healthy and this wait never ends. Wait for `create-links` or `configure` instead, or give `ceos` a `healthcheck:`.* |
| `exec-form` (R9a) | `stages.<stage>.exec` | A mapping (`on-enter:`/`on-exit:`) instead of a list. | error (P: refused by 0.79.0 although its schema allows it) | *Line 10: containerlab 0.79.0 reads stage commands as a list of `- command: …` entries (with `phase: on-enter` or `on-exit` and `target: container` or `host`), not as on-enter/on-exit sections.* |
| `exec-entry` (R9b) | each `exec[]` item | Not a mapping, or without `command` (a string). `phase` outside on-enter/on-exit, `target` outside container/host. | error (P) for the shape; warning (S) for the values | *Line 11: each stage command is a mapping with `command:`; `ls -l` on its own is not one.* |
| `wait-extra` (R9c) | each `wait-for[]` item | A key other than `node`, `stage` (R1 at that level, named here because `until` is upstream's UI word). | error when `exact` (P) | *Line 13: a wait-for entry has `node` and `stage` only; `until` is not a setting.* |
| `nodes-empty` | `topology.nodes` | Empty or null (the blank canvas). | not reported in the panel (the review says *Add at least one device before saving*); the bar note never counts it | — |

Not checked, on purpose: the `ipv4`/`ipv6` of `mgmt-ipv4` against the `mgmt` subnet (containerlab's own job), image
names (the background image check of 1.30.54 covers them), `startup-config` paths (relative to the lab folder on the
VM; the browser cannot see it), the kind-specific `type` patterns of SR OS (`anyOf` with a 400-character regex;
reported only as a warning when the enum branch fails and the pattern branch fails too), `labels`/`env` value types
beyond "mapping", and anything under `settings.certificate-authority` beyond R1.

Walker details that matter: `$ref` resolves local definitions only (any other `$ref` is skipped, never fetched);
`anyOf`/`oneOf` are decided by a discriminator where the design names one (links by `type`; `exec` by list-vs-map;
`debug` null-or-boolean) and otherwise by "the first branch whose `type` matches, else the first branch", so the
message names that branch's problem instead of "matches no form"; `if`/`then` is evaluated only for the `kind`
condition the schema uses; `patternProperties` keys compile once; a `pattern` compiles with the `u` flag only when it
contains `\p{`, otherwise without, and a pattern that fails to compile disables that one check (counted in a
`builderCheckSelfTest()` the tests call, which must report zero failed patterns for the vendored schema); `uniqueItems`
compares `JSON.stringify` of the items; `minItems`/`maxItems`/`minimum`/`maximum`/`minLength`/`minProperties` are
reported as warnings with the limit in the sentence. The validator never reads the schema's `markdownDescription`
except for the key help's URL (§4.3).

## 4. The UI (`lab-builder-yaml.js`, `lab-builder-page.js`, `lab-builder.html`, `lab-builder.css`)

### 4.1 The Problems list under the editor

Below `#builder-yaml-status` the panel gains:

```html
<section class="builder-yaml-problems" id="builder-yaml-problems" aria-labelledby="builder-yaml-problems-title">
 <h3 id="builder-yaml-problems-title" class="builder-yaml-problems-title">Problems <span id="builder-yaml-count" role="status" aria-live="polite"></span></h3>
 <ol id="builder-yaml-list" class="builder-yaml-list"></ol>
 <p id="builder-yaml-schema" class="form-help builder-yaml-schema"></p>
</section>
```

- `builderYamlValidate()` (today: `checkYaml`, 400 ms after the last keystroke) becomes: `flaw = checkYaml(text)`; if
  `flaw.severity === 'error'` the status line shows it as today and the list is emptied (the text has no tree);
  otherwise `located = locateYaml(text)`, `list = builderCheck(located.tree, schema, context)` and the list renders.
  The `checkYaml` **warning** (an endpoint naming an unknown device) no longer goes to the status line while the list
  is active: the list carries it as `link-node`. The status line keeps the state words (*Edited · not applied*,
  *Applied*, …) and the blocking errors only. Also run once when the panel opens (on the engine's text) and after every
  Apply and Revert, so a text that came from the canvas is checked too.
- Each item is `<li class="is-error|is-warning"><button type="button" class="builder-yaml-problem" data-line="12">
  <span class="builder-yaml-sev">Error</span> Line 12: …</button></li>`; activating it calls `builderYamlGoto(line)`
  (the existing caret mover). The severity word is text, not colour alone. Errors first within a line; the list is
  `max-height` 30 % of the panel with its own scroll, `tabindex` on the `<ol>` when it scrolls.
- `#builder-yaml-count` reads *2 errors, 1 warning* / *1 warning* / *No problems found* (from `builderCheckSummary`)
  and is updated only when the text of the summary changes, so the live region speaks once per real change and never
  on a keystroke that changed nothing. While the schema loads it reads *Checking…* once.
- `#builder-yaml-schema` is the caption of §2.3; with `exact` false it is also the first sentence a screen reader
  meets after the count, so the downgrade is never silent.
- The textarea's `aria-invalid` is `true` while the list has an error or the status line shows a blocking one
  (today: blocking only); `aria-describedby` gains `builder-yaml-count`.
- Apply and Revert are untouched (decision 4). After an Apply with errors still listed the status line reads *Applied
  · 2 problems remain* (tone `warn`), so the list's persistence is explained.

### 4.2 The gutter

`builderYamlGutter()` builds the gutter as `<span class="builder-yaml-line">N</span>` per line (numbers only, no
student text, so no `esc()` is needed but the markup is still built through `textContent` per span, never
`innerHTML` of interpolated text: the file keeps its "no innerHTML" pin by using `replaceChildren` with created
elements). A line with a finding gets `is-error` or `is-warning` (error wins) and a `title` with the first message;
the gutter stays `aria-hidden` (the list is the accessible form). Marks are refreshed with the list and cleared when
the text changes before the next validation lands (stale marks never point at moved lines).

### 4.3 Key help on the caret

A `<p id="builder-yaml-keyhelp" class="form-help builder-yaml-keyhelp" aria-live="off"></p>` under the list. On
`selectionchange` (document-level in `shell.js`? No: the builder page has no `shell.js`; the panel binds
`document.addEventListener('selectionchange', …)` itself behind a `typeof document` guard, as the page already binds
`DOMContentLoaded`) and on `keyup`/`click` in the textarea, throttled to 150 ms, `builderKeyHelp(tree, schema, line)`
finds the key on the caret's line (`^\s*(?:- )?([\w.-]+):`), resolves its level by walking the located tree for the
map whose entry has `keyLine === line`, and shows *`startup-config` · path to a startup config file (if supported by
the kind). [More]* where *More* is `<a href="https://containerlab.dev/manual/nodes/#startup-config" target="_blank"
rel="noopener">More</a>` taken from the first `(https://containerlab.dev/…)` in the key's `markdownDescription`
(only that host; anything else drops the link). A line without a known key clears the help. It is `aria-live="off"`:
a caret move is not an event to announce; the text is read when focus or the virtual cursor reaches it. Not shown
while the schema is absent.

### 4.4 The bar note on the stored draft (`lab-builder-page.js`)

`persist()` already debounces the image check (`builderImageStatus`, 1.2 s). The same hook runs
`builderCheckStatus()`: if the schema is loaded (the page asks the panel's loader `builderYamlSchema()` and never
fetches itself), `locateYaml(draft.yaml)` through the attached editor and `builderCheck` on it; errors only. The
note is a line under the bar in the style of `#builder-images` (`<div id="builder-check" role="status" hidden>`),
one sentence: *1 setting containerlab 0.79.0 will refuse: line 7, `imge` is not a device setting. Open YAML to see
it.* with a **Show in YAML** button (opens the panel, moves the caret) and **Dismiss** (remembered by draft, text and
count like `builderImageKey`). It never changes `builderBlocked()`: Save stays on (decision 4); the review's own
refusals and containerlab's deploy output remain the hard stops. With `exact` false the note is not shown at all
(warnings do not earn a bar line).

### 4.5 The stage example in the help

The panel's help paragraph gains a `<details class="builder-yaml-example"><summary>Boot order: start the router
after the switch is healthy (stages)</summary>…</details>` with the sentence *On a VM with little memory, start one
VM-based device at a time: the router's container is created only when the switch reports healthy. `healthy` works
for devices with a health check (vJunos-switch, vJunos-router, XRv9k); for cEOS or cJunosEvolved wait for
`create-links` instead.* and the example (verified in §0):

```yaml
name: juniper-pair
topology:
  nodes:
    vsw:
      kind: juniper_vjunosswitch
      image: n24l/vjunos-switch:23.2R1.14
    vrt:
      kind: juniper_vjunosrouter
      image: n24l/juniper_vjunos-router:26.2R1.7
      stages:
        create:
          wait-for:
            - node: vsw
              stage: healthy
  links:
    - endpoints: ["vsw:ge-0/0/0", "vrt:ge-0/0/0"]
```

A **Copy example** button (`copyButton` from `clipboard.js`, present when the script loaded, otherwise the button is
absent as C02 decided). Nothing is inserted into the text automatically.

### 4.6 States

Default: the list reads *No problems found* under a valid text, the caption names the schema. Loading: *Checking…*
once, the status line and Apply unaffected. Empty text: the shape error in the status line, list cleared. Error
(fetch): the one sentence with *Try again*. Disabled: never; the panel is read-only before the editor attaches as
today, and the list is then empty with no caption. Narrow (≤ 900 px): the panel is the lower 55 % as today; the list
takes at most 30 % of the panel and scrolls inside; nothing scrolls sideways (`overflow-wrap: anywhere` on items). The
list, its buttons, *Try again*, *More*, *Copy example*, *Show in YAML* and *Dismiss* are all reachable with Tab in
reading order; Escape keeps its meaning (closes a clean panel only).

## 5. The vendored schema, its licence and its refresh

Files (new):

- `clab-backup-ui/app/static/clab-schema/0.79.0.json`: the upstream file verbatim (digest §0).
- `clab-backup-ui/app/static/clab-schema/LICENSE`: containerlab's `LICENSE` at the same tag (BSD-3-Clause, Nokia).
- `clab-backup-ui/app/static/clab-schema/SOURCES.txt`: one line per file: `0.79.0.json  v0.79.0
  https://raw.githubusercontent.com/srl-labs/containerlab/v0.79.0/schemas/clab.schema.json  sha256 51a70250…f58d02
  fetched 2026-10-23`.
- `clab-backup-ui/lab-builder/fetch-schema.mjs <tag>` (Node, like upstream's `sync-clab-schema.mjs`): downloads the
  tag's schema and `LICENSE`, checks `$id === 'https://containerlab.dev/clab.schema.json'`, `type === 'object'` and
  `definitions['node-config']`, writes `app/static/clab-schema/<version>.json` (version = tag without `v`), rewrites
  `SOURCES.txt`, prints the digest, and reminds the maintainer to add the version to `BUILDER_SCHEMA_VERSIONS` and
  to run the tests. It lives in the build project because that is where Node is expected; it never runs on a VM.

Why `app/static/clab-schema/` and not under `app/static/lab-builder/`: `build.mjs` deletes and regenerates that
folder on every rebuild. Why not bundled into `main.js`: a schema refresh would then need Node 24, `npm ci` and a
bundle rebuild, and the bundle is cached `immutable` so it would wait for a release anyway; a static JSON is served
`no-store` (`main.py:136`) and reaches the browser at the next page load. `verify-release.py` checks `?v=` only on
`/static/…` references inside the HTML pages; the fetch URL in the script carries none and needs none.

Licence record: `deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md` gains a row *containerlab topology schema
(`schemas/clab.schema.json`) · validation and key help in the YAML panel · BSD-3-Clause (`LICENSE` beside the file) ·
No (verbatim per release, `SOURCES.txt`)*; `docs/LAB-BUILDER.md` "Third-party software" names it in one sentence.

Threats a reviewer will raise, answered here: the file is data, never executed (`JSON.parse` after a same-origin
fetch; `script-src 'self'` unchanged); a tampered checkout changes the digest the stdlib test pins; the walker never
follows a non-local `$ref` and never fetches anything but the vendored path built from a version that matched
`^\d+\.\d+\.\d+$` against the hard-coded list (the VM's version string never becomes part of a URL: the list entry
does); the publish path is untouched (`host_operations.py` `plan`, `publish`, `revise`, `builder_texts` unchanged;
`test_lab_operations.py` keeps every publish and revise test byte for byte).

## 6. Tests and documentation

### 6.1 Tests

- `tests/test_lab_builder_check_ui.js` (new; `node:test`, loads `lab-builder-check.js` in a bare context like
  `test_lab_builder_yaml_ui.js` loads the panel, and reads the vendored `0.79.0.json` from disk). Test helper
  `located(value)`: a depth-first walk of a plain object that assigns increasing line numbers to every key and item
  in the order a block YAML would print them, so a test states a topology as an object literal and asserts the line
  of a finding from the same walk. Cases, one per rule of §3 with the exact wording pinned: unknown key with and
  without a suggestion at every closed level; `exact` true → error, false → warning (same tree); kind missing,
  unknown with suggestion, inherited through `group`, `kinds`, `defaults`; the eight aliases accepted with the
  warning; image missing for `juniper_vjunosswitch` and not for `bridge`; every enum; the five stage names and
  `boot`; `wait-for` `ready` and a missing `stage`; `env` as a list; the four hard patterns and three soft ones; the
  `ports` strings `8080:80`, `127.0.0.1:2201:22/tcp`, `abc`; brief links with one, two, three endpoints; every long
  link form's required keys; an unknown endpoint, `host:eth1` and `mgmt-net:x` accepted; a duplicate endpoint; the
  wait graph: unknown target, self, inherited self through `defaults`, a two-node loop, a three-node loop reported
  once, no loop in a chain; `healthy` on `ceos` without and with `healthcheck`; the exec object form, a string
  entry, a list entry without `phase` (accepted), `phase: later` (warning); `until`; the 200-item cap; the summary
  text for 0/1/2 errors and warnings; `builderSchemaChoice` for every row of §2.3 and for `'0.79'`, `''`, `'dev'`;
  `builderKeyHelp` for a node key, a nested `wait-for` key, a line without a key, and a `markdownDescription` whose
  link is not containerlab.dev (no link); `builderCheckSelfTest()` reports zero failed patterns for the vendored
  schema; the §4.5 example yields an empty list; the tree of a text whose root is a list yields R0 only. A final
  test asserts the script declares no top-level name the other builder scripts declare (the `test_page_load_ui.js`
  rule, checked locally too).
- `tests/test_clab_schema.py` (new; stdlib only, so it can run in the first CI group): every file named in
  `SOURCES.txt` exists with the stated SHA-256; every `*.json` in the folder is in `SOURCES.txt`; each parses, has the
  `$id`, `definitions.node-config` and `properties.topology`; `LICENSE` exists and contains "Redistribution and use";
  `BUILDER_SCHEMA_VERSIONS` in `lab-builder-check.js` equals the set of files (read by regex); `fetch-schema.mjs`
  exists, names the raw URL pattern and never writes outside `app/static/clab-schema/`.
- `tests/test_lab_builder_yaml_ui.js` (extended): the markup has the new ids and `role="status"` on the count only;
  a validation with a fake `locateYaml` renders items with the severity word, the line and `data-line`, and clicking
  one moves the caret; the count changes once per summary change (two validations with the same summary → one
  `textContent` write); the `checkYaml` warning leaves the status line while the list is active; an error in
  `checkYaml` empties the list; Apply with findings succeeds and reads *Applied · 2 problems remain*; the gutter marks
  the lines and clears on the next keystroke; the schema caption for `exact` true and false; the failed fetch sentence
  and *Try again*; the context upgrade when capabilities arrive late; the key help for a caret line (fake tree);
  the example `<details>` exists with the §4.5 text and a Copy button only when `copyButton` is defined; the bundle
  test adds `locateYaml` to the names the committed `main.js` must contain; the "no innerHTML" pin is kept.
- `tests/test_lab_builder_ui.js` (extended): `builderCheckStatus` renders the bar note for one error, hides it for
  warnings only and when `exact` is false, remembers a dismissal per draft and text, and never changes
  `builderBlocked()`; *Show in YAML* calls the panel toggle and the goto.
- Bundle: `node build.mjs` then `node build.mjs --check` (Node 24) after the adapter change; CI's rebuild step compares.
- Fixture smoke (`clab-ui-qa`, `fixture_manager.py` already answers `containerlab: '0.79.0'`):
  `student_workflow.py` gains, after its existing YAML check: open YAML, paste the §4.5 example with `vsw` misspelt in
  the `wait-for` and `imge:` on a node, wait for the list, assert two items with their lines and the caption
  *the version on this VM*, click the first item and assert the caret line, correct both, assert *No problems found*,
  Apply, assert *Applied*; assert the gutter class and that the bar note appeared and went; Tab from the textarea
  reaches the first problem button; `securitypolicyviolation` stays empty (the schema fetch is same-origin). Viewports
  1440 and 760 (the panel's two layouts); the Problems list never scrolls the page sideways.
- CI: the lead appends `tests/test_lab_builder_check_ui.js` to the `node --test` line and `test_clab_schema.py` to
  the stdlib group (`-p test_clab_schema.py`).

### 6.2 Documentation

`docs/LAB-BUILDER.md` "Edit the topology as YAML" gains a subsection **What the panel checks**: one paragraph that the
text is checked against the containerlab schema of the VM's release (the manager carries the schema for the releases
named in its `SOURCES.txt`; when the VM's release is newer, unknown settings are warnings, and the caption says so);
a short list of what is reported (unknown or misspelt settings with a suggestion, a missing or unknown kind, a
missing image, wrong value types, link endpoints, boot-order problems: a wait for a node that does not exist, a node
waiting for itself, nodes waiting in a loop, a wait for `healthy` on a device without a health check); that problems
never stop Apply or Save ("the review and the deploy keep their own refusals; containerlab's own message names the
line"); the key help on the caret with its *More* link; and a subsection **Boot order (stages)** with the §4.5
example and its sentence about memory. "Limits of this version" replaces "editable YAML" (already gone) with: *No
completion while typing: the key on the caret line shows its help; completion and hover as in a code editor come with
the editor upgrade.* "Third-party software" gains the schema sentence. The maintainer paragraph gets the refresh
recipe: `node fetch-schema.mjs v0.80.0` in `clab-backup-ui/lab-builder/`, add the version to
`BUILDER_SCHEMA_VERSIONS`, run `test_clab_schema.py` and `test_lab_builder_check_ui.js` (its self-test must still
report zero failed patterns), and record the release in `SOURCES.txt`. `deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md` as
in §5. `docs/parity-campaign/PARITY.md` rows R071 and R072: the lead moves them to *partial* / *present (interim)*
with the C11 remainder named (completion, hover, the Stages tab, wait-for arrows). Release records: the lead.

## 7. Assumptions, dead ends removed, refusals, what to attack, the live pass

### 7.1 Assumptions

- `builderCaps.containerlab` is the string C03's `capabilities` returns (`'0.79.0'`, kept only when it matches
  `^\d+\.\d+\.\d+`); an older helper has no key and the panel takes the "unknown" row.
- The `yaml` library's `LineCounter` gives the line of a node's first character (the pattern `yamlFlaw` uses today);
  a flow mapping on one line gives every key the same line, which is correct.
- The Go unmarshaller refuses every unknown key and every type mismatch at the levels §0 probed; levels not probed
  (`healthcheck`, `dns`, `certificate`, long-form endpoints) are assumed to behave the same because they are the same
  `KnownFields(true)` decoder (the error text names Go types for each). The live pass probes two of them.
- `deploy` refuses a wait-for loop and an unknown wait-for target (upstream's statement); until §7.4 proves it the
  wording "containerlab will not deploy the lab" is upstream's, not this session's.
- The `vr-*` aliases map to the kinds `inventory.ALIASES` names; aliases it does not name are reported without a
  current name.

### 7.2 Dead ends removed, refusals

Removed: a topology with a misspelt key that opens fine, saves fine and fails at deploy with `field imge not found in
type types.NodeDefinitionWithDeprecatedFields` in the operation output; a `wait-for` that names a node that does not
exist and makes the deploy wait for ever (nothing on the VM reports it: `validate` and `--dry-run` both pass it); two
VM-based nodes booting at once on a VM with memory for one; a wait for `healthy` on a cEOS that never becomes healthy;
"which keys does a node take" answered only by leaving the manager for containerlab.dev.

Refusals kept, each with its wording: Apply on a text the engine cannot draw (`yamlFlaw`, unchanged); the review's
*Add at least one device before saving* and *The manager cannot read this topology*; the helper's `publish`/`revise`
rules (unchanged). New refusals: none. The check adds no refusal anywhere; its findings are advisory by decision 4.

### 7.3 What to attack

`risk-reviewer`: the vendored file's provenance (digest, tag, the fetch script's checks: can a refresh accept a file
that is not containerlab's schema?); that the validator is data-driven and the schema is data (no `eval`, no
`Function`, no regex built from student text: patterns come from the schema only, and student text is only ever the
subject of `RegExp.test`); the regex set (26 patterns compiled from the schema: catastrophic backtracking on a crafted
scalar? The SR OS `type` pattern is the longest; the walker caps a tested scalar at 1,024 characters and reports a
longer one as "too long to check" instead of testing it); the URL built for the fetch (the version comes from the
hard-coded list, never from the VM's string); the `More` link host check; that the publish path is untouched and that
no finding ever reaches the manager (nothing is posted; the bar note is local); the 200-item cap and the 1 MiB text
cap against a tree that nests 10,000 levels (the walker is iterative or depth-capped at 64 with one finding).

`clab-ui-reviewer`: the severity table (is a warning ever shown where the student will be refused, or an error where
containerlab would accept the text?); the downgrade when the VM is newer (does a student on 0.81 understand why a
valid key is a warning?); the three surfaces (list, gutter, bar note) saying the same thing in three words; the count
live region's chatter; the caret help's `aria-live="off"`; the `checkYaml` warning moving from the status line to
the list (does the status line still explain why Apply is on?); *Applied · 2 problems remain* against the existing
*Applied · newer edits not applied*; the example's Copy against a student who expects Insert; the 760 px layout with
a long list; the lost-functionality check against `docs/redesign/inventory` (nothing of the panel's today is removed).

### 7.4 The live pass

Measure first (`free -g`, `docker ps`): the `parity` lab is the lead's and stays up; a second lab needs about 10 GB
for the Juniper pair (the router on the local nested image `local/juniper_vjunos-router:26.2R1.7-nested`, C00). Only
if at least 20 GB are available and the lead assigns the lab: publish the §4.5 example through the builder (Save to
the VM, the reviewed `publish`), deploy it from the manager, and record from `docker ps` timestamps that `clab-<lab>-vrt`
was created after `clab-<lab>-vsw` turned `(healthy)`; then destroy it. Otherwise the evidence is the dry run of §0
(repeatable: `containerlab deploy --dry-run -t <file>` on the saved file, read-only) plus `containerlab validate`.
In either case, two cheap read-only probes close §7.1's assumptions: `containerlab validate` on a `healthcheck: {foo:
1}` and on a long-form endpoint with an extra key (expected: both refused). The deploy behaviour on a loop needs a
real deploy; a two-node cEOS loop lab (about 4 GB, no healthcheck, `wait-for … create`) is the cheapest proof and is
done only with the lead's assignment, destroyed afterwards, evidence to `docs/parity-campaign/evidence/c08-live.md`.

## 8. Slices (disjoint files), owners, sizes, acceptance

Contract between the slices: §2.1 (the located tree) and §2.2 (the diagnostics). S2 and S3 build against hand-made
trees and fake handles, so all four can run in parallel; S3 integrates with S1's bundle at the end.

| Slice | Files | Owner (proposal) | Size | Acceptance |
|---|---|---|---|---|
| **S1 adapter**: `locateYaml` on the `YamlEditorHandle`; bundle rebuild | `clab-backup-ui/lab-builder/src/main.tsx`; `clab-backup-ui/app/static/lab-builder/**` (regenerated); no `patches.mjs` change | `clab-editor-specialist` | S (about 30 lines of TypeScript) | `node build.mjs` then `node build.mjs --check` exit 0 with Node 24; the committed `main.js` contains `locateYaml`; the tree of the §4.5 example has `topology.nodes.vrt.stages.create['wait-for'][0].node` at line 13; a flow map gives one line to its keys; a parse error returns `{error}` equal to `checkYaml`'s; `checkYaml`, `applyYaml`, `MAP_COMMANDS`, `disabledTabIds` unchanged (`test_lab_builder_yaml_ui.js` bundle test and `test_lab_builder_ui.js` "every editor control the page hides still exists" pass) |
| **S2 validator and schema**: the walker, the rules, the choice, the key help, the self-test; the vendored schema with licence, sources and fetch script; their tests | `clab-backup-ui/app/static/lab-builder-check.js` (new); `clab-backup-ui/app/static/clab-schema/{0.79.0.json,LICENSE,SOURCES.txt}` (new); `clab-backup-ui/lab-builder/fetch-schema.mjs` (new); `clab-backup-ui/tests/test_lab_builder_check_ui.js` (new); `clab-backup-ui/tests/test_clab_schema.py` (new) | `clab-fable-specialist` (the rule table has many edges) or `clab-opus-specialist`; `risk-reviewer` on the diff | L (about 350 lines of script, 300 of tests) | `node --test tests/test_lab_builder_check_ui.js` and the stdlib test exit 0; `node --check` on the script; every §3 wording pinned; the self-test reports 0 failed patterns; `sha256sum 0.79.0.json` equals §0; the script loads in a bare `vm` context (no `document`, no `fetch`); no top-level name clashes with the other builder scripts |
| **S3 panel and page wiring**: the list, the gutter marks, the count, the caption, the schema fetch and context, the caret help, the example with Copy, the bar note; CSS; the script tag | `clab-backup-ui/app/static/lab-builder-yaml.js`, `lab-builder-page.js`, `lab-builder.html` (the `<script src="/static/lab-builder-check.js?v=…">` after `lab-builder-yaml.js`; the release owner moves the number), `lab-builder.css`; `clab-backup-ui/tests/test_lab_builder_yaml_ui.js`, `test_lab_builder_ui.js` (extended) | `clab-ui-builder`; `clab-ui-reviewer` on the slice | M (about 150 lines of script, 30 of CSS, 150 of tests) | both test files exit 0; `node --check` on both scripts; `test_page_load_ui.js` exit 0 (`lab-builder.html` loads every script in one context); no `innerHTML` in `lab-builder-yaml.js`; no inline style; every §4 state reachable with a fake `locateYaml` and a fake `fetch`; `map-editor.html` unchanged |
| **S4 docs and fixture smoke** | `docs/LAB-BUILDER.md`, `deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md`, `docs/lab-builder/tools/student_workflow.py` | `docs-auditor` (docs), `clab-ui-qa` (the smoke) | S | `python3 docs/maintenance-audit/tools/check_links.py` and `python3 deploy/verify-release.py --docs` exit 0; the smoke's new checks pass at 1440 and 760 on a fresh `FIXTURE_DATA` with the rebuilt bundle; evidence under `docs/parity-campaign/evidence/` |

Lead only: the release number (the bundle is cached `immutable`, so the chunk is a release), the `?v=` on the new
script tag, the two CI list entries, `PARITY.md` rows, the three history files, the live pass assignment.

**Lead's decisions on the open questions:** (1) a wait-for loop and an unknown wait-for target are errors with upstream's
wording ("containerlab's deploy refuses this"); the live pass proves it on a disposable two-cEOS loop lab under the lead's
assignment (memory measured first), otherwise the wording stands as upstream's and VALIDATION says so; (2) the Juniper
pair live pass is conditional on 20 GB available beside the parity lab, with the dry run as the fallback evidence;
(3) S2 goes to `clab-opus-specialist` with `clab-ui-reviewer` on the panel and `risk-reviewer` on the vendored schema;
(4) a read-only `validate` helper mode is not pursued in this campaign (noted for a later chunk).

## 9. Review answers

One row per confirmed finding of `/clab-design-review` (risk R…, UI U…); refuted findings need no row.

| Finding | Answer | Where |
|---|---|---|
| | | |
