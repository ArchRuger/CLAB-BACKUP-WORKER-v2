import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.wait_quiet(LAB); s.record_toasts()
s.say('before: chip %r jobs %s' % (s.chip(), [(j['status'], j.get('pushed')) for j in s.jobs(LAB)][-3:]))
s.reset_counts(); s.click('#git-save-progress'); p.wait_for_timeout(9000)
s.say('Save with no device change: chip %r; toasts %s; panel open %s' % (s.chip(), s.toasts(), s.visible('#save-panel')))
if s.visible('#save-panel'): s.say('panel: %r' % s.panel().replace('\n',' | ')[:400])
s.say('jobs %s' % [(j['status'], j.get('note'), j.get('pushed'), j.get('message')[:70]) for j in s.jobs(LAB)][-3:])
s.say('git_status %s' % s.lab(LAB)['git_status'])
checkout('VM'); github('GitHub')
s.finish()
