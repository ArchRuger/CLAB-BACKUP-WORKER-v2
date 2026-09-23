// shell.js: hash routing, button menus, storage helpers and the action-error banner, driven through a
// small DOM with window, location, history and storage (app.js is stubbed: it only needs the globals).
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function matches(node,selector){
 return selector.split(',').some(part=>{
  const m=part.trim().match(/^([a-z]+)?(#[\w-]+)?((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/);if(!m)return false;
  if(m[1]&&node.tag!==m[1])return false;if(m[2]&&node.id!==m[2].slice(1))return false;
  for(const cls of (m[3]||'').split('.').filter(Boolean))if(!node.className.split(/\s+/).includes(cls))return false;
  for(const attr of (m[4]||'').match(/\[[^\]]+\]/g)||[]){const [,name,value]=attr.match(/^\[([\w-]+)(?:="?([^"\]]*)"?)?\]$/);
   if(['open','hidden','disabled'].includes(name)){if(!node[name])return false;continue;}
   const actual=node.getAttribute(name);if(actual===null||(value!==undefined&&actual!==value))return false;}
  return true;
 });
}
function dom(){
 const doc={listeners:{},activeElement:null,body:null,addEventListener(name,fn,capture){(this.listeners[name]=this.listeners[name]||[]).push({fn,capture:!!capture});},querySelectorAll(sel){return all(this.body).filter(n=>matches(n,sel));},querySelector(sel){return this.querySelectorAll(sel)[0]||null;},getElementById(id){return all(this.body).find(n=>n.id===id)||null;},createElement:tag=>el(tag)};
 function all(node){return node?[node,...node.children.flatMap(all)]:[];}
 function el(tag,attrs={},children=[]){
  const node={tag,attrs:{},children:[],parentElement:null,listeners:{},hidden:!!attrs.hidden,disabled:!!attrs.disabled,open:false,textContent:attrs.text||'',className:attrs.class||'',
   get id(){return this.attrs.id||'';},set id(v){this.attrs.id=v;},
   getAttribute(n){return n in this.attrs?String(this.attrs[n]):null;},setAttribute(n,v){this.attrs[n]=String(v);},hasAttribute(n){return n in this.attrs;},
   addEventListener(name,fn,capture){(this.listeners[name]=this.listeners[name]||[]).push({fn,capture:!!capture});},
   querySelectorAll(sel){return all(this).slice(1).filter(n=>matches(n,sel));},querySelector(sel){return this.querySelectorAll(sel)[0]||null;},
   contains(other){return all(this).includes(other);},closest(sel){let n=this;while(n){if(matches(n,sel))return n;n=n.parentElement;}return null;},
   focus(){doc.activeElement=this;},click(){this.dispatch('click');},dispatchEvent(e){return this.dispatch(e.type,e);},
   append(...nodes){for(const c of nodes){c.parentElement=this;this.children.push(c);}},
   dispatch(type,init={}){
    const event={type,target:this,key:init.key,detail:init.detail,stopped:false,prevented:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},stopImmediatePropagation(){this.stopped=true;}};
    const chain=[];for(let n=this;n;n=n.parentElement)chain.unshift(n);
    const run=(target,capture)=>{for(const l of (target.listeners[type]||[]))if(l.capture===capture&&!event.stopped)l.fn.call(target,event);};
    run(doc,true);for(const n of chain.slice(0,-1)){if(event.stopped)break;run(n,true);}
    if(!event.stopped){run(this,true);run(this,false);if(typeof this['on'+type]==='function'&&!event.stopped)this['on'+type](event);}
    for(const n of chain.slice(0,-1).reverse()){if(event.stopped)break;run(n,false);}
    if(!event.stopped)run(doc,false);
    return event;
   }};
  for(const [k,v] of Object.entries(attrs))if(!['hidden','disabled','text','class'].includes(k))node.attrs[k]=v;
  node.append(...children);return node;
 }
 doc.body=el('body');
 return {doc,el,all};
}
function harness({hash='',session={},local={},throwStorage=false,labs=[{id:'a',name:'A'},{id:'b',name:'B'}],loaded=true}={}){
 const {doc,el}=dom();
 const item=(id,attrs={},text='')=>el('button',{id,role:'menuitem',text,...attrs});
 const managerList=el('div',{id:'manager-menu-list',class:'menu-list'},[item('vm-settings',{},'VM connection…'),item('vm-refresh',{disabled:true},'Refresh lab list'),item('inspect-all',{},'Running labs on the VM…')]);
 const managerButton=el('button',{id:'manager-button',class:'button secondary menu-button','aria-expanded':'false',text:'Manager'});
 const manager=el('span',{id:'manager-menu',class:'menu'},[managerButton,managerList]);
 const labList=el('div',{id:'lab-actions-menu',class:'menu-list'},[item('lab-start',{},'Start lab'),item('menu-destroy',{},'Destroy lab…'),item('lab-actions-advanced-toggle',{'data-menu-group':'lab-actions-advanced','aria-expanded':'false'},'Advanced options'),el('div',{id:'lab-actions-advanced','data-menu-panel':'',role:'group',hidden:true},[item('menu-import-map',{},'Import map…'),item('menu-map-edit',{disabled:true},'Edit map'),item('menu-telemetry',{},'Telemetry settings…'),item('menu-operation-history',{},'Operation history…')])]);
 const labButton=el('button',{id:'lab-actions-button',class:'button secondary menu-button','aria-expanded':'false',text:'Lab actions'});
 const labActions=el('span',{class:'menu'},[labButton,labList]);
 const gitSummary=el('summary',{text:'▾'});const gitSave=el('details',{id:'git-save-menu',class:'git-save-menu'},[gitSummary,el('div',{class:'git-save-options'},[item('',{'data-git-action':'checkpoint'},'Create checkpoint…')])]);
 const switcherSummary=el('summary',{text:'Switch lab'});const switcher=el('details',{id:'lab-switcher',class:'lab-switcher'},[switcherSummary,el('nav',{id:'labs'})]);
 const dialog=el('dialog',{id:'details-dialog'});dialog.close=function(){this.open=false;this.dispatch('close');};
 const nodeMenu=el('div',{id:'node-context-menu',hidden:true});
 const banner=el('div',{id:'lab-banner',hidden:true});
 const skeleton=el('div',{id:'home-skeleton',hidden:true});
 const navHome=el('a',{id:'nav-home',href:'/'});const crumbHome=el('button',{id:'crumb-home'});
 const outside=el('main',{id:'outside'});
 doc.body.append(navHome,crumbHome,switcher,manager,labActions,gitSave,dialog,nodeMenu,banner,skeleton,outside);
 const storage=map=>{const m=new Map(Object.entries(map));return throwStorage?{getItem(){throw new Error('blocked');},setItem(){throw new Error('blocked');},removeItem(){throw new Error('blocked');}}:{getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k),map:m};};
 const history=[],location={hash,pathname:'/',search:''};
 const setUrl=url=>{location.hash=url.includes('#')?url.slice(url.indexOf('#')):'';};
 const calls={selectLab:[],showTab:[],openDetails:[],render:0,renderLabBanner:0,notify:[]};
 const context=vm.createContext({document:doc,location,history:{pushState(s,t,url){history.push(['push',url]);setUrl(url);},replaceState(s,t,url){history.push(['replace',url]);setUrl(url);}},localStorage:storage(local),sessionStorage:storage(session),URLSearchParams,CustomEvent:class{constructor(type,init={}){this.type=type;this.detail=init.detail;}},setTimeout:fn=>{context.timers.push(fn);return 0;},console,
  state:{labs,loaded},activeId:'',tab:'topology',detailName:'',
  selectLab(id,view='topology'){calls.selectLab.push([id,view]);context.activeId=id;context.tab=view;},showTab(view){calls.showTab.push(view);context.tab=view;},openDetails(name){calls.openDetails.push(name);context.detailName=name;dialog.open=true;},render(){calls.render++;},renderLabBanner(){calls.renderLabBanner++;},notify(m){calls.notify.push(m);}});
 context.window=context;context.timers=[];context.windowListeners={};context.addEventListener=(name,fn)=>{context.windowListeners[name]=fn;};
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/shell.js'),'utf8'),context);
 return {context,doc,el,history,location,calls,managerButton,managerList,labButton,labList,gitSave,gitSummary,switcher,dialog,nodeMenu,outside,skeleton};
}

test('route precedence: the hash wins, sessionStorage is consumed once, unknown ids fall back to Home',()=>{
 const h=harness({hash:'#lab=b&view=devices',session:{activeLab:'a'}});
 assert.equal(JSON.stringify(h.context.readRoute()),JSON.stringify({lab:'b',view:'devices',device:''}));
 assert.equal(h.context.applyRoute(),true);
 assert.deepEqual(h.calls.selectLab,[['b','devices']]);
 assert.equal(h.context.sessionStorage.getItem('activeLab'),null,'the stored id is removed once the route has been applied');
 const stored=harness({session:{activeLab:'a'}});stored.context.applyRoute();
 assert.deepEqual(stored.calls.selectLab,[['a','topology']],'a same-tab reload resumes the stored lab');
 stored.context.activeId='';stored.location.hash='';stored.context.sessionStorage.setItem('activeLab','b');
 stored.context.applyRoute();
 assert.equal(stored.calls.selectLab.length,1,'sessionStorage is read once; afterwards the hash decides');
 const unknown=harness({hash:'#lab=zzz'});unknown.context.activeId='a';unknown.context.applyRoute();
 assert.equal(unknown.context.activeId,'');assert.equal(unknown.location.hash,'');assert.equal(unknown.calls.render,1);
 const waiting=harness({hash:'#lab=a',loaded:false});assert.equal(waiting.context.applyRoute(),false,'nothing happens before the first /state');
 const sameLab=harness({hash:'#lab=a&view=progress&device=R1'});sameLab.context.activeId='a';sameLab.context.tab='topology';sameLab.context.applyRoute();
 assert.deepEqual(sameLab.calls.selectLab,[]);assert.deepEqual(sameLab.calls.showTab,['progress']);assert.deepEqual(sameLab.calls.openDetails,['R1']);
});

test('writeRoute no-ops when the hash already matches; polls replace, navigation pushes, routes never push while applying',()=>{
 const h=harness({hash:'#lab=a&view=topology'});
 assert.equal(h.context.writeRoute({lab:'a',view:'topology'}),false);assert.equal(h.history.length,0);
 assert.equal(h.context.writeRoute({lab:'a',view:'devices'}),true);assert.deepEqual(h.history[0],['replace','/#lab=a&view=devices']);
 assert.equal(h.context.writeRoute({lab:'b',view:'topology'},{push:true}),true);assert.deepEqual(h.history[1],['push','/#lab=b&view=topology']);
 assert.equal(h.location.hash,'#lab=b&view=topology');
 assert.equal(h.context.writeRoute({}),true);assert.equal(h.location.hash,'');
 assert.equal(h.context.serialiseRoute({lab:'x y',view:'',device:'R 1'}),'#lab=x+y&device=R+1');
 const applying=harness({hash:'#lab=b'});applying.context.applyRoute();
 assert.ok(applying.history.every(([kind])=>kind==='replace'),'applying a route never adds a history entry');
});

test('goHome clears the lab, the hash and sessionStorage, closes the drawer and re-renders',()=>{
 const h=harness({hash:'#lab=a&view=devices&device=R1',session:{activeLab:'a'}});
 h.context.activeId='a';h.context.detailName='R1';h.dialog.open=true;h.managerButton.dispatch('click');
 assert.equal(h.context.goHome(),true);
 assert.equal(h.context.activeId,'');assert.equal(h.location.hash,'');assert.equal(h.context.sessionStorage.getItem('activeLab'),null);
 assert.equal(h.dialog.open,false);assert.equal(h.managerList.hidden,true);assert.equal(h.calls.render,1);
 h.context.goHome({push:true});assert.equal(h.history.filter(([k])=>k==='push').length,0,'an already empty hash is not pushed again');
});

test('initMenu: open focuses the first enabled item, arrows rove, Escape closes and returns focus to the button',()=>{
 const h=harness();const [settings,refresh,inspect]=h.managerList.children;
 assert.equal(h.managerButton.getAttribute('aria-controls'),'manager-menu-list');assert.equal(h.managerList.getAttribute('role'),'menu');
 h.managerButton.dispatch('click');
 assert.equal(h.managerList.hidden,false);assert.equal(h.managerButton.getAttribute('aria-expanded'),'true');
 assert.equal(h.doc.activeElement,settings,'the first enabled item takes focus');
 h.managerList.dispatch('keydown',{key:'ArrowDown'});assert.equal(h.doc.activeElement,inspect,'the disabled item is skipped');
 h.managerList.dispatch('keydown',{key:'ArrowDown'});assert.equal(h.doc.activeElement,settings,'roving wraps');
 h.managerList.dispatch('keydown',{key:'End'});assert.equal(h.doc.activeElement,inspect);
 h.managerList.dispatch('keydown',{key:'Home'});assert.equal(h.doc.activeElement,settings);
 const escape=settings.dispatch('keydown',{key:'Escape'});
 assert.equal(h.managerList.hidden,true);assert.equal(h.managerButton.getAttribute('aria-expanded'),'false');
 assert.equal(h.doc.activeElement,h.managerButton,'focus returns to the button');assert.equal(escape.stopped,true,'the map never sees the Escape');
 h.managerButton.dispatch('click');assert.equal(h.managerList.hidden,false);
 h.labButton.dispatch('click');assert.equal(h.managerList.hidden,true,'opening one menu closes the other');assert.equal(h.labList.hidden,false);
 let activated=0;h.labList.children[0].onclick=()=>{activated++;assert.equal(h.labList.hidden,true,'the menu is closed before the item handler runs');assert.equal(h.doc.activeElement,h.labButton);};
 h.labList.children[0].dispatch('click');assert.equal(activated,1);
 h.labButton.dispatch('click');h.labList.dispatch('keydown',{key:'Tab'});assert.equal(h.labList.hidden,true,'Tab closes without trapping focus');
 assert.equal(h.context.initMenu(h.labButton),null,'a button is wired once');
});

test('an expandable menu group: the toggle never closes the menu, collapsed items are skipped, arrows open and close it, reopening collapses it',()=>{
 const h=harness();const [start,destroy,toggle,panel]=h.labList.children,[importMap,editMap,telemetry,history]=panel.children;
 h.labButton.dispatch('click');assert.equal(panel.hidden,true);assert.equal(toggle.getAttribute('aria-expanded'),'false');
 h.labList.dispatch('keydown',{key:'End'});assert.equal(h.doc.activeElement,toggle,'items of the collapsed group are not reachable by the arrow keys');
 toggle.dispatch('click');assert.equal(h.labList.hidden,false,'the toggle keeps the menu open');assert.equal(panel.hidden,false);assert.equal(toggle.getAttribute('aria-expanded'),'true');
 h.labList.dispatch('keydown',{key:'ArrowDown'});assert.equal(h.doc.activeElement,importMap);
 h.labList.dispatch('keydown',{key:'ArrowDown'});assert.equal(h.doc.activeElement,telemetry,'a disabled item in the group is skipped');
 h.labList.dispatch('keydown',{key:'End'});assert.equal(h.doc.activeElement,history);
 const left=h.labList.dispatch('keydown',{key:'ArrowLeft'});assert.equal(panel.hidden,true);assert.equal(h.doc.activeElement,toggle,'ArrowLeft collapses and returns to the toggle');assert.equal(left.prevented,true);
 h.labList.dispatch('keydown',{key:'ArrowRight'});assert.equal(panel.hidden,false);assert.equal(h.doc.activeElement,importMap,'ArrowRight expands and enters the group');
 start.focus();const ignored=h.labList.dispatch('keydown',{key:'ArrowRight'});assert.equal(ignored.prevented,false,'the arrows mean nothing on an ordinary item');assert.equal(panel.hidden,false);
 let ran=0;telemetry.onclick=()=>{ran++;assert.equal(h.labList.hidden,true,'a group item closes the menu before its handler runs');};
 telemetry.dispatch('click');assert.equal(ran,1);assert.equal(h.doc.activeElement,h.labButton);
 h.labButton.dispatch('click');assert.equal(panel.hidden,true,'the group is collapsed again when the menu opens');assert.equal(toggle.getAttribute('aria-expanded'),'false');
 toggle.dispatch('click');toggle.dispatch('click');assert.equal(panel.hidden,true,'a second click collapses it');assert.equal(h.labList.hidden,false);assert.ok(destroy);
});

test('closeMenus returns true only when it closed something and keeps the excepted menu open',()=>{
 const h=harness();
 assert.equal(h.context.closeMenus(),false);
 h.managerButton.dispatch('click');
 assert.equal(h.context.closeMenus(h.managerButton),false,'the menu containing the exception stays open');assert.equal(h.managerList.hidden,false);
 assert.equal(h.context.closeMenus(),true);assert.equal(h.managerList.hidden,true);assert.equal(h.context.closeMenus(),false);
 h.gitSave.open=true;h.switcher.open=true;
 assert.equal(h.context.closeMenus(),true);assert.equal(h.gitSave.open,false);assert.equal(h.switcher.open,false);
});

test('outside pointerdown closes menus; Escape at the document closes them and stops propagation unless the node menu is open',()=>{
 const h=harness();
 h.managerButton.dispatch('click');h.outside.dispatch('pointerdown');assert.equal(h.managerList.hidden,true);
 h.managerButton.dispatch('click');h.managerButton.dispatch('pointerdown');assert.equal(h.managerList.hidden,false,'pressing the menu button itself does not close it here');
 const escape=h.outside.dispatch('keydown',{key:'Escape'});assert.equal(h.managerList.hidden,true);assert.equal(escape.stopped,true);
 const idle=h.outside.dispatch('keydown',{key:'Escape'});assert.equal(idle.stopped,false,'nothing to close: the map handler may run');
 h.managerButton.dispatch('click');h.nodeMenu.hidden=false;const deferred=h.outside.dispatch('keydown',{key:'Escape'});
 assert.equal(h.managerList.hidden,false);assert.equal(deferred.stopped,false,'the node context menu is handled by topology.js first');
 h.nodeMenu.hidden=true;h.gitSave.open=true;const summary=h.gitSummary.dispatch('keydown',{key:'Escape'});
 assert.equal(h.gitSave.open,false);assert.equal(h.doc.activeElement,h.gitSummary);assert.equal(summary.stopped,true);
});

test('storage helpers remember when a lab was opened and dismissed jobs, and never throw when storage is blocked',()=>{
 const h=harness();
 assert.equal(h.context.openedAt('a'),'');
 assert.equal(h.context.rememberOpened('a'),true);assert.match(h.context.openedAt('a'),/^\d{4}-/);assert.equal(h.context.openedAt('b'),'','one lab\'s time is not another\'s');
 assert.equal(typeof h.context.lastOpened,'undefined','no reader is left for the Continue block that Home no longer has');
 assert.equal(h.context.isDismissed('job1'),false);assert.equal(h.context.dismissJob('job1'),true);assert.equal(h.context.isDismissed('job1'),true);
 assert.equal(h.context.rememberOpened(''),false);
 const blocked=harness({throwStorage:true,hash:'#lab=a'});
 assert.equal(blocked.context.rememberOpened('a'),false);assert.equal(blocked.context.openedAt('a'),'');
 assert.equal(blocked.context.isDismissed('x'),false);assert.equal(blocked.context.dismissJob('x'),false);
 assert.equal(blocked.context.applyRoute(),true,'routing works without sessionStorage');assert.deepEqual(blocked.calls.selectLab,[['a','topology']]);
 assert.equal(blocked.context.goHome(),true);
});

test('noticeDismissed/dismissNotice: a notice key is remembered for the session, a different key is unaffected, and neither throws when storage is blocked',()=>{
 const h=harness();
 assert.equal(h.context.noticeDismissed('a.lab-banner.abc'),false);
 assert.equal(h.context.dismissNotice('a.lab-banner.abc'),true);
 assert.equal(h.context.noticeDismissed('a.lab-banner.abc'),true);
 assert.equal(h.context.noticeDismissed('a.lab-banner.def'),false,'a materially different headline digest is its own key');
 const blocked=harness({throwStorage:true});
 assert.equal(blocked.context.dismissNotice('x'),false);assert.equal(blocked.context.noticeDismissed('x'),false);
});

test('showActionError renders the lab banner on a lab page and falls back to a toast elsewhere',()=>{
 const h=harness();
 assert.equal(h.context.showActionError('Request failed'),false);assert.deepEqual(h.calls.notify,['Request failed']);
 h.context.activeId='a';
 assert.equal(h.context.showActionError('Configured devices changed. Review the Git repository device selection.'),true);
 const err=h.context.actionError();assert.equal(err.lab,'a');assert.match(err.sentence,/devices in this lab changed/);assert.match(err.message,/Configured devices changed/);
 assert.equal(h.calls.renderLabBanner,1);
 h.context.dismissActionError();assert.equal(h.context.actionError(),null);
 h.context.showActionError('Exit 1');assert.match(h.context.actionError().sentence,/did not work/);
 h.context.goHome();assert.equal(h.context.actionError(),null,'leaving the lab drops the error');
});

test('closing the drawer clears the device from the route; Home links go home; the skeleton waits 200 ms',()=>{
 const h=harness({hash:'#lab=a&view=topology&device=R1'});
 h.context.activeId='a';h.context.detailName='R1';h.dialog.open=true;
 h.dialog.close();assert.equal(h.location.hash,'#lab=a&view=topology');
 h.doc.getElementById('crumb-home').dispatch('click');assert.equal(h.context.activeId,'');assert.equal(h.location.hash,'');assert.deepEqual(h.history.at(-1),['push','/']);
 assert.equal(h.skeleton.hidden,true);h.context.state.loaded=false;h.context.timers[0]();assert.equal(h.skeleton.hidden,false);
 const quick=harness();quick.context.timers[0]();assert.equal(quick.skeleton.hidden,true,'no skeleton once the state has arrived');
 quick.context.applyRoute();quick.location.hash='#lab=b';quick.context.windowListeners.hashchange();
 assert.deepEqual(quick.calls.selectLab,[['b','topology']],'the Back and Forward buttons re-read the hash');
 quick.location.hash='';quick.context.windowListeners.hashchange();
 assert.equal(quick.context.activeId,'');assert.equal(quick.calls.render,1,'an empty hash goes home');
});

test('index.html: Lab actions ends with an Advanced options group holding exactly the four reviewed items; nothing else moved or vanished',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 const menu=html.slice(html.indexOf('id="lab-actions-menu"'),html.indexOf('</header>',html.indexOf('id="lab-actions-menu"')));
 const at=menu.indexOf('id="lab-actions-advanced" data-menu-panel'),outside=menu.slice(0,at),group=menu.slice(at);
 assert.ok(at>0);assert.match(menu,/id="lab-actions-advanced-toggle" data-menu-group="lab-actions-advanced" aria-expanded="false" aria-controls="lab-actions-advanced"><span>Advanced options<\/span>/);
 assert.match(group,/^id="lab-actions-advanced" data-menu-panel role="group" aria-labelledby="lab-actions-advanced-toggle" hidden>/);
 assert.deepEqual([...group.matchAll(/role="menuitem" id="([\w-]+)"/g)].map(m=>m[1]),['menu-import-map','menu-map-edit','menu-telemetry','menu-operation-history']);
 assert.match(group,/id="menu-import-map" data-proxy="import-map"/);assert.match(group,/id="menu-map-edit" data-proxy="map-edit"/);
 for(const id of ['lab-start','menu-sync-vm','menu-capture','menu-lab-files','lab-actions','menu-destroy','menu-remove-lab','lab-actions-advanced-toggle'])assert.match(outside,new RegExp('id="'+id+'"'),id+' stays in the main list');
 assert.ok(outside.indexOf('class="menu-danger"')<outside.indexOf('lab-actions-advanced-toggle'),'the group is the last thing in the menu, after the destructive actions');
 assert.match(html,/id="map-edit" class="button secondary small">Edit map</,'Edit map stays on the map toolbar');assert.match(html,/id="tools-telemetry-settings"/);assert.match(html,/id="advanced-operation-history"/);assert.match(html,/role="menuitem" id="import-map"/);
});

test('style.css: the device lists carry no list indent and the Devices tab is one grid whose rows are subgrids, single column on a narrow window',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8');
 assert.match(css,/\.device-list \{ display: grid; gap: 8px; list-style: none; margin: 0; padding: 0; \}/,'a <ul> keeps 40px of padding otherwise: the rows then start to the right of their heading');
 assert.match(css,/#device-list \{ grid-template-columns: minmax\(200px, 1\.1fr\) minmax\(240px, 1\.9fr\) auto;/);assert.match(css,/#device-list > li \{ grid-column: 1 \/ -1; \}/,'rows and the empty message span the grid');
 assert.match(css,/@supports \(grid-template-columns: subgrid\) \{ #device-list \.device-row \{ grid-template-columns: subgrid; \} \}/);
 assert.match(css,/\.device-row, #device-list, #device-list \.device-row \{ grid-template-columns: 1fr; \}/,'one column below 760px');
 assert.match(css,/\.device-rail \.device-row \{ grid-template-columns: minmax\(0, 1fr\) auto; grid-template-areas: "name state" "platform platform" "reason reason" "actions actions";/,'the Topology rail keeps its own named-area grid');
});

test('index.html: the Topology tab keeps the hint, the controls and the badge; the wiring caveat and its Details toggle are gone; the device rail is a focusable, labelled region',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 const view=html.slice(html.indexOf('id="topology-view"'),html.indexOf('</section>',html.indexOf('id="topology-view"')));
 assert.doesNotMatch(view,/map-notes/,'the Details disclosure and its note text are removed, not just hidden');
 assert.doesNotMatch(view,/Lines show how the lab is wired, not whether links are up\./);
 assert.match(view,/<p id="topology-hint" class="topology-hint caption">Click a device to open it\. Click a link to capture its traffic\. Right-click for more actions\.<\/p>/,'the one-line hint stays, now addressable so notes can join it');
 for(const id of ['map-fit','map-in','map-out','map-expand','map-edit'])assert.match(view,new RegExp('id="'+id+'"'),id+' stays on the map toolbar');
 assert.match(view,/id="map-status" class="caption" role="status"/,'the "N devices · M links" badge stays');
 assert.match(view,/<aside class="device-rail" aria-labelledby="topology-devices-title" tabindex="0">/,'the rail is keyboard-focusable so Page keys can scroll it directly');
});

test('style.css: the topology layout is bounded to the same viewport math as the map stage (plus the hint), the rail stretches to it and scrolls on its own with a sticky heading, and both reset to the old stacked, page-scrolling layout at 1280px',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8');
 assert.match(css,/--topology-hint-h: 28px;/);
 assert.match(css,/\.topology-layout \{ display: grid; grid-template-columns: minmax\(0, 1fr\) 300px; gap: 16px; align-items: start;\n {2}height: calc\(100dvh - var\(--stage-offset\) \+ var\(--topology-hint-h\)\);\n {2}min-height: calc\(420px \+ var\(--topology-hint-h\)\);\n {2}max-height: calc\(900px \+ var\(--topology-hint-h\)\);\n\}/);
 assert.match(css,/\.device-rail \{ display: flex; flex-direction: column; gap: 6px; min-width: 0; align-self: stretch; min-height: 0; overflow-y: auto; \}/,'no overscroll-behavior: contain — the page must still scroll once the rail reaches its end');
 assert.doesNotMatch(css,/\.device-rail[^{]*\{[^}]*overscroll-behavior/,'scrolling never traps at the rail');
 assert.match(css,/\.device-rail h2, \.device-rail h3 \{ position: sticky; top: 0;/,'the Devices heading stays put while the list scrolls under it');
 assert.match(css,/@media \(max-width: 1280px\) \{\n {2}\.topology-layout \{ grid-template-columns: minmax\(0, 1fr\); height: auto; min-height: 0; max-height: none; \}\n {2}\.device-rail \{ align-self: auto; overflow-y: visible; max-height: none; gap: 8px; \}/,'below 1280px the rail stacks under the map and scrolls with the page again');
 assert.match(css,/\.map-expanded \.topology-layout, \.map-expanded \.topology-layout > div:first-child \{ display: flex; flex-direction: column; flex: 1; height: auto; max-height: none;/,'Expand never gets clamped by the bounded-height rule');
});

test('the topology rail renders one row per device however many there are, so a scrollable rail actually has something to scroll',()=>{
 const elements=new Map();
 function element(){return {dataset:{},value:'',innerHTML:'',textContent:'',title:'',open:false,disabled:false,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},showModal(){this.open=true;},appendChild(){},remove(){},click(){}};}
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},createElement:element,body:element()};
 const context=vm.createContext({document,sessionStorage:{getItem(){return null;},setItem(){}},setTimeout:()=>0,clearTimeout(){},setInterval(){},URL:{createObjectURL:()=>'blob:fixture',revokeObjectURL(){}},URLSearchParams,Blob,console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8'),context);
 const nodes=Array.from({length:12},(_,i)=>({name:'r'+i,short_name:'R'+i,ssh_ready:i%2===0,readiness:'Ready',nos_login:{status:i%2===0?'ready':'booting'}}));
 vm.runInContext(`activeId='lab';state={labs:[{id:'lab',name:'Lab',nodes:${JSON.stringify(nodes)},profiles:[],defaults:{}}],jobs:[],platforms:{}};renderDeviceList();`,context);
 const html=document.getElementById('topology-devices').innerHTML;
 assert.equal((html.match(/class="device-row /g)||[]).length,12,'every device gets its own row; nothing is truncated client-side for a long list');
});

// setBanner (app.js) needs shell.js's noticeDismissed/dismissNotice, so this harness loads status.js,
// shell.js and app.js in production order; fetch is left undefined so app.js's own startup refresh()
// fails immediately (caught by its own .catch) instead of racing this test with a real render().
function bannerHarness(){
 const elements=new Map();
 function element(){
  const classes=new Set();
  return {dataset:{},value:'',innerHTML:'',textContent:'',title:'',open:false,disabled:false,hidden:false,className:'',attrs:{},listeners:{},
   addEventListener(name,fn){(this.listeners[name]=this.listeners[name]||[]).push(fn);},
   setAttribute(n,v){this.attrs[n]=String(v);},getAttribute(n){return n in this.attrs?this.attrs[n]:null;},removeAttribute(n){delete this.attrs[n];},
   classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c),toggle(c,force){const on=force===undefined?!classes.has(c):!!force;if(on)classes.add(c);else classes.delete(c);return on;}},
   showModal(){this.open=true;},close(){this.open=false;},appendChild(){},remove(){},click(){},reset(){},querySelector(){return null;},querySelectorAll(){return [];}};
 }
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},addEventListener(){},querySelectorAll(){return [];},querySelector(){return null;},createElement:element,body:element()};
 const session=new Map();
 const context=vm.createContext({document,sessionStorage:{getItem:k=>session.has(k)?session.get(k):null,setItem:(k,v)=>session.set(k,String(v)),removeItem:k=>session.delete(k)},localStorage:{getItem(){return null;},setItem(){},removeItem(){}},setTimeout:()=>0,clearTimeout(){},setInterval(){},URL:{createObjectURL:()=>'blob:fixture',revokeObjectURL(){}},URLSearchParams,Blob,console,location:{hash:'',pathname:'/',search:''},history:{pushState(){},replaceState(){}}});
 context.window=context;context.addEventListener=()=>{};
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/shell.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8'),context);
 return {context,$:id=>document.getElementById(id)};
}

test('setBanner: a notice hides once closed and stays hidden across rerenders of the same headline; a materially different headline is shown again',()=>{
 const h=bannerHarness();
 const spec={tone:'warn',icon:'alert',text:'3 devices need login credentials before you can open their CLI.',actions:{'banner-credentials':{label:'Add credentials',run:()=>{}}}};
 h.context.setBanner('lab-banner',spec);
 const banner=h.$('lab-banner'),close=h.$('lab-banner-close');
 assert.equal(banner.hidden,false);assert.equal(close.hidden,false);
 close.onclick();
 h.context.setBanner('lab-banner',spec);
 assert.equal(banner.hidden,true,'the same headline stays hidden across the next poll\'s rerender');
 h.context.setBanner('lab-banner',{...spec,text:'5 devices need login credentials before you can open their CLI.'});
 assert.equal(banner.hidden,false,'a materially different headline reopens the notice');
 assert.equal(h.$('banner-credentials').disabled,false,'closing a notice never makes an unavailable feature look ready, and never disables an available one either');
});

test('setBanner: a running-operation notice collapses to a one-line pill instead of disappearing, keeps collapsed through detail-only updates, and reappears in full once its headline changes',()=>{
 const h=bannerHarness();
 const running={tone:'info',icon:'clock',running:true,text:'Redeploying…',detail:'Copying files…',actions:{'banner-output':{label:'View output',run:()=>{}}}};
 h.context.setBanner('lab-banner',running);
 const banner=h.$('lab-banner'),close=h.$('lab-banner-close');
 assert.equal(banner.hidden,false);assert.equal(banner.classList.contains('banner-collapsed'),false);
 close.onclick();
 assert.equal(banner.hidden,false,'a running operation is never fully removed, only collapsed');
 assert.equal(banner.classList.contains('banner-collapsed'),true);
 h.context.setBanner('lab-banner',{...running,detail:'Copying files… 80%'});
 assert.equal(banner.classList.contains('banner-collapsed'),true,'a detail-only change (the same headline) keeps it collapsed');
 h.context.setBanner('lab-banner',{...running,text:'Starting…'});
 assert.equal(banner.classList.contains('banner-collapsed'),false,'a new headline (the operation moved on) reappears in full');
});

test('setBanner: the close control carries the documented accessible name and toggles it between collapse and expand for a running notice',()=>{
 const h=bannerHarness();
 h.context.setBanner('home-banner',{tone:'info',icon:'info',text:'Lab operation'});
 assert.equal(h.$('home-banner-close').getAttribute('aria-label'),'Hide this notice');
 const running={tone:'info',icon:'clock',running:true,text:'Starting lab…'};
 h.context.setBanner('lab-banner',running);
 const close=h.$('lab-banner-close');
 assert.equal(close.getAttribute('aria-label'),'Collapse this notice');
 close.onclick();
 assert.equal(close.getAttribute('aria-label'),'Show this notice');
 close.onclick();
 assert.equal(close.getAttribute('aria-label'),'Collapse this notice');
});

test('the Home list tab is kept for the browser session and never throws when storage is blocked',()=>{
 const h=harness();assert.equal(h.context.homeTab(),'recent');assert.equal(h.context.rememberHomeTab('all'),true);assert.equal(h.context.homeTab(),'all');
 const blocked=harness({throwStorage:true});assert.equal(blocked.context.homeTab(),'recent');assert.equal(blocked.context.rememberHomeTab('all'),false);
});
