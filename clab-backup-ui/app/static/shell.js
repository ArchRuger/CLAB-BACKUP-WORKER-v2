'use strict';
// shell.js — navigation, menus and browser storage for index.html. Everything that touches window,
// location, history, localStorage or a document-level listener lives here, so app.js keeps loading
// in the node harnesses that have none of them. app.js globals (state, activeId, tab, detailName,
// selectLab, showTab, openDetails, render, renderLabBanner, notify) are read at call time, never at load.
const SHELL_ROUTE_KEYS=['lab','view','device'];
let shellSessionConsumed=false, shellApplying=false, shellMenuCount=0, shellActionError=null;
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
function goHome(options={}){
 const dialog=shellEl('details-dialog');if(dialog&&dialog.open&&typeof dialog.close==='function')dialog.close();
 if(typeof activeId!=='undefined')activeId='';
 shellRemove('sessionStorage','activeLab');closeMenus();shellActionError=null;
 writeRoute({},options);
 if(typeof render==='function')render();
 return true;
}
// Menus. New menus are button + sibling div.menu-list inside span.menu (initMenu); #git-save-menu and
// #lab-switcher stay <details>. closeMenus(except) closes everything except the menu containing `except`
// and returns true when it closed something, so topology.js can defer its Escape handling.
function shellContains(menu,el){return !!menu&&!!el&&(menu===el||(typeof menu.contains==='function'&&menu.contains(el)));}
function closeMenus(except){
 let closed=false;
 for(const button of document.querySelectorAll('.menu-button[aria-expanded="true"]')){if(shellContains(button.parentElement||button,except))continue;if(typeof button._menuClose==='function'&&button._menuClose(false))closed=true;}
 for(const details of document.querySelectorAll('details.menu[open], details#git-save-menu[open], details#lab-switcher[open]')){if(shellContains(details,except))continue;details.open=false;closed=true;}
 return closed;
}
function initMenu(button){
 if(!button||button._menuReady)return null;
 const wrapper=button.parentElement,list=wrapper&&typeof wrapper.querySelector==='function'?wrapper.querySelector('.menu-list'):null;
 if(!list)return null;button._menuReady=true;
 if(!list.id)list.id=(button.id||'menu-'+(++shellMenuCount))+'-list';
 button.setAttribute('aria-haspopup','menu');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls',list.id);list.setAttribute('role','menu');list.hidden=true;
 const items=()=>[...list.querySelectorAll('[role="menuitem"]')].filter(item=>!item.disabled&&!item.hidden);
 const close=restore=>{if(list.hidden)return false;list.hidden=true;button.setAttribute('aria-expanded','false');if(restore&&typeof button.focus==='function')button.focus();return true;};
 const open=()=>{closeMenus(wrapper);list.hidden=false;button.setAttribute('aria-expanded','true');const first=items()[0];if(first&&typeof first.focus==='function')first.focus();if(typeof CustomEvent==='function'&&typeof list.dispatchEvent==='function')list.dispatchEvent(new CustomEvent('menuopen'));};
 button._menuClose=close;button._menuOpen=open;
 button.addEventListener('click',()=>{if(list.hidden)open();else close(false);});
 button.addEventListener('keydown',e=>{if(e.key==='ArrowDown'&&list.hidden){e.preventDefault();open();}});
 list.addEventListener('keydown',e=>{
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);return;}
  if(e.key==='Tab'){close(false);return;}
  if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;
  const all=items();if(!all.length)return;e.preventDefault();
  const i=all.indexOf(document.activeElement),next=e.key==='Home'?0:e.key==='End'?all.length-1:e.key==='ArrowDown'?(i+1)%all.length:(i-1+all.length)%all.length;
  if(typeof all[next].focus==='function')all[next].focus();
 });
 // Capture phase: the menu closes and focus returns to the button before the item's own handler runs,
 // so a dialog opened by the item gives focus back to the button when it closes.
 list.addEventListener('click',e=>{const item=e.target&&typeof e.target.closest==='function'?e.target.closest('[role="menuitem"]'):null;if(!item||item.disabled||!shellContains(list,item))return;close(true);},true);
 return {open,close};
}
// Escape priority: node context menu (topology.js) → open menus → expanded map (topology.js). Closing a
// menu stops the event here so the map handler never sees it; focus inside a .menu-list is handled by
// the list's own keydown, which restores focus to the button.
function shellEscape(e){
 if(e.key!=='Escape')return;
 const target=e.target&&typeof e.target.closest==='function'?e.target:null;
 const nodeMenu=shellEl('node-context-menu');if(nodeMenu&&!nodeMenu.hidden)return;
 if(target&&target.closest('.menu-list'))return;
 const details=target?target.closest('details#git-save-menu, details#lab-switcher, details.menu'):null;
 if(details&&details.open){details.open=false;const summary=typeof details.querySelector==='function'?details.querySelector('summary'):null;if(summary&&typeof summary.focus==='function')summary.focus();e.stopPropagation();return;}
 if(closeMenus())e.stopPropagation();
}
function shellPointerDown(e){const target=e.target&&typeof e.target.closest==='function'?e.target:null;const menu=target?target.closest('.menu, details#git-save-menu, details#lab-switcher'):null;closeMenus(menu||undefined);}
// localStorage: the last opened lab, when each lab was opened, and dismissed job warnings.
function rememberOpened(id){if(!id)return false;shellSet('localStorage','clab.lastLab',id);return shellSet('localStorage','clab.opened.'+id,new Date().toISOString());}
function lastOpened(){return shellGet('localStorage','clab.lastLab')||'';}
function openedAt(id){return id?shellGet('localStorage','clab.opened.'+id)||'':'';}
function isDismissed(jobId){return !!jobId&&!!shellGet('localStorage','clab.dismissed.'+jobId);}
function dismissJob(jobId){return !!jobId&&shellSet('localStorage','clab.dismissed.'+jobId,new Date().toISOString());}
// Failures of header, menu and tool actions: a student sentence in the lab banner with the backend
// message under Details; a toast when there is no lab page to show it on.
function shellErrorSentence(message){
 const text=String(message||'');
 if(/Configured devices changed/i.test(text))return 'The devices in this lab changed since the save location was set up. Check the devices under Progress › Save settings.';
 if(/Reconnect the original VM/i.test(text))return 'This lab was set up on a different VM. Reconnect that VM before saving.';
 if(/not connected|VM connection|discovery is not configured/i.test(text))return 'The lab VM is not connected. Choose Manager › VM connection… to set it up.';
 return 'That did not work. The details below say why.';
}
function showActionError(message){
 const text=String(message||'Something went wrong.'),lab=typeof activeId==='string'?activeId:'';
 if(!lab||!shellEl('lab-banner')||typeof renderLabBanner!=='function'){if(typeof notify==='function')notify(text);return false;}
 shellActionError={lab,message:text,sentence:shellErrorSentence(text),at:Date.now()};
 renderLabBanner();return true;
}
function actionError(){return shellActionError;}
function dismissActionError(){shellActionError=null;}
// Load-time wiring: every static .menu-button, the Home links, the drawer's close event, the router and
// the delayed skeleton (only shown when the first /state takes longer than 200 ms).
document.querySelectorAll('.menu-button').forEach(initMenu);
for(const id of ['nav-home','crumb-home']){const el=shellEl(id);if(el)el.addEventListener('click',e=>{e.preventDefault();goHome({push:true});});}
{const dialog=shellEl('details-dialog');if(dialog)dialog.addEventListener('close',()=>{if(!shellApplying)writeRoute({...currentRoute(),device:''});});}
document.addEventListener('keydown',shellEscape,true);
document.addEventListener('pointerdown',shellPointerDown,true);
window.addEventListener('hashchange',()=>{if(!shellApplying)applyRoute();});
setTimeout(()=>{const skeleton=shellEl('home-skeleton');if(skeleton&&!(typeof state!=='undefined'&&state&&state.loaded))skeleton.hidden=false;},200);
