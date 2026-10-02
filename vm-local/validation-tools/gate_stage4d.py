import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
pw, b, ctx, r = session('stage4d'); p = r.page
r.open_lab(); r.tab('advanced')
try:
    p.wait_for_function('() => document.querySelectorAll("#log-rows tr, #log-rows li").length > 0', timeout=15000); r.check('N action logs: rows render on the Advanced tab within one poll', True)
except Exception as exc: r.check('N action logs: rows render on the Advanced tab within one poll', False, r.js('() => ({status: document.getElementById("log-status")?.textContent, html: document.getElementById("logs-view")?.textContent.replace(/\\s+/g," ").slice(0,300)})'))
r.note('logs', r.js('() => ({rows: document.querySelectorAll("#log-rows tr, #log-rows li").length, status: document.getElementById("log-status")?.textContent, first: document.querySelector("#log-rows tr, #log-rows li")?.textContent.replace(/\\s+/g," ").slice(0,160)})')); r.shot('N-action-logs', full=True)
link = p.locator('a[href*="workspace.html"]').first; r.note('cli launcher link', link.get_attribute('href') if link.count() else None)
r.tab('tools'); lnk = p.locator('#tools-ssh-all, a[href*="mode=ssh"]').first
with ctx.expect_page(timeout=15000) as pop: lnk.click()
w = pop.value; r.attach(w); w.wait_for_selector('#ssh-launch-all', timeout=15000); w.wait_for_timeout(500)
ws = w.evaluate('() => ({title: document.getElementById("workspace-title").textContent, rows: document.querySelectorAll(".op-session-row").length, pills: [...document.querySelectorAll(".op-session-row .pill")].map(x => x.textContent)})'); r.note('CLI launcher', ws)
r.check('N CLI launcher: Open CLIs page lists both devices with Ready pills', ws['title'].startswith('Open CLIs') and ws['rows'] == 2 and all(x == 'Ready' for x in ws['pills']), ws); r.shot('N-cli-launcher', page=w); w.close()
r.tab('progress'); p.wait_for_selector('#git-save-progress', timeout=15000); p.wait_for_function('() => !busy()', timeout=120000)
p.click('#git-save-progress'); p.wait_for_function('() => document.getElementById("git-save-progress").textContent === "Saving…"', timeout=20000); p.wait_for_timeout(500)
p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); menu = r.js('() => [...document.querySelectorAll("#lab-actions-menu button")].map(b => ({t: (b.querySelector("span")?.textContent || b.textContent).trim().slice(0,30), d: b.disabled, r: b.querySelector(".menu-reason")?.textContent || ""}))'); r.note('menu while saving', menu)
r.check('F busy: while Save progress runs, Stop/Restart/Redeploy/Destroy are disabled with a visible reason', all(m['d'] and m['r'] for m in menu if any(k in m['t'] for k in ('Stop', 'Restart', 'Redeploy', 'Destroy'))), menu); r.shot('F-busy-menu'); p.keyboard.press('Escape')
p.wait_for_function('() => document.getElementById("git-save-progress").textContent === "Save progress" && !/Saving/.test(document.getElementById("git-progress-status").textContent)', timeout=420000)
r.check('F busy: the save completed afterwards (Saved to Git)', r.js('() => document.getElementById("git-progress-status").textContent').startswith('Saved to Git'), r.js('() => document.getElementById("git-progress-status").textContent'))
r.report('stage4d'); b.close(); pw.stop()
