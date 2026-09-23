const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const read=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8');
const IDS=['builder-yaml-panel','builder-yaml-apply','builder-yaml-revert','builder-yaml-close','builder-yaml-editor','builder-yaml-gutter','builder-yaml-status'];
// Just enough of an element: the panel sets properties and handler properties only.
function element(id){return {id,value:'',textContent:'',hidden:id==='builder-yaml-panel',disabled:false,readOnly:false,className:'',scrollTop:0,attrs:{},focused:0,selection:null,
 setAttribute(k,v){this.attrs[k]=String(v);},focus(){this.focused++;},setSelectionRange(a,b){this.selection=[a,b];}};}
// Timers run only when the test says so.
function load(){
 const els=Object.fromEntries(IDS.map(id=>[id,element(id)])),timers=new Map();let next=1;
 const context=vm.createContext({console,Promise,document:{getElementById:id=>els[id]||null},
  setTimeout:(fn,ms)=>{const id=next++;timers.set(id,{fn,ms});return id;},clearTimeout:id=>{timers.delete(id);}});
 vm.runInContext(read('lab-builder-yaml.js'),context);
 context.BUILDER_YAML_TEXT=vm.runInContext('BUILDER_YAML_TEXT',context);
 context.els=els;context.timers=timers;
 context.runTimers=()=>{const due=[...timers.values()];timers.clear();for(const t of due)t.fn();return due.map(t=>t.ms);};
 return context;
}
// The adapter's handle, faked: the engine keeps the text as given, like setYamlContent does.
function fakeEditor(yaml,{refuse=null,check=null}={}){
 const listeners=new Set(),e={yaml,applied:[],checked:[],
  applyYaml(text){e.applied.push(text);if(refuse)return Promise.reject(refuse);e.yaml=text;for(const l of listeners)l(text,'');return Promise.resolve();},
  getYaml:()=>e.yaml,
  checkYaml(text){e.checked.push(text);return check?check(text):null;},
  subscribe(l){listeners.add(l);return ()=>listeners.delete(l);},
  // A visual edit on the canvas: the engine settles, the page stores, the panel hears.
  canvas(text){e.yaml=text;for(const l of listeners)l(text,'{}');},
  get listeners(){return listeners.size;}};
 return e;
}
const type=(c,text)=>{c.els['builder-yaml-editor'].value=text;c.els['builder-yaml-editor'].oninput();};
const key=(target,init)=>{const e={ctrlKey:false,metaKey:false,prevented:false,stopped:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},...init};target.onkeydown(e);return e;};
const START='name: lab\ntopology:\n  nodes:\n    a:\n      kind: linux\n';

test('the panel markup has the ids the page and the adapter contract name',()=>{
 const c=load(),html=c.builderYamlPanelMarkup();
 assert.match(html,/^<aside id="builder-yaml-panel" class="builder-yaml-panel" hidden /);
 for(const id of IDS)assert.match(html,new RegExp(`id="${id}"`),id);
 assert.match(html,/<textarea id="builder-yaml-editor"[^>]* spellcheck="false" wrap="off"/);
 assert.match(html,/id="builder-yaml-status" class="builder-yaml-status" role="status"/);
 assert.match(html,/aria-describedby="builder-yaml-status builder-yaml-help"/);
 assert.match(html,/id="builder-yaml-gutter" aria-hidden="true"/);
 assert.match(html,/>Topology YAML</);assert.match(html,/>Apply</);assert.match(html,/>Revert</);
 assert.doesNotMatch(html,/style=/,'no inline styles');assert.doesNotMatch(html,/ on[a-z]+=/,'no inline handlers');
});
test('the file loads without a document and keeps its names off the page script',()=>{
 const context=vm.createContext({console});vm.runInContext(read('lab-builder-yaml.js'),context);
 assert.equal(typeof context.builderYamlPanelInit,'function');assert.equal(context.builderYamlPanelToggle(true),false);
 const page=read('lab-builder-page.js');for(const name of ['builderYamlPanelMarkup','builderYamlPanelInit','builderYamlPanelToggle','builderYamlPanelState','builderYaml'])assert.doesNotMatch(page,new RegExp(`(function|const|let) ${name}\\b`),name);
});
test('init shows the engine text, numbers its lines and subscribes',()=>{
 const c=load(),e=fakeEditor(START),s=c.builderYamlPanelInit({editor:e,getDraftYaml:()=>'stale'});
 assert.equal(s.text,START);assert.equal(s.dirty,false);assert.equal(s.ready,true);assert.equal(e.listeners,1);
 assert.equal(c.els['builder-yaml-gutter'].textContent,'1\n2\n3\n4\n5\n6');
 assert.equal(c.els['builder-yaml-apply'].disabled,true,'nothing to apply yet');assert.equal(c.els['builder-yaml-revert'].disabled,true);
 // A second init (the editor attaching again) drops the first subscription.
 const other=fakeEditor(START);c.builderYamlPanelInit({editor:other});assert.equal(e.listeners,0);assert.equal(other.listeners,1);
});
test('without an editor the panel shows the draft read-only',()=>{
 const c=load(),s=c.builderYamlPanelInit({editor:null,getDraftYaml:()=>START});
 assert.equal(s.text,START);assert.equal(s.ready,false);assert.equal(c.els['builder-yaml-editor'].readOnly,true);assert.equal(s.status,c.BUILDER_YAML_TEXT.notReady);
 return c.builderYamlApply().then(ok=>assert.equal(ok,false));
});
test('typing marks the panel dirty and Apply sends the whole text as one step',async()=>{
 const c=load(),e=fakeEditor(START);let applied=null;c.builderYamlPanelInit({editor:e,onApplied:t=>{applied=t;}});
 const edited=START+'    b:\n      kind: linux\n';type(c,edited);
 let s=c.builderYamlPanelState();assert.equal(s.dirty,true);assert.equal(s.status,'Edited · not applied');assert.equal(c.els['builder-yaml-apply'].disabled,false);assert.equal(c.els['builder-yaml-revert'].disabled,false);
 assert.equal(c.els['builder-yaml-gutter'].textContent.split('\n').length,8);
 assert.equal(await c.builderYamlApply(),true);
 assert.deepEqual(e.applied,[edited]);assert.equal(applied,edited);
 s=c.builderYamlPanelState();assert.equal(s.dirty,false);assert.equal(s.status,'Applied');assert.equal(s.tone,'ok');assert.equal(s.canvasChanged,false);assert.equal(s.base,edited);
 assert.equal(c.els['builder-yaml-status'].className,'builder-yaml-status is-ok');
 // Apply with nothing edited asks the engine nothing.
 assert.equal(await c.builderYamlApply(),false);assert.equal(e.applied.length,1);assert.equal(c.builderYamlPanelState().status,'Nothing to apply');
});
test('a refused text stays in the panel with the reason and the caret on its line',async()=>{
 const refusal=Object.assign(new Error('Line 3: topology.nodes must be a mapping of device names.'),{code:'yaml',line:3});
 const c=load(),e=fakeEditor(START,{refuse:refusal});c.builderYamlPanelInit({editor:e});
 const bad='name: lab\ntopology:\n  nodes: [a]\n';type(c,bad);
 assert.equal(await c.builderYamlApply(),false);
 const s=c.builderYamlPanelState();assert.equal(s.text,bad);assert.equal(s.dirty,true);assert.equal(s.tone,'error');assert.equal(s.status,refusal.message);assert.equal(s.base,START);
 assert.equal(e.yaml,START,'the engine text is untouched');assert.equal(c.els['builder-yaml-editor'].attrs['aria-invalid'],'true');
 assert.deepEqual(c.els['builder-yaml-editor'].selection,[bad.indexOf('  nodes'),bad.indexOf('  nodes')+'  nodes: [a]'.length]);
 assert.equal(c.els['builder-yaml-apply'].disabled,false,'the student can correct and apply again');
});
test('Revert loads the engine text and clears the edits',()=>{
 const c=load(),e=fakeEditor(START);c.builderYamlPanelInit({editor:e});type(c,'garbage: [');
 c.els['builder-yaml-revert'].onclick();
 const s=c.builderYamlPanelState();assert.equal(s.text,START);assert.equal(s.dirty,false);assert.equal(s.status,c.BUILDER_YAML_TEXT.reverted);assert.equal(c.els['builder-yaml-revert'].disabled,true);
});
test('a canvas edit refreshes a clean panel and never overwrites the student’s text',()=>{
 const c=load(),e=fakeEditor(START);c.builderYamlPanelInit({editor:e});
 const moved=START+'    c:\n      kind: linux\n';e.canvas(moved);
 assert.equal(c.builderYamlPanelState().text,moved,'clean: the panel follows the canvas');
 const mine=moved+'# mine\n';type(c,mine);
 const later=moved+'    d:\n      kind: linux\n';e.canvas(later);
 let s=c.builderYamlPanelState();assert.equal(s.text,mine);assert.equal(s.canvasChanged,true);assert.equal(s.status,'Canvas changed · Revert to load it');assert.equal(s.tone,'warn');
 c.builderYamlRevert();s=c.builderYamlPanelState();assert.equal(s.text,later);assert.equal(s.canvasChanged,false);
 // Typed back to the old text while the canvas moved on: nothing of the student's is left, the canvas text loads.
 type(c,later+'x');e.canvas(START);type(c,later);s=c.builderYamlPanelState();assert.equal(s.text,START);assert.equal(s.dirty,false);assert.equal(s.canvasChanged,false);
});
test('the engine echoing the applied text does not count as a canvas change',async()=>{
 const c=load(),e=fakeEditor(START);c.builderYamlPanelInit({editor:e});type(c,START+'# x\n');
 await c.builderYamlApply();const s=c.builderYamlPanelState();assert.equal(s.canvasChanged,false);assert.equal(s.status,'Applied');
});
test('typing while an apply runs keeps the newer text dirty',async()=>{
 const c=load(),e=fakeEditor(START);let release;e.applyYaml=text=>{e.applied.push(text);return new Promise(r=>{release=()=>{e.yaml=text;r();};});};
 c.builderYamlPanelInit({editor:e});type(c,START+'# one\n');const run=c.builderYamlApply();
 assert.equal(c.builderYamlPanelState().applying,true);assert.equal(c.els['builder-yaml-apply'].disabled,true);
 assert.equal(await c.builderYamlApply(),false,'one apply at a time');
 type(c,START+'# one\n# two\n');release();await run;
 const s=c.builderYamlPanelState();assert.equal(s.dirty,true);assert.equal(s.status,'Applied · newer edits not applied');assert.equal(s.base,START+'# one\n');
});
test('live validation waits 400 ms, asks the parser only and shows line and severity',()=>{
 const c=load(),e=fakeEditor(START,{check:t=>t.includes('[')?{message:'Flow sequence must end with a ]',line:2,severity:'error'}:t.includes('zz')?{message:'The link endpoint zz is not a device',line:6,severity:'warning'}:null});
 c.builderYamlPanelInit({editor:e});
 type(c,'a: [');type(c,'a: [\n');assert.equal(c.timers.size,1,'debounced');assert.deepEqual(e.checked,[]);
 assert.deepEqual(c.runTimers(),[400]);assert.deepEqual(e.checked,['a: [\n']);assert.deepEqual(e.applied,[],'no engine call');
 let s=c.builderYamlPanelState();assert.equal(s.status,'Line 2: Flow sequence must end with a ]');assert.equal(s.tone,'error');
 type(c,START+'zz\n');c.runTimers();s=c.builderYamlPanelState();assert.equal(s.tone,'warn');assert.match(s.status,/^Line 6: The link endpoint zz/);
 type(c,START+'# fine\n');c.runTimers();s=c.builderYamlPanelState();assert.equal(s.status,'Edited · not applied');assert.equal(s.tone,'');
 // Back to the engine text: no timer, nothing to check.
 type(c,START);assert.equal(c.timers.size,0);
});
test('Ctrl+Enter applies; other keys do not',async()=>{
 const c=load(),e=fakeEditor(START);c.builderYamlPanelInit({editor:e});type(c,START+'# k\n');
 const box=c.els['builder-yaml-editor'];
 assert.equal(key(box,{key:'Enter'}).prevented,false);assert.deepEqual(e.applied,[]);
 const ev=key(box,{key:'Enter',ctrlKey:true});assert.equal(ev.prevented,true);
 await new Promise(r=>setImmediate(r));assert.deepEqual(e.applied,[START+'# k\n']);
 type(c,START+'# m\n');key(box,{key:'Enter',metaKey:true});await new Promise(r=>setImmediate(r));assert.equal(e.applied.length,2);
});
test('Escape closes a clean panel only; the close button hides and keeps the edits',()=>{
 const c=load(),e=fakeEditor(START),panel=c.els['builder-yaml-panel'];c.builderYamlPanelInit({editor:e});
 assert.equal(c.builderYamlPanelToggle(),true);assert.equal(panel.hidden,false);assert.ok(c.els['builder-yaml-editor'].focused>0);
 const esc=key(panel,{key:'Escape'});assert.equal(esc.prevented,true);assert.equal(panel.hidden,true);
 c.builderYamlPanelToggle(true);type(c,START+'# keep\n');key(panel,{key:'Escape'});
 assert.equal(panel.hidden,false,'dirty: Escape does not close');assert.equal(c.builderYamlPanelState().status,c.BUILDER_YAML_TEXT.closeDirty);
 c.els['builder-yaml-close'].onclick();assert.equal(panel.hidden,true);
 e.canvas(START+'# canvas\n');
 assert.equal(c.builderYamlPanelToggle(true),true);assert.equal(c.builderYamlPanelState().text,START+'# keep\n','reopening keeps the unapplied text');
 c.builderYamlRevert();c.builderYamlPanelToggle(false);e.yaml=START+'# newer\n';c.builderYamlPanelToggle(true);
 assert.equal(c.builderYamlPanelState().text,START+'# newer\n','a clean panel reloads the engine text on opening');
});
test('YAML text with markup goes into the text box as text, never as HTML',()=>{
 const c=load(),evil='name: "<script>alert(1)</script>"\ntopology: {}\n',e=fakeEditor(evil,{refuse:new Error('Line 1: <b>bold</b> & "q"')});
 c.builderYamlPanelInit({editor:e});assert.equal(c.els['builder-yaml-editor'].value,evil);
 type(c,evil+'# <img src=x>\n');return c.builderYamlApply().then(()=>{
  assert.equal(c.els['builder-yaml-status'].textContent,'Line 1: <b>bold</b> & "q"','the message is set as text');
  assert.equal(c.els['builder-yaml-status'].innerHTML,undefined,'the panel never writes innerHTML');
  assert.doesNotMatch(read('lab-builder-yaml.js'),/innerHTML|insertAdjacentHTML|outerHTML/);
 });
});
test('the committed editor bundle carries the YAML handle and the engine command',()=>{
 const dir=path.join(__dirname,'../app/static/lab-builder/assets'),main=fs.readFileSync(path.join(dir,'main.js'),'utf8');
 for(const name of ['setYamlContent','applyYaml','getYaml','checkYaml','applyAnnotations','external-change'])assert.ok(main.includes(name),name);
 const source=fs.readFileSync(path.join(__dirname,'../lab-builder/src/main.tsx'),'utf8');
 assert.match(source,/command: "setYamlContent", payload: \{ content: text \} \}/,'setYamlContent keeps the engine history (no skipHistory)');
 assert.match(source,/if \(!mapOnly && page\.attach\) page\.attach\(\{\s*applyYaml/,'the YAML handle is for the builder, never the map editor');
 assert.match(source,/disabledTabIds: \["yaml", "json"\]/,'the editor’s own YAML tab stays off');
});
test('every open and close reaches the page, the panel’s own close button and Escape included',()=>{
 const c=load(),e=fakeEditor(START),seen=[];c.builderYamlPanelInit({editor:e,onToggle:open=>seen.push(open)});
 c.builderYamlPanelToggle();c.els['builder-yaml-close'].onclick();c.builderYamlPanelToggle(true);key(c.els['builder-yaml-panel'],{key:'Escape'});
 assert.deepEqual(seen,[true,false,true,false]);
});
