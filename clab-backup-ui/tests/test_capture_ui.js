const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/capture.js'),'utf8');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function harness(){
 const elements=new Map(),timers=[];
 function $(id){if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',textContent:'',hidden:false,open:false,disabled:false,listeners:{},checked:[],addEventListener(k,fn){this.listeners[k]=fn;},removeAttribute(k){delete this[k];},showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();},querySelectorAll(){return this.checked;}});return elements.get(id);}
 const calls=[];
 const c=vm.createContext({$,esc,URLSearchParams,activeId:'lab',current:()=>({name:'demo'}),map:$('map'),closeNodeMenu:()=>{},notify:()=>{},clearTimeout:()=>{},setTimeout:fn=>{timers.push(fn);return timers.length;},
 api:async url=>{calls.push(url);return {json:async()=>url.includes('/status')?{enabled:true}:{targets:[{id:'a'.repeat(64),name:'clab-demo-r1',kind:'docker',prefix:'',interfaces:['lo','eth2']}],message:'live'}};},
 json:async(url,method,data)=>{calls.push({url,method,data});return {uri:'packetflix:ws://localhost:5001/capture?container=fixture',message:'Open Wireshark to start.'};}});
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
 await c.refreshCaptureTargets();assert.ok(calls.includes('/capture/targets?'));assert.doesNotMatch($('capture-interfaces').innerHTML,/checked/);assert.match($('capture-status').textContent,/Select its Linux interface explicitly/);
});
test('handoff requires selection and prepares an explicit native link',async()=>{
 const {c,$,calls,timers}=harness();await c.refreshCaptureTargets();
 await $('capture-form').onsubmit({preventDefault(){}});assert.match($('capture-status').textContent,/at least one/);
 $('capture-interfaces').checked=[{value:'eth2'}];await $('capture-form').onsubmit({preventDefault(){}});
 assert.equal(calls.at(-1).data.interfaces[0],'eth2');assert.equal($('capture-launch').hidden,false);assert.match($('capture-launch').href,/^packetflix:ws:/);
 $('capture-launch').onclick();assert.match($('capture-status').textContent,/handoff requested/);
 timers.at(-1)();assert.equal($('capture-launch').hidden,true);assert.equal($('capture-launch').href,undefined);
});
test('changing selection clears a prepared link and releases the prepare button',async()=>{
 const {c,$}=harness();await c.refreshCaptureTargets();$('capture-launch').href='packetflix:ws://old';$('capture-launch').hidden=false;$('capture-prepare').disabled=true;
 $('capture-interfaces').onchange();assert.equal($('capture-launch').hidden,true);assert.equal($('capture-launch').href,undefined);assert.equal($('capture-prepare').disabled,false);
});
test('closing during an in-flight launch cannot restore a stale link',async()=>{
 const {c,$}=harness();await c.refreshCaptureTargets();$('capture-interfaces').checked=[{value:'eth2'}];let finish;
 c.json=()=>new Promise(resolve=>finish=resolve);const pending=$('capture-form').onsubmit({preventDefault(){}});
 $('capture-dialog').close();finish({uri:'packetflix:ws://old',message:'old'});await pending;assert.equal($('capture-launch').href,undefined);
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
 $('capture-interfaces').checked=[{value:'eth2'}];c.json=async()=>({uri:'javascript:alert(1)'});await $('capture-form').onsubmit({preventDefault(){}});assert.equal($('capture-launch').href,undefined);assert.match($('capture-status').textContent,/Unsupported/);
});
test('every rendered link including coincident nodes exposes both endpoint actions',()=>{
 const {c}=harness();vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/topology-render.js'),'utf8'),c);
 for(const x of [0,200]){
  const nodes=new Map([['a',{label:'R1',inventory_name:'node1',x:0,y:0}],['b',{label:'R2',inventory_name:'node2',x,y:0}]]);
  const markup=c.topologyLink([{node:'a',interface:'eth2'},{node:'b',interface:'eth1'}],nodes,0,{});
  assert.match(markup,/data-capture-endpoints=/);assert.match(markup,/node1/);assert.match(markup,/node2/);assert.match(markup,/role="button"/);assert.match(markup,/tabindex="0"/);
 }
});
