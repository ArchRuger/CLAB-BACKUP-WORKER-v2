// device-diagnostics.js: the device drawer's Interfaces and Logs (docs/parity-campaign/C03-DESIGN.md section 4.1 and 5).
// The pure functions run directly; the poll loop, the reset keys and the scroll rule run against a small fake DOM with fake
// timers, a fake api() and a fake clock. index.html is read as text for the markup contract (labels, roles, tabindex).
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const dir=path.join(__dirname,'../app/static');
const source=fs.readFileSync(path.join(dir,'device-diagnostics.js'),'utf8');
const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');
const css=fs.readFileSync(path.join(dir,'style.css'),'utf8');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const HEX='a'.repeat(64);
function fakeElement(id){
 return {id,hidden:false,open:false,value:'',textContent:'',innerHTML:'',scrollTop:0,scrollHeight:0,clientHeight:0,attrs:{},listeners:{},appended:[],removable:0,removed:0,
  setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return k in this.attrs?this.attrs[k]:null;},hasAttribute(k){return k in this.attrs;},
  addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn);},
  insertAdjacentHTML(position,markup){this.appended.push(markup);this.innerHTML+=markup;},
  get firstElementChild(){return this.removable>0?{remove:()=>{this.removable--;this.removed++;}}:null;},
  contains(){return false;},querySelector(){return null;},
  fire(type,event={}){for(const fn of this.listeners[type]||[])fn({target:this,...event});}};
}
function harness({caps={diagnostics:true},visible=true}={}){
 const els=new Map(),requests=[],timers=[],handlers=[],clock={t:1000000};
 const get=id=>{if(!els.has(id))els.set(id,fakeElement(id));return els.get(id);};
 const downloads=[];
 const state={labs:[{id:'L1',name:'lab one',nodes:[{name:'r1',short_name:'router-1'},{name:'r2'}]},{id:'L2',name:'lab two',nodes:[{name:'r1'}]}],operations:[]};
 const context=vm.createContext({$:get,esc,state,activeId:'L1',detailName:'r1',opCaps:caps,URLSearchParams,Blob,setTimeout:(fn,ms)=>{timers.push({fn,ms,live:true});return timers.length;},clearTimeout:id=>{if(timers[id-1])timers[id-1].live=false;},
  Date:class extends Date{static now(){return clock.t;}},
  current:()=>state.labs.find(l=>l.id===context.activeId),
  pageVisible:()=>context.visible,visible,
  captureActionAttrs:()=>'',captureStatusLine:()=>'',openCapture(node,hint,ends,options){context.opened=[node,hint];context.openedFull=[node,hint,ends,options];},
  URL:{createObjectURL:()=>'blob:x',revokeObjectURL(){}},
  document:{activeElement:null,body:{append(){}},createElement:()=>({click(){downloads.push(this.download);},remove(){}})},
  api:async url=>{
   requests.push(url);
   const handler=handlers.find(h=>url.startsWith(h.prefix));
   if(!handler)throw Object.assign(new Error('no handler for '+url),{status:500});
   const body=await handler.fn(url,requests.length);
   return {json:async()=>body};
  }});
 vm.runInContext(source,context,{filename:'device-diagnostics.js'});
 const on=(prefix,fn)=>{handlers.unshift({prefix,fn});};
 const live=()=>timers.filter(t=>t.live);
 const run=async()=>{const t=live()[0];assert.ok(t,'a timer is waiting');t.live=false;t.fn();await tick();await tick();};
 const get2=name=>vm.runInContext(name,context);
 return {context,els,get,requests,timers,live,run,on,clock,downloads,get2,open(name){const box=get('diag-'+name);box.open=true;box.fire('toggle');}};
}
const iface=(over={})=>({name:'eth1',alias:'',state:'up',mac:'aa:bb:cc:00:00:01',type:'veth',mtu:9500,ifindex:2,port:'ge-0/0/0',role:'data',...over});
const counters=(rx,tx)=>({rx_bytes:rx,rx_packets:1,rx_errors:0,rx_dropped:0,tx_bytes:tx,tx_packets:1,tx_errors:0,tx_dropped:0});
const answer=(over={})=>({container:'clab-lab-r1',present:true,facts:{present:true,id:HEX,pid:5,status:'running',health:'',started:'t0',ports:[]},
 interfaces:[iface({name:'eth0',port:'',role:'management'}),iface(),iface({name:'cpu',port:'',role:'internal'})],counters:{eth0:counters(1000,2000),eth1:counters(5000,6000),cpu:counters(1,1)},sampled_at:100,counters_reason:'',...over});
const logLine=(at,text)=>({at,text});
const stamp=(s,ns='000000000')=>`2026-10-23T02:03:${String(s).padStart(2,'0')}.${ns}Z`;
const logAnswer=(lines,over={})=>({container:'c',present:true,facts:{present:true,id:HEX,status:'running'},lines,truncated:false,fetched_at:1,...over});

test('diagPollNext: chained plan, 503 doubles to 30 s and a success halves back, three errors stop, 30 minutes pause',()=>{
 const h=harness(),next=(plan,answer,now=1)=>h.context.diagPollNext(plan,answer,now);
 let plan=h.context.diagPlan(0);
 let r=next(plan,{ok:true});assert.equal(r.delay,5000);assert.equal(r.stop,'');
 const delays=[];for(let i=0;i<5;i++){r=next(r.plan,{ok:false,status:503});delays.push(r.delay);}
 assert.deepEqual(delays,[10000,20000,30000,30000,30000],'a 503 doubles the wait up to 30 s');assert.equal(r.plan.errors,0,'a 503 is a back-off, not an error');
 const back=[];for(let i=0;i<4;i++){r=next(r.plan,{ok:true});back.push(r.delay);}
 assert.deepEqual(back,[15000,7500,5000,5000],'a success halves it back to 5 s');
 r=next(plan,{ok:false,status:500});assert.equal(r.delay,5000);assert.equal(r.stop,'');
 r=next(r.plan,{ok:false,status:409});assert.equal(r.stop,'');
 r=next(r.plan,{ok:false,status:0});assert.equal(r.stop,'retry','three consecutive errors stop with Retry');assert.equal(r.delay,null);
 r=next(plan,{ok:false,status:500});r=next(r.plan,{ok:true});r=next(r.plan,{ok:false,status:500});r=next(r.plan,{ok:false,status:500});assert.equal(r.stop,'','a success between errors restarts the count');
 r=next(plan,{ok:true},30*60*1000-1);assert.equal(r.stop,'');
 r=next(plan,{ok:true},30*60*1000);assert.equal(r.stop,'resume','after 30 minutes the poll pauses with Resume');assert.equal(r.delay,null);
});

test('diagRate needs the same container run, the same interface, a non-negative delta and a positive time step',()=>{
 const h=harness(),rate=(a,b,n='eth1')=>h.context.diagRate(a,b,n);
 const a=answer(),b=answer({sampled_at:102,counters:{eth1:counters(7000,10000)}});
 const r=rate(a,b);assert.equal(r.rx,1000);assert.equal(r.tx,2000);
 assert.equal(rate(null,b),null,'no earlier sample');
 assert.equal(rate(a,answer({sampled_at:102,facts:{...a.facts,id:'b'.repeat(64)},counters:b.counters})),null,'a new container (other id) is a new baseline');
 assert.equal(rate(a,answer({sampled_at:102,facts:{...a.facts,started:'t1'},counters:b.counters})),null,'a restart (other start time) is a new baseline');
 assert.equal(rate(a,answer({sampled_at:102,counters:{eth1:counters(10,10000)}})),null,'a negative delta shows no rate');
 assert.equal(rate(a,answer({sampled_at:100,counters:b.counters})),null,'no time step, no rate');
 assert.equal(rate(a,answer({sampled_at:99,counters:b.counters})),null);
 assert.equal(rate(a,b,'eth9'),null,'an interface missing from a sample');
 assert.equal(rate(a,answer({sampled_at:102,counters:{}})),null);
 assert.equal(h.context.diagRateText(12.4),'12 B/s');assert.equal(h.context.diagRateText(2500),'2.5 kB/s');assert.equal(h.context.diagRateText(3.2e6),'3.2 MB/s');
 assert.equal(h.context.diagBytes(999),'999 B');assert.equal(h.context.diagBytes(1500),'1.50 kB');assert.equal(h.context.diagBytes(NaN),'—');
});

test('the Follow cursor is the last line with a stamp; a redacted line keeps its stamp and is shown; a stampless line is kept',()=>{
 const h=harness(),c=h.context;
 const lines=[logLine(stamp(1),'a'),logLine(stamp(2),'[sensitive output omitted]'),logLine('','continuation')];
 assert.equal(c.diagCursor(lines),stamp(2),'a stampless last line never hides the cursor');
 assert.equal(c.diagCursor([logLine('','x')]),'');
 const incoming=[logLine(stamp(1),'old'),logLine(stamp(2),'old2'),logLine('','no stamp'),logLine(stamp(2,'000000001'),'new'),logLine(stamp(3),'newer')];
 assert.deepEqual(Array.from(c.diagFreshLines(incoming,stamp(2)),l=>l.text),['no stamp','new','newer'],'dropped only when its own stamp is at or before the cursor');
 assert.equal(c.diagFreshLines(incoming,'').length,5,'without a cursor nothing is dropped');
 const log=c.diagLogNew();
 c.diagApplyLogs(log,[logLine(stamp(1),'one'),logLine(stamp(2),'PASSWORD: [sensitive output omitted]')],true);
 assert.equal(log.cursor,stamp(2));
 const result=c.diagApplyLogs(log,[logLine(stamp(2),'PASSWORD: [sensitive output omitted]'),logLine(stamp(3),'three')],false);
 assert.deepEqual(Array.from(log.lines,l=>l.text),['one','PASSWORD: [sensitive output omitted]','three']);assert.equal(result.fresh.length,1);assert.equal(log.cursor,stamp(3));
 c.diagApplyLogs(log,[logLine(stamp(3),'three'),logLine('','tail piece')],false);
 assert.equal(log.cursor,stamp(3),'the cursor skips the stampless tail');
});

test('the DOM keeps 2000 lines, says what was dropped and warns when exactly 2000 lines came back',()=>{
 const c=harness().context,log=c.diagLogNew();
 const many=n=>Array.from({length:n},(_,i)=>logLine(`2026-10-23T03:00:00.${String(i).padStart(9,'0')}Z`,'l'+i));
 c.diagApplyLogs(log,many(1990),true);assert.equal(log.lines.length,1990);assert.equal(log.older,false);
 const more=Array.from({length:30},(_,i)=>logLine(`2026-10-23T03:00:01.${String(i).padStart(9,'0')}Z`,'m'+i));
 const result=c.diagApplyLogs(log,more,false);
 assert.equal(log.lines.length,2000);assert.equal(log.older,true);assert.equal(result.dropped.length,20);assert.equal(log.lines[0].text,'l20');
 assert.equal(log.missing,false);
 c.diagApplyLogs(log,many(2000).map((l,i)=>({...l,at:`2026-10-23T04:00:00.${String(i).padStart(9,'0')}Z`})),false);
 assert.equal(log.missing,true,'exactly 2000 lines back: some lines may be missing');
 const replaced=c.diagApplyLogs(log,many(2005),true);
 assert.equal(log.lines.length,2000);assert.equal(replaced.replaced,true);assert.equal(log.older,true);assert.equal(log.missing,false);
});

test('Find shows matching lines only while it is non-empty, with an "n of m lines" count; stamps show as HH:MM:SS',()=>{
 const c=harness().context,lines=[logLine(stamp(1),'Interface Up'),logLine(stamp(2),'BGP down'),logLine('','up again')];
 assert.equal(c.diagFilter(lines,'').length,3);assert.equal(c.diagFilter(lines,'   ').length,3);
 assert.deepEqual(Array.from(c.diagFilter(lines,'UP'),l=>l.text),['Interface Up','up again'],'case-insensitive substring');
 assert.equal(c.diagCount(2,3,true),'2 of 3 lines');assert.equal(c.diagCount(3,3,false),'3 lines');assert.equal(c.diagCount(1,1,false),'1 line');
 assert.equal(c.diagLineText(lines[0]),'02:03:01 Interface Up');assert.equal(c.diagLineText(lines[2]),'up again');
 assert.equal(c.diagLineFull(lines[0]),stamp(1)+' Interface Up','Export keeps the full stamp');
 assert.match(c.diagLineMarkup(lines[0]),new RegExp(`title="${stamp(1)}"`),'the full stamp is in the title');
 assert.doesNotMatch(c.diagLineMarkup(logLine('','<b>x</b>')),/<b>/,'log text is escaped');
});

test('the export file name is <lab>-<device>-logs-<UTC stamp>.txt and holds only safe characters',()=>{
 const c=harness().context;
 assert.equal(c.diagExportName('lab one','r1',new Date('2026-10-23T02:03:04.567Z')),'lab-one-r1-logs-20261023T020304Z.txt');
 assert.equal(c.diagExportName('../x/y','a b/c',new Date('2026-01-02T03:04:05Z')),'x-y-a-b-c-logs-20260102T030405Z.txt');
});

test('the 30 px rule: follow scrolls only when the reader was within 30 px of the bottom',()=>{
 const c=harness().context;
 assert.equal(c.diagNearBottom({scrollHeight:1000,scrollTop:670,clientHeight:300}),true);
 assert.equal(c.diagNearBottom({scrollHeight:1000,scrollTop:700,clientHeight:300}),true);
 assert.equal(c.diagNearBottom({scrollHeight:1000,scrollTop:669,clientHeight:300}),false);
});

test('interfaces: data first with a Capture button on the container interface name, management labelled, internal grouped',()=>{
 const c=harness().context;
 const ctx={device:'r1',rates:{eth1:{rx:1000,tx:2000}},impair:{eth1:'delay 15ms · loss 5%'},captureAttrs:'disabled title="Packet capture is not set up on this VM. See Tools › Packet capture for details."',captureReason:'Packet capture is not set up on this VM. Ask your instructor or administrator.',otherOpen:false};
 const out=c.diagInterfacesMarkup(answer(),ctx);
 assert.equal((out.match(/data-diag-capture=/g)||[]).length,1,'a Capture button on data rows only');
 assert.match(out,/data-diag-capture="eth1"/);assert.match(out,/aria-label="Capture packets on eth1"/);
 assert.match(out,/disabled title="Packet capture is not set up/,'captureActionAttrs() reaches the button');
 assert.match(out,/Packet capture is not set up on this VM\. Ask your instructor/,'the caption gives the reason');
 assert.match(out,/<strong>eth0<\/strong> · management \(the manager reaches the device through it\)/);
 assert.doesNotMatch(out,/impaired/i,'the management label does not say impaired');
 assert.match(out,/<summary data-diag-key="other-summary">Other interfaces \(1\)<\/summary>/);assert.ok(out.indexOf('eth1')<out.indexOf('eth0'),'data rows come first');assert.ok(out.indexOf('eth0')<out.indexOf('cpu'));
 assert.match(out,/ge-0\/0\/0/,'the Port column');assert.match(out,/delay 15ms · loss 5%/);
 assert.match(out,/1\.0 kB\/s/);assert.match(out,/2\.0 kB\/s/);assert.match(out,/5\.00 kB/);
 assert.equal((out.match(/class="table-wrap diag-wrap" tabindex="0"/g)||[]).length,2,'each table scrolls in a focusable, labelled region');
 assert.match(out,/<th scope="col">Name<\/th><th scope="col">Port<\/th><th scope="col">State<\/th><th scope="col">RX<\/th><th scope="col">TX<\/th>/);
 assert.doesNotMatch(out,/<details[^>]* open/,'Other interfaces stays closed until the student opens it');
 assert.match(c.diagInterfacesMarkup(answer(),{...ctx,otherOpen:true}),/<details class="diag-other" data-diag-other open>/);
 const hostile=c.diagInterfacesMarkup(answer({interfaces:[iface({name:'<img onerror=x>',port:'"><script>'})]}),{...ctx,captureAttrs:''});
 assert.doesNotMatch(hostile,/<img|<script/,'esc() on every interpolation');
});

test('interfaces: the empty states say whether the container is absent, running or stopped',()=>{
 const c=harness().context,ctx={device:'r1'};
 assert.match(c.diagInterfacesMarkup({present:false,interfaces:[]},ctx),/No container for this device yet \(deploy the lab, or wait for the deploy to create it\)\./);
 assert.match(c.diagInterfacesMarkup(answer({interfaces:[]}),ctx),/No interfaces reported\./);
 const stopped=c.diagInterfacesMarkup(answer({interfaces:[],facts:{present:true,id:HEX,pid:0,status:'exited',started:'t0'}}),ctx);
 assert.match(stopped,/The container is stopped \(exited\)\. Interfaces exist only while it runs; Logs shows its last output\./);
 assert.doesNotMatch(stopped,/No interfaces reported/);
 assert.match(c.diagInterfacesMarkup(answer({counters:{},counters_reason:'pid'}),ctx),/Traffic counters are not available/);
});

test('index.html: the sections, their labels, roles and the script order are the markup contract',()=>{
 const root=/<div id="details-diagnostics" hidden>([\s\S]*?)<\/details><\/div>/.exec(html);
 assert.ok(root,'both sections sit in one hidden container after #details-info');
 assert.ok(html.indexOf('<div id="details-info"></div><div id="details-diagnostics"')>0);
 const inside=root[1];
 const sections=inside.split('<details ').slice(1);assert.equal(sections.length,2);
 for(const section of sections)assert.equal((section.match(/role="status"/g)||[]).length,1,'one role=status per section');
 assert.match(inside,/<summary>Interfaces<\/summary>/);assert.match(inside,/<summary>Logs<\/summary>/);
 assert.match(inside,/<label for="diag-log-find">Find<\/label><input type="search" id="diag-log-find"/,'Find has a visible label');
 assert.match(inside,/<label for="diag-log-tail">Tail<\/label><select id="diag-log-tail">/);
 assert.match(inside,/id="diag-log-follow" aria-pressed="false">Follow</,'Follow is a toggle button');
 assert.match(inside,/<pre class="op-code diag-log" id="diag-log-view" tabindex="0"/,'the log region is focusable');
 assert.match(inside,/id="diag-log-export">Export</);assert.match(inside,/id="diag-log-refresh">Refresh</);
 assert.doesNotMatch(inside,/<details [^>]*\bopen\b/,'closed by default');
 const scripts=[...html.matchAll(/<script src="\/static\/([^"?]+\.js)\?v=([^"]*)" defer><\/script>/g)];
 const names=scripts.map(m=>m[1]);assert.ok(names.includes('device-diagnostics.js'));
 assert.ok(names.indexOf('device-diagnostics.js')>names.indexOf('operations.js'),'after operations.js');
 assert.ok(names.indexOf('device-diagnostics.js')>names.indexOf('shell.js')&&names.indexOf('device-diagnostics.js')>names.indexOf('app.js'));
 assert.equal(scripts.find(m=>m[1]==='device-diagnostics.js')[2],fs.readFileSync(path.join(dir,'../../VERSION'),'utf8').trim(),'carries ?v=<release>');
 assert.match(html,/<span id="clab-version" hidden><\/span>/,'the Manager menu footer has the containerlab version span');
 assert.match(html,/id="manager-images"/);
});

test('the narrow layout: the interface table never forces a sideways scroll in the drawer',()=>{
 assert.match(css,/\.table-wrap\.diag-wrap table, \.diag-table \{ min-width: 0; table-layout: auto; \}/,'beats the 730 px minimum of .table-wrap tables');
 assert.match(css,/\.diag-table th \{ white-space: normal; \}/);assert.match(css,/\.diag-table td \{ overflow-wrap: anywhere; \}/);
 assert.match(css,/\.op-code\.diag-log \{[^}]*white-space: pre-wrap; overflow-wrap: anywhere;/,'long log lines wrap instead of scrolling the drawer');
 assert.ok(css.indexOf('.table-wrap.diag-wrap table')>css.indexOf('.table-wrap table { min-width: 730px; }'),'declared after the narrow-screen rule');
 assert.doesNotMatch(source,/\.style\b|style=/,'no inline styles');
});

test('sections are gated on opCaps.diagnostics: hidden for an older helper, capabilities asked at most once a minute',async()=>{
 const h=harness({caps:{diagnostics:false}}),n={name:'r1'};
 h.context.renderDeviceDiagnostics(n);assert.equal(h.get('details-diagnostics').hidden,true,'an older helper shows neither section');
 const none=harness({caps:null});let asked=0;
 none.context.opCapabilities=async()=>{asked++;await tick();none.context.opCaps={diagnostics:true};};
 none.get('details-dialog').open=true;
 none.context.renderDeviceDiagnostics(n);none.context.renderDeviceDiagnostics(n);
 assert.equal(none.get('details-diagnostics').hidden,true,'hidden until the answer');
 await tick();
 assert.equal(asked,1,'one capabilities request, not one per 4 s render');
 assert.equal(none.get('details-diagnostics').hidden,false,'shown once the helper says it can');
 const on=harness();on.context.renderDeviceDiagnostics(n);assert.equal(on.get('details-diagnostics').hidden,false);
 assert.deepEqual(on.requests,[],'an open drawer asks the VM for nothing until a section is opened');
});

test('interfaces: opening asks once, the next request waits for the answer, rates appear from the second sample',async()=>{
 const h=harness();let n=0,release;
 h.on('/operations/netem',()=>({container:'c',present:true,impairments:[{interface:'eth1',delay:'15ms',loss:'5%'}]}));
 h.on('/operations/interfaces',()=>{n++;return n===1?answer():answer({sampled_at:102,counters:{eth0:counters(1000,2000),eth1:counters(7000,10000),cpu:counters(1,1)}});});
 h.context.renderDeviceDiagnostics({name:'r1'});
 h.open('interfaces');await tick();await tick();
 assert.equal(h.requests.filter(r=>r.startsWith('/operations/interfaces')).length,1);
 assert.match(h.requests[0],/\?lab_id=L1&node=r1$/,'the browser sends the lab id and the manager node name only');
 assert.equal(h.live().length,1,'one timer, scheduled after the answer');assert.equal(h.live()[0].ms,5000);
 assert.doesNotMatch(h.get('diag-if-body').innerHTML,/B\/s/,'no rate from one sample');
 assert.match(h.get('diag-if-body').innerHTML,/delay 15ms · loss 5%/,'the impairment line from /netem');
 assert.equal(h.get('diag-if-status').textContent,'Interfaces loaded.');
 await h.run();
 assert.match(h.get('diag-if-body').innerHTML,/1\.0 kB\/s/);assert.match(h.get('diag-if-body').innerHTML,/2\.0 kB\/s/);
 assert.equal(h.requests.filter(r=>r.startsWith('/operations/netem')).length,1,'impairments are fetched once per open, not per poll');
 assert.equal(h.live().length,1);
 assert.equal(h.get('diag-if-status').textContent,'Interfaces loaded.','a routine poll never rewrites the status element');
});

test('impairments are fetched again after an operation of this lab finishes',async()=>{
 const h=harness();
 h.on('/operations/netem',()=>({container:'c',present:true,impairments:[]}));
 h.on('/operations/interfaces',()=>answer());
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();await tick();
 h.context.state.operations.push({lab_id:'L2',finished:'2026-10-23T01:00:00Z'});await h.run();
 assert.equal(h.requests.filter(r=>r.startsWith('/operations/netem')).length,1,'another lab\'s operation changes nothing');
 h.context.state.operations.push({lab_id:'L1',finished:'2026-10-23T01:05:00Z'});await h.run();
 assert.equal(h.requests.filter(r=>r.startsWith('/operations/netem')).length,2);
});

test('a 503 backs off to 30 s and the shown data stays under "Updating paused, retrying…"; the 503 sentence never replaces it',async()=>{
 const h=harness();let mode='ok';const busy='The manager is already asking the VM for diagnostics; try again in a moment.';
 h.on('/operations/netem',()=>({present:true,impairments:[]}));
 h.on('/operations/interfaces',()=>{if(mode==='busy')throw Object.assign(new Error(busy),{status:503});return answer();});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();await tick();
 const shown=h.get('diag-if-body').innerHTML;assert.match(shown,/eth1/);
 mode='busy';const waits=[];
 for(let i=0;i<5;i++){await h.run();waits.push(h.live()[0].ms);}
 assert.deepEqual(waits,[10000,20000,30000,30000,30000]);
 assert.equal(h.get('diag-if-body').innerHTML,shown,'the last data stays');
 assert.equal(h.get('diag-if-status').textContent,'Updating paused, retrying…');
 assert.notEqual(h.get('diag-if-status').textContent,busy);
 assert.equal(h.get('diag-if-retry').hidden,true,'a 503 never stops the plan');
 mode='ok';await h.run();assert.equal(h.live()[0].ms,15000);assert.equal(h.get('diag-if-status').textContent,'Interfaces loaded.');
});

test('three errors in a row stop the poll with the sentence and Retry; Retry starts it again',async()=>{
 const h=harness();let fail=false;const sentence="This VM's manager tools need an update; ask your instructor or administrator.";
 h.on('/operations/netem',()=>({present:true,impairments:[]}));
 h.on('/operations/interfaces',()=>{if(fail)throw Object.assign(new Error(sentence),{status:409});return answer();});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();await tick();
 fail=true;
 await h.run();assert.equal(h.get('diag-if-retry').hidden,true);assert.equal(h.get('diag-if-status').textContent,'Updating paused, retrying…');
 await h.run();assert.equal(h.get('diag-if-retry').hidden,true);
 await h.run();
 assert.equal(h.get('diag-if-retry').hidden,false);assert.equal(h.get('diag-if-retry').textContent,'Retry');
 assert.equal(h.get('diag-if-status').textContent,sentence,'the manager\'s sentence verbatim');assert.equal(h.live().length,0,'no timer once stopped');
 fail=false;h.get('diag-if-retry').fire('click');await tick();await tick();
 assert.equal(h.get('diag-if-retry').hidden,true);assert.equal(h.get('diag-if-status').textContent,'Interfaces loaded.');assert.equal(h.live().length,1);
});

test('an error on first load (nothing shown yet) shows the sentence with Retry at once; a failed Refresh does the same',async()=>{
 const h=harness();const sentence='Cannot reach the VM operations helper. Check setup and SSH settings.';
 h.on('/operations/logs',()=>{throw Object.assign(new Error(sentence),{status:409});});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 assert.equal(h.get('diag-log-status').textContent,sentence);assert.equal(h.get('diag-log-retry').hidden,false);assert.equal(h.live().length,0);
});

test('after 30 minutes the poll pauses with Resume',async()=>{
 const h=harness();
 h.on('/operations/netem',()=>({present:true,impairments:[]}));h.on('/operations/interfaces',()=>answer());
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();await tick();
 h.clock.t+=29*60*1000;await h.run();assert.equal(h.get('diag-if-retry').hidden,true);
 h.clock.t+=2*60*1000;await h.run();
 assert.equal(h.get('diag-if-retry').hidden,false);assert.equal(h.get('diag-if-retry').textContent,'Resume');
 assert.equal(h.get('diag-if-status').textContent,'Interface updates paused after 30 minutes.');assert.equal(h.live().length,0);
 h.get('diag-if-retry').fire('click');await tick();await tick();assert.equal(h.get('diag-if-retry').hidden,true);assert.equal(h.live().length,1);
});

test('a hidden tab stops asking; on return one fresh fetch replaces the content',async()=>{
 const h=harness();let n=0;
 h.on('/operations/netem',()=>({present:true,impairments:[]}));
 h.on('/operations/interfaces',()=>{n++;return answer({sampled_at:100+n*2,counters:{eth1:counters(1000*n,1000*n)}});});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();await tick();
 h.context.visible=false;const before=h.requests.length;await h.run();
 assert.equal(h.requests.length,before,'the tick of a hidden tab asks nothing');assert.equal(h.live().length,0,'and schedules nothing');
 h.context.visible=true;h.context.diagVisibilityChanged();await tick();await tick();
 assert.equal(h.requests.filter(r=>r.startsWith('/operations/interfaces')).length,2,'exactly one fresh fetch');
 assert.doesNotMatch(h.get('diag-if-body').innerHTML,/B\/s/,'the fetch on return replaces the content: a new baseline, no rate across the gap');
 assert.equal(h.live().length,1,'polling continues');
});

test('the reset is keyed on the lab and device and runs from the drawer close hook',async()=>{
 const h=harness();
 h.on('/operations/netem',()=>({present:true,impairments:[]}));h.on('/operations/interfaces',()=>answer());h.on('/operations/logs',()=>logAnswer([logLine(stamp(1),'hello')]));
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');h.open('logs');await tick();await tick();
 h.get('diag-log-follow').fire('click');await tick();await tick();
 assert.equal(h.get('diag-log-follow').getAttribute('aria-pressed'),'true');assert.ok(h.live().length>=1);
 h.get('diag-log-find').value='zzz';
 h.context.renderDeviceDiagnostics({name:'r1'});assert.equal(h.get('diag-interfaces').open,true,'the same device keeps its sections across the 4 s render');
 h.context.renderDeviceDiagnostics({name:'r2'});
 assert.equal(h.get('diag-interfaces').open,false,'Next device collapses both sections');assert.equal(h.get('diag-logs').open,false);
 assert.equal(h.live().length,0,'the timers are cleared');assert.equal(h.get('diag-log-follow').getAttribute('aria-pressed'),'false');assert.equal(h.get2('diagLog').lines.length,0);assert.equal(h.get2('diagIf').sample,null);
 assert.equal(h.get('diag-log-find').value,'');assert.equal(h.get('diag-if-body').innerHTML,'');
 h.open('interfaces');await tick();await tick();h.context.activeId='L2';h.context.renderDeviceDiagnostics({name:'r1'});
 assert.equal(h.get('diag-interfaces').open,false,'another lab\'s device of the same name is a different key');
 h.open('logs');await tick();await tick();assert.ok(h.get2('diagSec').logs.open);
 h.context.resetDeviceDiagnostics();
 assert.equal(h.get('diag-logs').open,false,'the close hook collapses both sections');assert.equal(h.live().length,0);
 assert.equal(h.get2('diagKey'),'');
 const reopened=h.requests.length;h.context.renderDeviceDiagnostics({name:'r1'});assert.equal(h.requests.length,reopened,'reopening the same device starts clean and asks for nothing');
});

test('a late answer for a device the drawer has left is discarded',async()=>{
 const h=harness();let release;
 h.on('/operations/netem',()=>({present:true,impairments:[]}));
 h.on('/operations/interfaces',()=>new Promise(resolve=>{release=()=>resolve(answer());}));
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();
 h.context.renderDeviceDiagnostics({name:'r2'});release();await tick();await tick();
 assert.equal(h.get('diag-if-body').innerHTML,'');assert.equal(h.live().length,0);
});

test('Follow: aria-pressed, tail=2000 on every request, since = the last stamped line, nothing earlier is repeated',async()=>{
 const h=harness();let n=0;
 h.on('/operations/logs',url=>{n++;
  if(n===1)return logAnswer([logLine(stamp(1),'one'),logLine(stamp(2),'two'),logLine('','stampless tail')]);
  return logAnswer([logLine(stamp(2),'two'),logLine(stamp(3),'three')]);});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 assert.match(h.requests[0],/tail=200/);assert.doesNotMatch(h.requests[0],/since=/,'the first load has no cursor');
 assert.equal(h.live().length,0,'without Follow nothing polls');
 assert.match(h.get('diag-log-view').innerHTML,/00:00|02:03:01 one/);
 h.get('diag-log-follow').fire('click');await tick();await tick();
 assert.equal(h.get('diag-log-follow').getAttribute('aria-pressed'),'true');
 const second=h.requests[1];assert.match(second,/tail=2000/);assert.match(second,new RegExp('since='+encodeURIComponent(stamp(2))),'the cursor skips the stampless tail');
 assert.equal((h.get('diag-log-view').innerHTML.match(/two/g)||[]).length,1,'the repeated line is dropped');assert.match(h.get('diag-log-view').innerHTML,/three/);
 assert.equal(h.get('diag-log-status').textContent,'Following the log.','the first answer under Follow does not rewrite the status');
 assert.equal(h.live().length,1);assert.equal(h.live()[0].ms,5000);
 h.live()[0].fn();await tick();await tick();
 assert.equal(h.get('diag-log-status').textContent,'Following the log.','a routine poll never rewrites the status');
 h.get('diag-log-follow').fire('click');
 assert.equal(h.get('diag-log-follow').getAttribute('aria-pressed'),'false');assert.equal(h.get('diag-log-status').textContent,'Follow stopped.');
});

test('Follow scrolls to the end only when the reader was within 30 px of the bottom; Refresh always does',async()=>{
 const h=harness();let n=0;
 h.on('/operations/logs',()=>{n++;return logAnswer([logLine(stamp(n),'line '+n)]);});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 const view=h.get('diag-log-view');view.scrollHeight=1000;view.clientHeight=300;view.scrollTop=700;
 h.get('diag-log-follow').fire('click');await tick();await tick();
 assert.equal(view.scrollTop,1000,'at the bottom: the append follows');
 view.scrollTop=100;await h.run();assert.equal(view.scrollTop,100,'the reader scrolled up: left where they are');
 h.get('diag-log-refresh').fire('click');await tick();await tick();assert.equal(view.scrollTop,1000,'Refresh scrolls to the end');
});

test('Follow appends keep what is on screen: lines are added at the end and the pushed-out ones leave from the top',async()=>{
 const h=harness();let n=0;
 const batch=(from,to)=>Array.from({length:to-from},(_,i)=>logLine(`2026-10-23T05:00:00.${String(from+i).padStart(9,'0')}Z`,'x'+(from+i)));
 h.on('/operations/logs',()=>{n++;return n===1?logAnswer(batch(0,1995)):logAnswer(batch(1990,2005));});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 const view=h.get('diag-log-view');view.removable=1995;
 h.get('diag-log-follow').fire('click');await tick();await tick();
 assert.equal(view.appended.length,1,'an append, not a rebuild');assert.equal(view.removed,5,'five oldest lines leave the screen');
 assert.match(h.get('diag-log-note').textContent,/Older lines dropped\./);
});

test('Logs empty states: no container, nothing written yet, nothing matching; one note element',async()=>{
 const h=harness();let body=logAnswer([]);
 h.on('/operations/logs',()=>body);
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 assert.equal(h.get('diag-log-note').textContent,'The container has written nothing yet.');assert.equal(h.get('diag-log-note').hidden,false);
 body={container:'c',present:false,facts:{present:false},lines:[],truncated:false};h.get('diag-log-refresh').fire('click');await tick();await tick();
 assert.match(h.get('diag-log-note').textContent,/No container for this device yet/);
 body=logAnswer([logLine(stamp(1),'alpha')],{truncated:true});h.get('diag-log-refresh').fire('click');await tick();await tick();
 assert.equal(h.get('diag-log-count').textContent,'1 line');assert.match(h.get('diag-log-note').textContent,/only the end of it is shown/);
 h.get('diag-log-find').value='zzz';h.get('diag-log-find').fire('input');
 assert.equal(h.get('diag-log-count').textContent,'0 of 1 line');assert.match(h.get('diag-log-note').textContent,/No lines match your search\./);
 assert.equal(h.get('diag-log-view').innerHTML,'');
});

test('Export saves the shown lines with their full stamps under the dated file name and sends nothing to the manager',async()=>{
 const h=harness();
 h.on('/operations/logs',()=>logAnswer([logLine(stamp(1),'alpha'),logLine(stamp(2),'beta')]));
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 const before=h.requests.length;
 const name=h.context.diagExport();
 assert.match(name,/^lab-one-router-1-logs-\d{8}T\d{6}Z\.txt$/);assert.deepEqual(h.downloads,[name]);assert.equal(h.requests.length,before);
});

test('Capture opens the capture dialog on the container interface name of this device',async()=>{
 const h=harness();
 h.on('/operations/netem',()=>({present:true,impairments:[]}));h.on('/operations/interfaces',()=>answer());
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();await tick();
 const button={disabled:false,dataset:{diagCapture:'eth1'}};
 h.get('diag-if-body').fire('click',{target:{closest:()=>button}});
 assert.deepEqual(Array.from(h.context.opened),['r1','eth1']);
 h.context.opened=null;button.disabled=true;h.get('diag-if-body').fire('click',{target:{closest:()=>button}});assert.equal(h.context.opened,null,'a disabled Capture does nothing');
});

test('the tail choice reloads the log; the stopped container still gets its last output',async()=>{
 const h=harness();
 h.on('/operations/logs',url=>logAnswer([logLine(stamp(1),'last words')],{facts:{present:true,id:HEX,status:'exited'}}));
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 h.get('diag-log-tail').value='1000';h.get('diag-log-tail').fire('change');await tick();await tick();
 assert.match(h.requests[1],/tail=1000/);assert.match(h.get('diag-log-view').innerHTML,/last words/);
});

test('C04: diagnosticsFacts gives the open device\'s facts only while a section is open and polling, and the drawer is drawn again when that changes',async()=>{
 const h=harness();let redraws=0;
 h.context.renderDetails=()=>{redraws++;};h.get('details-dialog').open=true;
 h.on('/operations/netem',()=>({container:'c',present:true,impairments:[]}));
 h.on('/operations/interfaces',()=>answer());h.on('/operations/logs',()=>logAnswer([logLine(stamp(1),'a')]));
 const facts=key=>h.context.diagnosticsFacts(key);
 assert.equal(facts('L1/r1'),null,'nothing before a section was opened');
 h.context.renderDeviceDiagnostics({name:'r1'});assert.equal(facts('L1/r1'),null);
 h.open('interfaces');await tick();await tick();
 assert.equal(facts('L1/r1').pid,5);assert.equal(facts('L1/r1').health,'');assert.equal(facts('L1/r2'),null,'another device\'s key never answers');assert.equal(facts('L2/r1'),null);
 assert.ok(redraws>=1,'the drawer was drawn again when the facts appeared');
 const before=redraws;await h.run();assert.equal(redraws,before,'an unchanged answer redraws nothing');
 h.get('diag-interfaces').open=false;h.get('diag-interfaces').fire('toggle');
 assert.equal(facts('L1/r1'),null,'closing the section drops the live rows');assert.equal(redraws,before+1,'and the drawer is drawn again at once');
 // Logs counts only while Follow polls: a one-shot Refresh would leave stale facts under a caption that says they are live
 h.open('logs');await tick();await tick();assert.equal(facts('L1/r1'),null,'Logs without Follow is not polling');
 h.get('diag-log-follow').fire('click');await tick();await tick();assert.equal(facts('L1/r1').status,'running','Follow polls');
 h.get('diag-log-follow').fire('click');assert.equal(facts('L1/r1'),null,'Follow stopped');
 h.get('diag-log-follow').fire('click');await tick();await tick();assert.ok(facts('L1/r1'));
 h.context.resetDeviceDiagnostics();assert.equal(facts('L1/r1'),null,'the drawer closing clears the cache');
});
test('C04: a stopped poll and a not-present container show no live facts',async()=>{
 const h=harness();let fail=false,absent=false;h.context.renderDetails=()=>{};
 h.on('/operations/netem',()=>({present:true,impairments:[]}));
 h.on('/operations/interfaces',()=>{if(fail)throw Object.assign(new Error('x'),{status:409});return absent?{container:'c',present:false,facts:{present:false},interfaces:[]}:answer();});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();await tick();
 assert.ok(h.context.diagnosticsFacts('L1/r1'));
 fail=true;await h.run();await h.run();await h.run();
 assert.equal(h.get('diag-if-retry').hidden,false);assert.equal(h.context.diagnosticsFacts('L1/r1'),null,'a stopped poll is not live');
 fail=false;absent=true;h.get('diag-if-retry').fire('click');await tick();await tick();
 assert.equal(h.context.diagnosticsFacts('L1/r1'),null,'a container the VM does not have has no facts to show');
});
test('this script declares only diag and DIAG names and keeps document and window listeners out (shell.js owns them)',()=>{
 const names=[...source.matchAll(/^(?:const|let|function|async function) +([A-Za-z0-9_]+)/gm)].map(m=>m[1]);
 for(const name of names)assert.match(name,/^(diag|DIAG_|renderDeviceDiagnostics$|resetDeviceDiagnostics$)/i,name);
 assert.doesNotMatch(source,/document\.addEventListener|window\.addEventListener|addEventListener\('visibilitychange/);
 const shell=fs.readFileSync(path.join(dir,'shell.js'),'utf8');
 assert.match(shell,/function pageVisible\(\)\{return typeof document==='undefined'\|\|document\.visibilityState!=='hidden';\}/);
 assert.match(shell,/addEventListener\('visibilitychange'/);assert.match(shell,/resetDeviceDiagnostics/);
});

test('the impairment line prints durations as given, percentages and kbit, and skips zero fields',()=>{
 const f=harness().context.diagImpairment;
 assert.equal(f({delay:'10ms',jitter:'2ms',loss:5,corruption:'0.5',rate:1000}),'delay 10ms · jitter 2ms · loss 5% · corruption 0.5% · rate 1000 kbit');
 assert.equal(f({delay:'0s',jitter:'0ms',loss:0,corruption:'0',rate:'',}),'','zero and empty fields are not impairments');
 assert.equal(f({delay:'1s',loss:'0%',rate:null}),'delay 1s');
 assert.equal(f({loss:'2%'}),'loss 2%','a value that already carries its unit is not given a second one');
 assert.equal(f(null),'');
});

test('Follow resume after a hidden tab replaces with tail=2000 and no since; the missing note is sticky until a replace',async()=>{
 const h=harness();let n=0;
 const many=count=>Array.from({length:count},(_,i)=>logLine(`2026-10-23T03:00:00.${String(i).padStart(9,'0')}Z`,'l'+i));
 h.on('/operations/logs',()=>{n++;return n===2?logAnswer(many(2000)):logAnswer([logLine(stamp(n),'x'+n)]);});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 h.get('diag-log-follow').fire('click');await tick();await tick();
 assert.match(h.get('diag-log-note').textContent,/Some lines may be missing\./,'exactly 2000 lines back');
 await h.run();
 assert.match(h.get('diag-log-note').textContent,/Some lines may be missing\./,'a later, shorter poll does not clear it');
 h.context.diagVisibilityChanged();await tick();await tick();
 const resume=h.requests.at(-1);
 assert.match(resume,/tail=2000/,'the resume under Follow asks for 2000 lines');assert.doesNotMatch(resume,/since=/,'and sends no cursor: it replaces');
 assert.doesNotMatch(h.get('diag-log-note').textContent,/missing/,'a replace clears the note');
});

test('a 503 on a one-shot Logs fetch retries once after 5 s with "The VM is busy, retrying…", then stops with Retry',async()=>{
 const h=harness();let mode='busy';
 h.on('/operations/logs',()=>{if(mode==='busy')throw Object.assign(new Error('The manager is already asking the VM for diagnostics; try again in a moment.'),{status:503});return logAnswer([logLine(stamp(1),'ok')]);});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 assert.equal(h.get('diag-log-status').textContent,'The VM is busy, retrying…');assert.equal(h.get('diag-log-retry').hidden,true);
 assert.equal(h.live().length,1);assert.equal(h.live()[0].ms,5000);
 await h.run();
 assert.equal(h.get('diag-log-retry').hidden,false,'the second 503 stops with Retry');assert.equal(h.live().length,0);
 mode='ok';h.get('diag-log-retry').fire('click');await tick();await tick();
 assert.equal(h.get('diag-log-retry').hidden,true);assert.match(h.get('diag-log-view').innerHTML,/ok/);
 mode='busy';h.get('diag-log-refresh').fire('click');await tick();await tick();
 assert.equal(h.get('diag-log-status').textContent,'The VM is busy, retrying…','the automatic retry is available again for the next one-shot fetch');
 mode='ok';await h.run();assert.equal(h.get('diag-log-retry').hidden,true);assert.match(h.get('diag-log-view').innerHTML,/ok/);
});

test('an unreachable manager says so; an HTTP error keeps the manager\'s sentence',async()=>{
 const h=harness();let mode='net';const sentence='Cannot reach the VM operations helper. Check setup and SSH settings.';
 h.on('/operations/logs',()=>{if(mode==='net')throw new TypeError('Failed to fetch');throw Object.assign(new Error(sentence),{status:409});});
 h.context.renderDeviceDiagnostics({name:'r1'});h.open('logs');await tick();await tick();
 assert.equal(h.get('diag-log-status').textContent,'The manager did not answer. Check the connection, then Retry.');assert.equal(h.get('diag-log-retry').hidden,false);
 mode='http';h.get('diag-log-retry').fire('click');await tick();await tick();
 assert.equal(h.get('diag-log-status').textContent,sentence);
});

test('Export stays disabled until a line is shown, and saves nothing when none is',async()=>{
 const h=harness();let lines=[];
 h.on('/operations/logs',()=>logAnswer(lines));
 h.context.renderDeviceDiagnostics({name:'r1'});
 assert.equal(h.get('diag-log-export').disabled,true,'a reset drawer starts with Export disabled');
 h.open('logs');await tick();await tick();
 assert.equal(h.get('diag-log-export').disabled,true,'an empty log has nothing to export');assert.equal(h.context.diagExport(),'');assert.deepEqual(h.downloads,[]);
 lines=[logLine(stamp(1),'alpha')];h.get('diag-log-refresh').fire('click');await tick();await tick();
 assert.equal(h.get('diag-log-export').disabled,false);
 h.get('diag-log-find').value='zzz';h.get('diag-log-find').fire('input');
 assert.equal(h.get('diag-log-export').disabled,true,'a Find that shows nothing disables it again');
});

test('the Find label and field are wrapped in one group that never splits; the numeric cells never wrap',()=>{
 const placed=[];
 const find={id:'find',previousElementSibling:{id:'label'},parentNode:{className:'diag-toolbar',insertBefore:(g,l)=>placed.push(['before',g.className,l.id])}};
 const group={className:'',append:(...c)=>placed.push(['append',...c.map(x=>x.id)])};
 const c=vm.createContext({$:id=>id==='diag-log-find'?find:null,esc,document:{createElement:()=>group}});
 vm.runInContext(source,c);
 assert.deepEqual(placed,[['before','diag-find','label'],['append','label','find']]);
 assert.match(css,/\.diag-find \{ display: inline-flex;/);
 const narrow=css.slice(css.indexOf('@media (max-width: 480px)'));
 assert.doesNotMatch(narrow.slice(0,narrow.indexOf('}\n}')),/diag-table td:nth-child\(n\+2\)/,'the narrow rule no longer lets RX, TX and Port wrap');
 assert.match(css,/\.diag-table td:nth-child\(n\+2\) \{ white-space: nowrap; overflow-wrap: normal; \}/);
});

test('the Other interfaces summary carries a key, so a poll rebuild gives it focus back and keeps the region scroll',()=>{
 const h=harness();
 assert.match(h.context.diagInterfacesMarkup(answer(),{device:'r1',withCounters:true}),/<summary data-diag-key="other-summary">Other interfaces \(1\)<\/summary>/);
 const body=h.get('diag-if-body'),summary={disabled:false,dataset:{diagKey:'other-summary'},focused:0,focus(){this.focused++;}};
 const region={dataset:{diagKey:'region:other'},scrollLeft:0};
 body.contains=node=>node===summary;body.querySelectorAll=()=>[{dataset:{diagKey:'region:other'},scrollLeft:120}];
 body.querySelector=sel=>sel==='[data-diag-key="other-summary"]'?summary:sel==='[data-diag-key="region:other"]'?region:null;
 h.context.document.activeElement=summary;
 assert.equal(h.context.diagSet(body,'<p>one</p>'),true);
 assert.equal(summary.focused,1,'the summary that held focus is focused again after the rebuild');assert.equal(region.scrollLeft,120,'the region keeps its horizontal scroll');
 assert.equal(h.context.diagSet(body,'<p>one</p>'),false,'unchanged markup is not rebuilt');assert.equal(summary.focused,1);
});

test('hiding Retry or Resume while it holds focus moves focus to the section summary first',()=>{
 for(const [name,box,retry] of [['interfaces','diag-interfaces','diag-if-retry'],['logs','diag-logs','diag-log-retry']]){
  const h=harness(),button=h.get(retry),summary={focused:0,focus(){this.focused++;}};
  h.get(box).querySelector=sel=>sel==='summary'?summary:null;
  h.context.diagRetryButton(name,'retry');assert.equal(button.hidden,false);
  h.context.document.activeElement=button;h.context.diagRetryButton(name,'');
  assert.equal(summary.focused,1,name+': focus moved to the summary');assert.equal(button.hidden,true);
  h.context.document.activeElement=null;h.context.diagRetryButton(name,'resume');h.context.diagRetryButton(name,'');assert.equal(summary.focused,1,'focus elsewhere is left alone');
 }
});

test('Capture all connected: only with two or more data rows, carrying the capture attributes, opening the dialog with the data rows as the preset',async()=>{
 const h=harness(),c=h.context;
 const ctx={device:'r1',rates:{},impair:{},captureAttrs:'',captureReason:'',otherOpen:false};
 assert.doesNotMatch(c.diagInterfacesMarkup(answer(),ctx),/data-diag-capture-all/,'one data row: nothing to capture "all" of');
 const two=answer({interfaces:[iface({name:'eth0',port:'',role:'management'}),iface({name:'eth1'}),iface({name:'eth2',port:'ge-0/0/1'}),iface({name:'cpu',port:'',role:'internal'})]});
 const out=c.diagInterfacesMarkup(two,ctx);
 assert.equal((out.match(/data-diag-capture-all=/g)||[]).length,1,'one button, in the main table');
 assert.match(out,/<button type="button" class="button ghost small" data-diag-capture-all="\[&quot;eth1&quot;,&quot;eth2&quot;\]"[^>]*>Capture all connected<\/button>/);
 const off=c.diagInterfacesMarkup(two,{...ctx,captureAttrs:'disabled title="Packet capture is not set up on this VM. See Tools › Packet capture for details."'});
 assert.match(off,/data-diag-capture-all="[^"]*"[^>]*disabled title="Packet capture is not set up/,'captureActionAttrs() reaches the button');
 const hostile=c.diagInterfacesMarkup(answer({interfaces:[iface({name:'<img onerror=x>'}),iface({name:'eth2'})]}),ctx);
 assert.doesNotMatch(hostile,/<img/);
 // the click
 h.on('/operations/netem',()=>({present:true,impairments:[]}));h.on('/operations/interfaces',()=>two);
 c.renderDeviceDiagnostics({name:'r1'});h.open('interfaces');await tick();await tick();
 c.openedFull=null;
 const button={disabled:false,dataset:{diagCaptureAll:'["eth1","eth2"]'}};
 h.get('diag-if-body').fire('click',{target:{closest:sel=>sel==='[data-diag-capture-all]'?button:null}});
 assert.equal(JSON.stringify(c.openedFull),JSON.stringify(['r1','',null,{preset:['eth1','eth2']}]));
 c.openedFull=null;button.disabled=true;h.get('diag-if-body').fire('click',{target:{closest:sel=>sel==='[data-diag-capture-all]'?button:null}});
 assert.equal(c.openedFull,null,'a disabled button does nothing');
});
