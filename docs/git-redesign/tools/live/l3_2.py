import sys, re
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB, STATE, TAG, DEVS = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4].split(',')
s = Live(); p = s.page
import os
old = lab_id(LAB)
if not os.environ.get('SKIP_IMPORT'):
  s.say('DELETE lab %s (manager only) -> %s' % (old[:8], mgr.call('DELETE', '/api/labs/' + old, {'name': LAB, 'prevent_reimport': False})[0]))
  mgr.call('POST', '/api/discovery/refresh', {})
  st, prev = mgr.call('POST', '/api/discovery/import-preview', {'name': LAB}); st2, imp = mgr.call('POST', '/api/discovery/import', {'name': LAB, 'token': prev['token']})
  s.say('import %s -> new record %s' % (st2, imp.get('id', '')[:8])); time.sleep(3)
s.open_lab(LAB)
for i in range(60):
    r = s.lab(LAB)['nos_readiness']
    if r['ready'] == r['total'] and r['total']: break
    p.wait_for_timeout(3000)
s.say('chip %r ; binding %s' % (s.chip(), s.git(LAB).get('binding')))
s.reset_counts(); load_open(s)
names = [x.split('\n')[0] for x in p.locator('#load-panel-body .save-list > li .save-item > span:first-child').all_inner_texts()]
s.say('Load panel text: %r' % s.text('#load-panel-body')[:420].replace('\n', ' | '))
s.say('rows in order: %s' % names)
s.shot('l3-2-load-list-%s' % LAB)
s.check('3 Start, Broken and Final are on the first screen, before the other labs\' states', {'Start', 'Broken', 'Final'} <= set(names[:4]), names)
exact = p.locator('#load-panel-body .save-list > li').filter(has=p.locator('.save-item > span:first-child', has_text=re.compile('^' + re.escape(STATE) + '$'))).first
s.click(exact.locator('button.save-item')); expect(p.locator('#load-run')).to_be_visible(timeout=120000)
s.say('confirmation %r rows %s' % (s.text('#load-panel-body .save-state'), device_words(s)))
s.click('#load-run'); s.wait_chip(r'^(Running .*|Loaded \d of \d)$', timeout=180000); p.wait_for_timeout(2000)
s.say('loaded: chip %r ; CLICKS Load + state + red Load = %d (typed %d)' % (s.chip(), s.clicks, s.typed))
got = descriptions(DEVS); s.say('CLI: %s' % {k: v.split()[-1] for k, v in got.items()})
s.check('%s runs on the device' % STATE, all(TAG in v for k, v in got.items() if k == DEVS[0]), got)
s.close_panels(); p.wait_for_timeout(1200)
s.reset_counts(); del s.sent[:]
s.click('#git-save-progress'); p.wait_for_timeout(3500)
s.say('SAVE after the load, chip %r: panel %r' % (s.chip(), s.panel().replace('\n', ' | ')[:380]))
s.say('buttons %s ; requests %s' % (p.locator('#save-panel-body button').evaluate_all("els=>els.map(e=>e.id+':'+e.textContent.trim())"), s.sent))
s.shot('l3-2-first-save-%s' % LAB)
s.check('2 Save opens the first-save view', s.visible('#save-first') or s.visible('#save-first-continue') or 'first save' in s.panel().lower() or 'already holds saves' in s.panel(), s.panel()[:200])
btn = '#save-first-continue' if s.visible('#save-first-continue') else '#save-first'
s.say('pressing %s' % btn); s.click(btn)
s.wait_chip(r'^(1 save to upload|Saved .*)$', timeout=120000); p.wait_for_timeout(1500)
s.say('after the first save: chip %r ; %r ; clicks since Save %d' % (s.chip(), s.text('#save-changes') if s.visible('#save-changes') else s.panel()[:160], s.clicks))
if s.chip().endswith('to upload'):
    expect(p.locator('#save-upload')).to_be_enabled(timeout=30000); s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$', timeout=90000); s.wait_chip('^Saved ')
s.say('uploaded: chip %r ; lab saves in %s ; clicks %d' % (s.chip(), s.prefix(LAB), s.clicks))
github('GitHub')
s.check('2 the first save worked from the header', s.chip().startswith('Saved') and s.prefix(LAB), (s.chip(), s.prefix(LAB)))
s.say('errors %s ; failed %s' % (s.errors, s.failed)); s.no_errors('items 2 and 3 on ' + LAB); print(report(s, 'items 2/3 ' + LAB)); s.finish()
