from playwright.sync_api import sync_playwright
JS="""()=>{const g=document.querySelector('.react-flow__edge'); const out=[...g.querySelectorAll('path')].map(p=>{const c=getComputedStyle(p);return {cls:p.getAttribute('class'),stroke:c.stroke,width:c.strokeWidth,opacity:c.opacity,style:p.getAttribute('style')}}); const svg=g.closest('svg'),s=getComputedStyle(svg); return JSON.stringify({out,svg:{w:s.width,h:s.height,overflow:s.overflow,pos:s.position,display:s.display}})}"""
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={'width':1440,'height':900}).new_page()
    pg.goto('http://127.0.0.1:8090/static/lab-builder.html#root=/srv/containerlab-node-manager/projects'); pg.wait_for_timeout(2000)
    pg.fill('#builder-new-name','wires4'); pg.select_option('#builder-new-starter','pair'); pg.click('#builder-new-create'); pg.wait_for_selector('.react-flow__edge', state='attached', timeout=15000); pg.wait_for_timeout(1500)
    print('MANAGER ', pg.evaluate(JS))
    pg2=b.new_context(viewport={'width':1440,'height':900}).new_page(); pg2.goto('http://127.0.0.1:8766/lab-builder.html?draft=walk1&mode=clean'); pg2.wait_for_selector('.react-flow__edge', state='attached', timeout=15000); pg2.wait_for_timeout(1500)
    print('PROTOTYPE', pg2.evaluate(JS)); b.close()
