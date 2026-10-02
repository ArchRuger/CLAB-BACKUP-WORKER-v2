"""Failure paths during boot: device not ready (menu/panel/launcher/terminal), save while devices are unavailable keeps the last complete snapshot."""
import json, os, re, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
def git(*a): return subprocess.run(['git', '-C', os.path.expanduser('~/labs/CLAB-MNGR-DEV-LLM')] + list(a), capture_output=True, text=True).stdout.strip()
pw, b, ctx, r = session('bootfail'); p = r.page
r.open_lab(); p.wait_for_selector('#topology-map [data-map-node]', timeout=20000); p.wait_for_timeout(500)
st = r.js('() => ({pill: document.getElementById("lab-state").textContent, ready: document.getElementById("lab-ready").textContent, banner: document.getElementById("lab-banner").hidden ? "" : document.getElementById("lab-banner-text").textContent})'); r.note('lab while booting', st)
node = p.locator('#topology-map [data-map-node$="-SW1"]').first; node.click(button='right'); p.wait_for_selector('#node-context-menu:not([hidden])')
menu = r.js('() => { const m = document.getElementById("node-context-menu"); return {header: m.querySelector(".context-node-name")?.textContent, items: [...m.querySelectorAll("[role=menuitem]")].map(b => ({t: b.textContent.trim().slice(0,60), d: b.disabled, r: b.querySelector("small")?.textContent}))}; }'); r.note('context menu on a starting device', menu)
r.check('F not ready: Open CLI disabled on a starting device with a plain reason (no backend error)', menu['items'][0]['d'] and 'starting' in (menu['items'][0]['r'] or '').lower() and 'Starting' in (menu['header'] or ''), menu); r.shot('F-starting-context-menu'); p.keyboard.press('Escape')
node.click(); p.wait_for_selector('#details-dialog[open]'); p.wait_for_timeout(400)
d = r.js('() => ({pill: document.getElementById("details-state").textContent, status: document.getElementById("details-status-text").textContent, primary: [...document.querySelectorAll("#details-actions button")].map(b => ({t: b.textContent.trim(), d: b.disabled, title: b.title})), actions: [...document.querySelectorAll("#details-status-actions button")].map(b => b.textContent.trim())})'); r.note('panel on a starting device', d)
r.check('F not ready: the device panel says Starting with a sentence and a disabled Open CLI', d['pill'] == 'Starting' and d['primary'] and d['primary'][0]['d'] and d['status'], d); r.shot('F-starting-panel'); p.keyboard.press('Escape')
labid = r.js('() => activeId'); p.goto(f'{BASE}/static/terminal.html#lab={labid}&node=clab-clab-llm-dev2-SW1&label=clab-llm-dev2'); p.wait_for_function('() => /Could not|not running|Disconnected|stale|Connecting|credentials|failed/i.test(document.getElementById("status").textContent)', timeout=60000); p.wait_for_timeout(2000)
t = r.js('() => ({status: document.getElementById("status").textContent, raw: document.getElementById("status").title, notice: document.getElementById("notice-text")?.textContent})'); r.note('terminal on a not-ready device', t)
r.check('F not ready: the terminal page explains the failure in student words with the raw reason in the title', t['status'] and not t['status'].startswith('Connected') and ('not running' in t['status'] or 'Could not connect' in t['status'] or 'Disconnected' in t['status']), t); r.shot('F-terminal-not-ready')
p.goto(f'{BASE}/#lab={labid}&view=progress'); p.wait_for_selector('#git-save-location', timeout=20000); p.wait_for_function('() => !busy()', timeout=600000); p.wait_for_timeout(1000)
head_before = git('rev-parse', 'HEAD'); latest_before = git('rev-parse', 'HEAD:clab-llm-dev2/work/latest')
sv = r.js('() => ({text: document.getElementById("git-save-progress").textContent, disabled: document.getElementById("git-save-progress").disabled, reason: document.getElementById("progress-save-reason")?.textContent, hidden: document.getElementById("progress-save-reason")?.hidden})'); r.note('save button while devices boot', sv)
if not sv['disabled']:
    p.click('#git-save-progress'); p.wait_for_timeout(1500)
    p.wait_for_function('() => document.getElementById("git-save-progress").textContent === "Save progress" && !/Saving/.test(document.getElementById("git-progress-status").textContent)', timeout=420000); p.wait_for_timeout(1500)
    res = r.js('() => ({status: document.getElementById("git-progress-status").textContent, saves: [...document.querySelectorAll("#git-saves-list .git-saved-job > summary")].map(s => s.textContent.replace(/\\s+/g," ").trim()).slice(0,2), jobOpen: !!document.getElementById("git-job-dialog")?.open, jobTitle: document.querySelector("#git-job-dialog h2")?.textContent, jobText: document.getElementById("git-job-detail")?.textContent.replace(/\\s+/g," ").slice(0,400)})'); r.note('save with devices unavailable', res)
    r.check('F save unavailable: the save needs attention and says which devices failed (window opens on its own)', res['jobOpen'] and 'attention' in (res['jobTitle'] or '').lower() and ('failed' in (res['jobText'] or '').lower() or 'unavailable' in (res['jobText'] or '').lower() or 'did not' in (res['jobText'] or '').lower()), res); r.shot('F-save-unavailable', full=True)
    if res['jobOpen']: p.click('#git-job-dialog [data-op-close]')
else:
    r.check('F save unavailable: Save progress is disabled with a visible reason while no device is ready', sv['reason'] and not sv['hidden'], sv); r.shot('F-save-disabled')
git('fetch', '-q'); r.check('F save unavailable: the repository latest/ is unchanged (incomplete capture never replaces the complete snapshot)', git('rev-parse', 'HEAD') == head_before and git('rev-parse', 'HEAD:clab-llm-dev2/work/latest') == latest_before and git('status', '--short') == '', (head_before[:8], git('rev-parse', 'HEAD')[:8]))
r.report('bootfail'); b.close(); pw.stop()
