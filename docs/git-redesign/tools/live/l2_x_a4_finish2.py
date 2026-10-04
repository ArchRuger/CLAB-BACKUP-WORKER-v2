import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.open_chip()
s.say('chip %r panel %r' % (s.chip(), s.panel().replace('\n',' | ')[:260]))
s.reset_counts()
btn = p.locator('#save-retry, #save-cant-again').first; s.say('button id %s' % btn.get_attribute('id'))
s.click(btn)
s.wait_toast(r'^Uploaded to github\.com\.$', timeout=60000); s.wait_chip('^Saved ')
s.say('after Try again (network back): chip %r; clicks %d; git_status %s' % (s.chip(), s.clicks, s.lab(LAB)['git_status']))
s.say('jobs: %s' % [(j['status'], j.get('note'), j.get('pushed'), j.get('message')) for j in s.jobs(LAB)][-3:])
github('after A4 retry'); checkout('VM')
s.no_errors('A4 finish'); s.finish()
