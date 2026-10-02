# Lab builder feasibility research (throwaway)

Nothing here is production code and nothing here touches the manager, the VM helpers or any lab.
The production checkout `~/projects/clab-manager` was only read.

## Sources (identical to what the eight readers examined)

| Input | Identity |
|---|---|
| Manager | `main` 398d726, release 1.29.1, clean tree |
| Upstream repo | srl-labs/containerlab-app be0ec244e60367a5e1f3aa8b5b68af6290ac4654 (clab-ui 0.4.0, unpublished) in `inputs/containerlab-app` |
| Published package | `@containerlab/clab-ui@0.3.2`, shasum e153aad0ad12232a3a996a775ac38512da64392d, integrity sha512-1ei9U9XK…Dj34g==, LICENSE sha256 43070e2d… (Apache-2.0) in `inputs/npm-0.3.2` |
| Toolchain | Node v24.21.0 (checksum-verified tarball in `tooling/`), esbuild 0.25.10, react/react-dom 19.2.5 |

Difference from the original research: the readers' long-form reports were lost with /tmp in the
power-off; `reports/` holds the condensed results recovered from the workflow journal
(`reports/journal.jsonl` is the raw record). The schema used for the precompiled-validator experiment
is HEAD's `schema/clab.schema.json`, because 0.3.2 inlines its schema and ships no JSON file.

## Layout

- `reports/` recovered reader results · `proposal.md` the proposal the reviewer attacked
- `evidence/architecture-review.md` independent Fable review
- `evidence/*.json`, `evidence/shots/`, `evidence/fidelity/REPORT.txt`, `evidence/bundled-licenses.tsv`
- `prototype/` the embed: `src/main.tsx` (host adapter), `build.mjs`, `serve.py`, Playwright probes
- `FEASIBILITY-REPORT.md` the write-up

## Inspecting the prototype

Two loopback-only servers send the manager's exact response headers (`app/main.py:116-123`):

```bash
cd ~/research/lab-builder/prototype
python3 serve.py 8765 dist               # published package, unmodified ajv
python3 serve.py 8766 dist-precompiled   # same, with the build-time validator
```

From your workstation: `ssh -L 8766:127.0.0.1:8766 clabllm@<vm>` then open

- `http://127.0.0.1:8766/lab-builder.html?draft=demo&mode=clean` — proposed policy, clean mode
- `…/lab-builder.html?draft=demo` — everything upstream exposes (Geo, Split view, all deploy items)
- `…/lab-builder.html?draft=demo&tabs=off` — YAML/JSON tabs removed through `disabledTabIds`
- `…/lab-builder-manager.html?…` — the manager's policy as it is today (inline styles refused)
- `…/lab-builder-eval.html?…` on port 8765 — comparison with `script-src 'unsafe-eval'`

Click the padlock first: the editor opens locked. Drafts are JSON files in `prototype/scratch-data/`.
In the browser console `__PROTO__.yaml()`, `__PROTO__.annotations()` and `__PROTO__.log` show what the
adapter holds and every request the editor made of its host.

Rebuild: `PATH=~/research/lab-builder/tooling/node-v24.21.0-linux-x64/bin:$PATH node build.mjs [--precompiled-ajv]`.
