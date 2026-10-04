import sys, re, base64, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, DEV = sys.argv[1], sys.argv[2]
s = Live(); p = s.page
def online(path, text, msg):
    c, out = sh('gh', 'api', '-X', 'PUT', 'repos/%s/contents/%s' % (REPO, path), '-f', 'message=' + msg, '-f', 'content=' + base64.b64encode(text.encode()).decode(), '--jq', '.commit.sha')
    s.say('gh api PUT %s -> %s %s' % (path, c, out[:10])); return out
s.open_lab(LAB); s.wait_quiet(LAB)
s.say('A5 hard case on %s; chip %s' % (LAB, s.chip()))
set_description(DEV, 'l2-a5-hard')
s.click('#git-save-progress'); s.wait_chip(r'^1 save to upload$', timeout=60000); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.click('#save-not-now')
s.say('kept waiting with Not now: chip %r; VM %s' % (s.chip(), vmgit('log', '--oneline', '-1')[1]))
online('l2-online/a5-online-2.txt', 'added online by L2 A5 hard case\n', 'L2 A5 online change 2 (outside the lab folders)')
s.reset_counts()
s.click('#save-chip'); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.click('#save-upload')
s.wait_chip(r'^(Can’t save|Upload failed)$', timeout=60000)
expect(p.locator('#save-cant-commands, #save-retry, #save-cant-again').first).to_be_visible(timeout=15000)
p.wait_for_timeout(500)
s.say('chip %r; panel title %r' % (s.chip(), s.text('#save-panel-title')))
s.say('PANEL TEXT: %r' % s.panel().replace('\n', ' | '))
cmds = s.text('#save-cant-commands') if s.visible('#save-cant-commands') else ''
s.say('commands shown: %r' % cmds)
s.say('buttons: %s' % p.locator('#save-panel-body button').all_inner_texts())
s.shot('A5-both-sides')
s.check('A5 the panel shows the sentence about both sides', 'both' in s.panel().lower() or 'each' in s.panel().lower(), s.panel()[:200])
s.check('A5 the panel shows the checkout path in the commands', CHECKOUT in cmds, cmds)
lines = [l.strip() for l in cmds.splitlines() if l.strip()]
s.say('git_status %s' % s.lab(LAB)['git_status'])
if lines and all(l.startswith('git -C ') for l in lines):
    for l in lines:
        c, out = sh('bash', '-c', l)
        s.say('ran as the checkout owner: $ %s -> exit %s %s' % (l, c, out.replace('\n', ' | ')[-160:]))
else:
    s.say('commands are not plain git -C lines; not run: %r' % lines)
checkout('VM after the owner commands')
s.reset_counts()
btn = p.locator('#save-cant-again, #save-retry').first
s.say('Try again button: %s %r' % (btn.get_attribute('id'), btn.inner_text()))
s.click(btn)
s.wait_chip(r'^(Saved .*|Upload failed|Can’t save|\d saves? to upload)$', timeout=60000)
p.wait_for_timeout(3000)
s.say('after Try again: chip %r; toasts %s; clicks %d' % (s.chip(), s.toasts()[-2:], s.clicks))
if s.chip().endswith('to upload'):
    s.open_chip(); s.say('panel %r' % s.panel()[:200])
s.say('jobs: %s' % [(j['status'], j.get('note'), j.get('pushed')) for j in s.jobs(LAB)][-3:])
s.say('waiting: %s; git_status %s' % (len(s.waiting(LAB)), s.lab(LAB)['git_status']))
github('after Try again'); checkout('VM after Try again')
s.check('A5 every waiting save ends uploaded', not s.waiting(LAB) and s.chip().startswith('Saved'), (s.chip(), len(s.waiting(LAB))))
s.no_errors('A5 hard case'); print(report(s, 'A5 hard case')); s.finish()
