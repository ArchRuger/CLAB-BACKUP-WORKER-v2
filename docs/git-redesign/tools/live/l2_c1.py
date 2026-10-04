import sys, re
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB = sys.argv[1]; NAMES = sys.argv[2].split(',')          # e.g. start,broken,final
DEVS = sys.argv[3].split(',') if len(sys.argv) > 3 and sys.argv[3] else []   # l1lib device keys changed before each state after the first
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
s.say('C1 on %s: states %s; lab saves in %s' % (LAB, NAMES, s.prefix(LAB)))
results = []
for i, name in enumerate(NAMES):
    if i > 0 or (len(sys.argv) > 4 and sys.argv[4] == 'change-first'):
        tag = 'l2-c1-%s' % name
        for d in DEVS: set_description(d, tag)
        s.say('changed every device (%s) to %s' % (DEVS, tag))
    s.close_panels(); p.wait_for_timeout(5200)
    s.reset_counts()
    s.click('#save-chip'); s.click('#save-as-state')
    expect(p.locator('#state-name')).to_be_visible(timeout=15000)
    s.wait_js("!!document.querySelector('#folder-repo')&&!!document.querySelector('#folder-repo').value&&!/still loading/.test(document.getElementById('save-drawer').textContent)", what='the folders of the drawer')
    s.click(p.locator('#save-drawer button').filter(has_text=re.compile('^%s$' % name)).first)
    p.wait_for_timeout(1500)
    s.say('[%s] chosen name %r; folder field %r; sentence %r' % (name, p.locator('#state-name').input_value(), p.locator('#folder-path').input_value(), s.text('#save-drawer').split('The state is saved in')[-1][:160].replace('\n', ' | ')))
    s.shot('C1-state-drawer-%s' % name)
    known = {j['id'] for j in s.jobs(LAB)}
    if p.locator('#save-drawer button', has_text='Replace it').count():
        s.say('[%s] the page asks: %r buttons %s' % (name, s.text('#save-drawer').split('Put it somewhere else')[-1][:200].replace('\n', ' | '), p.locator('#save-drawer button').all_inner_texts()))
        s.shot('C1-question-%s' % name)
        s.click(p.locator('#save-drawer button', has_text='Replace it'))
    else:
        s.click(p.locator('#save-drawer button', has_text='Save state'))
    p.wait_for_timeout(2500)
    if s.visible('#save-drawer') and p.locator('#save-drawer button', has_text='Replace it').count():
        s.say('[%s] the page asks: %r buttons %s' % (name, s.text('#save-drawer').split('Folder')[-1][:240].replace('\n', ' | '), p.locator('#save-drawer button').all_inner_texts()))
        s.shot('C1-question-%s' % name)
        s.click(p.locator('#save-drawer button', has_text='Replace it'))
    common.wait_until(lambda: any(j['id'] not in known and j.get('kind') == 'state' and j['status'] in ('review_pending', 'committed', 'synced') for j in s.jobs(LAB)), timeout=120, what='the state save')
    s.wait_chip(r'^\d saves? to upload$', timeout=60000)
    p.wait_for_timeout(1000)
    s.say('[%s] clicks: %d, typed %d (chip, Save as a lab state…, name, Save state); chip %r; panel title %r sentence %r' % (name, s.clicks, s.typed, s.chip(), s.text('#save-panel-title') if s.visible('#save-panel') else None, s.text('#save-changes') if s.visible('#save-changes') else ''))
    results.append((name, s.clicks, s.typed))
# one Upload sends all waiting states
s.open_chip() if not s.visible('#save-panel') else None
expect(p.locator('#save-upload')).to_be_enabled(timeout=30000)
t0 = time.time()
while 'Checking what this upload sends' in s.panel() and time.time() - t0 < 90: p.wait_for_timeout(500)
s.say('Upload enabled; the panel said "Checking what this upload sends…" for %.1f s more; panel before Upload: %r' % (time.time() - t0, s.panel().replace('\n', ' | ')[:200]))
s.reset_counts(); s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$', timeout=90000); s.wait_chip('^Saved ')
s.say('uploaded with %d click; chip %r' % (s.clicks, s.chip()))
for j in s.jobs(LAB)[-len(NAMES):]: s.say('state job: %s' % trim(j, ('status', 'kind', 'note', 'pushed', 'commit', 'destination'), 400))
github('after the states')
folder = s.prefix(LAB)
cands = sorted({'/'.join(x.split('/')[:-1]) for x in gh_tree('') if x.endswith('manifest.json') and any(x.startswith(f) for f in ['%s/%s/' % (folder, n) for n in NAMES])})
s.say('state folders on GitHub: %s' % cands)
import base64, json
for c in cands:
    m = json.loads(base64.b64decode(gh('contents/%s/manifest.json' % c, '.content')[1].strip('"').replace('\\n', '')))
    s.say('  %s manifest state=%r node_names=%d' % (c, m.get('state'), len(m.get('node_names', []))))
# Load lists them
s.close_panels(); s.click('#load-button'); expect(p.locator('#load-panel-body .save-list').first).to_be_visible(timeout=20000)
heads = p.locator('#load-panel-body h3.save-heading').all_inner_texts()
states_list = p.locator('#load-panel-body .save-list').last.locator('li .save-item > span:first-child').all_inner_texts()
s.say('Load panel headings %s; lab states: %s' % (heads, [x.split('\n')[0] for x in states_list]))
s.shot('C1-load-list')
s.close_panels()
s.say('failed requests with bodies: %s' % s.failed)
s.no_errors('C1'); print(report(s, 'C1')); s.finish()
