const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/capture.js'),'utf8');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function harness(){
 const elements=new Map(),timers=[];
 function $(id){if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',textContent:'',hidden:false,open:false,disabled:false,listeners:{},checked:[],addEventListener(k,fn){this.listeners[k]=fn;},removeAttribute(k){delete this[k];},showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();},querySelectorAll(){return this.checked;}});return elements.get(id);}
 const calls=[];
 const c=vm.createContext({$,esc,URLSearchParams,crypto:require('node:crypto').webcrypto,Uint8Array,confirm:()=>true,activeId:'lab',current:()=>({name:'demo'}),map:$('map'),closeNodeMenu:()=>{},notify:()=>{},clearTimeout:()=>{},setTimeout:fn=>{timers.push(fn);return timers.length;},
 api:async url=>{calls.push(url);return {json:async()=>url.includes('/status')?{enabled:true}:{targets:[{id:'a'.repeat(64),name:'clab-demo-r1',kind:'docker',prefix:'',interfaces:['lo','eth2']}],message:'live'}};},
 json:async(url,method,data)=>{calls.push({url,method,data});return {url:'/static/capture-session.html#'+'a'.repeat(64),id:'a'.repeat(64),message:'Session started.'};}});
 vm.runInContext(source,c);$('capture-dialog').open=true;
 return {c,$,calls,timers};
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
 assert.equal(calls.find(c=>c?.url==='/capture/launch').data.interfaces[0],'eth2');assert.equal($('capture-launch').hidden,false);assert.match($('capture-launch').href,/^\/static\/capture-session\.html#/);
 $('capture-launch').onclick();assert.match($('capture-status').textContent,/Wireshark opened in a new tab/);
 assert.equal(timers.length,0);
});
test('changing selection clears a prepared link and releases the prepare button',async()=>{
 const {c,$}=harness();await c.refreshCaptureTargets();$('capture-launch').href='/static/capture-session.html#'+'b'.repeat(64);$('capture-launch').hidden=false;$('capture-prepare').disabled=true;
 $('capture-interfaces').checked=[{value:'eth2'}];
 $('capture-interfaces').onchange();assert.equal($('capture-launch').hidden,true);assert.equal($('capture-launch').href,undefined);assert.equal($('capture-prepare').disabled,false);
});
test('prepare stays disabled until an interface is ticked and a target-less dialog says so',async()=>{
 const {c,$}=harness();await c.refreshCaptureTargets();
 assert.equal($('capture-prepare').disabled,true);
 $('capture-interfaces').checked=[];$('capture-interfaces').onchange();assert.equal($('capture-prepare').disabled,true);
 $('capture-interfaces').checked=[{value:'eth2'}];$('capture-interfaces').onchange();assert.equal($('capture-prepare').disabled,false);
 $('capture-target').value='';c.renderCaptureInterfaces();
 assert.match($('capture-interfaces').innerHTML,/Choose a device above/);assert.equal($('capture-prepare').disabled,true);
});
test('shared namespaces and loopback-only targets are labelled, the kind shows only for the whole VM, and aliases are searchable',()=>{
 const {c,$}=harness();
 vm.runInContext(`captureTargets=[{id:'h',name:'systemd(1)',kind:'proc',prefix:'',interfaces:['ens33','lo'],aliases:['containerlab-node-manager-backup-ui-1']},{id:'s',name:'sandbox',kind:'proc',prefix:'',interfaces:['lo'],aliases:[]}];`,c);
 c.filterCaptureTargets();
 assert.match($('capture-target').innerHTML,/also: containerlab-node-manager-backup-ui-1/);assert.match($('capture-target').innerHTML,/sandbox · 1 interfaces · loopback only/);assert.doesNotMatch($('capture-target').innerHTML,/\(proc\)/,'inside a lab every row is a device');
 $('capture-scope').value='host';c.filterCaptureTargets();assert.match($('capture-target').innerHTML,/sandbox \(proc\) · 1 interfaces · loopback only/);$('capture-scope').value='';
 $('capture-search').value='backup-ui';c.filterCaptureTargets();
 assert.equal($('capture-target').value,'h');assert.doesNotMatch($('capture-target').innerHTML,/sandbox/);
 vm.runInContext(`captureTargets=[{id:'n',name:'clab-demo-r1',kind:'docker',prefix:'',interfaces:['eth0'],aliases:['CliShell(1)','CliShell(2)','CliShell(3)','CliShell(4)']}];`,c);
 $('capture-search').value='';c.filterCaptureTargets();
 assert.match($('capture-target').innerHTML,/also: CliShell\(1\), CliShell\(2\) \+2 more/);
 $('capture-search').value='clishell(4)';c.filterCaptureTargets();assert.equal($('capture-target').value,'n');
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
 $('capture-dialog').close();finish({url:'/static/capture-session.html#'+'b'.repeat(64),message:'old'});await pending;assert.equal($('capture-launch').href,undefined);
});
test('out of order discovery cannot replace newer results',async()=>{
 const {c,$}=harness();let finish;c.api=()=>new Promise(resolve=>finish=resolve);
 const pending=c.refreshCaptureTargets();$('capture-dialog').close();finish({json:async()=>({enabled:true})});await pending;
 assert.equal($('capture-target').innerHTML,'');
});
test('disabled providers and outages have an actionable local message',async()=>{
 const {c,$}=harness();c.api=async()=>({json:async()=>({enabled:false,message:'Configure Edgeshark'})});await c.refreshCaptureTargets();assert.equal($('capture-status').textContent,'Configure Edgeshark');assert.equal($('capture-prepare').disabled,true);
 c.api=async()=>{throw Error('Provider unreachable');};await c.refreshCaptureTargets();assert.equal($('capture-status').textContent,'Provider unreachable');assert.equal($('capture-search').disabled,false);
});
test('untrusted labels are escaped and unsupported launch schemes cannot navigate',async()=>{
 const {c,$}=harness();vm.runInContext(`captureTargets=[{id:'a',name:'<img onerror=x>',prefix:'<script>',kind:'docker',interfaces:['eth2']}];`,c);c.filterCaptureTargets();assert.doesNotMatch($('capture-target').innerHTML,/<img|<script>/);assert.match($('capture-target').innerHTML,/&lt;img/);
 $('capture-interfaces').checked=[{value:'eth2'}];c.json=async()=>({url:'javascript:alert(1)'});await $('capture-form').onsubmit({preventDefault(){}});assert.equal($('capture-launch').href,undefined);assert.match($('capture-status').textContent,/Unsupported/);
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
test('a link opens on its first endpoint with that port ticked',async()=>{
 const h=mapHarness(['eth0','eth1','eth2'],[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}],[{node:'r1',interface:'eth2'},{node:'r2',interface:'eth2'}]]);
 vm.runInContext("activeId='lab'",h.c);
 h.c.openCapture('','',[{node:'clab-demo-r1',label:'r1',interface:'eth2'},{node:'clab-demo-r2',label:'r2',interface:'eth2'}]);
 await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
 assert.equal(h.$('capture-context').textContent,'Link endpoint: r1: eth2');
 assert.match(h.$('capture-interfaces').innerHTML,/value="eth2" checked/);assert.doesNotMatch(h.$('capture-interfaces').innerHTML,/value="eth1" checked/);
 assert.equal(h.$('capture-prepare').disabled,false);
});
test('every rendered link including coincident nodes exposes both endpoint actions',()=>{
 const {c}=harness();vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/topology-render.js'),'utf8'),c);
 for(const x of [0,200]){
  const nodes=new Map([['a',{label:'R1',inventory_name:'node1',x:0,y:0}],['b',{label:'R2',inventory_name:'node2',x,y:0}]]);
  const markup=c.topologyLink([{node:'a',interface:'eth2'},{node:'b',interface:'eth1'}],nodes,0,{});
  assert.match(markup,/data-capture-endpoints=/);assert.match(markup,/node1/);assert.match(markup,/node2/);assert.match(markup,/role="button"/);assert.match(markup,/tabindex="0"/);
 }
});
