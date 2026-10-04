import sys, time
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.open_chip(); p.wait_for_timeout(2000)
cmds = s.text('#save-cant-commands'); s.say('commands read from the panel: %r' % cmds)
for l in [l.strip() for l in cmds.splitlines() if l.strip()]:
    assert l.startswith('git -C %s ' % CHECKOUT), l
    c, out = sh('bash', '-c', l); s.say('ran as %s: $ %s -> exit %s | %s' % (sh('id','-un')[1], l, c, out.replace('\n', ' | ')[-200:]))
checkout('VM after the two commands')
s.say('chip before pressing anything: %r; git_status %s' % (s.chip(), s.lab(LAB)['git_status']))
s.reset_counts()
btn = p.locator('#save-cant-again, #save-retry').first
s.say('pressing %s %r' % (btn.get_attribute('id'), btn.inner_text()))
s.click(btn)
s.wait_chip(r'^(Saved .*|Upload failed|Can’t save|\d saves? to upload)$', timeout=60000)
p.wait_for_timeout(4000)
s.say('after Try again: chip %r; toasts %s; clicks %d' % (s.chip(), s.toasts()[-2:], s.clicks))
s.say('jobs: %s' % [(j['status'], j.get('note'), j.get('pushed'), j.get('message')[:70]) for j in s.jobs(LAB)][-4:])
s.say('waiting %d; git_status %s' % (len(s.waiting(LAB)), s.lab(LAB)['git_status']))
github('after Try again'); checkout('VM after Try again')
s.check('A5 hard case: after the owner commands and Try again every waiting save is uploaded', not s.waiting(LAB) and s.chip().startswith('Saved'), (s.chip(), len(s.waiting(LAB))))
s.no_errors('A5 recovery'); print(report(s, 'A5 recovery')); s.finish()
