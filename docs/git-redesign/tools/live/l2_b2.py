import sys, re
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, DEV, MODE = sys.argv[1], sys.argv[2], sys.argv[3]    # MODE: continue | beside (the second chooses Save in <name>-2)
s = Live(); p = s.page
def reimport(name):
    cur = lab_ids().get(name)
    if cur:
        s.say('DELETE /api/labs/%s (manager only) -> %s' % (cur[:8], mgr.call('DELETE', '/api/labs/' + cur, {'name': name, 'prevent_reimport': False})[0]))
    mgr.call('POST', '/api/discovery/refresh', {})
    st, prev = mgr.call('POST', '/api/discovery/import-preview', {'name': name})
    st2, imp = mgr.call('POST', '/api/discovery/import', {'name': name, 'token': prev['token']})
    s.say('import-preview %s, import %s -> new lab %s' % (st, st2, imp.get('id', '')[:8]))
s.say('B2 (%s): remove lab %s and import it again' % (MODE, LAB))
reimport(LAB)
s.open_lab(LAB)
for i in range(30):
    if s.lab(LAB)['nos_readiness']['ready'] == 2: break
    p.wait_for_timeout(2000)
s.say('new lab: chip %r; binding %s' % (s.chip(), s.git(LAB).get('binding')))
s.reset_counts()
s.click('#git-save-progress')
expect(p.locator('#save-first-place, #save-first-looking, #save-first').first).to_be_visible(timeout=20000)
p.wait_for_timeout(1500)
s.say('first-save panel: title %r' % s.text('#save-panel-title'))
s.say('panel text: %r' % s.panel().replace('\n', ' | ')[:520])
s.say('buttons: %s' % p.locator('#save-panel-body button').evaluate_all("els=>els.map(e=>e.id+':'+e.textContent.trim())"))
s.shot('B2-first-save-%s' % MODE)
q = s.visible('#save-first-continue')
s.say('same-name question asked: %s' % q)
if MODE == 'continue':
    s.check('B2 the same-name question is asked', q)
    s.click('#save-first-continue')
else:
    if q:
        s.click(p.locator('#save-first'))      # Save in <name>-2
    else:
        s.click('#save-first')
s.wait_chip(r'^(1 save to upload|Saved .*)$', timeout=90000)
p.wait_for_timeout(1500)
s.say('chip after the first save: %r; panel %r' % (s.chip(), s.text('#save-changes') if s.visible('#save-changes') else s.panel()[:200]))
s.say('CLICKS of the first save so far: %d (typed %d)' % (s.clicks, s.typed))
if s.chip().startswith('1 save'):
    expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$', timeout=60000); s.wait_chip('^Saved ')
s.say('with Upload: %d clicks; lab saves in %s; chip %r' % (s.clicks, s.prefix(LAB), s.chip()))
j = s.jobs(LAB)[-1]; s.say('job: %s' % trim(j, ('status', 'note', 'pushed', 'summary', 'destination'), 600))
github('after B2'); checkout('VM')
s.no_errors('B2'); print(report(s, 'B2')); s.finish()
