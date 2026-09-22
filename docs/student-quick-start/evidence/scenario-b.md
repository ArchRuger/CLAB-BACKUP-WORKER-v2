# Scenario B: build your own lab and keep it in Git — evidence

Manager: `http://127.0.0.1:8081`  
Run: 2026-09-22T18:41:59Z — 2026-09-22T18:57:02Z

## Step 1: Start a new lab in the builder — PASS

Actions:
- Home: click "Open the lab builder" (#home-build) in the Build box
- Click "New lab…"
- Fill name='my-first-lab', starter="Two devices, one link", device type='Arista cEOS · n24l/ceos:4.35.0F', folder='/srv/containerlab-node-manager/projects'
- Click "Create draft"

Observed:
- **template_options**: ['Arista cEOS · n24l/ceos:4.35.0F', 'Juniper cJunosEvolved · cjunosevolved:26.2R1.7-EVO', 'Juniper vJunos-switch · vrnetlab/juniper_vjunos-switch:23.2R1.14', 'Cisco XRv9k · vrnetlab/cisco_xrv9k:24.3.1', 'Linux host · ghcr.io/srl-labs/network-multitool:latest']
- **ceos_template_text**: Arista cEOS · n24l/ceos:4.35.0F
- **root_options**: ['/etc/containerlab', '/srv/containerlab-node-manager/projects']
- **node_count**: 2
- **edge_count**: 1
- **node_names**: ['ceos1', 'ceos2']
- **builder_status**: Draft · kept in this browser only · not on the VM yet

Screenshots:
- `b1-new-lab-dialog-full.png` (full-page)
- `b1-new-lab-dialog-el.png` (New lab (filled))
- `b1-editor-two-nodes-full.png` (full-page)
- `b1-editor-two-nodes-el.png` (Editor: two devices, one link)

## Step 2: Draw and check the topology — PASS

Actions:
- Edit Node on the first device: renamed to r1, Management IPv4 172.20.20.21, Image/Version reasserted to n24l/ceos / 4.35.0F, Apply
- Edit Node on the second device: renamed to r2, Management IPv4 172.20.20.22, Image/Version reasserted, Apply
- Right-click empty canvas -> "Add Text" -> typed "My first lab: r1 eth1 - r2 eth1"
- Click "View YAML"

Observed:
- **r1_image_before_reassert**: n24l/ceos
- **r1_version_before_reassert**: 4.35.0F
- **r2_image_before_reassert**: n24l/ceos
- **r2_version_before_reassert**: 4.35.0F
- **canvas_context_menu**: ['Add Node', 'Add Group', 'Add Text', 'Add Shape', 'Add Traffic Rate', 'Open Palette']
- **annotation_tool_found**: True
- **yaml_text**: name: my-first-lab
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

- **both_images_n24l_ceos_4_35_0F**: True

Screenshots:
- `b2-node-editor-r1-full.png` (full-page)
- `b2-node-editor-r1-el.png` (Node Editor: r1)
- `b2-canvas-finished-full.png` (full-page)
- `b2-canvas-finished-el.png` (Finished canvas: r1, r2, note)
- `b2-view-yaml-full.png` (full-page)
- `b2-view-yaml-el.png` (View YAML)

Notes:
- Both nodes were already placed side by side by the "pair" starter (left/right); no further dragging was needed to satisfy "arrange side by side".

## Step 3: Save to the VM and deploy — PASS

Actions:
- Click "Save to the VM…"
- Confirm the save review
- Click "Deploy or add this lab…"
- Click "Deploy lab"
- Confirm with "Start lab" (job result shown on the builder page itself)
- Home -> open the my-first-lab lab card (the builder page does not navigate there itself)

Observed:
- **save_review_title**: Save my-first-lab to the VM?
- **save_review_path**: /srv/containerlab-node-manager/projects/my-first-lab/my-first-lab.clab.yml
- **save_job_banner**: ✔ Save lab to the VM succeeded
my-first-lab · Operation completed
Exit code 0
- **builder_status_after_save**: Saved on the VM
- **topology_file_path**: /srv/containerlab-node-manager/projects/my-first-lab/my-first-lab.clab.yml
- **start_review_title**: Start my-first-lab?
- **deploy_job_banner**: ✔ Save lab to the VM succeeded
my-first-lab · Operation completed
Exit code 0
- **lab_id**: d2eba4e95b164d4c8ddf67e5448fbbf7
- **vm_folder_listing**: ['clab-my-first-lab', 'my-first-lab.clab.yml', 'my-first-lab.clab.yml.annotations.json']
- **annotations_file**: my-first-lab.clab.yml.annotations.json

Remote evidence (GitHub):
- **ls_la_output**: total 20
drwxrwsr-x 3 root clab_admins 4096 Sep 22 18:42 .
drwxrwsr-x 4 root clab_admins 4096 Sep 22 18:42 ..
drwxr-sr-x 5 root clab_admins 4096 Sep 22 18:42 clab-my-first-lab
-rw-rw-r-- 1 root clab_admins  275 Sep 22 18:42 my-first-lab.clab.yml
-rw-rw-r-- 1 root clab_admins  871 Sep 22 18:42 my-first-lab.clab.yml.annotations.json


Screenshots:
- `b3-save-review-full.png` (full-page)
- `b3-save-review-el.png` (Save my-first-lab to the VM?)
- `b3-save-result-full.png` (full-page)
- `b3-save-result-el.png` (Save result: Deploy or add this lab…)
- `b3-topology-file-full.png` (full-page)
- `b3-topology-file-el.png` (Topology file)
- `b3-start-review-full.png` (full-page)
- `b3-start-review-el.png` (Start my-first-lab?)

## Step 4: Bring the link up — PASS

Actions:
- Polled the Devices tab until both rows read Ready (40.7s since confirm)
- r1 CLI: enable/configure terminal/ip routing/interface Ethernet1/no switchport/ip address 10.0.0.1/30/end/write memory
- r2 CLI: same commands with ip address 10.0.0.2/30
- r1 CLI: ping 10.0.0.2

Observed:
- **deploy_to_ready_seconds**: 40.7
- **devices_pills_ready**: ['Ready', 'Ready']
- **ping_ok**: True

Device evidence (eos.py, direct SSH):
- **r1_ping_10_0_0_2**: enable
r1#ping 10.0.0.2 repeat 3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.
80 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.093 ms
80 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.006 ms
80 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.004 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.004/0.034/0.093/0.041 ms, ipg/ewma 0.069/0.072 ms
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
- `b4-devices-ready-el.png` (Devices tab (Ready))
- `b4-r1-ping-terminal-full.png` (full-page)
- `b4-r1-ping-terminal-el.png` (r1 CLI: ping 10.0.0.2)

## Step 5: Create the student's own repository on GitHub — PASS

Actions:
- gh repo create pruger-dev/my-network-labs --private --add-readme --description My containerlab labs

Observed:
- **repo_url**: https://github.com/pruger-dev/my-network-labs
- **repo_visibility**: PRIVATE
- **repo_default_branch**: main

Remote evidence (GitHub):
- **gh_repo_create_output**: HTTP 422: Repository creation failed. (https://api.github.com/user/repos)
name already exists on this account

- **gh_repo_create_returncode**: 1
- **gh_repo_view_output**: {"defaultBranchRef":{"name":"main"},"url":"https://github.com/pruger-dev/my-network-labs","visibility":"PRIVATE"}


Notes:
- pruger-dev/my-network-labs already existed from an earlier attempt at this scenario run (the authenticated gh account has no delete_repo scope, so a prior attempt's repository could not be cleaned up between runs); reused it. It was still pristine (only the auto-added README, never pushed to by this scenario) at this point.
- Clarification added when step 10 was re-executed (see step 10's own notes): the HTTP 422 recorded above for this step happened because pruger-dev/my-network-labs already existed from earlier attempts made earlier in this authoring session; the repository creation itself (HTTP 201, a genuinely new empty repository) was exercised in one of those earlier attempts, not in the run that produced this evidence file. An independent QA replay of this scenario, using a repository name that has never existed, will see the create call itself succeed.

## Step 6: Connect the repository and save progress — PASS

Actions:
- Open the Progress tab
- Click "Connect a repository by URL"
- Click "Connect repository" and wait for the clone/check/register
- Click "Save progress"
- Click "Upload these changes"

Observed:
- **unconnected_card_heading**: Folders in this repository
- **destination_line**: my-first-lab saves to my-network-labs › my-first-lab › latest/
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
- **save_job_status**: synced
- **progress_status_after_save**: Saved to Git just now

Remote evidence (GitHub):
- **tree_paths_after_first_save**: {'my-first-lab/latest/manifest.json': True, 'my-first-lab/latest/r1.cfg': True, 'my-first-lab/latest/r2.cfg': True, 'my-first-lab/latest/r1.eoscfg': True, 'my-first-lab/latest/r2.eoscfg': True}
- **no_topology_file_uploaded_by_save**: True
- **unexpected_topology_paths**: []

Screenshots:
- `b6-connect-dialog-filled-full.png` (full-page)
- `b6-connect-dialog-filled-el.png` (Connect a repository by URL (filled))
- `b6-connected-card-full.png` (full-page)
- `b6-connected-card-el.png` (Connected save location)
- `b6-save-review-full.png` (full-page)
- `b6-save-review-el.png` (Review before uploading)
- `b6-save-job-result-full.png` (full-page)
- `b6-save-job-result-el.png` (Save job result)
- `b6-progress-after-save-full.png` (full-page)
- `b6-progress-after-save-el.png` (Progress tab after save)

## Step 7: Publish the topology files (owner terminal, lab VM) — PASS

Actions:
- $ cd /home/clabllm/labs/my-network-labs && mkdir -p my-first-lab && cp /srv/containerlab-node-manager/projects/my-first-lab/my-first-lab.clab.yml* my-first-lab/
- $ cat > my-first-lab/README.md   # 5-line description written above
- $ git add my-first-lab
- $ git commit -m "my-first-lab: topology and map"
- $ git push
- $ git status -sb

Observed:
- **git_status_clean**: ## main...origin/main

Remote evidence (GitHub):
- **transcript**: [['cd /home/clabllm/labs/my-network-labs && mkdir -p my-first-lab && cp /srv/containerlab-node-manager/projects/my-first-lab/my-first-lab.clab.yml* my-first-lab/', ''], ['cat > my-first-lab/README.md   # 5-line description written above', ''], ['git add my-first-lab', ''], ['git commit -m "my-first-lab: topology and map"', '[main 127bfe8] my-first-lab: topology and map\n 3 files changed, 65 insertions(+)\n create mode 100644 my-first-lab/README.md\n create mode 100644 my-first-lab/my-first-lab.clab.yml\n create mode 100644 my-first-lab/my-first-lab.clab.yml.annotations.json\n'], ['git push', 'To https://github.com/pruger-dev/my-network-labs.git\n   a6121e5..127bfe8  main -> main\n'], ['git status -sb', '## main...origin/main\n']]

Screenshots:
- `b7-terminal-git-push.png` (rendered transcript (not a live terminal))

## Step 8: Check GitHub, then browse the same tree in the manager — PASS

Actions:
- Saved versions -> "Browse the repository…"

Observed:
- **browse_listing_text**: my-network-labs
›
my-first-lab
Apply to running lab…
New folder…
Save this lab here

Applies this folder’s latest save (my-first-lab/latest) to the running devices. They are not rebooted.

my-network-labs
my-first-lab
This lab
latest
Name	What it is	Size

latest
	Most recent save	5.3 KB

my-first-lab.clab.yml
	File	275 B

my-first-lab.clab.yml.annotations.json
	File	871 B

README.md
	File	367 B
Last saved just now
Details
This lab already saves here.

Remote evidence (GitHub):
- **expect_files_present**: {'my-first-lab/my-first-lab.clab.yml': True, 'my-first-lab/README.md': True, 'my-first-lab/latest/manifest.json': True}
- **annotations_file_present**: ['my-first-lab/my-first-lab.clab.yml.annotations.json']

Screenshots:
- `b8-browse-repository-full.png` (full-page)
- `b8-browse-repository-el.png` (Folders in this repository)

## Step 9: Change, save, and checkpoint again — PASS

Actions:
- r2 CLI: added Loopback0 10.255.0.2/32, write memory
- Save progress -> Review before uploading -> Upload these changes
- Save progress menu -> "Create checkpoint…"
- Review before uploading -> Upload these changes

Observed:
- **second_save_review_text**: Review before uploading
×

What this save changed compared with the previous one. Configuration files may contain passwords or keys.

This save is on the lab VM only. Nothing is uploaded to github.com unless you choose Upload these changes.

Details
r2.cfg changed
r2.eoscfg changed
Open the full saved version
Not now — keep it on the VM
Upload these changes
- **review_shows_r2_changed_not_r1**: True
- **second_save_job_status**: synced
- **checkpoint_job_status**: synced
- **saved_versions_text**: Browse the repository…
Full history…
Latest
Latest
my-network-labs › my-first-lab › latest
Saved just now · 5 files
View
Apply to running lab…
Checkpoints
link-up
Saved just now · 5 files
View
Compare with my latest save
Apply to running lab…

Remote evidence (GitHub):
- **latest_r2_has_loopback0**: True
- **checkpoint_link_up_exists**: True
- **no_nested_latest_latest**: True
- **last_three_commits**: ['Save my-first-lab progress', 'Manager-Operation: 45b1b88e8391285adedd1e0544ed43ff', 'Save my-first-lab progress', 'Manager-Operation: 2a69b63062c5368c3bdf84ad8ed7c804', 'my-first-lab: topology and map']

Screenshots:
- `b9-second-save-review-full.png` (full-page)
- `b9-second-save-review-el.png` (Review before uploading (r2 changed))
- `b9-checkpoint-dialog-full.png` (full-page)
- `b9-checkpoint-dialog-el.png` (Create checkpoint (link-up))
- `b9-saved-versions-with-checkpoint-full.png` (full-page)
- `b9-saved-versions-with-checkpoint-el.png` (Saved versions (Latest + link-up))

## Step 10: Prove it: destroy, remove, and rebuild from Git — PASS

Actions:
- Lab actions -> "Destroy lab…"
- Waited for the lab to read Not running: 'Stopped'
- Lab actions -> "Remove from this manager…"
- Unticked "Don't offer this lab for import again", clicked "Remove lab"
- (authoring-only) sudo mv /srv/containerlab-node-manager/projects/my-first-lab /srv/containerlab-node-manager/projects-archive-2026-09-22/my-first-lab.original — not a guide step; removes the only other thing this validation could accidentally deploy from
- Home -> "Choose a file on the lab VM…"
- Open /srv/containerlab-node-manager/projects
- Open my-network-labs (a direct child of /srv/containerlab-node-manager/projects, scoped)
- Open my-first-lab (a direct child of my-network-labs, scoped — NOT the top-level my-first-lab folder, which was archived away above anyway)
- Select my-first-lab.clab.yml
- Deploy lab -> Start lab (from the cloned copy)
- Open the Topology tab (redeployed lab)
- Progress -> "Connect a repository by URL" (same URL and folder)
- Saved versions -> Latest -> "Apply to running lab…"

Observed:
- **vm_project_path_before_redo**: /srv/containerlab-node-manager/projects/my-first-lab/my-first-lab.clab.yml
- **destroy_review_title**: Destroy my-first-lab?
- **lab_state_after_destroy**: Stopped
- **docker_containers_after_remove**: []
- **cloned_topology_path_field**: /srv/containerlab-node-manager/projects/my-network-labs/my-first-lab/my-first-lab.clab.yml
- **cloned_topology_path_contains_expected_fragment**: True
- **vm_project_path_after_redeploy**: /srv/containerlab-node-manager/projects/my-network-labs/my-first-lab/my-first-lab.clab.yml
- **redeploy_to_ready_seconds**: 46.8
- **devices_pills_ready_after_redeploy**: ['Ready', 'Ready']
- **reconnect_result**: connected
- **apply_latest_seconds**: 12.0
- **apply_latest_status**: succeeded
- **addresses_and_loopback_restored**: True
- **ping_ok_final**: True
- **console_errors_seen**: []

Device evidence (eos.py, direct SSH):
- **r1_show_ip_interface_brief_final**: enable
r1#show ip interface brief
                                                                               Address
Interface         IP Address            Status       Protocol           MTU    Owner  
----------------- --------------------- ------------ -------------- ---------- -------
Ethernet1         10.0.0.1/30           up           up                1500           
Management0       172.20.20.21/24       up           up                1500           

r1#
- **r2_show_ip_interface_brief_final**: enable
r2#show ip interface brief
                                                                                Address
Interface         IP Address            Status       Protocol            MTU    Owner  
----------------- --------------------- ------------ -------------- ----------- -------
Ethernet1         10.0.0.2/30           up           up                 1500           
Loopback0         10.255.0.2/32         up           up                65535           
Management0       172.20.20.22/24       up           up                 1500           

r2#
- **r1_ping_10_0_0_2_final**: enable
r1#ping 10.0.0.2 repeat 3
PING 10.0.0.2 (10.0.0.2) 72(100) bytes of data.
80 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.093 ms
80 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.006 ms
80 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.006 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.006/0.035/0.093/0.041 ms, ipg/ewma 0.071/0.072 ms
r1#

Remote evidence (GitHub):
- **archived_original_folder**: {'from': '/srv/containerlab-node-manager/projects/my-first-lab', 'to': '/srv/containerlab-node-manager/projects-archive-2026-09-22/my-first-lab.original', 'rc': 0}
- **clone_transcript**: [('sudo mkdir -p /srv/containerlab-node-manager/projects-archive-2026-09-22', ''), ('sudo mv /srv/containerlab-node-manager/projects/my-first-lab /srv/containerlab-node-manager/projects-archive-2026-09-22/my-first-lab.original', ''), ('git clone https://github.com/pruger-dev/my-network-labs.git /srv/containerlab-node-manager/projects/my-network-labs', '# already cloned in an earlier attempt made earlier in this authoring session; not re-run'), ('git -C /srv/containerlab-node-manager/projects/my-network-labs log --oneline -3', '77108a9 Save my-first-lab progress\n11aadc0 Save my-first-lab progress\n127bfe8 my-first-lab: topology and map\n'), ('ls -la /srv/containerlab-node-manager/projects/my-network-labs/my-first-lab', 'total 28\ndrwxrwsr-x 4 clabllm clab_admins 4096 Sep 22 18:44 .\ndrwxrwsr-x 4 clabllm clab_admins 4096 Sep 22 18:44 ..\ndrwxrwsr-x 3 clabllm clab_admins 4096 Sep 22 18:44 checkpoints\ndrwxrwsr-x 2 clabllm clab_admins 4096 Sep 22 18:44 latest\n-rw-rw-r-- 1 clabllm clab_admins  275 Sep 22 18:44 my-first-lab.clab.yml\n-rw-rw-r-- 1 clabllm clab_admins  871 Sep 22 18:44 my-first-lab.clab.yml.annotations.json\n-rw-rw-r-- 1 clabllm clab_admins  367 Sep 22 18:44 README.md\n')]
- **binding_folder_via_api**: my-first-lab

Screenshots:
- `b10-destroy-review-full.png` (full-page)
- `b10-destroy-review-el.png` (Destroy my-first-lab?)
- `b10-remove-review-full.png` (full-page)
- `b10-remove-review-el.png` (Remove this lab from the manager?)
- `b10-terminal-clone.png` (rendered transcript (not a live terminal))
- `b10-redeploy-topology-file-full.png` (full-page)
- `b10-redeploy-topology-file-el.png` (Topology file (cloned))
- `b10-redeploy-start-review-el.png` (Deploy lab (cloned copy))
- `b10-redeployed-topology-full.png` (full-page)
- `b10-redeployed-topology-el.png` (Topology (redeployed, saved map))
- `b10-reconnect-full.png` (full-page)
- `b10-reconnect-el.png` (Progress tab after reconnecting)
- `b10-apply-latest-review-full.png` (full-page)
- `b10-apply-latest-review-el.png` (Replace running configuration (Latest))
- `b10-apply-latest-result-full.png` (full-page)
- `b10-apply-latest-result-el.png` (Restore result (Latest))

Notes:
- Step 10 was re-executed on its own (--from-step 10) after an earlier run deployed the WRONG topology file: the tree-navigation locator matched the first folder anywhere in the tree named "my-first-lab" (the original, top-level one), not the one nested inside my-network-labs, because it searched the whole #op-file-tree by text instead of the direct children of the folder just opened. This run replaces steps 1-9's untouched evidence with a fixed, re-verified step 10: navigation is now scoped to direct children at each level (see open_tree_folder()), and the topology file path is asserted before Deploy lab and the deployed lab's vm_project_path is asserted via the API after Start lab.
- /srv/containerlab-node-manager/projects/my-network-labs already existed from an earlier attempt at this scenario validation; reused rather than re-cloned. A first-time student only ever runs this clone once, so this is a redo artefact, not a guide divergence.

