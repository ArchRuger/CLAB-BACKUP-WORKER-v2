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
 const c=ctx(),labels={verified:'Applied and verified',applying:'Replacing',rollback_expected:'Rolled back',verify_mismatch:'Differences'};
 assert.match(c.restoreBadge('verified',labels),/badge good/);
 assert.match(c.restoreBadge('applying',labels),/badge running/);   // an active status polls
 assert.match(c.restoreBadge('rollback_expected',labels),/badge bad/);
 assert.match(c.restoreBadge('verify_mismatch',labels),/badge warn/);
 assert.match(c.restoreBadge('<x>',{}),/&lt;x&gt;/,'an unknown status label is escaped');
});
test('restore words: preflight reasons, result sentence and titles are the student\'s, the backend text stays available',()=>{
 const c=ctx();
 assert.equal(c.restoreReasonLabel('SSH probe failed: TimeoutError'),'The device did not answer over SSH.');
 assert.equal(c.restoreReasonLabel('Assign NOS credentials to this node first.'),'Add login credentials for this device first (Advanced › Credentials).');
 assert.equal(c.restoreReasonLabel('Something new'),'Something new');
 assert.equal(c.restoreResultSentence({status:'partial',targets:[{status:'verified'},{status:'verify_mismatch'},{status:'rollback_expected'},{status:'ineligible'}]}),'Configuration replaced on 2 devices. 1 device needs attention. 2 devices were not changed.');
 assert.equal(c.restoreResultSentence({status:'applying',targets:[{status:'applying'}]}),'');
 assert.equal(c.restoreJobTitle({status:'applying'}),'Applying saved configuration');assert.equal(c.restoreJobTitle({status:'succeeded'}),'Configuration replaced');assert.equal(c.restoreJobTitle({status:'preflight_failed'}),'Configuration not replaced');
 const tables=vm.runInContext('({job:restoreJobLabels,target:restoreTargetLabels})',c);
 for(const key of ['pending','backing_up','applying','confirming','applied','verified','applied_unverified','verify_mismatch','rollback_expected','failed','ineligible','interrupted'])assert.ok(tables.target[key],key+' has a label');
 assert.equal(new Set(Object.values(tables.target)).size,12,'all twelve target states stay distinct');
 assert.doesNotMatch(Object.values(tables.job).join(' ')+Object.values(tables.target).join(' '),/router|✓|✔/,'devices, and no text glyphs');
});
