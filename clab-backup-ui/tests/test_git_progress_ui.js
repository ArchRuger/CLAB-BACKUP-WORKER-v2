const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/git-progress.js'),'utf8');
function makeContext(){
 const storage=new Map();let sequence=0;
 const context=vm.createContext({$:()=>null,state:{labs:[],jobs:[],git_jobs:[]},activeId:'lab',
  esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  utcDisplay:value=>new Date(value).toISOString(),
  crypto:{getRandomValues:bytes=>bytes.fill(++sequence)},
  sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  refresh:async()=>{},clearTimeout:()=>{},setTimeout:()=>0});
 vm.runInContext(source,context);return context;
}
test('Git progress scope is exact, complete and independent of scheduled backup selection',()=>{
 const context=makeContext(),node=name=>({name,status:'succeeded'}),base={id:'capture',lab_id:'lab',operation:'backup',status:'succeeded',nodes:[node('r1'),node('r2')]};
 const jobs=[base,{...base,id:'partial',status:'partial'},
  {...base,id:'mixed',nodes:[node('r1'),{name:'r2',status:'failed'}]},
  {...base,id:'subset',nodes:[node('r1')]},
  {...base,id:'superset',nodes:[...base.nodes,node('r3')]},
  {...base,id:'duplicate',nodes:[node('r1'),node('r1')]},
  {...base,id:'different-lab',lab_id:'other'},
  {...base,id:'test',operation:'test'},{...base,id:'active',status:'running'}];
 assert.deepEqual(Array.from(context.gitCompleteBackups(jobs,'lab',['r1','r2']),job=>job.id),['capture','partial']);
 assert.equal(context.gitCompleteBackups(jobs,'lab',[]).length,0);
});
test('save commands are structured and baseline replacement is explicit',()=>{
 const context=makeContext();
 const normal=context.gitSavePayload({},'request');
 assert.equal(normal.target,'latest');assert.equal(normal.push,true);assert.equal(normal.backup_job_id,'');assert.equal(normal.replace_baseline,false);assert.equal(normal.allow_removed,false);
 const baseline=context.gitSavePayload({target:'baseline',backup_job_id:'old-capture',expected_baseline:'old-revision',replace_baseline:true,push:false,note:'Reviewed baseline',command:'git add .'},'id');
 assert.equal(baseline.backup_job_id,'old-capture');assert.equal(baseline.expected_baseline,'old-revision');assert.equal(baseline.replace_baseline,true);assert.equal(baseline.push,false);assert.equal(baseline.command,undefined);
});
test('diffs and job output escape configuration, filenames, notes and labels',()=>{
 const context=makeContext(),attack='<img src=x onerror=alert(1)>';
 const markup=context.gitDiffMarkup([{name:attack,status:attack,before:'</pre><script>bad()</script>',after:'router <peer> & policy'}],attack,'Saved');
 assert.doesNotMatch(markup,/<script>|<img/);assert.match(markup,/&lt;script&gt;/);assert.match(markup,/router &lt;peer&gt; &amp; policy/);
 const output=context.gitJobMarkup({status:'push_pending',message:attack,target:attack,commit:attack,created:'2026-09-11T12:00:00Z'});
 assert.doesNotMatch(output,/<img/);assert.match(output,/push pending/);
});
test('Git Unix commit timestamps are interpreted as seconds',()=>{
 const context=makeContext();assert.equal(context.gitTime(0),'1970-01-01T00:00:00.000Z');assert.equal(context.gitTime(1789128000),'2026-09-11T12:00:00.000Z');
 assert.equal(context.gitTime('2026-09-11T12:00:00Z'),'2026-09-11T12:00:00.000Z');
});
test('a changed registered destination requires export acknowledgement even with the same binding ID',()=>{
 const context=makeContext(),binding={binding_id:'repo',revision:'original'};
 assert.equal(context.gitBindingChanged(binding,{id:'repo',revision:'original'}),false);
 assert.equal(context.gitBindingChanged(binding,{id:'repo',revision:'new-destination'}),true);
 assert.equal(context.gitBindingChanged(binding,{id:'other',revision:'original'}),true);
 assert.equal(context.gitBindingChanged(null,{id:'repo',revision:'original'}),true);
});
test('repository selection identifies the verified remote URL and branch',()=>{
 const context=makeContext();
 const text=context.gitRegisteredDestination({owner:'ben',path:'/home/ben/BENS-BGP-LAB',remote:'origin',branch:'main',push_url:'https://github.com/ben/BENS-BGP-LAB.git',prefix:'labs/bgp'});
 assert.match(text,/origin \/ main/);assert.match(text,/Push to https:\/\/github.com\/ben\/BENS-BGP-LAB\.git/);assert.match(text,/labs\/bgp/);
 assert.doesNotMatch(context.gitRegisteredDestination({owner:'ben',path:'/home/ben/lab',remote:'origin',branch:'main'}),/undefined|Push to/);
});
test('connected repository displays the push URL as escaped text',()=>{
 const context=makeContext(),container={innerHTML:'',querySelectorAll:()=>[]};
 context.$=id=>id==='git-repository-content'?container:null;
 context.gitRenderRepository('lab',{binding:{binding_id:'repo',node_names:[],repository:{label:'BENS-BGP-LAB',remote:'origin',branch:'main',push_url:'https://github.com/ben/<img onerror="bad()">.git'}}},{repositories:[]});
 assert.match(container.innerHTML,/Verified push destination/);assert.match(container.innerHTML,/https:\/\/github.com\/ben\/&lt;img/);assert.doesNotMatch(container.innerHTML,/<img|href=/);
});
test('historical baseline and checkpoint commits open their recorded target instead of latest',async()=>{
 const context=makeContext(),opened=[];
 context.gitViewVersion=async(id,version)=>opened.push({id,version});
 context.state.git_jobs=[{id:'baseline-save',lab_id:'lab',commit:'baseline-commit',target:'baseline',changed_files:['baseline/r1.cfg'],created:'2026-09-11T12:00:00Z'},
  {id:'checkpoint-save',lab_id:'lab',commit:'checkpoint-commit',target:'checkpoint',checkpoint:'bgp-working',changed_files:['checkpoints/bgp-working/r1.cfg'],created:'2026-09-11T13:00:00Z'}];
 await context.gitOpenCommit('lab',{commit:'baseline-commit'},[]);
 await context.gitOpenCommit('lab',{commit:'checkpoint-commit'},[]);
 assert.equal(opened[0].version.path,'baseline');assert.equal(opened[1].version.path,'checkpoints/bgp-working');
});
test('unchanged saves sharing HEAD do not replace the actual historical commit target',async()=>{
 const context=makeContext(),opened=[];
 context.gitViewVersion=async(id,version)=>opened.push(version.path);
 context.state.git_jobs=[{id:'baseline-save',lab_id:'lab',commit:'shared-head',target:'baseline',changed_files:['baseline/r1.cfg'],created:'2026-09-11T12:00:00Z'},
  {id:'unchanged-latest',lab_id:'lab',commit:'shared-head',target:'latest',changed_files:[],created:'2026-09-11T13:00:00Z'}];
 await context.gitOpenCommit('lab',{commit:'shared-head'},[]);assert.equal(opened[0],'baseline');
 context.state.git_jobs.shift();await context.gitOpenCommit('lab',{commit:'shared-head'},[]);assert.equal(opened[1],'latest');
});
test('one-click save captures fresh configurations and delegates review preference to server',async()=>{
 const context=makeContext(),calls=[];
 context.gitLoadContext=async()=>({binding:{node_names:['r1'],review_before_push:true}});
 context.gitSubmitSave=async(id,request)=>calls.push({id,request});
 await context.gitSaveProgress();assert.equal(calls.length,1);assert.equal(calls[0].id,'lab');assert.equal(calls[0].request.target,'latest');assert.equal(calls[0].request.push,true);assert.equal(calls[0].request.node_names,undefined);
 let opened=0;context.gitLoadContext=async()=>({binding:null});context.gitOpenRepository=()=>opened++;await context.gitSaveProgress();assert.equal(opened,1);assert.equal(calls.length,1);
});
test('an uncertain save response retries with the same persistent request ID',async()=>{
 const context=makeContext(),calls=[];let fail=true;
 context.gitShowJob=async()=>{};
 context.json=async(endpoint,method,payload)=>{calls.push({endpoint,method,payload});if(fail)throw Error('Network interrupted');return {id:'job',lab_id:'lab',created:'2026-09-11T12:00:00Z',status:'queued'};};
 await assert.rejects(context.gitSubmitSave('lab',{target:'latest',push:true}),/Network interrupted/);
 fail=false;await context.gitSubmitSave('lab',{target:'latest',push:true});
 assert.equal(calls[0].payload.request_id,calls[1].payload.request_id);assert.match(calls[1].payload.request_id,/^[a-f0-9]{32}$/);assert.equal(calls[1].endpoint,'/labs/lab/git/save');
 await context.gitSubmitSave('lab',{target:'latest',push:true});assert.notEqual(calls[2].payload.request_id,calls[1].payload.request_id);
});
test('double-clicking Save progress dispatches one save while the first request is pending',async()=>{
 const context=makeContext();let calls=0,release;
 context.json=()=>{calls++;return new Promise(resolve=>release=resolve);};context.gitShowJob=async()=>{};
 const first=context.gitSubmitSave('lab',{target:'latest'});await context.gitSubmitSave('lab',{target:'latest'});assert.equal(calls,1);
 release({id:'job',lab_id:'lab',created:'2026-09-11T12:00:00Z',status:'queued'});await first;
});
test('single-job review requests parent-versus-saved changes, not the latest snapshot',async()=>{
 const context=makeContext(),requests=[],elements=new Map();
 context.$=id=>{if(!elements.has(id))elements.set(id,{addEventListener:()=>{}});return elements.get(id);};
 context.json=async(endpoint,method,payload)=>{requests.push({endpoint,method,payload});return {files:[]};};
 context.opDialog=()=>({});
 await context.gitReviewJob({id:'pending-job',lab_id:'lab',status:'review_pending',commit:'abc123',target:'latest'});
 assert.equal(requests.length,1);assert.equal(requests[0].endpoint,'/labs/lab/git/compare');assert.equal(requests[0].payload.job_id,'pending-job');assert.equal(requests[0].payload.commit,undefined);
});
test('save options close their own modal and one job poll continues after the output closes',async()=>{
 const context=makeContext(),elements=new Map(),dialogs=new Map(),timers=new Map();let timerId=0,stage='capturing',polls=0;
 const element=()=>({value:'',checked:false,querySelectorAll:()=>[]});
 for(const id of ['git-save-cancel','git-save-confirm','git-save-note','git-allow-removed','git-job-detail','git-job-actions'])elements.set(id,element());
 context.$=id=>elements.get(id)||dialogs.get(id)||null;
 context.opDialog=id=>{const dialog={open:true,close(){this.open=false;this.onclose?.();}};dialogs.set(id,dialog);return dialog;};
 context.opTask=async(dialog,fn)=>fn();
 context.gitLoadContext=async()=>({binding:{node_names:['r1'],repository:{label:'lab',branch:'main'}},repository_status:{}});
 context.setTimeout=fn=>{timers.set(++timerId,fn);return timerId;};context.clearTimeout=id=>timers.delete(id);context.tab='topology';
 const job={id:'save-job',lab_id:'lab',target:'latest',status:'queued',created:'2026-09-11T12:00:00Z'};
 context.json=async()=>job;
 context.api=async endpoint=>{assert.equal(endpoint,'/git/jobs/save-job');polls++;return {json:async()=>({...job,status:stage})};};
 await context.gitSaveOptions('local','lab');await elements.get('git-save-confirm').onclick();
 assert.equal(dialogs.get('git-save-options').open,false);assert.equal(dialogs.get('git-job-dialog').open,true);assert.equal(timers.size,1);
 const tick=async()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);await fn();};
 await tick();assert.equal(polls,1);assert.equal(timers.size,1);
 dialogs.get('git-job-dialog').close();stage='synced';await tick();
 assert.equal(polls,2);assert.equal(timers.size,0);assert.equal(dialogs.get('git-job-dialog').open,false);
});
