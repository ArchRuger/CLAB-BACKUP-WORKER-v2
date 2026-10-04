'use strict';
// shell.js — navigation, menus and browser storage for index.html. Everything that touches window,
// location, history, localStorage or a document-level listener lives here, so app.js keeps loading
// in the node harnesses that have none of them. app.js globals (state, activeId, tab, detailName,
// selectLab, showTab, openDetails, render, renderLabBanner, notify) are read at call time, never at load.
const SHELL_ROUTE_KEYS=['lab','view','device'];
let shellSessionConsumed=false, shellApplying=false, shellMenuCount=0, shellActionError=null, shellActionSeq=0;
const shellEl=id=>document.getElementById(id);
// Storage is optional: private windows, blocked site data and thumbnail captures all throw or return
// nothing, and the page must render either way.
function shellGet(kind,key){try{return window[kind].getItem(key);}catch{return null;}}
function shellSet(kind,key,value){try{window[kind].setItem(key,value);return true;}catch{return false;}}
function shellRemove(kind,key){try{window[kind].removeItem(key);return true;}catch{return false;}}
function shellHash(){try{return String(location.hash||'');}catch{return '';}}
// Route: #lab=<id>&view=<tab>&device=<name>. The hash is the source of truth once the page has loaded.
function readRoute(){const params=new URLSearchParams(shellHash().replace(/^#/,''));return {lab:params.get('lab')||'',view:params.get('view')||'',device:params.get('device')||''};}
function serialiseRoute(route){const params=new URLSearchParams();for(const key of SHELL_ROUTE_KEYS)if(route&&route[key])params.set(key,route[key]);const text=params.toString();return text?'#'+text:'';}
function currentRoute(){const lab=typeof activeId==='string'?activeId:'',dialog=shellEl('details-dialog');return {lab,view:lab&&typeof tab==='string'?tab:'',device:lab&&dialog&&dialog.open&&typeof detailName==='string'?detailName:''};}
// No-op when the serialised route already matches; replaceState for poll-driven writes, pushState only
// for user navigation (and never while a route is being applied, or Back would loop).
function writeRoute(route,options={}){
 const next=serialiseRoute(route),hash=shellHash();
 if(next===hash||(next===''&&hash==='#'))return false;
 const push=!!options.push&&!shellApplying;
 try{const url=location.pathname+location.search+next;if(push)history.pushState(null,'',url);else history.replaceState(null,'',url);}
 catch{try{location.hash=next;}catch{/* no history API: the route stays in memory only */}}
 return true;
}
// Precedence on the first load: hash → sessionStorage.activeLab (read once, then removed; legacy writers
// keep setting it) → Home. An unknown id falls back to Home. Later calls (hashchange) diff against the
// current lab, tab and open device before touching anything.
function applyRoute(){
 if(typeof state==='undefined'||!state||!state.loaded)return false;
 let route=readRoute();
 if(!route.lab&&!shellSessionConsumed){const stored=shellGet('sessionStorage','activeLab');if(stored)route={lab:String(stored),view:'',device:''};}
 if(!shellSessionConsumed){shellSessionConsumed=true;shellRemove('sessionStorage','activeLab');}
 const known=!!route.lab&&(state.labs||[]).some(l=>l.id===route.lab);
 shellApplying=true;
 try{
  if(!known){if(typeof activeId==='string'&&activeId)goHome();else writeRoute({});return true;}
  const view=route.view||'topology';
  if(route.lab!==activeId){if(typeof selectLab==='function')selectLab(route.lab,view);}
  else if(view!==tab&&typeof showTab==='function')showTab(view);
  const dialog=shellEl('details-dialog'),openDevice=dialog&&dialog.open&&typeof detailName==='string'?detailName:'';
  if(route.device&&route.device!==openDevice){if(typeof openDetails==='function')openDetails(route.device);}
  else if(!route.device&&openDevice&&dialog&&typeof dialog.close==='function')dialog.close();
  writeRoute(currentRoute());
 }finally{shellApplying=false;}
 return true;
}
// Dialogs that speak for one lab (the device drawer and every dialog marked data-lab-dialog: the design's
// Remove and Renumber, its Apply and Export reviews) close when the page moves to another lab or Home. A
// dialog left open over the next lab must never act on the lab it was opened for (QA-021).
function closeLabDialogs(){
 const dialog=shellEl('details-dialog');if(dialog&&dialog.open&&typeof dialog.close==='function')dialog.close();
 if(typeof document==='undefined'||!document||typeof document.querySelectorAll!=='function')return;
 for(const d of document.querySelectorAll('dialog[data-lab-dialog][open]'))if(typeof d.close==='function')d.close();
}
function goHome(options={}){
 closeLabDialogs();
 if(typeof activeId!=='undefined')activeId='';
 shellRemove('sessionStorage','activeLab');closeMenus();shellActionError=null;
 writeRoute({},options);
 if(typeof render==='function')render();
 return true;
}
// Menus. New menus are button + sibling div.menu-list inside span.menu (initMenu); the header's chip and
// Load panels are button + sibling [data-panel] inside span.menu (initPanel); #lab-switcher stays <details>.
// closeMenus(except) closes every menu and panel except the one containing `except` and returns true when
// it closed something, so topology.js can defer its Escape handling. A drawer or dialog that opens calls it first.
function shellContains(menu,el){return !!menu&&!!el&&(menu===el||(typeof menu.contains==='function'&&menu.contains(el)));}
function closeMenus(except){
 let closed=false;
 for(const button of document.querySelectorAll('.menu-button[aria-expanded="true"], .panel-button[aria-expanded="true"]')){if(shellContains(button.parentElement||button,except))continue;if(typeof button._menuClose==='function'&&button._menuClose(false))closed=true;}
 for(const details of document.querySelectorAll('details.menu[open], details#lab-switcher[open]')){if(shellContains(details,except))continue;details.open=false;closed=true;}
 return closed;
}
function initMenu(button){
 if(!button||button._menuReady)return null;
 const wrapper=button.parentElement,list=wrapper&&typeof wrapper.querySelector==='function'?wrapper.querySelector('.menu-list'):null;
 if(!list)return null;button._menuReady=true;
 if(!list.id)list.id=(button.id||'menu-'+(++shellMenuCount))+'-list';
 button.setAttribute('aria-haspopup','menu');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls',list.id);list.setAttribute('role','menu');list.hidden=true;
 // A menu may hold one or more expandable groups: a [data-menu-group="<panel id>"] item shows and hides
 // the [data-menu-panel] with that id. Items of a collapsed panel are skipped by the arrow keys, the
 // toggle never closes the menu, and every panel is collapsed again when the menu opens.
 const panelOf=toggle=>toggle&&typeof toggle.getAttribute==='function'&&toggle.getAttribute('data-menu-group')?shellEl(toggle.getAttribute('data-menu-group')):null;
 const items=()=>[...list.querySelectorAll('[role="menuitem"]')].filter(item=>!item.disabled&&!item.hidden&&!(typeof item.closest==='function'&&item.closest('[data-menu-panel][hidden]')));
 const setGroup=(toggle,expanded,focus)=>{
  const panel=panelOf(toggle);if(!panel)return false;
  panel.hidden=!expanded;toggle.setAttribute('aria-expanded',expanded?'true':'false');
  if(expanded){const inside=items().filter(item=>shellContains(panel,item));if(focus&&inside[0]&&typeof inside[0].focus==='function')inside[0].focus();const last=inside[inside.length-1]||toggle;if(typeof last.scrollIntoView==='function')last.scrollIntoView({block:'nearest'});}
  else if(focus&&typeof toggle.focus==='function')toggle.focus();
  return true;
 };
 const toggles=()=>[...list.querySelectorAll('[data-menu-group]')];
 const close=restore=>{if(list.hidden)return false;list.hidden=true;button.setAttribute('aria-expanded','false');if(restore&&typeof button.focus==='function')button.focus();return true;};
 // A list is right-aligned to its button; near the left edge of a narrow screen that would put its items
 // off screen, so it anchors to the button's left instead (menu-clamped), measured each time it opens.
 const clamp=()=>{if(typeof list.getBoundingClientRect!=='function'||!list.classList)return;list.classList.remove('menu-clamped');if(list.getBoundingClientRect().left<8)list.classList.add('menu-clamped');};
 const open=()=>{closeMenus(wrapper);for(const toggle of toggles())setGroup(toggle,false,false);list.hidden=false;clamp();button.setAttribute('aria-expanded','true');const first=items()[0];if(first&&typeof first.focus==='function')first.focus();if(typeof CustomEvent==='function'&&typeof list.dispatchEvent==='function')list.dispatchEvent(new CustomEvent('menuopen'));};
 button._menuClose=close;button._menuOpen=open;
 button.addEventListener('click',()=>{if(list.hidden)open();else close(false);});
 button.addEventListener('keydown',e=>{if(e.key==='ArrowDown'&&list.hidden){e.preventDefault();open();}});
 list.addEventListener('keydown',e=>{
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);return;}
  if(e.key==='Tab'){close(false);return;}
  if(e.key==='ArrowRight'||e.key==='ArrowLeft'){
   const at=document.activeElement,toggle=at&&typeof at.closest==='function'?(at.closest('[data-menu-group]')||toggles().find(t=>shellContains(panelOf(t),at))):null;
   if(toggle&&setGroup(toggle,e.key==='ArrowRight',true))e.preventDefault();
   return;
  }
  if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;
  const all=items();if(!all.length)return;e.preventDefault();
  const i=all.indexOf(document.activeElement),next=e.key==='Home'?0:e.key==='End'?all.length-1:e.key==='ArrowDown'?(i+1)%all.length:(i-1+all.length)%all.length;
  if(typeof all[next].focus==='function')all[next].focus();
 });
 // Capture phase: the menu closes and focus returns to the button before the item's own handler runs,
 // so a dialog opened by the item gives focus back to the button when it closes.
 list.addEventListener('click',e=>{const item=e.target&&typeof e.target.closest==='function'?e.target.closest('[role="menuitem"]'):null;if(!item||item.disabled||!shellContains(list,item))return;if(panelOf(item)){setGroup(item,item.getAttribute('aria-expanded')!=='true',false);return;}close(true);},true);
 return {open,close};
}
// Panels: a .panel-button and its sibling [data-panel] inside span.menu (the chip panel, the Load panel). A panel is a
// non-modal dialog, not a menu: no roving focus, Tab moves through it, a click inside never closes it. It shares
// closeMenus(), so one panel or menu is open at a time; shellPointerDown closes it on an outside click.
// The panel element gets a `panelopen` event when it opens (before focus moves, so a listener can render the
// focus target first) and `panelclose` when it closes: each once per change, never for a call that changes nothing.
function initPanel(button){
 if(!button||button._menuReady)return null;
 // The panel is the opener's sibling, never one nested deeper in another wrapper.
 const wrapper=button.parentElement,panel=wrapper&&wrapper.children?[...wrapper.children].find(child=>child!==button&&typeof child.hasAttribute==='function'&&child.hasAttribute('data-panel'))||null:null;
 if(!panel)return null;button._menuReady=true;
 button.setAttribute('aria-expanded','false');panel.hidden=true;
 const fire=name=>{if(typeof CustomEvent==='function'&&typeof panel.dispatchEvent==='function')panel.dispatchEvent(new CustomEvent(name));};
 const focusIn=()=>{const target=panel.querySelector('[data-panel-focus]')||panel;if(typeof target.focus==='function')target.focus();};
 const close=restore=>{if(panel.hidden)return false;panel.hidden=true;button.setAttribute('aria-expanded','false');fire('panelclose');if(restore&&typeof button.focus==='function')button.focus();return true;};
 // A panel is right-aligned to its opener. Where that would put it past the left edge of a narrow screen it anchors to
 // the opener's left instead (menu-clamped); where even that leaves the screen on the right (the opener is not at the
 // left gutter) the wrapper stops being its anchor (panel-anchored) and it hangs under the whole action row, from that
 // row's left edge. Measured each time it opens; classes only, never an inline style.
 const clamp=()=>{
  if(typeof panel.getBoundingClientRect!=='function'||!panel.classList||!wrapper.classList)return;
  panel.classList.remove('menu-clamped');wrapper.classList.remove('panel-anchored');
  if(panel.getBoundingClientRect().left>=8)return;
  panel.classList.add('menu-clamped');
  const width=typeof innerWidth==='number'?innerWidth:0;
  if(width&&panel.getBoundingClientRect().right>width-8)wrapper.classList.add('panel-anchored');
 };
 // options.focus===false: opened by the page, not by the person; focus stays where it is. An open panel stays as it
 // is (no second event, no focus move) unless the caller asks for the focus with options.focus===true.
 const open=(options={})=>{
  if(!panel.hidden){if(options.focus===true)focusIn();return true;}
  closeMenus(wrapper);panel.hidden=false;clamp();button.setAttribute('aria-expanded','true');fire('panelopen');
  if(options.focus!==false)focusIn();
  return true;
 };
 button._menuClose=close;button._menuOpen=open;button._panelButton=true;
 button.addEventListener('click',()=>{if(panel.hidden)open();else close(false);});
 panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}});
 // Tab or a click that moves focus to another control closes it; a rebuilt body (focus falls to nothing) does not.
 wrapper.addEventListener('focusout',e=>{const next=e.relatedTarget;if(next&&!shellContains(wrapper,next))close(false);});
 return {open,close};
}
// Open a panel by the id of its opener or of the panel itself (openPanel('save-chip'), openPanel('load-panel')).
// Returns false when there is no such panel. options.focus as in initPanel.
function openPanel(id,options={}){
 const el=shellEl(id);if(!el)return false;
 let button=null;
 if(el._panelButton)button=el;
 else if(typeof el.hasAttribute==='function'&&el.hasAttribute('data-panel')&&el.parentElement&&el.parentElement.children)button=[...el.parentElement.children].find(child=>child._panelButton)||null;
 return !!button&&!!button._panelButton&&button._menuOpen(options);
}
// Whether the page may open a panel by itself: never over a modal dialog, never while another menu or panel is open.
function panelCanOpen(button){
 if(typeof document==='undefined'||typeof document.querySelector!=='function')return false;
 if(document.querySelector('dialog[open]'))return false;
 const other=document.querySelector('.menu-button[aria-expanded="true"], .panel-button[aria-expanded="true"], details.menu[open], details#lab-switcher[open]');
 return !other||other===button;
}
// Escape priority: node context menu (topology.js) → open menus and panels → expanded map (topology.js). Closing a
// menu stops the event here so the map handler never sees it; focus inside a .menu-list or a panel is handled by
// its own keydown, which restores focus to the button. A panel the page opened while focus was elsewhere is closed
// by closeMenus() below and focus stays where it is.
function shellEscape(e){
 if(e.key!=='Escape')return;
 const target=e.target&&typeof e.target.closest==='function'?e.target:null;
 const nodeMenu=shellEl('node-context-menu');if(nodeMenu&&!nodeMenu.hidden)return;
 if(target&&target.closest('.menu-list, [data-panel]'))return;
 const details=target?target.closest('details#lab-switcher, details.menu'):null;
 if(details&&details.open){details.open=false;const summary=typeof details.querySelector==='function'?details.querySelector('summary'):null;if(summary&&typeof summary.focus==='function')summary.focus();e.stopPropagation();return;}
 if(closeMenus())e.stopPropagation();
}
function shellPointerDown(e){const target=e.target&&typeof e.target.closest==='function'?e.target:null;const menu=target?target.closest('.menu, details#lab-switcher'):null;closeMenus(menu||undefined);}
// localStorage: when each lab was opened (the card's "Opened …" line in home.js), and dismissed job warnings.
function rememberOpened(id){if(!id)return false;return shellSet('localStorage','clab.opened.'+id,new Date().toISOString());}
// sessionStorage: the Home list tab the student chose (home.js), for this browser session.
function homeTab(){return shellGet('sessionStorage','clab.homeTab')||'recent';}
function rememberHomeTab(tab){return shellSet('sessionStorage','clab.homeTab',String(tab||'recent'));}
function openedAt(id){return id?shellGet('localStorage','clab.opened.'+id)||'':'';}
function isDismissed(jobId){return !!jobId&&!!shellGet('localStorage','clab.dismissed.'+jobId);}
function dismissJob(jobId){return !!jobId&&shellSet('localStorage','clab.dismissed.'+jobId,new Date().toISOString());}
// sessionStorage: notices closed with the generic × (setBanner, app.js builds the key from the lab, the
// banner id and a digest of the headline). Session-scoped, not localStorage: a notice a student closed
// reopens next visit rather than staying hidden forever, and closing one never touches a job record.
function noticeDismissed(key){return !!key&&!!shellGet('sessionStorage','clab.notice.'+key);}
function dismissNotice(key){return !!key&&shellSet('sessionStorage','clab.notice.'+key,'1');}
// sessionStorage: the request the student confirmed for a lab operation (action, options, path, node), by the
// job id the manager answered with, so Try again on a failed job repeats exactly that request (the manager's
// job record carries no options). Memory first; sessionStorage keeps it across a reload for small requests only.
const shellJobRequests=new Map();
function rememberJobRequest(jobId,request){
 if(!jobId||!request||typeof request!=='object')return false;
 const copy={};for(const k of ['lab_id','action','path','name','node','options'])if(request[k]!==undefined)copy[k]=request[k];
 shellJobRequests.set(jobId,copy);
 let text='';try{text=JSON.stringify(copy);}catch{return false;}
 return text.length<=4000&&shellSet('sessionStorage','clab.request.'+jobId,text);
}
function jobRequest(jobId){
 if(!jobId)return null;
 if(shellJobRequests.has(jobId))return shellJobRequests.get(jobId);
 const raw=shellGet('sessionStorage','clab.request.'+jobId);if(!raw)return null;
 try{const value=JSON.parse(raw);return value&&typeof value==='object'&&typeof value.action==='string'?value:null;}catch{return null;}
}
// localStorage: the Network design page's unsaved draft for one lab ({revision, intent}), so a reload
// or an accidental tab close does not lose guided or advanced edits that were never saved. network-design.js
// drops a stored draft itself once its revision no longer matches the saved design.
function designDraftKey(labId){return 'clab.design.draft.'+labId;}
function readDesignDraft(labId){
 if(!labId)return null;
 const raw=shellGet('localStorage',designDraftKey(labId));if(!raw)return null;
 try{const value=JSON.parse(raw);return value&&typeof value==='object'&&value.intent?value:null;}catch{return null;}
}
function writeDesignDraft(labId,value){
 if(!labId)return false;
 try{return shellSet('localStorage',designDraftKey(labId),JSON.stringify(value));}catch{return false;}
}
function clearDesignDraft(labId){return !!labId&&shellRemove('localStorage',designDraftKey(labId));}
// Failures of header, menu and tool actions: a student sentence in the lab banner with the backend
// message under Details; a toast when there is no lab page to show it on.
function shellErrorSentence(message){
 const text=String(message||'');
 if(/Configured devices changed/i.test(text))return 'The devices in this lab changed since the save location was set up. Check the devices under Save settings.';
 if(/Reconnect the original VM/i.test(text))return 'This lab was set up on a different VM. Reconnect that VM before saving.';
 if(/not connected|VM connection|discovery is not configured/i.test(text))return 'The lab VM is not connected. Choose Manager › VM connection… to set it up.';
 if(/^Restart device… is not available: /.test(text))return text;   // the reason is the sentence
 return 'That did not work. The details below say why.';
}
// Leaving the page with an unsaved Design draft the browser could not store (network-design.js's
// designLeaveGuard) gets the browser's own "leave site?" prompt: that draft exists nowhere else.
if(typeof window!=='undefined'&&typeof window.addEventListener==='function')window.addEventListener('beforeunload',e=>{if(typeof designLeaveGuard==='function'&&designLeaveGuard()){e.preventDefault();e.returnValue='';}});
function showActionError(message){
 const text=String(message||'Something went wrong.'),lab=typeof activeId==='string'?activeId:'';
 if(!lab||!shellEl('lab-banner')||typeof renderLabBanner!=='function'){if(typeof notify==='function')notify(text);return false;}
 shellActionError={lab,message:text,sentence:shellErrorSentence(text),at:Date.now(),seq:++shellActionSeq};
 renderLabBanner();return true;
}
function actionError(){return shellActionError;}
function dismissActionError(){shellActionError=null;}
// Load-time wiring: every static .menu-button and .panel-button, the Home links, the drawer's close event, the router and
// the delayed skeleton (only shown when the first /state takes longer than 200 ms).
document.querySelectorAll('.menu-button').forEach(initMenu);
document.querySelectorAll('.panel-button').forEach(initPanel);
for(const id of ['nav-home','crumb-home']){const el=shellEl(id);if(el)el.addEventListener('click',e=>{e.preventDefault();goHome({push:true});});}
{const dialog=shellEl('details-dialog');if(dialog)dialog.addEventListener('close',()=>{if(!shellApplying)writeRoute({...currentRoute(),device:''});});}
document.addEventListener('keydown',shellEscape,true);
document.addEventListener('pointerdown',shellPointerDown,true);
window.addEventListener('hashchange',()=>{if(!shellApplying)applyRoute();});
setTimeout(()=>{const skeleton=shellEl('home-skeleton');if(skeleton&&!(typeof state!=='undefined'&&state&&state.loaded))skeleton.hidden=false;},200);
// Deferred scripts run in order, and a fast first /api/state answer can render before the later scripts
// (operations, Git, capture) have defined their renderers; those parts would then wait for the next poll.
// One more render once every script is in keeps the menus and cards right from the first paint.
if(typeof document!=='undefined'&&typeof document.addEventListener==='function')document.addEventListener('DOMContentLoaded',()=>{if(typeof state!=='undefined'&&state&&state.loaded&&typeof render==='function')render();});
