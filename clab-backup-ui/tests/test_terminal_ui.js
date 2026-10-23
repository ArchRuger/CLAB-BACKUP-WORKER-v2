const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/terminal.js'),'utf8'),clipboardSource=fs.readFileSync(path.join(__dirname,'../app/static/clipboard.js'),'utf8');
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
// A buffer of rows [text, isWrapped] the way xterm's IBuffer shows them.
function fakeBuffer(rows,viewportY=0,cursorY=Math.max(0,rows.length-1)){return {length:rows.length,viewportY,baseY:0,cursorY,getLine:i=>rows[i]?{isWrapped:!!rows[i][1],translateToString:()=>rows[i][0]}:undefined};}
function harness({hash='#lab=l1&node=r1&label=Demo',protocol='http:',reply=()=>({ok:true,body:{ticket:'T1',endpoint:'admin@172.20.20.2'}}),deferred=false,store=undefined,throwStorage=false,clipboardWrites,fallback=false,blurOnDisable=false}={}){
 const elements=new Map(),sockets=[],fetched=[],written=[],handlers={},downloads=[],copied=[],timers=[],fitted={count:0};let term=null,pending=null;
 function $(id){if(!elements.has(id)){const attrs={},listeners={};elements.set(id,{id,textContent:'',hidden:false,href:'',title:'',removeAttribute(name){this[name]='';},attrs,listeners,
   setAttribute(n,v){attrs[n]=String(v);},getAttribute(n){return n in attrs?attrs[n]:null;},addEventListener(type,fn){listeners[type]=fn;},
   focus(){document.activeElement=this;},
   set disabled(v){this._disabled=!!v;if(v&&blurOnDisable&&document.activeElement===this)document.activeElement=document.body;},get disabled(){return !!this._disabled;},press(init){const event={type:'keydown',prevented:false,preventDefault(){this.prevented=true;},...init};listeners.keydown?.(event);return event;}});}return elements.get(id);}
 // body, textarea and execCommand are enough for the copy fallback (no navigator.clipboard) to run as in a browser on plain http.
 const body={tag:'body',appendChild(n){n.parentNode=this;},removeChild(n){n.parentNode=null;if(document.activeElement===n)document.activeElement=body;}};
 const document={getElementById:$,title:'',activeElement:null,body,execCommand:()=>true,
  createElement:tag=>tag==='textarea'?{tag,value:'',attrs:{},parentNode:null,setAttribute(){},focus(){document.activeElement=this;},select(){this.selectionStart=0;this.selectionEnd=this.value.length;}}:{click(){downloads.push({href:this.href,download:this.download});}}};
 document.activeElement=body;
 class Terminal{constructor(options){term=this;this.options=options;this.cols=100;this.rows=30;this.focused=0;this.resets=0;this.selection='';this.cleared=0;this.buffer={active:fakeBuffer([]),normal:fakeBuffer([])};}loadAddon(){}open(){}onData(fn){this.dataHandler=fn;}write(bytes){written.push(bytes);}reset(){this.resets++;}focus(){this.focused++;}
  getSelection(){return this.selection;}clear(){this.cleared++;}attachCustomKeyEventHandler(fn){this.keyHandler=fn;}}
 class WebSocket{constructor(url){this.url=url;this.readyState=0;this.sent=[];this.closed=0;sockets.push(this);}send(data){this.sent.push(data);}close(){this.closed++;this.readyState=3;}}
 WebSocket.OPEN=1;
 const storage=store?{getItem:k=>(k in store?store[k]:null),setItem:(k,v)=>{if(throwStorage)throw new Error('blocked');store[k]=String(v);}}:undefined;
 const navigator=fallback?{}:{clipboard:{writeText:async text=>{copied.push(text);}}};
 const fetch=(url,options={})=>{fetched.push({url,options});const answer=reply(url,options);const result={ok:answer.ok,json:async()=>answer.body??{}};
  if(!deferred)return Promise.resolve(result);return new Promise(resolve=>{pending=()=>resolve(result);});};
 const c=vm.createContext({document,fetch,Terminal,navigator,Blob:class{constructor(parts,options){this.parts=parts;this.type=options.type;}},URL:{createObjectURL:b=>'blob:'+b.parts.join(''),revokeObjectURL(){}},Date,setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},WebSocket,URLSearchParams,JSON,Uint8Array,ArrayBuffer,Error,String,Math,encodeURIComponent,
  FitAddon:{FitAddon:class{fit(){fitted.count++;}}},ResizeObserver:class{observe(){}},
  location:{hash,protocol,host:'manager:8080'},window:{addEventListener(name,fn){handlers[name]=fn;}}});
 if(storage)c.localStorage=storage;
 vm.runInContext(clipboardSource,c);vm.runInContext(source,c);
 return {c,$,sockets,fetched,written,handlers,document,downloads,copied,timers,fitted,term:()=>term,release:()=>pending()};
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

// ---- terminal tools (C02 section 1) ----
const key=(init)=>({type:'keydown',altKey:false,ctrlKey:false,metaKey:false,shiftKey:false,prevented:false,preventDefault(){this.prevented=true;},...init});
test('text size is clamped to 11..18 px, the bounds disable their button and focus moves to the sibling',()=>{
 const h=harness({store:{}}),{$,term}=h;
 assert.equal(term().options.fontSize,14);
 for(let i=0;i<10;i++)$('font-up').onclick({detail:0});
 assert.equal(term().options.fontSize,18);assert.equal($('font-up').disabled,true);assert.equal($('font-down').disabled,false);assert.equal($('tools-status').textContent,'Text size 18 px');
 for(let i=0;i<10;i++)$('font-down').onclick({detail:0});
 assert.equal(term().options.fontSize,11);assert.equal($('font-down').disabled,true);assert.equal($('font-up').disabled,false);
 $('font-up').focus();for(let i=0;i<7;i++)$('font-up').onclick({detail:0});
 assert.equal($('font-up').disabled,true);assert.equal(h.document.activeElement,$('font-down'),'the disabled button gives up focus');
 assert.equal($('font-down').getAttribute('tabindex'),'0');assert.equal($('font-up').getAttribute('tabindex'),'-1');
 $('font-reset').onclick({detail:0});assert.equal(term().options.fontSize,14);assert.equal($('font-up').disabled,false);assert.equal($('font-down').disabled,false);
});
test('a size change refits the terminal and the remembered size is read back; blocked storage is tolerated',()=>{
 const store={},a=harness({store});const before=a.fitted.count;a.$('font-up').onclick({detail:0});
 assert.equal(store['clab.terminal.fontSize'],'15');assert.equal(a.fitted.count,before+1,'a size change refits once');
 assert.equal(harness({store}).term().options.fontSize,15);
 assert.equal(harness({store:{'clab.terminal.fontSize':'99'}}).term().options.fontSize,18);
 assert.equal(harness({store:{'clab.terminal.fontSize':'junk'}}).term().options.fontSize,14);
 const blocked=harness({store:{},throwStorage:true});blocked.$('font-up').onclick({detail:0});assert.equal(blocked.term().options.fontSize,15);
 assert.equal(harness().term().options.fontSize,14,'no storage at all');
});
test('Alt+ArrowUp changes the size once and is swallowed on keydown, keypress and keyup; other keys pass',()=>{
 const {term}=harness({store:{}}),t=term();
 const chord={altKey:true,key:'ArrowUp'};
 const down=key({...chord});assert.equal(t.keyHandler(down),false);assert.equal(t.options.fontSize,15);assert.equal(down.prevented,true);
 assert.equal(t.keyHandler(key({...chord,type:'keypress'})),false);assert.equal(t.keyHandler(key({...chord,type:'keyup'})),false);assert.equal(t.options.fontSize,15);
 assert.equal(t.keyHandler(key({altKey:true,key:'ArrowDown'})),false);assert.equal(t.options.fontSize,14);
 t.keyHandler(key({altKey:true,key:'ArrowUp'}));t.keyHandler(key({altKey:true,key:'0',code:'Digit0'}));assert.equal(t.options.fontSize,14);
 for(const other of [{key:'a'},{key:'c',ctrlKey:true},{key:'ArrowUp'},{key:'ArrowUp',altKey:true,shiftKey:true},{key:'Insert'},{key:'C',ctrlKey:true,shiftKey:true}])
  for(const type of ['keydown','keypress','keyup'])assert.equal(t.keyHandler(key({...other,type})),true,JSON.stringify(other)+type);
});
test('Ctrl+Insert copies the selection once, without preventDefault, and is swallowed on every event type',async()=>{
 const h=harness({store:{}}),t=h.term();t.selection='show version';
 const down=key({ctrlKey:true,key:'Insert'});assert.equal(t.keyHandler(down),false);assert.equal(down.prevented,false);
 assert.equal(t.keyHandler(key({ctrlKey:true,key:'Insert',type:'keypress'})),false);assert.equal(t.keyHandler(key({ctrlKey:true,key:'Insert',type:'keyup'})),false);
 await settle();assert.deepEqual(h.copied,['show version']);assert.equal(h.$('tools-status').textContent,'Copied');
});
test('Copy selection with nothing selected says so and copies nothing; Copy screen and Clear',async()=>{
 const h=harness({store:{}}),t=h.term();
 h.$('copy-selection').onclick({detail:0});await settle();assert.equal(h.$('tools-status').textContent,'Nothing is selected');assert.deepEqual(h.copied,[]);
 t.buffer.active=fakeBuffer([['R1# show ver  '],['Arista'],['']],0);t.rows=3;
 h.$('copy-screen').onclick({detail:0});await settle();assert.deepEqual(h.copied,['R1# show ver\nArista']);
 h.$('clear').onclick({detail:0});assert.equal(t.cleared,1);assert.equal(h.$('tools-status').textContent,'Screen cleared. The device was not told; Save session still includes the earlier lines.');
 assert.equal(h.sockets.length<=1,true);
});
test('a failed copy reports the Ctrl+Insert sentence and never says Copied',async()=>{
 const h=harness({store:{}}),t=h.term();t.selection='x';
 h.c.navigator={};h.c.document.createElement=()=>{throw new Error('no dom');};
 h.$('copy-selection').onclick({detail:0});await settle();
 assert.equal(h.$('tools-status').textContent,'Could not copy. Select the text and press Ctrl+Insert.');
});
test('Alt+T focuses the toolbar current button',()=>{
 const h=harness({store:{}}),t=h.term();
 const e=key({altKey:true,key:'t',code:'KeyT'});assert.equal(t.keyHandler(e),false);assert.equal(e.prevented,true);assert.equal(h.document.activeElement,h.$('font-down'));
 assert.equal(t.keyHandler(key({altKey:true,key:'t',code:'KeyT',type:'keyup'})),false);
 h.$('copy-screen').focus();h.$('copy-screen').listeners.focus();h.document.activeElement=null;
 t.keyHandler(key({altKey:true,key:'T',code:'KeyT'}));assert.equal(h.document.activeElement,h.$('copy-screen'));
});
test('the toolbar is a roving tabindex: one stop, ArrowLeft and ArrowRight move, Home and End jump',()=>{
 const h=harness({store:{}});const stops=()=>['font-down','font-up','font-reset','copy-selection','copy-screen','clear','export-screen','export-session'].filter(id=>h.$(id).getAttribute('tabindex')==='0');
 h.$('font-down').focus();h.$('font-down').listeners.focus?.();
 const bar=h.$('terminal-tools');
 bar.press({key:'ArrowRight'});assert.equal(h.document.activeElement,h.$('font-up'));assert.deepEqual(stops(),['font-up']);
 bar.press({key:'ArrowLeft'});bar.press({key:'ArrowLeft'});assert.equal(h.document.activeElement,h.$('export-session'),'wraps');assert.deepEqual(stops(),['export-session']);
 bar.press({key:'Home'});assert.equal(h.document.activeElement,h.$('font-down'));bar.press({key:'End'});assert.equal(h.document.activeElement,h.$('export-session'));
 const tab=bar.press({key:'Tab'});assert.equal(tab.prevented,false,'Tab leaves the toolbar');
});
test('a pointer activation hands focus back to the terminal; Enter or Space on the button does not',()=>{
 const h=harness({store:{}}),t=h.term(),before=t.focused;
 h.$('font-up').onclick({detail:0});assert.equal(t.focused,before);
 h.$('font-up').onclick({detail:1});assert.equal(t.focused,before+1);
 h.$('clear').onclick({detail:0});assert.equal(t.focused,before+1);h.$('clear').onclick({detail:2});assert.equal(t.focused,before+2);
});
test('rowsText joins wrapped rows without a newline, trims only at the end of a logical line and drops trailing blanks',()=>{
 const {c}=harness();
 const text=rows=>{c.__rows=fakeBuffer(rows);return vm.runInContext('rowsText(__rows,0,__rows.length-1)',c);};
 assert.equal(text([['interface Ethernet1 descri'],['ption uplink   ',true],['!'],['  keep   indent  '],['',false],['x'],['',false],['']]),'interface Ethernet1 description uplink\n!\n  keep   indent\n\nx');
 assert.equal(text([['abc '],['def',true],['ghi',true]]),'abc defghi','a space at the wrap point stays');
 assert.equal(text([[''],['']]),'');
 assert.equal(text([['tail',true],['next']]),'tail\nnext','a screen that starts on a wrapped row still starts a line');
});
test('screenText reads the viewport of the active buffer and sessionText the normal buffer, also while the alternate screen is active',()=>{
 const {c,term}=harness(),t=term();
 t.rows=2;t.buffer.normal=fakeBuffer([['one'],['two'],['three'],['four']]);t.buffer.active=fakeBuffer([['alt-a'],['alt-b'],['alt-c']],1);
 assert.equal(vm.runInContext('screenText()',c),'alt-b\nalt-c');assert.equal(vm.runInContext('sessionText()',c),'one\ntwo\nthree\nfour');
});
test('exportName keeps only safe characters and falls back to lab and device',()=>{
 const {c}=harness(),d=new Date(Date.UTC(2026,9,23,10,11,12,345)),name=(a,b)=>{c.__a=a;c.__b=b;c.__d=d;return vm.runInContext('exportName(__a,__b,__d)',c);};
 assert.equal(name('Demo Lab','r1'),'Demo-Lab-r1-20261023T101112Z.txt');
 c.__d=d;assert.equal(vm.runInContext('exportName("Demo Lab","r1",__d,"screen")',c),'Demo-Lab-r1-20261023T101112Z-screen.txt');assert.equal(vm.runInContext('exportName("Demo Lab","r1",__d,"session")',c),'Demo-Lab-r1-20261023T101112Z-session.txt');
 assert.equal(name('../../etc','a/b\\c:d'),'etc-a-b-c-d-20261023T101112Z.txt');
 assert.equal(name('','…'),'lab-device-20261023T101112Z.txt');assert.equal(name('.hidden','r_1.2-x'),'hidden-r_1.2-x-20261023T101112Z.txt');
});
test('Save as text downloads in the browser only: nothing goes over fetch or the socket, and the 3,000 line limit is named',async()=>{
 const h=harness({store:{}}),t=h.term();await settle();h.sockets[0].readyState=1;h.sockets[0].onopen();
 const fetched=h.fetched.length,sent=h.sockets[0].sent.length;
 t.rows=2;t.buffer.active=fakeBuffer([['a'],['b']]);t.buffer.normal=fakeBuffer([['a'],['b']]);
 h.$('export-screen').onclick({detail:0});
 assert.equal(h.downloads.length,1);assert.match(h.downloads[0].download,/^Demo-r1-\d{8}T\d{6}Z-screen\.txt$/);assert.equal(h.downloads[0].href,'blob:a\nb\n');
 assert.equal(h.$('tools-status').textContent,'Saved on this computer only. The manager keeps no copy of this session.');
 t.buffer.normal=fakeBuffer(Array.from({length:3000},(_,i)=>['line '+i]));
 h.$('export-session').onclick({detail:0});assert.equal(h.downloads.length,2);assert.match(h.downloads[1].download,/-session\.txt$/,'two exports in one second never share a name');assert.match(h.$('tools-status').textContent,/the last 3,000 lines/);
 t.buffer.normal=fakeBuffer([]);t.buffer.active=fakeBuffer([]);h.$('export-session').onclick({detail:0});assert.equal(h.downloads[2].href,'blob:\n','an empty buffer exports one empty line');
 assert.equal(h.fetched.length,fetched);assert.equal(h.sockets[0].sent.length,sent);
});
test('a reconnect clears the screen and says so, the first connection does not; the size persists',async()=>{
 const h=harness({store:{}});await settle();h.$('font-up').onclick({detail:0});
 h.sockets[0].onopen();assert.notEqual(h.$('tools-status').textContent,'Reconnected; the previous screen was cleared');
 h.$('connect').onclick();await settle();h.sockets[1].onopen();
 assert.equal(h.$('tools-status').textContent,'Reconnected; the previous screen was cleared');assert.equal(h.term().options.fontSize,15);
});

// ---- review fixes (C02 section 8) ----
test('Ctrl+Insert without navigator.clipboard copies through the textarea and leaves focus in the terminal',async()=>{
 const h=harness({store:{},fallback:true}),t=h.term(),helper={id:'xterm-helper',focus(){h.document.activeElement=this;}};
 t.selection='show version';helper.focus();
 assert.equal(t.keyHandler(key({ctrlKey:true,key:'Insert'})),false);await settle();
 assert.equal(h.$('tools-status').textContent,'Copied');assert.equal(h.document.activeElement,helper,'focus is back in the terminal, not on BODY');
 // the same for the Copy screen button: focus returns to the button
 t.buffer.active=fakeBuffer([['a']],0);t.rows=1;h.$('copy-screen').focus();h.$('copy-screen').onclick({detail:0});await settle();
 assert.equal(h.document.activeElement,h.$('copy-screen'));
});
test('Chromium blurs a button the moment it is disabled: the focus is read first and handed to the sibling',()=>{
 const h=harness({store:{},blurOnDisable:true}),{$,term}=h;
 for(let i=0;i<3;i++)$('font-down').onclick({detail:0});   // 11
 $('font-down').focus();$('font-down').onclick({detail:0});
 assert.equal(term().options.fontSize,11);assert.equal($('font-down').disabled,true);assert.equal(h.document.activeElement,$('font-up'),'not BODY');assert.equal($('font-up').getAttribute('tabindex'),'0');
 for(let i=0;i<7;i++)$('font-up').onclick({detail:0});   // 18
 $('font-up').focus();$('font-up').onclick({detail:0});
 assert.equal($('font-up').disabled,true);assert.equal(h.document.activeElement,$('font-down'));
 // Alt+ArrowUp from the terminal (nothing focused in the toolbar) takes no focus
 const g=harness({store:{'clab.terminal.fontSize':'17'},blurOnDisable:true}),before=g.document.activeElement;g.term().keyHandler(key({altKey:true,key:'ArrowUp'}));
 assert.equal(g.$('font-up').disabled,true);assert.equal(g.document.activeElement,before);
});
test('Clear keeps the earlier lines in Save session and says so; a reconnect starts the session over',async()=>{
 const h=harness({store:{}}),t=h.term();await settle();h.sockets[0].readyState=1;h.sockets[0].onopen();
 t.rows=2;t.buffer.normal=fakeBuffer([['one'],['two'],['R1# ']]);t.buffer.active=t.buffer.normal;
 h.$('clear').onclick({detail:0});assert.equal(t.cleared,1);
 t.buffer.normal=fakeBuffer([['R1# '],['three']]);t.buffer.active=t.buffer.normal;   // xterm dropped the scrollback
 h.$('export-session').onclick({detail:0});assert.equal(h.downloads.at(-1).href,'blob:one\ntwo\nR1#\nthree\n','the prompt row xterm keeps is not repeated');
 h.$('export-screen').onclick({detail:0});assert.doesNotMatch(h.downloads.at(-1).href,/one/,'Save screen is the screen only');
 h.$('connect').onclick();await settle();h.sockets[1].onopen();
 t.buffer.normal=fakeBuffer([['fresh']]);h.$('export-session').onclick({detail:0});assert.equal(h.downloads.at(-1).href,'blob:fresh\n');
});
test('after Clear, Save session names the 3,000 line limit when earlier lines were already cut, and repeated Clears stay capped',async()=>{
 const h=harness({store:{}}),t=h.term();await settle();h.sockets[0].readyState=1;h.sockets[0].onopen();
 const full=Array.from({length:3000},(_,i)=>['line '+i]);
 t.buffer.normal=fakeBuffer(full);t.buffer.active=t.buffer.normal;h.$('clear').onclick({detail:0});
 t.buffer.normal=fakeBuffer([['line 2999'],['next']]);t.buffer.active=t.buffer.normal;
 h.$('export-session').onclick({detail:0});assert.match(h.$('tools-status').textContent,/The file holds the last 3,000 lines\./,'the limit is named although the live buffer is short');
 const lines=h.downloads.at(-1).href.slice(5).split('\n');assert.equal(lines.length,3001,'3,000 lines plus the closing newline');assert.equal(lines.at(-2),'next');
 h.$('clear').onclick({detail:0});h.$('clear').onclick({detail:0});t.buffer.normal=fakeBuffer([['x']]);
 h.$('export-session').onclick({detail:0});assert.ok(h.downloads.at(-1).href.slice(5).split('\n').length<=3001,'repeated Clears never grow the export past the limit');
 // without a Clear, a short session carries no note
 const g=harness({store:{}}),u=g.term();await settle();u.buffer.normal=fakeBuffer([['a'],['R1#']]);g.$('clear').onclick({detail:0});u.buffer.normal=fakeBuffer([['R1#']]);
 g.$('export-session').onclick({detail:0});assert.equal(g.downloads.at(-1).href,'blob:a\nR1#\n');assert.doesNotMatch(g.$('tools-status').textContent,/3,000/);
 // a cursor row that differs from the last snapshot row is kept (nothing is dropped)
 const k=harness({store:{}}),w=k.term();await settle();w.buffer.normal=fakeBuffer([['a'],['b'],['']],0,0);k.$('clear').onclick({detail:0});w.buffer.normal=fakeBuffer([['a']]);
 k.$('export-session').onclick({detail:0});assert.equal(k.downloads.at(-1).href,'blob:a\nb\na\n');
});
test('the tools status keeps its own two-line row: the sentence is also the title, and terminal.css reserves the box with or without text',()=>{
 const h=harness({store:{}});h.$('clear').onclick({detail:0});assert.equal(h.$('tools-status').title,h.$('tools-status').textContent);
 const css=fs.readFileSync(path.join(__dirname,'../app/static/terminal.css'),'utf8'),rule=css.match(/#tools-status\s*\{([^}]*)\}/)[1];
 assert.match(rule,/flex:\s*1 1 100%/,'a row of its own');assert.match(rule,/(?:^|[;\s])height:\s*36px/,'a fixed height, not a min-height that text can outgrow');
 assert.match(rule,/line-height:\s*18px/,'two lines fill the 36px');assert.match(rule,/white-space:\s*normal/);assert.match(rule,/overflow:\s*hidden/);assert.match(rule,/line-clamp:\s*2/);assert.doesNotMatch(rule,/nowrap|ellipsis/,'the warning clause is not cut to one line');
 assert.match(css.match(/\.terminal-tools\s*\{([^}]*)\}/)[1],/min-height:\s*\d+px/);
});
test('the notice names the Esc route to a shell\'s own Alt shortcuts',()=>{
 const h=harness();assert.match(h.$('notice-text').textContent,/; on a Linux node type Esc then the key for the shell's own Alt shortcuts\.$/);
 assert.match(fs.readFileSync(path.join(__dirname,'../app/static/terminal.html'),'utf8'),/on a Linux node type Esc then the key for the shell's own Alt shortcuts\./);
});
test('terminal.html carries every id the script drives, one tab stop, a toolbar role and clipboard.js before terminal.js',()=>{
 const page=fs.readFileSync(path.join(__dirname,'../app/static/terminal.html'),'utf8'),h=harness();
 const ids=new Set([...page.matchAll(/\sid="([^"]+)"/g)].map(m=>m[1]));
 const toolIds=vm.runInContext('TOOL_IDS',h.c);assert.equal(toolIds.length,8);
 for(const id of [...toolIds,'tools-status','terminal-tools','status','connect','disconnect','title','endpoint','back','notice-text','terminal'])assert.ok(ids.has(id),id+' is missing from terminal.html');
 const tools=page.match(/<div id="terminal-tools"[^>]*>/)[0];assert.match(tools,/role="toolbar"/);assert.match(tools,/aria-label="[^"]+"/);
 const buttons=toolIds.map(id=>page.match(new RegExp('<button[^>]*id="'+id+'"[^>]*>'))[0]);
 assert.equal(buttons.filter(b=>/tabindex="0"/.test(b)).length,1);assert.equal(buttons.filter(b=>/tabindex="-1"/.test(b)).length,7);assert.match(buttons[0],/tabindex="0"/,'the first button is the one tab stop');
 const order=[...page.matchAll(/<script src="\/static\/([^"?]+\.js)\?v=[^"]*"/g)].map(m=>m[1]);
 assert.ok(order.indexOf('clipboard.js')>=0&&order.indexOf('clipboard.js')<order.indexOf('terminal.js'));
});
