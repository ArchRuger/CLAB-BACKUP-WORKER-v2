// workspace.js and workspace.html (docs/sign-on/UI.md 3.5, 4.4; REVIEW U5, U8, U11): the page that holds the topology browser and the
// CLI launcher. session.js does not load here: the stand-ins below have the exact contract of UI 3.2 (sessionLost, sessionMark,
// sessionEnded, sessionEndedError, sessionGo), so the page is tested both with them and without.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const STATIC=path.join(__dirname,'../app/static');
const source=fs.readFileSync(path.join(STATIC,'workspace.js'),'utf8');
const html=fs.readFileSync(path.join(STATIC,'workspace.html'),'utf8');
const VERSION=fs.readFileSync(path.join(__dirname,'../VERSION'),'utf8').trim();
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function page({hash='',session=true,answers=[],dialog=null}={}){
 const els=new Map(),fetches=[],handlers={},gone=[];
 const get=id=>{if(!els.has(id))els.set(id,{id,hidden:false,textContent:'',innerHTML:'',onclick:null,addEventListener(){},focus(){}});return els.get(id);};
 let ended=false;
 const queue=[...answers];
 const context=vm.createContext({URLSearchParams,decodeURIComponent,console,
  location:{hash},document:{getElementById:get,querySelectorAll:sel=>sel==='dialog[open]'?(Array.isArray(dialog)?dialog:dialog?[dialog]:[]):[],title:'',addEventListener:(type,fn)=>{handlers[type]=fn;}},
  window:{open:()=>({})},setTimeout:()=>1,clearTimeout:()=>{},
  fetch:async(url,options)=>{
   fetches.push(url);
   const next=queue.shift()||{status:200,body:{labs:[],jobs:[],operations:[]}};
   return {ok:next.status<400,status:next.status,json:async()=>next.body,headers:{get:()=>null}};
  },
  opTask:async(d,fn)=>fn(),opBrowse(){},opHistory(){}});
 if(session)Object.assign(context,{
  sessionLost:(status,data)=>status===401&&!!data&&typeof data==='object'&&!!data.detail&&data.detail.code==='signed_out',
  sessionMark:()=>{if(ended)return false;ended=true;return true;},sessionClear:()=>{ended=false;},
  sessionEnded:()=>ended,
  sessionEndedError:()=>Object.assign(new Error('Your session ended. Sign in again.'),{status:401,sessionEnded:true}),
  sessionGo:reason=>gone.push(reason)});
 vm.runInContext(source,context,{filename:'workspace.js'});
 const start=async()=>{handlers.DOMContentLoaded();await tick();await tick();};
 return {context,get,fetches,gone,start,ended:()=>ended,queue};
}
const SIGNED_OUT={status:401,body:{detail:{code:'signed_out',message:'Your session ended. Sign in again.'}}};
const ok=user=>({status:200,body:{labs:[],jobs:[],operations:[],user}});

test('workspace.html loads session.js with the release after status.js and before workspace.js, and marks the Diagnostics line',()=>{
 const scripts=[...html.matchAll(/<script src="\/static\/([^"?]+)\?v=([^"]+)" defer><\/script>/g)].map(m=>[m[1],m[2]]);
 const names=scripts.map(s=>s[0]);
 assert.ok(names.includes('session.js'),'session.js is loaded');
 assert.ok(names.indexOf('status.js')<names.indexOf('session.js')&&names.indexOf('session.js')<names.indexOf('workspace.js'),names.join(','));
 for(const [name,version] of scripts)assert.equal(version,VERSION,name+' carries ?v=<release>');
 assert.match(html,/<p class="workspace-links" id="workspace-links"><a href="\/static\/debug\.html">Diagnostics<\/a>/);
});
test('a 401 signed_out sends the person to the sign-in page at once, once, and the page holds nothing typed',async()=>{
 const p=page({answers:[SIGNED_OUT]});
 await p.start();
 assert.deepEqual(p.gone,['ended']);assert.equal(p.fetches.length,1);
 assert.equal(p.get('workspace-message').textContent,'Your session ended. Sign in again.');
});
test('while the page is marked signed out no request leaves it',async()=>{
 const p=page({answers:[SIGNED_OUT]});
 await p.start();
 const before=p.fetches.length;
 await assert.rejects(p.context.api('/state'),e=>e.sessionEnded===true&&e.status===401&&e.message==='Your session ended. Sign in again.');
 await assert.rejects(p.context.json('/operations/browse','POST',{}),e=>e.sessionEnded===true);
 assert.equal(p.fetches.length,before,'the helpers throw without a request');assert.deepEqual(p.gone,['ended'],'and without a second navigation');
});
test('a 401 that is not signed_out keeps its own wording and does not navigate; the answer\'s detail.message is shown (REVIEW U11)',async()=>{
 const p=page({answers:[{status:401,body:{detail:{code:'invalid_credentials',message:'Wrong name or password.'}}}]});
 await p.start();
 assert.deepEqual(p.gone,[]);assert.equal(p.get('workspace-message').textContent,'Wrong name or password.');
 const q=page({answers:[{status:403,body:{detail:{code:'admin_required',message:'Administrators only.'}}}]});
 await q.start();assert.equal(q.get('workspace-message').textContent,'Administrators only.');
 const old=page({answers:[{status:500,body:{detail:'The manager failed.'}}]});
 await old.start();assert.equal(old.get('workspace-message').textContent,'The manager failed.','a plain string detail still reads');
 const bare=page({answers:[{status:502,body:{}}]});
 await bare.start();assert.equal(bare.get('workspace-message').textContent,'Request failed.');
});
test('an operator is not sent to Diagnostics: the line is hidden; an administrator keeps it (REVIEW U5)',async()=>{
 const operator=page({answers:[ok({name:'olga',role:'operator',must_change_password:false})]});
 await operator.start();assert.equal(operator.get('workspace-links').hidden,true);
 const admin=page({answers:[ok({name:'ada',role:'admin',must_change_password:false})]});
 await admin.start();assert.equal(admin.get('workspace-links').hidden,false);
 const none=page({answers:[ok(undefined)]});
 await none.start();assert.equal(none.get('workspace-links').hidden,false,'no user in the answer: the line stays as it was');
});
test('a page without session.js behaves as before: the error is shown, nothing navigates, nothing throws',async()=>{
 const p=page({session:false,answers:[SIGNED_OUT]});
 await p.start();
 assert.equal(p.get('workspace-message').textContent,'Your session ended. Sign in again.');
 assert.equal(p.fetches.length,1);
});
test('the CLI launcher mode still lists the devices and opens the history from a signed-in page',async()=>{
 const lab={id:'L1',name:'BGP',nodes:[{name:'clab-BGP-r1',short_name:'r1',ssh_ready:true,address:'10.0.0.1'},{name:'clab-BGP-r2',short_name:'r2',ssh_ready:false,address:'10.0.0.2'}]};
 const p=page({hash:'#lab=L1&mode=ssh',answers:[{status:200,body:{labs:[lab],jobs:[],operations:[],user:{name:'ada',role:'admin'}}}]});
 await p.start();
 assert.equal(p.get('workspace-title').textContent,'Open CLIs · BGP');
 assert.match(p.get('workspace-message').textContent,/^1 of 2 devices ready\./);
 assert.match(p.get('workspace-content').innerHTML,/Open CLI <span/);assert.match(p.get('workspace-content').innerHTML,/id="ssh-launch-all" >/);
});

const dialogWith=fields=>({querySelectorAll:()=>fields});
test('a 401 signed_out while a dialog holds typed text keeps the page; it leaves once, on the next request, when nothing typed remains',async()=>{
 const fields=[{type:'textarea',value:'name: lab\ntopology: {}'}];
 const p=page({answers:[SIGNED_OUT],dialog:dialogWith(fields)});
 await p.start();
 assert.deepEqual(p.gone,[],'the typed topology is not thrown away');assert.ok(p.ended(),'the page is marked signed out');
 const before=p.fetches.length;
 await assert.rejects(p.context.api('/state'),e=>e.sessionEnded===true&&/Sign in again/.test(e.message));
 assert.deepEqual(p.gone,[],'still typed: still no navigation');assert.equal(p.fetches.length,before,'and a read sends no request (only the person\'s own act is let through, see the held-page tests)');
 fields[0].value='';
 await assert.rejects(p.context.api('/state'),e=>e.sessionEnded===true);
 assert.deepEqual(p.gone,['ended']);
 await assert.rejects(p.context.api('/state'));assert.deepEqual(p.gone,['ended'],'once');
});
test('a read-only or empty field in an open dialog does not hold the page',async()=>{
 const p=page({answers:[SIGNED_OUT],dialog:dialogWith([{type:'textarea',value:'x',readOnly:true},{type:'text',value:'  '}])});
 await p.start();assert.deepEqual(p.gone,['ended']);
});

test('stacked dialogs: typed text in a lower or upper dialog holds the page, whichever is first in the document',async()=>{
 const browser=dialogWith([{type:'text',value:'',readOnly:false}]),editor=dialogWith([{type:'textarea',value:'name: lab'}]);
 const p=page({answers:[SIGNED_OUT],dialog:[browser,editor]});
 await p.start();
 assert.deepEqual(p.gone,[],'the topology typed in the second open dialog is kept');assert.ok(p.ended());
});
// Rewritten claim, same test: the held sentence no longer says "press this button again", which is false for a read-only act (an output poll); it says "try again here" and still names the new tab and the kept text.
test('a held page: the error says what to do (sign in in a new tab, try again here, the text is kept) and names no button',async()=>{
 const p=page({answers:[SIGNED_OUT],dialog:dialogWith([{type:'textarea',value:'name: lab'}])});
 await p.start();
 await assert.rejects(p.context.api('/state'),e=>e.sessionEnded===true&&/new tab/.test(e.message)&&/try again here/.test(e.message)&&/still here/.test(e.message)&&!/button/.test(e.message));
});
test('a held page: after signing in elsewhere the next Create is sent; a 401 again holds the page again',async()=>{
 const fields=[{type:'textarea',value:'name: lab'}];
 const p=page({answers:[SIGNED_OUT,SIGNED_OUT,{status:200,body:{ok:1}}],dialog:dialogWith(fields)});
 await p.start();
 const before=p.fetches.length;
 await assert.rejects(p.context.json('/operations/preview','POST',{}),e=>e.status===401&&/new tab/.test(e.message));
 assert.equal(p.fetches.length,before+1,'the held page lets one act of the person through');
 assert.ok(p.ended(),'the 401 marked the page again');assert.deepEqual(p.gone,[],'and it is still held');
 const result=await p.context.json('/operations/preview','POST',{});
 assert.deepEqual(result,{ok:1});assert.equal(p.fetches.length,before+2);assert.equal(p.ended(),false,'a success leaves the page signed in');
});

// UI 3.2 stand-ins of sessionOnResume and sessionRetry: retry clears the mark, runs the page's refresh() and then the registered resume functions, and resolves whether the session is back.
function withRetry(p,{back=true}={}){
 const resume=new Set();let retries=0;
 Object.assign(p.context,{
  sessionOnResume:fn=>{if(typeof fn==='function')resume.add(fn);},
  sessionRetry:async()=>{retries++;p.context.sessionClear();if(!back){p.context.sessionMark();return false;}await p.context.refresh();const fns=[...resume];resume.clear();for(const fn of fns)await fn();return true;}});
 return {retries:()=>retries,resume};
}
test('a held page: a person-initiated act calls sessionRetry() and is sent only when it resolves true; otherwise the held error is thrown and nothing is sent',async()=>{
 const p=page({answers:[SIGNED_OUT],dialog:dialogWith([{type:'textarea',value:'name: lab'}])});
 const r=withRetry(p,{back:false});
 await p.start();
 const before=p.fetches.length;
 await assert.rejects(p.context.json('/operations/preview','POST',{}),e=>e.sessionEnded===true&&/new tab/.test(e.message));
 assert.equal(r.retries(),1);assert.equal(p.fetches.length,before,'sessionRetry() said no: nothing was sent');
 assert.ok(p.ended());
});
test('a held page: with a running job, the output poll goes quiet on the 401, the dialog shows the held sentence, and the next act resumes the poll',async()=>{
 const operations=fs.readFileSync(path.join(STATIC,'operations.js'),'utf8'),HELD='Your session ended. Sign in again in a new tab, then try again here; what you typed is still here.';
 const field={type:'textarea',value:'git@host:course/labs.git',readOnly:false,disabled:false};
 const line={textContent:''},out={textContent:'',innerHTML:'',hidden:false,className:'',scrollTop:0,scrollHeight:0,clientHeight:0};
 const dialog={id:'operation-output',open:true,onclose:null,classList:{toggle(){}},querySelector:sel=>sel==='.form-error'?line:sel==='h2'?{textContent:''}:null,querySelectorAll:()=>[field],close(){this.open=false;}};
 const clone={open:true,querySelector:sel=>sel==='.form-error'?{textContent:''}:null,querySelectorAll:()=>[field]};
 const p=page({answers:[SIGNED_OUT],dialog:[clone,dialog]});
 const r=withRetry(p);
 const timers=[];p.context.setTimeout=fn=>{timers.push(fn);return timers.length;};
 vm.runInContext(operations,p.context,{filename:'operations.js'});
 p.context.opDialog=()=>dialog;
 p.get('op-job-banner');p.get('op-job-output');p.get('op-job-result');
 // The first answer (a 401) is the poll's own GET; the person's act and the resumed poll then see running jobs.
 const running={status:200,body:{id:'j1',action:'clone',status:'running',output:'cloning'}};
 p.queue.push(running);
 await p.context.opShowJob('j1');
 assert.ok(p.ended(),'the 401 marked the page signed out');assert.deepEqual(p.gone,[],'a typed dialog holds the page');
 assert.equal(line.textContent,HELD,'the dialog tells the person, though the poll swallows the error');
 assert.match(line.textContent,/new tab/);assert.equal(timers.length,0,'the quiet poll arms no timer and spends no retry');
 assert.equal(r.resume.size,1,'the poll waits for the resume');
 // The person's next act: sessionRetry() runs the registered poll before the act is sent.
 p.queue.push(running,{status:200,body:{ok:1}});
 const before=p.fetches.length;
 const result=await p.context.json('/operations/preview','POST',{});
 assert.deepEqual(result,{ok:1});assert.equal(r.retries(),1);
 assert.ok(p.fetches.slice(before).some(u=>u==='/api/operations/j1'),'the output poll asked again');
 assert.notEqual(line.textContent,HELD,'the held sentence is gone once the session is back');
 assert.equal(timers.length,1,'and the running job is polled on');
});
