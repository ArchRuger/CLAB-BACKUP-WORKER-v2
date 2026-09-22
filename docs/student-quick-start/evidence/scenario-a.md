# Scenario A: use an instructor's lab — evidence

Manager: `http://127.0.0.1:8081`  
Run: 2026-09-22T17:26:40Z — 2026-09-22T17:30:05Z

## Step 1: Home: empty My labs, Deploy box — PASS

Actions:
- Navigate to the manager home page

Observed:
- **lab_card_count**: 0
- **empty_state_heading**: No labs yet

Screenshots:
- `a1-home-full.png` (full-page)
- `a1-deploy-box.png` (Deploy box)

## Step 2: Deploy link-basics from the lab VM — PASS

Actions:
- Click "Choose a file on the lab VM…"
- Open folder /srv/containerlab-node-manager/projects
- Open folder link-basics
- Click ◇ link-basics.clab.yml
- Topology file dialog shown with YAML preview
- Click "Deploy lab"

Observed:
- **topology_path_field**: /srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml
- **yaml_preview_first_line**: # link-basics: two Arista cEOS routers joined by one link.
- **review_title**: Start link-basics?
- **confirm_button_label**: Start lab
- **post_confirm_hash**: #lab=b84d9778df174d5fb80efae12c92b69a&view=topology
- **lab_id**: b84d9778df174d5fb80efae12c92b69a

Screenshots:
- `a2-file-picker-full.png` (full-page)
- `a2-file-picker-dialog.png` (Lab folders on the VM)
- `a2-topology-file-full.png` (full-page)
- `a2-topology-file-dialog.png` (Topology file)
- `a2-start-review-full.png` (full-page)
- `a2-start-review-dialog.png` (Start link-basics?)

## Step 3: Starting -> Ready (deploy timing) — PASS

Actions:
- Open the Devices tab while devices are starting
- Polled the Devices tab until both rows read Ready (38.0s since confirm)

Observed:
- **lab_state_starting**: Starting lab
- **lab_ready_starting**: 0 of 2 devices ready
- **devices_pills_starting**: ['Unavailable', 'Unavailable']
- **deploy_to_ready_seconds**: 38.0
- **lab_ready_final**: 2 of 2 devices ready
- **devices_pills_ready**: ['Ready', 'Ready']

Screenshots:
- `a3-header-starting-full.png` (full-page)
- `a3-header-starting-el.png` (Lab header (Starting))
- `a3-devices-starting-full.png` (full-page)
- `a3-devices-starting-el.png` (Devices tab (Starting))
- `a3-devices-ready-full.png` (full-page)
- `a3-devices-ready-el.png` (Devices tab (Ready))

## Step 4: Topology tab and r1 CLI (show version / show interfaces status) — PASS

Actions:
- Open the Topology tab
- Open CLI on r1 from the Devices tab

Observed:
- **terminal_status_before_typing**: Connected
- **et1_connected**: True
- **no_ip_on_et1_yet**: True

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
- `a4-topology-el.png` (Topology map)
- `a4-r1-terminal-full.png` (full-page)
- `a4-r1-terminal-el.png` (r1 CLI (show version / show interfaces status))

## Step 5: Connect a repository by URL — PASS

Actions:
- Open the Progress tab
- Click "Connect a repository by URL"
- Click "Connect repository" and wait for the clone/check/register

Observed:
- **unconnected_card_heading**: Choose where to save your progress
- **destination_line**: link-basics saves to netlab-course-student › link-basics/work › latest/
- **saved_versions_text**: Browse the repository…
Full history…
Latest

You haven't saved this lab yet. Save progress creates a configuration snapshot you can return to later.

Checkpoints

No checkpoints yet. Create a checkpoint when you reach an important milestone.

Instructor and reference versions

Versions your instructor put in the repository appear here. Apply one to load it onto your running devices; the current configuration is backed up first.

Troubleshooting scenario 01
link-basics/reference/broken-01/latest
5 files
View
Compare with my latest save
Apply to running lab…
Final state (instructor)
link-basics/reference/solution/latest
5 files
View
Compare with my latest save
Apply to running lab…
Starting state
link-basics/reference/start/latest
5 files
View
Compare with my latest save
Apply to running lab…
- **saved_versions_rows**: ['Troubleshooting scenario 01 | link-basics/reference/broken-01/latest | 5 files | View | Compare with my latest save | Apply to running lab…', 'Final state (instructor) | link-basics/reference/solution/latest | 5 files | View | Compare with my latest save | Apply to running lab…', 'Starting state | link-basics/reference/start/latest | 5 files | View | Compare with my latest save | Apply to running lab…']
- **reference_group_present**: True

Screenshots:
- `a5-progress-unconnected-full.png` (full-page)
- `a5-progress-unconnected-el.png` (Choose where to save your progress)
- `a5-connect-dialog-filled-full.png` (full-page)
- `a5-connect-dialog-filled-el.png` (Connect a repository by URL (filled))
- `a5-progress-connected-full.png` (full-page)
- `a5-progress-connected-el.png` (Connected save location)

## Step 6: Apply reference 'start' state — PASS

Actions:
- Click Saved versions › Starting state › Apply to running lab…

Observed:
- **start_row_caption**: link-basics/reference/start/latest
- **restore_source_line**: Source: Starting state · netlab-course-student › link-basics/reference/start/latest · saved 35 minutes ago · 089a35aeb8
- **restore_target_rows**: ['r1 EOS 6 differences from the running configuration', 'r2 EOS 6 differences from the running configuration']
- **restore_job_id**: 6a9f7302b32e46cba7b492eb233b8446
- **restore_apply_seconds**: 12.0
- **restore_job_status**: succeeded
- **restore_targets**: [{'name': 'clab-link-basics-r1', 'status': 'verified', 'message': 'Configuration replaced and verified against the saved desired state.'}, {'name': 'clab-link-basics-r2', 'status': 'verified', 'message': 'Configuration replaced and verified against the saved desired state.'}]
- **ping_ok_after_start**: True

Device evidence (eos.py, direct SSH):
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
- **r1_ping_10_0_0_2**: enable
r1#ping 10.0.0.2 repeat 3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.
80 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.091 ms
80 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.007 ms
80 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.003 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.003/0.033/0.091/0.040 ms, ipg/ewma 0.063/0.070 ms
r1#

Remote evidence (GitHub):
- **binding_prefix_after_apply_start**: link-basics/work

Screenshots:
- `a6-apply-start-review-full.png` (full-page)
- `a6-apply-start-review-el.png` (Replace running configuration (start))
- `a6-apply-start-result-full.png` (full-page)
- `a6-apply-start-result-el.png` (Restore result (start))

## Step 7: r1: add Loopback0 over the CLI — PASS

Actions:
- Terminal: enable
- Terminal: configure terminal
- Terminal: interface Loopback0
- Terminal: description r1 loopback
- Terminal: ip address 10.255.0.1/32
- Terminal: end
- Terminal: write memory
- Terminal: show ip interface brief

Observed:
- **loopback0_present**: True

Device evidence (eos.py, direct SSH):
- **r1_show_ip_interface_brief_after_loopback**: enable
r1#show ip interface brief
                                                                                Address
Interface         IP Address            Status       Protocol            MTU    Owner  
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.1/30           up           up                 1500           
Loopback0         10.255.0.1/32         up           up                65535           
Management0       172.20.20.11/24       up           up                 1500           

r1#

Screenshots:
- `a7-r1-loopback-terminal-full.png` (full-page)
- `a7-r1-loopback-terminal-el.png` (r1 CLI (Loopback0 readback))

## Step 8: Save progress and upload — PASS

Actions:
- Click "Save progress"
- Click "Upload these changes"

Observed:
- **review_before_uploading_text**: Review before uploading
×

What this save changed compared with the previous one. Configuration files may contain passwords or keys.

This save is on the lab VM only. Nothing is uploaded to github.com unless you choose Upload these changes.

Details
r1.cfg added
r1.eoscfg added
r2.cfg added
r2.eoscfg added
Open the full saved version
Not now — keep it on the VM
Upload these changes
- **upload_button_label**: Upload these changes
- **not_now_button_label**: Not now — keep it on the VM
- **save_job_status**: synced
- **save_job_commit**: 7d3c23337247d825a2fad20bdfb32e79340b0e7f
- **progress_status_after_save**: Saved to Git just now

Remote evidence (GitHub):
- **tree_paths_after_first_save**: {'link-basics/work/latest/manifest.json': True, 'link-basics/work/latest/r1.cfg': True, 'link-basics/work/latest/r2.cfg': True, 'link-basics/work/latest/r1.eoscfg': True, 'link-basics/work/latest/r2.eoscfg': True}
- **commit**: 7d3c23337247d825a2fad20bdfb32e79340b0e7f

Screenshots:
- `a8-save-review-full.png` (full-page)
- `a8-save-review-el.png` (Review before uploading)
- `a8-save-job-result-full.png` (full-page)
- `a8-save-job-result-el.png` (Save job result)
- `a8-progress-after-save-full.png` (full-page)
- `a8-progress-after-save-el.png` (Progress tab after save)

Notes:
- Documented "Not now — keep it on the VM" sentence (not exercised here): "This save is on the lab VM only. Nothing is uploaded to <host> unless you choose Upload these changes."

## Step 9: Checkpoint 'loopback-added', then r2's loopback and a second save — PASS

Actions:
- Click "Create checkpoint…"
- Review before uploading -> Upload these changes
- r2 terminal: added Loopback0 10.255.0.2/32, write memory
- Save progress again -> Review -> Upload these changes

Observed:
- **checkpoint_job_status**: synced
- **checkpoint_job_commit**: da05d70fd0f6d223dcb5fd6d7b641d7d9af6bdc3
- **second_save_job_status**: synced
- **second_save_job_commit**: cf244a099fe2a3c812e70e8bbb6da7c7aeea041a
- **saved_versions_text_after_checkpoint**: Browse the repository…
Full history…
Latest
Latest
netlab-course-student › link-basics/work › latest
Saved just now · 5 files
View
Apply to running lab…
Checkpoints
loopback-added
Saved just now · 5 files
View
Compare with my latest save
Apply to running lab…
Instructor and reference versions

Versions your instructor put in the repository appear here. Apply one to load it onto your running devices; the current configuration is backed up first.

Troubleshooting scenario 01
link-basics/reference/broken-01/latest
5 files
View
Compare with my latest save
Apply to running lab…
Final state (instructor)
link-basics/reference/solution/latest
5 files
View
Compare with my latest save
Apply to running lab…
Starting state
link-basics/reference/start/latest
5 files
View
Compare with my latest save
Apply to running lab…

Remote evidence (GitHub):
- **latest_r2_has_loopback0**: True
- **checkpoint_r2_lacks_loopback0**: True
- **no_nested_latest_latest**: True
- **double_latest_paths_found**: []

Screenshots:
- `a9-checkpoint-dialog-full.png` (full-page)
- `a9-checkpoint-dialog-el.png` (Create checkpoint (loopback-added))
- `a9-checkpoint-job-result-full.png` (full-page)
- `a9-checkpoint-job-result-el.png` (Checkpoint job result)
- `a9-saved-versions-with-checkpoint-full.png` (full-page)
- `a9-saved-versions-with-checkpoint-el.png` (Saved versions (Latest + loopback-added))

## Step 10: Apply reference 'broken-01', then return to the lab's own Latest — PASS

Actions:
- Saved versions › Troubleshooting scenario 01 › Apply to running lab…
- Saved versions › Latest › Apply to running lab…

Observed:
- **broken_source_line**: Source: Troubleshooting scenario 01 · netlab-course-student › link-basics/reference/broken-01/latest · saved 35 minutes ago · cf244a099f
- **broken_restore_status**: succeeded
- **ping_fails_after_broken**: True
- **et1_notconnect_after_broken**: True
- **latest_source_line**: Source: work · netlab-course-student › link-basics/work/latest · saved just now · cf244a099f
- **latest_restore_status**: succeeded
- **ping_ok_after_latest**: True
- **loopbacks_back**: True
- **compare_checkpoint_dialog_title**: Compared with your latest save

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
- **r1_ping_after_latest**: enable
r1#ping 10.0.0.2 repeat 3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.
80 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.095 ms
80 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.004 ms
80 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.003 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.003/0.034/0.095/0.043 ms, ipg/ewma 0.062/0.073 ms
r1#
- **r1_show_ip_interface_brief_after_latest**: enable
r1#show ip interface brief
                                                                                Address
Interface         IP Address            Status       Protocol            MTU    Owner  
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.1/30           up           up                 1500           
Loopback0         10.255.0.1/32         up           up                65535           
Management0       172.20.20.11/24       up           up                 1500           

r1#
- **r2_show_ip_interface_brief_after_latest**: enable
r2#show ip interface brief
                                                                                Address
Interface         IP Address            Status       Protocol            MTU    Owner  
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.2/30           up           up                 1500           
Loopback0         10.255.0.2/32         up           up                65535           
Management0       172.20.20.12/24       up           up                 1500           

r2#

Remote evidence (GitHub):
- **binding_prefix_after_apply_latest**: link-basics/work

Screenshots:
- `a10-apply-broken-review-full.png` (full-page)
- `a10-apply-broken-review-el.png` (Replace running configuration (broken-01))
- `a10-apply-broken-result-full.png` (full-page)
- `a10-apply-broken-result-el.png` (Restore result (broken-01))
- `a10-apply-latest-review-full.png` (full-page)
- `a10-apply-latest-review-el.png` (Replace running configuration (own Latest))
- `a10-apply-latest-result-full.png` (full-page)
- `a10-apply-latest-result-el.png` (Restore result (own Latest))
- `a10-compare-checkpoint-full.png` (full-page)
- `a10-compare-checkpoint-el.png` (Compare with my latest save (loopback-added))

## Step 11: Fresh context: Home card, Progress tab, Lab actions menu, Destroy review (cancelled) — PASS

Actions:
- Fresh browser context -> Home
- Opened "Destroy lab…" review, screenshotted it, then Cancel (no destroy performed)

Observed:
- **home_card_text**: link-basics | ⋯ |  | Running | 2 of 2 devices ready |  | Last saved 1 minute ago |  | Deployed 3 minutes ago |  | Open lab
- **lab_actions_menu_items**: ['Start stopped devices\nThe lab is already running', 'Stop devices', 'Restart devices', 'Sync topology from VM', 'Packet capture…', 'Lab files…', 'All lab operations…', 'Redeploy lab…', 'Redeploy and clear the lab folder…', 'Destroy lab…', 'Remove from this manager…', 'Advanced options', 'Import map…', 'Edit map', 'Telemetry settings…', 'Operation history…']
- **destroy_review_title**: Destroy link-basics?
- **console_errors_seen**: []

Screenshots:
- `a11-home-fresh-full.png` (full-page)
- `a11-home-fresh-lab-card-el.png` (link-basics lab card)
- `a11-progress-fresh-full.png` (full-page)
- `a11-progress-fresh-el.png` (Saved versions (fresh context))
- `a11-lab-actions-menu-full.png` (full-page)
- `a11-lab-actions-menu-el.png` (Lab actions menu)
- `a11-destroy-review-full.png` (full-page)
- `a11-destroy-review-el.png` (Destroy link-basics?)

Notes:
- Lab left running and connected for the lead, as instructed.

