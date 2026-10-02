import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={'width':1440,'height':900}).new_page(); errs=[]
    pg.on('console', lambda m: errs.append(m.text[:220]) if m.type=='error' else None); pg.on('pageerror', lambda e: errs.append('PAGEERROR '+str(e)[:220]))
    pg.goto('http://127.0.0.1:8090/static/lab-builder.html#root=/srv/containerlab-node-manager/projects'); pg.wait_for_timeout(3000)
    pg.screenshot(path=sys.argv[1]+'/01-new-dialog.png')
    pg.fill('#builder-new-name','student-lab'); pg.select_option('#builder-new-starter','triangle'); pg.click('#builder-new-create'); pg.wait_for_timeout(5000)
    pg.screenshot(path=sys.argv[1]+'/02-editor.png'); print('nodes',pg.locator('.react-flow__node').count(),'edges',pg.locator('.react-flow__edge').count(),'status',pg.inner_text('#builder-status')); print('errors',errs[:6]); b.close()
