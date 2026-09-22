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
