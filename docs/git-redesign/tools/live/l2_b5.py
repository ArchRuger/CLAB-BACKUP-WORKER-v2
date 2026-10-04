import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB = sys.argv[1]; URL = 'https://github.com/ArchRuger/clab-scratch-git-redesign-empty.git'
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
s.say('B5 on %s: binding %s' % (LAB, s.git(LAB).get('binding')))
s.reset_counts()
s.click('#git-save-progress'); p.wait_for_timeout(2500)
s.click('#save-first-url'); p.wait_for_timeout(1000)
s.fill('#folder-url', URL); p.wait_for_timeout(2500)
s.say('STALE ANSWER with the address typed: %r buttons %s' % (s.text('#folder-answer') if s.visible('#folder-answer') else None, p.locator('#folder-foot button').all_inner_texts()))
s.fill('#folder-path', 'git-redesign-b'); p.wait_for_timeout(500)
s.fill('#folder-path', 'lab-b-empty'); p.wait_for_timeout(2500)
s.say('buttons now: %s' % p.locator('#folder-foot button').all_inner_texts())
s.click(p.locator('#folder-foot button', has_text='Connect and save here'))
p.wait_for_timeout(6000)
s.say('after Connect and save here: chip %r; drawer %s; panel %r' % (s.chip(), s.visible('#save-drawer'), s.panel().replace('\n', ' | ')[:300]))
s.say('drawer text: %r' % (s.text('#save-drawer')[:500].replace('\n', ' | ') if s.visible('#save-drawer') else ''))
s.shot('B5-empty-repository')
start = p.locator('#save-first-start, #folder-foot button:has-text("Start the repository"), button:has-text("Start the repository")').first
expect(start).to_be_visible(timeout=30000)
s.say('empty-repository sentence: %r ; button %r' % (p.locator('#save-first-empty, #folder-answer').first.inner_text(), start.inner_text()))
s.click(start)
s.wait_chip(r'^(1 save to upload|Saved .*)$', timeout=120000)
p.wait_for_timeout(1500)
s.say('after Start the repository: chip %r; sentence %r; clicks so far %d (typed %d)' % (s.chip(), s.text('#save-changes') if s.visible('#save-changes') else s.panel()[:200], s.clicks, s.typed))
if s.chip().startswith('1 save'):
    expect(p.locator('#save-upload')).to_be_enabled(timeout=30000)
    s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$', timeout=90000); s.wait_chip('^Saved ')
s.say('uploaded: chip %r; clicks %d; lab saves in %s of %s' % (s.chip(), s.clicks, s.prefix(LAB), (s.git(LAB).get('binding') or {}).get('repository', {}).get('path')))
EMPTY = 'ArchRuger/clab-scratch-git-redesign-empty'
c, out = sh('gh', 'api', 'repos/%s/commits' % EMPTY, '--jq', r'.[] | "\(.sha[0:10]) \(.commit.message | split("\n")[0])"')
s.say('GitHub commits of the new repository:\n' + out)
c, out = sh('gh', 'api', 'repos/%s/git/trees/main?recursive=1' % EMPTY, '--jq', '.tree[] | select(.type=="blob") | .path')
s.say('files on GitHub: %s' % out.replace('\n', ', '))
s.no_errors('B5'); print(report(s, 'B5')); s.finish()
