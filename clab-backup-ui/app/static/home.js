'use strict';
// home.js — the Home page ("My labs"): the lab list under its two tabs (Recent labs, All labs), one card
// per lab and the delegated card actions. The Deploy and Build cards above it are plain markup. Labs the VM runs that are not in My labs live under Manager ▾ › Labs found on the VM…. Vocabulary comes from status.js and storage from shell.js;
// both are read at call time so the harness can load this file with stubs.
function homeLabState(lab){return typeof labState==='function'?labState(lab,typeof labContext==='function'?labContext():state):{key:'',label:lab.deployment?.status||'Not matched to a running lab',pill:'neutral'};}
function homeReadyLine(lab,ls){if(typeof readyLine==='function')return readyLine(lab,ls);const total=(lab.nodes||[]).length,ready=(lab.nodes||[]).filter(n=>n.ssh_ready).length;return ls.key==='stopped'?'Not running':['unlinked','unknown'].includes(ls.key)?'':`${ready} of ${total} devices ready`;}
function homeSavedLine(lab){
 const ps=typeof progressState==='function'?progressState(lab,state.git_jobs):null;if(!ps)return '';
 const when=ps.at&&typeof relativeTime==='function'?relativeTime(ps.at):'';
 if(['attention','failed','interrupted','local'].includes(ps.key))return ps.label+(ps.detail?' — '+ps.detail:'');
 if(['git','review','kept'].includes(ps.key))return 'Last saved '+(when||'recently');
 if(ps.key==='unconnected')return 'Not saved anywhere yet';
 return ps.label;
}
function homeStartReason(lab,quick){
 if(quick&&quick.reason)return quick.reason;const discovery=state.discovery||{};
 if(!discovery.connected)return 'Connect the VM first';if(typeof busy==='function'&&busy())return 'Wait for the current operation to finish';
 if(!(lab.vm_project_path||lab.vm_source?.files?.definition?.path))return 'This lab has no topology file on the VM (Advanced › Deployment details)';
 return 'Lab status is unknown — refresh the lab list';
}
// When this manager last deployed the lab, in words. `last_deployed` is the finish time of a succeeded
// deploy or redeploy (app/lab_operations.py); a lab deployed from a terminal, or before the manager kept
// that, has none, and the card says so instead of showing a time that would be a guess.
function homeDeployedLine(lab){const when=lab.last_deployed&&typeof relativeTime==='function'?relativeTime(lab.last_deployed):'';return when?'Deployed '+when:'No deployment recorded by this manager';}
// The two orders. recent: newest deployment first; labs without a recorded deployment come after all of
// them, by name, so they are never presented as recently deployed. all: favourites first, then by name
// (the order Home always had). Neither looks at when a lab was opened, saved or polled.
const HOME_TABS={recent:{label:'Recent labs',note:'Most recently deployed first. Labs this manager has not deployed come last, by name.'},all:{label:'All labs',note:'Favourites first, then by name.'}};
function homeByName(a,b){return String(a.name).localeCompare(String(b.name))||String(a.id).localeCompare(String(b.id));}
function homeOrder(labs,tab){
 const list=[...(labs||[])];
 if(tab==='all')return list.sort((a,b)=>Number(!!b.favorite)-Number(!!a.favorite)||homeByName(a,b));
 return list.sort((a,b)=>{const x=a.last_deployed||'',y=b.last_deployed||'';return x&&y?(x<y?1:x>y?-1:homeByName(a,b)):x?-1:y?1:homeByName(a,b);});
}
// The tab is the student's choice: kept for the browser session (shell.js), so neither the 4 s poll nor
// opening a lab and coming back resets it.
let homeTabFallback='recent';
function homeCurrentTab(){const stored=typeof homeTab==='function'?homeTab():homeTabFallback;return HOME_TABS[stored]?stored:'recent';}
function homeSelectTab(tab){if(!HOME_TABS[tab])return;homeTabFallback=tab;if(typeof rememberHomeTab==='function')rememberHomeTab(tab);renderHome();}
function homeCard(lab){
 const ls=homeLabState(lab),id=esc(lab.id),name=esc(lab.name),favourite=!!lab.favorite;
 const quick=typeof opQuickActions==='function'?opQuickActions(lab,state.discovery,typeof busy==='function'&&busy()):null;
 const showStart=!!quick&&lab.deployment?.status!=='Running'&&ls.key!=='working';
 const reason=showStart&&!quick.canStart?homeStartReason(lab,quick):'';
 const start=showStart?`<button type="button" class="button secondary" data-lab-start="${id}" ${quick.canStart?'':`disabled title="${esc(reason)}"`}>${quick.startAction==='deploy'?'Start lab':'Start stopped devices'}</button>${reason?`<small class="caption">${esc(reason)}</small>`:''}`:'';
 const opened=typeof openedAt==='function'?openedAt(lab.id):'',openedLine=opened&&typeof relativeTime==='function'?relativeTime(opened):'',times=[homeDeployedLine(lab),openedLine?'Last opened '+openedLine:''].filter(Boolean).join(' · ');
 const favLabel=favourite?'Remove from favourites':'Add to favourites';
 return `<article class="lab-card" data-lab-id="${id}"><div class="lab-card-head"><div><h3>${name}</h3></div><div class="lab-card-tools"><button type="button" class="icon-button" data-lab-favorite="${id}" aria-pressed="${favourite?'true':'false'}" aria-label="${favLabel}" title="${favLabel}"><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-star"></use></svg></button><button type="button" class="icon-button" data-lab-more="${id}" aria-label="More actions for ${name}" title="More actions">⋯</button></div></div><p class="lab-status-line"><span class="pill ${esc(ls.pill||'neutral')}">${esc(ls.label)}</span><span>${esc(homeReadyLine(lab,ls))}</span></p><p>${esc(homeSavedLine(lab))}</p><p class="caption lab-card-times">${esc(times)}</p><div class="actions"><button type="button" class="button primary" data-lab="${id}">Open lab</button>${start}</div></article>`;
}
function homeMarkup(el,html){if(!el)return;if(typeof setMarkup==='function')setMarkup(el,html);else el.innerHTML=html;}
// What Manager ▾ › Labs found on the VM… has to offer: labs the VM reports that are not in My labs, and
// labs hidden after a removal. An excluded discovery counts as hidden only, never as waiting.
function homeVmLabs(discovery){
 const d=discovery||{},waiting=(d.discovered||[]).filter(l=>!l.imported&&!l.excluded).length,hidden=(d.ignored_labs||[]).length;
 return {waiting,hidden,note:[waiting?waiting+' not in My labs':'',hidden?hidden+' hidden':''].filter(Boolean).join(' · ')};
}
// Called from render() on every poll; cheap because the list is diffed (setMarkup), which also keeps
// the focus. The order depends only on the chosen tab and the labs' own fields.
function renderHome(){
 if(!$('home'))return;
 if(typeof current==='function'&&current())return;
 const labs=state.labs||[],loaded=!!state.loaded,tab=homeCurrentTab();
 if($('home-skeleton'))$('home-skeleton').hidden=loaded;
 // The two ways to start a lab lead every Home, with or without labs, as soon as the state is known.
 if($('home-start'))$('home-start').hidden=!loaded;
 if($('home-labs'))$('home-labs').hidden=!loaded||!labs.length;
 for(const name of Object.keys(HOME_TABS)){const button=$('home-tab-'+name);if(!button)continue;const on=name===tab;if(typeof button.setAttribute==='function'){button.setAttribute('aria-selected',on?'true':'false');button.setAttribute('tabindex',on?'0':'-1');}if(button.classList&&typeof button.classList.toggle==='function')button.classList.toggle('active',on);}
 if($('home-tab-note'))$('home-tab-note').textContent=HOME_TABS[tab].note;
 const cards=$('lab-cards');if(cards){homeMarkup(cards,homeOrder(labs,tab).map(homeCard).join(''));cards.hidden=!labs.length;if(typeof cards.setAttribute==='function')cards.setAttribute('aria-labelledby','home-tab-'+tab);}
}
if($('home')){
 $('home').addEventListener('click',async e=>{
  const t=e.target;if(!t||typeof t.closest!=='function')return;
  const open=t.closest('[data-lab]');if(open){if(typeof selectLab==='function')selectLab(open.dataset.lab);return;}
  const start=t.closest('[data-lab-start]');if(start){if(start.disabled)return;if(typeof selectLab==='function')selectLab(start.dataset.labStart);const b=$('lab-start');if(b&&!b.disabled&&typeof b.onclick==='function')b.onclick();return;}
  const more=t.closest('[data-lab-more]');if(more){if(typeof openLabOperations==='function')openLabOperations(more.dataset.labMore);return;}
  const fav=t.closest('[data-lab-favorite]');if(fav){const lab=(state.labs||[]).find(l=>l.id===fav.dataset.labFavorite);if(!lab)return;fav.disabled=true;try{await json('/labs/'+encodeURIComponent(lab.id)+'/operations-settings','PUT',{favorite:!lab.favorite});await refresh();}catch(error){notify(error.message);}finally{fav.disabled=false;}}
 });
 const cardMenu=e=>{const card=e.target&&typeof e.target.closest==='function'?e.target.closest('[data-lab-id]'):null;if(!card||typeof openLabOperations!=='function')return;e.preventDefault();openLabOperations(card.dataset.labId);};
 $('home').addEventListener('contextmenu',cardMenu);
 $('home').addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10'))cardMenu(e);});
 if($('home-tabs')){
  $('home-tabs').addEventListener('click',e=>{const b=e.target&&typeof e.target.closest==='function'?e.target.closest('[data-home-tab]'):null;if(b)homeSelectTab(b.dataset.homeTab);});
  $('home-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const names=Object.keys(HOME_TABS),i=names.indexOf(homeCurrentTab()),next=e.key==='Home'?0:e.key==='End'?names.length-1:(i+(e.key==='ArrowRight'?1:-1)+names.length)%names.length;homeSelectTab(names[next]);const button=$('home-tab-'+names[next]);if(button&&typeof button.focus==='function')button.focus();});
 }
 if($('home-deploy'))$('home-deploy').onclick=()=>{if(typeof openDeploy==='function')openDeploy();};
 if($('home-upload'))$('home-upload').onclick=()=>{if(typeof opUpload==='function')opUpload();};
}
