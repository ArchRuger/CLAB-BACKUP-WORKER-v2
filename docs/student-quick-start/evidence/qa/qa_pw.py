"""QA replay tooling for the student quick-start guide.

Connects to a persistent headless Chromium started out-of-band (CDP on
127.0.0.1:9333) so a shell-tool session can drive the browser across many
short-lived bash invocations while keeping one browser context per scenario
(a fresh context per scenario session, as required by the QA task).

Not part of the guide; QA tooling only.
"""
import os
import sys
from playwright.sync_api import sync_playwright

CDP_URL = "ws://127.0.0.1:9333/devtools/browser"
BASE = "http://127.0.0.1:8081"
EVIDENCE_DIR = os.path.dirname(os.path.abspath(__file__))


def connect():
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
    return p, browser


def new_context(browser, label):
    """Create a brand-new context (and close any others tagged for this
    scenario) so nothing cached from a previous session fills a gap."""
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    ctx._qa_label = label
    return ctx


def shot(page, name):
    path = os.path.join(EVIDENCE_DIR, name)
    page.screenshot(path=path)
    return path
