// home.js: the Home page cards, the single-lab rule, escaping, the Start reason and the discovered section.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const NOW=Date.parse('2026-09-16T12:00:00Z');
function harness(state,{lastLab='',opened={},quick}={}){
 const elements=new Map(),calls={selectLab:[],openLabOperations:[],json:[],deploy:0};
 const element=id=>{if(!elements.has(id))elements.set(id,{id,hidden:false,disabled:false,innerHTML:'',textContent:'',listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}});return elements.get(id);};
 const context=vm.createContext({$:element,esc,console,state:{labs:[],jobs:[],loaded:true,...state},current:()=>undefined,busy:()=>false,
  setMarkup(el,html){if(el._markup===html)return false;el.innerHTML=html;el._markup=html;return true;},
  lastOpened:()=>lastLab,openedAt:id=>opened[id]||'',Date:class extends Date{static now(){return NOW;}},
  selectLab(id,view){calls.selectLab.push([id,view]);},openLabOperations(id){calls.openLabOperations.push(id);},openDeploy(){calls.deploy++;},
  json:async(...args)=>{calls.json.push(args);return {};},refresh:async()=>{},notify(){}});
 if(quick)context.opQuickActions=quick;
 for(const file of ['status.js','home.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/'+file),'utf8'),context);
 return {context,element,calls};
}
const running={id:'run',name:'BGP core',favorite:false,nodes:[{name:'r1',ssh_ready:true},{name:'r2',ssh_ready:true}],deployment:{status:'Running'},nos_readiness:{status:'ready',total:2,ready:2},git_binding:{binding_id:'b',repository:{push_url:'https://github.com/x/y'}},vm_project_path:'/labs/bgp.clab.yaml'};
const stopped={id:'stop',name:'OSPF area 0',favorite:true,nodes:[{name:'s1'},{name:'s2'},{name:'s3'}],deployment:{status:'Not deployed'},vm_project_path:'/labs/ospf.clab.yaml'};
const saved=[{id:'g1',lab_id:'run',status:'synced',target:'latest',created:'2026-09-16T11:48:00Z',finished:'2026-09-16T11:48:30Z'}];

test('cards read the lab state, the ready count and the last save in student words, favourites first',()=>{
 const h=harness({labs:[running,stopped],git_jobs:saved,discovery:{connected:true}},{opened:{run:'2026-09-16T09:00:00Z'}});
 h.context.renderHome();
 const cards=h.element('lab-cards').innerHTML;
 assert.equal(h.element('lab-cards').hidden,false);assert.equal(h.element('home-continue').hidden,true,'nothing was opened before');
 assert.ok(cards.indexOf('OSPF area 0')<cards.indexOf('BGP core'),'favourites come first');
 assert.match(cards,/class="pill ok">Running<\/span><span>2 of 2 devices ready/);
 assert.match(cards,/Last saved 12 minutes ago/);assert.match(cards,/Last opened 3 hours ago/);
 assert.match(cards,/class="pill neutral">Stopped<\/span><span>Not running/);assert.match(cards,/Not saved anywhere yet/);
 assert.match(cards,/data-lab="run">Open lab/);assert.match(cards,/data-lab="stop">Open lab/);
 assert.match(cards,/data-lab-favorite="stop" aria-pressed="true" aria-label="Remove from favourites"/);
 assert.match(cards,/data-lab-favorite="run" aria-pressed="false" aria-label="Add to favourites"/);
 assert.match(cards,/data-lab-more="run" aria-label="More actions for BGP core"/);
 assert.doesNotMatch(cards,/container|discover|NOS|worker|Unlinked/i);
 const attention=harness({labs:[{...running,id:'att',name:'Att'}],git_jobs:[{id:'g2',lab_id:'att',status:'push_pending',target:'latest',created:'2026-09-16T11:50:00Z'}]});
 attention.context.renderHome();assert.match(attention.element('home-continue').innerHTML,/Needs attention — Saved on this VM, but it could not be uploaded to github\.com/);
});

test('with exactly one lab only the Continue card is shown; the last opened lab gets the Continue card otherwise',()=>{
 const single=harness({labs:[running],git_jobs:saved});single.context.renderHome();
 assert.equal(single.element('home-continue').hidden,false);assert.match(single.element('home-continue').innerHTML,/class="lab-card continue"/);
 assert.match(single.element('home-continue').innerHTML,/<p class="caption">Continue where you left off<\/p><h3>BGP core<\/h3>/);
 assert.equal(single.element('lab-cards').hidden,true);assert.equal(single.element('lab-cards').innerHTML,'');
 const two=harness({labs:[running,stopped]},{lastLab:'stop'});two.context.renderHome();
 assert.equal(two.element('home-continue').hidden,false);assert.match(two.element('home-continue').innerHTML,/OSPF area 0/);assert.doesNotMatch(two.element('home-continue').innerHTML,/BGP core/);
 assert.equal(two.element('lab-cards').hidden,false);
 const gone=harness({labs:[running,stopped]},{lastLab:'removed'});gone.context.renderHome();assert.equal(gone.element('home-continue').hidden,true);
 const none=harness({labs:[]});none.context.renderHome();
 assert.equal(none.element('home-continue').hidden,true);assert.equal(none.element('lab-cards').hidden,true);assert.equal(none.element('home-actions').hidden,true);
 const later=harness({labs:[running,stopped]});later.context.renderHome();const before=later.element('lab-cards').innerHTML;later.context.renderHome();
 assert.equal(later.element('lab-cards')._markup,before,'unchanged markup is not reassigned on the next poll');
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
 ready.context.renderHome();assert.match(ready.element('home-continue').innerHTML,/data-lab-start="stop" >Start stopped devices<\/button>/);
 assert.doesNotMatch(ready.element('home-continue').innerHTML,/<small class="caption">/,'no reason line when Start is available');
 const legacy=harness({labs:[stopped],discovery:{connected:false}},{quick:()=>({startAction:'deploy',canStart:false,canDestroy:false})});
 legacy.context.renderHome();assert.match(legacy.element('home-continue').innerHTML,/title="Connect the VM first"/,'a reason is computed when opQuickActions does not give one');
 const noOps=harness({labs:[stopped]});noOps.context.renderHome();assert.doesNotMatch(noOps.element('home-continue').innerHTML,/data-lab-start/,'no operations module, no Start button');
});

test('the discovered section shows whenever the VM has a lab that is not in My labs or one was hidden, once the state has loaded',()=>{
 const shown=harness({labs:[running,stopped],discovery:{discovered:[{name:'extra',imported:false}]}});shown.context.renderHome();
 assert.equal(shown.element('home-discovered').hidden,false);assert.equal(shown.element('home-skeleton').hidden,true);
 const imported=harness({labs:[running],discovery:{discovered:[{name:'run',imported:true}],ignored_labs:[]}});imported.context.renderHome();
 assert.equal(imported.element('home-discovered').hidden,true);
 const hiddenLab=harness({labs:[],discovery:{discovered:[],ignored_labs:['old']}});hiddenLab.context.renderHome();
 assert.equal(hiddenLab.element('home-discovered').hidden,false,'excluded labs stay reachable even with zero labs');
 const excludedOnly=harness({labs:[running],discovery:{discovered:[{name:'gone',imported:false,excluded:true}]}});excludedOnly.context.renderHome();
 assert.equal(excludedOnly.element('home-discovered').hidden,true,'an excluded discovery is listed under ignored_labs, not here');
 const loading=harness({labs:[],loaded:false,discovery:{discovered:[{name:'extra',imported:false}]}});loading.context.renderHome();
 assert.equal(loading.element('home-discovered').hidden,true);assert.equal(loading.element('home-skeleton').hidden,false);
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
});
