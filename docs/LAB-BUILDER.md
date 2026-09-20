# Lab builder

Draw a new Containerlab lab in the browser, save it to the VM and deploy it, without writing YAML.
The builder is a page of the manager; saving and deploying go through the same reviewed lab
operations as everything else, so nothing about the manager's security boundary changes.

## Build a lab

1. **Manager ▾ › Deploy a new lab** (or *Deploy a new lab* on Home), then **Build a lab visually…**.
   While My labs is still empty, *Build a lab visually…* is on the first page as well.
2. Give the lab a name. The name becomes the lab folder on the VM and part of every device's
   container name, so it is limited to letters, digits, dot, dash and underscore. Choose a starter
   (blank, two devices with a link, three devices in a triangle), the device type for it and the lab
   folder on the VM. The image shown with each device type is a suggestion (see *Device templates and
   images*); the builder does not check that it is installed on the VM.
3. Drag devices from *Node Templates* onto the canvas, or Shift+click the canvas for the starred
   template. Right-click a device for **Create Link** (then click the other device), **Edit Node** and
   **Delete Node**; right-click a link to edit its interfaces or delete it. Interfaces are allocated
   from the template's pattern (`eth1`, `et-0/0/0`, `ge-0/0/0`, `Gi0/0/0/0`). Undo, redo, layouts,
   groups, notes and shapes are in the editor's toolbar. An empty canvas shows how to begin.
4. **View YAML** shows what the editor has built, read-only.
5. **Save to the VM…** opens the usual review: the lab folder that will be created and the YAML that
   will be written. After it succeeds, **Deploy or add this lab…** opens the normal *Topology file*
   dialog with *Deploy lab* and *Add to My labs without starting*.

The editor's *Lab settings* (the gear button) can rename the lab. A draft that is not on the VM yet
takes the new name, in the bar, in *Drafts…* and for the folder it will be saved to. A lab that is
already on the VM keeps its name: the page says so at once and saving stays off until the name is set
back.

The map you drew is what the manager's own Topology tab shows: the builder writes the same
`<file>.annotations.json` layout file as the VS Code Containerlab extension, next to the topology.

## Drafts live in this browser

Until you save, your work is a draft in this browser's storage, never on the manager. **Drafts…**
lists them; **Download draft** gives a `.lab-draft.json` file you can move to another computer or
hand in, and *Open a downloaded draft…* brings one back. Clearing the browser's site data deletes
drafts that were not downloaded or saved to the VM. If the same draft is edited in two tabs, the
older tab stops instead of overwriting the newer work: it offers **Download this version** (what that
tab shows) and **Reload** (the newer version).

When the browser cannot store a change (its storage is full or switched off), the status turns to
*Last change not kept in this browser*, editing pauses and nothing is shown as saved that is not:
**Download this version** still contains your newest work, **Try to store it again** works once older
drafts are deleted, and *Save to the VM* stays off until the change is stored. A browser that refuses
storage altogether (a private window, blocked site data) can still build: the page says that the draft
lives in that tab only and should be downloaded before the tab is closed.

A draft file is checked when it is opened: a topology the manager cannot read is refused with the
reason, and the draft takes the lab name its topology carries.

## Saving again

**Save changes to the VM…** replaces the topology and the layout of a lab that is **not deployed**.
The review shows the difference against the file on the VM, a copy of the previous version is kept
in `.clab-manager-history` in the lab folder, and the save is refused when the file changed on the
VM after you opened it. For a running lab, use *Lab actions › Destroy lab* first. When the lab is
already in My labs, its device list and map follow the saved topology.

One lab is one draft: opening the file a draft was saved to continues that draft. When the lab is
deployed, the page says so as soon as the draft opens, so the destroy is not a surprise after the work.

### When a save does not go through

Nothing is written before the review is confirmed, and a refused save never changes the draft. The
refusal is a dialog that stays: it gives the reason and says that nothing on the VM changed. When the
VM holds a different version than the one the draft started from (an earlier save whose answer never
reached the page, an edit made on the VM, another computer), the dialog offers **Open the VM version**
(the draft stays in *Drafts…*) and **Review the differences…**, which turns the next save into a
revision of the version that is on the VM now: the review shows every difference, the previous file
is kept in `.clab-manager-history`, and a deployed lab is still refused. A folder that carries another
lab's name is never offered this way; the dialog then says whose it is. A save that did reach the VM
while the page never heard of it (a closed tab, a lost connection) is recognised the next time the
draft opens and the VM can be asked, also when the draft was edited in between (it then shows as
saved with newer changes), or when the same content is saved again.

An existing topology file opens in the builder with **Edit visually…** in the *Topology file*
dialog. Opening a file never changes it. Editing can drop a YAML comment on an edited link or on a
key the editor removes, and a renamed device moves to the end of the list; settings are kept,
including ones the editor has no field for. A topology the editor cannot parse (a YAML syntax error,
the same key twice in one block) is not opened for editing, because the editor would accept edits to
it and keep none; the page names the problem and its line, and the file has to be corrected as text.

## Device templates and images

The templates cover the kinds the manager has drivers for (Arista cEOS, Juniper cJunosEvolved and
vJunos-switch, Cisco XRv9k) plus a Linux host. Each takes the image this site already uses for its
kind, read from the topologies in My labs; otherwise a placeholder you can change. Edit, add and
star templates in the palette; they are kept in this browser. The image field is free text, and the
manager cannot see which images exist on the VM: a wrong image name fails at deploy time. The
operation output then names the images the VM does not have; correct them with *Edit visually…* (the
device's *Image* field), save the change and deploy again. *Import templates* and *Export templates*
in the palette move a template list between browsers.

Any Containerlab kind can be used. A kind without a manager driver deploys normally and shows
*Choose NOS* in the workspace (no automatic login, backup or readiness). A kind the VM's Containerlab
does not know fails at deploy time; the editor's list of kinds comes with the editor and can be
newer than the VM's Containerlab.

## What is on the VM

```text
<lab folder>/<lab>/<lab>.clab.yml
<lab folder>/<lab>/<lab>.clab.yml.annotations.json
```

`<lab folder>` is one of the trusted lab folders (by default
`/srv/containerlab-node-manager/projects`). The VM helper derives both paths from the lab name,
writes the layout first and the topology last (the file browser lists topologies, so a lab appears
complete or not at all), never replaces an existing folder or file, and treats a repeated save with
identical content as already done. A save interrupted half way is completed by saving again.

## Limits of this version

- Topology only: no startup-configuration files, no Git destination, no image management.
- The editor's YAML and JSON tabs, Geo layout, split view, Grafana export and its own deploy menu are
  not available; the manager's review and deploy replace the last one.
- Saving needs the VM helpers of the same release as the manager. After an upgrade run
  `sudo bash "$HOME/projects/clab-manager/deploy/start-manager.sh"`; until then the page says that
  saving is unavailable and drafts can still be built and downloaded.

## Third-party software

The editor is SR Labs' containerlab topology editor (`@containerlab/clab-ui`, Apache-2.0), bundled
unmodified under `clab-backup-ui/app/static/lab-builder/` with its licence and the generated
[third-party notices](../clab-backup-ui/app/static/lab-builder/THIRD-PARTY-NOTICES.txt); see
[deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md](../deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md).
Maintainers rebuild it with `npm ci && node build.mjs` in `clab-backup-ui/lab-builder/` (Node 24);
it is never built on a lab VM, and CI checks that the committed files match a fresh build.
