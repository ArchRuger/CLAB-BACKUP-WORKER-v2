import sys, re, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, STATE, TAG = sys.argv[1], sys.argv[2], sys.argv[3]
DEVS = ['a-ceos1', 'a-ceos2', 'a-cjunos', 'a-xrv9k']
s = Live(viewport=(390, 844)); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB); s.close_panels()
s.reset_counts()
load_open(s)
lb = p.locator('#load-panel').bounding_box(); s.say('Load panel box %s ; page scroll x %s' % ({k: round(v) for k, v in lb.items()}, p.evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth")))
rows = p.locator('#load-panel-body .save-list > li button.save-item').evaluate_all("els=>els.map(e=>[e.querySelector('span').textContent.trim(), Math.round(e.getBoundingClientRect().height)])"); s.say('rows (name, height px): %s' % rows[:10])
s.shot('D3-load-list-390')
load_choose(s, STATE)
s.say('confirmation: %r' % s.text('#load-panel-body .save-state'))
rb = p.locator('#load-run').bounding_box(); s.say('red Load box %s ; foot buttons %s' % ({k: round(v) for k, v in rb.items()}, p.locator('#load-panel-body .save-row').last.locator('button').evaluate_all("els=>els.map(e=>[e.textContent.trim(), Math.round(e.getBoundingClientRect().width), Math.round(e.getBoundingClientRect().height)])")))
s.shot('D3-confirmation-390')
s.click('#load-run')
s.wait_chip(r'^(Loading…|Checking)', timeout=30000)
p.wait_for_timeout(500); s.shot('D3-loading-390')
s.say('while loading: chip %r ; panel visible %s ; covers Save/Load buttons: %s' % (s.chip(), s.visible('#save-panel'), p.evaluate("(()=>{const r=document.getElementById('save-panel').getBoundingClientRect();const b=document.getElementById('load-button').getBoundingClientRect();return r.bottom>b.top&&r.top<b.bottom})()")))
s.wait_chip(r'^(Running .*|Loaded \d of \d)$', timeout=180000); p.wait_for_timeout(2500)
s.say('result: chip %r ; panel %r ; clicks %d' % (s.chip(), s.panel().replace('\n', ' | ')[:250] if s.visible('#save-panel') else None, s.clicks))
s.shot('D3-result-390')
got = descriptions(DEVS); s.say('CLI read-back: %s' % {k: v.split()[-1] for k, v in got.items()})
s.check('D3 every device runs %s' % STATE, all(TAG in v for v in got.values()), got)
s.say('errors %s ; failed %s' % (s.errors, s.failed))
s.no_errors('D3'); print(report(s, 'D3')); s.finish()
