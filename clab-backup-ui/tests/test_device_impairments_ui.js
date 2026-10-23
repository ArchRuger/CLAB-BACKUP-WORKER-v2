// device-impairments.js: the device drawer's Impairments section (docs/parity-campaign/C05-DESIGN.md sections 4.1 and 5).
// The pure validator runs against the shared value table (tests/fixtures/impairment_values.json); the section runs against a
// small fake DOM (elements made on first use by id), a fake api() and a fake busyReason().
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const dir=path.join(__dirname,'../app/static');
const source=fs.readFileSync(path.join(dir,'device-impairments.js'),'utf8');
const table=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/impairment_values.json'),'utf8'));
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const HEX='b'.repeat(64);
function harness({caps=null,busy='',lab='L1'}={}){
 const els=new Map(),calls=[],doc={activeElement:null},writes={body:0};
 const make=id=>{
  const el={id,hidden:false,open:false,disabled:false,title:'',textContent:'',_html:'',listeners:{},dataset:{},
   addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn);},
   focus(){doc.activeElement=this;},
   fire(type,event){for(const fn of this.listeners[type]||[])fn(event);}};
  Object.defineProperty(el,'innerHTML',{get(){return this._html;},set(v){this._html=v;if(id==='imp-body')writes.body++;}});
  return el;
 };
 const $=id=>{if(!els.has(id))els.set(id,make(id));return els.get(id);};
 const handlers=[];
 const context=vm.createContext({$,esc,URLSearchParams,document:doc,activeId:lab,detailName:'r1',opCaps:caps,
  state:{operations:[]},Date,busyReason:()=>context.busyText,busyText:busy,
  opCapabilities:async()=>context.opCaps,
  api:async(url,options)=>{
   calls.push({url,body:options&&options.body?JSON.parse(options.body):null});
   const h=handlers.find(x=>url.startsWith(x.prefix));
   if(!h)throw Object.assign(new Error('no handler '+url),{status:500});
   const body=await h.fn(url,options);
   return {json:async()=>body};
  }});
 vm.runInContext(source,context,{filename:'device-impairments.js'});
 const section=$('details-impairments');
 const render=()=>context.renderDeviceImpairments({name:'r1',short_name:'router-1'});
 const on=(prefix,fn)=>handlers.unshift({prefix,fn});
 const ifs=(over={})=>({present:true,facts:{present:true,id:HEX,status:'running'},interfaces:[
  {name:'eth0',port:'',role:'management'},{name:'eth1',port:'Ethernet1',role:'data'},{name:'eth2',port:'Ethernet2',role:'data'}],...over});
 const row=(over={})=>({interface:'eth1',port:'Ethernet1',delay:'15ms',jitter:'2ms',loss:5,rate:0,corruption:0,...over});
 const standard=(rows=[row()],over={})=>{
  on('/operations/interfaces',()=>ifs(over.ifs));
  on('/operations/impairments?',()=>({devices:{r1:{present:true,id:HEX,impairments:rows}},interfaces:rows.length,complete:true,fetched_at:1}));
 };
 const open=async()=>{render();section.open=true;section.fire('toggle');await tick();await tick();await tick();};
 const click=(id,act,i)=>{const btn={disabled:$(id).disabled,dataset:{impAct:act,impI:String(i)}};section.fire('click',{target:{id,closest:()=>btn}});};
 const type=(i,field,value)=>section.fire('input',{target:{dataset:{impI:String(i),impF:field},value}});
 const get=name=>vm.runInContext(name,context);
 return {context,$,els,calls,section,render,on,ifs,row,standard,open,click,type,get,doc,writes};
}
const wire=(over={})=>({delay:'0ms',jitter:'0ms',loss:0,rate:0,corruption:0,...over});

test('impairmentProblem agrees with every case of the shared value table',()=>{
 const h=harness(),check=values=>h.context.impairmentProblem(JSON.parse(JSON.stringify(values)));
 for(const c of table.accepted)assert.equal(check(c.values),'',c.name);
 for(const c of table.refused){
  // JSON cannot tell 1000.0 from 1000 in JavaScript; the helper and the manager pin that case.
  if(c.name==='rate as a float')continue;
  assert.equal(check({...table.base,...c.values}),table.sentences[c.problem],c.name);
 }
});
test('typed text is normalised before it is checked',()=>{
 const h=harness(),w=raw=>JSON.parse(JSON.stringify(h.context.impWire(raw)));
 assert.deepEqual(w({delay:'20'}),wire({delay:'20ms'}));
 assert.deepEqual(w({delay:'007ms',jitter:' 5 '}),wire({delay:'7ms',jitter:'5ms'}));
 assert.deepEqual(w({delay:'000ms'}),wire());
 assert.deepEqual(w({loss:'-0'}),wire());
 assert.ok(Object.is(h.context.impWire({loss:'-0'}).loss,0));
 assert.equal(h.context.impairmentProblem(h.context.impWire({delay:'abc'})),table.sentences.time);
 assert.equal(h.context.impairmentProblem(h.context.impWire({delay:'10',loss:'x'})),table.sentences.percent);
 assert.equal(h.context.impairmentProblem(h.context.impWire({delay:'10',rate:'1.5'})),table.sentences.rate);
 assert.equal(h.context.impairmentProblem(h.context.impWire({})),table.sentences.zero);
 assert.equal(h.context.impairmentProblem(h.context.impWire({delay:'61s'})),table.sentences.time);
});
test('nothing is fetched until the section opens; opening reads interfaces and impairments once',async()=>{
 const h=harness();h.standard();h.render();
 assert.equal(h.calls.length,0);
 await h.open();
 assert.deepEqual(h.calls.map(c=>c.url).sort(),['/operations/impairments?lab_id=L1&node=r1','/operations/interfaces?lab_id=L1&node=r1']);
 const body=h.$('imp-body').innerHTML;
 assert.match(body,/Ethernet1/);assert.match(body,/value="15ms"/);assert.match(body,/aria-label="Delay on Ethernet1"/);
 assert.doesNotMatch(body,/eth0/,'the management interface is not listed');
 assert.match(body,/<th scope="col">Loss %<\/th>/);
 assert.doesNotMatch(body,/ style=/);
});
test('Apply is enabled only for a changed valid row, Reset only on an impaired row',async()=>{
 const h=harness();h.standard();await h.open();
 assert.equal(h.$('imp-apply-0').disabled,true,'untouched row');
 assert.equal(h.$('imp-reset-0').disabled,false,'impaired row');
 assert.equal(h.$('imp-reset-1').disabled,true,'plain row');
 assert.equal(h.$('imp-clear').disabled,false);
 h.type(1,'delay','20');
 assert.equal(h.$('imp-apply-1').disabled,false);
 h.type(1,'jitter','abc');
 assert.equal(h.$('imp-apply-1').disabled,true);
 assert.equal(h.$('imp-hint-1').textContent,table.sentences.time);
 h.type(1,'jitter','');h.type(1,'delay','');
 assert.equal(h.$('imp-apply-1').disabled,true);
 assert.equal(h.$('imp-hint-1').textContent,'','an untouched row has no hint');
 h.type(0,'delay','','');h.type(0,'jitter','');h.type(0,'loss','');
 assert.equal(h.$('imp-apply-0').disabled,true);
 assert.equal(h.$('imp-hint-0').textContent,table.sentences.zero);
});
test('Apply asks first, Keep as is changes nothing, Apply sends all five values and expected_id',async()=>{
 const h=harness();h.standard();await h.open();
 h.on('/operations/impairments/set',()=>({container:'c',impairments:[h.row(),h.row({interface:'eth2',port:'Ethernet2',delay:'20ms',jitter:'5ms',loss:1.5,rate:1000,corruption:0.5})]}));
 h.type(1,'delay','20');h.type(1,'jitter','5ms');h.type(1,'loss','1.5');h.type(1,'rate','1000');h.type(1,'corruption','0.5');
 h.click('imp-apply-1','apply',1);
 const q=h.$('imp-question-zone').innerHTML;
 assert.match(q,/role="group" aria-labelledby="imp-q-text"/);
 assert.match(q,/Set delay 20ms, jitter 5ms, loss 1\.5%, rate 1000 kbit, corruption 0\.5% on router-1 Ethernet2\? Traffic leaving this interface is shaped until you reset it\./);
 assert.match(q,/Keep as is/);
 assert.equal(h.doc.activeElement.id,'imp-keep','Keep as is is focused first');
 assert.equal(h.$('imp-apply-0').disabled,true,'one question at a time');
 h.click('imp-keep','cancel',0);
 assert.equal(h.calls.filter(c=>c.url.includes('/set')).length,0);
 assert.equal(h.$('imp-question-zone').innerHTML,'');assert.equal(h.$('imp-apply-1').disabled,false);
 h.click('imp-apply-1','apply',1);
 h.click('imp-confirm','confirm',0);
 await tick();await tick();
 const post=h.calls.find(c=>c.url==='/operations/impairments/set');
 assert.deepEqual(post.body,{lab_id:'L1',node:'r1',interface:'eth2',delay:'20ms',jitter:'5ms',loss:1.5,rate:1000,corruption:0.5,expected_id:HEX});
 assert.match(h.$('imp-status').textContent,/Impairments set on Ethernet2\./);
 assert.equal(h.doc.activeElement.id,'imp-reset-1','focus moves to the enabled Reset');
 assert.equal(h.$('imp-apply-1').disabled,true,'the row now equals the stored values');
});
test('Reset: changed false reads "had no impairments to remove"; changed true reads "removed"',async()=>{
 const h=harness();h.standard();await h.open();
 h.on('/operations/impairments/reset',()=>({container:'c',changed:false,impairments:[]}));
 h.click('imp-reset-0','reset',0);
 assert.match(h.$('imp-question-zone').innerHTML,/Remove the impairments on router-1 Ethernet1\?/);
 h.click('imp-confirm','confirm',0);await tick();await tick();
 assert.equal(h.calls.find(c=>c.url.endsWith('/reset')).body.expected_id,HEX);
 assert.equal(h.$('imp-status').textContent,'Ethernet1 had no impairments to remove.');
 assert.equal(h.$('imp-reset-0').disabled,true);
 const g=harness();g.standard();await g.open();
 g.on('/operations/impairments/reset',()=>({container:'c',changed:true,impairments:[]}));
 g.click('imp-reset-0','reset',0);g.click('imp-confirm','confirm',0);await tick();await tick();
 assert.equal(g.$('imp-status').textContent,'Impairments removed from Ethernet1.');
 assert.equal(g.doc.activeElement.id,'imp-status','nothing enabled in the row: focus goes to the status');
});
test('Clear: question counts interfaces; full, partial and budget outcomes are worded',async()=>{
 const h=harness();h.standard([{interface:'eth1',delay:'15ms',jitter:'',loss:0,rate:0,corruption:0},{interface:'eth2',delay:'',jitter:'',loss:3,rate:0,corruption:0}]);await h.open();
 h.click('imp-clear','clear',-1);
 assert.match(h.$('imp-question-zone').innerHTML,/Remove every impairment on router-1 \(2 interfaces\)\?/);
 h.on('/operations/impairments/clear',()=>({cleared:2,total:2,failed:[],remaining:[],complete:true,devices:{r1:{impairments:[]}}}));
 h.click('imp-confirm','confirm',0);await tick();await tick();
 assert.deepEqual(h.calls.find(c=>c.url.endsWith('/clear')).body,{lab_id:'L1',node:'r1'});
 assert.equal(h.$('imp-status').textContent,'2 interfaces cleared.');
 assert.equal(h.$('imp-clear').disabled,true);
 // partial
 const p=harness();p.standard([{interface:'eth1',delay:'15ms',jitter:'',loss:0,rate:0,corruption:0},{interface:'eth2',delay:'',jitter:'',loss:3,rate:0,corruption:0}]);await p.open();
 p.on('/operations/impairments/clear',()=>({cleared:1,total:2,failed:[{node:'r1',interface:'eth2',reason:'Containerlab on the VM could not reset the impairment on eth2.'}],remaining:[],complete:true,devices:{r1:{impairments:[{interface:'eth2',delay:'',jitter:'',loss:3,rate:0,corruption:0}]}}}));
 p.click('imp-clear','clear',-1);p.click('imp-confirm','confirm',0);await tick();await tick();
 assert.equal(p.$('imp-status').textContent,'1 of 2 interfaces cleared; Ethernet2: Containerlab on the VM could not reset the impairment on eth2. Try again.');
 assert.equal(p.$('imp-reset-1').disabled,false,'the row that stayed impaired keeps Reset');
 // budget
 const b=harness();b.standard([{interface:'eth1',delay:'15ms',jitter:'',loss:0,rate:0,corruption:0},{interface:'eth2',delay:'',jitter:'',loss:3,rate:0,corruption:0}]);await b.open();
 b.on('/operations/impairments/clear',()=>({cleared:1,total:2,failed:[],remaining:[{node:'r1',interface:'eth2'}],complete:true,devices:{}}));
 b.click('imp-clear','clear',-1);b.click('imp-confirm','confirm',0);await tick();await tick();
 assert.equal(b.$('imp-status').textContent,'1 of 2 interfaces cleared; the rest were not reached in time. Try again.');
});
test('the three busy sentences disable every control with the sentence; Retry clears the third',async()=>{
 for(const sentence of ['Wait for the current lab operation to finish.','Wait for the lab backup or login job to finish.','Another lab operation is running on the VM (it may belong to another lab); try again when it has finished.']){
  const h=harness();h.standard();await h.open();
  h.on('/operations/impairments/reset',()=>{throw Object.assign(new Error(sentence),{status:409});});
  h.click('imp-reset-0','reset',0);h.click('imp-confirm','confirm',0);await tick();await tick();
  assert.equal(h.$('imp-busy').textContent,sentence);assert.equal(h.$('imp-busy').hidden,false);
  assert.equal(h.$('imp-status').textContent,'','the sentence is shown once: not again in the status');assert.equal(h.$('imp-error').textContent,'');
  assert.equal(h.$('imp-reset-0').disabled,true);assert.equal(h.$('imp-reset-0').title,sentence);
  assert.equal(h.$('imp-clear').disabled,true);
  assert.equal(h.$('imp-retry').hidden,false);
  h.render();assert.equal(h.$('imp-reset-0').disabled,true,'a poll keeps it blocked');
  h.$('imp-retry').dataset={};h.section.fire('click',{target:{id:'imp-retry',closest:()=>null}});
  assert.equal(h.$('imp-reset-0').disabled,false);assert.equal(h.$('imp-retry').hidden,true);
  assert.equal(h.doc.activeElement.id,'imp-reset-0','focus lands on a visible control, not the hidden Retry');
 }
});
test('a local busy lab disables the controls and re-enables them when it clears',async()=>{
 const h=harness();h.standard();await h.open();
 h.context.busyText='Deploy is running.';h.render();
 assert.equal(h.$('imp-reset-0').disabled,true);assert.equal(h.$('imp-reset-0').title,'Deploy is running.');
 assert.equal(h.$('imp-busy').textContent,'Deploy is running.');
 h.context.busyText='';h.render();
 assert.equal(h.$('imp-reset-0').disabled,false);assert.equal(h.$('imp-busy').hidden,true);
});
test('typed values, focus and an open question survive the poll; the markup is written once',async()=>{
 const h=harness();h.standard();await h.open();
 h.type(1,'delay','20');
 h.click('imp-apply-1','apply',1);
 const before=h.writes.body,question=h.$('imp-question-zone').innerHTML;
 h.context.busyText='A backup is running.';h.render();h.context.busyText='';h.render();h.render();
 assert.equal(h.writes.body,before,'the body is not rewritten by the poll');
 assert.equal(h.$('imp-question-zone').innerHTML,question,'the open question stays');
 assert.equal(h.doc.activeElement.id,'imp-keep');
 assert.equal(h.get('imp').typed.eth2.delay,'20');
});
test('after an operation: refresh when idle; a Refresh line when a row is edited or a question is open',async()=>{
 const h=harness();h.standard();await h.open();
 h.context.state.operations=[{lab_id:'L1',finished:'2026-10-23T10:00:00Z'}];
 const n=h.calls.length;h.render();await tick();await tick();await tick();
 assert.equal(h.calls.length,n+2,'idle: re-read');
 h.type(1,'delay','30');
 h.context.state.operations=[{lab_id:'L1',finished:'2026-10-23T10:05:00Z'}];
 const m=h.calls.length;h.render();await tick();
 assert.equal(h.calls.length,m,'edited: no re-read');
 assert.equal(h.$('imp-stale').hidden,false);
 assert.equal(h.get('imp').typed.eth2.delay,'30');
 h.context.state.operations=[{lab_id:'L2',finished:'2026-10-23T11:00:00Z'}];h.render();
 assert.equal(h.calls.length,m,'another lab does not count');
 h.section.fire('click',{target:{id:'imp-refresh',closest:()=>null}});await tick();await tick();await tick();
 assert.equal(h.$('imp-stale').hidden,true);
 assert.equal(h.get('imp').typed.eth2.delay,'','Refresh re-reads the stored values');
});
test('capabilities: known lacking hides the section; unknown counts as available; open re-checks',async()=>{
 const lacking=harness({caps:{actions:{restart:{available:true}}}});lacking.render();
 assert.equal(lacking.section.hidden,true);
 const have=harness({caps:{actions:{impairments:{available:true}}}});have.render();assert.equal(have.section.hidden,false);
 const unknown=harness();unknown.render();assert.equal(unknown.section.hidden,false);
 unknown.context.opCapabilities=async()=>{unknown.context.opCaps={actions:{}};return unknown.context.opCaps;};
 await unknown.open();
 assert.match(unknown.$('imp-body').innerHTML,/Not available on this VM — its containerlab or helper cannot set impairments \(see Diagnostics\)/);
 assert.equal(unknown.section.hidden,false,'the sentence stays for a section the person opened');
 assert.equal(unknown.calls.length,0);
});
test('states: not running, no container, no links, load error with Retry',async()=>{
 const a=harness();a.standard([],{ifs:{facts:{present:true,id:HEX,status:'exited'}}});await a.open();
 assert.match(a.$('imp-body').innerHTML,/router-1 is not running\. Impairments can be set only on a running device\./);
 const b=harness();b.standard([],{ifs:{present:false,facts:{present:false}}});await b.open();
 assert.match(b.$('imp-body').innerHTML,/No container for this device yet\./);
 const c=harness();c.standard([],{ifs:{interfaces:[{name:'eth0',port:'',role:'management'}]}});await c.open();
 assert.match(c.$('imp-body').innerHTML,/This device has no lab links\./);
 const d=harness();let fail=true;
 d.on('/operations/interfaces',()=>{if(fail)throw Object.assign(new Error('The VM could not be reached.'),{status:503});return d.ifs();});
 d.on('/operations/impairments?',()=>({devices:{r1:{present:true,id:HEX,impairments:[]}},complete:true}));
 await d.open();
 assert.equal(d.$('imp-status').textContent,'The VM could not be reached.');assert.equal(d.$('imp-retry').hidden,false);
 fail=false;d.section.fire('click',{target:{id:'imp-retry',closest:()=>null}});await tick();await tick();await tick();
 assert.match(d.$('imp-body').innerHTML,/Ethernet1/);assert.equal(d.$('imp-retry').hidden,true);
});
test('an error keeps the typed values and shows the manager sentence in the status and the error line',async()=>{
 const h=harness();h.standard();await h.open();
 h.on('/operations/impairments/set',()=>{throw Object.assign(new Error('router-1 is not running. Impairments can be set only on a running device.'),{status:409});});
 h.type(1,'delay','20');h.click('imp-apply-1','apply',1);h.click('imp-confirm','confirm',0);await tick();await tick();
 assert.match(h.$('imp-status').textContent,/is not running/);assert.match(h.$('imp-error').textContent,/is not running/);
 assert.equal(h.get('imp').typed.eth2.delay,'20');
 assert.equal(h.$('imp-apply-1').disabled,false);
});
test('a successful change tells the map to re-read; a new device or close resets the section',async()=>{
 const h=harness();h.standard();await h.open();
 const seen=[];h.context.opLoadImpairments=k=>seen.push(k);
 h.on('/operations/impairments/set',()=>({container:'c',impairments:[h.row(),h.row({interface:'eth2',port:'Ethernet2',delay:'9ms',jitter:'',loss:0})]}));
 h.type(1,'delay','9');h.click('imp-apply-1','apply',1);h.click('imp-confirm','confirm',0);await tick();await tick();
 assert.deepEqual(seen,['L1']);
 h.context.resetDeviceImpairments();
 assert.equal(h.section.open,false);assert.equal(h.$('imp-body').innerHTML,'');assert.equal(h.get('imp').rows.length,0);
});
test('the script holds no inline style, no document or window listener and escapes its interpolations',()=>{
 assert.doesNotMatch(source,/style=|\.style\b|window\.addEventListener|document\.addEventListener/);
 assert.match(source,/esc\(/);
});

test('B2: the map refresh runs once per successful Apply, Reset and Clear and never on a refusal',async()=>{
 const h=harness();h.standard();await h.open();
 const maps=[];h.context.opLoadImpairments=id=>maps.push(id);
 h.on('/operations/impairments/set',()=>({container:'c',impairments:[h.row(),h.row({interface:'eth2',port:'Ethernet2',delay:'9ms',jitter:'',loss:0})]}));
 h.type(1,'delay','9');h.click('imp-apply-1','apply',1);h.click('imp-confirm','confirm',0);await tick();await tick();
 assert.deepEqual(maps,['L1'],'Apply');
 h.on('/operations/impairments/reset',()=>({changed:true,impairments:[h.row()]}));
 h.click('imp-reset-1','reset',1);h.click('imp-confirm','confirm',0);await tick();await tick();
 assert.deepEqual(maps,['L1','L1'],'Reset');
 h.on('/operations/impairments/clear',()=>({cleared:1,total:1,failed:[],remaining:[],devices:{r1:{impairments:[]}}}));
 h.click('imp-clear','clear',-1);h.click('imp-confirm','confirm',0);await tick();await tick();
 assert.deepEqual(maps,['L1','L1','L1'],'Clear');
});
test('B2: a refused change does not refresh the map',async()=>{
 const h=harness();h.standard();await h.open();
 const maps=[];h.context.opLoadImpairments=id=>maps.push(id);
 h.on('/operations/impairments/set',()=>{throw new Error('The container changed; refresh.');});
 h.type(1,'delay','9');h.click('imp-apply-1','apply',1);h.click('imp-confirm','confirm',0);await tick();await tick();
 assert.deepEqual(maps,[]);
 assert.match(h.$('imp-error').textContent,/The container changed/);
});
test('a reload started by the poll keeps values typed while it was fetching and an open question; Refresh still replaces them',async()=>{
 const h=harness();h.standard();await h.open();
 let release;const gate=new Promise(res=>{release=res;});
 h.on('/operations/impairments?',async()=>{await gate;return {devices:{r1:{present:true,id:HEX,impairments:[h.row()]}},complete:true};});
 h.context.state.operations=[{lab_id:'L1',finished:'2026-10-23T10:00:00Z'}];
 h.render();await tick();
 h.type(1,'delay','40');h.click('imp-apply-1','apply',1);
 assert.ok(h.get('imp').question,'a question is open while the reload is in flight');
 release();await tick();await tick();await tick();
 assert.equal(h.get('imp').typed.eth2.delay,'40','typed text survives');
 assert.ok(h.get('imp').question,'the question survives');
 assert.equal(h.$('imp-stale').hidden,false,'the Refresh line is shown');
 h.section.fire('click',{target:{id:'imp-refresh',closest:()=>null}});await tick();await tick();await tick();
 assert.equal(h.get('imp').typed.eth2.delay,'');assert.equal(h.get('imp').question,null);
});

test('Escape inside an open question closes the question only; without a question it is left to the drawer',async()=>{
 const h=harness();h.standard();await h.open();
 h.type(1,'delay','40');h.click('imp-apply-1','apply',1);
 const ev={key:'Escape',stopped:0,prevented:0,preventDefault(){this.prevented++;},stopPropagation(){this.stopped++;}};
 h.section.fire('keydown',ev);
 assert.equal(h.get('imp').question,null);assert.equal(ev.stopped,1);assert.equal(ev.prevented,1);
 assert.equal(h.$('imp-question-zone').innerHTML,'');
 const again={key:'Escape',stopped:0,prevented:0,preventDefault(){this.prevented++;},stopPropagation(){this.stopped++;}};
 h.section.fire('keydown',again);assert.equal(again.stopped,0,'no question: the drawer handles Escape');
});
