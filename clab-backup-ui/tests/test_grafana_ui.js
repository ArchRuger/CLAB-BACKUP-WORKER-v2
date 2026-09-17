const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
// The Grafana start page: asks the manager for the state, starts Grafana when it is stopped and moves the
// tab to the dashboard on the manager's own host; a failure stays on the page with a retry.
function harness(hash,responses){
 const elements=new Map(),fetches=[],replaced=[];
 const el=id=>{if(!elements.has(id))elements.set(id,{id,textContent:'',hidden:false,href:'',onclick:null});return elements.get(id);};
 const page=vm.createContext({document:{getElementById:el},URLSearchParams,console,
  location:{protocol:'http:',hostname:'10.0.0.5',hash,replace(url){replaced.push(url);}},
  fetch:async(url,options)=>{fetches.push([url,options?.method||'GET',options?.body]);const answer=responses[url+' '+(options?.method||'GET')];
   if(answer instanceof Error)throw answer;return {ok:answer.ok!==false,json:async()=>answer.body};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/grafana.js'),'utf8'),page);
 return {page,el,fetches,replaced,settle:()=>new Promise(resolve=>setImmediate(resolve))};
}
const hash='#path=%2Fd%2Fclab-map-abc%3Fvar-lab%3Dbgp%2Blab%26refresh%3D10s&title=bgp+lab';
test('a running Grafana is opened at once on the manager host without a start request',async()=>{
 const h=harness(hash,{'/api/telemetry/grafana GET':{body:{enabled:true,running:true,port:3000}}});
 await h.settle();
 assert.deepEqual(h.fetches.map(f=>f[1]),['GET']);
 assert.deepEqual(h.replaced,['http://10.0.0.5:3000/d/clab-map-abc?var-lab=bgp+lab&refresh=10s']);
 assert.equal(h.el('grafana-title').textContent,'Network dashboard · bgp lab');assert.equal(h.el('grafana-status').textContent,'The dashboard is ready.');assert.equal(h.el('grafana-headline').hidden,true);
 assert.equal(h.el('grafana-open').href,h.replaced[0]);assert.equal(h.el('grafana-open').hidden,false);assert.equal(h.el('grafana-retry').hidden,true);
});
test('a stopped Grafana is started through the manager, then the port the manager announces is used',async()=>{
 const h=harness(hash,{'/api/telemetry/grafana GET':{body:{enabled:true,running:false,port:3000}},'/api/telemetry/grafana/start POST':{body:{enabled:true,running:true,port:3100}}});
 await h.settle();
 assert.deepEqual(h.fetches.map(f=>[f[1],f[2]]),[['GET',undefined],['POST','{}']],'the POST carries a body: the manager refuses empty writes');
 assert.deepEqual(h.replaced,['http://10.0.0.5:3100/d/clab-map-abc?var-lab=bgp+lab&refresh=10s']);
});
test('a failed start stays on the page with the manager\'s reason and a retry',async()=>{
 const responses={'/api/telemetry/grafana GET':{body:{enabled:true,running:false,port:3000}},'/api/telemetry/grafana/start POST':{ok:false,body:{detail:'The VM operations helper predates on-demand Grafana.'}}};
 const h=harness(hash,responses);
 await h.settle();
 assert.deepEqual(h.replaced,[]);assert.equal(h.el('grafana-status').textContent,'The VM operations helper predates on-demand Grafana.','the manager reason stays verbatim as the Details line');assert.equal(h.el('grafana-headline').textContent,'The network dashboard could not be opened.');
 assert.equal(h.el('grafana-retry').hidden,false);assert.equal(h.el('grafana-open').hidden,true);
 responses['/api/telemetry/grafana/start POST']={body:{enabled:true,running:true,port:3000}};
 await h.el('grafana-retry').onclick();
 assert.equal(h.replaced.length,1);assert.equal(h.el('grafana-retry').hidden,true);
 const missing=harness(hash,{'/api/telemetry/grafana GET':{body:{enabled:false,message:'The Grafana stack is not installed on this manager.'}}});
 await missing.settle();
 assert.equal(missing.fetches.length,1);assert.equal(missing.el('grafana-status').textContent,'The Grafana stack is not installed on this manager.');assert.equal(missing.el('grafana-headline').textContent,'Telemetry is not installed on this VM.');
 const down=harness(hash,{'/api/telemetry/grafana GET':new Error('Failed to fetch')});
 await down.settle();
 assert.equal(down.el('grafana-status').textContent,'Failed to fetch');assert.equal(down.el('grafana-retry').hidden,false);
});
test('only a Grafana dashboard path is taken from the link; anything else opens the overview',()=>{
 const h=harness('',{});
 const origin={protocol:'https:',hostname:'lab.example'};
 assert.equal(h.page.grafanaTarget(new URLSearchParams('path=%2Fd%2Fclab-bgp%3Fvar-lab%3Dx'),origin,3000),'https://lab.example:3000/d/clab-bgp?var-lab=x');
 for(const bad of ['https://evil.example/d/x','//evil.example/d/x','/d/x?redirect=<script>','/api/admin','']){
  assert.equal(h.page.grafanaTarget(new URLSearchParams({path:bad}),origin,3000),'https://lab.example:3000/d/clab-lab-overview',bad);
 }
});
