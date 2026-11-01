const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/debug.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
// A stand-in for app/static/session.js with the exact contract of docs/sign-on/UI.md 3.2 (the real file is S8's).
const SESSION_STAND_IN=`
let sessionFlag=false;const sessionFns=new Set();
function sessionLost(status,data){return status===401&&!!data&&typeof data==='object'&&!!data.detail&&typeof data.detail==='object'&&data.detail.code==='signed_out';}
function loginUrl(pathname,search,hash,reason){return '/login?next='+encodeURIComponent(pathname+search+hash)+(reason?'&reason=ended':'');}
function sessionEnded(){return sessionFlag;}
function sessionMark(){if(sessionFlag)return false;sessionFlag=true;return true;}
function sessionClear(){sessionFlag=false;}
function sessionEndedError(){return Object.assign(new Error('Your session ended. Sign in again.'),{status:401,sessionEnded:true});}
function sessionGo(reason){if(typeof location!=='undefined')location.replace(loginUrl(location.pathname,location.search,location.hash,reason));}
function sessionOnResume(fn){if(typeof fn==='function')sessionFns.add(fn);}
async function sessionRetry(){sessionClear();if(typeof refresh==='function'){try{await refresh();}catch{}}if(sessionFlag)return false;if(typeof sessionRestored==='function')sessionRestored();const fns=[...sessionFns];sessionFns.clear();for(const fn of fns){try{fn();}catch{}}return true;}
`;
function fixture(fetch,{session=false}={}){
 const moves=[];const elements=new Map(),downloads=[];let blob;
 const element=tag=>({tag,children:[],checked:false,disabled:false,value:'',textContent:'',
  append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},remove(){},click(){downloads.push(this.download);}});
 const get=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
 const context=vm.createContext({document:{getElementById:get,createElement:element,body:element('body')},fetch,Blob,
  URL:{createObjectURL:value=>{blob=value;return 'blob:fixture';},revokeObjectURL:()=>{}},setTimeout:fn=>fn(),
  location:{pathname:'/static/debug.html',search:'',hash:'',replace:url=>moves.push(url)}});
 if(session)vm.runInContext(SESSION_STAND_IN,context);
 vm.runInContext(source,context);
 return {context,get,downloads,moves,blob:()=>blob};
}
const snapshot={generated_at:'2026-09-11T12:00:00+00:00',manager_version:'1.19.0',python_version:'3.12',packages:{},uptime_seconds:10,vm:{configured:false},saved_counts:{labs:0},requests:[
 {time:'UTC',id:'one',method:'POST',route:'/api/operations/browse',status:409,duration_ms:15},
 {time:'UTC',id:'two',method:'GET',route:'/api/operations/capabilities',status:200,duration_ms:20}]};

test('debug report renders metadata as text and failures filter works',async()=>{
 const f=fixture(async()=>({ok:true,json:async()=>({...snapshot,manager_version:'<script>untrusted</script>'})}));await tick();
 assert.equal(f.get('debug-summary').children[0].children[1].children[1].textContent,'<script>untrusted</script>');
 assert.equal(f.get('debug-requests').children.length,2);
 f.get('debug-errors').checked=true;f.get('debug-errors').onchange();
 assert.equal(f.get('debug-requests').children.length,1);
 assert.equal(f.get('debug-download').disabled,false);
});

test('read-only check disables running button, exports results and omits input path',async()=>{
 let resolveProbe,request;
 const f=fixture(async(url,options)=>{
  if(url.endsWith('/probe')){request=JSON.parse(options.body);return new Promise(resolve=>{resolveProbe=resolve;});}
  return {ok:true,json:async()=>snapshot};
 });await tick();
 f.get('debug-path').value='/private/fixture-path';
 const running=f.get('debug-probe-form').onsubmit({preventDefault(){}});
 assert.equal(f.get('debug-probe').disabled,true);assert.equal(request.path,'/private/fixture-path');
 resolveProbe({ok:true,json:async()=>({generated_at:snapshot.generated_at,checks:[{check:'browse',status:'pass',entry_count:1,duration_ms:10},{check:'capabilities',status:'fail',message:'Check VM setup.',duration_ms:20}]})});
 await running;assert.equal(f.get('debug-probe').disabled,false);
 assert.match(f.get('debug-checks').children[1].textContent,/FAIL/);
 f.get('debug-download').onclick();
 const report=JSON.parse(await f.blob().text());assert.equal(report.probe.checks.length,2);
 assert.doesNotMatch(JSON.stringify(report),/fixture-path/);assert.match(f.downloads[0],/^clab-debug-.*\.json$/);
});

test('failed probe clears prior result and leaves retry available',async()=>{
 let fail=false;
 const f=fixture(async(url)=>url.endsWith('/probe')?
  fail?{ok:false,status:409}:{ok:true,json:async()=>({checks:[],generated_at:'UTC'})}:
  {ok:true,json:async()=>snapshot});await tick();
 await f.context.debugRun({preventDefault(){}});fail=true;await f.context.debugRun({preventDefault(){}});
 assert.equal(f.get('debug-probe').disabled,false);assert.match(f.get('debug-checks').children[0].textContent,/HTTP 409/);
 f.context.debugDownload();assert.equal(JSON.parse(await f.blob().text()).probe,null);
});

test('debug flags audit write failures without displaying exception details',async()=>{
 const f=fixture(async()=>({ok:true,json:async()=>({...snapshot,audit_log_available:false})}));await tick();
 assert.equal(f.get('debug-summary').children[0].children[1].children[7].textContent,'Failed — check storage');
});

test('the capabilities check line names the VM helper and the containerlab version as text',()=>{
 const f=fixture(async()=>({ok:true,json:async()=>snapshot}));
 const line=f.context.debugCheckLine({check:'capabilities',status:'pass',helper_version:'1.31.1',containerlab_version:'0.79.0',duration_ms:20});
 assert.equal(line,'VM commands — PASSED · VM helper 1.31.1 · containerlab 0.79.0 · 20 ms');
 assert.equal(f.context.debugCheckLine({check:'capabilities',status:'pass',helper_version:'1.31.1',duration_ms:20}),'VM commands — PASSED · VM helper 1.31.1 · 20 ms','an older answer without the version reads as before');
 assert.match(f.context.debugCheckLine({check:'capabilities',status:'pass',containerlab_version:'<b>0</b>',duration_ms:1}),/<b>0<\/b>/,'it is placed as text (the page uses textContent), never as markup');
});

const signedOutAnswer={ok:false,status:401,json:async()=>({detail:{code:'signed_out',message:'Your session ended. Sign in again.'}})};
test('a signed_out answer sends the page to the sign-in page once and later requests are not sent (UI 3.5, REVIEW U8)',async()=>{
 const sent=[];
 const f=fixture(async url=>{sent.push(url);return signedOutAnswer;},{session:true});await tick();
 assert.deepEqual(f.moves,['/login?next=%2Fstatic%2Fdebug.html&reason=ended'],'one location.replace, with the page as next');
 assert.equal(f.context.sessionEnded(),true);assert.equal(sent.length,1);
 await assert.rejects(()=>f.context.debugFetch(''),error=>error.sessionEnded===true&&error.status===401);
 await f.context.debugRefresh();await f.context.debugRun({preventDefault(){}});
 assert.equal(sent.length,1,'no request leaves a page that is signed out');assert.equal(f.moves.length,1);
});
test('a 401 that is not signed_out keeps the page and its plain error wording',async()=>{
 const f=fixture(async()=>({ok:false,status:401,json:async()=>({detail:'Nope'})}),{session:true});await tick();
 assert.equal(f.moves.length,0);assert.equal(f.context.sessionEnded(),false);assert.match(f.get('debug-status').textContent,/HTTP 401: Nope/);
});
test('403 admin_required shows the answer\'s own sentence in place of the report',async()=>{
 const f=fixture(async()=>({ok:false,status:403,json:async()=>({detail:{code:'admin_required',message:'Administrators only.'}})}),{session:true});await tick();
 assert.equal(f.get('debug-status').textContent,'Administrators only.');assert.equal(f.moves.length,0);
 assert.equal(f.get('debug-summary').children.length,0);assert.equal(vm.runInContext('debugSnapshot',f.context),null,'no report is shown');assert.equal(f.get('debug-refresh').disabled,false);
});
test('without session.js the page behaves as before (the harnesses of other pages load no session script)',async()=>{
 const f=fixture(async()=>signedOutAnswer);await tick();
 assert.equal(f.moves.length,0);assert.match(f.get('debug-status').textContent,/Your session ended|HTTP 401/);
});

// ---- the pages that load session.js (UI 3.2, 3.5; REVIEW U5) ----
const pageHtml=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8');
test('debug.html loads session.js with the release number before its own script',()=>{
 const html=pageHtml('debug.html');
 const tags=[...html.matchAll(/<script\b[^>]*\bsrc="(\/static\/[^"?]+)\?v=([\d.]+)"/g)];
 const session=tags.find(t=>t[1]==='/static/session.js');assert.ok(session,'session.js is loaded with ?v=');
 assert.ok(tags.every(t=>t[2]===session[2]),'one release number on every script');
 assert.ok(html.indexOf('session.js')<html.indexOf('debug.js'));
 assert.doesNotMatch(html,/\\sstyle=|<style/,'no inline style on this page');
});
test('vm-connection.html names Diagnostics in a role-neutral sentence and loads no script',()=>{
 const html=pageHtml('vm-connection.html'),text=html.replace(/<[^>]+>/g,'').replace(/\s+/g,' ');
 assert.match(text,/An administrator can open Diagnostics to check the manager version and the VM connection\./);
 assert.match(html,/<a href="\/static\/debug\.html">open Diagnostics<\/a>/);assert.doesNotMatch(html,/<script/);assert.doesNotMatch(html,/\sstyle=|<style/);
});
