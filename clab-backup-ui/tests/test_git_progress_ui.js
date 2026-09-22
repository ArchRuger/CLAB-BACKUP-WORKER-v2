const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/git-progress.js'),'utf8');
// Objects returned from the vm context are not reference-equal to a literal built in this realm even
// when they have the same shape, so deepStrictEqual on them needs a structural comparison instead.
const same=(actual,expected)=>assert.equal(JSON.stringify(actual),JSON.stringify(expected));
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
 assert.match(help('checkpoint').where,/checkpoints\/<name> in Course-Labs › JunOS-TEST-2\/working/);assert.match(help('checkpoint').where,/uploaded to github\.com only after you have seen what changed and confirmed the upload/);
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
 assert.equal(opened[0].version.path,'/baseline');assert.equal(opened[1].version.path,'/checkpoints/bgp-working');
});
test('unchanged saves sharing HEAD do not replace the actual historical commit target',async()=>{
 const context=makeContext(),opened=[];
 context.gitViewVersion=async(id,version)=>opened.push(version.path);
 context.state.git_jobs=[{id:'baseline-save',lab_id:'lab',commit:'shared-head',target:'baseline',changed_files:['baseline/r1.cfg'],created:'2026-09-11T12:00:00Z'},
  {id:'unchanged-latest',lab_id:'lab',commit:'shared-head',target:'latest',changed_files:[],created:'2026-09-11T13:00:00Z'}];
 await context.gitOpenCommit('lab',{commit:'shared-head'},[]);assert.equal(opened[0],'/baseline');
 context.state.git_jobs.shift();await context.gitOpenCommit('lab',{commit:'shared-head'},[]);assert.equal(opened[1],'/latest');
});
test('gitOpenCommit fast path sends the job\'s own snapshot_path with the wire\'s leading slash when present, else the binding prefix joined with its target',async()=>{
 const context=makeContext(),opened=[];
 context.gitViewVersion=async(id,version)=>opened.push(version.path);
 vm.runInContext("gitContexts.set('lab',{binding:{repository:{prefix:'course/lab-a'}}})",context);
 context.state.git_jobs=[{id:'with-path',lab_id:'lab',commit:'c1',target:'checkpoint',checkpoint:'day-1',changed_files:['x.cfg'],snapshot_path:'course/lab-a/checkpoints/day-1'},
  {id:'no-path',lab_id:'lab',commit:'c2',target:'baseline',changed_files:['y.cfg']}];
 await context.gitOpenCommit('lab',{commit:'c1'},[]);
 await context.gitOpenCommit('lab',{commit:'c2'},[]);
 assert.deepEqual(opened,['/course/lab-a/checkpoints/day-1','/course/lab-a/baseline'],'the job\'s own recorded path is preferred and never doubles the leading slash; a job saved before that field existed falls back to the binding\'s prefix');
});
test('one-click save captures fresh configurations and delegates review preference to server',async()=>{
 const context=makeContext(),calls=[];
 context.gitLoadContext=async()=>({binding:{node_names:['r1'],review_before_push:true}});
 context.gitSubmitSave=async(id,request)=>calls.push({id,request});
 await context.gitSaveProgress();assert.equal(calls.length,1);assert.equal(calls[0].id,'lab');assert.equal(calls[0].request.target,'latest');assert.equal(calls[0].request.push,true);assert.equal(calls[0].request.node_names,undefined);
 let opened=0;context.gitLoadContext=async()=>({binding:null});context.gitFirstSave=async()=>{opened++;};await context.gitSaveProgress();assert.equal(opened,1,'an unbound lab goes to the first-save flow');assert.equal(calls.length,1,'and nothing is saved yet');
});
test('the review before an upload is mandatory: every upload of an unreviewed save goes through the review window, and only its button uploads',async()=>{
 const context=makeContext(),elements=new Map(),dialogs=new Map(),calls=[],toasts=[];
 const element=()=>({onclick:null,innerHTML:'',listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},querySelectorAll:()=>[]});
 context.$=id=>elements.get(id)||dialogs.get(id)||null;context.notify=m=>toasts.push(m);context.opTask=async(dialog,fn)=>fn();context.refresh=async()=>{};
 context.opDialog=(id,title,html)=>{for(const stale of ['git-review-cancel','git-review-push'])elements.delete(stale);for(const m of html.matchAll(/ id="([\w-]+)"/g))elements.set(m[1],element());const dialog={id,title,html,open:true,close(){this.open=false;this.onclose?.();},querySelector:()=>null};dialogs.set(id,dialog);return dialog;};
 context.json=async(endpoint,method,payload)=>{calls.push({endpoint,payload});return endpoint.endsWith('/compare')?{files:[{name:'r1.cfg',status:'modified',before:'a',after:'b'}]}:{id:'j',lab_id:'lab',status:'queued',commit:'c'.repeat(40),created:'2026-09-11T12:00:00Z'};};
 const pending={id:'j',lab_id:'lab',status:'review_pending',target:'latest',commit:'c'.repeat(40),created:'2026-09-11T12:00:00Z'};
 assert.equal(context.gitNeedsReview(pending),true);assert.equal(context.gitNeedsReview({...pending,reviewed:'2026-09-11T12:01:00Z'}),false);assert.equal(context.gitNeedsReview({...pending,commit:''}),false);
 assert.equal(context.gitNeedsReview({...pending,target:'move'}),false,'a folder move has no configuration change to review');assert.equal(context.gitNeedsReview({...pending,status:'committed'}),true,'a local save uploaded later is reviewed too');
 assert.equal(context.gitUploadLabel(pending),'Review and upload…');assert.equal(context.gitUploadLabel({...pending,reviewed:'x'}),'Upload now');assert.equal(context.gitUploadLabel({...pending,commit:''}),'Retry save, then review');
 // Cancel: nothing is uploaded and nothing is reported as uploaded
 await context.gitReviewJob(pending);const review=dialogs.get('git-diff-dialog');
 assert.equal(review.title,'Review before uploading');assert.match(review.html,/Nothing is uploaded to the online repository unless you choose <strong>Upload these changes<\/strong>/);assert.match(review.html,/r1\.cfg/);
 elements.get('git-review-cancel').onclick();assert.equal(review.open,false);assert.match(toasts[0],/^Not uploaded\. The save stays on the lab VM/);
 assert.deepEqual(calls.map(c=>c.endpoint),['/labs/lab/git/compare'],'declining sends no upload request');
 // Proceed: the upload states that the review happened
 await context.gitReviewJob(pending);await elements.get('git-review-push').listeners.click();
 assert.equal(calls[calls.length-1].endpoint,'/git/jobs/j/retry');assert.equal(JSON.stringify(calls[calls.length-1].payload),'{"push":true,"reviewed":true}');
 // The Recent saves button and the job window lead to the review, never straight to the upload
 calls.length=0;context.state.git_jobs=[pending];
 await context.gitSavesAction({dataset:{gitJobUpload:'j'}},'lab');assert.deepEqual(calls.map(c=>c.endpoint),['/labs/lab/git/compare']);
 await context.gitShowJob('j',pending);const actions=elements.get('git-job-actions').innerHTML;
 assert.match(actions,/data-git-job-action="review">Review and upload…/);assert.doesNotMatch(actions,/data-git-job-action="push"/);assert.match(actions,/data-git-job-action="dismiss">Keep snapshot only/);
 // A synced save is reviewed for reading only: no decision, no upload button
 await context.gitReviewJob({...pending,status:'synced',pushed:true});assert.equal(dialogs.get('git-diff-dialog').title,'Review this save');assert.equal(elements.get('git-review-push'),undefined);assert.equal(elements.get('git-review-cancel'),undefined);
});
test('the save location form no longer offers to skip the review and never sends the old preference',()=>{
 assert.doesNotMatch(source,/git-review-before-push|Let me review changes/);assert.doesNotMatch(source,/review_before_push\s*:/,'no request carries the preference any more');
 assert.match(source,/Nothing is uploaded without you/);
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

test('a save with nothing new that is already uploaded reads as saved: no review, no upload offered',()=>{
 const context=makeContext();
 const job={id:'u',lab_id:'lab',status:'unchanged',pushed:true,commit:'c'.repeat(40),target:'latest',changed_files:[]};
 assert.equal(context.gitNeedsReview(job),false,'there is nothing to review');
 assert.equal(context.gitUploadState(job),'Uploaded');assert.equal(context.gitSavePill(job),'ok');
 assert.match(context.gitDoneToast(job),/nothing had changed since your last save/);
 assert.equal(context.gitJobTitle(job),'Progress saved');
});
test('the disabled reason of Save progress is visible text and an unbound lab keeps the button enabled',()=>{
 const context=makeContext();
 assert.equal(context.gitSaveReason(null,null),'');
 assert.equal(context.gitSaveReason({binding_id:'b'},{id:'active'}),'Saving… wait for the current save to finish');
 context.busy=()=>true;assert.match(context.gitSaveReason({binding_id:'b'},null),/backup or lab operation is running/);
 context.busy=()=>false;assert.equal(context.gitSaveReason({binding_id:'b'},null),'');
});

test('saved versions list every snapshot folder below the lab folder\'s parent, any depth, from its exact path; a folder without manifest.json is never listed',()=>{
 // Live finding (release 1.29 validation): scaffold-lab.py creates <slug>/reference/{start,solution}/latest beside
 // <slug>/work; only direct siblings with a latest/ were shown, so the reference states never appeared.
 // Chunk 2 (save-location-fix): a folder is a saved configuration when it holds manifest.json, whatever
 // its name or depth — not by carrying a latest/ child, and not by any restore-artifact extension.
 const context=makeContext();
 const node=(path,dirs=[],extra={})=>({path,name:path.split('/').pop(),dirs,count:0,snapshot:false,registration:null,...extra});
 const own=node('bgp/work',[
  node('bgp/work/latest',[],{count:5,snapshot:true}),
  node('bgp/work/checkpoints',[node('bgp/work/checkpoints/day-1',[],{count:2,snapshot:true})]),
 ],{count:7,registration:{id:'b1',lab:{id:'lab',name:'BGP'}}});
 // A legacy parent convenience: "start" itself is not a snapshot, only its latest/ child is.
 const startLatest=node('bgp/reference/start/latest',[],{count:5,snapshot:true});
 // A folder that is itself a snapshot, any name, any depth.
 const solution=node('bgp/reference/solution',[],{count:5,snapshot:true});
 const flat=node('bgp/final-state',[],{count:5,snapshot:true});
 // Inside another lab's registered folder: grouped under that lab's name, not "reference".
 const otherLatest=node('bgp/reference/other/latest',[],{count:3,snapshot:true});
 const otherReg=node('bgp/reference/other',[otherLatest],{count:3,registration:{id:'b2',lab:{id:'other-lab',name:'OSPF'}}});
 // Outside the lab folder's parent entirely: neither "reference" nor "others" — a third, collapsed group.
 const elsewhere=node('zzz/vault',[],{count:1,snapshot:true});
 // A folder with ordinary files but no manifest.json: never a saved version, at any depth.
 const decoy=node('bgp/notes',[],{count:2,snapshot:false});
 const model={nodes:new Map([own,startLatest,solution,flat,otherReg,otherLatest,elsewhere,decoy].map(n=>[n.path,n]))};
 const context2=context;context2.gitRepository=()=>({prefix:'bgp/work',label:'Course'});context2.gitRepoName=()=>'Course';context2.gitLabJobs=()=>[];
 const groups=context2.gitVersionGroups('lab',{binding:{}},model,{head:'abc'},null);
 same(groups.latest[0].view,{commit:'abc',path:'/bgp/work/latest'});same(groups.latest[0].apply,{path:'/bgp/work/latest'});
 same(groups.checkpoints[0].apply,{path:'/bgp/work/checkpoints/day-1'});
 assert.equal(groups.baseline.length,0);
 same([...groups.reference.map(r=>r.caption)].sort(),['bgp/final-state','bgp/reference/solution','bgp/reference/start/latest']);
 assert.ok(groups.reference.every(r=>r.apply&&r.apply.path==='/'+r.caption),'reference rows apply from their exact snapshot path, with the wire\'s leading slash, never a substituted one');
 assert.deepEqual(Array.from(groups.others,r=>r.name+' '+r.caption),['OSPF bgp/reference/other/latest']);
 assert.deepEqual(Array.from(groups.elsewhere,r=>r.caption),['zzz/vault']);
 assert.ok(![...groups.reference,...groups.others,...groups.elsewhere].some(r=>r.caption==='bgp/notes'),'a folder without manifest.json is never a saved version, however deep it is scanned');
 assert.equal(groups.latest.length,1);assert.deepEqual(Array.from(groups.checkpoints,r=>r.name),['day-1']);
});
test('a top-level lab folder does not absorb the whole repository into "reference": only nearby top-level folders count, everything deeper is "elsewhere"',()=>{
 const context=makeContext();
 const node=(path,extra={})=>({path,name:path.split('/').pop(),dirs:[],count:0,snapshot:false,registration:null,...extra});
 const own=node('bgp',{count:0,registration:{id:'b1',lab:{id:'lab',name:'BGP'}}});
 const final=node('Final',{count:1,snapshot:true});
 const refSolution=node('ref/solution/latest',{count:1,snapshot:true});
 const deep=node('deep/a/b/c',{count:1,snapshot:true});
 const model={nodes:new Map([own,final,refSolution,deep].map(n=>[n.path,n]))};
 context.gitRepository=()=>({prefix:'bgp'});context.gitRepoName=()=>'Course';context.gitLabJobs=()=>[];
 const groups=context.gitVersionGroups('lab',{binding:{}},model,{head:'h'},null);
 same([...groups.reference.map(r=>r.caption)].sort(),['Final','ref/solution/latest'],'Final (depth 1) and ref/solution/latest (depth 2 once its legacy latest/ convenience is discounted) stay nearby reference versions');
 same(groups.elsewhere.map(r=>r.caption),['deep/a/b/c'],'anything deeper than the cap is elsewhere, never silently absorbed as "reference"');
});
test('a lab registered at the repository root does not claim every snapshot elsewhere in the repository as its own',()=>{
 const context=makeContext();
 const node=(path,extra={})=>({path,name:path.split('/').pop(),dirs:[],count:0,snapshot:false,registration:null,...extra});
 const own=node('bgp',{count:3,registration:{id:'b1',lab:{id:'lab',name:'BGP'}}});
 const rootLab=node('',{count:0,registration:{id:'root-reg',lab:{id:'root-lab',name:'Root course'}}});
 const stray=node('other/place',{count:1,snapshot:true});
 const model={nodes:new Map([own,rootLab,stray].map(n=>[n.path,n]))};
 context.gitRepository=()=>({prefix:'bgp'});context.gitRepoName=()=>'Course';context.gitLabJobs=()=>[];
 const groups=context.gitVersionGroups('lab',{binding:{}},model,{head:'h'},null);
 assert.equal(groups.others.length,0,'the root registration is skipped when attributing a foreign snapshot elsewhere in the repository');
 assert.ok(groups.reference.some(r=>r.caption==='other/place'),'the snapshot is still listed, just not claimed by the root registration');
});
test('a snapshot at the repository root is viewed, compared and downloaded with "/" on the wire, never an empty path; the history fallback root does too',()=>{
 const context=makeContext();
 const node=(path,extra={})=>({path,name:path.split('/').pop()||'',dirs:[],count:0,snapshot:false,registration:null,...extra});
 const own=node('bgp',{count:0,registration:{id:'b1',lab:{id:'lab',name:'BGP'}}});
 const root=node('',{count:1,snapshot:true});
 const model={nodes:new Map([own,root].map(n=>[n.path,n]))};
 context.gitRepository=()=>({prefix:'bgp'});context.gitRepoName=()=>'Course';context.gitLabJobs=()=>[];
 const groups=context.gitVersionGroups('lab',{binding:{}},model,{head:'h'},null);
 same(groups.elsewhere[0].view,{commit:'h',path:'/'});same(groups.elsewhere[0].apply,{path:'/'});
 const fromHistory=context.gitVersionGroups('lab',{binding:{}},null,null,{versions:[{path:'',commit:'h2',connected:false,label:'Root'}]});
 same(fromHistory.reference[0].view,{commit:'h2',path:'/'});
});
test('gitSnapshotPath is the exact repository-relative path, with the wire\'s one leading slash: a lab folder prefix joined with the name, or the bare name at the repository root',()=>{
 const context=makeContext();
 assert.equal(context.gitSnapshotPath({repository:{prefix:'course/lab-a'}},'latest'),'/course/lab-a/latest');
 assert.equal(context.gitSnapshotPath({repository:{prefix:'course/lab-a'}},'checkpoints/day-1'),'/course/lab-a/checkpoints/day-1');
 assert.equal(context.gitSnapshotPath({repository:{prefix:''}},'latest'),'/latest');
 assert.equal(context.gitSnapshotPath(null,'baseline'),'/baseline');
});
test('gitOpenCommit offers exact snapshot paths for the registered lab folder, never bare names, each with the wire\'s leading slash but shown to the student without it',async()=>{
 const context=makeContext();
 vm.runInContext("gitContexts.set('lab',{binding:{repository:{prefix:'course/lab-a'}}})",context);
 let dialogHtml='';
 context.$=()=>({onclick:null,value:''});
 context.opDialog=(id,title,html)=>{dialogHtml=html;return {querySelector:()=>({onclick:null})};};
 await context.gitOpenCommit('lab',{commit:'old-commit',message:'old save'},[{path:'course/lab-a/reference/one'}]);
 const values=[...dialogHtml.matchAll(/<option value="([^"]*)"/g)].map(m=>m[1]);
 assert.deepEqual(values.slice().sort(),['/course/lab-a/baseline','/course/lab-a/latest','/course/lab-a/reference/one'].sort());
 const labels=[...dialogHtml.matchAll(/<option value="[^"]*">([^<]*)</g)].map(m=>m[1]);
 assert.ok(labels.every(label=>!label.startsWith('/')),'the option text shown to the student never carries the leading slash');
});
test('gitReviewJob\'s "Open the full saved version" opens the job\'s own snapshot path when known, else the binding prefix joined with the target',async()=>{
 const context=makeContext(),elements=new Map(),opened=[];
 const element=()=>({onclick:null,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}});
 context.$=id=>elements.get(id)||null;context.opTask=async(dialog,fn)=>fn();
 context.opDialog=(id,title,html)=>{for(const m of html.matchAll(/ id="([\w-]+)"/g))elements.set(m[1],element());return {};};
 context.json=async endpoint=>endpoint.endsWith('/compare')?{files:[]}:{};
 context.gitViewVersion=async(id,version)=>opened.push(version);
 vm.runInContext("gitContexts.set('lab',{binding:{repository:{prefix:'course/lab-a'}}})",context);
 await context.gitReviewJob({id:'j1',lab_id:'lab',status:'review_pending',commit:'c1',target:'checkpoint',checkpoint:'day-1',snapshot_path:'course/lab-a/checkpoints/day-1'});
 await elements.get('git-review-files').onclick();
 await context.gitReviewJob({id:'j2',lab_id:'lab',status:'synced',pushed:true,commit:'c2',target:'latest'});
 await elements.get('git-review-files').onclick();
 assert.deepEqual(opened.map(v=>v.path),['/course/lab-a/checkpoints/day-1','/course/lab-a/latest']);
});
test('the Full history… dialog opens a saved version with the wire\'s leading slash added to the raw path; the repository root is opened as "/"',async()=>{
 const context=makeContext(),opened=[];
 context.opTask=async(dialog,fn)=>fn();
 context.gitViewVersion=async(id,version)=>opened.push(version);
 const versionButtons=[{dataset:{gitVersion:'0'},onclick:null},{dataset:{gitVersion:'1'},onclick:null}];
 context.api=async()=>({json:async()=>({versions:[{path:'course/lab-a/latest',commit:'c1',connected:true,label:'Latest'},{path:'',commit:'c2',connected:false,label:'Root'}],commits:[]})});
 context.opDialog=()=>({querySelectorAll:sel=>sel==='[data-git-version]'?versionButtons:[]});
 await context.gitHistory('lab');
 await versionButtons[0].onclick();
 await versionButtons[1].onclick();
 assert.deepEqual(opened.map(v=>v.path),['/course/lab-a/latest','/']);
 assert.equal(opened[0].label,'Latest');assert.equal(opened[0].commit,'c1');
});
test('gitViewVersion falls back to a slash-free label when no friendly name is given, e.g. opened from the review dialog',async()=>{
 const context=makeContext();let html='';
 context.json=async()=>({files:[]});
 context.opDialog=(id,title,markup)=>{html=markup;return {querySelector:()=>({onclick:null})};};
 context.$=()=>({onclick:null});
 await context.gitViewVersion('lab',{commit:'c'.repeat(40),path:'/course/lab-a/checkpoints/day-1'});
 assert.match(html,/<p class="op-path">course\/lab-a\/checkpoints\/day-1<\/p>/);
 await context.gitViewVersion('lab',{commit:'c'.repeat(40),path:'/'});
 assert.match(html,/<p class="op-path">the repository root<\/p>/);
});
test('gitLegacyDestinationNotice warns when a lab folder is itself shaped like the snapshot it holds, and says nothing for an ordinary folder',()=>{
 const context=makeContext();
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:'JunOS-TEST-2/working/latest'}}),
  'This lab saves to JunOS-TEST-2/working/latest, a folder named like a saved state, so its saves go to JunOS-TEST-2/working/latest/latest. To save into JunOS-TEST-2/working/latest again, open Change folder…, pick JunOS-TEST-2/working and choose Save this lab here without moving the files.');
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:'course/lab-a/checkpoints/day-1'}}),
  'This lab saves to course/lab-a/checkpoints/day-1, a folder named like a saved state, so its saves go to course/lab-a/checkpoints/day-1/latest. To save into course/lab-a/latest again, open Change folder…, pick course/lab-a and choose Save this lab here without moving the files.');
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:'latest'}}),
  'This lab saves to latest, a folder named like a saved state, so its saves go to latest/latest. To save into the top of the repository/latest again, open Change folder…, pick the top of the repository and choose Save this lab here without moving the files.','an empty parent reads as words, not a bare slash');
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:'bgp/work'}}),'','an ordinary lab folder gets no notice');
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:''}}),'');
 assert.equal(context.gitLegacyDestinationNotice(null),'');
});
test('a legacy binding shows the notice on the Save location card right under the destination line; an ordinary binding shows nothing',()=>{
 const context=makeContext(),container={innerHTML:'',querySelectorAll:()=>[]};
 context.$=id=>id==='git-repository-content'?container:null;context.state.labs=[{id:'lab',name:'BGP'}];
 context.gitRenderRepository('lab',{binding:{binding_id:'repo',node_names:['r1'],repository:{label:'x',path:'/home/ben/labs/Course-Labs',remote:'origin',branch:'main',prefix:'JunOS-TEST-2/working/latest',push_url:'https://github.com/ben/Course-Labs.git',owner:'ben'}},supported_nodes:[{name:'r1',platform:'arista_ceos'}]},{repositories:[]});
 assert.match(container.innerHTML,/<\/p><p class="op-notice" id="git-legacy-notice">This lab saves to JunOS-TEST-2\/working\/latest, a folder named like a saved state/);
 context.gitRenderRepository('lab',{binding:{binding_id:'repo',node_names:['r1'],repository:{label:'x',path:'/p',branch:'main',prefix:'bgp',owner:'ben'}},supported_nodes:[]},{repositories:[]});
 assert.doesNotMatch(container.innerHTML,/git-legacy-notice/,'an ordinary lab folder never shows the notice');
});
