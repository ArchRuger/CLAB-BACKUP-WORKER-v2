import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign'
s.open_lab(LAB); s.wait_quiet(LAB); s.record_toasts()
before = vmgit('rev-parse', 'HEAD')[1]
s.click('#git-save-progress')
try: s.wait_toast(r'^Nothing changed since your last save\.$', timeout=60000); res = 'toast'
except AssertionError: res = 'no toast; chip %r' % s.chip()
p.wait_for_timeout(1500)
s.say('unchanged Save on lab A (4 devices incl. Junos and IOS XR): %s ; VM HEAD moved: %s ; chip %r ; panel %r' % (res, vmgit('rev-parse','HEAD')[1] != before, s.chip(), s.panel().replace('\n',' | ')[:200] if s.visible('#save-panel') else None))
s.finish()
