import time
from playwright.sync_api import sync_playwright
LAB='rev-'+time.strftime('%H%M%S')
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={'width':1440,'height':900}).new_page(); log=[]
    pg.on('console', lambda m: log.append(m.type+': '+m.text[:200])); pg.on('pageerror', lambda e: log.append('PAGEERROR '+str(e)[:300]))
    pg.on('response', lambda r: log.append(f'{r.status} {r.request.method} {r.url[-40:]}') if '/api/operations/' in r.url and r.request.method=='POST' else None)
    pg.goto('http://127.0.0.1:8090/static/lab-builder.html#root=/srv/containerlab-node-manager/projects'); pg.wait_for_selector('#builder-new-name')
    pg.fill('#builder-new-name',LAB); pg.select_option('#builder-new-starter','pair'); pg.click('#builder-new-create'); pg.wait_for_selector('.react-flow__node'); pg.wait_for_timeout(1500)
    pg.click('#builder-save'); pg.wait_for_selector('#op-confirm'); pg.click('#op-confirm'); pg.wait_for_selector('#op-open-published', timeout=30000); pg.click('#operation-output [data-op-close]')
    bx=pg.get_by_text('Linux host', exact=True).bounding_box(); pg.mouse.move(bx['x']+10,bx['y']+8); pg.mouse.down(); pg.mouse.move(640,560,steps=12); pg.mouse.up(); pg.wait_for_timeout(900)
    pg.click('#builder-save'); pg.wait_for_selector('#op-confirm'); log.append('--- clicking confirm'); pg.click('#op-confirm'); pg.wait_for_timeout(6000)
    print('review error:', pg.locator('#operation-review .form-error').inner_text() if pg.locator('#operation-review').count() else 'n/a')
    print('output open:', pg.locator('#operation-output').evaluate('d=>d.open') if pg.locator('#operation-output').count() else None, '| banner:', pg.inner_text('#op-job-banner') if pg.locator('#op-job-banner').count() else '')
    print('result html:', pg.inner_html('#op-job-result')[:300] if pg.locator('#op-job-result').count() else '')
    print('\n'.join(log[-12:])); b.close()
