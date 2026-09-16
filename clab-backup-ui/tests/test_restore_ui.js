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
 assert.match(c.restoreSourceLabel({type:'git',commit:'abcdef0123456789',path:'latest'}),/Git version · abcdef0123/);
 assert.match(c.restoreSourceLabel({type:'backup',backup_job_id:'0123456789abcdef'}),/Saved capture · 0123456789/);
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
