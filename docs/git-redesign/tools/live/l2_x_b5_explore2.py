import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.click('#git-save-progress'); p.wait_for_timeout(2500)
s.click('#save-first-url'); p.wait_for_timeout(1500)
s.fill('#folder-url', 'https://github.com/ArchRuger/clab-scratch-git-redesign-empty.git'); p.wait_for_timeout(2500)
s.say('after typing: %r' % s.text('#save-drawer')[:900].replace('\n',' | '))
s.say('buttons: %s' % p.locator('#save-drawer button').all_inner_texts())
s.fill('#folder-path', 'lab-b-empty'); p.wait_for_timeout(2500)
s.say('after changing the folder: %r | buttons %s' % (s.text('#save-drawer')[:700].replace('\n',' | '), p.locator('#save-drawer button').all_inner_texts()))
s.shot('B5-explore2')
s.finish()
