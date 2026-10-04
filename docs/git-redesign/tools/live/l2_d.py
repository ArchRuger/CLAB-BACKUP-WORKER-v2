import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, DEV, NODE = sys.argv[1], sys.argv[2], sys.argv[3]
s = Live(viewport=(390, 844)); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
def overflow():
    return p.evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth")
def boxes():
    return {k: p.locator(sel).bounding_box() for k, sel in (('chip', '#save-chip'), ('Save', '#git-save-progress'), ('Load', '#load-button'), ('Lab actions', '#lab-actions-button'))}
b = boxes(); s.say('D header at 390: %s; horizontal page scroll: %s' % ({k: (round(v['x']), round(v['y']), round(v['width'])) for k, v in b.items() if v}, overflow()))
s.check('D header: the four controls are inside the screen', all(v and v['x'] >= 0 and v['x'] + v['width'] <= 390 for v in b.values()))
s.shot('D1-header-390')
# ---- D1: A2's save and upload
set_description(DEV, 'l2-d1')
s.say('D1 map move by the page at 390 ...')
try:
    move_on_map(s, NODE, 20, 15)
    s.shot('D1-map-editor-after')
except Exception as e:
    s.say('map editor at 390 FAILED: %s' % str(e)[:200])
    s.open_lab(LAB)
s.reset_counts(); s.click('#git-save-progress'); s.wait_chip('Saving…', timeout=8000)
s.shot('D1-saving')
s.wait_chip(r'^1 save to upload$', timeout=60000); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
bb = p.locator('#save-panel').bounding_box(); s.say('waiting panel box %s; page scroll x %s; sentence %r' % ({k: round(v) for k, v in bb.items()}, overflow(), s.text('#save-changes')))
s.shot('D1-waiting-panel')
ub = p.locator('#save-upload').bounding_box(); s.say('Upload button box %s (min target 44px high: %s)' % ({k: round(v) for k, v in ub.items()}, ub['height'] >= 44))
s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$', timeout=60000); s.wait_chip('^Saved ')
s.shot('D1-saved')
s.say('D1: Save -> Upload = %d clicks, typed %d; chip %r' % (s.clicks, s.typed, s.chip()))
s.close_panels()
# ---- D2: B1's chooser
open_chooser(s)
s.shot('D2-chooser-open')
s.say('chooser box %s; page scroll x %s' % ({k: round(v) for k, v in p.locator('#save-drawer').bounding_box().items()}, overflow()))
enabled, before, made, after = new_folder_in(s, '', 'l2-d2-top')
s.say('D2 New folder… at the top level: enabled %s, created %r, %r' % (enabled, made, after))
s.shot('D2-new-folder')
nb = p.locator('.folder-chooser [data-folder-action="new"]').bounding_box(); s.say('New folder… button box %s' % {k: round(v) for k, v in nb.items()})
fb = p.locator('#folder-foot button').evaluate_all("els=>els.map(e=>[e.textContent.trim(), Math.round(e.getBoundingClientRect().width), Math.round(e.getBoundingClientRect().height)])"); s.say('foot buttons (text,w,h): %s' % fb)
s.click('#folder-foot [data-folder-action="cancel"]')
s.no_errors('D1 D2 at 390'); print(report(s, 'D1 D2')); s.finish()
