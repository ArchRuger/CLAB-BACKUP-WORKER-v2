import sys, re, json
RESTORE_END_ = ('succeeded', 'partial', 'needs_attention', 'failed', 'preflight_failed', 'interrupted')
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, STATE, TAG = sys.argv[1], sys.argv[2], sys.argv[3]
DEVS = ['a-ceos1', 'a-ceos2', 'a-cjunos', 'a-xrv9k']; PAUSE = 'clab-git-redesign-ceos2'
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB); s.close_panels(); p.wait_for_timeout(1500)
s.say('C4: devices before: %s' % {k: v.split()[-1] for k, v in descriptions(DEVS).items()})
load_open(s); load_choose(s, STATE)
s.say('confirmation open (the devices were checked first): rows %s' % device_words(s))
s.shot('C4-confirmation-before-pause')
try:
    s.say('docker pause %s -> %s' % (PAUSE, sh('docker', 'pause', PAUSE)))
    before = {j['id'] for j in s.state()['restore_jobs']}
    s.reset_counts(); t0 = time.time()
    s.click('#load-run')
    p.wait_for_timeout(2500)
    s.say('2.5 s after the red Load: chip %r ; load panel error %r ; panel title %r' % (s.chip(), s.text('#load-panel-error') if s.visible('#load-panel-error') else None, s.text('#save-panel-title') if s.visible('#save-panel') else None))
    s.shot('C4-just-after-load')
    s.say('requests: %s' % [c[:140] for c in s.calls('restore')][-3:])
    s.say('failed so far: %s' % s.failed)
    end = time.time() + 240
    last = None
    while time.time() < end:
        job = [j for j in s.state()['restore_jobs'] if j['id'] not in before]
        job = job[0] if job else None
        view = (s.chip(), job and job['status'], tuple((t.get('short_name'), t.get('stage'), t.get('status')) for t in (job or {}).get('targets', [])))
        if view != last:
            last = view; s.say('+%.0fs chip %r job %s %s' % (time.time() - t0, view[0], view[1], view[2]))
        if job and job['status'] in RESTORE_END_: break
        p.wait_for_timeout(1000)
    s.say('job ended: %s %r' % (job['status'], job.get('message')))
    for t in job['targets']: s.say('   target %s' % json.dumps({k: t.get(k) for k in ('short_name', 'status', 'stage', 'message', 'attempts')}))
    p.wait_for_timeout(1500)
    s.say('chip %r ; panel title %r' % (s.chip(), s.text('#save-panel-title') if s.visible('#save-panel') else None))
    if not s.visible('#save-panel'): s.click('#save-chip', count=False)
    p.wait_for_timeout(1000)
    s.say('PANEL: %r ; devices %s' % (s.panel().replace('\n', ' | ')[:500], device_words(s, '#save-panel-body')))
    s.say('buttons: %s' % p.locator('#save-panel-body button').evaluate_all("els=>els.map(e=>e.id+':'+e.textContent.trim())"))
    s.shot('C4-partial-result')
finally:
    s.say('docker unpause %s -> %s' % (PAUSE, sh('docker', 'unpause', PAUSE)))
    s.say('paused containers now: %r' % sh('docker', 'ps', '--filter', 'status=paused', '--format', '{{.Names}}')[1])
# the others now run the state; ceos2 does not
p.wait_for_timeout(4000)
s.say('CLI: %s' % {k: v.split()[-1] for k, v in descriptions(['a-ceos1', 'a-cjunos', 'a-xrv9k']).items()})
retry = p.locator('#load-retry')
for i in range(30):
    if retry.count() and retry.is_visible(): break
    p.wait_for_timeout(1000)
s.say('Try again button: %r' % (retry.inner_text() if retry.count() else None))
s.reset_counts(); before2 = {j['id'] for j in s.state()['restore_jobs']}
if not retry.count() or not retry.is_visible():
    s.close_panels(); s.click('#save-chip', count=False)
s.click('#load-retry')
expect(p.locator('#load-run')).to_be_visible(timeout=60000)
s.say('retry confirmation: %r ; rows %s ; text %r' % (s.text('#load-panel-body .save-state'), device_words(s), s.text('#load-panel-body')[:300].replace('\n', ' | ')))
s.shot('C4-try-again-confirmation')
s.click('#load-run')
common.wait_until(lambda: any(j['id'] not in before2 and j['status'] in RESTORE_END_ for j in s.state()['restore_jobs']), timeout=240, what='the retry job')
p.wait_for_timeout(2000)
s.say('after Try again: chip %r ; clicks %d' % (s.chip(), s.clicks))
got = descriptions(DEVS); s.say('CLI read-back: %s' % got)
s.check('C4 all four devices run %s after Try again' % STATE, all(TAG in v for v in got.values()), got)
s.say('errors %s ; failed %s' % (s.errors, s.failed))
s.no_errors('C4'); print(report(s, 'C4')); s.finish()
