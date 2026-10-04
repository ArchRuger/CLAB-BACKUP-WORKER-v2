import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB = sys.argv[1]
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
s.say('B5 afterwards: lab saves in %s of %s' % (s.prefix(LAB), (s.git(LAB).get('binding') or {}).get('repository', {}).get('path')))
open_chooser(s); s.reset_counts()
s.say('repositories offered: %s' % p.locator('#folder-repo option').all_inner_texts())
p.locator('#folder-repo').select_option(label='clab-scratch-git-redesign'); s.clicks += 1
p.wait_for_timeout(2500)
s.fill('#folder-path', 'git-redesign-b'); text = chooser_answer(s)
s.say('answer for git-redesign-b: %r ; buttons %s' % (text, p.locator('#folder-foot button').all_inner_texts()))
s.shot('B5-back-to-scratch')
# the lab's own earlier saves are in this folder: a lab of the same name; choose the way that continues there
btn = p.locator('#folder-foot [data-folder-choice="take"], #folder-foot [data-folder-action="save"]').first
s.say('pressing %r' % btn.inner_text()); s.click(btn)
expect(p.locator('#save-drawer')).to_be_hidden(timeout=30000)
common.wait_until(lambda: (s.git(LAB).get('binding') or {}).get('repository', {}).get('path', '').endswith('clab-scratch-git-redesign') and s.prefix(LAB) == 'git-redesign-b', timeout=30, what='the lab pointed back')
p.wait_for_timeout(2500)
s.say('lab B saves in %s of %s; chip %r; clicks %d' % (s.prefix(LAB), s.git(LAB)['binding']['repository']['path'], s.chip(), s.clicks))
s.no_errors('B5 back'); s.finish()
