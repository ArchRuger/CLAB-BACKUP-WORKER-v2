import json, os, re, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
def git(*a): return subprocess.run(['git', '-C', os.path.expanduser('~/labs/CLAB-MNGR-DEV-LLM')] + list(a), capture_output=True, text=True).stdout.strip()
pw, b, ctx, r = session('move'); p = r.page
r.open_lab(); r.tab('progress'); p.wait_for_selector('#git-save-location', timeout=15000); p.wait_for_timeout(500)
r.note('destination before', r.js('() => document.getElementById("git-destination").textContent'))
p.click('#git-change-folder > summary'); p.wait_for_selector('#git-places-panel .git-places-head', timeout=30000); p.wait_for_timeout(800)
p.locator('#git-places-panel summary[data-git-place="clab-llm-dev2"]').first.click(); p.wait_for_timeout(600)
st = r.js('() => ({crumbs: [...document.querySelectorAll(".git-crumbs button")].map(b => b.textContent), use: document.querySelector("[data-git-places-action=use]")?.title, tag: [...document.querySelectorAll("#git-places-panel .git-outline summary")].filter(s => /This lab/.test(s.textContent)).map(s => s.dataset.gitPlace)})'); r.note('this lab folder', st)
r.check('G move: the lab now saves at clab-llm-dev2 after the earlier move (This lab tag, already saves here)', 'clab-llm-dev2' in st['tag'] and 'already saves here' in (st['use'] or ''), st)
p.click('[data-git-places-action=new]'); p.wait_for_selector('#git-new-folder-name', timeout=10000); p.fill('#git-new-folder-name', 'work'); p.wait_for_timeout(300)
dlg = r.js('() => ({path: document.querySelector("#git-new-folder-dialog .op-path")?.textContent, result: document.getElementById("git-new-folder-result").textContent.replace(/\\s+/g," "), use: document.getElementById("git-new-folder-use")?.checked, useLabel: document.getElementById("git-new-folder-use")?.closest("label")?.textContent.trim(), move: document.getElementById("git-new-folder-move")?.checked, moveLabel: document.getElementById("git-new-folder-move")?.closest("label")?.textContent.trim()})'); r.note('new folder dialog', dlg)
r.check('G move: New folder shows the destination preview, Save this lab here and the move-files option with their consequences', 'work' in dlg['result'] and dlg['use'] is not None and dlg['moveLabel'], dlg); r.shot('G-new-folder-move-dialog')
if not dlg['use']: p.check('#git-new-folder-use')
if p.locator('#git-new-folder-move').count() and not r.js('() => document.getElementById("git-new-folder-move").checked'): p.check('#git-new-folder-move')
p.click('#git-new-folder-confirm'); p.wait_for_timeout(1500)
conf = p.locator('dialog[open]').last
if conf.count() and not r.js('() => !!document.getElementById("git-new-folder-dialog")?.open'):
    r.note('move confirmation', r.js('() => [...document.querySelectorAll("dialog[open]")].map(d => d.textContent.replace(/\\s+/g," ").slice(0,500))'))
    btn = conf.locator('button.primary, button.danger, #op-confirm').first
    if btn.count(): btn.click()
p.wait_for_function('() => /clab-llm-dev2\\/work/.test(document.getElementById("git-destination").textContent)', timeout=300000); p.wait_for_timeout(1000)
p.wait_for_function('() => !/Moving|Saving/.test(document.getElementById("git-progress-status").textContent)', timeout=300000); p.wait_for_timeout(1500)
after = r.js('() => ({destination: document.getElementById("git-destination").textContent, status: document.getElementById("git-progress-status").textContent, saves: [...document.querySelectorAll("#git-saves-list .git-saved-job > summary")].map(s => s.textContent.replace(/\\s+/g," ").trim()).slice(0,3)})'); r.note('after move back', after)
r.check('G move: the lab saves to clab-llm-dev2/work again and the move is a Folder move row', 'clab-llm-dev2/work' in after['destination'] and any('move' in s.lower() for s in after['saves']), after); r.shot('G-after-move-back', full=True)
git('fetch', '-q', 'origin'); tree = git('ls-tree', '-r', '--name-only', 'HEAD', 'clab-llm-dev2'); r.note('tree after move back', tree)
r.check('G move: latest and the checkpoint moved with the lab in one commit, pushed', 'clab-llm-dev2/work/latest/manifest.json' in tree and 'clab-llm-dev2/work/checkpoints/release-129-live-validation/manifest.json' in tree and 'clab-llm-dev2/latest/' not in tree and git('rev-list', '--count', 'origin/main..main') == '0', (git('log', '-1', '--oneline'), tree[:200]))
r.report('move'); b.close(); pw.stop()
