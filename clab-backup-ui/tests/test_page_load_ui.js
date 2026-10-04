// The whole page, loaded as a browser loads it: every script of index.html, in the page's order, into ONE context. Classic scripts
// share one global lexical scope, so a `const`, `let`, `class` or `function` name declared at the top level of two scripts stops the
// second one from loading at all ("Identifier 'saveDrawer' has already been declared": save-drawers.js never ran in a browser while
// every per-script test passed). This file fails on that, on any script that throws while loading, and on a shared name of
// docs/git-redesign/DESIGN.md section 5 that no script defines. It also holds the seams between the page scripts that only show
// with all of them loaded.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const dir=path.join(__dirname,'../app/static');
const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');
const scripts=[...html.matchAll(/<script src="\/static\/([^"?]+\.js)\?v=[^"]*" defer><\/script>/g)].map(m=>m[1]);
// A document whose every element exists: the scripts wire their static controls at load (`$('new-lab').onclick=…`).
function fakeElement(id){
 const listeners={},el={id:id||'',hidden:false,disabled:false,value:'',textContent:'',innerHTML:'',className:'',title:'',open:false,checked:false,tabIndex:0,dataset:{},style:{},children:[],listeners,
  classList:{add(){},remove(){},toggle(){},contains:()=>false},
  addEventListener(type,fn){listeners[type]=fn;},removeEventListener(){},dispatchEvent(){return true;},
  setAttribute(){},getAttribute:()=>null,hasAttribute:()=>false,removeAttribute(){},
  querySelector:()=>null,querySelectorAll:()=>[],closest:()=>null,contains:()=>false,matches:()=>false,
  insertAdjacentHTML(){},insertAdjacentElement(){},prepend(){},after(){},before(){},replaceChildren(){},appendChild(child){return child;},
  focus(){},blur(){},click(){},close(){el.open=false;},showModal(){el.open=true;},reset(){},scrollIntoView(){},append(){},remove(){},
  getBoundingClientRect:()=>({left:100,right:200,top:0,bottom:10,width:100,height:10}),getClientRects:()=>[1]};
 el.parentElement=null;return el;
}
function loadPage(){
 const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,fakeElement(id));return elements.get(id);};
 const storage=()=>{const m=new Map();return {getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k)};};
 const timers=[];
 const document={getElementById:element,querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){},removeEventListener(){},createElement:()=>fakeElement(''),body:fakeElement('body'),activeElement:null,documentElement:fakeElement('html')};
 const sandbox={document,console,URL,URLSearchParams,Date,Math,JSON,Promise,Set,Map,Error,TypeError,
  location:{hash:'',pathname:'/',search:'',origin:'http://manager'},history:{pushState(){},replaceState(){}},
  localStorage:storage(),sessionStorage:storage(),navigator:{clipboard:{}},
  setTimeout:(fn,ms)=>{timers.push(fn);return timers.length;},clearTimeout(){},setInterval:()=>0,clearInterval(){},requestAnimationFrame:()=>0,
  fetch:async()=>({ok:true,status:200,json:async()=>({labs:[],jobs:[],git_jobs:[],platforms:{}}),headers:{get:()=>''}}),
  crypto:{getRandomValues:bytes=>bytes.fill(7)},innerWidth:1440,innerHeight:900,CustomEvent:function(type){this.type=type;},
  addEventListener(){},removeEventListener(){},open(){},matchMedia:()=>({matches:false,addEventListener(){}})};
 sandbox.window=sandbox;sandbox.globalThis=sandbox;
 const context=vm.createContext(sandbox),failures=[];
 for(const name of scripts){
  try{vm.runInContext(fs.readFileSync(path.join(dir,name),'utf8'),context,{filename:name});}
  catch(error){failures.push(name+': '+error.message);}
 }
 return {context,failures,element,elements,timers};
}
const get=(context,name)=>vm.runInContext(`typeof ${name}==='undefined'?undefined:${name}`,context);
test('index.html lists the page scripts once each, with the header, the drawers and Load among them',()=>{
 assert.ok(scripts.length>=18,scripts.join(' '));assert.equal(new Set(scripts).size,scripts.length);
 for(const name of ['status.js','shell.js','app.js','git-progress.js','save-header.js','git-places.js','save-drawers.js','load.js','restore.js'])assert.ok(scripts.includes(name),name);
});
test('every script of the page loads into one context, in the page’s order: no script throws, no top-level name is declared twice',()=>{
 const page=loadPage();
 assert.deepEqual(page.failures,[],'a script that throws while loading never runs in a browser');
});
test('a name declared at the top level of two scripts is caught by this harness (the saveDrawer collision)',()=>{
 const context=vm.createContext({});
 vm.runInContext('function saveDrawer(){}',context);
 assert.throws(()=>vm.runInContext('const saveDrawer={};',context),/already been declared/);
});
test('the names the page scripts call across files exist once the page is loaded (DESIGN.md section 5)',()=>{
 const page=loadPage(),context=page.context;
 const functions=['saveChipState','loadState','loadSourceName','loadDeviceWord','saveChangeSentence','savedVersionName','relativeTimeShort','saveProblem',
  'initPanel','openPanel','closeMenus','panelCanOpen','render','refresh','setMarkup','busyReason',
  'renderSaveHeader','saveOpenPanel','saveFinished','saveAction','saveRefused','saveStartBody',
  'gitReviewJob','gitReviewData','gitReviewCached','gitWaitingKey','gitSubmitSave','gitStartWatch','gitLoadContext','gitShowJob','gitRememberJob',
  'loadOpen','loadChoose','loadUndo','loadRetry','loadJobMarkup','loadChipView','loadRender','loadDifferentMarkup','loadCtx',
  'saveDrawerOpen','saveDrawerRender','saveDrawerClose','saveDrawerBack',
  'folderChooserMarkup','folderChooserEvent','folderClean','folderChooserModel','gitTreeModel','gitApplySource',
  'restoreShowJob','restoreReview','restoreFromVersion','restoreDiffBody','diffMarkup','gitResumeWatch','gitRunAction','gitSwitchRepository','openSaveRoute','saveUploadsText'];
 for(const name of functions)assert.equal(typeof get(context,name),'function',name+' is not defined by any script of the page');
 assert.equal(typeof get(context,'saveDrawer'),'object','save-drawers.js keeps its state under the name saveDrawer');
 assert.equal(typeof get(context,'saveHeader'),'object');
});
test('render() reaches the header, the drawer and Load on every poll, each behind a guard',()=>{
 const source=fs.readFileSync(path.join(dir,'app.js'),'utf8'),body=source.slice(source.indexOf('function render(){'),source.indexOf('function syncProxies'));
 for(const name of ['renderSaveHeader','saveDrawerRender','loadRender'])assert.match(body,new RegExp(`if\\(typeof ${name}==='function'\\)${name}\\(\\);`),name);
 // And it really runs: a render of the loaded page calls loadRender (it holds the red Load while a save runs and toasts a finished load).
 const page=loadPage(),context=page.context;let called=0;
 vm.runInContext('state={labs:[],jobs:[],git_jobs:[],restore_jobs:[],platforms:{},loaded:true};',context);
 context.__count=()=>{called++;};vm.runInContext('{const real=loadRender;loadRender=function(){__count();return real();};}',context);
 vm.runInContext('render()',context);assert.equal(called,1);
});
test('no click is handled twice and none is dropped: the save scripts take data-save-action, Load takes data-load-action',()=>{
 const page=loadPage(),context=page.context,panel=page.element('save-panel'),drawer=page.element('save-drawer');
 const seen=[];
 vm.runInContext('saveAction=function(action){__seen.push("save:"+action);};loadAction=function(action){__seen.push("load:"+action);};',Object.assign(context,{__seen:seen}));
 // save-header.js and load.js each put one listener on #save-panel; the fake element keeps only the last, so both are called by name.
 const click=(id,data)=>{const button={id,disabled:false,dataset:data,closest(selector){return (selector.includes('data-save-action')&&data.saveAction)||(selector.includes('data-load-action')&&data.loadAction)?button:null;}};
  const event={target:button};vm.runInContext('savePanelClick(__event);loadClick(__event.target.closest("[data-load-action]")?__event:{target:null});',Object.assign(context,{__event:event}));};
 click('save-upload',{saveAction:'upload'});click('load-undo',{loadAction:'undo'});
 assert.deepEqual(seen,['save:upload','load:undo']);
 assert.equal(typeof drawer.listeners.click,'function');assert.equal(typeof panel.listeners.click,'function');
});
// ---- class names (DESIGN.md 7.5): what the new scripts emit has a rule, and a shared piece has no second name ----
const css=fs.readFileSync(path.join(dir,'style.css'),'utf8');
const hasRule=name=>new RegExp('\\.'+name.replace(/-/g,'\\-')+'(?![\\w-])').test(css);
function emitted(file,from){
 let text=fs.readFileSync(path.join(dir,file),'utf8');if(from)text=text.slice(text.indexOf(from));
 const names=new Set();
 for(const m of text.matchAll(/class="([^"]*)"/g))for(const token of m[1].replace(/\$\{[^}]*\}/g,' ').split(/\s+/))if(/^[a-z][\w-]*$/.test(token))names.add(token);
 return [...names];
}
const SHARED=['save-control','save-pair','save-chip','save-dot','save-panel','save-state','save-sub','save-row','save-note','save-kv','save-foot','save-name','save-keep','save-heading','save-list','save-item','save-when','save-why','save-devices','save-end','save-drawer','save-settings','save-settings-foot'];
test('every class the header, the drawers, Load and the chooser emit has its rule in style.css; save-* names are those of DESIGN.md 7.5, the chooser adds folder-* only',()=>{
 const HOOKS=['row','folder','name','size','desc'];   // cells of the file listing, styled through .git-listing
 for(const [file,from] of [['save-header.js'],['save-drawers.js'],['load.js'],['git-places.js','// The folder chooser']]){
  for(const name of emitted(file,from)){
   if(name.startsWith('save-'))assert.ok(SHARED.includes(name),`${file} emits ${name}, which is not a name of DESIGN.md 7.5`);
   if(HOOKS.includes(name))continue;
   assert.ok(hasRule(name),`${file} emits class ${name}, and style.css has no rule for it`);
  }
 }
 for(const name of ['folder-new','folder-new-list','folder-more','folder-tree','folder-row','folder-answer'])assert.ok(hasRule(name),name);
});
test('no script of the page writes an inline style, and index.html carries none',()=>{
 assert.doesNotMatch(html,/\sstyle="/);
 for(const file of ['save-header.js','save-drawers.js','load.js','git-places.js'])assert.doesNotMatch(fs.readFileSync(path.join(dir,file),'utf8'),/style="|\.style\./,file);
});
// ---- seams that need several scripts at once ----
test('the chip names a loaded lab state from the saved-states list Load holds (DESIGN.md 7.1), else from its folder',()=>{
 const page=loadPage(),context=page.context;
 const lab={id:'lab',name:'bgp',nodes:[],git_binding:{repository:{path:'/r/Nested',prefix:'BGP',push_url:'https://github.com/x/y.git'},node_names:[]}};
 const load={id:'r1',lab_id:'lab',status:'succeeded',created:'2026-10-04T10:00:00Z',finished:'2026-10-04T10:01:00Z',source:{type:'folder',path:'BGP/final/latest',commit:'c1'},targets:[{name:'a',status:'verified'}]};
 Object.assign(context,{__lab:lab,__load:load});
 vm.runInContext('state={labs:[__lab],jobs:[],git_jobs:[],restore_jobs:[__load],operations:[],design_jobs:[],platforms:{},loaded:true};activeId="lab";',context);
 assert.equal(vm.runInContext('saveChipState(__lab,saveCtx(__lab)).text',context),'Running Final');
 vm.runInContext('loadStates.set("lab",{repository:"",repoName:"",answer:{states:[{path:"BGP/final/latest",commit:"c1",name:"Final · BGP",group:"state"}]}});',context);
 assert.equal(vm.runInContext('saveChipState(__lab,saveCtx(__lab)).text',context),'Running Final · BGP');
});
test('an upload sent through the save of another lab keeps its watch across a render, and a watch the poll started first takes its flags',()=>{
 const page=loadPage(),context=page.context;
 const lab={id:'lab',name:'bgp',nodes:[],git_binding:{repository:{path:'/r',prefix:'a'},node_names:[]}};
 Object.assign(context,{__lab:lab});
 vm.runInContext('state={labs:[__lab],jobs:[],git_jobs:[],restore_jobs:[],platforms:{},loaded:true};activeId="lab";',context);
 vm.runInContext('gitStartWatch({id:"other-job",lab_id:"other-lab",status:"queued"},{quiet:true,keep:true});renderSaveHeader();',context);
 assert.equal(vm.runInContext('gitWatch&&gitWatch.id',context),'other-job','the upload’s watch is not dropped because its save belongs to another lab');
 vm.runInContext('gitWatch=null;gitStartWatch({id:"plain",lab_id:"other-lab",status:"queued"},{quiet:true});renderSaveHeader();',context);
 assert.equal(vm.runInContext('gitWatch',context),null,'any other watch on another lab’s save still ends with the render');
 vm.runInContext('gitStartWatch({id:"mine",lab_id:"lab",status:"queued"});gitStartWatch({id:"mine",lab_id:"lab",status:"pushing"},{quiet:true,keep:true});',context);
 assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify({quiet:gitWatch.quiet,keep:gitWatch.keep})',context)),{quiet:true,keep:true});
});
test('the Load confirmation is headed by the state’s name alone, and a design export leaves the person where they are',()=>{
 const page=loadPage(),context=page.context,chosen=[];
 vm.runInContext('state={labs:[{id:"lab",name:"bgp",nodes:[]}],jobs:[],git_jobs:[],restore_jobs:[],platforms:{},loaded:true};activeId="lab";',context);
 context.__chosen=chosen;vm.runInContext('loadChoose=async function(lab,source,name){__chosen.push(name);return true;};',context);
 vm.runInContext('restoreReview("lab",{type:"folder",path:"/course/final/latest"},restoreSourceName("lab",{type:"folder",path:"/course/final/latest"},""));restoreFromVersion("lab",{type:"git",commit:"c",path:"/BGP/checkpoints/day-1"},"BGP/checkpoints/day-1");',context);
 return Promise.resolve().then(()=>new Promise(resolve=>setImmediate(resolve))).then(()=>{
  assert.deepEqual(chosen,['Final','Day-1']);
  const design=fs.readFileSync(path.join(dir,'network-design.js'),'utf8'),submit=design.slice(design.indexOf('async function designExportGitSubmit'),design.indexOf('function initDesignExportGit'));
  assert.doesNotMatch(submit,/showTab\(/,'the export ends in the chip, not on the Progress tab');assert.match(submit,/gitStartWatch\(job,\{quiet:true\}\)/);
 });
});
test('What changed names the folder a move left (the public moved_from), the top level in words',()=>{
 const page=loadPage(),context=page.context;
 const view=folder=>vm.runInContext(`drwChangesView({job:{id:'m',target:'move',status:'committed',commit:'c',lab_id:'lab',destination:{repository:'Repo',path:'new'},moved_from:${JSON.stringify(folder)}},review:null,error:'',also:new Map()}).content`,context);
 vm.runInContext('state={labs:[{id:"lab",name:"bgp",nodes:[]}],jobs:[],git_jobs:[],restore_jobs:[],platforms:{},loaded:true};activeId="lab";',context);
 assert.match(view('old/place'),/This moves the saved files of bgp from old\/place to /);
 assert.match(view(''),/from the top level to /);
 assert.doesNotMatch(vm.runInContext(`drwChangesView({job:{id:'m',target:'move',status:'committed',commit:'c',lab_id:'lab',destination:{repository:'Repo',path:'new'}},review:null,error:'',also:new Map()}).content`,context),/ from /);
});
test('a lab the VM reports as not running shows Start the lab in the Load panel also when its pill reads Needs attention',async()=>{
 const page=loadPage(),context=page.context;
 const partial={id:'r1',lab_id:'lab',status:'partial',created:'2026-10-04T10:00:00Z',finished:'2026-10-04T10:01:00Z',source:{type:'folder',path:'a/latest'},targets:[{name:'a',status:'verified'},{name:'b',status:'failed'}]};
 Object.assign(context,{__partial:partial});
 vm.runInContext('state={labs:[{id:"lab",name:"bgp",nodes:[],deployment:{status:"Not deployed"}}],jobs:[],git_jobs:[],restore_jobs:[__partial],operations:[],platforms:{},loaded:true};activeId="lab";',context);
 assert.equal(vm.runInContext('labState(current(),labContext()).key',context),'attention');
 await vm.runInContext('loadShowList("lab",false)',context);
 assert.equal(vm.runInContext('loadView.kind',context),'notrunning');
});
test('the differences of a load carry Load’s own Back: the drawer’s head shows no second one, and closing it any other way drops the review',()=>{
 const page=loadPage(),context=page.context;
 vm.runInContext('state={labs:[{id:"lab",name:"bgp",nodes:[]}],jobs:[],git_jobs:[],restore_jobs:[],platforms:{},loaded:true};activeId="lab";',context);
 vm.runInContext('saveDrawerOpen("different",{review:null})',context);
 assert.equal(vm.runInContext('saveDrawer.kind',context),'different');assert.equal(vm.runInContext('saveDrawer.back',context),null);
 assert.match(vm.runInContext('loadDifferentMarkup({labId:"lab",name:"Final",review:{source:{},targets:[]},chosen:new Set(),sending:false,error:""}).html',context),/id="load-diff-back" data-load-action="diff-back">Back</);
});
