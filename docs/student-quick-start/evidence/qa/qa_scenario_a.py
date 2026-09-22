#!/usr/bin/env python3
"""QA replay driver for Scenario A of the student quick-start guide.

This is QA tooling (not the guide's own content). It drives the manager UI
at http://127.0.0.1:8081 with Playwright the way the PDF describes step A1
through A11, using a single fresh browser context for the whole scenario
session, and saves qa-a<step>-*.png screenshots plus a findings log.

It documents, in runnable form, the steps this agent actually replayed
interactively while verifying the guide; it is not guaranteed to run
unattended end-to-end (some steps need timing-sensitive waits for VM
operations), but each block mirrors a verified interactive step.

Usage:
    LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps \
    clab-backup-ui/.venv/bin/python docs/student-quick-start/evidence/qa/qa_scenario_a.py

Repository substitution used for this run (per the QA task assignment):
    https://github.com/pruger-dev/netlab-course-qa.git  (in place of the
    guide's netlab-course-student.git)
"""
import os
import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8081"
EVDIR = os.path.dirname(os.path.abspath(__file__))
REPO_URL = "https://github.com/pruger-dev/netlab-course-qa.git"
REPO_FOLDER = "link-basics/work"


def shot(page, name):
    page.screenshot(path=os.path.join(EVDIR, name))


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()

        # A1: Open the manager
        page.goto(BASE, wait_until="networkidle")
        time.sleep(1)
        shot(page, "qa-a1-home.png")
        assert "No labs yet" in page.locator("body").inner_text()

        # A2: Deploy the lab (browse VM folders to link-basics.clab.yml)
        page.get_by_text("Choose a file on the lab VM…").click()
        time.sleep(1)
        page.get_by_text("/srv/containerlab-node-manager/projects", exact=True).click()
        time.sleep(1)
        page.get_by_text("link-basics", exact=True).click()
        time.sleep(1)
        page.get_by_text("link-basics.clab.yml").click()
        time.sleep(1)
        shot(page, "qa-a2-topology-dialog.png")
        page.get_by_text("Deploy lab", exact=True).click()
        time.sleep(1.5)
        shot(page, "qa-a2b-start-review.png")
        page.locator("#op-confirm").click()
        time.sleep(1)
        shot(page, "qa-a3a-starting.png")

        # A3: wait for readiness
        deadline = time.time() + 150
        while time.time() < deadline:
            if "2 of 2 devices ready" in page.locator("body").inner_text():
                break
            time.sleep(5)
        shot(page, "qa-a3b-ready.png")

        # A4: Open CLI on r1, run three show commands
        page.get_by_role("tab", name="Devices").click()
        time.sleep(0.5)
        with ctx.expect_page() as pinfo:
            page.locator("text=Open CLI").nth(0).click()
        r1term = pinfo.value
        r1term.wait_for_load_state()
        deadline = time.time() + 30
        while time.time() < deadline:
            if "Connected" in r1term.locator("body").inner_text():
                break
            time.sleep(1)
        r1term.locator("body").click()
        for cmd in ("show version", "show interfaces status", "show ip interface brief"):
            r1term.keyboard.type(cmd)
            r1term.keyboard.press("Enter")
            time.sleep(1.5)
        shot(r1term, "qa-a4-terminal-shows.png")

        # A5: Connect the repository
        page.bring_to_front()
        page.get_by_role("tab", name="Progress").click()
        time.sleep(0.5)
        page.get_by_text("Connect a repository by URL", exact=True).click()
        time.sleep(0.5)
        page.get_by_label("Repository URL").fill(REPO_URL)
        page.get_by_label("Folder for this lab").fill(REPO_FOLDER)
        page.get_by_role("checkbox").check()
        shot(page, "qa-a5b-connect-dialog-filled.png")
        page.get_by_role("button", name="Connect repository").click()
        time.sleep(5)
        shot(page, "qa-a5c-progress-connected.png")

        # A6: apply Starting state, tick ack, confirm
        page.locator("button:has-text('Apply to running lab')").nth(2).click()
        time.sleep(2)
        shot(page, "qa-a6a-review.png")
        page.locator("#restore-ack").check()
        page.locator("#restore-run").click()
        time.sleep(8)
        shot(page, "qa-a6b-replaced.png")

        # A7: r1 loopback via terminal
        r1term.bring_to_front()
        for cmd in (
            "enable", "configure terminal", "interface Loopback0",
            "description r1 loopback", "ip address 10.255.0.1/32", "end",
            "write memory", "show ip interface brief",
        ):
            r1term.keyboard.type(cmd)
            r1term.keyboard.press("Enter")
            time.sleep(0.8)
        shot(r1term, "qa-a7-loopback.png")

        # A8: Save progress, upload
        page.bring_to_front()
        page.get_by_role("button", name="Save progress", exact=True).first.click()
        time.sleep(3)
        shot(page, "qa-a8a-review.png")
        page.get_by_role("button", name="Upload these changes").click()
        time.sleep(4)
        shot(page, "qa-a8b-uploaded.png")

        print("Scenario A driver reached A8; remaining steps (A9-A11) were")
        print("run interactively in the same fashion — see qa-replay-a.md")
        ctx.close()
        browser.close()


if __name__ == "__main__":
    run()
