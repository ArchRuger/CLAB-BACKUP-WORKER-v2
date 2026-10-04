import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB = sys.argv[1]
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
lid = lab_id(LAB)
def op(action):
    st, pv = mgr.call('POST', '/api/operations/preview', {'action': action, 'lab_id': lid})
    st2, c = mgr.call('POST', '/api/operations/confirm', {'token': pv['token']})
    for _ in range(60):
        j = mgr.call('GET', '/api/operations/' + c['id'])[1]
        if j.get('status') not in ('queued', 'running'): return j
        time.sleep(3)
s.say('C5: destroy %s with the manager\'s own lab operation (POST /api/operations/preview + confirm)' % LAB)
j = op('destroy'); s.say('destroy job: %s' % trim(j, ('status', 'message'), 200))
p.wait_for_timeout(8000); s.open_lab(LAB)
s.wait_js("document.getElementById('lab-state').textContent!=='Running'", timeout=60000, what='the lab to read stopped')
s.say('lab state label: %r ; chip %r' % (s.text('#lab-state'), s.chip()))
s.reset_counts(); s.click('#load-button')
expect(p.locator('#load-start')).to_be_visible(timeout=20000)
s.say('Load panel: %r ; buttons %s' % (s.text('#load-panel-body').replace('\n', ' | ')[:400], p.locator('#load-panel-body button').all_inner_texts()))
s.check('C5 the Load panel says the lab is not running and offers Start lab', 'Start the lab to load a state' in s.text('#load-panel-body') and s.text('#load-start') == 'Start lab')
s.shot('C5-stopped-lab-load')
s.click('#load-start')
p.wait_for_timeout(3000)
s.say('after Start lab: url %s ; dialog/drawer: %r' % (p.url.replace(BASE, ''), (s.text('dialog[open], .dialog[open], [role=dialog]')[:300].replace('\n', ' | ') if p.locator('dialog[open], [role=dialog]').count() else None)))
s.shot('C5-after-start-lab')
s.say('buttons now: %s' % p.evaluate("[...document.querySelectorAll('dialog[open] button, [role=dialog] button')].filter(b=>b.offsetParent).map(b=>b.id+':'+b.textContent.trim())"))
s.finish()
