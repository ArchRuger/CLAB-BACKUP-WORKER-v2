// The Load panel (load.js, docs/git-redesign/design/LOAD.md 11.4): the list, the confirmation, the single sender of `acknowledge: true`,
// the review's life, retry, undo, the chip panel's load views and the parity of every old entry point. status.js, load.js and restore.js
// run together in one vm context with fake elements for the header's panels and the drawer.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const STATIC=path.join(__dirname,'../app/static');
const read=name=>fs.readFileSync(path.join(STATIC,name),'utf8');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
const NOW=Date.now();
const iso=ms=>new Date(ms).toISOString();
const PLATFORMS={arista_ceos:{restore_suffix:'eoscfg'},cisco_xrv9k:{restore_suffix:'xrcfg'},juniper_vjunosswitch:{restore_suffix:'jcfg'},juniper_cjunosevolved:{restore_suffix:'jcfg'},linux:{}};
const node=(short,platform)=>({name:'clab-BGP-'+short,short_name:short,platform,ssh_ready:true,runtime_state:'running'});
function makeLab(extra={}){return {id:'lab',name:'BGP',deployment:{status:'Running'},nos_readiness:{status:'ready'},git_binding:{repository:{prefix:'BGP',path:'/home/ben/repo',push_url:'https://github.com/x/repo.git'}},
 nodes:[node('ceos','arista_ceos'),node('xrv9k','cisco_xrv9k'),node('vjunos','juniper_vjunosswitch'),node('evo','juniper_cjunosevolved'),node('host','linux')],...extra};}
function element(id){
 const el={id,hidden:false,innerHTML:'',textContent:'',disabled:false,open:false,listeners:{},focused:0,
  addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn);},
  dispatch(type,event={}){for(const fn of this.listeners[type]||[])fn(event);},
  querySelector(sel){if(sel==='[data-panel-focus]')return /data-panel-focus/.test(this.innerHTML)?{focus:()=>{el.focused++;}}:null;if(sel==='.menu-reason')return el.reason||null;return null;},
  contains(){return false;},click(){this.clicked=(this.clicked||0)+1;}};
 return el;
}
// One page: the Load panel (#load-panel, #load-panel-body), the chip panel (#save-panel), the drawer (#save-drawer), and the routes answered
// as the backend contract says. `routes(endpoint, method, body)` answers json(); GET answers come from `gets`.
function page(options={}){
 const els={},get=id=>els[id]||(els[id]=element(id));
 for(const id of ['load-panel','load-panel-body','save-panel','save-drawer','load-button','save-chip','save-live','lab-start','vm-refresh'])get(id);
 els['load-panel'].hidden=true;els['save-panel'].hidden=true;
 const calls=[],gets=[],toasts=[],drawers=[],shown=[],timers=[];
 const lab=options.lab||makeLab();
 const context=vm.createContext({console,Date,setImmediate,URLSearchParams,crypto:require('node:crypto').webcrypto,esc,
  state:{labs:[lab],jobs:[],git_jobs:[],restore_jobs:[],operations:[],design_jobs:[],platforms:PLATFORMS,...(options.state||{})},
  activeId:'lab',$:id=>els[id]||null,
  setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{},
  setMarkup:(el,html)=>{if(!el||el._markup===html)return false;el.innerHTML=html;el._markup=html;return true;},
  notify:message=>toasts.push(message),refresh:async()=>{},utcDisplay:v=>String(v),
  json:async(endpoint,method,body)=>{calls.push({endpoint,method,body:JSON.parse(JSON.stringify(body))});if(options.routes)return options.routes(endpoint,method,body,calls.length);return {};},
  api:async(endpoint)=>{gets.push(endpoint);const answer=options.gets?options.gets(endpoint):{};if(answer instanceof Error)throw answer;return {json:async()=>answer};},
  openPanel:(id,opts)=>{if(id==='load-button'||id==='load-panel'){const p=els['load-panel'];if(!p.hidden)return true;els['save-panel'].hidden=true;p.hidden=false;p.dispatch('panelopen');if(!(opts&&opts.focus===false)){const t=els['load-panel-body'].querySelector('[data-panel-focus]');if(t)t.focus();}return true;}
   if(id==='save-chip'||id==='save-panel'){closeLoad();els['save-panel'].hidden=false;return true;}return false;},
  saveOpenPanel:kind=>{shown.push(kind);if(kind==='status'){closeLoad();els['save-panel'].hidden=false;}},
  closeMenus:()=>{closeLoad();els['save-panel'].hidden=true;},
  ...(options.drawer===false?{}:{saveDrawerOpen:(kind,opts)=>{closeLoad();drawers.push({kind,opts});els['save-drawer'].open=true;},saveDrawerClose:()=>{els['save-drawer'].open=false;els['save-drawer'].dispatch('close');}}),
  ...(options.globals||{})});
 function closeLoad(){const p=els['load-panel'];if(p.hidden)return;p.hidden=true;p.dispatch('panelclose');}
 els['load-button']._menuClose=()=>closeLoad();
 for(const name of ['status.js','load.js','restore.js'])vm.runInContext(read(name),context,{filename:name});
 const body=()=>els['load-panel-body'].innerHTML;
 const click=async(selector,where='load-panel')=>{
  // Finds the control in the rendered markup by attribute and dispatches a delegated click to the element's listener.
  const html=where==='load-panel'?body():where==='save-panel'?els['save-panel'].innerHTML:els['save-drawer'].innerHTML;
  const m=html.match(new RegExp('<[^>]*'+selector+'[^>]*>'));assert.ok(m,'control '+selector+' is rendered');
  const tag=m[0],data={};for(const [,k,v] of tag.matchAll(/data-load-([a-z-]+)="([^"]*)"/g))data['load'+k.split('-').map(s=>s[0].toUpperCase()+s.slice(1)).join('')]=v.replace(/&amp;/g,'&');
  const control={dataset:data,disabled:/\sdisabled(\s|>|$)/.test(tag),closest(){return control;}};
  const target={closest:()=>control};
  for(const fn of els[where].listeners.click||[])await fn({target});
  await settle();
 };
 const tick=async(name,checked)=>{for(const fn of els['load-panel'].listeners.change||[])fn({target:{name:'load-node',value:name,checked}});};
 return {c:context,els,calls,gets,toasts,drawers,shown,timers,body,click,tick,lab,
  open:async()=>{context.openPanel('load-button');await settle();},
  close:()=>closeLoad()};
}
const rowAnswer=(rows,extra={})=>({head:'h'.repeat(40),truncated:false,lab_devices:4,states:rows,...extra});
const stateRow=(p,group,extra={})=>({path:p,commit:'h'.repeat(40),name:p.split('/').filter(x=>x!=='latest').pop(),group,lab:'',kind:'capture',layout:'latest',saved_at:iso(NOW-3600e3),saved_devices:4,loadable_devices:4,view_only:false,view_only_reason:'',...extra});
const target=(short,platform,extra={})=>({name:'clab-BGP-'+short,short_name:short,platform,running_platform:platform,eligible:true,reason:'',requested:true,reachable:true,matches_saved:false,pending_changes:3,...extra});
const preflight=(targets,source={})=>({source:{type:'folder',path:'/BGP/latest',commit:'c'.repeat(40),captured_at:iso(NOW-2*86400e3),topology:{differs:null,saved_devices:4,matching_devices:4},...source},targets,eligible_count:targets.filter(t=>t.eligible).length});
const fourTargets=()=>[target('ceos','arista_ceos',{pending_changes:5}),target('evo','juniper_cjunosevolved'),target('vjunos','juniper_vjunosswitch',{matches_saved:true,pending_changes:0}),target('xrv9k','cisco_xrv9k',{pending_changes:7})];
const ALLOWED=new Set(['save-panel','wide','save-state','save-sub','save-row','save-note','save-kv','save-foot','save-heading','save-list','save-item','save-when','save-why','save-devices','save-end','ok','bad','now','warn','save-dot','none','busy','info','off','button','danger','primary','ghost','small','sr-only','caption','form-error','secondary']);
const classes=html=>[...html.matchAll(/class="([^"]*)"/g)].flatMap(m=>m[1].split(/\s+/).filter(Boolean));
const focusCount=html=>(html.match(/data-panel-focus/g)||[]).length;

// ---- 9. the list ---------------------------------------------------------------------------------------------------------------------
test('the list: Your saves (latest and the three newest checkpoints), Lab states capped at eight, view-only rows with their reason, coverage, and only the shared class names',async()=>{
 const states=[stateRow('course/start','state',{name:'Start',view_only:true,view_only_reason:'no_restore_data'}),stateRow('course/s1','state',{name:'State 1',loadable_devices:2}),
  stateRow('course/odd','state',{name:'Odd',saved_devices:null,loadable_devices:null,view_only_reason:'unknown'})];
 for(let i=2;i<=10;i++)states.push(stateRow('course/s'+i,'state',{name:'State '+i}));
 const rows=[stateRow('BGP/latest','latest'),...[1,2,3,4,5].map(i=>stateRow('BGP/checkpoints/cp'+i,'checkpoint',{saved_at:iso(NOW-i*3600e3)})),stateRow('BGP/baseline','baseline',{name:'Baseline'}),stateRow('other/latest','other-lab',{name:'Their save',lab:'Other'}),...states];
 const p=page({gets:e=>e==='/labs/lab/restore/states'?rowAnswer(rows):{},
  state:{git_jobs:[{id:'g1',lab_id:'lab',target:'latest',status:'synced',commit:'a'.repeat(40),note:'Interface descriptions cleaned up',created:iso(NOW-3600e3),finished:iso(NOW-3600e3),captured:true}]}});
 await p.open();
 assert.deepEqual(p.gets,['/labs/lab/restore/states'],'one request, to the lab\'s own save location: no repository parameter');
 const html=p.body();
 assert.match(html,/^<h2 class="sr-only" tabindex="-1" data-panel-focus>Load a saved state<\/h2>/);
 assert.match(html,/<h3 class="save-heading">Your saves<\/h3><ul class="save-list"><li><button type="button" class="save-item" id="load-row-0" data-load-row="0"><span>Interface descriptions cleaned up<\/span><span class="save-when">1 hour ago<\/span>/);
 assert.match(html,/cp1<\/span>.*cp2<\/span>.*cp3<\/span>/s);assert.doesNotMatch(html,/cp4|cp5/,'only the three newest checkpoints');
 assert.doesNotMatch(html,/Baseline|Their save/,'the starting point and another lab\'s saves are not in the panel');
 assert.match(html,/<h3 class="save-heading">Lab states<\/h3>/);
 const labStates=html.slice(html.indexOf('Lab states'));
 assert.equal((labStates.match(/<li/g)||[]).length,8,'eight lab states');
 assert.match(html,/<p class="save-note">4 more in All versions<\/p>/);
 assert.match(html,/<li class="off"><div class="save-item"><span>Start<span class="save-why">Saved without the files needed to load it<\/span><\/span><span class="save-when">View only<\/span><\/div><button type="button" class="button ghost small" id="load-view-\d+" data-load-view="\d+">View<\/button><\/li>/,'a view-only row is text with its reason and a View button, not a disabled button');
 assert.doesNotMatch(html,/<button[^>]*data-load-row[^>]*><span>Start</,'a view-only row is not a button');
 assert.match(html,/<span>Odd<span class="save-why">Its save details cannot be read<\/span><\/span><span class="save-when"><\/span>/,'unknown coverage: no count, the reason, still loadable through the preflight');
 assert.match(html,/<span>State 1<\/span><span class="save-when">2 of 4 devices<\/span>/);assert.match(html,/<span>State 2<\/span><span class="save-when">4 devices<\/span>/);
 assert.match(html,/<div class="save-foot"><button[^>]*data-load-action="all">All versions<\/button><button[^>]*data-load-action="browse">Browse the repository…<\/button><\/div>$/);
 assert.doesNotMatch(html,/From /,'a lab read through its own save location names no repository');
 for(const name of classes(html))assert.ok(ALLOWED.has(name),'class '+name);
 // A row sends its own commit and the list's repository in five keys.
 await p.click('data-load-row="0"');
 assert.equal(p.calls[0].endpoint,'/labs/lab/restore/preflight');
 assert.deepEqual(p.calls[0].body,{source:{type:'folder',commit:'h'.repeat(40),path:'/BGP/latest',backup_job_id:'',repository:''}});
});
test('the list foot opens All versions and the browse mode of the chooser through the drawer; View opens the state\'s files',async()=>{
 const p=page({gets:()=>rowAnswer([stateRow('course/start','state',{name:'Start',view_only:true,view_only_reason:'no_restore_data'})])});
 await p.open();
 await p.click('data-load-action="all"');assert.equal(p.drawers[0].kind,'versions');
 await p.open();await p.click('data-load-action="browse"');assert.equal(p.drawers[1].kind,'chooser');assert.equal(p.drawers[1].opts.mode,'browse');
 await p.open();await p.click('data-load-view="0"');assert.equal(p.drawers[2].kind,'files','the drawer kind that shows a state’s files (the versions kind only lists; integration)');assert.equal(p.drawers[2].opts.row.path,'course/start');
 assert.equal(p.calls.length,0,'nothing is sent');
});

// ---- 10. the confirmation ----------------------------------------------------------------------------------------------------------
function confirmPage(targets,extra={}){
 const lab=makeLab({nodes:[node('ceos','arista_ceos'),node('xrv9k','cisco_xrv9k'),node('vjunos','juniper_vjunosswitch'),node('evo','juniper_cjunosevolved'),node('r5','arista_ceos'),node('r6','arista_ceos'),node('r7','arista_ceos'),node('host','linux')]});
 return page({lab,routes:(e)=>e.endsWith('/preflight')?preflight(targets,extra.source):{id:'job1',lab_id:'lab',status:'queued',targets:[]},...extra});
}
test('the confirmation: every preflight row kind gives its text, tick box and reason; lab devices without a row read Not in this state',async()=>{
 const targets=[target('ceos','arista_ceos',{pending_changes:5}),target('xrv9k','cisco_xrv9k',{matches_saved:true,pending_changes:0}),target('r7','arista_ceos',{pending_changes:1}),
  target('vjunos','juniper_vjunosswitch',{eligible:false,reachable:false,reason:'SSH probe failed: TimeoutError'}),
  target('evo','juniper_cjunosevolved',{eligible:false,reachable:true,reason:'Another change is waiting for confirmation on this node.'}),
  target('r6','arista_ceos',{eligible:false,reachable:undefined,reason:'Assign NOS credentials to this node first.',matches_saved:undefined,pending_changes:undefined}),
  target('gone','arista_ceos',{eligible:false,reachable:undefined,reason:'No running node in this lab matches this saved node.'}),
  target('odd','arista_ceos',{name:'clab-BGP-odd',eligible:false,reachable:undefined,reason:'<b>strange</b>'})];
 targets.push(target('ready','arista_ceos',{name:'clab-BGP-r5',short_name:'r5',matches_saved:undefined,pending_changes:undefined}));
 const p=confirmPage(targets);
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest',commit:'h'.repeat(40)},'ospf-up');
 const html=p.body();
 assert.match(html,/^<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot warn" aria-hidden="true"><\/span>Load ospf-up\?<\/p><p class="save-sub">The running configuration of the ticked devices is replaced\. The current one is backed up first; nothing reboots\.<\/p><p class="save-note">Saved 2 days ago\.<\/p>/);
 const li=short=>{const m=html.match(new RegExp('<li[^>]*><label><input[^>]*value="clab-BGP-'+short+'"[^>]*>.*?</li>'));assert.ok(m,short);return m[0];};
 assert.match(li('ceos'),/<li><label><input type="checkbox" name="load-node" id="load-node-\d" value="clab-BGP-ceos" checked><span>ceos <small>EOS<\/small><\/span><\/label><span class="save-end">5 lines differ<\/span><\/li>/);
 assert.match(li('xrv9k'),/ checked><span>xrv9k <small>IOS XR<\/small><\/span><\/label><span class="save-end">Already matches<\/span>/);
 assert.match(li('r7'),/checked>.*<span class="save-end">1 line differs<\/span>/);
 assert.match(li('r5'),/checked>.*<span class="save-end">Ready to load<\/span>/);
 assert.match(li('vjunos'),/^<li class="off"><label><input [^>]* disabled><span>vjunos <small>Junos<\/small><span class="save-why">The device did not answer over SSH\.<\/span><\/span><\/label><span class="save-end">Not reachable<\/span>/);
 assert.match(li('evo'),/class="off".* disabled>.*<span class="save-why">Someone else&#39;s configuration change is waiting for confirmation on this device\. Try again when it has finished\.<\/span>.*<span class="save-end">Blocked<\/span>/);
 assert.match(li('r6'),/class="off".* disabled>.*<span class="save-why">Add login credentials for this device first\.<\/span><\/span><\/label><button type="button" class="button ghost small" id="load-fix-\d" data-load-action="credentials">Credentials…<\/button><span class="save-end">Can&#39;t load<\/span>/,'the action that clears the reason is a button beside it (review D3), outside the label');
 assert.match(li('gone'),/class="off".* disabled>.*<span class="save-end">Not in this lab<\/span>/);
 assert.match(li('odd'),/&lt;b&gt;strange&lt;\/b&gt;/,'reasons are escaped');assert.doesNotMatch(html,/<b>strange/);
 assert.doesNotMatch(html,/value="clab-BGP-host"/,'a device without a restore format has no row');
 assert.match(html,/<li class="off"><label><input type="checkbox" name="load-node" id="load-node-\d+" value="clab-BGP-r6"/);
 // Every lab device with a restore format has a row here, so no subset sentence; a lab device missing from the preflight reads Not in this state.
 assert.doesNotMatch(html,/This state covers/);
 assert.match(html,/<details><summary>Options<\/summary><label for="load-minutes">Undo automatically if a device cannot be reached again within \(minutes\)<\/label><input id="load-minutes" type="number" min="2" max="60" value="5"><\/details>/);
 assert.match(html,/<p class="save-note">Each device checks the new configuration itself and undoes it if it loses contact\.<\/p>/);
 assert.match(html,/<div class="save-row"><button type="button" class="button danger" id="load-run" data-load-action="run">Load<\/button><button[^>]*data-load-action="cancel">Cancel<\/button><button[^>]*data-load-action="diff">See what's different<\/button><span class="caption" id="load-run-reason" hidden><\/span><\/div>/);
 assert.doesNotMatch(html,/type="checkbox"(?![^>]*name="load-node")/,'no acknowledgement tick box (D4)');
 for(const name of classes(html))assert.ok(ALLOWED.has(name),'class '+name);
 assert.equal(focusCount(html),1);
});
test('the subset sentence, the topology line and the "none can be loaded" sentence',async()=>{
 const p=confirmPage([target('ceos','arista_ceos'),target('xrv9k','cisco_xrv9k')],{source:{topology:{differs:true,saved_devices:4,matching_devices:3}}});
 await p.c.loadChoose('lab',{type:'folder',path:'/course/final'},'Final');
 const html=p.body();
 assert.match(html,/<p class="save-note">This state covers 2 of your 7 devices\. The others are left as they are\.<\/p>/);
 assert.match(html,/value="clab-BGP-vjunos" disabled><span>vjunos <small>Junos<\/small><\/span><\/label><span class="save-end">Not in this state<\/span>/);
 assert.match(html,/<p class="save-note">Saved on a different topology: 3 of 4 devices match\. <button type="button" class="button ghost small" id="load-topology" data-load-action="topology">View its topology<\/button><\/p>/);
 await p.click('data-load-action="topology"');
 assert.equal(p.drawers[0].kind,'files');assert.equal(p.drawers[0].opts.file,'topology');assert.ok(p.drawers[0].opts.row.path);
 assert.equal(p.calls.filter(c=>c.endpoint.endsWith('/restore')).length,0,'View its topology never changes anything');
 const q=confirmPage([target('ceos','arista_ceos',{eligible:false,reachable:false,reason:'SSH probe failed: OSError'})],{source:{topology:{differs:null}}});
 await q.c.loadChoose('lab',{type:'folder',path:'/x'},'X');
 assert.match(q.body(),/<p class="save-sub">None of the devices can be loaded right now\.<\/p>/);
 assert.match(q.body(),/id="load-run" data-load-action="run" disabled>Load</);
 assert.doesNotMatch(q.body(),/different topology/,'no line when the comparison is unknown');
});
test('nothing ticked disables Load with its reason; a save of the lab disables it with "A save is running." and keeps the ticks',async()=>{
 const p=confirmPage(fourTargets());
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');
 const run=p.els['load-run']=element('load-run'),why=p.els['load-run-reason']=element('load-run-reason');
 for(const t of fourTargets())await p.tick(t.name,false);
 assert.equal(run.disabled,true);assert.equal(why.textContent,'Tick at least one device.');assert.equal(why.hidden,false);
 assert.equal(await p.c.loadSubmit(),null);assert.equal(p.calls.length,1,'nothing ticked: nothing sent');
 await p.tick('clab-BGP-ceos',true);
 assert.equal(run.disabled,false);assert.equal(why.hidden,true);
 p.c.state.git_jobs=[{id:'g',lab_id:'lab',status:'capturing',target:'latest'}];
 const before=p.body();p.c.loadRender();
 assert.equal(run.disabled,true);assert.equal(why.textContent,'A save is running.');
 assert.equal(p.body(),before,'the poll does not rebuild the confirmation');
 assert.equal(await p.c.loadSubmit(),null);assert.equal(p.calls.length,1,'a save runs: nothing sent');
 p.c.state.git_jobs=[{id:'g',lab_id:'lab',status:'synced',target:'latest'}];p.c.loadRender();
 assert.equal(run.disabled,false);
 await p.c.loadSubmit();
 assert.deepEqual(p.calls[1].body.node_names,['clab-BGP-ceos'],'only the ticked device is sent');
});

// ---- 11. the review's life (L1) ---------------------------------------------------------------------------------------------------
test('L1: closing the panel drops the review and Load opens on the list again; a review of another lab submits nothing',async()=>{
 const p=confirmPage(fourTargets(),{gets:()=>rowAnswer([stateRow('BGP/latest','latest')])});
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');
 assert.equal(p.els['load-panel'].hidden,false,'loadChoose opens the panel');
 assert.match(p.body(),/Load ospf-up\?/,'and shows the confirmation');
 p.close();
 assert.equal(vm.runInContext('loadReview',p.c),null,'closed: the review is gone');
 await p.open();
 assert.match(p.body(),/Load a saved state/);assert.doesNotMatch(p.body(),/Load ospf-up\?/,'the panel opens on the list');
 // A review, then the lab on screen changes: nothing is sent and the review is gone.
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');
 p.c.activeId='other';
 assert.equal(await p.c.loadSubmit(),null);
 assert.equal(p.calls.filter(c=>c.endpoint.endsWith('/restore')).length,0);
 p.c.loadRender();assert.equal(vm.runInContext('loadReview',p.c),null,'every render drops a review of another lab');
});
test('L1: loadSubmit sends nothing without a finished preflight, and an answer that arrives after its review was replaced renders nothing',async()=>{
 let release;const pending=new Promise(r=>{release=r;});
 const p=page({routes:async(e,m,b,n)=>{if(e.endsWith('/preflight')&&n===1){await pending;return preflight([target('ceos','arista_ceos',{short_name:'stale'})]);}return preflight(fourTargets());}});
 const first=p.c.loadChoose('lab',{type:'folder',path:'/a'},'First');await settle();
 assert.match(p.body(),/Checking First against your devices…/);
 assert.equal(await p.c.loadSubmit(),null,'no finished preflight: nothing sent');
 await p.c.loadChoose('lab',{type:'folder',path:'/b'},'Second');
 release();await first;
 assert.match(p.body(),/Load Second\?/);assert.doesNotMatch(p.body(),/stale/,'the late answer of the replaced review renders nothing');
 // Cancel while checking: the answer of the cleared review renders nothing either.
 let release2;const pending2=new Promise(r=>{release2=r;});
 const q=page({routes:async()=>{await pending2;return preflight(fourTargets());},gets:()=>rowAnswer([])});
 const third=q.c.loadChoose('lab',{type:'folder',path:'/c'},'Third');await settle();
 await q.click('data-load-action="cancel"');
 release2();await third;
 assert.doesNotMatch(q.body(),/Load Third\?/);
 assert.equal(q.calls.filter(c=>c.endpoint.endsWith('/restore')).length,0);
});
test('L1, L4: the differences drawer holds the review; Back shows the same confirmation with the same ticks and request id; any other close drops it',async()=>{
 const p=confirmPage(fourTargets());
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');
 await p.tick('clab-BGP-evo',false);
 const id=vm.runInContext('loadReview.requestId',p.c);
 await p.click('data-load-action="diff"');
 assert.equal(p.drawers[0].kind,'different');assert.equal(p.els['load-panel'].hidden,true,'the drawer closed the panel');
 assert.ok(vm.runInContext('loadReview && loadReview.drawer',p.c),'held while the drawer is open');
 p.els['save-drawer'].innerHTML=p.c.loadDifferentMarkup(p.drawers[0].opts.review).html;
 await p.click('data-load-action="diff-back"','save-drawer');
 assert.equal(p.els['load-panel'].hidden,false);assert.match(p.body(),/Load ospf-up\?/,'Back shows the same confirmation');
 assert.match(p.body(),/value="clab-BGP-evo"><span>/,'the tick that was removed stays removed');assert.match(p.body(),/value="clab-BGP-ceos" checked>/);
 assert.equal(vm.runInContext('loadReview.requestId',p.c),id,'the same request id');
 assert.equal(p.calls.length,1,'Back sends no new preflight');
 // Closed any other way: dropped.
 await p.click('data-load-action="diff"');
 p.els['save-drawer'].dispatch('close');
 assert.equal(vm.runInContext('loadReview',p.c),null);
 assert.equal(p.c.loadDifferentBack(),false,'Back without a held review shows no confirmation');
 assert.equal(p.els['load-panel'].hidden,true);
});
test('a double click on the red Load sends one request with one request id',async()=>{
 let answer;const gate=new Promise(r=>{answer=r;});
 const p=page({routes:async e=>{if(e.endsWith('/preflight'))return preflight(fourTargets());await gate;return {id:'job1',lab_id:'lab',status:'queued',targets:[]};}});
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');
 const one=p.click('data-load-action="run"'),two=p.click('data-load-action="run"');
 answer();await one;await two;
 const sent=p.calls.filter(c=>c.endpoint==='/labs/lab/restore');
 assert.equal(sent.length,1);assert.match(sent[0].body.request_id,/^[0-9a-f]{32}$/);
 // A failed submit keeps the confirmation and sends the same request id again (idempotent on the server).
 const q=page({routes:(e,m,b,n)=>{if(e.endsWith('/preflight'))return preflight(fourTargets());if(n===2)throw new Error('The lab is busy.');return {id:'job2',lab_id:'lab',status:'queued',targets:[]};}});
 await q.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');
 await q.c.loadSubmit();
 assert.match(q.body(),/<p class="form-error" role="alert">The lab is busy\.<\/p>/,'the server\'s 409 shows in the confirmation');assert.match(q.body(),/Load ospf-up\?/);
 await q.c.loadSubmit();
 assert.equal(q.calls[1].body.request_id,q.calls[2].body.request_id);
});

// ---- 13. the submit body and the five source keys (L3) -----------------------------------------------------------------------------
test('L3: the submit body is exactly request_id, source, node_names, confirm_minutes, acknowledge; every source has five keys; a folder carries the preflight\'s commit',async()=>{
 const p=confirmPage(fourTargets());
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest',commit:'',extra:'never sent'},'ospf-up');
 assert.deepEqual(Object.keys(p.calls[0].body.source).sort(),['backup_job_id','commit','path','repository','type']);
 assert.equal(p.calls[0].body.source.extra,undefined,'never a key of a richer object');
 for(const fn of p.els['load-panel'].listeners.change)fn({target:{id:'load-minutes',value:'90'}});
 const job=await p.c.loadSubmit();
 const body=p.calls[1].body;
 assert.equal(p.calls[1].endpoint,'/labs/lab/restore');
 assert.deepEqual(Object.keys(body).sort(),['acknowledge','confirm_minutes','node_names','request_id','source']);
 assert.equal(body.acknowledge,true);assert.equal(body.confirm_minutes,60,'the minutes are clamped to 2..60');
 assert.deepEqual(body.source,{type:'folder',commit:'c'.repeat(40),path:'/BGP/latest',backup_job_id:'',repository:''},'the commit the preflight read');
 assert.deepEqual(body.node_names,['clab-BGP-ceos','clab-BGP-evo','clab-BGP-vjunos','clab-BGP-xrv9k']);
 assert.equal(job.id,'job1');
 // After a successful submit: the review is dropped, the Load panel closes and the chip panel shows the progress.
 assert.equal(vm.runInContext('loadReview',p.c),null);assert.equal(p.els['load-panel'].hidden,true);assert.deepEqual(p.shown,['status']);
 assert.equal(vm.runInContext('loadWatching',p.c),'job1','the load is followed');
 for(const [source,expected] of [[{type:'git',commit:'e'.repeat(40),path:'checkpoints/day-1'},{type:'git',commit:'e'.repeat(40),path:'checkpoints/day-1',backup_job_id:'',repository:''}],
  [{type:'backup',backup_job_id:'b1'},{type:'backup',commit:'',path:'',backup_job_id:'b1',repository:''}]]){
  const q=page({routes:e=>e.endsWith('/preflight')?preflight(fourTargets(),{commit:'d'.repeat(40)}):{id:'j',lab_id:'lab',status:'queued',targets:[]}});
  await q.c.loadChoose('lab',source,'X');await q.c.loadSubmit();
  assert.equal(JSON.stringify(q.calls[1].body.source),JSON.stringify(q.c.loadSource(expected)),'git and backup sources are sent as chosen');
 }
 assert.deepEqual(Object.keys(p.c.loadSource({type:'folder',path:'/x',repository:'r1',targets:[]})),['type','commit','path','backup_job_id','repository']);
});

// ---- 14. the single sender ----------------------------------------------------------------------------------------------------------
test('single sender: `acknowledge: true` reaches a restore route from one place, loadSubmit, which only the two Load handlers call',()=>{
 const files=fs.readdirSync(STATIC).filter(f=>f.endsWith('.js'));
 const hits=[];
 for(const file of files){const text=read(file);for(const line of text.split('\n'))if(/acknowledge\s*:\s*true/.test(line)&&/\/restore/.test(line))hits.push({file,line});
  if(file!=='load.js'&&/\/restore'/.test(text))assert.doesNotMatch(text,/acknowledge\s*:\s*true/,file+' sends no acknowledgement to a restore route');}
 assert.equal(hits.length,1,JSON.stringify(hits));assert.equal(hits[0].file,'load.js');
 const load=read('load.js'),start=load.indexOf('async function loadSubmit('),end=load.indexOf('\n}\n',start);
 assert.ok(start>0&&hits[0].line&&load.slice(start,end).includes(hits[0].line),'inside loadSubmit');
 assert.doesNotMatch(read('restore.js'),/acknowledge\s*:/,'the old dialog\'s sender is gone');
 const code=text=>text.split('\n').filter(line=>!/^\s*\/\//.test(line)).join('\n');
 const calls=files.flatMap(f=>[...code(read(f)).matchAll(/(?<!function )loadSubmit\(\)/g)].map(m=>({f,i:m.index})));
 assert.equal(calls.length,2,'two calls: the red Load and the drawer\'s Load on n devices');
 assert.match(load,/case 'run':return loadSubmit\(\);\n\s*case 'diff-run':return loadSubmit\(\);/);
 for(const name of ['loadChoose','loadUndo','loadRetry','restoreFromVersion','restoreFromFolder','restoreReview']){
  const text=files.map(read).join('\n'),at=text.search(new RegExp('function '+name+'\\('));assert.ok(at>=0,name);
  assert.doesNotMatch(text.slice(at,text.indexOf('\n}\n',at)),/loadSubmit|acknowledge/,name+' ends in the confirmation, never in the submit');
 }
});

// ---- 15. the differences drawer (L4) --------------------------------------------------------------------------------------------
test('L4: the differences drawer says what its button does, shows ticked devices only, and is disabled with its reason',async()=>{
 const diff={identical:false,truncated:false,labels:{old:'Saved',new:'Running now'},hunks:[{old_start:1,old_count:1,new_start:1,new_count:1,lines:[{type:'del',text:'hostname <A>'}]}]};
 const targets=fourTargets().map(t=>({...t,diff:t.matches_saved?{identical:true,hunks:[]}:diff}));
 const p=confirmPage(targets);
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');
 let d=p.c.loadDifferentMarkup();
 assert.equal(d.title,'What\'s different');
 assert.match(d.meta,/^Ospf-up compared with what the devices run now · saved 2 days ago · c{10}$/);
 assert.match(d.html,/^<div class="save-row"><button type="button" class="button danger" id="load-diff-run" data-load-action="diff-run">Load on 4 devices<\/button><button[^>]*data-load-action="diff-back">Back<\/button><span class="caption" id="load-diff-reason" hidden><\/span><\/div>/);
 assert.equal((d.html.match(/<h3 class="save-heading">/g)||[]).length,3,'the device that already matches has no differences');
 assert.match(d.html,/hostname &lt;A&gt;/);
 await p.tick('clab-BGP-ceos',false);await p.tick('clab-BGP-evo',false);await p.tick('clab-BGP-vjunos',false);
 d=p.c.loadDifferentMarkup();
 assert.match(d.html,/>Load on 1 device<\/button>/);assert.equal((d.html.match(/<h3 class="save-heading">/g)||[]).length,1,'ticked devices only');assert.match(d.html,/xrv9k/);
 await p.tick('clab-BGP-xrv9k',false);
 d=p.c.loadDifferentMarkup();
 assert.match(d.html,/id="load-diff-run" data-load-action="diff-run" disabled>Load on 0 devices<\/button>/);assert.match(d.html,/id="load-diff-reason">Tick at least one device\.<\/span>/);
 await p.tick('clab-BGP-xrv9k',true);
 p.c.state.git_jobs=[{id:'g',lab_id:'lab',status:'exporting'}];
 d=p.c.loadDifferentMarkup();
 assert.match(d.html,/disabled>Load on 1 device<\/button>/);assert.match(d.html,/>A save is running\.<\/span>/);
 p.c.state.git_jobs=[];
 // The drawer's Load is the same submit, with the same request id.
 await p.click('data-load-action="diff"');p.els['save-drawer'].innerHTML=p.c.loadDifferentMarkup().html;
 const id=vm.runInContext('loadReview.requestId',p.c);
 await p.click('data-load-action="diff-run"','save-drawer');
 const sent=p.calls.find(c=>c.endpoint==='/labs/lab/restore');
 assert.equal(sent.body.request_id,id);assert.deepEqual(sent.body.node_names,['clab-BGP-xrv9k']);
 assert.equal(p.els['save-drawer'].open,false,'the drawer closes');assert.deepEqual(p.shown,['status']);
});
test('without the drawer script the differences show inside the panel, and Back returns to the confirmation',async()=>{
 const p=page({drawer:false,routes:e=>e.endsWith('/preflight')?preflight(fourTargets()):{}});
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');
 await p.click('data-load-action="diff"');
 assert.match(p.body(),/^<p class="save-state" tabindex="-1" data-panel-focus>What&#39;s different<\/p>/);
 await p.click('data-load-action="diff-back"');
 assert.match(p.body(),/Load ospf-up\?/);
});

// ---- 12, 17. retry (L2) ---------------------------------------------------------------------------------------------------------------
const partialJob=extra=>({id:'job9',lab_id:'lab',status:'partial',created:iso(NOW-120e3),finished:iso(NOW-60e3),pre_backup_job_id:'pre9',
 source:{type:'folder',path:'/course/final',folder:'course/final',commit:'f'.repeat(40),repository:'reg2',captured_at:iso(NOW-86400e3)},
 targets:[{name:'clab-BGP-ceos',short_name:'ceos',platform:'arista_ceos',status:'verified',stage:'replaced',timeline:{settled:1}},
  {name:'clab-BGP-xrv9k',short_name:'xrv9k',platform:'cisco_xrv9k',status:'failed',stage:'failed',message:'Configuration was not changed: The device refused the configuration.',timeline:{settled:1}},
  {name:'clab-BGP-vjunos',short_name:'vjunos',platform:'juniper_vjunosswitch',status:'rolled_back',stage:'rolled_back',timeline:{settled:1}},
  {name:'clab-BGP-evo',short_name:'evo',platform:'juniper_cjunosevolved',status:'uncertain',stage:'uncertain',timeline:{settled:1}}],...extra});
test('L2: a retry asks about the devices that were not loaded and lists exactly those; no page-derived row, no subset sentence, the retry note',async()=>{
 const job=partialJob();
 const p=page({state:{restore_jobs:[job],jobs:[{id:'pre9',status:'succeeded',source:'restore-pre',progress_id:'job9'}]},
  routes:e=>e.endsWith('/preflight')?preflight([target('ceos','arista_ceos',{requested:false}),target('xrv9k','cisco_xrv9k',{pending_changes:2}),target('vjunos','juniper_vjunosswitch'),target('evo','juniper_cjunosevolved',{requested:false})]):{id:'job10',lab_id:'lab',status:'queued',targets:[]}});
 assert.equal(p.c.loadRetryLabel(job),'Try 2 devices again');
 await p.c.loadRetry(job);
 const sent=p.calls[0].body;
 assert.deepEqual(sent.node_names,['clab-BGP-xrv9k','clab-BGP-vjunos']);
 assert.deepEqual(sent.source,{type:'folder',commit:'f'.repeat(40),path:'/course/final',backup_job_id:'',repository:'reg2'},'the same commit and repository, five keys');
 const html=p.body();
 assert.equal((html.match(/name="load-node"/g)||[]).length,2,'exactly the rows it asked about');
 assert.doesNotMatch(html,/clab-BGP-ceos|clab-BGP-evo|Not in this state|This state covers/);
 assert.match(html,/<p class="save-note">Only the devices that were not loaded are listed\.<\/p>/);
 await p.c.loadSubmit();
 const submit=p.calls[1].body;assert.match(submit.request_id,/^[0-9a-f]{32}$/);assert.deepEqual(submit.node_names,['clab-BGP-xrv9k','clab-BGP-vjunos']);
});
test('loadRetry rebuilds git and backup sources in five keys; the button names one device or is absent when nothing was left unchanged',async()=>{
 for(const [source,expected] of [[{type:'git',commit:'a'.repeat(40),path:'BGP/latest',repository:'r9',captured_at:'x'},{type:'git',commit:'a'.repeat(40),path:'BGP/latest',backup_job_id:'',repository:'r9'}],
  [{type:'backup',backup_job_id:'b7',saved_nodes:[]},{type:'backup',commit:'',path:'',backup_job_id:'b7',repository:''}]]){
  const p=page({routes:()=>preflight([])});
  await p.c.loadRetry(partialJob({source}));
  assert.equal(JSON.stringify(p.calls[0].body.source),JSON.stringify(expected));
 }
 const one=partialJob({targets:[partialJob().targets[0],partialJob().targets[1]]});
 const p=page();assert.equal(p.c.loadRetryLabel(one),'Try xrv9k again');
 const none=partialJob({targets:[partialJob().targets[0],partialJob().targets[3],{name:'clab-BGP-xrv9k',status:'applied_unverified'}]});
 assert.equal(p.c.loadRetryLabel(none),'');assert.equal(p.c.loadRetry(none),false);assert.equal(p.calls.length,0);
 const view=p.c.loadChipView({key:'partial'},makeLab());
 assert.equal(view,null,'no load state: no view');
});

// ---- 18. undo ---------------------------------------------------------------------------------------------------------------------
test('loadUndo: a backup source in five keys through the same confirmation; Undo loading X?, and Load X again? for the undo of an undo',async()=>{
 const job=partialJob({status:'succeeded',targets:[partialJob().targets[0]]});
 const jobs=[{id:'pre9',status:'partial',source:'restore-pre',progress_id:'job9',nodes:[]}];
 const p=page({state:{restore_jobs:[job],jobs},routes:()=>preflight([target('ceos','arista_ceos')])});
 const states={head:'',states:[{path:'course/final',name:'Final',group:'state'}]};
 vm.runInContext('loadStates',p.c).set('lab',{repository:'',answer:states});
 await p.c.loadUndo(job);
 assert.deepEqual(p.calls[0].body,{source:{type:'backup',commit:'',path:'',backup_job_id:'pre9',repository:''}},'a partial safety backup can be undone (B4)');
 assert.match(p.body(),/>Undo loading Final\?<\/p>/);
 assert.match(p.body(),/<p class="save-note">This undoes the load on the device it changed\. The others are left as they are\.<\/p>/,'the backup covers fewer devices than the lab');
 // The undo of that undo loads Final again.
 const undo={...job,id:'job11',source:{type:'backup',backup_job_id:'pre9'},pre_backup_job_id:'pre11',finished:iso(NOW)};
 const q=page({state:{restore_jobs:[job,undo],jobs:[...jobs,{id:'pre11',status:'succeeded',source:'restore-pre',progress_id:'job11'}]},routes:()=>preflight([target('ceos','arista_ceos')])});
 vm.runInContext('loadStates',q.c).set('lab',{repository:'',answer:states});
 await q.c.loadUndo(undo);
 assert.deepEqual(q.calls[0].body.source.backup_job_id,'pre11');assert.match(q.body(),/>Load Final again\?<\/p>/);
 assert.doesNotMatch(q.body(),/from before the configuration from before/,'the name never nests');
});
test('loadUndo is unavailable when the backup is no longer kept or failed, and absent for a job without one or a load that changed nothing',()=>{
 const job=partialJob();
 const p=page({state:{restore_jobs:[job],jobs:[]}});
 assert.equal(p.c.loadUndo(job),false);
 const ls=p.c.loadState(p.lab,p.c.state);
 assert.equal(ls.undo.available,false);assert.equal(ls.undo.reason,'The automatic backup of this load is no longer kept.');
 const view=p.c.loadChipView(p.c.saveChipState(p.lab,p.c.state),p.lab);
 assert.match(view.html,/<button type="button" class="button ghost small" id="load-undo" data-load-action="undo" data-load-job="job9" disabled>Undo this load<\/button>/);
 assert.match(view.html,/<p class="save-note">The automatic backup of this load is no longer kept\.<\/p>/,'the reason is visible text');
 p.c.state.jobs=[{id:'pre9',status:'failed'}];assert.equal(p.c.loadUndo(job),false,'a failed backup is never loaded');
 const none={...job,pre_backup_job_id:''};p.c.state.restore_jobs=[none];
 assert.equal(p.c.loadUndo(none),false);
 assert.doesNotMatch(p.c.loadChipView(p.c.saveChipState(p.lab,p.c.state),p.lab).html,/Undo this load/,'no backup: no Undo');
 const nothing={...job,status:'failed',targets:[job.targets[1],{...job.targets[2],status:'interrupted',stage:'failed',timeline:{settled:1}}]};
 p.c.state.restore_jobs=[nothing];p.c.state.jobs=[{id:'pre9',status:'succeeded'}];
 assert.equal(p.c.loadUndo(nothing),false,'a load that changed nothing is not undone');
 assert.equal(p.calls.length,0);
});

// ---- the chip panel's load views (G04, G05, G06) ----------------------------------------------------------------------------------
test('loading view: device words from loadDeviceWord only, Loaded never before the check, the chip panel follows the job',()=>{
 const job={id:'job5',lab_id:'lab',status:'applying',created:iso(NOW),source:{type:'folder',path:'/course/final'},targets:[
  {name:'clab-BGP-ceos',short_name:'ceos',platform:'arista_ceos',status:'verified',stage:'replaced'},
  {name:'clab-BGP-evo',short_name:'evo',platform:'juniper_cjunosevolved',status:'applied',stage:'checking'},
  {name:'clab-BGP-vjunos',short_name:'vjunos',platform:'juniper_vjunosswitch',status:'backing_up',stage:'backing_up'},
  {name:'clab-BGP-xrv9k',short_name:'xrv9k',platform:'cisco_xrv9k',status:'pending',stage:'queued'}]};
 const p=page({state:{restore_jobs:[job]}});
 vm.runInContext('loadStates',p.c).set('lab',{repository:'',answer:{states:[{path:'course/final',name:'Final',group:'state'}]}});
 const cs=p.c.saveChipState(p.lab,{...p.c.state,states:[{path:'course/final',name:'Final',group:'state'}]});
 assert.equal(cs.text,'Loading… 1 of 4');
 const view=p.c.loadChipView(cs,p.lab);
 assert.equal(view.title,'Loading Final…');assert.equal(view.dot,'busy');
 assert.match(view.html,/^<p class="save-sub">Each device checks the new configuration itself and undoes it if it loses contact\. You can keep working\.<\/p><ul class="save-devices">/);
 assert.match(view.html,/<li><span>ceos <small>EOS<\/small><\/span><span class="save-end ok">Loaded<\/span><\/li>/);
 assert.match(view.html,/<span>evo <small>Junos Evolved<\/small><\/span><span class="save-end now">Loading…<\/span>/,'replaced, still under the check: Loading…, never Loaded');
 assert.match(view.html,/<span class="save-end now">Backing up…<\/span>/);assert.match(view.html,/<span class="save-end">Waiting<\/span>/);
 assert.doesNotMatch(view.key,/\d{4}-\d\d-\d\d/,'no time in the key');
 assert.equal(vm.runInContext('loadWatching',p.c),'job5','an open loading view follows the job every 1.5 s');
 for(const name of classes(view.html))assert.ok(ALLOWED.has(name),name);
});
test('result views: Running with all or a subset of devices, Partial with the service\'s words, Kept previous only for rolled_back, uncertain is Not confirmed',()=>{
 const ok={id:'job7',lab_id:'lab',status:'succeeded',created:iso(NOW-60e3),finished:iso(NOW-60e3),pre_backup_job_id:'pre7',source:{type:'folder',path:'/course/final'},
  targets:['ceos','xrv9k','vjunos','evo'].map(s=>({name:'clab-BGP-'+s,short_name:s,platform:'arista_ceos',status:'verified',stage:'replaced'}))};
 const p=page({state:{restore_jobs:[ok],jobs:[{id:'pre7',status:'succeeded',source:'restore-pre',progress_id:'job7'}],git_jobs:[{id:'g0',lab_id:'lab',target:'latest',status:'synced',note:'Interfaces up',captured:true,created:iso(NOW-3600e3),finished:iso(NOW-3600e3)}]}});
 vm.runInContext('loadStates',p.c).set('lab',{repository:'',answer:{states:[{path:'course/final',name:'Final',group:'state'}]}});
 let view=p.c.loadChipView(p.c.saveChipState(p.lab,{...p.c.state,states:[{path:'course/final',name:'Final',group:'state'}]}),p.lab);
 assert.equal(view.title,'Running Final');assert.equal(view.dot,'info');
 assert.match(view.html,/^<p class="save-sub">Loaded 1 minute ago on all 4 devices\.<\/p><p class="save-kv"><span>Your latest save:<\/span> Interfaces up, 1 hour ago<\/p><p class="save-kv"><span>Before loading:<\/span> backed up automatically<\/p><div class="save-foot"><button[^>]*id="load-undo" data-load-action="undo" data-load-job="job7">Undo this load<\/button><button[^>]*data-load-action="details" data-load-job="job7">What changed<\/button><\/div>$/);
 const subset={...ok,targets:ok.targets.slice(0,2)};p.c.state.restore_jobs=[subset];
 view=p.c.loadChipView(p.c.saveChipState(p.lab,p.c.state),p.lab);
 assert.match(view.html,/Loaded 1 minute ago on 2 devices\./,'a subset never says "all"');
 const job=partialJob({pre_backup_job_id:'pre7'});p.c.state.restore_jobs=[job];
 view=p.c.loadChipView(p.c.saveChipState(p.lab,p.c.state),p.lab);
 assert.equal(view.title,'Loaded on 1 of 4 devices');assert.equal(view.dot,'warn');
 assert.match(view.html,/<p class="save-sub">The manager could not confirm what evo runs\. Open Details before relying on it\. vjunos undid the change and runs its previous configuration again\. xrv9k was not changed\.<\/p>/);
 assert.match(view.html,/<span>xrv9k <small>IOS XR<\/small><span class="save-why">The device refused the configuration\.<\/span><\/span><span class="save-end bad">Not loaded<\/span>/,'failed reads Not loaded with the service\'s reason, never Kept previous');
 assert.match(view.html,/<span class="save-why">Undid the change; its previous configuration was read back\.<\/span><\/span><span class="save-end bad">Kept previous<\/span>/);
 assert.match(view.html,/<span class="save-why">The manager could not confirm what this device runs\. Open Details\.<\/span><\/span><span class="save-end warn">Not confirmed<\/span>/);
 assert.equal((view.html.match(/Kept previous/g)||[]).length,1,'Kept previous for rolled_back only');
 assert.match(view.html,/<div class="save-row"><button type="button" class="button primary" id="load-retry" data-load-action="retry" data-load-job="job9">Try 2 devices again<\/button><button[^>]*data-load-action="undo"[^>]*>Undo this load<\/button><button[^>]*data-load-action="details"[^>]*>Details<\/button><\/div>/);
 const unverified={...job,targets:[job.targets[0],{...job.targets[1],status:'applied_unverified',stage:'replaced'}]};
 assert.equal(p.c.loadPartialSentence(unverified),'xrv9k was loaded, but the check afterwards did not confirm it. Open Details.');
 assert.equal(p.c.loadPartialSentence({targets:[{status:'failed'},{status:'ineligible'},{status:'uncertain'},{status:'interrupted'}]}),'The manager could not confirm what 2 devices run. Open Details before relying on them. 2 devices were not changed.');
 for(const name of classes(view.html))assert.ok(ALLOWED.has(name),name);
});
test('the chip panel\'s buttons: Undo and Try again start a confirmation, What changed and Details open the job window',async()=>{
 const job=partialJob();
 const opened=[];
 const p=page({state:{restore_jobs:[job],jobs:[{id:'pre9',status:'succeeded',source:'restore-pre',progress_id:'job9'}]},routes:()=>preflight(fourTargets()),
  globals:{}});
 p.c.restoreShowJob=async(id,known,opener)=>{opened.push({id,opener});};
 const view=p.c.loadChipView(p.c.saveChipState(p.lab,p.c.state),p.lab);
 p.els['save-panel'].hidden=false;p.els['save-panel'].innerHTML=view.html;
 await p.click('data-load-action="details"','save-panel');
 assert.deepEqual(opened.map(o=>o.id),['job9']);assert.equal(opened[0].opener,p.els['save-chip'],'focus returns to the chip');
 await p.click('data-load-action="undo"','save-panel');
 assert.equal(p.calls[0].body.source.backup_job_id,'pre9');assert.equal(p.els['load-panel'].hidden,false);assert.match(p.body(),/Undo loading Final\?|Undo loading /);
 p.els['save-panel'].innerHTML=view.html;
 await p.click('data-load-action="retry"','save-panel');
 assert.deepEqual(p.calls[1].body.node_names,['clab-BGP-xrv9k','clab-BGP-vjunos']);
 assert.equal(p.calls.filter(c=>c.endpoint.endsWith('/restore')).length,0,'none of them submits');
});

// ---- 20. the toast (O5) ---------------------------------------------------------------------------------------------------------------
test('O5: the toast fires once, for a load that succeeded only, when the page sees it leave the active set',()=>{
 const running={id:'job3',lab_id:'lab',status:'applying',source:{type:'folder',path:'/course/final'},targets:[{name:'clab-BGP-ceos',status:'applying'},{name:'clab-BGP-xrv9k',status:'applying'}]};
 const p=page({state:{restore_jobs:[running]}});
 vm.runInContext('loadStates',p.c).set('lab',{repository:'',answer:{states:[{path:'course/final',name:'Final',group:'state'}]}});
 p.c.loadRender();assert.deepEqual(p.toasts,[]);
 p.c.state.restore_jobs=[{...running,status:'succeeded',targets:running.targets.map(t=>({...t,status:'verified',stage:'replaced'}))}];
 p.c.loadRender();p.c.loadRender();
 assert.deepEqual(p.toasts,['Final loaded on 2 devices.']);
 for(const status of ['partial','needs_attention','failed','preflight_failed','interrupted']){
  const q=page({state:{restore_jobs:[running]}});q.c.loadRender();
  q.c.state.restore_jobs=[{...running,status,targets:[{name:'clab-BGP-ceos',status:'verified'},{name:'clab-BGP-xrv9k',status:'failed'}]}];q.c.loadRender();
  assert.deepEqual(q.toasts,[],status+' has no toast');
 }
 const r=page({state:{restore_jobs:[{...running,status:'succeeded',targets:[{name:'clab-BGP-ceos',status:'verified'}]}]}});r.c.loadRender();
 assert.deepEqual(r.toasts,[],'a load already finished when the page opened has no toast');
});
test('a load that changed nothing, ending while the chip panel showed it, is shown in the Load panel: was not loaded, no review, no red button',async()=>{
 const running={id:'job4',lab_id:'lab',status:'applying',source:{type:'folder',path:'/course/final'},targets:[{name:'clab-BGP-xrv9k',short_name:'xrv9k',platform:'cisco_xrv9k',status:'applying'}]};
 const done={...running,status:'failed',targets:[{...running.targets[0],status:'failed',stage:'failed',message:'Configuration was not changed. Connectivity: TimeoutError',timeline:{settled:1}}]};
 const p=page({state:{restore_jobs:[running]},gets:()=>done});
 vm.runInContext('loadStates',p.c).set('lab',{repository:'',answer:{states:[{path:'course/final',name:'Final',group:'state'}]}});
 p.els['save-panel'].hidden=false;
 p.c.loadWatch(running);await p.timers.shift()();await settle();
 assert.equal(p.els['load-panel'].hidden,false);
 assert.match(p.body(),/^<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot bad" aria-hidden="true"><\/span>Final was not loaded<\/p><p class="save-sub">No device was changed\.<\/p>/);
 assert.match(p.body(),/The device did not answer over SSH\./);assert.match(p.body(),/data-load-action="retry"[^>]*>Try again</);assert.match(p.body(),/>Details</);
 assert.doesNotMatch(p.body(),/button danger|Undo this load/);assert.equal(vm.runInContext('loadReview',p.c),null);
 assert.deepEqual(p.toasts,[]);
});
test('a failed status poll pauses the loading view with Refresh, outside any live region',async()=>{
 const job={id:'job6',lab_id:'lab',status:'applying',source:{type:'backup',backup_job_id:'b'},targets:[{name:'clab-BGP-ceos',status:'applying',stage:'applying'}]};
 const p=page({state:{restore_jobs:[job]},gets:()=>new Error('offline')});
 p.c.loadWatch(job);await p.timers.shift()();await settle();
 const html=p.c.loadJobMarkup(job);
 assert.match(html,/<p class="save-note">Status updates paused\. <button type="button" class="button ghost small" id="load-resume" data-load-action="resume" data-load-job="job6">Refresh<\/button><\/p>/);
 assert.doesNotMatch(html,/role="status"|aria-live/);
});

// ---- 21. disabled states (D1) ---------------------------------------------------------------------------------------------------------
test('D1: the Load button is disabled only while a load of the lab runs; a row chosen during a save sends no request and says why',async()=>{
 const p=page({gets:()=>rowAnswer([stateRow('course/final','state',{name:'Final'})])});
 const lab=p.lab,cs=extra=>p.c.saveChipState(lab,{...p.c.state,...extra});
 assert.equal(cs({restore_jobs:[{id:'r',lab_id:'lab',status:'applying',targets:[]}]}).loadDisabled,true);
 for(const extra of [{git_jobs:[{id:'g',lab_id:'lab',status:'capturing'}]},{jobs:[{id:'b',lab_id:'lab',status:'running'}]},{operations:[{id:'o',lab_id:'lab',status:'running',action:'deploy'}]},{restore_jobs:[{id:'r',lab_id:'other',status:'applying',targets:[]}]}])
  assert.equal(cs(extra).loadDisabled,false,JSON.stringify(extra));
 p.c.state.git_jobs=[{id:'g',lab_id:'lab',status:'capturing',target:'latest'}];
 await p.open();await p.click('data-load-row="0"');
 assert.equal(p.calls.length,0,'no preflight during a save');
 assert.match(p.body(),/<span class="save-dot bad" aria-hidden="true"><\/span>Final cannot be loaded right now\.<\/p><p class="save-sub">A save is running\.<\/p><div class="save-row"><button[^>]*data-load-action="again">Try again<\/button><button[^>]*data-load-action="back">Back<\/button><\/div>/);
 p.c.state.git_jobs=[];
 await p.click('data-load-action="again"');
 assert.equal(p.calls.length,1,'Try again runs the preflight once the save ended');
 // A preflight the server refuses shows the manager's sentence.
 const q=page({routes:()=>{throw new Error('A backup is running on this lab.');}});
 await q.c.loadChoose('lab',{type:'folder',path:'/x'},'final');
 assert.match(q.body(),/Final cannot be loaded right now\.<\/p><p class="save-sub">A backup is running on this lab\.<\/p>/);
 // loadChoose does nothing while a load of the lab runs, or for a lab not on screen.
 const r=page({state:{restore_jobs:[{id:'x',lab_id:'lab',status:'applying',targets:[]}]}});
 assert.equal(await r.c.loadChoose('lab',{type:'folder',path:'/x'},'X'),false);assert.equal(await r.c.loadChoose('other',{type:'folder',path:'/x'},'X'),false);assert.equal(r.calls.length,0);
});

// ---- 22. focus and listeners (A2) -------------------------------------------------------------------------------------------------
test('A2: every view holds exactly one data-panel-focus element with tabindex -1; load.js adds no document or window listener',async()=>{
 const views=[];
 const p=confirmPage(fourTargets(),{gets:()=>rowAnswer([stateRow('BGP/latest','latest')])});
 await p.open();views.push(p.body());
 const pending=p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');views.push(p.body());await pending;views.push(p.body());
 const q=page({routes:()=>{throw new Error('no');}});await q.c.loadChoose('lab',{type:'folder',path:'/x'},'X');views.push(q.body());
 const stopped=page({lab:makeLab({deployment:{status:'Stopped'}})});await stopped.open();views.push(stopped.body());
 const none=page({lab:makeLab({git_binding:null}),gets:()=>({repositories:[],default:null})});await none.open();views.push(none.body());
 const broken=page({gets:()=>new Error('The lab VM could not be reached.')});await broken.open();views.push(broken.body());
 for(const html of views){assert.equal(focusCount(html),1,html);assert.match(html,/tabindex="-1" data-panel-focus/);for(const name of classes(html))assert.ok(ALLOWED.has(name),name);}
 assert.match(broken.body(),/<p class="save-sub">The saved states could not be read from the lab VM\.<\/p><p class="form-error" role="alert">The lab VM could not be reached\.<\/p><div class="save-row"><button[^>]*data-load-action="reload">Try again<\/button><\/div><div class="save-foot">/);
 const source=read('load.js');
 assert.doesNotMatch(source,/(document|window|globalThis|location|history)\s*\.\s*addEventListener/);assert.doesNotMatch(source,/localStorage|sessionStorage|style=/);
 assert.ok(p.els['load-button'].focused===0,'the danger button is never focused automatically');
 assert.doesNotMatch(p.body().match(/<button[^>]*danger[^>]*>/)[0],/data-panel-focus|autofocus/);
});

// ---- 23. not running, no save location, no repository ----------------------------------------------------------------------------------
test('not running: the Start lab view, no request; its button runs the header\'s start and shows its reason when it is disabled',async()=>{
 const started=[];
 const p=page({lab:makeLab({deployment:{status:'Not deployed'}}),globals:{startLab:()=>started.push(1)}});
 p.els['lab-start'].disabled=true;p.els['lab-start'].reason={textContent:'A backup is running.'};
 await p.open();
 assert.match(p.body(),/^<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot none" aria-hidden="true"><\/span>Start the lab to load a state<\/p><p class="save-sub">Loading puts a saved configuration onto running devices\. This lab is not running\.<\/p><div class="save-row"><button type="button" class="button primary" id="load-start" data-load-action="start" disabled>Start lab<\/button><span class="caption">A backup is running\.<\/span><\/div>$/);
 assert.deepEqual(p.gets,[]);assert.equal(p.calls.length,0);
 p.els['lab-start'].disabled=false;p.close();await p.open();
 await p.click('data-load-action="start"');assert.deepEqual(started,[1]);assert.equal(p.els['load-panel'].hidden,true);
});
test('no save location: the places request, then the states of the default repository; From <repository>.; every source carries the repository',async()=>{
 const p=page({lab:makeLab({git_binding:null}),routes:()=>preflight(fourTargets()),
  gets:e=>e==='/labs/lab/git/places'?{repositories:[{id:'reg1',name:'Other'},{id:'reg2',name:'Course-Labs'}],default:{repository:'reg2',folder:'BGP'}}:e==='/labs/lab/restore/states?repository=reg2'?rowAnswer([stateRow('course/start','state',{name:'Start'})]):{}});
 await p.open();
 assert.deepEqual(p.gets,['/labs/lab/git/places','/labs/lab/restore/states?repository=reg2']);
 assert.match(p.body(),/<p class="save-sub">This lab has no saves of its own yet\. You can start from one of these\.<\/p><h3 class="save-heading">Lab states<\/h3>/);
 assert.doesNotMatch(p.body(),/Your saves/);
 assert.match(p.body(),/<p class="save-note">From Course-Labs\.<\/p><div class="save-foot">/);
 await p.click('data-load-row="0"');
 assert.equal(p.calls[0].body.source.repository,'reg2');
 await p.c.loadSubmit();assert.equal(p.calls[1].body.source.repository,'reg2');
 await p.open();await p.click('data-load-action="all"');assert.equal(p.drawers[0].opts.repository,'reg2');
});
test('no repository on the VM: "There is nothing to load yet" with Save…, and no foot; a lab with saves but no lab states, and an empty repository',async()=>{
 const p=page({lab:makeLab({git_binding:null}),gets:()=>({repositories:[],default:null})});
 await p.open();
 assert.match(p.body(),/^<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot none" aria-hidden="true"><\/span>There is nothing to load yet<\/p><p class="save-sub">No repository is connected to this lab VM\. Save this lab once to connect one, or ask your instructor for the course repository's address\.<\/p><div class="save-row"><button type="button" class="button primary" id="load-save" data-load-action="save">Save…<\/button><\/div>$/);
 assert.doesNotMatch(p.body(),/All versions|Browse the repository/);
 await p.click('data-load-action="save"');assert.deepEqual(p.shown,['status']);assert.equal(p.els['load-panel'].hidden,true);
 const q=page({gets:()=>rowAnswer([])});await q.open();
 assert.match(q.body(),/Nothing is saved in this repository yet\. Save this lab, or ask your instructor for the course's lab states\./);
 const r=page({gets:()=>rowAnswer([stateRow('BGP/latest','latest')])});await r.open();
 assert.doesNotMatch(r.body(),/no saves of its own|Lab states/);
});

// ---- parity (LOAD.md section 9) ---------------------------------------------------------------------------------------------------------
test('parity: restoreFromVersion, restoreFromFolder, restoreReview and the job window\'s Load this backup… each lead to a confirmation',async()=>{
 const job=partialJob({source:{type:'git',commit:'a'.repeat(40),path:'BGP/latest'}});
 const p=page({state:{restore_jobs:[job],jobs:[{id:'pre9',status:'succeeded',source:'restore-pre',progress_id:'job9'}]},routes:()=>preflight(fourTargets())});
 const confirmed=()=>/<span class="save-dot warn" aria-hidden="true"><\/span>(Load |Undo loading )[^<]*\?<\/p>/.test(p.body());
 await p.c.restoreFromVersion('lab',{type:'git',commit:'b'.repeat(40),path:'BGP/checkpoints/day-1'},'day-1');
 assert.ok(confirmed());assert.deepEqual(p.calls.at(-1).body.source,{type:'git',commit:'b'.repeat(40),path:'BGP/checkpoints/day-1',backup_job_id:'',repository:''});
 await p.c.restoreFromFolder('lab','course/final',{repository:{path:'/home/ben/Course-Labs'}});
 assert.ok(confirmed());assert.deepEqual(p.calls.at(-1).body.source,{type:'folder',commit:'',path:'/course/final',backup_job_id:'',repository:''});assert.match(p.body(),/>Load Final\?<\/p>/,'the headline is the state’s name alone, never its repository or folder (integration seam 8)');assert.doesNotMatch(p.body(),/Course-Labs|course\/final\?/);
 await p.c.restoreReview('lab',{type:'backup',backup_job_id:'b1'},'A backup');
 assert.ok(confirmed());assert.equal(p.calls.at(-1).body.source.backup_job_id,'b1');
 // The job window's Load this backup… (rendered by restoreRenderJob) ends in loadUndo, which ends in a confirmation.
 const button={onclick:null},detail={innerHTML:'',querySelectorAll:sel=>sel==='[data-restore-load-backup]'?[button]:[]};
 const dialog={open:true,querySelector:()=>({textContent:''}),close(){this.open=false;}};
 const before=p.c.$;p.c.$=id=>id==='restore-job-dialog'?dialog:id==='restore-job-detail'?detail:before(id);
 vm.runInContext('restoreDialogJob="job9"',p.c);p.c.restoreRenderJob(job);
 assert.match(detail.innerHTML,/Load this backup…/);
 await button.onclick();await settle();p.c.$=before;
 assert.equal(dialog.open,false,'the window closes first');assert.equal(p.calls.at(-1).body.source.backup_job_id,'pre9');assert.ok(confirmed());
 assert.equal(p.calls.filter(c=>c.endpoint.endsWith('/restore')).length,0,'no entry point submits');
});
test('loadOpen always lands on the list; a page without the Load panel sends no preflight',async()=>{
 const p=confirmPage(fourTargets(),{gets:()=>rowAnswer([stateRow('BGP/latest','latest')])});
 await p.c.loadChoose('lab',{type:'folder',path:'/BGP/latest'},'ospf-up');p.close();
 vm.runInContext('loadReview={labId:"lab",keep:true,phase:"confirm",chosen:new Set()}',p.c);
 p.c.loadOpen('lab');await settle();
 assert.match(p.body(),/Load a saved state/);assert.equal(vm.runInContext('loadReview',p.c),null);
 const q=page({globals:{openPanel:()=>false}});q.els['load-button']._menuOpen=undefined;
 assert.equal(await q.c.loadChoose('lab',{type:'folder',path:'/x'},'X'),false);
 assert.equal(q.calls.length,0);assert.equal(vm.runInContext('loadReview',q.c),null);
});
