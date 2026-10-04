import sys, re, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
LAB = sys.argv[1]; DEV = sys.argv[2]
s = Live(); p = s.page
s.open_lab(LAB); s.wait_quiet(LAB)
folder = s.prefix(LAB)
def head(): return vmgit('rev-parse', 'HEAD')[1]
def latest_hash():
    return gh('contents/%s/latest/%s.cfg' % (folder, DEV.split('-')[1]), '.sha')[1]
s.say('A3 part 2 (older save as a checkpoint) on %s' % LAB)
import base64
wait_until = common.wait_until
# 4. in All versions keep an OLDER save as a checkpoint
latest_blob = latest_hash(); files_before = sorted(gh_tree(folder + '/latest/'))
s.say('latest/ %s blob before %s' % (DEV.split('-')[1] + '.cfg', latest_blob[:10]))
s.reset_counts()
s.click('#save-chip'); s.click('#save-all')
expect(p.locator('#save-drawer')).to_be_visible(timeout=15000)
expect(p.locator('#save-drawer-content li').first).to_be_visible(timeout=20000)
heads = p.locator('#save-drawer-content h3').all_inner_texts(); s.say('All versions groups: %s' % heads)
rows = p.locator('#save-drawer-content .save-list > li > button.save-item')
names = rows.evaluate_all("els=>els.map(e=>e.innerText.replace(/\\n/g,' | '))"); s.say('rows: %s' % names[:8])
s.shot('A3-all-versions')
older = 2   # the third row of Your saves: two newer saves exist
s.say('opening the older row #%d: %s' % (older, names[older]))
s.click(rows.nth(older))
expect(p.locator('[data-save-action="checkpoint"]').first).to_be_enabled(timeout=10000)
older_job_commit = None
s.click(p.locator('[data-save-action="checkpoint"]').first)
cp_input = p.locator('#save-checkpoint-name'); expect(cp_input).to_be_visible()
s.say('checkpoint name placeholder %r; "Saved as" %r' % (cp_input.get_attribute('placeholder'), s.text('#save-drawer-content .form-help')))
cp_name = 'l2-older-checkpoint'
s.fill('#save-checkpoint-name', cp_name)
s.click('[data-save-action="checkpoint-keep"]')
p.wait_for_timeout(1500)
s.wait_chip(r'^1 save to upload$', timeout=60000)
s.say('after Keep: chip %s; drawer open %s' % (s.chip(), s.visible('#save-drawer')))
common.wait_until(lambda: any(j.get('checkpoint') == cp_name for j in s.jobs(LAB)), what='the checkpoint job')
cj = [j for j in s.jobs(LAB) if j.get('checkpoint') == cp_name][-1]
s.say('checkpoint job: %s' % trim(cj, ('status', 'target', 'checkpoint', 'note', 'commit', 'changed_files', 'summary'), 900))
s.close_panels(); s.open_chip(); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$'); s.wait_chip('^Saved ')
github('after the older save was kept as a checkpoint')
latest_after = latest_hash(); files_after = sorted(gh_tree(folder + '/latest/'))
s.check('A3 DEFECT L1: latest/ did not change when an OLDER save was kept (device blob)', latest_after == latest_blob, (latest_blob[:10], latest_after[:10]))
s.check('A3 latest/ files unchanged', files_after == files_before)
cp_files = gh_tree('%s/checkpoints/%s/' % (folder, cp_name))
s.check('A3 the checkpoint folder holds the older state', len(cp_files) >= 6, cp_files)
cfg = DEV.split('-')[1] + '.cfg'
cp_desc = gh('contents/%s/checkpoints/%s/%s' % (folder, cp_name, cfg), '.content')[1]
import base64
txt = base64.b64decode(cp_desc.strip('"')).decode(errors='replace')
lines = [l.strip() for l in txt.splitlines() if 'l2-' in l or 'l1-' in l]
latest_txt = base64.b64decode(gh('contents/%s/latest/%s' % (folder, cfg), '.content')[1].strip('"')).decode(errors='replace')
s.say('checkpoint %s description lines: %s' % (cp_name, lines))
s.say('latest %s description lines: %s' % (cfg, [l.strip() for l in latest_txt.splitlines() if 'l2-' in l or 'l1-' in l]))
c = gh('commits?per_page=1', '.[0].sha')[1]
print('commit of the checkpoint upload:'); l1lib.gh_commit_patch(c, r'latest', 6)
s.say('clicks for the older-save checkpoint (chip, All versions, row, Keep as a checkpoint, [name], Keep, [chip, Upload]) = %d, typed %d' % (s.clicks, s.typed))
s.no_errors('A3')
print(report(s, 'A3')); s.finish()
