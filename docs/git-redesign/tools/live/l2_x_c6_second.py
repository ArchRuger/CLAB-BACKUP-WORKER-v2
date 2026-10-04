import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign'
old = lab_id(LAB)
s.say('second removal/import: DELETE %s -> %s' % (old[:8], mgr.call('DELETE', '/api/labs/' + old, {'name': LAB, 'prevent_reimport': False})[0]))
mgr.call('POST', '/api/discovery/refresh', {})
st, prev = mgr.call('POST', '/api/discovery/import-preview', {'name': LAB}); st2, imp = mgr.call('POST', '/api/discovery/import', {'name': LAB, 'token': prev['token']})
s.say('import %s -> %s' % (st2, imp.get('id', '')[:8])); p.wait_for_timeout(3000)
s.open_lab(LAB)
for i in range(60):
    if s.lab(LAB)['nos_readiness']['ready'] == 4: break
    p.wait_for_timeout(3000)
s.say('readiness %s ; chip %r' % (s.lab(LAB)['nos_readiness'], s.chip()))
s.reset_counts(); s.click('#git-save-progress'); p.wait_for_timeout(3500)
s.say('FIRST SAVE panel (no load before it): %r' % s.panel().replace('\n', ' | ')[:420])
s.say('buttons: %s' % p.locator('#save-panel-body button').evaluate_all("els=>els.map(e=>e.id+':'+e.textContent.trim())"))
s.shot('C6-first-save-question')
s.check('C6 the first save asks the same-name question and offers Continue there', s.visible('#save-first-continue'))
s.click('#save-first-continue')
s.wait_chip(r'^(1 save to upload|Saved .*)$', timeout=120000); p.wait_for_timeout(1500)
s.say('after Continue there: chip %r ; sentence %r ; clicks %d' % (s.chip(), s.text('#save-changes') if s.visible('#save-changes') else s.panel()[:200], s.clicks))
if s.chip().endswith('to upload'):
    expect(p.locator('#save-upload')).to_be_enabled(timeout=30000); s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$', timeout=90000); s.wait_chip('^Saved ')
s.say('lab saves in %s ; chip %r ; clicks (Save, Continue there, Upload) = %d' % (s.prefix(LAB), s.chip(), s.clicks))
j = [x for x in s.jobs(LAB) if x.get('kind') != 'state'][-1]; s.say('job %s' % trim(j, ('status', 'note', 'summary', 'destination', 'pushed'), 500))
s.check('C6 the save continues in the old folder git-redesign', s.prefix(LAB) == 'git-redesign', s.prefix(LAB))
github('after C6')
s.say('errors %s ; failed %s' % (s.errors, s.failed))
s.no_errors('C6'); print(report(s, 'C6')); s.finish()
