const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const read=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8');
const IDS=['builder-yaml-panel','builder-yaml-apply','builder-yaml-revert','builder-yaml-close','builder-yaml-editor','builder-yaml-gutter','builder-yaml-status',
 'builder-yaml-count','builder-yaml-list','builder-yaml-schema','builder-yaml-keyhelp','builder-yaml-schema-failed','builder-yaml-schema-retry','builder-yaml-more'];
// Just enough of an element: the panel sets properties and handler properties, and builds list items, gutter spans and the key help with
// createElement/append/replaceChildren (textContent of a container reads its children, like the DOM's).
function element(id){const el={id,value:'',hidden:id==='builder-yaml-panel'||id==='builder-yaml-schema-failed',disabled:false,readOnly:false,className:'',scrollTop:0,scrollHeight:0,clientHeight:0,open:true,attrs:{},focused:0,selection:null,children:[],_text:'',selectionStart:0,
 get textContent(){return this.children.length?this.children.map(c=>typeof c==='string'?c:c.textContent).join(''):this._text;},
 set textContent(v){this.children=[];this._text=String(v);},
 setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return k in this.attrs?this.attrs[k]:null;},removeAttribute(k){delete this.attrs[k];},
 focus(){this.focused++;},setSelectionRange(a,b){this.selection=[a,b];},
 replaceChildren(...n){this.children=[...n];this._text='';},append(...n){this.children.push(...n);},querySelector(sel){const f=n=>{for(const c of n.children||[]){if(typeof c==='string')continue;if(sel==='button'&&c.tag==='button')return c;const r=f(c);if(r)return r;}return null;};return f(this);}};
 return el;}
// Timers run only when the test says so.
function load(extra=[]){
 const els=Object.fromEntries(IDS.map(id=>[id,element(id)])),timers=new Map();let next=1;
 const context=vm.createContext({console,Promise,document:{getElementById:id=>els[id]||null,createElement:tag=>Object.assign(element(''),{tag}),querySelector:()=>null},
  setTimeout:(fn,ms)=>{const id=next++;timers.set(id,{fn,ms});return id;},clearTimeout:id=>{timers.delete(id);}});
 for(const name of extra)vm.runInContext(read(name),context);
 vm.runInContext(read('lab-builder-yaml.js'),context);
 context.BUILDER_YAML_TEXT=vm.runInContext('BUILDER_YAML_TEXT',context);
 context.els=els;context.timers=timers;
 context.runTimers=()=>{const due=[...timers.values()];timers.clear();for(const t of due)t.fn();return due.map(t=>t.ms);};
 return context;
}
// The adapter's handle, faked: the engine keeps the text as given, like setYamlContent does.
function fakeEditor(yaml,{refuse=null,check=null,locate=null}={}){
 const listeners=new Set(),e={yaml,applied:[],checked:[],
  applyYaml(text){e.applied.push(text);if(refuse)return Promise.reject(refuse);e.yaml=text;for(const l of listeners)l(text,'');return Promise.resolve();},
  getYaml:()=>e.yaml,
  checkYaml(text){e.checked.push(text);return check?check(text):null;},
  subscribe(l){listeners.add(l);return ()=>listeners.delete(l);},
  ...(locate?{locateYaml(text){e.located.push(text);return locate(text);}}:{}),located:[],
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
 assert.match(html,/aria-describedby="builder-yaml-status builder-yaml-help builder-yaml-count"/,'the count joins the description; the example and the note stay out of it');
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
 for(const name of ['setYamlContent','applyYaml','getYaml','checkYaml','locateYaml','applyAnnotations','external-change'])assert.ok(main.includes(name),name);
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

// ---- the Problems list, the gutter marks, the count, the schema and the key help (C08 S3) ---------------------
const SCHEMA=JSON.parse(fs.readFileSync(path.join(__dirname,'../app/static/clab-schema/0.79.0.json'),'utf8'));
const isObj=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
function located(root){
 let n=0;
 const scalar=(v,line)=>({kind:'scalar',line,value:v,tag:v===null?'null':typeof v==='boolean'?'bool':typeof v==='number'?(Number.isInteger(v)?'int':'float'):'str'});
 const value=(v,keyLine)=>{if(isObj(v)&&Object.keys(v).length)return map(v,false);if(Array.isArray(v)&&v.length)return seq(v);if(Array.isArray(v))return {kind:'seq',line:keyLine,items:[]};if(isObj(v))return {kind:'map',line:keyLine,items:[]};return scalar(v,keyLine);};
 const map=(o,first)=>{const items=[];let line=0;Object.entries(o).forEach(([k,v],i)=>{const keyLine=i===0&&first?n:++n;if(i===0)line=keyLine;items.push({key:k,keyLine,value:value(v,keyLine)});});return {kind:'map',line,items};};
 const seq=a=>({kind:'seq',line:n+1,items:a.map(v=>{if(isObj(v)&&Object.keys(v).length){++n;return map(v,true);}++n;if(Array.isArray(v)&&v.length){const line=n,s=seq(v);s.line=line;return s;}return value(v,n);})});
 if(isObj(root)&&Object.keys(root).length)return map(root,false);
 return value(root,1);
}

// A lab whose text and tree agree line by line: line 7 holds the unknown key `imge`.
const BAD='name: lab\ntopology:\n  nodes:\n    a:\n      kind: arista_ceos\n      image: ceos:4.33\n      imge: x\n';
const BAD_DOC={name:'lab',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',imge:'x'}}}};
const GOOD='name: lab\ntopology:\n  nodes:\n    a:\n      kind: arista_ceos\n      image: ceos:4.33\n';
const GOOD_DOC={name:'lab',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33'}}}};
const DOCS=new Map([[BAD,BAD_DOC],[GOOD,GOOD_DOC]]);
// Known texts have their hand-made tree; a text that starts a broken flow sequence is a parse error; any other text (a comment added) is the plain lab.
const locateFrom=docs=>text=>docs.has(text)?{tree:located(docs.get(text))}:text.startsWith('a: [')?{error:{message:'Flow sequence must end with a ]',line:2,severity:'error'}}:{tree:located(GOOD_DOC)};
function loadCheck(opts={}){
 const c=load(['lab-builder-check.js']),fetched=[];
 c.fetch=opts.fetch||(async url=>{fetched.push(url);return {ok:true,json:async()=>SCHEMA};});c.fetched=fetched;
 // The VM runs the vendored version unless a test says otherwise, so unknown keys are errors.
 if(opts.vm!==null)c.builderYamlContext({containerlab:opts.vm||'0.79.0'});
 return c;
}
const settle=()=>new Promise(r=>setImmediate(r));
const items=c=>c.els['builder-yaml-list'].children;
const itemText=li=>li.textContent;
function openWith(c,yaml,editorOpts={}){
 const e=fakeEditor(yaml,{locate:locateFrom(DOCS),...editorOpts});c.builderYamlPanelInit({editor:e});c.builderYamlPanelToggle(true);return e;
}
test('the markup adds the Problems section: one status count, the fixed note, the example as a sibling of the help outside every describedby target',()=>{
 const c=load(),html=c.builderYamlPanelMarkup();
 for(const id of ['builder-yaml-problems','builder-yaml-problems-title','builder-yaml-count','builder-yaml-problems-note','builder-yaml-list','builder-yaml-schema','builder-yaml-keyhelp','builder-yaml-more','builder-yaml-schema-retry'])assert.match(html,new RegExp(`id="${id}"`),id);
 assert.match(html,/id="builder-yaml-count" role="status" aria-live="polite"/);
 assert.equal((html.match(/role="status"/g)||[]).length,2,'the status line and the count only');
 assert.match(html,/<p[^>]*id="builder-yaml-problems-note">These do not stop Apply or Save; containerlab refuses errors when the lab is deployed\.<\/p>/);
 assert.match(html,/id="builder-yaml-keyhelp"[^>]*aria-live="off"/);
 const help=html.indexOf('id="builder-yaml-help"'),helpEnd=html.indexOf('</p>',help),example=html.indexOf('<details class="builder-yaml-example"');
 assert.ok(help>0&&example>helpEnd,'the example comes after the help paragraph closed: a sibling, never inside it');
 assert.ok(example<html.indexOf('id="builder-yaml-editor"'));
 assert.match(html,/<summary>Boot order: start the router after the switch is healthy \(stages\)<\/summary>/);
 assert.match(html,/wait for <code>create-links<\/code> instead/);assert.match(html,/the images are this course’s, use your own/);
 for(const line of ['stage: healthy','- node: vsw','kind: juniper_vjunosrouter'])assert.ok(html.includes(line),line);
 assert.doesNotMatch(html,/style=/);assert.doesNotMatch(html,/class="builder-yaml-example-actions"><button/,'no Copy button without clipboard.js');
 // The textarea's description is exactly the status line, the help and the count.
 const described=/aria-describedby="([^"]+)"/.exec(html)[1].split(' ');assert.deepEqual(described,['builder-yaml-status','builder-yaml-help','builder-yaml-count']);
 const inside=id=>{const at=html.indexOf(`id="${id}"`),open=html.lastIndexOf('<',at),tag=/^<(\w+)/.exec(html.slice(open))[1],end=html.indexOf(`</${tag}>`,at);return html.slice(open,end);};
 for(const id of described)assert.ok(!inside(id).includes('builder-yaml-example'),id+' does not contain the example');
});
test('the example has a Copy button only when clipboard.js defined copyButton',()=>{
 const c=load();vm.runInContext("function copyButton(value,what,target,visible){return '<button type=\"button\" class=\"copy\" data-copy=\"'+value.length+'\">'+visible+'</button>';}",c);
 assert.match(c.builderYamlPanelMarkup(),/<div class="builder-yaml-example-actions"><button type="button" class="copy" data-copy="\d+">Copy example<\/button><\/div>/);
 const copy=vm.runInContext('BUILDER_YAML_EXAMPLE',c);assert.match(copy,/^name: juniper-pair\n/);assert.ok(copy.endsWith('\n'));
});
test('the gutter keeps one number per text line in span markup, and marks the lines with findings',async()=>{
 const c=loadCheck(),e=openWith(c,BAD);
 const gutter=c.els['builder-yaml-gutter'];
 assert.equal(gutter.textContent,'1\n2\n3\n4\n5\n6\n7\n8','one number per text line');
 assert.ok(gutter.children.filter(n=>typeof n!=='string').every(n=>n.className.startsWith('builder-yaml-line')));
 await settle();
 const mark=gutter.children.find(n=>typeof n!=='string'&&n.textContent==='7');
 assert.equal(mark.className,'builder-yaml-line is-error');assert.match(mark.attrs.title,/`imge` is not a device setting/);
 assert.equal(gutter.children.filter(n=>typeof n!=='string'&&/is-/.test(n.className)).length,1);
 // The next keystroke clears every mark at once, before any new check ran.
 type(c,BAD+'# x\n');assert.equal(gutter.children.filter(n=>typeof n!=='string'&&/is-/.test(n.className)).length,0);assert.equal(gutter.textContent,'1\n2\n3\n4\n5\n6\n7\n8\n9');
 // So does a canvas edit (builderYamlSet).
 c.runTimers();await settle();assert.equal(gutter.children.filter(n=>typeof n!=='string'&&/is-/.test(n.className)).length,0,'no tree for that text: no marks');
 e.canvas(BAD);await settle();c.runTimers();await settle();
 assert.equal(gutter.children.filter(n=>typeof n!=='string'&&/is-error/.test(n.className)).length,0,'a dirty panel is not refreshed by the canvas');
});
test('a validation with a tree lists the findings with severity word, line and data-line; the status line is not touched by the list',async()=>{
 const c=loadCheck(),e=openWith(c,GOOD);await settle();
 assert.equal(items(c).length,0);assert.equal(c.els['builder-yaml-count'].textContent,'No problems found');
 c.els['builder-yaml-status'].textContent='kept';
 type(c,BAD);assert.equal(c.builderYamlPanelState().status,'Edited · not applied');
 assert.deepEqual(c.runTimers(),[400],'one timer for the status line and the list');await settle();
 assert.equal(items(c).length,1);
 const li=items(c)[0],button=li.children[0];
 assert.equal(li.className,'is-error');assert.equal(button.className,'builder-yaml-problem');assert.equal(button.attrs['data-line'],'7');assert.equal(button.attrs.type,'button');
 assert.match(itemText(li),/^Error Line 7: `imge` is not a device setting containerlab 0\.79\.0 knows\. Did you mean `image`\?$/);
 assert.equal(c.els['builder-yaml-count'].textContent,'1 error');
 assert.equal(c.els['builder-yaml-editor'].attrs['aria-invalid'],'true','an error in the list');
 assert.ok(e.checked.includes(BAD),'the parser answered once for the status line and the list together');assert.equal(e.checked.filter(t=>t===BAD).length,1);
 // Clicking the item puts the caret on the key with nothing selected; an Apply refusal still selects the line.
 const box=c.els['builder-yaml-editor'];
 c.els['builder-yaml-list'].onclick({target:{closest:sel=>{assert.equal(sel,'button[data-line]');return button;}}});
 const at=BAD.indexOf('      imge')+6;assert.deepEqual(box.selection,[at,at]);assert.ok(box.focused>0);
 c.els['builder-yaml-list'].onclick({target:{closest:()=>null}});assert.deepEqual(box.selection,[at,at],'a click beside a button does nothing');
 c.builderYamlGoto(7);assert.deepEqual(box.selection,[BAD.indexOf('      imge'),BAD.indexOf('      imge')+'      imge: x'.length]);
});
test('the count is written once per change of the summary, and says what was not checked',async()=>{
 const c=loadCheck(),writes=[],e=openWith(c,GOOD);await settle();
 const count=c.els['builder-yaml-count'];let text=count.textContent;Object.defineProperty(count,'textContent',{get:()=>text,set:v=>{writes.push(v);text=v;}});
 for(let i=0;i<3;i++){type(c,GOOD+`# ${i}\n`);c.runTimers();await settle();}
 assert.deepEqual(writes,[],'the same summary: no write, so the live region stays quiet');
 type(c,BAD);c.runTimers();await settle();assert.deepEqual(writes,['1 error']);
 // No tree (a parse error): the list is empty and the count says nothing was checked.
 e.checkYaml=()=>({message:'Flow sequence must end with a ]',line:2,severity:'error'});type(c,'a: [\n');c.runTimers();await settle();
 assert.equal(items(c).length,0);assert.equal(text,'Not checked: fix the error above first');assert.equal(c.builderYamlPanelState().tone,'error');
});
test('No problems found is written only after a run on a tree',async()=>{
 const c=loadCheck(),e=fakeEditor(GOOD,{locate:locateFrom(DOCS)});c.builderYamlPanelInit({editor:e});
 assert.equal(c.els['builder-yaml-count'].textContent,'','closed and not run: nothing');
 c.builderYamlPanelToggle(true);assert.match(c.els['builder-yaml-count'].textContent,/^No problems found/);
 const noTree=fakeEditor(GOOD);const d=loadCheck();d.builderYamlPanelInit({editor:noTree});d.builderYamlPanelToggle(true);assert.equal(d.els['builder-yaml-count'].textContent,'','no locateYaml: never No problems found');
});
test('while the schema loads the count carries (settings not checked yet), then the full result replaces it',async()=>{
 let release;const gate=new Promise(r=>{release=r;});
 const c=loadCheck({fetch:async()=>{await gate;return {ok:true,json:async()=>SCHEMA};}});
 const e=openWith(c,BAD);
 assert.equal(c.els['builder-yaml-count'].textContent,'No problems found (settings not checked yet)','the schema-free rules found nothing yet');
 assert.equal(items(c).length,0);
 release();await settle();await settle();
 assert.equal(c.els['builder-yaml-count'].textContent,'1 error');assert.equal(items(c).length,1,'the load re-ran the list');
});
test('the schema is fetched once, from the same origin, with the release marker of the page’s script tag',async()=>{
 const c=loadCheck(),urls=[];c.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>SCHEMA};};
 c.document.querySelector=sel=>sel==='script[src*="lab-builder-check.js"]'?{getAttribute:()=>'/static/lab-builder-check.js?v=9.9.9'}:null;
 const e=openWith(c,GOOD);await settle();type(c,GOOD+'# a\n');c.runTimers();await settle();type(c,BAD);c.runTimers();await settle();
 assert.deepEqual(urls,['/static/clab-schema/0.79.0.json?v=9.9.9']);
});
test('the caption names the schema: exact when the VM version matches, a warning otherwise; the context upgrade re-draws without a reload',async()=>{
 const c=loadCheck({vm:null});openWith(c,BAD);await settle();
 assert.match(c.els['builder-yaml-schema'].textContent,/^The VM’s containerlab version is not known yet/);
 assert.equal(items(c)[0].className,'is-warning','unknown VM version: the unknown key is a warning');
 c.builderYamlContext({containerlab:'0.79.0'});
 assert.equal(c.els['builder-yaml-schema'].textContent,'Checked against containerlab 0.79.0, the version on this VM.');
 assert.equal(items(c)[0].className,'is-error','exact: the same text now reads as an error');
 c.builderYamlContext({containerlab:'0.81.0'});assert.match(c.els['builder-yaml-schema'].textContent,/this VM runs 0\.81\.0/);assert.equal(items(c)[0].className,'is-warning');
 c.builderYamlContext(null);assert.match(c.els['builder-yaml-schema'].textContent,/not known yet/);
});
test('a failed schema fetch shows the one sentence with Try again; links and boot order are still checked',async()=>{
 let ok=false;const c=loadCheck({fetch:async()=>ok?{ok:true,json:async()=>SCHEMA}:{ok:false,json:async()=>({})},fetched:[]});
 openWith(c,BAD);await settle();await settle();
 assert.equal(c.els['builder-yaml-schema-failed'].hidden,false);
 assert.match(c.builderYamlPanelMarkup(),/The topology schema could not be loaded from the manager, so settings and kinds are not checked; links and boot order still are\./);
 assert.equal(items(c).length,0,'the settings rule needs the schema');
 ok=true;c.els['builder-yaml-schema-retry'].onclick();await settle();await settle();
 assert.equal(c.els['builder-yaml-schema-failed'].hidden,true);assert.equal(items(c).length,1);
});
test('the problems list is empty and the sentence absent without the check script: the panel is the old panel',()=>{
 const c=load(),e=fakeEditor(GOOD,{locate:locateFrom(DOCS)});c.builderYamlPanelInit({editor:e});c.builderYamlPanelToggle(true);
 assert.equal(c.els['builder-yaml-count'].textContent,'');assert.equal(items(c).length,0);
});
test('with a tree, an unknown endpoint is a list error and the status line stays Edited; without a tree the old warning is the status line',async()=>{
 const warn=()=>({message:'The link endpoint zz is not a device',line:6,severity:'warning'});
 const DOC={name:'lab',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33'}},links:[{endpoints:['a:eth1','zz:eth1']}]}};
 const TEXT=GOOD+'  links:\n    - endpoints: ["a:eth1", "zz:eth1"]\n';
 const c=loadCheck(),e=openWith(c,GOOD,{check:warn,locate:locateFrom(new Map([[GOOD,GOOD_DOC],[TEXT,DOC]]))});
 type(c,TEXT);c.runTimers();await settle();
 const s=c.builderYamlPanelState();assert.equal(s.status,'Edited · not applied');assert.equal(s.tone,'');
 assert.ok(items(c).some(li=>/zz/.test(itemText(li))&&li.className==='is-error'),'link-node is an error in the list');
 const d=loadCheck(),f=fakeEditor(GOOD,{check:warn});d.builderYamlPanelInit({editor:f});d.builderYamlPanelToggle(true);
 type(d,GOOD+'zz\n');d.runTimers();const t=d.builderYamlPanelState();assert.equal(t.tone,'warn');assert.match(t.status,/^Line 6: The link endpoint zz/,'the old claim without a tree');
});
test('a blocking error empties the list and the count never says No problems found beside it',async()=>{
 const c=loadCheck(),e=openWith(c,BAD);await settle();assert.equal(items(c).length,1);
 e.checkYaml=()=>({message:'Flow sequence must end with a ]',line:2,severity:'error'});
 type(c,'a: [\n');c.runTimers();await settle();
 assert.equal(items(c).length,0);assert.equal(c.els['builder-yaml-count'].textContent,'Not checked: fix the error above first');
 assert.equal(c.els['builder-yaml-editor'].attrs['aria-invalid'],'true');
 assert.equal(c.builderYamlPanelState().status,'Line 2: Flow sequence must end with a ]');
});
test('the list check runs on set, open, Revert and Apply without touching the status line, and not while the panel is closed',async()=>{
 const c=loadCheck(),e=fakeEditor(BAD,{locate:locateFrom(DOCS)});c.builderYamlPanelInit({editor:e});
 assert.deepEqual(e.located,[],'closed: nothing is parsed');
 c.builderYamlPanelToggle(true);assert.equal(e.located.length,1,'open');assert.equal(c.builderYamlPanelState().status,'');
 e.canvas(GOOD);assert.equal(c.runTimers().length,1,'a canvas edit schedules the list');await settle();assert.equal(items(c).length,0);assert.equal(c.builderYamlPanelState().status,'');
 type(c,BAD);c.builderYamlRevert();assert.equal(items(c).length,0,'Revert draws the engine text’s list');assert.equal(c.builderYamlPanelState().status,c.BUILDER_YAML_TEXT.reverted);
});
test('Apply goes through with errors listed and says how many remain; newer edits win the sentence',async()=>{
 const c=loadCheck(),e=openWith(c,GOOD);await settle();
 type(c,BAD);assert.equal(await c.builderYamlApply(),true);
 assert.deepEqual(e.applied,[BAD],'the engine was asked despite the error');
 let s=c.builderYamlPanelState();assert.equal(s.status,'Applied · 1 error remains (see Problems)');assert.equal(s.tone,'warn');
 const two={name:'lab',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',imge:'x',imgx:'y'}}}},TWO=BAD+'      imgx: y\n';
 DOCS.set(TWO,two);type(c,TWO);await c.builderYamlApply();s=c.builderYamlPanelState();assert.equal(s.status,'Applied · 2 errors remain (see Problems)');
 // The status is not left behind when the canvas moves a clean panel on.
 e.canvas(GOOD);assert.equal(c.builderYamlPanelState().status,'');
 // Newer edits typed while an apply runs: today’s sentence wins.
 let release;e.applyYaml=text=>{e.applied.push(text);return new Promise(r=>{release=()=>{e.yaml=text;r();};});};
 type(c,BAD);const run=c.builderYamlApply();await settle();type(c,BAD+'# more\n');release();await run;assert.equal(c.builderYamlPanelState().status,'Applied · newer edits not applied');
 DOCS.delete(TWO);
});
test('the key help follows the caret: description and a containerlab.dev link, cleared when the text and the tree disagree',async()=>{
 const c=loadCheck(),e=openWith(c,GOOD);await settle();
 const box=c.els['builder-yaml-editor'],help=c.els['builder-yaml-keyhelp'];
 box.selectionStart=GOOD.indexOf('      image')+8;box.onkeyup();assert.equal(c.timers.size,1,'throttled');box.onclick();assert.equal(c.timers.size,1);
 assert.deepEqual(c.runTimers(),[150]);
 assert.match(help.textContent,/^image · .+More about image$/);
 const link=help.children.find(n=>typeof n!=='string'&&n.tag==='a');assert.equal(link.attrs.target,'_blank');assert.equal(link.attrs.rel,'noopener');assert.match(link.attrs.href,/^https:\/\/containerlab\.dev\//);
 // A line without a key, and a text that moved on since the tree was made.
 box.selectionStart=0;box.value=GOOD;box.selectionStart=GOOD.indexOf('topology')-1;c.builderYamlKeyHelpNow();assert.notEqual(help.textContent,'','the name line has help');
 box.selectionStart=GOOD.length;c.builderYamlKeyHelpNow();assert.equal(help.textContent,'','no key on the last empty line');
 box.value=GOOD.replace('image: ceos:4.33','image: other:1');box.selectionStart=box.value.indexOf('      image')+8;c.builderYamlKeyHelpNow();assert.equal(help.textContent,'','the tree is behind the text');
 // No schema, no help.
 const d=loadCheck({fetch:async()=>({ok:false})});openWith(d,GOOD);await settle();d.els['builder-yaml-editor'].selectionStart=GOOD.indexOf('      image')+8;d.builderYamlKeyHelpNow();assert.equal(d.els['builder-yaml-keyhelp'].textContent,'');
});
test('the disclosure is open on a wide window and closed at 900 px and below',()=>{
 const c=load();c.matchMedia=q=>({matches:q==='(max-width: 900px)',addEventListener(){}});
 c.builderYamlPanelInit({editor:fakeEditor(GOOD)});assert.equal(c.els['builder-yaml-more'].open,false);
 c.matchMedia=()=>({matches:false});c.builderYamlLayout();assert.equal(c.els['builder-yaml-more'].open,true);
});
test('the stylesheet gives the text box 160 px, one block per state and no inline style anywhere in the markup',()=>{
 const css=read('lab-builder.css');
 assert.match(css,/\.builder-yaml-body\{[^}]*min-height:160px/);
 assert.match(css,/\.builder-yaml-line\.is-error/);assert.match(css,/\.builder-yaml-list\{[^}]*overflow:auto/);
 assert.match(css,/\.lab-builder #root svg\{max-width:none\}/);
});

test('redrawing the Problems list keeps keyboard focus on the same item (by line and code), or on the list when that item is gone',async()=>{
 const c=loadCheck(),e=openWith(c,BAD);await settle();
 const ol=c.els['builder-yaml-list'],first=items(c)[0].children[0];
 assert.equal(first.attrs['data-code'],'unknown-key');
 c.document.activeElement=first;
 c.builderYamlCheckList();
 const again=items(c)[0].children[0];
 assert.notEqual(again,first,'the list was rebuilt');assert.equal(again.focused,1,'focus moved to the same item in the new list');assert.equal(ol.focused,0);
 // Focus elsewhere is left alone.
 c.document.activeElement=c.els['builder-yaml-editor'];c.builderYamlCheckList();
 assert.equal(items(c)[0].children[0].focused,0);assert.equal(ol.focused,0);
 // The focused item is gone after a fix: focus lands on the list container, which can take it.
 c.document.activeElement=items(c)[0].children[0];
 type(c,GOOD);c.runTimers();await settle();
 assert.equal(items(c).length,0);assert.equal(ol.focused,1);assert.equal(ol.attrs.tabindex,'-1');
 // Focus on the list itself stays on it.
 c.document.activeElement=ol;c.builderYamlCheckList();assert.equal(ol.focused,2);
});
test('the Problems list keeps at least three items visible; the panel scrolls for the rest',()=>{
 const css=read('lab-builder.css');
 const list=/\.builder-yaml-list\{([^}]*)\}/.exec(css)[1];
 const min=/min-height:(\d+)px/.exec(list);assert.ok(min&&Number(min[1])>=78,'a minimum of three items (about 26px each)');
 assert.doesNotMatch(/\.builder-yaml-problems\{([^}]*)\}/.exec(css)[1],/max-height/,'the section no longer squeezes the list');
 assert.match(css,/\.builder-yaml-panel\{overflow-y:auto\}/);
});

// ---- C08 review fixes ----------------------------------------------------------------------------------------
test('a limit of locateYaml is a warning-toned "Not checked" in the count, never a blocking error',async()=>{
 const c=loadCheck(),limit={message:'The topology is nested more than 64 levels deep',line:1,severity:'error'};
 const e=openWith(c,GOOD,{locate:t=>t===GOOD?{tree:located(GOOD_DOC)}:{error:limit}});await settle();
 type(c,GOOD+'# more\n');c.runTimers();await settle();
 const count=c.els['builder-yaml-count'];
 assert.equal(count.textContent,'Not checked: The topology is nested more than 64 levels deep');
 assert.match(count.className,/\bis-warn\b/,'warning tone');
 assert.notEqual(c.builderYamlPanelState().tone,'error','the status line stays calm');assert.equal(c.builderYamlPanelState().status,'Edited · not applied');
 assert.equal(c.els['builder-yaml-editor'].attrs['aria-invalid'],'false');
 assert.equal(c.els['builder-yaml-schema'].textContent,'','nothing was checked, so no caption');
 // A text that locates again clears the tone.
 type(c,GOOD);c.runTimers();await settle();assert.equal(count.className,'');assert.match(count.textContent,/^No problems found/);
});
test('the caption and the status line follow what ran: no tree, no locateYaml or a throwing check says nothing about a check',async()=>{
 const warn={message:'a link names an unknown device',line:5,severity:'warning'};
 const noLocate=loadCheck(),e1=fakeEditor(GOOD,{check:()=>warn});noLocate.builderYamlPanelInit({editor:e1});noLocate.builderYamlPanelToggle(true);
 assert.equal(noLocate.els['builder-yaml-schema'].textContent,'','no locateYaml: no caption');
 type(noLocate,GOOD+'# x\n');noLocate.runTimers();await settle();
 assert.match(noLocate.builderYamlPanelState().status,/a link names an unknown device/,'no list check ran: the checkYaml warning stays visible');
 const boom=loadCheck(),e2=openWith(boom,GOOD,{check:()=>warn});await settle();
 assert.match(boom.els['builder-yaml-schema'].textContent,/^Checked against containerlab 0\.79\.0/);
 vm.runInContext("builderCheck=function(){throw new Error('x');}",boom);
 type(boom,GOOD+'# y\n');boom.runTimers();await settle();
 assert.equal(boom.els['builder-yaml-schema'].textContent,'','the check threw: no caption');
 assert.match(boom.builderYamlPanelState().status,/a link names an unknown device/,'the warning is not hidden when the list did not run');
 const fine=loadCheck(),e3=openWith(fine,GOOD,{check:()=>warn});await settle();type(fine,GOOD+'# z\n');fine.runTimers();await settle();
 assert.equal(fine.builderYamlPanelState().status,'Edited · not applied','the list ran: the list carries the warning');
});
test('the gutter title follows a new message of the same length on the same line',()=>{
 const c=load();
 c.builderYamlMarks([{line:3,severity:'error',message:'aaaa'}]);const sig=()=>vm.runInContext('builderYaml.markSig',c),first=sig();
 c.builderYamlMarks([{line:3,severity:'error',message:'bbbb'}]);
 assert.notEqual(sig(),first);
});
