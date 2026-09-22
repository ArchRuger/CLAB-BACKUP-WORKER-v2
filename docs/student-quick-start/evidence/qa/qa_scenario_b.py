#!/usr/bin/env python3
"""QA replay driver for Scenario B of the student quick-start guide.

QA tooling (not the guide's own content). Mirrors the interactive replay of
steps B1-B10 against http://127.0.0.1:8081, using one fresh browser context
for the whole session, and saves qa-b<step>-*.png evidence.

Repository substitution used for this run (per the QA task assignment):
    my-network-labs-qa (in place of the guide's my-network-labs), created
    with: gh repo create my-network-labs-qa --private --add-readme

Step B7 (publish the topology files) and part of B10 (clone into the
trusted VM folder) run git/gh directly on the lab VM as the ordinary
account, not through the browser — see qa-replay-b.md for the exact
commands and their output.
"""
import os
import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8081"
EVDIR = os.path.dirname(os.path.abspath(__file__))
REPO_URL = "https://github.com/pruger-dev/my-network-labs-qa.git"


def shot(page, name):
    page.screenshot(path=os.path.join(EVDIR, name))


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        time.sleep(1)

        # B1: New lab in the builder
        with ctx.expect_page() as pinfo:
            page.get_by_text("Open the lab builder", exact=True).click()
        # (lab builder navigates the SAME tab in this build; kept here for
        # documentation of the attempted popup pattern — see qa-replay-b.md
        # for the same-tab fallback actually used.)
        builder = page
        builder.get_by_text("New lab…", exact=True).click()
        time.sleep(1)
        builder.get_by_label("Lab name").fill("my-first-lab")
        builder.locator("#builder-new-starter").select_option(label="Two devices, one link")
        builder.locator("#builder-new-root").select_option(label="/srv/containerlab-node-manager/projects")
        shot(builder, "qa-b1a-new-lab-filled.png")
        builder.get_by_role("button", name="Create draft").click()
        time.sleep(2)
        shot(builder, "qa-b1b-draft-created.png")

        # B2: rename nodes, set mgmt IPs, add note
        for old, new, ip in (("ceos1", "r1", "172.20.20.21"), ("ceos2", "r2", "172.20.20.22")):
            builder.locator(f"text={old}").first.click(button="right")
            time.sleep(0.5)
            builder.get_by_text("Edit Node", exact=True).click()
            time.sleep(0.5)
            builder.locator("#node-name").fill(new)
            builder.get_by_text("Network", exact=True).click()
            time.sleep(0.3)
            builder.locator("#node-mgmt-ipv4").fill(ip)
            builder.get_by_role("button", name="Apply", exact=True).click()
            time.sleep(0.5)
        builder.locator(".react-flow__pane").click(button="right", position={"x": 400, "y": 650})
        time.sleep(0.5)
        builder.get_by_text("Add Text", exact=True).click()
        time.sleep(0.5)
        builder.mouse.click(620, 777)
        builder.keyboard.type("My first lab: r1 eth1 - r2 eth1")
        builder.mouse.click(1000, 200)
        shot(builder, "qa-b2j-canvas-final.png")

        # B3: Save to the VM, deploy
        builder.get_by_role("button", name="Save to the VM…").click()
        time.sleep(1)
        shot(builder, "qa-b3a-save-review.png")
        builder.get_by_role("button", name="Save lab", exact=True).click()
        time.sleep(3)
        builder.get_by_role("button", name="Deploy or add this lab…").click()
        time.sleep(1)
        builder.locator("button:has-text('Deploy lab')").click()
        time.sleep(1.5)
        builder.locator("#op-confirm").click()
        time.sleep(12)
        shot(builder, "qa-b3f-deployed.png")

        print("Scenario B driver reached B3; remaining steps (B4-B10,")
        print("including the VM-side git/gh commands for B7 and B10) were")
        print("run interactively — see qa-replay-b.md for the full record.")
        ctx.close()
        browser.close()


if __name__ == "__main__":
    run()
