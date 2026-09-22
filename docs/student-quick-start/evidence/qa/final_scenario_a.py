#!/usr/bin/env python3
"""Final acceptance replay driver for Scenario A of the student quick-start
guide (guide-under-test.pdf, sha256 e53aa7b9af2f2542a7dd40b7e0b056dca1612586f3ff509f2b7bf03a2a1d475d).

QA tooling only, not the guide's own content. This is a consolidated,
runnable record of the steps actually driven interactively against
http://127.0.0.1:8081 during the final replay (each step's result was
inspected — screenshot plus captured page/terminal text — before moving on;
see final-replay-a.md for the verdicts). It mirrors final_scenario_b.py's
structure and uses final_pw.py's CDP-connect helper so the whole scenario
runs in one fresh browser context, per the QA task's environment note.

Repository substitution used for this run (per the QA task assignment):
    https://github.com/pruger-dev/netlab-course-qa2.git
    (in place of the guide's netlab-course-student.git)

Usage (needs a persistent Chromium already listening on CDP 127.0.0.1:9333,
e.g. `chrome --headless=new --remote-debugging-port=9333`):
    LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps \
    clab-backup-ui/.venv/bin/python docs/student-quick-start/evidence/qa/final_scenario_a.py
"""
import time
import final_pw as fpw

REPO_URL = "https://github.com/pruger-dev/netlab-course-qa2.git"
REPO_FOLDER = "link-basics/work"


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

    # A1
    page.goto(fpw.BASE, wait_until="networkidle")
    assert "No labs yet" in page.locator("body").inner_text()
    fpw.shot(page, "final-a1-home.png")

    # A2
    page.get_by_text("Choose a file on the lab VM…").click()
    page.get_by_text("/srv/containerlab-node-manager/projects", exact=True).click()
    page.get_by_text("link-basics", exact=True).click()
    page.get_by_text("link-basics.clab.yml").click()
    fpw.shot(page, "final-a2d-topology-dialog.png")
    page.get_by_role("button", name="Deploy lab", exact=True).click()
    page.wait_for_timeout(1200)
    fpw.shot(page, "final-a2e-start-review.png")
    page.locator("#op-confirm").click()

    # A3
    wait_for(page, "2 of 2 devices ready")
    fpw.shot(page, "final-a3b-ready.png")

    # A4
    page.get_by_role("tab", name="Devices").click()
    with ctx.expect_page() as pinfo:
        page.locator("button.ssh-action[data-terminal='clab-link-basics-r1']").nth(1).click()
    r1term = pinfo.value
    r1term.wait_for_load_state()
    wait_for(r1term, "Connected", timeout=30, interval=1)
    r1term.locator("body").click()
    for cmd in ("show version", "show interfaces status", "show ip interface brief"):
        r1term.keyboard.type(cmd)
        r1term.keyboard.press("Enter")
        r1term.wait_for_timeout(1200)
    fpw.shot(r1term, "final-a4b-terminal-shows.png")

    # A5
    page.bring_to_front()
    page.get_by_role("tab", name="Progress").click()
    page.get_by_role("button", name="Connect a repository by URL", exact=True).click()
    page.get_by_label("Repository URL").fill(REPO_URL)
    page.get_by_label("Folder for this lab").fill(REPO_FOLDER)
    page.get_by_role("checkbox").check()
    page.get_by_role("button", name="Connect repository").click()
    wait_for(page, "Instructor and reference versions", timeout=30, interval=1)
    fpw.shot(page, "final-a5d-progress-connected.png")

    # A6 — apply Starting state (3rd Apply button: broken-01, solution, start)
    btn = page.get_by_role("button", name="Apply to running lab…")
    btn.nth(2).click()
    page.wait_for_timeout(3000)
    fpw.shot(page, "final-a6b-review.png")
    page.locator("#restore-ack").check()
    page.locator("#restore-run").click()
    wait_for(page, "Configuration replaced", timeout=40, interval=2)
    fpw.shot(page, "final-a6c-replaced.png")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")

    r1term.bring_to_front()
    r1term.locator("body").click()
    r1term.keyboard.type("ping 10.0.0.2")
    r1term.keyboard.press("Enter")
    r1term.wait_for_timeout(3000)
    fpw.shot(r1term, "final-a6d-ping.png")

    # A7
    for cmd in (
        "enable", "configure terminal", "interface Loopback0",
        "description r1 loopback", "ip address 10.255.0.1/32", "end",
        "write memory", "show ip interface brief",
    ):
        r1term.keyboard.type(cmd)
        r1term.keyboard.press("Enter")
        r1term.wait_for_timeout(700)
    fpw.shot(r1term, "final-a7-loopback.png")

    # A8
    page.bring_to_front()
    page.locator("#git-save-progress").click()
    wait_for(page, "Review before uploading", timeout=30, interval=1)
    fpw.shot(page, "final-a8a-review.png")
    page.get_by_role("button", name="Upload these changes").click()
    wait_for(page, "Saved to Git just now", timeout=30, interval=1)
    fpw.shot(page, "final-a8b-uploaded.png")

    # A9 — checkpoint, then r2's loopback, second save+upload
    page.get_by_role("button", name="Create checkpoint…").click()
    page.get_by_label("Checkpoint name").fill("loopback-added")
    page.get_by_role("button", name="Create checkpoint", exact=True).click()
    wait_for(page, "Review before uploading", timeout=20, interval=1)
    page.get_by_role("button", name="Upload these changes").click()
    page.wait_for_timeout(2000)
    page.keyboard.press("Escape")

    page.get_by_role("tab", name="Devices").click()
    with ctx.expect_page() as pinfo:
        page.locator("button.ssh-action[data-terminal='clab-link-basics-r2']").nth(1).click()
    r2term = pinfo.value
    r2term.wait_for_load_state()
    wait_for(r2term, "Connected", timeout=30, interval=1)
    r2term.locator("body").click()
    for cmd in (
        "enable", "configure terminal", "interface Loopback0",
        "description r2 loopback", "ip address 10.255.0.2/32", "end",
        "write memory", "show ip interface brief",
    ):
        r2term.keyboard.type(cmd)
        r2term.keyboard.press("Enter")
        r2term.wait_for_timeout(700)
    fpw.shot(r2term, "final-a9e-r2-loopback.png")

    page.bring_to_front()
    page.get_by_role("tab", name="Progress").click()
    page.locator("#git-save-progress").click()
    wait_for(page, "Review before uploading", timeout=30, interval=1)
    fpw.shot(page, "final-a9f-second-save-review.png")
    page.get_by_role("button", name="Upload these changes").click()
    wait_for(page, "Saved to Git", timeout=30, interval=2)
    page.wait_for_timeout(3000)
    fpw.shot(page, "final-a9i-saved-versions-final.png")

    # A10 — break it (Troubleshooting scenario 01), then recover with Latest
    btn = page.get_by_role("button", name="Apply to running lab…")
    btn.nth(2).click()  # broken-01, given Latest(0) + checkpoint(1) precede it here
    page.wait_for_timeout(3000)
    fpw.shot(page, "final-a10b-review.png")
    page.locator("#restore-ack").check()
    page.locator("#restore-run").click()
    wait_for(page, "Configuration replaced", timeout=40, interval=2)
    page.keyboard.press("Escape")

    r1term.bring_to_front()
    r1term.locator("body").click()
    for cmd in ("ping 10.0.0.2", "show interfaces status"):
        r1term.keyboard.type(cmd)
        r1term.keyboard.press("Enter")
        r1term.wait_for_timeout(2500)
    fpw.shot(r1term, "final-a10d-r1-broken.png")
    # Note: the very first ping right after "Configuration replaced" can
    # transiently still succeed before the interface actually drops; a
    # second check a few seconds later reliably shows the fault (see
    # final-replay-a.md, cosmetic finding).

    page.bring_to_front()
    btn = page.get_by_role("button", name="Apply to running lab…")
    btn.nth(0).click()  # Latest
    page.wait_for_timeout(3000)
    fpw.shot(page, "final-a10f-recover-review.png")
    page.locator("#restore-ack").check()
    page.locator("#restore-run").click()
    wait_for(page, "Configuration replaced", timeout=40, interval=2)
    page.keyboard.press("Escape")

    r1term.bring_to_front()
    r1term.locator("body").click()
    r1term.keyboard.type("ping 10.0.0.2")
    r1term.keyboard.press("Enter")
    r1term.wait_for_timeout(3000)
    fpw.shot(r1term, "final-a10h-r1-recovered.png")

    # A11 — close/reopen browser (new context), Lab actions, Destroy/Remove
    # reviews viewed then cancelled (leave the lab running, per the task).
    ctx.close()
    ctx2 = fpw.new_context(browser)
    page2 = ctx2.new_page()
    page2.goto(fpw.BASE, wait_until="networkidle")
    fpw.shot(page2, "final-a11a-home-reopened.png")
    page2.get_by_role("button", name="Open lab").click()
    page2.get_by_role("tab", name="Progress").click()
    page2.wait_for_timeout(1500)
    fpw.shot(page2, "final-a11b-progress-persisted.png")

    page2.get_by_role("button", name="Lab actions").click()
    fpw.shot(page2, "final-a11c-lab-actions-menu.png")
    page2.get_by_role("menuitem", name="Destroy lab…").click()
    page2.wait_for_timeout(700)
    fpw.shot(page2, "final-a11d-destroy-review.png")
    page2.get_by_role("button", name="Cancel").click()

    page2.get_by_role("button", name="Lab actions").click()
    page2.get_by_role("menuitem", name="Remove from this manager…").click()
    page2.wait_for_timeout(700)
    fpw.shot(page2, "final-a11e-remove-review.png")
    page2.get_by_role("button", name="Cancel").click()

    ctx2.close()
    p.stop()


if __name__ == "__main__":
    run()
