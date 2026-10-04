import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.open_chip(); p.wait_for_timeout(2500); s.record_toasts(); s.reset_counts()
s.say('Try again (save-retry) now that the owner has pushed and a no-change save exists')
s.click('#save-retry'); p.wait_for_timeout(8000)
s.say('chip %r; toasts %s; clicks %d' % (s.chip(), s.toasts(), s.clicks))
s.say('jobs %s' % [(j['status'], j.get('note'), j.get('pushed'), j.get('message')[:70]) for j in s.jobs(LAB)][-3:])
s.say('waiting %d git_status %s' % (len(s.waiting(LAB)), s.lab(LAB)['git_status'])); github('GitHub')
s.finish()
