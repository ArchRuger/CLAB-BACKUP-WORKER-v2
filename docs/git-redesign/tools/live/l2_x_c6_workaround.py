import sys, re
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign'
s.open_lab(LAB); s.close_panels(); p.wait_for_timeout(1000)
s.click('#git-save-progress'); p.wait_for_timeout(1000)
s.click('#save-as-state'); expect(p.locator('#state-name')).to_be_visible(timeout=15000)
s.wait_js("!!document.querySelector('#folder-repo')&&!!document.querySelector('#folder-repo').value&&!/still loading/.test(document.getElementById('save-drawer').textContent)", what='drawer')
s.say('drawer for an unbound lab: %r' % s.text('#save-drawer')[:500].replace('\n',' | '))
s.fill('#state-name', 'c6probe'); p.wait_for_timeout(2500)
s.say('folder %r ; buttons %s' % (p.locator('#folder-path').input_value(), p.locator('#save-drawer button').all_inner_texts()))
known = {j['id'] for j in s.jobs(LAB)}
s.click(p.locator('#save-drawer button', has_text='Save state'))
common.wait_until(lambda: any(j['id'] not in known and j['status'] in ('review_pending','committed','synced') for j in s.jobs(LAB)), timeout=120, what='state save')
p.wait_for_timeout(2500)
s.say('after the state save: chip %r ; lab binding %s' % (s.chip(), s.git(LAB).get('binding') and s.prefix(LAB)))
s.close_panels(); s.click('#git-save-progress'); p.wait_for_timeout(3500)
s.say('Save now opens: %r' % s.panel().replace('\n',' | ')[:420])
s.say('buttons: %s' % p.locator('#save-panel-body button').evaluate_all("els=>els.map(e=>e.id+':'+e.textContent.trim())"))
s.shot('C6-first-save-question')
s.finish()
