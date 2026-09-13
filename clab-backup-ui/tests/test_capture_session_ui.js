const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/capture-session.js'),'utf8');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
function harness(responses,hash='#'+'a'.repeat(64)){
 const elements=new Map(),created=[],aborted=[],fetched=[];
 function $(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,href:''});return elements.get(id);}
 const document={getElementById:$,body:{appendChild(){}},createElement(tag){const el={tag,clicked:0,click(){this.clicked++;},remove(){}};created.push(el);return el;}};
 const fetch=async(url,options={})=>{fetched.push({url,options});const handler=Object.entries(responses).find(([suffix])=>url.endsWith(suffix));
  if(!handler)throw Error('unexpected fetch '+url);const reply=handler[1]();return {ok:reply.ok,json:async()=>reply.body??{}};};
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
 assert.match($('viewer-status').textContent,/Downloading saved captures/);
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
test('an invalid session link never contacts the manager',async()=>{
 const {$,fetched}=harness(live,'#nope');
 await settle();assert.equal(fetched.length,0);assert.match($('viewer-status').textContent,/Invalid session link/);
 assert.equal($('capture-download').hidden,false);assert.equal($('capture-end').disabled,false);
});
