import sys, re
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page
A = 'git-redesign'
s.open_lab(A)
tabs = p.evaluate("[...document.querySelectorAll('[role=tab],.tab-button,[id^=tab-]')].map(e=>e.id+':'+e.textContent.trim())")
s.say('tabs: ' + str(tabs))
for tab in ['topology', 'devices', 'tools', 'advanced']:
    if p.locator('#tab-' + tab).count() == 0:
        s.check('A1 tab %s exists' % tab, False); continue
    s.click('#tab-' + tab, count=False)
    boxes = [p.locator(sel).bounding_box() for sel in ['#save-chip', '#git-save-progress', '#load-button', '#lab-actions-button']]
    s.check('A1 %s tab: chip, Save, Load, Lab actions visible' % tab, all(boxes))
    s.check('A1 %s tab: one row at 1440 and in order' % tab, all(boxes) and len({round(b['y'] + b['height'] / 2) for b in boxes}) == 1 and [b['x'] for b in boxes] == sorted(b['x'] for b in boxes))
s.check('A1 no Progress tab', p.locator('#tab-progress').count() == 0 and not any('progress' in t.lower() for t in tabs), tabs)
s.say('chip text: ' + s.chip())
s.shot('A1-header-topology')
for view in ('progress', 'git'):
    p.goto('%s/#lab=%s&view=%s' % (s.base, lab_id(A), view)); p.reload()
    p.wait_for_selector('#lab-content:not([hidden])')
    try:
        expect(p.locator('#save-panel')).to_be_visible(timeout=15000)
        ok = True
    except Exception as e:
        ok = False
    active = p.evaluate("(()=>{const t=document.getElementById('tab-topology');return t.getAttribute('aria-selected')+'/'+t.className})()")
    s.check('A1 old address view=%s: chip panel open on the first tab' % view, ok and active.startswith('true'), (ok, active, p.url))
    s.say('view=%s -> url %s active tab %s panel title %r' % (view, p.url.replace(BASE, ''), active, s.text('#save-panel-title') if ok else None))
    s.shot('A1-old-address-%s' % view)
    s.close_panels()
s.no_errors('A1')
print(report(s, 'A1'))
s.finish()
