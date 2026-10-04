import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB = sys.argv[1]
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
A = s.prefix('git-redesign')
s.say('B4 on %s (saves in %s); lab A saves in %s' % (LAB, s.prefix(LAB), A))
open_chooser(s); s.reset_counts()
s.fill('#folder-path', A); text = chooser_answer(s)
s.say('typed %s -> question %r; buttons %s; note %r' % (A, text, p.locator('#folder-foot button').all_inner_texts(), s.text('#folder-answer-note') if s.visible('#folder-answer-note') else ''))
s.check('B4 the question is asked, not a refusal', 'saves here too' in text and not s.visible('#folder-refused'), text)
s.shot('B4-question-1')
btn = p.locator('#folder-foot [data-folder-choice="beside"]'); s.say('answering with: %r' % btn.inner_text())
s.click(btn)
expect(p.locator('#save-drawer')).to_be_hidden(timeout=30000)
common.wait_until(lambda: s.prefix(LAB) != A and s.prefix(LAB), timeout=20, what='the placement')
s.say('lab B saves in %s; lab A still saves in %s; chip %r' % (s.prefix(LAB), s.prefix('git-redesign'), s.chip()))
s.check('B4 never took A\'s folder', s.prefix('git-redesign') == A and s.prefix(LAB) == A + '/' + LAB, (s.prefix('git-redesign'), s.prefix(LAB)))
s.no_errors('B4'); print(report(s, 'B4')); s.finish()
