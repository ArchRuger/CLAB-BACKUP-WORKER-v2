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
   (`lab-builder/fetch-schema.mjs <tag>`), never a hand edit: the maintainer names the expected digest (or a commit SHA) and the
   script refuses anything else; the stdlib test carries every digest as a literal of its own (§5). Verbatim beats a
   pruned extract: a reviewer can `sha256sum` it against upstream, and nothing of ours can drift inside it. The browser
   fetches it once per page load (105 KB, `no-store` like every static file outside the bundle), the first time a
   check needs it: the panel's first validation, or the bar note's first run after a stored change (§4.4), so a student
   who never opens YAML downloads it once and still gets the note; the rules that need no schema run before it arrives.
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
   the builder bar on the stored draft, so a student who never opens the panel still learns before saving. The bar
   note's check runs only inside its own debounced timer, never synchronously in `persist()`, and a throw inside it
   hides the note and nothing else (§4.4): an advisory check can never pause the builder. The manager's review and
   containerlab at deploy keep their own refusals. The panel says in one fixed sentence that the list stops neither
   Apply nor Save (§4.1).
5. **Unknown keys and enum values are errors only when the vendored schema matches the VM's version exactly** (full string
   equality of a `^\d+\.\d+\.\d+$` version; `0.79.0-rc1` is never exact) **and at a level §0 probed.** There the
   binary provably refuses them; a level not yet probed, a key the binary accepts although the schema omits it, and a
   renamed key it still accepts are warnings by per-version tables beside the schema (§3). When the VM's version is newer than every vendored schema,
   unknown, or older than the oldest, the same findings are warnings and the caption names both versions (§2.3): a
   key added in 0.81 must not be called an error on a 0.81 VM because the manager carries 0.79.
6. **The adapter gives the panel a located tree; it does not validate.** `main.tsx` gains one handle method,
   `locateYaml(text)`, that turns the `yaml` library's document into a plain tree with a line per node (§2.1). One
   parser for the whole page (no second YAML parser in plain JavaScript), and the validator stays a pure function of
   plain data that `node:test` exercises without the bundle, without `lab-builder/node_modules`, and without a browser.
   `checkYaml` and `applyYaml` are unchanged (pinned by `test_lab_builder_yaml_ui.js`).
7. **Stage validation follows upstream's wording and adds inheritance.** "There is no device named X", "A device cannot
   wait for itself", "Devices wait for each other in a loop (a → b → a). containerlab will not deploy the lab." are the
   upstream sentences (`StagesTab.tsx`) with "node" read as "device", the manager's word everywhere else. The graph includes the `wait-for` entries containerlab adds from
   `topology.defaults`, `kinds` and `groups` (so a `defaults` entry naming node `a` is a self-wait on `a`), and each
   finding points at the line of the entry that causes it.
8. **Hover becomes key help on the caret; completion is deferred to C11 with the reason.** A textarea has no token
   hover, but it has a caret: the help line under the list shows the schema `description` of the key on the caret's
   line, resolved by indentation, with a *More about `<key>`* link to the containerlab.dev page the schema's
   `markdownDescription` names (an external link, no asset). A completion popup over a textarea (positioning, keyboard, screen reader,
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
is bounded by the text size (`BUILDER_DROP_LIMIT` 1 MiB already caps a draft), no cycles (aliases are copied), and
**depth is capped at 64 levels**: a deeper document returns `{error: {message: 'The topology nests deeper than 64
levels, which no lab file needs.', line, severity: 'error'}}` and no tree. `locateYaml` **never throws**: any exception
inside it (a `RangeError` included) becomes that `{error}` shape with the exception's first line, so a caller on the
page's persist path cannot be tripped by it (finding 0).

The panel passes `tree` to the validator together with the schema and the context; the fake editor in the tests
builds trees by hand or with the test helper of §6.

### 2.2 Diagnostics (`lab-builder-check.js` → the panel and the page)

```js
// builderCheck(tree, schema, context) → [{severity:'error'|'warning', line:number, message:string, code:string, path:string[], help?:string}]
// context: {version:'0.79.0'|'' (the VM's containerlab), schemaVersion:'0.79.0', exact:boolean, images?:string[]}
```

Pure, synchronous, no DOM, no fetch. With `schema === null` it runs the schema-free rules only (R2a, R3, R7a/c/d,
R8a–d, R9a/b of §3), so the list works before the schema arrives and when its fetch failed; sorted by line then severity (errors first on a line); at most
`BUILDER_CHECK_LIMIT = 200` items (then one closing item "… and N more"); `message` is one sentence a student can act
on, never a JSON pointer or a Go type name; `code` is a stable short word (`unknown-key`, `wait-loop`, …) for the
tests and the suppression of duplicates; `path` is the key path for the tests. `builderCheckSummary(list)` →
`{errors, warnings, text}` with `text` = "2 errors, 1 warning" / "1 warning" / "No problems found" (the count sentence
for the `role=status` element; the panel writes "No problems found" only after a real run on a tree, §4.1). `builderKeyHelp(tree, schema, line)` → `{key, path, description, url}` or null for the
key on a line (the caret help, §4.3). `builderSchemaChoice(vmVersion, available)` → `{schemaVersion, exact, reason}`
(§2.3). All four are top-level functions of the script, prefixed `builderCheck`/`builderSchema`/`builderKeyHelp`, so
`test_page_load_ui.js` (which loads every builder script in one context) finds no clash.

### 2.3 Which schema, and what the mismatch means

`BUILDER_SCHEMA_VERSIONS = ['0.79.0']` in `lab-builder-check.js` lists the vendored files; the stdlib test of §6 pins
the list to the files present. `builderSchemaChoice(vm, list)`:

| VM version (`builderCaps.containerlab`, from C03's `capabilities`) | Choice | `exact` | Caption under the list |
|---|---|---|---|
| equals a vendored version (the whole string, `^\d+\.\d+\.\d+$`, string equality) | that one | true | *Checked against containerlab 0.79.0, the version on this VM.* |
| newer than every vendored one | the newest vendored | false | *Checked against the containerlab 0.79.0 schema; this VM runs 0.81.0. A setting added since then is shown as a warning, not an error.* |
| between two vendored versions | the greatest vendored not above it | false | *Checked against the containerlab 0.79.0 schema; this VM runs 0.79.3.* (same patch line: findings are still warnings, because the lead has not proven the patch releases equal) |
| older than the oldest vendored | the oldest vendored | false | *Checked against the containerlab 0.79.0 schema; this VM runs 0.70.0, older than any schema the manager carries. containerlab itself reports settings it does not know when the lab is deployed.* |
| a suffixed string (`0.79.0-rc1`, `0.79.0+dev`) | the row of its numeric part, never exact | false | the row's caption with the full string (*this VM runs 0.79.0-rc1*) |
| unknown (`''`: no capabilities yet, VM away, a helper older than C03) | the newest vendored | false | *The VM's containerlab version is not known yet (not connected, or the VM's manager tools are older), so the text is checked against the containerlab 0.79.0 schema; unknown settings are shown as warnings.* |

Versions compare as three integers taken from the start of the string; `exact` needs the whole VM string to equal a
vendored version (the helper keeps a prefix match, `host_operations.py:778`, so a suffix can arrive); a string that does
not start with three integers is "unknown". `exact` makes R1 (at a probed level), R2b, R4 and R7b errors; otherwise they
are warnings. The schema file is fetched by the panel (`fetch('/static/clab-schema/' + v +
'.json')`, same origin, `connect-src 'self'`) the first time a validation needs it and kept for the page's life; a
failed fetch sets `builderYaml.schema = 'failed'` and the list shows one sentence: *The topology schema could not be
loaded from the manager, so settings and kinds are not checked; links and boot order still are.* with a *Try again*
button (the schema-free rules keep running on every text change). The choice is re-made when
`builderCaps` arrives after the panel opened (the page calls `builderYamlContext(caps)`), so a slow VM answer upgrades
the caption and the severities on the next validation without a reload.

## 3. The rules (`lab-builder-check.js`)

Evidence: **P** = `containerlab validate` refused it in §0 (parse-time refusal, error when `exact`); **M** = the
manager's review refuses it (`parse_definition`, error always); **U** = upstream's Stages tab calls it an error and
says containerlab will not deploy it (error; the live pass of §7.4 verifies the deploy behaviour); **D** = a deploy
cannot use it but neither `validate` nor the manager refuses it (warning, with the consequence in the sentence);
**S** = the schema says so and the binary was not probed (warning when the schema alone is the source). `<k>` is the
key, `<n>` the node name, `<v>` the value, `<L>` a line.

**Rule-owned paths.** The walker applies no generic keyword (`enum`, `required`, `const`, `uniqueItems`,
`additionalProperties`, `pattern`, `type`, `minItems`) at these paths; only the named rule reports there, and once:
`kind` at every level (R2), the keys of `stages` (R4), each `wait-for[]` entry and its `stage` (R4b, R8, R9c),
`stages.*.exec` and its entries (R9), every link and endpoint (R7). Outside the named rows a generic finding (a
`required` key, a `const`, `uniqueItems`, `minItems`, an `enum` R4 does not list) is a warning (S). An `exec` entry
without `phase` yields no finding at all (the binary defaults it to `on-enter`; §0 shows `validate` accepts it), and
`stage: ready` yields R4b's warning only, never the walker's `enum` error. One test per owned path asserts exactly one
finding with the rule's code and severity (findings 2 and 8).

**Per-version tables beside the schema** (constants of `lab-builder-check.js`, keyed by schema version, each entry
with its source in a comment):

- `BUILDER_SCHEMA_EXTRA_KEYS['0.79.0']`: keys the binary accepts although the schema omits them, from
  `types/node_definition.go` at `v0.79.0`: `position` (`NodeDefinition.Position`; accepted silently at node, `defaults`,
  `kinds` and `groups` level), `username` and `password` (`NodeDefinitionWithDeprecatedFields.LegacyUsername` /
  `LegacyPassword`; a warning: *Line 6: `username` is an old place for the login; containerlab still reads it, the
  current form is `credentials: {username: …, password: …}`.*). Never an R1 finding.
- `BUILDER_DEPRECATED_KEYS = {mgmt_ipv4: 'mgmt-ipv4', mgmt_ipv6: 'mgmt-ipv6', ipv4_subnet: 'ipv4-subnet', ipv6_subnet:
  'ipv6-subnet'}` (renamed in containerlab 0.41 and still read by the `…WithDeprecatedFields` decoders §0's error texts
  name): a warning, *Line 6: `mgmt_ipv4` is an old name containerlab still accepts; the current name is `mgmt-ipv4`.*,
  never an R1 error. The value is checked under the current name's rules.
- `BUILDER_PROBED_LEVELS['0.79.0']`: the closed maps where §0 proved that an unknown key is refused: the root, `mgmt`, a
  node under `nodes`, `stages`, a `wait-for` entry. R1 is an error only at a probed level with `exact`; at every other
  level (`defaults`, `kinds`, `groups`, a stage, an `exec` entry, `healthcheck`, `dns`, `certificate`, `config`,
  `extras`, `settings`, long-form links and endpoints) it is a warning until §7.4's probe of that level is recorded in
  the constant's comment and the level is added (finding 1).

| Code | Where | Rule | Severity | Wording (one example) |
|---|---|---|---|---|
| `shape` (R0) | root, `topology`, `nodes`, `links` | The shape rules `yamlFlaw` already applies; repeated here so the list and the status line agree. The panel suppresses the list item when the status line shows the same blocking error. | error (M) | as `yamlFlaw` |
| `unknown-key` (R1) | every map the schema closes (`additionalProperties: false`): root, `mgmt`, `settings`, `topology`, each node, `defaults`, each `kinds` entry, each `groups` entry, `stages`, each stage, each `wait-for` entry, each `exec` entry, `healthcheck`, `dns`, `certificate`, `config`, `extras`, each long-form link, each long-form endpoint | A key the level does not list. Suggestion: the listed key with Damerau-Levenshtein distance ≤ 2, or the one that differs only in `-`/`_`/case. | error when `exact` and the level is in `BUILDER_PROBED_LEVELS` (P), else warning; the extra and deprecated keys above come first and are never R1 | *Line 7: `imge` is not a device setting containerlab 0.79.0 knows. Did you mean `image`?* / *Line 2: `foo` is not a top-level section (name, prefix, mgmt, topology, settings, debug).* |
| `kind-missing` (R2a) | each node, after inheritance (`node → group → kind section → defaults`, the order `parse_definition` uses) | No `kind` resolves. | error (P, M) | *Line 4: `vrt` has no kind. Add `kind:` to the device (or to topology.defaults).* |
| `kind-unknown` (R2b) | the resolved `kind` | Not in the schema's `kind` enum and not in `BUILDER_KIND_ALIASES` (the aliases 0.79.0 printed in §0: `^vr-` plus `ceos`, `srl`, `xrd`, `cvx`, `cumulus_cvx`, `crpd`, `cjunosevolved`, `c8000`; a constant with its source line). Suggestion as R1. | error when `exact` (P), else warning | *Line 5: containerlab 0.79.0 knows no kind `juniper_vjunos_switch`. Did you mean `juniper_vjunosswitch`?* |
| `kind-alias` (R2c) | the resolved `kind` | An alias: accepted, named once per lab (the first device that uses it). Two wordings: a `vr-*` name is old, a short name (`ceos`, `srl`, `xrd`, `crpd`, …) is a documented short form. | warning | *Line 5: `vr-xrv9k` is an old name containerlab still accepts; the current name is `cisco_xrv9k`.* / *Line 5: `ceos` is a short name for `arista_ceos`; the long name is what the manager's device catalog uses.* (the long name from `inventory.ALIASES` mirrored in the constant where known, else the sentence ends after the first clause) |
| `image-missing` (R3) | each node, after inheritance | No `image` resolves and the kind is not in `BUILDER_NO_IMAGE_KINDS = {bridge, ovs-bridge, host, ext-container}`. | warning (D) | *Line 4: `vsw` has no image. containerlab needs one to create the container; the deploy fails without it.* |
| `enum` (R4) | `restart-policy`, `image-pull-policy`, `runtime`, the stage names (keys of `stages`), `phase`, and `type` where the schema's `if kind … then type enum` applies (nokia_srlinux, nokia_sros, nokia_srsim, cisco_iol) | Value outside the enum. Suggestion as R1. For the keys of `stages` this rule alone reports (never R1 as well). | error when `exact` (P for stage names), else warning; `type` enums: warning (S) | *Line 9: `boot` is not a stage. The stages are create, create-links, configure, healthy and exit.* |
| `wait-stage` (R4b) | `wait-for[].stage` | Outside the five stages, or missing. | warning (D; `validate` accepts `ready` and a missing stage, the wait then has nothing to complete) | *Line 12: `ready` is not a stage, so this wait may never end. Use create, create-links, configure, healthy or exit.* / *Line 11: this wait-for entry has no `stage:`.* |
| `type` (R5) | every scalar or collection the schema types | Wrong YAML type for the key. Error only for a collection where a scalar is expected or a scalar where a collection is expected (`env` as a list, `ports` as a map, `image` as a mapping) and for a quoted string where a number is expected (`cpu: "2"`); a number or boolean where a string is expected (`prefix: 2024`, `image: 5`) is a warning, because Go's decoder puts a plain scalar into a string field. | error (P: `env` proven; the collection cases are the same decoder path) / warning (S) for scalar-to-scalar | *Line 7: `env` must be a mapping of NAME: value, not a list.* / *Line 2: `prefix` is read as the text `2024`; quote it if that is meant.* |
| `pattern-hard` (R6a) | `name`, `prefix`, node names (`^[a-zA-Z0-9][a-zA-Z0-9-._|]*$`), `ports[]` | The schema pattern fails. | error (M for names, P for ports) | *Line 1: the lab name `my lab` can only use letters, digits, dot, dash and underscore.* / *Line 8: `abc` is not a port mapping (host:container, e.g. 8080:80).* |
| `pattern-soft` (R6b) | `network-mode`, `mgmt-ipv4/6`, `shm-size`, link `mac`, `ipv4`/`ipv6`, `mgmt.ipv4-subnet` and the other mgmt patterns | The schema pattern fails. | warning (S; `network-mode: bogus` passed `validate`) | *Line 6: `bogus` is not a network mode containerlab documents (host, none, container:<name>); Docker refuses it when the lab is deployed.* |
| `binds` (R6c) | `binds[]` | Not a string, or a string without `:`. | error (P for a number) / warning (S) | *Line 8: a bind is `host-path:container-path[:ro]`; `1` is not one.* |
| `link-brief` (R7a) | a link without `type` | `endpoints` missing, not two items, an item not `node:interface`, the two items equal. | error (P) | *Line 14: a link needs exactly two endpoints as `device:interface`.* |
| `link-type` (R7b) | a link with `type` | `type` outside veth, veth-stitch, mgmt-net, host, macvlan, vxlan, vxlan-stitch, dummy; a required key of that form missing (`endpoint`, `host-interface`, `remote`, `vni`, `dst-port` per form); a key the form does not take (R1 at that level). | error when `exact` (P/S), else warning | *Line 16: a `host` link needs `endpoint` and `host-interface`.* |
| `link-node` (R7c) | each endpoint `node` (brief `node:iface` or long `node:`), except `host`, `mgmt-net`, `macvlan`, `vxlan`, `vxlan-stitch`, `dummy`, `bridge` | Not in `topology.nodes`. | error (P: `Unable to find node zz`) | *Line 15: the link endpoint `zz` is not a device in topology.nodes.* (the list carries this error whenever a tree exists; the `checkYaml` warning is written to the status line only when no tree exists, §4.1) |
| `link-duplicate` (R7d) | all endpoints | The same `node:interface` used twice in the lab. | warning (S) | *Line 17: `vsw:ge-0/0/0` is already used by the link on line 14.* |
| `wait-node` (R8a) | each effective `wait-for` entry (own and inherited) | `node` not in `topology.nodes`. | error (U) | *Line 12: There is no device named `vws`. Did you mean `vsw`?* |
| `wait-self` (R8b) | same | `node` equals the waiting node (also through `defaults`/`kinds`/`groups`). | error (U) | *Line 12: A device cannot wait for itself (`vsw` waits for `vsw` through topology.defaults).* |
| `wait-loop` (R8c) | the whole graph (edges `waiting → waited-for`, whatever the stages; upstream's `findWaitForCycle`) | A cycle. Reported once per cycle at the first entry of the cycle in text order. | error (U) | *Line 12: Devices wait for each other in a loop (vsw → vrt → vsw). containerlab will not deploy the lab.* |
| `wait-health` (R8d) | `wait-for … stage: healthy` | The waited-for node's kind is in `BUILDER_NO_HEALTHCHECK_KINDS = {arista_ceos, ceos, juniper_cjunosevolved, cjunosevolved, linux}` and it has no `healthcheck:` key (own or inherited). | warning (D, from §0's `docker ps`) | *Line 13: `ceos` has no health check, so it never reports healthy and this wait never ends. Wait for `create-links` or `configure` instead, or give `ceos` a `healthcheck:`.* For `linux`: *`host1` shows healthy only if its image defines a health check or the device has a `healthcheck:`; otherwise this wait never ends.* |
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

- **Two paths, one text.** `builderYamlValidate()` keeps today's rule: dirty only, 400 ms after the last keystroke,
  and it alone writes the status line (the state words and a blocking `checkYaml` error). A new
  `builderYamlCheckList(text)` runs on **every** text change: `input` after the same 400 ms, `builderYamlSet` (a canvas
  edit, Revert, the initial text), the panel opening, after Apply, and on the context upgrade when capabilities arrive;
  it touches only the list, the gutter marks, the count and `aria-invalid`, never the status line (finding 11).
- **What the list check does.** `flaw = checkYaml(text)`, `located = locateYaml(text)`. With `located.tree`:
  `builderCheck(tree, schemaOrNull, context)`: the schema-free rules at once, the schema rules once the schema has
  loaded (the load re-runs the list). **The list is active whenever a tree exists** (findings 4 and 14): the
  `checkYaml` warning (an endpoint naming an unknown device) is then not written to the status line, because the list
  carries it as `link-node`, an error. Without a tree (a parse error, a document too deep, an editor whose bundle has no
  `locateYaml`): the list is emptied, and the status line shows the `checkYaml` warning exactly as today. `builderYamlValidate`
  therefore writes a `checkYaml` warning only when `locateYaml` gave no tree.
- Each item is `<li class="is-error|is-warning"><button type="button" class="builder-yaml-problem" data-line="12">
  <span class="builder-yaml-sev">Error</span> Line 12: …</button></li>`; activating it calls
  `builderYamlGoto(line, {select: false})`: the caret lands after the indentation, on the key, with no selection, so
  the first key typed edits rather than replaces the line. An Apply refusal keeps today's selecting form
  (`builderYamlGoto(line)`); both forms are pinned (finding 18). The severity word is text, not colour alone. Errors
  first within a line; the list is `max-height` 30 % of the panel with its own scroll, `tabindex` on the `<ol>` when it
  scrolls.
- One fixed sentence above the list, always present with it (`<p class="form-help" id="builder-yaml-problems-note">`):
  *These do not stop Apply or Save; containerlab refuses errors when the lab is deployed.* The severity words stay
  *Error* and *Warning*, and the bar note uses the same word (finding 13).
- `#builder-yaml-count` reads *2 errors, 1 warning* / *1 warning* / *No problems found* (from `builderCheckSummary`)
  and is updated only when the text of the summary changes, so the live region speaks once per real change and never
  on a keystroke that changed nothing. *No problems found* is written only after `builderCheck` ran on a tree. While
  the status line holds a blocking error (no tree) the count reads *Not checked: fix the error above first*. While the
  schema loads and a tree exists it reads the schema-free result with *(settings not checked yet)* appended once
  (finding 12).
- `#builder-yaml-schema` is the caption of §2.3; with `exact` false it is also the first sentence a screen reader
  meets after the count, so the downgrade is never silent. At 900 px and below the caption and the key help (§4.3) sit
  under one `<details class="builder-yaml-more"><summary>About this check</summary>` disclosure, closed by default, so
  the textarea keeps its height (finding 17).
- The textarea's `aria-invalid` is `true` while the list has an error or the status line shows a blocking one
  (today: blocking only); `aria-describedby` gains `builder-yaml-count` (and nothing else: the example of §4.5 and the
  problems note stay outside it).
- Apply and Revert are untouched (decision 4). After an Apply with errors still listed the status line reads *Applied
  · 2 errors remain (see Problems)* (tone `warn`; errors only, warnings are not counted); when newer edits exist as
  well, today's *Applied · newer edits not applied* wins (finding 19).

### 4.2 The gutter

`builderYamlGutter()` builds the gutter as `<span class="builder-yaml-line">N</span>` per line (numbers only, no
student text, so no `esc()` is needed but the markup is still built through `textContent` per span, never
`innerHTML` of interpolated text: the file keeps its "no innerHTML" pin by using `replaceChildren` with created
elements). A line with a finding gets `is-error` or `is-warning` (error wins) and a `title` with the first message;
the gutter stays `aria-hidden` (the list is the accessible form). Marks are refreshed with the list; `builderYamlSet` and every `input` clear them at once
and schedule the list check, so a stale mark never points at a moved line (finding 11). The tests keep today's claim
"one number per text line" in the new markup (finding 22).

### 4.3 Key help on the caret

A `<p id="builder-yaml-keyhelp" class="form-help builder-yaml-keyhelp" aria-live="off"></p>` under the list. On
`selectionchange` (document-level in `shell.js`? No: the builder page has no `shell.js`; the panel binds
`document.addEventListener('selectionchange', …)` itself behind a `typeof document` guard, as the page already binds
`DOMContentLoaded`) and on `keyup`/`click` in the textarea, throttled to 150 ms, `builderKeyHelp(tree, schema, line)`
finds the key on the caret's line (`^\s*(?:- )?([\w.-]+):`), resolves its level by walking the located tree for the
map whose entry has `keyLine === line`, and shows *`startup-config` · path to a startup config file (if supported by
the kind). [More about startup-config]* where the link is `<a href="https://containerlab.dev/manual/nodes/#startup-config"
target="_blank" rel="noopener">More about startup-config</a>` (the key in the link text, finding 20) taken from the first `(https://containerlab.dev/…)` in the key's `markdownDescription`
(only that host; anything else drops the link). A line without a known key clears the help, and so does a stale tree: the help is shown only
when the key the regex reads from the current text equals the tree's key at that line (between a keystroke and the next
validation the tree can be behind the text, finding 21). It is `aria-live="off"`:
a caret move is not an event to announce; the text is read when focus or the virtual cursor reaches it. Not shown
while the schema is absent. At 900 px and below it lives under the §4.1 disclosure.

### 4.4 The bar note on the stored draft (`lab-builder-page.js`)

`persist()` already debounces the image check (`builderImageStatus`, 1.2 s). `builderCheckStatus()` joins it **inside
its own debounced timer, never synchronously in `persist()`**, and its whole body is wrapped in `try/catch`: a throw
hides the note and does nothing else, so an advisory check can never reach `page.problem`, `builderPaused` or the
`inert` overlay (finding 0; the image check is safe for the same reason, `lab-builder-page.js:303`). Its first run after
a stored change asks the panel's loader (`builderYamlSchema()`, the one fetcher on the page) to fetch the schema once
(105 KB, same origin), so a student who never opens the panel still gets the note (finding 7, option a); until the
schema arrives it runs the schema-free rules. It calls `locateYaml(draft.yaml)` through the attached editor (nothing
before the editor attached) and `builderCheck` on it, and keeps **every finding whose severity is error after the
`exact` rule, whatever `exact` is** (a wait-for loop, an unknown link endpoint, a missing kind and the exec form are
errors on any VM; finding 15). The note is a line under the bar in the style of `#builder-images`
(`<div id="builder-check" role="status" hidden>`), one sentence: *1 error containerlab will refuse when deploying: line 7,
`imge` is not a device setting. Open YAML to see it.* (*2 errors …: the first is line 7, …*), with a **Show in YAML**
button and **Dismiss** (remembered by draft, text and count like `builderImageKey`; focus then goes to Save, or to the
YAML button when Save is off, as `builderImageDismiss` does). **Show in YAML** opens the panel and, when the panel is
clean, moves the caret to the finding's line; when the panel holds unapplied edits (its text differs from the stored
draft, so the lines differ) it opens the panel at its own Problems list instead and moves nothing. It never changes
`builderBlocked()`: Save stays on (decision 4); the review's own refusals and containerlab's deploy output remain the
hard stops.

### 4.5 The stage example in the help

After the help paragraph `#builder-yaml-help`, as its **sibling** and outside every `aria-describedby` target (a
`<details>` cannot sit inside a `<p>`, and the example must never be read as the textarea's description; findings 6 and
16, pinned by the markup test), the panel gains `<details class="builder-yaml-example"><summary>Boot order: start the
router after the switch is healthy (stages)</summary>…</details>` with the sentence *On a VM with little memory, start one
VM-based device at a time: the router's container is created only when the switch reports healthy. `healthy` works
for devices with a health check (vJunos-switch, vJunos-router, XRv9k); for cEOS or cJunosEvolved wait for
`create-links` instead. Copy the `stages:` block under the device that should wait; the images are this course's, use
your own.* and the example (verified in §0):

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

Default: the list reads *No problems found* under a valid text, the caption names the schema. Loading: the schema-free
result with *(settings not checked yet)* once, the status line and Apply unaffected. Blocking error: the list empty,
the count *Not checked: fix the error above first*. Empty text: the shape error in the status line, list cleared. Error
(fetch): the one sentence with *Try again*. Disabled: never; the panel is read-only before the editor attaches as
today, and the list is then empty with no caption. Narrow (≤ 900 px): the panel is the lower 55 % as today; `.builder-yaml-body`
has `min-height: 160px` (eight lines) at every width; the list takes at most 30 % of the panel and scrolls inside; the
caption and the key help are under the *About this check* disclosure; the 760 px smoke asserts the textarea is at
least 160 px tall with ten items listed and the "unknown version" caption (finding 17); nothing scrolls sideways
(`overflow-wrap: anywhere` on items). The list, its buttons, *Try again*, *More about …*, *Copy example*, *Show in
YAML*, *Dismiss* and the disclosure are all reachable with Tab in reading order; Escape keeps its meaning (closes a clean panel only).

## 5. The vendored schema, its licence and its refresh

Files (new):

- `clab-backup-ui/app/static/clab-schema/0.79.0.json`: the upstream file verbatim (digest §0).
- `clab-backup-ui/app/static/clab-schema/LICENSE`: containerlab's `LICENSE` at the same tag (BSD-3-Clause, Nokia).
- `clab-backup-ui/app/static/clab-schema/SOURCES.txt`: one line per file: `0.79.0.json  v0.79.0
  https://raw.githubusercontent.com/srl-labs/containerlab/v0.79.0/schemas/clab.schema.json  sha256 51a70250…f58d02
  fetched 2026-10-23`.
- `clab-backup-ui/lab-builder/fetch-schema.mjs <tag> --sha256 <expected>` or `… <tag> --commit <sha>` (Node, like
  upstream's `sync-clab-schema.mjs`): the tag must match `^v\d+\.\d+\.\d+$` before any path is derived (else it
  refuses); with `--sha256` it downloads the tag's schema and refuses to write when the digest differs from the one the
  maintainer took from GitHub; with `--commit` it downloads by the 40-hex commit (immutable, unlike a tag) and records
  that commit; it also checks `$id === 'https://containerlab.dev/clab.schema.json'`, `type === 'object'` and
  `definitions['node-config']`, downloads `LICENSE` at the same ref, writes `app/static/clab-schema/<version>.json`
  (version = tag without `v`), appends to `SOURCES.txt` (tag, commit or digest source, URL, digest, date), prints the
  digest, and reminds the maintainer to add the version to `BUILDER_SCHEMA_VERSIONS` and to the digest literal in
  `test_clab_schema.py`, then to run the tests: a refresh is a reviewed test diff, not a `SOURCES.txt` rewrite
  (finding 3). It lives in the build project because that is where Node is expected; it never runs on a VM.

Why `app/static/clab-schema/` and not under `app/static/lab-builder/`: `build.mjs` deletes and regenerates that
folder on every rebuild. Why not bundled into `main.js`: a schema refresh would then need Node 24, `npm ci` and a
bundle rebuild, and the bundle is cached `immutable` so it would wait for a release anyway; a static JSON is served
`no-store` (`main.py:136`) and reaches the browser at the next page load. `verify-release.py` checks `?v=` only on
`/static/…` references inside the HTML pages; the fetch URL in the script carries none and needs none.

Licence record: `deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md` gains a row *containerlab topology schema
(`schemas/clab.schema.json`) · validation and key help in the YAML panel · BSD-3-Clause (`LICENSE` beside the file) ·
No (verbatim per release, `SOURCES.txt`)*; `docs/LAB-BUILDER.md` "Third-party software" names it in one sentence.

Threats a reviewer will raise, answered here: the file is data, never executed (`JSON.parse` after a same-origin
fetch; `script-src 'self'` unchanged); a tampered checkout changes the digest the stdlib test carries as a literal (and `SOURCES.txt`, which must agree); the walker never
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
  once, no loop in a chain; `healthy` on `ceos` without and with `healthcheck`, on `linux` (its wording); the exec object form, a string
  entry, a list entry without `phase` (no finding at all), `phase: later` (warning); `until`; one test per rule-owned
  path asserting exactly one finding with the rule's code and severity (`kind: nosuch`, `stage: ready`, `boot:`, an
  exec entry, a link with `type: host` lacking `host-interface`); `position` silent, `username` the credentials
  warning, `mgmt_ipv4` the renamed-key warning and never R1; R1 at an unprobed level (`defaults`, `healthcheck`) a
  warning with `exact` true, at a probed level an error; R5: `env` list error, `image` mapping error, `cpu: "2"` error,
  `prefix: 2024` warning; `schema === null` runs the schema-free rules only; the 200-item cap; the summary
  text for 0/1/2 errors and warnings; `builderSchemaChoice` for every row of §2.3 and for `'0.79'`, `''`, `'dev'`, `'0.79.0-rc1'` (never exact, caption with the full string);
  `builderKeyHelp` for a node key, a nested `wait-for` key, a line without a key, and a `markdownDescription` whose
  link is not containerlab.dev (no link); `builderCheckSelfTest()` reports zero failed patterns for the vendored
  schema; the §4.5 example yields an empty list; the tree of a text whose root is a list yields R0 only. A final
  test asserts the script declares no top-level name the other builder scripts declare (the `test_page_load_ui.js`
  rule, checked locally too).
- `tests/test_clab_schema.py` (new; stdlib only, so it can run in the first CI group): every file named in
  `SOURCES.txt` exists with the stated SHA-256; every `*.json` in the folder is in `SOURCES.txt`; each parses, has the
  `$id`, `definitions.node-config` and `properties.topology`; `LICENSE` exists and contains "Redistribution and use";
  the expected digests are a literal in the test itself (`EXPECTED = {'0.79.0.json': '51a7…f58d02'}`) and equal both the
  files and `SOURCES.txt`; `BUILDER_SCHEMA_VERSIONS` in `lab-builder-check.js` equals the set of files (read by regex);
  `fetch-schema.mjs` exists, names the raw URL pattern, requires `--sha256` or `--commit` and the tag regex (read by
  regex), and never writes outside `app/static/clab-schema/`.
- `tests/test_lab_builder_yaml_ui.js` (extended): the markup has the new ids, `role="status"` on the count only, the
  fixed problems note, the example `<details>` as a sibling after `#builder-yaml-help` and the `aria-describedby`
  string exactly `builder-yaml-status builder-yaml-help builder-yaml-count` (the old string test rewritten, not
  deleted); the gutter test keeps "one number per text line" in the span markup; a validation with a fake `locateYaml`
  renders items with the severity word, the line and `data-line`; clicking one puts the caret on the key with no
  selection while an Apply refusal still selects the line; the count changes once per summary change (two validations
  with the same summary → one `textContent` write); the old claim of line 119 (an unknown endpoint is reported with
  line 6 and warning severity on the status line) is rewritten: with a tree it is a `link-node` error in the list and the
  status line reads *Edited · not applied*; without a tree (a fake editor with no `locateYaml`) the old assertion holds
  as written; an error in `checkYaml` empties the list and the count reads *Not checked: fix the error above first*;
  *No problems found* never appears before a run on a tree; the list check runs on `builderYamlSet`, open, Apply and
  Revert without touching the status line; Apply with findings succeeds and reads *Applied · 2 errors remain (see
  Problems)*, and *Applied · newer edits not applied* when both apply; the gutter marks the lines and clears on the
  next keystroke and on `builderYamlSet`; the key help clears when the text's key differs from the tree's; the schema caption for `exact` true and false; the failed fetch sentence
  and *Try again*; the context upgrade when capabilities arrive late; the key help for a caret line (fake tree);
  the example `<details>` exists with the §4.5 text and a Copy button only when `copyButton` is defined; the bundle
  test adds `locateYaml` to the names the committed `main.js` must contain; the "no innerHTML" pin is kept.
- `tests/test_lab_builder_ui.js` (extended): `builderCheckStatus` runs only from its timer (a `persist()` call makes
  no synchronous check), renders the bar note for one error, shows an error-level finding with `exact` false (a wait
  loop) and hides warnings only, asks the loader once for the schema when none is loaded, remembers a dismissal per
  draft and text, moves focus after Dismiss as the image note does, and never changes `builderBlocked()`; a
  `locateYaml` or `builderCheck` that throws leaves `persist()`'s result, `builderUnstored`, `builderPaused` and
  `builderBlocked()` unchanged and the note hidden; *Show in YAML* on a clean panel calls the toggle and the goto, on a
  dirty panel the toggle only.
- Bundle: `node build.mjs` then `node build.mjs --check` (Node 24) after the adapter change; CI's rebuild step compares.
- Fixture smoke (`clab-ui-qa`, `fixture_manager.py` already answers `containerlab: '0.79.0'`):
  `student_workflow.py` gains, after its existing YAML check: open YAML, paste the §4.5 example with `vsw` misspelt in
  the `wait-for` and `imge:` on a node, wait for the list, assert two items with their lines and the caption
  *the version on this VM*, click the first item and assert the caret line, correct both, assert *No problems found*,
  Apply, assert *Applied*; assert the gutter class and that the bar note appeared and went; with the panel closed and a
  wait loop pasted through a canvas-free path (the draft file import) assert the bar note appears without the panel
  ever opened; Tab from the textarea reaches the first problem button; at 760 px assert the textarea's height is at
  least 160 px with ten items listed and the "unknown version" caption forced through the context; `securitypolicyviolation` stays empty (the schema fetch is same-origin). Viewports
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
line"); the key help on the caret with its *More about …* link; that the panel's *Error* never stops Apply or Save; and a subsection **Boot order (stages)** with the §4.5
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
- The Go unmarshaller refuses every unknown key at the levels §0 probed (R1 is an error there only); at every other
  level R1 stays a warning until §7.4's probe of that level is recorded. Type mismatches are errors only for the
  collection-versus-scalar cases (R5).
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
hard-coded list, never from the VM's string); the `More about …` link host check; the bar note's timer and `try/catch` against a `locateYaml` that throws; that the publish path is untouched and that
no finding ever reaches the manager (nothing is posted; the bar note is local); the 200-item cap and the 1 MiB text
cap against a tree that nests 10,000 levels (the walker is iterative or depth-capped at 64 with one finding).

`clab-ui-reviewer`: the severity table (is a warning ever shown where the student will be refused, or an error where
containerlab would accept the text?); the downgrade when the VM is newer (does a student on 0.81 understand why a
valid key is a warning?); the three surfaces (list, gutter, bar note) saying the same thing in three words; the count
live region's chatter; the caret help's `aria-live="off"`; the `checkYaml` warning moving from the status line to
the list (does the status line still explain why Apply is on?); *Applied · 2 errors remain (see Problems)* against the existing
*Applied · newer edits not applied*; the example's Copy against a student who expects Insert; the 760 px layout with
a long list; the lost-functionality check against `docs/redesign/inventory` (nothing of the panel's today is removed).

### 7.4 The live pass

Measure first (`free -g`, `docker ps`): the `parity` lab is the lead's and stays up; a second lab needs about 10 GB
for the Juniper pair (the router on the local nested image `local/juniper_vjunos-router:26.2R1.7-nested`, C00). Only
if at least 20 GB are available and the lead assigns the lab: publish the §4.5 example through the builder (Save to
the VM, the reviewed `publish`), deploy it from the manager, and record from `docker ps` timestamps that `clab-<lab>-vrt`
was created after `clab-<lab>-vsw` turned `(healthy)`; then destroy it. Otherwise the evidence is the dry run of §0
(repeatable: `containerlab deploy --dry-run -t <file>` on the saved file, read-only) plus `containerlab validate`.
In either case, cheap read-only `containerlab validate` probes close §7.1's assumptions and grow the per-version
tables of §3, each result recorded beside the constant it changes: `position: 1,2` on a node (expected accepted),
`username:`/`password:` on a node (expected accepted), `mgmt_ipv4:` on a node and `ipv4_subnet:` under `mgmt`
(expected accepted with containerlab's deprecation warning), `prefix: 2024` (expected accepted), an unknown key under
`defaults`, a `kinds` entry, a `groups` entry, a stage (`create: {foo: 1}`), an `exec` entry, `healthcheck`, `dns`,
`certificate`, `settings`, a long-form link and a long-form endpoint (each expected refused: the level then joins
`BUILDER_PROBED_LEVELS`). The deploy behaviour on a loop needs a
real deploy; a two-node cEOS loop lab (about 4 GB, no healthcheck, `wait-for … create`) is the cheapest proof and is
done only with the lead's assignment, destroyed afterwards, evidence to `docs/parity-campaign/evidence/c08-live.md`.

## 8. Slices (disjoint files), owners, sizes, acceptance

Contract between the slices: §2.1 (the located tree) and §2.2 (the diagnostics). S2 and S3 build against hand-made
trees and fake handles, so all four can run in parallel; S3 integrates with S1's bundle at the end.

| Slice | Files | Owner (the lead's decision) | Size | Acceptance |
|---|---|---|---|---|
| **S1 adapter**: `locateYaml` on the `YamlEditorHandle`; bundle rebuild | `clab-backup-ui/lab-builder/src/main.tsx`; `clab-backup-ui/app/static/lab-builder/**` (regenerated); no `patches.mjs` change | `clab-editor-specialist` | S (about 30 lines of TypeScript) | `node build.mjs` then `node build.mjs --check` exit 0 with Node 24; the committed `main.js` contains `locateYaml`; the tree of the §4.5 example has `topology.nodes.vrt.stages.create['wait-for'][0].node` at line 13; a flow map gives one line to its keys; a parse error returns `{error}` equal to `checkYaml`'s; a 65-level document returns `{error}` and `locateYaml` never throws (a test wraps a throwing `parseDocument`); `checkYaml`, `applyYaml`, `MAP_COMMANDS`, `disabledTabIds` unchanged (`test_lab_builder_yaml_ui.js` bundle test and `test_lab_builder_ui.js` "every editor control the page hides still exists" pass) |
| **S2 validator and schema**: the walker, the rules, the choice, the key help, the self-test; the vendored schema with licence, sources and fetch script; their tests | `clab-backup-ui/app/static/lab-builder-check.js` (new); `clab-backup-ui/app/static/clab-schema/{0.79.0.json,LICENSE,SOURCES.txt}` (new); `clab-backup-ui/lab-builder/fetch-schema.mjs` (new); `clab-backup-ui/tests/test_lab_builder_check_ui.js` (new); `clab-backup-ui/tests/test_clab_schema.py` (new) | `clab-opus-specialist`; `risk-reviewer` on the vendored schema and the fetch script | L (about 350 lines of script, 300 of tests) | `node --test tests/test_lab_builder_check_ui.js` and the stdlib test exit 0; `node --check` on the script; every §3 wording pinned; one finding per rule-owned path; the self-test reports 0 failed patterns; the digest literal in the test equals the file; `sha256sum 0.79.0.json` equals §0; the script loads in a bare `vm` context (no `document`, no `fetch`); no top-level name clashes with the other builder scripts |
| **S3 panel and page wiring**: the list, the gutter marks, the count, the caption, the schema fetch and context, the caret help, the example with Copy, the bar note; CSS; the script tag | `clab-backup-ui/app/static/lab-builder-yaml.js`, `lab-builder-page.js`, `lab-builder.html` (the `<script src="/static/lab-builder-check.js?v=…">` after `lab-builder-yaml.js`; the release owner moves the number), `lab-builder.css`; `clab-backup-ui/tests/test_lab_builder_yaml_ui.js`, `test_lab_builder_ui.js` (extended) | `clab-ui-builder`; `clab-ui-reviewer` on the slice | M (about 150 lines of script, 30 of CSS, 150 of tests) | both test files exit 0; `node --check` on both scripts; `test_page_load_ui.js` exit 0 (`lab-builder.html` loads every script in one context); no `innerHTML` in `lab-builder-yaml.js`; no inline style; every §4 state reachable with a fake `locateYaml` and a fake `fetch`; the gutter tests keep "one number per text line" and the describedby test is rewritten, not deleted; `.builder-yaml-body` `min-height: 160px`; `map-editor.html` unchanged |
| **S4 docs and fixture smoke** | `docs/LAB-BUILDER.md`, `deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md`, `docs/lab-builder/tools/student_workflow.py` | `docs-auditor` (docs), `clab-ui-qa` (the smoke) | S | `python3 docs/maintenance-audit/tools/check_links.py` and `python3 deploy/verify-release.py --docs` exit 0; the smoke's new checks pass at 1440 and 760 on a fresh `FIXTURE_DATA` with the rebuilt bundle (the 760 px textarea height among them); evidence under `docs/parity-campaign/evidence/` |

Lead only: the release number (the bundle is cached `immutable`, so the chunk is a release), the `?v=` on the new
script tag, the two CI list entries, `PARITY.md` rows, the three history files, the live pass assignment.

**Lead's decisions on the open questions:** (1) a wait-for loop and an unknown wait-for target are errors with upstream's
wording ("containerlab's deploy refuses this"); the live pass proves it on a disposable two-cEOS loop lab under the lead's
assignment (memory measured first), otherwise the wording stands as upstream's and VALIDATION says so; (2) the Juniper
pair live pass is conditional on 20 GB available beside the parity lab, with the dry run as the fallback evidence;
(3) S2 goes to `clab-opus-specialist` with `clab-ui-reviewer` on the panel and `risk-reviewer` on the vendored schema;
(4) a read-only `validate` helper mode is not pursued in this campaign (noted for a later chunk).

## 9. Review answers

One row per confirmed finding of `/clab-design-review`, in the review's order (23 confirmed: 2 must-fix, 15 should-fix,
6 optional; the 4 refuted findings need no row). Every row is the lead's binding decision; the body sections named were
amended accordingly.

| Finding | Answer | Where |
|---|---|---|
| 0 must-fix: an exception in the bar-note check inside `persist()` would pause the whole builder | Accepted (lead): `builderCheckStatus` runs only inside its own debounced timer, never synchronously in `persist()`, wrapped in `try/catch` so a throw hides the note; `locateYaml` caps depth at 64 and returns `{error}` instead of throwing; a test shows a throwing check leaves `persist()` and `builderBlocked()` unchanged | §1.4, §2.1, §4.4, §6.1, §7.3, §8 S1 |
| 1 should-fix: with an exact match, keys containerlab 0.79.0 accepts are reported as errors | Accepted (lead): per-version `BUILDER_SCHEMA_EXTRA_KEYS` citing `types/node_definition.go` (`position` accepted; node-level `username`/`password` a warning pointing to `credentials`); `validate` probes of those in §7.4; R1 is a warning at any level not yet probed (`BUILDER_PROBED_LEVELS`) | §1.5, §3 tables and R1, §6.1, §7.1, §7.4 |
| 2 should-fix: precedence between generic schema keywords and the hand-written rules | Accepted (lead, with 8): a rule-owned paths list; the walker skips generic keywords there; generic findings outside the named rows are warnings; an exec entry without `phase` yields no finding; one test per path | §3 "Rule-owned paths", §6.1 |
| 3 should-fix: the schema digest is pinned by the script that writes it | Accepted (lead): `fetch-schema.mjs` requires `--sha256 <expected>` or fetches by commit SHA and refuses a mismatch; the tag must match `^v\d+\.\d+\.\d+$` before a path is derived; the digests are a literal in `test_clab_schema.py` as well | §1.2, §5, §6.1, §8 S2 |
| 4 should-fix: moving the `checkYaml` warning off the status line needs the old test rewritten and a fallback | Accepted (lead, with 14): the list is active whenever a tree exists; the status line keeps today's warning when no tree exists; the list check skips the dirty gate; line 119's claim is rewritten into the list with the no-tree case kept as written | §3 R7c, §4.1, §6.1 |
| 5 optional: exact version match uses a prefix test | Accepted (lead): `exact` is full `^\d+\.\d+\.\d+$` string equality; a suffix takes the "between" row with the full string in the caption; `'0.79.0-rc1'` tested | §1.5, §2.3, §6.1 |
| 6 optional: the stage example would sit inside the textarea's `aria-describedby` paragraph | Accepted (lead, with 16): the `<details>` is a sibling after `#builder-yaml-help`, outside every `aria-describedby` target, pinned by the markup test | §4.5, §4.1 (describedby), §6.1 |
| 7 must-fix: the bar note never appears for a student who has not opened the YAML panel | Accepted (lead, option a): the note's first run after a stored change asks the panel's loader to fetch the schema once; the schema-free rules run before it arrives; decision 2 reworded; a smoke step asserts the note with the panel never opened | §1.2, §1.4, §4.4, §6.1 |
| 8 should-fix: no rule says which wins when the walker and a hand-written rule judge the same key | Accepted (lead, with 2): rule-owned paths `kind`, the keys of `stages`, `wait-for[]` and its `stage`, `stages.*.exec`, links; only the named rule reports, once; `boot:` is R4 only, `stage: ready` R4b only, aliases R2c only | §3 "Rule-owned paths", R4, §6.1 |
| 9 should-fix: the old underscore keys containerlab still accepts would be errors | Accepted (lead): `BUILDER_DEPRECATED_KEYS` for `mgmt_ipv4`, `mgmt_ipv6`, `ipv4_subnet`, `ipv6_subnet` as warnings naming the current key, never R1; `mgmt_ipv4:` and `ipv4_subnet:` in the §7.4 probes | §3 tables, §6.1, §7.4 |
| 10 should-fix: R5 makes every type mismatch an error, but only `env` as a list was proven | Accepted (lead): R5 is an error only for a collection where a scalar is expected or the reverse and for a quoted string where a number is expected; other mismatches are warnings with their own sentence; `prefix: 2024` probed in §7.4 | §3 R5, §6.1, §7.1, §7.4 |
| 11 should-fix: validating after Apply, Revert, open or a canvas edit collides with the dirty-only validator | Accepted (lead): the work is split; `builderYamlCheckList` runs on every text change (input after 400 ms, `builderYamlSet`, open, Apply, Revert, the context upgrade) and touches only the list, gutter, count and `aria-invalid`; the status line keeps its dirty-only rule; `builderYamlSet` clears the marks | §4.1, §4.2, §6.1 |
| 12 should-fix: the count says "No problems found" beside a blocking error | Accepted (lead): with a blocking error the count reads *Not checked: fix the error above first*; *No problems found* only after a real run on a tree; the loading state is the schema-free result with *(settings not checked yet)*; tests for each | §2.2, §4.1, §4.6, §6.1 |
| 13 should-fix: "Error" means two different things in one panel | Accepted (lead): *Error* kept, with the fixed sentence above the list *These do not stop Apply or Save; containerlab refuses errors when the lab is deployed.*; the bar note uses the same word (*1 error containerlab will refuse when deploying …*) | §1.4, §4.1, §4.4, §6.2 |
| 14 should-fix: "list active" undefined; a failed fetch drops the stage checks | Accepted (lead, with 4): active whenever a tree exists; the schema-free rules (R2a, R3, R7a/c/d, R8a–d, R9a/b) run without the schema and the schema rules once loaded; the failed-fetch sentence reads *so settings and kinds are not checked; links and boot order still are* | §1.10, §2.2, §2.3, §4.1 |
| 15 should-fix: with an inexact match the bar note hides findings that are errors either way | Accepted (lead): the note covers every finding whose severity is error after the exact rule, whatever `exact` is; with a dirty panel *Show in YAML* opens the panel at its own list; focus after Dismiss as `builderImageDismiss` | §4.4, §6.1 |
| 16 should-fix: the stage example inside the help paragraph is invalid HTML and read as the description | Accepted (lead, with 6): sibling after `#builder-yaml-help`, outside every `aria-describedby` target, pinned | §4.5, §6.1 |
| 17 should-fix: at ≤ 900 px the new parts leave the textarea almost no height | Accepted (lead): `.builder-yaml-body` `min-height: 160px` (eight lines); at 900 px and below the caption and the key help collapse under an *About this check* disclosure; the 760 px smoke asserts the textarea height with ten items and the unknown caption | §4.1, §4.3, §4.6, §6.1, §8 S3, S4 |
| 18 should-fix: clicking a problem selects the whole line | Accepted (lead): the list's goto puts the caret on the key without a selection (`builderYamlGoto(line, {select: false})`); Apply refusals keep the selecting form; both pinned | §4.1, §6.1 |
| 19 optional: "Applied · 2 problems remain" is undefined | Accepted as proposed: *Applied · 2 errors remain (see Problems)*, errors only; *Applied · newer edits not applied* wins when both apply; the bar note counts errors in the word of finding 13 | §4.1, §4.4, §6.1 |
| 20 optional: some finding wordings would mislead a student | Accepted as proposed: R2c distinguishes a short name (*a short name for `arista_ceos`*) from an old `vr-*` name, once per lab; "device" throughout with upstream's sentence shape; the `linux` wording of R8d; the link text *More about `<key>`*; the example's sentence says which block to copy and that the images are the course's | §1.7, §1.8, §3 R2c, R8a–d, §4.3, §4.5 |
| 21 optional: the caret help can describe the wrong key between a keystroke and the next validation | Accepted as proposed: help only when the tree's key at the caret line equals the key read from the current text; otherwise cleared; tested | §4.3, §6.1 |
| 22 optional: lost functionality against the inventories and parity records (none found) | Accepted as proposed: S3's acceptance states that the gutter tests keep "one number per text line" in the new markup and that the describedby string test is rewritten, not deleted | §4.2, §6.1, §8 S3 |

## 10. Verification answers (`/clab-slice-verify` on `wt-c08-s3` at 0fc010b, six workers; every acceptance check held; the fixture passes at 1440, 760 and 390)

| Finding | Answer | Where |
|---|---|---|
| Medium: `locateYaml` resolved each alias through the library with no context, so an alias-heavy draft froze the tab for seconds through the bar note | Accepted: aliases are resolved in one pass over the document (1,000 / 3,000 / 6,000 aliases in 33 / 107 / 372 ms, from 387 / 2,852 / 11,303 ms) and a 1,500 ms time bound returns `{error}` instead of blocking; the parser's own cost (yaml 2.9.0) remains and is bounded by the 1 MiB input cap | §2.1; `main.tsx`, the bundle |
| Medium-low: YAML merge keys (`<<: *anchor`) produced false errors on a topology containerlab accepts | Accepted twice: the located tree applies merge keys as Go yaml does (the map's own keys win, merged keys at the `<<` line), and the validator applies a `<<` entry itself when a tree still carries one | §2.1, §3; `main.tsx`, `lab-builder-check.js` |
| Low: the SR OS free-form `type` pattern was never tested, so a wrong type was never reported | Accepted: tested behind a guard (at most 64 characters from the characters a type line uses), so a wrong short type gets the enum warning and a 300-character value returns in about a millisecond | §3; the old test's claim rewritten |
| Low: the wait-loop message listed every name | Accepted: at most eight names, then "… (n more)" | §3 |
| Low: an environment-variable prefix was attributed to containerlab while the manager's import refuses it | Accepted: the error keeps its severity, reads "the manager's import refuses this prefix", carries `refuser: 'manager'`, and the bar note counts containerlab's errors apart | §3, §4.4 |
| Low: the Problems list rebuild dropped keyboard focus | Accepted: the same item (line and code) is refocused, else the list (`tabindex=-1`) | §4.1 |
| Low to medium: at 760 and 390 the Problems list shrank to a sliver with the disclosure open | Accepted: a minimum of about three items (84 px), the 42 % cap removed, the panel's own scroll carries the rest, the textarea keeps 160 px (measured 253 px at 390×844) | §4.6; `lab-builder.css` |
| Info: the bar note's Dismiss was not remembered across a reload | Accepted: remembered per draft digest in `sessionStorage` until the text changes | §4.4 |
| Info: nesting beyond 64 levels shows a status error while Apply still works; a throwing check leaves no trace | Accepted as designed: the advisory check never blocks and never pauses the builder | §1, §4 |
