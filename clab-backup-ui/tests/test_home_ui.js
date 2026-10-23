// home.js: the Home page cards, the single-lab rule, escaping, the Start reason and the count of labs found on the VM.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const NOW=Date.parse('2026-09-16T12:00:00Z');
function harness(state,{opened={},quick,tab}={}){
 const elements=new Map(),calls={selectLab:[],openLabOperations:[],json:[],deploy:0};
 const element=id=>{if(!elements.has(id))elements.set(id,{id,hidden:false,disabled:false,innerHTML:'',textContent:'',listeners:{},attrs:{},classes:new Set(),addEventListener(name,fn){this.listeners[name]=fn;},setAttribute(n,v){this.attrs[n]=String(v);},classList:{toggle:(name,on)=>{const e=elements.get(id);if(on)e.classes.add(name);else e.classes.delete(name);}},focus(){calls.focus=id;}});return elements.get(id);};
 const tabStore={value:tab||''};
 const context=vm.createContext({$:element,esc,console,state:{labs:[],jobs:[],loaded:true,...state},current:()=>undefined,busy:()=>false,
  setMarkup(el,html){if(el._markup===html)return false;el.innerHTML=html;el._markup=html;return true;},
  openedAt:id=>opened[id]||'',homeTab:()=>tabStore.value||'recent',rememberHomeTab:v=>{tabStore.value=v;return true;},Date:class extends Date{static now(){return NOW;}},
  selectLab(id,view){calls.selectLab.push([id,view]);},openLabOperations(id){calls.openLabOperations.push(id);},openDeploy(){calls.deploy++;},
  json:async(...args)=>{calls.json.push(args);return {};},refresh:async()=>{},notify(){}});
 if(quick)context.opQuickActions=quick;
 for(const file of ['status.js','home.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/'+file),'utf8'),context);
 return {context,element,calls,tabStore,created:id=>elements.has(id)};
}
const running={id:'run',name:'BGP core',favorite:false,nodes:[{name:'r1',ssh_ready:true},{name:'r2',ssh_ready:true}],deployment:{status:'Running'},nos_readiness:{status:'ready',total:2,ready:2},git_binding:{binding_id:'b',repository:{push_url:'https://github.com/x/y'}},vm_project_path:'/labs/bgp.clab.yaml'};
const stopped={id:'stop',name:'OSPF area 0',favorite:true,nodes:[{name:'s1'},{name:'s2'},{name:'s3'}],deployment:{status:'Not deployed'},vm_project_path:'/labs/ospf.clab.yaml'};
const saved=[{id:'g1',lab_id:'run',status:'synced',target:'latest',created:'2026-09-16T11:48:00Z',finished:'2026-09-16T11:48:30Z'}];

test('cards read the lab state, the ready count, the last save and the deployment in student words; All labs keeps favourites first',()=>{
 const h=harness({labs:[{...running,last_deployed:'2026-09-16T10:00:00Z'},stopped],git_jobs:saved,discovery:{connected:true}},{opened:{run:'2026-09-16T09:00:00Z'},tab:'all'});
 h.context.renderHome();
 const cards=h.element('lab-cards').innerHTML;
 assert.equal(h.element('lab-cards').hidden,false);assert.equal(h.element('home-labs').hidden,false);assert.equal(h.created('home-continue'),false,'no separate Continue block outranks the two starting choices');
 assert.ok(cards.indexOf('OSPF area 0')<cards.indexOf('BGP core'),'favourites come first under All labs');
 assert.match(cards,/class="pill ok">Running<\/span><span>2 of 2 devices ready/);
 assert.match(cards,/Saved 12 min ago/,'the card reads the header chip’s own text (saveChipState, PROMPT 5.2: one status function)');assert.match(cards,/<p class="caption lab-card-times">Deployed 2 hours ago · Last opened 3 hours ago<\/p>/);
 assert.match(cards,/<p class="caption lab-card-times">No deployment recorded by this manager<\/p>/,'a lab without a recorded deployment says so and shows no time');
 assert.match(cards,/class="pill neutral">Stopped<\/span><span>Not running/);assert.match(cards,/Not saved yet/);
 assert.match(cards,/data-lab="run">Open lab/);assert.match(cards,/data-lab="stop">Open lab/);
 assert.match(cards,/data-lab-favorite="stop" aria-pressed="true" aria-label="Remove from favourites"/);
 assert.match(cards,/data-lab-favorite="run" aria-pressed="false" aria-label="Add to favourites"/);
 // the favourite glyph is a class="icon-button" wrapping <use href="#i-star">: style.css keys the
 // filled-vs-outline look off this exact shape (.icon-button[aria-pressed="true"] use[href="#i-star"]),
 // so both the class and the glyph reference must survive together, in both pressed states.
 assert.match(cards,/<button type="button" class="icon-button" data-lab-favorite="stop" aria-pressed="true"[^>]*><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-star"><\/use><\/svg><\/button>/);
 assert.match(cards,/<button type="button" class="icon-button" data-lab-favorite="run" aria-pressed="false"[^>]*><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-star"><\/use><\/svg><\/button>/);
 assert.match(cards,/data-lab-more="run" aria-label="More actions for BGP core"/);
 assert.doesNotMatch(cards,/container|discover|NOS|worker|Unlinked/i);assert.doesNotMatch(cards,/Continue where you left off/);
 const attention=harness({labs:[{...running,id:'att',name:'Att'}],git_jobs:[{id:'g2',lab_id:'att',status:'push_pending',target:'latest',captured:true,commit:'c2',pushed:false,created:'2026-09-16T11:50:00Z'}]});
 attention.context.renderHome();assert.match(attention.element('lab-cards').innerHTML,/Upload failed/,'a failed upload reads as the chip reads it');
 // A save waiting for upload and a loaded state read as the chip reads them (parity C-080).
 const waiting=harness({labs:[{...running,id:'w',name:'W'}],git_jobs:[{id:'g3',lab_id:'w',status:'review_pending',target:'latest',captured:true,commit:'c3',pushed:false,created:'2026-09-16T11:50:00Z'}]});
 waiting.context.renderHome();assert.match(waiting.element('lab-cards').innerHTML,/1 save to upload/);
 const loaded=harness({labs:[{...running,id:'l',name:'L'}],git_jobs:[],restore_jobs:[{id:'r1',lab_id:'l',status:'succeeded',created:'2026-09-16T11:40:00Z',finished:'2026-09-16T11:41:00Z',source:{type:'folder',path:'course/final/latest'},targets:[{name:'a',status:'verified'}]}]});
 loaded.context.renderHome();assert.match(loaded.element('lab-cards').innerHTML,/Running Final/);
});

test('Recent labs orders by the most recent deployment, newest first; opening, saving and favourites do not reorder it; labs without a deployment come last by name',()=>{
 const lab=(id,name,last_deployed,extra={})=>({...stopped,id,name,favorite:false,last_deployed,...extra});
 const labs=[lab('a','Alpha',''),lab('z','Zulu','2026-09-10T08:00:00Z'),lab('m','Mike','2026-09-15T08:00:00Z',{favorite:true}),lab('b','Bravo',undefined),lab('k','Kilo','2026-09-15T08:00:00Z')];
 const names=(h,t)=>Array.from(h.context.homeOrder(labs,t),l=>l.name);
 const h=harness({labs},{opened:{a:'2026-09-16T11:59:00Z'}});
 assert.deepEqual(names(h,'recent'),['Kilo','Mike','Zulu','Alpha','Bravo'],'newest deployment first, equal times by name, undated labs last by name');
 assert.deepEqual(names(h,'all'),['Mike','Alpha','Bravo','Kilo','Zulu']);
 h.context.renderHome();const cards=h.element('lab-cards').innerHTML,order=['Kilo','Mike','Zulu','Alpha','Bravo'].map(n=>cards.indexOf('<h3>'+n+'</h3>'));
 assert.deepEqual(order,[...order].sort((x,y)=>x-y),'Recent labs is the default tab');assert.ok(order.every(i=>i>=0));
 assert.equal(h.element('home-tab-note').textContent,'Most recently deployed first. Labs this manager has not deployed come last, by name.');
 assert.equal(h.element('home-tab-recent').attrs['aria-selected'],'true');assert.equal(h.element('home-tab-all').attrs['aria-selected'],'false');assert.ok(h.element('home-tab-recent').classes.has('active'));
 // the most recently OPENED lab (Alpha) and a git save do not move anything
 const saved2=harness({labs,git_jobs:[{id:'g',lab_id:'b',status:'synced',target:'latest',created:'2026-09-16T11:59:00Z',finished:'2026-09-16T11:59:30Z'}]});
 assert.deepEqual(names(saved2,'recent'),['Kilo','Mike','Zulu','Alpha','Bravo']);
 assert.deepEqual(labs.map(l=>l.name),['Alpha','Zulu','Mike','Bravo','Kilo'],'the state itself is never reordered');
});

test('the tab is the student\'s choice: it survives polls and coming back to Home, and only real changes redraw the list',()=>{
 const h=harness({labs:[running,stopped]});h.context.renderHome();
 h.element('home-tabs').listeners.click({target:{closest:sel=>sel==='[data-home-tab]'?{dataset:{homeTab:'all'}}:null}});
 assert.equal(h.tabStore.value,'all','kept for the browser session');assert.equal(h.element('home-tab-all').attrs['aria-selected'],'true');assert.equal(h.element('home-tab-recent').attrs.tabindex,'-1');
 assert.equal(h.element('home-tab-note').textContent,'Favourites first, then by name.');assert.equal(h.element('lab-cards').attrs['aria-labelledby'],'home-tab-all');
 const before=h.element('lab-cards').innerHTML;
 for(let poll=0;poll<3;poll++)h.context.renderHome();
 assert.equal(h.element('home-tab-all').attrs['aria-selected'],'true','a poll does not reset the tab');assert.equal(h.element('lab-cards')._markup,before,'unchanged markup is not reassigned on the next poll');
 const back=harness({labs:[running,stopped]},{tab:'all'});back.context.renderHome();assert.equal(back.element('home-tab-all').attrs['aria-selected'],'true','a new visit to Home in the same session opens the same tab');
 const odd=harness({labs:[running]},{tab:'nonsense'});odd.context.renderHome();assert.equal(odd.element('home-tab-recent').attrs['aria-selected'],'true');
 // keyboard: arrows move between the tabs and the focus follows
 let prevented=0;h.element('home-tabs').listeners.keydown({key:'ArrowLeft',preventDefault(){prevented++;}});
 assert.equal(h.tabStore.value,'recent');assert.equal(h.calls.focus,'home-tab-recent');assert.equal(prevented,1);
 h.element('home-tabs').listeners.keydown({key:'a',preventDefault(){prevented++;}});assert.equal(prevented,1);
 // one lab, or none: the list is an ordinary list, the starting choices stay
 const single=harness({labs:[running],git_jobs:saved});single.context.renderHome();
 assert.equal(single.element('lab-cards').hidden,false);assert.match(single.element('lab-cards').innerHTML,/<h3>BGP core<\/h3>/);
 const none=harness({labs:[]});none.context.renderHome();
 assert.equal(none.element('home-labs').hidden,true);assert.equal(none.element('lab-cards').hidden,true);assert.equal(none.element('home-start').hidden,false,'Deploy and Build lead the page without any lab too');
});

test('lab names and ids are escaped everywhere they are interpolated',()=>{
 const hostile={...running,id:'x"y',name:'<script>alert(1)</script> & "quoted"'};
 const h=harness({labs:[hostile,stopped]});h.context.renderHome();
 const cards=h.element('lab-cards').innerHTML;
 assert.doesNotMatch(cards,/<script>/);assert.match(cards,/&lt;script&gt;alert\(1\)&lt;\/script&gt; &amp; &quot;quoted&quot;/);
 assert.match(cards,/data-lab="x&quot;y"/);assert.match(cards,/aria-label="More actions for &lt;script&gt;/);
});

test('Start shows on labs that are not running, with the reason as visible text when it is unavailable',()=>{
 const blocked=harness({labs:[running,stopped],discovery:{connected:false}},{quick:(lab,discovery)=>({startAction:'deploy',canStart:false,canDestroy:false,reason:'Connect the VM first'})});
 blocked.context.renderHome();const cards=blocked.element('lab-cards').innerHTML;
 assert.match(cards,/data-lab-start="stop" disabled title="Connect the VM first">Start lab<\/button><small class="caption">Connect the VM first<\/small>/);
 assert.doesNotMatch(cards,/data-lab-start="run"/,'a running lab has no Start button');
 const ready=harness({labs:[stopped],discovery:{connected:true}},{quick:()=>({startAction:'start',canStart:true,canDestroy:true,reason:''})});
 ready.context.renderHome();assert.match(ready.element('lab-cards').innerHTML,/data-lab-start="stop" >Start stopped devices<\/button>/);
 assert.doesNotMatch(ready.element('lab-cards').innerHTML,/<small class="caption">/,'no reason line when Start is available');
 const legacy=harness({labs:[stopped],discovery:{connected:false}},{quick:()=>({startAction:'deploy',canStart:false,canDestroy:false})});
 legacy.context.renderHome();assert.match(legacy.element('lab-cards').innerHTML,/title="Connect the VM first"/,'a reason is computed when opQuickActions does not give one');
 const noOps=harness({labs:[stopped]});noOps.context.renderHome();assert.doesNotMatch(noOps.element('lab-cards').innerHTML,/data-lab-start/,'no operations module, no Start button');
});

test('labs the VM has that are not in My labs, and hidden ones, are counted for Manager › Labs found on the VM and never drawn on Home',()=>{
 const h=harness({labs:[running,stopped],discovery:{discovered:[{name:'extra',imported:false}]}});h.context.renderHome();
 assert.equal(h.created('home-discovered'),false,'Home no longer has a discovered section');assert.equal(h.element('home-skeleton').hidden,true);
 const count=d=>JSON.parse(vm.runInContext('JSON.stringify(homeVmLabs('+JSON.stringify(d)+'))',h.context));
 assert.deepEqual(count({discovered:[{name:'extra',imported:false}]}),{waiting:1,hidden:0,note:'1 not in My labs'});
 assert.deepEqual(count({discovered:[{name:'run',imported:true}],ignored_labs:[]}),{waiting:0,hidden:0,note:''});
 assert.deepEqual(count({discovered:[],ignored_labs:['old']}),{waiting:0,hidden:1,note:'1 hidden'},'hidden labs stay reachable even with zero labs');
 assert.deepEqual(count({discovered:[{name:'gone',imported:false,excluded:true}],ignored_labs:['gone']}),{waiting:0,hidden:1,note:'1 hidden'},'an excluded discovery is listed as hidden, not as waiting');
 assert.deepEqual(count({discovered:[{name:'a'},{name:'b'}],ignored_labs:['c']}).note,'2 not in My labs · 1 hidden');
 assert.deepEqual(count(undefined),{waiting:0,hidden:0,note:''});
 const loading=harness({labs:[],loaded:false,discovery:{discovered:[{name:'extra',imported:false}]}});loading.context.renderHome();
 assert.equal(loading.element('home-skeleton').hidden,false);
});

test('a lab hidden from Home is not drawn, is counted as hidden with the ways back, and Home still lists the others',()=>{
 const h=harness({labs:[{...running,hidden:true},stopped],discovery:{connected:true}},{tab:'all'});
 h.context.renderHome();
 const cards=h.element('lab-cards').innerHTML;
 assert.doesNotMatch(cards,/BGP core/,'the hidden lab has no card');assert.match(cards,/OSPF area 0/,'the other lab keeps its card');
 assert.equal(h.element('home-labs').hidden,false);
 assert.equal(h.element('home-hidden-note').hidden,false);
 assert.equal(h.element('home-hidden-note').textContent,'1 lab is hidden from Home. Show it again under Manager ▾ › Labs found on the VM…, or add it again from Choose a file on the lab VM….');
 const count=(d,labs)=>JSON.parse(vm.runInContext('JSON.stringify(homeVmLabs('+JSON.stringify(d)+','+JSON.stringify(labs)+'))',h.context));
 assert.deepEqual(count({discovered:[],ignored_labs:['old']},[{id:'x',hidden:true},{id:'y'}]),{waiting:0,hidden:2,note:'2 hidden'},'removed-and-excluded labs and labs hidden from Home are counted together');
 assert.deepEqual(count({discovered:[]},[{id:'y'}]),{waiting:0,hidden:0,note:''});
 const all=harness({labs:[{...running,hidden:true},{...stopped,hidden:true}],discovery:{connected:true}});all.context.renderHome();
 assert.equal(all.element('home-labs').hidden,true,'with every lab hidden the list is gone');
 assert.equal(all.element('home-hidden-note').textContent.slice(0,27),'2 labs are hidden from Home');
 const none=harness({labs:[running,stopped],discovery:{connected:true}});none.context.renderHome();
 assert.equal(none.element('home-hidden-note').hidden,true);assert.equal(none.element('home-hidden-note').textContent,'');
 const loading=harness({labs:[{...running,hidden:true}],loaded:false});loading.context.renderHome();
 assert.equal(loading.element('home-hidden-note').hidden,true,'no note before the state is known');
});

test('card actions are delegated: Open lab selects, Start selects then starts, the star toggles the favourite, ⋯ opens lab operations',async()=>{
 const h=harness({labs:[running,stopped],discovery:{connected:true}},{quick:()=>({startAction:'deploy',canStart:true,canDestroy:false,reason:''})});
 const click=h.element('home').listeners.click;
 let started=0;h.element('lab-start').onclick=()=>started++;
 const target=(attrs,disabled=false)=>({closest:sel=>{const key=sel.slice(1,-1).replace(/^data-/,'').replace(/-([a-z])/g,(m,c)=>c.toUpperCase());return key in attrs?{dataset:attrs,disabled}:null;}});
 await click({target:target({lab:'run'})});assert.deepEqual(h.calls.selectLab,[['run',undefined]]);
 await click({target:target({labStart:'stop'})});assert.deepEqual(h.calls.selectLab[1],['stop',undefined]);assert.equal(started,1);
 await click({target:target({labStart:'stop'},true)});assert.equal(started,1,'a disabled Start does nothing');
 await click({target:target({labMore:'stop'})});assert.deepEqual(h.calls.openLabOperations,['stop']);
 await click({target:target({labFavorite:'stop'})});assert.equal(JSON.stringify(h.calls.json[0]),JSON.stringify(['/labs/stop/operations-settings','PUT',{favorite:false}]));
 h.element('home').listeners.contextmenu({target:{closest:()=>({dataset:{labId:'run'}})},preventDefault(){}});assert.deepEqual(h.calls.openLabOperations,['stop','run']);
 h.element('home-deploy').onclick();assert.equal(h.calls.deploy,1);
 let uploads=0;h.context.opUpload=()=>{uploads++;};h.element('home-upload').onclick();assert.equal(uploads,1,'Upload a file from this computer opens the upload, not the VM browser');assert.equal(h.calls.deploy,1);
});

test('Home leads with two equal starting choices: Deploy (a file on the lab VM, or one from this computer) and Build',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8'),home=html.slice(html.indexOf('<section id="home"'),html.indexOf('<div id="lab-content"'));
 const start=home.indexOf('id="home-start"'),cards=home.indexOf('id="lab-cards"'),tabs=home.indexOf('id="home-tabs"');
 assert.ok(start>0&&start<tabs&&tabs<cards,'the two choices come before the tabs and the lab list');assert.doesNotMatch(home,/home-continue/);
 assert.match(home,/id="home-tab-recent" class="active" data-home-tab="recent" aria-selected="true" aria-controls="lab-cards" tabindex="0">Recent labs<\/button>/);assert.match(home,/data-home-tab="all" aria-selected="false" aria-controls="lab-cards" tabindex="-1">All labs<\/button>/);
 assert.equal((home.match(/<article class="start-card"/g)||[]).length,2);
 assert.match(home,/<h2 id="home-start-deploy">Deploy<\/h2>[^]*?id="home-deploy">Choose a file on the lab VM…<\/button><button type="button" class="button secondary" id="home-upload">Upload a file from this computer…<\/button>/);
 assert.match(home,/<h2 id="home-start-build">Build<\/h2>[^]*?<a class="button primary" id="home-build" href="\/static\/lab-builder\.html">Open the lab builder<\/a>/,'Build opens the builder itself, not a deployment dialog');
 assert.match(home,/On the lab VM: browse the lab folders that are already there\. From this computer: the file is shown to you, then copied to the lab VM when you confirm\./);
 assert.doesNotMatch(home,/id="deploy-empty"|id="build-empty"|id="home-actions"/,'the empty page has no second set of the same buttons');
 const loading=harness({labs:[],loaded:false});loading.context.renderHome();assert.equal(loading.element('home-start').hidden,true,'nothing is offered before the state is known');
 const many=harness({labs:[running,stopped]});many.context.renderHome();assert.equal(many.element('home-start').hidden,false);
});

// C09 S2: the Home lab filter (docs/parity-campaign/C09-DESIGN.md section 4). The markup is S1's (index.html); the harness
// supplies the ids it must carry: home-filter-row, home-filter (value), home-filter-clear, home-filter-count, home-filter-empty,
// home-filter-live.
function filterHarness(labs,opts={}){
 const h=harness({labs,...(opts.state||{})},opts);
 const timers=[];let active=null;
 h.context.document={get activeElement(){return active;}};
 h.context.setTimeout=(fn,ms)=>{timers.push({fn,ms,live:true});return timers.length;};
 h.context.clearTimeout=id=>{if(timers[id-1])timers[id-1].live=false;};
 const row=h.element('home-filter-row'),field=h.element('home-filter'),clear=h.element('home-filter-clear');
 field.value='';field.focus=()=>{active=field;};clear.focus=()=>{active=clear;};
 row.contains=el=>el===field||el===clear;
 h.element('home-filter-live').textContent='';
 const type=text=>{field.value=text;field.oninput();};
 const fire=()=>{for(const t of timers.splice(0))if(t.live)t.fn();};
 return {...h,field,clear,row,timers,type,fire,setActive:el=>{active=el;},active:()=>active,};
}
const labOf=(id,name,extra={})=>({...stopped,id,name,favorite:false,nodes:[{name:'clab-x-r1',short_name:'r1'},{name:'clab-x-sw9',short_name:'sw9'}],...extra});
const cardNames=h=>[...h.element('lab-cards').innerHTML.matchAll(/<h3>([^<]*)<\/h3>/g)].map(m=>m[1]);

test('C09: the filter narrows by name (substring, any case, trimmed), keeps the tab order and counts what it shows',()=>{
 const labs=[labOf('a','BGP core',{deployment:{status:'Running'}}),labOf('b','OSPF area 0'),labOf('c','Bgp edge')];
 const h=filterHarness(labs,{tab:'all'});
 h.context.renderHome();assert.deepEqual(cardNames(h),['BGP core','Bgp edge','OSPF area 0']);assert.equal(h.element('home-filter-count').textContent,'');assert.equal(h.clear.hidden,true);
 h.type('  bgp ');
 assert.deepEqual(cardNames(h),['BGP core','Bgp edge'],'substring, case-insensitive, trimmed; the All labs order is kept');
 assert.equal(h.element('home-filter-count').textContent,'2 of 3 labs');assert.equal(h.clear.hidden,false);assert.equal(h.element('home-filter-empty').hidden,true);assert.equal(h.element('lab-cards').hidden,false);
 h.type('');assert.deepEqual(cardNames(h),['BGP core','Bgp edge','OSPF area 0']);assert.equal(h.element('home-filter-count').textContent,'');
});

test('C09: the state word matches by whole label only; a device short name matches by substring and the card says why',()=>{
 const running=labOf('r','Alpha',{deployment:{status:'Running'},nodes:[{name:'clab-a-r1',short_name:'r1',ssh_ready:true}],nos_readiness:{status:'ready',total:1,ready:1}});
 const q={nodes:[{name:'q',short_name:'q'}]},unlinked=labOf('u','Beta',{...q,deployment:{status:'Unlinked'}}),partial=labOf('p','Gamma',{deployment:{status:'Partially running'},nodes:[{name:'a',runtime_state:'running'},{name:'b',runtime_state:'exited'}]}),idle=labOf('s','Delta',q);
 const h=filterHarness([running,unlinked,partial,idle],{tab:'all'});
 h.context.renderHome();
 h.type('running');assert.deepEqual(cardNames(h),['Alpha'],'running is the whole word: not "Not matched to a running lab", not "Some devices stopped"');
 h.type('RUNNING ');assert.deepEqual(cardNames(h),['Alpha']);
 h.type('stopped');assert.deepEqual(cardNames(h),['Delta'],'stopped matches the Stopped lab and not Some devices stopped');
 h.type('not matched');assert.deepEqual(cardNames(h),[],'part of a longer state label is not a state match');
 h.type('R1');assert.deepEqual(cardNames(h),['Alpha'],'a device short name');
 assert.match(h.element('lab-cards').innerHTML,/<p class="caption lab-card-match">has device r1<\/p>/);
 h.type('alp');assert.deepEqual(cardNames(h),['Alpha']);assert.doesNotMatch(h.element('lab-cards').innerHTML,/has device/,'a name match needs no explanation');
 h.type('running');assert.doesNotMatch(h.element('lab-cards').innerHTML,/has device/,'nor does a state match');
 const hostile=filterHarness([labOf('x','X',{nodes:[{name:'n',short_name:'<b>"r"</b>'}]})]);hostile.context.renderHome();hostile.type('<b>');
 assert.match(hostile.element('lab-cards').innerHTML,/has device &lt;b&gt;&quot;r&quot;&lt;\/b&gt;/,'the device name is escaped');
});

test('C09: no match hides the cards, shows the visible sentence with the term and keeps Clear; hidden labs stay out whatever the term',()=>{
 const h=filterHarness([labOf('a','Alpha'),labOf('b','Beta'),labOf('h','Hidden one',{hidden:true})]);
 h.context.renderHome();h.type('zzz & <i>');
 assert.equal(h.element('lab-cards').hidden,true);assert.equal(h.element('home-labs').hidden,false,'the row and the sentence stay while the cards are hidden');
 assert.equal(h.element('home-filter-empty').hidden,false);assert.equal(h.element('home-filter-empty').textContent,'No lab matches “zzz & <i>”. Try part of a lab name, a state such as Running, or a device name.','textContent: the term needs no escaping');
 assert.equal(h.element('home-filter-empty').attrs.role,undefined,'the visible sentence is not a live region');assert.equal(h.element('home-filter-count').textContent,'0 of 2 labs');assert.equal(h.clear.hidden,false);
 h.type('hidden');assert.deepEqual(cardNames(h),[],'a hidden lab never matches');
 h.type('');assert.equal(h.element('home-filter-empty').hidden,true);assert.equal(h.element('home-filter-empty').textContent,'');assert.deepEqual(cardNames(h).sort(),['Alpha','Beta']);
});

test('C09: the one live region is written once, 500 ms after the last input, never by the poll, and carries no term',()=>{
 const labs=[labOf('a','Alpha'),labOf('b','Beta'),labOf('c','Alpine')];
 const h=filterHarness(labs),live=()=>h.element('home-filter-live').textContent;
 h.context.renderHome();h.type('a');h.type('al');h.type('alp');
 assert.equal(live(),'','nothing is announced per keystroke');assert.equal(h.timers.filter(t=>t.live).length,1,'one pending timer: each keystroke cancels the previous');assert.equal(h.timers.find(t=>t.live).ms,500);
 h.context.renderHome();h.context.renderHome();assert.equal(live(),'','the poll never writes it');
 h.fire();assert.equal(live(),'2 of 3 labs shown');
 h.context.renderHome();assert.equal(live(),'2 of 3 labs shown','and does not rewrite it');
 h.type('zzz');h.fire();assert.equal(live(),'No lab matches. Try part of a lab name, a state or a device name.');assert.doesNotMatch(live(),/zzz/);
 h.type('');h.fire();assert.equal(live(),'','an empty term empties it');
 assert.equal(h.element('home-filter-live').hidden,false,'never hidden');
});

test('C09: the row shows with two labs, hides with one lab and an empty unfocused field, and a value or focus inside it keeps it',()=>{
 const one=filterHarness([labOf('a','Alpha')]);one.context.renderHome();assert.equal(one.row.hidden,true);
 one.type('al');assert.equal(one.row.hidden,false,'a typed term keeps the row');
 one.type('');assert.equal(one.row.hidden,true,'empty and not focused: hidden again');
 one.setActive(one.field);one.context.renderHome();assert.equal(one.row.hidden,false,'focus in the field keeps it');
 one.setActive(one.clear);one.context.renderHome();assert.equal(one.row.hidden,false,'focus on Clear keeps it (focus anywhere inside the row)');
 one.setActive(null);one.context.renderHome();assert.equal(one.row.hidden,true);
 const two=filterHarness([labOf('a','Alpha'),labOf('b','Beta')]);two.context.renderHome();assert.equal(two.row.hidden,false);
 const loading=filterHarness([labOf('a','Alpha'),labOf('b','Beta')],{state:{loaded:false}});loading.context.renderHome();assert.equal(loading.row.hidden,true,'hidden until the state is loaded');
 const none=filterHarness([]);none.context.renderHome();assert.equal(none.element('home-labs').hidden,true);
});

test('C09: Clear empties the field, focuses it before rendering (so one lab keeps the row), and schedules the live sentence',()=>{
 const h=filterHarness([labOf('a','Alpha')]);
 h.context.renderHome();h.type('zzz');h.setActive(h.clear);
 const order=[];const render=h.context.renderHome;
 h.field.focus=()=>{order.push('focus');h.setActive(h.field);};
 h.context.renderHome=()=>{order.push('render:'+(h.active()===h.field?'field focused':'not focused'));return render();};
 h.clear.onclick();
 assert.equal(h.field.value,'');assert.equal(h.active(),h.field,'focus is in the field');assert.equal(h.row.hidden,false,'one lab: the row is still there');assert.equal(h.clear.hidden,true);
 assert.deepEqual(order.slice(0,2),['focus','render:field focused'],'focus first, then render');
 assert.deepEqual(cardNames(h),['Alpha']);h.fire();assert.equal(h.element('home-filter-live').textContent,'');
 h.setActive(null);h.context.renderHome=render;h.context.renderHome();assert.equal(h.row.hidden,true,'once focus leaves, the one-lab row goes away again');
});

test('C09: the field, its value and the markup of an unchanged list survive polls',()=>{
 const h=filterHarness([labOf('a','Alpha'),labOf('b','Beta')]);
 h.context.renderHome();h.type('alp');const field=h.element('home-filter'),html=h.element('lab-cards')._markup;
 h.context.renderHome();h.context.renderHome();
 assert.equal(h.element('home-filter'),field);assert.equal(field.value,'alp');assert.equal(h.element('lab-cards')._markup,html);assert.deepEqual(cardNames(h),['Alpha']);
 assert.equal(h.tabStore.value,'','the filter is neither stored nor a route: the tab store is untouched');
 const src=fs.readFileSync(path.join(__dirname,'../app/static/home.js'),'utf8');
 assert.doesNotMatch(src,/localStorage|sessionStorage|location\.|history\.|addEventListener\('keydown',[^)]*Escape.*filter/,'no storage, no URL');
});
