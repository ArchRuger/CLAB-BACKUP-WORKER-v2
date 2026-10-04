import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.open_chip(); p.wait_for_timeout(1500)
p.locator('#save-cant-upload-again').click(); p.wait_for_timeout(4000)
s.say('panel error element: %r visible %s' % (p.locator('#save-panel-error').inner_text() if p.locator('#save-panel-error').count() else None, s.visible('#save-panel-error')))
s.say('toast now: %r; live region: %r' % (s.toast(), p.evaluate("(document.querySelector('[aria-live]')||{}).textContent")))
s.say('FULL PANEL: %r' % s.panel().replace('\n',' | '))
s.shot('A5-try-again-does-nothing')
s.finish()
