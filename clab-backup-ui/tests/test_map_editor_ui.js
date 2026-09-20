// map-editor-page.js: the pure rules of the map editor page, its save and leave behaviour over a small
// fake document, and the wiring that sends Edit map there.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const read=name=>fs.readFileSync(path.join(__dirname,'../app/static/'+name),'utf8');
function harness({hash='#lab=lab1',doc={name:'BGP lab',yaml:'name: bgp\n',annotations:'{"nodeAnnotations":[]}',revision:'r1'},put}={}){
 const elements=new Map(),calls=[],moves=[],toasts=[];
 const el=id=>{if(!elements.has(id))elements.set(id,{id,hidden:false,disabled:false,textContent:'',className:'',title:'',href:'',value:'',files:[],inert:false,open:false,onclick:null,showModal(){this.open=true;},close(){this.open=false;}});return elements.get(id);};
 const context=vm.createContext({console,URLSearchParams,Blob:class{},URL:{createObjectURL:()=>'blob:x',revokeObjectURL(){}},setTimeout:()=>0,clearTimeout(){},
  document:{getElementById:el,title:'',querySelector:()=>null,createElement:()=>({click(){},remove(){}}),body:{append(){}}},
  location:{hash,assign:u=>moves.push(u),reload:()=>moves.push('reload')},
  fetch:async(url,options={})=>{calls.push({url,method:options.method||'GET',body:options.body?JSON.parse(options.body):undefined});
   if((options.method||'GET')==='GET')return doc?{ok:true,json:async()=>doc}:{ok:false,status:409,json:async()=>({detail:'This lab has no topology file in the manager, so its map opens in the simple editor.'})};
   return put?put(JSON.parse(options.body)):{ok:true,json:async()=>({saved:true,revision:'r2'})};}});
 context.window=context;context.window.addEventListener=()=>{};
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
 for(const refused of ['addNode','editNode','deleteNode','addLink','editLink','deleteLink','setYamlContent','setLabSettings','undo','redo'])assert.ok(!new RegExp('MAP_COMMANDS[^;]*"'+refused+'"').test(adapter),refused+' must never be in the map editor\'s whitelist');
});
