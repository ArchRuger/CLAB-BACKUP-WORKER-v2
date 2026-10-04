import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.click('#load-button'); expect(p.locator('#load-start')).to_be_visible(timeout=20000)
s.click('#load-start'); expect(p.locator('#operation-review')).to_be_visible(timeout=20000); p.wait_for_timeout(1500)
s.say('review dialog: %r' % s.text('#operation-review')[:700].replace('\n', ' | '))
s.say('buttons: %s' % p.locator('#operation-review button').evaluate_all("els=>els.map(e=>e.id+':'+e.textContent.trim())"))
s.shot('C5-start-lab-review')
btn = p.locator('#operation-confirm, #operation-review button.primary, #operation-review button.danger').first
s.say('confirm button %r' % btn.inner_text()); s.click(btn)
for i in range(40):
    r = s.lab(LAB)['nos_readiness'];
    if r['ready'] == 2: break
    p.wait_for_timeout(3000)
s.say('lab B after Start lab: %s; label %r; chip %r' % (s.lab(LAB)['nos_readiness'], s.text('#lab-state'), s.chip()))
s.shot('C5-after-start')
s.no_errors('C5'); s.finish()
