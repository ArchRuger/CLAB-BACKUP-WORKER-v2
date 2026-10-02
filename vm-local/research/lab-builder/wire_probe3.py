from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1440,'height':900}); pg=ctx.new_page(); errs=[]
    pg.on('console', lambda m: errs.append(m.type+': '+m.text[:300]))
    pg.on('pageerror', lambda e: errs.append('PAGEERROR '+str(e)[:300]))
    pg.goto('http://127.0.0.1:8090/static/lab-builder.html#root=/srv/containerlab-node-manager/projects'); pg.wait_for_timeout(2000)
    pg.fill('#builder-new-name','wires2'); pg.select_option('#builder-new-starter','pair'); pg.click('#builder-new-create'); pg.wait_for_timeout(4000)
    for i in range(2):
        d=json.loads(pg.evaluate("localStorage.getItem('clab-builder:draft:new:wires2')"))
        print('open',i,'nodes',pg.locator('.react-flow__node').count(),'edges',pg.locator('.react-flow__edge').count(),'rev',d['revision']); print(d['yaml']); print(d['annotations'][:600])
        pg.reload(); pg.wait_for_timeout(4000)
    print([e for e in errs if 'error' in e.lower()][:6]); b.close()
