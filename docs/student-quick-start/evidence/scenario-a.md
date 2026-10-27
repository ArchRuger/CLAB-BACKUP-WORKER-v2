# Scenario A: use an instructor's lab — evidence

Manager: `http://127.0.0.1:8081`
Run: 2026-10-27T03:30:43Z — 2026-10-27T03:43:16Z

## Step 1: Home: Deploy and Build boxes — PASS

Actions:
- Open the manager address

Observed:
- **home_title**: My labs
- **deploy_box**: Deploy
- **build_box**: Build
- **lab_cards_on_this_manager**: ['parity', 'camp-topo', 'camp-vsrx', 'git-redesign', 'git-redesign-b']

Screenshots:
- `a1-home-full.png` (full-page)

Notes:
- The development manager already lists other labs; the figure is cropped to the Deploy and Build boxes. A new installation reads "No labs yet".

## Step 2: Deploy link-basics from the lab VM — PASS

Actions:
- Click "Choose a file on the lab VM…"
- Open /srv/containerlab-node-manager/projects, then link-basics
- Click ◇ link-basics.clab.yml
- Click "Deploy lab"
- Click "Start lab"

Observed:
- **topology_path_field**: /srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml
- **editor_buttons**: ['×', 'Preview topology', 'Edit topology…', 'Add to My labs without starting', 'Deploy lab']
- **editor_title**: Topology file
- **review_title**: Start link-basics?
- **review_text**: Start link-basics?
×

link-basics

/srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml

Creates and starts the devices in this topology as its file describes them, including any hooks, mounts and image pulls. Nothing is deleted; device logins open as the devices boot.

Run with options
Command run on the VM
"/usr/bin/containerlab" "deploy" "-t" "/srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml" "--name" "link-basics"
Cancel
Start lab
- **confirm_button**: Start lab
- **lab_id**: d7ea15c5ccb54f7b8bc0d27e404cc5c9
- **hash_after_confirm**: #lab=d7ea15c5ccb54f7b8bc0d27e404cc5c9&view=topology

Screenshots:
- `a2-file-picker.png` (Deploy a new lab (folders))
- `a2-topology-file.png` (Topology file)
- `a2-start-review.png` (Start link-basics?)

Notes:
- waited 0.1s for other work on the shared manager to finish

## Step 3: Starting, then Ready — PASS

Observed:
- **header_state_starting**: Starting lab
- **header_ready_starting**: 0 of 2 devices ready
- **chip_starting**: Not saved yet
- **device_pills_starting**: ['Starting', 'Starting']
- **deploy_to_ready_seconds**: 46.8
- **header_state_ready**: Running
- **header_ready_ready**: 2 of 2 devices ready
- **chip_ready**: Not saved yet

Screenshots:
- `a3-devices-starting-full.png` (full-page)
- `a3-devices-ready-full.png` (full-page)

## Step 4: Look around from the command line — PASS

Actions:
- Devices tab > Open CLI next to r1; wait for Connected

Observed:
- **topology_toolbar**: ['Import map…', 'Fit', '+', '−', 'Expand', 'Edit map', 'Edit topology…', 'Clear impairments', 'More ', 'Edit map', 'Edit topology…', 'Import map…']
- **et1_connected**: True

Device evidence (eos.py, direct SSH):
- **r1_show_interfaces_status**: enable
r1#show interfaces status
Port       Name   Status       Vlan     Duplex Speed  Type            Flags Encapsulation
Et1               connected    1        full   1G     EbraTestPhyPort
Ma0               connected    routed   a-full a-1G   10/100/1000

r1#
- **r1_show_ip_interface_brief**: enable
r1#show ip interface brief
                                                                               Address
Interface         IP Address            Status       Protocol           MTU    Owner
----------------- --------------------- ------------ -------------- ---------- -------
Management0       172.20.20.11/24       up           up                1500

r1#

Screenshots:
- `a4-topology-full.png` (full-page)
- `a4-r1-terminal-full.png` (full-page)
- `a4-r1-terminal.png` (r1 CLI)

## Step 5: Connect your repository (the first save) — PASS

Actions:
- Click the chip (Not saved yet), then Connect by URL…
- Click Save here
- See changes > Upload

Observed:
- **chip_before**: Not saved yet
- **first_save_panel**: Not saved yet

Your first save goes to clab-scratch-git-redesign, in a folder named link-basics.

Save
Choose another place
Connect by URL…

Uploads go to github.com/ArchRuger/clab-scratch-git-redesign, branch main.

Saved files can contain passwords or keys.

Save as a lab state…
- **drawer_text**: Where should link-basics save?

Pick a folder, type a path, or make a new folder.

Repository address (HTTPS)

The lab VM’s own GitHub login is used. You are never asked for a password or a token here.

Use a repository on this VM
Folder

Saves go to
campaign2-netlab-course-student
›
link-basics/work

The folders of this repository are listed once it is connected.

Cancel
Save here

Saved files can contain passwords or keys.
- **connect_path**: saved at once
- **seconds_to_first_save_on_vm**: 8.0
- **first_save_sentence**: Not uploaded yet

This is the first save here: 2 devices, the topology and the map.

To: campaign2-netlab-course-student › link-basics/work

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

All versions
Save as a lab state…
Save settings
- **chip_after_connect**: 1 save to upload
- **see_changes_files**: ['Topology file link-basics.clab.yml added', 'Map link-basics.clab.yml.annotations.json added', 'r1 r1.cfg added', 'r2 r2.cfg added']
- **seconds_to_uploaded**: 15.5
- **chip_after_upload**: Saved just now
- **panel_after_upload**: Saved just now
Name of this save
Keep as a checkpoint

Running: your latest save

Uploaded: yes, to github.com

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

All versions
Save as a lab state…
Save settings

Remote evidence (GitHub):
- **first_save_files**: {'link-basics/work/latest/manifest.json': True, 'link-basics/work/latest/link-basics.clab.yml': True, 'link-basics/work/latest/link-basics.clab.yml.annotations.json': True, 'link-basics/work/latest/r1.cfg': True, 'link-basics/work/latest/r1.eoscfg': True, 'link-basics/work/latest/r2.cfg': True, 'link-basics/work/latest/r2.eoscfg': True}

Screenshots:
- `a5-chip-first-save-full.png` (full-page)
- `a5-connect-drawer-full.png` (full-page)
- `a5-connect-drawer.png` (Where should link-basics save?)
- `a5-first-save-panel-full.png` (full-page)
- `a5-see-changes-full.png` (full-page)
- `a5-see-changes.png` (What changed (first save))
- `a5-saved-panel-full.png` (full-page)

## Step 6: Load the Start state — PASS

Actions:
- Load > Start > red Load

Observed:
- **start_list**: Load a saved state
YOUR SAVES
First save
2 minutes ago
LAB STATES
Broken-01
2 devices
Solution
2 devices
Start
2 devices
All versions
Browse the repository…
- **start_confirmation**: Load Start?

The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.

Saved Sep 22, 2026.

r1 EOS
6 lines differ
r2 EOS
6 lines differ

Each device checks the new configuration itself and undoes it if it loses contact.

Options
Load
Cancel
See what’s different
- **start_seconds**: 9.3
- **start_chip**: Running Start
- **chip_panel_after_load**: Running Start

Loaded just now on all 2 devices.

Your latest save: First save, 2 minutes ago

Before loading: backed up automatically

Undo this load
What changed

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

All versions
Save as a lab state…
Save settings
- **ping_ok**: True

Device evidence (eos.py, direct SSH):
- **r1_ping**: enable
r1#ping 10.0.0.2 repeat 3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.
80 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.091 ms
80 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.005 ms
80 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.004 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.004/0.033/0.091/0.040 ms, ipg/ewma 0.061/0.070 ms
r1#
- **r1_show_ip_interface_brief**: enable
r1#show ip interface brief
                                                                               Address
Interface         IP Address            Status       Protocol           MTU    Owner
----------------- --------------------- ------------ -------------- ---------- -------
Ethernet1         10.0.0.1/30           up           up                1500
Management0       172.20.20.11/24       up           up                1500

r1#
- **r2_show_ip_interface_brief**: enable
r2#show ip interface brief
                                                                               Address
Interface         IP Address            Status       Protocol           MTU    Owner
----------------- --------------------- ------------ -------------- ---------- -------
Ethernet1         10.0.0.2/30           up           up                1500
Management0       172.20.20.12/24       up           up                1500

r2#

Screenshots:
- `a6-start-list-full.png` (full-page)
- `a6-start-confirm-full.png` (full-page)
- `a6-start-loaded-full.png` (full-page)

## Step 7: Make a change on r1 — PASS

Actions:
- r1 CLI: enable
- r1 CLI: configure terminal
- r1 CLI: interface Loopback0
- r1 CLI: description r1 loopback
- r1 CLI: ip address 10.255.0.1/32
- r1 CLI: end
- r1 CLI: write memory
- r1 CLI: show ip interface brief

Observed:
- **loopback0_present**: True

Device evidence (eos.py, direct SSH):
- **r1_show_ip_interface_brief**:                                          Address
Interface         IP Address            Status       Protocol            MTU    Owner
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.1/30           up           up                 1500
Loopback0         10.255.0.1/32         up           up                65535
Management0       172.20.20.11/24       up           up                 1500

r1#

Screenshots:
- `a7-r1-loopback-full.png` (full-page)
- `a7-r1-loopback.png` (r1 CLI after the change)

## Step 8: Save, look at the changes, upload — PASS

Actions:
- Save in the lab header; the chip panel opens
- See changes > Upload

Observed:
- **chip_before**: Running Start
- **save2_seconds_to_commit**: 6.1
- **save2_panel**: Not uploaded yet

2 devices changed since your last save: r1 and r2. 12 lines added, 4 removed.

To: campaign2-netlab-course-student › link-basics/work

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

Last load:
Start, 1 minute ago
Details

All versions
Save as a lab state…
Save settings
- **see_changes_text**: What changed

2 devices changed since your last save: r1 and r2. 12 lines added, 4 removed. Not uploaded yet.

Upload
Not now
View files

To: campaign2-netlab-course-student › link-basics/work/latest

Saved files can contain passwords or keys.

THIS SAVE
r1 r1.cfg changed

8 added · 2 removed

Before this save / This save
@@ -3,7 +3,7 @@
3	3		!
4	4		no aaa root
5	5		!
6		-	username admin privilege 15 role network-admin secret sha512 <hash>
	6	+	username admin privilege 15 role network-admin secret sha512 <hash>
7	7		!
8	8		management api http-commands
9	9		   no shutdown
@@ -29,11 +29,17 @@
29	29		   transport ssh default
30	30		!
31	31		interface Ethernet1
	32	+	   no switchport
	33	+	   ip address 10.0.0.1/30
	34	+	!
	35	+	interface Loopback0
	36	+	   description r1 loopback
	37	+	   ip address 10.255.0.1/32
32	38		!
33	39		interface Management0
34	40		   ip address 172.20.20.11/24
35	41		!
36		-	no ip routing
	42	+	ip routing
37	43		!
38	44		ip route 0.0.0.0/0 172.20.20.1
39	45		!
Also uploaded for r1: r1.eoscfg, the file Load uses
r2 r2.cfg changed

4 added · 2 removed

Before this save / This save
@@ -3,7 +3,7 @@
3	3		!
4	4		no aaa root
5	5		!
6		-	username admin privilege 15 role network-admin secret sha512 <hash>
	6	+	username admin privilege 15 role network-admin secret sha512 <hash>
7	7		!
8	8		management api http-commands
9	9		   no shutdown
@@ -29,11 +29,13 @@
29	29		   transport ssh default
30	30		!
31	31		interface Ethernet1
	32	+	   no switchport
	33	+	   ip address 10.0.0.2/30
32	34		!
33	35		interface Management0
34	36		   ip address 172.20.20.12/24
35	37		!
36		-	no ip routing
	38	+	ip routing
37	39		!
38	40		ip route 0.0.0.0/0 172.20.20.1
39	41		!
Also uploaded for r2: r2.eoscfg, the file Load uses
Save details manifest.json changed
- **chip_after_upload**: Saved just now
- **panel_after_upload**: Saved just now
Name of this save
Keep as a checkpoint

Running: your latest save

Uploaded: yes, to github.com

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

Last load:
Start, 1 minute ago
Details

All versions
Save as a lab state…
Save settings

Remote evidence (GitHub):
- **latest_r1_has_loopback0**: True
- **latest_folder_files**: ['link-basics/work/latest/link-basics.clab.yml', 'link-basics/work/latest/link-basics.clab.yml.annotations.json', 'link-basics/work/latest/manifest.json', 'link-basics/work/latest/r1.cfg', 'link-basics/work/latest/r1.eoscfg', 'link-basics/work/latest/r2.cfg', 'link-basics/work/latest/r2.eoscfg']

Screenshots:
- `a8-save2-panel-full.png` (full-page)
- `a8-see-changes-full.png` (full-page)
- `a8-see-changes.png` (What changed (second save))
- `a8-saved-panel-full.png` (full-page)

## Step 9: Checkpoint, then r2 and a second upload — PASS

Actions:
- Chip panel: name the save loopback-added, tick Keep as a checkpoint
- r2 CLI: enable; configure terminal; interface Loopback0; description r2 loopback; ip address 10.255.0.2/32; end; write memory

Observed:
- **name_before**: r1 and r2 changed
- **checkpoint_panel**: Not uploaded yet

Checkpoint loopback-added kept. It is not uploaded yet.

To: campaign2-netlab-course-student › link-basics/work

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

Last load:
Start, 1 minute ago
Details

All versions
Save as a lab state…
Save settings
- **chip_after_checkpoint_upload**: Saved just now
- **r2_loopback0_present**: True
- **save3_seconds_to_commit**: 6.1
- **save3_panel**: Not uploaded yet

1 device changed since your last save: r2. 4 lines added, 0 removed.

To: campaign2-netlab-course-student › link-basics/work

Upload
Not now
See changes
Details

Saved files can contain passwords or keys.

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

Last load:
Start, 2 minutes ago
Details

All versions
Save as a lab state…
Save settings
- **save3_seconds_to_uploaded**: 12.5
- **save3_chip**: Saved just now
- **panel_after_save3**: Saved just now
Name of this save
Keep as a checkpoint

Running: your latest save

Uploaded: yes, to github.com

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

Last load:
Start, 2 minutes ago
Details

All versions
Save as a lab state…
Save settings
- **save3_name**: r2 changed
- **all_versions**: All versions

Everything saved for link-basics. Choose one to load it.

YOUR SAVES
r2 changed
just now
loopback-added
1 minute ago
First save
4 minutes ago
CHECKPOINTS
loopback-added
1 minute ago
STARTING POINT

No starting point yet.

Choose a backup as starting point…
LAB STATES
Save as a lab state…
Broken-01
Sep 22, 2026
Solution
Sep 22, 2026
Start
Sep 22, 2026
Save activity (1)
Full history…
Browse the repository…

Device evidence (eos.py, direct SSH):
- **r2_show_ip_interface_brief**:                                          Address
Interface         IP Address            Status       Protocol            MTU    Owner
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.2/30           up           up                 1500
Loopback0         10.255.0.2/32         up           up                65535
Management0       172.20.20.12/24       up           up                 1500

r2#

Remote evidence (GitHub):
- **latest_r2_has_loopback0**: True
- **checkpoint_r2_lacks_loopback0**: True
- **checkpoint_folder_files**: ['link-basics/work/checkpoints/loopback-added', 'link-basics/work/checkpoints/loopback-added/link-basics.clab.yml', 'link-basics/work/checkpoints/loopback-added/link-basics.clab.yml.annotations.json', 'link-basics/work/checkpoints/loopback-added/manifest.json', 'link-basics/work/checkpoints/loopback-added/r1.cfg', 'link-basics/work/checkpoints/loopback-added/r1.eoscfg', 'link-basics/work/checkpoints/loopback-added/r2.cfg', 'link-basics/work/checkpoints/loopback-added/r2.eoscfg']
- **no_nested_latest_latest**: True

Screenshots:
- `a9-name-and-keep-full.png` (full-page)
- `a9-checkpoint-kept-full.png` (full-page)
- `a9-save3-panel-full.png` (full-page)
- `a9-all-versions-full.png` (full-page)
- `a9-all-versions.png` (All versions)

## Step 10: Break it with Broken-01, go back two ways — PASS

Actions:
- Load > Broken-01 > red Load
- Chip panel > Undo this load > red Load
- Load > Broken-01 again
- Load > your newest own save > red Load

Observed:
- **broken_list**: Load a saved state
YOUR SAVES
r2 changed
5 minutes ago
loopback-added
6 minutes ago
LAB STATES
Broken-01
2 devices
Solution
2 devices
Start
2 devices
All versions
Browse the repository…
- **broken_confirmation**: Load Broken-01?

The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.

Saved Sep 22, 2026.

r1 EOS
1 line differs
r2 EOS
2 lines differ

Each device checks the new configuration itself and undoes it if it loses contact.

Options
Load
Cancel
See what’s different
- **broken_seconds**: 9.3
- **broken_chip**: Running Broken-01
- **ping_fails_after_broken**: True
- **et1_notconnect_after_broken**: True
- **chip_panel_broken**: Running Broken-01

Loaded just now on all 2 devices.

Your latest save: r2 changed, 6 minutes ago

Before loading: backed up automatically

Undo this load
What changed

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

All versions
Save as a lab state…
Save settings
- **undo_confirmation**: Undo loading Broken-01?

The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.

Saved just now.

r1 EOS
1 line differs
r2 EOS
2 lines differ

Each device checks the new configuration itself and undoes it if it loses contact.

Options
Load
Cancel
See what’s different
- **undo_seconds**: 9.0
- **chip_after_undo**: Running the configuration from before Broken-01
- **ping_ok_after_undo**: True
- **broken2_list**: Load a saved state
YOUR SAVES
r2 changed
6 minutes ago
loopback-added
7 minutes ago
LAB STATES
Broken-01
2 devices
Solution
2 devices
Start
2 devices
All versions
Browse the repository…
- **broken2_confirmation**: Load Broken-01?

The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.

Saved Sep 22, 2026.

r1 EOS
1 line differs
r2 EOS
2 lines differ

Each device checks the new configuration itself and undoes it if it loses contact.

Options
Load
Cancel
See what’s different
- **broken2_seconds**: 9.3
- **broken2_chip**: Running Broken-01
- **ping_fails_after_broken2**: True
- **recover_list**: Load a saved state
YOUR SAVES
r2 changed
6 minutes ago
loopback-added
7 minutes ago
LAB STATES
Broken-01
2 devices
Solution
2 devices
Start
2 devices
All versions
Browse the repository…
- **recover_confirmation**: Load r2 changed?

The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.

Saved 7 minutes ago.

r1 EOS
1 line differs
r2 EOS
2 lines differ

Each device checks the new configuration itself and undoes it if it loses contact.

Options
Load
Cancel
See what’s different
- **recover_seconds**: 9.3
- **recover_chip**: Running r2 changed
- **recovered_with**: r2 changed
- **ping_ok_after_recover**: True
- **loopbacks_back**: True
- **chip_panel_recovered**: Running r2 changed

Loaded just now on all 2 devices.

Your latest save: r2 changed, 7 minutes ago

Before loading: backed up automatically

Undo this load
What changed

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

All versions
Save as a lab state…
Save settings
- **compare_drawer_text**: Back
Different from your latest save

How loopback-added differs from the last save of link-basics. To see what would change on the devices, choose Load this state…: the devices are compared before anything is loaded.

r2.cfg changed

0 lines only in this version (−) · 4 only in your latest save (+)

This version / Your latest save
@@ -32,6 +32,10 @@
32	32		   no switchport
33	33		   ip address 10.0.0.2/30
34	34		!
	35	+	interface Loopback0
	36	+	   description r2 loopback
	37	+	   ip address 10.255.0.2/32
	38	+	!
35	39		interface Management0
36	40		   ip address 172.20.20.12/24
37	41		!
r2.eoscfg changed

0 lines only in this version (−) · 4 only in your latest save (+)

This version / Your latest save
@@ -32,6 +32,10 @@
32	32		   no switchport
33	33		   ip address 10.0.0.2/30
34	34		!
	35	+	interface Loopback0
	36	+	   description r2 loopback
	37	+	   ip address 10.255.0.2/32
	38	+	!
35	39		interface Management0
36	40		   ip address 172.20.20.12/24
37	41		!

Device evidence (eos.py, direct SSH):
- **r1_ping_after_broken**: enable
r1#ping 10.0.0.2 repeat 3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.

- **r1_show_interfaces_status_after_broken**: enable
r1#show interfaces status
Port       Name       Status       Vlan     Duplex Speed  Type            Flags Encapsulation
Et1        link to r2 notconnect   routed   full   1G     EbraTestPhyPort
Ma0                   connected    routed   a-full a-1G   10/100/1000

r1#
- **r1_ping_after_undo**:  3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.
80 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.094 ms
80 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.005 ms
80 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.004 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.004/0.034/0.094/0.042 ms, ipg/ewma 0.061/0.073 ms
r1#
- **r1_ping_after_recover**:  3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.
80 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.133 ms
80 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.011 ms
80 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.007 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.007/0.050/0.133/0.058 ms, ipg/ewma 0.102/0.104 ms
r1#
- **r1_show_ip_interface_brief**:                                          Address
Interface         IP Address            Status       Protocol            MTU    Owner
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.1/30           up           up                 1500
Loopback0         10.255.0.1/32         up           up                65535
Management0       172.20.20.11/24       up           up                 1500

r1#
- **r2_show_ip_interface_brief**:                                          Address
Interface         IP Address            Status       Protocol            MTU    Owner
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.2/30           up           up                 1500
Loopback0         10.255.0.2/32         up           up                65535
Management0       172.20.20.12/24       up           up                 1500

r2#

Screenshots:
- `a10-broken-list-full.png` (full-page)
- `a10-broken-confirm-full.png` (full-page)
- `a10-broken-loaded-full.png` (full-page)
- `a10-undo-confirm-full.png` (full-page)
- `a10-broken2-list-full.png` (full-page)
- `a10-broken2-confirm-full.png` (full-page)
- `a10-recover-list-full.png` (full-page)
- `a10-recover-confirm-full.png` (full-page)
- `a10-recovered-full.png` (full-page)
- `a10-compare-full.png` (full-page)

## Step 11: Next time you open this lab — PASS

Observed:
- **home_card_text**: link-basics | ⋯ |  | Running | 2 of 2 devices ready |  | Running r2 changed |  | Deployed 12 minutes ago |  | Open lab
- **chip_reopened**: Running r2 changed
- **panel_reopened**: Running r2 changed

Loaded just now on all 2 devices.

Your latest save: r2 changed, 7 minutes ago

Before loading: backed up automatically

Undo this load
What changed

Saves to:
campaign2-netlab-course-student › link-basics/work
Change…

All versions
Save as a lab state…
Save settings
- **load_list_reopened**: Load a saved state
YOUR SAVES
r2 changed
7 minutes ago
loopback-added
8 minutes ago
LAB STATES
Broken-01
2 devices
Solution
2 devices
Start
2 devices
All versions
Browse the repository…
- **lab_actions_items**: ['Start stopped devices The lab is already running', 'Stop devices', 'Restart all devices…', 'Apply topology changes…', 'Sync topology from VM', 'Packet capture…', 'Lab files…', 'All lab operations…', 'Redeploy lab…', 'Redeploy and clear the lab folder…', 'Destroy lab…', 'Remove from this manager…', 'Advanced options', 'Import map…', 'Edit map', 'Edit topology…', 'Retired telemetry configuration…', 'Operation history…']
- **destroy_review**: Destroy link-basics?
×

link-basics

/srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml

The running devices are removed from the VM. Configuration changes you have not saved are lost. Your saves, lab states and backups remain.

Run with options

Last saved 7 minutes ago. A saved state was loaded since.

Open CLI sessions to this lab will disconnect.

2 running devices affected

Technical details

Runs on the lab VM. If the lab changes before you confirm, this check is repeated.

Cancel
Save first
Destroy lab
- **remove_dialog_ids**: ['remove-lab-dialog']
- **remove_dialog_text**: Remove link-basics from this manager?
×

This removes the lab from My labs: its device list, map, saved device logins, backup schedule and backup history entries. Backup files stay on this VM's disk.

Nothing on the lab VM changes: the running devices and the topology files stay. What you saved stays in its repository.

Don't offer this lab for import again

Untick it if you want the lab to be offered again under Manager ▾ › Labs found on the VM…. Either way, adding it back needs your confirmation.

Cancel
Remove lab

Screenshots:
- `a11-home-card.png` (link-basics card)
- `a11-reopened-panel-full.png` (full-page)
- `a11-load-list-full.png` (full-page)
- `a11-lab-actions-full.png` (full-page)
- `a11-lab-actions.png` (Lab actions)
- `a11-destroy-review-full.png` (full-page)
- `a11-destroy-review.png` (Destroy review)
- `a11-remove-review-full.png` (full-page)
