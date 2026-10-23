const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/capture.js'),'utf8');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function harness(store=new Map()){
 const elements=new Map(),timers=[];
 function $(id){if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',textContent:'',hidden:false,open:false,disabled:false,listeners:{},checked:[],dataset:{},style:{},attrs:{},setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused=true;},querySelector(){return null;},addEventListener(k,fn){this.listeners[k]=fn;},removeAttribute(k){delete this[k];},showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();},querySelectorAll(){return this.checked;}});return elements.get(id);}
 const calls=[];
 const c=vm.createContext({$,esc,URLSearchParams,crypto:require('node:crypto').webcrypto,Uint8Array,confirm:()=>true,plural:(n,w)=>n+' '+(n===1?w:w+'s'),captureMemory:(lab,scope)=>{const raw=store.get(lab+'|'+scope);return raw?JSON.parse(raw):null;},rememberCapture:(lab,scope,rec)=>{store.set(lab+'|'+scope,JSON.stringify(rec));return true;},captureOpenAs:()=>store.get('openas')||'',rememberOpenAs:v=>{store.set('openas',v);return true;},activeId:'lab',current:()=>({name:'demo'}),map:$('map'),closeNodeMenu:()=>{},notify:()=>{},clearTimeout:()=>{},setTimeout:fn=>{timers.push(fn);return timers.length;},
 api:async url=>{calls.push(url);return {json:async()=>url.includes('/status')?{enabled:true}:{targets:[{id:'a'.repeat(64),name:'clab-demo-r1',kind:'docker',prefix:'',interfaces:['lo','eth2']}],message:'live'}};},
 json:async(url,method,data)=>{calls.push({url,method,data});return {url:'/static/capture-session.html#'+'a'.repeat(64),id:'a'.repeat(64),message:'Session started.'};}});
 vm.runInContext(source,c);$('capture-dialog').open=true;
 return {c,$,calls,timers,store};
}
test('node scope uses captured lab identity and live interfaces',async()=>{
 const {c,$,calls}=harness();vm.runInContext("captureLab='lab';captureNode='r1';captureHint='eth2'",c);$('capture-scope').value='lab';
 await c.refreshCaptureTargets();assert.ok(calls.includes('/capture/targets?lab_id=lab&node=r1'));
 assert.match($('capture-interfaces').innerHTML,/value="eth2" checked/);assert.equal($('capture-prepare').disabled,false);
});
test('all host scope removes lab filtering and missing aliases are never guessed',async()=>{
 const {c,$,calls}=harness();vm.runInContext("captureLab='lab';captureNode='r1';captureHint='Gi0/0/0/1'",c);$('capture-scope').value='host';
 await c.refreshCaptureTargets();assert.ok(calls.includes('/capture/targets?'));assert.doesNotMatch($('capture-interfaces').innerHTML,/checked/);assert.match($('capture-status').textContent,/Tick the matching interface below/);
});
test('capture requires selection and creates a same-origin browser session',async()=>{
 const {c,$,calls,timers}=harness();await c.refreshCaptureTargets();
 await $('capture-form').onsubmit({preventDefault(){}});assert.match($('capture-status').textContent,/at least one/);
 $('capture-interfaces').checked=[{value:'eth2'}];await $('capture-form').onsubmit({preventDefault(){}});
 assert.equal(calls.find(c=>c?.url==='/capture/launch').data.interfaces[0],'eth2');assert.equal($('capture-launches').hidden,false);
 assert.equal(($('capture-launches').innerHTML.match(/<a /g)||[]).length,1,'one session, one link');assert.match($('capture-launches').innerHTML,/href="\/static\/capture-session\.html#a{64}"/);
 $('capture-launches').onclick({target:{closest:()=>({dataset:{captureOpen:''}})}});assert.match($('capture-status').textContent,/Wireshark opened in a new tab/);
 assert.equal(timers.length,0);
});
test('changing selection clears a prepared link and releases the prepare button',async()=>{
 const {c,$}=harness();await c.refreshCaptureTargets();$('capture-launches').innerHTML='<a href="/static/capture-session.html#'+'b'.repeat(64)+'">x</a>';$('capture-launches').hidden=false;$('capture-prepare').disabled=true;
 $('capture-interfaces').checked=[{value:'eth2'}];
 $('capture-interfaces').onchange();assert.equal($('capture-launches').hidden,true);assert.equal($('capture-launches').innerHTML,'');assert.equal($('capture-prepare').disabled,false);
});
test('prepare stays disabled until an interface is ticked and a target-less dialog says so',async()=>{
 const {c,$}=harness();await c.refreshCaptureTargets();
 assert.equal($('capture-prepare').disabled,true);
 $('capture-interfaces').checked=[];$('capture-interfaces').onchange();assert.equal($('capture-prepare').disabled,true);
 $('capture-interfaces').checked=[{value:'eth2'}];$('capture-interfaces').onchange();assert.equal($('capture-prepare').disabled,false);
 $('capture-target').value='';c.renderCaptureInterfaces();
 assert.match($('capture-interfaces').innerHTML,/Choose a device above/);assert.equal($('capture-prepare').disabled,true);
});
test('shared namespaces and loopback-only targets are labelled, the kind shows only for the whole VM, and aliases show in the option labels',()=>{
 const {c,$}=harness();
 vm.runInContext(`captureTargets=[{id:'h',name:'systemd(1)',kind:'proc',prefix:'',interfaces:['ens33','lo'],aliases:['containerlab-node-manager-backup-ui-1']},{id:'s',name:'sandbox',kind:'proc',prefix:'',interfaces:['lo'],aliases:[]}];`,c);
 c.filterCaptureTargets();
 assert.match($('capture-target').innerHTML,/also: containerlab-node-manager-backup-ui-1/);assert.match($('capture-target').innerHTML,/sandbox · 1 interfaces · loopback only/);assert.doesNotMatch($('capture-target').innerHTML,/\(proc\)/,'inside a lab every row is a device');
 $('capture-scope').value='host';c.filterCaptureTargets();assert.match($('capture-target').innerHTML,/sandbox \(proc\) · 1 interfaces · loopback only/);$('capture-scope').value='';
 $('capture-scope').value='lab';c.filterCaptureTargets();
 assert.match($('capture-target').innerHTML,/sandbox/,'every target stays listed: there is no search to hide one');assert.equal($('capture-target').value,'','several targets: nothing is chosen for the student');
 $('capture-target').value='h';c.filterCaptureTargets();assert.equal($('capture-target').value,'h','the chosen device survives a rebuild');
 vm.runInContext(`captureTargets=[{id:'n',name:'clab-demo-r1',kind:'docker',prefix:'',interfaces:['eth0'],aliases:['CliShell(1)','CliShell(2)','CliShell(3)','CliShell(4)']}];`,c);
 c.filterCaptureTargets();
 assert.match($('capture-target').innerHTML,/also: CliShell\(1\), CliShell\(2\) \+2 more/);assert.equal($('capture-target').value,'n','a single target is chosen automatically');
});
test('node and menu capture actions are disabled only once the manager reports capture disabled',async()=>{
 const {c}=harness();await new Promise(r=>setImmediate(r));
 assert.equal(c.captureActionAttrs(),'');
 vm.runInContext('captureEnabled=false',c);assert.match(c.captureActionAttrs(),/^disabled title=/);
 vm.runInContext('captureEnabled=null',c);assert.equal(c.captureActionAttrs(),'');
});
test('closing during an in-flight launch cannot restore a stale link',async()=>{
 const {c,$}=harness();await c.refreshCaptureTargets();$('capture-interfaces').checked=[{value:'eth2'}];let finish;
 c.json=()=>new Promise(resolve=>finish=resolve);const pending=$('capture-form').onsubmit({preventDefault(){}});
 for(let i=0;i<4;i++)await new Promise(r=>setImmediate(r));   // the slot pre-check answers first, then the launch is in flight
 $('capture-dialog').close();finish({url:'/static/capture-session.html#'+'b'.repeat(64),message:'old'});await pending;assert.equal($('capture-launches').innerHTML,'');assert.equal($('capture-launches').hidden,true);
});
test('out of order discovery cannot replace newer results',async()=>{
 const {c,$}=harness();let finish;c.api=()=>new Promise(resolve=>finish=resolve);
 const pending=c.refreshCaptureTargets();$('capture-dialog').close();finish({json:async()=>({enabled:true})});await pending;
 assert.equal($('capture-target').innerHTML,'');
});
test('disabled providers and outages have an actionable local message',async()=>{
 const {c,$}=harness();c.api=async()=>({json:async()=>({enabled:false,message:'Configure Edgeshark'})});await c.refreshCaptureTargets();assert.equal($('capture-status').textContent,'Configure Edgeshark');assert.equal($('capture-prepare').disabled,true);
 c.api=async()=>{throw Error('Provider unreachable');};await c.refreshCaptureTargets();assert.equal($('capture-status').textContent,'Provider unreachable');assert.equal($('capture-prepare').disabled,true);
});
test('untrusted labels are escaped and unsupported launch schemes cannot navigate',async()=>{
 const {c,$}=harness();vm.runInContext(`captureTargets=[{id:'a',name:'<img onerror=x>',prefix:'<script>',kind:'docker',interfaces:['eth2']}];`,c);c.filterCaptureTargets();assert.doesNotMatch($('capture-target').innerHTML,/<img|<script>/);assert.match($('capture-target').innerHTML,/&lt;img/);
 $('capture-interfaces').checked=[{value:'eth2'}];c.json=async()=>({url:'javascript:alert(1)'});await $('capture-form').onsubmit({preventDefault(){}});assert.equal($('capture-launches').innerHTML,'');assert.match($('capture-status').textContent,/Unsupported/);
});
function mapHarness(live,links){
 const h=harness();
 h.c.api=async url=>{h.calls.push(url);return {json:async()=>url.includes('/status')?{enabled:true}:url.includes('/topology')?{nodes:[{id:'r1',inventory_name:'clab-demo-r1'},{id:'r2',inventory_name:'clab-demo-r2'}],links}:{targets:[{id:'a'.repeat(64),name:'clab-demo-r1',kind:'docker',prefix:'',interfaces:live}],message:'live'}};};
 return h;
}
test('a node lists its wired ports first and keeps the rest behind a toggle',async()=>{
 const h=mapHarness(['eth0','eth1','eth2','fabric','lo'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}],[{node:'r1',interface:'eth2'},{node:'r2',interface:'eth2'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",h.c);
 await h.c.refreshCaptureTargets();
 assert.ok(h.calls.includes('/labs/lab/topology'));
 const first=h.$('capture-interfaces').innerHTML,rest=h.$('capture-interfaces-all').innerHTML;
 assert.match(first,/value="eth1"/);assert.match(first,/value="eth2"/);assert.doesNotMatch(first,/value="fabric"|value="eth0"|value="lo"/);
 assert.doesNotMatch(first,/checked/);
 assert.match(rest,/value="eth0"/);assert.match(rest,/value="fabric"/);assert.doesNotMatch(rest,/value="eth1"/);
 assert.equal(h.$('capture-more').hidden,false);assert.equal(h.$('capture-more-label').textContent,'Other interfaces on this device (3)');
 assert.equal(h.$('capture-primary-legend').textContent,'Connected interfaces');assert.equal(h.$('capture-advanced-label').textContent,'Advanced: capture somewhere else');
 assert.equal(h.$('capture-advanced').open,false);assert.match(h.$('capture-status').textContent,/Tick the interfaces/);
});
test('a node with a single wired port starts ticked and ready to capture',async()=>{
 const h=mapHarness(['eth0','eth1','lo'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",h.c);
 await h.c.refreshCaptureTargets();
 assert.match(h.$('capture-interfaces').innerHTML,/value="eth1" checked/);assert.equal(h.$('capture-prepare').disabled,false);
 assert.match(h.$('capture-status').textContent,/eth1 is selected/);
 assert.equal(h.$('capture-more-label').textContent,'Other interfaces on this device (2)');
});
test('without a map the live list is shown and an unresolved target unfolds the advanced selector',async()=>{
 const h=mapHarness(['eth0','eth1'],[]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",h.c);
 await h.c.refreshCaptureTargets();
 assert.equal(h.$('capture-primary-legend').textContent,'Interfaces');assert.match(h.$('capture-interfaces').innerHTML,/value="eth0"/);
 assert.equal(h.$('capture-more').hidden,true);assert.equal(h.$('capture-advanced').open,false);
 h.c.api=async url=>({json:async()=>url.includes('/status')?{enabled:true}:url.includes('/topology')?{nodes:[],links:[]}:{targets:[{id:'x',name:'a',kind:'docker',prefix:'',interfaces:['eth0']},{id:'y',name:'b',kind:'docker',prefix:'',interfaces:['eth0']}],message:'live'}});
 vm.runInContext("captureNode=''",h.c);await h.c.refreshCaptureTargets();
 assert.equal(h.$('capture-advanced').open,true);assert.equal(h.$('capture-advanced-label').textContent,'Choose a device');assert.match(h.$('capture-interfaces').innerHTML,/Choose a device above/);
});
test('ticked interfaces from both lists are captured together',async()=>{
 const h=mapHarness(['eth0','eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",h.c);
 await h.c.refreshCaptureTargets();
 h.$('capture-interfaces').checked=[{value:'eth1'}];h.$('capture-interfaces-all').checked=[{value:'eth0'}];
 await h.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(JSON.stringify(h.calls.find(c=>c?.url==='/capture/launch').data.interfaces),'["eth1","eth0"]');
});
// ---- C07 helpers: two lab containers (r1 = a..., r2 = b...) and a drawing between them ----
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
const LINK_ENDS=(a,b)=>[{node:'clab-demo-r1',label:'r1',interface:a},{node:'clab-demo-r2',label:'r2',interface:b}];
const A64='a'.repeat(64),B64='b'.repeat(64);
function linkHarness(liveA,liveB,links,{sessions=[],store,max=4,twoNodes=true}={}){
 const h=harness(store);
 const targets=[{id:A64,name:'clab-demo-r1',kind:'docker',prefix:'',interfaces:liveA}].concat(twoNodes?[{id:B64,name:'clab-demo-r2',kind:'docker',prefix:'',interfaces:liveB}]:[]);
 h.state={sessions};
 h.c.api=async url=>{h.calls.push(url);return {json:async()=>url.includes('/status')?{enabled:true}:url.includes('/health')?{ready:true,max_sessions:max}:url.includes('/topology')?{nodes:[{id:'r1',inventory_name:'clab-demo-r1'},{id:'r2',inventory_name:'clab-demo-r2'}],links}:url.startsWith('/capture/sessions')?{sessions:h.state.sessions}:{targets:url.includes('node=')?targets.filter(x=>url.includes('node='+x.name)):targets,message:'live'}};};
 vm.runInContext("activeId='lab'",h.c);
 return h;
}
test('a link opens in link mode with both ends ticked and the veth of each shown',async()=>{
 const h=linkHarness(['lo','eth1','eth2'],['lo','eth1','eth2'],[[{node:'r1',interface:'eth2'},{node:'r2',interface:'eth2'}]]);
 h.c.openCapture('','',LINK_ENDS('eth2','eth2'));await settle();
 assert.equal(h.$('capture-context').textContent,'Link: r1: eth2 — r2: eth2');
 assert.equal(h.$('capture-ends').hidden,false);assert.equal(h.$('capture-dialog').attrs['data-mode'],'link');
 const ends=h.$('capture-ends-list').innerHTML;
 assert.equal((ends.match(/data-capture-end="\d" checked/g)||[]).length,2,'both ends ticked');
 assert.match(ends,/<span>r1: eth2<\/span><\/label>/);assert.match(ends,/<span>r2: eth2<\/span><\/label>/);assert.doesNotMatch(ends,/<small>|eth2 live/,'a veth equal to the port is not printed again (as captureBox does)');
 assert.equal(h.$('capture-prepare').disabled,false);assert.equal(h.$('capture-prepare').textContent,'Start 2 captures');
 assert.equal(h.$('capture-advanced').open,false,'link mode never unfolds Advanced');assert.equal(h.$('capture-advanced-label').textContent,'Advanced: capture somewhere else');
 assert.ok(h.calls.includes('/capture/targets?lab_id=lab'),'one lab-wide lookup, no node filter');
});
test('a mapped NOS port name preselects its container interface once confirmed live (Junos)',async()=>{
 const h=mapHarness(['lo','eth1','eth2','eth3'],[[{node:'r1',interface:'ge-0/0/0',capture_interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint='ge-0/0/0'",h.c);
 await h.c.refreshCaptureTargets();
 assert.match(h.$('capture-interfaces').innerHTML,/value="eth1" checked/);
 assert.equal(h.$('capture-prepare').disabled,false);
 assert.equal(h.$('capture-status').textContent,'Capturing clab-demo-r1 port ge-0/0/0 (container interface eth1) — start the capture when you are ready.');
});
test('a mapped NOS port name preselects its container interface (XRv9k, first data port)',async()=>{
 const h=mapHarness(['lo','eth1'],[[{node:'r1',interface:'Gi0/0/0/0',capture_interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint='Gi0/0/0/0'",h.c);
 await h.c.refreshCaptureTargets();
 assert.match(h.$('capture-interfaces').innerHTML,/value="eth1" checked/);
 assert.match(h.$('capture-status').textContent,/Capturing clab-demo-r1 port Gi0\/0\/0\/0 \(container interface eth1\)/);
});
test('a mapped cJunosEvolved port missing from the live list keeps manual selection with a specific reason',async()=>{
 const h=mapHarness(['lo','eth1','eth2','eth3'],[[{node:'r1',interface:'et-0/0/31',capture_interface:'eth35'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint='et-0/0/31'",h.c);
 await h.c.refreshCaptureTargets();
 assert.doesNotMatch(h.$('capture-interfaces').innerHTML,/checked/);
 assert.equal(h.$('capture-prepare').disabled,true);
 assert.equal(h.$('capture-status').textContent,'The VM lists no eth35 for et-0/0/31 yet: the node may still be starting, or the topology changed. Tick the interface to use.');
});
test('an EOS/linux identity mapping behaves exactly as an unmapped hint did before',async()=>{
 const h=mapHarness(['lo','eth1'],[[{node:'r1',interface:'eth1',capture_interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint='eth1'",h.c);
 await h.c.refreshCaptureTargets();
 assert.match(h.$('capture-interfaces').innerHTML,/value="eth1" checked/);
 assert.equal(h.$('capture-status').textContent,'eth1 is selected — start the capture when you are ready.');
});
test('an unrecognised kind or port shape falls back to the prior "not found" guidance',async()=>{
 const h=mapHarness(['lo','eth1'],[[{node:'r1',interface:'fabric0'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint='fabric0'",h.c);
 await h.c.refreshCaptureTargets();
 assert.doesNotMatch(h.$('capture-interfaces').innerHTML,/checked/);
 assert.match(h.$('capture-status').textContent,/The diagram calls this port fabric0, but the VM lists no interface with that name/);
});
test('a mapped port is never preselected onto a vJunos tap device',async()=>{
 const h=mapHarness(['lo','tap1','eth1'],[[{node:'r1',interface:'ge-0/0/0',capture_interface:'tap1'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint='ge-0/0/0'",h.c);
 await h.c.refreshCaptureTargets();
 assert.doesNotMatch(h.$('capture-interfaces').innerHTML,/checked/);
 assert.equal(h.$('capture-prepare').disabled,true);
 assert.equal(h.$('capture-status').textContent,'The VM lists no tap1 for ge-0/0/0 yet: the node may still be starting, or the topology changed. Tick the interface to use.');
});

test('a link between two different kinds resolves the mapped interface of each end, and unticking end 1 sends only end 2\'s veth',async()=>{
 const h=linkHarness(['lo','eth1'],['lo','eth4','eth5'],[[{node:'r1',interface:'Gi0/0/0/0',capture_interface:'eth1'},{node:'r2',interface:'et-0/0/0',capture_interface:'eth4'}]]);
 h.c.openCapture('','',LINK_ENDS('Gi0/0/0/0','et-0/0/0'));await settle();
 const ends=h.$('capture-ends-list').innerHTML;
 assert.match(ends,/<span>r1: Gi0\/0\/0\/0<\/span> <small>eth1<\/small>/);assert.match(ends,/<span>r2: et-0\/0\/0<\/span> <small>eth4<\/small>/);
 assert.equal(h.$('capture-status').textContent,'Both ends of the link: r1 Gi0/0/0/0 (eth1) and r2 et-0/0/0 (eth4), one Wireshark each (2 sessions).');
 h.$('capture-ends-list').checked=[{dataset:{captureEnd:'1'}}];h.$('capture-ends').onchange();
 assert.equal(h.$('capture-status').textContent,'One end: r2 et-0/0/0 (eth4).');assert.equal(h.$('capture-prepare').textContent,'Start capture');
 await h.$('capture-form').onsubmit({preventDefault(){}});
 const launch=h.calls.find(c=>c?.url==='/capture/launch').data;
 assert.equal(JSON.stringify([launch.target_id,launch.interfaces]),JSON.stringify([B64,['eth4']]),'the single form, end 2 only');
});
test('every rendered link including coincident nodes exposes both endpoint actions',()=>{
 const {c}=harness();vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/topology-render.js'),'utf8'),c);
 for(const x of [0,200]){
  const nodes=new Map([['a',{label:'R1',inventory_name:'node1',x:0,y:0}],['b',{label:'R2',inventory_name:'node2',x,y:0}]]);
  const markup=c.topologyLink([{node:'a',interface:'eth2'},{node:'b',interface:'eth1'}],nodes,0,{});
  assert.match(markup,/data-capture-endpoints=/);assert.match(markup,/node1/);assert.match(markup,/node2/);assert.match(markup,/role="button"/);assert.match(markup,/tabindex="0"/);
 }
});

test('QA-013: a Junos or IOS XR device\'s diagram ports are matched through their container names, labelled with the port, and "not found" is said only of a port whose veth is absent',async()=>{
 const links=[[{node:'r1',interface:'ge-0/0/0',capture_interface:'eth1'},{node:'r2',interface:'eth1',capture_interface:'eth1'}],[{node:'r1',interface:'ge-0/0/1',capture_interface:'eth2'},{node:'r2',interface:'eth2',capture_interface:'eth2'}],[{node:'r1',interface:'ge-0/0/5',capture_interface:'eth6'},{node:'r2',interface:'eth6',capture_interface:'eth6'}]];
 const h=mapHarness(['eth0','eth1','eth2','tap1','tap2','lo'],links);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",h.c);
 await h.c.refreshCaptureTargets();
 const first=h.$('capture-interfaces').innerHTML,rest=h.$('capture-interfaces-all').innerHTML;
 assert.match(first,/value="eth1"[^>]*> <span>eth1<\/span> <small>ge-0\/0\/0<\/small>/,'the connected veth is listed with the device\'s own port name');
 assert.match(first,/value="eth2"/);assert.doesNotMatch(first,/value="eth0"|value="tap1"|value="lo"/,'management, tap and loopback stay behind the toggle');
 assert.doesNotMatch(first,/ge-0\/0\/5/,'a port whose veth the VM does not list is not offered as connected');
 assert.match(rest,/value="eth0"/);assert.match(rest,/value="tap1"/);
 assert.equal(h.$('capture-primary-legend').textContent,'Connected interfaces');
 assert.match(h.$('capture-status').textContent,/Diagram port ge-0\/0\/5 was not found on the VM/,'only the absent port is reported, by its diagram name');
 // Every wired port present: no "not found" at all.
 const ok=mapHarness(['eth0','eth1','eth2','lo'],links.slice(0,2));
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",ok.c);
 await ok.c.refreshCaptureTargets();
 assert.match(ok.$('capture-status').textContent,/Tick the interfaces to capture/);assert.doesNotMatch(ok.$('capture-status').textContent,/not found/);
});


test('captureSummary: the plan sentence and the Start label for each shape',()=>{
 const {c}=harness();
 assert.equal(c.captureSummary('device',['eth1'],false,null,'vsw').text,'One Wireshark for eth1 on vsw.');
 const two=c.captureSummary('device',['eth1','eth2'],false,null,'vsw');
 assert.equal(two.text,'One Wireshark for eth1, eth2 on vsw (or one Wireshark per interface, under Open as).');assert.equal(two.button,'Start capture');assert.equal(two.sessions,1);
 const each=c.captureSummary('device',['eth1','eth2'],true,null,'vsw');
 assert.equal(each.text,'One Wireshark per interface: eth1, eth2 on vsw (2 sessions).');assert.equal(each.button,'Start 2 captures');
 assert.equal(c.captureSummary('device',['a','b','c'],true,null,'x').button,'Start 3 captures');assert.equal(c.captureSummary('device',[],false,null,'x').sessions,0);
 const ends=[{label:'vsw',port:'ge-0/0/0',veth:'eth1',targetId:'A'},{label:'vrt',port:'ge-0/0/0',veth:'eth1',targetId:'B'}];
 assert.equal(c.captureSummary('link',[],false,ends).text,'Both ends of the link: vsw ge-0/0/0 (eth1) and vrt ge-0/0/0 (eth1), one Wireshark each (2 sessions).');
 assert.equal(c.captureSummary('link',[],false,[ends[1]]).text,'One end: vrt ge-0/0/0 (eth1).');
 const loop=[{label:'vsw',port:'e1',veth:'eth1',targetId:'A'},{label:'vsw',port:'e2',veth:'eth2',targetId:'A'}];
 assert.equal(c.captureSummary('link',[],false,loop).text,'Both ends are on vsw: one Wireshark for eth1, eth2.');
 assert.equal(c.captureSummary('link',[],true,loop).button,'Start 2 captures');
 assert.equal(c.captureSummary('link',[],false,[]).text,'Tick at least one end of the link.');
});
test('Open as: absent with one box and in two-device link mode, present for two boxes and a same-device link; one sends the single body, each sends captures',async()=>{
 const h=mapHarness(['eth0','eth1','eth2','lo'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}],[{node:'r1',interface:'eth2'},{node:'r2',interface:'eth2'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",h.c);await h.c.refreshCaptureTargets();
 h.$('capture-interfaces').checked=[{value:'eth1'}];h.$('capture-interfaces').onchange();assert.equal(h.$('capture-openas').hidden,true);
 h.$('capture-interfaces').checked=[{value:'eth1'},{value:'eth2'}];h.$('capture-interfaces').onchange();assert.equal(h.$('capture-openas').hidden,false);
 assert.equal(h.$('capture-openas-one').checked,true,'one is the default');assert.match(h.$('capture-status').textContent,/\(or one Wireshark per interface, under Open as\)/);
 await h.$('capture-form').onsubmit({preventDefault(){}});
 let body=h.calls.find(c=>c?.url==='/capture/launch').data;assert.equal(JSON.stringify(body.interfaces),'["eth1","eth2"]');assert.equal(body.captures,undefined);
 h.calls.length=0;h.$('capture-openas-each').checked=true;h.$('capture-openas-one').checked=false;h.$('capture-openas').onchange();
 assert.equal(h.$('capture-prepare').textContent,'Start 2 captures');assert.equal(h.$('capture-status').textContent,'One Wireshark per interface: eth1, eth2 on clab-demo-r1 (2 sessions).');
 await h.$('capture-form').onsubmit({preventDefault(){}});
 body=h.calls.find(c=>c?.url==='/capture/launch').data;
 assert.equal(JSON.stringify(body.captures),JSON.stringify([{target_id:A64,interfaces:['eth1']},{target_id:A64,interfaces:['eth2']}]));assert.equal(body.target_id,undefined);assert.match(body.request_id,/^[0-9a-f]{64}$/);
 const link=linkHarness(['lo','eth1'],['lo','eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 link.c.openCapture('','',LINK_ENDS('eth1','eth1'));await settle();assert.equal(link.$('capture-openas').hidden,true);
 const loop=linkHarness(['lo','eth1','eth2'],[],[[{node:'r1',interface:'eth1'},{node:'r1',interface:'eth2'}]],{twoNodes:false});
 loop.c.openCapture('','',[{node:'clab-demo-r1',label:'r1',interface:'eth1'},{node:'clab-demo-r1',label:'r1',interface:'eth2'}]);await settle();
 assert.equal(loop.$('capture-openas').hidden,false);assert.equal(loop.$('capture-openas-one').checked,true);
 assert.equal(loop.$('capture-status').textContent,'Both ends are on r1: one Wireshark for eth1, eth2.');
 loop.$('capture-ends-list').checked=[{dataset:{captureEnd:'0'}},{dataset:{captureEnd:'1'}}];
 await loop.$('capture-form').onsubmit({preventDefault(){}});
 const single=loop.calls.find(c=>c?.url==='/capture/launch').data;assert.equal(JSON.stringify([single.target_id,single.interfaces]),JSON.stringify([A64,['eth1','eth2']]),'one session with both veths');
 loop.calls.length=0;loop.$('capture-openas-each').checked=true;loop.$('capture-openas-one').checked=false;loop.$('capture-openas').onchange();
 await loop.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(loop.calls.find(c=>c?.url==='/capture/launch').data.captures.length,2);
});
test('All connected ticks only wired data ports (never eth0, a tap, fabric or lo), None clears, and a tick under the toggle opens it',async()=>{
 const links=[[{node:'r1',interface:'ge-0/0/0',capture_interface:'eth1'},{node:'r2',interface:'x'}],[{node:'r1',interface:'ge-0/0/1',capture_interface:'eth2'},{node:'r2',interface:'y'}],[{node:'r1',interface:'ge-0/0/2',capture_interface:'tap1'},{node:'r2',interface:'z'}]];
 const h=mapHarness(['eth0','eth1','eth2','tap1','fabric','lo'],links);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",h.c);await h.c.refreshCaptureTargets();
 assert.equal(h.$('capture-presets').hidden,false);
 h.$('capture-all').onclick();
 const first=h.$('capture-interfaces').innerHTML;
 assert.equal((first.match(/checked/g)||[]).length,2);assert.match(first,/value="eth1" checked/);assert.match(first,/value="eth2" checked/);assert.doesNotMatch(first,/value="tap1" checked/);
 assert.doesNotMatch(h.$('capture-interfaces-all').innerHTML,/checked/);assert.match(h.$('capture-status').textContent,/eth1, eth2/);
 h.$('capture-none').onclick();assert.doesNotMatch(h.$('capture-interfaces').innerHTML,/checked/);assert.equal(h.$('capture-prepare').disabled,true);
 vm.runInContext("captureOptions={preset:['eth1','eth0','nope']}",h.c);h.c.renderCaptureInterfaces();
 assert.equal(h.$('capture-more').open,true);assert.match(h.$('capture-interfaces-all').innerHTML,/value="eth0" checked/);assert.match(h.$('capture-status').textContent,/Diagram port nope was not found on the VM/);
 const one=mapHarness(['eth0','eth1','lo'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",one.c);await one.c.refreshCaptureTargets();
 assert.equal(one.$('capture-presets').hidden,true,'presets need two or more connected boxes');
});
test('the preset buttons and End all never submit the form: no launch request, and they are type=button in the page',async()=>{
 const h=mapHarness(['eth1','eth2','lo'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}],[{node:'r1',interface:'eth2'},{node:'r2',interface:'eth2'}]]);
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",h.c);await h.c.refreshCaptureTargets();
 h.$('capture-all').onclick();h.$('capture-none').onclick();await h.c.refreshCaptureSessions();await h.$('capture-end-all').onclick();
 assert.equal(h.calls.some(c=>c?.url==='/capture/launch'),false);
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 for(const id of ['capture-all','capture-none','capture-end-all','tools-capture-end-all'])assert.match(html,new RegExp('<button type="button"[^>]*id="'+id+'"'),id+' is type=button');
 assert.match(h.$('capture-ends-list').innerHTML,/^$/);
});
test('an unmapped kind on one end is disabled with the sentence and a Choose button that lands in today\'s manual list',async()=>{
 const h=linkHarness(['lo','eth1','eth2'],['lo','eth1'],[[{node:'r1',interface:'Ethernet0/1'},{node:'r2',interface:'eth1'}]]);
 h.c.openCapture('','',LINK_ENDS('Ethernet0/1','eth1'));await settle();
 const ends=h.$('capture-ends-list').innerHTML;
 assert.match(ends,/data-capture-end="0" disabled/);assert.match(ends,/The diagram calls this port Ethernet0\/1, but the VM lists no interface with that name\./);
 assert.match(ends,/<button type="button" class="button secondary small" data-capture-choose="0">Choose the interface on r1…<\/button>/);
 assert.doesNotMatch(ends,/data-capture-choose="1"/);
 assert.equal(h.$('capture-status').textContent,'One end: r2 eth1.');
 h.$('capture-ends-list').checked=[{dataset:{captureEnd:'1'}}];
 await h.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(h.calls.find(c=>c?.url==='/capture/launch').data.target_id,B64,'the resolvable end is sent as one entry');
 h.$('capture-ends').onclick({target:{closest:()=>({dataset:{captureChoose:'0'}})}});await settle();
 assert.equal(h.$('capture-dialog').attrs['data-mode'],'device');assert.equal(h.$('capture-ends').hidden,true);
 assert.equal(h.$('capture-context').textContent,'Device: clab-demo-r1 · port Ethernet0/1');
 assert.equal(h.$('capture-advanced').open,false);assert.equal(h.$('capture-advanced-label').textContent,'Advanced: capture somewhere else');
 assert.match(h.$('capture-status').textContent,/The diagram calls this port Ethernet0\/1/);assert.match(h.$('capture-interfaces-all').innerHTML+h.$('capture-interfaces').innerHTML,/value="eth1"/);
});
test('an end whose device the VM does not list is disabled with its sentence; neither end resolvable says so and offers both Choose buttons',async()=>{
 const h=linkHarness(['lo','eth1'],[],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]],{twoNodes:false});
 h.c.openCapture('','',LINK_ENDS('eth1','eth1'));await settle();
 assert.match(h.$('capture-ends-list').innerHTML,/r2 is not running on the VM \(no live interfaces\), so this end cannot be captured now\./);
 const none=linkHarness([],[],[],{twoNodes:false});
 none.c.openCapture('','',[{node:'',label:'r1',interface:'eth1'},{node:'clab-demo-r2',label:'r2',interface:'eth1'}]);await settle();
 assert.match(none.$('capture-ends-list').innerHTML,/this diagram node is not in the inventory — choose its device under Advanced/);
 assert.equal((none.$('capture-ends-list').innerHTML.match(/data-capture-choose/g)||[]).length,2);
 assert.equal(none.$('capture-status').textContent,'Neither end of this link is on the VM right now. Start the lab, or choose the interface by hand below.');
 assert.equal(none.$('capture-prepare').disabled,true);
});
test('a refused answer keeps the request id and the started links, narrows to the refused entry, and the next Start sends only it',async()=>{
 const h=linkHarness(['lo','eth1'],['lo','eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 h.c.openCapture('','',LINK_ENDS('eth1','eth1'));await settle();
 const url1='/static/capture-session.html#'+A64,url2='/static/capture-session.html#'+B64;
 h.c.json=async(url,method,data)=>{h.calls.push({url,method,data});return h.calls.filter(c=>c?.url==='/capture/launch').length===1
  ?{sessions:[{id:A64,url:url1,name:'clab-demo-r1',interfaces:['eth1'],label:'r1 eth1'}],refused:[{position:'Capture 2 of 2',label:'r2 eth1',interfaces:['eth1'],detail:'All browser capture slots are in use. End a session or wait for expiry.'}],message:'Wireshark started for r1 eth1; not for r2 eth1: All browser capture slots are in use. End a session or wait for expiry.'}
  :{sessions:[{id:B64,url:url2,name:'clab-demo-r2',interfaces:['eth1'],label:'r2 eth1'}],refused:[],message:'Wireshark session started on the VM.'};};
 h.$('capture-ends-list').checked=[{dataset:{captureEnd:'0'}},{dataset:{captureEnd:'1'}}];
 await h.$('capture-form').onsubmit({preventDefault(){}});
 const first=h.calls.find(c=>c?.url==='/capture/launch').data,id=first.request_id;
 assert.equal(first.captures.length,2);
 assert.match(h.$('capture-launches').innerHTML,/Open Wireshark: r1 eth1/);assert.equal((h.$('capture-launches').innerHTML.match(/<a /g)||[]).length,1);
 assert.match(h.$('capture-status').textContent,/not for r2 eth1: All browser capture slots are in use/);
 assert.match(h.$('capture-ends-list').innerHTML,/data-capture-end="0" disabled>[^]*<p class="form-help">Started: open it with the link below\.<\/p>/);assert.doesNotMatch(h.$('capture-ends-list').innerHTML,/data-capture-end="0" checked/);
 assert.equal(h.$('capture-prepare').textContent,'Start the remaining 1');assert.equal(h.$('capture-prepare').disabled,false);
 h.state.sessions=Array.from({length:4},(_,i)=>({id:String(i).repeat(64).slice(0,64)}));   // a full listing would refuse a fresh Start, never the retry
 await h.$('capture-form').onsubmit({preventDefault(){}});
 const second=h.calls.filter(c=>c?.url==='/capture/launch')[1].data;
 assert.equal(second.request_id,id,'the request id is kept');assert.equal(second.target_id,undefined,'the set form is kept for the narrowed retry');assert.equal(JSON.stringify(second.captures),JSON.stringify([{target_id:B64,interfaces:['eth1']}]));
 assert.equal((h.$('capture-launches').innerHTML.match(/<a /g)||[]).length,2,'the first round\'s link stays');
 h.state.sessions=[];await h.$('capture-form').onsubmit({preventDefault(){}});
 assert.notEqual(h.calls.filter(c=>c?.url==='/capture/launch')[2].data.request_id,id,'a new Start after a full success is a new request');
});
test('the slot sentence appears from a fresh listing without a launch request, in the mode\'s variant, and not on a retry',async()=>{
 const rows=n=>Array.from({length:n},(_,i)=>({id:String(i).repeat(64).slice(0,64)}));
 const links=[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}],[{node:'r1',interface:'eth2'},{node:'r2',interface:'eth2'}]];
 const h=linkHarness(['eth1','eth2','lo'],['eth1'],links,{sessions:rows(3),twoNodes:false});
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1'",h.c);await h.c.refreshCaptureTargets();
 h.$('capture-interfaces').checked=[{value:'eth1'},{value:'eth2'}];h.$('capture-openas-each').checked=true;
 await h.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(h.$('capture-status').textContent,'You already have 3 Wireshark sessions running from this browser; 2 more would pass the limit of 4 at a time. End a session under Your capture sessions, untick interfaces, or open one Wireshark for all of them.');
 assert.equal(h.calls.some(c=>c?.url==='/capture/launch'),false);assert.equal(h.$('capture-prepare').disabled,false);
 h.state.sessions=rows(1);await h.$('capture-form').onsubmit({preventDefault(){}});assert.equal(h.calls.some(c=>c?.url==='/capture/launch'),true,'the listing is fetched again on every Start');
 const l=linkHarness(['eth1'],['eth1'],links,{sessions:rows(3)});l.c.openCapture('','',LINK_ENDS('eth1','eth1'));await settle();
 l.$('capture-ends-list').checked=[{dataset:{captureEnd:'0'}},{dataset:{captureEnd:'1'}}];
 await l.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(l.$('capture-status').textContent,'You already have 3 Wireshark sessions running from this browser; both ends would pass the limit of 4 at a time. End a session under Your capture sessions, or untick one end.');
 const s=linkHarness(['eth1','lo'],[],links,{sessions:rows(4),twoNodes:false});
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1'",s.c);await s.c.refreshCaptureTargets();s.$('capture-interfaces').checked=[{value:'eth1'}];
 await s.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(s.$('capture-status').textContent,'You already have 4 Wireshark sessions running from this browser, the limit at a time. End a session under Your capture sessions first.');
 const one=linkHarness(['eth1','lo'],[],links,{sessions:rows(1),max:1,twoNodes:false});
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1'",one.c);await one.c.refreshCaptureTargets();one.$('capture-interfaces').checked=[{value:'eth1'}];
 await one.$('capture-form').onsubmit({preventDefault(){}});assert.match(one.$('capture-status').textContent,/You already have 1 Wireshark session running/);
 const big=linkHarness(['eth1','eth2','lo'],[],links,{max:1,twoNodes:false});
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1'",big.c);await big.c.refreshCaptureTargets();big.$('capture-interfaces').checked=[{value:'eth1'},{value:'eth2'}];big.$('capture-openas-each').checked=true;
 await big.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(big.$('capture-status').textContent,'2 separate Wireshark sessions are more than the limit of 1 at a time. Untick interfaces, or open one Wireshark for all of them.');
 const r=linkHarness(['eth1','lo'],[],links,{sessions:rows(4),twoNodes:false});
 vm.runInContext("captureLab='lab';captureNode='clab-demo-r1'",r.c);await r.c.refreshCaptureTargets();r.$('capture-interfaces').checked=[{value:'eth1'}];
 r.c.json=async()=>{throw new Error('lost');};vm.runInContext("captureLaunchId='f'.repeat(64)",r.c);
 await r.$('capture-form').onsubmit({preventDefault(){}});assert.equal(r.$('capture-status').textContent,'lost','the server\'s answer, not the local sentence');
});
test('memory: restored for live names only, ignored with a hint, an end or a preset, written only after a full success under the same condition',async()=>{
 const store=new Map([['lab|node:clab-demo-r1',JSON.stringify({interfaces:['eth2','gone'],separate:true})]]);
 const links=[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}],[{node:'r1',interface:'eth2'},{node:'r2',interface:'eth2'}]];
 const answer=url=>({json:async()=>url.includes('/status')?{enabled:true}:url.includes('/topology')?{nodes:[{id:'r1',inventory_name:'clab-demo-r1'},{id:'r2',inventory_name:'clab-demo-r2'}],links}:{targets:[{id:A64,name:'clab-demo-r1',kind:'docker',prefix:'',interfaces:['eth0','eth1','eth2','lo']}],message:'live'}});
 const make=async(setup,mem=store)=>{const h=harness(mem);h.c.api=async url=>answer(url);vm.runInContext(setup,h.c);await h.c.refreshCaptureTargets();return h;};
 const restored=await make("captureLab='lab';captureNode='clab-demo-r1';captureHint=''");
 assert.match(restored.$('capture-interfaces').innerHTML,/value="eth2" checked/);assert.doesNotMatch(restored.$('capture-interfaces').innerHTML,/value="eth1" checked/);
 assert.equal((restored.$('capture-interfaces').innerHTML.match(/checked/g)||[]).length,1,'the name the VM no longer lists is dropped');
 assert.match(restored.$('capture-status').textContent,/^Your last selection here was restored\./);assert.equal(restored.$('capture-openas-each').checked,true);
 const hinted=await make("captureLab='lab';captureNode='clab-demo-r1';captureHint='eth1'");
 assert.match(hinted.$('capture-interfaces').innerHTML,/value="eth1" checked/);assert.doesNotMatch(hinted.$('capture-interfaces').innerHTML,/value="eth2" checked/);assert.doesNotMatch(hinted.$('capture-status').textContent,/restored/);
 const preset=await make("captureLab='lab';captureNode='clab-demo-r1';captureHint='';captureOptions={preset:['eth1']}");
 assert.doesNotMatch(preset.$('capture-interfaces').innerHTML,/value="eth2" checked/);
 store.set('lab|node:clab-demo-r1',JSON.stringify({interfaces:['gone']}));
 const gone=await make("captureLab='lab';captureNode='clab-demo-r1';captureHint=''");assert.doesNotMatch(gone.$('capture-status').textContent,/restored/);
 const w=new Map();
 const run=async setup=>{const h=await make(setup,w);h.$('capture-interfaces').checked=[{value:'eth1'},{value:'eth2'}];h.$('capture-openas-each').checked=true;await h.$('capture-form').onsubmit({preventDefault(){}});return h;};
 await run("captureLab='lab';captureNode='clab-demo-r1';captureHint='eth1'");assert.equal(w.size,0,'a hinted open writes nothing');
 await run("captureLab='lab';captureNode='clab-demo-r1';captureHint='';captureOptions={preset:['eth1']}");assert.equal(w.size,0);
 await run("captureLab='lab';captureNode='clab-demo-r1';captureHint='';captureOptions={end:1}");assert.equal(w.size,0);
 await run("captureLab='lab';captureNode='clab-demo-r1';captureHint=''");
 assert.deepEqual(JSON.parse(w.get('lab|node:clab-demo-r1')),{interfaces:['eth1','eth2'],separate:true});assert.equal(w.get('openas'),'each');
 const p=new Map(),ph=await make("captureLab='lab';captureNode='clab-demo-r1';captureHint=''",p);
 ph.$('capture-interfaces').checked=[{value:'eth1'},{value:'eth2'}];ph.$('capture-openas-each').checked=true;
 ph.c.json=async()=>({sessions:[{id:A64,url:'/static/capture-session.html#'+A64,label:'x'}],refused:[{position:'Capture 2 of 2',interfaces:['eth2'],detail:'no'}],message:'part'});
 await ph.$('capture-form').onsubmit({preventDefault(){}});assert.equal(p.size,0,'nothing remembered after a partial result');
 assert.match(ph.$('capture-interfaces').innerHTML,/value="eth1" disabled>[^]*started \(open it above\)/);assert.match(ph.$('capture-interfaces').innerHTML,/value="eth2" checked/);assert.equal(ph.$('capture-prepare').textContent,'Start the remaining 1');
 const lm=new Map([['lab|link:clab-demo-r1:eth1|clab-demo-r2:eth1',JSON.stringify({interfaces:['eth1'],separate:false,ends:[false,true]})]]);
 const lh=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]],{store:lm});lh.c.openCapture('','',LINK_ENDS('eth1','eth1'));await settle();
 assert.doesNotMatch(lh.$('capture-ends-list').innerHTML,/data-capture-end="0" checked/);assert.match(lh.$('capture-ends-list').innerHTML,/data-capture-end="1" checked/);assert.match(lh.$('capture-status').textContent,/^Your last selection here was restored\. One end: r2 eth1/);
 const eh=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]],{store:lm});eh.c.openCapture('','',LINK_ENDS('eth1','eth1'),{end:0});await settle();
 assert.match(eh.$('capture-ends-list').innerHTML,/data-capture-end="0" checked/);assert.doesNotMatch(eh.$('capture-ends-list').innerHTML,/data-capture-end="1" checked/);
 // a link success writes the link scope with the ends as ticked
 const wl=new Map(),lw=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]],{store:wl});lw.c.openCapture('','',LINK_ENDS('eth1','eth1'));await settle();
 lw.$('capture-ends-list').checked=[{dataset:{captureEnd:'0'}},{dataset:{captureEnd:'1'}}];await lw.$('capture-form').onsubmit({preventDefault(){}});
 assert.deepEqual(JSON.parse(wl.get('lab|link:clab-demo-r1:eth1|clab-demo-r2:eth1')),{interfaces:['eth1','eth1'],separate:false,ends:[true,true]});
});
function wire(ends){return {dataset:{captureEndpoints:JSON.stringify(ends)},focus(){this.focused=true;},getBoundingClientRect(){return {right:50,top:20};}};}
test('the wire menu: three items, the first focused, a click opens link mode (both, or one end), Escape returns focus to the wire, Tab closes, the lab guard',async()=>{
 const h=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 const menu=h.$('link-context-menu'),first={disabled:false,focus(){this.focused=true;}};
 menu.querySelectorAll=()=>[];menu.querySelector=()=>first;
 const w=wire(LINK_ENDS('ge-0/0/0','ge-0/0/1')),open=()=>h.$('map').listeners.contextmenu({target:{closest:()=>w},preventDefault(){},clientX:10,clientY:10});
 let prevented=false;h.$('map').listeners.contextmenu({target:{closest:()=>w},preventDefault(){prevented=true;},clientX:10,clientY:10});
 assert.equal(prevented,true);assert.equal(menu.hidden,false);assert.equal(first.focused,true);
 assert.match(menu.innerHTML,/<div class="context-node-name">r1: ge-0\/0\/0 — r2: ge-0\/0\/1<\/div>/);
 assert.match(menu.innerHTML,/data-link-both[^>]*>Capture both ends…/);assert.match(menu.innerHTML,/data-link-end="0"[^>]*>Capture r1: ge-0\/0\/0…/);assert.match(menu.innerHTML,/data-link-end="1"[^>]*>Capture r2: ge-0\/0\/1…/);
 assert.doesNotMatch(menu.innerHTML,/disabled/);
 menu.listeners.click({target:{closest:()=>({disabled:false,dataset:{linkBoth:''}})}});
 assert.equal(menu.hidden,true);await settle();assert.equal(h.$('capture-context').textContent,'Link: r1: ge-0/0/0 — r2: ge-0/0/1');
 open();menu.listeners.click({target:{closest:()=>({disabled:false,dataset:{linkEnd:'1'}})}});
 assert.equal(vm.runInContext('JSON.stringify(captureOptions)',h.c),'{"end":1}');
 open();let stopped=false;menu.listeners.keydown({key:'Escape',preventDefault(){},stopPropagation(){stopped=true;}});
 assert.equal(menu.hidden,true);assert.equal(w.focused,true);assert.equal(stopped,true);
 open();menu.listeners.keydown({key:'Tab'});assert.equal(menu.hidden,true);
 open();vm.runInContext("activeId='other';captureOptions={marker:1}",h.c);
 menu.listeners.click({target:{closest:()=>({disabled:false,dataset:{linkBoth:''}})}});
 assert.equal(menu.hidden,true);assert.equal(vm.runInContext('captureOptions.marker',h.c),1,'nothing opened');
 vm.runInContext("activeId='lab'",h.c);
 const items=[0,1,2].map(()=>({disabled:false,focus(){this.focused=true;}}));menu.querySelectorAll=()=>items;
 let moved=false;menu.listeners.keydown({key:'ArrowDown',target:items[0],preventDefault(){moved=true;}});assert.equal(items[1].focused,true);assert.equal(moved,true);
 menu.listeners.keydown({key:'End',target:items[0],preventDefault(){}});assert.equal(items[2].focused,true);
 items[2].focused=false;menu.listeners.keydown({key:'ArrowUp',target:items[0],preventDefault(){}});assert.equal(items[2].focused,true,'wraps');
});
test('the wire menu opens from the keyboard (ContextMenu, Shift+F10), click/Enter/Space keep opening the dialog, and items say why they are off when capture is not set up',async()=>{
 const h=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 const menu=h.$('link-context-menu'),w=wire(LINK_ENDS('eth1','eth1'));menu.querySelector=()=>null;
 h.$('map').listeners.keydown({key:'ContextMenu',target:{closest:()=>w},preventDefault(){}});assert.equal(menu.hidden,false);
 menu.hidden=true;h.$('map').listeners.keydown({key:'F10',shiftKey:true,target:{closest:()=>w},preventDefault(){}});assert.equal(menu.hidden,false);
 menu.hidden=true;let p=false;h.$('map').listeners.keydown({key:'Enter',target:{closest:()=>w},preventDefault(){p=true;}});
 assert.equal(p,true);assert.equal(menu.hidden,true);await settle();assert.equal(h.$('capture-context').textContent,'Link: r1: eth1 — r2: eth1','Enter opens the dialog in link mode');
 vm.runInContext('captureEnabled=false',h.c);h.$('map').listeners.keydown({key:'ContextMenu',target:{closest:()=>w},preventDefault(){}});
 assert.equal((menu.innerHTML.match(/ disabled title=/g)||[]).length,3);assert.match(menu.innerHTML,/Packet capture isn’t set up on this VM yet — see Tools › Packet capture\./);
});
test('the sessions list, the upper-bound time, End all my sessions and the Tools caption',async()=>{
 const h=harness();const hex=n=>String(n).repeat(64).slice(0,64);
 let rows=[{id:hex(1),name:'clab-demo-r1',interfaces:['eth1'],ports:['ge-0/0/0'],device:'vsw',lab:'parity',remaining_seconds:7199,idle_seconds:900},{id:hex(2),name:'clab-x',interfaces:['eth2'],remaining_seconds:3000}];
 h.c.api=async url=>({json:async()=>url.includes('/status')?{enabled:true}:{sessions:rows}});
 await h.c.refreshCaptureSessions();
 const list=h.$('capture-sessions').innerHTML;
 assert.match(list,/>vsw ge-0\/0\/0 \(eth1\) · parity<\/a>/);assert.match(list,/at most 1 h 59 min left \(15 min once its viewer is closed\)/);assert.match(list,/>clab-x · eth2<\/a>/,'no lab match: the container name as before');
 assert.match(list,/at most 50 min left/);
 assert.equal(h.$('capture-sessions-caption').textContent,'2 Wireshark sessions running from this browser.');assert.equal(h.$('capture-sessions-caption').hidden,false);
 assert.equal(h.$('capture-end-all').hidden,false);assert.equal(h.$('tools-capture-end-all').hidden,false);
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');assert.match(html,/id="capture-end-all" class="button danger"/);
 const asked=[];h.c.confirm=m=>{asked.push(m);return true;};
 const button={textContent:'End all my sessions',disabled:false};const states=[];
 h.c.json=async(url,method,data)=>{states.push([button.textContent,button.disabled]);assert.equal(url,'/capture/sessions/end-all');assert.equal(method,'POST');assert.equal(JSON.stringify(data),'{}');rows=[];return {ended:2,failed:[]};};
 await h.c.endAllCaptureSessions(button);
 assert.equal(asked[0],'End all 2 Wireshark sessions started from this browser and delete their capture files? Download saved files first.');
 assert.deepEqual(states[0],['Ending…',true]);assert.equal(button.textContent,'End all my sessions');assert.equal(button.disabled,false);
 assert.equal(h.$('capture-status').textContent,'Ended 2 sessions.');assert.equal(h.$('capture-sessions-caption').hidden,true);assert.equal(h.$('capture-end-all').hidden,true);
 rows=[{id:hex(3),name:'c',interfaces:['eth1']}];await h.c.refreshCaptureSessions();assert.equal(h.$('capture-sessions-caption').textContent,'1 Wireshark session running from this browser.');
 h.c.json=async()=>{rows=[];return {ended:1,failed:[]};};
 await h.c.endAllCaptureSessions(button);assert.equal(asked[1],'End the 1 Wireshark session started from this browser and delete its capture files? Download saved files first.');assert.equal(h.$('capture-status').textContent,'Ended 1 session.');
 h.c.json=async()=>({ended:2,failed:[{id:hex(4),label:'vsw ge-0/0/0 (eth1)',detail:'Could not end vsw ge-0/0/0 (eth1); try End session on its row.'}]});
 rows=[{id:hex(3),name:'c',interfaces:['eth1']}];await h.c.refreshCaptureSessions();await h.c.endAllCaptureSessions(button);
 assert.equal(h.$('capture-status').textContent,'Ended 2 sessions; 1 could not be ended: Could not end vsw ge-0/0/0 (eth1); try End session on its row.');
 rows=[];await h.c.refreshCaptureSessions();asked.length=0;let called=false;h.c.json=async()=>{called=true;return {};};
 await h.c.endAllCaptureSessions(button);assert.equal(asked.length,0);assert.equal(called,false);assert.equal(h.$('capture-status').textContent,'No capture sessions to end.');
 rows=[{id:hex(3),name:'c',interfaces:['eth1']}];await h.c.refreshCaptureSessions();vm.runInContext('captureEnabled=false',h.c);h.c.renderCaptureCaption();
 assert.equal(h.$('capture-sessions-caption').hidden,true);assert.equal(h.$('tools-capture-end-all').hidden,true);
});
test('untrusted labels in the ends, the session rows, the links and the wire menu are escaped',async()=>{
 const hostile='<img src=x onerror=1>';
 const h=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 h.c.openCapture('','',[{node:'clab-demo-r1',label:hostile,interface:'eth1'},{node:'clab-demo-r2',label:'r2',interface:'eth1'}]);await settle();
 assert.doesNotMatch(h.$('capture-ends-list').innerHTML,/<img/);
 const menu=h.$('link-context-menu');menu.querySelector=()=>null;
 h.$('map').listeners.contextmenu({target:{closest:()=>wire([{node:'x',label:hostile,interface:'"><b>'},{node:'y',label:'r2',interface:'e'}])},preventDefault(){},clientX:1,clientY:1});
 assert.doesNotMatch(menu.innerHTML,/<img|<b>/);
 h.c.api=async()=>({json:async()=>({sessions:[{id:A64,name:hostile,interfaces:[hostile],device:hostile,ports:[hostile],lab:hostile,remaining_seconds:60}]})});
 await h.c.refreshCaptureSessions();assert.doesNotMatch(h.$('capture-sessions').innerHTML,/<img/);
});
test('C07 fix: an unchanged sessions list rewrites nothing (so a focused End session button keeps focus), a changed one does, and the failure and disabled notes use the same cache',async()=>{
 const h=harness();const hex=n=>String(n).repeat(64).slice(0,64);let writes=0,html='';const list=h.$('capture-sessions');
 Object.defineProperty(list,'innerHTML',{get:()=>html,set:v=>{writes++;html=v;}});
 let rows=[{id:hex(1),name:'c1',interfaces:['eth1'],remaining_seconds:3000}];
 h.c.api=async()=>({json:async()=>({sessions:rows})});
 await h.c.refreshCaptureSessions();assert.equal(writes,1);
 for(let i=0;i<3;i++)await h.c.refreshCaptureSessions();
 assert.equal(writes,1,'three more refreshes of an unchanged list wrote nothing');
 rows=rows.concat([{id:hex(2),name:'c2',interfaces:['eth2'],remaining_seconds:3000}]);await h.c.refreshCaptureSessions();assert.equal(writes,2);
 h.c.api=async()=>{throw new Error('x');};await h.c.refreshCaptureSessions();await h.c.refreshCaptureSessions();assert.equal(writes,3,'the failure note is written once');
 assert.match(html,/Could not list capture sessions/);
 assert.equal(await h.c.refreshCaptureSessions(),false,'a failed listing says so to End all');
});
test('C07 fix: End all my sessions lists again before it asks and names the current count; a failed listing ends nothing; the focus leaves a hidden button for a live control',async()=>{
 const h=harness();const hex=n=>String(n).repeat(64).slice(0,64);
 let rows=[{id:hex(1),name:'c',interfaces:['eth1']}];
 h.c.api=async()=>({json:async()=>({sessions:rows})});
 await h.c.refreshCaptureSessions();
 rows=rows.concat([{id:hex(2),name:'d',interfaces:['eth2']},{id:hex(3),name:'e',interfaces:['eth3']}]);   // two more started elsewhere since the Tools tab listed
 const asked=[];h.c.confirm=m=>{asked.push(m);return false;};
 const button={textContent:'End all my sessions',disabled:false,hidden:false};
 await h.c.endAllCaptureSessions(button);
 assert.match(asked[0],/^End all 3 Wireshark sessions/,'the confirmation names the current count, not the stale 1');
 assert.equal(button.disabled,false);assert.equal(button.textContent,'End all my sessions');
 let called=false;h.c.json=async()=>{called=true;return {};};h.c.api=async()=>{throw new Error('down');};asked.length=0;
 await h.c.endAllCaptureSessions(button);assert.equal(asked.length,0);assert.equal(called,false);assert.match(h.$('capture-status').textContent,/Could not list capture sessions, so none were ended/);
 // double press: the second is ignored while the first is checking
 h.c.api=async()=>({json:async()=>({sessions:rows})});h.c.confirm=m=>{asked.push(m);return true;};
 const done=hex(4);let ended=0;h.c.json=async()=>{ended++;rows=[];return {ended:3,failed:[]};};
 const dialogRefresh=h.$('capture-sessions-refresh');dialogRefresh.focused=false;const endAll=h.$('capture-end-all');
 const first=h.c.endAllCaptureSessions(endAll),second=h.c.endAllCaptureSessions(endAll);await Promise.all([first,second]);
 assert.equal(ended,1,'one end-all request');assert.equal(asked.length,1);
 assert.equal(endAll.hidden,true);assert.equal(dialogRefresh.focused,true,'with the dialog open focus lands on Refresh list');
 h.$('capture-dialog').open=false;const open=h.$('capture-open');open.focused=false;rows=[{id:hex(5),name:'f',interfaces:['eth1']}];await h.c.refreshCaptureSessions();
 h.c.json=async()=>{rows=[];return {ended:1,failed:[]};};const tools=h.$('tools-capture-end-all');await h.c.endAllCaptureSessions(tools);
 assert.equal(open.focused,true,'from the Tools card focus lands on Capture traffic…');
});
test('C07 fix: the wire menu with every item off takes focus itself, closes on Escape and Tab, and Enter on the wire closes it before the dialog opens',async()=>{
 const h=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 const menu=h.$('link-context-menu'),w=wire(LINK_ENDS('eth1','eth1'));menu.querySelector=()=>null;
 vm.runInContext('captureEnabled=false',h.c);
 h.$('map').listeners.keydown({key:'ContextMenu',target:{closest:()=>w},preventDefault(){}});
 assert.equal(menu.hidden,false);assert.equal(menu.focused,true,'no enabled item: the menu element is focused');
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');assert.match(html,/id="link-context-menu"[^>]*tabindex="-1"/,'the menu element can take focus');
 menu.focused=false;w.focused=false;menu.listeners.keydown({key:'Escape',preventDefault(){},stopPropagation(){}});assert.equal(menu.hidden,true);assert.equal(w.focused,true,'Escape returns focus to the wire');
 h.$('map').listeners.keydown({key:'ContextMenu',target:{closest:()=>w},preventDefault(){}});menu.listeners.keydown({key:'Tab'});assert.equal(menu.hidden,true);
 vm.runInContext('captureEnabled=null',h.c);
 h.$('map').listeners.keydown({key:'ContextMenu',target:{closest:()=>w},preventDefault(){}});assert.equal(menu.hidden,false);
 h.$('map').listeners.keydown({key:'Enter',target:{closest:()=>w},preventDefault(){}});assert.equal(menu.hidden,true,'Enter on the wire closes the open menu first');
 await settle();assert.equal(h.$('capture-context').textContent,'Link: r1: eth1 — r2: eth1');
});
test('C07 fix: Capture both ends… from the menu ignores the remembered selection; the wire itself still restores it; the one-end item and a success under it are unchanged',async()=>{
 const lm=new Map([['lab|link:clab-demo-r1:eth1|clab-demo-r2:eth1',JSON.stringify({interfaces:['eth1'],separate:false,ends:[false,true]})]]);
 const h=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]],{store:lm});
 const menu=h.$('link-context-menu'),w=wire(LINK_ENDS('eth1','eth1'));menu.querySelector=()=>null;
 h.$('map').listeners.click({target:{closest:()=>w}});await settle();
 assert.doesNotMatch(h.$('capture-ends-list').innerHTML,/data-capture-end="0" checked/,'the wire click restores the memory');
 h.$('capture-dialog').close();
 h.$('map').listeners.contextmenu({target:{closest:()=>w},preventDefault(){},clientX:1,clientY:1});
 menu.listeners.click({target:{closest:()=>({disabled:false,dataset:{linkBoth:''}})}});await settle();
 assert.match(h.$('capture-ends-list').innerHTML,/data-capture-end="0" checked/);assert.match(h.$('capture-ends-list').innerHTML,/data-capture-end="1" checked/,'both ends ticked');
 assert.doesNotMatch(h.$('capture-status').textContent,/restored/);
 h.$('capture-ends-list').checked=[{dataset:{captureEnd:'0'}},{dataset:{captureEnd:'1'}}];await h.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(JSON.parse(lm.get('lab|link:clab-demo-r1:eth1|clab-demo-r2:eth1')).ends[0],false,'a menu item is a hint: it writes nothing');
});
test('C07 fix: closing the dialog returns focus to the wire (found again by its ends after a redraw), from a click, a menu item and Enter',async()=>{
 const h=linkHarness(['eth1'],['eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 const menu=h.$('link-context-menu'),ends=LINK_ENDS('eth1','eth1'),w=wire(ends);menu.querySelector=()=>null;
 h.$('map').listeners.click({target:{closest:()=>w}});await settle();
 h.$('capture-dialog').close();assert.equal(w.focused,true,'click: the wire gets focus back');
 w.focused=false;h.$('map').listeners.contextmenu({target:{closest:()=>w},preventDefault(){},clientX:1,clientY:1});
 menu.listeners.click({target:{closest:()=>({disabled:false,dataset:{linkEnd:'0'}})}});await settle();
 h.$('capture-dialog').close();assert.equal(w.focused,true,'menu item: the opener is the wire, not the hidden menu');
 // the map was redrawn while the dialog was open: the old node is detached, the new one has the same ends
 const fresh=wire(ends);w.isConnected=false;w.focused=false;
 h.$('map').listeners.click({target:{closest:()=>w}});await settle();
 h.$('map').querySelectorAll=()=>[fresh];h.$('capture-dialog').close();
 assert.equal(fresh.focused,true,'the redrawn wire is found by its ends');assert.equal(w.focused,false);
 h.$('capture-dialog').close();   // no opener left: nothing throws
});
test('C07 fix: after a full success Start waits for a changed selection and the status says what is listed; a narrowed retry says two sessions, not one',async()=>{
 const h=linkHarness(['lo','eth1'],['lo','eth1'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}]]);
 h.c.openCapture('','',LINK_ENDS('eth1','eth1'));await settle();
 const u1='/static/capture-session.html#'+A64,u2='/static/capture-session.html#'+B64;let n=0;
 h.c.json=async(url,method,data)=>{n++;return n===1
  ?{sessions:[{id:A64,url:u1,label:'r1 eth1'}],refused:[{position:'Capture 2 of 2',label:'r2 eth1',interfaces:['eth1'],detail:'busy'}],message:'part'}
  :{sessions:[{id:B64,url:u2,label:'r2 eth1'}],refused:[],message:'Wireshark session started on the VM. Open the browser viewer.'};};
 h.$('capture-ends-list').checked=[{dataset:{captureEnd:'0'}},{dataset:{captureEnd:'1'}}];
 await h.$('capture-form').onsubmit({preventDefault(){}});assert.equal(h.$('capture-prepare').disabled,false,'a partial result keeps Start for the remaining one');
 await h.$('capture-form').onsubmit({preventDefault(){}});
 assert.equal(h.$('capture-prepare').disabled,true,'Start waits after a full success');
 assert.match(h.$('capture-status').textContent,/^2 Wireshark sessions started on the VM\. Open each with its link below\. Change the selection to start another capture\.$/);
 h.$('capture-ends').onchange();assert.equal(h.$('capture-prepare').disabled,false,'a changed selection releases Start');
});
test('C07 fix: a link end prints the veth only when it differs from the port, a started end is a readable line of its own, and the style sheet wraps the ends, the rows and the launch links',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8');
 assert.match(css,/@media \(max-width: 420px\) \{ #capture-ends-list \{ grid-template-columns: minmax\(0, 1fr\); \} \}/);
 assert.match(css,/\.capture-interface \{ flex-wrap: wrap; \}/);assert.match(css,/#capture-launches \.button \{ white-space: normal;/);assert.match(css,/#capture-launches \{ justify-content: flex-start; \}/);
});
