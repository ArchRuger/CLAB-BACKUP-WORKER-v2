import sys, re, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, STATE, TAG = sys.argv[1], sys.argv[2], sys.argv[3]
DEVS = ['a-ceos1', 'a-ceos2', 'a-cjunos', 'a-xrv9k']
s = Live(); p = s.page
import os
if not os.environ.get('SKIP_IMPORT'):
    s.open_lab(LAB); s.wait_quiet(LAB)
    for d in DEVS: set_description(d, 'l2-c6-before')
    s.say('C6: devices set to l2-c6-before: %s' % {k: v.split()[-1] for k, v in descriptions(DEVS).items()})
    old = lab_id(LAB)
    s.say('DELETE /api/labs/%s (manager only) -> %s' % (old[:8], mgr.call('DELETE', '/api/labs/' + old, {'name': LAB, 'prevent_reimport': False})[0]))
    mgr.call('POST', '/api/discovery/refresh', {})
    st, prev = mgr.call('POST', '/api/discovery/import-preview', {'name': LAB})
    st2, imp = mgr.call('POST', '/api/discovery/import', {'name': LAB, 'token': prev['token']})
    s.say('import-preview %s import %s -> new lab %s (old %s)' % (st, st2, imp.get('id', '')[:8], old[:8]))
    p.wait_for_timeout(3000)
s.open_lab(LAB)
for i in range(60):
    r = s.lab(LAB)['nos_readiness']
    if r['ready'] == 4: break
    p.wait_for_timeout(3000)
s.say('new lab record: readiness %s ; chip %r ; binding %s' % (s.lab(LAB)['nos_readiness'], s.chip(), s.git(LAB).get('binding')))
# Load before any save location
s.reset_counts(); load_open(s)
text = s.text('#load-panel-body'); s.say('Load panel (no save location): %r' % text[:500].replace('\n', ' | '))
s.shot('C6-load-without-location')
names = [x.split('\n')[0] for x in p.locator('#load-panel-body .save-list > li .save-item > span:first-child').all_inner_texts()]
s.say('lists: %s' % names)
s.check('C6 Load lists the lab states of the default repository', 'This lab has no saves of its own yet' in text and len(names) >= 4, (names, text[:200]))
s.check('C6 the state asked for is on the first screen of the Load panel', STATE in names, 'not among the %d rows shown: %s; the panel says %r' % (len(names), names, re.findall(r'\d+ more in All versions', text)))
if STATE in names:
    load_choose(s, STATE)
else:
    s.click('#load-all'); expect(p.locator('#save-drawer')).to_be_visible(timeout=15000)
    expect(p.locator('#save-drawer-content .save-list > li > button.save-item').first).to_be_visible(timeout=20000)
    s.click(p.locator('#save-drawer-content .save-list > li > button.save-item').filter(has_text=re.compile('^' + STATE)).first)
    s.click(p.locator('#save-drawer [data-save-action="load"]').first)
    expect(p.locator('#load-run')).to_be_visible(timeout=40000)
s.say('confirmation: %r ; rows %s' % (s.text('#load-panel-body .save-state'), device_words(s)))
s.say('preflight request source: %s' % s.calls('/restore/preflight')[-1][:260])
s.click('#load-run'); s.wait_chip(r'^(Running .*|Loaded \d of \d)$', timeout=180000)
s.say('loaded: chip %r ; clicks %d (Load, state, red Load)' % (s.chip(), s.clicks))
got = descriptions(DEVS); s.say('CLI read-back: %s' % {k: v.split()[-1] for k, v in got.items()})
s.check('C6 every device runs %s' % STATE, all(TAG in v for v in got.values()), got)
job = last_restore(s, LAB)
for r in timeline_rows(job): s.say('   target %s' % json.dumps(r))
s.close_panels(); p.wait_for_timeout(1200)
# first save: the same-name question
s.reset_counts(); s.click('#git-save-progress'); p.wait_for_timeout(3500)
s.say('first-save panel: %r' % s.panel().replace('\n', ' | ')[:420])
s.say('buttons: %s' % p.locator('#save-panel-body button').evaluate_all("els=>els.map(e=>e.id+':'+e.textContent.trim())"))
s.shot('C6-first-save-question')
s.check('C6 the first save asks the same-name question and offers Continue there', s.visible('#save-first-continue'))
s.click('#save-first-continue')
s.wait_chip(r'^(1 save to upload|Saved .*)$', timeout=120000); p.wait_for_timeout(1500)
s.say('after Continue there: chip %r ; sentence %r ; clicks %d' % (s.chip(), s.text('#save-changes') if s.visible('#save-changes') else s.panel()[:200], s.clicks))
if s.chip().startswith('1 save'):
    expect(p.locator('#save-upload')).to_be_enabled(timeout=30000); s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$', timeout=90000); s.wait_chip('^Saved ')
s.say('lab saves in %s ; chip %r ; clicks (Save, Continue there, [Upload]) = %d' % (s.prefix(LAB), s.chip(), s.clicks))
j = s.jobs(LAB)[-1]; s.say('job %s' % trim(j, ('status', 'note', 'summary', 'destination', 'pushed'), 500))
s.check('C6 the save continues in the old folder git-redesign', s.prefix(LAB) == 'git-redesign', s.prefix(LAB))
github('after C6')
s.say('errors %s ; failed %s' % (s.errors, s.failed))
s.no_errors('C6'); print(report(s, 'C6')); s.finish()
