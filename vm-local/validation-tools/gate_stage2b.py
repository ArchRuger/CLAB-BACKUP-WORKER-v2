"""Stage 2b: retry the checkpoint that needed attention (fixed helper), then H compare, G folder rules, J downloads."""
import json, os, re, sys, time, subprocess, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
CP = 'release-129-live-validation'
def git(*args): return subprocess.run(['git', '-C', os.path.expanduser('~/labs/CLAB-MNGR-DEV-LLM')] + list(args), capture_output=True, text=True).stdout.strip()
pw, b, ctx, r = session('stage2b'); p = r.page
def section(name, fn):
    try: fn()
    except Exception as exc:
        r.check(f'{name}: section completed without an exception', False, repr(exc)[:300]); r.shot(f'{name}-exception')
        for sel in ('#git-new-folder-cancel', '#git-save-cancel', '[data-op-close]'):
            try:
                loc = p.locator(f'dialog[open] {sel}')
                if loc.count(): loc.first.click(timeout=1000)
            except Exception: pass
r.open_lab(); r.tab('progress'); p.wait_for_selector('#git-save-location', timeout=15000); p.wait_for_function('() => document.querySelectorAll("#git-saves-list .git-saved-job").length > 0', timeout=30000); p.wait_for_timeout(800)
def gate_f_retry():
    st = r.js('() => ({status: document.getElementById("git-progress-status").textContent, problem: document.getElementById("git-problem").hidden ? "" : document.getElementById("git-problem").textContent.replace(/\\s+/g," ").slice(0,300), saves: [...document.querySelectorAll("#git-saves-list .git-saved-job > summary")].map(s => s.textContent.replace(/\\s+/g," ").trim())})'); r.note('progress with the failed checkpoint', st)
    r.check('E failure path: a save that needs attention is surfaced on the status card / problem line and in Recent saves', ('attention' in st['status'].lower() or st['problem']) and any('attention' in s.lower() for s in st['saves']), st); r.shot('F-needs-attention', full=True)
    row = p.locator('#git-saves-list .git-saved-job', has_text=re.compile('attention', re.I)).first; row.locator('summary').click(); row.locator('[data-git-job-open]').first.click(); p.wait_for_selector('#git-job-dialog[open]', timeout=15000); p.wait_for_timeout(500)
    jd = r.js('() => ({title: document.querySelector("#git-job-dialog h2").textContent, detail: document.getElementById("git-job-detail").textContent.replace(/\\s+/g," ").slice(0,400), actions: [...document.querySelectorAll("#git-job-actions button")].map(b => b.textContent.trim())})'); r.note('job dialog', jd)
    r.check('E failure path: the save window says Save needs attention with the raw reason under Details and offers Retry save and upload', jd['title'] == 'Save needs attention' and 'outside its manager manifest' in jd['detail'] and 'Retry save and upload' in jd['actions'], jd); r.shot('F-job-needs-attention')
    p.click('#git-job-actions [data-git-job-action="push"]'); p.wait_for_function('() => /Progress saved|Checkpoint|saved/i.test(document.querySelector("#git-job-dialog h2")?.textContent || "") && !/attention|Saving|pending/i.test(document.querySelector("#git-job-dialog h2")?.textContent || "")', timeout=420000); p.wait_for_timeout(1000)
    jd2 = r.js('() => ({title: document.querySelector("#git-job-dialog h2").textContent, detail: document.getElementById("git-job-detail").textContent.replace(/\\s+/g," ").slice(0,400)})'); r.note('job dialog after retry', jd2)
    r.check('F checkpoint: retry with the fixed helper completes the checkpoint and uploads it', 'saved' in jd2['title'].lower() and ('Pushed' in jd2['detail'] or 'uploaded' in jd2['detail'].lower() or 'Git' in jd2['detail']), jd2); r.shot('F-job-after-retry'); p.click('#git-job-dialog [data-op-close]')
    p.wait_for_function('(n) => [...document.querySelectorAll("#git-saved-versions .git-version-row")].some(x => x.textContent.includes(n))', arg=CP, timeout=60000); p.wait_for_timeout(500)
    rows = r.js('() => [...document.querySelectorAll("#git-saved-versions .git-version-row")].map(x => x.textContent.replace(/\\s+/g," ").trim().slice(0,160))'); r.note('saved version rows', rows)
    cp = [x for x in rows if CP in x]; r.check('F checkpoint: listed under Saved versions with its own time', bool(cp) and not any(cp[0].endswith(x.split(' ')[-1]) for x in rows if 'Latest' in x and x != cp[0]) , rows)
    files = git('ls-tree', '-r', '--name-only', 'HEAD', 'clab-llm-dev2/work/checkpoints'); r.note('checkpoint files in git', files)
    r.check('F checkpoint: checkpoints/<name>/ holds manifest, .set and .jcfg files, pushed to GitHub', f'clab-llm-dev2/work/checkpoints/{CP}/manifest.json' in files and '.jcfg' in files and git('rev-list', '--count', 'origin/main..main') == '0', (files, git('log', '-1', '--oneline')))
    remote = subprocess.run(['gh', 'api', 'repos/pruger-dev/CLAB-MNGR-DEV-LLM/commits/main', '--jq', '.sha'], capture_output=True, text=True).stdout.strip(); r.check('F git push: GitHub main equals the local HEAD after the checkpoint', remote == git('rev-parse', 'HEAD'), (remote[:10], git('rev-parse', 'HEAD')[:10]))
    r.shot('F-saved-versions', full=True)
    # a second plain save into latest (the other half of the regression): unchanged configs → no new commit, still Saved to Git
    p.click('#git-save-progress'); p.wait_for_function('() => document.getElementById("git-save-progress").textContent === "Saving…"', timeout=20000); p.wait_for_function('() => document.getElementById("git-save-progress").textContent === "Save progress" && !/Saving/.test(document.getElementById("git-progress-status").textContent)', timeout=420000); p.wait_for_timeout(1000)
    again = r.js('() => ({status: document.getElementById("git-progress-status").textContent, saves: [...document.querySelectorAll("#git-saves-list .git-saved-job > summary")].map(s => s.textContent.replace(/\\s+/g," ").trim()).slice(0,3)})'); r.note('second latest save', again)
    r.check('E regression: a second Save progress into the same Junos folder succeeds (no "files outside its manager manifest")', again['status'].startswith('Saved to Git') and not any('attention' in s.lower() for s in again['saves'][:1]), again)
section('F', gate_f_retry)
def gate_h():
    row = p.locator('#git-saved-versions .git-version-row', has_text=CP).first; row.locator('[data-git-version-action="compare"]').click(); p.wait_for_selector('#git-diff-dialog[open]'); p.wait_for_function('() => document.getElementById("git-diff-dialog").textContent.length > 80', timeout=60000); p.wait_for_timeout(500)
    diff = r.js('() => ({title: document.querySelector("#git-diff-dialog h2").textContent, text: document.getElementById("git-diff-dialog").textContent.replace(/\\s+/g," ").slice(0,500), script: document.getElementById("git-diff-dialog").innerHTML.includes("<script"), marks: document.querySelectorAll("#git-diff-dialog pre, #git-diff-dialog ins, #git-diff-dialog del, #git-diff-dialog .diff-add, #git-diff-dialog .diff-del").length})'); r.note('compare', diff)
    r.check('H compare: Compared with your latest save, never the running configuration', diff['title'] == 'Compared with your latest save' and 'running configuration' not in diff['text'].lower(), diff)
    r.check('H compare: result renders (identical or a diff) and no HTML is interpreted', ('No differences' in diff['text'] or 'identical' in diff['text'].lower() or 'same' in diff['text'].lower() or diff['marks'] > 0) and not diff['script'], diff); r.shot('H-compare', full=True); p.click('#git-diff-dialog [data-op-close]')
    row.locator('[data-git-version-action="view"]').click(); p.wait_for_selector('#git-version-dialog[open]'); p.wait_for_function('() => document.querySelectorAll("#git-version-dialog li, #git-version-dialog pre, #git-version-dialog table tr").length > 0', timeout=60000); p.wait_for_timeout(400)
    v = r.js('() => ({title: document.querySelector("#git-version-dialog h2").textContent, text: document.getElementById("git-version-dialog").textContent.replace(/\\s+/g," ").slice(0,400), apply: !!document.getElementById("git-version-restore") && !document.getElementById("git-version-restore").hidden})'); r.note('checkpoint version dialog', v)
    r.check('H view: the checkpoint opens as a Saved version with its files and Apply available', v['title'] == 'Saved version' and CP in v['text'] and v['apply'], v); r.shot('H-checkpoint-view'); p.click('#git-version-dialog [data-op-close]')
section('H', gate_h)
def gate_g():
    p.click('#git-change-folder > summary'); p.wait_for_selector('#git-places-panel .git-places-head', timeout=30000); p.wait_for_timeout(800)
    def pick(path):
        p.locator(f'#git-places-panel summary[data-git-place="{path}"]').first.click(); p.wait_for_timeout(700)
        return r.js('() => { const u = document.querySelector("[data-git-places-action=use]"), n = document.querySelector("[data-git-places-action=new]"); return {crumbs: [...document.querySelectorAll(".git-crumbs button")].map(b => b.textContent), useDisabled: u?.disabled, useReason: u?.title, newDisabled: n?.disabled, newReason: n?.title, apply: !!document.querySelector("[data-git-places-action=apply]"), caption: [...document.querySelectorAll("#git-places-panel .caption, #git-places-panel .form-help")].map(c => c.textContent.trim()).join(" | ").slice(0,300)}; }')
    a = pick('clab-llm-dev2/work/latest'); r.note('latest folder', a)
    r.check('G places: a latest/ folder cannot be a destination and explains why', a['useDisabled'] and 'latest' in (a['useReason'] or '') , a)
    bgp = pick('bgp-core/work'); r.note('bgp-core/work (another lab folder in the repository)', bgp)
    r.check("G places: another lab's saved folder is protected: Save this lab here disabled with a reason, no New folder inside it", bgp['useDisabled'] and bool(bgp['useReason']) and bgp['newDisabled'], bgp); r.shot('G-other-lab-folder')
    free = pick('Week-01/BGP/Final-State'); r.note('nested free folder', free)
    r.check('G places: the nested folder created earlier is a free lab folder (Save this lab here allowed)', free['useDisabled'] is False and 'free' in (free['useReason'] or '').lower(), free)
    reg = subprocess.run(['sudo', '-n', 'bash', os.path.expanduser('~/projects/clab-manager/deploy/setup-git.sh'), '--list'], capture_output=True, text=True).stdout; prefixes = re.findall(r'"prefix": "([^"]+)"', reg); r.note('registered prefixes', prefixes)
    r.check('G new folder: the nested path was registered on the VM in one step', 'Week-01/BGP/Final-State' in prefixes, prefixes)
    p.locator('.git-crumbs button').first.click(); p.wait_for_timeout(600); p.click('[data-git-places-action=new]'); p.wait_for_selector('#git-new-folder-name', timeout=10000)
    for bad, label in (('../etc', 'path traversal'), ('clab-llm-dev2/work', 'occupied destination'), ('clab-llm-dev2', 'folder containing another lab folder')):
        p.fill('#git-new-folder-name', bad); p.click('#git-new-folder-confirm'); p.wait_for_timeout(1500)
        err = r.js('() => document.querySelector("#git-new-folder-dialog .form-error")?.textContent || ""'); r.note(f'new folder {label}', err)
        r.check(f'G new folder: {label} is rejected with a sentence', bool(err) and r.js('() => document.getElementById("git-new-folder-dialog").open'), err)
    r.shot('G-new-folder-rejected'); p.click('#git-new-folder-cancel'); p.click('#git-change-folder > summary')
section('G', gate_g)
def gate_j():
    r.tab('tools'); p.wait_for_timeout(600); p.wait_for_selector('#jobs details, #jobs li', timeout=15000)
    first = p.locator('#jobs details').first
    if first.count() and not first.evaluate('d => d.open'): first.locator('summary').first.click(); p.wait_for_timeout(400)
    for d in p.locator('#jobs details:not([open])').all()[:3]:
        try: d.locator('summary').first.click(timeout=1000); p.wait_for_timeout(200)
        except Exception: pass
    btns = p.locator('#jobs [data-download]:visible'); n = btns.count(); r.note('visible download buttons', [btns.nth(i).text_content() for i in range(min(n, 8))])
    got = []
    for i in range(min(n, 5)):
        with p.expect_download(timeout=60000) as dl: btns.nth(i).click()
        d = dl.value; path = os.path.join(OUT, 'dl-' + d.suggested_filename); d.save_as(path); head = open(path, 'rb').read(120)
        got.append({'filename': d.suggested_filename, 'bytes': os.path.getsize(path), 'head': 'zip:' + ','.join(zipfile.ZipFile(path).namelist()[:6]) if head[:2] == b'PK' else head.decode('utf-8', 'replace')[:60]})
    r.note('downloaded', got)
    r.check('J downloads: device files and the whole-backup ZIP download with content', n >= 3 and all(g['bytes'] > 50 for g in got) and any(g['head'].startswith('zip:') for g in got), got)
    r.check('J downloads: filenames carry .set / .jcfg / .zip and the device name', any(g['filename'].endswith('.set') for g in got) and any(g['filename'].endswith('.jcfg') for g in got) and any(g['filename'].endswith('.zip') for g in got) and any('PTX1' in g['filename'] for g in got), [g['filename'] for g in got])
    r.check('J downloads: a .set file holds Junos set statements and a .jcfg the hierarchical config', any('set ' in g['head'] for g in got if g['filename'].endswith('.set')) and any('{' in g['head'] or 'Last commit' in g['head'] or 'version' in g['head'] for g in got if g['filename'].endswith('.jcfg')), [g['head'][:40] for g in got])
    hist = r.js('() => [...document.querySelectorAll("#jobs details > summary, #jobs .job-title, #jobs h3")].map(x => x.textContent.replace(/\\s+/g," ").trim().slice(0,120)).slice(0,8)'); r.note('backup history', hist)
    r.check('J history: configuration backups and login checks listed with times and outcomes', any('Configuration backup' in h for h in hist) and any('Login check' in h for h in hist), hist); r.shot('J-backups', full=True)
section('J', gate_j)
r.report('stage2b'); b.close(); pw.stop()
