import sys, re
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, DEV = sys.argv[1], sys.argv[2]
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
A_FOLDER = s.prefix('git-redesign')
def choose(folder):
    open_chooser(s)
    s.fill('#folder-path', folder)
    return chooser_answer(s)
def upload_all():
    s.close_panels(); s.open_chip(); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.click('#save-upload', count=False); s.wait_toast(r'^Uploaded to'); s.wait_chip('^Saved '); s.close_panels()
s.say('B3 on %s: saves in %s; lab A saves in %s' % (LAB, s.prefix(LAB), A_FOLDER))
# --- 1. move into a folder inside lab A's folder with the files brought along
s.reset_counts()
text = choose(A_FOLDER + '/inner')
s.say('typed %s/inner -> answer %r; bring-along line: %r ticked=%s; foot %s' % (A_FOLDER, text, s.text('#folder-move').strip() if s.visible('#folder-move') else None, p.locator('#folder-move input').is_checked() if s.visible('#folder-move') else None, p.locator('#folder-foot button').all_inner_texts()))
s.shot('B3-chooser-inner')
s.click('#folder-foot [data-folder-action="save"]')
expect(p.locator('#save-drawer')).to_be_hidden(timeout=30000)
common.wait_until(lambda: s.prefix(LAB) == A_FOLDER + '/inner', timeout=20, what='the move')
s.wait_chip(r'^1 save to upload$', timeout=60000)
s.say('moved: lab saves in %s; chip %r; clicks (chip, Change…, [type], Save here) = %d, typed %d' % (s.prefix(LAB), s.chip(), s.clicks, s.typed))
s.open_chip(); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.say('move panel: title %r sentence %r' % (s.text('#save-panel-title'), s.text('#save-changes')))
s.click('#save-see'); expect(p.locator('#save-drawer-content')).to_contain_text('This moves', timeout=15000)
s.say('What changed: %r' % s.text('#save-drawer-content')[:260].replace('\n', ' | '))
s.click('#save-drawer-actions [data-save-action="upload"]'); s.wait_toast(r'^Uploaded to'); s.wait_chip('^Saved ')
github('after the move upload')
s.say('GitHub: %s ; old folder files left: %d ; new folder files: %d' % ('', len(gh_tree('git-redesign-b-2/')), len(gh_tree(A_FOLDER + '/inner/'))))
s.say('registrations/lab A unaffected: lab A saves in %s' % s.prefix('git-redesign'))
s.close_panels()
# --- 2. a folder change while a save waits: question 3, both answers
for n, (answer, sel, tag) in enumerate((('Upload it, then move', 'upload', 'l2-move-1'), ('Move and keep that save on the VM only', 'keep', 'l2-move-2')), 1):
    p.wait_for_timeout(5200)
    set_description(DEV, 'l2-b3-try%d' % n)
    s.click('#git-save-progress', count=False); s.wait_chip(r'^1 save to upload$', timeout=60000); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.click('#save-not-now', count=False)
    before = s.prefix(LAB); s.reset_counts()
    choose(tag)
    s.click('#folder-foot [data-folder-action="save"]')
    expect(p.locator('#folder-foot [data-folder-pending="%s"]' % sel)).to_be_visible(timeout=20000)
    s.say('TRY %d: question 3 text %r; note %r; buttons %s' % (n, s.text('#folder-answer'), s.text('#folder-answer-note') if s.visible('#folder-answer-note') else '', p.locator('#folder-foot button').all_inner_texts()))
    s.shot('B3-question-3-try-%d' % n)
    s.click('#folder-foot [data-folder-pending="%s"]' % sel)
    expect(p.locator('#save-drawer')).to_be_hidden(timeout=60000)
    common.wait_until(lambda: s.prefix(LAB) == tag, timeout=30, what='the folder change')
    p.wait_for_timeout(3000)
    s.say('answered %r: lab saves in %s (was %s); chip %r; waiting saves %s; clicks %d' % (answer, s.prefix(LAB), before, s.chip(),
          [(j['status'], j.get('target'), j.get('pushed'), (j.get('destination') or {}).get('path')) for j in s.waiting(LAB)], s.clicks))
    if sel == 'keep':
        s.check('B3 keep: the save keeps waiting', len(s.waiting(LAB)) >= 1, s.chip())
        github('GitHub before uploading the kept save')
    else:
        s.check('B3 upload then move: nothing waits for the old save', all(j.get('target') == 'move' for j in s.waiting(LAB)) or not s.waiting(LAB), s.chip())
    upload_all() if s.chip() != 'Saved just now' and not s.chip().startswith('Saved') else None
    if not s.chip().startswith('Saved'): upload_all()
    github('after try %d' % n)
    s.say('after try %d: GitHub folders: %s' % (n, sorted({'/'.join(x.split('/')[:-1]) for x in gh_tree('') if x.endswith('manifest.json') and (A_FOLDER + '/inner' in x or 'l2-move' in x)})))
s.no_errors('B3'); print(report(s, 'B3')); s.finish()
