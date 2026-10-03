const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/terminal.js'),'utf8');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
function harness({hash='#lab=l1&node=r1&label=Demo',protocol='http:',reply=()=>({ok:true,body:{ticket:'T1',endpoint:'admin@172.20.20.2'}}),deferred=false}={}){
 const elements=new Map(),sockets=[],fetched=[],written=[],handlers={};let term=null,pending=null;
 function $(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,href:'',title:'',removeAttribute(name){this[name]='';}});return elements.get(id);}
 const document={getElementById:$,title:''};
 class Terminal{constructor(options){term=this;this.options=options;this.cols=100;this.rows=30;this.focused=0;this.resets=0;}loadAddon(){}open(){}onData(fn){this.dataHandler=fn;}write(bytes){written.push(bytes);}reset(){this.resets++;}focus(){this.focused++;}}
 class WebSocket{constructor(url){this.url=url;this.readyState=0;this.sent=[];this.closed=0;sockets.push(this);}send(data){this.sent.push(data);}close(){this.closed++;this.readyState=3;}}
 WebSocket.OPEN=1;
 const fetch=(url,options={})=>{fetched.push({url,options});const answer=reply(url,options);const result={ok:answer.ok,json:async()=>answer.body??{}};
  if(!deferred)return Promise.resolve(result);return new Promise(resolve=>{pending=()=>resolve(result);});};
 const c=vm.createContext({document,fetch,Terminal,WebSocket,URLSearchParams,JSON,Uint8Array,ArrayBuffer,Error,String,Math,encodeURIComponent,
  FitAddon:{FitAddon:class{fit(){this.fits=(this.fits||0)+1;}}},ResizeObserver:class{observe(){}},
  location:{hash,protocol,host:'manager:8080'},window:{addEventListener(name,fn){handlers[name]=fn;}}});
 vm.runInContext(source,c);
 return {c,$,sockets,fetched,written,handlers,document,term:()=>term,release:()=>pending()};
}
test('script parses and connects with a single-use ticket over a same-origin WebSocket',async()=>{
 const {$,sockets,fetched,document,term}=harness();
 assert.equal(document.title,'r1 · Demo · Containerlab Node Manager');assert.equal($('title').textContent,'r1 · Demo');
 assert.equal($('back').href,'/#lab=l1&device=r1');assert.equal($('back').hidden,false);
 assert.match($('notice-text').textContent,/credentials saved for r1/);
 await settle();
 assert.equal(fetched.length,1);assert.equal(fetched[0].url,'/api/labs/l1/terminal-ticket');
 assert.equal(fetched[0].options.method,'POST');assert.deepEqual(JSON.parse(fetched[0].options.body),{name:'r1'});
 assert.equal(sockets.length,1);assert.equal(sockets[0].url,'ws://manager:8080/api/terminal');assert.equal(sockets[0].binaryType,'arraybuffer');
 sockets[0].onopen();assert.deepEqual(sockets[0].sent.map(JSON.parse),[{ticket:'T1'}]);
 assert.equal(term().resets,1);assert.equal(term().focused,1);assert.equal($('endpoint').textContent,'admin@172.20.20.2');
 assert.equal($('connect').disabled,true);assert.match($('connect').title,/click Disconnect first/);
});
test('https pages use wss and the lab name is URL-encoded',async()=>{
 const {sockets,fetched}=harness({hash:'#lab=a%20b%2Fc&node=r1',protocol:'https:'});
 await settle();assert.equal(fetched[0].url,'/api/labs/a%20b%2Fc/terminal-ticket');assert.equal(sockets[0].url,'wss://manager:8080/api/terminal');
});
test('without a lab or device nothing is requested',async()=>{
 const {$,fetched,sockets}=harness({hash:'#'});
 await settle();assert.equal(fetched.length,0);assert.equal(sockets.length,0);
 assert.equal($('status').textContent,'Open this CLI from a device in the lab.');assert.equal($('back').hidden,true);assert.equal($('title').textContent,'Unknown device · Lab');
});
test('manager messages become student sentences and the exact text stays in the title',async()=>{
 const {$,sockets}=harness();
 await settle();sockets[0].onopen();
 const send=message=>sockets[0].onmessage({data:JSON.stringify({message})});
 send('Session timeout after 900 seconds');assert.match($('status').textContent,/Closed after 15 minutes without activity/);assert.equal($('status').title,'Session timeout after 900 seconds');
 send('Assign SSH credentials first');assert.match($('status').textContent,/needs login credentials/);
 send('Too many pending tickets');assert.match($('status').textContent,/limit 32/);
 send('Node not found');assert.match($('status').textContent,/no longer in the manager/);
 send('Connected');assert.equal($('status').textContent,'Connected');assert.equal($('status').title,'');
 send('Something unmapped');assert.equal($('status').textContent,'Something unmapped');assert.equal($('status').title,'');
});
test('typing and resizing are sent as JSON frames and the size is clamped',async()=>{
 const {c,sockets,term}=harness();
 await settle();const ws=sockets[0];ws.readyState=1;ws.onopen();ws.sent.length=0;
 term().dataHandler('ls\r');assert.deepEqual(JSON.parse(ws.sent[0]),{type:'input',data:'ls\r'});
 ws.onmessage({data:JSON.stringify({message:'Connected'})});
 assert.deepEqual(JSON.parse(ws.sent[1]),{type:'resize',cols:100,rows:30});
 term().cols=5;term().rows=900;vm.runInContext('resize()',c);
 assert.deepEqual(JSON.parse(ws.sent[2]),{type:'resize',cols:20,rows:150});
 ws.readyState=3;ws.sent.length=0;term().dataHandler('x');assert.equal(ws.sent.length,0);
});
test('binary output is written to the terminal',async()=>{
 const {sockets,written}=harness();
 await settle();sockets[0].onopen();
 sockets[0].onmessage({data:new Uint8Array([104,105]).buffer});
 assert.equal(written.length,1);assert.deepEqual([...written[0]],[104,105]);
});
test('a refused ticket shows the manager detail and allows another attempt',async()=>{
 const {$,sockets}=harness({reply:()=>({ok:false,body:{detail:'Assign SSH credentials to r1.'}})});
 await settle();assert.equal(sockets.length,0);assert.match($('status').textContent,/needs login credentials/);assert.equal($('connect').disabled,false);
 const second=harness({reply:()=>({ok:false,body:{detail:[{msg:'x'}]}})});
 await settle();assert.equal(second.$('status').textContent,'Could not connect to r1.');assert.equal(second.$('status').title,'Connection failed');
});
test('closing keeps the reason after Disconnected and ignores a socket from an older attempt',async()=>{
 const {$,sockets}=harness();
 await settle();const first=sockets[0];first.onopen();
 first.onmessage({data:JSON.stringify({message:'Session ended by the device'})});
 first.onclose();assert.match($('status').textContent,/^Disconnected — The session ended/);assert.equal($('connect').disabled,false);
 $('connect').onclick();await settle();assert.equal(sockets.length,2);
 const shown=$('status').textContent;
 first.onmessage({data:JSON.stringify({message:'Connection failed'})});first.onerror();first.onclose();
 assert.equal($('status').textContent,shown);assert.equal($('connect').disabled,true);
 sockets[1].onclose();assert.equal($('status').textContent,'Disconnected');assert.equal($('connect').disabled,false);
});
test('Disconnect during the ticket request prevents the late WebSocket',async()=>{
 const h=harness({deferred:true});
 await settle();assert.equal(h.fetched.length,1);assert.equal(h.$('status').textContent.startsWith('Connecting'),true);
 h.$('disconnect').onclick();assert.equal(h.$('status').textContent,'Disconnected');
 h.release();await settle();assert.equal(h.sockets.length,0);assert.equal(h.$('status').textContent,'Disconnected');assert.equal(h.$('connect').disabled,false);
});
test('leaving the page closes the socket',async()=>{
 const {sockets,handlers}=harness();
 await settle();sockets[0].onopen();assert.equal(typeof handlers.beforeunload,'function');
 handlers.beforeunload();assert.equal(sockets[0].closed,1);
});
