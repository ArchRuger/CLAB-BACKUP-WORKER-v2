'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Navigation state. activeId is chosen by shell.js's applyRoute() after the first /state (hash →
// sessionStorage → Home); render() shows Home whenever it is empty. tab holds one of PANELS; legacy
// names (inventory, git, backups, credentials, logs) are normalised by setTab() so old callers still work.
let state={labs:[],jobs:[],platforms:{}}, activeId='', tab='topology', toastTimer, subview='', devicesTechnical=false, scrollTarget='', routeApplied=false;
const PANELS=['topology','devices','progress','tools','advanced'];
const TAB_ALIAS={inventory:'devices',git:'progress',backups:'tools',credentials:'advanced',logs:'advanced'};
const SUBVIEW={inventory:'technical',backups:'backups-view',credentials:'credentials-view',logs:'logs-view'};
const APP_RESTORE_BUSY=['queued','preflight','backing_up','applying','confirming','verifying'];
const BANNER_BUTTONS={'lab-banner':['banner-start','banner-output','banner-restore','banner-try-again','banner-retry-save','banner-save-details','banner-credentials','banner-vm','banner-link','banner-dismiss'],'home-banner':['home-banner-output']};
const current=()=>state.labs.find(l=>l.id===activeId);
const busy=()=>state.jobs.some(j=>['queued','running'].includes(j.status))||(state.operations||[]).some(j=>['queued','running'].includes(j.status))||(state.git_jobs||[]).some(j=>['queued','capturing','exporting','pushing'].includes(j.status));
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(path,options={}){
 const headers={...(options.headers||{})};
 const response=await fetch('/api'+path,{...options,headers});
 if(!response.ok){let data;try{data=await response.json();}catch{data={detail:'The manager did not respond. Try again.'};}
 throw new Error(typeof data.detail==='string'?data.detail:'Check the form fields and try again.');}
 return response;
}
async function json(path,method,data){return (await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).json();}
// Only touch innerHTML when the markup changed: lists re-render on the 4 s poll and must not steal focus.
function setMarkup(el,html){if(!el)return false;if(el._markup===html)return false;el.innerHTML=html;el._markup=html;return true;}
// Disabled menu items and tool rows show why as visible text (a title on a disabled button is unreachable).
function menuReason(el,text){if(!el||typeof el.querySelector!=='function')return;const small=el.querySelector('.menu-reason');if(!small)return;small.textContent=text||'';small.hidden=!text;}
// Action logs live on the Advanced tab; the 4 s poll refreshes them only while that section is on screen.
function logsVisible(){if(tab!=='advanced')return false;const view=$('logs-view');if(!view||typeof view.getBoundingClientRect!=='function'||typeof innerHeight==='undefined')return true;const box=view.getBoundingClientRect();return box.bottom>0&&box.top<innerHeight;}
async function refresh(){const response=await api('/state');state=await response.json();state.loaded=true;if(activeId&&!current())activeId='';if(!routeApplied){routeApplied=true;if(typeof applyRoute==='function')applyRoute();}render();if(logsVisible())await refreshLogs();}
function setTab(value){const legacy=TAB_ALIAS[value];if(legacy){if(value==='inventory')devicesTechnical=true;else scrollTarget=SUBVIEW[value]||'';subview=value;value=legacy;}else subview='';tab=PANELS.includes(value)?value:'topology';}
function syncRoute(push=false){if(!routeApplied||typeof writeRoute!=='function'||typeof currentRoute!=='function')return;writeRoute(currentRoute(),{push});}
function selectLab(id,view='topology'){if($('details-dialog').open)$('details-dialog').close();activeId=id;setTab(view);sessionStorage.setItem('activeLab',id);$('search').value='';$('log-job').value='';if(typeof rememberOpened==='function')rememberOpened(id);if(typeof closeMenus==='function')closeMenus();if(typeof writeRoute==='function')writeRoute({lab:id,view:tab},{push:true});render();}
function platformLabel(kind){return state.platforms[kind]?.label||(kind==='ssh'?'Generic SSH / Linux':'Unmapped');}
function badge(status){const type=['Ready','succeeded','reachable'].includes(status)?'good':['failed','unreachable','interrupted'].includes(status)?'bad':['queued','running'].includes(status)?'running':'warn';const label=typeof badgeLabel==='function'?badgeLabel(status):status;return `<span class="badge ${type}" title="${esc(status)}">${esc(label)}</span>`;}
function profileName(lab,node){const id=node.profile_id||lab.defaults[node.platform||'ssh'];return lab.profiles.find(p=>p.id===id)?.label||(node.inventory_credentials?'From inventory':node.credential_source==='default'?'Containerlab default login':'Not configured');}
// Why an SSH action is disabled right now; the readiness monitor clears it on its own. Fallback for
// contexts without status.js — deviceState(n).detail is the student sentence.
function sshHint(n){return typeof deviceState==='function'?deviceState(n).detail||'Add login credentials to open the CLI.':(n.nos_login?.status==='booting'?'NOS is still booting; SSH opens when it accepts a login':n.nos_login?.status==='failed'?'SSH login failed with the saved credentials; assign a credential profile':n.nos_login?.status==='unavailable'?'Node is not running':'Assign credentials first');}
// Telemetry is read in Grafana, which runs beside the manager on the VM (deploy/setup-telemetry.sh);
// the browser reaches it on the manager's own host name. The lab's generated map when it has one,
// else the lab overview dashboard, both filtered to this lab.
// Grafana is on demand (stopped until someone opens it), so the button goes through /static/grafana.html:
// that page asks the manager to start Grafana on the VM when needed and then moves on to the dashboard.
// Only the dashboard path travels in the link; the page builds the Grafana origin from the manager's host.
function grafanaPath(lab){
 const g=lab?.telemetry?.grafana;if(!g?.enabled||!g.port)return '';
 return `/d/${g.map_uid||'clab-lab-overview'}?${new URLSearchParams({'var-lab':lab.name||'',refresh:'10s'})}`;
}
function grafanaLaunch(lab){const path=grafanaPath(lab);return path?'/static/grafana.html#'+new URLSearchParams({path,title:lab.name||''}):'';}
function renderGrafanaLink(lab){
 const link=$('grafana-open');if(!link)return;const url=grafanaLaunch(lab);link.hidden=!url;
 if(!url){link.removeAttribute('href');return;}
 link.href=url;setMarkup(link,(lab.telemetry.grafana.map_uid?'Open lab map':'Open network dashboard')+' <span aria-hidden="true">↗</span>');
 link.title=(lab.telemetry.grafana.map_uid?'Live map of this lab: link rates, port and device state, in Grafana.':'Live interface rates, link state and BGP neighbours of this lab, in Grafana.')+' The dashboard starts on the VM when needed.';
}
function renderTelemetryLine(lab){const el=$('telemetry-line');if(!el)return;const t=lab.telemetry||{};el.textContent=t.grafana&&t.grafana.enabled===false?'Telemetry is not installed on this VM.':typeof telemetryLine==='function'?telemetryLine(t.status,t):'';}
// Vocabulary helpers shared by the header, the lab switcher and home.js. labContext adds the dismissed
// operation ids so a failed job the student already dismissed stops reading as "Needs attention".
function dismissedSet(){const ids=new Set();if(typeof isDismissed!=='function')return ids;for(const j of [...(state.operations||[]),...(state.restore_jobs||[])])if(j.id&&['failed','interrupted','preflight_failed'].includes(j.status)&&isDismissed(j.id))ids.add(j.id);return ids;}
function labContext(){return {...state,dismissed:dismissedSet()};}
function labStateOf(lab){return typeof labState==='function'?labState(lab,labContext()):{key:'',label:lab.deployment?.status||'Not matched to a running lab',pill:'neutral',detail:''};}
function readyLine(lab,ls){const total=(lab.nodes||[]).length,ready=(lab.nodes||[]).filter(n=>n.ssh_ready).length;if(ls.key==='stopped')return 'Not running';if(['unlinked','unknown'].includes(ls.key))return '';return `${ready} of ${total} devices ready`;}
function gitProblem(lab){return typeof gitContexts!=='undefined'&&gitContexts&&typeof gitContexts.get==='function'?gitContexts.get(lab.id)?.repository_status?.problem||'':'';}
function scheduleSummary(lab){if(!lab.interval)return 'Off';const paused=lab.deployment&&!['Running','Unlinked'].includes(lab.deployment.status);return (paused?'Paused (lab not running) · every ':'Every ')+lab.interval+' min';}
function labsMarkup(){
 if(!state.labs.length)return '<p class="side-hint">Your labs will appear here.</p>';
 return [...state.labs].sort((a,b)=>Number(!!b.favorite)-Number(!!a.favorite)||String(a.name).localeCompare(String(b.name))).map(l=>{const ls=labStateOf(l);return `<button type="button" class="lab-item ${l.id===activeId?'active':''}" data-lab="${esc(l.id)}" ${l.id===activeId?'aria-current="true"':''}>${l.favorite?'<svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-star"></use></svg> ':''}${esc(l.name)}<small>${esc([ls.label,readyLine(l,ls)].filter(Boolean).join(' · '))}</small></button>`;}).join('');
}
function renderWorkerState(){
 const el=$('worker-state');if(!el)return;const running=state.jobs.filter(j=>['queued','running'].includes(j.status));
 const text=(state.git_jobs||[]).some(j=>['queued','capturing','exporting','pushing'].includes(j.status))?'Saving progress…':(state.restore_jobs||[]).some(j=>APP_RESTORE_BUSY.includes(j.status))?'Replacing configuration…':running.some(j=>j.operation==='backup')?'Backing up…':running.length?'Checking device logins…':(state.operations||[]).some(j=>['queued','running'].includes(j.status))?'Lab operation running…':'';
 el.textContent=text;el.hidden=!text;
}
function renderLabHeader(lab){
 const ls=labStateOf(lab),pill=$('lab-state');
 if(pill){pill.textContent=ls.label;pill.className='pill '+(ls.pill||'neutral');}
 if($('lab-ready'))$('lab-ready').textContent=readyLine(lab,ls);
 if($('lab-progress'))$('lab-progress').textContent=typeof progressSummary==='function'?progressSummary(lab,state.git_jobs,undefined,gitProblem(lab)):'';
}
function renderTechnical(lab){const set=(id,value)=>{if($(id))$(id).textContent=value||'—';};set('tech-lab-id',lab.id);set('tech-source',lab.source);set('tech-path',lab.vm_project_path||lab.vm_source?.files?.definition?.path);set('tech-prefix',lab.container_prefix??'clab');set('tech-deployment',lab.deployment_name);set('tech-binding',lab.git_binding?[lab.git_binding.binding_id,lab.git_binding.revision].filter(Boolean).join(' · '):'');}
function render(){
 const lab=current(),home=!lab,loaded=!!state.loaded;
 setMarkup($('labs'),labsMarkup());
 const version=state.version||'1.29.1';$('app-version').textContent='v'+version;
 if($('supported-release'))$('supported-release').textContent='Works with Junos, IOS-XR and Arista EOS';
 renderWorkerState();
 $('empty').hidden=!home||!loaded||state.labs.length>0;$('lab-content').hidden=!lab;
 if($('home'))$('home').hidden=!home;
 if($('home-skeleton'))$('home-skeleton').hidden=loaded;
 $('title').textContent=lab?.name||'My labs';$('breadcrumb').textContent=lab?.name||'';$('breadcrumb').hidden=!lab;
 for(const id of ['crumb-sep','lab-switcher'])if($(id))$(id).hidden=!lab;
 if(!lab&&$('lab-switcher'))$('lab-switcher').open=false;
 $('import-top').textContent='Replace inventory…';
 $('updated').textContent=lab?new Date(lab.updated).toLocaleString():'';
 if(typeof renderManagement==='function')renderManagement();
 if(typeof renderLabOperations==='function')renderLabOperations();
 if(typeof renderGitProgress==='function')renderGitProgress();
 if(typeof renderHome==='function')renderHome();
 if(!lab){renderLabBanner();syncProxies();syncRoute();return;}
 renderLabHeader(lab);renderTechnical(lab);
 $('node-count').textContent=lab.nodes.length;
 renderGrafanaLink(lab);renderTelemetryLine(lab);
 const sshReady=lab.nodes.some(n=>n.ssh_ready);
 $('map-ssh-all').disabled=!sshReady;
 $('map-ssh-all').title=sshReady?'':lab.nodes.some(n=>n.nos_login?.status==='booting')?'Waiting for devices to finish starting — this becomes available automatically':'No device is ready for a CLI session yet';
 menuReason($('map-ssh-all'),$('map-ssh-all').title);
 $('map-backup-all').disabled=busy()||!lab.nodes.some(n=>n.readiness==='Ready');
 $('map-backup-all').title=$('map-backup-all').disabled?(busy()?'Wait for the current job to finish':'No device can be backed up yet'):'';
 menuReason($('map-backup-all'),$('map-backup-all').title);
 const enabled=lab.nodes.filter(n=>n.enabled), ready=enabled.filter(n=>n.readiness==='Ready');
 $('enabled-count').textContent=enabled.length;$('ready-count').textContent=ready.length;
 $('schedule-summary').textContent=scheduleSummary(lab);
 $('test').disabled=$('backup').disabled=busy()||!enabled.length||ready.length!==enabled.length;
 $('test').title=$('backup').title=ready.length!==enabled.length?'Add credentials for every device included in backups first':'';
 $('inventory-caption').textContent='Source: '+lab.source+' · '+enabled.length+' of '+lab.nodes.length+' included in backups';
 renderNodes();renderDeviceList();if(typeof renderMapState==='function')renderMapState();renderProfiles();renderJobs();showTab(tab);refreshHealth();renderLabBanner();syncProxies();syncRoute();
 if(document.activeElement!==$('interval'))$('interval').value=lab.interval;
}
// One control per id: a mirror (button[data-proxy="<id>"]) copies the owner's disabled/title/hidden state
// and shows the reason as visible text; clicking it runs the owner's onclick function (never .click()
// on a hidden or disabled control).
function syncProxies(){
 if(typeof document.querySelectorAll!=='function')return;
 for(const mirror of document.querySelectorAll('[data-proxy]')){const owner=$(mirror.dataset.proxy);if(!owner){mirror.hidden=true;continue;}mirror.hidden=!!owner.hidden;mirror.disabled=!!owner.disabled;mirror.title=owner.disabled?owner.title||'':'';menuReason(mirror,mirror.disabled?owner.title:'');}
 for(const note of document.querySelectorAll('[data-proxy-reason]')){const owner=$(note.dataset.proxyReason);const text=owner&&owner.disabled?owner.title||'':'';note.textContent=text;note.hidden=!text;}
}
function activateProxy(mirror){const owner=$(mirror.dataset.proxy);if(!owner||owner.disabled)return false;if(typeof owner.onclick==='function'){owner.onclick.call(owner);return true;}if(typeof owner.click==='function')owner.click();return true;}
// The situational banner: static children only (text, hidden, className), never innerHTML, so an open
// menu or a focused button survives the 4 s poll. One case at a time, in priority order.
function setBanner(id,spec={}){
 const banner=$(id);if(!banner)return;
 if(!spec.text){banner.hidden=true;return;}
 banner.hidden=false;banner.className='banner '+(spec.tone||'info');
 if(typeof banner.setAttribute==='function'){banner.setAttribute('role',spec.tone==='danger'?'alert':'status');banner.setAttribute('aria-live',spec.tone==='danger'?'assertive':'polite');}
 const glyph=$(id+'-glyph');if(glyph&&typeof glyph.setAttribute==='function')glyph.setAttribute('href','#i-'+(spec.icon||'info'));
 if($(id+'-text'))$(id+'-text').textContent=spec.text;
 // A disabled Start in the banner explains itself: its reason becomes the Details line when nothing else is.
 const disabledStart=spec.actions?.['banner-start']?.disabled?spec.actions['banner-start'].title:'',detailText=spec.detail||disabledStart||'';
 const details=$(id+'-detail');if(details){details.hidden=!detailText;if($(id+'-detail-text'))$(id+'-detail-text').textContent=detailText;}
 for(const key of BANNER_BUTTONS[id]||[]){const b=$(key);if(!b)continue;const action=spec.actions?.[key];b.hidden=!action;if(action){b.textContent=action.label;b.disabled=!!action.disabled;b.title=action.title||'';b.onclick=action.run;}}
}
function startLab(){const b=$('lab-start');if(b&&!b.disabled&&typeof b.onclick==='function')b.onclick();}
function renderHomeBanner(){
 const op=(state.operations||[]).find(j=>!j.lab_id&&['queued','running'].includes(j.status));
 if(!op){setBanner('home-banner',{});return;}
 setBanner('home-banner',{tone:'info',icon:'clock',text:(typeof operationLabel==='function'?operationLabel(op.action):'Lab operation')+'…',detail:op.message||'',actions:{'home-banner-output':{label:'View output',run:()=>{if(typeof opShowJob==='function')opShowJob(op.id);}}}});
}
function renderLabBanner(){
 const lab=current();
 if(!lab){setBanner('lab-banner',{});renderHomeBanner();return;}
 setBanner('home-banner',{});
 const ls=labStateOf(lab),err=typeof actionError==='function'?actionError():null;
 const ops=(state.operations||[]).filter(j=>j.lab_id===lab.id),restores=(state.restore_jobs||[]).filter(j=>j.lab_id===lab.id);
 const runningOp=ops.find(j=>['queued','running'].includes(j.status)),runningRestore=restores.find(j=>APP_RESTORE_BUSY.includes(j.status));
 const ps=typeof progressState==='function'?progressState(lab,state.git_jobs,undefined,gitProblem(lab)):null;
 const credentials=typeof credentialsNeeded==='function'?credentialsNeeded(lab):0;
 // The menu item carries its label in a <span> and its disabled reason in a <small>; the banner button takes the label only.
 const startLabel=()=>{const b=$('lab-start');const span=b&&typeof b.querySelector==='function'?b.querySelector('span'):null;return (span?span.textContent:b?.textContent)?.trim()||'Start lab';};
 const start=()=>({'banner-start':{label:startLabel(),run:startLab,disabled:!!$('lab-start')?.disabled,title:$('lab-start')?.title||''}});
 let spec={};
 if(err&&err.lab===lab.id)spec={tone:'danger',icon:'alert',text:err.sentence,detail:err.message,actions:{'banner-dismiss':{label:'Dismiss',run:()=>{if(typeof dismissActionError==='function')dismissActionError();renderLabBanner();}}}};
 else if(runningOp)spec={tone:'info',icon:'clock',text:(typeof operationLabel==='function'?operationLabel(runningOp.action):'Lab operation')+'…',detail:runningOp.message||'',actions:{'banner-output':{label:'View output',run:()=>{if(typeof opShowJob==='function')opShowJob(runningOp.id);}}}};
 else if(runningRestore)spec={tone:'info',icon:'clock',text:'Replacing configuration…',detail:runningRestore.message||'',actions:{'banner-restore':{label:'View progress',run:()=>{if(typeof restoreShowJob==='function')restoreShowJob(runningRestore.id);}}}};
 else if(ls.key==='attention'&&ls.job){
  const job=ls.job,isRestore=restores.includes(job),actions={'banner-dismiss':{label:'Dismiss',run:()=>{if(typeof dismissJob==='function')dismissJob(job.id);render();}}};
  if(isRestore)actions['banner-restore']={label:'Details',run:()=>{if(typeof restoreShowJob==='function')restoreShowJob(job.id);}};
  else{actions['banner-output']={label:'View output',run:()=>{if(typeof opShowJob==='function')opShowJob(job.id);}};actions['banner-try-again']={label:'Try again',run:()=>{if(typeof opReview==='function'&&typeof opTask==='function')opTask(null,()=>opReview({lab_id:lab.id,action:job.action,options:job.options||{}}));}};}
  spec={tone:'danger',icon:'alert',text:ls.detail,detail:job.message||'',actions};
 }
 else if(ps&&ps.problem)spec={tone:'warn',icon:'alert',text:'Saving to Git is not possible right now.',detail:ps.problem,actions:{'banner-save-details':{label:'Save location settings',run:()=>{if(typeof gitOpenRepository==='function')gitOpenRepository();}}}};
 else if(ps&&['attention','failed','interrupted'].includes(ps.key)){
  const actions={};
  if(ps.key==='attention')actions['banner-retry-save']={label:'Retry',run:()=>{if(typeof gitPushPending==='function'&&typeof opTask==='function')opTask(null,()=>gitPushPending(lab.id));}};
  if(ps.job)actions['banner-save-details']={label:'Details',run:()=>{if(typeof gitShowJob==='function'&&typeof opTask==='function')opTask(null,()=>gitShowJob(ps.job.id));}};
  spec={tone:ps.key==='attention'?'warn':'danger',icon:'alert',text:ps.detail,detail:ps.job?.message||'',actions};
 }
 else if(ls.key==='attention')spec={tone:'danger',icon:'alert',text:ls.detail,actions:lab.deployment?.status==='Partially running'?start():{'banner-credentials':{label:'Check credentials',run:()=>showTab('credentials')}}};
 else if(credentials)spec={tone:'warn',icon:'alert',text:`${credentials} ${credentials===1?'device needs':'devices need'} login credentials before you can open ${credentials===1?'its':'their'} CLI.`,actions:{'banner-credentials':{label:'Add credentials',run:()=>openProfile()}}};
 else if(ls.key==='starting')spec={tone:'info',icon:'clock',text:'Lab is starting — '+ls.detail};
 else if(ls.key==='stopped')spec={tone:'info',icon:'info',text:'This lab is not running.',actions:start()};
 else if(ls.key==='unknown')spec={tone:'warn',icon:'alert',text:ls.detail||'The lab VM cannot be reached. Status may be out of date.',actions:{'banner-vm':{label:'VM connection…',run:()=>{if(typeof openVmDialog==='function')openVmDialog();}}}};
 else if(ls.key==='unlinked')spec={tone:'info',icon:'info',text:ls.detail,actions:{'banner-link':{label:'Match to a running lab…',run:()=>{const b=$('link-deployment');if(b&&typeof b.onclick==='function')b.onclick();}}}};
 setBanner('lab-banner',spec);
}
function renderNodes(){const lab=current();if(!lab)return;const term=$('search').value.toLowerCase();const nodes=lab.nodes.filter(n=>(n.name+' '+n.address+' '+platformLabel(n.platform)).toLowerCase().includes(term));
 const markup=nodes.map(n=>{const h=nodeHealth(n.name);return `<tr><td><input type="checkbox" data-enable="${esc(n.name)}" ${n.enabled?'checked':''} ${!n.platform?'disabled title="Choose a network OS first (Edit connection)"':''} aria-label="Include ${esc(n.name)} in backups"></td><td><button class="node-name" data-details="${esc(n.name)}">${esc(n.short_name||n.name)}</button><span class="endpoint">${esc(n.address)}:${n.port}</span></td><td><span class="badge platform">${esc(platformLabel(n.platform))}</span><span class="secondary-text">${esc(profileName(lab,n))}</span></td><td>${h?.ssh?badge(h.ssh.status):'<span class="status-neutral">Not checked</span>'}<span class="timestamp">${h?.ssh?.at?esc(utcDisplay(h.ssh.at)):'No check yet'}</span></td><td>${h?.backup?badge(h.backup.status):'<span class="status-neutral">No backup yet</span>'}<span class="timestamp">${h?.backup?.at?esc(utcDisplay(h.backup.at)):''}</span></td><td><div class="node-actions">${nodeActions(n)}</div></td></tr>`;}).join('')||'<tr><td colspan="6" class="table-empty">No devices match. Try another name, address or platform.</td></tr>';setMarkup($('nodes'),markup);
}
function nodeActions(n,details=false){const hint=sshHint(n);return `<button class="ssh-action" data-terminal="${esc(n.name)}" ${!n.ssh_ready?`disabled title="${esc(hint)}"`:''}>Open CLI <span aria-hidden="true">↗</span></button><button data-capture="${esc(n.name)}" ${typeof captureActionAttrs==='function'?captureActionAttrs():''}>Capture traffic…</button><button data-backup="${esc(n.name)}" ${busy()||n.readiness!=='Ready'?'disabled title="Available when the device has a supported network OS and credentials and no other backup is running"':''}>Back up configuration</button>${details?'':`<button class="details-action" data-details="${esc(n.name)}" aria-label="Details for ${esc(n.name)}">Details</button>`}`;}
// The drawer's Advanced section: check the saved login now, or change the connection settings.
function nodeDrawerActions(n){return `<button data-check="${esc(n.name)}" ${!(n.login_configured??n.ssh_ready)?'disabled title="Add credentials first"':''}>Test login</button><button data-edit="${esc(n.name)}">Edit connection…</button>`;}
// A readable id per device name; the hash keeps names that differ only in punctuation apart.
function deviceSlug(name){let hash=0;for(const c of String(name))hash=(hash*31+c.charCodeAt(0))>>>0;return String(name).replace(/[^A-Za-z0-9_-]+/g,'-')+'-'+hash.toString(36);}
// One row per device for the Devices tab and the topology rail: name, platform, state pill and the
// reason the CLI is unavailable as visible text the Open CLI button points at.
function deviceRow(n,rail){
 const ds=typeof deviceState==='function'?deviceState(n):{key:n.ssh_ready?'ready':'unknown',label:n.ssh_ready?'Ready':'Not ready',detail:n.ssh_ready?'':sshHint(n),cli:!!n.ssh_ready,pill:n.ssh_ready?'ok':'neutral'};
 const why=(rail?'why-rail-':'why-')+deviceSlug(n.name),reason=!ds.cli&&ds.detail?`<small class="row-reason" id="${esc(why)}">${esc(ds.detail)}</small>`:'';
 const open=$('details-dialog').open&&detailName===n.name;
 return `<li class="device-row state-${esc(ds.key)}" ${open?'aria-current="true"':''}><div><button class="node-name" data-details="${esc(n.name)}">${esc(n.short_name||n.name)}</button><span class="badge platform">${esc(platformLabel(n.platform))}</span></div><div><span class="pill ${esc(ds.pill||'neutral')}">${esc(ds.label)}</span>${reason}</div><div class="node-actions"><button class="ssh-action" data-terminal="${esc(n.name)}" ${ds.cli?'':`disabled title="${esc(ds.detail)}"${reason?` aria-describedby="${esc(why)}"`:''}`}>Open CLI <span aria-hidden="true">↗</span></button>${rail?'':`<button class="details-action" data-details="${esc(n.name)}" aria-label="Details for ${esc(n.name)}">Details</button>`}</div></li>`;
}
function renderDeviceList(){
 const lab=current();if(!lab)return;const term=$('search').value.toLowerCase();
 const nodes=lab.nodes.filter(n=>(n.name+' '+n.address+' '+platformLabel(n.platform)).toLowerCase().includes(term));
 setMarkup($('device-list'),nodes.map(n=>deviceRow(n,false)).join('')||(lab.nodes.length?'<li class="table-empty">No devices match. Try another name, address or platform.</li>':'<li class="table-empty">This lab has no devices yet.</li>'));
 setMarkup($('topology-devices'),lab.nodes.map(n=>deviceRow(n,true)).join('')||'<li class="table-empty">This lab has no devices yet.</li>');
}
function renderProfiles(){const lab=current();$('profiles').innerHTML=lab.profiles.length?lab.profiles.map(p=>`<article class="profile-card"><span class="badge">${esc(platformLabel(p.platform))}</span><h3>${esc(p.label)}</h3><p>${esc(p.username)}</p><span class="profile-type">${p.auth==='key'?'SSH private key':'Password'}</span>${lab.defaults[p.platform]===p.id?'<small>Default for this network OS</small>':''}</article>`).join(''):'<div class="blank-state"><h2>No login credentials yet</h2><p>Add one profile per network OS.<br>Credentials found in the lab files work automatically.</p></div>';}
function jobMarkup(j,opened){
 const finished=!['queued','running'].includes(j.status);
 const available=j.operation==='backup'&&finished&&j.nodes.some(n=>n.status==='succeeded'&&n.download_name);
 return `<details class="job" data-job="${esc(j.id)}" ${opened.has(j.id)?'open':''}>
 <summary><div class="job-title"><strong>${j.operation==='test'?'Login check'+(j.source==='automatic'?' (automatic)':''):'Configuration backup'}</strong><small><span>${esc(utcDisplay(j.started||j.created))}</span> <span>· ${j.nodes.length} devices</span></small></div>${badge(j.status)}</summary>
 <div class="job-body"><p>${esc(j.message)}</p><button class="button secondary" data-logs="${esc(j.id)}">View action logs</button>
 ${j.nodes.map((n,index)=>`<div class="job-result"><strong>${esc(n.short_name||n.name)}</strong>${badge(n.status)}
 ${n.message?`<p>${esc(n.message)}</p>`:''}
 ${n.captured_at?`<small>Captured ${esc(utcDisplay(n.captured_at))}${n.capture_time_source==='legacy job time'?' (time taken from the backup job)':''}</small>`:''}
 ${j.operation==='backup'&&finished&&n.status==='succeeded'&&n.download_name?`<div class="device-download"><code>${esc(n.download_name)}</code><button class="button secondary" data-download="${esc(j.id)}" data-node-index="${index}" data-filename="${esc(n.download_name)}">Download configuration</button></div>`:''}</div>`).join('')}
 ${available?`<div class="archive-download"><button class="button secondary" data-download="${esc(j.id)}" data-filename="${esc(j.archive_name)}">Download all (ZIP)</button><small>${esc(j.archive_name)} · UTC</small></div>`:''}
 </div></details>`;
}
// Tools › Configuration backups lists backup jobs; the automatic login checks sit under a collapsed group
// below them so the card reads as backups while every job (and its action-log link) stays reachable.
function renderJobs(){
 const lab=current();const opened=new Set([...document.querySelectorAll('.job[open]')].map(e=>e.dataset.job));
 const jobs=state.jobs.filter(j=>j.lab_id===lab.id),backups=jobs.filter(j=>j.operation!=='test'),checks=jobs.filter(j=>j.operation==='test'),checksOpen=!!$('login-checks')?.open;
 $('jobs').innerHTML=(backups.length?backups.map(j=>jobMarkup(j,opened)).join(''):'<div class="blank-state"><h2>No backups yet</h2><p>Back up now saves a copy of every device\'s configuration on this VM.</p></div>')+(checks.length?`<details class="job-group" id="login-checks" ${checksOpen?'open':''}><summary>Login checks (${checks.length})</summary>${checks.map(j=>jobMarkup(j,opened)).join('')}</details>`:'');
}
function utcDisplay(value){const date=new Date(value);return Number.isNaN(date.getTime())?'Unknown time':date.toISOString().replace('T',' ').slice(0,19)+' UTC';}
// Five real panels; the legacy sections stay visible inside them except the technical table, which
// follows devicesTechnical. Legacy names scroll to their section once after mapping.
function showTab(value){
 setTab(value);
 for(const name of PANELS){const el=$(name+'-view');if(el)el.hidden=name!==tab;}
 if($('inventory-view'))$('inventory-view').hidden=!devicesTechnical;
 if($('devices-technical')&&typeof $('devices-technical').setAttribute==='function')$('devices-technical').setAttribute('aria-pressed',String(devicesTechnical));
 document.querySelectorAll('[data-tab]').forEach(b=>{const active=b.dataset.tab===tab;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;if(active&&typeof b.scrollIntoView==='function'&&($('lab-tabs')?.scrollWidth||0)>($('lab-tabs')?.clientWidth||0))b.scrollIntoView({block:'nearest',inline:'nearest'});});
 if(tab==='topology'&&typeof refreshMap==='function')refreshMap();
 if(tab==='progress'&&typeof gitShowRepository==='function')gitShowRepository();
 if(scrollTarget){const target=$(scrollTarget);if(target&&typeof target.scrollIntoView==='function')target.scrollIntoView({block:'start'});scrollTarget='';}
}
function tabKeydown(e){
 const step={ArrowLeft:-1,ArrowRight:1,Home:0,End:0}[e.key];if(step===undefined)return;
 const tabs=PANELS.map(name=>$('tab-'+name)).filter(Boolean);if(!tabs.length)return;e.preventDefault();
 const i=Math.max(0,tabs.indexOf(document.activeElement)),next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+step+tabs.length)%tabs.length;
 if(typeof tabs[next].focus==='function')tabs[next].focus();showTab(tabs[next].dataset.tab);syncRoute(true);if(logsVisible())refreshLogs().catch(err=>notify(err.message));
}
function openImport(replace=false){$('import-form').reset();$('import-form').querySelector('.form-error').textContent='';const lab=replace?current():null;$('import-lab-id').value=lab?.id||'';$('lab-name').value=lab?.name||'';$('import-title').textContent=lab?"Replace this lab's device list":'Import a lab from an Ansible inventory';$('import-dialog').showModal();}
function platformOptions(includeUnknown=false){return (includeUnknown?'<option value="">Choose network OS</option>':'')+Object.entries(state.platforms).map(([id,p])=>`<option value="${esc(id)}">${esc(p.label)}</option>`).join('');}
function openProfile(){if(!current())return;$('profile-form').reset();$('profile-form').querySelector('.form-error').textContent='';$('profile-platform').innerHTML=platformOptions()+'<option value="ssh">Linux host (CLI only, no backups)</option>';toggleAuth();$('profile-dialog').showModal();}
function toggleEnable(){$('enable-fields').hidden=$('profile-platform').value!=='arista_ceos';}
function toggleAuth(){toggleEnable();const isKey=$('auth-type').value==='key';$('password-fields').hidden=isKey;$('key-fields').hidden=!isKey;$('private-key').required=isKey;}
function openNode(name){const lab=current(),n=lab.nodes.find(n=>n.name===name);if(!n)return;$('node-form').querySelector('.form-error').textContent='';$('node-title').textContent=(n.short_name||n.name)+' · Connection';$('node-name').value=n.name;$('node-short-name').value=n.short_name||'';$('node-address').value=n.address;$('node-port').value=n.port;$('node-endpoint-mode').value=n.endpoint_mode||'manual';$('node-endpoint-mode').disabled=!lab.deployment_name;$('node-platform').innerHTML=platformOptions(true);$('node-platform').value=n.platform;$('node-enabled').checked=n.enabled;$('node-profile').innerHTML='<option value="">Lab default (lab files or the default profile for this OS)</option>'+lab.profiles.map(p=>`<option value="${esc(p.id)}">${esc(p.label)} · ${esc(p.username)}</option>`).join('');$('node-profile').value=n.profile_id;$('node-dialog').showModal();}
async function withForm(form,fn){const button=form.querySelector('button[type=submit]');button.disabled=true;const error=form.querySelector('.form-error');if(error)error.textContent='';try{await fn();}catch(e){if(error)error.textContent=e.message;else notify(e.message);}finally{button.disabled=false;}}
$('new-lab').onclick=$('import-empty').onclick=()=>openImport();$('import-top').onclick=()=>openImport(!!current());
$('manager-import-inventory').onclick=()=>openImport();
document.querySelectorAll('.close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{showTab(b.dataset.tab);if(typeof closeMenus==='function')closeMenus();syncRoute(true);if(logsVisible())refreshLogs().catch(e=>notify(e.message));});
$('lab-tabs').addEventListener('keydown',tabKeydown);
$('labs').addEventListener('click',e=>{const b=e.target.closest('[data-lab]');if(b)selectLab(b.dataset.lab);});
$('search').oninput=()=>{renderNodes();renderDeviceList();};
$('devices-technical').onclick=()=>{devicesTechnical=!devicesTechnical;showTab('devices');};
$('lab-content').addEventListener('click',e=>{const mirror=e.target.closest('[data-proxy]');if(mirror&&!mirror.disabled)activateProxy(mirror);});
for(const id of ['menu-telemetry','tools-telemetry-settings'])$(id).onclick=()=>{if(typeof openTelemetrySettings==='function'&&typeof opTask==='function')opTask(null,()=>openTelemetrySettings(activeId));};
for(const id of ['menu-lab-files','advanced-lab-files'])$(id).onclick=()=>{if(typeof opBrowse==='function'&&typeof opTask==='function')opTask(null,()=>opBrowse('',activeId));};
// Progress-tab git buttons: onclick properties so git-progress.js can take them over by assigning its own.
for(const b of document.querySelectorAll('#progress-view [data-git-action], #git-repository-advanced [data-git-repo-action]'))b.onclick=()=>{if(typeof closeMenus==='function')closeMenus();if(typeof gitRunAction==='function')gitRunAction(b.dataset.gitAction||b.dataset.gitRepoAction);};
async function handleNodeAction(e){const b=e.target.closest('button');if(!b||b.disabled)return;
 if(b.dataset.capture)openCapture(b.dataset.capture);
 if(b.dataset.edit){$('details-dialog').close();openNode(b.dataset.edit);}
 if(b.dataset.profile!==undefined){profileFromDrawer=detailName;$('details-dialog').close();openProfile();}
 if(b.dataset.details)openDetails(b.dataset.details);
 if(b.dataset.terminal){const url='/static/terminal.html#'+new URLSearchParams({lab:activeId,node:b.dataset.terminal,label:current().name});window.open(url,'_blank');}
 if(b.dataset.backup){$('details-dialog').close();startJob('backup',[b.dataset.backup]);}
 if(b.dataset.check){const labId=activeId;b.disabled=true;try{const result=await json('/labs/'+labId+'/ssh-check','POST',{name:b.dataset.check});notify(result.message);if(activeId===labId)await refreshHealth();}catch(error){notify(error.message);}finally{b.disabled=false;}}
}
for(const id of ['nodes','details-dialog','device-list','topology-devices'])$(id).addEventListener('click',handleNodeAction);
async function handleEnableChange(e){const name=e.target.dataset?.enable;if(!name)return;const n=current().nodes.find(n=>n.name===name);try{await json('/labs/'+activeId+'/node','PUT',{name:n.name,address:n.address,port:n.port,platform:n.platform,profile_id:n.profile_id,enabled:e.target.checked});await refresh();}catch(error){e.target.checked=n.enabled;notify(error.message);renderNodes();if($('details-dialog').open)renderDetails();}}
$('nodes').addEventListener('change',handleEnableChange);$('details-dialog').addEventListener('change',handleEnableChange);
$('import-form').addEventListener('submit',e=>{e.preventDefault();withForm(e.currentTarget,async()=>{const data=new FormData(e.currentTarget);const result=await(await api('/inventory',{method:'POST',body:data})).json();$('import-dialog').close();$('import-form').reset();await refresh();selectLab(result.id,'devices');notify('Lab imported. Check the devices and their login credentials.');});});
$('add-profile').onclick=openProfile;$('auth-type').onchange=toggleAuth;$('profile-platform').onchange=toggleEnable;
$('profile-form').addEventListener('submit',e=>{e.preventDefault();withForm(e.currentTarget,async()=>{const data=new FormData(e.currentTarget);data.set('make_default',$('make-default').checked?'true':'false');await api('/labs/'+activeId+'/profiles',{method:'POST',body:data});$('profile-dialog').close();$('profile-form').reset();noteRecheck(profileFromDrawer);profileFromDrawer='';await refresh();notify('Credentials saved.');});});
$('node-form').addEventListener('submit',e=>{e.preventDefault();withForm(e.currentTarget,async()=>{await json('/labs/'+activeId+'/node','PUT',{name:$('node-name').value,short_name:$('node-short-name').value,address:$('node-address').value,port:Number($('node-port').value),endpoint_mode:$('node-endpoint-mode').value,platform:$('node-platform').value,profile_id:$('node-profile').value,enabled:$('node-enabled').checked});$('node-dialog').close();noteRecheck($('node-name').value);await refresh();notify('Connection updated.');});});
$('schedule-form').addEventListener('submit',e=>{e.preventDefault();withForm(e.currentTarget,async()=>{await json('/labs/'+activeId+'/schedule','PUT',{interval:Number($('interval').value)});await refresh();notify('Backup schedule saved.');});});
async function startJob(operation,node_names){try{await json('/labs/'+activeId+'/jobs','POST',{operation,...(node_names?{node_names}:{})});if(operation==='backup')setTab('backups');await refresh();notify(operation==='test'?'Checking device logins… Results appear under Tools › Configuration backups.':'Backing up configurations…');}catch(e){notify(e.message);}}
$('test').onclick=()=>startJob('test');$('backup').onclick=()=>startJob('backup');
function attachmentName(response,fallback){
 const disposition=response.headers.get('Content-Disposition')||'';
 const encoded=disposition.match(/filename\*=UTF-8''([^;]+)/i);
 if(encoded){try{return decodeURIComponent(encoded[1]);}catch{/* use plain filename */}}
 const plain=disposition.match(/filename="([^"]+)"/i);
 return plain?plain[1]:fallback;
}
async function handleDownload(e){
 const logButton=e.target.closest('[data-logs]');
 if(logButton){$('log-job').value=logButton.dataset.logs;$('log-level').value='';$('log-node').value='';showTab('logs');syncRoute(true);await refreshLogs();return;}
 const button=e.target.closest('[data-download]');if(!button||button.disabled)return;
 button.disabled=true;
 try{
 const node=button.hasAttribute('data-node-index')?'/nodes/'+button.dataset.nodeIndex:'';
 const response=await api('/jobs/'+encodeURIComponent(button.dataset.download)+node+'/download');
 const blob=await response.blob();const url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=attachmentName(response,button.dataset.filename);document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch(error){notify(error.message);}finally{button.disabled=false;}
}
$('jobs').addEventListener('click',handleDownload);

let healthState={lab:'',nodes:[]}, healthRequest=0, detailName='';
function nodeHealth(name){return healthState.lab===activeId?healthState.nodes.find(n=>n.name===name):null;}
async function refreshHealth(){
 const id=activeId,request=++healthRequest;if(!id)return;
 try{const data=await(await api('/labs/'+id+'/health')).json();if(id!==activeId||request!==healthRequest)return;
 healthState={...data,lab:id};renderNodes();if($('details-dialog').open)renderDetails();
 }catch{if(id===activeId&&request===healthRequest){healthState={lab:id,nodes:[]};renderNodes();if($('details-dialog').open)renderDetails();}}
}
// The device workspace. openDetails is safe to call while the drawer is already open (Previous / Next).
// The route gains &device=<name> by replaceState, never pushState: the drawer adds no history entry, so
// Back after closing it leaves the tab instead of landing on the same view, and Back while it is open
// returns to the previous view (applyRoute closes the drawer).
function openDetails(name){if(!current()?.nodes.some(n=>n.name===name))return;detailName=name;renderDetails();const dialog=$('details-dialog');if(!dialog.open&&typeof dialog.showModal==='function')dialog.showModal();if(typeof writeRoute==='function'&&typeof currentRoute==='function')writeRoute(currentRoute());renderDeviceList();}
function stepDetails(direction){const lab=current();if(!lab||lab.nodes.length<2)return;const names=lab.nodes.map(n=>n.name),i=names.indexOf(detailName);if(i<0)return;openDetails(names[(i+direction+names.length)%names.length]);}
function readinessWord(value){return value==='Needs credentials'?'needs credentials':value==='Choose NOS'?'choose a network OS':value==='Lab unavailable'?'the lab is not running':String(value||'');}
// After the student edits a connection or adds credentials from the drawer, the readiness monitor
// re-checks the device within a minute; the drawer says so instead of repeating the old failure.
let detailsRecheck={name:'',at:0},profileFromDrawer='';
function noteRecheck(name){if(name)detailsRecheck={name,at:Date.now()};}
function recheckPending(n){return !!n&&detailsRecheck.name===n.name&&Date.now()-detailsRecheck.at<60000&&!n.ssh_ready;}
function statusActions(n,ds){if(!ds)return '';if(recheckPending(n))return `<button data-check="${esc(n.name)}">Test login now</button>`;if(ds.key==='attention')return `<button data-edit="${esc(n.name)}">Check credentials</button><button data-check="${esc(n.name)}">Test login now</button>`;if(ds.key==='credentials')return ds.next==='Edit connection'?`<button data-edit="${esc(n.name)}">Edit connection…</button>`:`<button data-profile="">Add credentials</button>`;return '';}
function renderDetails(){
 const lab=current(),n=lab?.nodes.find(n=>n.name===detailName);if(!n){if($('details-dialog').open)$('details-dialog').close();return;}
 const h=nodeHealth(n.name),ds=typeof deviceState==='function'?deviceState(n):null;
 $('details-title').textContent=n.short_name||n.name;
 $('details-endpoint').textContent=n.address+':'+n.port;
 if($('details-platform'))$('details-platform').textContent=platformLabel(n.platform);
 if($('details-state')){$('details-state').textContent=ds?ds.label:'';$('details-state').className='pill '+(ds?ds.pill||'neutral':'neutral');}
 for(const id of ['details-prev','details-next'])if($(id))$(id).disabled=lab.nodes.length<2;
 setMarkup($('details-actions'),nodeActions(n,true));
 if($('details-actions-note')){const note=typeof captureStatusLine==='function'?captureStatusLine():'';$('details-actions-note').textContent=note;$('details-actions-note').hidden=!note;}
 setMarkup($('details-advanced-actions'),nodeDrawerActions(n));
 if($('details-status-text'))$('details-status-text').textContent=recheckPending(n)?`Checking ${n.short_name||n.name} again… (automatic within a minute — or Test login now)`:ds?ds.detail:(h?.ssh?.message||'');
 setMarkup($('details-status-actions'),statusActions(n,ds));
 setMarkup($('details-status-raw-body'),`<div class="connection-result">${h?.ssh?badge(h.ssh.status):'<span class="status-neutral">Not checked</span>'}<p>${esc(h?.ssh?.message||'No login check yet.')}</p>${h?.ssh?.at?`<time>${esc(utcDisplay(h.ssh.at))}${h.ssh.source==='automatic'?' · automatic check':''}</time>`:''}</div><p class="form-help">Running devices are checked automatically until they accept a login. Test login (under Advanced) checks the saved credentials now.</p>`);
 setMarkup($('details-info'),`<section class="drawer-section"><h3>Connection</h3><dl class="health-grid"><dt>Name in lab files</dt><dd class="mono">${esc(n.name)}</dd><dt>Network OS</dt><dd>${esc(platformLabel(n.platform))}</dd><dt>Login credentials</dt><dd>${esc(profileName(lab,n))}</dd><dt>Address</dt><dd class="mono">${esc(n.address)}:${esc(n.port)}</dd></dl></section>`);
 setMarkup($('details-advanced-body'),`<dl class="health-grid"><dt>Included in backups</dt><dd><label class="checkbox-label"><input type="checkbox" data-enable="${esc(n.name)}" ${n.enabled?'checked':''} ${!n.platform?'disabled title="Choose a network OS first (Edit connection)"':''}> Include ${esc(n.short_name||n.name)} in backups</label></dd><dt>Can be backed up</dt><dd>${n.readiness==='Ready'?'Yes':'No'+(n.readiness?' — '+esc(readinessWord(n.readiness)):'')}</dd></dl>`);
 const backups=state.jobs.filter(j=>j.lab_id===activeId&&j.operation==='backup'&&!['queued','running'].includes(j.status));
 const entries=backups.flatMap(j=>j.nodes.map((node,index)=>({j,node,index}))).filter(x=>x.node.name===n.name&&x.node.status==='succeeded'&&x.node.download_name);
 $('node-history').innerHTML=entries.length?entries.map(({j,node,index},i)=>`<div class="device-download"><div><strong>${i===0?'Latest successful backup':'Backup'}</strong><small>${esc(utcDisplay(node.captured_at||j.finished||j.created))}</small><code>${esc(node.download_name)}</code></div><button class="button secondary" data-download="${esc(j.id)}" data-node-index="${index}" data-filename="${esc(node.download_name)}">Download configuration</button></div>`).join(''):'<p>No configuration backups for this device yet. Back up configuration creates one.</p>';
}
$('node-history').addEventListener('click',handleDownload);
$('details-prev').onclick=()=>stepDetails(-1);$('details-next').onclick=()=>stepDetails(1);
let logEvents=[], logRequest=0;

async function refreshLogs(){
 const request=++logRequest;
 const params=new URLSearchParams({lab_id:$('log-scope').value==='lab'?activeId:'',job_id:$('log-job').value.trim(),level:$('log-level').value,node:$('log-node').value.trim(),limit:'1000'});
 try{const data=await(await api('/logs?'+params)).json();if(request!==logRequest)return;logEvents=data.events;
 $('log-rows').innerHTML=logEvents.map(e=>`<tr><td>${esc(e.time)}<br>${esc(e.level)}</td><td>${esc(e.node||'Manager')}<br><small>${esc(e.job_id)}</small></td><td>${esc(e.action)}</td><td class="log-message">${esc(e.message)}</td></tr>`).join('');
 $('log-status').textContent=`${logEvents.length} events shown (latest 1,000 matching). Updated ${new Date().toLocaleTimeString()}.`;
 }catch(e){$('log-status').textContent='The logs could not be refreshed: '+e.message;}
}
for(const id of ['log-scope','log-level','log-node','log-job'])$(id).addEventListener('change',refreshLogs);
$('refresh-logs').onclick=refreshLogs;
$('download-logs').onclick=()=>{const blob=new Blob([logEvents.map(e=>JSON.stringify(e)).join('\n')+'\n'],{type:'application/x-ndjson'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='backup-action-logs.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
refresh().catch(e=>notify(e.message));
setInterval(()=>{refresh().catch(()=>{});},4000);
