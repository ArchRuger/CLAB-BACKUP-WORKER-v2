// The Progress tab is gone (owner decision D1; PROMPT 5.11, section 11 step 6). Every old address of it opens the lab's default tab
// with the header's save chip panel (a lab without a save location gets its first-save view there), a link to the save location
// opens Save settings and one to the saved versions opens All versions: once, after the lab is rendered, never again on a poll.
// The whole page is loaded as a browser loads it (every script of index.html, in order, one context), with a hash to start from.
// This file also holds the rules that keep the tab from coming back: no `progress` panel, no tab markup, no page script that
// calls an old folder route or uploads without the review.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const dir=path.join(__dirname,'../app/static'),read=name=>fs.readFileSync(path.join(dir,name),'utf8');
const html=read('index.html');
const scripts=[...html.matchAll(/<script src="\/static\/([^"?]+\.js)\?v=[^"]*" defer><\/script>/g)].map(m=>m[1]);
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
const bound={binding_id:'b',repository:{path:'/home/me/Course',prefix:'a',push_url:'https://github.com/me/course.git'},node_names:[]};
function page(hash,options={}){
 const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,fakeElement(id));return elements.get(id);};
 const storage=initial=>{const m=new Map(Object.entries(initial||{}));return {getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k)};};
 const location={hash,pathname:'/',search:'',origin:'http://manager'},urls=[];
 const history={pushState(_s,_t,url){urls.push(url);location.hash=url.includes('#')?url.slice(url.indexOf('#')):'';},replaceState(_s,_t,url){urls.push(url);location.hash=url.includes('#')?url.slice(url.indexOf('#')):'';}};
 const document={getElementById:element,querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){},removeEventListener(){},createElement:()=>fakeElement(''),body:fakeElement('body'),activeElement:null,documentElement:fakeElement('html')};
 const sandbox={document,console,URL,URLSearchParams,Date,Math,JSON,Promise,Set,Map,Error,TypeError,location,history,
  localStorage:storage(),sessionStorage:storage(options.session),navigator:{clipboard:{}},
  setTimeout:()=>0,clearTimeout(){},setInterval:()=>0,clearInterval(){},requestAnimationFrame:()=>0,
  fetch:()=>new Promise(()=>{}),
  crypto:{getRandomValues:bytes=>bytes.fill(7)},innerWidth:1440,innerHeight:900,CustomEvent:function(type){this.type=type;},
  addEventListener(){},removeEventListener(){},open(){},matchMedia:()=>({matches:false,addEventListener(){}})};
 sandbox.window=sandbox;sandbox.globalThis=sandbox;
 const context=vm.createContext(sandbox),opened=[];
 for(const name of scripts)vm.runInContext(read(name),context,{filename:name});
 // What the router opens is recorded instead of drawn (the panels and the drawer have their own tests).
 context.__opened=opened;
 vm.runInContext('saveOpenPanel=function(kind,options){__opened.push("panel:"+kind);return true;};saveDrawerOpen=function(kind,options){__opened.push("drawer:"+kind);};',context);
 const labs=options.labs||[{id:'a',name:'A',nodes:[],profiles:[],defaults:{},git_binding:bound},{id:'b',name:'B',nodes:[],profiles:[],defaults:{}}];
 context.__labs=labs;
 const run=code=>vm.runInContext(code,context);
 const start=()=>run('state={labs:__labs,jobs:[],git_jobs:[],restore_jobs:[],operations:[],design_jobs:[],platforms:{},loaded:true};routeApplied=true;applyRoute();');
 if(options.start!==false)start();
 return {context,opened,urls,location,run,start,get:name=>run(name)};
}
test('view=progress and view=git open the lab’s default tab with the save chip panel, once; the address is rewritten to that tab',()=>{
 for(const view of ['progress','git']){
  const p=page('#lab=a&view='+view);
  assert.equal(p.get('activeId'),'a');assert.equal(p.get('tab'),'topology',view+' resolves to the default tab');
  assert.deepEqual(p.opened,['panel:status'],view);
  p.run('render();render();showTab(tab);');assert.deepEqual(p.opened,['panel:status'],'never again on a poll or a re-render');
  assert.match(p.location.hash,/^#lab=a&view=topology$/,'the old address is replaced by the tab it resolves to');
  assert.equal(p.get('saveRoutePending'),null);
 }
});
test('a lab without a save location: the same chip panel opens (it shows the first-save view)',()=>{
 const p=page('#lab=b&view=progress');
 assert.equal(p.get('activeId'),'b');assert.equal(p.get('tab'),'topology');assert.deepEqual(p.opened,['panel:status']);
});
test('old sub-targets keep meaning: a link to the save location opens Save settings, one to the saved versions opens All versions',()=>{
 for(const [view,want] of [['save-location','drawer:settings'],['save-settings','drawer:settings'],['saved-versions','drawer:versions'],['versions','drawer:versions']]){
  const p=page('#lab=a&view='+view);
  assert.equal(p.get('tab'),'topology',view);assert.deepEqual(p.opened,[want],view);
  p.run('render();');assert.deepEqual(p.opened,[want]);
 }
});
test('a caller that still asks for the tab by name (showTab, selectLab, a hash change) gets the same: the default tab and the panel',()=>{
 const p=page('#lab=a&view=devices');
 assert.equal(p.get('tab'),'devices');assert.deepEqual(p.opened,[]);
 p.run("showTab('progress');");assert.equal(p.get('tab'),'topology');assert.deepEqual(p.opened,['panel:status']);
 p.run("selectLab('b','git');");assert.equal(p.get('activeId'),'b');assert.equal(p.get('tab'),'topology');assert.deepEqual(p.opened,['panel:status','panel:status']);
 p.location.hash='#lab=a&view=progress';p.run('applyRoute();');
 assert.equal(p.get('activeId'),'a');assert.deepEqual(p.opened,['panel:status','panel:status','panel:status']);
 // The same lab, asked again by the hash: opened again (a person followed the link again), still not by a poll.
 p.run('render();');assert.equal(p.opened.length,3);
});
test('a lab remembered from an older session opens as before; an unknown lab goes Home and nothing opens later for another lab',()=>{
 const p=page('',{session:{activeLab:'a'}});
 assert.equal(p.get('activeId'),'a');assert.equal(p.get('tab'),'topology');assert.deepEqual(p.opened,[],'a remembered lab alone opens no panel');
 const gone=page('#lab=zzz&view=progress');
 assert.equal(gone.get('activeId'),'');assert.deepEqual(gone.opened,[]);
 gone.run("selectLab('a');");assert.deepEqual(gone.opened,[],'the old address named another lab: nothing opens for this one');
});
test('the panel waits for the header’s scripts: a first render before they exist keeps the request, the next render opens it',()=>{
 const p=page('#lab=a&view=progress',{start:false});
 p.run('var __keep=saveOpenPanel;saveOpenPanel=undefined;');p.start();
 assert.equal(p.get('tab'),'topology');assert.notEqual(p.get('saveRoutePending'),null);
 p.run('saveOpenPanel=__keep;render();');assert.deepEqual(p.opened,['panel:status']);assert.equal(p.get('saveRoutePending'),null);
});
test('every other legacy tab name still resolves (stored links): inventory, backups, credentials, logs, design',()=>{
 for(const [view,want] of [['inventory','devices'],['backups','tools'],['credentials','advanced'],['logs','advanced'],['design','advanced'],['devices','devices'],['nonsense','topology']]){
  const p=page('#lab=a&view='+view);assert.equal(p.get('tab'),want,view);assert.deepEqual(p.opened,[],view);
 }
});
// ---- the tab does not come back ----
test('PANELS holds no progress panel, TAB_ALIAS keeps git and gains progress, and index.html has no tab button or panel of it',()=>{
 const p=page('',{start:false});
 assert.deepEqual(Array.from(p.get('PANELS')),['topology','devices','tools','advanced']);
 assert.equal(p.get('TAB_ALIAS').git,'topology');assert.equal(p.get('TAB_ALIAS').progress,'topology');
 assert.doesNotMatch(html,/id="tab-progress"|id="progress-view"|data-tab="progress"|aria-controls="progress-view"/);
 assert.deepEqual([...html.matchAll(/role="tab" id="tab-([a-z]+)"/g)].map(m=>m[1]),['topology','devices','tools','advanced']);
 assert.doesNotMatch(html,/>Progress<\/button>|under the Progress tab|Recent saves|Saved versions/);
});
test('no page script names the Progress tab or switches to it',()=>{
 for(const name of scripts){
  const text=read(name).split('\n').filter(line=>!/^\s*\/\//.test(line)).join('\n');
  assert.doesNotMatch(text,/showTab\('(progress|git)'\)|gitTabActive|gitShowRepository|renderGitProgress|#progress-view|progress-save/,name);
  assert.doesNotMatch(text,/Progress ›|under Progress|Progress tab is|the Progress tab’s|Recent saves|Save progress|Saving progress|Apply to running lab|Upload these changes|Review before uploading|Create checkpoint|Set baseline|Replacing configuration|See what's different|saved progress/,name+' still uses a word of the removed tab');
 }
});
test('no page script calls an old folder route, and gitReviewJob is the only sender of an upload (push: true, with the reviewed head)',()=>{
 const OLD=[[/\/git','PUT'/,'PUT /api/labs/{lab}/git'],[/\/git\/connect/,'POST …/git/connect'],[/\/git\/destination/,'POST …/git/destination'],[/\/folders','POST'/,'POST /api/git/repositories/{id}/folders'],[/\/tree'\)|\/tree`/,'GET /api/git/repositories/{id}/tree']];
 let senders=0;
 for(const name of scripts){
  const text=read(name);
  for(const [pattern,route] of OLD)assert.doesNotMatch(text,pattern,name+' calls the old route '+route);
  // A retry request with push: true anywhere but the one upload of gitReviewJob.
  for(const m of text.matchAll(/\/retry','POST',\{([^}]*)\}/g)){
   if(/push:\s*true/.test(m[1])){senders++;assert.equal(name,'git-progress.js');assert.match(m[1],/^push:true,reviewed:true,head:review\.head$/);}
   else assert.match(m[1],/^push:false$/,name+': a retry that is not the reviewed upload never asks for one');
  }
  assert.doesNotMatch(text,/push:\s*action===|push:\s*!0/,name);
 }
 assert.equal(senders,1,'exactly one sender of {push: true, reviewed: true, head}');
 const progress=read('git-progress.js'),at=progress.indexOf("/retry','POST',{push:true,reviewed:true,head:review.head}");
 assert.ok(at>progress.indexOf('async function gitReviewJob(')&&at<progress.indexOf('function gitDoneToast('),'inside gitReviewJob');
 // The first save and every saved request stop before an upload: `push: true` on the save route asks for the review, never uploads.
 assert.match(progress,/function gitNeedsReview\(job\)/);
});
test('D4-1 one apostrophe on the save and load surfaces: the curly one, as the chip has it (Can’t save); no word with a straight apostrophe in their text',()=>{
 for(const name of ['load.js','restore.js','git-progress.js','git-places.js','save-header.js','save-drawers.js']){
  const lines=read(name).split('\n').filter(line=>!/^\s*\/\//.test(line)).map(line=>line.replace(/\s\/\/ .*$/,''));
  const found=lines.flatMap(line=>[...line.matchAll(/[A-Za-z]\\?'(?:s|t|re|ll|ve|d)\b[^']{0,24}/g)].map(m=>m[0]));
  assert.deepEqual(found,[],name+' has a straight apostrophe in a word');
 }
 assert.match(read('load.js'),/'Can’t load'/);assert.match(read('load.js'),/title:'What’s different'/);
});
test('Use a different repository…: either choice opens the folder chooser for that repository; nothing is sent before Save here (never PUT …/git)',async()=>{
 const p=page('#lab=a&view=topology'),context=p.context,sent=[];
 const el=id=>context.document.getElementById(id);
 context.__sent=sent;context.__places={repositories:[{id:'cur',name:'Course',current:true},{id:'r2',name:'Other-Repo',remote:'https://github.com/x/o.git',branch:'main',current:false}],default:null};
 vm.runInContext(`api=async path=>({json:async()=>__places});json=async(path,method,body)=>{__sent.push(method+' '+path);return {};};
  opDialog=(id,title,markup)=>{__dialog={id,title,markup,open:true,close(){this.open=false;}};return __dialog;};var __dialog=null;opTask=async(dialog,fn)=>fn();
  saveDrawerOpen=function(kind,options){__opened.push('drawer:'+kind+':'+(options.repository||'')+(options.address?'address':''));};`,context);
 await vm.runInContext('gitSwitchRepository("a")',context);
 assert.match(p.get('__dialog').markup,/<option value="r2">Other-Repo<\/option>/);assert.doesNotMatch(p.get('__dialog').markup,/value="cur"/,'the repository the lab saves to is not offered again');
 el('git-switch-id').value='r2';await el('git-switch-choose').listeners.click();
 assert.deepEqual(p.opened,['drawer:chooser:r2']);assert.equal(p.get('__dialog').open,false);
 await vm.runInContext('gitSwitchRepository("a")',context);await el('git-switch-connect').onclick();
 assert.deepEqual(p.opened,['drawer:chooser:r2','drawer:chooser:address']);
 assert.deepEqual(sent,[],'nothing is sent by the dialog itself');
});
