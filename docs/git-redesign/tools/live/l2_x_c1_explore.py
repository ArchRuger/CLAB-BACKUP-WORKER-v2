import sys
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l2lib import *
s = Live(); p = s.page; LAB='git-redesign-b'
s.open_lab(LAB); s.open_chip()
s.click('#save-as-state'); expect(p.locator('#save-drawer')).to_be_visible(timeout=15000); p.wait_for_timeout(2500)
s.say('title %r' % s.text('#save-drawer-title'))
s.say('text: %r' % s.text('#save-drawer')[:900].replace('\n',' | '))
s.say('controls: %s' % p.evaluate("[...document.querySelectorAll('#save-drawer input, #save-drawer button, #save-drawer select')].filter(e=>e.offsetParent).map(e=>e.id+'|'+(e.getAttribute('data-save-action')||e.getAttribute('data-folder-action')||e.getAttribute('data-state-name')||'')+'|'+(e.value||e.textContent||'').trim().slice(0,40))"))
s.shot('C1-state-drawer-explore')
s.finish()
