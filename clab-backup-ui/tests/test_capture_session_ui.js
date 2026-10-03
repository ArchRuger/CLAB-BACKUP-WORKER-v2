const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/capture-session.js'),'utf8');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
function harness(responses,hash='#'+'a'.repeat(64)){
 const elements=new Map(),created=[],aborted=[],fetched=[];
 function $(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,href:''});return elements.get(id);}
 const document={getElementById:$,body:{appendChild(){}},createElement(tag){const el={tag,clicked:0,click(){this.clicked++;},remove(){}};created.push(el);return el;}};
 const fetch=async(url,options={})=>{fetched.push({url,options});const handler=Object.entries(responses).find(([suffix])=>url.endsWith(suffix));
  if(!handler)throw Error('unexpected fetch '+url);const reply=handler[1]();return {ok:reply.ok,status:reply.status??(reply.ok?200:404),json:async()=>reply.body??{}};};
 class AbortController{constructor(){this.signal={};}abort(){aborted.push(this);}}
 const c=vm.createContext({document,fetch,AbortController,location:{hash,protocol:'http:',host:'manager',reload(){}},
  confirm:()=>true,setInterval:()=>1,clearInterval(){},setTimeout:fn=>fn(),console});
 vm.runInContext(source,c);
 return {c,$,created,aborted,fetched};
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
