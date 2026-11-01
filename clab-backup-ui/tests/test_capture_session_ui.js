const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/capture-session.js'),'utf8');
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
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
function harness(responses,hash='#'+'a'.repeat(64),{session=false}={}){
 const elements=new Map(),created=[],aborted=[],fetched=[],intervals=[],cleared=[],moves=[];
 function $(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,href:''});return elements.get(id);}
 const document={getElementById:$,body:{appendChild(){}},createElement(tag){const el={tag,clicked:0,click(){this.clicked++;},remove(){}};created.push(el);return el;}};
 const fetch=async(url,options={})=>{fetched.push({url,options});const handler=Object.entries(responses).find(([suffix])=>url.endsWith(suffix));
  if(!handler)throw Error('unexpected fetch '+url);const reply=handler[1]();return {ok:reply.ok,status:reply.status??(reply.ok?200:404),json:async()=>reply.body??{}};};
 class AbortController{constructor(){this.signal={};}abort(){aborted.push(this);}}
 const c=vm.createContext({document,fetch,AbortController,location:{hash,protocol:'http:',host:'manager',pathname:'/static/capture-session.html',search:'',reload(){},replace:u=>moves.push(u)},
  confirm:()=>true,setInterval:fn=>{intervals.push(fn);return intervals.length;},clearInterval:id=>cleared.push(id),setTimeout:fn=>fn(),console});
 if(session)vm.runInContext(SESSION_STAND_IN,c);
 vm.runInContext(source,c);
 return {c,$,created,aborted,fetched,intervals,cleared,moves};
}
const base='/api/capture/sessions/'+'a'.repeat(64);
const live={[base]:()=>({ok:true,body:{name:'clab-demo-r1',interfaces:['eth2'],running:true,remaining_seconds:7000}}),'/assets/core/rfb.js':()=>({ok:false})};
test('download explains an empty capture folder instead of navigating to JSON',async()=>{
 const {$,created,aborted}=harness({...live,'/download':()=>({ok:false,body:{detail:'No saved captures yet. Use File > Save As under /pcaps.'}})});
 await settle();assert.equal($('capture-download').hidden,false);assert.equal($('capture-download').href,base+'/download');
 let prevented=0;await $('capture-download').onclick({preventDefault(){prevented++;}});
 assert.equal(prevented,1);assert.match($('viewer-status').textContent,/No saved captures yet/);
 assert.equal(created.length,0);assert.equal(aborted.length,0);
});
test('a saved capture is handed to the browser as a native download after the check passes',async()=>{
 const {$,created,aborted,fetched}=harness({...live,'/download':()=>({ok:true})});
 await settle();await $('capture-download').onclick({preventDefault(){}});
 assert.equal(aborted.length,1);assert.equal(fetched.filter(f=>f.url.endsWith('/download')).length,1);
 const link=created.find(el=>el.tag==='a');assert.equal(link.href,base+'/download');assert.equal(link.download,'wireshark-captures.tar');assert.equal(link.clicked,1);
 assert.match($('viewer-status').textContent,/Downloading saved captures.*\.pcapng/);
});
test('ending a session only disconnects a live viewer and clears the download link',async()=>{
 const {c,$,fetched}=harness({...live,'/end':()=>({ok:true})});
 await settle();
 vm.runInContext('rfb={disconnect(){globalThis.disconnected=(globalThis.disconnected||0)+1;}};rfbConnected=false',c);
 await $('capture-end').onclick();assert.equal(c.disconnected,undefined);
 assert.equal($('capture-end').disabled,true);assert.equal($('capture-download').hidden,true);assert.match($('viewer-status').textContent,/Session ended/);
 vm.runInContext('ended=false;rfbConnected=true',c);await $('capture-end').onclick();assert.equal(c.disconnected,1);
 assert.equal(fetched.filter(f=>f.url.endsWith('/end')&&f.options.method==='POST').length,2);
});
test('a stopped Wireshark desktop never promises its saved files and leaves the download as the check',async()=>{
 // AUDIT-2026-10-03 M-12 review: the service reports the loss only when the archive really is empty,
 // so the download stays available and answers for itself; the status never claims the files survived.
 const lost='The Wireshark desktop stopped and its saved files were lost with it. End this session and start a new capture.';
 const {$,fetched}=harness({[base]:()=>({ok:true,body:{name:'clab-demo-r1',interfaces:['eth2'],running:false,remaining_seconds:7000}}),
  '/download':()=>({ok:false,status:409,body:{detail:lost}})});
 await settle();
 assert.match($('viewer-status').textContent,/desktop stopped/);assert.match($('viewer-status').textContent,/Download saved captures/);
 assert.match($('viewer-status').textContent,/[Ee]nd this session/);assert.doesNotMatch($('viewer-status').textContent,/Download your saved files/);
 assert.equal($('capture-download').hidden,false);assert.equal($('capture-end').disabled,false);
 assert.equal(fetched.filter(f=>f.url.endsWith('/rfb.js')).length,0);
 await $('capture-download').onclick({preventDefault(){}});assert.equal($('viewer-status').textContent,lost);
});
test('the viewer answers its own desktop password challenge, which no other desktop knows',async()=>{
 const status={name:'clab-demo-r1',interfaces:['eth2'],running:true,remaining_seconds:7000,viewer_password:'Ab3x7k9Z'};
 const {c,$}=harness({[base]:()=>({ok:true,body:status}),'/assets/core/rfb.js':()=>({ok:true})});
 await settle();
 const made=[];c.loadRFB=async url=>({default:class{constructor(...args){made.push({url,args});this.listeners={};}addEventListener(name,fn){this.listeners[name]=fn;}}});
 await c.connectViewer();
 assert.equal(made.length,1);assert.equal(made[0].url,base+'/assets/core/rfb.js');
 assert.equal(made[0].args[1],'ws://manager'+base+'/websockify');
 assert.equal(JSON.stringify(made[0].args[2]),JSON.stringify({credentials:{password:'Ab3x7k9Z'}}));
 // A wrong or missing password is explained instead of leaving a silent blank viewer.
 vm.runInContext('rfb.listeners.credentialsrequired()',c);assert.match($('viewer-status').textContent,/password/);
});
test('a viewer module the relay refuses is explained with a next step, not the browser\'s raw import error',async()=>{
 const {c,$}=harness({[base]:()=>({ok:true,body:{name:'clab-demo-r1',interfaces:['eth2'],running:true,remaining_seconds:7000,viewer_password:'Ab3x7k9Z'}}),'/assets/core/rfb.js':()=>({ok:true})});
 await settle();
 // rfb.js itself is served, but a dependency it imports was refused (or vanished), so the dynamic import rejects.
 // The harness already ran connectViewer() once with the real loadRFB, so clear that outcome: only this rejection may produce the text.
 let loads=0;c.loadRFB=async()=>{loads++;throw new TypeError('Failed to fetch dynamically imported module: http://manager'+base+'/assets/core/rfb.js');};
 $('viewer-status').textContent='';
 await c.connectViewer();
 assert.equal(loads,1);
 const text=$('viewer-status').textContent;
 assert.doesNotMatch(text,/dynamically imported|TypeError|Failed to fetch/);
 assert.match(text,/Wireshark viewer could not be loaded/);
 assert.match(text,/Reconnect viewer/);
 assert.match(text,/end this session and start a new capture/);
});
test('a desktop that is still starting is polled until the time limit, then Reconnect is offered',async()=>{
 for(const status of [404,503]){
  const {$,fetched}=harness({...live,'/assets/core/rfb.js':()=>({ok:false,status,body:{detail:'Viewer asset unavailable. Reopen the capture session.'}})});
  await settle();
  assert.equal(fetched.filter(f=>f.url.endsWith('/rfb.js')).length,20,String(status));
  assert.match($('viewer-status').textContent,/taking longer than expected.*Reconnect viewer/);
 }
 // AUDIT-2026-10-03 L-28 review: an unreachable capture service (the manager's 503) may clear by itself, so it is retried too.
 const {$,fetched}=harness({...live,'/assets/core/rfb.js':()=>({ok:false,status:503,body:{detail:'Browser viewer unavailable. Click Reconnect viewer to try again.'}})});
 await settle();
 assert.equal(fetched.filter(f=>f.url.endsWith('/rfb.js')).length,20);
 assert.match($('viewer-status').textContent,/Reconnect viewer/);
});
test('a refused viewer file stops the start-up wait and shows the manager\'s reason',async()=>{
 // AUDIT-2026-10-03 L-28 review: a 502 for a viewer file that is not the pinned one never fixes itself by waiting.
 const detail='The Wireshark desktop served a viewer file that is not the pinned one, so it was not opened. End this session and start a new capture.';
 const {$,fetched}=harness({...live,'/assets/core/rfb.js':()=>({ok:false,status:502,body:{detail}})});
 await settle();
 assert.equal(fetched.filter(f=>f.url.endsWith('/rfb.js')).length,1);
 assert.equal($('viewer-status').textContent,detail);assert.doesNotMatch($('viewer-status').textContent,/taking longer|Starting Wireshark/);
 // A refusal without a JSON body still stops with controlled text.
 const bare=harness({...live,'/assets/core/rfb.js':()=>({ok:false,status:502,body:null})});
 await settle();assert.equal(bare.fetched.filter(f=>f.url.endsWith('/rfb.js')).length,1);
 assert.match(bare.$('viewer-status').textContent,/viewer unavailable/i);
});
test('an invalid session link never contacts the manager',async()=>{
 const {$,fetched}=harness(live,'#nope');
 await settle();assert.equal(fetched.length,0);assert.match($('viewer-status').textContent,/Invalid session link/);
 assert.equal($('capture-download').hidden,false);assert.equal($('capture-end').disabled,false);
});

test('the tab title tells up to four viewers apart; the toolbar text is unchanged',async()=>{
 const {c,$}=harness({...live});
 await settle();
 assert.equal(c.document.title,'clab-demo-r1 · eth2 — Wireshark');assert.equal($('capture-name').textContent,'clab-demo-r1 · eth2');
});

// ---- signed out while the viewer is open (docs/sign-on/UI.md 3.5) ----
const VIEWER_SENTENCE='Your session ended. Sign in again in the lab manager, then click Reconnect viewer.';
const signedOutBody={detail:{code:'signed_out',message:'Your session ended. Sign in again.'}};
test('the status request answering signed_out says the sentence, stops the heartbeat and never navigates',async()=>{
 const h=harness({[base]:()=>({ok:false,status:401,body:signedOutBody})},undefined,{session:true});
 await settle();
 assert.equal($v(h),VIEWER_SENTENCE);assert.equal(h.moves.length,0,'the viewer never navigates');
 assert.equal(h.c.sessionEnded(),true);assert.ok(h.cleared.length>=1,'clearInterval(heartbeat) ran');
 assert.equal(vm.runInContext('ended',h.c),false,'ended stays false so Reconnect viewer can work');
});
function $v(h){return h.$('viewer-status').textContent;}
test('the heartbeat sends nothing once the page is signed out and says the sentence on its own 401',async()=>{
 let signedOut=false;const h=harness({[base]:()=>signedOut?{ok:false,status:401,body:signedOutBody}:{ok:true,body:{name:'n',interfaces:['eth2'],running:true,remaining_seconds:7000}},'/assets/core/rfb.js':()=>({ok:false})},undefined,{session:true});
 await settle();assert.equal(h.intervals.length,1);
 signedOut=true;const before=h.fetched.length;await h.intervals[0]();
 assert.equal(h.fetched.length,before+1);assert.equal($v(h),VIEWER_SENTENCE);assert.ok(h.cleared.length>=1);
 await h.intervals[0]();assert.equal(h.fetched.length,before+1,'the guard: no second request');assert.equal($v(h),VIEWER_SENTENCE);
});
test('the asset probe, the download check and End session answer a signed_out the same way',async()=>{
 const ok={ok:true,body:{name:'n',interfaces:['eth2'],running:true,remaining_seconds:7000}};
 const probe=harness({[base]:()=>ok,'/assets/core/rfb.js':()=>({ok:false,status:401,body:signedOutBody})},undefined,{session:true});
 await settle();assert.equal($v(probe),VIEWER_SENTENCE);assert.equal(probe.fetched.filter(f=>f.url.endsWith('/rfb.js')).length,1,'no polling after the session ended');
 const dl=harness({...live,'/download':()=>({ok:false,status:401,body:signedOutBody})},undefined,{session:true});
 await settle();let prevented=0;await dl.$('capture-download').onclick({preventDefault(){prevented++;}});
 assert.equal(prevented,1);assert.equal($v(dl),VIEWER_SENTENCE);assert.equal(dl.created.length,0);
 const end=harness({...live,'/end':()=>({ok:false,status:401,body:signedOutBody})},undefined,{session:true});
 await settle();await end.$('capture-end').onclick();
 assert.equal($v(end),VIEWER_SENTENCE);assert.equal(vm.runInContext('ended',end.c),false,'a session that expired has not ended the capture');assert.equal(end.$('capture-end').disabled,false);
});
test('once signed out no helper sends a request (the guard, REVIEW U8)',async()=>{
 const h=harness({...live},undefined,{session:true});await settle();
 h.c.sessionMark();const before=h.fetched.length;
 await h.$('capture-download').onclick({preventDefault(){}});await h.$('capture-end').onclick();
 assert.equal(h.fetched.length,before);assert.equal($v(h),VIEWER_SENTENCE);
});
test('the capture relay\'s own 401 refusals keep their wording (they are not a lost session)',async()=>{
 const h=harness({[base]:()=>({ok:false,status:401,body:{detail:'This capture session belongs to another browser.'}})},undefined,{session:true});
 await settle();assert.equal($v(h),'This capture session belongs to another browser.');assert.equal(h.c.sessionEnded(),false);assert.equal(h.cleared.length,0);
});
test('a refusal object with a message is shown as its sentence (REVIEW U11)',async()=>{
 const h=harness({[base]:()=>({ok:false,status:403,body:{detail:{code:'forbidden',message:'Not allowed here.'}}})},undefined,{session:true});
 await settle();assert.equal($v(h),'Not allowed here.');
});
test('without session.js the viewer behaves as before',async()=>{
 const h=harness({[base]:()=>({ok:false,status:401,body:signedOutBody})});await settle();
 assert.equal(h.moves.length,0);assert.notEqual($v(h),'');
});

// ---- the pages that load session.js (UI 3.2, 3.5; REVIEW U5) ----
const pageHtml=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8');
test('capture-session.html loads session.js with the release number before its own script',()=>{
 const html=pageHtml('capture-session.html');
 const tags=[...html.matchAll(/<script\b[^>]*\bsrc="(\/static\/[^"?]+)\?v=([\d.]+)"/g)];
 const session=tags.find(t=>t[1]==='/static/session.js');assert.ok(session,'session.js is loaded with ?v=');
 assert.ok(tags.every(t=>t[2]===session[2]),'one release number on every script');
 assert.ok(html.indexOf('session.js')<html.indexOf('capture-session.js'));

});

// ---- the pages that load session.js (UI 3.2, 3.5; REVIEW U5) ----
test('capture-setup.html loads session.js with the release number before its own script',()=>{
 const html=pageHtml('capture-setup.html');
 const tags=[...html.matchAll(/<script\b[^>]*\bsrc="(\/static\/[^"?]+)\?v=([\d.]+)"/g)];
 const session=tags.find(t=>t[1]==='/static/session.js');assert.ok(session,'session.js is loaded with ?v=');
 assert.ok(tags.every(t=>t[2]===session[2]),'one release number on every script');

 assert.doesNotMatch(html,/\\sstyle=|<style/,'no inline style on this page');
});
