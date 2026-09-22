#!/usr/bin/env python3
"""Final acceptance replay driver for Scenario B of the student quick-start
guide (guide-under-test.pdf, sha256 e53aa7b9af2f2542a7dd40b7e0b056dca1612586f3ff509f2b7bf03a2a1d475d).

QA tooling only. Consolidated, runnable record of the steps actually driven
interactively against http://127.0.0.1:8081 during the final replay (each
step's result was inspected before moving on; see final-replay-b.md for the
verdicts). Uses final_pw.py's CDP-connect helper for one fresh browser
context for the whole scenario session.

Substitutions used for this run (per the QA task assignment):
    Repository created in B5:  my-network-labs-qa2  (in place of my-network-labs)
    GitHub account: pruger-dev (gh CLI already authenticated as this user)

Usage (needs a persistent Chromium already listening on CDP 127.0.0.1:9333):
    LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps \
    clab-backup-ui/.venv/bin/python docs/student-quick-start/evidence/qa/final_scenario_b.py

B5 (create the repository) and B7 (publish the topology files, "on the lab
VM as your ordinary account") are plain shell/gh commands, run separately —
see final-replay-b.md for the exact commands and their output.
"""
import time
import final_pw as fpw

REPO_URL = "https://github.com/pruger-dev/my-network-labs-qa2.git"


def wait_for(page, text, timeout=180, interval=4):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if text in page.locator("body").inner_text():
            return True
        time.sleep(interval)
    return False


def run():
    p, browser = fpw.connect()
    ctx = fpw.new_context(browser)
    page = ctx.new_page()

    # B1
    page.goto(fpw.BASE, wait_until="networkidle")
    fpw.shot(page, "final-b1-home.png")
    page.get_by_text("Open the lab builder", exact=True).click()
    page.get_by_text("New lab…", exact=True).click()
    page.get_by_label("Lab name").fill("my-first-lab")
    page.locator("#builder-new-starter").select_option(label="Two devices, one link")
    page.locator("#builder-new-template").select_option(label="Arista cEOS · n24l/ceos:4.35.0F")
    page.locator("#builder-new-root").select_option(label="/srv/containerlab-node-manager/projects")
    fpw.shot(page, "final-b1c-new-lab-filled.png")
    page.get_by_role("button", name="Create draft").click()
    page.wait_for_timeout(1500)
    fpw.shot(page, "final-b1d-draft-created.png")

    # B2 — rename/set image+version+mgmt-ip for both nodes, add a text note
    for old_name, new_name, mgmt_ip in (("ceos1", "r1", "172.20.20.21"), ("ceos2", "r2", "172.20.20.22")):
        page.locator(f"text={old_name}").click(button="right")
        page.get_by_text("Edit Node", exact=True).click()
        page.wait_for_timeout(400)
        page.get_by_role("textbox").nth(0).fill(new_name)
        page.get_by_text("Network", exact=True).click()
        page.wait_for_timeout(300)
        page.get_by_role("textbox").nth(0).fill(mgmt_ip)
        page.get_by_text("Basic", exact=True).click()  # PDF: glance at Basic before Apply
        page.wait_for_timeout(300)
        page.get_by_text("APPLY").last.click()
        page.wait_for_timeout(500)
    fpw.shot(page, "final-b2i-r2-applied.png")

    page.locator("body").click(position={"x": 400, "y": 650}, button="right")
    page.get_by_text("Add Text", exact=True).click()
    page.mouse.click(623, 678)
    page.keyboard.type("My first lab: r1 eth1 - r2 eth1")
    page.mouse.click(300, 200)
    page.keyboard.press("Escape")
    fpw.shot(page, "final-b2m-canvas-final.png")

    page.get_by_role("button", name="View YAML").click()
    page.wait_for_timeout(500)
    fpw.shot(page, "final-b2n-view-yaml.png")
    page.keyboard.press("Escape")

    # B3 — save to VM and deploy
    page.get_by_role("button", name="Save to the VM…").click()
    page.wait_for_timeout(700)
    fpw.shot(page, "final-b3a-save-review.png")
    page.get_by_role("button", name="Save lab", exact=True).click()
    wait_for(page, "Saved on the VM", timeout=20, interval=1)
    fpw.shot(page, "final-b3b-saved.png")
    page.get_by_role("button", name="Deploy or add this lab…").click()
    page.wait_for_timeout(700)
    fpw.shot(page, "final-b3c-topology-dialog.png")
    page.get_by_role("button", name="Deploy lab", exact=True).click()
    page.wait_for_timeout(2000)
    fpw.shot(page, "final-b3d-start-review.png")
    page.get_by_role("button", name="Start lab", exact=True).first.click()
    wait_for(page, "Operation completed", timeout=40, interval=2)
    fpw.shot(page, "final-b3f-deployed.png")
    page.keyboard.press("Escape")
    page.get_by_text("← My labs", exact=True).click()
    wait_for(page, "2 of 2 devices ready", timeout=180, interval=4)
    fpw.shot(page, "final-b4a-ready.png")

    # B4 — bring the link up
    page.get_by_role("tab", name="Devices").click()
    with ctx.expect_page() as pinfo:
        page.locator("button.ssh-action[data-terminal='clab-my-first-lab-r1']").nth(1).click()
    r1 = pinfo.value
    r1.wait_for_load_state()
    wait_for(r1, "Connected", timeout=30, interval=1)
    r1.locator("body").click()
    for cmd in ("enable", "configure terminal", "ip routing", "interface Ethernet1",
                "no switchport", "ip address 10.0.0.1/30", "end", "write memory"):
        r1.keyboard.type(cmd)
        r1.keyboard.press("Enter")
        r1.wait_for_timeout(700)

    page.bring_to_front()
    with ctx.expect_page() as pinfo:
        page.locator("button.ssh-action[data-terminal='clab-my-first-lab-r2']").nth(1).click()
    r2 = pinfo.value
    r2.wait_for_load_state()
    wait_for(r2, "Connected", timeout=30, interval=1)
    r2.locator("body").click()
    for cmd in ("enable", "configure terminal", "ip routing", "interface Ethernet1",
                "no switchport", "ip address 10.0.0.2/30", "end", "write memory"):
        r2.keyboard.type(cmd)
        r2.keyboard.press("Enter")
        r2.wait_for_timeout(700)

    r1.bring_to_front()
    r1.locator("body").click()
    r1.keyboard.type("ping 10.0.0.2")
    r1.keyboard.press("Enter")
    r1.wait_for_timeout(3000)
    fpw.shot(r1, "final-b4d-ping.png")

    # B5 (create the repo) and B7 (publish topology) are plain shell/gh
    # commands run outside this browser session — see final-replay-b.md.

    # B6 — connect the repository and save
    page.bring_to_front()
    page.get_by_role("tab", name="Progress").click()
    page.get_by_role("button", name="Connect a repository by URL", exact=True).click()
    page.get_by_label("Repository URL").fill(REPO_URL)
    page.get_by_label("Folder for this lab").fill("my-first-lab")
    page.locator("#git-connect-ack").check()
    page.get_by_role("button", name="Connect repository").click()
    wait_for(page, "saves to", timeout=30, interval=1)
    fpw.shot(page, "final-b6c-connected.png")
    page.locator("#git-save-progress").click()
    wait_for(page, "Review before uploading", timeout=30, interval=1)
    fpw.shot(page, "final-b6d-review.png")
    page.get_by_role("button", name="Upload these changes").click()
    wait_for(page, "Saved to Git just now", timeout=30, interval=1)
    page.keyboard.press("Escape")

    # B8 — browse the repository (page reload recommended right after an
    # out-of-band VM git push; see final-replay-b.md finding)
    page.reload(wait_until="networkidle")
    page.get_by_role("tab", name="Progress").click()
    page.wait_for_timeout(700)
    page.get_by_role("button", name="Browse the repository…").click()
    page.wait_for_timeout(1200)
    fpw.shot(page, "final-b8d-after-browse-click.png")

    # B9 — change, save, checkpoint again
    r2.bring_to_front()
    r2.locator("body").click()
    for cmd in ("enable", "configure terminal", "interface Loopback0",
                "description r2 loopback", "ip address 10.255.0.2/32", "end",
                "write memory", "show ip interface brief"):
        r2.keyboard.type(cmd)
        r2.keyboard.press("Enter")
        r2.wait_for_timeout(700)

    page.bring_to_front()
    page.locator("#git-save-progress").click()
    wait_for(page, "Review before uploading", timeout=30, interval=1)
    fpw.shot(page, "final-b9b-review.png")
    page.get_by_role("button", name="Upload these changes").click()
    page.wait_for_timeout(4000)
    page.keyboard.press("Escape")

    page.get_by_role("button", name="Create checkpoint…").click()
    page.get_by_label("Checkpoint name").fill("link-up")
    page.get_by_role("button", name="Create checkpoint", exact=True).click()
    wait_for(page, "Review before uploading", timeout=20, interval=1)
    page.get_by_role("button", name="Upload these changes").click()
    page.wait_for_timeout(4000)
    page.keyboard.press("Escape")

    # B10 — destroy, remove; clone into the trusted folder is a shell
    # command (`git clone … /srv/containerlab-node-manager/projects/…`),
    # run separately — see final-replay-b.md.
    page.get_by_role("button", name="Lab actions").click()
    page.get_by_role("menuitem", name="Destroy lab…").click()
    page.wait_for_timeout(700)
    fpw.shot(page, "final-b10a-destroy-review.png")
    page.get_by_role("button", name="Destroy lab", exact=True).click()
    wait_for(page, "Stopped", timeout=30, interval=2)

    page.get_by_role("button", name="Lab actions").click()
    page.get_by_role("menuitem", name="Remove from this manager…").click()
    page.wait_for_timeout(700)
    page.get_by_role("button", name="Remove lab", exact=True).click()
    page.wait_for_timeout(2000)

    # Redeploy from the clone, path-checked, then reconnect and apply Latest
    page.get_by_text("Choose a file on the lab VM…").click()
    page.get_by_text("/srv/containerlab-node-manager/projects", exact=True).click()
    page.get_by_label("Lab topology files").get_by_text("my-network-labs-qa2", exact=True).click()
    page.get_by_label("Lab topology files").get_by_text("my-first-lab", exact=True).nth(1).click()
    page.get_by_role("button", name="◇ my-first-lab.clab.yml").click()
    page.wait_for_timeout(800)
    fpw.shot(page, "final-b10h-topology-dialog.png")
    # PDF: check File location on the VM contains "my-network-labs-qa2"
    path = page.get_by_role("textbox").nth(0).input_value()
    assert "my-network-labs-qa2" in path, path
    page.get_by_role("button", name="Deploy lab", exact=True).click()
    page.wait_for_timeout(2000)
    page.locator("#op-confirm").click()
    wait_for(page, "2 of 2 devices ready", timeout=180, interval=4)
    fpw.shot(page, "final-b10j-redeployed-ready.png")

    page.get_by_role("tab", name="Progress").click()
    page.get_by_role("button", name="Connect a repository by URL", exact=True).click()
    page.get_by_label("Repository URL").fill(REPO_URL)
    page.get_by_label("Folder for this lab").fill("my-first-lab")
    page.locator("#git-connect-ack").check()
    page.get_by_role("button", name="Connect repository").click()
    wait_for(page, "saves to", timeout=30, interval=1)
    fpw.shot(page, "final-b10l-reconnected.png")

    page.get_by_role("button", name="Apply to running lab…").nth(0).click()
    page.wait_for_timeout(3000)
    fpw.shot(page, "final-b10m-apply-review.png")
    page.locator("#restore-ack").check()
    page.locator("#restore-run").click()
    wait_for(page, "Configuration replaced", timeout=40, interval=2)
    page.keyboard.press("Escape")

    r1.bring_to_front()
    r1.locator("body").click()
    r1.keyboard.type("ping 10.0.0.2")
    r1.keyboard.press("Enter")
    r1.wait_for_timeout(3000)
    fpw.shot(r1, "final-b10o-r1-ping.png")

    ctx.close()
    p.stop()


if __name__ == "__main__":
    run()
