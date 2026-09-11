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
 vm.runInContext(`activeId='a';healthState={lab:'b',nodes:[{name:'PE1',ssh:{status:'reachable'}}]};state={labs:[{id:'a',nodes:[{name:'PE1',address:'host',port:22,platform:'arista_ceos',readiness:'Ready',ssh_ready:true,enabled:true}],profiles:[],defaults:{}}],jobs:[],platforms:{}};renderNodes();`,h.context);
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
