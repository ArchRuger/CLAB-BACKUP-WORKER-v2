import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB = sys.argv[1]
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
s.say('B1 on %s; saves in %s' % (LAB, s.prefix(LAB)))
open_chooser(s)
s.say('chooser title %r; New folder… enabled at open: %s; foot: %s' % (s.text('#save-drawer-title'), new_folder_enabled(s), p.locator('#folder-foot button').all_inner_texts()))
tree_rows = p.locator('#folder-tree [data-folder]').evaluate_all("els=>els.map(e=>e.getAttribute('data-folder')+(e.querySelector(':scope > .folder-row .git-tag')?' ['+e.querySelector(':scope > .folder-row .git-tag').textContent.trim()+']':''))")
s.say('tree rows: %s' % tree_rows)
s.shot('B1-chooser-open')
for tag, parent, name in (('top level', '', 'l2-top'), ('inside a lab folder', 'git-redesign', 'l2-in-lab'), ('nested', 'git-redesign/l2-in-lab', 'l2-nested')):
    enabled, before, made, after = new_folder_in(s, parent, name)
    s.check('B1 New folder… is enabled with %s selected' % (parent or 'the top level'), enabled, before)
    s.say('%s: parent %r selected -> answer %r; New folder… enabled %s; created %r; sentence after: %r; refusal shown: %s' % (tag, parent, before, enabled, made, after, s.visible('#folder-refused')))
    s.check('B1 %s: created, planned, no refusal' % tag, not s.visible('#folder-refused') and made.endswith(name) and 'is new' in after, (made, after))
    s.shot('B1-new-folder-%s' % tag.replace(' ', '-'))
s.click('#folder-foot [data-folder-action="cancel"]')
s.say('cancelled; the lab still saves in %s' % s.prefix(LAB))
s.no_errors('B1'); print(report(s, 'B1')); s.finish()
