const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/git-progress.js'),'utf8');
function makeContext(){
 const storage=new Map();let sequence=0;
 const context=vm.createContext({$:()=>null,state:{labs:[],jobs:[],git_jobs:[]},activeId:'lab',
  esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  utcDisplay:value=>new Date(value).toISOString(),
  crypto:{getRandomValues:bytes=>bytes.fill(++sequence)},
  sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  refresh:async()=>{},notify(){},clearTimeout:()=>{},setTimeout:()=>0});
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
test('every Save progress option is explained from what it really does: a local save never uploads, history saves nothing',()=>{
 const context=makeContext();vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 const binding={binding_id:'b',repository:{path:'/home/me/labs/Course-Labs',prefix:'JunOS-TEST-2/working/',push_url:'https://github.com/me/Course-Labs.git'}};
 const help=action=>context.gitSaveHelp(action,binding);
 const actions=Array.from(vm.runInContext('GIT_SAVE_HELP_ACTIONS',context));assert.deepEqual(actions,['checkpoint','local','history','settings']);
 assert.match(help('checkpoint').what,/Reads the configuration of every included device now/);assert.match(help('checkpoint').what,/named version that later saves never overwrite/);
 assert.match(help('checkpoint').where,/checkpoints\/<name> in Course-Labs › JunOS-TEST-2\/working/);assert.match(help('checkpoint').where,/uploaded to github\.com unless you untick/);
 assert.match(help('local').what,/without uploading anything/);assert.match(help('local').where,/Stays in the lab VM’s copy of Course-Labs › JunOS-TEST-2\/working/);assert.match(help('local').where,/Upload saved progress/);
 assert.doesNotMatch(help('local').where,/github/,'a local save never names the upload host as its destination');
 assert.match(help('history').what,/Nothing is read from the devices and nothing new is saved/);
 assert.match(help('settings').where,/Nothing is saved or moved until you confirm/);
 assert.equal(context.gitSaveHelp('push',binding),null);
 assert.match(context.gitSaveHelp('checkpoint',{binding_id:'b',repository:{path:'/r'}}).where,/the online repository/,'an unknown push URL is not given a host name');
 const attack={binding_id:'b',repository:{path:'/labs/<img src=x onerror=1>',push_url:'https://github.com/x/y'}};
 assert.doesNotMatch(context.gitSaveHelpMarkup(context.gitSaveHelp('local',attack)),/<img/);
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 for(const action of actions){assert.match(html,new RegExp('data-git-action="'+action+'" aria-describedby="git-save-help-'+action+'"'));assert.match(html,new RegExp('<div id="git-save-help-'+action+'" hidden>'));}
});
test('the help pane shows one explanation at a time and the default line when no option is active',()=>{
 const context=makeContext(),els={};for(const id of ['default','checkpoint','local','history','settings'])els['git-save-help-'+id]={hidden:id!=='default',innerHTML:''};
 context.$=id=>els[id]||null;
 context.gitRenderSaveHelp({binding_id:'b',repository:{path:'/r/Labs'}});assert.match(els['git-save-help-local'].innerHTML,/<strong>Save on this VM only<\/strong>/);
 const first=els['git-save-help-local'].innerHTML;els['git-save-help-local'].innerHTML='kept';context.gitRenderSaveHelp({binding_id:'b',repository:{path:'/r/Labs'}});assert.equal(els['git-save-help-local'].innerHTML,'kept','an unchanged text is not rewritten on a poll');assert.ok(first);
 context.gitShowSaveHelp('local');assert.equal(els['git-save-help-local'].hidden,false);assert.equal(els['git-save-help-default'].hidden,true);assert.equal(els['git-save-help-checkpoint'].hidden,true);
 context.gitShowSaveHelp('history');assert.equal(els['git-save-help-local'].hidden,true);assert.equal(els['git-save-help-history'].hidden,false);
 context.gitShowSaveHelp('');assert.equal(els['git-save-help-history'].hidden,true);assert.equal(els['git-save-help-default'].hidden,false);
});
test('the Save progress menu is placed where it fits: right-aligned, from the left of a wrapped control, stacked when the window is too narrow',()=>{
 const context=makeContext(),place=box=>JSON.parse(JSON.stringify(context.gitSaveMenuPlacement(box)));
 assert.deepEqual(place({left:690,right:873,vw:1366}),{side:'right',stacked:false},'a desktop header');
 assert.deepEqual(place({left:440,right:622,vw:853}),{side:'right',stacked:false},'150 % zoom, header not wrapped');
 assert.deepEqual(place({left:16,right:198,vw:640}),{side:'left',stacked:false},'200 % zoom, the control wrapped to the left edge');
 assert.deepEqual(place({left:16,right:198,vw:512}),{side:'left',stacked:true},'250 % zoom: the explanation goes under the options');
 assert.deepEqual(place({left:300,right:482,vw:500}),{side:'right',stacked:true});
 assert.deepEqual(place({left:10,right:192,vw:260}),{side:'left',stacked:true},'nothing fits: the side with more room');assert.deepEqual(place({left:60,right:242,vw:260}),{side:'right',stacked:true});
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
 let opened=0;context.gitLoadContext=async()=>({binding:null});context.gitFirstSave=async()=>{opened++;};await context.gitSaveProgress();assert.equal(opened,1,'an unbound lab goes to the first-save flow');assert.equal(calls.length,1,'and nothing is saved yet');
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
 assert.equal(dialogs.get('git-save-options').open,false);assert.equal(dialogs.get('git-job-dialog'),undefined,'a plain save is quiet: no job window opens');assert.equal(timers.size,1,'the save is watched in the background');
 await context.gitShowJob('save-job',job);assert.equal(dialogs.get('git-job-dialog').open,true);assert.equal(timers.size,1,'opening the window reuses the running watch');
 const tick=async()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);await fn();};
 await tick();assert.equal(polls,1);assert.equal(timers.size,1);
 dialogs.get('git-job-dialog').close();stage='synced';await tick();
 assert.equal(polls,2);assert.equal(timers.size,0);assert.equal(dialogs.get('git-job-dialog').open,false);
});
test('save rows read as student sentences and the job window keeps the raw status under Details',()=>{
 const context=makeContext();
 assert.equal(context.gitSaveSentence({status:'synced',target:'latest'}),'Progress saved to Git');
 assert.equal(context.gitSaveSentence({status:'committed',target:'checkpoint',checkpoint:'ospf-done'}),"Checkpoint 'ospf-done' saved");
 assert.equal(context.gitSaveSentence({status:'push_pending',target:'latest'}),'Saved on this VM — upload needs attention');
 assert.equal(context.gitSaveSentence({status:'dismissed',target:'update'}),'Repository updated');
 assert.equal(context.gitSaveSentence({status:'exporting',target:'move',snapshot_path:'labs/x/latest'}),'Moving saved files…');
 assert.equal(context.gitSaveSentence({status:'synced',target:'move',snapshot_path:'labs/x/latest'}),'Moved to folder labs/x');
 assert.equal(context.gitSavedAs({target:'baseline'}),'Baseline');assert.equal(context.gitSavePill({status:'capturing'}),'busy');assert.equal(context.gitSavePill({status:'failed'}),'danger');
 const markup=context.gitJobMarkup({id:'j',status:'push_pending',message:'push failed',target:'latest',commit:'abc',created:'2026-09-11T12:00:00Z'});
 assert.match(markup,/Saved on this VM — upload needs attention/);assert.match(markup,/<details><summary>Details<\/summary>/);assert.match(markup,/push pending/);
 assert.match(context.gitJobMarkup(null),/No saves yet/);
});
test('the disabled reason of Save progress is visible text and an unbound lab keeps the button enabled',()=>{
 const context=makeContext();
 assert.equal(context.gitSaveReason(null,null),'');
 assert.equal(context.gitSaveReason({binding_id:'b'},{id:'active'}),'Saving… wait for the current save to finish');
 context.busy=()=>true;assert.match(context.gitSaveReason({binding_id:'b'},null),/backup or lab operation is running/);
 context.busy=()=>false;assert.equal(context.gitSaveReason({binding_id:'b'},null),'');
});

test('saved versions list the course layout reference states one level below the lab folder',()=>{
 // Live finding (release 1.29 validation): scaffold-lab.py creates <slug>/reference/{start,solution}/latest beside
 // <slug>/work; only direct siblings with a latest/ were shown, so the reference states never appeared.
 const context=makeContext();
 const node=(path,dirs=[],extra={})=>({path,name:path.split('/').pop(),dirs,count:0,restorable:false,registration:null,...extra});
 const latest=count=>({path:'latest',name:'latest',dirs:[],count});
 const work=node('bgp/work',[latest(5),{path:'bgp/work/checkpoints',name:'checkpoints',dirs:[node('bgp/work/checkpoints/day-1',[latest(2)],{count:2})]}],{restorable:true,registration:{id:'b1',lab:{id:'lab',name:'BGP'}}});
 const start=node('bgp/reference/start',[latest(5)],{restorable:true}),solution=node('bgp/reference/solution',[latest(5)],{restorable:true});
 const reference=node('bgp/reference',[start,solution]);
 const flat=node('bgp/final-state',[latest(5)],{restorable:true});
 const otherLab=node('bgp/reference/other',[latest(3)],{registration:{id:'b2',lab:{id:'other-lab',name:'OSPF'}}});reference.dirs.push(otherLab);
 const bgp=node('bgp',[work,reference,flat]);
 const model={nodes:new Map([bgp,work,reference,start,solution,otherLab,flat].map(n=>[n.path,n]))};
 const context2=context;context2.gitRepository=()=>({prefix:'bgp/work',label:'Course'});context2.gitRepoName=()=>'Course';context2.gitLabJobs=()=>[];
 const groups=context2.gitVersionGroups('lab',{binding:{}},model,{head:'abc'},null);
 assert.deepEqual(Array.from(groups.reference,r=>r.caption),['bgp/reference/start','bgp/reference/solution','bgp/final-state']);
 assert.ok(groups.reference.every(r=>r.apply&&r.apply.folder===r.caption),'reference rows apply straight from their folder');
 assert.deepEqual(Array.from(groups.others,r=>r.name+' '+r.caption),['OSPF bgp/reference/other']);
 assert.equal(groups.latest.length,1);assert.deepEqual(Array.from(groups.checkpoints,r=>r.name),['day-1']);
});
