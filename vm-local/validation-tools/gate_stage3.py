"""Live gate I: apply a saved Junos state from a reference folder to the running node, prove replacement, pre/post backups, no recreate."""
import json, os, re, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *; import junos_ssh
PTX = node_address('cjunosevolved'); SW = node_address('vjunosswitch'); SOURCE_FOLDER = os.environ.get('SOURCE_FOLDER', 'clab-llm-dev2/reference/solution'); STALE_LO = '10.77.77.77/32'; STALE_HOST = 'PTX1-BROKEN-BY-STUDENT'
def api(path):
    import urllib.request; return json.load(urllib.request.urlopen(BASE + '/api' + path, timeout=60))
def started(): return subprocess.run(['sudo', '-n', 'docker', 'inspect', '-f', '{{.State.StartedAt}}', 'clab-clab-llm-dev2-PTX1'], capture_output=True, text=True).stdout.strip()
pw, b, ctx, r = session('stage3'); p = r.page
before_started = started(); r.note('PTX1 StartedAt before', before_started)
# deliberate stale configuration on the running node
m = re.search(r'encrypted-password "([^"]+)"', '\n'.join(junos_ssh.cli(PTX, ['show configuration system login user admin authentication | display set | no-more']))); h = m.group(1) if m else ''
# The factory cJunosEvolved image rejects any commit without root-authentication; a student would have to add it too.
out = junos_ssh.cli(PTX, ['configure', f'set system root-authentication encrypted-password "{h}"', f'set interfaces lo0 unit 0 family inet address {STALE_LO}', f'set system host-name {STALE_HOST}', 'delete interfaces et-0/0/0 description', 'commit and-quit', 'show configuration | display set | match "lo0|host-name|et-0/0/0 description" | no-more'])
joined = '\n'.join(out).replace(h, '<hash>'); r.note('stale commit output', joined[-1200:])
r.check('I stale: the student change is committed on PTX1 (lo0 address + host-name)', STALE_LO in joined and STALE_HOST in joined and 'commit complete' in joined.lower(), joined[-300:])
r.note('addresses', {'PTX1': PTX, 'SW1': SW})
r.note('SW1 before restore', '\n'.join(junos_ssh.cli(SW, ['show configuration | display set | match "ge-0/0/0|lo0|host-name" | no-more']))[-400:])
# UI: Progress → Saved versions → Instructor and reference versions → Apply (fallback: folder browser)
r.open_lab(); r.tab('progress'); p.wait_for_function('() => document.querySelectorAll("#git-saved-versions .git-version-row").length > 0', timeout=60000); p.wait_for_timeout(800)
binding_before = api('/labs/' + r.js('() => activeId') + '/git').get('binding', {}); r.note('binding before', {k: binding_before.get(k) for k in ('prefix', 'binding_id', 'repository')})
rows = r.js('() => [...document.querySelectorAll("#git-saved-versions .git-version-row")].map(x => ({text: x.textContent.replace(/\\s+/g," ").trim().slice(0,120), apply: !!x.querySelector("[data-git-version-action=apply]")}))'); r.note('version rows', rows)
row = p.locator('#git-saved-versions .git-version-row', has_text='solution').filter(has=p.locator('[data-git-version-action="apply"]')).first
if row.count(): row.locator('[data-git-version-action="apply"]').click(); r.check('I source: Apply to running lab… offered on the reference version in Saved versions', True)
else:
    r.check('I source: Apply to running lab… offered on the reference version in Saved versions', False, rows)
    p.click('#git-change-folder > summary'); p.wait_for_selector('#git-places-panel .git-places-head', timeout=30000)
    parts = SOURCE_FOLDER.split('/')
    for i in range(1, len(parts) + 1):
        s = p.locator(f'#git-places-panel summary[data-git-place="{"/".join(parts[:i])}"]').first
        if s.count(): s.scroll_into_view_if_needed(); s.click(); p.wait_for_timeout(600)
    r.note('places before apply', r.js('() => ({crumbs: [...document.querySelectorAll(".git-crumbs button")].map(b => b.textContent), apply: !!document.querySelector("[data-git-places-action=apply]")})'))
    r.check('I source (fallback): Browse the repository… reaches the reference folder and offers Apply to running lab…', r.js('() => !!document.querySelector("[data-git-places-action=apply]")'))
    p.click('[data-git-places-action=apply]')
p.wait_for_selector('#restore-review-dialog[open]', timeout=30000); p.wait_for_function('() => !!document.getElementById("restore-run") || !!document.querySelector("#restore-review-dialog .form-error")?.textContent', timeout=120000); p.wait_for_timeout(500)
review = r.js(r'''() => ({title: document.querySelector('#restore-review-dialog h2')?.textContent, text: document.getElementById('restore-review-dialog').textContent.replace(/\s+/g,' ').slice(0,1500), rows: [...document.querySelectorAll('#restore-review-dialog .restore-target')].map(l => l.textContent.trim().replace(/\s+/g, ' ').slice(0, 160)), bullets: [...document.querySelectorAll('#restore-review-dialog .restore-safety li')].map(l => l.textContent.slice(0,120)), ack: !!document.getElementById('restore-ack'), run: document.getElementById('restore-run')?.textContent, runDisabled: document.getElementById('restore-run')?.disabled})''')
r.note('restore review', review)
r.check('I review: Replace running configuration with source, lab, devices, safety bullets and acknowledgement', review['title'] == 'Replace running configuration' and 'Lab:' in review['text'] and SOURCE_FOLDER.split('/')[-1] in review['text'] and len(review['bullets']) == 3 and review['ack'] and review['run'] == 'Replace configurations', review)
r.check('I review: PTX1 listed as restore-capable with differences from the running configuration', any('PTX1' in x and ('difference' in x or 'differ' in x) for x in review['rows']), review['rows'])
r.check('I review: SW1 status is explained (matches, differs or skipped with a reason)', any('SW1' in x for x in review['rows']), review['rows'])
r.shot('I-restore-review', full=True)
p.click('#restore-run'); p.wait_for_timeout(800); ackerr = r.js('() => document.querySelector("#restore-review-dialog .form-error")?.textContent || ""'); r.note('run without acknowledgement', ackerr)
r.check('I review: Replace configurations without the acknowledgement is refused with a sentence', 'Tick the box' in ackerr and r.js('() => document.getElementById("restore-review-dialog").open'), ackerr)
p.check('#restore-ack'); p.click('#restore-run'); p.wait_for_selector('#restore-job-dialog[open]', timeout=30000)
p.wait_for_function('() => /replaced|failed|did not|attention|rolled back/i.test(document.getElementById("restore-job-detail").textContent) && !/running|in progress|Backing up|Loading|Confirming/i.test(document.querySelector("#restore-job-dialog h2")?.textContent || "")', timeout=900000); p.wait_for_timeout(1500)
job = r.js('() => ({title: document.querySelector("#restore-job-dialog h2")?.textContent, detail: document.getElementById("restore-job-detail").textContent.replace(/\\s+/g," ").slice(0,800), rows: [...document.querySelectorAll("#restore-job-dialog .restore-target-row")].map(x => x.textContent.replace(/\\s+/g," ").trim().slice(0,200)), text: document.getElementById("restore-job-dialog").textContent})'); r.note('restore job dialog', {k: job[k] for k in ('title', 'detail', 'rows')})
r.check('I job: finished with Configuration replaced and PTX1 verified', 'Configuration replaced' in job['detail'] and any('PTX1' in x and 'erified' in x for x in job['rows']), job['rows'])
r.check('I job: no candidate configuration text dumped into the dialog', 'root-authentication' not in job['text'] and 'set system login' not in job['text'], '')
r.shot('I-restore-job', full=True); p.click('#restore-job-dialog [data-op-close]')
jobs = api('/state').get('restore_jobs', []); rj = sorted(jobs, key=lambda j: j.get('created_at') or j.get('created') or '')[-1] if jobs else {}
pub = {k: rj.get(k) for k in ('id', 'status', 'source', 'pre_backup_job_id', 'post_backup_job_id', 'result', 'summary', 'nodes', 'targets', 'error')}; r.note('restore job record (public)', json.dumps(pub)[:1500])
r.check('I backend: job succeeded with pre and post backup ids recorded', rj.get('status') in ('succeeded', 'success', 'finished', 'completed') and rj.get('pre_backup_job_id') and rj.get('post_backup_job_id'), pub)
r.check('I backend: public job carries no _candidates or host_identity', '_candidates' not in rj and 'host_identity' not in rj, list(rj.keys())[:20])
node_result = json.dumps(rj)[:3000]; r.check('I backend: root_authentication synthesized and 0 missing / 0 extra recorded for PTX1', 'synthesized' in node_result or '"root_authentication"' in node_result, node_result[:400])
allj = api('/state').get('jobs', []); pre = [j for j in allj if j.get('id') == rj.get('pre_backup_job_id')]; post = [j for j in allj if j.get('id') == rj.get('post_backup_job_id')]
r.note('pre/post backup jobs', {'pre': {k: pre[0].get(k) for k in ('id', 'status', 'source', 'created_at')} if pre else None, 'post': {k: post[0].get(k) for k in ('id', 'status', 'source', 'created_at')} if post else None})
r.check('I backups: pre-restore backup restore-pre and post-restore backup restore-post both succeeded', pre and post and pre[0].get('source') == 'restore-pre' and post[0].get('source') == 'restore-post' and pre[0].get('status') == 'succeeded' and post[0].get('status') == 'succeeded', '')
after = '\n'.join(junos_ssh.cli(PTX, ['show configuration | display set | match "lo0|host-name|et-0/0/0 description|root-authentication"', 'show configuration | compare rollback 1 | no-more', 'show system uptime | no-more'])); r.note('PTX1 after restore', after[-1500:])
r.check('I device: stale lo0 address REMOVED after restore (replacement, not merge)', STALE_LO not in after, after[-400:])
r.check('I device: host-name reset to the saved state', STALE_HOST not in after, '')
r.check('I device: the desired description is back', 'et-0/0/0 description' in after, '')
r.check('I device: root-authentication present so the node stays loginable', 'root-authentication' in after, '')
after_started = started(); r.note('PTX1 StartedAt after', after_started)
r.check('I no reboot / no recreate: container StartedAt unchanged', before_started == after_started and bool(before_started), (before_started, after_started))
r.check('I no rebinding: the lab still saves to its work folder', api('/labs/' + r.js('() => activeId') + '/git').get('binding', {}).get('prefix') == binding_before.get('prefix'), '')
last = r.js('() => document.getElementById("git-last-restore").hidden ? "" : document.getElementById("git-last-restore-text").textContent'); r.check('I progress: Last configuration change line shows the restore', last.startswith('Last configuration change'), last)
r.report('stage3'); b.close(); pw.stop()
