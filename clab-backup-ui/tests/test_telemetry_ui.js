// Telemetry view, SVG charts, map overlay and the menu/tab wiring into the existing UI.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const read=name=>fs.readFileSync(path.join(__dirname,'../app/static/'+name),'utf8');
function element(id=''){return {id,dataset:{},classList:{toggle(){},add(){},remove(){},contains(){return false;}},value:'',innerHTML:'',textContent:'',className:'',title:'',hidden:false,open:false,disabled:false,style:{},listeners:{},children:[],
 addEventListener(k,fn){this.listeners[k]=fn;},removeAttribute(){},setAttribute(k,v){this['attr_'+k]=v;},getAttribute(k){return this['attr_'+k]??null;},querySelector(){return null;},querySelectorAll(){return [];},showModal(){this.open=true;},close(){this.open=false;},focus(){},closest(){return null;},contains(){return false;},reset(){},click(){},appendChild(){},remove(){}};}
function harness(state){
 const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
 const calls=[];const map=element('topology-map');
 const context=vm.createContext({$,esc,activeId:'lab',tab:'telemetry',state:{labs:[{id:'lab',name:'demo',nodes:[{name:'clab-demo-r1',platform:'arista_ceos'},{name:'clab-demo-r2',platform:'cisco_xrv9k'}]}],...state},
  current(){return context.state.labs[0];},api:async url=>{calls.push(url);return {json:async()=>context.responses[url]||context.responses.default};},
  json:async(url,method,data)=>{calls.push({url,method,data});return context.responses[url]||context.responses.default;},
  notify(){},showTab(name){context.tab=name;calls.push('tab:'+name);},opDialog(id,title,body){const d=$(id);d.innerHTML=body;return d;},opTask:async(d,fn)=>fn(),map,nodeMenu:element('node-context-menu'),closeNodeMenu(){calls.push('closeNodeMenu');},contextLab:'',contextNode:null,captureActionAttrs:()=>'',openLinkCapture(el){calls.push('capture:'+el.dataset.captureEndpoints);},
  window:{innerWidth:1200,innerHeight:800},confirm:()=>true,console,Date,Number,Math,JSON,URLSearchParams,setTimeout(){},responses:{default:{}}});
 vm.runInContext(read('telemetry-charts.js'),context);vm.runInContext(read('telemetry.js'),context);
 return {context,$,calls,map};
}
const now=Date.now()/1000;
function payload(overrides={}){
 return {lab_id:'lab',generated_at:new Date().toISOString(),enabled:true,unavailable:'',linked:true,method:'gNMI dial-in: counters sampled every 10 s',sample_interval:10,stale_after:45,windows:[300,900,3600],
  settings:{auto:true,decided:true,profile_id:'',profile_label:''},password_profiles:[{id:'p',label:'Ops',platform:'arista_ceos'}],
  summary:{status:'partial',total:2,streaming:1,waiting:1,failed:0,stale:0,configuring:0,connecting:0,unsupported:0,disabled:0},
  nodes:[{name:'clab-demo-r1',short_name:'r1',platform:'arista_ceos',label:'EOS',supported:true,state:'streaming',message:'Usable samples are arriving.',endpoint:'172.20.20.2:6030',transport:'plaintext',method:'gNMI dial-in: counters sampled every 10 s',groups:{interfaces:{status:'streaming',message:'ok'},bgp:{status:'unsupported',message:'The node does not advertise the OpenConfig model for this group.'}},applied:2,last_sample:now-3,fresh:true,samples:12,dropped:0,overflow:0,
    interfaces:[{name:'Ethernet1',oper:'UP',admin:'UP',at:now-3,fresh:true,method:'gnmi-sample-10s',resets:0,totals:{'in-errors':0,'out-errors':0,'in-discards':3,'out-discards':0},rx_bps:1200000,tx_bps:800,rx_pps:120,tx_pps:null,rx_errors:0,tx_errors:0,rx_discards:0,tx_discards:0,role:'physical',wired:true,peer:'clab-demo-r2',peer_interface:'eth1',drawn:'eth1'},
                {name:'Management0',oper:'UP',admin:'UP',at:now-70,fresh:false,method:'gnmi-sample-10s',resets:1,totals:{},rx_bps:null,tx_bps:null,rx_pps:null,tx_pps:null,rx_errors:null,tx_errors:null,rx_discards:null,tx_discards:null,role:'management',wired:false,peer:'',peer_interface:'',drawn:''}],peers:[]},
   {name:'clab-demo-r2',short_name:'r2',platform:'cisco_xrv9k',label:'IOS-XR',supported:true,state:'waiting',message:'Waiting for the NOS: the automatic SSH login and show version check has not answered yet.',endpoint:'',transport:'',method:'',groups:{},applied:0,last_sample:0,fresh:false,samples:0,dropped:0,overflow:0,interfaces:[],peers:[]}],
  links:[{index:0,status:'up-partial',mismatch:false,ends:[{node:'clab-demo-r1',label:'r1',interface:'eth1',nos_interface:'Ethernet1',state:'up',rx_bps:1200000,tx_bps:800,oper:'UP',at:now-3},{node:'clab-demo-r2',label:'r2',interface:'eth1',nos_interface:'',state:'unknown',rx_bps:null,tx_bps:null,oper:'',at:0}]}],...overrides};
}

test('charts scale nicely, break lines at gaps and say when a window is empty',()=>{
 const c=vm.createContext({esc});vm.runInContext(read('telemetry-charts.js'),c);
 assert.equal(c.telemetryFormatRate(1250000,'bps'),'1.25 Mb/s');assert.equal(c.telemetryFormatRate(950,'pps'),'950 pps');assert.equal(c.telemetryFormatRate(0.025,'/s'),'0.025 /s');assert.equal(c.telemetryFormatRate(20000,'bps'),'20 kb/s');assert.equal(c.telemetryFormatRate(2.5,'pps'),'2.5 pps');assert.equal(c.telemetryFormatRate(null,'bps'),'n/a');assert.equal(c.telemetryFormatRate(12345678900,'bps'),'12.3 Gb/s');
 assert.equal(c.telemetryNice(0),1);assert.equal(c.telemetryNice(1300),2000);assert.equal(c.telemetryNice(4999),5000);assert.equal(c.telemetryNice(7000),10000);
 assert.equal(c.telemetryFormatCount(1234567),(1234567).toLocaleString());assert.match(c.telemetryAge(now-5,now),/^5 s ago$/);assert.equal(c.telemetryAge(0),'never');
 const points=[{t:now-40,rx_bps:100,tx_bps:50},{t:now-30,rx_bps:200,tx_bps:60},{t:now-20},{t:now-10,rx_bps:300,tx_bps:70}];
 const svg=c.telemetryChart({points,series:[{key:'rx_bps',label:'RX',color:'#111'},{key:'tx_bps',label:'TX',color:'#222'}],window:300,now,unit:'bps',title:'Bit <rate>'});
 assert.match(svg,/aria-label="Bit &lt;rate&gt;"/);assert.doesNotMatch(svg,/<rate>/);
 assert.equal((svg.match(/<polyline/g)||[]).length,2,'the gap splits one series into a line and a lone point');assert.equal((svg.match(/<circle class="tele-point"/g)||[]).length,2);
 assert.match(svg,/RX · 300 b\/s/);assert.match(svg,/TX · 70 b\/s/);assert.doesNotMatch(svg,/NaN|Infinity/);
 const empty=c.telemetryChart({points:[{t:now-4000,rx_bps:5}],series:[{key:'rx_bps',label:'RX',color:'#111'}],window:300,now});
 assert.match(empty,/No samples in this window yet/);assert.doesNotMatch(empty,/<polyline/);
});

test('link classes and titles describe both ends without guessing',()=>{
 const {context}=harness();const link=payload().links[0];
 assert.equal(context.telemetryLinkClass(link),'tele-up-partial');assert.equal(context.telemetryLinkClass({status:'down',mismatch:true}),'tele-down tele-mismatch');assert.equal(context.telemetryLinkClass(undefined),'tele-unknown');
 const title=context.telemetryLinkTitle(link);
 assert.match(title,/observed end/);assert.match(title,/r1:eth1 \(Ethernet1\) UP · RX 1.2 Mb\/s · TX 800 b\/s/);assert.match(title,/r2:eth1 no data/);
 assert.match(context.telemetryLinkTitle({status:'down',mismatch:true,ends:[]}),/two ends disagree/);
});

test('the view renders streaming, waiting, unsupported and undecided states from real payload shapes',()=>{
 const h=harness();h.context.teleState.data=payload();h.context.renderTelemetryView();
 assert.match(h.$('telemetry-banner').innerHTML,/Partially streaming · 2 supported nodes · 1 streaming · 1 waiting/);assert.equal(h.$('telemetry-banner').className,'tele-banner partial');
 assert.match(h.$('telemetry-nodes').innerHTML,/data-tele-node="clab-demo-r1"/);assert.match(h.$('telemetry-nodes').innerHTML,/tele-node active/);assert.match(h.$('telemetry-nodes').innerHTML,/Waiting for the NOS/);
 assert.equal(h.context.teleState.node,'clab-demo-r1','the streaming node is selected first');assert.equal(h.context.teleState.interface,'Ethernet1','the wired port is charted first');
 const detail=h.$('telemetry-detail').innerHTML;
 assert.match(detail,/gNMI 172.20.20.2:6030 · plain text/);assert.match(detail,/2 configuration lines added by the manager/);assert.match(detail,/BGP: unsupported/);assert.match(detail,/BGP telemetry is unavailable on this node/);
 assert.match(detail,/data-tele-interface="Ethernet1"/);assert.match(detail,/clab-demo-r2:eth1/);assert.match(detail,/1.2 Mb\/s/);assert.match(detail,/<td>n\/a<\/td>/,'unavailable packet rate is shown as n\/a, never as zero');
 assert.match(detail,/Management0/);assert.match(detail,/· stale · 1 reset/);assert.match(detail,/not measured end-to-end loss/);
 assert.match(h.$('telemetry-charts').innerHTML,/Select an interface row|Ethernet1 · last 5 min/);
 h.context.teleState.node='clab-demo-r2';h.context.renderTelemetryView();
 assert.match(h.$('telemetry-detail').innerHTML,/No telemetry yet/);assert.match(h.$('telemetry-detail').innerHTML,/Waiting for the NOS/);assert.doesNotMatch(h.$('telemetry-detail').innerHTML,/Retry now/);
 const failed=payload();failed.nodes[1].state='failed';failed.nodes[1].message='The gNMI port did not answer. Next attempt in 30 s.';h.context.teleState.data=failed;h.context.renderTelemetryView();
 assert.match(h.$('telemetry-detail').innerHTML,/data-tele-retry="clab-demo-r2"/);assert.match(h.$('telemetry-detail').innerHTML,/Next attempt in 30 s/);
 const unsupported=payload();unsupported.nodes[1]={...unsupported.nodes[1],state:'unsupported',supported:false,label:'',message:'No telemetry adapter for this node kind; supported kinds: cEOS, XRv9k, cJunosEvolved.'};h.context.teleState.data=unsupported;h.context.renderTelemetryView();
 assert.match(h.$('telemetry-detail').innerHTML,/No telemetry adapter for this kind/);
 const undecided=payload({settings:{auto:false,decided:false,profile_id:'',profile_label:''},summary:{status:'disabled',total:0}});h.context.teleState.data=undecided;h.context.renderTelemetryView();
 assert.match(h.$('telemetry-banner').innerHTML,/not enabled for this lab yet/);assert.match(h.$('telemetry-banner').innerHTML,/id="telemetry-enable"/);assert.match(h.$('telemetry-banner').innerHTML,/configure the gNMI service on supported nodes/);
 const off=payload({settings:{auto:false,decided:true,profile_id:'',profile_label:''},summary:{status:'disabled',total:0}});h.context.teleState.data=off;h.context.renderTelemetryView();
 assert.match(h.$('telemetry-banner').innerHTML,/Automatic telemetry is off/);assert.doesNotMatch(h.$('telemetry-banner').innerHTML,/telemetry-enable/);
 const unavailable=payload({enabled:false,unavailable:'The gNMI client library (pygnmi) is not installed in this image; rebuild the manager.'});h.context.teleState.data=unavailable;h.context.renderTelemetryView();
 assert.match(h.$('telemetry-banner').innerHTML,/pygnmi/);
 const unlinked=payload({linked:false});h.context.teleState.data=unlinked;h.context.renderTelemetryView();assert.match(h.$('telemetry-banner').innerHTML,/linked to a VM deployment/);
});

test('settings save through the API and enabling from the banner needs no second confirmation',async()=>{
 const h=harness();h.context.teleState.data=payload({settings:{auto:false,decided:false,profile_id:'',profile_label:''}});h.context.responses['/labs/lab/telemetry/settings']=payload();
 h.context.renderTelemetryView();h.$('telemetry-enable').onclick();await new Promise(r=>setImmediate(r));
 const call=h.calls.find(c=>c?.url==='/labs/lab/telemetry/settings');assert.equal(JSON.stringify(call.data),JSON.stringify({auto:true,profile_id:''}));assert.equal(call.method,'PUT');
 assert.match(h.$('telemetry-banner').innerHTML,/Partially streaming/);
 h.context.openTelemetrySettings();const dialog=h.$('telemetry-settings-dialog');
 assert.match(dialog.innerHTML,/id="tele-profile"/);assert.match(dialog.innerHTML,/Ops · arista_ceos/);assert.match(dialog.innerHTML,/never saves the whole running configuration/);assert.match(dialog.innerHTML,/id="tele-remove" disabled/);
 h.$('tele-auto').checked=false;h.$('tele-profile').value='p';await h.$('tele-save').onclick();
 const saved=h.calls.filter(c=>c?.url==='/labs/lab/telemetry/settings').pop();assert.equal(JSON.stringify(saved.data),JSON.stringify({auto:false,profile_id:'p'}));
});

test('the map overlay colours links per end state, marks nodes and updates the legend',()=>{
 const h=harness();h.context.tab='topology';
 const wire=element();wire.dataset.linkIndex='0';const title=element();wire.querySelector=()=>title;
 const device=element();device.dataset.mapNode='clab-demo-r1';device.attr_class='map-device';const deviceTitle=element();device.querySelector=sel=>sel==='title'?deviceTitle:null;
 const other=element();other.dataset.mapNode='clab-demo-r2';other.attr_class='map-device';other.querySelector=()=>null;
 h.map.querySelectorAll=sel=>sel==='[data-link-index]'?[wire]:[device,other];
 h.context.teleState.data=payload();h.context.applyTelemetryOverlay();
 assert.equal(wire.attr_class,'topology-wire tele-up-partial');assert.match(title.textContent,/observed end/);
 assert.equal(device.attr_class,'map-device tele-streaming');assert.equal(other.attr_class,'map-device tele-waiting');assert.match(deviceTitle.textContent,/Streaming: Usable samples/);
 assert.match(h.$('map-live-legend').innerHTML,/Live link state/);
 h.context.teleState.data=payload({settings:{auto:false,decided:true,profile_id:'',profile_label:''}});h.context.applyTelemetryOverlay();
 assert.equal(wire.attr_class,'topology-wire ','overlay classes are removed when telemetry is off');assert.equal(device.attr_class,'map-device');assert.match(h.$('map-live-legend').innerHTML,/not live status/);
});

test('polling is scoped to the telemetry and topology tabs and to the selected lab',async()=>{
 const h=harness();h.context.responses['/labs/lab/telemetry']=payload();h.context.responses['/labs/lab/telemetry/series?node=clab-demo-r1&interface=Ethernet1&window=300']={node:'clab-demo-r1',interface:'Ethernet1',window:300,interval:10,points:[{t:now-10,rx_bps:5,tx_bps:6}]};
 h.context.tab='inventory';await h.context.refreshTelemetry();assert.equal(h.calls.length,0);
 h.context.tab='telemetry';await h.context.refreshTelemetry();
 assert.ok(h.calls.includes('/labs/lab/telemetry'));assert.ok(h.calls.some(c=>String(c).startsWith('/labs/lab/telemetry/series?node=clab-demo-r1&interface=Ethernet1&window=300')));
 assert.match(h.$('telemetry-charts').innerHTML,/Ethernet1 · last 5 min · 1 samples/);assert.match(h.$('telemetry-charts').innerHTML,/RX · 5 b\/s/);
 const before=h.calls.length;await h.context.refreshTelemetry();assert.equal(h.calls.length,before,'no second fetch within the poll interval');
 h.context.openTelemetry('clab-demo-r2','GigabitEthernet0/0/0/0');assert.ok(h.calls.includes('tab:telemetry'));assert.equal(h.context.teleState.node,'clab-demo-r2');
});

test('Grafana links appear only when the manager announces the stack and carry the selection',()=>{
 const h=harness();h.context.location={protocol:'http:',hostname:'lab-vm'};
 h.context.teleState.data=payload();h.context.renderTelemetryView();
 assert.equal(h.$('telemetry-grafana').hidden,true);assert.doesNotMatch(h.$('telemetry-detail').innerHTML,/Grafana/);
 h.context.teleState.data=payload({grafana:{enabled:true,port:3100,prometheus_port:9090},lab_name:'de mo'});h.context.renderTelemetryView();
 assert.equal(h.$('telemetry-grafana').hidden,false);assert.equal(h.$('telemetry-grafana').href,'http://lab-vm:3100/d/clab-lab-overview?var-lab=de+mo&refresh=10s');
 assert.match(h.$('telemetry-detail').innerHTML,/href="http:\/\/lab-vm:3100\/d\/clab-interface\?var-lab=de\+mo&amp;var-node=r1&amp;var-interface=Ethernet1&amp;refresh=10s" target="_blank" rel="noopener">Grafana/);
 assert.equal(h.context.telemetryGrafanaUrl({grafana:{enabled:false}},'clab-bgp'),'');
});

test('the right-click link menu offers capture and per-end telemetry',()=>{
 const h=harness();h.context.teleState.data=payload();
 const wire=element();wire.dataset.captureEndpoints=JSON.stringify([{node:'clab-demo-r1',label:'r1',interface:'eth1'},{node:'clab-demo-r2',label:'r2',interface:'eth1'}]);
 h.context.openLinkMenu(wire,20,30);const menu=h.context.nodeMenu;
 assert.equal(menu.hidden,false);assert.match(menu.innerHTML,/data-link-capture="1"/);assert.match(menu.innerHTML,/Telemetry r1:eth1/);assert.match(menu.innerHTML,/Telemetry r2:eth1/);
 const button=element();button.dataset.linkTelemetry='0';button.closest=()=>button;
 menu.onclick({target:button});assert.equal(h.context.teleState.node,'clab-demo-r1');assert.equal(h.context.teleState.interface,'Ethernet1','the NOS name of the wired port is preselected');
 h.context.openLinkMenu(wire,20,30);const capture=element();capture.dataset.linkCapture='1';capture.closest=()=>capture;menu.onclick({target:capture});
 assert.ok(h.calls.some(c=>String(c).startsWith('capture:')));
});

test('the map renderer exposes link indexes and a telemetry dot only for matched nodes',()=>{
 const c=vm.createContext({esc});vm.runInContext(read('topology-render.js'),c);
 const nodes=new Map([['a',{id:'a',label:'a',x:0,y:0,inventory_name:'n1'}],['b',{id:'b',label:'b',x:100,y:0,inventory_name:'n2'}]]);
 assert.match(c.topologyLink([{node:'a',interface:'eth1'},{node:'b',interface:'eth1'}],nodes,7,{}),/data-link-index="7"/);
 const same=new Map([['a',{label:'a',x:0,y:0}],['b',{label:'b',x:0,y:0}]]);assert.match(c.topologyLink([{node:'a',interface:'eth1'},{node:'b',interface:'eth1'}],same,3,{}),/data-link-index="3"/);
 assert.match(c.topologyNode({id:'R1',inventory_name:'clab-lab-R1',label:'R1',x:0,y:0}),/class="tele-dot"/);assert.doesNotMatch(c.topologyNode({id:'R1',label:'R1',x:0,y:0}),/tele-dot/);
});

test('the node menu, details drawer and tabs reach the telemetry view',()=>{
 const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
 const c=vm.createContext({$,esc,activeId:'lab',current:()=>({name:'demo',nodes:[{name:'r1',short_name:'r1',address:'10.0.0.1',port:22,ssh_ready:true,readiness:'Ready'}]}),busy:()=>false,openDetails(){},handleNodeAction(){},api:async()=>({json:async()=>null}),notify(){},withForm(){},attachmentName(){},URL:{createObjectURL(){},revokeObjectURL(){}},FormData:class{},
  document:{addEventListener(){},activeElement:null,createElement:()=>element(),querySelectorAll(){return [];}},window:{addEventListener(){},innerWidth:1000,innerHeight:800},JSON});
 vm.runInContext(read('topology.js'),c);
 const target=element();target.dataset.mapNode='r1';c.openNodeMenu(target,10,10);
 const menu=$('node-context-menu');assert.match(menu.innerHTML,/data-telemetry="r1"/);assert.match(menu.innerHTML,/View telemetry/);assert.match(menu.innerHTML,/data-terminal="r1"/);assert.match(menu.innerHTML,/data-backup="r1"/);assert.match(menu.innerHTML,/data-capture="r1"/);
 const app=new Map(),$$=id=>{if(!app.has(id))app.set(id,element(id));return app.get(id);};const opened=[];
 const a=vm.createContext({document:{getElementById:$$,querySelectorAll(){return [];},createElement:()=>element(),body:element()},sessionStorage:{getItem(){return null;},setItem(){}},setTimeout:()=>0,clearTimeout(){},setInterval(){},URL:{},URLSearchParams,Blob,console,openTelemetry(n){opened.push(n);}});
 vm.runInContext(read('app.js'),a);a.fetch=async()=>({ok:true,json:async()=>({labs:[],jobs:[],platforms:{}}),headers:{get:()=>''}});
 assert.match(a.nodeActions({name:'r1'},true),/data-telemetry="r1">Telemetry</);assert.doesNotMatch(a.nodeActions({name:'r1'}),/data-telemetry/,'the compact row keeps its existing actions');
 a.showTab('telemetry');assert.equal($$('telemetry-view').hidden,false);assert.equal($$('topology-view').hidden,true);assert.equal($$('inventory-view').hidden,true);
 a.showTab('topology');assert.equal($$('telemetry-view').hidden,true);assert.equal($$('topology-view').hidden,false);
 const button=element();button.dataset.telemetry='r1';a.handleNodeAction({target:{closest:()=>button}});assert.deepEqual(opened,['r1']);
});

test('a right-click on a wired link opens the shared menu when it exists and capture otherwise',()=>{
 const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};const calls=[];
 const c=vm.createContext({$,esc,URLSearchParams,crypto:require('node:crypto').webcrypto,Uint8Array,confirm:()=>true,activeId:'lab',current:()=>({name:'demo'}),map:$('map'),closeNodeMenu(){calls.push('close');},notify(){},clearTimeout(){},setTimeout(){},api:async()=>({json:async()=>({enabled:true})}),json:async()=>({})});
 vm.runInContext(read('capture.js'),c);
 const wire=element();wire.dataset.captureEndpoints='[]';const event={target:{closest:()=>wire},preventDefault(){},clientX:5,clientY:6};
 c.openLinkMenu=(el,x,y)=>calls.push(['menu',x,y]);$('map').listeners.contextmenu(event);assert.deepEqual(calls,['close',['menu',5,6]]);
 delete c.openLinkMenu;calls.length=0;c.openCapture=()=>calls.push('capture');$('map').listeners.contextmenu(event);assert.deepEqual(calls,['close','capture']);
});
