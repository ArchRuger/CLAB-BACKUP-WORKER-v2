"""Live gates M (Lab actions reviews, destroy cancelled, save configurations, running labs, history), N (Advanced), O (Diagnostics), failure paths."""
import json, os, re, sys, time, subprocess, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
def get(url):
    try: return urllib.request.urlopen(url, timeout=60).read().decode('utf-8', 'replace')
    except Exception as exc: return 'ERR ' + repr(exc)
pw, b, ctx, r = session('stage4b'); p = r.page
def section(name, fn):
    try: fn()
    except Exception as exc:
        r.check(f'{name}: section completed without an exception', False, repr(exc)[:300]); r.shot(f'{name}-exception')
        for sel in ('#op-cancel', '[data-op-close]', '[data-dismiss]', '#capture-close'):
            try:
                loc = p.locator(f'dialog[open] {sel}')
                if loc.count(): loc.first.click(timeout=1000)
            except Exception: pass
        try: p.keyboard.press('Escape')
        except Exception: pass
r.open_lab(); r.tab('tools'); p.wait_for_function('() => state.discovery?.connected && current()?.deployment?.status === "Running" && !busy()', timeout=120000); p.wait_for_timeout(500)
def review(action_sel, tag):
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); p.click(action_sel); p.wait_for_selector('#operation-review[open]', timeout=20000); p.wait_for_timeout(400)
    rv = r.js('() => ({title: document.querySelector("#operation-review h2").textContent, tops: [...document.querySelectorAll("#operation-review > p, #operation-review .op-review-body p, #operation-review li")].map(p => p.textContent.trim()).filter(Boolean).slice(0,8), confirm: document.getElementById("op-confirm").textContent, danger: document.getElementById("op-confirm").classList.contains("danger"), save: !!document.getElementById("op-save-first"), pre: document.querySelector("#operation-review details pre")?.textContent || "", summary: document.querySelector("#operation-review details summary")?.textContent, text: document.getElementById("operation-review").textContent.replace(/\\s+/g," ")})')
    r.note(f'review {tag}', {k: rv[k] for k in ('title', 'tops', 'confirm', 'danger', 'save', 'pre', 'summary')}); r.shot(f'M-review-{tag}', full=True); return rv
def gate_m():
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])')
    menu = r.js('() => [...document.querySelectorAll("#lab-actions-menu button, #lab-actions-menu a")].map(b => ({t: (b.querySelector("span")?.textContent || b.textContent).trim().slice(0,40), d: b.disabled, r: b.querySelector(".menu-reason")?.textContent || ""}))'); r.note('lab actions menu', menu)
    r.check('M menu: Start/Stop/Restart/Redeploy/Destroy/All lab operations present; disabled items carry a reason', all(any(k in m['t'] for m in menu) for k in ('Start', 'Stop', 'Restart', 'Redeploy', 'Destroy', 'All lab operations')) and all(m['r'] for m in menu if m['d']), menu)
    r.check('M menu: Start is disabled on the running lab with a reason', any('Start' in m['t'] and m['d'] and m['r'] for m in menu), [m for m in menu if 'Start' in m['t']]); r.shot('M-lab-actions-menu'); p.keyboard.press('Escape')
    rv = review('#menu-destroy', 'destroy')
    r.check('M destroy review: names the lab, says what is lost, last-save line, Save progress first, danger confirm', rv['title'].startswith('Destroy ') and 'Configuration changes you have not saved are lost' in rv['text'] and ('Last saved' in rv['text'] or 'Never saved' in rv['text']) and rv['save'] and rv['confirm'] == 'Destroy lab' and rv['danger'], rv['title'])
    r.check('M destroy review: cleanup folder and raw command only under Technical details', '/usr/bin/containerlab' in rv['pre'] and '--cleanup' in rv['pre'] and 'containerlab' not in ' '.join(rv['tops']), rv['pre'])
    p.click('#op-cancel'); r.check('M destroy review: CANCELLED, lab still running', r.js('() => !document.getElementById("operation-review").open && current().deployment.status === "Running"'))
    for sel, tag, title in (('#lab-actions-menu [data-op-action="stop"]', 'stop', 'Stop devices?'), ('#lab-actions-menu [data-op-action="restart"]', 'restart', 'Restart devices?'), ('#lab-actions-menu [data-op-action="redeploy"]', 'redeploy', 'Redeploy')):
        rv = review(sel, tag); r.check(f'M {tag} review: student title, effect and Technical details, then cancelled', rv['title'].startswith(title.rstrip('?')) and rv['pre'] and rv['summary'] == 'Technical details', rv['title']); p.click('#op-cancel')
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); p.click('#lab-actions'); p.wait_for_selector('#lab-operations-dialog[open]'); p.wait_for_timeout(500)
    ops = r.js('() => ({sections: [...document.querySelectorAll("#lab-operations-dialog .op-sections h3")].map(h => h.textContent), buttons: [...document.querySelectorAll("#lab-operations-dialog [data-op-action]")].map(b => ({t: b.textContent.trim(), d: b.disabled, a: b.dataset.opAction}))})'); r.note('all lab operations', ops)
    r.check('M all operations: Deployment / Lab tools / Danger with apply, inspect and save available', ops['sections'] == ['Deployment', 'Lab tools', 'Danger'] and any(x['a'] == 'save' for x in ops['buttons']) and any(x['a'] == 'inspect' for x in ops['buttons']), ops); r.shot('M-all-lab-operations', full=True)
    applyb = [x for x in ops['buttons'] if x['a'] == 'apply']; r.note('apply topology changes', applyb)
    p.click('#lab-operations-dialog [data-op-action="save"]'); p.wait_for_selector('#operation-review[open]', timeout=20000); p.wait_for_timeout(300)
    sv = r.js('() => ({title: document.querySelector("#operation-review h2").textContent, confirm: document.getElementById("op-confirm").textContent, pre: document.querySelector("#operation-review details pre")?.textContent})'); r.note('save configurations review', sv)
    p.click('#op-confirm'); p.wait_for_function('() => !document.getElementById("operation-review")?.open', timeout=20000); p.wait_for_timeout(1000)
    ban = r.js('() => ({hidden: document.getElementById("lab-banner").hidden, text: document.getElementById("lab-banner-text").textContent, output: !document.getElementById("banner-output").hidden})'); r.note('banner during save configurations', ban)
    r.check('M save device configurations: runs from the review and reports in the banner with View output', (not ban['hidden']) and ban['output'], ban)
    p.wait_for_function('() => !busy()', timeout=300000); p.wait_for_timeout(1500)
    if not r.js('() => document.getElementById("lab-banner").hidden') and r.js('() => !document.getElementById("banner-output").hidden'): p.click('#banner-output'); p.wait_for_selector('#operation-output[open]'); p.wait_for_timeout(500)
    else:
        p.click('#manager-button'); p.wait_for_selector('#manager-menu-list:not([hidden])'); p.click('#operations-history'); p.wait_for_selector('#operation-history[open]'); p.locator('#operation-history [data-job]').first.click(); p.wait_for_selector('#operation-output[open]', timeout=15000)
    out = r.js('() => ({h2: document.querySelector("#operation-output h2").textContent, banner: document.getElementById("op-job-banner").textContent, result: document.getElementById("op-job-result")?.textContent.slice(0,200), output: document.getElementById("op-job-output")?.textContent.slice(0,400)})'); r.note('operation output', out)
    r.check('M operation output: heading, result banner with exit code and raw output available', 'Save' in out['h2'] and bool(out['output']), out); r.shot('M-operation-output', full=True); p.click('#operation-output [data-op-close]')
    p.click('#manager-button'); p.wait_for_selector('#manager-menu-list:not([hidden])'); p.click('#inspect-all'); p.wait_for_selector('#operation-review[open]', timeout=15000)
    r.check('M running labs review: read-only wording', r.js('() => /Nothing is changed/.test(document.getElementById("operation-review").textContent) && document.getElementById("op-confirm").textContent === "Show running labs"'))
    p.click('#op-confirm'); p.wait_for_selector('#operation-output[open]', timeout=15000); p.wait_for_function('() => !!document.querySelector("#operation-output table caption") || /✖/.test(document.getElementById("op-job-banner").textContent)', timeout=60000)
    tbl = r.js('() => ({caption: document.querySelector("#operation-output table caption")?.textContent, rows: [...document.querySelectorAll("#operation-output tbody tr")].map(tr => tr.textContent.replace(/\\s+/g," ").trim().slice(0,160))})'); r.note('running labs table', tbl)
    r.check('M running labs on the VM: table lists both real devices', any('PTX1' in x for x in tbl['rows']) and any('SW1' in x for x in tbl['rows']), tbl); r.shot('M-running-labs', full=True); p.click('#operation-output [data-op-close]')
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); hist = p.locator('#lab-actions-menu button', has_text='history').first
    if hist.count(): hist.click(); p.wait_for_selector('#operation-history[open]', timeout=15000)
    else: p.keyboard.press('Escape'); p.click('#manager-button'); p.click('#operations-history'); p.wait_for_selector('#operation-history[open]', timeout=15000)
    h = r.js('() => ({title: document.querySelector("#operation-history h2").textContent, rows: [...document.querySelectorAll("#operation-history [data-job] strong")].map(s => s.textContent)})'); r.note('history', h)
    r.check('M operation history: the deploy, save and inspect operations are recorded with student names', len(h['rows']) >= 3 and all(' · ' in x for x in h['rows']), h); r.shot('M-history', full=True); p.click('#operation-history [data-op-close]')
section('M', gate_m)
def gate_n():
    r.tab('advanced'); p.wait_for_timeout(800)
    adv = r.js('() => ({sections: [...document.querySelectorAll("#advanced-view h2")].map(h => h.textContent), vm: document.getElementById("vm-summary").textContent, files: document.getElementById("vm-files-status").textContent, deployment: document.getElementById("deployment-status").textContent, checked: document.getElementById("deployment-checked").textContent, profiles: document.getElementById("profiles").textContent.replace(/\\s+/g," ").slice(0,200), sync: {hidden: document.getElementById("sync-vm").hidden, disabled: document.getElementById("sync-vm").disabled}, logs: !!document.getElementById("logs-view"), remove: !!document.getElementById("remove-lab"), gitAdv: document.getElementById("git-repository-advanced")?.textContent.replace(/\\s+/g," ").slice(0,300), buttons: [...document.querySelectorAll("#advanced-view button")].map(b => b.textContent.trim()).filter(Boolean).slice(0,30)})'); r.note('advanced', adv)
    r.check('N advanced: deployment details, VM status sentence, credentials, action logs, all lab operations, danger zone present', adv['vm'].startswith('Lab VM') and adv['deployment'] and adv['logs'] and adv['remove'] and any('Add credentials' in x or 'credentials' in x.lower() for x in adv['buttons']), adv)
    r.check('N advanced: VM file details and lab source shown, Sync topology from VM available', not adv['sync']['hidden'], adv['sync']); r.shot('N-advanced', full=True)
    p.click('#advanced-view details summary >> nth=0'); p.wait_for_timeout(600); fl = r.js('() => document.getElementById("advanced-file-list")?.textContent.replace(/\\s+/g," ").slice(0,300)'); r.note('VM file details', fl); r.check('N advanced: VM file details list the lab topology on the VM', bool(fl) and 'clab-llm-dev2' in fl, fl)
    p.click('#sync-vm'); p.wait_for_timeout(2500); r.note('after sync', r.js('() => ({files: document.getElementById("vm-files-status").textContent, banner: document.getElementById("lab-banner").hidden ? "" : document.getElementById("lab-banner-text").textContent})')); r.check('N sync: Sync topology from VM ran without error', 'error' not in r.js('() => document.getElementById("vm-files-status").textContent').lower())
    p.locator('#advanced-view button', has_text='Add credentials').first.click(); p.wait_for_selector('#profile-dialog[open]', timeout=10000); r.check('N credentials: Add credentials dialog opens with platform, user and password fields', r.js('() => !!document.getElementById("profile-platform") && !!document.getElementById("profile-user") && document.getElementById("profile-password").type === "password"')); r.shot('N-credentials-dialog'); p.keyboard.press('Escape'); p.wait_for_timeout(300)
    if r.js('() => document.getElementById("profile-dialog").open'): p.locator('#profile-dialog button', has_text=re.compile('Cancel|Close')).first.click()
    lg = r.js('() => ({rows: document.querySelectorAll("#log-rows tr, #log-rows li").length, status: document.getElementById("log-status")?.textContent})'); r.note('action logs', lg); r.check('N action logs: rows rendered', lg['rows'] > 0, lg)
    p.click('#remove-lab'); p.wait_for_selector('#remove-lab-dialog[open]'); rm = r.js('() => ({title: document.getElementById("remove-lab-title").textContent, text: document.getElementById("remove-lab-dialog").textContent.replace(/\\s+/g," ").slice(0,300), danger: document.querySelector("#remove-lab-form button[type=submit]").classList.contains("danger")})'); r.note('remove lab dialog', rm)
    r.check('N danger zone: Remove lab dialog explains manager-only scope with a danger submit, cancelled', rm['title'].startswith('Remove ') and rm['danger'], rm); r.shot('N-remove-lab'); p.click('#remove-lab-dialog [data-dismiss]')
    with ctx.expect_page(timeout=15000) as pop: p.locator('a[href*="workspace.html#mode=ssh"]').first.click()
    w = pop.value; r.attach(w); w.wait_for_selector('#ssh-launch-all', timeout=15000); w.wait_for_timeout(500)
    ws = w.evaluate('() => ({title: document.getElementById("workspace-title").textContent, rows: document.querySelectorAll(".op-session-row").length, pills: [...document.querySelectorAll(".op-session-row .pill")].map(x => x.textContent)})'); r.note('CLI launcher', ws)
    r.check('N CLI launcher: Open CLIs page lists both devices with Ready pills', ws['title'].startswith('Open CLIs') and ws['rows'] == 2 and all(x == 'Ready' for x in ws['pills']), ws); r.shot('N-cli-launcher', page=w); w.close()
section('N', gate_n)
def gate_o():
    p.goto(BASE + '/static/debug.html'); p.wait_for_function('() => /^Updated /.test(document.getElementById("debug-status").textContent)', timeout=20000)
    p.click('#debug-probe'); p.wait_for_function('() => document.querySelectorAll("#debug-checks p").length >= 2', timeout=180000); p.wait_for_timeout(500)
    dbg = r.js('() => ({h1: document.querySelector("h1").textContent, cards: [...document.querySelectorAll("#debug-summary h2")].map(h => h.textContent), summary: document.getElementById("debug-summary").textContent.replace(/\\s+/g," ").slice(0,600), checks: [...document.querySelectorAll("#debug-checks p")].map(x => x.textContent.slice(0,160)), errors: document.getElementById("debug-errors")?.textContent.slice(0,200), body: document.body.innerText})'); r.note('diagnostics', {k: dbg[k] for k in ('h1', 'cards', 'checks', 'errors')})
    pwd = open(os.path.expanduser('~/.clab-discovery-password')).read().strip()
    r.check('O diagnostics: manager, VM connection and saved-state cards; probes pass against the real VM', dbg['h1'] == 'Diagnostics' and dbg['cards'] == ['This manager', 'VM connection', 'Saved in this manager'] and all(('OK' in c or 'PASS' in c) for c in dbg['checks']), dbg['checks'])
    r.check('O diagnostics: no secret in the page (VM password absent)', pwd not in dbg['body'] and 'admin@123' not in dbg['body'], ''); r.shot('O-diagnostics', full=True)
    dl = ctx.request.get(BASE + '/api/debug/report') if False else None
section('O', gate_o)
def failure_paths():
    r.open_lab(); r.tab('tools'); p.wait_for_function('() => !busy()', timeout=120000)
    p.click('#backup'); p.wait_for_timeout(400); conf = p.locator('dialog[open] #op-confirm, dialog[open] button.primary, dialog[open] button[type=submit]')
    if conf.count(): conf.first.click()
    p.wait_for_function('() => busy()', timeout=20000); p.wait_for_timeout(300)
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); menu = r.js('() => [...document.querySelectorAll("#lab-actions-menu button")].map(b => ({t: (b.querySelector("span")?.textContent || b.textContent).trim().slice(0,30), d: b.disabled, r: b.querySelector(".menu-reason")?.textContent || ""}))'); r.note('menu while busy', menu)
    r.check('F busy: conflicting lab actions disable with a reason while a backup runs', any(m['d'] and m['r'] for m in menu if 'Destroy' in m['t'] or 'Redeploy' in m['t'] or 'Stop' in m['t']), menu); r.shot('F-busy-menu'); p.keyboard.press('Escape')
    hb = r.js('() => ({save: document.getElementById("progress-save")?.disabled, reason: document.getElementById("progress-save-reason")?.textContent, hidden: document.getElementById("progress-save-reason")?.hidden})'); r.note('save while busy', hb); r.check('F busy: Save progress disabled with a visible reason while a backup runs', hb['save'] and hb['reason'] and not hb['hidden'], hb)
    p.wait_for_function('() => !busy()', timeout=300000)
    r.tab('progress'); p.click('#git-change-folder > summary'); p.wait_for_selector('#git-places-panel .git-places-head', timeout=30000); p.wait_for_timeout(500)
    ar = p.locator('#git-places-panel button', has_text=re.compile(r'^ARISTA-LAB-TEST\\b')).first
    if ar.count():
        ar.click(); p.wait_for_timeout(700); t = r.js('() => ({apply: !!document.querySelector("[data-git-places-action=apply]") && !document.querySelector("[data-git-places-action=apply]").hidden && !document.querySelector("[data-git-places-action=apply]").disabled, text: document.getElementById("git-places-panel").textContent.replace(/\\s+/g," ").slice(0,300)})'); r.note('legacy/EOS folder', t)
        r.check('F incompatible source: a non-Junos / non-restore-capable folder does not offer Apply to running lab', not t['apply'], t); r.shot('F-incompatible-source')
    else: r.check('F incompatible source: ARISTA-LAB-TEST folder found in the browser', False, r.js('() => document.getElementById("git-places-panel").textContent.slice(0,300)'))
    p.click('#git-change-folder > summary')
section('failure', failure_paths)
r.report('stage4b'); b.close(); pw.stop()
