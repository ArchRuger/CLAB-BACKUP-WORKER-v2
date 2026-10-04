const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/git-progress.js'),'utf8');
const diffViewSource=fs.readFileSync(path.join(__dirname,'../app/static/diff-view.js'),'utf8');
// Objects returned from the vm context are not reference-equal to a literal built in this realm even
// when they have the same shape, so deepStrictEqual on them needs a structural comparison instead.
const same=(actual,expected)=>assert.equal(JSON.stringify(actual),JSON.stringify(expected));
const readStatic=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8'),indexHtml=readStatic('index.html');
// Every page script of index.html, for the rules that hold across files.
const pageScripts=[...indexHtml.matchAll(/<script src="\/static\/([^"?]+\.js)/g)].map(m=>m[1]);
function makeContext(){
 const storage=new Map();let sequence=0;
 const context=vm.createContext({$:()=>null,state:{labs:[],jobs:[],git_jobs:[]},activeId:'lab',
  esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  utcDisplay:value=>new Date(value).toISOString(),
  crypto:{getRandomValues:bytes=>bytes.fill(++sequence)},
  sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  refresh:async()=>{},notify(){},clearTimeout:()=>{},setTimeout:()=>0});
 vm.runInContext(diffViewSource,context);vm.runInContext(source,context);return context;
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
 // The compare route's real diff (textdiff.unified()) lands here as file.diff; the file list's
 // markup escapes the filename and every diff line's text, whatever a saved configuration contains.
 const diff={identical:false,added:1,removed:1,truncated:false,hunks:[{old_start:1,old_count:1,new_start:1,new_count:1,lines:[
  {type:'del',old:1,new:null,text:'</pre><script>bad()</script>'},{type:'add',old:null,new:1,text:'router <peer> & policy'}]}]};
 const markup=context.gitFilesDiffMarkup([{name:attack,status:'changed',diff}],attack,'Saved');
 assert.doesNotMatch(markup,/<script>|<img/);assert.match(markup,/&lt;script&gt;/);assert.match(markup,/router &lt;peer&gt; &amp; policy/);
 assert.match(markup,/&lt;img src=x onerror=alert\(1\)&gt;/,'the filename itself is escaped too');
 const output=context.gitJobMarkup({status:'push_pending',message:attack,target:attack,commit:attack,created:'2026-09-11T12:00:00Z'});
 assert.doesNotMatch(output,/<img/);assert.match(output,/push pending/);
});
test('every option of the old Save progress menu has its home in the header, and none leads to a tab (owner decision D1, PROMPT 5.11)',async()=>{
 const context=makeContext(),opened=[];
 context.opTask=async(dialog,fn)=>fn();context.closeMenus=()=>{};context.showTab=()=>{throw new Error('no tab is opened');};
 context.saveDrawerOpen=(kind,options)=>opened.push('drawer:'+kind+(options.mode?':'+options.mode:'')+(options.address?':address':''));
 context.saveOpenPanel=kind=>opened.push('panel:'+kind);
 for(const action of ['settings','versions','load','browse','push','connect'])await context.gitRunAction(action,'lab');
 assert.deepEqual(opened,['drawer:settings','drawer:versions','panel:load','drawer:chooser:browse','panel:status','drawer:chooser:location:address']);
 await assert.rejects(context.gitRunAction('checkpoint','lab'),/not available here/,'Create checkpoint… is Keep as a checkpoint on a save; Save on this VM only is Save, then Not now');
 assert.doesNotMatch(indexHtml,/id="git-save-menu"|id="git-save-help|data-git-action=/);assert.match(indexHtml,/<button type="button" class="button primary" id="git-save-progress"[^>]*>Save<\/button>/);
 for(const gone of ['gitSaveHelp','gitSaveHelpMarkup','gitRenderSaveHelp','gitShowSaveHelp','gitSaveMenuPlacement','gitPlaceSaveMenu','gitInsideMenu','gitActionButtons'])assert.equal(typeof context[gone],'undefined',gone);
});
test('the help pane went with the split menu (D1): what a control does is said where it is, in the panel that offers it',()=>{
 const header=readStatic('save-header.js'),chooser=readStatic('git-places.js');
 assert.match(header,/Saved files can contain passwords or keys\./);assert.match(header,/Your first save goes to /);assert.match(header,/You can keep working\./);
 assert.match(chooser,/Saved files can contain passwords or keys\./);
 assert.doesNotMatch(indexHtml+source,/git-save-help/);
});
test('the header’s panels are placed by shell.js (initPanel), right-aligned, from the left of a wrapped control or under the whole row: git-progress.js places nothing any more',()=>{
 const shell=readStatic('shell.js');
 assert.match(shell,/menu-clamped/);assert.match(shell,/panel-anchored/);assert.match(shell,/getBoundingClientRect\(\)\.left<8|getBoundingClientRect\(\)\.left>=8/);
 assert.doesNotMatch(source,/getBoundingClientRect|menu-from-left|menu-stacked/);
 assert.match(indexHtml,/class="button secondary panel-button save-chip" id="save-chip"/);assert.match(indexHtml,/class="button secondary panel-button" id="load-button"/);
});
test('Git Unix commit timestamps are interpreted as seconds (Full history…)',async()=>{
 const context=makeContext();let html='';
 context.api=async()=>({json:async()=>({versions:[],commits:[{commit:'a'.repeat(40),message:'Save',time:1789128000},{commit:'b'.repeat(40),message:'Old',time:0}]})});
 context.opDialog=(id,title,markup)=>{html=markup;return {querySelectorAll:()=>[]};};
 await context.gitHistory('lab');
 assert.match(html,/2026-09-11T12:00:00\.000Z/);assert.doesNotMatch(html,/1970-01-21/,'never read as milliseconds');
});
test('placing a lab always carries the acknowledgement, beside the sentence about passwords and keys (D5: the tick box of a changed destination became that sentence)',()=>{
 const drawers=readStatic('save-drawers.js'),header=readStatic('save-header.js'),chooser=readStatic('git-places.js');
 assert.match(drawers,/const body=\{.*node_names:names,acknowledge:true,/,'the chooser’s place request');assert.match(header,/base=\{choice:'',pending:'',move_files:false,acknowledge:true\}/,'the first save’s place request');
 assert.match(chooser,/<p class="save-note">Saved files can contain passwords or keys\.<\/p>/);assert.match(header,/const SAVE_EXPOSURE='Saved files can contain passwords or keys\.'/);
 for(const name of pageScripts)assert.doesNotMatch(readStatic(name),/git-exposure|GIT_EXPOSURE/,name+': the old tick box is gone');
 assert.equal(typeof makeContext().gitBindingChanged,'undefined');
});
test('repository selection identifies the verified remote URL and branch: the chooser says where uploads of the selected repository go',()=>{
 const context=makeContext();for(const name of ['status.js','git-places.js'])vm.runInContext(readStatic(name),context);
 const tree={files:[],folders:[{path:'',folder:'',kind:'free',exists:true}]},view={mode:'location',status:'ready',value:'',labName:'bgp',repoName:'BENS-BGP-LAB',expanded:new Set(['']),repository:'r1',
  repositories:[{id:'r1',name:'BENS-BGP-LAB',remote:'https://github.com/ben/BENS-BGP-LAB.git',branch:'main'},{id:'r2',name:'lab',remote:'',branch:'main'}]};
 let html=context.folderChooserMarkup(context.folderChooserModel(tree),view);
 assert.match(html,/id="folder-uploads">Uploads go to github\.com\/ben\/BENS-BGP-LAB, branch main\.</);
 html=context.folderChooserMarkup(context.folderChooserModel(tree),{...view,repository:'r2'});
 assert.doesNotMatch(html,/folder-uploads|undefined|Uploads go to/,'a repository without a known address says nothing');
});
test('connected repository displays the push URL as escaped text (Save settings › Git details)',()=>{
 const context=makeContext();vm.runInContext(readStatic('save-drawers.js'),context);
 const html=context.saveSettingsMarkup('lab',{binding:{binding_id:'repo',node_names:[],repository:{label:'BENS-BGP-LAB',remote:'origin',branch:'main',push_url:'https://github.com/ben/<img onerror="bad()">.git'}},supported_nodes:[],unsupported_nodes:[],repository_status:{ready:true}},{repositories:[]},{});
 assert.match(html,/Verified push destination/);assert.match(html,/https:\/\/github.com\/ben\/&lt;img/);assert.doesNotMatch(html,/<img|href=/);
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
test('one-click save sends the save at once with an empty label (D2), captures fresh configurations and delegates review preference to server',async()=>{
 const context=makeContext(),calls=[],dialogs=[];
 context.opDialog=id=>{dialogs.push(id);return {open:true,close(){}};};
 context.opTask=async(dialog,fn)=>fn();
 context.gitLoadContext=async()=>({binding:{node_names:['r1'],review_before_push:true}});
 context.gitSubmitSave=async(id,request)=>calls.push({id,request});
 await context.gitSaveProgress();
 assert.equal(calls.length,1,'the save is sent by the click itself');assert.deepEqual(dialogs,[],'no dialog asks for a label');
 assert.equal(calls[0].id,'lab');assert.equal(calls[0].request.target,'latest');assert.equal(calls[0].request.push,true);
 assert.equal(calls[0].request.note,'','the manager names the save');assert.equal(calls[0].request.allow_removed,true);assert.equal(calls[0].request.node_names,undefined);
 // The lab in /api/state decides without a request when the page holds it.
 context.state.labs=[{id:'lab',name:'bgp',git_binding:{binding_id:'b'}}];context.gitLoadContext=async()=>{throw new Error('not asked');};
 await context.gitSaveProgress();assert.equal(calls.length,2);
 const opened=0;context.state.labs=[];context.gitLoadContext=async()=>({binding:null});await assert.rejects(context.gitSaveProgress(),/first save asks where to save/,'without the chip panel nothing can ask where to save: said, never guessed');assert.equal(calls.length,2,'and nothing is saved');
 // With the header chip the first save is the chip panel's view: the panel opens and nothing is sent.
 const panels=[];context.saveOpenPanel=(kind,options)=>panels.push([kind,options&&options.focus]);context.state.labs=[{id:'lab',name:'bgp'}];
 await context.gitSaveProgress();assert.deepEqual(panels,[['status',true]]);assert.equal(opened,0);assert.equal(calls.length,2);
 // A refusal the chip panel shows is not thrown a second time; any other failure is.
 context.state.labs=[{id:'lab',name:'bgp',git_binding:{binding_id:'b'}}];
 context.gitSubmitSave=async()=>{throw Object.assign(new Error('busy'),{saveShown:true});};await context.gitSaveProgress();
 context.gitSubmitSave=async()=>{throw new Error('lost');};await assert.rejects(context.gitSaveProgress(),/lost/);
});
test('no label is asked anywhere (D2): the label dialog and its draft are gone, an empty note is a valid request, and the name is given afterwards in the chip panel',async()=>{
 const context=makeContext();
 for(const gone of ['gitLabelDialog','gitLabelDraft','gitSaveLabelDraft','gitValidateLabel','gitFirstSave'])assert.equal(typeof context[gone],'undefined',gone);
 assert.doesNotMatch(source,/What changed\?|git-label-/);
 const sent=[];context.json=async(endpoint,method,payload)=>{sent.push(payload);return {id:'j',lab_id:'lab',status:'queued',created:'2026-10-04T12:00:00Z'};};context.gitStartWatch=()=>{};
 await context.gitSubmitSave('lab',{target:'latest',push:true,note:''},undefined,{quiet:true});assert.equal(sent[0].note,'');
 const header=readStatic('save-header.js');
 assert.match(header,/<label class="sr-only" for="save-name">Name of this save<\/label><input id="save-name"/);assert.match(header,/'\/name','POST',\{note\}/);
 assert.match(header,/note\.length>120/,'an over-length name is refused before it is sent');
});
test('the review before an upload is mandatory: every upload of a save goes through the review, and only its button uploads, with the head that was shown',async()=>{
 const context=makeContext(),elements=new Map(),dialogs=new Map(),calls=[];
 const element=()=>({onclick:null,innerHTML:'',listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},querySelectorAll:()=>[],querySelector:()=>null});
 context.$=id=>elements.get(id)||dialogs.get(id)||null;context.opTask=async(dialog,fn)=>fn();context.refresh=async()=>{};context.gitStartWatch=()=>{};
 context.opDialog=(id,title,html)=>{for(const m of html.matchAll(/ id="([\w-]+)"/g))elements.set(m[1],element());const dialog={id,title,html,open:true,close(){this.open=false;this.onclose?.();},querySelector:()=>null};dialogs.set(id,dialog);return dialog;};
 context.json=async(endpoint,method,payload)=>{calls.push({endpoint,payload});return endpoint.endsWith('/compare')?{files:[{name:'r1.cfg',status:'modified',before:'a',after:'b'}],head:'h'.repeat(40),upload_job:'j',also_sends:[]}:{id:'j',lab_id:'lab',status:'queued',commit:'c'.repeat(40),created:'2026-09-11T12:00:00Z'};};
 const pending={id:'j',lab_id:'lab',status:'review_pending',target:'latest',commit:'c'.repeat(40),created:'2026-09-11T12:00:00Z'};
 assert.equal(context.gitNeedsReview(pending),true);assert.equal(context.gitNeedsReview({...pending,reviewed:'2026-09-11T12:01:00Z'}),false);assert.equal(context.gitNeedsReview({...pending,commit:''}),false);
 assert.equal(context.gitNeedsReview({...pending,target:'move'}),false,'a folder move has no configuration change to review');assert.equal(context.gitNeedsReview({...pending,status:'committed'}),true,'a local save uploaded later is reviewed too');
 // Without the What changed drawer there is no review, so nothing can be uploaded: said, never bypassed.
 await assert.rejects(context.gitReviewJob(pending),/did not load/);assert.equal(calls.length,0);
 // The review is the drawer: opening it requests nothing here and uploads nothing.
 const drawers=[];context.saveDrawerOpen=(kind,options)=>drawers.push([kind,options.job.id]);context.document={querySelectorAll:()=>[]};
 await context.gitReviewJob(pending);assert.deepEqual(drawers,[['changes','j']]);assert.equal(calls.length,0);
 // Upload without a review of this save on the page is refused in the page.
 context.state.git_jobs=[pending];
 await assert.rejects(context.gitReviewJob(pending,{upload:true}),/See what this upload sends before uploading\./);assert.equal(calls.length,0);
 // With the review shown, the upload states that the review happened and which head was shown.
 await context.gitReviewData(pending);await context.gitReviewJob(pending,{upload:true});
 assert.equal(calls[calls.length-1].endpoint,'/git/jobs/j/retry');assert.equal(JSON.stringify(calls[calls.length-1].payload),JSON.stringify({push:true,reviewed:true,head:'h'.repeat(40)}));
 // The save window leads to the review, never straight to the upload; a save whose review already happened and whose upload
 // failed goes the same way, because the saves under it may have changed since.
 for(const job of [pending,{...pending,status:'push_pending',reviewed:'x'}]){
  await context.gitShowJob('j',job);const actions=elements.get('git-job-actions').innerHTML;
  assert.match(actions,/data-git-job-action="review">See changes and upload…/);assert.doesNotMatch(actions,/data-git-job-action="push"/);assert.match(actions,/data-git-job-action="dismiss">Keep snapshot only/);
 }
 // A synced save is reviewed for reading only.
 await context.gitShowJob('j',{...pending,status:'synced',pushed:true});
 assert.match(elements.get('git-job-actions').innerHTML,/class="button secondary" data-git-job-action="review">See changes<\/button>/);assert.doesNotMatch(elements.get('git-job-actions').innerHTML,/upload|dismiss/);
 // A save that stopped before its commit is tried again on the VM (never with an upload) and then waits like any save.
 await context.gitShowJob('j',{...pending,status:'export_pending',commit:''});
 assert.match(elements.get('git-job-actions').innerHTML,/data-git-job-action="local">Try again</);assert.doesNotMatch(elements.get('git-job-actions').innerHTML,/data-git-job-action="(push|review)"/);
});
test('no page script offers to skip the review or sends the old preference',()=>{
 for(const name of pageScripts){const text=readStatic(name);assert.doesNotMatch(text,/git-review-before-push|Let me review changes/,name);assert.doesNotMatch(text,/review_before_push\s*:/,name+': no request carries the preference any more');}
 assert.match(readStatic('save-header.js'),/Not uploaded yet/,'nothing is uploaded without the person: a save waits, with Upload, Not now and See changes');
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
test('a stored request whose save already finished is never replayed: a later save with the same label captures afresh (audit L-8)',async()=>{
 const context=makeContext(),calls=[];let fail=true,now=Date.parse('2026-10-03T10:00:00Z');
 context.gitNow=()=>now;context.gitShowJob=async()=>{};context.gitStartWatch=()=>{};
 context.json=async(endpoint,method,payload)=>{calls.push(payload);if(fail)throw Error('Network interrupted');return {id:payload.request_id,lab_id:'lab',created:'2026-10-03T10:00:00Z',status:'queued'};};
 await assert.rejects(context.gitSubmitSave('lab',{target:'latest',push:true,note:'OSPF up'},undefined,{quiet:true}),/Network interrupted/);
 const lost=calls[0].request_id;fail=false;
 // The lost save was created, finished, reviewed and uploaded: the page now knows it as synced.
 context.state.git_jobs=[{id:lost,lab_id:'lab',status:'synced',created:'2026-10-03T10:00:00Z'}];
 await context.gitSubmitSave('lab',{target:'latest',push:true,note:'OSPF up'},undefined,{quiet:true});
 assert.notEqual(calls[1].request_id,lost);assert.match(calls[1].request_id,/^[a-f0-9]{32}$/);
 // Still running: the retry returns that same save instead of capturing twice.
 fail=true;await assert.rejects(context.gitSubmitSave('lab',{target:'latest',push:true,note:'BGP up'},undefined,{quiet:true}));
 const running=calls[2].request_id;fail=false;context.state.git_jobs=[{id:running,lab_id:'lab',status:'capturing'}];
 await context.gitSubmitSave('lab',{target:'latest',push:true,note:'BGP up'},undefined,{quiet:true});assert.equal(calls[3].request_id,running);
 // Unknown to the page but stored long ago: never replayed either.
 fail=true;await assert.rejects(context.gitSubmitSave('lab',{target:'latest',push:true,note:'ISIS up'},undefined,{quiet:true}));
 const old=calls[4].request_id;fail=false;now+=11*60*1000;context.state.git_jobs=[];
 await context.gitSubmitSave('lab',{target:'latest',push:true,note:'ISIS up'},undefined,{quiet:true});assert.notEqual(calls[5].request_id,old);
 // The payload sent is exactly the save request: no storage bookkeeping leaks onto the wire.
 same(Object.keys(calls[5]).sort(),['allow_removed','backup_job_id','checkpoint','expected_baseline','note','push','replace_baseline','request_id','target']);
});
test('double-clicking Save progress dispatches one save while the first request is pending',async()=>{
 const context=makeContext();let calls=0,release;
 context.json=()=>{calls++;return new Promise(resolve=>release=resolve);};context.gitShowJob=async()=>{};
 const first=context.gitSubmitSave('lab',{target:'latest'});await context.gitSubmitSave('lab',{target:'latest'});assert.equal(calls,1);
 release({id:'job',lab_id:'lab',created:'2026-09-11T12:00:00Z',status:'queued'});await first;
});
test('single-job review requests parent-versus-saved changes, not the latest snapshot',async()=>{
 const context=makeContext(),requests=[];
 context.json=async(endpoint,method,payload)=>{requests.push({endpoint,method,payload});return {files:[]};};
 await context.gitReviewData({id:'pending-job',lab_id:'lab',status:'review_pending',commit:'abc123',target:'latest'});
 assert.equal(requests.length,1);assert.equal(requests[0].endpoint,'/labs/lab/git/compare');assert.equal(requests[0].payload.job_id,'pending-job');assert.equal(requests[0].payload.commit,undefined);
});
test('save options close their own modal and one job poll continues after the output closes',async()=>{
 const context=makeContext(),elements=new Map(),dialogs=new Map(),timers=new Map();let timerId=0,stage='capturing',polls=0;
 const element=()=>({value:'',checked:false,querySelectorAll:()=>[]});
 for(const id of ['git-save-cancel','git-save-confirm','git-baseline-job','git-job-detail','git-job-actions'])elements.set(id,element());
 context.$=id=>elements.get(id)||dialogs.get(id)||null;
 context.opDialog=id=>{const dialog={open:true,close(){this.open=false;this.onclose?.();}};dialogs.set(id,dialog);return dialog;};
 context.opTask=async(dialog,fn)=>fn();
 context.gitLoadContext=async()=>({binding:{node_names:['r1'],repository:{label:'lab',branch:'main'}},repository_status:{}});
 context.setTimeout=fn=>{timers.set(++timerId,fn);return timerId;};context.clearTimeout=id=>timers.delete(id);context.tab='topology';
 const job={id:'save-job',lab_id:'lab',target:'latest',status:'queued',created:'2026-09-11T12:00:00Z'};
 context.json=async()=>job;
 context.api=async endpoint=>{assert.equal(endpoint,'/git/jobs/save-job');polls++;return {json:async()=>({...job,status:stage})};};
 // The one dialog left of the old save options: Choose a backup as starting point… (All versions).
 await context.gitSaveOptions('baseline','lab');elements.get('git-baseline-job').value='bk';await elements.get('git-save-confirm').onclick();
 assert.equal(dialogs.get('git-save-options').open,false);assert.equal(dialogs.get('git-job-dialog'),undefined,'a plain save is quiet: no job window opens');assert.equal(timers.size,1,'the save is watched in the background');
 await context.gitShowJob('save-job',job);assert.equal(dialogs.get('git-job-dialog').open,true);assert.equal(timers.size,1,'opening the window reuses the running watch');
 const tick=async()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);await fn();};
 await tick();assert.equal(polls,1);assert.equal(timers.size,1);
 dialogs.get('git-job-dialog').close();stage='synced';await tick();
 assert.equal(polls,2);assert.equal(timers.size,0);assert.equal(dialogs.get('git-job-dialog').open,false);
});
test('save rows read as student sentences and the job window keeps the raw status under Details',()=>{
 const context=makeContext();
 assert.equal(context.gitSaveSentence({status:'synced',target:'latest'}),'Saved and uploaded');
 assert.equal(context.gitSaveSentence({status:'committed',target:'checkpoint',checkpoint:'ospf-done'}),"Checkpoint 'ospf-done' saved");
 assert.equal(context.gitSaveSentence({status:'push_pending',target:'latest'}),'Saved on this VM — upload needs attention');
 assert.equal(context.gitSaveSentence({status:'dismissed',target:'update'}),'Repository updated');
 assert.equal(context.gitSaveSentence({status:'exporting',target:'move',snapshot_path:'labs/x/latest'}),'Moving saved files…');
 assert.equal(context.gitSaveSentence({status:'synced',target:'move',snapshot_path:'labs/x/latest'}),'Moved to folder labs/x');
 assert.equal(context.gitSavedAs({target:'baseline'}),'Starting point');assert.equal(context.gitSavePill({status:'capturing'}),'busy');assert.equal(context.gitSavePill({status:'failed'}),'danger');
 const markup=context.gitJobMarkup({id:'j',status:'push_pending',message:'push failed',target:'latest',commit:'abc',created:'2026-09-11T12:00:00Z'});
 assert.match(markup,/Saved on this VM — upload needs attention/);assert.match(markup,/<details><summary>Details<\/summary>/);assert.match(markup,/push pending/);
 assert.match(context.gitJobMarkup(null),/No saves yet/);
});

test('a save with nothing new that is already uploaded reads as saved: no review, no upload offered',()=>{
 const context=makeContext();
 const job={id:'u',lab_id:'lab',status:'unchanged',pushed:true,commit:'c'.repeat(40),target:'latest',changed_files:[]};
 assert.equal(context.gitNeedsReview(job),false,'there is nothing to review');
 assert.equal(context.gitSavePill(job),'ok');assert.equal(context.gitSaveSentence(job),'Saved — nothing had changed');
 assert.match(context.gitDoneToast(job),/Nothing changed since your last save/);
 assert.equal(context.gitJobTitle(job),'Saved');
});
test('the disabled reason of Save is visible text and a lab without a save location keeps the button enabled (the header, save-header.js)',()=>{
 const context=makeContext(),els=new Map(),el=id=>{if(!els.has(id))els.set(id,{id,hidden:false,disabled:false,textContent:'',className:'',addEventListener(){}});return els.get(id);};
 for(const id of ['save-chip','save-chip-text','save-chip-dot','git-save-progress','save-reason','load-button','save-panel-title-text','save-panel-dot'])el(id);
 context.$=id=>els.get(id)||null;let hold='';context.busyReason=()=>hold;
 const lab={id:'lab',name:'bgp',nodes:[],git_binding:{binding_id:'b',repository:{path:'/r',prefix:'a'},node_names:[]},git_status:{checked:true,ready:true}};
 context.state.labs=[lab];context.current=()=>context.state.labs[0];
 for(const name of ['status.js','save-header.js'])vm.runInContext(readStatic(name),context);
 context.renderSaveHeader();assert.equal(el('git-save-progress').disabled,false);assert.equal(el('save-reason').hidden,true);
 hold='A backup is running.';context.renderSaveHeader();
 assert.equal(el('git-save-progress').disabled,true);assert.equal(el('save-reason').textContent,'A backup is running. Save is available when it finishes.');assert.equal(el('save-reason').hidden,false);
 context.state.git_jobs=[{id:'s',lab_id:'lab',status:'capturing',target:'latest',created:'2026-10-04T12:00:00Z'}];hold='';context.gitStartWatch=()=>{};context.renderSaveHeader();
 assert.equal(el('git-save-progress').disabled,true);assert.equal(el('save-chip-text').textContent,'Saving…','a running save is said by the chip');
 context.state.git_jobs=[];context.state.labs=[{id:'lab',name:'bgp',nodes:[]}];hold='A backup is running.';context.renderSaveHeader();
 assert.equal(el('git-save-progress').disabled,false,'a lab without a save location keeps Save enabled: it opens the first-save view');
});
// Owner decision D1 with DESIGN.md 3.8 N3: the Saved versions card is All versions, and the page groups nothing itself. Which
// folder is a saved state (a manifest, whatever its name or depth), whose it is and what it is called is the manager's one list.
const withDrawers=()=>{const context=makeContext();for(const name of ['status.js','git-places.js','save-drawers.js'])vm.runInContext(readStatic(name),context);return context;};
// A row of the saved-states list the manager answers (GET …/restore/states): its group and its name are the manager's.
const stateRow=(path,group,more={})=>({path,commit:'abc',name:path.split('/').filter(p=>p!=='latest').pop()||'',group,lab:'',kind:'capture',saved_devices:2,loadable_devices:2,view_only:false,saved_at:'2026-10-01T10:00:00Z',...more});
test('saved versions list every saved state the manager names, from its exact path, in the manager’s groups: the page regroups nothing and invents no row',()=>{
 const context=withDrawers();
 const list={head:'abc',lab_devices:2,states:[stateRow('bgp/work/latest','latest'),stateRow('bgp/work/checkpoints/day-1','checkpoint'),stateRow('bgp/reference/start/latest','state',{name:'Start'}),
  stateRow('bgp/reference/solution','state',{name:'Solution'}),stateRow('bgp/final-state','state',{name:'Final-state'}),stateRow('bgp/reference/other/latest','other-lab',{lab:'OSPF',name:'Other'}),stateRow('zzz/vault','state',{name:'Vault'})]};
 const model=context.drwVersionsModel([],list,true);
 same(model.yours.map(r=>r.path),['bgp/work/latest']);same(model.checkpoints.map(r=>r.path),['bgp/work/checkpoints/day-1']);assert.equal(model.start.length,0);
 same(model.states.map(r=>r.path).sort(),['bgp/final-state','bgp/reference/solution','bgp/reference/start/latest','zzz/vault']);
 same(model.others.map(r=>r.lab+' '+r.path),['OSPF bgp/reference/other/latest']);
 const all=[...model.yours,...model.checkpoints,...model.states,...model.others];
 assert.ok(all.every(r=>context.drwVersionRequest(r,{list}).path==='/'+r.path),'every row is viewed and loaded from its exact folder, with the wire’s leading slash, never a substituted one');
 assert.ok(all.every(r=>context.drwSource(r,'').path==='/'+r.path&&context.drwSource(r,'').type==='folder'));
 assert.ok(!all.some(r=>r.path==='bgp/notes'),'a folder the manager does not list is never a saved version');
});
test('a top-level lab folder does not absorb the whole repository: only the rows the manager marks as the lab’s own are its own',()=>{
 const context=withDrawers();
 const list={head:'h',states:[stateRow('bgp/latest','latest'),stateRow('ospf/reference/latest','state',{name:'Reference'}),stateRow('archive/2025/week-1/bgp/latest','state',{name:'Bgp'})]};
 const model=context.drwVersionsModel([],list,true);
 same(model.yours.map(r=>r.path),['bgp/latest']);same(model.states.map(r=>r.path),['ospf/reference/latest','archive/2025/week-1/bgp/latest']);
});
test('a lab registered at the repository root does not claim every snapshot elsewhere in the repository as its own',()=>{
 const context=withDrawers();
 const list={head:'h',states:[stateRow('latest','latest'),stateRow('course/start/latest','state',{name:'Start'}),stateRow('other/latest','other-lab',{lab:'Edge'})]};
 const model=context.drwVersionsModel([],list,true);
 same(model.yours.map(r=>r.path),['latest']);same(model.states.map(r=>r.name),['Start']);same(model.others.map(r=>r.lab),['Edge']);
});
test('a snapshot at the repository root is viewed, compared, downloaded and loaded with "/" on the wire, never an empty path',()=>{
 const context=withDrawers();
 const list={head:'h',states:[stateRow('','state',{name:'Top level'})]},row=context.drwVersionsModel([],list,true).states[0];
 same(context.drwVersionRequest(row,{list}),{commit:'abc',path:'/'});assert.equal(context.drwSource(row,'').path,'/');
 same(context.drwVersionRequest(row,{list,repository:'r9'}),{commit:'abc',path:'/',repository:'r9'},'a lab without a save location names the repository');
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
test('View files of a save (the old review window’s "Open the full saved version") opens the job’s own snapshot path when known, else the binding prefix joined with the target',()=>{
 const context=withDrawers();context.state.labs=[{id:'lab',name:'bgp',git_binding:{repository:{prefix:'course/lab-a'}}}];
 assert.equal(context.drwJobPath({id:'j1',lab_id:'lab',target:'checkpoint',checkpoint:'day-1',snapshot_path:'course/lab-a/checkpoints/day-1'}),'course/lab-a/checkpoints/day-1');
 assert.equal(context.drwJobPath({id:'j2',lab_id:'lab',target:'latest'}),'course/lab-a/latest');
 assert.equal(context.drwJobPath({id:'j3',lab_id:'lab',target:'checkpoint',checkpoint:'x'}),'course/lab-a/checkpoints/x');
 assert.match(readStatic('save-drawers.js'),/saveDrawerOpen\('files',\{row:\{path:drwJobPath\(job\),commit:job\.commit\}/);
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
  'This lab saves to JunOS-TEST-2/working/latest, a folder named like a saved state, so its saves go to JunOS-TEST-2/working/latest/latest. To save into JunOS-TEST-2/working/latest again, open Change folder…, pick JunOS-TEST-2/working and choose Save here without bringing the saved files along.');
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:'course/lab-a/checkpoints/day-1'}}),
  'This lab saves to course/lab-a/checkpoints/day-1, a folder named like a saved state, so its saves go to course/lab-a/checkpoints/day-1/latest. To save into course/lab-a/latest again, open Change folder…, pick course/lab-a and choose Save here without bringing the saved files along.');
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:'latest'}}),
  'This lab saves to latest, a folder named like a saved state, so its saves go to latest/latest. To save into the top of the repository/latest again, open Change folder…, pick the top of the repository and choose Save here without bringing the saved files along.','an empty parent reads as words, not a bare slash');
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:'bgp/work'}}),'','an ordinary lab folder gets no notice');
 assert.equal(context.gitLegacyDestinationNotice({repository:{prefix:''}}),'');
 assert.equal(context.gitLegacyDestinationNotice(null),'');
});
test('a legacy binding shows the notice in Save settings right under the destination line; an ordinary binding shows nothing',()=>{
 const context=withDrawers();
 const settings=prefix=>context.saveSettingsMarkup('lab',{binding:{binding_id:'repo',node_names:['r1'],repository:{label:'x',path:'/home/ben/labs/Course-Labs',remote:'origin',branch:'main',prefix,push_url:'https://github.com/ben/Course-Labs.git',owner:'ben'}},supported_nodes:[{name:'r1',platform:'arista_ceos'}],unsupported_nodes:[],repository_status:{}},{repositories:[]},{});
 assert.match(settings('JunOS-TEST-2/working/latest'),/<\/p><p class="save-note" id="git-legacy-notice">This lab saves to JunOS-TEST-2\/working\/latest, a folder named like a saved state/);
 assert.doesNotMatch(settings('bgp'),/git-legacy-notice/,'an ordinary lab folder never shows the notice');
});
test('closeDialogsExcept closes every other open dialog layer, keeping only the named destination',()=>{
 const context=makeContext();
 const a={id:'a',open:true,close(){this.open=false;}},b={id:'b',open:true,close(){this.open=false;}},c={id:'c',open:false,close(){this.open=false;}};
 context.document={querySelectorAll:sel=>{assert.equal(sel,'dialog[open]');return [a,b,c].filter(d=>d.open);}};
 context.closeDialogsExcept('b');
 assert.equal(a.open,false);assert.equal(b.open,true,'the destination stays open');
 context.closeDialogsExcept();
 assert.equal(b.open,false,'nothing is kept when no destination is named');
});
test('E2 repro: opening a dialog, then a save\'s job window, then "View configuration backup" leaves no stale dialog open',async()=>{
 const context=makeContext(),dialogs=new Map(),elements=new Map();
 const plain=()=>({onclick:null,innerHTML:'',querySelectorAll:()=>[]});
 const actionsElement=()=>({
  dataset:{},_html:'',get innerHTML(){return this._html;},
  set innerHTML(v){this._html=v;this._buttons=[...v.matchAll(/data-git-job-action="(\w+)"/g)].map(m=>({dataset:{gitJobAction:m[1]},onclick:null}));},
  querySelectorAll(sel){return sel==='[data-git-job-action]'?(this._buttons||[]):[];},
 });
 const capture={dataset:{job:'bk'},open:false,scrollIntoView(){},focused:false,querySelector(sel){return sel==='summary'?{focus(){capture.focused=true;}}:null;}};
 elements.set('git-job-detail',plain());elements.set('git-job-actions',actionsElement());
 context.$=id=>elements.get(id)||dialogs.get(id)||null;
 context.opDialog=(id,title,html)=>{
  for(const m of html.matchAll(/ id="([\w-]+)"/g))if(!elements.has(m[1]))elements.set(m[1],plain());
  let dialog=dialogs.get(id);if(!dialog){dialog={id,open:false,close(){this.open=false;this.onclose?.();},querySelector:()=>null,querySelectorAll:()=>[]};dialogs.set(id,dialog);}
  dialog.title=title;dialog.open=true;return dialog;
 };
 context.document={querySelectorAll:sel=>{
  if(sel==='dialog[open]')return [...dialogs.values()].filter(d=>d.open);
  if(sel==='.job')return [capture];
  return [];
 }};
 context.opTask=async(dialog,fn)=>fn();context.refresh=async()=>{};context.notify=()=>{};
 context.selectLab=()=>{};context.showTab=()=>{};
 const pendingJob={id:'b',lab_id:'lab',status:'push_pending',commit:'d'.repeat(40),target:'latest',created:'2026-09-11T12:00:00Z',backup_job_id:'bk'};
 // Another dialog, opened first (the reported repro started in the pending dialog, which went with the tab: Full history… stands in).
 context.api=async()=>({json:async()=>({versions:[],commits:[]})});
 context.state.git_jobs=[{...pendingJob,id:'a'},pendingJob];
 await context.gitHistory('lab');
 assert.equal(dialogs.get('git-history-dialog').open,true);
 // Opening a save's job window: the dialog before it must not stay open underneath it.
 await context.gitShowJob(pendingJob.id,pendingJob);
 assert.equal(dialogs.get('git-history-dialog').open,false,'the earlier dialog is closed once the job window opens');
 assert.equal(dialogs.get('git-job-dialog').open,true);
 // "View configuration backup" navigates to the Backups tab: the job window must not stay open underneath it.
 const button=elements.get('git-job-actions').querySelectorAll('[data-git-job-action]').find(b=>b.dataset.gitJobAction==='backup');
 assert.ok(button,'the backup action is offered for a job with a capture');
 await button.onclick();
 assert.equal(dialogs.get('git-job-dialog').open,false,'the job window is closed once "View configuration backup" navigates away (E2)');
 assert.equal([...dialogs.values()].filter(d=>d.open).length,0,'no dialog is left open under the destination');
 assert.equal(capture.open,true);assert.equal(capture.focused,true,'focus moves to the destination');
});
test('E3: a save\'s frozen destination is shown in the job window as repository · branch · path, with its state, and the checkout path under Details',()=>{
 const context=makeContext();
 const job={id:'j',lab_id:'lab',status:'review_pending',commit:'c'.repeat(40),target:'latest',created:'2026-09-11T12:00:00Z',note:'OSPF up',
  destination:{repository:'Course-Labs',branch:'main',path:'Gtel-100G-G8032/Working/latest',checkout:'/home/ben/labs/bgp'}};
 const html=context.gitJobMarkup(job);
 assert.match(html,/Saving to<\/span><code>Course-Labs<\/code>.*<code>main<\/code>.*<code>Gtel-100G-G8032\/Working\/latest<\/code>/s);
 assert.match(html,/waiting for your review/);
 assert.match(html,/<dt>Destination<\/dt><dd>Course-Labs · main · Gtel-100G-G8032\/Working\/latest<\/dd>/);
 assert.match(html,/<dt>Checkout<\/dt><dd class="mono">\/home\/ben\/labs\/bgp<\/dd>/);
 assert.match(html,/<dt>Label<\/dt><dd>OSPF up<\/dd>/,'the label row is named Label, not Note');
 const synced=context.gitJobMarkup({...job,status:'synced',pushed:true,message:'Saved commit is included in the verified remote history.'});
 assert.match(synced,/verified on remote/);
 const uploaded=context.gitJobMarkup({...job,status:'synced',pushed:true,message:'Saved to Git.'});
 assert.match(uploaded,/uploaded to the remote/);
 assert.doesNotMatch(context.gitJobMarkup({...job,destination:undefined}),/Saving to|<dt>Destination<\/dt>/,'a job saved before this release has no destination row');
});
test('E1: a waiting save reads as its label and when, with "Not uploaded yet" as its second line (All versions; the pending list went with the tab)',()=>{
 const context=withDrawers();context.gitWhen=value=>'at '+value;
 const withLabel={id:'a',lab_id:'lab',status:'review_pending',commit:'c'.repeat(40),target:'latest',created:'2026-09-11T12:00:00Z',note:'OSPF adjacencies up',changed_files:['x'],snapshot_path:'bgp/latest'};
 const withoutLabel={id:'b',lab_id:'lab',status:'push_pending',commit:'d'.repeat(40),target:'checkpoint',checkpoint:'day-1',created:'2026-09-11T12:00:00Z'};
 const model=context.drwVersionsModel([withLabel,withoutLabel],{head:'h',states:[]},true);
 assert.equal(model.yours[0].name,'OSPF adjacencies up');assert.equal(model.yours[0].waiting,true);assert.equal(model.yours[0].when,'at 2026-09-11T12:00:00Z');
 assert.equal(model.activity[0].waiting,true);assert.equal(model.activity[0].name,"Checkpoint 'day-1'",'a save without a label falls back to what it is');
 assert.equal(model.activity[0].why,'Saved on this VM — upload needs attention');
});
test('a design export job window is titled "Design export…"; an ordinary save keeps its own wording',()=>{
 const context=makeContext();
 const design={id:'d',lab_id:'lab',kind:'design',status:'queued',target:'checkpoint',checkpoint:'design-abc'};
 assert.equal(context.gitJobTitle(design),'Design export in progress');
 assert.equal(context.gitJobTitle({...design,status:'review_pending'}),'Design export saved');
 assert.equal(context.gitJobTitle({...design,status:'committed'}),'Design export saved');
 assert.equal(context.gitJobTitle({...design,status:'failed'}),'Design export failed');
 assert.equal(context.gitJobTitle({...design,status:'push_pending'}),'Design export needs attention');
 assert.equal(context.gitJobTitle({id:'s',status:'queued',target:'latest'}),'Saving');
 assert.equal(context.gitJobTitle({id:'s',status:'committed',target:'latest'}),'Saved');
});
test('the What changed drawer of a design export is titled as one, never as a save of the lab; an ordinary save keeps its own title',()=>{
 const context=withDrawers();
 const pending={id:'d',lab_id:'lab',kind:'design',status:'review_pending',target:'checkpoint',checkpoint:'design-abc',commit:'c'.repeat(40),created:'2026-09-11T12:00:00Z'};
 const view=job=>context.drwChangesView({job,review:{files:[],head:'h',upload_job:job.id,also_sends:[]},error:'',also:new Map()});
 assert.equal(view(pending).title,'What this design export changed');assert.match(view(pending).actions,/data-save-action="upload"/);
 assert.equal(view({...pending,status:'synced',pushed:true}).title,'What this design export changed');assert.doesNotMatch(view({...pending,status:'synced',pushed:true}).actions,/data-save-action="upload"/);
 assert.equal(view({id:'s',lab_id:'lab',status:'review_pending',target:'latest',commit:'c'.repeat(40)}).title,'What changed');
});
test('a folder move reads as moved only once it committed; one that stopped or lost its answer is retried, never worded as moved',()=>{
 const context=makeContext(),move={id:'m',lab_id:'lab',target:'move',destination:{path:'labs/x'},created:'2026-10-03T12:00:00Z'};
 for(const status of ['failed','export_pending','interrupted']){
  const sentence=context.gitSaveSentence({...move,status});
  assert.doesNotMatch(sentence,/Moved/,status);assert.equal(sentence,'Moving the saved files did not finish — retry it');
  assert.equal(context.gitSavedAs({...move,status}),'Folder move to labs/x',status);
 }
 assert.doesNotMatch(context.gitSaveSentence({id:'old',target:'move',status:'failed',snapshot_path:''}),/repository root/,'an empty path no longer reads as moved to the root');
 assert.equal(context.gitSaveSentence({...move,status:'committed',commit:'c'.repeat(40),snapshot_path:'labs/x/latest'}),'Moved to folder labs/x');
 assert.equal(context.gitSaveSentence({...move,status:'push_pending',commit:'c'.repeat(40),snapshot_path:'labs/x/latest'}),'Moved to folder labs/x on this VM — upload needs attention');
 assert.equal(context.gitSaveSentence({...move,status:'synced',snapshot_path:'latest'}),'Moved to folder the repository root');
 assert.equal(context.gitSavedAs({...move,status:'synced',snapshot_path:'labs/x/latest'}),'Moved to labs/x');
 // In its window a move that stopped is tried again; one with a commit is uploaded only from What changed.
 assert.match(readStatic('git-progress.js'),/job\.target==='move'\?'Try the move again':'Try again'/);
});
test('a folder move waiting on the VM is uploaded through the review that names every save the upload sends (review follow-up J2; DESIGN.md 3.4)',async()=>{
 const context=withDrawers(),calls=[];
 context.opTask=async(dialog,fn)=>fn();context.refresh=async()=>{};context.notify=()=>{};context.gitStartWatch=()=>{};
 context.json=async(endpoint,method,payload)=>{calls.push({endpoint,payload});return endpoint.endsWith('/compare')?{files:[],head:'h1',upload_job:'m',also_sends:[{job_id:'k',lab:'other-lab',name:'OSPF <done>',kind:'',target:'latest'}]}:{id:'m',lab_id:'lab',status:'queued',target:'move',created:'2026-10-04T12:00:00Z'};};
 const move={id:'m',lab_id:'lab',lab_name:'bgp',target:'move',status:'committed',commit:'c'.repeat(40),snapshot_path:'bgp/latest',review_before_push:true,created:'2026-10-04T12:00:00Z',destination:{repository:'Course',path:'bgp'},moved_from:'old'};
 assert.equal(context.gitNeedsReview(move),true);assert.equal(context.gitNeedsReview({...move,reviewed:'2026-10-04T12:01:00Z'}),false);assert.equal(context.gitSaveSentence(move),'Moved to folder bgp');
 context.state.git_jobs=[move];context.state.labs=[{id:'lab',name:'bgp'}];
 // Nothing uploads a move without its review on the page.
 await assert.rejects(context.gitReviewJob(move,{upload:true}),/See what this upload sends/);assert.equal(calls.length,0);
 const review=await context.gitReviewData(move);
 const view=context.drwChangesView({job:move,review,error:'',also:new Map()});
 assert.match(view.content,/This moves the saved files of bgp from old to bgp\. No device file changes\./);
 assert.match(view.content,/This upload also sends 1 other save: OSPF &lt;done&gt; \(other-lab\)\./);assert.match(view.actions,/data-save-action="upload"/);
 assert.equal(context.saveChangeSentence(null,review.also_sends,move),'bgp’s saved files moved to bgp. This upload also sends 1 other save: OSPF <done> (other-lab).');
 await context.gitReviewJob(move,{upload:true});
 assert.equal(calls[calls.length-1].endpoint,'/git/jobs/m/retry');assert.equal(JSON.stringify(calls[calls.length-1].payload),'{"push":true,"reviewed":true,"head":"h1"}');
});
test('a move an older release marked failed offers its retry in the job window',async()=>{
 const context=makeContext(),elements=new Map(),dialogs=new Map();
 const element=()=>({onclick:null,innerHTML:'',textContent:'',querySelectorAll:()=>[]});
 for(const id of ['git-job-detail','git-job-actions'])elements.set(id,element());
 context.$=id=>elements.get(id)||dialogs.get(id)||null;context.closeDialogsExcept=()=>{};context.gitFocusDialog=()=>{};context.renderGitProgress=()=>{};
 context.opDialog=id=>{const dialog={id,open:true,close(){this.open=false;},querySelector:()=>null};dialogs.set(id,dialog);return dialog;};
 const failed={id:'m',lab_id:'lab',target:'move',status:'failed',created:'2026-10-03T12:00:00Z',destination:{path:'bgp'}};
 await context.gitShowJob('m',failed);
 const actions=elements.get('git-job-actions').innerHTML;
 assert.match(actions,/data-git-job-action="local">Try the move again</);assert.doesNotMatch(actions,/data-git-job-action="push"/,'the window never asks for an upload itself');
});
test('the review names the saves an upload carries from every lab of the checkout, and another lab\'s waiting save no longer blocks it (DESIGN.md 3.4)',async()=>{
 const context=withDrawers();
 let answer={files:[],head:'h',upload_job:'s',also_sends:[{job_id:'a',lab:'bgp',name:'Start',kind:'',target:'latest'},{job_id:'b',lab:'<b>',name:'ospf fixed',kind:'state',target:'latest'}]};
 context.json=async endpoint=>endpoint.endsWith('/compare')?answer:{};
 const save={id:'s',lab_id:'lab',status:'review_pending',target:'latest',commit:'c'.repeat(40),created:'2026-10-03T12:00:00Z',destination:{checkout:'/home/me/labs'}};
 const drawer=async()=>{const review=await context.gitReviewData(save,{fresh:true});return context.drwChangesView({job:save,review,error:'',also:new Map()});};
 let view=await drawer();
 assert.match(view.content,/This upload also sends 2 other saves: Start \(bgp\), ospf fixed \(&lt;b&gt;\)\./);
 assert.match(view.actions,/data-save-action="upload"/,'the upload is offered: the other lab\'s save goes along and is named');
 // The page's own knowledge is the floor: a waiting save of the same checkout the answer does not name is still named.
 context.state.git_jobs=[{...save,id:'earlier',commit:'d'.repeat(40),status:'committed',note:'Before lunch',lab_name:'bgp',created:'2026-10-03T11:00:00Z'},{...save,id:'elsewhere',commit:'e'.repeat(40),status:'committed',destination:{checkout:'/home/me/other'}}];answer={files:[],head:'h',upload_job:'s'};
 view=await drawer();
 assert.match(view.content,/This upload also sends 1 other save: Before lunch \(bgp\)\./,'a save of another checkout is not counted');
 // No save of the manager at the checkout's newest commit: no upload is offered and the drawer says why.
 context.state.git_jobs=[];answer={files:[],head:'h',upload_job:null,also_sends:[]};
 view=await drawer();
 assert.match(view.actions,/Someone is working in this repository on the VM\./);assert.doesNotMatch(view.actions,/data-save-action="upload"/);
});
test('the review names the saves kept with Keep snapshot only and the commits the manager no longer holds that the upload sends along (review follow-up G1)',async()=>{
 const context=withDrawers();
 let answer={files:[],head:'h',upload_job:'s',also_sends:[{job_id:'k',lab:'<b>-lab',name:'OSPF done',kind:'',target:'latest'},{commit:'f'.repeat(40),name:'Save r1: first save',files:['r1.cfg']}]};
 context.json=async endpoint=>endpoint.endsWith('/compare')?answer:{};
 const save={id:'s',lab_id:'lab',status:'review_pending',target:'latest',commit:'c'.repeat(40),created:'2026-10-03T12:00:00Z'};
 let review=await context.gitReviewData(save,{fresh:true});
 // Each save is named once; one the manager no longer holds is named by its subject, in quotes.
 assert.equal(context.saveChangeSentence({},review.also_sends).replace(/^.*?This upload/,'This upload'),'This upload also sends 2 other saves: OSPF done (<b>-lab) and "Save r1: first save".');
 const html=context.drwChangesView({job:save,review,error:'',also:new Map()}).content;
 assert.match(html,/OSPF done \(&lt;b&gt;-lab\)/);assert.doesNotMatch(html,/<b>-lab/);
 context.state.git_jobs=[{...save,id:'changed',commit:'9'.repeat(40)}];answer={files:[],head:'h',upload_job:'s',also_sends:[]};
 review=await context.gitReviewData(save,{fresh:true});
 assert.doesNotMatch(context.drwChangesView({job:save,review,error:'',also:new Map()}).content,/also sends/,'nothing else waits, nothing is named');
});
test('blocked site data never stops a save or leaves Save stuck: every storage call may throw (audit L-32, review follow-up G7)',async()=>{
 const context=makeContext(),calls=[],submitting=()=>vm.runInContext('gitSubmitting',context);
 const blocked=()=>{throw new Error('SecurityError: The operation is insecure.');};
 context.sessionStorage={getItem:blocked,setItem:blocked,removeItem:blocked};
 context.gitShowJob=async()=>{};context.gitStartWatch=()=>{};let fail=true;
 context.json=async(endpoint,method,payload)=>{calls.push(payload);if(fail)throw Error('Network interrupted');return {id:payload.request_id,lab_id:'lab',created:'2026-10-03T12:00:00Z',status:'queued'};};
 const values={target:'latest',push:true,note:'OSPF up'};
 await assert.rejects(context.gitSubmitSave('lab',values,undefined,{quiet:true}),/Network interrupted/);assert.equal(submitting(),false);
 fail=false;const job=await context.gitSubmitSave('lab',values,undefined,{quiet:true});
 assert.equal(job.id,calls[1].request_id);assert.match(job.id,/^[a-f0-9]{32}$/);assert.equal(submitting(),false);
 await context.gitSubmitSave('lab',{...values,target:'checkpoint',checkpoint:'ospf'},'f'.repeat(32),{quiet:true});assert.equal(calls[2].request_id,'f'.repeat(32));assert.equal(submitting(),false);
 // Storage that cannot even be reached (the property itself throws) is the same.
 Object.defineProperty(context,'sessionStorage',{get:blocked,configurable:true});
 await context.gitSubmitSave('lab',values,undefined,{quiet:true});assert.equal(calls.length,4);assert.equal(submitting(),false);
 // Whatever else fails on the way (here drawing the Saving… state), the next click still saves.
 let draws=0;context.renderSaveHeader=()=>{if(++draws===1)throw Error('draw failed');};
 await assert.rejects(context.gitSubmitSave('lab',values,undefined,{quiet:true}),/draw failed/);assert.equal(submitting(),false);
 await context.gitSubmitSave('lab',values,undefined,{quiet:true});assert.equal(calls.length,5);assert.equal(submitting(),false);
});
test('the last load line skips a load still read back after a restart, like the lab header (review follow-up H3; the Last load line of the chip panel)',()=>{
 // An interrupted load the manager still reads back (`rechecking: true`) holds the lab and is shown as devices being checked; the
 // Last load line (loadState.recent in status.js) must not name it as finished meanwhile.
 const context=makeContext();vm.runInContext(readStatic('status.js'),context);
 const lab={id:'lab',name:'bgp'};
 const older={id:'old',lab_id:'lab',status:'succeeded',created:'2026-10-01T09:00:00Z',finished:'2026-10-01T09:05:00Z',source:{type:'folder',path:'a/start/latest'},targets:[{name:'r1',status:'verified'}]};
 const recheck={id:'new',lab_id:'lab',status:'interrupted',rechecking:true,created:'2026-10-02T09:00:00Z',finished:'2026-10-02T09:01:00Z',source:{type:'folder',path:'a/final/latest'},targets:[{name:'r1',status:'interrupted',timeline:{settled:null}}]};
 const recent=jobs=>context.loadState(lab,{restore_jobs:jobs}).recent;
 assert.equal(recent([recheck,older]).job.id,'old','the older finished load stays named');
 assert.equal(recent([recheck]),null,'no line while the only load is still being read back');
 for(const flag of [false,undefined]){
  const plain={...recheck,rechecking:flag};if(flag===undefined)delete plain.rechecking;
  assert.equal(recent([plain,older]).job.id,'new','a load no longer read back is the last load');
 }
});
test('a lab folder inside the asking lab\'s folder keeps its saved states out of the asking lab\'s own list: they appear under the inner lab\'s name',()=>{
 const context=withDrawers();
 const list={head:'h',states:[stateRow('bgp/latest','latest'),stateRow('bgp/edge/latest','other-lab',{lab:'Edge',name:'Edge'})]};
 const model=context.drwVersionsModel([],list,true);
 same(model.yours.map(r=>r.path),['bgp/latest'],'only the lab\'s own latest is its own');
 same(model.others.map(r=>r.lab+' '+r.path),['Edge bgp/edge/latest'],'the inner lab\'s save is listed once, under that lab\'s name');
 assert.equal(model.states.length,0);
 assert.match(context.drwStateRow(list.states[1],'others',list).why,/^From Edge/);
});
test('a top-level lab is labelled "top level", not "whole repository", now that other labs may sit below it',()=>{
 const context=makeContext();
 context.gitRepository=()=>({prefix:''});context.gitRepoName=()=>'Course';
 assert.equal(context.gitFolderWords({binding_id:'x'}),'Course (top level)');
});
