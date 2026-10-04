import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(viewport=(390, 844)); p = s.page
s.open_lab('git-redesign-b')
print('scrollWidth', p.evaluate("document.documentElement.scrollWidth"), 'client', p.evaluate("document.documentElement.clientWidth"))
print(p.evaluate("""[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>391&&e.offsetParent!==null).slice(0,8).map(e=>(e.id||e.className||e.tagName)+':'+Math.round(e.getBoundingClientRect().right))"""))
s.click('#tab-devices', count=False); print('devices tab scrollWidth', p.evaluate("document.documentElement.scrollWidth"))
s.click('#tab-topology', count=False)
s.click('#map-edit', count=False); p.wait_for_url('**/map-editor.html#lab=*'); p.wait_for_selector('.react-flow__node'); p.wait_for_timeout(1500)
s.shot('D1-map-editor-390')
print('nodes', [(n, p.locator('[data-testid="rf__node-%s"]' % n).bounding_box()) for n in ('ceos1','ceos2')])
s.finish()
