import sys, re, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB = sys.argv[1]; DEVS = sys.argv[2].split(','); LOAD = sys.argv[3]; BEFORE = sys.argv[4]; AFTER = sys.argv[5]
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB); s.close_panels(); p.wait_for_timeout(1500)
s.say('C3: devices before: %s' % {k: v.split()[-1] for k, v in descriptions(DEVS).items()})
load_open(s); load_choose(s, LOAD); s.click('#load-run')
s.wait_chip(r'^Running ' + LOAD + '$', timeout=180000)
t_end = time.time()
s.say('load of %s ended: chip %r' % (LOAD, s.chip()))
s.reset_counts()
if not s.visible('#save-panel'): s.click('#save-chip')
expect(p.locator('#load-undo')).to_be_visible(timeout=10000)
s.click('#load-undo')
t_click = time.time() - t_end
s.say('Undo this load pressed %.1f s after the chip read Running' % t_click)
live_seen = []
seen = []
shots = {0.4: 'C3-undo-after-click-a', 1.5: 'C3-undo-after-click-b'}
end = time.time() + 40
while time.time() < end:
    el = time.time() - t_end - t_click
    for at in list(shots):
        if el >= at: s.shot(shots.pop(at))
    panel = s.panel() if s.visible('#save-panel') else ''
    err = s.text('#save-panel-error') if s.visible('#save-panel-error') else ''
    run = s.visible('#load-run')
    key = (panel.replace('\n', ' | ')[:140], err, run, p.locator('#load-run').is_disabled() if run else None)
    if not seen or seen[-1][1] != key: seen.append((round(time.time() - t_end, 1), key))
    s_text = p.evaluate("(()=>{const l=document.querySelector('[aria-live]');return l?l.textContent:''})()")
    if s_text and (not seen or seen[-1][1][1:] != key[1:] or True) and not any(x == s_text for _, x in [(0, k_) for k_ in live_seen]): live_seen.append(s_text); s.say('   live region: %r' % s_text[:160])
    if run and not p.locator('#load-run').is_disabled(): break
    p.wait_for_timeout(250)
for t, k in seen: s.say('   +%.1fs panel=%r error=%r red Load visible=%s disabled=%s' % (t, k[0], k[1], k[2], k[3]))
s.say('requests: %s' % [c[:120] for c in s.calls('restore')])
s.say('failed requests so far: %s' % s.failed)
s.shot('C3-undo-confirmation')
s.say('confirmation: %r ; rows %s' % (s.text('#load-panel-body .save-state') if s.visible('#load-panel-body .save-state') else s.panel()[:120], device_words(s) if s.visible('#load-run') else None))
before_ids = {j['id'] for j in s.state()['restore_jobs']}
s.click('#load-run'); t_run = time.time()
common.wait_until(lambda: any(j['id'] not in before_ids for j in s.state()['restore_jobs']), timeout=60, what='the undo job to exist')
s.say('undo job created %.1f s after the red Load click' % (time.time() - t_run))
s.wait_chip(r'^(Loading…|Checking).*', timeout=60000)
s.say('chip while the undo runs: %r ; panel %r' % (s.chip(), s.text('#save-panel-title') if s.visible('#save-panel') else None))
s.wait_chip(r'^(Running .*|Loaded \d of \d)$', timeout=180000)
s.say('after Undo: chip %r ; clicks (chip, Undo, Load) = %d' % (s.chip(), s.clicks))
got = descriptions(DEVS); s.say('CLI read-back: %s' % got)
s.check('C3 every device is back to what it ran before the load (%s)' % BEFORE, all(BEFORE in v for v in got.values()), got)
job = last_restore(s, LAB); s.check('C3 the job just ended is the undo (source backup)', (job.get('source') or {}).get('type') == 'backup', job.get('source')); s.say('undo job: %s %r' % (job['status'], job.get('message')))
for r in timeline_rows(job): s.say('   target %s' % json.dumps(r))
s.shot('C3-after-undo')
s.say('errors %s ; failed %s' % (s.errors, s.failed))
s.no_errors('C3'); print(report(s, 'C3')); s.finish()
