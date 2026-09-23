// The lab builder's editor: SR Labs' @containerlab/clab-ui mounted with the manager's own host.
// Everything manager-specific (drafts, saving to the VM, dialogs) lives in ../../app/static/lab-builder-page.js;
// this file only adapts the editor to it. The editing engine (TopologySessionCore) runs in the page over a
// two-document store, so the manager never implements the editor's command protocol.
import React from "react";
import { createRoot } from "react-dom/client";
import { App, useTopoViewerStore } from "@containerlab/clab-ui";
import { createClabUiRuntime, createWindowClabUiHost } from "@containerlab/clab-ui/host";
import { TopologySessionCore, mergeCustomNodeTemplates, parseCustomNodeTemplatesExport } from "@containerlab/clab-ui/session";
import type { FileSystemAdapter } from "@containerlab/clab-ui/session";
import { applyThemeVars } from "@containerlab/clab-ui/theme";
import { LineCounter, isMap, isSeq, isScalar, parseDocument } from "yaml";
import type { Node as YamlNode } from "yaml";
import "@containerlab/clab-ui/styles/global.css";

// mapOnly: the page is the manager's map editor (../../app/static/map-editor-page.js). The topology is an
// existing lab's and must come out exactly as it went in; only the annotations document is edited.
interface BuilderDraft { id: string; name: string; yaml: string; annotations: string; mapOnly?: boolean }
interface BuilderTemplate { name: string; kind: string; [key: string]: unknown }
interface BuilderPage {
  // Stores the pair durably (browser storage) before returning; throws when another tab changed the draft.
  persist(yaml: string, annotations: string): void;
  templates(): { list: BuilderTemplate[]; defaultName: string };
  saveTemplates(list: BuilderTemplate[], defaultName: string): void;
  images(): string[];
  // The text of a template file the student picked, or null when the file dialog was dismissed.
  chooseTemplates(): Promise<string | null>;
  notify(message: string): void;
  requestSave(): void;
  // code: "storage" (the browser could not store the draft) or "conflict" (another tab holds a newer one).
  problem(message: string, code?: string): void;
  ready(mount: (draft: BuilderDraft) => Promise<void>): void;
  // Map editor: the page receives a way to put a whole annotations document into the running editor
  // (its own undo / redo history, the device look). The topology is not reachable through it.
  // Lab builder: the page receives the topology text handle behind its editable YAML panel.
  attach?(editor: MapEditorHandle | YamlEditorHandle): void;
}
interface MapEditorHandle { applyAnnotations(text: string): Promise<void> }
// A refusal found before the engine is asked: `line` is 1-based when the text points at one.
interface YamlFlaw { message: string; line?: number; severity: "error" | "warning" }
interface YamlEditorHandle {
  // Replaces the whole topology text as one engine step (the editor's own undo takes it back). Rejects with
  // an Error carrying `code: "yaml"` and `line` when the text is refused; the graph is then untouched.
  applyYaml(text: string): Promise<void>;
  // The topology text as of the last settled operation.
  getYaml(): string;
  // Parser and shape check only, no engine call: the first error, else the first warning, else null.
  checkYaml(text: string): YamlFlaw | null;
  // Hears every stored state, after the page stored it. Returns the unsubscribe function.
  subscribe(listener: (yaml: string, annotations: string) => void): () => void;
}
declare global { interface Window { labBuilderPage: BuilderPage; __DOCKER_IMAGES__?: string[] } }

// Everything the map editor may ask the engine to do: each of these writes the annotations document only.
// The editor's view mode already hides adding, editing and deleting devices and links, but it enforces that
// in its own UI only; the engine applies whatever it is sent, so the refusal is made here.
const MAP_COMMANDS = new Set(["savePositions", "savePositionsAndAnnotations", "setAnnotations", "setAnnotationsWithMemberships",
  "setEdgeAnnotations", "setViewerSettings", "setNodeGroupMembership", "setNodeGroupMemberships"]);
const mapCommandAllowed = (command: unknown): boolean => {
  const c = command as { command?: string; payload?: { commands?: unknown[] }; commands?: unknown[] };
  if (c?.command === "batch") { const inner = c.payload?.commands ?? c.commands; return Array.isArray(inner) && inner.length > 0 && inner.every(mapCommandAllowed); }
  return typeof c?.command === "string" && MAP_COMMANDS.has(c.command);
};
const refused = (message: string) => Object.assign(new Error(message), { code: "topology" });

// The engine refuses only text the parser cannot read. A readable text of the wrong shape (an empty file, a
// list, `topology: 5`, nodes written as a list) it accepts, and the canvas then shows nothing: such a text is
// refused here, so the last good graph is never replaced by an empty one. Links naming a device that is not
// in topology.nodes are kept by the engine but not drawn: that is a warning, not a refusal.
function yamlFlaw(text: string): YamlFlaw | null {
  const lines = new LineCounter(), doc = parseDocument(text, { prettyErrors: true, lineCounter: lines });
  const lineOf = (node: unknown) => { const r = (node as YamlNode | null)?.range; return r ? lines.linePos(r[0]).line : undefined; };
  const error = doc.errors[0];
  if (error) return { message: error.message.split("\n")[0].replace(/ at line \d+, column \d+:?$/, ""), line: error.linePos?.[0]?.line, severity: "error" };
  const shape = (message: string, node?: unknown): YamlFlaw => ({ message, line: lineOf(node), severity: "error" });
  if (!isMap(doc.contents)) return shape("A topology file is a mapping with name: and topology: at the top.", doc.contents);
  const topology = doc.contents.get("topology", true);
  if (!isMap(topology)) return shape(topology === undefined ? "The file has no topology: section." : "topology: must be a mapping (nodes:, links:, …).", topology);
  const nodes = topology.get("nodes", true), links = topology.get("links", true);
  if (nodes !== undefined && !(isMap(nodes) || (isScalar(nodes) && nodes.value === null))) return shape("topology.nodes must be a mapping of device names.", nodes);
  if (links !== undefined && !(isSeq(links) || (isScalar(links) && links.value === null))) return shape("topology.links must be a list.", links);
  const names = new Set(isMap(nodes) ? nodes.items.map((p) => String(isScalar(p.key) ? p.key.value : p.key)) : []);
  for (const link of isSeq(links) ? links.items : []) {
    const endpoints = isMap(link) ? link.get("endpoints", true) : undefined;
    for (const end of isSeq(endpoints) ? endpoints.items : []) {
      const node = isScalar(end) ? String(end.value ?? "").split(":")[0] : isMap(end) ? String(end.get("node") ?? "") : "";
      // host:, macvlan:, mgmt-net: and the like are containerlab's special endpoints, not devices.
      if (node && !names.has(node) && !/^(host|mgmt-net|macvlan|vxlan|vxlan-stitch|dummy)$/.test(node)) return { message: `The link endpoint ${node} is not a device in topology.nodes: containerlab refuses such a link and the canvas cannot draw it.`, line: lineOf(end), severity: "warning" };
    }
  }
  return null;
}
const yamlRefusal = (flaw: YamlFlaw) => Object.assign(new Error(flaw.line ? `Line ${flaw.line}: ${flaw.message}` : flaw.message), { code: "yaml", line: flaw.line });

const enoent = (p: string) => Object.assign(new Error(`ENOENT: no such file, open '${p}'`), { code: "ENOENT" });

// The engine writes through a temporary name and a backup name for every save. Those stay in memory;
// only the settled topology and layout ever leave this class, and only between engine operations.
class DraftFiles implements FileSystemAdapter {
  files = new Map<string, string>();
  async readFile(p: string) { const v = this.files.get(p); if (v === undefined) throw enoent(p); return v; }
  async writeFile(p: string, c: string) { this.files.set(p, c); }
  async unlink(p: string) { this.files.delete(p); }
  async rename(a: string, b: string) { const v = this.files.get(a); if (v === undefined) throw enoent(a); this.files.delete(a); this.files.set(b, v); }
  async exists(p: string) { return this.files.has(p); }
  dirname(p: string) { const i = p.lastIndexOf("/"); return i <= 0 ? "/" : p.slice(0, i); }
  basename(p: string) { return p.slice(p.lastIndexOf("/") + 1); }
  join(...s: string[]) { return s.join("/").replace(/\/+/g, "/"); }
}

async function mount(draft: BuilderDraft): Promise<void> {
  const page = window.labBuilderPage;
  // The engine acknowledges edits to a document it cannot parse (a syntax error, a repeated key) and writes
  // none of them. Such a topology is refused here, with the parser's own reason and line.
  const flaw = parseDocument(draft.yaml, { prettyErrors: true }).errors[0];
  if (flaw) throw Object.assign(new Error(flaw.message.split("\n")[0]), { code: "unreadable" });
  const yamlPath = `/draft/${draft.name}.clab.yml`, layoutPath = `${yamlPath}.annotations.json`;
  const files = new DraftFiles();
  files.files.set(yamlPath, draft.yaml);
  if (draft.annotations) files.files.set(layoutPath, draft.annotations);
  const mapOnly = draft.mapOnly === true, mode = mapOnly ? "view" : "edit";
  const core = new TopologySessionCore({
    fs: files, yamlFilePath: yamlPath, mode, deploymentState: "undeployed",
    logger: { debug() {}, info() {}, warn() {}, error: (m: unknown) => console.error(m) }
  });
  // One engine operation at a time, and the draft is stored before the editor hears the answer: an
  // acknowledged edit is already durable, and a half-finished rename sequence is never stored.
  let queue: Promise<unknown> = Promise.resolve();
  // The texts as of the last settled operation, and the page's listeners for them (the YAML panel).
  let storedYaml = draft.yaml;
  const yamlListeners = new Set<(yaml: string, annotations: string) => void>();
  const settled = <T,>(work: () => Promise<T>): Promise<T> => {
    const run = queue.then(work).then((value) => {
      // Second line of defence in the map editor: whatever happened, the topology text leaves as it came.
      if (mapOnly && (files.files.get(yamlPath) ?? "") !== draft.yaml) {
        files.files.set(yamlPath, draft.yaml);
        const e = refused("The map editor does not change the topology. That edit was not kept."); page.problem(e.message, "topology"); throw e;
      }
      const yaml = files.files.get(yamlPath) ?? "", annotations = files.files.get(layoutPath) ?? "";
      try { page.persist(yaml, annotations); }
      catch (e) { page.problem(e instanceof Error ? e.message : String(e), (e as { code?: string }).code); throw e; }
      storedYaml = yaml;
      for (const listener of Array.from(yamlListeners)) { try { listener(yaml, annotations); } catch (e) { console.error(e); } }
      return value;
    });
    queue = run.catch(() => undefined);
    return run;
  };

  // The engine replaces the annotations document as one annotation-only command, and the editor redraws from
  // the snapshot it is sent, as it does for a file changed outside it. Zoom, pan and selection stay.
  if (mapOnly && page.attach) page.attach({
    applyAnnotations: (text: string) => settled(async () => {
      const before = await core.getSnapshot() as { revision: number };
      const answer = await core.applyCommand({ command: "setAnnotationsContent", payload: { content: text }, skipHistory: true } as never, before.revision) as { type?: string; error?: string };
      if (answer?.type === "topology-host:error" || answer?.type === "topology-host:reject") throw new Error(answer.error || "The editor did not accept that map.");
      const snapshot = await core.getSnapshot();
      window.postMessage({ type: "topology-host:snapshot", protocolVersion: 1, snapshot, reason: "external-change" }, window.location.origin);
    })
  });

  // Lab builder: the page's YAML panel drives the same engine. The whole text is one setYamlContent command
  // with history, so the editor's own undo takes an apply back in one step; the editor redraws from the
  // snapshot it is sent, as for a file changed outside it. The engine keeps the text exactly as given; its next
  // visual edit reprints the whole document in its own style (see docs/LAB-BUILDER.md).
  if (!mapOnly && page.attach) page.attach({
    applyYaml: (text: string) => {
      const flaw = yamlFlaw(text);
      if (flaw?.severity === "error") return Promise.reject(yamlRefusal(flaw));
      return settled(async () => {
        const before = await core.getSnapshot() as { revision: number; yamlContent?: string };
        if (before.yamlContent === text) return;
        const answer = await core.applyCommand({ command: "setYamlContent", payload: { content: text } } as never, before.revision) as { type?: string; error?: string };
        if (answer?.type === "topology-host:error") throw yamlRefusal({ message: (answer.error || "The editor did not accept that topology.").split("\n")[0], severity: "error" });
        if (answer?.type === "topology-host:reject") throw Object.assign(new Error("The editor changed the topology meanwhile. Nothing was applied; try again."), { code: "yaml" });
        const snapshot = await core.getSnapshot();
        window.postMessage({ type: "topology-host:snapshot", protocolVersion: 1, snapshot, reason: "external-change" }, window.location.origin);
      });
    },
    getYaml: () => storedYaml,
    checkYaml: yamlFlaw,
    subscribe(listener: (yaml: string, annotations: string) => void) { yamlListeners.add(listener); return () => { yamlListeners.delete(listener); }; }
  });

  const listeners = new Set<(e: unknown) => void>();
  const emit = (e: unknown) => { for (const h of Array.from(listeners)) h(e); };
  const pushTemplates = () => { const t = page.templates(); emit({ type: "customNodesUpdated", customNodes: t.list, defaultNode: t.defaultName }); };
  const nothing = () => {};
  const topoViewer = {
    // The editor's own deploy controls are hidden by the page; a keyboard path still lands here.
    runLifecycle() { emit({ type: "lifecycleStatus", status: "success" }); page.requestSave(); },
    cancelLifecycle() { emit({ type: "lifecycleStatus", status: "error", errorMessage: "Cancelled" }); },
    toggleSplitView: nothing, runNodeAction: nothing, captureInterface: nothing, setLinkImpairment: nothing,
    // The palette's Import templates: the file format and the merge rules are the editor's own.
    importCustomNodes() {
      page.chooseTemplates().then((text) => {
        if (text === null) return;
        const t = page.templates(), merged = mergeCustomNodeTemplates(t.list as never, parseCustomNodeTemplatesExport(text));
        // The page keeps the starred template by name; a flag inside an imported template would star a second one.
        const list = (merged.customNodes as unknown as BuilderTemplate[]).map(({ setDefault: _s, ...rest }) => rest as BuilderTemplate);
        page.saveTemplates(list, t.defaultName); pushTemplates();
        page.notify(`Device templates imported: ${merged.added} new, ${merged.replaced} replaced.`);
      }).catch((e) => page.notify(e instanceof Error ? e.message : String(e)));
    },
    requestIconList() { emit({ type: "iconList", icons: [] }); }, uploadIcon: nothing, deleteIcon: nothing, reconcileIcons: nothing,
    exportGrafanaBundle(payload: { requestId: string }) { emit({ type: "svgExportResult", requestId: payload.requestId, success: false, error: "Not available in the lab builder." }); },
    dumpCssVars: nothing,
    saveCustomNode(data: Record<string, unknown>) {
      const t = page.templates(), name = String(data.name ?? ""), old = String(data.oldName ?? name);
      if (!name) { emit({ type: "customNodeError", error: "Give the device template a name." }); return; }
      const { oldName: _o, setDefault, ...rest } = data as Record<string, unknown>;
      const list = t.list.filter((x) => x.name !== old && x.name !== name).concat([{ ...rest, name, kind: String(data.kind ?? "linux") }]);
      page.saveTemplates(list, setDefault ? name : t.defaultName === old ? name : t.defaultName); pushTemplates();
    },
    deleteCustomNode(name: string) { const t = page.templates(); page.saveTemplates(t.list.filter((x) => x.name !== name), t.defaultName === name ? "" : t.defaultName); pushTemplates(); },
    setDefaultCustomNode(name: string) { page.saveTemplates(page.templates().list, name); pushTemplates(); },
    subscribe(h: (e: unknown) => void) { listeners.add(h); return () => { listeners.delete(h); }; }
  };
  const host = createWindowClabUiHost({
    postMessage: nothing,
    topoViewer: topoViewer as never,
    topology: {
      requestSnapshot: () => settled(() => core.getSnapshot()),
      dispatchCommand: (_context, revision, command) => mapOnly && !mapCommandAllowed(command)
        ? Promise.reject(refused("The map editor changes the drawing only: positions, text, shapes, groups and label settings."))
        : settled(() => core.applyCommand(command as never, revision))
    }
  });
  const runtime = createClabUiRuntime({
    host,
    initialContext: { mode, deploymentState: "undeployed", path: yamlPath, sessionId: `builder-${draft.id}` },
    disabledTabIds: ["yaml", "json"]
  });
  window.__DOCKER_IMAGES__ = page.images();
  applyThemeVars("light");
  const t = page.templates();
  const initialData = { dockerImages: page.images(), customNodes: t.list, defaultNode: t.defaultName, customIcons: [] };
  createRoot(document.getElementById("root")!).render(<App initialData={initialData as never} runtime={runtime} />);
  // The editor opens locked because its other hosts show running labs. A builder draft is there to be edited.
  if (useTopoViewerStore.getState().isLocked) useTopoViewerStore.getState().toggleLock();
}

window.labBuilderPage.ready(mount);
