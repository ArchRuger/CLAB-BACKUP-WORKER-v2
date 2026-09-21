const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/restore.js'),'utf8');
function ctx(){
 const context=vm.createContext({
  esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  crypto:{getRandomValues:bytes=>{for(let i=0;i<bytes.length;i++)bytes[i]=i;return bytes;}},
  state:{labs:[]},utcDisplay:v=>new Date(v).toISOString(),clearTimeout:()=>{},setTimeout:()=>0,
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
 assert.equal(c.restoreSourceLabel(null),'Saved configuration');
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
 assert.equal(c.restoreReasonLabel('Assign NOS credentials to this node first.'),'Add login credentials for this device first (Advanced › Credentials).');
 assert.equal(c.restoreReasonLabel('Live restore is not supported for this platform: cisco_iosv'),'This kind of device cannot be updated this way yet.','no platform is singled out any more');
 assert.equal(c.restoreReasonLabel('This saved configuration has no restore data for this node'),'This saved version was made before this kind of device could be restored. Save the lab again to get a restorable version.');
 assert.equal(c.restoreReasonLabel('The saved restore data for this node is not usable'),'The saved configuration for this device is incomplete or damaged, so it was not applied.');
 assert.equal(c.restoreReasonLabel('Another change is waiting for confirmation on this node'),'Someone else\'s configuration change is waiting for confirmation on this device. Try again when it has finished.');
 assert.equal(c.restoreReasonLabel('Something new'),'Something new');
 // rollback_expected and uncertain now count as "needs attention" (neither is a verified outcome);
 // rolled_back (checked, self-undone) counts as "not changed".
 assert.equal(c.restoreResultSentence({status:'partial',targets:[{status:'verified'},{status:'rolled_back'},{status:'uncertain'},{status:'rollback_expected'}]}),'Configuration replaced on 1 device. 2 devices need attention. 1 device was not changed.');
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
 const unknownKind=c.restoreTargetRow({name:'r1',status:'verified',platform:'linux'});
 assert.doesNotMatch(unknownKind,/<span class="caption">/,'an unknown kind shows no device-type label');
});
