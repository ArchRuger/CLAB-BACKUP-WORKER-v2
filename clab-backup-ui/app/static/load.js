'use strict';
// Load: the old tab's Apply inside the header (docs/git-redesign/design/LOAD.md). The Load panel lists the saved states of
// the repository, runs the restore preflight for the state chosen and shows the confirmation; the red Load is the acknowledgement
// (owner decision D4). loadSubmit() is the only sender of `acknowledge: true` to a restore route. The restore service is not changed by
// this file: a load replaces the whole running configuration inside each device's own transaction with timed recovery, after a
// mandatory backup, and every outcome is worded from status.js (loadDeviceWord, loadState, loadSourceName) as the service reports it.
// Every name of another script is read at call time behind a typeof guard, so this file loads alone in a Node vm context. Listeners sit
// on elements only (#load-panel, and the clicks of this file's own buttons inside #save-panel and #save-drawer), never on document or window.
const LOAD_STATE_CAP=8, LOAD_OWN_CHECKPOINTS=3, LOAD_MINUTES=5;
const LOAD_GIT_BUSY=['queued','capturing','exporting','pushing'];
const LOAD_RESTORE_BUSY=['queued','preflight','backing_up','applying','confirming','verifying'];
const LOAD_REPLACED=['verified','applied','applied_unverified','verify_mismatch'];
// The devices "Try … again" asks about: those the load did not change. Unknown, interrupted and unverified devices go to Details first.
const LOAD_RETRY=['failed','rolled_back','ineligible'];
const LOAD_VIEW_ONLY_TEXT='Saved without the files needed to load it';
// The review of one state for the lab on screen (LOAD.md 3.1): {labId, source, name, headline, undo, retry, nodes, review, chosen, minutes,
// requestId, seq, phase ('checking' | 'refused' | 'confirm'), error, drawer, keep, sending}. Cleared when the panel closes, when the lab changes
// and after a submit; held only while the differences drawer shows it.
let loadReview=null;
// What #load-panel-body shows: {kind: '' | 'reading' | 'list' | 'error' | 'nothing' | 'notrunning' | 'review' | 'different' | 'result', labId, ...}.
let loadView={kind:'',labId:''};
let loadList=null, loadSeq=0, loadListSeq=0, loadPending=null, loadWatching=null, loadWatchTimer=null, loadPaused='';
// The states list per lab ({repository, repoName, answer}), the jobs this page saw active, the toasts already shown, the freshest copy of a watched job.
const loadStates=new Map(), loadSeenActive=new Set(), loadToasted=new Set(), loadJobs=new Map();

// ---- small helpers ------------------------------------------------------------------------------------------------------------------
function loadEl(id){return typeof $==='function'?$(id):null;}
function loadOnScreen(){return typeof activeId==='string'?activeId:'';}
function loadState_(){return typeof state==='object'&&state?state:{};}
function loadLab(labId){return (loadState_().labs||[]).find(l=>l.id===labId)||null;}
function loadCap(text){const s=String(text||'');return s.charAt(0).toUpperCase()+s.slice(1);}
function loadEpoch(value){if(typeof statusEpoch==='function')return statusEpoch(value);const t=typeof value==='number'?value*(value<1e12?1000:1):new Date(value||0).getTime();return Number.isNaN(t)?0:t;}
function loadWhen(value){if(!value)return '';return typeof relativeTime==='function'?relativeTime(value):String(value);}
function loadDevices(n){return n===1?'1 device':n+' devices';}
function loadJobActive(job){if(typeof statusRestoreActive==='function')return statusRestoreActive(job);return LOAD_RESTORE_BUSY.includes(job?.status)||(job?.status==='interrupted'&&job.rechecking===true);}
function loadEffective(job){if(typeof statusLoadEffective==='function')return statusLoadEffective(job);return !!job&&!loadJobActive(job)&&(job.targets||[]).some(t=>LOAD_REPLACED.includes(t.status)||t.status==='uncertain'||t.stage==='uncertain');}
function loadRestoreActive(labId){return (loadState_().restore_jobs||[]).some(j=>j.lab_id===labId&&loadJobActive(j));}
function loadSaveRunning(labId){const busy=typeof STATUS_GIT_BUSY!=='undefined'?STATUS_GIT_BUSY:LOAD_GIT_BUSY;return (loadState_().git_jobs||[]).some(j=>j.lab_id===labId&&busy.includes(j.status));}
// What holds the manager right now ('' when nothing does), as app.js's busyReason words it: right after a load ends its check backup
// still runs for a few seconds, and a preflight or a submit sent then is answered 409. A control that would send one is disabled
// with this reason until the manager is free.
function loadBusy(labId){return typeof busyReason==='function'?String(busyReason(labId)||''):'';}
function loadRequestId(){if(typeof restoreRequestId==='function')return restoreRequestId();const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return Array.from(bytes,n=>n.toString(16).padStart(2,'0')).join('');}
function loadMinutes(value){return Math.min(60,Math.max(2,parseInt(value,10)||LOAD_MINUTES));}
// The /api/state document plus the saved-states rows this page holds for the lab (loadSourceName names a lab state by them).
function loadCtx(lab){const entry=lab?loadStates.get(lab.id):null;return {...loadState_(),states:entry&&entry.answer&&Array.isArray(entry.answer.states)?entry.answer.states:[]};}
function loadName(source,ctx,lab){return typeof loadSourceName==='function'?loadSourceName(source,ctx,lab):typeof savedVersionName==='function'?savedVersionName(source?.path)||'a saved state':'a saved state';}
// The lab's devices that have a restore format (state.platforms[kind].restore_suffix): the set "Not in this state" and "all 4 devices" count.
function loadLabDevices(lab){const platforms=loadState_().platforms||{};return ((lab&&lab.nodes)||[]).filter(n=>platforms[n.platform]&&platforms[n.platform].restore_suffix);}
function loadDeviceLabel(name,short,platform){const kind=typeof restorePlatformLabel==='function'?restorePlatformLabel(platform):'';return esc(short||name)+(kind?' <small>'+esc(kind)+'</small>':'');}
function loadReason(reason){if(typeof restoreReasonParts==='function')return restoreReasonParts(reason);return {text:typeof restoreReasonLabel==='function'?restoreReasonLabel(reason):String(reason||''),action:'',label:''};}
// The freshest copy of a job: the one loadWatch fetched last, else the one in /api/state.
function loadFresh(job){if(!job)return null;const seen=loadJobs.get(job.id);return seen&&loadEpoch(seen.finished||0)>=loadEpoch(job.finished||0)&&(loadJobActive(job)||!loadJobActive(seen))?seen:job;}
function loadFindJob(id){if(!id)return null;const listed=(loadState_().restore_jobs||[]).find(j=>j.id===id);return loadFresh(listed||loadJobs.get(id)||null);}

// Every source this page sends, to the preflight and to the submit, has exactly these five keys (review L3); an unused one is ''.
// Never the richer `source` object a preflight or a job returns.
function loadSource(source){const s=source||{},text=v=>v==null?'':String(v);return {type:text(s.type),commit:text(s.commit),path:text(s.path),backup_job_id:text(s.backup_job_id),repository:text(s.repository)};}
// The source the submit sends: a folder source carries the commit the preflight read, so the reviewed bytes are the loaded bytes; git and
// backup sources name their bytes themselves and are sent as chosen.
function loadSubmitSource(r){const s=loadSource(r.source);if(s.type==='folder'){const pinned=r.review&&r.review.source&&r.review.source.commit;if(pinned)s.commit=String(pinned);}return s;}

// ---- panel mechanics (initPanel in shell.js) ------------------------------------------------------------------------------------------
function loadPanelOpen(){const panel=loadEl('load-panel');return !!panel&&panel.hidden===false;}
function loadOpenPanel(options){
 if(typeof openPanel==='function'&&openPanel('load-button',options||{}))return true;
 const button=loadEl('load-button');if(button&&typeof button._menuOpen==='function')return !!button._menuOpen(options||{});
 return false;
}
function loadClosePanel(){const button=loadEl('load-button');if(loadPanelOpen()&&button&&typeof button._menuClose==='function')button._menuClose(false);}
function loadFocus(){const body=loadEl('load-panel-body'),target=body&&typeof body.querySelector==='function'?body.querySelector('[data-panel-focus]'):null;if(target&&typeof target.focus==='function')target.focus();}
function loadSet(el,html){if(typeof setMarkup==='function')return setMarkup(el,html);if(el._markup===html)return false;el.innerHTML=html;el._markup=html;return true;}
// Renders the current view into #load-panel-body. focus: move focus to the view's data-panel-focus element (a view change inside the open
// panel); a rebuild that removed the focused element also gives the focus to it, never to <body>.
function loadPaint(focus){
 const body=loadEl('load-panel-body');if(!body)return;
 const active=typeof document!=='undefined'&&document?document.activeElement:null,inside=!!active&&typeof body.contains==='function'&&body.contains(active);
 const changed=loadSet(body,loadViewMarkup());
 if((focus||(changed&&inside))&&loadPanelOpen())loadFocus();
}
function loadAnnounce(text){const live=loadEl('save-live');if(live&&text)live.textContent=text;}

// ---- the list (G02, G08) ----------------------------------------------------------------------------------------------------------
// Opens the Load panel on the list. The Load button opens on the list too (panelopen): a confirmation is never what a click on Load shows.
function loadOpen(labId){
 const id=labId||loadOnScreen();if(!id||id!==loadOnScreen())return false;
 if(!loadPanelOpen()){loadPending={kind:'list',labId:id};if(loadOpenPanel())return true;loadPending=null;return false;}
 loadShowList(id,true);return true;
}
function loadPanelOpened(){
 const id=loadOnScreen(),pending=loadPending;loadPending=null;
 if(pending&&pending.kind==='result'&&pending.labId===id){loadReview=null;loadView={kind:'result',labId:id,jobId:pending.jobId};loadPaint(false);return;}
 if(pending&&pending.kind==='list'){loadShowList(id,false);return;}
 // Back from the differences drawer: the same confirmation, the same ticks and request id, for the review of the lab on screen only.
 if(loadReview&&loadReview.keep&&loadReview.labId===id){loadReview.keep=false;loadView={kind:'review',labId:id};loadPaint(false);return;}
 loadShowList(id,false);
}
function loadPanelClosed(){
 if(loadReview&&!loadReview.drawer&&!loadReview.keep)loadReview=null;
 loadView={kind:'',labId:''};loadListSeq++;
}
// The manager's sentence with the devices as the page names them (their short names, never the container names).
function loadShortNames(labId,text){
 const lab=loadLab(labId);let out=String(text||'');
 for(const node of [...((lab&&lab.nodes)||[])].sort((x,y)=>String(y.name||'').length-String(x.name||'').length))if(node.name&&node.short_name&&node.short_name!==node.name)out=out.split(node.name).join(node.short_name);
 return out;
}
function loadLabStopped(lab){
 const deployed=lab.deployment&&lab.deployment.status,ls=typeof labState==='function'?labState(lab,typeof labContext==='function'?labContext():loadState_()):null;
 return deployed==='Not deployed'||deployed==='Stopped'||!!(ls&&ls.key==='stopped');
}
async function loadShowList(labId,focus){
 loadReview=null;
 const lab=loadLab(labId);if(!lab){loadView={kind:'',labId:''};return;}
 // Not running is what the VM says about the deployment, whatever else the lab's pill reports: a lab that also "needs attention"
 // (a load that ended on some devices only, a failed operation) is still a stopped lab, and nothing can be loaded onto it.
 if(loadLabStopped(lab)){loadView={kind:'notrunning',labId};loadPaint(focus);return;}
 loadView={kind:loadStates.has(labId)?'list':'reading',labId};loadPaint(focus);
 const seq=++loadListSeq,still=()=>seq===loadListSeq&&loadOnScreen()===labId&&loadView.labId===labId&&['list','reading','error'].includes(loadView.kind);
 try{
  const states=await loadFetchStates(labId,lab);
  if(!still())return;
  if(states.nothing){loadView={kind:'nothing',labId};loadPaint(false);return;}
  loadStates.set(labId,states);loadView={kind:'list',labId};loadPaint(false);
 }catch(error){if(!still())return;loadView={kind:'error',labId,message:String(error&&error.message||'')};loadPaint(false);}
}
// The saved states of the lab's repository: its own save location, or for a lab without one the default repository of
// GET …/git/places (DESIGN.md 2.8; LOAD.md section 8). Fetched when the panel opens, never on the poll. → {repository, repoName, answer} or {nothing: true}.
async function loadFetchStates(labId,lab){
 let repository='',repoName='';
 if(!lab.git_binding){
  const places=await (await api('/labs/'+encodeURIComponent(labId)+'/git/places')).json();
  const repos=Array.isArray(places&&places.repositories)?places.repositories:[];
  if(!repos.length)return {nothing:true};
  repository=String((places.default&&places.default.repository)||repos[0].id||'');
  repoName=String((repos.find(r=>r.id===repository)||repos[0]).name||'');
 }
 const answer=await (await api('/labs/'+encodeURIComponent(labId)+'/restore/states'+(repository?'?repository='+encodeURIComponent(repository):''))).json();
 return {repository,repoName,answer:answer&&typeof answer==='object'?answer:{}};
}
// The lab's own latest save is named by the newest save that wrote `latest` (its name), `Your latest save` when it has none.
function loadLatestName(lab){
 const own=(loadState_().git_jobs||[]).filter(j=>j.lab_id===lab.id&&j.commit&&(j.target||'latest')==='latest'&&j.kind!=='state'&&j.kind!=='design').sort((a,b)=>loadEpoch(b.finished||b.created)-loadEpoch(a.finished||a.created));
 return own[0]&&own[0].note?String(own[0].note):'Your latest save';
}
// `4 devices` (every device of the lab with a restore format can be loaded), `2 of 4 devices`, or '' when the save details are unknown.
function loadCoverage(row,labDevices){
 if(row.saved_devices==null||row.loadable_devices==null)return '';
 const n=Math.max(0,Number(row.loadable_devices)||0),m=Math.max(0,Number(labDevices)||0);
 return !m||n>=m?loadDevices(n):n+' of '+m+' devices';
}
// Pure: the model of the list for a lab from its states answer. The own saves only for a lab read through its own save location.
function loadListModel(lab,entry){
 entry=entry||{};const answer=entry.answer||{},rows=Array.isArray(answer.states)?answer.states.filter(r=>r&&typeof r==='object'):[];
 const own=!!(lab&&lab.git_binding)&&!entry.repository;
 const latest=own?rows.filter(r=>r.group==='latest').slice(0,1):[];
 const checkpoints=own?rows.filter(r=>r.group==='checkpoint').sort((a,b)=>loadEpoch(b.saved_at)-loadEpoch(a.saved_at)).slice(0,LOAD_OWN_CHECKPOINTS):[];
 const states=rows.filter(r=>r.group==='state');
 const labDevices=Number.isFinite(answer.lab_devices)?answer.lab_devices:loadLabDevices(lab).length;
 const repository=String(entry.repository||'');
 const item=(row,name,when)=>({row,name,when,source:loadSource({type:'folder',path:'/'+String(row.path||'').replace(/^\/+/,''),commit:row.commit,repository})});
 const ctx=loadCtx(lab);
 // One time for one save: the lab's latest save shows the time it was saved (the job's, as the chip and All versions show it),
 // not the time its folder was last written (an upload or a checkpoint made from it touches the folder later).
 const bare=value=>String(value||'').replace(/^\/+|\/+$/g,'');
 const saved=own&&latest.length?(ctx.git_jobs||[]).filter(j=>j&&j.lab_id===lab.id&&j.target==='latest'&&j.kind!=='state'&&j.kind!=='design'&&j.commit&&Array.isArray(j.changed_files)&&j.changed_files.length>0)
  .sort((a,b)=>String(b.created||'').localeCompare(String(a.created||'')))[0]:null;
 const latestAt=row=>saved&&bare(saved.snapshot_path)===bare(row.path)?(saved.finished||saved.created||row.saved_at):row.saved_at;
 return {lab,own,repository,repoName:String(entry.repoName||''),labDevices,
  saves:[...latest.map(r=>item(r,loadLatestName(lab),loadWhen(latestAt(r)))),...checkpoints.map(r=>item(r,loadName({type:'folder',path:r.path},ctx,lab)||r.name,loadWhen(r.saved_at)))],
  states:states.slice(0,LOAD_STATE_CAP).map(r=>item(r,String(r.name||'')||(typeof savedVersionName==='function'?savedVersionName(r.path):'')||'A saved state',loadCoverage(r,labDevices))),
  more:Math.max(0,states.length-LOAD_STATE_CAP)};
}
function loadListMarkup(model){
 const items=[...model.saves,...model.states];loadList={labId:model.lab?model.lab.id:'',repository:model.repository,items};
 const row=(it,i)=>{
  const r=it.row;
  if(r.view_only)return `<li class="off"><div class="save-item"><span>${esc(it.name)}<span class="save-why">${esc(LOAD_VIEW_ONLY_TEXT)}</span></span><span class="save-when">View only</span></div><button type="button" class="button ghost small" id="load-view-${i}" data-load-view="${i}">View</button></li>`;
  const unknown=r.view_only_reason==='unknown'||r.view_only_reason==='unreadable';
  return `<li><button type="button" class="save-item" id="load-row-${i}" data-load-row="${i}"><span>${esc(it.name)}${unknown?'<span class="save-why">Its save details cannot be read</span>':''}</span><span class="save-when">${esc(it.when)}</span></button></li>`;
 };
 let html='<h2 class="sr-only" tabindex="-1" data-panel-focus>Load a saved state</h2>';
 if(model.saves.length)html+=`<h3 class="save-heading">Your saves</h3><ul class="save-list">${model.saves.map((it,i)=>row(it,i)).join('')}</ul>`;
 else if(model.states.length)html+='<p class="save-sub">This lab has no saves of its own yet. You can start from one of these.</p>';
 if(model.states.length){
  html+=`<h3 class="save-heading">Lab states</h3><ul class="save-list">${model.states.map((it,i)=>row(it,model.saves.length+i)).join('')}</ul>`;
  if(model.more)html+=`<p class="save-note">${esc(model.more)} more in All versions</p>`;
 }
 if(!model.saves.length&&!model.states.length)html+='<p class="save-sub">Nothing is saved in this repository yet. Save this lab, or ask your instructor for the course’s lab states.</p>';
 if(!model.own)html+=`<p class="save-note">From ${esc(model.repoName||'the repository')}.</p>`;
 return html+loadFootMarkup();
}
function loadFootMarkup(){return '<div class="save-foot"><button type="button" class="button ghost small" id="load-all" data-load-action="all">All versions</button><button type="button" class="button ghost small" id="load-browse" data-load-action="browse">Browse the repository…</button></div>';}
function loadNotRunningMarkup(){
 const start=loadEl('lab-start'),disabled=!!(start&&start.disabled),small=start&&typeof start.querySelector==='function'?start.querySelector('.menu-reason'):null,reason=disabled&&small?String(small.textContent||''):'';
 return `<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot none" aria-hidden="true"></span>Start the lab to load a state</p><p class="save-sub">Loading puts a saved configuration onto running devices. This lab is not running.</p><div class="save-row"><button type="button" class="button primary" id="load-start" data-load-action="start"${disabled?' disabled':''}>Start lab</button>${reason?`<span class="caption">${esc(reason)}</span>`:''}</div>`;
}

// ---- the confirmation (G03, G07) --------------------------------------------------------------------------------------------------
// Starts a review: runs the preflight for `source` and shows the confirmation in the Load panel, opening it when it is closed. Every way
// to load ends here (a row, Load this state…, Undo this load, Try … again, Load this backup…), and never in loadSubmit. It does nothing for
// a lab that is not on screen and while a load of the lab runs. options: {nodes: [names] (a retry: only those are asked about and listed),
// headline, undo: {changed}}.
async function loadChoose(labId,source,name,options){
 options=options||{};
 if(!labId||labId!==loadOnScreen())return false;
 const lab=loadLab(labId);if(!lab||loadRestoreActive(labId))return false;
 const nodes=Array.isArray(options.nodes)?options.nodes.map(String):null;
 const r={labId,source:loadSource(source),name:String(name||'')||'a saved state',headline:String(options.headline||''),undo:options.undo||null,retry:!!nodes,nodes,
  review:null,chosen:new Set(),minutes:LOAD_MINUTES,requestId:loadRequestId(),seq:++loadSeq,phase:'checking',error:'',drawer:false,keep:false,sending:false,args:[labId,source,name,options]};
 loadReview=r;
 // The server refuses a preflight while a save of the lab runs, or anything else holds the manager (guard_idle); none is sent.
 // That is a wait, never a failed load: the view says what runs and Try again is available when it has finished.
 const hold=loadSaveRunning(labId)?'A save is running.':loadBusy(labId);
 if(hold){r.phase='refused';r.wait=true;r.error=hold;loadShowReview();return false;}
 // No preflight for a review the page cannot show (no Load panel): nothing is asked of the devices that nobody sees.
 if(!loadShowReview()){loadReview=null;return false;}
 loadAnnounce(`Checking ${r.name} against your devices…`);
 let answer;
 try{answer=await json('/labs/'+encodeURIComponent(labId)+'/restore/preflight','POST',nodes?{source:r.source,node_names:nodes}:{source:r.source});}
 catch(error){if(loadReview!==r)return false;r.phase='refused';r.wait=!!error&&error.status===409;r.error=String(error&&error.message||'');loadShowReview();return false;}
 // An answer for a review that was cleared or replaced meanwhile, or for a lab no longer on screen, renders nothing.
 if(loadReview!==r||r.labId!==loadOnScreen())return false;
 r.review=answer&&typeof answer==='object'?answer:{};r.phase='confirm';
 for(const row of loadConfirmRows(r,lab))if(row.eligible)r.chosen.add(row.name);
 loadShowReview();return true;
}
function loadShowReview(){
 const r=loadReview;if(!r)return false;
 loadView={kind:'review',labId:r.labId};
 if(!loadPanelOpen()){r.keep=true;if(loadOpenPanel())return true;r.keep=false;return false;}
 loadPaint(true);return true;
}
// Pure: the rows of the confirmation (LOAD.md 3.2). Each {name, label (escaped markup), eligible, text, why, action, actionLabel, off, derived}.
// A retry lists only the devices it asked about (review L2); otherwise every lab device with a restore format that the state does not
// hold is added as `Not in this state`.
function loadConfirmRows(r,lab){
 const targets=((r.review&&r.review.targets)||[]).filter(t=>t&&(!r.retry||t.requested===true));
 const rows=targets.map(t=>{
  const base={name:String(t.name||''),label:loadDeviceLabel(t.name,t.short_name,t.platform),eligible:false,text:'',why:'',action:'',actionLabel:'',off:true,derived:false};
  if(t.eligible===true&&t.requested!==false){
   const n=Number(t.pending_changes);
   const text=t.matches_saved===true?'Already matches':Number.isFinite(n)&&n>0?(n===1?'1 line differs':n+' lines differ'):'Ready to load';
   return {...base,eligible:true,off:false,text};
  }
  const reason=String(t.reason||'');
  if(reason.startsWith('No running node in this lab matches'))return {...base,text:'Not in this lab'};
  const parts=loadReason(reason||'Not eligible');
  const kind=t.reachable===false?'Not reachable':t.reachable===true?'Blocked':'Can’t load';
  return {...base,text:kind,why:parts.text,action:parts.action||'',actionLabel:parts.label||''};
 });
 if(!r.retry){
  const named=new Set(rows.map(x=>x.name));
  for(const n of loadLabDevices(lab))if(!named.has(n.name))rows.push({name:String(n.name),label:loadDeviceLabel(n.name,n.short_name,n.platform),eligible:false,text:'Not in this state',why:'',action:'',actionLabel:'',off:true,derived:true});
 }
 return rows;
}
// Why the red Load is disabled, as the visible text beside it; '' when it is enabled.
function loadRunReason(r,rows){
 rows=rows||loadConfirmRows(r,loadLab(r.labId));
 if(!rows.some(x=>x.eligible))return '';
 if(loadSaveRunning(r.labId))return 'A save is running.';
 const hold=loadBusy(r.labId);if(hold)return hold;
 if(!rows.some(x=>x.eligible&&r.chosen.has(x.name)))return 'Tick at least one device.';
 return '';
}
function loadConfirmMarkup(r,lab){
 const rows=loadConfirmRows(r,lab),eligible=rows.filter(x=>x.eligible).length,derived=rows.filter(x=>x.derived).length,source=(r.review&&r.review.source)||{};
 const reason=loadRunReason(r,rows),topology=source.topology||{},saved=loadWhen(source.captured_at);
 const covered=loadLabDevices(lab).length-derived;
 let html=`<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot warn" aria-hidden="true"></span>${esc(r.headline||`Load ${r.name}?`)}</p>`;
 html+=`<p class="save-sub">${eligible?'The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.':'None of the devices can be loaded right now.'}</p>`;
 if(saved)html+=`<p class="save-note">Saved ${esc(saved)}.</p>`;
 if(r.retry)html+='<p class="save-note">Only the devices that were not loaded are listed.</p>';
 else if(derived&&r.undo)html+=`<p class="save-note">This undoes the load on ${r.undo.changed===1?'the device':'the '+esc(r.undo.changed)+' devices'} it changed. The others are left as they are.</p>`;
 else if(derived)html+=`<p class="save-note">This state covers ${esc(covered)} of your ${esc(loadLabDevices(lab).length)} devices. The others are left as they are.</p>`;
 if(topology.differs===true)html+=`<p class="save-note">Saved on a different topology: ${esc(Number(topology.matching_devices)||0)} of ${esc(Number(topology.saved_devices)||0)} devices match. <button type="button" class="button ghost small" id="load-topology" data-load-action="topology">View its topology</button></p>`;
 html+='<ul class="save-devices">'+rows.map((x,i)=>{
  const why=x.why?`<span class="save-why">${esc(x.why)}</span>`:'';
  const act=x.action?`<button type="button" class="button ghost small" id="load-fix-${i}" data-load-action="${esc(x.action)}">${esc(x.actionLabel)}</button>`:'';
  return `<li${x.off?' class="off"':''}><label><input type="checkbox" name="load-node" id="load-node-${i}" value="${esc(x.name)}"${x.eligible?(r.chosen.has(x.name)?' checked':''):' disabled'}><span>${x.label}${why}</span></label>${act}<span class="save-end">${esc(x.text)}</span></li>`;
 }).join('')+'</ul>';
 html+='<p class="save-note">Each device checks the new configuration itself and undoes it if it loses contact.</p>';
 html+=`<details><summary>Options</summary><label for="load-minutes">Undo automatically if a device cannot be reached again within (minutes)</label><input id="load-minutes" type="number" min="2" max="60" value="${esc(loadMinutes(r.minutes))}"></details>`;
 html+=`<p class="form-error" role="alert">${esc(r.error||'')}</p>`;
 html+=`<div class="save-row"><button type="button" class="button danger" id="load-run" data-load-action="run"${reason||!eligible||r.sending?' disabled':''}>Load</button><button type="button" class="button ghost small" id="load-cancel" data-load-action="cancel">Cancel</button><button type="button" class="button ghost small" id="load-diff" data-load-action="diff">See what’s different</button><span class="caption" id="load-run-reason"${reason?'':' hidden'}>${esc(reason)}</span></div>`;
 return html;
}
function loadCheckingMarkup(r){return `<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot busy" aria-hidden="true"></span>Checking ${esc(r.name)} against your devices…</p><div class="save-row"><button type="button" class="button ghost small" id="load-cancel" data-load-action="cancel">Cancel</button></div>`;}
function loadRefusedMarkup(r){
 // The manager was busy (another backup, save, load or lab operation): a wait with Try again, never a failed load.
 if(r.wait){
  const hold=loadSaveRunning(r.labId)?'A save is running.':loadBusy(r.labId);
  return `<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot busy" aria-hidden="true"></span>${esc(loadCap(r.name))} can be loaded in a moment.</p><p class="save-sub" id="load-wait-why">${esc(hold||r.error||'')}</p><div class="save-row"><button type="button" class="button primary" id="load-again" data-load-action="again"${hold?' disabled':''} aria-describedby="load-wait-why">Try again</button><button type="button" class="button ghost small" id="load-back" data-load-action="back">Back</button>${hold?'<span class="caption" id="load-wait-note">Available when it finishes.</span>':''}</div>`;
 }
 return `<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot bad" aria-hidden="true"></span>${esc(loadCap(r.name))} cannot be loaded right now.</p><p class="save-sub" id="load-refused-why">${esc(loadShortNames(r.labId,r.error||''))}</p><div class="save-row"><button type="button" class="button primary" id="load-again" data-load-action="again">Try again</button><button type="button" class="button ghost small" id="load-back" data-load-action="back">Back</button></div>`;
}
// The poll switches only the red button's disabled state and its reason; the confirmation itself is not rebuilt, so the ticks, an open
// Options and the focus stay.
function loadSyncRun(){
 const r=loadReview,run=loadEl('load-run'),why=loadEl('load-run-reason');if(!r||r.phase!=='confirm'||!run)return;
 const rows=loadConfirmRows(r,loadLab(r.labId)),reason=loadRunReason(r,rows);
 run.disabled=!!reason||r.sending||!rows.some(x=>x.eligible);
 if(why){why.textContent=reason;why.hidden=!reason;}
}

// ---- the submit: the only sender of `acknowledge: true` to a restore route (D4) ------------------------------------------------------
// Reached only from the click on the red Load of a confirmation and on the drawer's "Load on n devices". It sends nothing unless the review
// is of the lab on screen, its preflight has answered, a device is ticked and no save of the lab runs; a second click while the first is out
// sends nothing (and the request id is one per review, so a lost answer retried returns the same job).
async function loadSubmit(){
 const r=loadReview,labId=loadOnScreen();
 if(!r||r.labId!==labId||r.phase!=='confirm'||!r.review||r.sending)return null;
 const eligible=new Set(loadConfirmRows(r,loadLab(labId)).filter(x=>x.eligible).map(x=>x.name)),chosen=[...r.chosen].filter(n=>eligible.has(n));
 if(!chosen.length||loadSaveRunning(labId))return null;
 r.sending=true;r.error='';loadSyncRun();
 let job;
 try{job=await json('/labs/'+encodeURIComponent(labId)+'/restore','POST',{request_id:r.requestId,source:loadSubmitSource(r),node_names:chosen,confirm_minutes:loadMinutes(r.minutes),acknowledge:true});}
 catch(error){r.sending=false;if(loadReview===r){r.error=String(error&&error.message||'');if(loadView.kind==='review')loadPaint(false);loadSyncRun();if(r.drawer&&typeof saveDrawerRender==='function')saveDrawerRender();}return null;}
 if(loadReview===r)loadReview=null;
 if(r.drawer&&typeof saveDrawerClose==='function')saveDrawerClose();
 loadClosePanel();
 if(job&&job.id){loadJobs.set(job.id,job);loadSeenActive.add(job.id);}
 if(typeof refresh==='function'){try{await refresh();}catch{/* the 4 s poll catches up */}}
 if(typeof saveOpenPanel==='function')saveOpenPanel('status');else if(typeof openPanel==='function')openPanel('save-chip');
 if(job&&job.id)loadWatch(job);
 return job;
}

// ---- See what's different: the drawer kind 'different' (save-drawers.js) ------------------------------------------------------------
// → {title, meta, html} for the drawer: the title, the meta line, and the content with its own action row (Load on n devices, Back) and the
// saved → running now differences of the ticked devices. No request. With no review (cleared meanwhile) the html is empty.
function loadDifferentMarkup(review){
 const r=review||loadReview;
 if(!r||!r.review)return {title:'What’s different',meta:'',html:''};
 const source=r.review.source||{},targets=r.review.targets||[],rows=loadConfirmRows(r,loadLab(r.labId));
 const ticked=rows.filter(x=>x.eligible&&r.chosen.has(x.name)),count=ticked.length,saving=loadSaveRunning(r.labId);
 const reason=saving&&rows.some(x=>x.eligible)?'A save is running.':(rows.some(x=>x.eligible)&&loadBusy(r.labId))||(count?'':'Tick at least one device.');
 const meta=[loadCap(r.name)+' compared with what the devices run now',source.captured_at?'saved '+loadWhen(source.captured_at):'',source.commit?String(source.commit).slice(0,10):''].filter(Boolean).join(' · ');
 let html=`<div class="save-row"><button type="button" class="button danger" id="load-diff-run" data-load-action="diff-run"${reason||r.sending?' disabled':''}>Load on ${esc(loadDevices(count))}</button><button type="button" class="button ghost small" id="load-diff-back" data-load-action="diff-back">Back</button><span class="caption" id="load-diff-reason"${reason?'':' hidden'}>${esc(reason)}</span></div>`;
 if(r.error)html+=`<p class="form-error" role="alert">${esc(r.error)}</p>`;
 const shown=ticked.map(x=>targets.find(t=>String(t.name)===x.name)).filter(t=>t&&!(t.diff&&t.diff.identical)&&t.matches_saved!==true);
 html+=shown.map(t=>`<h3 class="save-heading">${loadDeviceLabel(t.name,t.short_name,t.platform)}</h3>${typeof restoreDiffBody==='function'?restoreDiffBody(t):''}`).join('');
 if(!shown.length)html+=`<p class="save-note">${count?'The ticked devices already run '+esc(r.name)+'.':'No device is ticked.'}</p>`;
 return {title:'What’s different',meta,html};
}
// Back from the differences: the panel shows the same confirmation (same ticks, same request id), only for the review of the lab on screen.
function loadDifferentBack(){
 const r=loadReview;
 if(!r||r.labId!==loadOnScreen()||r.phase!=='confirm'){loadReview=null;if(typeof saveDrawerClose==='function')saveDrawerClose();return false;}
 if(r.drawer){r.drawer=false;r.keep=true;if(typeof saveDrawerClose==='function')saveDrawerClose();if(!loadPanelOpen()){if(!loadOpenPanel())r.keep=false;}else{r.keep=false;loadView={kind:'review',labId:r.labId};loadPaint(true);}return true;}
 loadView={kind:'review',labId:r.labId};loadPaint(true);return true;
}
// The drawer closed by anything but Back drops the review it held.
function loadDrawerClosed(){if(loadReview&&loadReview.drawer)loadReview=null;}
function loadOpenDifferent(){
 const r=loadReview;if(!r||r.phase!=='confirm')return;
 if(typeof saveDrawerOpen==='function'){r.drawer=true;saveDrawerOpen('different',{review:r,opener:loadEl('load-button')});return;}
 loadView={kind:'different',labId:r.labId};loadPaint(true);   // a page without the drawer shows the differences in the panel
}

// ---- loading, results, undo, retry (G04, G05, G06) --------------------------------------------------------------------------------
function loadRowsMarkup(job){
 return '<ul class="save-devices">'+((job&&job.targets)||[]).map(t=>{
  const w=typeof loadDeviceWord==='function'?loadDeviceWord(t,job):{text:String(t.status||''),cls:'',help:''};
  let help=String(w.help||'');
  if(t.status==='ineligible'&&t.message)help=typeof restoreReasonLabel==='function'?restoreReasonLabel(t.message):String(t.message);
  else if(t.status==='failed'&&help&&typeof restoreReasonLabel==='function')help=restoreReasonLabel(help);
  return `<li><span>${loadDeviceLabel(t.name,t.short_name,t.platform)}${help?`<span class="save-why">${esc(help)}</span>`:''}</span><span class="save-end${w.cls?' '+esc(w.cls):''}">${esc(w.text)}</span></li>`;
 }).join('')+'</ul>';
}
// The body of the loading view (G04), and the device rows of every result view: words from loadDeviceWord only.
function loadJobMarkup(job){
 if(!job)return '';
 const active=loadJobActive(job),rechecking=job.status==='interrupted'&&job.rechecking===true;
 const lead=!active?'':rechecking?(typeof STATUS_RESTORE_RECHECK_DETAIL==='string'?STATUS_RESTORE_RECHECK_DETAIL:'The manager restarted while it was replacing configuration and is reading back the devices it was changing.'):'Each device checks the new configuration itself and undoes it if it loses contact. You can keep working.';
 return (lead?`<p class="save-sub">${esc(lead)}</p>`:'')+loadRowsMarkup(job)+(loadPaused===job.id?`<p class="save-note">Status updates paused. <button type="button" class="button ghost small" id="load-resume" data-load-action="resume" data-load-job="${esc(job.id)}">Refresh</button></p>`:'');
}
// One sentence for a load that did not change every device, by the worst remaining outcome, uncertain first (LOAD.md section 10).
function loadPartialSentence(job){
 const targets=(job&&job.targets)||[],label=t=>String(t.short_name||t.name||'');
 const unknown=targets.filter(t=>t.status==='uncertain'||t.status==='interrupted'||t.status==='rollback_expected'||t.stage==='uncertain');
 const undone=targets.filter(t=>t.status==='rolled_back'),unchanged=targets.filter(t=>t.status==='failed'||t.status==='ineligible');
 const unverified=targets.filter(t=>t.status==='applied_unverified'||t.status==='verify_mismatch');
 const parts=[];
 if(unknown.length)parts.push(unknown.length===1?`The manager could not confirm what ${label(unknown[0])} runs. Open Details before relying on it.`:`The manager could not confirm what ${unknown.length} devices run. Open Details before relying on them.`);
 if(undone.length)parts.push(undone.length===1?`${label(undone[0])} undid the change and runs its previous configuration again.`:`${undone.length} devices undid the change and run their previous configuration again.`);
 if(unchanged.length)parts.push(unchanged.length===1?`${label(unchanged[0])} was not changed.`:`${unchanged.length} devices were not changed.`);
 if(unverified.length)parts.push(unverified.length===1?`${label(unverified[0])} was loaded, but the check afterwards did not confirm it. Open Details.`:`${unverified.length} devices were loaded, but the check afterwards did not confirm them. Open Details.`);
 return parts.join(' ');
}
function loadRetryNodes(job){return ((job&&job.targets)||[]).filter(t=>LOAD_RETRY.includes(t.status));}
function loadRetryLabel(job){const nodes=loadRetryNodes(job);return !nodes.length?'':nodes.length===1?`Try ${nodes[0].short_name||nodes[0].name} again`:`Try ${nodes.length} devices again`;}
// `hold`: what holds the manager (loadBusy); Undo this load then waits, with the reason beside it.
function loadUndoMarkup(job,undo,cls,hold){
 if(!job||!job.pre_backup_job_id||!undo)return {button:'',note:''};
 return {button:`<button type="button" class="${cls}" id="load-undo" data-load-action="undo" data-load-job="${esc(job.id)}"${undo.available&&!hold?'':' disabled'}>Undo this load</button>`,note:!undo.available&&undo.reason?`<p class="save-note">${esc(undo.reason)}</p>`:''};
}
function loadHoldNote(hold){return hold?`<p class="save-note" id="load-hold">${esc(hold)} Available when it finishes.</p>`:'';}
// The chip panel's view for the states Loading, Running and Partial, called by save-header.js (savePanelView). → {title, dot, key, html}:
// `title` goes into the panel title, `dot` is the save-dot modifier, `key` changes only when what the body shows changes (no time in it),
// `html` is the body. null for any other state. cs is saveChipState's answer; its `load` (loadState's answer) is used when present.
function loadChipView(cs,lab){
 if(!lab)return null;
 const ctx=loadCtx(lab),ls=(cs&&cs.load)||(typeof loadState==='function'?loadState(lab,ctx):null);if(!ls)return null;
 const want=cs&&['loading','running','partial'].includes(cs.key)?cs.key:cs&&['loading','running','partial'].includes(cs.panel)?cs.panel:ls.key;
 const view=['loading','running','partial'].includes(ls.key)?ls.key:want;
 if(!['loading','running','partial'].includes(view))return null;
 const job=loadFresh(ls.job||(cs&&cs.job));if(!job)return null;
 const words=(job.targets||[]).map(t=>typeof loadDeviceWord==='function'?loadDeviceWord(t,job).text:t.status).join(',');
 const hold=view==='loading'?'':loadBusy(lab.id);
 const key=['load',view,job.id,job.status,words,ls.undo&&ls.undo.available?'u':'',loadPaused===job.id?'p':'',hold].join('|');
 if(view==='loading'){
  if(loadJobActive(job))loadWatch(job);
  const rechecking=job.status==='interrupted'&&job.rechecking===true;
  return {title:rechecking?'Checking devices…':`Loading ${ls.name}…`,dot:'busy',key,html:loadJobMarkup(job)};
 }
 const undo=loadUndoMarkup(job,ls.undo,'button ghost small',hold);undo.note+=loadHoldNote(hold&&(undo.button||loadRetryLabel(job))?hold:'');
 const details=`<button type="button" class="button ghost small" id="load-details" data-load-action="details" data-load-job="${esc(job.id)}">${view==='running'?'What changed':'Details'}</button>`;
 if(view==='running'){
  const m=(job.targets||[]).length,names=new Set((job.targets||[]).map(t=>t.name)),labDevices=loadLabDevices(lab),all=labDevices.length>0&&labDevices.every(n=>names.has(n.name));
  const when=loadWhen(job.finished),latest=typeof statusCaptureSaves==='function'?statusCaptureSaves(lab,ctx)[0]:null;
  let html=`<p class="save-sub">Loaded ${when?esc(when)+' ':''}on ${all?'all ':''}${esc(loadDevices(m))}.</p>`;
  if(latest)html+=`<p class="save-kv"><span>Your latest save:</span> ${esc(latest.note||'Saved without a name')}${loadWhen(latest.finished||latest.created)?', '+esc(loadWhen(latest.finished||latest.created)):''}</p>`;
  if(job.pre_backup_job_id)html+='<p class="save-kv"><span>Before loading:</span> backed up automatically</p>';
  html+=`<div class="save-foot">${undo.button}${details}</div>${undo.note}`;
  return {title:`Running ${ls.name}`,dot:'info',key,html};
 }
 const retry=loadRetryLabel(job);
 const html=`<p class="save-sub">${esc(loadPartialSentence(job))}</p>${loadRowsMarkup(job)}<div class="save-row">${retry?`<button type="button" class="button primary" id="load-retry" data-load-action="retry" data-load-job="${esc(job.id)}"${hold?' disabled':''}>${esc(retry)}</button>`:''}${undo.button}${details}</div>${undo.note}`;
 return {title:`Loaded on ${ls.loaded} of ${ls.total} devices`,dot:'warn',key,html};
}
// A load that changed nothing (not an effective load) is no chip state; when the chip panel showed it as it ended, the Load panel shows it.
function loadResultMarkup(job){
 if(!job)return '<h2 class="sr-only" tabindex="-1" data-panel-focus>Load a saved state</h2>';
 const lab=loadLab(job.lab_id),name=loadName(job.source,loadCtx(lab),lab),retry=loadRetryLabel(job);
 return `<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot bad" aria-hidden="true"></span>${esc(loadCap(name))} was not loaded</p><p class="save-sub">No device was changed.</p>${loadRowsMarkup(job)}<div class="save-row">${retry?`<button type="button" class="button primary" id="load-retry" data-load-action="retry" data-load-job="${esc(job.id)}">Try again</button>`:''}<button type="button" class="button ghost small" id="load-details" data-load-action="details" data-load-job="${esc(job.id)}">Details</button></div>`;
}
// Undo this load (D7): an ordinary load of the job's automatic backup, through the same preflight, confirmation, mandatory backup and
// transaction. Nothing happens for a load that changed nothing, without a backup, or once the backup is no longer kept (or failed).
function loadUndo(job){
 if(!job||!job.pre_backup_job_id||job.lab_id!==loadOnScreen()||!loadEffective(job))return false;
 const jobs=loadState_().jobs||[],backup=jobs.find(j=>j.id===job.pre_backup_job_id);
 if(!backup||!['succeeded','partial'].includes(backup.status))return false;
 const lab=loadLab(job.lab_id),ctx=loadCtx(lab),source={type:'backup',backup_job_id:job.pre_backup_job_id},name=loadName(source,ctx,lab);
 // The undo of an undo of X loads X again; its name never nests (review U3).
 const inner=job.source||{},innerBackup=inner.type==='backup'?jobs.find(j=>j.id===inner.backup_job_id):null;
 const again=!!innerBackup&&innerBackup.source==='restore-pre'&&(loadState_().restore_jobs||[]).some(j=>j.id===innerBackup.progress_id);
 const changed=(job.targets||[]).filter(t=>LOAD_REPLACED.includes(t.status)||t.status==='uncertain'||t.stage==='uncertain'||(t.status==='interrupted'&&!!t.timeline&&t.timeline.settled==null)).length;
 return loadChoose(job.lab_id,source,name,{headline:again?`Load ${name} again?`:`Undo loading ${loadName(inner,ctx,lab)}?`,undo:{changed}});
}
// Try … again: the devices the load did not change, from the same source (the same commit, the same repository), through a new preflight
// that asks about them only and a confirmation that lists them only.
function loadRetry(job){
 if(!job||job.lab_id!==loadOnScreen()||loadJobActive(job))return false;
 const nodes=loadRetryNodes(job).map(t=>String(t.name));if(!nodes.length)return false;
 const s=job.source||{},lab=loadLab(job.lab_id);
 const source=s.type==='backup'?{type:'backup',backup_job_id:s.backup_job_id}:s.type==='git'?{type:'git',commit:s.commit,path:s.path,repository:s.repository}:{type:'folder',path:s.path,commit:s.commit,repository:s.repository};
 return loadChoose(job.lab_id,source,loadName(s,loadCtx(lab),lab),{nodes});
}
// Follows a load every 1.5 s while it is active (as restoreStartWatch does) and re-renders the chip panel; the chip itself follows the 4 s poll.
function loadWatch(job){
 if(!job||!job.id||loadWatching===job.id)return;
 loadStopWatch();loadWatching=job.id;if(loadPaused===job.id)loadPaused='';loadSeenActive.add(job.id);
 const id=job.id,poll=async()=>{
  if(loadWatching!==id)return;
  let value;
  try{value=await (await api('/restore/jobs/'+encodeURIComponent(id))).json();}
  catch{if(loadWatching!==id)return;loadStopWatch();loadPaused=id;loadRepaint();return;}
  if(loadWatching!==id||!value)return;
  loadJobs.set(id,value);
  if(loadJobActive(value)){loadWatchTimer=setTimeout(poll,1500);loadRepaint();return;}
  loadStopWatch();loadFinished(value);
  if(typeof refresh==='function'){try{await refresh();}catch{/* the 4 s poll catches up */}}
  loadRepaint();
 };
 loadWatchTimer=setTimeout(poll,1500);
}
function loadStopWatch(){clearTimeout(loadWatchTimer);loadWatchTimer=null;loadWatching=null;}
function loadRepaint(){if(typeof renderSaveHeader==='function')renderSaveHeader();}
// The toast, once per job, only for a load that succeeded (review O5).
function loadToast(job){
 if(!job||!job.id||loadToasted.has(job.id)||job.status!=='succeeded'||job.lab_id!==loadOnScreen())return false;
 loadToasted.add(job.id);
 const lab=loadLab(job.lab_id),m=(job.targets||[]).length;
 if(typeof notify==='function')notify(`${loadCap(loadName(job.source,loadCtx(lab),lab))} loaded on ${loadDevices(m)}.`);
 return true;
}
function loadFinished(job){
 loadSeenActive.delete(job.id);loadToast(job);
 if(loadEffective(job)||job.lab_id!==loadOnScreen())return;
 const chip=loadEl('save-panel');if(!chip||chip.hidden)return;
 if(typeof document!=='undefined'&&document&&typeof document.querySelector==='function'&&document.querySelector('dialog[open]'))return;
 const active=typeof document!=='undefined'&&document?document.activeElement:null,focus=!!active&&typeof chip.contains==='function'&&chip.contains(active);
 loadPending={kind:'result',labId:job.lab_id,jobId:job.id};
 if(!loadOpenPanel({focus}))loadPending=null;
}
// Called on every render (the 4 s poll): drops a review of a lab no longer on screen, toasts a load this page saw running that has now
// succeeded, and switches the red Load's disabled state. Nothing here fetches.
function loadRender(){
 const id=loadOnScreen();
 if(loadReview&&loadReview.labId!==id){const held=loadReview.drawer;loadReview=null;if(held&&typeof saveDrawerClose==='function')saveDrawerClose();}
 for(const job of loadState_().restore_jobs||[]){
  if(loadJobActive(job)){loadSeenActive.add(job.id);continue;}
  if(loadSeenActive.has(job.id)){loadSeenActive.delete(job.id);loadToast(loadFresh(job));}
 }
 // A lab that stopped while a list or a confirmation was on screen: nothing can be loaded onto it any more, and the panel says
 // so with Start lab instead of keeping a red Load that the manager would refuse (B06).
 const shown=id&&loadView.labId===id?loadLab(id):null;
 if(shown&&loadPanelOpen()&&['review','list','reading'].includes(loadView.kind)&&!(loadReview&&loadReview.sending)&&loadLabStopped(shown)){
  const held=loadReview&&loadReview.drawer;loadReview=null;if(held&&typeof saveDrawerClose==='function')saveDrawerClose();
  loadView={kind:'notrunning',labId:id};loadPaint(false);return;
 }
 if(loadView.kind==='review'&&loadPanelOpen()){
  // A wait repaints when the manager is free (Try again becomes available); a confirmation only switches its red button.
  if(loadReview&&loadReview.phase==='refused'&&loadReview.wait)loadPaint(false);else loadSyncRun();
 }
}

// ---- one dispatcher for every control of this file ----------------------------------------------------------------------------------
function loadViewMarkup(){
 const v=loadView,lab=loadLab(v.labId);
 if(!lab)return '';
 if(v.kind==='review'&&loadReview&&loadReview.labId===v.labId){
  const r=loadReview;
  return r.phase==='checking'?loadCheckingMarkup(r):r.phase==='refused'?loadRefusedMarkup(r):loadConfirmMarkup(r,lab);
 }
 if(v.kind==='different'&&loadReview){const d=loadDifferentMarkup(loadReview);return `<p class="save-state" tabindex="-1" data-panel-focus>${esc(d.title)}</p><p class="save-note">${esc(d.meta)}</p>${d.html}`;}
 if(v.kind==='notrunning')return loadNotRunningMarkup();
 if(v.kind==='nothing')return '<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot none" aria-hidden="true"></span>There is nothing to load yet</p><p class="save-sub">No repository is connected to this lab VM. Save this lab once to connect one, or ask your instructor for the course repository’s address.</p><div class="save-row"><button type="button" class="button primary" id="load-save" data-load-action="save">Save…</button></div>';
 if(v.kind==='error')return `<h2 class="sr-only" tabindex="-1" data-panel-focus>Load a saved state</h2><p class="save-sub">The saved states could not be read from the lab VM.</p><p class="form-error" role="alert">${esc(v.message||'')}</p><div class="save-row"><button type="button" class="button ghost small" id="load-reload" data-load-action="reload">Try again</button></div>${loadFootMarkup()}`;
 if(v.kind==='reading')return '<h2 class="sr-only" tabindex="-1" data-panel-focus>Load a saved state</h2><p class="save-sub">Reading the saved states…</p>'+loadFootMarkup();
 if(v.kind==='list')return loadListMarkup(loadListModel(lab,loadStates.get(lab.id)));
 if(v.kind==='result')return loadResultMarkup(loadFindJob(v.jobId));
 return '';
}
function loadDrawer(kind,options){if(typeof saveDrawerOpen==='function'){saveDrawerOpen(kind,{...options,opener:loadEl('load-button')});return true;}return false;}
async function loadAction(action,el){
 const r=loadReview,id=loadOnScreen(),lab=loadLab(id),job=el&&el.dataset&&el.dataset.loadJob?loadFindJob(el.dataset.loadJob):null;
 const repository=loadList&&loadList.labId===id?loadList.repository:'';
 switch(action){
  case 'run':return loadSubmit();
  case 'diff-run':return loadSubmit();
  case 'diff':return loadOpenDifferent();
  case 'diff-back':return loadDifferentBack();
  case 'cancel':case 'back':loadReview=null;return loadShowList(id,true);
  case 'again':return r&&r.labId===id?loadChoose(...r.args):loadShowList(id,true);
  case 'reload':loadStates.delete(id);return loadShowList(id,true);
  case 'all':return loadDrawer('versions',{repository});
  case 'browse':return loadDrawer('chooser',{mode:'browse',repository});
  // The state's own files, by the exact snapshot folder this review was started with (the preflight's `folder` is a display name without `latest`).
  case 'topology':{if(!r||!r.review)return;const s=r.review.source||{};return loadDrawer('files',{repository:r.source.repository,row:{path:String(r.source.path||s.path||''),commit:String(s.commit||r.source.commit||'')},name:r.name,file:'topology'});}
  case 'start':loadClosePanel();if(typeof startLab==='function')startLab();return;
  case 'save':loadClosePanel();if(typeof saveOpenPanel==='function')saveOpenPanel('status');return;
  case 'credentials':loadClosePanel();if(typeof showTab==='function')showTab('credentials');return;
  case 'refresh':{loadClosePanel();const b=loadEl('vm-refresh');if(b&&typeof b.click==='function')b.click();return;}
  case 'undo':return loadUndo(job);
  case 'retry':return loadRetry(job);
  case 'details':if(!job)return;if(typeof closeMenus==='function')closeMenus();if(typeof restoreShowJob==='function')return restoreShowJob(job.id,undefined,loadEl('save-chip'));return;
  case 'resume':if(job){loadPaused='';loadWatch(job);loadRepaint();}return;
 }
 return lab?null:undefined;
}
function loadClick(event){
 const target=event&&event.target&&typeof event.target.closest==='function'?event.target:null;if(!target)return;
 const control=target.closest('[data-load-action], [data-load-row], [data-load-view]');if(!control||control.disabled)return;
 const data=control.dataset||{};
 if(data.loadAction)return loadAction(data.loadAction,control);
 const items=loadList&&loadList.labId===loadOnScreen()?loadList.items:[];
 if(data.loadRow!=null){const item=items[Number(data.loadRow)];if(item)return loadChoose(loadOnScreen(),item.source,item.name);return;}
 if(data.loadView!=null){const item=items[Number(data.loadView)];if(item)loadDrawer('files',{repository:loadList.repository,row:{path:String(item.row.path||''),commit:String(item.row.commit||'')},name:item.name});}
}
function loadChange(event){
 const target=event&&event.target,r=loadReview;if(!target||!r||r.phase!=='confirm')return;
 if(target.name==='load-node'){if(target.checked)r.chosen.add(String(target.value));else r.chosen.delete(String(target.value));loadSyncRun();return;}
 if(target.id==='load-minutes')r.minutes=loadMinutes(target.value);
}
// Wiring: element listeners only. #load-panel is this file's; in #save-panel and #save-drawer only clicks on this file's own buttons
// ([data-load-action]) are taken, and the drawer's close drops a review it held.
if(typeof $==='function'){
 const panel=$('load-panel'),chip=$('save-panel'),drawer=$('save-drawer'),on=el=>!!el&&typeof el.addEventListener==='function';
 if(on(panel)){panel.addEventListener('panelopen',loadPanelOpened);panel.addEventListener('panelclose',loadPanelClosed);panel.addEventListener('click',loadClick);panel.addEventListener('change',loadChange);panel.addEventListener('input',loadChange);}
 const own=event=>{const t=event&&event.target&&typeof event.target.closest==='function'?event.target.closest('[data-load-action]'):null;if(t)loadClick(event);};
 if(on(chip))chip.addEventListener('click',own);
 if(on(drawer)){drawer.addEventListener('click',own);drawer.addEventListener('close',loadDrawerClosed);}
}
