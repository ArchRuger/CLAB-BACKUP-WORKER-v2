from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={'width':1440,'height':900}).new_page(); errs=[]
    pg.on('console', lambda m: errs.append(m.type+': '+m.text[:200]) if m.type in ('error','warning') else None)
    pg.goto('http://127.0.0.1:8090/static/lab-builder.html#root=/srv/containerlab-node-manager/projects'); pg.wait_for_timeout(2500)
    pg.fill('#builder-new-name','wires'); pg.select_option('#builder-new-starter','pair'); pg.click('#builder-new-create'); pg.wait_for_timeout(5000)
    print('edges',pg.locator('.react-flow__edge').count(), 'edge-ish', pg.evaluate("[...document.querySelectorAll('[class*=edge]')].slice(0,8).map(e=>e.tagName+'.'+e.getAttribute('class'))"))
    print(pg.evaluate("""()=>{const ps=[...document.querySelectorAll('.react-flow__edges path, .react-flow__edge path, svg path[d^=M]')].slice(0,4).map(p=>{const c=getComputedStyle(p);return {cls:p.getAttribute('class'),stroke:c.stroke,width:c.strokeWidth,fill:c.fill,opacity:c.opacity}});return JSON.stringify(ps)}"""))
    print(pg.evaluate("JSON.parse(localStorage.getItem('clab-builder:draft:new:wires')).yaml"))
    print(errs[:5]); b.close()
