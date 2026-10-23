// Vendors containerlab's topology schema for one release, verbatim, for the lab builder's YAML check
// (docs/parity-campaign/C08-DESIGN.md §5). Run by a maintainer where Node is installed; never on a lab VM.
//   node fetch-schema.mjs v0.80.0 --sha256 <digest from GitHub>    download at the tag, refuse any other digest
//   node fetch-schema.mjs v0.80.0 --commit <40-hex commit>          download at the commit (immutable), record it
//   … --out <existing folder>                                       write there instead (a scratch check)
// Writes only <version>.json, LICENSE and SOURCES.txt in app/static/clab-schema (or the --out folder). The downloaded
// files are data: the schema is read with JSON.parse and checked, nothing is executed. A refresh is a reviewed change:
// add the version to BUILDER_SCHEMA_VERSIONS in app/static/lab-builder-check.js and its digest to EXPECTED in
// tests/test_clab_schema.py, then run both test files.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const RAW = "https://raw.githubusercontent.com/srl-labs/containerlab";
const SCHEMA_ID = "https://containerlab.dev/clab.schema.json";
const TAG = /^v\d+\.\d+\.\d+$/, DIGEST = /^[0-9a-f]{64}$/, COMMIT = /^[0-9a-f]{40}$/;
const fail = (message) => { console.error(`fetch-schema: ${message}`); process.exit(1); };

const args = process.argv.slice(2), tag = args[0] ?? "";
// The tag is checked before anything is derived from it (a path, a URL).
if (!TAG.test(tag)) fail("usage: node fetch-schema.mjs vX.Y.Z (--sha256 <digest> | --commit <sha>) [--out <folder>]; the tag must look like v0.79.0");
const option = (name) => { const i = args.indexOf(name); if (i < 0) return ""; const v = args[i + 1]; if (!v || v.startsWith("--")) fail(`${name} needs a value`); return v; };
for (const a of args.slice(1)) if (a.startsWith("--") && !["--sha256", "--commit", "--out"].includes(a)) fail(`unknown option ${a}`);
const expected = option("--sha256").toLowerCase(), commit = option("--commit").toLowerCase(), outArg = option("--out");
if (!expected && !commit) fail("name the expected digest (--sha256, from GitHub) or a commit (--commit): a tag alone can move");
if (expected && !DIGEST.test(expected)) fail("--sha256 takes 64 hexadecimal characters");
if (commit && !COMMIT.test(commit)) fail("--commit takes the full 40-character commit id");
const version = tag.slice(1), ref = commit || tag;
const out = outArg ? resolve(outArg) : resolve(dirname(fileURLToPath(import.meta.url)), "../app/static/clab-schema");
if (!existsSync(out) || !statSync(out).isDirectory()) fail(`${out} is not an existing folder`);

async function download(url, limit) {
  const response = await fetch(url, { redirect: "error", signal: AbortSignal.timeout(30000) });
  if (!response.ok) fail(`${url} answered HTTP ${response.status}`);
  const body = Buffer.from(await response.arrayBuffer());
  if (body.length > limit) fail(`${url} is larger than ${limit} bytes`);
  return body;
}
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
// Written beside the target under a temporary name, then renamed: a failed run leaves the old file.
function put(name, bytes) { const target = join(out, name), part = `${target}.part`; writeFileSync(part, bytes); renameSync(part, target); }

const schemaUrl = `${RAW}/${ref}/schemas/clab.schema.json`, licenceUrl = `${RAW}/${ref}/LICENSE`;
const schema = await download(schemaUrl, 2 * 1024 * 1024), digest = sha256(schema);
if (expected && digest !== expected) fail(`the downloaded schema has sha256 ${digest}, not the expected ${expected}; nothing written`);
let parsed;
try { parsed = JSON.parse(schema.toString("utf8")); } catch { fail("the download is not JSON; nothing written"); }
if (parsed?.$id !== SCHEMA_ID || parsed?.type !== "object" || typeof parsed?.definitions?.["node-config"] !== "object" || typeof parsed?.properties?.topology !== "object")
  fail("the download is not containerlab's topology schema ($id, type, definitions.node-config, properties.topology); nothing written");
const licence = await download(licenceUrl, 64 * 1024), licenceDigest = sha256(licence);
if (!licence.toString("utf8").includes("Redistribution and use")) fail("the LICENSE at that ref is not the BSD licence containerlab ships; nothing written");

const file = `${version}.json`, existing = join(out, file);
if (existsSync(existing)) {
  if (!readFileSync(existing).equals(schema)) fail(`${file} exists with different contents; a vendored release is never replaced`);
  console.log(`${file} is already vendored with these exact bytes (sha256 ${digest}); nothing written.`);
  process.exit(0);
}
const date = new Date().toISOString().slice(0, 10), line = (name, url, sum) => `${name}  ${tag}  ${url}  sha256 ${sum}  fetched ${date}`;
const sourcesPath = join(out, "SOURCES.txt");
const header = "# The containerlab topology schemas the lab builder's YAML check uses, verbatim from containerlab's repository, and\n"
  + "# containerlab's licence (BSD-3-Clause, Nokia). Written by clab-backup-ui/lab-builder/fetch-schema.mjs; never edit a\n"
  + "# schema by hand. Fields, two spaces apart: file, tag, source URL, sha256 digest, date fetched.\n";
let sources = existsSync(sourcesPath) ? readFileSync(sourcesPath, "utf8") : header;
const licencePath = join(out, "LICENSE"), licenceChanged = !existsSync(licencePath) || !readFileSync(licencePath).equals(licence);
// One LICENSE line, for the licence file as it now is.
let rows = sources.split("\n").filter((row) => row !== "");
if (licenceChanged) rows = rows.filter((row) => !row.startsWith("LICENSE  "));
const at = rows.findIndex((row) => row.startsWith("LICENSE  "));
rows.splice(at < 0 ? rows.length : at, 0, line(file, schemaUrl, digest));
if (licenceChanged) rows.push(line("LICENSE", licenceUrl, licenceDigest));
put(file, schema);
if (licenceChanged) put("LICENSE", licence);
put("SOURCES.txt", rows.join("\n") + "\n");
console.log(`Wrote ${join(out, file)} (sha256 ${digest}${commit ? `, commit ${commit}` : ""})${licenceChanged ? " and LICENSE" : ""}, and its line in SOURCES.txt.`);
console.log(`Next: add '${version}' to BUILDER_SCHEMA_VERSIONS in app/static/lab-builder-check.js and '${file}': '${digest}' to EXPECTED in tests/test_clab_schema.py, then run node --test tests/test_lab_builder_check_ui.js and tests/test_clab_schema.py (the self-test must still report zero failed patterns).`);
