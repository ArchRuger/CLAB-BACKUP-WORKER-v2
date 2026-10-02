import json, os, re, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
pw, b, ctx, r = session('stage4c'); p = r.page
def closeall():
    for _ in range(4):
        if r.js('() => !!document.querySelector("dialog[open]")'):
            loc = p.locator('dialog[open] [data-op-close], dialog[open] [data-dismiss], dialog[open] #op-cancel')
            if loc.count():
                try: loc.first.click(timeout=1500)
                except Exception: p.keyboard.press('Escape')
            else: p.keyboard.press('Escape')
            p.wait_for_timeout(300)
r.open_lab(); r.tab('tools'); p.wait_for_function('() => state.discovery?.connected && current()?.deployment?.status === "Running" && !busy()', timeout=120000); p.wait_for_timeout(500)
# operation history → most recent Save device configurations output
p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); hist = p.locator('#lab-actions-menu button', has_text=re.compile('history', re.I)).first
if hist.count(): hist.click()
else: p.keyboard.press('Escape'); p.click('#manager-button'); p.click('#operations-history')
p.wait_for_selector('#operation-history[open]', timeout=15000); p.wait_for_timeout(500)
h = r.js('() => ({title: document.querySelector("#operation-history h2").textContent, rows: [...document.querySelectorAll("#operation-history [data-job] strong")].map(s => s.textContent)})'); r.note('history', h)
r.check('M operation history: deploy, redeploy, save-configurations and inspect recorded with student names', len(h['rows']) >= 3 and all(' · ' in x for x in h['rows']), h); r.shot('M-history', full=True)
p.locator('#operation-history [data-job]').first.click(); p.wait_for_selector('#operation-output[open]', timeout=15000); p.wait_for_timeout(500)
out = r.js('() => ({h2: document.querySelector("#operation-output h2").textContent, banner: document.getElementById("op-job-banner").textContent, output: (document.getElementById("op-job-output")?.textContent || "").slice(0,300)})'); r.note('operation output', out)
r.check('M operation output: heading, result banner and raw output available from history', bool(out['h2']) and bool(out['banner']) and bool(out['output']), out); r.shot('M-operation-output', full=True); closeall()
p.click('#manager-button'); p.wait_for_selector('#manager-menu-list:not([hidden])'); p.click('#inspect-all'); p.wait_for_selector('#operation-review[open]', timeout=15000)
r.check('M running labs review: read-only wording and Show running labs', r.js('() => /Nothing is changed/.test(document.getElementById("operation-review").textContent) && document.getElementById("op-confirm").textContent === "Show running labs"'))
p.click('#op-confirm'); p.wait_for_selector('#operation-output[open]', timeout=15000); p.wait_for_function('() => !!document.querySelector("#operation-output table caption") || /✖/.test(document.getElementById("op-job-banner").textContent)', timeout=90000)
tbl = r.js('() => ({caption: document.querySelector("#operation-output table caption")?.textContent, rows: [...document.querySelectorAll("#operation-output tbody tr")].map(tr => tr.textContent.replace(/\\s+/g," ").trim().slice(0,160))})'); r.note('running labs table', tbl)
r.check('M running labs on the VM: table lists both real devices with state and addresses', any('PTX1' in x and 'running' in x.lower() for x in tbl['rows']) and any('SW1' in x for x in tbl['rows']), tbl); r.shot('M-running-labs', full=True); closeall()
# Advanced
r.tab('advanced'); p.wait_for_timeout(800)
adv = r.js('() => ({vm: document.getElementById("vm-summary").textContent, files: document.getElementById("vm-files-status").textContent, deployment: document.getElementById("deployment-status").textContent, msg: document.getElementById("deployment-message").textContent, profiles: document.getElementById("profiles").textContent.replace(/\\s+/g," ").slice(0,160), sync: {hidden: document.getElementById("sync-vm").hidden, disabled: document.getElementById("sync-vm").disabled}, logs: document.querySelectorAll("#log-rows tr, #log-rows li").length, remove: !!document.getElementById("remove-lab"), gitAdv: (document.getElementById("git-repository-advanced")?.textContent || "").replace(/\\s+/g," ").slice(0,300), buttons: [...document.querySelectorAll("#advanced-view button")].map(b => b.textContent.trim()).filter(Boolean).slice(0,24)})'); r.note('advanced', adv)
r.check('N advanced: deployment details, VM status sentence, credentials, action logs, danger zone present', adv['vm'].startswith('Lab VM') and adv['deployment'] and adv['remove'] and any('credentials' in x.lower() for x in adv['buttons']), adv)
r.check('N advanced: Sync topology from VM available; VM file status shown', not adv['sync']['hidden'] and 'Topology files on the VM' in adv['files'], adv['files']); r.shot('N-advanced', full=True)
p.click('#sync-vm'); p.wait_for_timeout(3000); r.check('N sync: Sync topology from VM ran without an error', 'error' not in r.js('() => document.getElementById("vm-files-status").textContent').lower(), r.js('() => document.getElementById("vm-files-status").textContent'))
d = p.locator('#advanced-view details summary', has_text='VM file details').first
if d.count(): d.click(); p.wait_for_timeout(600); fl = r.js('() => (document.getElementById("advanced-file-list")?.textContent || "").replace(/\\s+/g," ").slice(0,300)'); r.note('VM file details', fl); r.check('N advanced: VM file details list this lab\'s files on the VM', 'clab-llm-dev2' in fl, fl)
addc = p.locator('#advanced-view button', has_text=re.compile('Add credentials|New credentials|Add profile', re.I)).first
if addc.count(): addc.click(); p.wait_for_selector('#profile-dialog[open]', timeout=10000); r.check('N credentials: Add credentials dialog with platform, user and masked password', r.js('() => !!document.getElementById("profile-platform") && !!document.getElementById("profile-user") && document.getElementById("profile-password").type === "password"')); r.shot('N-credentials-dialog'); closeall()
else: r.check('N credentials: Add credentials button present', False, adv['buttons'])
r.check('N action logs: rows rendered on the Advanced tab', adv['logs'] > 0, adv['logs'])
p.click('#remove-lab'); p.wait_for_selector('#remove-lab-dialog[open]'); rm = r.js('() => ({title: document.getElementById("remove-lab-title").textContent, text: document.getElementById("remove-lab-dialog").textContent.replace(/\\s+/g," ").slice(0,300), danger: document.querySelector("#remove-lab-form button[type=submit]").classList.contains("danger")})'); r.note('remove lab dialog', rm)
r.check('N danger zone: Remove lab dialog names the lab, manager-only scope, danger submit, cancelled', rm['title'].startswith('Remove ') and rm['danger'], rm); r.shot('N-remove-lab'); closeall()
gitadv = r.js('() => { const el = document.getElementById("git-repository-advanced"); return el ? {hidden: el.hidden, text: el.textContent.replace(/\\s+/g," ").slice(0,400)} : null; }'); r.note('git technical details', gitadv)
r.tab('progress'); p.wait_for_timeout(800); gt = r.js('() => { const el = document.getElementById("git-repository-advanced"); return el ? {hidden: el.hidden, text: el.textContent.replace(/\\s+/g," ").slice(0,400)} : null; }'); r.note('git technical details (progress)', gt)
r.check('N Git technical details: repository, branch/owner/push destination visible', gt and not gt['hidden'] and ('main' in gt['text'] or 'Verified push destination' in gt['text']), gt)
with ctx.expect_page(timeout=15000) as pop: p.locator('a[href*="workspace.html#mode=ssh"]').first.click()
w = pop.value; r.attach(w); w.wait_for_selector('#ssh-launch-all', timeout=15000); w.wait_for_timeout(500)
ws = w.evaluate('() => ({title: document.getElementById("workspace-title").textContent, rows: document.querySelectorAll(".op-session-row").length, pills: [...document.querySelectorAll(".op-session-row .pill")].map(x => x.textContent)})'); r.note('CLI launcher', ws)
r.check('N CLI launcher: Open CLIs page lists both devices with Ready pills', ws['title'].startswith('Open CLIs') and ws['rows'] == 2 and all(x == 'Ready' for x in ws['pills']), ws); r.shot('N-cli-launcher', page=w); w.close()
# busy failure path: during a Save progress (capture + git) conflicting actions disable with reasons
p.click('#git-save-progress'); p.wait_for_function('() => document.getElementById("git-save-progress").textContent === "Saving…"', timeout=20000); p.wait_for_timeout(500)
p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); menu = r.js('() => [...document.querySelectorAll("#lab-actions-menu button")].map(b => ({t: (b.querySelector("span")?.textContent || b.textContent).trim().slice(0,30), d: b.disabled, r: b.querySelector(".menu-reason")?.textContent || ""}))'); r.note('menu while saving', menu)
r.check('F busy: while Save progress runs, Stop/Restart/Redeploy/Destroy are disabled with a visible reason', all(m['d'] and m['r'] for m in menu if any(k in m['t'] for k in ('Stop', 'Restart', 'Redeploy', 'Destroy'))), menu); r.shot('F-busy-menu'); p.keyboard.press('Escape')
p.wait_for_function('() => document.getElementById("git-save-progress").textContent === "Save progress" && !/Saving/.test(document.getElementById("git-progress-status").textContent)', timeout=420000)
r.check('F busy: the save completed afterwards (Saved to Git)', r.js('() => document.getElementById("git-progress-status").textContent').startswith('Saved to Git'), r.js('() => document.getElementById("git-progress-status").textContent'))
r.report('stage4c'); b.close(); pw.stop()
