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
    const event={type,target:this,key:init.key,detail:init.detail,relatedTarget:init.relatedTarget||null,stopped:false,prevented:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},stopImmediatePropagation(){this.stopped=true;}};
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
 const labList=el('div',{id:'lab-actions-menu',class:'menu-list'},[item('lab-start',{},'Start lab'),item('menu-destroy',{},'Destroy lab…'),item('lab-actions-advanced-toggle',{'data-menu-group':'lab-actions-advanced','aria-expanded':'false'},'Advanced options'),el('div',{id:'lab-actions-advanced','data-menu-panel':'',role:'group',hidden:true},[item('menu-import-map',{},'Import map…'),item('menu-map-edit',{disabled:true},'Edit map'),item('menu-telemetry-retired',{hidden:true},'Retired telemetry configuration…'),item('menu-operation-history',{},'Operation history…')])]);
 const labButton=el('button',{id:'lab-actions-button',class:'button secondary menu-button','aria-expanded':'false',text:'Lab actions'});
 const labActions=el('span',{class:'menu'},[labButton,labList]);
 // The header's save control (index.html): the chip and its panel, Save, the Load button and its panel.
 const saveTitle=el('h2',{id:'save-panel-title',tabindex:'-1','data-panel-focus':''}),saveInside=el('button',{id:'save-inside',text:'Upload'});
 const savePanel=el('div',{id:'save-panel',class:'save-panel','data-panel':'',role:'dialog'},[saveTitle,el('div',{id:'save-panel-body'},[saveInside])]);
 const saveChip=el('button',{id:'save-chip',class:'button secondary panel-button save-chip','aria-expanded':'false','aria-haspopup':'dialog',text:'Not saved yet'});
 const saveButton=el('button',{id:'git-save-progress',class:'button primary',text:'Save'});
 const loadPanel=el('div',{id:'load-panel',class:'save-panel wide','data-panel':'',role:'dialog'},[el('div',{id:'load-panel-body'})]);
 const loadButton=el('button',{id:'load-button',class:'button secondary panel-button','aria-expanded':'false','aria-haspopup':'dialog',text:'Load'});
 const saveControl=el('div',{id:'save-control',class:'save-control'},[el('span',{class:'save-pair'},[el('span',{class:'menu'},[saveChip,savePanel]),saveButton]),el('span',{class:'menu'},[loadButton,loadPanel])]);
 const saveDrawer=el('dialog',{id:'save-drawer','data-lab-dialog':''});saveDrawer.close=function(){this.open=false;};
 const panelEvents=[];for(const panel of [savePanel,loadPanel])for(const name of ['panelopen','panelclose'])panel.addEventListener(name,e=>panelEvents.push(panel.id+':'+e.type));
 const switcherSummary=el('summary',{text:'Switch lab'});const switcher=el('details',{id:'lab-switcher',class:'lab-switcher'},[switcherSummary,el('nav',{id:'labs'})]);
 const dialog=el('dialog',{id:'details-dialog'});dialog.close=function(){this.open=false;this.dispatch('close');};
 const nodeMenu=el('div',{id:'node-context-menu',hidden:true});
 const banner=el('div',{id:'lab-banner',hidden:true});
 const skeleton=el('div',{id:'home-skeleton',hidden:true});
 const navHome=el('a',{id:'nav-home',href:'/'});const crumbHome=el('button',{id:'crumb-home'});
 const outside=el('main',{id:'outside'});
 doc.body.append(navHome,crumbHome,switcher,manager,saveControl,labActions,dialog,saveDrawer,nodeMenu,banner,skeleton,outside);
 const storage=map=>{const m=new Map(Object.entries(map));return throwStorage?{getItem(){throw new Error('blocked');},setItem(){throw new Error('blocked');},removeItem(){throw new Error('blocked');}}:{getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k),map:m};};
 const history=[],location={hash,pathname:'/',search:''};
 const setUrl=url=>{location.hash=url.includes('#')?url.slice(url.indexOf('#')):'';};
 const calls={selectLab:[],showTab:[],openDetails:[],render:0,renderLabBanner:0,notify:[]};
 const context=vm.createContext({document:doc,location,history:{pushState(s,t,url){history.push(['push',url]);setUrl(url);},replaceState(s,t,url){history.push(['replace',url]);setUrl(url);}},localStorage:storage(local),sessionStorage:storage(session),URLSearchParams,CustomEvent:class{constructor(type,init={}){this.type=type;this.detail=init.detail;}},setTimeout:fn=>{context.timers.push(fn);return 0;},console,
  state:{labs,loaded},activeId:'',tab:'topology',detailName:'',
  selectLab(id,view='topology'){calls.selectLab.push([id,view]);context.activeId=id;context.tab=view;},showTab(view){calls.showTab.push(view);context.tab=view;},openDetails(name){calls.openDetails.push(name);context.detailName=name;dialog.open=true;},render(){calls.render++;},renderLabBanner(){calls.renderLabBanner++;},notify(m){calls.notify.push(m);}});
 context.window=context;context.timers=[];context.windowListeners={};context.addEventListener=(name,fn)=>{context.windowListeners[name]=fn;};
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/shell.js'),'utf8'),context);
 return {context,doc,el,history,location,calls,managerButton,managerList,labButton,labList,saveChip,savePanel,saveTitle,saveInside,saveButton,loadButton,loadPanel,saveDrawer,panelEvents,switcher,switcherSummary,dialog,nodeMenu,outside,skeleton};
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

test('QA-021: a lab change closes every open dialog that speaks for a lab, and only those',()=>{
 const h=harness();
 const bound=h.el('dialog',{id:'design-clear-dialog','data-lab-dialog':''}),plain=h.el('dialog',{id:'import-dialog'}),shut=h.el('dialog',{id:'design-apply-dialog','data-lab-dialog':''});
 for(const d of [bound,plain,shut])d.close=function(){this.open=false;this.closes=(this.closes||0)+1;};
 bound.open=true;plain.open=true;shut.open=false;h.doc.body.append(bound,plain,shut);
 h.context.activeId='a';h.dialog.open=true;
 h.context.closeLabDialogs();
 assert.equal(bound.open,false,'the marked open dialog closed');assert.equal(h.dialog.open,false,'the device drawer closed');
 assert.equal(plain.open,true,'an unmarked dialog is left alone');assert.equal(shut.closes||0,0,'a closed dialog is not closed again');
 bound.open=true;h.context.goHome();assert.equal(bound.open,false,'Home closes them too');
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
 const h=harness();const [start,destroy,toggle,panel]=h.labList.children,[importMap,editMap,retiredItem,history]=panel.children;
 assert.equal(retiredItem.id,'menu-telemetry-retired');assert.equal(retiredItem.hidden,true,'hidden by default, matching the real markup until the active lab has a record');
 h.labButton.dispatch('click');assert.equal(panel.hidden,true);assert.equal(toggle.getAttribute('aria-expanded'),'false');
 h.labList.dispatch('keydown',{key:'End'});assert.equal(h.doc.activeElement,toggle,'items of the collapsed group are not reachable by the arrow keys');
 toggle.dispatch('click');assert.equal(h.labList.hidden,false,'the toggle keeps the menu open');assert.equal(panel.hidden,false);assert.equal(toggle.getAttribute('aria-expanded'),'true');
 h.labList.dispatch('keydown',{key:'ArrowDown'});assert.equal(h.doc.activeElement,importMap);
 h.labList.dispatch('keydown',{key:'ArrowDown'});assert.equal(h.doc.activeElement,history,'a disabled item (map-edit) and a hidden one (retired telemetry) are both skipped');
 importMap.focus();h.labList.dispatch('keydown',{key:'End'});assert.equal(h.doc.activeElement,history,'End reaches the last reachable item from elsewhere in the group, not only because it was already there');
 const left=h.labList.dispatch('keydown',{key:'ArrowLeft'});assert.equal(panel.hidden,true);assert.equal(h.doc.activeElement,toggle,'ArrowLeft collapses and returns to the toggle');assert.equal(left.prevented,true);
 h.labList.dispatch('keydown',{key:'ArrowRight'});assert.equal(panel.hidden,false);assert.equal(h.doc.activeElement,importMap,'ArrowRight expands and enters the group');
 start.focus();const ignored=h.labList.dispatch('keydown',{key:'ArrowRight'});assert.equal(ignored.prevented,false,'the arrows mean nothing on an ordinary item');assert.equal(panel.hidden,false);
 let ran=0;history.onclick=()=>{ran++;assert.equal(h.labList.hidden,true,'a group item closes the menu before its handler runs');};
 history.dispatch('click');assert.equal(ran,1);assert.equal(h.doc.activeElement,h.labButton);
 h.labButton.dispatch('click');assert.equal(panel.hidden,true,'the group is collapsed again when the menu opens');assert.equal(toggle.getAttribute('aria-expanded'),'false');
 toggle.dispatch('click');toggle.dispatch('click');assert.equal(panel.hidden,true,'a second click collapses it');assert.equal(h.labList.hidden,false);assert.ok(destroy);
});

test('closeMenus returns true only when it closed something and keeps the excepted menu open',()=>{
 const h=harness();
 assert.equal(h.context.closeMenus(),false);
 h.managerButton.dispatch('click');
 assert.equal(h.context.closeMenus(h.managerButton),false,'the menu containing the exception stays open');assert.equal(h.managerList.hidden,false);
 assert.equal(h.context.closeMenus(),true);assert.equal(h.managerList.hidden,true);assert.equal(h.context.closeMenus(),false);
 h.saveChip.dispatch('click');h.switcher.open=true;
 assert.equal(h.context.closeMenus(),true);assert.equal(h.savePanel.hidden,true,'a header panel is closed like a menu');assert.equal(h.switcher.open,false);
 h.loadButton.dispatch('click');
 assert.equal(h.context.closeMenus(h.loadPanel),false,'the panel containing the exception stays open');assert.equal(h.loadPanel.hidden,false);
 assert.equal(h.context.closeMenus(),true);assert.equal(h.loadPanel.hidden,true);
});

test('outside pointerdown closes menus; Escape at the document closes them and stops propagation unless the node menu is open',()=>{
 const h=harness();
 h.managerButton.dispatch('click');h.outside.dispatch('pointerdown');assert.equal(h.managerList.hidden,true);
 h.managerButton.dispatch('click');h.managerButton.dispatch('pointerdown');assert.equal(h.managerList.hidden,false,'pressing the menu button itself does not close it here');
 const escape=h.outside.dispatch('keydown',{key:'Escape'});assert.equal(h.managerList.hidden,true);assert.equal(escape.stopped,true);
 const idle=h.outside.dispatch('keydown',{key:'Escape'});assert.equal(idle.stopped,false,'nothing to close: the map handler may run');
 h.managerButton.dispatch('click');h.nodeMenu.hidden=false;const deferred=h.outside.dispatch('keydown',{key:'Escape'});
 assert.equal(h.managerList.hidden,false);assert.equal(deferred.stopped,false,'the node context menu is handled by topology.js first');
 h.nodeMenu.hidden=true;h.context.closeMenus();h.switcher.open=true;const summary=h.switcherSummary.dispatch('keydown',{key:'Escape'});
 assert.equal(h.switcher.open,false);assert.equal(h.doc.activeElement,h.switcherSummary,'a <details> menu gives focus back to its summary');assert.equal(summary.stopped,true);
 // The save control that used to be a <details> split menu is a panel now: Escape inside it closes it and returns focus to its opener.
 h.saveChip.dispatch('click');const inside=h.saveInside.dispatch('keydown',{key:'Escape'});
 assert.equal(h.savePanel.hidden,true);assert.equal(h.doc.activeElement,h.saveChip);assert.equal(inside.stopped,true);
});

// Panels (initPanel): the chip panel and the Load panel of the lab header.
test('initPanel: the opener toggles its panel, aria-expanded follows, opening moves focus to the [data-panel-focus] element and a panel without one takes the focus itself',()=>{
 const h=harness();
 assert.equal(h.savePanel.hidden,true);assert.equal(h.loadPanel.hidden,true);assert.equal(h.saveChip.getAttribute('aria-expanded'),'false');
 assert.equal(h.savePanel.getAttribute('role'),'dialog','a panel is a dialog, never given the menu role');assert.equal(h.saveChip.getAttribute('aria-haspopup'),'dialog');
 h.saveChip.dispatch('click');
 assert.equal(h.savePanel.hidden,false);assert.equal(h.saveChip.getAttribute('aria-expanded'),'true');assert.equal(h.doc.activeElement,h.saveTitle);
 h.saveChip.dispatch('click');
 assert.equal(h.savePanel.hidden,true);assert.equal(h.saveChip.getAttribute('aria-expanded'),'false');
 h.loadButton.dispatch('click');assert.equal(h.doc.activeElement,h.loadPanel,'no marked element: the panel itself');
 assert.equal(h.context.initPanel(h.saveChip),null,'a second wiring of the same opener is refused');
 assert.equal(h.context.initPanel(h.saveButton),null,'a button without a [data-panel] beside it is not an opener');
});

test('initPanel: Escape inside the panel closes it and returns focus to the opener; Escape with focus elsewhere closes it and leaves focus alone',()=>{
 const h=harness();
 h.saveChip.dispatch('click');h.saveInside.focus();
 const inside=h.saveInside.dispatch('keydown',{key:'Escape'});
 assert.equal(h.savePanel.hidden,true);assert.equal(h.doc.activeElement,h.saveChip);assert.equal(inside.prevented,true);assert.equal(inside.stopped,true,'the map handler never sees it');
 // Opened by the page (focus: false): focus stays where the person was.
 h.outside.focus();assert.equal(h.saveChip._menuOpen({focus:false}),true);
 assert.equal(h.savePanel.hidden,false);assert.equal(h.doc.activeElement,h.outside);
 const outside=h.outside.dispatch('keydown',{key:'Escape'});
 assert.equal(h.savePanel.hidden,true);assert.equal(h.doc.activeElement,h.outside,'focus does not jump to the chip');assert.equal(outside.stopped,true);
});

test('initPanel: a pointer down inside the wrapper keeps the panel open, one outside closes it',()=>{
 const h=harness();
 h.saveChip.dispatch('click');
 h.saveInside.dispatch('pointerdown');assert.equal(h.savePanel.hidden,false,'a click in the panel never closes it');
 h.saveInside.dispatch('click');assert.equal(h.savePanel.hidden,false,'nor does activating a control in it (a panel is not a menu)');
 h.saveChip.dispatch('pointerdown');assert.equal(h.savePanel.hidden,false);
 h.saveButton.dispatch('pointerdown');assert.equal(h.savePanel.hidden,true,'Save is outside the chip\'s wrapper');
 h.saveChip.dispatch('click');h.outside.dispatch('pointerdown');assert.equal(h.savePanel.hidden,true);
 assert.equal(h.doc.activeElement,h.saveTitle,'an outside click does not pull focus to the opener: it follows the click');
});

test('initPanel: focus leaving for an outside control closes the panel; a focusout to nothing (a rebuilt body) does not',()=>{
 const h=harness();
 h.saveChip.dispatch('click');
 h.saveInside.dispatch('focusout',{relatedTarget:null});assert.equal(h.savePanel.hidden,false,'the focused control was replaced by a re-render');
 h.saveTitle.dispatch('focusout',{relatedTarget:h.saveInside});assert.equal(h.savePanel.hidden,false,'focus moved inside the panel');
 h.saveInside.dispatch('focusout',{relatedTarget:h.saveChip});assert.equal(h.savePanel.hidden,false,'the opener is part of the wrapper');
 h.saveInside.dispatch('focusout',{relatedTarget:h.saveButton});assert.equal(h.savePanel.hidden,true,'Tab past the last control closes it');
 assert.notEqual(h.doc.activeElement,h.saveChip,'and focus is not pulled back');
});

test('one at a time: opening a panel closes an open menu or the other panel, and opening a menu closes an open panel',()=>{
 const h=harness();
 h.managerButton.dispatch('click');h.saveChip.dispatch('click');
 assert.equal(h.managerList.hidden,true);assert.equal(h.managerButton.getAttribute('aria-expanded'),'false');assert.equal(h.savePanel.hidden,false);
 h.loadButton.dispatch('click');
 assert.equal(h.savePanel.hidden,true);assert.equal(h.saveChip.getAttribute('aria-expanded'),'false');assert.equal(h.loadPanel.hidden,false);
 h.labButton.dispatch('click');
 assert.equal(h.loadPanel.hidden,true);assert.equal(h.labList.hidden,false);
 h.switcher.open=true;h.saveChip.dispatch('click');assert.equal(h.switcher.open,false,'the lab switcher closes too');
});

test('panelopen and panelclose fire once per change on the panel element, panelopen before focus moves; a call that changes nothing fires nothing',()=>{
 const h=harness();let focusAtOpen='unset';
 h.savePanel.addEventListener('panelopen',()=>{focusAtOpen=h.doc.activeElement;});
 h.outside.focus();h.saveChip.dispatch('click');
 assert.deepEqual(h.panelEvents,['save-panel:panelopen']);assert.equal(focusAtOpen,h.outside,'a listener can render the focus target before focus is set');
 assert.equal(h.saveChip._menuOpen(),true);assert.equal(h.context.openPanel('save-chip'),true);
 assert.deepEqual(h.panelEvents,['save-panel:panelopen'],'opening an open panel is not a second open');
 h.saveInside.focus();h.saveChip._menuOpen();assert.equal(h.doc.activeElement,h.saveInside,'and it does not move focus');
 h.saveChip._menuOpen({focus:true});assert.equal(h.doc.activeElement,h.saveTitle,'unless the caller asks for it');
 h.loadButton.dispatch('click');
 assert.deepEqual(h.panelEvents,['save-panel:panelopen','save-panel:panelclose','load-panel:panelopen']);
 assert.equal(h.context.closeMenus(),true);assert.equal(h.context.closeMenus(),false);assert.equal(h.saveChip._menuClose(false),false);
 assert.deepEqual(h.panelEvents,['save-panel:panelopen','save-panel:panelclose','load-panel:panelopen','load-panel:panelclose']);
});

test('openPanel opens a panel by its opener\'s id or its own, with the options of initPanel, and refuses anything that is not a panel',()=>{
 const h=harness();
 assert.equal(h.context.openPanel('load-panel'),true);assert.equal(h.loadPanel.hidden,false);assert.equal(h.loadButton.getAttribute('aria-expanded'),'true');
 h.outside.focus();assert.equal(h.context.openPanel('save-chip',{focus:false}),true);
 assert.equal(h.savePanel.hidden,false);assert.equal(h.loadPanel.hidden,true,'still one at a time');assert.equal(h.doc.activeElement,h.outside);
 h.context.closeMenus();
 assert.equal(h.context.openPanel('manager-button'),false,'a menu is not a panel');assert.equal(h.managerList.hidden,true);
 assert.equal(h.context.openPanel('git-save-progress'),false);assert.equal(h.context.openPanel('outside'),false);assert.equal(h.context.openPanel('missing'),false);
});

test('a drawer or dialog that opens closes the panels first (it calls closeMenus), and a lab change or Home closes them',()=>{
 const h=harness();
 h.saveChip.dispatch('click');
 // What saveDrawerOpen does (DRAWERS.md 0.2): closeMenus(), then showModal().
 h.context.closeMenus();h.saveDrawer.open=true;
 assert.equal(h.savePanel.hidden,true);assert.equal(h.saveChip.getAttribute('aria-expanded'),'false');assert.deepEqual(h.panelEvents,['save-panel:panelopen','save-panel:panelclose']);
 assert.equal(h.context.panelCanOpen(h.saveChip),false,'the page never opens a panel over a modal dialog');
 h.context.closeLabDialogs();assert.equal(h.saveDrawer.open,false,'the save drawer speaks for one lab and closes with it');
 assert.equal(h.context.panelCanOpen(h.saveChip),true);
 h.loadButton.dispatch('click');assert.equal(h.context.panelCanOpen(h.saveChip),false,'nor while another panel is open');assert.equal(h.context.panelCanOpen(h.loadButton),true,'its own panel does not count');
 h.context.closeMenus();h.managerButton.dispatch('click');assert.equal(h.context.panelCanOpen(h.saveChip),false,'nor while a menu is open');
 h.context.closeMenus();h.switcher.open=true;assert.equal(h.context.panelCanOpen(h.saveChip),false);h.switcher.open=false;
 h.saveChip.dispatch('click');h.context.goHome();assert.equal(h.savePanel.hidden,true,'Home closes the panel');
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

test('index.html: Lab actions ends with an Advanced options group holding the four reviewed items, one of them hidden until a lab has a retired-telemetry record; nothing else moved or vanished',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 const menu=html.slice(html.indexOf('id="lab-actions-menu"'),html.indexOf('</header>',html.indexOf('id="lab-actions-menu"')));
 const at=menu.indexOf('id="lab-actions-advanced" data-menu-panel'),outside=menu.slice(0,at),group=menu.slice(at);
 assert.ok(at>0);assert.match(menu,/id="lab-actions-advanced-toggle" data-menu-group="lab-actions-advanced" aria-expanded="false" aria-controls="lab-actions-advanced"><span>Advanced options<\/span>/);
 assert.match(group,/^id="lab-actions-advanced" data-menu-panel role="group" aria-labelledby="lab-actions-advanced-toggle" hidden>/);
 assert.deepEqual([...group.matchAll(/role="menuitem" id="([\w-]+)"/g)].map(m=>m[1]),['menu-import-map','menu-map-edit','menu-telemetry-retired','menu-operation-history']);
 assert.match(group,/id="menu-import-map" data-proxy="import-map"/);assert.match(group,/id="menu-map-edit" data-proxy="map-edit"/);
 assert.match(group,/id="menu-telemetry-retired" hidden><span>Retired telemetry configuration…<\/span><\/button>/,'present in the markup, but hidden until the render path shows it');
 for(const id of ['lab-start','menu-sync-vm','menu-capture','menu-lab-files','lab-actions','menu-destroy','menu-remove-lab','lab-actions-advanced-toggle'])assert.match(outside,new RegExp('id="'+id+'"'),id+' stays in the main list');
 assert.ok(outside.indexOf('class="menu-danger"')<outside.indexOf('lab-actions-advanced-toggle'),'the group is the last thing in the menu, after the destructive actions');
 assert.match(html,/id="map-edit" class="button secondary small">Edit map</,'Edit map stays on the map toolbar');assert.match(html,/id="advanced-operation-history"/);assert.match(html,/role="menuitem" id="import-map"/);
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
// bannerHarness plus operations.js (production order), for renderLabOperations()'s menu-item wiring.
function menuHarness(){
 const h=bannerHarness();
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),h.context);
 return h;
}
// app.js declares `let state`/`let activeId`: a plain property assignment on the context object does
// not reach that lexical binding (see setLab in test_telemetry_retired_ui.js), so the active lab is
// set by running an assignment inside the context itself.
function setActiveLab(context,lab){
 vm.runInContext(`activeId='lab';state=${JSON.stringify({labs:[lab],jobs:[],operations:[],restore_jobs:[],git_jobs:[],platforms:{},loaded:true})};`,context);
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

test('the Advanced options group\'s retired-telemetry item is hidden without a record and shown once the active lab has one',()=>{
 const h=menuHarness();
 const lab={id:'lab',name:'demo',nodes:[],deployment:{status:'Not deployed'}};
 setActiveLab(h.context,lab);
 h.context.renderLabOperations();
 assert.equal(h.$('menu-telemetry-retired').hidden,true);
 lab.telemetry_retired={nodes:[{name:'clab-demo-r1',short_name:'r1'}],total:1,malformed:false};
 setActiveLab(h.context,lab);
 h.context.renderLabOperations();
 assert.equal(h.$('menu-telemetry-retired').hidden,false);
 delete lab.telemetry_retired;
 setActiveLab(h.context,lab);
 h.context.renderLabOperations();
 assert.equal(h.$('menu-telemetry-retired').hidden,true,'hides again once the record is gone (removed or forgotten)');
});

test('the Home list tab is kept for the browser session and never throws when storage is blocked',()=>{
 const h=harness();assert.equal(h.context.homeTab(),'recent');assert.equal(h.context.rememberHomeTab('all'),true);assert.equal(h.context.homeTab(),'all');
 const blocked=harness({throwStorage:true});assert.equal(blocked.context.homeTab(),'recent');assert.equal(blocked.context.rememberHomeTab('all'),false);
});

test('U-08: a menu that would open past the left edge anchors to its button instead, measured each time it opens',()=>{
 const h=harness();const list=h.managerList;
 const classes=new Set();list.classList={add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c)};
 list.getBoundingClientRect=()=>({left:-102});
 h.managerButton.dispatch('click');assert.equal(list.hidden,false);assert.equal(classes.has('menu-clamped'),true,'off the left edge (a narrow screen): anchored to the button');
 h.managerButton.dispatch('click');assert.equal(list.hidden,true);
 list.getBoundingClientRect=()=>({left:120});h.managerButton.dispatch('click');assert.equal(classes.has('menu-clamped'),false,'room on the left: the usual right-aligned list');
});

// M-14: the generic x of a notice must not hide a later, different failure that shares its headline.
function noticeLab(){return {id:'lab',name:'Lab',nodes:[],profiles:[],defaults:{},deployment:{status:'Running'}};}
function setLabState(context,lab,extra={}){
 vm.runInContext(`activeId='lab';state=${JSON.stringify({labs:[lab],jobs:[],operations:[],restore_jobs:[],git_jobs:[],platforms:{},loaded:true,...extra})};`,context);
}
test('M-14: closing an action-error notice with the x does not hide the next failure that has the same generic headline',()=>{
 const h=menuHarness();setLabState(h.context,noticeLab());
 const banner=h.$('lab-banner'),close=h.$('lab-banner-close');
 assert.equal(h.context.showActionError('Host said no (first)'),true);
 assert.equal(banner.hidden,false);assert.equal(h.$('lab-banner-detail-text').textContent,'Host said no (first)');
 close.onclick();assert.equal(banner.hidden,true,'the student closed the first failure');
 assert.equal(h.context.actionError(),null,'closing the error clears it, so lower-priority notices are no longer shadowed by it');
 assert.equal(h.context.showActionError('Host said no (second)'),true);
 assert.equal(banner.hidden,false,'a later, different failure with the same generic headline is shown');
 assert.equal(h.$('lab-banner-detail-text').textContent,'Host said no (second)');
});

test('M-14: after the x on an action error the notices underneath it (a failed operation) are not hidden by the stale error',()=>{
 const h=menuHarness();
 const failed={id:'op-1',lab_id:'lab',action:'deploy',status:'failed',created:'2026-09-16T11:00:00Z',finished:'2026-09-16T11:01:00Z',message:'boom'};
 setLabState(h.context,{...noticeLab(),deployment:{status:'Not deployed'}},{operations:[failed]});
 h.context.showActionError('Something broke');
 h.$('lab-banner-close').onclick();
 assert.equal(h.$('lab-banner').hidden,false,'the failed-operation notice is visible at once, not after the next poll');
 assert.equal(h.$('lab-banner-text').textContent,'Starting lab did not finish.');
});

test('M-14: closing the failed-operation notice hides that job only; a later failure of the same kind reopens it',()=>{
 const h=menuHarness();
 const job=(id,at)=>({id,lab_id:'lab',action:'deploy',status:'failed',created:at,finished:at,message:'boom '+id});
 const lab={...noticeLab(),deployment:{status:'Not deployed'}};
 setLabState(h.context,lab,{operations:[job('op-1','2026-09-16T11:00:00Z')]});
 h.context.renderLabBanner();
 const banner=h.$('lab-banner');
 assert.equal(banner.hidden,false);
 h.$('lab-banner-close').onclick();assert.equal(banner.hidden,true);
 h.context.renderLabBanner();assert.equal(banner.hidden,true,'the same job stays closed across the next poll');
 setLabState(h.context,lab,{operations:[job('op-2','2026-09-16T12:00:00Z'),job('op-1','2026-09-16T11:00:00Z')]});
 h.context.renderLabBanner();
 assert.equal(banner.hidden,false,'a new failed job with the identical headline is a new notice');
 assert.equal(h.$('lab-banner-detail-text').textContent,'boom op-2');
});

// M-15: the same dismissal path that covers failed jobs covers restores that ended needs_attention or partial.
test('M-15: dismissedSet() includes needs_attention and partial restore jobs the student dismissed, and the banner offers Dismiss and Details',()=>{
 const h=menuHarness();
 const restore=(id,status)=>({id,lab_id:'lab',status,created:'2026-09-16T11:30:00Z',finished:'2026-09-16T11:30:00Z',message:'1/2 node(s) verified'});
 setLabState(h.context,noticeLab(),{restore_jobs:[restore('rs-1','needs_attention'),restore('rs-2','partial'),restore('rs-3','succeeded')]});
 vm.runInContext(`isDismissed=id=>['rs-1','rs-2','rs-3'].includes(id);`,h.context);
 assert.deepEqual([...h.context.dismissedSet()].sort(),['rs-1','rs-2'],'succeeded jobs are never in the set');
 vm.runInContext(`isDismissed=()=>false;`,h.context);
 setLabState(h.context,noticeLab(),{restore_jobs:[restore('rs-1','needs_attention')]});
 h.context.renderLabBanner();
 assert.equal(h.$('lab-banner').hidden,false);assert.match(h.$('lab-banner-text').textContent,/needs a check on some devices/);
 assert.equal(h.$('banner-dismiss').hidden,false);assert.equal(h.$('banner-restore').hidden,false);assert.equal(h.$('banner-restore').textContent,'Details');
 assert.equal(h.$('lab-banner').className,'banner warn','needs attention after a replaced configuration is a warning, not an error');
});

// L-31: Try again repeats the request the student confirmed, options included.
test('L-31: Try again on a failed destroy repeats it with the confirmed --cleanup option',()=>{
 const h=menuHarness();
 const failed={id:'op-1',lab_id:'lab',action:'destroy',status:'failed',created:'2026-09-16T11:00:00Z',finished:'2026-09-16T11:01:00Z'};
 setLabState(h.context,noticeLab(),{operations:[failed]});
 vm.runInContext(`var retried=null;opReview=async r=>{retried=r;};`,h.context);
 h.context.rememberJobRequest('op-1',{lab_id:'lab',action:'destroy',options:{cleanup:true}});
 h.context.renderLabBanner();
 const retry=h.$('banner-try-again');
 assert.equal(retry.hidden,false);assert.equal(retry.textContent,'Try again');
 retry.onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext('retried',h.context))),{lab_id:'lab',action:'destroy',options:{cleanup:true}});
});

test('L-31: without a stored request a destroy retries with the default options; an action whose options or text are unknown offers the operations dialog instead of a weaker repeat',()=>{
 const h=menuHarness();
 const make=action=>({id:'op-'+action,lab_id:'lab',action,status:'failed',created:'2026-09-16T11:00:00Z',finished:'2026-09-16T11:01:00Z'});
 vm.runInContext(`var retried=null,opened=null;opReview=async r=>{retried=r;};openLabOperations=id=>{opened=id;};`,h.context);
 setLabState(h.context,noticeLab(),{operations:[make('destroy')]});
 h.context.renderLabBanner();h.$('banner-try-again').onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext('retried',h.context))),{lab_id:'lab',action:'destroy',options:{cleanup:true}});
 vm.runInContext('retried=null',h.context);
 for(const action of ['deploy','redeploy','create','revise']){
  setLabState(h.context,noticeLab(),{operations:[make(action)]});
  h.context.renderLabBanner();
  assert.equal(h.$('banner-try-again').textContent,'Open lab operations',action+': the original options are unknown, so nothing is guessed');
  h.$('banner-try-again').onclick();
  assert.equal(vm.runInContext('opened',h.context),'lab');assert.equal(vm.runInContext('retried',h.context),null,'no weaker request is sent for '+action);
 }
 setLabState(h.context,noticeLab(),{operations:[make('stop')]});
 h.context.renderLabBanner();assert.equal(h.$('banner-try-again').textContent,'Try again','an action without options retries as it was');
});

// The page skeleton of the save and load redesign (docs/git-redesign): header markup, the one drawer, the hooks in app.js.
test('index.html: the lab header holds chip, Save, Load, then Lab actions; the chip and Load are panel openers; the split menu and #lab-progress are gone',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 const header=html.slice(html.indexOf('<header class="lab-header">'),html.indexOf('</header>',html.indexOf('<header class="lab-header">')));
 const at=id=>header.indexOf('id="'+id+'"');
 for(const id of ['save-control','save-chip','save-chip-dot','save-chip-text','save-panel','save-panel-title','save-panel-dot','save-panel-title-text','save-panel-body','git-save-progress','load-button','load-panel','load-panel-body','lab-actions-button','save-reason','save-live'])assert.equal(header.split('id="'+id+'"').length,2,id+' is in the header exactly once');
 assert.ok(at('save-chip')<at('git-save-progress')&&at('git-save-progress')<at('load-button')&&at('load-button')<at('lab-actions-button'),'DOM order is the visual order');
 assert.match(header,/<button type="button" class="button secondary panel-button save-chip" id="save-chip" aria-haspopup="dialog" aria-expanded="false" aria-controls="save-panel">/);
 assert.match(header,/<button type="button" class="button secondary panel-button" id="load-button" aria-haspopup="dialog" aria-expanded="false" aria-controls="load-panel">Load<\/button>/);
 assert.match(header,/<button type="button" class="button primary" id="git-save-progress" aria-describedby="save-reason">Save<\/button>/,'the load-bearing id stays on Save');
 assert.match(header,/<div class="save-panel" id="save-panel" data-panel role="dialog" aria-labelledby="save-panel-title" hidden>\s*<h2 class="save-state" id="save-panel-title" tabindex="-1" data-panel-focus>/);
 assert.match(header,/<div class="save-panel wide" id="load-panel" data-panel role="dialog" aria-label="Load a saved state" hidden><div id="load-panel-body"><\/div><\/div>/);
 // Each opener and its panel are the two children of one span.menu, the element an outside click is measured against.
 for(const [button,panel] of [['save-chip','save-panel'],['load-button','load-panel']]){const open=header.lastIndexOf('<span class="menu">',at(button));assert.ok(open>=0&&!header.slice(open,at(button)).includes('</span>'),button+' sits directly in a span.menu');assert.ok(at(panel)>at(button));}
 assert.match(header,/<small class="caption" id="save-reason" hidden><\/small>\s*<p class="sr-only" id="save-live" role="status" aria-live="polite"><\/p>/,'the reason is visible text; the live region holds a sentence, never a button');
 assert.doesNotMatch(html,/id="lab-progress"|git-save-menu|git-save-help|git-save-control|banner-retry-save|banner-save-details/);
 assert.doesNotMatch(header,/data-git-action/);assert.doesNotMatch(header,/ style=/);
 // First wave: the Progress tab and what git-progress.js renders into stay.
 for(const id of ['git-progress-bar','progress-save','git-saved-versions','git-saves-list','git-repository-content'])assert.match(html,new RegExp('id="'+id+'"'),id+' stays');
});

test('index.html: the one save drawer is a page-level lab dialog with a static head, and the three new scripts load in the agreed order with the release marker',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 const start=html.indexOf('<dialog id="save-drawer"'),drawer=html.slice(start,html.indexOf('</dialog>',start));
 assert.match(drawer,/^<dialog id="save-drawer" class="drawer save-drawer" data-lab-dialog aria-labelledby="save-drawer-title">/);
 assert.ok(start>html.indexOf('</main>'),'never inside a tab panel: a modal in a hidden panel shows nothing');
 for(const id of ['save-drawer-back','save-drawer-title','save-drawer-close','save-drawer-meta','save-drawer-actions','save-drawer-content','save-drawer-status'])assert.equal(html.split('id="'+id+'"').length,2,id);
 assert.match(drawer,/<button type="button" class="button ghost small" id="save-drawer-back" hidden>Back<\/button>/);
 assert.match(drawer,/<button type="button" class="icon-button close" id="save-drawer-close" aria-label="Close">/);
 assert.match(drawer,/<p class="sr-only" role="status" aria-live="polite" id="save-drawer-status"><\/p>/);
 const scripts=[...html.matchAll(/<script src="\/static\/([\w-]+\.js)\?v=([\d.]+)" defer><\/script>/g)].map(m=>m[1]),versions=new Set([...html.matchAll(/<script src="\/static\/[\w-]+\.js\?v=([\d.]+)"/g)].map(m=>m[1]));
 const at=scripts.indexOf('diff-view.js');
 assert.deepEqual(scripts.slice(at,at+7),['diff-view.js','git-progress.js','save-header.js','git-places.js','save-drawers.js','load.js','restore.js']);
 assert.equal(versions.size,1,'every script carries the same release marker');
 assert.ok(scripts.indexOf('shell.js')<scripts.indexOf('app.js')&&scripts.indexOf('app.js')<at);
});

test('style.css: the header group is one wrapping row with chip and Save kept together; the retired split menu rules are gone; dots survive forced colours',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8');
 assert.match(css,/\.save-control \{ display: contents; \}/);assert.match(css,/\.save-pair \{ display: flex; align-items: center; gap: 8px; min-width: 0; flex: 0 1 auto; \}/);
 assert.match(css,/\.save-chip \{[^}]*min-width: 0; max-width: 16rem; \}/);assert.match(css,/#save-chip-text \{[^}]*text-overflow: ellipsis/);
 assert.match(css,/@media \(min-width: 1280px\) \{ #lab-content \{ --lab-action-col: 36rem; \} \}/);
 assert.ok(css.indexOf('--lab-action-col: 36rem')>css.indexOf('--lab-action-col: 26rem'),'the wider column follows the 901px rule it overrides');
 assert.match(css,/\.save-panel \{[^}]*position: absolute;[^}]*width: min\(380px, calc\(100vw - 32px\)\);[^}]*max-height: calc\(100dvh - 140px\);[^}]*overflow-y: auto;/);
 assert.match(css,/\.save-panel\.wide \{ width: min\(440px, calc\(100vw - 32px\)\); \}/);
 assert.match(css,/\.save-panel\.menu-clamped \{ right: auto; left: 0; \}/);
 assert.match(css,/\.lab-header-actions \{ position: relative; \}\s*\.menu\.panel-anchored \{ position: static; \}\s*\.menu\.panel-anchored > \.save-panel \{ right: auto; left: 0; \}/,'a panel that fits neither way hangs from the action row\'s left edge');
 assert.match(css,/\.save-dot\.none \{ background: transparent; border: 2px solid var\(--muted\); \}/);
 assert.match(css,/\.save-dot \{ forced-color-adjust: none; box-shadow: none; \}\s*\.save-dot:not\(\.none\) \{ background: CanvasText; \}\s*\.save-dot\.none \{ background: Canvas; border: 1px solid CanvasText; \}/,'filled and hollow stay apart in forced colours');
 assert.match(css,/\.lab-header:has\(\.pill\.busy\) \.save-dot\.busy \{ animation: none; \}/);
 assert.match(css,/dialog\.drawer\.save-drawer \{ width: min\(760px, 100vw\); \}/);
 assert.ok(css.indexOf('dialog.drawer.save-drawer {')<css.indexOf('dialog.drawer, dialog.node-details {'),'it precedes the device drawer\'s width, so it must be the more specific selector');
 assert.match(css,/\.checkbox-label\.save-keep \{/,'likewise against .checkbox-label');
 for(const name of ['save-state','save-sub','save-row','save-note','save-kv','save-foot','save-name','save-keep','save-heading','save-list','save-item','save-when','save-why','save-devices','save-end','save-settings','save-settings-foot','folder-tree','folder-row','folder-name','folder-answer','folder-names','folder-state','panel-button'])assert.ok(css.includes('.'+name),'.'+name+' has a rule');
 for(const cls of ['ok','bad','now','warn'])assert.ok(css.includes('.save-end.'+cls+' {'),'save-end.'+cls);
 assert.doesNotMatch(css,/\.git-save-(control|menu|options|list|help)/);
 const rules=[...css.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter(m=>/[.#](save|folder)-|\.panel-button/.test(m[1])&&!m[1].includes('.pill'));   // the shared high-contrast pill rule keeps its white
 assert.ok(rules.length>60);for(const [,selector,body] of rules)assert.doesNotMatch(body,/#[0-9a-fA-F]{3,8}\b|rgba?\(/,'no new colour, tokens only: '+selector.trim());
});

test('render() hands every poll and every lab switch to the header and the drawer, after renderGitProgress, and loads without them',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8'),body=source.slice(source.indexOf('function render(){'),source.indexOf('function syncProxies'));
 const order=['renderGitProgress','renderSaveHeader','saveDrawerRender','renderNetworkDesign'].map(name=>body.indexOf(`if(typeof ${name}==='function')${name}();`));
 assert.ok(order.every(i=>i>=0),'each is called behind its typeof guard');assert.deepEqual([...order].sort((a,b)=>a-b),order);
 assert.ok(order[2]<body.indexOf('if(!lab){'),'also on Home, so the drawer and the panels can drop a lab that is no longer open');
 assert.doesNotMatch(source,/lab-progress|banner-retry-save|banner-save-details|gitPushPending/);
});

test('the lab banner no longer reports a save: a save location problem and a failed upload are the chip\'s; what a load or an operation reports stays',()=>{
 const h=bannerHarness(),lab={id:'lab',name:'L',nodes:[],profiles:[],defaults:{},deployment:{status:'Running'},nos_readiness:{status:'idle'},git_binding:{repository:{push_url:'https://github.com/x/y.git'}}};
 const paint=extra=>vm.runInContext(`state=${JSON.stringify({labs:[lab],jobs:[],operations:[],restore_jobs:[],git_jobs:[],platforms:{},loaded:true,...extra})};activeId='lab';var gitContexts=new Map([['lab',{repository_status:{problem:'The push URL rejected the VM account.'}}]]);renderLabBanner();`,h.context);
 paint({git_jobs:[{id:'g1',lab_id:'lab',status:'push_pending',message:'Upload failed.',created:'2026-10-04T10:00:00Z'}]});
 assert.equal(h.$('lab-banner').hidden,true,'neither the problem nor the failed upload makes a banner');
 paint({restore_jobs:[{id:'r1',lab_id:'lab',status:'applying',message:'Applying.'}]});
 assert.equal(h.$('lab-banner').hidden,false);assert.equal(h.$('banner-restore').hidden,false,'a running load keeps View progress');
 paint({operations:[{id:'o1',lab_id:'lab',action:'deploy',status:'running',message:'Executing'}]});
 assert.equal(h.$('lab-banner').hidden,false);assert.equal(h.$('banner-output').hidden,false);
});

test('busyReason() names what holds the manager for each thing the server\'s operation_busy and save guard count, and busy() is its flag',()=>{
 const h=bannerHarness(),labs=[{id:'lab',name:'Mine',nodes:[]},{id:'other',name:'OSPF-lab',nodes:[]}];
 const ask=(extra,labsNow=labs)=>{vm.runInContext(`activeId='lab';state=${JSON.stringify({labs:labsNow,jobs:[],operations:[],restore_jobs:[],git_jobs:[],design_jobs:[],platforms:{},loaded:true,...extra})};`,h.context);return [h.context.busyReason(),vm.runInContext('busy()',h.context)];};
 assert.deepEqual(ask({}),['',false],'idle');
 assert.deepEqual(ask({operations:[{id:'o',lab_id:'other',action:'deploy',status:'running'}]}),[h.context.operationLabel('deploy')+' is running.',true]);
 assert.deepEqual(ask({operations:[{id:'o',action:'mystery',status:'queued'}]}),['Lab operation is running.',true]);
 assert.deepEqual(ask({operations:[{id:'o',lab_id:'other',action:'deploy',status:'succeeded'}]}),['',false]);
 for(const status of ['queued','capturing','exporting','pushing'])assert.deepEqual(ask({git_jobs:[{id:'g',lab_id:'other',status}]}),['A save is running on OSPF-lab.',true],status);
 for(const status of ['committed','review_pending','push_pending','synced','unchanged','failed'])assert.deepEqual(ask({git_jobs:[{id:'g',lab_id:'other',status}]}),['',false],'a waiting or finished save holds nothing: '+status);
 for(const status of ['queued','preflight','backing_up','applying','confirming','verifying'])assert.deepEqual(ask({restore_jobs:[{id:'r',lab_id:'other',status}]}),['A load is running on OSPF-lab.',true],status);
 assert.deepEqual(ask({restore_jobs:[{id:'r',lab_id:'other',status:'interrupted',rechecking:true}]}),['The manager is checking devices after a restart.',true],'a load read back after a restart holds every lab');
 assert.deepEqual(ask({restore_jobs:[{id:'r',lab_id:'other',status:'interrupted'},{id:'r2',lab_id:'other',status:'verified'}]}),['',false]);
 for(const status of ['queued','preflight','backing_up','applying','confirming','verifying'])assert.deepEqual(ask({design_jobs:[{id:'d',lab_id:'other',status}]}),['A network design is being applied on OSPF-lab.',true],status);
 assert.deepEqual(ask({design_jobs:[{id:'d',lab_id:'lab',status:'interrupted',rechecking:['r1']}]}),['The manager is checking devices after a restart.',true],'a design read-back holds its own lab');
 assert.deepEqual(ask({design_jobs:[{id:'d',lab_id:'other',status:'interrupted',rechecking:['r1']}]}),['',false],'and only its own lab');
 vm.runInContext(`state.design_jobs=[{id:'d',lab_id:'other',status:'interrupted',rechecking:['r1']}];`,h.context);assert.equal(h.context.busyReason('other'),'The manager is checking devices after a restart.','asked for that lab');
 assert.deepEqual(ask({},[labs[0],{...labs[1],telemetry_retired:{nodes:[],total:0,removing:'2026-10-04T10:00:00Z'}}]),['Retired telemetry configuration is being removed on OSPF-lab.',true]);
 assert.deepEqual(ask({},[labs[0],{...labs[1],telemetry_retired:{nodes:[],total:0}}]),['',false]);
 assert.deepEqual(ask({jobs:[{id:'j',lab_id:'other',operation:'backup',status:'running'}]}),['A backup is running.',true]);
 assert.deepEqual(ask({jobs:[{id:'j',lab_id:'other',operation:'test',status:'queued'}]}),['Device logins are being checked.',true]);
 assert.deepEqual(ask({jobs:[{id:'j',lab_id:'other',operation:'backup',status:'succeeded'}]}),['',false]);
 assert.deepEqual(ask({git_jobs:[{id:'g',lab_id:'gone',status:'capturing'}]}),['A save is running.',true],'a lab the page does not know is not named');
 // Server order: a lab operation is named before a save that also runs.
 assert.match(ask({operations:[{id:'o',lab_id:'lab',action:'destroy',status:'running'}],git_jobs:[{id:'g',lab_id:'other',status:'capturing'}]})[0],/ is running\.$/);
 assert.doesNotMatch(ask({operations:[{id:'o',lab_id:'lab',action:'destroy',status:'running'}],git_jobs:[{id:'g',lab_id:'other',status:'capturing'}]})[0],/save/);
});

test('a panel that would open past the left edge anchors to its opener; one that then leaves the right edge hangs from the action row; measured each time it opens',()=>{
 const h=harness();const set=()=>{const c=new Set();return {add:x=>c.add(x),remove:x=>c.delete(x),contains:x=>c.has(x)};};
 const panel=h.loadPanel,wrapper=h.loadButton.parentElement;panel.classList=set();wrapper.classList=set();h.context.innerWidth=390;
 let box={left:120,right:560};panel.getBoundingClientRect=()=>box;
 h.loadButton.dispatch('click');assert.equal(panel.classList.contains('menu-clamped'),false,'room on the left: right-aligned to the opener');assert.equal(wrapper.classList.contains('panel-anchored'),false);
 h.loadButton.dispatch('click');
 panel.getBoundingClientRect=()=>panel.classList.contains('menu-clamped')?{left:16,right:374}:{left:-90,right:268};
 h.loadButton.dispatch('click');assert.equal(panel.classList.contains('menu-clamped'),true,'off the left edge: anchored to the opener\'s left');assert.equal(wrapper.classList.contains('panel-anchored'),false,'and it fits there');
 h.loadButton.dispatch('click');
 panel.getBoundingClientRect=()=>panel.classList.contains('menu-clamped')?{left:268,right:626}:{left:-22,right:336};
 h.loadButton.dispatch('click');assert.equal(wrapper.classList.contains('panel-anchored'),true,'the opener is mid-row on a phone: the panel hangs from the row instead');
 h.loadButton.dispatch('click');box={left:120,right:560};panel.getBoundingClientRect=()=>box;
 h.loadButton.dispatch('click');assert.equal(panel.classList.contains('menu-clamped'),false);assert.equal(wrapper.classList.contains('panel-anchored'),false,'both are measured again on the next open');
});
