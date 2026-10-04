import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign'
s.open_lab(LAB); load_open(s)
s.say('foot buttons ids: %s' % p.locator('#load-panel-body button').evaluate_all("els=>els.map(e=>e.id+'|'+e.textContent.trim().slice(0,40))")[-6:])
s.shot('C6-load-list-capped')
s.click('#load-all'); expect(p.locator('#save-drawer')).to_be_visible(timeout=15000); p.wait_for_timeout(3000)
heads = p.locator('#save-drawer-content h3').all_inner_texts(); s.say('All versions headings: %s' % heads)
rows = p.locator('#save-drawer-content .save-list > li > button.save-item').evaluate_all("els=>els.map(e=>e.innerText.replace(/\\n/g,' | '))"); s.say('rows: %s' % rows)
s.finish()
