'use strict';
// home.js — the Home page ("My labs"): the Continue card, one card per lab, the "Also running on the
// VM" section and the delegated card actions. Vocabulary comes from status.js and storage from shell.js;
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
function homeCard(lab,continued=false){
 const ls=homeLabState(lab),id=esc(lab.id),name=esc(lab.name),favourite=!!lab.favorite;
 const quick=typeof opQuickActions==='function'?opQuickActions(lab,state.discovery,typeof busy==='function'&&busy()):null;
 const showStart=!!quick&&lab.deployment?.status!=='Running'&&ls.key!=='working';
 const reason=showStart&&!quick.canStart?homeStartReason(lab,quick):'';
 const start=showStart?`<button type="button" class="button secondary" data-lab-start="${id}" ${quick.canStart?'':`disabled title="${esc(reason)}"`}>${quick.startAction==='deploy'?'Start lab':'Start stopped devices'}</button>${reason?`<small class="caption">${esc(reason)}</small>`:''}`:'';
 const opened=typeof openedAt==='function'?openedAt(lab.id):'',openedLine=opened&&typeof relativeTime==='function'?relativeTime(opened):'';
 const favLabel=favourite?'Remove from favourites':'Add to favourites';
 return `<article class="lab-card${continued?' continue':''}" data-lab-id="${id}"><div class="lab-card-head"><div>${continued?'<p class="caption">Continue where you left off</p>':''}<h3>${name}</h3></div><div class="lab-card-tools"><button type="button" class="icon-button" data-lab-favorite="${id}" aria-pressed="${favourite?'true':'false'}" aria-label="${favLabel}" title="${favLabel}"><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-star"></use></svg></button><button type="button" class="icon-button" data-lab-more="${id}" aria-label="More actions for ${name}" title="More actions">⋯</button></div></div><p class="lab-status-line"><span class="pill ${esc(ls.pill||'neutral')}">${esc(ls.label)}</span><span>${esc(homeReadyLine(lab,ls))}</span></p><p>${esc(homeSavedLine(lab))}</p>${openedLine?`<p>Last opened ${esc(openedLine)}</p>`:''}<div class="actions"><button type="button" class="button primary" data-lab="${id}">Open lab</button>${start}</div></article>`;
}
function homeMarkup(el,html){if(!el)return;if(typeof setMarkup==='function')setMarkup(el,html);else el.innerHTML=html;}
// Called from render() on every poll; cheap because every list is diffed. With exactly one lab only the
// Continue card is shown. The discovered section appears whenever the VM has a lab that is not in My labs
// or a lab was hidden earlier, regardless of how many labs exist.
function renderHome(){
 if(!$('home'))return;
 if(typeof current==='function'&&current())return;
 const labs=state.labs||[],loaded=!!state.loaded,single=labs.length===1;
 if($('home-skeleton'))$('home-skeleton').hidden=loaded;
 const last=typeof lastOpened==='function'?lastOpened():'',continued=single?labs[0]:labs.find(l=>l.id===last)||null;
 const continueEl=$('home-continue');if(continueEl){homeMarkup(continueEl,continued?homeCard(continued,true):'');continueEl.hidden=!continued;}
 const sorted=[...labs].sort((a,b)=>Number(!!b.favorite)-Number(!!a.favorite)||String(a.name).localeCompare(String(b.name)));
 const cards=$('lab-cards');if(cards){homeMarkup(cards,single?'':sorted.map(l=>homeCard(l,false)).join(''));cards.hidden=single||!labs.length;}
 if($('home-actions'))$('home-actions').hidden=!loaded||!labs.length;
 const discovery=state.discovery||{},others=(discovery.discovered||[]).some(l=>!l.imported&&!l.excluded)||(discovery.ignored_labs||[]).length>0;
 if($('home-discovered'))$('home-discovered').hidden=!loaded||!others;
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
 if($('home-deploy'))$('home-deploy').onclick=()=>{if(typeof openDeploy==='function')openDeploy();};
}
