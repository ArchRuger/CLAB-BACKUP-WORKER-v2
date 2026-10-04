import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.open_chip(); p.wait_for_timeout(4000)
s.say('panel %r' % s.panel().replace('\n',' | ')[:200])
s.say('upload enabled: %s; failed so far %s' % (p.locator('#save-upload').is_enabled() if p.locator('#save-upload').count() else None, s.failed))
del s.sent[:]
if p.locator('#save-upload').count() and p.locator('#save-upload').is_enabled():
    s.click('#save-upload'); p.wait_for_timeout(8000)
    s.say('after Upload: chip %r; requests %s; failed %s; toasts %s' % (s.chip(), [c[:110] for c in s.sent], s.failed, s.toasts()))
s.finish()
