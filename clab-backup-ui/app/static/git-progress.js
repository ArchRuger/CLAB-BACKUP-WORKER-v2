'use strict';
// Git credentials stay with the registered VM account. The browser sends only
// registered binding IDs and structured actions; it never assembles shell commands.
// The header's chip and its panels read in the student's words (saveChipState in status.js); the backend's own status
// words stay available under Details of the save window and in gitStateLabels.
const gitActiveStates=new Set(['queued','capturing','exporting','pushing']);
const gitPendingStates=new Set(['committed','push_pending','export_pending','review_pending','interrupted']);
const gitStateLabels={queued:'Waiting to save',capturing:'Capturing configurations',exporting:'Saving to repository',pushing:'Pushing to remote',synced:'Saved to Git',committed:'Saved on VM · not pushed',unchanged:'No configuration changes',push_pending:'Saved on VM · push pending',export_pending:'Snapshot saved · export pending',review_pending:'Saved on VM · review before pushing',interrupted:'Save interrupted · snapshot retained',capture_incomplete:'Capture incomplete',failed:'Save needs attention',dismissed:'Snapshot kept locally'};
const gitSaveSentences={queued:'Waiting to start…',capturing:'Reading device configurations…',exporting:'Saving to the repository…',pushing:'Uploading…',synced:'Saved and uploaded',unchanged:'Saved — nothing had changed',committed:'Saved on this VM — not uploaded',review_pending:'Saved on this VM — not uploaded yet',push_pending:'Saved on this VM — upload needs attention',export_pending:'Configurations read — saving to the repository needs attention',interrupted:'Save interrupted — retry it',capture_incomplete:'Save failed — a device could not be read',failed:'Save failed',dismissed:'Kept on this VM only'};
const gitContexts=new Map(),gitLoads=new Map();
let gitWatch=null,gitWatchTimer=null,gitDialogJob='',gitSubmitting=false,gitSubmittingLab='';
function gitLabel(job){return gitStateLabels[job?.status]||job?.status||'Not saved yet';}
function gitJobTime(job){return job?.created||job?.finished||'';}
function gitWhen(value){if(!value)return '';const relative=typeof relativeTime==='function'?relativeTime(value):'';return relative||utcDisplay(value);}
function gitLabJobs(id,context=gitContexts.get(id)){
 const jobs=new Map();for(const job of [...(context?.jobs||[]),...(state.git_jobs||[])])if(!job.lab_id||job.lab_id===id)jobs.set(job.id,{...jobs.get(job.id),...job});
 return [...jobs.values()].sort((a,b)=>gitJobTime(b).localeCompare(gitJobTime(a)));
}
function gitRepository(binding){return binding?.repository||{};}
function gitRepoName(repo){return String(repo?.path||'').split('/').filter(Boolean).pop()||repo?.label||'Repository';}
// "Course-Labs › bgp" in words.
function gitFolderWords(binding){const repo=gitRepository(binding),name=gitRepoName(repo)||binding?.binding_id||'the repository';return repo.prefix?name+' › '+repo.prefix.replace(/\/$/,''):name+' (top level)';}
// The exact repository-relative path of a snapshot name ("latest", "baseline", "checkpoints/<name>")
// inside a lab folder: the lab folder's prefix joined with it, or the bare name at the repository root.
// Every exact snapshot path the browser sends carries one leading slash on the wire ('/' = the
// repository root itself); the manager treats a leading slash as "exact repository path".
function gitSnapshotPath(binding,name){const prefix=(gitRepository(binding).prefix||'').replace(/\/$/,'');return '/'+(prefix?prefix+'/'+name:name);}
// The pure sentence for a lab folder whose own name looks like a saved state a save writes
// (latest, baseline, checkpoints/<name>): a legacy destination that nests a second one inside it.
// '' when the prefix is not shaped like that.
function gitLegacyDestinationNotice(binding){
 const prefix=(gitRepository(binding).prefix||'').replace(/\/$/,'');
 if(!prefix)return '';
 const parts=prefix.split('/'),last=parts[parts.length-1],last2=parts.length>1?parts[parts.length-2]:'';
 const reservedLen=last2==='checkpoints'?2:['latest','baseline','checkpoints'].includes(last)?1:0;
 if(!reservedLen)return '';
 const parent=parts.slice(0,-reservedLen).join('/'),parentWords=parent||'the top of the repository';
 return `This lab saves to ${prefix}, a folder named like a saved state, so its saves go to ${prefix}/latest. To save into ${parentWords}/latest again, open Change folder…, pick ${parentWords} and choose Save here without bringing the saved files along.`;
}
function gitTargetPath(job){if(job.target==='move')return 'latest';return job.target==='checkpoint'?'checkpoints/'+job.checkpoint:job.target||'latest';}
function gitTargetLabel(job){if(job.target==='move')return 'Folder move → '+((job.snapshot_path||'').replace(/\/?latest$/,'')||'repository root');return job.target==='checkpoint'?'checkpoints/'+(job.checkpoint||''):job.target||'latest';}
// A folder move reads as moved only once it committed (synced, or kept on this VM); one that stopped before its
// commit, or lost its answer, is retried, never worded as moved. Its folder: where the commit put the files, else
// the folder it is moving to.
function gitMoveDone(job){return ['synced','committed','unchanged'].includes(job.status);}
function gitMoveFolder(job){const path=job.snapshot_path?job.snapshot_path.replace(/\/?latest$/,''):String(job.destination?.path||'');return path&&path!=='(repository root)'?path:'the repository root';}
// Student sentence, pill and "Saved as" for one save job.
function gitSaveSentence(job){
 if(!job)return '';const s=job.status,active=gitActiveStates.has(s);
 if(job.target==='update')return active?'Updating from the repository…':'Repository updated';
 if(job.target==='move'){if(active)return 'Moving saved files…';if(gitMoveDone(job))return 'Moved to folder '+gitMoveFolder(job);if(s==='push_pending')return 'Moved to folder '+gitMoveFolder(job)+' on this VM — upload needs attention';if(s==='dismissed')return gitSaveSentences.dismissed;return 'Moving the saved files did not finish — retry it';}
 if(!active&&['synced','committed','review_pending','unchanged'].includes(s)){if(job.target==='checkpoint')return `Checkpoint '${job.checkpoint||''}' saved`;if(job.target==='baseline')return 'Starting point set';}
 return gitSaveSentences[s]||gitLabel(job);
}
function gitSavePill(job){const s=job?.status;if(gitActiveStates.has(s))return 'busy';if(['synced','unchanged'].includes(s))return 'ok';if(['failed','capture_incomplete'].includes(s))return 'danger';if(s==='dismissed'||!s)return 'neutral';return 'warn';}
function gitBadgeClass(job){const s=job?.status;return gitActiveStates.has(s)?'running':['synced','unchanged'].includes(s)?'good':['failed','capture_incomplete'].includes(s)?'bad':'warn';}
function gitSavedAs(job){if(job.target==='update')return 'Repository update';if(job.target==='move')return (gitMoveDone(job)||job.status==='push_pending'?'Moved to ':'Folder move to ')+gitMoveFolder(job);if(job.target==='checkpoint')return `Checkpoint '${job.checkpoint||''}'`;if(job.target==='baseline')return 'Starting point';return 'Latest';}
function gitCompleteBackups(jobs,id,names){
 const required=new Set(names||[]);
 return jobs.filter(job=>required.size&&job.lab_id===id&&job.operation==='backup'&&['succeeded','partial'].includes(job.status)&&job.nodes?.length===required.size&&new Set(job.nodes.map(node=>node.name)).size===required.size&&job.nodes.every(node=>node.status==='succeeded'&&required.has(node.name)));
}
function gitSavePayload(values,requestId){return {request_id:requestId,target:values.target||'latest',checkpoint:values.checkpoint||'',push:values.push!==false,note:values.note||'',backup_job_id:values.backup_job_id||'',replace_baseline:values.replace_baseline===true,expected_baseline:values.expected_baseline||'',allow_removed:values.allow_removed===true};}
function gitRequestId(){const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return Array.from(bytes,n=>n.toString(16).padStart(2,'0')).join('');}
// E2: every navigation out of a <dialog> to another destination (a tab, or a new dialog) closes
// every other open dialog layer first, so nothing stale is left open underneath. `keep` is the
// dialog id that should stay open (the one just opened as the destination), if any.
function closeDialogsExcept(keep=''){
 if(typeof document==='undefined'||typeof document.querySelectorAll!=='function')return;
 for(const dialog of document.querySelectorAll('dialog[open]'))if(dialog.id!==keep&&typeof dialog.close==='function')dialog.close();
}
// Moves focus to a freshly opened dialog's own heading (never the default close button), or its
// first control when it has no heading; the destination of a navigation should be where focus lands.
function gitFocusDialog(dialog){
 if(!dialog||typeof dialog.querySelector!=='function')return;
 const heading=dialog.querySelector('h2');
 if(heading){heading.tabIndex=-1;if(typeof heading.focus==='function')heading.focus();return;}
 const control=dialog.querySelector('button, [href], input, select, textarea');
 if(control&&typeof control.focus==='function')control.focus();
}
// E3: `<repository> · <branch> · <path>` for a save's frozen destination, with its current state as
// a trailing pill. The four phrases are read straight off the job's own status/pushed/message — no
// new backend state.
function gitDestinationState(job,remote){
 if(gitActiveStates.has(job.status))return 'saving…';
 if(job.pushed||job.status==='synced')return /verified/i.test(job.message||'')?'verified on remote':'uploaded to '+(remote||'the remote');
 if(job.status==='review_pending')return 'not uploaded yet';
 if(job.status==='unchanged')return job.pushed?'uploaded to '+(remote||'the remote'):'saved on this VM';
 return 'saved on this VM';
}
function gitDestinationPill(job){
 if(gitActiveStates.has(job.status))return 'busy';
 if(job.pushed||job.status==='synced')return /verified/i.test(job.message||'')?'ok':'info';
 if(job.status==='review_pending')return 'warn';
 return 'neutral';
}
function gitDestinationMarkup(destination,job){
 if(!destination)return '';
 const state=job?gitDestinationState(job,destination.remote):'',pillClass=job?gitDestinationPill(job):'neutral';
 return `<p class="git-destination-line"><span>Saving to</span><code>${esc(destination.repository)}</code><span aria-hidden="true">›</span><code>${esc(destination.branch)}</code><span aria-hidden="true">›</span><code>${esc(destination.path)}</code>${state?` <span class="pill ${esc(pillClass)}">${esc(state)}</span>`:''}</p>`;
}
function gitJobMarkup(job){
 if(!job)return '<p>No saves yet. Save saves every device chosen under Save settings.</p>';
 const changed=Array.isArray(job.changed_files)?job.changed_files.length:job.changed_files;
 const explain=gitActiveStates.has(job.status)||gitPendingStates.has(job.status)||['failed','capture_incomplete'].includes(job.status);
 return `<div class="git-job-summary"><span class="badge ${gitBadgeClass(job)}">${esc(gitSaveSentence(job))}</span>${gitDestinationMarkup(job.destination,job)}<p>${esc(explain?job.message||'':'')}</p><dl class="health-grid">${job.destination?`<dt>Destination</dt><dd>${esc([job.destination.repository,job.destination.branch,job.destination.path].filter(Boolean).join(' · '))}</dd>`:''}<dt>Saved as</dt><dd>${esc(gitSavedAs(job))}</dd><dt>Started</dt><dd>${esc(gitWhen(job.created))}</dd>${job.note?`<dt>Label</dt><dd>${esc(job.note)}</dd>`:''}</dl><details><summary>Details</summary><dl class="health-grid"><dt>Status</dt><dd>${esc(gitLabel(job))}</dd><dt>Message</dt><dd>${esc(job.message||'')}</dd><dt>Saved target</dt><dd>${esc(gitTargetLabel(job))}</dd><dt>Started (UTC)</dt><dd>${esc(utcDisplay(job.created))}</dd>${job.commit?`<dt>Commit</dt><dd class="mono">${esc(job.commit)}</dd>`:''}${job.destination?.checkout?`<dt>Checkout</dt><dd class="mono">${esc(job.destination.checkout)}</dd>`:''}${changed!==undefined?`<dt>Files changed</dt><dd>${esc(changed)}</dd>`:''}${job.id?`<dt>Job id</dt><dd class="mono">${esc(job.id)}</dd>`:''}</dl></details></div>`;
}
// Adapter over diff-view.js's diffFileMarkup for the compare route's file list (each file already
// carries `diff`, `label` and, when the manager folded a suffix rename, `renamed_from`).
function gitFilesDiffMarkup(files,oldLabel='Before',newLabel='After'){
 if(!files?.length)return '<p>No differences — this version matches your latest save.</p>';
 return files.map(file=>diffFileMarkup(file.name,file.status,file.diff,{oldLabel,newLabel,renamedFrom:file.renamed_from})).join('');
}
async function gitLoadContext(id,force=false){
 if(gitLoads.has(id))return gitLoads.get(id);
 if(!force&&gitContexts.has(id))return gitContexts.get(id);
 const pending=(async()=>{const value=await(await api('/labs/'+encodeURIComponent(id)+'/git')).json();gitContexts.set(id,value);return value;})();
 gitLoads.set(id,pending);try{return await pending;}finally{gitLoads.delete(id);}
}
// A save already running when the page loads (or started elsewhere) is followed to its end, once per job, so its result reaches the
// header (saveFinished: the panel on the result, the Nothing changed and Uploaded toasts). A watch on another lab's save ends with the
// lab change, except the upload this page sent: it may go through the save of another lab of the repository (the one at the checkout's
// newest commit), and its end is this page's toast and chip. Called by renderSaveHeader on every render; `lab` is the lab on screen.
function gitResumeWatch(lab){
 if(!lab){clearTimeout(gitWatchTimer);gitWatch=null;return;}
 if(gitWatch&&gitWatch.lab_id!==lab.id&&!gitWatch.keep&&!$('git-job-dialog')?.open){clearTimeout(gitWatchTimer);gitWatch=null;}
 const active=(state.git_jobs||[]).find(job=>job.lab_id===lab.id&&gitActiveStates.has(job.status));
 if(active&&!gitWatch)gitStartWatch(active,{quiet:true});
}
function gitLabName(id){return (state.labs||[]).find(lab=>lab.id===id)?.name||'This lab';}
// Use a different repository…: the repositories of the VM this lab does not save to, and one by its address. Either choice opens
// the folder chooser for that repository (the place route, with its questions as buttons); nothing changes before Save here.
async function gitSwitchRepository(id){
 const places=await(await api('/labs/'+encodeURIComponent(id)+'/git/places')).json();
 const repositories=(places.repositories||[]).filter(value=>!value.current);
 const chooser=options=>{if(typeof saveDrawerOpen!=='function')throw new Error('This part of the page did not load. Reload the page and try again.');saveDrawerOpen('chooser',{mode:'location',opener:$('save-chip'),...options});};
 const dialog=opDialog('git-switch-dialog','Use a different repository',`<p>Pick another repository already available on this lab VM, or connect a new one by its GitHub address. Nothing already saved is deleted.</p>${repositories.length?`<label for="git-switch-id">Repositories on this VM</label><select id="git-switch-id">${repositories.map(value=>`<option value="${esc(value.id)}">${esc(value.name||gitRepoName(value))}</option>`).join('')}</select><div class="dialog-actions"><button class="button secondary" id="git-switch-choose">Choose this repository</button></div>`:'<p class="form-help">No other repository is set up on this VM yet.</p>'}<h3>Connect a repository by URL</h3><p class="form-help">For a repository that is not on this VM yet. You need its HTTPS URL (GitHub › Code › HTTPS); the VM’s existing GitHub login is used.</p><div class="dialog-actions"><button class="button primary" id="git-switch-connect">Connect by URL…</button></div>`);
 $('git-switch-choose')?.addEventListener('click',()=>opTask(dialog,async()=>{const repository=$('git-switch-id').value;dialog.close();chooser({repository});}));
 $('git-switch-connect').onclick=()=>opTask(dialog,async()=>{dialog.close();chooser({address:true});});
}
// A request whose answer was lost is retried with the same ID (the job ID), so the server returns
// that save instead of capturing twice. It is replayed only shortly after it was sent and only while
// the page does not already know that save as finished: otherwise a later save with the same label
// would get the old job back and report "Saved" without reading any device (audit L-8).
const GIT_REQUEST_REUSE_MS=10*60*1000;
function gitNow(){return Date.now();}
function gitReusableRequest(previous,request){
 if(!previous||typeof previous!=='object'||!previous.request||!(gitNow()-Number(previous.sent)<=GIT_REQUEST_REUSE_MS))return null;
 if(JSON.stringify({...previous.request,request_id:''})!==JSON.stringify({...request,request_id:''}))return null;
 const known=[...(state.git_jobs||[]),...[...gitContexts.values()].flatMap(context=>context?.jobs||[])].find(job=>job.id===previous.request.request_id);
 return known&&!gitActiveStates.has(known.status)?null:previous.request;
}
// options.quiet: no job dialog. With the header chip (save-header.js) the chip and its panel carry the phases and the result;
// without it a toast does, and the dialog opens on its own only when the save ends needing attention. Every step after
// gitSubmitting is set runs inside the try, so nothing (blocked site data included: every storage call may throw) leaves it stuck.
// A refusal of the request itself is handed to the header (saveRefused), which shows it in the chip panel; the error is still thrown,
// marked `saveShown`, so a caller with its own error place can tell.
async function gitSubmitSave(id,values,requestId,options={}){
 if(gitSubmitting)return;
 gitSubmitting=true;gitSubmittingLab=id;
 const header=()=>{if(typeof renderSaveHeader==='function')renderSaveHeader();};
 let sent=false;
 try{
  header();
  const storageKey='git-save-request:'+id;
  let request=gitSavePayload(values,requestId||gitRequestId());
  if(!requestId){try{request=gitReusableRequest(JSON.parse(sessionStorage.getItem(storageKey)||'null'),request)||request;sessionStorage.setItem(storageKey,JSON.stringify({request,sent:gitNow()}));}catch{}}
  sent=true;
  const job=await json('/labs/'+encodeURIComponent(id)+'/git/save','POST',request);
  sent=false;
  if(!requestId){try{sessionStorage.removeItem(storageKey);}catch{}}
  gitRememberJob(job);
  if(typeof saveRefused==='function')saveRefused(id,null,values);
  if(options.quiet){if(typeof saveFinished!=='function')notify(values.target==='checkpoint'?'Saving checkpoint…':values.target==='baseline'?'Setting the starting point…':'Saving…');gitStartWatch(job,{quiet:true});}
  else await gitShowJob(job.id,job);
  await refresh();return job;
 }catch(error){
  if(sent&&error&&typeof saveRefused==='function'&&saveRefused(id,error,values))error.saveShown=true;
  throw error;
 }finally{gitSubmitting=false;gitSubmittingLab='';header();}
}
// Save (owner decision D2): no label is asked. A lab with a save location is saved at once with an empty note (the manager names
// the save) and the chip panel shows the phases; a lab without one gets the first-save view of the chip panel. A refusal the
// chip panel shows is not thrown again.
async function gitSaveProgress(id=activeId){
 if(!id||typeof id!=='string')id=activeId;if(!id)return;
 const lab=(state.labs||[]).find(item=>item.id===id),bound=lab?!!lab.git_binding:!!(await gitLoadContext(id)).binding;
 const panel=typeof saveOpenPanel==='function'&&id===activeId;
 if(panel)saveOpenPanel('status',{focus:true});
 if(!bound){if(!panel)throw new Error('Open this lab and choose Save: its first save asks where to save.');return;}
 try{await gitSubmitSave(id,{target:'latest',push:true,note:'',allow_removed:true},undefined,{quiet:true});}
 catch(error){if(!error||!error.saveShown)throw error;}
}
function gitCheckpointName(value){return String(value||'').replace(/\s+/g,'-').replace(/[^A-Za-z0-9_-]/g,'').replace(/^[_-]+/,'');}
// Choose a backup as starting point… (All versions › Starting point): one of the lab's complete captures becomes the starting
// point; no device is read or changed. Replacing an existing starting point needs its tick. The save is named by the manager and
// waits for upload like every save. (The lab's own saves offer Use as starting point… in their row instead.)
async function gitSaveOptions(target,id=activeId){
 const context=await gitLoadContext(id,true);
 if(!context.binding){if(typeof saveOpenPanel==='function')saveOpenPanel('status',{focus:true});return;}
 const backups=gitCompleteBackups(state.jobs||[],id,context.binding.node_names),baselineRevision=context.repository_status?.baseline_revision||'',total=(context.binding.node_names||[]).length;
 const dialog=opDialog('git-save-options','Choose a backup as starting point',`<p class="op-path">Saving to ${esc(gitFolderWords(context.binding))}</p>
 <p>The starting point is the reference state of this lab (for example the instructor’s starting state). Pick one of the complete backups below — no device is read or changed.</p><label for="git-baseline-job">Use this backup</label><select id="git-baseline-job" required><option value="">Choose a backup</option>${backups.map(job=>`<option value="${esc(job.id)}" title="${esc(job.id)}">${esc(gitWhen(job.created))} · ${job.nodes.length} devices</option>`).join('')}</select>${backups.length?'':`<p class="op-notice">No complete backup includes all ${total} devices yet. Save first, then choose Use as starting point… on that save.</p>`}<details class="caption"><summary>Details</summary><p>Setting the starting point does not check whether it can be loaded onto a running lab.</p></details>${baselineRevision?'<label class="checkbox-label"><input type="checkbox" id="git-replace-baseline"> Replace the current starting point with this one (the previous one stays in the history)</label>':''}
 <div class="dialog-actions"><button class="button secondary" id="git-save-cancel">Cancel</button><button class="button primary" id="git-save-confirm" ${backups.length?'':'disabled'}>Use as starting point</button></div>`);
 const requestId=gitRequestId();$('git-save-cancel').onclick=()=>dialog.close();
 $('git-save-confirm').onclick=()=>opTask(dialog,async()=>{
  const backup=$('git-baseline-job')?.value||'';
  if(!backup)throw new Error('Choose a backup.');
  if(baselineRevision&&!$('git-replace-baseline').checked)throw new Error('Tick the box to replace the current starting point.');
  const values={target:'baseline',checkpoint:'',push:true,note:'',backup_job_id:backup,replace_baseline:!!baselineRevision,expected_baseline:baselineRevision,allow_removed:true};
  await gitSubmitSave(id,values,requestId,{quiet:true});dialog.close();
 });
}
function gitRememberJob(job){
 const context=gitContexts.get(job.lab_id);if(context)context.jobs=[job,...(context.jobs||[]).filter(item=>item.id!==job.id)];
 state.git_jobs=[job,...(state.git_jobs||[]).filter(item=>item.id!==job.id)];
}
// A design export (job.kind==='design', created by network-design.js's Export plan to Git…) is a Git
// save like any other, but is never worded as a save of the lab: it carries no captured device backup,
// its checkpoint holds the plan and generated files, and it is never a restore source.
function gitJobTitle(job){
 const design=job.kind==='design';
 if(gitActiveStates.has(job.status))return design?'Design export in progress':'Saving';
 if(['synced','unchanged','committed','review_pending'].includes(job.status))return design?'Design export saved':'Saved';
 if(['failed','capture_incomplete'].includes(job.status))return design?'Design export failed':'Save failed';
 if(job.target==='update')return 'Repository update';
 return design?'Design export needs attention':'Save needs attention';
}
async function gitShowJob(id,known){
 const job=known||await(await api('/git/jobs/'+encodeURIComponent(id))).json();gitRememberJob(job);gitDialogJob=id;
 closeDialogsExcept();
 const dialog=opDialog('git-job-dialog',gitJobTitle(job),'<div id="git-job-detail"></div><div class="actions" id="git-job-actions"></div>');
 dialog.onclose=()=>{gitDialogJob='';};gitRenderJob(job);gitFocusDialog(dialog);
 if(gitActiveStates.has(job.status))gitStartWatch(job);
}
function gitRenderJob(job){
 if(gitDialogJob!==job.id||!$('git-job-dialog')?.open)return;
 const heading=typeof $('git-job-dialog').querySelector==='function'?$('git-job-dialog').querySelector('h2'):null;if(heading)heading.textContent=gitJobTitle(job);
 $('git-job-detail').innerHTML=gitJobMarkup(job);
 // A move an older release marked failed is retryable as well (its journal on the VM makes the retry safe).
 const pending=gitPendingStates.has(job.status)||(job.target==='move'&&job.status==='failed'),active=gitActiveStates.has(job.status),hasCommit=!!job.commit;
 // A save with a commit is uploaded only from What changed (See changes: the review, then Upload). One that stopped before its
 // commit is tried again on the VM and then waits for upload like any save: this window never asks for an upload itself.
 $('git-job-actions').innerHTML=`${job.backup_job_id?'<button class="button secondary" data-git-job-action="backup">View configuration backup</button>':''}${hasCommit?`<button class="button ${pending?'primary':'secondary'}" data-git-job-action="review">${pending?'See changes and upload…':'See changes'}</button>`:''}${pending?`${!hasCommit?`<button class="button primary" data-git-job-action="local">${job.target==='move'?'Try the move again':'Try again'}</button>`:''}<button class="button secondary" data-git-job-action="dismiss">Keep snapshot only</button>`:''}${active?'<p class="form-help" role="status">You can close this window. The save continues in the background, and the save chip in the header shows its result.</p>':''}`;
 for(const button of $('git-job-actions').querySelectorAll('[data-git-job-action]'))button.onclick=()=>opTask($('git-job-dialog'),async()=>{
  const action=button.dataset.gitJobAction;
  if(action==='backup'){closeDialogsExcept();selectLab(job.lab_id);showTab('backups');const capture=[...document.querySelectorAll('.job')].find(item=>item.dataset.job===job.backup_job_id);if(capture){capture.open=true;capture.scrollIntoView({block:'center',behavior:'smooth'});const summary=capture.querySelector('summary');if(summary&&typeof summary.focus==='function')summary.focus();}return;}
  if(action==='review'){await gitReviewJob(job);return;}
  if(action==='dismiss'){await gitDismissJob(job);return;}
  const result=await json('/git/jobs/'+encodeURIComponent(job.id)+'/retry','POST',{push:false});gitRememberJob(result);await gitShowJob(result.id,result);await refresh();
 });
}
// The review before an upload is mandatory: a save with a commit is uploaded only from the review
// window, by the student's own choice, and the manager refuses an upload that does not say so. A save
// whose review already happened (its upload failed afterwards) and a folder move upload directly; a move the manager
// kept on the VM because its upload would send saves kept with Keep snapshot only along (review_before_push) is reviewed.
function gitNeedsReview(job){return !!job&&!!job.commit&&!job.reviewed&&!job.pushed&&(job.target!=='move'||job.review_before_push===true);}

// The review of a save and of the upload it would be part of (DESIGN.md 3.4, 7.3). One cache for the page: job id → the answer of
// POST …/git/compare, kept until the set of waiting saves in /api/state changes (a save made anywhere changes what an upload carries).
const gitReviews={key:'',answers:new Map(),loads:new Map()};
function gitWaitingKey(){return (state.git_jobs||[]).filter(j=>j.commit&&!j.pushed).map(j=>j.id+':'+j.commit+':'+j.status).sort().join('|');}
function gitReviewsCurrent(){const key=gitWaitingKey();if(gitReviews.key!==key){gitReviews.key=key;gitReviews.answers.clear();gitReviews.loads.clear();}return key;}
// The answer the page holds for this save and the current set of waiting saves, or null: what a view renders and what Upload sends.
function gitReviewCached(job){gitReviewsCurrent();return (job&&gitReviews.answers.get(job.id))||null;}
// The floor of `also_sends`: a waiting save of the same checkout this page knows and the answer does not name is added, so the
// sentence never under-reports what an upload carries.
function gitReviewRows(job,rows){
 const list=(Array.isArray(rows)?rows:[]).filter(row=>row&&typeof row==='object'),checkout=job.destination?.checkout||'';
 if(!checkout||!job.commit||job.pushed)return list;
 const named=new Set(list.map(row=>row.job_id).filter(Boolean)),commits=new Set([job.commit]);
 for(const other of state.git_jobs||[]){
  if(other.id===job.id||!other.commit||other.pushed||named.has(other.id)||commits.has(other.commit)||!gitPendingStates.has(other.status)||(other.destination?.checkout||'')!==checkout)continue;
  commits.add(other.commit);list.push({job_id:other.id,lab:other.lab_name||gitLabName(other.lab_id),name:other.note||(other.target==='move'?'Folder move':'Unnamed save'),kind:other.kind||'',target:other.target||'latest'});
 }
 return list;
}
// What a save changed and what an upload of its repository would send: {files, summary, head, upload_job, also_sends}.
// options.fresh asks the VM again. An answer for a set of waiting saves that changed meanwhile is returned but not kept.
async function gitReviewData(job,options={}){
 const key=gitReviewsCurrent();
 if(!options.fresh&&gitReviews.answers.has(job.id))return gitReviews.answers.get(job.id);
 if(!options.fresh&&gitReviews.loads.has(job.id))return gitReviews.loads.get(job.id);
 const load=(async()=>{
  const result=await json('/labs/'+encodeURIComponent(job.lab_id)+'/git/compare','POST',{job_id:job.id});
  const review={files:result.files||[],summary:result.summary||job.summary||null,head:String(result.head||''),upload_job:result.upload_job||'',also_sends:gitReviewRows(job,result.also_sends)};
  if(gitReviewsCurrent()===key&&gitReviews.loads.get(job.id)===load)gitReviews.answers.set(job.id,review);
  return review;
 })();
 gitReviews.loads.set(job.id,load);
 try{return await load;}finally{if(gitReviews.loads.get(job.id)===load)gitReviews.loads.delete(job.id);}
}
// The review before an upload is mandatory. Without options.upload this opens the What changed drawer for the save (save-drawers.js).
// With options.upload===true it uploads what the review of this save showed: it
// posts to the retry route of the review's `upload_job` (the manager's save at the checkout's newest commit) with the `head` the
// person was shown, and refuses when the page holds no review of this save for the current set of waiting saves. On 409 (a save
// landed after the review) it fetches the review again and the views show it; nothing was uploaded. This function is the only
// place in the static scripts that sends the reviewed flag with an upload.
async function gitReviewJob(job,options={}){
 if(options.upload!==true){
  if(typeof saveDrawerOpen==='function'){closeDialogsExcept('save-drawer');saveDrawerOpen('changes',{job,opener:options.opener});return null;}
  throw new Error('This part of the page did not load. Reload the page and try again.');
 }
 const review=gitReviewCached(job);
 if(!review||!review.head||!review.upload_job)throw new Error('See what this upload sends before uploading.');
 try{
  const next=await json('/git/jobs/'+encodeURIComponent(review.upload_job)+'/retry','POST',{push:true,reviewed:true,head:review.head});
  gitRememberJob(next);gitStartWatch(next,{quiet:true,keep:true});await refresh();return next;
 }catch(error){
  if(error&&error.status===409){
   gitReviews.answers.clear();gitReviews.loads.clear();
   try{await gitReviewData(job,{fresh:true});}catch{}
   if(typeof renderSaveHeader==='function')renderSaveHeader();if(typeof saveDrawerRender==='function')saveDrawerRender();
  }
  throw error;
 }
}
function gitDoneToast(job){
 if(job.target==='checkpoint')return `Checkpoint '${job.checkpoint||''}' saved.`;
 if(job.target==='baseline')return 'Starting point set.';
 if(job.status==='synced')return 'Saved and uploaded.';
 if(job.status==='unchanged')return 'Nothing changed since your last save.';
 if(job.status==='committed')return 'Saved on this VM. Upload it when you are ready.';
 return gitSaveSentence(job)+'.';
}
function gitStartWatch(job,options={}){
 // A save already followed (the poll's own render follows an active save of the lab on screen) takes what this caller asks for:
 // its end still reaches the header (quiet) and it survives a render for another lab (keep). Without this, a poll that lands
 // between a click on Upload and its answer would swallow the upload's toast and leave the panel open.
 if(gitWatch?.id===job.id){if(options.quiet)gitWatch.quiet=true;if(options.keep)gitWatch.keep=true;return;}
 clearTimeout(gitWatchTimer);const watch={id:job.id,lab_id:job.lab_id,quiet:!!options.quiet,keep:!!options.keep};gitWatch=watch;
 const poll=async()=>{
  if(gitWatch!==watch)return;
  try{
   const value=await(await api('/git/jobs/'+encodeURIComponent(job.id))).json();if(gitWatch!==watch)return;
   gitRememberJob(value);gitRenderJob(value);
   if(gitActiveStates.has(value.status))gitWatchTimer=setTimeout(poll,1500);
   else{
    gitWatch=null;await refresh();
    // With the header chip the result is the chip panel's (saveFinished in save-header.js): no job window, no review window.
    if(watch.quiet&&typeof saveFinished==='function')saveFinished(value);
    else if(watch.quiet){if(value.status==='review_pending'&&gitNeedsReview(value))await gitReviewJob(value);else if(['push_pending','export_pending','failed','capture_incomplete','interrupted','review_pending'].includes(value.status))await gitShowJob(value.id,value);else notify(gitDoneToast(value));}
   }
  }catch(error){if(gitWatch===watch){gitWatch=null;if(gitDialogJob===job.id&&$('git-job-dialog')?.open)$('git-job-dialog').querySelector('.form-error').textContent='The save status could not be refreshed. Close and reopen this save to check it. ('+error.message+')';else if(watch.quiet)notify('The save status could not be refreshed. Open the save chip in the header to check it.');}}
 };gitWatchTimer=setTimeout(poll,1000);
}
async function gitDismissJob(job){
 const dialog=opDialog('git-dismiss-dialog','Keep this snapshot only?',`<p>The configuration backup and anything already saved stay as they are. The manager just stops waiting for this save to be uploaded, so the lab can be disconnected or removed.</p><p>Nothing is deleted; a save kept on the VM may be included in a later upload.</p><details class="caption"><summary>Details</summary><p>${esc(gitLabel(job))} · ${esc(job.id)}</p></details><div class="dialog-actions"><button class="button secondary" id="git-dismiss-cancel">Cancel</button><button class="button primary" id="git-dismiss-confirm">Keep snapshot only</button></div>`);
 $('git-dismiss-cancel').onclick=()=>dialog.close();$('git-dismiss-confirm').onclick=()=>opTask(dialog,async()=>{const result=await json('/git/jobs/'+encodeURIComponent(job.id)+'/dismiss','POST',{acknowledge:true});gitRememberJob(result);dialog.close();await gitShowJob(result.id,result);await refresh();});
}
async function gitUpdateRemote(id=activeId){
 const dialog=opDialog('git-update-dialog','Update from the repository','<p>Downloads the newest files from the online repository — for example versions your instructor added. Your running devices are not changed.</p><p class="form-help">If the VM’s copy can’t be updated automatically, nothing changes and the reason is shown.</p><div class="dialog-actions"><button class="button secondary" id="git-update-cancel">Cancel</button><button class="button primary" id="git-update-confirm">Update now</button></div>');
 $('git-update-cancel').onclick=()=>dialog.close();
 $('git-update-confirm').onclick=()=>opTask(dialog,async()=>{const result=await json('/labs/'+encodeURIComponent(id)+'/git/update','POST',{});dialog.close();await gitLoadContext(id,true);await refresh();if(typeof saveDrawerRefresh==='function')await saveDrawerRefresh(true);notify(result.message||'Repository is up to date.');});
}
async function gitUnlink(id=activeId){
 const context=gitContexts.get(id),repoName=gitRepoName(gitRepository(context?.binding)),pending=gitLabJobs(id,context).some(job=>gitPendingStates.has(job.status));
 const dialog=opDialog('git-unlink-dialog',`Disconnect this lab from ${repoName}?`,`<p>Nothing is deleted. Your saves stay in ${esc(repoName)} and the configuration backups stay on this VM. The next Save asks where to save again.</p>${pending?'<p class="op-notice">A save of this lab still waits for upload. It stays on the lab VM and stays part of the next upload.</p>':''}<div class="dialog-actions"><button class="button secondary" id="git-unlink-cancel">Cancel</button><button class="button danger" id="git-unlink-confirm">Disconnect</button></div>`);
 $('git-unlink-cancel').onclick=()=>dialog.close();$('git-unlink-confirm').onclick=()=>opTask(dialog,async()=>{await json('/labs/'+encodeURIComponent(id)+'/git/unlink','POST',{});dialog.close();gitContexts.delete(id);await refresh();});
}
async function gitHistory(id=activeId){
 const data=await(await api('/labs/'+encodeURIComponent(id)+'/git/history')).json();
 const versions=data.versions||[],commits=data.commits||[];
 const dialog=opDialog('git-history-dialog','Full history',`<p>Every saved state of this lab and of the other labs in this repository, and every save. Open one to view, download or compare it, or to load it onto the running lab (the current configuration is backed up first and nothing reboots).</p><h3>Saved versions</h3><div class="op-history">${versions.map((version,index)=>`<button class="button secondary" data-git-version="${index}"><strong>${esc(version.label||version.name||version.path)}</strong><small>${esc(version.path)}${version.connected?' · this lab':''}</small></button>`).join('')||'<p>Nothing saved yet.</p>'}</div><h3>Save history</h3><div class="op-history">${commits.map((commit,index)=>`<button class="button secondary" data-git-commit="${index}"><strong>${esc(commit.message)}</strong><small>${esc(commit.time?gitWhen(commit.time*1000):'')} · <span class="mono">${esc((commit.commit||'').slice(0,10))}</span></small></button>`).join('')||'<p>No save history yet.</p>'}</div>`);
 for(const button of dialog.querySelectorAll('[data-git-version]'))button.onclick=()=>opTask(dialog,()=>{const version=versions[Number(button.dataset.gitVersion)];return gitViewVersion(id,{...version,path:'/'+(version.path||'')});});
 for(const button of dialog.querySelectorAll('[data-git-commit]'))button.onclick=()=>opTask(dialog,()=>gitOpenCommit(id,commits[Number(button.dataset.gitCommit)],versions));
}
async function gitOpenCommit(id,commit,versions){
 const matching=gitLabJobs(id).filter(job=>job.commit===commit.commit&&['latest','baseline','checkpoint'].includes(job.target));
 // An unchanged save can reuse HEAD without producing the selected commit.
 const known=matching.find(job=>Array.isArray(job.changed_files)&&job.changed_files.length)||matching.find(job=>job.target==='latest');
 const binding=gitContexts.get(id)?.binding;
 // The job's own recorded snapshot path (exact) is preferred; only a job saved before that field
 // existed falls back to the binding's current prefix joined with its target.
 if(known)return gitViewVersion(id,{commit:commit.commit,path:known.snapshot_path?'/'+known.snapshot_path:gitSnapshotPath(binding,gitTargetPath(known))});
 const paths=[...new Set([gitSnapshotPath(binding,'latest'),gitSnapshotPath(binding,'baseline'),...versions.map(version=>'/'+version.path)])];
 const dialog=opDialog('git-commit-dialog','Which saved version?',`<p>${esc(commit.message||'Older save')}</p><p class="op-path">${esc(commit.commit)}</p><label for="git-commit-path">Which folder was saved at this point?</label><select id="git-commit-path">${paths.map(folder=>`<option value="${esc(folder)}">${esc(folder.replace(/^\//,''))}</option>`).join('')}</select><p class="form-help">Only folders that already existed at this save can be opened.</p><button class="button primary" id="git-commit-view">Open this version</button>`);
 $('git-commit-view').onclick=()=>opTask(dialog,()=>gitViewVersion(id,{commit:commit.commit,path:$('git-commit-path').value}));
}
async function gitCompareVersion(id,request,label){
 const result=await json('/labs/'+encodeURIComponent(id)+'/git/compare','POST',{commit:request.commit,path:request.path});
 closeDialogsExcept();
 const dialog=opDialog('git-diff-dialog','Compared with your latest save',`<p>Shows how <strong>${esc(label||request.path)}</strong> differs from your latest save. To see what would change on the devices, choose Load this state…: the devices are compared before anything is loaded.</p>${gitFilesDiffMarkup(result.files,'This version','Your latest save')}`);
 gitFocusDialog(dialog);
}
async function gitViewVersion(id,version){
 const request={commit:version.commit,path:version.path},data=await json('/labs/'+encodeURIComponent(id)+'/git/version','POST',request);
 // A caller without a friendly label (e.g. the review dialog's "Open the full saved version") falls
 // back to the exact path; it is never shown with its wire-form leading slash.
 const files=data.files||[],name=version.label||version.name||String(version.path||'').replace(/^\/+/,'')||'the repository root';
 const restoreBtn=data.restore_supported&&typeof restoreFromVersion==='function'?'<button class="button danger" id="git-version-restore">Load this state…</button>':'';
 const restoreNote=data.restore_supported
  ?'<p class="form-help">This saved state can be loaded onto the running lab. You choose the devices first; the current configuration is backed up and nothing reboots.</p>'
  :'<p class="form-help">View or download only: it was saved without the files needed to load it.</p>';
 closeDialogsExcept();
 const dialog=opDialog('git-version-dialog','Saved version',`<p class="op-path">${esc(name)}</p><details class="caption"><summary>Details</summary><p class="mono">${esc(version.path)} · ${esc(version.commit)}</p></details><div class="actions">${restoreBtn}<button class="button secondary" id="git-version-compare">Compare with my latest save</button><button class="button primary" id="git-version-download">Download (ZIP)</button></div>${restoreNote}<details><summary>Technical details</summary><pre class="git-file-content" tabindex="0">${esc(JSON.stringify(data.manifest,null,2))}</pre></details><div class="git-version-files">${files.map(file=>`<details><summary>${esc(file.name)}</summary><pre class="git-file-content" tabindex="0">${esc(file.text)}</pre></details>`).join('')||'<p>No configuration files in this version.</p>'}</div>`);
 gitFocusDialog(dialog);
 if(restoreBtn)$('git-version-restore').onclick=()=>opTask(dialog,async()=>{dialog.close();closeDialogsExcept();await restoreFromVersion(id,{type:'git',commit:version.commit,path:version.path},name);});
 $('git-version-compare').onclick=()=>opTask(dialog,()=>gitCompareVersion(id,request,name));
 $('git-version-download').onclick=()=>opTask(dialog,async()=>{const response=await api('/labs/'+encodeURIComponent(id)+'/git/version/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=attachmentName(response,'lab-version.zip');document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
}
// The actions other scripts and dialogs ask for by name. Each has its home in the header: Save settings, the Load panel, the
// folder chooser, All versions; none leads to a tab.
function gitRunAction(action,id=activeId){
 if(typeof closeMenus==='function')closeMenus();
 const drawer=(kind,options={})=>{if(typeof saveDrawerOpen!=='function')throw new Error('This part of the page did not load. Reload the page and try again.');saveDrawerOpen(kind,{opener:$('save-chip'),...options});};
 return opTask(null,async()=>{
  if(action==='settings'){drawer('settings');return;}
  if(action==='versions'){drawer('versions');return;}
  if(action==='refresh'){if(typeof saveDrawerRefresh==='function')await saveDrawerRefresh(true);return;}
  if(action==='load'){if(typeof saveOpenPanel==='function')saveOpenPanel('load');return;}
  // Every folder of the repository, each with Load this state…, without changing where this lab saves.
  if(action==='browse'){drawer('chooser',{mode:'browse'});return;}
  if(action==='history'){await gitHistory(id);return;}
  if(action==='push'){if(typeof saveOpenPanel==='function')saveOpenPanel('status',{focus:true});return;}
  if(action==='update'){await gitUpdateRemote(id);return;}
  if(action==='unlink'){await gitUnlink(id);return;}
  if(action==='switch'){await gitSwitchRepository(id);return;}
  if(action==='connect'){drawer('chooser',{mode:'location',address:true});return;}
  if(action==='baseline'){await gitSaveOptions('baseline',id);return;}
  throw new Error('This action is not available here.');
 });
}
