const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/restore.js'),'utf8');
// Objects returned from the vm context are not reference-equal to a literal built in this realm even
// when they have the same shape, so deepStrictEqual on them needs a structural comparison instead.
const same=(actual,expected)=>assert.equal(JSON.stringify(actual),JSON.stringify(expected));
function ctx(){
 const context=vm.createContext({
  esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  crypto:{getRandomValues:bytes=>{for(let i=0;i<bytes.length;i++)bytes[i]=i;return bytes;}},
  state:{labs:[]},utcDisplay:v=>new Date(v).toISOString(),clearTimeout:()=>{},setTimeout:()=>0,
  // gitRepoName lives in git-progress.js, loaded before restore.js in the real page; restore.js only
  // calls it behind a typeof guard, so this suite stubs it the same way git-progress.js defines it.
  gitRepoName:repo=>String(repo?.path||'').split('/').filter(Boolean).pop()||repo?.label||'Repository',
  $:()=>null,api:async()=>({json:async()=>({})}),json:async()=>({}),opDialog:()=>({}),opTask:async()=>{},refresh:async()=>{}});
 vm.runInContext(source,context);return context;
}
test('restore request id is 32 hex characters',()=>{
 const id=ctx().restoreRequestId();
 assert.match(id,/^[0-9a-f]{32}$/);
});
test('source labels describe git and backup origins',()=>{
 const c=ctx();
 assert.match(c.restoreSourceLabel({type:'git',commit:'abcdef0123456789',path:'latest'}),/Saved version · abcdef0123/);
 assert.match(c.restoreSourceLabel({type:'backup',backup_job_id:'0123456789abcdef'}),/Backup · 0123456789/);
 assert.equal(c.restoreSourceLabel({type:'folder',path:'labs/BGP/solution/latest'}),'Saved version · labs/BGP/solution');
 assert.equal(c.restoreSourceLabel({type:'folder',path:'/labs/BGP/solution/latest'}),'Saved version · labs/BGP/solution','the wire form\'s leading slash is stripped for display too');
 assert.equal(c.restoreSourceLabel({type:'folder',path:'/'}),'Saved version · the repository root','the wire form of the repository root reads in words, not as a slash');
 assert.equal(c.restoreSourceLabel({type:'folder',path:'Final'}),'Saved version · Final','an exact snapshot folder with no latest/ suffix names itself');
 assert.equal(c.restoreSourceLabel({type:'folder',path:'/Final'}),'Saved version · Final');
 assert.equal(c.restoreSourceLabel(null),'Saved configuration');
});
test('restoreFromFolder sends the exact snapshot path over the wire with one leading slash, never a substituted /latest, and "/" for the repository root; a path that already carries the slash is not doubled',async()=>{
 const c=ctx(),sent=[];
 c.notify=()=>{};
 c.restoreReview=async(labId,source,label)=>sent.push({labId,source,label});
 await c.restoreFromFolder('lab','Final',{repository:{path:'/home/ben/Course-Labs'}});
 same(sent[0].source,{type:'folder',path:'/Final'});
 assert.match(sent[0].label,/^Final · Course-Labs › Final$/,'the label shown to the student never carries the wire\'s leading slash');
 await c.restoreFromFolder('lab','Broken/latest',{repository:{path:'/home/ben/Course-Labs'}});
 same(sent[1].source,{type:'folder',path:'/Broken/latest'},'the exact folder is sent; nothing appends another /latest');
 assert.match(sent[1].label,/^Broken · Course-Labs › Broken\/latest$/);
 await c.restoreFromFolder('lab','',{repository:{path:'/home/ben/Course-Labs'}});
 same(sent[2].source,{type:'folder',path:'/'},'the repository root is written "/" on the wire');
 assert.match(sent[2].label,/^the repository root · Course-Labs$/,'the root label names no path at all, never a bare slash');
 await c.restoreFromFolder('lab','/Final',{repository:{path:'/home/ben/Course-Labs'}});
 same(sent[3].source,{type:'folder',path:'/Final'},'a path that already carries the leading slash is not doubled');
 assert.match(sent[3].label,/^Final · Course-Labs › Final$/);
 await c.restoreFromFolder('lab','/',{repository:{path:'/home/ben/Course-Labs'}});
 same(sent[4].source,{type:'folder',path:'/'},'the wire-form root, given directly, stays "/"');
 const toasts=[];c.notify=m=>toasts.push(m);
 await c.restoreFromFolder('lab',undefined,{});
 assert.equal(sent.length,5,'nothing chosen sends no request');assert.match(toasts[0],/Choose a saved folder/);
});
test('restoreReview submits exactly the reviewed folder source (type, path, commit) and shows the pinned commit beside the source line; git and backup sources are sent unchanged',async()=>{
 const c=ctx(),calls=[],elements=new Map(),dialogs=[];
 const field=()=>({checked:false,value:'5',textContent:''});
 const makeDialog=()=>({innerHTML:'',close(){},querySelector:()=>({onclick:null}),querySelectorAll(sel){return sel==='[data-op-close]'?[]:sel==='[name="restore-node"]:checked'?[{value:'r1'}]:[];}});
 c.opDialog=()=>{const d=makeDialog();dialogs.push(d);return d;};c.opTask=async(d,fn)=>fn();c.refresh=async()=>{};
 c.$=id=>elements.get(id)||(elements.set(id,field()),elements.get(id));
 c.json=async(endpoint,method,payload)=>{calls.push({endpoint,method,payload});
  if(endpoint.endsWith('/preflight'))return {source:{commit:'c'.repeat(40)},targets:[{name:'r1',short_name:'r1',eligible:true,platform:'arista_ceos'}]};
  return {id:'job',lab_id:'lab',status:'queued',targets:[]};};
 await c.restoreReview('lab',{type:'folder',path:'course/lab/latest'},'Latest · Course-Labs › course/lab/latest');
 assert.match(dialogs[0].innerHTML,/c{10}/,'the commit is shown, first 10 characters, beside the source line');
 c.$('restore-ack').checked=true;
 await elements.get('restore-run').onclick();
 assert.equal(calls[1].endpoint,'/labs/lab/restore');
 assert.deepEqual(Object.keys(calls[1].payload.source).sort(),['commit','path','type'],'the API model forbids extra keys on a folder source');
 assert.equal(calls[1].payload.source.commit,'c'.repeat(40));assert.equal(calls[1].payload.source.path,'course/lab/latest');
 // A git source is submitted unchanged: it already names its own commit.
 calls.length=0;elements.clear();
 c.json=async(endpoint,method,payload)=>{calls.push({endpoint,method,payload});
  if(endpoint.endsWith('/preflight'))return {source:{commit:'d'.repeat(40)},targets:[{name:'r1',short_name:'r1',eligible:true,platform:'arista_ceos'}]};
  return {id:'job2',lab_id:'lab',status:'queued',targets:[]};};
 await c.restoreReview('lab',{type:'git',commit:'e'.repeat(40),path:'checkpoints/day-1'},'Checkpoint');
 c.$('restore-ack').checked=true;
 await elements.get('restore-run').onclick();
 same(calls[1].payload.source,{type:'git',commit:'e'.repeat(40),path:'checkpoints/day-1'});
});
test('badge classes reflect status and escape the label text',()=>{
 const c=ctx(),labels={verified:'Applied and verified',applying:'Replacing',rollback_expected:'Rolled back',verify_mismatch:'Differences',rolled_back:'Undone',uncertain:'Unknown'};
 assert.match(c.restoreBadge('verified',labels),/badge good/);
 assert.match(c.restoreBadge('applying',labels),/badge running/);   // an active status polls
 // rollback_expected no longer claims a verified rollback, so it is not badged as a confirmed failure.
 assert.match(c.restoreBadge('rollback_expected',labels),/badge warn/);
 assert.match(c.restoreBadge('verify_mismatch',labels),/badge warn/);
 assert.match(c.restoreBadge('rolled_back',labels),/badge bad/,'a checked, self-undone change is a confirmed non-outcome');
 assert.match(c.restoreBadge('uncertain',labels),/badge warn/,'an unchecked device needs attention, not a confirmed failure');
 assert.match(c.restoreBadge('<x>',{}),/&lt;x&gt;/,'an unknown status label is escaped');
});
test('restorePlatformLabel shows a short device-type label for known containerlab kinds only',()=>{
 const c=ctx();
 assert.equal(c.restorePlatformLabel('juniper_cjunosevolved'),'Junos Evolved');
 assert.equal(c.restorePlatformLabel('juniper_vjunosswitch'),'Junos');
 assert.equal(c.restorePlatformLabel('juniper_vqfx'),'Junos');
 assert.equal(c.restorePlatformLabel('arista_ceos'),'EOS');
 assert.equal(c.restorePlatformLabel('cisco_xrv9k'),'IOS XR');
 assert.equal(c.restorePlatformLabel('linux'),'','an unknown kind shows nothing');
 assert.equal(c.restorePlatformLabel(undefined),'');
});
test('restore words: preflight reasons, result sentence and titles are the student\'s, the backend text stays available',()=>{
 const c=ctx();
 assert.equal(c.restoreReasonLabel('SSH probe failed: TimeoutError'),'The device did not answer over SSH.');
 assert.equal(c.restoreReasonLabel('The node rejected the login credentials.'),'The device rejected the login. Check its credentials (Advanced › Credentials).','a wrong password is not "did not answer"');
 assert.equal(c.restoreReasonLabel('Assign NOS credentials to this node first.'),'Add login credentials for this device first (Advanced › Credentials).');
 assert.equal(c.restoreReasonLabel('Live restore is not supported for this platform: cisco_iosv'),'This kind of device cannot be updated this way yet.','no platform is singled out any more');
 assert.equal(c.restoreReasonLabel('This saved configuration has no restore data for this node'),'This saved version was made before this kind of device could be restored. Save the lab again to get a restorable version.');
 assert.equal(c.restoreReasonLabel('The saved restore data for this node is not usable'),'The saved configuration for this device is incomplete or damaged, so it was not applied.');
 assert.equal(c.restoreReasonLabel('Another change is waiting for confirmation on this node'),'Someone else\'s configuration change is waiting for confirmation on this device. Try again when it has finished.');
 assert.equal(c.restoreReasonLabel('Something new'),'Something new');
 // rollback_expected and uncertain now count as "needs attention" (neither is a verified outcome);
 // rolled_back (checked, self-undone) counts as "not changed".
 assert.equal(c.restoreResultSentence({status:'partial',targets:[{status:'verified'},{status:'rolled_back'},{status:'uncertain'},{status:'rollback_expected'}]}),'Configuration replaced on 1 device. 2 devices need attention. 1 device undid the change; its previous configuration is back.','an undone device was changed for a while: it is not counted as "not changed"');
 assert.equal(c.restoreResultSentence({status:'partial',targets:[{status:'verified'},{status:'failed'},{status:'rolled_back'},{status:'rolled_back'}]}),'Configuration replaced on 1 device. 2 devices undid the change; their previous configuration is back. 1 device was not changed.');
 assert.equal(c.restoreResultSentence({status:'applying',targets:[{status:'applying'}]}),'');
 assert.equal(c.restoreJobTitle({status:'applying'}),'Applying saved configuration');assert.equal(c.restoreJobTitle({status:'succeeded'}),'Configuration replaced');assert.equal(c.restoreJobTitle({status:'preflight_failed'}),'Configuration not replaced');
 const tables=vm.runInContext('({job:restoreJobLabels,target:restoreTargetLabels})',c);
 for(const key of ['pending','backing_up','applying','confirming','applied','verified','applied_unverified','verify_mismatch','rollback_expected','rolled_back','uncertain','failed','ineligible','interrupted'])assert.ok(tables.target[key],key+' has a label');
 assert.equal(new Set(Object.values(tables.target)).size,14,'all fourteen target states stay distinct');
 assert.doesNotMatch(Object.values(tables.job).join(' ')+Object.values(tables.target).join(' '),/router|✓|✔/,'devices, and no text glyphs');
 assert.doesNotMatch(tables.target.rollback_expected,/rolled back/i,'the old status no longer claims a verified rollback');
});
test('a job target row shows the device-type label, the new status help lines and the persistence warning',()=>{
 const c=ctx();
 const rolledBack=c.restoreTargetRow({name:'ceos1',status:'rolled_back',platform:'arista_ceos'});
 assert.match(rolledBack,/badge bad/);
 assert.match(rolledBack,/EOS/);
 assert.match(rolledBack,/The device could not be confirmed in time, so it undid the change by itself\. The manager checked: the previous configuration is active\./);
 const uncertain=c.restoreTargetRow({name:'xrv1',status:'uncertain',platform:'cisco_xrv9k'});
 assert.match(uncertain,/badge warn/);
 assert.match(uncertain,/IOS XR/);
 assert.match(uncertain,/The manager could not check this device after the change\. Look at it before relying on it\./);
 const notConfirmed=c.restoreTargetRow({name:'vjunos1',status:'rollback_expected',platform:'juniper_vjunosswitch'});
 assert.match(notConfirmed,/badge warn/);
 assert.match(notConfirmed,/<span class="caption">Junos<\/span>/);
 assert.match(notConfirmed,/The change was not confirmed in time\. The device is set to undo it by itself; the manager has not checked that yet\./);
 assert.doesNotMatch(notConfirmed,/returned to its previous configuration/,'the old, unverified wording is gone');
 const evolved=c.restoreTargetRow({name:'evo1',status:'verified',platform:'juniper_cjunosevolved'});
 assert.match(evolved,/Junos Evolved/);
 const notSaved=c.restoreTargetRow({name:'ceos2',status:'verified',platform:'arista_ceos',persistence:'not_saved'});
 assert.match(notSaved,/Replaced, but the device did not save it as its startup configuration; a device restart would lose it\./);
 const saved=c.restoreTargetRow({name:'ceos3',status:'verified',platform:'arista_ceos',persistence:'saved'});
 assert.doesNotMatch(saved,/did not save it as its startup configuration/);
 // A device that was not changed says why beside its badge, not only under Details (actionable).
 const refused=c.restoreTargetRow({name:'xrv9k',status:'failed',platform:'cisco_xrv9k',message:'Configuration was not changed: Another change on this node is already pending confirmation; this restore was not started.'});
 assert.match(refused,/form-help">Another change on this node is already pending confirmation; this restore was not started\.<\/p>/);
 const badLogin=c.restoreTargetRow({name:'ceos',status:'failed',platform:'arista_ceos',message:'Configuration was not changed. The node rejected the login credentials.'});
 assert.match(badLogin,/form-help">The device rejected the login\. Check its credentials/);
 const unreachable=c.restoreTargetRow({name:'ceos',status:'failed',platform:'arista_ceos',message:'Configuration was not changed. Connectivity: TimeoutError'});
 assert.match(unreachable,/form-help">The device did not answer over SSH\.<\/p>/);
 assert.doesNotMatch(c.restoreTargetRow({name:'x',status:'failed',platform:'arista_ceos',message:'Configuration was not changed: <b>x</b>'}),/<b>/,'escaped');
 const unknownKind=c.restoreTargetRow({name:'r1',status:'verified',platform:'linux'});
 assert.doesNotMatch(unknownKind,/<span class="caption">/,'an unknown kind shows no device-type label');
});
// --- per-device stages (the progress dialog) and the review diff ---------------------------------------
const stepStates=(c,t,now=1000)=>JSON.parse(JSON.stringify(c.restoreStageSteps(t,now)));
test('a queued device waits: nothing is highlighted and nothing claims a backup has started',()=>{
 const c=ctx(),steps=stepStates(c,{name:'r1',status:'pending',stage:'queued',timeline:{queued:990}});
 assert.equal(steps.length,7);
 assert.deepEqual(steps.map(s=>s.label),['Queued','Backup','Validate','Replace (timed recovery armed)','Fresh connection & read-back','Confirm','Done']);
 assert.ok(steps.every(s=>s.state==='waiting'&&s.text==='Waiting'),'queued is waiting, not a spinner');
 const row=c.restoreTargetRow({name:'r1',status:'pending',stage:'queued',timeline:{queued:990}});
 assert.doesNotMatch(row,/Backing up/);assert.doesNotMatch(row,/restore-stage--current/);
});
test('a running device shows finished steps done, its current step with words and elapsed time, and later steps waiting',()=>{
 const c=ctx();
 let steps=stepStates(c,{name:'r1',status:'backing_up',stage:'backing_up',timeline:{queued:980,backing_up:990}});
 assert.deepEqual(steps.slice(0,3).map(s=>s.state),['done','current','waiting']);
 assert.equal(steps[1].text,'Backing up the current configuration');assert.equal(steps[1].elapsed,'10 s');
 steps=stepStates(c,{name:'r1',status:'confirming',stage:'verifying',attempts:3,timeline:{queued:900,backing_up:910,backed_up:922,connecting:930,applying:931,armed:950,verifying:951}},1100);
 assert.deepEqual(steps.map(s=>s.state),['done','done','done','done','current','waiting','waiting']);
 assert.equal(steps[1].elapsed,'12 s');assert.equal(steps[2].elapsed,'20 s');assert.equal(steps[3].text,'Armed');
 assert.equal(steps[4].text,'Reconnecting and reading back (attempt 3)');assert.equal(steps[4].elapsed,'2 min 29 s');
 assert.ok(steps.every(s=>s.text),'every step says in words where it is; colour is never the only signal');
});
test('green only once the device is replaced: confirming and checking are not an outcome yet',()=>{
 const c=ctx(),base={queued:900,backing_up:901,backed_up:902,connecting:903,applying:904,armed:905,verifying:906,confirming:907};
 for(const t of [{status:'confirming',stage:'armed'},{status:'confirming',stage:'confirming'},{status:'applied',stage:'checking'}]){
  const steps=stepStates(c,{name:'r',timeline:{...base,settled:908,checking:909},...t});
  assert.ok(!steps.some(s=>s.state.startsWith('outcome-')),t.stage);
 }
 const checking=stepStates(c,{name:'r',status:'applied',stage:'checking',timeline:{...base,replaced:908,settled:908,checking:909}},915);
 assert.equal(checking[6].state,'current');assert.equal(checking[6].text,'Checking with a fresh backup');
 const done=stepStates(c,{name:'r',status:'verified',stage:'replaced',timeline:{...base,replaced:908,settled:908,checking:909,checked:930}});
 assert.deepEqual(done.map(s=>s.state),['done','done','done','done','done','done','outcome-good']);
 assert.equal(done[6].text,'Replaced and verified');assert.equal(done[6].elapsed,'total 30 s');
});
test('each final outcome is distinct in words and colour, and a stopped device shows where it stopped',()=>{
 const c=ctx(),outcome=t=>stepStates(c,{name:'r',...t})[6];
 const all={
  matched:outcome({status:'verified',stage:'matched',no_op:true,timeline:{queued:1,settled:2}}),
  skipped:outcome({status:'ineligible',stage:'skipped',timeline:{queued:1,settled:2}}),
  failed:outcome({status:'failed',stage:'failed',timeline:{queued:1,backing_up:2,backed_up:3,connecting:4,settled:5}}),
  rolled:outcome({status:'rolled_back',stage:'rolled_back',timeline:{queued:1,armed:3,verifying:4,settled:5}}),
  uncertain:outcome({status:'uncertain',stage:'uncertain',timeline:{queued:1,settled:2}}),
  verified:outcome({status:'verified',stage:'replaced',timeline:{queued:1,settled:2}})};
 assert.equal(all.matched.state,'outcome-good');assert.match(all.matched.text,/Already matched — no change needed/);
 assert.equal(all.skipped.state,'outcome-skip');assert.equal(all.skipped.text,'Skipped');
 assert.equal(all.failed.state,'outcome-bad');assert.match(all.failed.text,/not changed/);
 assert.equal(all.rolled.state,'outcome-warn');assert.match(all.rolled.text,/Rolled back — previous configuration read back/);
 assert.equal(all.uncertain.state,'outcome-warn');assert.match(all.uncertain.text,/Uncertain/);
 assert.equal(new Set(Object.values(all).map(o=>o.text)).size,6,'six different sentences');
 const failed=stepStates(c,{name:'r',status:'failed',stage:'failed',timeline:{queued:1,backing_up:2,backed_up:3,connecting:4,settled:5}});
 assert.deepEqual(failed.map(s=>s.state),['done','done','stopped','unreached','unreached','unreached','outcome-bad']);
 const skipped=stepStates(c,{name:'r',status:'ineligible',stage:'skipped',timeline:{queued:1,settled:2}});
 assert.deepEqual(skipped.map(s=>s.state),['done','unreached','unreached','unreached','unreached','unreached','outcome-skip']);
 const noOp=stepStates(c,{name:'r',status:'verified',stage:'matched',no_op:true,timeline:{queued:1,armed:3,settled:5}});
 assert.equal(noOp[3].text,'Armed — no change needed');
});
test('the device rows and the progress line are rebuilt from the job document alone (reopen, reload, any settle order)',()=>{
 const job={id:'j',status:'applying',progress:{settled:2,total:3},targets:[
  {name:'c',status:'verified',stage:'replaced',timeline:{queued:1,connecting:5,armed:6,verifying:7,confirming:8,replaced:9,settled:9,checked:12}},
  {name:'a',status:'confirming',stage:'verifying',attempts:1,timeline:{queued:1,connecting:5,armed:6,verifying:7}},
  {name:'b',status:'failed',stage:'failed',timeline:{queued:1,connecting:5,settled:6}}]};
 const render=()=>{const c=ctx();const doc=JSON.parse(JSON.stringify(job));return doc.targets.map(t=>c.restoreTargetRow(t,c.restoreJobNow(doc))).join('')+c.restoreProgressLine(doc);};
 const first=render(),second=render();
 assert.equal(first,second,'a fresh page renders the same rows from the same document');
 assert.match(first,/2 of 3 devices settled/);
 assert.match(first,/restore-stage--outcome-good/);assert.match(first,/restore-stage--outcome-bad/);assert.match(first,/restore-stage--current/);
 assert.equal(ctx().restoreProgressLine({progress:{settled:0,total:1}}),'<p class="restore-progress" role="status">0 of 1 device settled</p>');
 assert.equal(ctx().restoreProgressLine({}),'','a job stored before progress existed shows no line');
 assert.doesNotMatch(ctx().restoreTargetRow({name:'old',status:'verified'}),/restore-stage-list/,'a job stored before stages existed keeps its plain row');
 assert.doesNotMatch(ctx().restoreTargetRow({name:'<x>',short_name:'<x>',status:'pending',stage:'queued',timeline:{queued:1}}),/<x>/,'escaped');
});
test('the review offers each differing device its saved → running now differences before anything is submitted',()=>{
 const c=ctx(),diff={identical:false,truncated:false,added:1,removed:1,labels:{old:'Saved (Final)',new:'Running now'},
  hunks:[{old_start:1,old_count:1,new_start:1,new_count:1,lines:[{type:'del',old:1,new:null,text:'set snmp contact <A>'},{type:'add',old:null,new:1,text:'set snmp contact B'}]}]};
 const fallback=c.restoreDiffDetails({name:'r1',eligible:true,diff});
 assert.match(fallback,/<details class="restore-diff"><summary>Show differences \(saved → running now\)<\/summary>/);
 assert.match(fallback,/what the device runs right now/);
 assert.match(fallback,/--- Saved \(Final\)/);assert.match(fallback,/restore-diff-del">- set snmp contact &lt;A&gt;/);assert.match(fallback,/restore-diff-add">\+ set snmp contact B/);
 const calls=[];c.diffMarkup=(d,labels)=>{calls.push(labels);return '<div class="diff-view">shared</div>';};
 assert.match(c.restoreDiffDetails({name:'r1',eligible:true,diff}),/<div class="diff-view">shared<\/div>/,'the shared diff view is used when it is loaded');
 same(calls[0],{oldLabel:'Saved (Final)',newLabel:'Running now'});
 assert.match(c.restoreDiffDetails({name:'r1',eligible:true,diff:{...diff,truncated:true}}),/only its first part is shown/);
 assert.equal(c.restoreDiffDetails({name:'r1',eligible:true,diff:{identical:true,hunks:[]}}),'','"Already matches" says it; no empty diff');
 assert.match(c.restoreDiffDetails({name:'r1',eligible:true}),/The differences are not available for this device\./,'no data says why, never "0 differences"');
 assert.match(c.restoreDiffDetails({name:'r1',eligible:true,diff_reason:'The differences could not be shown for this device.'}),/could not be shown/);
 assert.equal(c.restoreDiffDetails({name:'r1',eligible:false,reason:'SSH probe failed'}),'','a skipped device already says why');
});
test('the review dialog places the differences beside each device, outside its checkbox label',async()=>{
 const c=ctx(),dialogs=[];
 c.opDialog=()=>{const d={innerHTML:'',close(){},querySelector:()=>({onclick:null}),querySelectorAll:()=>[]};dialogs.push(d);return d;};
 c.$=()=>({checked:false,value:'5',textContent:''});
 c.json=async()=>({source:{type:'backup',backup_job_id:'b'},targets:[
  {name:'r1',eligible:true,platform:'arista_ceos',pending_changes:2,diff:{identical:false,labels:{old:'Saved (backup b)',new:'Running now'},hunks:[{old_start:1,old_count:1,new_start:1,new_count:1,lines:[{type:'del',text:'hostname A'}]}]}},
  {name:'r2',eligible:true,platform:'arista_ceos',matches_saved:true,diff:{identical:true,hunks:[]}}]});
 await c.restoreReview('lab',{type:'backup',backup_job_id:'b'},'Backup');
 const html=dialogs[0].innerHTML;
 assert.match(html,/<\/label><details class="restore-diff">/,'the details follow the label, so opening them never ticks the box');
 assert.equal((html.match(/restore-diff"/g)||[]).length,1,'only the differing device has a diff');
 assert.match(html,/Already matches — nothing to change/);
});
test('elapsed times are measured on the manager\'s clock, never the browser\'s',()=>{
 const c=ctx();
 c.Date={now:()=>{throw new Error('the browser clock must not be read');}};
 vm.runInContext('Date={now:()=>{throw new Error("browser clock")}}',c);
 const job={id:'j',status:'applying',server_time:1060,targets:[{name:'a',status:'backing_up',stage:'backing_up',timeline:{queued:1000,backing_up:1010}}]};
 assert.equal(c.restoreJobNow(job),1060);
 const steps=JSON.parse(JSON.stringify(c.restoreStageSteps(job.targets[0],c.restoreJobNow(job))));
 assert.equal(steps[1].elapsed,'50 s');
 assert.equal(c.restoreJobNow({targets:[{timeline:{queued:5,settled:9}},{timeline:{queued:3,backing_up:12}}]}),12,'without server_time: the latest recorded time');
 assert.match(c.restoreTargetRow(job.targets[0],c.restoreJobNow(job)),/50 s/);
 assert.match(c.restoreTargetRow(job.targets[0]),/restore-stage--current/,'a row rendered on its own still renders');
});
test('a device that differs is never shown as identical: with no lines to show it says why',()=>{
 const c=ctx();
 const html=c.restoreDiffDetails({name:'r1',eligible:true,diff:{identical:false,hunks:[],reason:'The comparison found differences in spacing or layout that this line view cannot show.'}});
 assert.match(html,/differences in spacing or layout/);assert.doesNotMatch(html,/<details/);
});
