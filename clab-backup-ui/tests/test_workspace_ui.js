// workspace.js and workspace.html (docs/sign-on/UI.md 3.5, 4.4; REVIEW U5, U8, U11): the page that holds the topology browser and the
// CLI launcher. session.js does not load here: the stand-ins below have the exact contract of UI 3.2 (sessionLost, sessionMark,
// sessionEnded, sessionEndedError, sessionGo), so the page is tested both with them and without.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const STATIC=path.join(__dirname,'../app/static');
const source=fs.readFileSync(path.join(STATIC,'workspace.js'),'utf8');
const html=fs.readFileSync(path.join(STATIC,'workspace.html'),'utf8');
const VERSION=fs.readFileSync(path.join(__dirname,'../VERSION'),'utf8').trim();
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function page({hash='',session=true,answers=[]}={}){
 const els=new Map(),fetches=[],handlers={},gone=[];
 const get=id=>{if(!els.has(id))els.set(id,{id,hidden:false,textContent:'',innerHTML:'',onclick:null});return els.get(id);};
 let ended=false;
 const queue=[...answers];
 const context=vm.createContext({URLSearchParams,decodeURIComponent,console,
  location:{hash},document:{getElementById:get,title:'',addEventListener:(type,fn)=>{handlers[type]=fn;}},
  window:{open:()=>({})},setTimeout:()=>1,clearTimeout:()=>{},
  fetch:async(url,options)=>{
   fetches.push(url);
   const next=queue.shift()||{status:200,body:{labs:[],jobs:[],operations:[]}};
   return {ok:next.status<400,status:next.status,json:async()=>next.body,headers:{get:()=>null}};
  },
  opTask:async(d,fn)=>fn(),opBrowse(){},opHistory(){}});
 if(session)Object.assign(context,{
  sessionLost:(status,data)=>status===401&&!!data&&typeof data==='object'&&!!data.detail&&data.detail.code==='signed_out',
  sessionMark:()=>{if(ended)return false;ended=true;return true;},
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
