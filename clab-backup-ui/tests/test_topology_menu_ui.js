// topology.js: the device context menu (order, roles, inline reasons, lab guard, keyboard), map state
// applied by class swaps without rebuilding the SVG, the loading / empty / caption states of the map
// stage, and the Escape order with the expanded map. The DOM is a set of stubs looked up by id.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function stub(id){
 const classes=new Set();
 return {id,hidden:false,disabled:false,textContent:'',innerHTML:'',title:'',dataset:{},style:{},attrs:{},open:false,offsetWidth:200,offsetHeight:120,focused:0,
  classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c),toggle(c,force){const on=force===undefined?!classes.has(c):!!force;if(on)classes.add(c);else classes.delete(c);return on;},list:()=>[...classes]},
  listeners:{},addEventListener(name,fn){(this.listeners[name]=this.listeners[name]||[]).push(fn);},
  setAttribute(n,v){this.attrs[n]=String(v);},getAttribute(n){return n in this.attrs?this.attrs[n]:null;},removeAttribute(n){delete this.attrs[n];},
  querySelector(){return null;},querySelectorAll(){return [];},closest(){return null;},focus(){this.focused++;},click(){},reset(){},showModal(){this.open=true;},close(){this.open=false;},
  setPointerCapture(){},getBoundingClientRect(){return {left:0,top:0,right:10,bottom:10,width:10,height:10};},contains(){return false;}};
}
function mapNode(name,label){const n=stub('node-'+name);n.dataset={mapNode:name,label};n.title={textContent:''};n.querySelector=sel=>sel==='title'?n.title:null;return n;}
function harness({lab,drawing,captureAttrs='',busy=false,jsonImpl}={}){
 const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,stub(id));return elements.get(id);};
 const docListeners={},winListeners={};
 const document={activeElement:null,addEventListener(name,fn){(docListeners[name]=docListeners[name]||[]).push(fn);},querySelector(){return null;},querySelectorAll(){return [];},createElement:()=>stub('a')};
 const window={innerWidth:1366,innerHeight:768,addEventListener(name,fn){winListeners[name]=fn;}};
 const nodeMenu=$('node-context-menu');nodeMenu.hidden=true;nodeMenu.querySelector=()=>({focus(){nodeMenu.focused++;}});
 const calls={openDetails:[],handleNodeAction:0,notify:[],api:[],json:[],refresh:0};
 const context=vm.createContext({$,esc,document,window,console,URLSearchParams,JSON,activeId:lab?lab.id:'',state:{labs:lab?[lab]:[]},busy:()=>busy,openDetails(n){calls.openDetails.push(n);},handleNodeAction(){calls.handleNodeAction++;},notify(m){calls.notify.push(m);},
  api:async url=>{calls.api.push(url);return {json:async()=>drawing===undefined?null:drawing};},topologyMarkup:d=>'<g data-nodes="'+d.nodes.length+'"></g>',measureTopology:()=>[0,0,100,50],syncProxies(){calls.synced=(calls.synced||0)+1;},setTimeout(){},closeMenus:()=>false,captureActionAttrs:()=>captureAttrs,
  json:async(path,method,data)=>{calls.json.push({path,method,data});return jsonImpl?jsonImpl(path,method,data):{started:0,skipped:[],at:''};},refresh:async()=>{calls.refresh++;}});
 context.current=()=>context.state.labs.find(l=>l.id===context.activeId);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/topology.js'),'utf8'),context);
 return {context,$,nodeMenu,docListeners,winListeners,calls,document};
}
const lab=()=>({id:'a',name:'Lab A',nodes:[
 {name:'r1',short_name:'R1',ssh_ready:true,readiness:'Ready',nos_login:{status:'ready'}},
 {name:'r2',short_name:'R2',ssh_ready:false,login_configured:true,readiness:'Ready',nos_login:{status:'booting'}},
 {name:'r3',short_name:'R3',ssh_ready:false,login_configured:true,readiness:'Ready',nos_login:{status:'failed'}},
 {name:'r4',short_name:'R4',ssh_ready:false,available:false,readiness:'Lab unavailable',nos_login:{status:'unavailable'}},
 {name:'r5',short_name:'R5',ssh_ready:false,login_configured:false,readiness:'Needs credentials',nos_login:{status:'needs_credentials'}},
 {name:'r6',short_name:'R6',ssh_ready:false,login_configured:true,readiness:'Choose NOS',nos_login:{status:'booting'}}]});
const element=name=>({dataset:{mapNode:name},focus(){}});
function items(html){return [...html.matchAll(/<button[^>]*role="menuitem"[^>]*data-(\w+)="([^"]*)"([^>]*)>([\s\S]*?)<\/button>/g)].map(m=>({kind:m[1],node:m[2],attrs:m[3],body:m[4]}));}

test('the context menu leads with Open CLI, shows the state instead of the address and explains every disabled item inline',()=>{
 const h=harness({lab:lab(),captureAttrs:'disabled title="Packet capture is not enabled."'});
 h.context.openNodeMenu(element('r2'),100,100);
 const html=h.nodeMenu.innerHTML,list=items(html);
 assert.deepEqual(list.map(i=>i.kind),['terminal','capture','backup','details'],'student order: CLI, capture, backup, details');
 assert.equal(list.length,4);assert.equal(h.nodeMenu.hidden,false);assert.equal(h.nodeMenu.focused,1,'the first enabled item takes focus');
 assert.match(html,/<div class="context-node-name">R2<span class="pill warn">Starting<\/span><\/div>/,'the header carries the state pill');
 assert.doesNotMatch(html,/\d+\.\d+\.\d+\.\d+|:22/,'the management address stays in the device panel');
 assert.match(list[0].attrs,/disabled title="R2 is still starting/);assert.match(list[0].body,/<small>R2 is still starting\. SSH opens automatically when it answers\. Use Test logins \(above\) or this device&#39;s Test login to check again now\.<\/small>/);
 assert.match(list[0].body,/Open CLI <span class="external" aria-hidden="true">↗<\/span>/);
 assert.match(list[1].attrs,/disabled/);assert.match(list[1].body,/<small>Packet capture isn’t set up on this VM yet — see Tools › Packet capture\.<\/small>/);
 assert.doesNotMatch(list[2].attrs,/disabled/,'a Ready device can be backed up');assert.doesNotMatch(list[2].body,/<small>/);
 assert.equal(list[3].body,'Device details');
 assert.doesNotMatch(html,/›_|ⓘ|↓/,'no text glyphs');
 h.context.openNodeMenu(element('r1'),0,0);const ready=items(h.nodeMenu.innerHTML);
 assert.doesNotMatch(ready[0].attrs,/disabled/);assert.doesNotMatch(ready[0].body,/<small>/);assert.match(h.nodeMenu.innerHTML,/<span class="pill ok">Ready<\/span>/);
 const enabledCapture=harness({lab:lab()});enabledCapture.context.openNodeMenu(element('r1'),0,0);
 assert.doesNotMatch(items(enabledCapture.nodeMenu.innerHTML)[1].attrs,/disabled/);
});

test('backup reasons follow readiness and the busy flag; unavailable and credential states read as sentences',()=>{
 const h=harness({lab:lab()});
 const reasons={};for(const name of ['r3','r4','r5','r6']){h.context.openNodeMenu(element(name),0,0);const list=items(h.nodeMenu.innerHTML);reasons[name]={cli:list[0],backup:list[2],header:h.nodeMenu.innerHTML.match(/<span class="pill [^"]*">([^<]*)<\/span>/)[1]};}
 assert.equal(reasons.r3.header,'Needs attention');assert.match(reasons.r3.cli.body,/R3 is running, but SSH login failed with the saved credentials\./);assert.doesNotMatch(reasons.r3.backup.attrs,/disabled/);
 assert.equal(reasons.r4.header,'Unavailable');assert.match(reasons.r4.cli.body,/R4 is not running/);assert.match(reasons.r4.backup.body,/<small>The lab is not running<\/small>/);assert.match(reasons.r4.backup.attrs,/disabled title="The lab is not running"/);
 assert.equal(reasons.r5.header,'Needs credentials');assert.match(reasons.r5.cli.body,/Add login credentials to open the CLI of R5\./);assert.match(reasons.r5.backup.body,/<small>Add credentials first<\/small>/);
 assert.match(reasons.r6.backup.body,/<small>Choose the network OS first<\/small>/);
 const busy=harness({lab:lab(),busy:true});busy.context.openNodeMenu(element('r1'),0,0);
 assert.match(items(busy.nodeMenu.innerHTML)[2].body,/<small>Another task is running<\/small>/);
});

test('menu clicks are ignored after switching labs; arrow keys rove over enabled items; Escape restores focus',()=>{
 const h=harness({lab:lab()});const target=element('r1');
 h.context.openNodeMenu(target,0,0);h.context.activeId='b';
 for(const fn of h.nodeMenu.listeners.click)fn({target:{}});
 assert.equal(h.calls.handleNodeAction,0,'a menu opened on another lab never acts');assert.equal(h.nodeMenu.hidden,true);
 h.context.activeId='a';h.context.openNodeMenu(target,0,0);
 for(const fn of h.nodeMenu.listeners.click)fn({target:{}});
 assert.equal(h.calls.handleNodeAction,1);assert.equal(h.nodeMenu.hidden,true);
 h.context.openNodeMenu(target,0,0);
 const buttons=[0,1,2].map(i=>({i,focus(){h.document.activeElement=this;}}));h.nodeMenu.querySelectorAll=()=>buttons;
 const key=k=>{const e={key:k,prevented:false,preventDefault(){this.prevented=true;}};for(const fn of h.nodeMenu.listeners.keydown)fn(e);return e;};
 h.document.activeElement=buttons[0];key('ArrowDown');assert.equal(h.document.activeElement,buttons[1]);
 key('ArrowUp');assert.equal(h.document.activeElement,buttons[0]);key('ArrowUp');assert.equal(h.document.activeElement,buttons[2],'roving wraps');
 key('Home');assert.equal(h.document.activeElement,buttons[0]);assert.equal(key('End').prevented,true);assert.equal(h.document.activeElement,buttons[2]);
 let restored=0;target.focus=()=>restored++;
 for(const fn of h.docListeners.keydown)fn({key:'Escape'});
 assert.equal(h.nodeMenu.hidden,true);assert.equal(restored,1,'Escape closes the menu and returns focus to the device');
});

test('renderMapState swaps state classes and labels on the drawn devices without touching the SVG markup',()=>{
 const h=harness({lab:lab()});const map=h.$('topology-map');map.innerHTML='<svg-before/>';
 const nodes=['r1','r2','r3','r4','r5','ghost'].map(n=>mapNode(n,n.toUpperCase()));for(const n of nodes)n.classList.add('map-device');
 nodes.forEach(n=>n.classList.add('state-neutral'));map.querySelectorAll=()=>nodes;
 assert.equal(h.context.renderMapState(),5,'one change per drawn device of the lab');
 const states=Object.fromEntries(nodes.map(n=>[n.dataset.mapNode,n.classList.list().filter(c=>c.startsWith('state-'))]));
 assert.deepEqual(states,{r1:['state-ready'],r2:['state-starting'],r3:['state-attention'],r4:['state-unavailable'],r5:['state-credentials'],ghost:['state-neutral']});
 assert.equal(map.innerHTML,'<svg-before/>','the markup is never rebuilt for a state change');
 assert.equal(nodes[0].getAttribute('aria-label'),'R1');assert.equal(nodes[0].title.textContent,'R1 — click to open, right-click for more actions');
 assert.equal(nodes[1].getAttribute('aria-label'),'R2 · Starting');assert.equal(nodes[1].title.textContent,"R2 · Starting. R2 is still starting. SSH opens automatically when it answers. Use Test logins (above) or this device's Test login to check again now.");
 assert.equal(nodes[2].getAttribute('aria-label'),'R3 · Needs attention');
 assert.equal(h.context.renderMapState(),0,'a second pass with the same state changes nothing');
 h.context.state.labs[0].nodes[1].ssh_ready=true;h.context.state.labs[0].nodes[1].nos_login.status='ready';
 assert.equal(h.context.renderMapState(),1);assert.deepEqual(nodes[1].classList.list().filter(c=>c.startsWith('state-')),['state-ready']);assert.equal(nodes[1].getAttribute('aria-label'),'R2');
 h.context.labStateOf=()=>({key:'working'});h.context.renderMapState();
 assert.deepEqual(nodes[2].classList.list().filter(c=>c.startsWith('state-')),['state-working'],'devices that are not ready read as working during a lab operation');
 assert.deepEqual(nodes[0].classList.list().filter(c=>c.startsWith('state-')),['state-ready'],'a device that accepts logins stays ready');
 assert.equal(typeof h.context.applyMapStates,'function');assert.equal(h.context.applyMapStates(),0,'applyMapStates is the same pass under its parity name');
 h.context.activeId='';assert.equal(h.context.renderMapState(),0,'nothing to do on Home');
});

test('the map stage shows the loading skeleton, then the empty state or the map with a student caption',async()=>{
 const empty=harness({lab:lab(),drawing:undefined});const e$=empty.$;
 const fetching=empty.context.refreshMap();
 assert.equal(e$('map-loading').hidden,false,'the first fetch for a lab shows the skeleton');assert.equal(e$('topology-map').hidden,true);
 await fetching;
 assert.equal(e$('map-loading').hidden,true);assert.equal(e$('map-empty').hidden,false);assert.equal(e$('topology-map').hidden,true);
 assert.equal(e$('map-status').textContent,'');assert.equal(e$('topology-hint').textContent,'Click a device to open it. Click a link to capture its traffic. Right-click for more actions.','no map: the hint resets to the fixed sentence, with no notes appended');
 for(const id of ['map-fit','map-in','map-out','map-expand'])assert.equal(e$(id).disabled,true,id+' is disabled without a map');
 assert.equal(e$('map-edit').disabled,true);assert.equal(e$('map-edit').title,'Import a map first.');
 assert.ok(empty.calls.synced>=1,'the proxies mirror the disabled tools');
 const drawing={schema:3,has_links_source:true,skipped_links:0,nodes:[{id:'a',inventory_name:'r1',label:'R1',x:0,y:0},{id:'b',inventory_name:'r2',label:'R2',x:100,y:0}],links:[[{node:'a',interface:'eth1'},{node:'b',interface:'eth1'}]],decorations:[],settings:{}};
 const h=harness({lab:lab(),drawing});const $=h.$;
 const nodes=['r1','r2'].map(n=>mapNode(n,n.toUpperCase()));$('topology-map').querySelectorAll=()=>nodes;
 await h.context.refreshMap();
 assert.equal($('map-loading').hidden,true);assert.equal($('map-empty').hidden,true);assert.equal($('topology-map').hidden,false);
 assert.equal($('map-status').textContent,'2 devices · 1 link');
 assert.equal($('topology-hint').textContent,'Click a device to open it. Click a link to capture its traffic. Right-click for more actions.','a normal drawing (schema 3, no skipped links) carries no extra notes');
 assert.equal($('map-edit').disabled,false);assert.equal($('map-fit').disabled,false);
 assert.equal($('topology-map').innerHTML,'<g data-nodes="2"></g>');assert.equal($('topology-map').attrs.viewBox,'0 0 100 50');
 assert.deepEqual(nodes.map(n=>n.classList.list()),[['state-ready'],['state-starting']],'state is applied right after the render');
 assert.equal(h.calls.api.length,1);await h.context.refreshMap();assert.equal(h.calls.api.length,2);
 assert.equal($('topology-map').innerHTML,'<g data-nodes="2"></g>','an unchanged drawing is not re-rendered');
 const busy=harness({lab:lab(),drawing:{...drawing,schema:2,has_links_source:false,skipped_links:2,nodes:[...drawing.nodes,{id:'c',label:'ghost',x:0,y:0}]}});
 await busy.context.refreshMap();
 assert.equal(busy.$('map-status').textContent,'2 devices · 1 link · 1 drawn but not in this lab. Links aren’t shown yet — import the lab topology file with the map to draw them.');
 assert.equal(busy.$('topology-hint').textContent,'Click a device to open it. Click a link to capture its traffic. Right-click for more actions. 2 links could not be drawn (unsupported or one-ended). Some map styling and port labels could not be shown. Re-import the original map files to restore them.','skipped-links and schema notes join the hint line instead of a Details toggle');
 const failing=harness({lab:lab(),drawing});failing.context.api=async()=>{throw new Error('boom');};
 await failing.context.refreshMap();
 assert.equal(failing.$('map-status').textContent,'The map could not be loaded. boom');assert.equal(failing.$('map-loading').hidden,true);
 const home=harness({});await home.context.refreshMap();assert.equal(home.calls.api.length,0,'no lab, no request');
});

test('Expand toggles its label through data-label and Escape closes the expanded map only when no menu is open',()=>{
 const h=harness({lab:lab()});const view=h.$('topology-view'),button=h.$('map-expand');button.dataset.label='Expand';
 button.onclick();assert.equal(view.classList.contains('map-expanded'),true);assert.equal(button.textContent,'Close expanded map');
 h.nodeMenu.hidden=false;for(const fn of h.docListeners.keydown)fn({key:'Escape'});
 assert.equal(h.nodeMenu.hidden,true);assert.equal(view.classList.contains('map-expanded'),true,'the node menu consumed the Escape');
 h.context.closeMenus=()=>true;for(const fn of h.docListeners.keydown)fn({key:'Escape'});
 assert.equal(view.classList.contains('map-expanded'),true,'an open menu consumed the Escape');
 h.context.closeMenus=()=>false;for(const fn of h.docListeners.keydown)fn({key:'Escape'});
 assert.equal(view.classList.contains('map-expanded'),false);assert.equal(button.textContent,'Expand');
 for(const fn of h.docListeners.keydown)fn({key:'a'});assert.equal(view.classList.contains('map-expanded'),false);
 button.onclick();button.onclick();assert.equal(button.textContent,'Expand');
});

test('a successful map import re-renders the map and reports in map words',async()=>{
 const h=harness({lab:lab(),drawing:{schema:3,has_links_source:true,nodes:[],links:[],decorations:[],settings:{}}});
 let pending;h.context.withForm=(form,fn)=>{pending=fn();return pending;};h.context.FormData=class{constructor(){}};
 const submit=h.$('map-form').listeners.submit[0];
 submit({preventDefault(){},currentTarget:h.$('map-form')});await pending;
 assert.deepEqual(h.calls.api,['/labs/a/topology','/labs/a/topology'],'the upload and the refresh both target the lab');
 assert.deepEqual(h.calls.notify,['Map imported.']);assert.equal(h.$('map-dialog').open,false);
 assert.equal(h.$('map-status').textContent,'0 devices · 0 links');
});

test('Test logins mirrors whichever check is really running and never marks a device ready by itself',()=>{
 const running=lab();running.nodes[1].nos_login={status:'checking'};
 const h=harness({lab:running});
 // A node already "checking" (started elsewhere: the other button, another tab, the automatic
 // monitor) disables both buttons before this browser ever clicks anything.
 assert.equal(h.context.railTestActive(h.context.state.labs[0]),true);
 assert.equal(h.context.renderRailTest(),true);
 for(const id of ['rail-test-logins','devices-test-logins']){assert.equal(h.$(id).disabled,true);assert.equal(h.$(id).textContent,'Testing…');}
 h.context.state.labs[0].nodes[1].nos_login.status='booting';
 assert.equal(h.context.renderRailTest(),false);
 for(const id of ['rail-test-logins','devices-test-logins']){assert.equal(h.$(id).disabled,false);assert.equal(h.$(id).textContent,'Test logins');}
 // renderMapState (the 4 s poll's entry point) keeps the buttons in step without a click.
 h.context.state.labs[0].nodes[1].nos_login.status='checking';h.context.renderMapState();
 assert.equal(h.$('rail-test-logins').disabled,true);
});

test('Test logins starts the lab-wide refresh, reports what was skipped, and settles once every device answers',async()=>{
 const h=harness({lab:lab(),jsonImpl:()=>({started:2,skipped:[{name:'r6',reason:'needs credentials'}],at:'2026-09-23T00:00:00Z'})});
 const pending=h.context.runRailTest();
 // Optimistic feedback: both buttons already read Testing… before the request settles.
 assert.equal(h.$('rail-test-logins').disabled,true);assert.equal(h.$('rail-test-logins').textContent,'Testing…');
 assert.equal(h.$('devices-test-logins').disabled,true);assert.equal(h.$('devices-test-logins').textContent,'Testing…');
 await pending;
 assert.equal(h.calls.json.length,1);assert.equal(h.calls.json[0].path,'/labs/a/ssh-check-all');
 assert.equal(h.calls.json[0].method,'POST');assert.equal(JSON.stringify(h.calls.json[0].data),'{}');
 assert.equal(h.calls.refresh,1,'the poll refreshes once so the cards pick up whatever already landed');
 assert.deepEqual(h.calls.notify,['Testing the SSH login of 2 devices… 1 device skipped — see each device for why.']);
 // No lab: never sends a request.
 const home=harness({});await home.context.runRailTest();assert.equal(home.calls.json.length,0);
});
