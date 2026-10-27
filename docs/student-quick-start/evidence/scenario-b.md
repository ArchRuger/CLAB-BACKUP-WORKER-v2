# Scenario B: build your own lab and keep it in Git — evidence

Manager: `http://127.0.0.1:8081`
Run: 2026-10-27T04:09:28Z — 2026-10-27T04:15:39Z

## Step 1: Start a new lab in the builder — PASS

Observed:
- **welcome_text**: Build a lab

Draw the devices and the links of a new Containerlab lab, then save it to the VM and deploy it. Your work is kept as a draft in this browser until you save it.

New lab…
Open a draft…

Drop a lab file here (.clab.yml, optionally with its .annotations.json)

Open lab files…
Accepts a containerlab topology (.clab.yml, .clab.yaml, .yml or .yaml) and, optionally, its saved map (a matching *.annotations.json file).
- **new_lab_dialog**: New lab
×
Lab name

Letters, digits, dot, dash and underscore. The name becomes the lab folder on the VM and part of every device's container name. The lab starts as a blank canvas; drag devices from the palette to build it.

Lab folder on the VM
/etc/containerlab
/srv/containerlab-node-manager/projects
Cancel
Create draft
- **builder_bar**: ← My labs
Lab builder
my-first-lab
Draft · kept in this browser only · not on the VM yet
Drafts…
Download draft
YAML
Undo
Redo
Save to the VM…
- **blank_canvas_hint**: Drag a device from the palette on the right onto the canvas to begin. Right-click a device to link it, edit it or delete it.
- **palette_templates**: True

Screenshots:
- `b1-builder-welcome-full.png` (full-page)
- `b1-new-lab-dialog-full.png` (full-page)
- `b1-new-lab-dialog.png` (New lab)
- `b1-blank-canvas-full.png` (full-page)

## Step 2: Draw and check the topology — PASS

Actions:
- Drag Arista cEOS from the palette twice; put the devices side by side
- Right-click the first device > Create Link, click the second
- Edit Node on each device: name r1 / r2, Management IPv4 172.20.20.21 / .22, Apply
- Right-click empty canvas > Add Text

Observed:
- **nodes**: ['ceos1', 'ceos2']
- **edges**: 1
- **r1_image_version**: n24l/ceos 4.35.0F
- **r2_image_version**: n24l/ceos 4.35.0F
- **canvas_menu**: ['Add Node', 'Add Group', 'Add Text', 'Add Shape', 'Add Traffic Rate', 'Open Palette']
- **yaml**: name: my-first-lab
topology:
  nodes:
    r1:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.21
    r2:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.22
  links:
    - endpoints: [ "r1:eth1", "r2:eth1" ]

- **yaml_shows_both_images_and_addresses**: True

Screenshots:
- `b2-node-editor-r1-full.png` (full-page)
- `b2-node-editor-r1.png` (Node Editor: r1)
- `b2-canvas-finished-full.png` (full-page)
- `b2-canvas-finished.png` (Finished canvas)
- `b2-yaml-full.png` (full-page)

## Step 3: Save to the VM and deploy — PASS

Actions:
- Home > the my-first-lab card > Open lab (the builder page does not open the lab itself)

Observed:
- **save_review**: Save my-first-lab to the VM?
×

my-first-lab

/srv/containerlab-node-manager/projects/my-first-lab/my-first-lab.clab.yml

Creates the lab folder /srv/containerlab-node-manager/projects/my-first-lab on the VM with the topology file and the map layout. Nothing on the VM is overwritten and no devices are started until you deploy it.

Topology that will be saved (YAML)
name: my-first-lab
topology:
  nodes:
    r1:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.21
    r2:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.22
  links:
    - endpoints: [ "r1:eth1", "r2:eth1" ]


Runs on the lab VM. If the lab changes before you confirm, this check is repeated.

Cancel
Save lab
- **save_result_dialog**: Save lab to the VM · my-first-lab
×
✔ Save lab to the VM succeeded
my-first-lab · Operation completed
Exit code 0
Copy output
Lab folder saved on the VM: /srv/containerlab-node-manager/projects/my-first-lab


Saved as /srv/containerlab-node-manager/projects/my-first-lab/my-first-lab.clab.yml. It is not running yet.

Add it to My labs to keep it with your other labs, or deploy it now (the deploy shows what it will do and asks you to confirm first).

Add to My labs without starting
Deploy now
- **builder_status_after_save**: Saved on the VM
- **save_button_after_save**: Save changes to the VM…
- **deploy_now_opens**: the Start review
- **start_review_title**: Start my-first-lab?
- **deploy_banner**: ✔ Save lab to the VM succeeded
my-first-lab · Operation completed
Exit code 0
- **vm_folder**: ['clab-my-first-lab', 'my-first-lab.clab.yml', 'my-first-lab.clab.yml.annotations.json']
- **lab_id**: 820b8d1c98e1477ea99328e1ea5dab17

Screenshots:
- `b3-save-review-full.png` (full-page)
- `b3-save-review.png` (Save my-first-lab to the VM?)
- `b3-save-result-full.png` (full-page)
- `b3-save-result.png` (Save lab result)
- `b3-start-review-full.png` (full-page)
- `b3-start-review.png` (Start my-first-lab?)

## Step 4: Bring the link up — PASS

Actions:
- clab-my-first-lab-r1: ip routing, Ethernet1 no switchport, ip address 10.0.0.1/30, write memory
- clab-my-first-lab-r2: ip routing, Ethernet1 no switchport, ip address 10.0.0.2/30, write memory

Observed:
- **deploy_to_ready_seconds**: 30.4
- **pills**: ['Ready', 'Ready']
- **ping_ok**: True

Device evidence (eos.py, direct SSH):
- **r1_ping**: enable
r1#ping 10.0.0.2 repeat 3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.
80 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.093 ms
80 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.023 ms
80 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.015 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.015/0.043/0.093/0.035 ms, ipg/ewma 0.114/0.075 ms
r1#
- **r1_show_ip_interface_brief**: enable
r1#show ip interface brief
                                                                               Address
Interface         IP Address            Status       Protocol           MTU    Owner
----------------- --------------------- ------------ -------------- ---------- -------
Ethernet1         10.0.0.1/30           up           up                1500
Management0       172.20.20.21/24       up           up                1500

r1#
- **r2_show_ip_interface_brief**: enable
r2#show ip interface brief
                                                                               Address
Interface         IP Address            Status       Protocol           MTU    Owner
----------------- --------------------- ------------ -------------- ---------- -------
Ethernet1         10.0.0.2/30           up           up                1500
Management0       172.20.20.22/24       up           up                1500

r2#

Screenshots:
- `b4-devices-ready-full.png` (full-page)
- `b4-ping-full.png` (full-page)
- `b4-ping.png` (r1: ping 10.0.0.2)

## Step 5: Your own repository on GitHub — PASS

Remote evidence (GitHub):
- **gh_repo_view**: {"createdAt":"2026-10-27T02:53:44Z","defaultBranchRef":{"name":"main"},"url":"https://github.com/ArchRuger/campaign2-my-network-labs","visibility":"PRIVATE"}
- **tree_before_first_save**: ['README.md']

Notes:
- The repository was created before the replay with: gh repo create ArchRuger/campaign2-my-network-labs --private --add-readme (the guide tells the student to do it in the browser or with that command).

## Step 6: Connect the repository; the first save — PASS

Observed:
- **chip_before**: Not saved yet
- **connect_first_save_panel**: Not saved yet

Your first save goes to campaign2-netlab-course-student, in a folder named my-first-lab.

Save
Choose another place
Connect by URL…

Uploads go to github.com/ArchRuger/campaign2-netlab-course-student, branch main.

Saved files can contain passwords or keys.

Save as a lab state…
- **connect_drawer_text**: Where should my-first-lab save?

Pick a folder, type a path, or make a new folder.

Repository address (HTTPS)

The lab VM’s own GitHub login is used. You are never asked for a password or a token here.

Use a repository on this VM
Folder

Saves go to
campaign2-my-network-labs
›
my-first-lab

The folders of this repository are listed once it is connected.

Cancel
Save here

Saved files can contain passwords or keys.
- **connect_path**: saved at once
- **connect_seconds_to_save_on_vm**: 6.9
- **connect_save_sentence**: Not uploaded yet

This is the first save here: 2 devices, the topology and the map.

To: campaign2-my-network-labs › my-first-lab

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-my-network-labs › my-first-lab
Change…

All versions
Save as a lab state…
Save settings
- **connect_chip**: 1 save to upload
- **see-changes_drawer**: What changed

This is the first save here: 2 devices, the topology and the map. Not uploaded yet.

Upload
Not now
View files

To: campaign2-my-network-labs › my-first-lab/latest

Saved files can contain passwords or keys.

THIS SAVE
Topology file my-first-lab.clab.yml added

13 added · 0 removed

Before this save / This save
@@ -0,1 +1,14 @@
	1	+	name: my-first-lab
	2	+	topology:
	3	+	  nodes:
	4	+	    r1:
	5	+	      kind: arista_ceos
	6	+	      image: n24l/ceos:4.35.0F
	7	+	      mgmt-ipv4: 172.20.20.21
	8	+	    r2:
	9	+	      kind: arista_ceos
	10	+	      image: n24l/ceos:4.35.0F
	11	+	      mgmt-ipv4: 172.20.20.22
	12	+	  links:
	13	+	    - endpoints: [ "r1:eth1", "r2:eth1" ]
1	14
Map my-first-lab.clab.yml.annotations.json added

46 added · 1 removed

Before this save / This save
@@ -1,1 +1,46 @@
1		-
	1	+	{
	2	+	  "freeTextAnnotations": [
	3	+	    {
	4	+	      "id": "freeText_1793074204681",
	5	+	      "text": "My first lab: r1 eth1 - r2 eth1",
	6	+	      "position": {
	7	+	        "x": 163.5,
	8	+	        "y": 356.8046875
	9	+	      },
	10	+	      "fontSize": 14,
	11	+	      "fontColor": "#333333",
	12	+	      "fontWeight": "normal",
	13	+	      "fontStyle": "normal",
	14	+	      "textDecoration": "none",
	15	+	      "textAlign": "left",
	16	+	      "fontFamily": "Arial"
	17	+	    }
	18	+	  ],
	19	+	  "freeShapeAnnotations": [],
	20	+	  "trafficRateAnnotations": [],
	21	+	  "groupStyleAnnotations": [],
	22	+	  "networkNodeAnnotations": [],
	23	+	  "nodeAnnotations": [
	24	+	    {
	25	+	      "id": "r1",
	26	+	      "position": {
	27	+	        "x": 40,
	28	+	        "y": 220
	29	+	      },
	30	+	      "icon": "switch",
	31	+	      "interfacePattern": "eth{n}"
	32	+	    },
	33	+	    {
	34	+	      "id": "r2",
	35	+	      "position": {
	36	+	        "x": 260,
	37	+
- **see-changes_files**: ['Topology file my-first-lab.clab.yml added', 'Map my-first-lab.clab.yml.annotations.json added', 'r1 r1.cfg added', 'r2 r2.cfg added']
- **panel_after_upload**: Saved just now
Name of this save
Keep as a checkpoint

Running: your latest save

Uploaded: yes, to github.com

Saves to:
campaign2-my-network-labs › my-first-lab
Change…

All versions
Save as a lab state…
Save settings
- **chip_after_upload**: Saved just now

Remote evidence (GitHub):
- **first_save_files**: {'my-first-lab/latest/manifest.json': True, 'my-first-lab/latest/my-first-lab.clab.yml': True, 'my-first-lab/latest/my-first-lab.clab.yml.annotations.json': True, 'my-first-lab/latest/r1.cfg': True, 'my-first-lab/latest/r1.eoscfg': True, 'my-first-lab/latest/r2.cfg': True, 'my-first-lab/latest/r2.eoscfg': True}
- **tree**: ['README.md', 'my-first-lab/latest/manifest.json', 'my-first-lab/latest/my-first-lab.clab.yml', 'my-first-lab/latest/my-first-lab.clab.yml.annotations.json', 'my-first-lab/latest/r1.cfg', 'my-first-lab/latest/r1.eoscfg', 'my-first-lab/latest/r2.cfg', 'my-first-lab/latest/r2.eoscfg']

Screenshots:
- `b6-connect-chip-first-save-full.png` (full-page)
- `b6-connect-drawer-full.png` (full-page)
- `b6-connect-drawer.png` (Where should the lab save?)
- `b6-first-save-panel-full.png` (full-page)
- `b6-see-changes-full.png` (full-page)
- `b6-see-changes.png` (What changed)
- `b6-saved-panel-full.png` (full-page)

## Step 7: Check GitHub and browse the same tree in the manager — PASS

Observed:
- **all_versions**: All versions

Everything saved for my-first-lab. Choose one to load it.

YOUR SAVES
First save
just now
CHECKPOINTS

No checkpoints yet. Keep a save as a checkpoint to hold on to it.

STARTING POINT

No starting point yet.

Choose a backup as starting point…
LAB STATES
Save as a lab state…

No lab states in this repository yet.

Full history…
Browse the repository…
- **browse_text**: Back
Browse the repository

Every folder of campaign2-my-network-labs. Looking at folders does not change where my-first-lab saves.

campaign2-my-network-labs
top level
my-first-lab
This lab saves here
latest
New folder…
Name	Size

my-first-lab
	7.1 KB

README.md
	91 B

Remote evidence (GitHub):
- **tree**: ['README.md', 'my-first-lab/latest/manifest.json', 'my-first-lab/latest/my-first-lab.clab.yml', 'my-first-lab/latest/my-first-lab.clab.yml.annotations.json', 'my-first-lab/latest/r1.cfg', 'my-first-lab/latest/r1.eoscfg', 'my-first-lab/latest/r2.cfg', 'my-first-lab/latest/r2.eoscfg']

Screenshots:
- `b7-all-versions-full.png` (full-page)
- `b7-remote-tree-full.png` (full-page)
- `b7-remote-tree.png` (Browse the repository)

## Step 8: Change, save, and checkpoint again — PASS

Actions:
- r2 CLI: enable; configure terminal; interface Loopback0; description r2 loopback; ip address 10.255.0.2/32; end; write memory

Observed:
- **r2_loopback_present**: True
- **save2_seconds_to_commit**: 6.1
- **save2_panel**: Not uploaded yet

1 device changed since your last save: r2. 4 lines added, 0 removed.

To: campaign2-my-network-labs › my-first-lab

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-my-network-labs › my-first-lab
Change…

All versions
Save as a lab state…
Save settings
- **save2_seconds_to_uploaded**: 12.5
- **save2_chip**: Saved just now
- **name_before**: r2 changed
- **checkpoint_panel**: Not uploaded yet

Checkpoint link-up kept. It is not uploaded yet.

To: campaign2-my-network-labs › my-first-lab

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-my-network-labs › my-first-lab
Change…

All versions
Save as a lab state…
Save settings
- **chip_after_checkpoint**: Saved just now
- **all_versions**: All versions

Everything saved for my-first-lab. Choose one to load it.

YOUR SAVES
link-up
just now
First save
1 minute ago
CHECKPOINTS
link-up
just now
STARTING POINT

No starting point yet.

Choose a backup as starting point…
LAB STATES
Save as a lab state…

No lab states in this repository yet.

Save activity (1)
Full history…
Browse the repository…

Device evidence (eos.py, direct SSH):
- **r2_show_ip_interface_brief**:                                          Address
Interface         IP Address            Status       Protocol            MTU    Owner
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.2/30           up           up                 1500
Loopback0         10.255.0.2/32         up           up                65535
Management0       172.20.20.22/24       up           up                 1500

r2#

Remote evidence (GitHub):
- **latest_r2_has_loopback0**: True
- **checkpoint_r2_has_loopback0**: True
- **checkpoint_files**: ['my-first-lab/checkpoints/link-up', 'my-first-lab/checkpoints/link-up/manifest.json', 'my-first-lab/checkpoints/link-up/my-first-lab.clab.yml', 'my-first-lab/checkpoints/link-up/my-first-lab.clab.yml.annotations.json', 'my-first-lab/checkpoints/link-up/r1.cfg', 'my-first-lab/checkpoints/link-up/r1.eoscfg', 'my-first-lab/checkpoints/link-up/r2.cfg', 'my-first-lab/checkpoints/link-up/r2.eoscfg']
- **no_nested_latest_latest**: True

Screenshots:
- `b8-save2-panel-full.png` (full-page)
- `b8-name-and-keep-full.png` (full-page)
- `b8-checkpoint-kept-full.png` (full-page)
- `b8-all-versions-full.png` (full-page)
- `b8-all-versions.png` (All versions)

## Step 9: Prove it: destroy, remove, rebuild from Git — PASS

Observed:
- **destroy_review**: Destroy my-first-lab?
×

my-first-lab

/srv/containerlab-node-manager/projects/my-first-lab/my-first-lab.clab.yml

The running devices are removed from the VM. Configuration changes you have not saved are lost. Your saves, lab states and backups remain.

Run with options

Last saved just now.

Open CLI sessions to this lab will disconnect.

2 running devices affected

Technical details

Runs on the lab VM. If the lab changes before you confirm, this check is repeated.

Cancel
Save first
Destroy lab
- **lab_state_after_destroy**: Stopped
- **remove_review**: Remove my-first-lab from this manager?
×

This removes the lab from My labs: its device list, map, saved device logins, backup schedule and backup history entries. Backup files stay on this VM's disk.

Nothing on the lab VM changes: the running devices and the topology files stay. What you saved stays in its repository.

Don't offer this lab for import again

Untick it if you want the lab to be offered again under Manager ▾ › Labs found on the VM…. Either way, adding it back needs your confirmation.

Cancel
Remove lab
- **containers_after_remove**: []
- **original_folder_still_on_vm**: True
- **cloned_topology_path**: /srv/containerlab-node-manager/projects/campaign2-my-network-labs/my-first-lab/latest/my-first-lab.clab.yml
- **vm_project_path**: /srv/containerlab-node-manager/projects/campaign2-my-network-labs/my-first-lab/latest/my-first-lab.clab.yml
- **redeploy_to_ready_seconds**: 36.4
- **ping_works_before_load**: False
- **chip_rebuilt**: Not saved yet

Looking for a place to save…

Save as a lab state…
- **load_list_rebuilt**: Load a saved state

This lab has no saves of its own yet. You can start from one of these.

LAB STATES
Broken-01
0 of 2 devices
Solution
0 of 2 devices
Start
0 of 2 devices

From campaign2-netlab-course-student.

All versions
Browse the repository…
- **reconnect_question**: Where should my-first-lab save?

Pick a folder, type a path, or make a new folder.

Repository
campaign2-my-network-labs
campaign2-netlab-course-student
clab-scratch-git-redesign
clab-scratch-git-redesign-empty

Uploads go to github.com/ArchRuger/campaign2-my-network-labs, branch main.

Connect by URL…
Folder

Saves go to
campaign2-my-network-labs
›
my-first-lab

campaign2-my-network-labs
top level
my-first-lab
Lab state: My-first-lab
New folder…

This folder holds the state “My-first-lab”.

If you replace it, the next save of my-first-lab replaces its files. The older contents stay in the Git history.

Cancel
Save beside it in my-first-lab/my-first-lab
Replace it

Saved files can contain passwords or keys.
- **reconnect_seconds**: 8.3
- **reconnect_sentence**: Not uploaded yet

2 devices changed since your last save: r1 and r2. 4 lines added, 12 removed.

To: campaign2-my-network-labs › my-first-lab

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-my-network-labs › my-first-lab
Change…

All versions
Save as a lab state…
Save settings
- **chip_after_not_now**: 1 save to upload
- **loadcp_list**: Load a saved state
YOUR SAVES
r1 and r2 changed
just now
link-up
2 minutes ago
All versions
Browse the repository…
- **loadcp_confirmation**: Load link-up?

The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.

Saved 2 minutes ago.

r1 EOS
6 lines differ
r2 EOS
9 lines differ

Each device checks the new configuration itself and undoes it if it loses contact.

Options
Load
Cancel
See what’s different
- **loadcp_seconds**: 11.4
- **loadcp_chip**: Running link-up
- **loaded**: link-up
- **ping_ok_after_load**: True
- **r2_loopback_back**: True
- **chip_panel_after_load**: Running link-up

Loaded just now on all 2 devices.

Your latest save: r1 and r2 changed, just now

Before loading: backed up automatically

Undo this load
What changed

Saves to:
campaign2-my-network-labs › my-first-lab
Change…

Also: 1 save to upload. Show

All versions
Save as a lab state…
Save settings
- **final_seconds_to_commit**: 5.1
- **final_panel**: Not uploaded yet

2 devices changed since your last save: r1 and r2. 12 lines added, 4 removed. This upload also sends 1 other save: r1 and r2 changed (my-first-lab).

To: campaign2-my-network-labs › my-first-lab

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-my-network-labs › my-first-lab
Change…

Last load:
link-up, just now
Details

All versions
Save as a lab state…
Save settings
- **final_seconds_to_uploaded**: 11.5
- **final_chip**: Saved just now

Device evidence (eos.py, direct SSH):
- **r1_ping_fresh**: enable
r1#ping 10.0.0.2 repeat 2
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.

- **r2_show_ip_interface_brief**:                                          Address
Interface         IP Address            Status       Protocol            MTU    Owner
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.2/30           up           up                 1500
Loopback0         10.255.0.2/32         up           up                65535
Management0       172.20.20.22/24       up           up                 1500

r2#

Remote evidence (GitHub):
- **clone_transcript**: [('git clone https://github.com/ArchRuger/campaign2-my-network-labs.git /srv/containerlab-node-manager/projects/campaign2-my-network-labs', "Cloning into '/srv/containerlab-node-manager/projects/campaign2-my-network-labs'...\n"), ('ls -R /srv/containerlab-node-manager/projects/campaign2-my-network-labs/my-first-lab', '/srv/containerlab-node-manager/projects/campaign2-my-network-labs/my-first-lab:\ncheckpoints\nlatest\n\n/srv/containerlab-node-manager/projects/campaign2-my-network-labs/my-first-lab/checkpoints:\nlink-up\n\n/srv/containerlab-node-manager/projects/campaign2-my-network-labs/my-first-lab/checkpoints/link-up:\nmanifest.json\nmy-first-lab.clab.yml\nmy-first-lab.clab.yml.annotations.json\nr1.cfg\nr1.eoscfg\nr2.cfg\nr2.eoscfg\n\n/srv/containerlab-node-manager/projects/campaign2-my-network-labs/my-first-lab/latest:\nmanifest.json\nmy-first-lab.clab.yml\nmy-first-lab.clab.yml.annotations.json\nr1.cfg\nr1.eoscfg\nr2.cfg\nr2.eoscfg\n')]
- **latest_r2_has_loopback0_after_rebuild**: True
- **latest_r1_has_10_0_0_1_after_rebuild**: True

Screenshots:
- `b9-destroy-review-full.png` (full-page)
- `b9-destroy-review.png` (Destroy my-first-lab?)
- `b9-destroyed-full.png` (full-page)
- `b9-remove-review-full.png` (full-page)
- `b9-remove-review.png` (Remove from this manager)
- `b9-terminal-clone.png` (rendered transcript)
- `b9-file-picker.png` (Deploy a new lab (clone))
- `b9-redeploy-topology-file-full.png` (full-page)
- `b9-redeploy-topology-file.png` (Topology file (clone))
- `b9-rebuilt-topology-full.png` (full-page)
- `b9-rebuilt-load-list-full.png` (full-page)
- `b9-reconnect-question-full.png` (full-page)
- `b9-reconnect-question.png` (This folder holds the state)
- `b9-reconnect-saved-full.png` (full-page)
- `b9-loadcp-list-full.png` (full-page)
- `b9-loadcp-confirm-full.png` (full-page)
- `b9-link-up-loaded-full.png` (full-page)
- `b9-final-panel-full.png` (full-page)

Notes:
- (authoring only) sudo mv /srv/containerlab-node-manager/projects/my-first-lab /srv/containerlab-node-manager/projects/../projects-aside-qs/my-first-lab.original: rc=1; the guide tells the student to read the path in the Topology file dialog instead
