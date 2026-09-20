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
import { parseDocument } from "yaml";
import "@containerlab/clab-ui/styles/global.css";

interface BuilderDraft { id: string; name: string; yaml: string; annotations: string }
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
}
declare global { interface Window { labBuilderPage: BuilderPage; __DOCKER_IMAGES__?: string[] } }

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
  const core = new TopologySessionCore({
    fs: files, yamlFilePath: yamlPath, mode: "edit", deploymentState: "undeployed",
    logger: { debug() {}, info() {}, warn() {}, error: (m: unknown) => console.error(m) }
  });
  // One engine operation at a time, and the draft is stored before the editor hears the answer: an
  // acknowledged edit is already durable, and a half-finished rename sequence is never stored.
  let queue: Promise<unknown> = Promise.resolve();
  const settled = <T,>(work: () => Promise<T>): Promise<T> => {
    const run = queue.then(work).then((value) => {
      try { page.persist(files.files.get(yamlPath) ?? "", files.files.get(layoutPath) ?? ""); }
      catch (e) { page.problem(e instanceof Error ? e.message : String(e), (e as { code?: string }).code); throw e; }
      return value;
    });
    queue = run.catch(() => undefined);
    return run;
  };

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
        page.saveTemplates(merged.customNodes as never, t.defaultName); pushTemplates();
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
      dispatchCommand: (_context, revision, command) => settled(() => core.applyCommand(command as never, revision))
    }
  });
  const runtime = createClabUiRuntime({
    host,
    initialContext: { mode: "edit", deploymentState: "undeployed", path: yamlPath, sessionId: `builder-${draft.id}` },
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
