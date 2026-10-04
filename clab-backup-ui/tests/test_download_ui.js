// Exercise the production UI handlers with a small DOM/fetch harness.
const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function harness(){
 const elements=new Map(),downloads=[],requests=[];
 function element(){return {dataset:{},value:'',innerHTML:'',open:false,disabled:false,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},showModal(){this.open=true;},appendChild(){},remove(){},click(){downloads.push(this.download);}};}
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},createElement:element,body:element()};
 const items=new Map();
 const context=vm.createContext({document,sessionStorage:{getItem:k=>items.get(k),setItem:(k,v)=>items.set(k,v)},setTimeout:()=>0,clearTimeout(){},setInterval(){},URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},URLSearchParams,Blob,console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8'),context);
 context.fetch=async(url)=>{requests.push(url);return {ok:true,status:200,headers:{get:()=>context.disposition},blob:async()=>new Blob(['config'])};};
 return {context,document,downloads,requests};
}
test('individual device zero uses its endpoint and server filename',async()=>{
 const h=harness();h.context.disposition='attachment; filename="CEOS_SW1_2026-09-10_01-04UTC.conf"';
 const button={disabled:false,dataset:{download:'job1',nodeIndex:'0',filename:'wrong.txt'},hasAttribute:()=>true};
 await h.document.getElementById('jobs').listeners.click({target:{closest:selector=>selector==='[data-download]'?button:null}});
 assert.deepEqual(h.requests,['/api/jobs/job1/nodes/0/download']);
 assert.deepEqual(h.downloads,['CEOS_SW1_2026-09-10_01-04UTC.conf']);assert.equal(button.disabled,false);
});
test('ZIP handler honors Content-Disposition instead of old generated name',async()=>{
 const h=harness();h.context.disposition="attachment; filename*=utf-8''BGP_TheoryToPractice_2026-09-10_01-02.zip";
 const button={disabled:false,dataset:{download:'job1',filename:'wrong.zip'},hasAttribute:()=>false};
 await h.document.getElementById('jobs').listeners.click({target:{closest:selector=>selector==='[data-download]'?button:null}});
 assert.deepEqual(h.requests,['/api/jobs/job1/download']);
 assert.deepEqual(h.downloads,['BGP_TheoryToPractice_2026-09-10_01-02.zip']);
});
test('history renders a button only for successful configurations and labels UTC',()=>{
 const h=harness();
 vm.runInContext(`state={labs:[{id:'lab'}],jobs:[{id:'job',lab_id:'lab',status:'partial',operation:'backup',started:'2026-09-10T01:02:03Z',archive_name:'Lab_2026-09-10_01-02.zip',nodes:[{name:'SW1',status:'succeeded',download_name:'CEOS_SW1_2026-09-10_01-04UTC.conf',captured_at:'2026-09-10T01:04:00Z'},{name:'failed',status:'failed'}]}]};activeId='lab';renderJobs();`,h.context);
 const html=h.document.getElementById('jobs').innerHTML;
 assert.match(html,/data-node-index="0"/);assert.doesNotMatch(html,/data-node-index="1"/);
 assert.match(html,/Download all \(ZIP\)/);assert.match(html,/2026-09-10 01:04:00 UTC/);
 // The topology travels with every backup (UI/UX changes 2, item 10): the row says so and where the text came from.
 vm.runInContext(`state.jobs[0].topology={file:'topology.clab.yml',source:'vm',path:'/labs/bgp.clab.yml',annotations_file:'topology.clab.yml.annotations.json'};renderJobs();`,h.context);
 assert.match(h.document.getElementById('jobs').innerHTML,/Topology and map embedded with this backup \(the files beside the deployed topology on the VM\)\./);
 vm.runInContext(`state.jobs[0].topology={file:'topology.clab.yml',source:'manager'};renderJobs();`,h.context);
 assert.match(h.document.getElementById('jobs').innerHTML,/Topology embedded with this backup \(the manager's copy\)\./);
 vm.runInContext(`delete state.jobs[0].topology;renderJobs();`,h.context);
 assert.doesNotMatch(h.document.getElementById('jobs').innerHTML,/embedded with this backup/,'a capture taken before carries no such line');
 vm.runInContext(`state.jobs[0].operation='test';renderJobs();`,h.context);
 assert.doesNotMatch(h.document.getElementById('jobs').innerHTML,/data-download=/);
});

test('per-node backup sends an explicit target; lab backup preserves the existing request',async()=>{
 const h=harness();
 vm.runInContext(`activeId='lab';captured=[];json=async(...args)=>captured.push(args);refresh=async()=>{};notify=()=>{};`,h.context);
 await vm.runInContext(`startJob('backup',['PE1'])`,h.context);
 await vm.runInContext(`startJob('backup')`,h.context);
 const captured=JSON.parse(vm.runInContext('JSON.stringify(captured)',h.context));
 assert.deepEqual(captured,[['/labs/lab/jobs','POST',{operation:'backup',node_names:['PE1']}],['/labs/lab/jobs','POST',{operation:'backup'}]]);
});

test('SSH action opens a separate tab with encoded node identity and no credentials',async()=>{
 const h=harness();h.context.opened=[];h.context.window={open:(...args)=>h.context.opened.push(args)};
 vm.runInContext(`activeId='lab';state.labs=[{id:'lab',name:'Test lab'}];`,h.context);
 await h.document.getElementById('nodes').listeners.click({target:{closest:()=>({dataset:{terminal:'PE1 & edge'}})}});
 assert.equal(h.context.opened[0][1],'_blank');
 const url=h.context.opened[0][0];assert.match(url,/terminal\.html#/);assert.match(url,/node=PE1\+%26\+edge/);assert.doesNotMatch(url,/token|password/);
});

test('connection state stays scoped to its lab and node rows contain no resource controls',()=>{
 const h=harness();
 vm.runInContext(`activeId='a';devicesTechnical=true;healthState={lab:'b',nodes:[{name:'PE1',ssh:{status:'reachable'}}]};state={labs:[{id:'a',nodes:[{name:'PE1',address:'host',port:22,platform:'arista_ceos',readiness:'Ready',ssh_ready:true,enabled:true}],profiles:[],defaults:{}}],jobs:[],platforms:{}};renderNodes();`,h.context);
 assert.equal(vm.runInContext(`nodeHealth('PE1')`,h.context),null);
 const html=h.document.getElementById('nodes').innerHTML;
 assert.match(html,/Not checked/);assert.match(html,/data-terminal=/);
 assert.doesNotMatch(html,/CPU|memory|metrics|container|monitor/i);
});

test('node history keeps saved job indexes when other devices precede the target',()=>{
 const h=harness();
 vm.runInContext(`activeId='lab';detailName='PE1';state={platforms:{},labs:[{id:'lab',nodes:[{name:'PE1',address:'host',port:22,platform:'arista_ceos'}],profiles:[],defaults:{}}],jobs:[{id:'job',lab_id:'lab',operation:'backup',status:'partial',created:'2026-09-10T01:00:00Z',nodes:[{name:'other',status:'failed'},{name:'PE1',status:'succeeded',download_name:'PE1.conf'}]}]};renderDetails();`,h.context);
 const html=h.document.getElementById('node-history').innerHTML;
 assert.match(html,/data-node-index="1"/);assert.match(html,/Latest successful backup/);
});

test('rejected backup-selection edit restores the checkbox',async()=>{
 const h=harness();
 vm.runInContext(`activeId='lab';state={platforms:{},labs:[{id:'lab',nodes:[{name:'PE1',enabled:false,address:'host',port:22,platform:'arista_ceos'}],profiles:[],defaults:{}}],jobs:[]};json=async()=>{throw new Error('fixture edit rejected');};notify=()=>{};`,h.context);
 const target={dataset:{enable:'PE1'},checked:true};
 await h.document.getElementById('nodes').listeners.change({target});
 assert.equal(target.checked,false);
});

// L-32: blocked site data (sessionStorage throws) must not break opening a lab.
test('selectLab still opens the lab and paints when sessionStorage is blocked',()=>{
 const h=harness();
 h.context.sessionStorage={getItem(){throw new Error('SecurityError');},setItem(){throw new Error('SecurityError');},removeItem(){throw new Error('SecurityError');}};
 vm.runInContext(`state={labs:[{id:'a'}],jobs:[],platforms:{}};painted=0;render=()=>{painted++;};selectLab('a','devices');`,h.context);
 assert.equal(vm.runInContext('activeId',h.context),'a');assert.equal(vm.runInContext('tab',h.context),'devices');
 assert.equal(vm.runInContext('painted',h.context),1,'render() ran after the blocked write');
});

// L-33: refresh() applies /state responses in request order.
function stateFetch(h){
 const pending=[];
 h.context.fetch=url=>new Promise((resolve,reject)=>pending.push({url,resolve:body=>resolve({ok:true,status:200,headers:{get:()=>''},json:async()=>body}),reject}));
 return pending;
}
const labIds=h=>JSON.parse(vm.runInContext('JSON.stringify(state.labs.map(l=>l.id))',h.context));
test('a slow older poll cannot overwrite the newer refresh or send the student Home',async()=>{
 const h=harness();vm.runInContext(`render=()=>{};`,h.context);
 const pending=stateFetch(h);
 const poll=vm.runInContext('refresh()',h.context),action=vm.runInContext('refresh()',h.context);
 pending[1].resolve({labs:[{id:'new'}],jobs:[],platforms:{}});await action;
 vm.runInContext(`activeId='new'`,h.context);
 pending[0].resolve({labs:[],jobs:[],platforms:{}});await poll;
 assert.equal(vm.runInContext('activeId',h.context),'new','the stale response did not reset the open lab');
 assert.deepEqual(labIds(h),['new']);
});
test('responses that arrive in order are each applied, and a failed newer refresh does not block an older answer',async()=>{
 const h=harness();vm.runInContext(`render=()=>{};`,h.context);
 const pending=stateFetch(h);
 const first=vm.runInContext('refresh()',h.context),second=vm.runInContext('refresh()',h.context);
 pending[0].resolve({labs:[{id:'a'}],jobs:[],platforms:{}});await first;
 assert.deepEqual(labIds(h),['a']);
 pending[1].resolve({labs:[{id:'a'},{id:'b'}],jobs:[],platforms:{}});await second;
 assert.deepEqual(labIds(h),['a','b']);
 const older=vm.runInContext('refresh()',h.context),newer=vm.runInContext('refresh()',h.context);
 pending[3].reject(new Error('down'));await assert.rejects(newer,/down/);
 pending[2].resolve({labs:[{id:'c'}],jobs:[],platforms:{}});await older;
 assert.deepEqual(labIds(h),['c'],'nothing newer was applied, so the older answer is still the best state');
});

// L-34: polled lists are rebuilt only when their content changed, and keep focus when they are.
function listHarness(){
 const h=harness();
 const focusable=new Map(),log={writes:0,focused:[]};
 const container=h.document.getElementById('jobs');
 let html='';
 Object.defineProperty(container,'innerHTML',{get:()=>html,set:v=>{html=v;log.writes++;}});
 container.contains=el=>!!el&&el.inside===true;
 container.querySelector=selector=>{log.selector=selector;return focusable.get(selector)||null;};
 return {h,container,focusable,log};
}
const backupJob=(id,extra={})=>({id,lab_id:'lab',status:'succeeded',operation:'backup',started:'2026-09-10T01:02:03Z',archive_name:'Lab.zip',nodes:[{name:'SW1',status:'succeeded',download_name:'CEOS_SW1.conf',captured_at:'2026-09-10T01:04:00Z'}],...extra});
test('renderJobs does not rebuild the backup list when nothing changed, so a poll never destroys the Download buttons',()=>{
 const {h,log}=listHarness();
 vm.runInContext(`state={labs:[{id:'lab'}],jobs:[${JSON.stringify(backupJob('j1'))}]};activeId='lab';renderJobs();renderJobs();renderJobs();`,h.context);
 assert.equal(log.writes,1,'three identical polls write the markup once');
 vm.runInContext(`state.jobs.push(${JSON.stringify(backupJob('j2'))});renderJobs();`,h.context);
 assert.equal(log.writes,2,'a new job does rebuild');
});
test('opening a backup row is not a change: the list is not rebuilt, and an opened row stays open when it is',()=>{
 const {h,log,container}=listHarness();
 vm.runInContext(`state={labs:[{id:'lab'}],jobs:[${JSON.stringify(backupJob('j1'))}]};activeId='lab';renderJobs();`,h.context);
 h.document.querySelectorAll=selector=>selector==='.job[open]'?[{dataset:{job:'j1'}}]:[];
 vm.runInContext('renderJobs();',h.context);
 assert.equal(log.writes,1,'the student opening a row (read back from the DOM) does not rebuild the list under their keyboard');
 vm.runInContext(`state.jobs.push(${JSON.stringify(backupJob('j2'))});renderJobs();`,h.context);
 assert.match(container.innerHTML,/data-job="j1" open/,'when the list is rebuilt for a real change the opened row stays open');
 assert.doesNotMatch(container.innerHTML,/data-job="j2" open/);
});
test('a rebuild hands keyboard focus back to the same Download button',()=>{
 const {h,focusable,log}=listHarness();
 vm.runInContext(`state={labs:[{id:'lab'}],jobs:[${JSON.stringify(backupJob('j1'))}]};activeId='lab';renderJobs();`,h.context);
 const focused={dataset:{download:'j1',nodeIndex:'0'},inside:true},replacement={focus(options){log.focused.push(options);}};
 h.document.activeElement=focused;focusable.set('[data-download="j1"][data-node-index="0"]',replacement);
 vm.runInContext(`state.jobs.push(${JSON.stringify(backupJob('j2'))});renderJobs();`,h.context);
 assert.equal(log.selector,'[data-download="j1"][data-node-index="0"]');assert.equal(JSON.stringify(log.focused),'[{"preventScroll":true}]','focus returns to the rebuilt control without scrolling');
});
test('the device drawer history is not rebuilt by an unchanged poll',()=>{
 const h=harness();
 const history=h.document.getElementById('node-history');let writes=0,html='';
 Object.defineProperty(history,'innerHTML',{get:()=>html,set:v=>{html=v;writes++;}});
 vm.runInContext(`state={labs:[{id:'lab',nodes:[{name:'SW1',address:'a',port:22,platform:'arista_ceos',enabled:true}],profiles:[],defaults:{}}],jobs:[${JSON.stringify(backupJob('j1'))}],platforms:{}};activeId='lab';detailName='SW1';renderDetails();renderDetails();renderDetails();`,h.context);
 assert.equal(writes,1);assert.match(html,/data-download="j1"/);
});
test('a download in flight is not started a second time from a rebuilt button',async()=>{
 const h=harness();h.context.disposition='attachment; filename="x.conf"';
 let release,started=0;const gate=new Promise(r=>release=r);const base=h.context.fetch;
 h.context.fetch=async url=>{started++;await gate;return base(url);};
 const make=()=>({disabled:false,dataset:{download:'job1',nodeIndex:'0',filename:'x.conf'},hasAttribute:()=>true});
 const first=make(),replacement=make(),click=button=>h.document.getElementById('jobs').listeners.click({target:{closest:s=>s==='[data-download]'?button:null}});
 const one=click(first),two=click(replacement);
 await new Promise(r=>setImmediate(r));
 assert.equal(started,1,'the rebuilt button of a download already running starts nothing');assert.equal(replacement.disabled,false);
 release();await Promise.all([one,two]);
 assert.deepEqual(h.requests,['/api/jobs/job1/nodes/0/download'],'one request only');
 await click(make());
 assert.equal(h.requests.length,2,'after it finished the same download can be requested again');
});
test('L-34: a list rebuilt while a download runs gives the same download a disabled button, which is enabled again when it finishes',async()=>{
 const {h}=listHarness();h.context.disposition='attachment; filename="x.conf"';
 let release;const gate=new Promise(r=>release=r);const base=h.context.fetch;
 h.context.fetch=async url=>{await gate;return base(url);};
 vm.runInContext(`state={labs:[{id:'lab'}],jobs:[${JSON.stringify(backupJob('job1'))}]};activeId='lab';renderJobs();`,h.context);
 const first={disabled:false,dataset:{download:'job1',nodeIndex:'0',filename:'x.conf'},hasAttribute:()=>true};
 const replacement={disabled:false,dataset:{download:'job1',nodeIndex:'0',filename:'x.conf'}};
 const other={disabled:false,dataset:{download:'job1',filename:'Lab.zip'}};
 h.document.querySelectorAll=selector=>selector==='[data-download]'?[replacement,other]:[];
 const running=h.document.getElementById('jobs').listeners.click({target:{closest:s=>s==='[data-download]'?first:null}});
 vm.runInContext(`state.jobs.push(${JSON.stringify(backupJob('j2'))});renderJobs();`,h.context);
 assert.equal(replacement.disabled,true,'the rebuilt button of the running download is disabled');
 assert.equal(other.disabled,false,'a different download of the same job stays available');
 release();await running;
 assert.equal(replacement.disabled,false,'the live button is enabled again once the download ends');
});
test('L-34 follow-up: the device drawer rebuilt while its download runs gives that download a disabled button',async()=>{
 const h=harness();h.context.disposition='attachment; filename="CEOS_SW1.conf"';
 let release;const gate=new Promise(r=>release=r);const base=h.context.fetch;
 h.context.fetch=async url=>{await gate;return base(url);};
 const history=h.document.getElementById('node-history');let writes=0,html='';
 Object.defineProperty(history,'innerHTML',{get:()=>html,set:v=>{html=v;writes++;}});
 vm.runInContext(`state={labs:[{id:'lab',nodes:[{name:'SW1',address:'a',port:22,platform:'arista_ceos',enabled:true}],profiles:[],defaults:{}}],jobs:[${JSON.stringify(backupJob('j1'))}],platforms:{}};activeId='lab';detailName='SW1';renderDetails();`,h.context);
 const first={disabled:false,dataset:{download:'j1',nodeIndex:'0',filename:'CEOS_SW1.conf'},hasAttribute:()=>true};
 const running=history.listeners.click({target:{closest:s=>s==='[data-download]'?first:null}});
 assert.equal(first.disabled,true);
 // The poll brings a newer backup of the device: the drawer's list is rebuilt, and its buttons are new elements.
 const rebuilt={disabled:false,dataset:{download:'j1',nodeIndex:'0'}},newer={disabled:false,dataset:{download:'j2',nodeIndex:'0'}};
 h.document.querySelectorAll=selector=>selector==='[data-download]'?[newer,rebuilt]:[];
 vm.runInContext(`state.jobs.unshift(${JSON.stringify(backupJob('j2'))});renderDetails();`,h.context);
 assert.equal(writes,2,'the changed history was rebuilt');assert.match(html,/data-download="j2"/);
 assert.equal(rebuilt.disabled,true,'the rebuilt button of the running download is disabled, so it cannot start it twice');
 assert.equal(newer.disabled,false,'the other backup stays available');
 release();await running;
 assert.equal(rebuilt.disabled,false,'enabled again once the download ends');
});
