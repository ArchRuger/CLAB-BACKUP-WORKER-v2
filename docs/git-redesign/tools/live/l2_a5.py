import sys, re, base64, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, DEV = sys.argv[1], sys.argv[2]
s = Live(); p = s.page
def online(path, text, msg):
    c, out = sh('gh', 'api', '-X', 'PUT', 'repos/%s/contents/%s' % (REPO, path), '-f', 'message=' + msg, '-f', 'content=' + base64.b64encode(text.encode()).decode(), '--jq', '.commit.sha')
    s.say('gh api PUT %s -> %s %s' % (path, c, out[:10])); return out
def events(since):
    ev = mgr.call('GET', '/api/logs?lab_id=%s&limit=60' % lab_id(LAB))[1]['events']
    return [(e.get('time', e.get('ts', ''))[11:19], e.get('kind') or e.get('type') or e.get('action'), (e.get('message') or '')[:140]) for e in ev if 'git' in str(e.get('kind') or e.get('type') or e.get('action'))][:8]
s.open_lab(LAB); s.wait_quiet(LAB)
s.say('A5 part 1 on %s: online copy ahead, nothing waiting; chip %s; waiting %s' % (LAB, s.chip(), s.waiting(LAB)))
online('l2-online/a5-online-1.txt', 'added online by L2 A5\n', 'L2 A5 online change 1 (outside the lab folders)')
s.say('VM: %s ; the VM knows nothing yet: %s' % (vmgit('status', '-sb')[1].splitlines()[0], vmgit('log', '--oneline', '-1')[1]))
set_description(DEV, 'l2-a5')
s.reset_counts()
s.click('#git-save-progress'); s.wait_chip(r'^(1 save to upload|Can’t save)$', timeout=60000)
s.say('after Save: chip %r panel %r / %r' % (s.chip(), s.text('#save-panel-title'), s.text('#save-changes') if s.visible('#save-changes') else s.panel()[:200]))
expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.click('#save-upload'); s.wait_chip(r'^(Saved .*|Upload failed|Can’t save)$', timeout=60000)
p.wait_for_timeout(1500)
s.say('after Upload: chip %r; clicks %d (Save, Upload); toast %s' % (s.chip(), s.clicks, s.toasts()[-1:]))
s.check('A5 Save then Upload ends Saved with nothing done by hand', s.chip().startswith('Saved'), s.chip())
github('after A5 part 1'); checkout('VM after A5 part 1')
s.say('VM log shows the online file merged first: %s' % sh('git', '-C', CHECKOUT, 'log', '--oneline', '-4', '--format=%h %p | %s')[1].replace('\n', ' // '))
s.say('files at the VM: %s' % sh('ls', CHECKOUT + '/l2-online')[1])
s.say('lab events (git): %s' % events(0))
job = s.jobs(LAB)[-1]; s.say('job: %s' % trim(job, ('status', 'note', 'pushed', 'message')))
s.open_lab(LAB); s.click('#tab-advanced', count=False); p.wait_for_timeout(1500)
logs = p.locator('#logs-view').inner_text() if s.visible('#logs-view') else ''
s.say('Advanced > logs mentions the update: %s' % ('brought up to date' in logs))
hits = [l for l in logs.splitlines() if 'up to date with the online' in l]; s.say('log lines: %s' % hits[:2])
s.shot('A5-advanced-logs')
s.no_errors('A5 part 1'); print(report(s, 'A5 part 1')); s.finish()
