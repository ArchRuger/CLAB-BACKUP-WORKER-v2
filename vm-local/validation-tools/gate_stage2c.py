import json, os, re, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
pw, b, ctx, r = session('stage2c'); p = r.page
r.open_lab(); r.tab('progress'); p.wait_for_selector('#git-save-location', timeout=15000); p.click('#git-change-folder > summary'); p.wait_for_selector('#git-places-panel .git-places-head', timeout=30000); p.wait_for_timeout(800)
def pick(path):
    parts = path.split('/')
    for i in range(1, len(parts) + 1):
        sub = '/'.join(parts[:i]); s = p.locator(f'#git-places-panel summary[data-git-place="{sub}"]').first
        if s.count():
            s.scroll_into_view_if_needed(); s.click(); p.wait_for_timeout(500)
    return r.js('() => { const u = document.querySelector("[data-git-places-action=use]"), n = document.querySelector("[data-git-places-action=new]"); return {crumbs: [...document.querySelectorAll(".git-crumbs button")].map(b => b.textContent), useDisabled: u?.disabled, useReason: u?.title, newDisabled: n?.disabled, newReason: n?.title, apply: !!document.querySelector("[data-git-places-action=apply]"), rows: [...document.querySelectorAll("#git-places-panel tbody tr")].map(t => t.textContent.replace(/\\s+/g," ").trim().slice(0,80)).slice(0,5)}; }')
bgp = pick('bgp-core/work'); r.note('bgp-core/work', bgp)
r.check("G places: another lab's saved folder (bgp-core/work) is protected: Save this lab here disabled with a reason and New folder disabled inside it", bgp['crumbs'][-1] == 'work' and bgp['useDisabled'] and bool(bgp['useReason']) and bgp['newDisabled'], bgp); r.shot('G-other-lab-folder', full=True)
sol = pick('bgp-core/reference/solution'); r.note('bgp-core/reference/solution', sol)
r.check('G places: a reference folder with a Junos saved state offers Apply to running lab… straight from the browser', sol['apply'], sol)
ar = pick('ARISTA-LAB-TEST'); r.note('ARISTA-LAB-TEST', ar)
r.check('failure path: a non-Junos (EOS) saved folder does not offer Apply to running lab', not ar['apply'], ar); r.shot('F-incompatible-source')
free = pick('Week-01/BGP/Final-State'); r.note('Week-01/BGP/Final-State', free)
r.check('G places: the nested folder created in one step is a free lab folder (Save this lab here allowed)', free['useDisabled'] is False and 'free' in (free['useReason'] or '').lower(), free)
p.locator('.git-crumbs button').first.click(); p.wait_for_timeout(500); p.click('[data-git-places-action=new]'); p.wait_for_selector('#git-new-folder-name', timeout=10000)
for bad, label in (('../etc', 'path traversal'), ('clab-llm-dev2/work', 'occupied destination'), ('clab-llm-dev2', 'a folder that would contain another lab folder')):
    p.fill('#git-new-folder-name', bad); p.click('#git-new-folder-confirm'); p.wait_for_timeout(2000)
    err = r.js('() => document.querySelector("#git-new-folder-dialog .form-error")?.textContent || ""'); r.note(f'new folder {label}', err)
    r.check(f'G new folder: {label} is rejected with a sentence and the dialog stays open', bool(err) and r.js('() => document.getElementById("git-new-folder-dialog").open'), err)
r.shot('G-new-folder-rejected'); p.click('#git-new-folder-cancel'); p.click('#git-change-folder > summary')
r.tab('tools'); p.wait_for_timeout(500)
groups = r.js('() => [...document.querySelectorAll("#jobs > details > summary, #jobs > h3, #jobs > details > h3, #jobs summary")].map(x => x.textContent.replace(/\\s+/g," ").trim().slice(0,80)).slice(0,12)'); r.note('backup history groups', groups)
r.check('J history: configuration backups (manual and restore captures) and the Login checks group are listed', any('Configuration backup' in g for g in groups) and any('Login check' in g for g in groups), groups)
r.report('stage2c'); b.close(); pw.stop()
