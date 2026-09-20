// home.js: the Home page cards, the single-lab rule, escaping, the Start reason and the count of labs found on the VM.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const NOW=Date.parse('2026-09-16T12:00:00Z');
function harness(state,{lastLab='',opened={},quick,tab}={}){
 const elements=new Map(),calls={selectLab:[],openLabOperations:[],json:[],deploy:0};
 const element=id=>{if(!elements.has(id))elements.set(id,{id,hidden:false,disabled:false,innerHTML:'',textContent:'',listeners:{},attrs:{},classes:new Set(),addEventListener(name,fn){this.listeners[name]=fn;},setAttribute(n,v){this.attrs[n]=String(v);},classList:{toggle:(name,on)=>{const e=elements.get(id);if(on)e.classes.add(name);else e.classes.delete(name);}},focus(){calls.focus=id;}});return elements.get(id);};
 const tabStore={value:tab||''};
 const context=vm.createContext({$:element,esc,console,state:{labs:[],jobs:[],loaded:true,...state},current:()=>undefined,busy:()=>false,
  setMarkup(el,html){if(el._markup===html)return false;el.innerHTML=html;el._markup=html;return true;},
  lastOpened:()=>lastLab,openedAt:id=>opened[id]||'',homeTab:()=>tabStore.value||'recent',rememberHomeTab:v=>{tabStore.value=v;return true;},Date:class extends Date{static now(){return NOW;}},
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
 assert.match(cards,/Last saved 12 minutes ago/);assert.match(cards,/<p class="caption lab-card-times">Deployed 2 hours ago · Last opened 3 hours ago<\/p>/);
 assert.match(cards,/<p class="caption lab-card-times">No deployment recorded by this manager<\/p>/,'a lab without a recorded deployment says so and shows no time');
 assert.match(cards,/class="pill neutral">Stopped<\/span><span>Not running/);assert.match(cards,/Not saved anywhere yet/);
 assert.match(cards,/data-lab="run">Open lab/);assert.match(cards,/data-lab="stop">Open lab/);
 assert.match(cards,/data-lab-favorite="stop" aria-pressed="true" aria-label="Remove from favourites"/);
 assert.match(cards,/data-lab-favorite="run" aria-pressed="false" aria-label="Add to favourites"/);
 assert.match(cards,/data-lab-more="run" aria-label="More actions for BGP core"/);
 assert.doesNotMatch(cards,/container|discover|NOS|worker|Unlinked/i);assert.doesNotMatch(cards,/Continue where you left off/);
 const attention=harness({labs:[{...running,id:'att',name:'Att'}],git_jobs:[{id:'g2',lab_id:'att',status:'push_pending',target:'latest',created:'2026-09-16T11:50:00Z'}]});
 attention.context.renderHome();assert.match(attention.element('lab-cards').innerHTML,/Needs attention — Saved on this VM, but it could not be uploaded to github\.com/);
});

test('Recent labs orders by the most recent deployment, newest first; opening, saving and favourites do not reorder it; labs without a deployment come last by name',()=>{
 const lab=(id,name,last_deployed,extra={})=>({...stopped,id,name,favorite:false,last_deployed,...extra});
 const labs=[lab('a','Alpha',''),lab('z','Zulu','2026-09-10T08:00:00Z'),lab('m','Mike','2026-09-15T08:00:00Z',{favorite:true}),lab('b','Bravo',undefined),lab('k','Kilo','2026-09-15T08:00:00Z')];
 const names=(h,t)=>Array.from(h.context.homeOrder(labs,t),l=>l.name);
 const h=harness({labs},{lastLab:'a',opened:{a:'2026-09-16T11:59:00Z'}});
 assert.deepEqual(names(h,'recent'),['Kilo','Mike','Zulu','Alpha','Bravo'],'newest deployment first, equal times by name, undated labs last by name');
 assert.deepEqual(names(h,'all'),['Mike','Alpha','Bravo','Kilo','Zulu']);
 h.context.renderHome();const cards=h.element('lab-cards').innerHTML,order=['Kilo','Mike','Zulu','Alpha','Bravo'].map(n=>cards.indexOf('<h3>'+n+'</h3>'));
 assert.deepEqual(order,[...order].sort((x,y)=>x-y),'Recent labs is the default tab');assert.ok(order.every(i=>i>=0));
 assert.equal(h.element('home-tab-note').textContent,'Most recently deployed first. Labs this manager has not deployed come last, by name.');
 assert.equal(h.element('home-tab-recent').attrs['aria-selected'],'true');assert.equal(h.element('home-tab-all').attrs['aria-selected'],'false');assert.ok(h.element('home-tab-recent').classes.has('active'));
 // the most recently OPENED lab (Alpha) and a git save do not move anything
 const saved2=harness({labs,git_jobs:[{id:'g',lab_id:'b',status:'synced',target:'latest',created:'2026-09-16T11:59:00Z',finished:'2026-09-16T11:59:30Z'}]},{lastLab:'b'});
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
