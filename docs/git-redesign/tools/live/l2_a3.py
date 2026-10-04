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
s.say('A3 on %s (folder %s); chip %s; VM HEAD %s' % (LAB, folder, s.chip(), head()[:8]))
# 1. Save, Not now, then Upload later from the chip
set_description(DEV, 'l2-a3')
s.reset_counts()
s.click('#git-save-progress'); s.wait_chip(r'^1 save to upload$', timeout=60000)
expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.click('#save-not-now')
s.check('A3 Not now closes the panel; the chip reads 1 save to upload', not s.visible('#save-panel') and s.chip() == '1 save to upload', s.chip())
s.check('A3 Not now: nothing on GitHub yet', gh('commits?per_page=1', '.[0].sha')[1] != head(), (gh('commits?per_page=1', '.[0].sha')[1][:8], head()[:8]))
github('after Not now (the new commit is only on the VM)')
s.say('VM HEAD now %s: %s' % (head()[:8], vmgit('log', '--oneline', '-1')[1]))
s.click('#save-chip'); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.say('panel from the chip: %r / %r' % (s.text('#save-panel-title'), s.text('#save-changes')))
s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$'); s.wait_chip('^Saved ')
s.say('uploaded later from the chip: %s; clicks (Save, Not now, chip, Upload) = %d' % (s.chip(), s.clicks))
github('after the later upload')
# 2. an unchanged save
before = head(); s.reset_counts()
p.wait_for_timeout(5200)
s.click('#git-save-progress')
s.wait_toast(r'^Nothing changed since your last save\.$', timeout=60000)
s.wait_chip('^Saved ')
s.check('A3 unchanged save: the toast, no commit, the panel stays closed', head() == before and not s.visible('#save-panel'), (head()[:8], before[:8]))
s.say('unchanged save: toast shown, VM HEAD unchanged %s; chip %s' % (head()[:8], s.chip()))
# 3. name field and Keep as a checkpoint in the panel of the finished save
p.wait_for_timeout(5200)
set_description(DEV, 'l2-a3-named')
s.click('#git-save-progress'); s.wait_chip(r'^1 save to upload$', timeout=60000); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$'); s.wait_chip('^Saved ')
p.wait_for_timeout(5200)
s.reset_counts()
s.click('#save-chip')
name = p.locator('#save-name'); expect(name).to_be_visible()
s.say('automatic name in the field: %r' % name.input_value())
name.fill('l2 named save'); name.press('Enter')
wait_until = common.wait_until
wait_until(lambda: any(j.get('note') == 'l2 named save' for j in s.jobs(LAB)), what='rename')
job = [j for j in s.jobs(LAB) if j.get('note') == 'l2 named save'][-1]
s.check('A3 rename: manager shows it, the GitHub commit subject is unchanged', job.get('note_auto') is False and gh('commits/%s' % job['commit'], '.commit.message | split("\\n")[0]')[1] != 'l2 named save', gh('commits/%s' % job['commit'], '.commit.message | split("\\n")[0]')[1])
s.click('#save-keep')
s.wait_chip(r'^1 save to upload$', timeout=60000); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
s.say('Keep as a checkpoint: sentence %r; clicks %d' % (s.text('#save-changes'), s.clicks))
latest_before = latest_hash()
s.click('#save-upload'); s.wait_toast(r'^Uploaded to github\.com\.$'); s.wait_chip('^Saved ')
github('after the checkpoint upload')
cps = sorted({'/'.join(x.split('/')[:3]) for x in gh_tree(folder + '/checkpoints/')})
s.say('checkpoint folders on GitHub: %s' % cps)
s.check('A3 the checkpoint folder exists on GitHub', len(cps) >= 1, cps)
s.check('A3 latest/ still holds the device file of that save (same blob)', latest_hash() == latest_before, (latest_hash(), latest_before))
# 4. in All versions keep an OLDER save as a checkpoint
p.wait_for_timeout(5200)
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
older = None
for i, n in enumerate(names):
    if 'l2' in n.lower() or 'changed' in n.lower():
        older = i if i >= 2 else older
older = older if older is not None else 2
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
