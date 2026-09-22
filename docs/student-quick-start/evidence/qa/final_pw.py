"""Final acceptance replay tooling for the student quick-start guide.

Connects to a persistent headless Chromium started out-of-band (CDP on
127.0.0.1:9333) so a shell-tool session can drive the browser across many
short-lived bash invocations while using one fresh browser context per
scenario session, per the QA task's environment note.

Not part of the guide; QA tooling only. Adapted from qa_pw.py for the final
replay (own file, own screenshot prefix final-).
"""
import os
from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9333"
BASE = "http://127.0.0.1:8081"
EVIDENCE_DIR = os.path.dirname(os.path.abspath(__file__))


def connect():
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(CDP_URL)
    return p, browser


def new_context(browser):
    return browser.new_context(viewport={"width": 1366, "height": 900})


def shot(page, name):
    path = os.path.join(EVIDENCE_DIR, name)
    page.screenshot(path=path)
    return path
