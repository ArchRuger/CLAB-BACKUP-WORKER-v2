import sys, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
RESTORE_END_ = ('succeeded', 'partial', 'needs_attention', 'failed', 'preflight_failed', 'interrupted')
s = Live(); p = s.page; LAB='git-redesign'; DEVS=['a-ceos1','a-ceos2','a-cjunos','a-xrv9k']
t0 = time.time()
s.open_lab(LAB)
s.say('manager readiness of the lab right after the unpause: %s' % s.lab(LAB)['nos_readiness'])
s.close_panels(); s.click('#save-chip', count=False); p.wait_for_timeout(1000)
for attempt in range(1, 9):
    s.reset_counts(); del s.sent[:]
    s.open_chip() if not s.visible('#save-panel') else None
    if not p.locator('#load-retry').count():
        s.say('no Try again visible: panel %r' % s.panel()[:200]); break
    s.click('#load-retry')
    expect(p.locator('#load-run')).to_be_visible(timeout=60000)
    ok = not p.locator('#load-run').is_disabled()
    s.say('attempt %d at +%.0f s after the unpause: confirmation rows %s ; red Load enabled=%s' % (attempt, time.time() - t0, device_words(s), ok))
    if ok: break
    s.click('#load-cancel', count=False); s.close_panels()
    p.wait_for_timeout(15000); s.open_lab(LAB)
s.shot('C4-try-again-confirmation')
before2 = {j['id'] for j in s.state()['restore_jobs']}
s.click('#load-run')
common.wait_until(lambda: any(j['id'] not in before2 and j['status'] in RESTORE_END_ for j in s.state()['restore_jobs']), timeout=240, what='the retry job')
p.wait_for_timeout(2500)
s.say('after Try again: chip %r ; clicks %d' % (s.chip(), s.clicks))
job = last_restore(s, LAB); s.say('job %s %r' % (job['status'], job['message']))
for r in timeline_rows(job): s.say('   target %s' % json.dumps(r))
got = descriptions(DEVS); s.say('CLI read-back: %s' % {k: v.split()[-1] for k, v in got.items()})
s.check('C4 all four devices run Start after Try again', all('l2-c1-start' in v for v in got.values()), got)
s.say('errors %s ; failed %s' % (s.errors, s.failed))
print(report(s, 'C4 finish')); s.finish()
