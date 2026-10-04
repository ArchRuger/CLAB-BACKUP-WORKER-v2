import sys, base64
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, DEV = 'git-redesign-b', 'b-ceos1'
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB); s.record_toasts()
set_description(DEV, 'l3-1')
s.click('#git-save-progress'); s.wait_chip(r'^1 save to upload$', timeout=60000); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.click('#save-not-now'); s.say('kept with Not now: chip %r' % s.chip())
c, out = sh('gh', 'api', '-X', 'PUT', 'repos/%s/contents/l3-online/one.txt' % REPO, '-f', 'message=L3 online change', '-f', 'content=' + base64.b64encode(b'l3\n').decode(), '--jq', '.commit.sha'); s.say('gh api PUT -> %s %s' % (c, out[:10]))
s.reset_counts(); s.click('#save-chip'); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000); s.click('#save-upload')
s.wait_chip(r'^Can’t save$', timeout=60000)
expect(p.locator('#save-cant-commands')).to_be_visible(timeout=30000); p.wait_for_timeout(1500)
s.say('PANEL: %r' % s.panel().replace('\n', ' | ')[:420]); s.shot('l3-1-both-sides')
cmds = [l.strip() for l in s.text('#save-cant-commands').splitlines() if l.strip()]
for l in cmds:
    assert l.startswith('git -C %s ' % CHECKOUT), l
    c, o = sh('bash', '-c', l); s.say('ran as %s: $ %s -> exit %s' % (sh('id', '-un')[1], l, c))
s.say('chip before Try again: %r ; waiting %s' % (s.chip(), [(j['status']) for j in s.waiting(LAB)]))
s.reset_counts(); n0 = len(s.jobs(LAB)); del s.sent[:]
s.click(p.locator('#save-panel-body button', has_text='Try again').first)
s.wait_chip(r'^Saved ', timeout=60000); p.wait_for_timeout(2000)
s.say('after ONE click on Try again: chip %r ; toasts %s ; clicks %d ; new jobs %d ; requests %s' % (s.chip(), s.toasts(), s.clicks, len(s.jobs(LAB)) - n0, [c[:90] for c in s.sent]))
s.say('waiting saves: %d ; git_status %s ; panel error visible %s' % (len(s.waiting(LAB)), s.lab(LAB)['git_status'], s.visible('#save-panel-error')))
s.shot('l3-1-after-try-again')
github('GitHub'); checkout('VM')
s.check('1 Try again uploads every waiting save, chip Saved, no extra Save', not s.waiting(LAB) and s.chip().startswith('Saved') and len(s.jobs(LAB)) == n0, (s.chip(), len(s.waiting(LAB))))
s.say('errors %s ; failed %s' % (s.errors, s.failed)); s.no_errors('item 1'); print(report(s, 'item 1')); s.finish()
