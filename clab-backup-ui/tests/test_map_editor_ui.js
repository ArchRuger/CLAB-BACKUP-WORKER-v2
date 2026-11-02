// map-editor-page.js: the pure rules of the map editor page, its save and leave behaviour over a small
// fake document, and the wiring that sends Edit map there.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
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
const read=name=>fs.readFileSync(path.join(__dirname,'../app/static/'+name),'utf8');
function harness({session=false,get,hash='#lab=lab1',doc={name:'BGP lab',yaml:'name: bgp\n',annotations:'{"nodeAnnotations":[]}',revision:'r1'},put}={}){
 const elements=new Map(),calls=[],moves=[],toasts=[];
 const el=id=>{if(!elements.has(id))elements.set(id,{id,hidden:false,disabled:false,textContent:'',className:'',title:'',href:'',value:'',files:[],inert:false,open:false,onclick:null,focused:0,focus(){this.focused++;},showModal(){this.open=true;},close(){this.open=false;}});return elements.get(id);};
 const context=vm.createContext({console,URLSearchParams,Blob:class{},URL:{createObjectURL:()=>'blob:x',revokeObjectURL(){}},setTimeout:()=>0,clearTimeout(){},
  document:{getElementById:el,title:'',querySelector:()=>null,createElement:()=>({click(){},remove(){}}),body:{append(){}}},
  location:{hash,pathname:'/static/map-editor.html',search:'',assign:u=>moves.push(u),replace:u=>moves.push('replace:'+u),reload:()=>moves.push('reload')},
  fetch:async(url,options={})=>{calls.push({url,method:options.method||'GET',body:options.body?JSON.parse(options.body):undefined});
   if((options.method||'GET')==='GET'&&get){const answer=get(url);if(answer)return answer;}
   if((options.method||'GET')==='GET')return doc?{ok:true,json:async()=>doc}:{ok:false,status:409,json:async()=>({detail:'This lab has no topology file in the manager, so its map opens in the simple editor.'})};
   return put?put(JSON.parse(options.body)):{ok:true,json:async()=>({saved:true,revision:'r2'})};}});
 context.window=context;context.window.addEventListener=()=>{};
 if(session)vm.runInContext(SESSION_STAND_IN,context);
 vm.runInContext(read('map-editor-page.js'),context);
 return {context,el,calls,moves,toasts,flush:()=>new Promise(r=>setImmediate(r))};
}
test('pure rules: the lab comes from the hash, the way back is the lab\'s Topology tab, and a map file is checked in plain words',()=>{
 const {context:c}=harness();
 assert.equal(c.mapLabFromHash('#lab=abc123'),'abc123');assert.equal(c.mapLabFromHash('#lab=../etc'),'');assert.equal(c.mapLabFromHash(''),'');
 assert.equal(c.mapBackUrl('abc'),'/#lab=abc&view=topology');assert.equal(c.mapBackUrl(''),'/');
 assert.equal(c.mapIsDirty(null,'x'),false,'nothing is unsaved before the editor has read the document');assert.equal(c.mapIsDirty('a','a'),false);assert.equal(c.mapIsDirty('a','b'),true);
 assert.equal(c.mapFileName('Week 4: BGP/final'),'Week 4_ BGP_final.clab.yaml.annotations.json');
 assert.deepEqual(JSON.parse(JSON.stringify([c.mapStatusView({dirty:true}),c.mapStatusView({}),c.mapStatusView({saving:true,dirty:true}),c.mapStatusView({paused:true})].map(v=>v.text))),['Unsaved changes','Saved in the manager','Saving…','Editing paused']);
 assert.deepEqual(JSON.parse(JSON.stringify(c.mapStatusView({sessionLost:true,dirty:true}))),{text:'Not saved · signed out',pill:'bad'},'a lost session is not an editing pause: the editor still works');
 assert.equal(c.mapStatusView({paused:true,sessionLost:true}).text,'Editing paused','a real pause wins');
 assert.match(c.mapImportProblem('notes.txt','{}'),/ends in \.annotations\.json/);assert.equal(c.mapImportProblem('a.json','  '),'This file is empty.');assert.match(c.mapImportProblem('a.json','{oops'),/not valid JSON/);
 assert.match(c.mapImportProblem('a.json','[1]'),/not a containerlab map file/);assert.match(c.mapImportProblem('a.json','{"name":"x"}'),/not a containerlab map file/);assert.match(c.mapImportProblem('a.json','x'.repeat(1024*1024+1)),/larger than 1 MiB/);
 assert.equal(c.mapImportProblem('lab.annotations.json','{"nodeAnnotations":[]}'),'');
});
test('the page mounts the editor in map mode, saves only the annotations, and never accepts a changed topology',async()=>{
 const h=harness(),c=h.context,mounted=[];await h.flush();
 c.labBuilderPage.ready(async draft=>{mounted.push(draft);});await h.flush();
 assert.equal(mounted.length,1);assert.equal(mounted[0].mapOnly,true,'the adapter is told to refuse topology commands');assert.equal(mounted[0].yaml,'name: bgp\n');assert.equal(mounted[0].id,'map:lab1');
 assert.equal(h.el('map-back').href,'/#lab=lab1&view=topology');assert.equal(h.el('map-name').textContent,'BGP lab');
 const first='{"nodeAnnotations":[],"viewerSettings":{}}';c.labBuilderPage.persist('name: bgp\n',first);
 assert.equal(h.el('map-save').disabled,true,'the editor\'s own first reading is the baseline, not a change');assert.equal(h.el('map-status').textContent,'Saved in the manager');
 c.labBuilderPage.persist('name: bgp\n','{"nodeAnnotations":[{"id":"r1"}]}');assert.equal(h.el('map-save').disabled,false);assert.equal(h.el('map-status').textContent,'Unsaved changes');
 assert.throws(()=>c.labBuilderPage.persist('name: other\n','{}'),/does not change the topology/);assert.equal(vm.runInContext('mapCurrent',c),'{"nodeAnnotations":[{"id":"r1"}]}','a refused state is not kept');
 await h.el('map-save').onclick();await h.flush();
 const put=h.calls.find(x=>x.method==='PUT');assert.equal(put.url,'/api/labs/lab1/map-document');assert.deepEqual(Object.keys(put.body).sort(),['annotations','revision'],'the request cannot carry a topology');assert.equal(put.body.revision,'r1');
 assert.equal(h.el('map-save').disabled,true);assert.equal(h.el('map-status').textContent,'Saved in the manager');
 c.labBuilderPage.persist('name: bgp\n','{"nodeAnnotations":[{"id":"r2"}]}');await h.el('map-save').onclick();await h.flush();
 assert.equal(h.calls.filter(x=>x.method==='PUT')[1].body.revision,'r2','the next save uses the revision the manager answered with');
 assert.ok(!h.calls.some(x=>/operations|deploy|publish|revise/.test(x.url)),'no operation of any kind is requested');
});
test('a refused save keeps the changes and says so; leaving with changes asks; without changes it just leaves',async()=>{
 const h=harness({put:()=>({ok:false,status:409,json:async()=>({detail:'The map changed since it was opened.'})})}),c=h.context;await h.flush();
 c.labBuilderPage.ready(async()=>{});await h.flush();c.labBuilderPage.persist('name: bgp\n','a');
 h.el('map-back').onclick({preventDefault(){}});assert.deepEqual(h.moves,['/#lab=lab1&view=topology'],'nothing unsaved: leave at once');h.moves.length=0;
 c.labBuilderPage.persist('name: bgp\n','b');await h.el('map-save').onclick();await h.flush();
 assert.match(h.el('toast').textContent,/changed since it was opened\. Download this map/);assert.equal(h.el('map-status').textContent,'Unsaved changes','a failed save is not reported as saved');assert.equal(h.el('map-save').disabled,false);
 h.el('map-back').onclick({preventDefault(){}});assert.equal(h.el('map-leave').open,true);assert.deepEqual(h.moves,[]);
 h.el('map-leave-stay').onclick();assert.equal(h.el('map-leave').open,false);assert.deepEqual(h.moves,[]);
 await h.el('map-leave-save').onclick();await h.flush();assert.deepEqual(h.moves,[],'a save that failed does not leave');
 h.el('map-leave-discard').onclick();assert.deepEqual(h.moves,['/#lab=lab1&view=topology']);
 c.labBuilderPage.persist('name: bgp\n','c');h.el('map-drawio').onclick();assert.match(h.el('toast').textContent,/Save the map first/);
});
test('a lab without a topology text is told why, and Edit map only goes to the map editor when the manager says it can',async()=>{
 const none=harness({doc:null});await none.flush();assert.match(none.el('map-welcome-text').textContent,/simple editor/);assert.equal(none.el('map-save').disabled,true);
 const noLab=harness({hash:''});await noLab.flush();assert.match(noLab.el('map-welcome-text').textContent,/No lab was named/);
 const moves=[];let simple=0;const ctx=vm.createContext({$:()=>null,esc:String,state:{labs:[{id:'a',map_editor:true},{id:'b',map_editor:false}]},console,document:{body:{insertAdjacentHTML(){}},querySelectorAll:()=>[],getElementById:()=>null},location:{pathname:'/',assign:u=>moves.push(u)},sessionStorage:{getItem:()=>null,setItem(){}},setTimeout:()=>0,clearTimeout(){},editDiagram:async()=>{simple++;}});
 vm.runInContext(read('operations.js'),ctx);
 await ctx.opLayout('a');assert.deepEqual(moves,['/static/map-editor.html#lab=a']);assert.equal(simple,0);await ctx.opLayout('b');assert.equal(simple,1);await ctx.opLayout('missing');assert.equal(simple,2);
 const html=read('map-editor.html');assert.match(html,/map-editor-page\.js\?v=/);assert.match(html,/lab-builder\/assets\/main\.js\?v=/);assert.doesNotMatch(html,/operations\.js|lab-builder-page\.js/,'the map editor page loads nothing that can start a VM operation or touch the builder\'s drafts');
 const adapter=fs.readFileSync(path.join(__dirname,'../lab-builder/src/main.tsx'),'utf8');
 for(const allowed of ['savePositions','setAnnotations','setAnnotationsWithMemberships','setEdgeAnnotations','setViewerSettings','setNodeGroupMembership'])assert.ok(adapter.includes('"'+allowed+'"'),allowed);
 assert.match(adapter,/command: "setAnnotationsContent"/,'the page-level history replaces the annotations document, nothing else');assert.doesNotMatch(adapter,/command: "(undo|redo)"/,'the engine\'s own undo restores both files and is never used');
 const mapStart=adapter.indexOf('if (mapOnly && page.attach)'),mapHandle=adapter.slice(mapStart,adapter.indexOf('\n  });',mapStart));assert.ok(mapHandle.includes('applyAnnotations')&&!mapHandle.includes('setYamlContent'),'the map editor\'s handle never replaces the topology');
 assert.equal(adapter.split('command: "setYamlContent"').length,2,'setYamlContent is sent from one place');assert.ok(adapter.indexOf('command: "setYamlContent"')>adapter.indexOf('if (!mapOnly && page.attach)'),'only the lab builder\'s YAML handle sends setYamlContent');
 for(const refused of ['addNode','editNode','deleteNode','addLink','editLink','deleteLink','setYamlContent','setLabSettings','undo','redo'])assert.ok(!new RegExp('MAP_COMMANDS[^;]*"'+refused+'"').test(adapter),refused+' must never be in the map editor\'s whitelist');
});

test('undo and redo are the page\'s own history of the map document: steps, merging of quick successions, a new edit drops the redo branch',async()=>{
 const h=harness(),c=h.context,push=(hist,text,now)=>JSON.parse(JSON.stringify(c.mapHistoryPush(hist,text,now)));
 let hist={entries:[],index:-1,at:0};hist=push(hist,'a',1000);assert.deepEqual(hist,{entries:['a'],index:0,at:1000});
 hist=push(hist,'b',1100);assert.deepEqual(hist.entries,['a','b'],'the state Undo returns to (the first) is never merged away');
 hist=push(hist,'c',1300);assert.deepEqual(hist.entries,['a','c'],'states within 700 ms are one step (typing, a drag that settles twice)');
 hist=push(hist,'d',5000);assert.deepEqual(hist.entries,['a','c','d']);hist=push(hist,'d',9000);assert.deepEqual(hist.entries,['a','c','d'],'an unchanged state adds nothing');
 const back=JSON.parse(JSON.stringify(c.mapHistoryStep(hist,-1)));assert.equal(back.index,1);assert.equal(c.mapHistoryStep(hist,1),null);assert.equal(c.mapHistoryStep({entries:['a'],index:0},-1),null);
 const branched=push(back,'e',back.at+10);assert.deepEqual(branched.entries,['a','c','e'],'a new edit after an undo drops what could be redone, and does not overwrite the step returned to');
 let long={entries:[],index:-1,at:0};for(let i=0;i<80;i++)long=push(long,'s'+i,i*10000);assert.equal(long.entries.length,60);assert.equal(long.entries[59],'s79');
 // the page: buttons follow the history, a step goes through the adapter's handle and is not pushed again
 await h.flush();c.labBuilderPage.ready(async()=>{});await h.flush();
 const applied=[];c.labBuilderPage.attach({applyAnnotations:async text=>{applied.push(text);c.labBuilderPage.persist('name: bgp\n',text);}});
 const real=c.Date;let clock=0;c.Date={now:()=>clock+=5000};
 c.labBuilderPage.persist('name: bgp\n','A');assert.equal(h.el('map-undo').disabled,true);assert.equal(h.el('map-redo').disabled,true);
 c.labBuilderPage.persist('name: bgp\n','B');c.labBuilderPage.persist('name: bgp\n','C');assert.equal(h.el('map-undo').disabled,false);
 await h.el('map-undo').onclick();assert.deepEqual(applied,['B']);assert.equal(vm.runInContext('mapHistory.entries.length',c),3,'the undone state was not pushed as a new one');assert.equal(h.el('map-redo').disabled,false);assert.equal(h.el('map-status').textContent,'Unsaved changes');
 await h.el('map-undo').onclick();assert.deepEqual(applied,['B','A']);assert.equal(h.el('map-status').textContent,'Saved in the manager','back at the opened map there is nothing to save');assert.equal(h.el('map-undo').disabled,true);assert.equal(h.el('map-save').disabled,true);
 await h.el('map-redo').onclick();assert.deepEqual(applied,['B','A','B']);
 c.labBuilderPage.attach({applyAnnotations:async()=>{throw new Error('stale');}});await h.el('map-undo').onclick();assert.match(h.el('toast').textContent,/^Undo did not work: stale/);assert.equal(vm.runInContext('mapHistory.index',c),1,'a failed step leaves the history where it was');
 c.Date=real;
});

test('the device look (applied through the editor\'s own node editor, translated by the adapter into applyLook) changes six keys of one device\'s entry and nothing else, with the editor\'s own values only',()=>{
 const {context:c}=harness(),text=JSON.stringify({nodeAnnotations:[{id:'r1',label:'Core',position:{x:1,y:2},groupId:'g',icon:'pe',vendorKey:{a:1}},{id:'r2',position:{x:3,y:4}}],groupStyleAnnotations:[{id:'g'}],somethingNew:[1]});
 const plain=v=>JSON.parse(JSON.stringify(v));
 assert.deepEqual(plain(c.mapLookDevices(text)),[{id:'r1',label:'Core',look:{icon:'pe'}},{id:'r2',label:'r2',look:{}}]);assert.deepEqual(plain(c.mapLookDevices('{oops')),[]);
 const next=JSON.parse(c.mapApplyLook(text,'r1',{icon:'server',iconColor:'#CC2200',iconCornerRadius:'12',labelPosition:'top',direction:'down',labelBackgroundColor:'transparent'}));
 assert.deepEqual(next.nodeAnnotations[0],{id:'r1',label:'Core',position:{x:1,y:2},groupId:'g',icon:'server',vendorKey:{a:1},iconColor:'#cc2200',iconCornerRadius:12,labelPosition:'top',direction:'down',labelBackgroundColor:'transparent'});
 assert.deepEqual(next.nodeAnnotations[1],{id:'r2',position:{x:3,y:4}},'other devices are untouched');assert.deepEqual(next.groupStyleAnnotations,[{id:'g'}]);assert.deepEqual(next.somethingNew,[1]);
 const cleared=JSON.parse(c.mapApplyLook(JSON.stringify(next),'r1',{icon:'',iconColor:'',iconCornerRadius:'',labelPosition:'',direction:'',labelBackgroundColor:''}));
 assert.deepEqual(cleared.nodeAnnotations[0],{id:'r1',label:'Core',position:{x:1,y:2},groupId:'g',vendorKey:{a:1}},'"default" removes the key instead of storing an empty value');
 for(const [bad,reason] of [[{icon:'<img>'},/listed icons/],[{iconColor:'red'},/not a colour/],[{iconCornerRadius:'33'},/0 to 32/],[{iconCornerRadius:'1.5'},/0 to 32/],[{labelPosition:'inside'},/label positions/],[{direction:'sideways'},/text directions/],[{labelBackgroundColor:'url(x)'},/not a colour/]])assert.throws(()=>c.mapApplyLook(text,'r1',bad),reason);
 assert.throws(()=>c.mapApplyLook(text,'ghost',{icon:'pe'}),/not on the map/);
 // The four corners are label positions of their own (item 6), and the page hands the adapter applyLook().
 for(const corner of ['center','top-left','top-right','bottom-left','bottom-right'])assert.equal(JSON.parse(c.mapApplyLook(text,'r1',{labelPosition:corner})).nodeAnnotations[0].labelPosition,corner);
 assert.deepEqual(plain(vm.runInContext('MAP_LABEL_POSITIONS.map(p=>p[0])',c)),['bottom','top','left','right','center','top-left','top-right','bottom-left','bottom-right']);
 assert.equal(typeof vm.runInContext('labBuilderPage.applyLook',c),'function');
 assert.doesNotMatch(read('map-editor.html'),/map-look/,'the page dialog is gone: the look is edited in the editor\'s node editor');
 const css=read('lab-builder.css');for(const tab of ['config','runtime','network','advanced'])assert.ok(css.includes('.map-editor [data-testid="panel-tab-'+tab+'"]'),'the map editor hides the node editor\'s '+tab+' tab');
 const code=fs.readdirSync(path.join(__dirname,'../app/static/lab-builder/assets')).filter(f=>f.endsWith('.js')).map(f=>fs.readFileSync(path.join(__dirname,'../app/static/lab-builder/assets',f),'utf8')).join('\n');
 for(const [icon] of vm.runInContext('MAP_ICONS',c))assert.ok(code.includes('"'+icon+'"'),'the bundled editor no longer knows the icon '+icon);
});

test('a link\'s own label distance is one edgeAnnotations entry found by the link\'s endpoints, 0 to 60, and removable',()=>{
 const {context:c}=harness(),plain=v=>JSON.parse(JSON.stringify(v));
 const links=[[{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}],[{node:'r2',interface:'eth2'},{node:'r3',interface:'eth1'}],['bad'],[{node:'r1'}]];
 const text=JSON.stringify({nodeAnnotations:[{id:'r1'}],edgeAnnotations:[{id:'e9',source:'r2',sourceEndpoint:'eth2',target:'r3',targetEndpoint:'eth1',endpointLabelOffsetEnabled:true,endpointLabelOffset:35,vendor:1}],somethingNew:[1]});
 const list=plain(c.mapLinks(links,text));assert.equal(list.length,2,'malformed links are skipped');
 assert.deepEqual(list[0],{source:'r1',sourceEndpoint:'eth1',target:'r2',targetEndpoint:'eth1',own:false,offset:20});assert.deepEqual([list[1].own,list[1].offset],[true,35]);
 assert.equal(c.mapLinkLabel(list[0]),'r1:eth1  ↔  r2:eth1');
 const added=JSON.parse(c.mapApplyLinkOffset(text,list[0],true,'48'));
 assert.deepEqual(added.edgeAnnotations[1],{source:'r1',sourceEndpoint:'eth1',target:'r2',targetEndpoint:'eth1',endpointLabelOffsetEnabled:true,endpointLabelOffset:48});assert.deepEqual(added.edgeAnnotations[0].vendor,1);assert.deepEqual(added.somethingNew,[1]);assert.deepEqual(added.nodeAnnotations,[{id:'r1'}]);
 const changed=JSON.parse(c.mapApplyLinkOffset(text,list[1],true,10));assert.deepEqual(changed.edgeAnnotations,[{id:'e9',source:'r2',sourceEndpoint:'eth2',target:'r3',targetEndpoint:'eth1',endpointLabelOffsetEnabled:true,endpointLabelOffset:10,vendor:1}],'an existing entry is updated in place with its other keys');
 const off=JSON.parse(c.mapApplyLinkOffset(text,list[1],false,''));assert.deepEqual(off.edgeAnnotations,[{id:'e9',source:'r2',sourceEndpoint:'eth2',target:'r3',targetEndpoint:'eth1',vendor:1}],'turning it off keeps an entry that carries something else');
 const gone=JSON.parse(c.mapApplyLinkOffset(JSON.stringify(added),list[0],false,''));assert.equal(gone.edgeAnnotations.length,1,'and removes one that carried nothing else');
 assert.equal(c.mapApplyLinkOffset(JSON.stringify({nodeAnnotations:[]}),list[0],false,''),JSON.stringify({nodeAnnotations:[]},null,2),'nothing to turn off adds no key');
 for(const bad of ['61','-1','2.5','x',''])assert.throws(()=>c.mapApplyLinkOffset(text,list[0],true,bad),/0 to 60/,bad);
});
test('L-37: when the editor goes inert the problem overlay takes focus on its Download button, so a keyboard user is not left on <body>',async()=>{
 const h=harness(),c=h.context;await h.flush();
 assert.equal(h.el('map-problem-download').focused,0);
 c.mapProblem('The editor refused that edit.');
 assert.equal(h.el('root').inert,true);assert.equal(h.el('builder-problem').hidden,false);assert.equal(h.el('builder-problem-text').textContent,'The editor refused that edit.');
 assert.equal(h.el('map-problem-download').focused,1,'focus moves to Download this map, the way to keep unsaved edits');
});

// ---- signed out (docs/sign-on/UI.md 3.5) ----
const lostAnswer={ok:false,status:401,json:async()=>({detail:{code:'signed_out',message:'Your session ended. Sign in again.'}})};
const SESSION_TOAST='Your session ended. Sign in in a new tab, then save again.';
test('nothing unsaved: a signed_out answer leaves for the sign-in page at once with this page as next',async()=>{
 const h=harness({session:true,get:url=>url.endsWith('/map-document')?lostAnswer:null});await h.flush();
 assert.deepEqual(h.moves,['replace:/login?next='+encodeURIComponent('/static/map-editor.html#lab=lab1')+'&reason=ended']);
 assert.equal(h.context.sessionEnded(),true);
 const before=h.calls.length;await assert.rejects(()=>h.context.api('/labs/lab1/topology'),e=>e.sessionEnded===true);
 assert.equal(h.calls.length,before,'a page that is signed out sends nothing');
});
test('unsaved changes: the page pauses, says so with the new-tab link, keeps the changes and warns on leaving',async()=>{
 const h=harness({session:true,put:()=>lostAnswer}),c=h.context;await h.flush();c.labBuilderPage.ready(async()=>{});await h.flush();
 c.labBuilderPage.persist('name: bgp\n','a');c.labBuilderPage.persist('name: bgp\n','b');
 await h.el('map-save').onclick();await h.flush();
 assert.equal(h.moves.length,0,'no redirect: the drawing would be lost');
 assert.equal(h.el('map-status').textContent,'Not saved · signed out');assert.equal(h.el('map-status').className,'pill bad');assert.equal(h.el('toast').textContent,SESSION_TOAST);
 assert.equal(h.el('map-session').hidden,false,'the new-tab link is shown');assert.equal(vm.runInContext('mapCurrent',c),'b','the changes are kept');
 assert.equal(h.el('map-save').disabled,false,'Save stays available: it is the way back');assert.equal(vm.runInContext('mapPaused',c),false,'beforeunload keeps asking while changes are unsaved');
 h.el('map-back').onclick({preventDefault(){}});assert.equal(h.el('map-leave').open,true);
});
test('the next Save calls sessionRetry first, then saves; a second 401 pauses again',async()=>{
 let signedIn=false;const h=harness({session:true,put:()=>signedIn?{ok:true,json:async()=>({saved:true,revision:'r2'})}:lostAnswer}),c=h.context;await h.flush();
 c.labBuilderPage.ready(async()=>{});await h.flush();c.labBuilderPage.persist('name: bgp\n','a');c.labBuilderPage.persist('name: bgp\n','b');
 await h.el('map-save').onclick();await h.flush();assert.equal(h.el('map-status').textContent,'Not saved · signed out');
 const putsBefore=h.calls.filter(x=>x.method==='PUT').length,order=[];
 const real=c.sessionRetry;c.sessionRetry=async()=>{order.push('retry:'+h.calls.filter(x=>x.method==='PUT').length);return real();};
 await h.el('map-save').onclick();await h.flush();
 assert.deepEqual(order,['retry:'+putsBefore],'sessionRetry ran before the PUT');assert.equal(h.calls.filter(x=>x.method==='PUT').length,putsBefore+1);
 assert.equal(h.el('map-status').textContent,'Not saved · signed out','still signed out: the same state again');assert.equal(h.el('toast').textContent,SESSION_TOAST);
 signedIn=true;await h.el('map-save').onclick();await h.flush();
 assert.equal(h.el('map-status').textContent,'Saved in the manager');assert.equal(h.el('map-session').hidden,true);assert.match(h.el('toast').textContent,/Map saved/);
});
async function lostWithChanges(extra={}){
 let signedIn=false;const h=harness({session:true,put:()=>signedIn?{ok:true,json:async()=>({saved:true,revision:'r2'})}:lostAnswer,get:url=>url.endsWith('/topology')?(signedIn?{ok:true,json:async()=>({links:[]})}:lostAnswer):null,...extra}),c=h.context;await h.flush();
 c.labBuilderPage.ready(async()=>{});await h.flush();c.labBuilderPage.persist('name: bgp\n','a');c.labBuilderPage.persist('name: bgp\n','b');
 await h.el('map-save').onclick();await h.flush();
 return {h,c,signIn:()=>{signedIn=true;}};
}
test('while signed out the editor is not claimed to be paused: Save, Undo and Link labels stay available',async()=>{
 const {h,c}=await lostWithChanges();
 assert.equal(vm.runInContext('mapPaused',c),false);assert.equal(h.el('map-save').disabled,false);assert.equal(h.el('map-import').disabled,false);assert.equal(h.el('root').inert,false);
});
test('after signing in elsewhere, Link labels and Import map file clear the signed-out flag and send their request (not only Save)',async()=>{
 const {h,c,signIn}=await lostWithChanges();signIn();
 const before=h.calls.length;await c.mapLinkOpen();
 assert.ok(h.calls.slice(before).some(x=>x.method==='GET'&&x.url.endsWith('/topology')),'Link labels sent its request instead of answering from the guard');
 assert.equal(vm.runInContext('mapSessionLost',c),false);assert.equal(h.el('map-session').hidden,true);
 const second=await lostWithChanges();second.signIn();
 second.h.el('map-import-file').files=[{name:'m.annotations.json',text:async()=>'{"nodeAnnotations":[]}'}];
 const putsBefore=second.h.calls.filter(x=>x.method==='PUT').length;await second.c.mapImport();
 assert.equal(second.h.calls.filter(x=>x.method==='PUT').length,putsBefore+1,'Import sent its request');assert.equal(second.h.el('map-import-error').textContent,'');
});
test('signed out, then undone back to the saved map: nothing is left to keep, so the page leaves for the sign-in page',async()=>{
 const {h,c}=await lostWithChanges();
 assert.equal(h.moves.length,0);
 c.labBuilderPage.persist('name: bgp\n','a');
 assert.equal(h.moves.length,1);assert.match(h.moves[0],/^replace:\/login\?next=.*&reason=ended$/);
 assert.equal(vm.runInContext('mapSessionLost',c),false);
});
test('signed out, Undo back to the saved map with a redo left: no redirect, the sentence stays, then Redo, Save and sign-in work',async()=>{
 const {h,c,signIn}=await lostWithChanges();
 c.labBuilderPage.attach({applyAnnotations:async text=>{c.labBuilderPage.persist('name: bgp\n',text);}});
 assert.equal(vm.runInContext('mapHistory.index',c),1);
 await h.el('map-undo').onclick();
 assert.equal(vm.runInContext('mapHistory.index',c),0);assert.equal(vm.runInContext('mapDirty()',c),false);
 assert.equal(h.moves.length,0,'a redo entry is left: leaving would lose it');
 assert.equal(h.el('map-session').hidden,false);assert.equal(vm.runInContext('mapSessionLost',c),true);assert.equal(h.el('map-redo').disabled,false);
 await h.el('map-redo').onclick();
 assert.equal(vm.runInContext('mapCurrent',c),'b');assert.equal(h.el('map-save').disabled,false);assert.equal(h.moves.length,0);
 signIn();await h.el('map-save').onclick();await h.flush();
 assert.equal(h.el('map-status').textContent,'Saved in the manager');assert.equal(h.el('map-session').hidden,true);assert.equal(h.moves.length,0);
});
test('Undo back to the saved map with a redo left, then a request meets the lost session: the page stays, so the redo is kept (UI.md 3.4, 3.5)',async()=>{
 const h=harness({session:true,get:url=>url.endsWith('/topology')?lostAnswer:null}),c=h.context;await h.flush();
 c.labBuilderPage.ready(async()=>{});await h.flush();c.labBuilderPage.persist('name: bgp\n','a');c.labBuilderPage.persist('name: bgp\n','b');
 c.labBuilderPage.attach({applyAnnotations:async text=>{c.labBuilderPage.persist('name: bgp\n',text);}});
 await h.el('map-undo').onclick();
 assert.equal(vm.runInContext('mapDirty()',c),false);assert.equal(h.el('map-redo').disabled,false,'the edit can be redone');
 await c.mapLinkOpen();await h.flush();   // Link labels is the first request after the session ended
 assert.equal(h.moves.length,0,'a redo entry is left: leaving would lose it');
 assert.equal(vm.runInContext('mapSessionLost',c),true);assert.equal(h.el('map-session').hidden,false);assert.equal(h.el('map-redo').disabled,false);
});
test('a lost session is not reported as a failed save, and other refusals keep their sentence (REVIEW U11)',async()=>{
 const h=harness({session:true,put:()=>({ok:false,status:403,json:async()=>({detail:{code:'forbidden',message:'Not allowed here.'}})})}),c=h.context;await h.flush();
 c.labBuilderPage.ready(async()=>{});await h.flush();c.labBuilderPage.persist('name: bgp\n','a');c.labBuilderPage.persist('name: bgp\n','b');
 await h.el('map-save').onclick();await h.flush();assert.equal(h.el('toast').textContent,'The map was not saved: Not allowed here.');assert.equal(h.context.sessionEnded(),false);
});
test('the page loads session.js with the release number, before the page script',()=>{
 const html=read('map-editor.html');assert.match(html,/<script src="\/static\/session\.js\?v=[\d.]+" defer><\/script>/);
 assert.ok(html.indexOf('session.js')<html.indexOf('map-editor-page.js'));assert.match(html,/id="map-session"[^>]*hidden/);assert.match(html,/id="map-session-signin"[^>]*href="\/login"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);
});
