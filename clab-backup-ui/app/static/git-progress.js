'use strict';
// Git credentials stay with the registered VM account. The browser sends only
// registered binding IDs and structured actions; it never assembles shell commands.
// The Progress tab reads in the student's words (progressState in status.js); the backend's
// own status words stay available under Details and in gitStateLabels for the technical view.
const gitActiveStates=new Set(['queued','capturing','exporting','pushing']);
const gitPendingStates=new Set(['committed','push_pending','export_pending','review_pending','interrupted']);
const gitStateLabels={queued:'Waiting to save',capturing:'Capturing configurations',exporting:'Saving to repository',pushing:'Pushing to remote',synced:'Saved to Git',committed:'Saved on VM · not pushed',unchanged:'No configuration changes',push_pending:'Saved on VM · push pending',export_pending:'Snapshot saved · export pending',review_pending:'Saved on VM · review before pushing',interrupted:'Save interrupted · snapshot retained',capture_incomplete:'Capture incomplete',failed:'Save needs attention',dismissed:'Snapshot kept locally'};
const gitSaveSentences={queued:'Waiting to start…',capturing:'Reading device configurations…',exporting:'Saving to the repository…',pushing:'Uploading…',synced:'Progress saved to Git',unchanged:'Progress saved to Git — nothing had changed',committed:'Saved on this VM — not uploaded',review_pending:'Saved on this VM — review before uploading',push_pending:'Saved on this VM — upload needs attention',export_pending:'Configurations read — saving to the repository needs attention',interrupted:'Save interrupted — retry it',capture_incomplete:'Save failed — a device could not be read',failed:'Save failed',dismissed:'Kept on this VM only'};
const GIT_EXPOSURE_TEXT='I understand that complete device configurations — including any passwords or keys they contain — will be saved to this repository and uploaded to its online copy.';
const GIT_EXPOSURE_ERROR='Tick the box to confirm that complete configurations will be saved to this repository.';
const gitContexts=new Map(),gitLoads=new Map();
let gitViewLab='',gitViewRequest=0,gitWatch=null,gitWatchTimer=null,gitDialogJob='',gitSubmitting=false,gitVersionRows=[],gitVersionTree=null;
function gitLabel(job){return gitStateLabels[job?.status]||job?.status||'No progress saved yet';}
function gitJobTime(job){return job?.created||job?.finished||'';}
function gitTime(value){return utcDisplay(typeof value==='number'?value*1000:value);}
function gitWhen(value){if(!value)return '';const relative=typeof relativeTime==='function'?relativeTime(value):'';return relative||utcDisplay(value);}
function gitTabActive(){return typeof tab==='string'&&(tab==='progress'||tab==='git');}
function gitLabJobs(id,context=gitContexts.get(id)){
 const jobs=new Map();for(const job of [...(context?.jobs||[]),...(state.git_jobs||[])])if(!job.lab_id||job.lab_id===id)jobs.set(job.id,{...jobs.get(job.id),...job});
 return [...jobs.values()].sort((a,b)=>gitJobTime(b).localeCompare(gitJobTime(a)));
}
function gitRepository(binding){return binding?.repository||{};}
function gitBindingChanged(binding,repository){return !binding||!repository||binding.binding_id!==repository.id||binding.revision!==repository.revision;}
function gitRegisteredDestination(repo){return [repo.owner,repo.path,[repo.remote,repo.branch].filter(Boolean).join(' / '),repo.push_url?'Push to '+repo.push_url:'',repo.prefix||'repository root'].filter(Boolean).join(' · ');}
function gitRepoName(repo){return String(repo?.path||'').split('/').filter(Boolean).pop()||repo?.label||'Repository';}
function gitDestination(binding){const repo=gitRepository(binding);return [[gitRepoName(repo)||binding?.binding_id,repo.prefix?repo.prefix.replace(/\/$/,''):'','latest/'].filter(Boolean).join(' › '),repo.branch].filter(Boolean).join(' · ');}
// "Course-Labs › bgp" in words for the status card and the Recent saves rows.
function gitFolderWords(binding){const repo=gitRepository(binding),name=gitRepoName(repo)||binding?.binding_id||'the repository';return repo.prefix?name+' › '+repo.prefix.replace(/\/$/,''):name+' (whole repository)';}
function gitTargetPath(job){if(job.target==='move')return 'latest';return job.target==='checkpoint'?'checkpoints/'+job.checkpoint:job.target||'latest';}
function gitTargetLabel(job){if(job.target==='move')return 'Folder move → '+((job.snapshot_path||'').replace(/\/?latest$/,'')||'repository root');return job.target==='checkpoint'?'checkpoints/'+(job.checkpoint||''):job.target||'latest';}
// Student sentence, pill and "Saved as" for one save job.
function gitSaveSentence(job){
 if(!job)return '';const s=job.status,active=gitActiveStates.has(s);
 if(job.target==='update')return active?'Updating from the repository…':'Repository updated';
 if(job.target==='move')return active?'Moving saved files…':'Moved to folder '+((job.snapshot_path||'').replace(/\/?latest$/,'')||'the repository root');
 if(!active&&['synced','committed','review_pending','unchanged'].includes(s)){if(job.target==='checkpoint')return `Checkpoint '${job.checkpoint||''}' saved`;if(job.target==='baseline')return 'Baseline set';}
 return gitSaveSentences[s]||gitLabel(job);
}
function gitSavePill(job){const s=job?.status;if(gitActiveStates.has(s))return 'busy';if(['synced','unchanged'].includes(s))return 'ok';if(['failed','capture_incomplete'].includes(s))return 'danger';if(s==='dismissed'||!s)return 'neutral';return 'warn';}
function gitBadgeClass(job){const s=job?.status;return gitActiveStates.has(s)?'running':['synced','unchanged'].includes(s)?'good':['failed','capture_incomplete'].includes(s)?'bad':'warn';}
function gitSavedAs(job){if(job.target==='update')return 'Repository update';if(job.target==='move')return 'Moved to '+((job.snapshot_path||'').replace(/\/?latest$/,'')||'the repository root');if(job.target==='checkpoint')return `Checkpoint '${job.checkpoint||''}'`;if(job.target==='baseline')return 'Baseline';return 'Latest';}
function gitUploadState(job){const s=job.status;if(job.pushed||s==='synced')return 'Uploaded';if(gitActiveStates.has(s))return 'In progress';return {committed:'Not uploaded yet',review_pending:'Waiting for your review',push_pending:'Upload needs attention',export_pending:'Not saved to the repository yet',dismissed:'Kept on this VM',unchanged:'Nothing to upload',interrupted:'Interrupted before the upload'}[s]||'—';}
let gitPendingSelection='';
function gitCompleteBackups(jobs,id,names){
 const required=new Set(names||[]);
 return jobs.filter(job=>required.size&&job.lab_id===id&&job.operation==='backup'&&['succeeded','partial'].includes(job.status)&&job.nodes?.length===required.size&&new Set(job.nodes.map(node=>node.name)).size===required.size&&job.nodes.every(node=>node.status==='succeeded'&&required.has(node.name)));
}
function gitSavePayload(values,requestId){return {request_id:requestId,target:values.target||'latest',checkpoint:values.checkpoint||'',push:values.push!==false,note:values.note||'',backup_job_id:values.backup_job_id||'',replace_baseline:values.replace_baseline===true,expected_baseline:values.expected_baseline||'',allow_removed:values.allow_removed===true};}
function gitRequestId(){const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return Array.from(bytes,n=>n.toString(16).padStart(2,'0')).join('');}
function gitJobMarkup(job){
 if(!job)return '<p>No saves yet. Save progress saves every device chosen under Save settings.</p>';
 const changed=Array.isArray(job.changed_files)?job.changed_files.length:job.changed_files;
 const explain=gitActiveStates.has(job.status)||gitPendingStates.has(job.status)||['failed','capture_incomplete'].includes(job.status);
 return `<div class="git-job-summary"><span class="badge ${gitBadgeClass(job)}">${esc(gitSaveSentence(job))}</span><p>${esc(explain?job.message||'':'')}</p><dl class="health-grid"><dt>Saved as</dt><dd>${esc(gitSavedAs(job))}</dd><dt>Started</dt><dd>${esc(gitWhen(job.created))}</dd>${job.note?`<dt>Note</dt><dd>${esc(job.note)}</dd>`:''}</dl><details><summary>Details</summary><dl class="health-grid"><dt>Status</dt><dd>${esc(gitLabel(job))}</dd><dt>Message</dt><dd>${esc(job.message||'')}</dd><dt>Saved target</dt><dd>${esc(gitTargetLabel(job))}</dd><dt>Started (UTC)</dt><dd>${esc(utcDisplay(job.created))}</dd>${job.commit?`<dt>Commit</dt><dd class="mono">${esc(job.commit)}</dd>`:''}${changed!==undefined?`<dt>Files changed</dt><dd>${esc(changed)}</dd>`:''}${job.id?`<dt>Job id</dt><dd class="mono">${esc(job.id)}</dd>`:''}</dl></details></div>`;
}
function gitDiffMarkup(files,beforeLabel='This version',afterLabel='Your latest save'){
 if(!files?.length)return '<p>No differences — this version matches your latest save.</p>';
 return files.map(file=>`<details class="git-diff-file"><summary>${esc(file.name)} <span class="badge">${esc(file.status||'changed')}</span></summary><div class="git-diff-columns"><section><h3>${esc(beforeLabel)}</h3><pre tabindex="0">${esc(file.before??'No file in this version')}</pre></section><section><h3>${esc(afterLabel)}</h3><pre tabindex="0">${esc(file.after??'No file in this version')}</pre></section></div></details>`).join('');
}
async function gitLoadContext(id,force=false){
 if(gitLoads.has(id))return gitLoads.get(id);
 if(!force&&gitContexts.has(id))return gitContexts.get(id);
 const pending=(async()=>{const value=await(await api('/labs/'+encodeURIComponent(id)+'/git')).json();gitContexts.set(id,value);return value;})();
 gitLoads.set(id,pending);try{return await pending;}finally{gitLoads.delete(id);}
}
function gitActionButtons(){
 if(typeof document!=='undefined'&&document&&typeof document.querySelectorAll==='function')return [...document.querySelectorAll('[data-git-action]')];
 const menu=$('git-save-menu');return menu&&typeof menu.querySelectorAll==='function'?[...menu.querySelectorAll('[data-git-action]')]:[];
}
function gitInsideMenu(button){return typeof button.closest==='function'&&!!button.closest('#git-save-menu');}
// Why Save progress is unavailable right now, as visible text; an unbound lab keeps the button
// enabled because it opens the first-save flow.
function gitSaveReason(binding,active){
 if(gitSubmitting||active)return 'Saving… wait for the current save to finish';
 if(binding&&typeof busy==='function'&&busy())return 'A backup or lab operation is running. Save progress is available when it finishes';
 return '';
}
function renderGitProgress(){
 const bar=$('git-progress-bar');if(!bar)return;
 const lab=current();bar.hidden=!lab;if(!lab){clearTimeout(gitWatchTimer);gitWatch=null;return;}
 const context=gitContexts.get(lab.id),binding=context?.binding||lab.git_binding,problem=context?.repository_status?.problem||'';
 const jobs=gitLabJobs(lab.id),active=jobs.find(job=>gitActiveStates.has(job.status));
 const ps=typeof progressState==='function'?progressState(lab,jobs,undefined,problem):null;
 $('git-destination').textContent=binding?'Saving to '+gitFolderWords(binding):'Not connected — choose where this lab’s progress is saved';
 $('git-progress-status').textContent=ps?(ps.key==='git'&&typeof progressSummary==='function'?progressSummary(lab,jobs,undefined,problem):[ps.label,ps.detail].filter(Boolean).join(' · ')):(jobs[0]?gitLabel(jobs[0]):'Save progress creates a snapshot you can return to later.');
 const reason=gitSaveReason(binding,active),label=gitSubmitting||active?'Saving…':binding?'Save progress':'Connect a save location…';
 for(const id of ['git-save-progress','progress-save']){const button=$(id);if(!button)continue;button.textContent=label;button.disabled=!!reason;button.title=reason||(binding?'Save every device’s configuration to '+gitDestination(binding):'Choose where this lab’s progress is saved');}
 if($('progress-save-reason')){$('progress-save-reason').textContent=reason;$('progress-save-reason').hidden=!reason;}
 $('git-save-menu').hidden=!binding;
 for(const button of gitActionButtons()){button.disabled=(gitSubmitting||!!active)&&!['history','load','settings'].includes(button.dataset.gitAction);if(!gitInsideMenu(button))button.hidden=!binding;}
 const more=$('progress-more-button');if(more&&more.parentElement)more.parentElement.hidden=!binding;
 if($('git-problem')){$('git-problem').hidden=!problem;if($('git-problem-text'))$('git-problem-text').textContent=problem;}
 gitRenderLastRestore(lab);
 if(gitWatch&&gitWatch.lab_id!==lab.id&&!$('git-job-dialog')?.open){clearTimeout(gitWatchTimer);gitWatch=null;}
 if(active&&!gitWatch)gitStartWatch(active);
}
// The newest finished "Apply to running lab" of this lab stays one click away on the status card.
function gitRenderLastRestore(lab){
 const line=$('git-last-restore');if(!line)return;
 const busyStates=typeof restoreActiveJob!=='undefined'?restoreActiveJob:new Set();
 const last=(state.restore_jobs||[]).filter(j=>j.lab_id===lab.id&&!busyStates.has(j.status)).sort((a,b)=>String(b.finished||b.created||'').localeCompare(String(a.finished||a.created||'')))[0];
 line.hidden=!last;if(!last)return;
 const labels=typeof restoreJobLabels!=='undefined'?restoreJobLabels:{};
 if($('git-last-restore-text'))$('git-last-restore-text').textContent='Last configuration change: '+(labels[last.status]||last.status)+(last.finished||last.created?' · '+gitWhen(last.finished||last.created):'');
 if($('git-last-restore-open'))$('git-last-restore-open').onclick=()=>{if(typeof restoreShowJob==='function')opTask(null,()=>restoreShowJob(last.id));};
}
function gitOpenRepository(){
 if(typeof showTab==='function')showTab('progress');
 const target=$('git-save-location')||$('git-repository-content');
 if(target&&typeof target.scrollIntoView==='function')target.scrollIntoView({block:'start',behavior:'smooth'});
 if(current()?.git_binding)return;
 const focus=$('git-binding-id')||(target&&typeof target.querySelector==='function'?target.querySelector('[data-git-repo-action="connect"]'):null);
 if(focus&&typeof focus.focus==='function')focus.focus();
}
// null = not requested, false = the VM did not answer (the versions list then shows Try again, never "not saved yet").
async function gitFetchHistory(id){try{return await(await api('/labs/'+encodeURIComponent(id)+'/git/history')).json();}catch{return false;}}
async function gitFetchTree(bindingId){try{return await(await api('/git/repositories/'+encodeURIComponent(bindingId)+'/tree')).json();}catch{return false;}}
async function gitShowRepository(force=false){
 const id=activeId,container=$('git-repository-content');if(!id||!container)return;
 if(gitViewLab===id&&!force)return;
 gitViewLab=id;const request=++gitViewRequest;container.innerHTML='<p role="status">Loading your saved progress…</p>';
 try{
  const [context,catalog]=await Promise.all([gitLoadContext(id,true),(await api('/git/repositories')).json()]);
  if(request!==gitViewRequest||activeId!==id)return;
  let history=null,tree=null;
  if(context.binding){[history,tree]=await Promise.all([gitFetchHistory(id),gitFetchTree(context.binding.binding_id)]);if(request!==gitViewRequest||activeId!==id)return;}
  gitRenderRepository(id,context,catalog,{history,tree});renderGitProgress();
 }catch(error){
  if(request!==gitViewRequest)return;
  container.innerHTML=`<div class="blank-state"><h3>Saved progress could not be loaded.</h3><p class="form-help">Check the VM connection (Manager ▾ › VM connection…), then try again.</p><div class="actions"><button type="button" class="button secondary" data-git-repo-action="refresh">Try again</button></div><details><summary>Details</summary><p class="form-error" role="alert">${esc(error.message)}</p></details></div>`;
  for(const button of container.querySelectorAll('[data-git-repo-action]'))button.onclick=()=>gitRunAction(button.dataset.gitRepoAction,id);
 }
}
function gitRenderRepository(id,context,catalog,extras={}){
 const binding=context.binding,repo=gitRepository(binding),repositories=catalog.repositories||[],supported=context.supported_nodes||[],excluded=context.unsupported_nodes||[];
 const selected=new Set(binding?.node_names||supported.map(node=>node.name));
 const activeBinding=!!binding,labName=gitLabName(id),repoName=gitRepoName(repo);
 const preselect=gitPendingSelection&&repositories.some(value=>value.id===gitPendingSelection)?gitPendingSelection:binding?.binding_id||'';gitPendingSelection='';
 const places=typeof gitPlacesState!=='undefined'?gitPlacesState:null,openBrowser=!activeBinding||!!(places&&places.open);if(places)places.open=false;
 const optionLabel=value=>{const twins=repositories.filter(r=>gitRepoName(r)===gitRepoName(value)&&(r.prefix||'')===(value.prefix||''));return `${gitRepoName(value)} › ${value.prefix||'(whole repository)'}${twins.length>1?' · '+value.owner:''}`;};
 const option=value=>`<option value="${esc(value.id)}" ${value.id===preselect?'selected':''}>${esc(optionLabel(value))}</option>`;
 const tree=extras.tree||null,model=tree&&typeof gitTreeModel==='function'?gitTreeModel(tree.files,tree.folders):null;
 const form=repositories.length?`<form id="git-binding-form" class="git-binding-form">
  <details id="git-change-folder" class="git-change-folder" ${openBrowser?'open':''}><summary>${activeBinding?'Change folder…':'Choose a folder for this lab'}</summary>
   <label for="git-binding-id">Save location</label><select id="git-binding-id" required>${!preselect?'<option value="">Choose a save location</option>':''}${repositories.map(option).join('')}</select>
   <p class="form-help">Not the repository you want? <button type="button" class="text-button git-inline-action" data-git-repo-action="connect">Connect a repository by URL</button></p>
   <section class="git-places" aria-label="Folders in this repository"><div class="git-places-title"><h3>Folders in this repository</h3><p>${activeBinding?'Pick a folder and choose <strong>Save this lab here</strong> to move this lab’s saves, or create a new folder.':'Pick the folder where this lab’s progress will be saved, or create a new one. Then choose the devices to include and Connect.'}</p></div><div id="git-places-panel"></div></section>
  </details>
  <h3 id="git-save-settings">${activeBinding?'Save settings':'Connect a save location'}</h3>
  <fieldset class="git-node-scope"><legend>Devices included in every save</legend>${supported.map(node=>`<label class="checkbox-label"><input type="checkbox" name="git-node" value="${esc(node.name)}" ${selected.has(node.name)?'checked':''}> <span>${esc(node.short_name||node.name)} <small>${esc(platformLabel(node.platform))}</small></span></label>`).join('')||'<p>No supported configuration devices in this lab.</p>'}</fieldset>
  ${excluded.length?`<p class="form-help">${excluded.map(node=>esc(node.short_name||node.name||node)).join(', ')} can’t be included yet — configuration saves aren’t supported for ${excluded.length===1?'its':'their'} platform.</p>`:''}
  <p class="form-help">If an included device can’t be reached, the save stops and nothing is written — an older configuration is never saved in its place.</p>
  <label class="checkbox-label"><input id="git-review-before-push" type="checkbox" ${binding?.review_before_push?'checked':''}> Let me review changes before they are uploaded</label>
  <label id="git-exposure-label" class="checkbox-label"><input id="git-exposure" type="checkbox"> ${esc(GIT_EXPOSURE_TEXT)}</label>
  <details class="caption"><summary>Registration details</summary><p id="git-binding-destination" class="op-path"></p><p>Git runs on the VM as the registered account with the login configured there. This app never asks for a Git password.</p></details>
  <p class="form-error" role="alert"></p><div class="actions"><button type="submit" class="button primary" ${supported.length?'':'disabled'}>${activeBinding?'Save settings':'Connect save location'}</button></div></form>`:'';
 const technical=activeBinding?`<details class="caption git-location-tech"><summary>Technical details</summary>${repo.push_url?`<p class="op-path">Verified push destination: <code>${esc(repo.push_url)}</code></p>`:''}<p class="op-path">Branch ${esc(repo.branch||'')} · VM account ${esc(repo.owner||'')} · ${esc(repo.path||'')}</p></details>`:'';
 $('git-repository-content').innerHTML=activeBinding
  ?`<section class="card git-save-location" id="git-save-location" aria-labelledby="git-save-location-title"><h2 id="git-save-location-title">Save location</h2><p class="git-destination-line"><span>${esc(labName)} saves to</span><code>${esc(repoName)}</code>${repo.prefix?`<span aria-hidden="true">›</span><code>${esc(repo.prefix)}</code>`:''}<span aria-hidden="true">›</span><code>latest/</code></p><p class="form-help">Each save includes ${selected.size} ${selected.size===1?'device':'devices'}.</p><div class="actions"><button type="button" class="button secondary" data-git-repo-action="switch">Use a different repository…</button><button type="button" class="button secondary" data-git-repo-action="connect">Connect by URL…</button></div><p class="form-help">Connected the wrong repository? Choose <strong>Use a different repository</strong>. Nothing is deleted, and files already saved stay where they are. To stop saving here, <button type="button" class="text-button git-inline-action" data-git-repo-action="unlink">disconnect this lab</button>.</p>${technical}${form}</section>`
  :repositories.length
  ?`<section class="card git-save-location" id="git-save-location" aria-labelledby="git-save-location-title"><h2 id="git-save-location-title">Choose a save location</h2><p>Your progress is saved as versions in a Git repository on the lab VM. Pick the repository and folder for this lab, then choose the devices to include.</p>${form}</section>`
  :`<section class="card git-save-location" id="git-save-location" aria-label="Save location"><div class="blank-state"><h3>Choose where to save your progress</h3><p>Connect a GitHub repository by pasting its HTTPS URL. The VM's Git login is used — you won't be asked for a password.</p><div class="actions git-blank-actions"><button type="button" class="button primary" data-git-repo-action="connect">Connect a repository by URL</button><button type="button" class="button secondary" data-git-repo-action="refresh">Check again</button></div><details><summary>Administrator setup (terminal)</summary><p>On the VM, run this as your normal account (no sudo). It sets up the checkout and Git login. Then click Check again.</p><pre class="git-setup-command">bash deploy/setup-git.sh</pre></details></div></section>`;
 gitVersionTree=tree;gitRenderVersions(id,context,model,tree,extras.history||null);gitRenderSaves(id,context);gitRenderAdvanced(context);
 const form_=$('git-binding-form'),panel=$('git-places-panel');
 const showPlaces=bindingId=>{
  if(!panel)return;
  if(!bindingId){panel.innerHTML='<p class="git-empty-folder">Pick a repository above to see its folders.</p>';return;}
  const browsed=repositories.find(value=>value.id===bindingId),connected=!!binding&&!!browsed&&browsed.path===repo.path;
  gitPlacesShow(panel,id,bindingId,{current:binding?.binding_id||'',connected,tree:bindingId===binding?.binding_id?tree:undefined,onUse:(path,model_,tree_)=>gitUseFolder(id,path,model_,tree_),onNew:(path,model_,tree_)=>gitNewFolder(id,path,model_,tree_),onApply:typeof restoreFromFolder==='function'?(path,model_,tree_)=>restoreFromFolder(id,path,tree_):undefined});
 };
 if(form_){
  const change=()=>{const selectedRepo=repositories.find(value=>value.id===$('git-binding-id').value);$('git-binding-destination').textContent=selectedRepo?gitRegisteredDestination(selectedRepo):'';const changed=gitBindingChanged(binding,selectedRepo);$('git-exposure-label').hidden=!changed;$('git-exposure').required=changed;$('git-exposure').checked=false;showPlaces(selectedRepo?.id||binding?.binding_id||'');};
  $('git-binding-id').onchange=()=>{if($('git-change-folder'))$('git-change-folder').open=true;change();};change();
  form_.onsubmit=event=>{event.preventDefault();opTask(form_,async()=>{
   const node_names=[...form_.querySelectorAll('[name="git-node"]:checked')].map(input=>input.value);
   if(!node_names.length)throw new Error('Choose at least one device to include.');
   if(gitBindingChanged(binding,repositories.find(value=>value.id===$('git-binding-id').value))&&!$('git-exposure').checked)throw new Error(GIT_EXPOSURE_ERROR);
   await json('/labs/'+encodeURIComponent(id)+'/git','PUT',{binding_id:$('git-binding-id').value,node_names,review_before_push:$('git-review-before-push').checked});
   await gitShowRepository(true);await refresh();notify(activeBinding?'Save settings updated.':'Save location connected. You can save progress now.');
  });};
 }else if(activeBinding)showPlaces(binding.binding_id);
 for(const button of $('git-repository-content').querySelectorAll('[data-git-repo-action]'))button.onclick=()=>gitRunAction(button.dataset.gitRepoAction,id);
 for(const button of $('git-repository-content').querySelectorAll('[data-git-job]'))button.onclick=()=>opTask(null,()=>gitShowJob(button.dataset.gitJob));
 if(openBrowser&&activeBinding){const settings=$('git-save-settings');if(settings&&typeof settings.scrollIntoView==='function')settings.scrollIntoView({block:'start',behavior:'smooth'});}
}
// Saved versions: rows come from the repository tree the folder browser already reads (folders with a
// latest/ save), grouped for the student; the History dialog keeps the commit list.
function gitVersionGroups(id,context,model,tree,history){
 const binding=context.binding,repo=gitRepository(binding),prefix=(repo.prefix||'').replace(/\/$/,''),head=tree?.head||history?.versions?.[0]?.commit||'',repoName=gitRepoName(repo),jobs=gitLabJobs(id,context);
 const groups={latest:[],checkpoints:[],baseline:[],reference:[],others:[]};
 const done=j=>['synced','committed','review_pending','unchanged','push_pending'].includes(j.status);
 const noteFor=(target,name)=>jobs.find(j=>j.target===target&&(!name||j.checkpoint===name)&&j.note&&done(j))?.note||'';
 const whenFor=(target,name)=>{const job=jobs.find(j=>j.target===target&&(!name||j.checkpoint===name)&&done(j));return job?job.finished||job.created:'';};
 const epoch=value=>typeof value==='number'?value*1000:'';
 if(model){
  const dir=model.nodes.get(prefix),latest=dir?.dirs.find(d=>d.name==='latest');
  if(latest&&latest.count)groups.latest.push({name:'Latest',caption:`${repoName} › ${prefix||'(whole repository)'} › latest`,when:epoch(tree?.saved?.latest)||whenFor('latest'),note:noteFor('latest'),count:latest.count,view:{commit:head,path:'latest'},compare:false,apply:dir.restorable?(prefix?{folder:prefix}:{version:{type:'git',commit:head,path:'latest'}}):null});
  const checkpoints=dir?.dirs.find(d=>d.name==='checkpoints');
  for(const cp of checkpoints?.dirs||[])if(cp.count)groups.checkpoints.push({name:cp.name,caption:'',when:whenFor('checkpoint',cp.name)||0,note:noteFor('checkpoint',cp.name),count:cp.count,view:{commit:head,path:'checkpoints/'+cp.name},compare:true,apply:null});
  const baseline=dir?.dirs.find(d=>d.name==='baseline');
  if(baseline&&baseline.count)groups.baseline.push({name:'Baseline',caption:'',when:epoch(tree?.saved?.baseline)||whenFor('baseline'),count:baseline.count,view:{commit:head,path:'baseline'},compare:true,apply:null});
  const parentPath=prefix.includes('/')?prefix.slice(0,prefix.lastIndexOf('/')):'',parent=model.nodes.get(parentPath);
  const seen=new Set([prefix]);
  const rowFor=child=>{const latestDir=child.dirs.find(d=>d.name==='latest');return {name:typeof savedVersionName==='function'?savedVersionName(child.path):child.name,caption:child.path,when:'',count:latestDir?latestDir.count:0,view:{commit:head,path:child.path+'/latest'},compare:true,apply:child.restorable?{folder:child.path}:null};};
  for(const child of parent?.dirs||[]){
   if(seen.has(child.path)||!child.dirs.some(d=>d.name==='latest'&&d.count))continue;seen.add(child.path);
   const row=rowFor(child),other=child.registration?.lab;
   if(other&&other.id!==id){row.name=other.name;groups.others.push(row);}else groups.reference.push(row);
  }
  for(const node of model.nodes.values()){
   if(seen.has(node.path)||!node.registration?.lab||node.registration.lab.id===id||!node.dirs.some(d=>d.name==='latest'&&d.count))continue;seen.add(node.path);
   const row=rowFor(node);row.name=node.registration.lab.name;groups.others.push(row);
  }
 }else if(history){
  for(const version of history.versions||[]){
   const row={name:version.label||version.path,caption:version.path,when:'',count:0,view:{commit:version.commit,path:version.path},compare:true,apply:null},leaf=String(version.path||'').split('/').pop();
   if(version.connected){if(leaf==='latest'){row.name='Latest';row.compare=false;groups.latest.push(row);}else if(leaf==='baseline'){row.name='Baseline';groups.baseline.push(row);}else{row.name=leaf;groups.checkpoints.push(row);}}
   else groups.reference.push(row);
  }
 }
 return groups;
}
function gitVersionRowMarkup(row,index){
 const actions=[`<button type="button" class="button secondary small" data-git-version="${index}" data-git-version-action="view">View</button>`];
 if(row.compare)actions.push(`<button type="button" class="button secondary small" data-git-version="${index}" data-git-version-action="compare">Compare with my latest save</button>`);
 if(row.apply)actions.push(`<button type="button" class="button danger-outline small" data-git-version="${index}" data-git-version-action="apply">Apply to running lab…</button>`);
 const meta=[row.when?'Saved '+gitWhen(row.when):'',row.count?`${row.count} ${row.count===1?'file':'files'}`:''].filter(Boolean).join(' · ');
 return `<li class="git-version-row"><div class="git-version-name"><strong>${esc(row.name)}</strong>${row.caption?`<small class="caption mono">${esc(row.caption)}</small>`:''}${row.note?`<small class="caption">${esc(row.note)}</small>`:''}</div><div class="caption git-version-when">${esc(meta)}</div><div class="actions">${actions.join('')}</div></li>`;
}
function gitVersionsMarkup(el,html){if(typeof setMarkup==='function')setMarkup(el,html);else el.innerHTML=html;}
function gitRenderVersions(id,context,model,tree,history){
 const el=$('git-saved-versions');if(!el)return;
 gitVersionRows=[];
 if(!context.binding){gitVersionsMarkup(el,'<p class="git-versions-empty">Choose a save location first. Save progress then creates versions you can return to.</p>');return;}
 const groups=gitVersionGroups(id,context,model,tree,history);
 const section=(title,rows,intro,empty,collapsed)=>{
  const items=rows.map(row=>{gitVersionRows.push(row);return gitVersionRowMarkup(row,gitVersionRows.length-1);}).join('');
  if(!items&&!empty)return '';
  const body=`${intro&&items?`<p class="caption">${esc(intro)}</p>`:''}${items?`<ul class="git-version-list">${items}</ul>`:`<p class="caption">${esc(empty)}</p>`}`;
  return collapsed?`<details class="git-version-group"><summary>${esc(title)} (${rows.length})</summary>${body}</details>`:`<section class="git-version-group"><h3>${esc(title)}</h3>${body}</section>`;
 };
 const html=`<div class="git-versions-head"><button type="button" class="button secondary small" data-git-repo-action="browse">Browse the repository…</button><button type="button" class="button secondary small" data-git-repo-action="history">Full history…</button></div>`
  +section('Latest',groups.latest,'',"You haven't saved this lab yet. Save progress creates a configuration snapshot you can return to later.")
  +section('Checkpoints',groups.checkpoints,'','No checkpoints yet. Create a checkpoint when you reach an important milestone.')
  +section('Baseline',groups.baseline,'The reference version set for this lab.','')
  +section('Instructor and reference versions',groups.reference,'Versions your instructor put in the repository appear here. Apply one to load it onto your running devices; the current configuration is backed up first.','')
  +section('Other labs in this repository',groups.others,'','',true);
 gitVersionsMarkup(el,html);
 if(typeof el.querySelectorAll==='function')for(const button of el.querySelectorAll('[data-git-repo-action]'))button.onclick=()=>gitRunAction(button.dataset.gitRepoAction,id);
}
function gitVersionAction(kind,row,id=activeId){
 if(kind==='view')return opTask(null,()=>gitViewVersion(id,{commit:row.view.commit,path:row.view.path,label:row.name}));
 if(kind==='compare')return opTask(null,()=>gitCompareVersion(id,row.view,row.name));
 if(kind==='apply'&&row.apply){
  if(row.apply.folder&&typeof restoreFromFolder==='function')return opTask(null,()=>restoreFromFolder(id,row.apply.folder,gitVersionTree||{repository:gitRepository(gitContexts.get(id)?.binding)}));
  if(row.apply.version&&typeof restoreFromVersion==='function')return opTask(null,()=>restoreFromVersion(id,row.apply.version,row.name));
 }
 return undefined;
}
// Recent saves: one expandable row per job in student words; the job dialog keeps the live poll,
// the review and the retry paths.
function gitRenderSaves(id,context){
 const list=$('git-saves-list');if(!list)return;
 const jobs=gitLabJobs(id,context).slice(0,20);
 const open=new Set(typeof list.querySelectorAll==='function'?[...list.querySelectorAll('details[open]')].map(d=>d.dataset?.gitJob||d.getAttribute?.('data-git-job')):[]);
 const html=jobs.map(job=>{const pending=gitPendingStates.has(job.status);
  return `<details class="git-saved-job" data-git-job="${esc(job.id)}" ${open.has(job.id)?'open':''}><summary><span class="pill ${esc(gitSavePill(job))}">${esc(gitSavedAs(job))}</span> <span>${esc(gitSaveSentence(job))} · ${esc(gitWhen(job.finished||job.created))}</span></summary><dl class="kv"><dt>Saved as</dt><dd>${esc(gitSavedAs(job))}</dd><dt>Where</dt><dd>${esc(gitFolderWords(context.binding))}</dd>${job.commit?`<dt>Commit</dt><dd class="mono">${esc(job.commit.slice(0,10))}</dd>`:''}<dt>Upload</dt><dd>${esc(gitUploadState(job))}</dd>${job.note?`<dt>Note</dt><dd>${esc(job.note)}</dd>`:''}<dt>Job id</dt><dd class="mono">${esc(job.id)}</dd><dt>Message</dt><dd>${esc(job.message||'')}</dd></dl><div class="actions"><button type="button" class="button secondary small" data-git-job-open="${esc(job.id)}">Open</button>${pending?`<button type="button" class="button primary small" data-git-job-upload="${esc(job.id)}">${job.commit?'Upload now':'Retry save and upload'}</button><button type="button" class="button secondary small" data-git-job-keep="${esc(job.id)}">Keep snapshot only</button>`:''}</div></details>`;}).join('')
  ||(context.binding?'<p class="caption">No saves yet. Save progress creates a snapshot you can return to later.</p>':'<p class="caption">Saves appear here once this lab has a save location.</p>');
 gitVersionsMarkup(list,html);
}
async function gitSavesAction(button,id=activeId){
 const jobId=button.dataset.gitJobOpen||button.dataset.gitJobUpload||button.dataset.gitJobKeep;if(!jobId)return;
 const job=gitLabJobs(id).find(item=>item.id===jobId);
 if(button.dataset.gitJobOpen)return gitShowJob(jobId,job);
 if(button.dataset.gitJobUpload){const result=await json('/git/jobs/'+encodeURIComponent(jobId)+'/retry','POST',{push:true});gitRememberJob(result);await gitShowJob(result.id,result);await refresh();return;}
 if(button.dataset.gitJobKeep&&job)return gitDismissJob(job);
}
function gitRenderAdvanced(context){
 const binding=context.binding,repo=gitRepository(binding),status=context.repository_status||{};
 const set=(id,value,html=false)=>{const el=$(id);if(!el)return;if(html)el.innerHTML=value;else el.textContent=value;};
 set('git-advanced-push-url',repo.push_url?`Verified push destination: <code>${esc(repo.push_url)}</code>`:'—',true);
 set('git-advanced-branch',repo.branch||'—');set('git-advanced-owner',repo.owner||'—');set('git-advanced-path',repo.path||'—');
 set('git-advanced-status',!binding?'Not connected':status.problem?status.problem:status.ready?'Ready'+(status.head?' · at commit '+String(status.head).slice(0,10):''):'Not checked yet');
 set('git-advanced-account',binding?`Git runs on the VM as ${repo.owner||'the registered account'} with the login configured there. This app never asks for a Git password.`:'');
 if($('git-repository-advanced'))$('git-repository-advanced').hidden=!binding;
}
function gitLabName(id){return (state.labs||[]).find(lab=>lab.id===id)?.name||'This lab';}
async function gitApplyDestination(id,prefix,moveFiles,labName){
 const result=await json('/labs/'+encodeURIComponent(id)+'/git/destination','POST',{prefix,move_files:moveFiles});
 gitContexts.delete(id);gitPlacesState.selected=prefix;await refresh();await gitShowRepository(true);
 if(result.job){gitRememberJob(result.job);await gitShowJob(result.job.id,result.job);}
 notify(labName+' now saves to '+(prefix||'the repository root')+'.');
 return result;
}
async function gitUseFolder(id,path,model,tree){
 const context=await gitLoadContext(id,true),binding=context.binding,repoName=gitRepoName(tree.repository),labName=gitLabName(id),target=path||'the repository root';
 if(!binding||binding.repository?.path!==tree.repository?.path){
  // Not connected to this repository yet: choose the folder, then confirm the devices under Save settings.
  let registration=model.nodes.get(path)?.registration;
  if(!registration)registration=(await json('/git/repositories/'+encodeURIComponent(tree.repository.id)+'/folders','POST',{prefix:path})).repository;
  gitPendingSelection=registration.id;gitPlacesState.open=true;await gitShowRepository(true);
  notify('Folder chosen: '+target+'. Now tick the devices to include and choose Connect.');$('git-save-settings')?.scrollIntoView?.({block:'start',behavior:'smooth'});return;
 }
 const current=gitLabFolder(model,binding.binding_id),count=current?current.count:0,from=binding.repository?.prefix||'the repository root';
 const dialog=opDialog('git-folder-dialog','Save this lab here?',`<p><strong>${esc(labName)}</strong> will keep its progress in <code>${esc(repoName)}${path?' › '+esc(path):''}</code> from now on.</p>${count?`<label class="checkbox-label"><input id="git-move-files" type="checkbox" checked> Also move the ${count} files already saved under <code>${esc(from)}</code> into the new folder. The move is saved and uploaded to the repository right away.</label>`:'<p class="form-help">Nothing is saved under the current folder yet, so there is nothing to move.</p>'}<p class="form-help">Earlier saves stay in the history either way. Backups and the device selection do not change.</p><div class="dialog-actions"><button class="button secondary" id="git-folder-cancel">Cancel</button><button class="button primary" id="git-folder-confirm">Save here</button></div>`);
 $('git-folder-cancel').onclick=()=>dialog.close();
 $('git-folder-confirm').onclick=()=>opTask(dialog,async()=>{const move=!!$('git-move-files')?.checked;await gitApplyDestination(id,path,move,labName);dialog.close();});
}
async function gitNewFolder(id,parent,model,tree){
 const context=await gitLoadContext(id,true),binding=context.binding,repoName=gitRepoName(tree.repository),labName=gitLabName(id);
 const connected=!!binding&&binding.repository?.path===tree.repository?.path,current=connected?gitLabFolder(model,binding.binding_id):null,count=current?current.count:0,from=binding?.repository?.prefix||'the repository root';
 const dialog=opDialog('git-new-folder-dialog','New folder',`<p class="op-path">${esc(repoName)}${parent?' › '+esc(parent):''} › <em>new folder</em></p><label for="git-new-folder-name">Folder name</label><input id="git-new-folder-name" maxlength="360" placeholder="Week-04/BGP/Final-State" autocomplete="off" spellcheck="false"><p class="form-help">Letters, numbers, dashes, dots and underscores. Use <code>/</code> to create nested folders in one step. A new folder appears in the repository after the first save into it.</p><p class="git-destination-line" id="git-new-folder-result" hidden><span>Result</span><code></code></p>${connected?`<label class="checkbox-label"><input id="git-new-folder-use" type="checkbox" checked> Save ${esc(labName)} here from now on</label>${count?`<label class="checkbox-label"><input id="git-new-folder-move" type="checkbox" checked> Also move the ${count} files already saved under <code>${esc(from)}</code> into it. The move is saved and uploaded to the repository right away.</label>`:''}`:'<p class="form-help">The folder is ready for this lab. Next, tick the devices to include under Save settings and choose Connect.</p>'}<div class="dialog-actions"><button class="button secondary" id="git-new-folder-cancel">Cancel</button><button class="button primary" id="git-new-folder-confirm">Create folder</button></div>`);
 const result=$('git-new-folder-result'),resultCode=result.querySelector('code');
 const preview=()=>{const full=gitDestinationPreview(parent,$('git-new-folder-name').value);result.hidden=!full;resultCode.textContent=full?repoName+' / '+full:'';};
 $('git-new-folder-name').oninput=preview;preview();
 $('git-new-folder-cancel').onclick=()=>dialog.close();
 $('git-new-folder-confirm').onclick=()=>opTask(dialog,async()=>{
  const nested=gitFolderPath($('git-new-folder-name').value),prefix=parent?parent+'/'+nested:nested;
  if(connected&&$('git-new-folder-use')?.checked){await gitApplyDestination(id,prefix,!!$('git-new-folder-move')?.checked,labName);dialog.close();return;}
  const created=await json('/git/repositories/'+encodeURIComponent(tree.repository.id)+'/folders','POST',{prefix});
  dialog.close();gitPlacesState.selected=prefix;gitPlacesState.open=true;if(!connected)gitPendingSelection=created.repository.id;await gitShowRepository(true);notify('Folder '+prefix+' is ready.');
 });
}
async function gitSwitchRepository(id){
 const [context,catalog]=await Promise.all([gitLoadContext(id,true),(await api('/git/repositories')).json()]);
 const binding=context.binding,repositories=(catalog.repositories||[]).filter(value=>value.id!==binding?.binding_id);
 const dialog=opDialog('git-switch-dialog','Use a different repository',`<p>Pick another repository already available on this lab VM, or connect a new one by its GitHub address. Nothing already saved is deleted.</p>${repositories.length?`<label for="git-switch-id">Repositories on this VM</label><select id="git-switch-id">${repositories.map(value=>`<option value="${esc(value.id)}">${esc(gitRepoName(value))} › ${esc(value.prefix||'(whole repository)')}</option>`).join('')}</select><div class="dialog-actions"><button class="button secondary" id="git-switch-choose">Choose this repository</button></div>`:'<p class="form-help">No other repository is set up on this VM yet.</p>'}<h3>Connect a repository by URL</h3><p class="form-help">For a repository that is not on this VM yet. You need its HTTPS URL (GitHub › Code › HTTPS); the VM's existing GitHub login is used.</p><div class="dialog-actions"><button class="button primary" id="git-switch-connect">Connect by URL…</button></div>`);
 $('git-switch-choose')?.addEventListener('click',()=>opTask(dialog,async()=>{gitPendingSelection=$('git-switch-id').value;gitPlacesState.open=true;dialog.close();await gitShowRepository(true);notify('Choose the folder, then tick the devices under Save settings.');$('git-save-settings')?.scrollIntoView?.({block:'start',behavior:'smooth'});}));
 $('git-switch-connect').onclick=()=>{dialog.close();opTask(null,()=>gitConnectByUrl(id));};
}
function gitSuggestedFolder(name){return String(name||'lab').replace(/[^A-Za-z0-9_.-]+/g,'-').replace(/^[^A-Za-z0-9_]+/,'').replace(/-+$/,'').slice(0,60)||'lab';}
async function gitConnectByUrl(id,options={}){
 const context=await gitLoadContext(id,true),labName=gitLabName(id),suggested=gitSuggestedFolder(labName);
 const backupButton=$('backup'),canBackup=!!options.firstSave&&!!backupButton&&!backupButton.disabled;
 const dialog=opDialog('git-connect-dialog','Connect a repository by URL',`${options.firstSave?'<p>Ask your instructor for the repository address, or paste it below.</p>':''}<p>Paste the repository's HTTPS address from GitHub (Code › HTTPS). The lab VM's existing GitHub login is used — you are never asked for a password or token.</p><label for="git-connect-url">Repository URL</label><input id="git-connect-url" placeholder="https://github.com/you/your-lab-repo" autocomplete="off" spellcheck="false"><label for="git-connect-folder">Folder for this lab <span class="muted">optional</span></label><input id="git-connect-folder" value="${esc(suggested)}" maxlength="180" autocomplete="off" spellcheck="false"><p class="form-help">One repository can hold several labs, each in its own folder. Clear it to save at the top level of a single-lab repository.</p><label class="checkbox-label"><input id="git-connect-ack" type="checkbox"> ${esc(GIT_EXPOSURE_TEXT)}</label><details class="caption"><summary>Details</summary><p>Saves are recorded under the name and e-mail already set on the VM; if none is set, the GitHub account's name and its private no-reply address are used.</p></details><div class="dialog-actions"><button class="button secondary" id="git-connect-cancel">Cancel</button>${canBackup?'<button class="button secondary" id="git-connect-backup">Back up to this VM instead</button>':''}<button class="button primary" id="git-connect-confirm">Connect repository</button></div>`);
 $('git-connect-cancel').onclick=()=>dialog.close();
 if($('git-connect-backup'))$('git-connect-backup').onclick=()=>{dialog.close();if(typeof backupButton.onclick==='function')backupButton.onclick();};
 $('git-connect-confirm').onclick=()=>opTask(dialog,async()=>{
  const url=$('git-connect-url').value.trim(),rawFolder=$('git-connect-folder').value.trim();
  if(!/^https:\/\/[^\s/]+\/\S+/.test(url))throw new Error('Paste the HTTPS address, for example https://github.com/you/your-lab-repo.');
  // Normalise the same way as New folder so the submitted prefix matches what is validated.
  const folder=rawFolder?gitFolderPath(rawFolder):'';
  if(!$('git-connect-ack').checked)throw new Error(GIT_EXPOSURE_ERROR);
  const button=$('git-connect-confirm'),label=button.textContent;button.textContent='Connecting… this can take a minute';
  try{
   const result=await json('/labs/'+encodeURIComponent(id)+'/git/connect','POST',{url,prefix:folder,acknowledge:true,node_names:context.binding?.node_names||[],review_before_push:context.binding?.review_before_push||false});
   dialog.close();gitContexts.delete(id);gitPlacesState.selected=folder;await refresh();if(gitTabActive())await gitShowRepository(true);notify(labName+' now saves to '+gitRepoName(result.binding?.repository)+'.');
   if(options.firstSave)await gitSubmitSave(id,{target:'latest',push:true},undefined,{quiet:true});
  }finally{button.textContent=label;}
 });
}
// First save of an unbound lab: choose the repository, the folder and the devices in one dialog,
// then save. With no repository on the VM yet the connect-by-URL dialog takes over.
async function gitFirstSave(id=activeId){
 if(!id)return;
 const [context,catalog]=await Promise.all([gitLoadContext(id,true),(await api('/git/repositories')).json()]);
 if(context.binding){await gitSubmitSave(id,{target:'latest',push:true},undefined,{quiet:true});return;}
 const repositories=catalog.repositories||[],labName=gitLabName(id),supported=context.supported_nodes||[];
 if(!repositories.length){await gitConnectByUrl(id,{firstSave:true});return;}
 const checkouts=[...new Map(repositories.map(r=>[r.path,r])).values()];
 const dialog=opDialog('git-first-save-dialog',`Where should ${labName}’s progress be saved?`,`<p>Your device configurations are saved as a version in a Git repository on the lab VM and uploaded to its online copy.</p><label for="git-first-repo">Repository</label><select id="git-first-repo">${checkouts.map((r,i)=>`<option value="${esc(r.path)}" ${i===0?'selected':''}>${esc(gitRepoName(r))}</option>`).join('')}</select><label for="git-first-folder">Folder</label><div class="git-first-folder"><input id="git-first-folder" value="${esc(gitSuggestedFolder(labName))}" maxlength="360" autocomplete="off" spellcheck="false"><button type="button" class="button secondary small" id="git-first-browse">Browse…</button></div><p class="form-help">One repository can hold several labs, each in its own folder.</p><details><summary>Devices (${supported.length} included)</summary><fieldset class="git-node-scope">${supported.map(node=>`<label class="checkbox-label"><input type="checkbox" name="git-first-node" value="${esc(node.name)}" checked> <span>${esc(node.short_name||node.name)} <small>${esc(platformLabel(node.platform))}</small></span></label>`).join('')||'<p>No supported configuration devices in this lab.</p>'}</fieldset></details><label class="checkbox-label"><input id="git-first-ack" type="checkbox"> ${esc(GIT_EXPOSURE_TEXT)}</label><p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" id="git-first-cancel">Cancel</button><button type="button" class="button primary" id="git-first-confirm" ${supported.length?'':'disabled'}>Save progress</button></div>`);
 $('git-first-cancel').onclick=()=>dialog.close();
 $('git-first-browse').onclick=()=>{dialog.close();gitPendingSelection=repositories.find(r=>r.path===$('git-first-repo').value)?.id||'';gitPlacesState.open=true;gitViewLab='';gitOpenRepository();if(gitTabActive())gitShowRepository(true);};
 $('git-first-confirm').onclick=()=>opTask(dialog,async()=>{
  const path=$('git-first-repo').value,raw=$('git-first-folder').value.trim(),folder=raw?gitFolderPath(raw):'';
  const node_names=[...dialog.querySelectorAll('[name="git-first-node"]:checked')].map(input=>input.value);
  if(!node_names.length)throw new Error('Choose at least one device to include.');
  if(!$('git-first-ack').checked)throw new Error(GIT_EXPOSURE_ERROR);
  const inRepo=repositories.filter(r=>r.path===path);
  let registration=inRepo.find(r=>(r.prefix||'')===folder);
  if(!registration)registration=(await json('/git/repositories/'+encodeURIComponent(inRepo[0].id)+'/folders','POST',{prefix:folder})).repository;
  await json('/labs/'+encodeURIComponent(id)+'/git','PUT',{binding_id:registration.id,node_names,review_before_push:false});
  gitContexts.delete(id);dialog.close();await refresh();if(gitTabActive())await gitShowRepository(true);
  await gitSubmitSave(id,{target:'latest',push:true},undefined,{quiet:true});
 });
}
// options.quiet: no job dialog — the header, the status card and a toast carry the phases; the dialog
// opens on its own only when the save ends needing attention.
async function gitSubmitSave(id,values,requestId,options={}){
 if(gitSubmitting)return;
 gitSubmitting=true;renderGitProgress();
 const storageKey='git-save-request:'+id;
 // A lost response can be retried with the same request ID without capturing twice.
 let request=gitSavePayload(values,requestId||gitRequestId());
 if(!requestId){try{const previous=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(previous&&JSON.stringify({...previous,request_id:''})===JSON.stringify({...request,request_id:''}))request=previous;}catch{}sessionStorage.setItem(storageKey,JSON.stringify(request));}
 try{
  const job=await json('/labs/'+encodeURIComponent(id)+'/git/save','POST',request);
  if(!requestId)sessionStorage.removeItem(storageKey);
  gitRememberJob(job);
  if(options.quiet){notify(values.target==='checkpoint'?'Saving checkpoint…':values.target==='baseline'?'Setting the baseline…':'Saving progress…');gitStartWatch(job,{quiet:true});}
  else await gitShowJob(job.id,job);
  await refresh();return job;
 }finally{gitSubmitting=false;renderGitProgress();}
}
async function gitSaveProgress(){
 const id=activeId;if(!id)return;
 const context=await gitLoadContext(id);
 if(!context.binding){await gitFirstSave(id);return;}
 await gitSubmitSave(id,{target:'latest',push:true},undefined,{quiet:true});
}
function gitCheckpointName(value){return String(value||'').replace(/\s+/g,'-').replace(/[^A-Za-z0-9_-]/g,'').replace(/^[_-]+/,'');}
async function gitSaveOptions(target,id=activeId){
 const context=await gitLoadContext(id,true);if(!context.binding){await gitFirstSave(id);return;}
 const baseline=target==='baseline',checkpoint=target==='checkpoint',local=target==='local';
 const label=baseline?'Set baseline':checkpoint?'Create checkpoint':local?'Save on this VM only':'Save progress';
 const backups=gitCompleteBackups(state.jobs||[],id,context.binding.node_names),baselineRevision=context.repository_status?.baseline_revision||'',total=(context.binding.node_names||[]).length;
 const dialog=opDialog('git-save-options',label,`<p class="op-path">Saving to ${esc(gitFolderWords(context.binding))}</p>
 ${baseline?`<p>The baseline is the reference version for this lab (for example the instructor's starting state). Pick one of the complete saves below — no device is read or changed.</p><label for="git-baseline-job">Use this saved configuration</label><select id="git-baseline-job" required><option value="">Choose a saved configuration</option>${backups.map(job=>`<option value="${esc(job.id)}" title="${esc(job.id)}">${esc(gitWhen(job.created))} · ${job.nodes.length} devices</option>`).join('')}</select>${backups.length?'':`<p class="op-notice">No complete save includes all ${total} devices yet. Save progress first, then set the baseline.</p>`}<details class="caption"><summary>Details</summary><p>Setting the baseline does not check whether the version can be applied to a running lab.</p></details>${baselineRevision?'<label class="checkbox-label"><input type="checkbox" id="git-replace-baseline"> Replace the current baseline with this version (the previous one stays in history)</label>':''}`:`<p>${local?'Saves a snapshot on the lab VM without uploading it. You can upload it later from Recent saves.':'A checkpoint is a named version you can return to later.'}</p>`}
 ${checkpoint?'<label for="git-checkpoint-name">Checkpoint name</label><input id="git-checkpoint-name" maxlength="100" placeholder="OSPF-complete" autocomplete="off" spellcheck="false"><p class="form-help">Letters, numbers, underscores or hyphens. Each name can be used once.</p><p class="caption" id="git-checkpoint-preview" hidden></p>':''}
 <label for="git-save-note">${checkpoint?'What did you get working? (optional)':'Note (optional)'}</label><input id="git-save-note" maxlength="300" placeholder="${checkpoint?'For example: OSPF adjacencies up on every router':'What changed in this experiment?'}">
 ${local?'':'<label class="checkbox-label"><input id="git-save-push" type="checkbox" checked> Upload after saving'+(context.binding.review_before_push?' (you asked to review changes first, so the upload waits for your review)':'')+'</label>'}
 <details><summary>Devices removed from this lab</summary><label class="checkbox-label"><input id="git-allow-removed" type="checkbox"> Also remove saved files for devices that are no longer included (their older versions stay in history)</label></details>
 <div class="dialog-actions"><button class="button secondary" id="git-save-cancel">Cancel</button><button class="button primary" id="git-save-confirm" ${baseline&&!backups.length?'disabled':''}>${label}</button></div>`);
 const requestId=gitRequestId();$('git-save-cancel').onclick=()=>dialog.close();
 const nameField=$('git-checkpoint-name');
 if(nameField){nameField.oninput=()=>{const clean=gitCheckpointName(nameField.value);if(nameField.value!==clean)nameField.value=clean;const preview=$('git-checkpoint-preview');if(preview){preview.textContent=clean?'Saved as: '+clean:'';preview.hidden=!clean;}};}
 $('git-save-confirm').onclick=()=>opTask(dialog,async()=>{
  const name=gitCheckpointName($('git-checkpoint-name')?.value.trim()||''),backup=$('git-baseline-job')?.value||'';
  if(checkpoint&&!/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(name))throw new Error('Enter a checkpoint name using letters, numbers, underscores or hyphens.');
  if(baseline&&!backup)throw new Error('Choose a saved configuration.');
  if(baselineRevision&&baseline&&!$('git-replace-baseline').checked)throw new Error('Tick the box to replace the current baseline.');
  const values={target:local?'latest':target,checkpoint:name,push:local?false:$('git-save-push').checked,note:$('git-save-note').value.trim(),backup_job_id:backup,replace_baseline:baseline&&!!baselineRevision,expected_baseline:baseline?baselineRevision:'',allow_removed:$('git-allow-removed').checked};
  await gitSubmitSave(id,values,requestId,{quiet:true});dialog.close();
 });
}
function gitRememberJob(job){
 const context=gitContexts.get(job.lab_id);if(context)context.jobs=[job,...(context.jobs||[]).filter(item=>item.id!==job.id)];
 state.git_jobs=[job,...(state.git_jobs||[]).filter(item=>item.id!==job.id)];
}
function gitJobTitle(job){if(gitActiveStates.has(job.status))return 'Saving progress';if(['synced','unchanged','committed','review_pending'].includes(job.status))return 'Progress saved';if(['failed','capture_incomplete'].includes(job.status))return 'Save failed';if(job.target==='update')return 'Repository update';return 'Save needs attention';}
async function gitShowJob(id,known){
 const job=known||await(await api('/git/jobs/'+encodeURIComponent(id))).json();gitRememberJob(job);gitDialogJob=id;
 const dialog=opDialog('git-job-dialog',gitJobTitle(job),'<div id="git-job-detail"></div><div class="actions" id="git-job-actions"></div>');
 dialog.onclose=()=>{gitDialogJob='';};gitRenderJob(job);renderGitProgress();
 if(gitActiveStates.has(job.status))gitStartWatch(job);
}
function gitRenderJob(job){
 if(gitDialogJob!==job.id||!$('git-job-dialog')?.open)return;
 const heading=typeof $('git-job-dialog').querySelector==='function'?$('git-job-dialog').querySelector('h2'):null;if(heading)heading.textContent=gitJobTitle(job);
 $('git-job-detail').innerHTML=gitJobMarkup(job);
 const pending=gitPendingStates.has(job.status),active=gitActiveStates.has(job.status),hasCommit=!!job.commit;
 $('git-job-actions').innerHTML=`${job.backup_job_id?'<button class="button secondary" data-git-job-action="backup">View configuration backup</button>':''}${hasCommit?'<button class="button secondary" data-git-job-action="review">Review changes</button>':''}${pending?`<button class="button primary" data-git-job-action="push">${hasCommit?'Upload now':'Retry save and upload'}</button>${!hasCommit?'<button class="button secondary" data-git-job-action="local">Retry save on this VM only</button>':''}<button class="button secondary" data-git-job-action="dismiss">Keep snapshot only</button>`:''}${active?'<p class="form-help" role="status">You can close this window. The save continues in the background and its result appears under Progress › Recent saves.</p>':''}`;
 for(const button of $('git-job-actions').querySelectorAll('[data-git-job-action]'))button.onclick=()=>opTask($('git-job-dialog'),async()=>{
  const action=button.dataset.gitJobAction;
  if(action==='backup'){$('git-job-dialog').close();selectLab(job.lab_id);showTab('backups');const capture=[...document.querySelectorAll('.job')].find(item=>item.dataset.job===job.backup_job_id);if(capture){capture.open=true;capture.scrollIntoView({block:'center',behavior:'smooth'});}return;}
  if(action==='review'){await gitReviewJob(job);return;}
  if(action==='dismiss'){await gitDismissJob(job);return;}
  const result=await json('/git/jobs/'+encodeURIComponent(job.id)+'/retry','POST',{push:action==='push'});gitRememberJob(result);await gitShowJob(result.id,result);await refresh();
 });
}
async function gitReviewJob(job){
 const result=await json('/labs/'+encodeURIComponent(job.lab_id)+'/git/compare','POST',{job_id:job.id});
 const dialog=opDialog('git-diff-dialog','Review this save',`<p>What this save changed compared with the previous one. Configuration files may contain passwords or keys.</p><details class="caption"><summary>Details</summary><p>Commit <code>${esc(job.commit)}</code></p></details>${gitDiffMarkup(result.files,'Before this save','This save')}<div class="dialog-actions"><button class="button secondary" id="git-review-files">Open the full saved version</button>${gitPendingStates.has(job.status)?'<button class="button primary" id="git-review-push">Upload now</button>':''}</div>`);
 $('git-review-files').onclick=()=>opTask(dialog,()=>gitViewVersion(job.lab_id,{commit:job.commit,path:gitTargetPath(job)}));
 $('git-review-push')?.addEventListener('click',()=>opTask(dialog,async()=>{const next=await json('/git/jobs/'+encodeURIComponent(job.id)+'/retry','POST',{push:true});dialog.close();gitRememberJob(next);await gitShowJob(next.id,next);await refresh();}));
}
function gitDoneToast(job){
 if(job.target==='checkpoint')return `Checkpoint '${job.checkpoint||''}' saved.`;
 if(job.target==='baseline')return 'Baseline set.';
 if(job.status==='synced')return 'Saved to Git just now.';
 if(job.status==='unchanged')return 'Saved to Git — nothing had changed since your last save.';
 if(job.status==='committed')return 'Saved on this VM. Upload it when you are ready.';
 return gitSaveSentence(job)+'.';
}
function gitStartWatch(job,options={}){
 if(gitWatch?.id===job.id)return;clearTimeout(gitWatchTimer);const watch={id:job.id,lab_id:job.lab_id,quiet:!!options.quiet};gitWatch=watch;
 const poll=async()=>{
  if(gitWatch!==watch)return;
  try{
   const value=await(await api('/git/jobs/'+encodeURIComponent(job.id))).json();if(gitWatch!==watch)return;
   gitRememberJob(value);gitRenderJob(value);renderGitProgress();
   if(gitActiveStates.has(value.status))gitWatchTimer=setTimeout(poll,1500);
   else{
    gitWatch=null;await refresh();
    if(watch.quiet){if(['push_pending','export_pending','failed','capture_incomplete','interrupted','review_pending'].includes(value.status))await gitShowJob(value.id,value);else notify(gitDoneToast(value));}
    if(gitTabActive()&&activeId===value.lab_id)await gitShowRepository(true);
   }
  }catch(error){if(gitWatch===watch){gitWatch=null;if(gitDialogJob===job.id&&$('git-job-dialog')?.open)$('git-job-dialog').querySelector('.form-error').textContent='The save status could not be refreshed. Close and reopen this save to check it. ('+error.message+')';else if(watch.quiet)notify('The save status could not be refreshed. Open the save under Progress › Recent saves to check it.');}}
 };gitWatchTimer=setTimeout(poll,1000);
}
async function gitDismissJob(job){
 const dialog=opDialog('git-dismiss-dialog','Keep this snapshot only?',`<p>The configuration backup and anything already saved stay as they are. The manager just stops waiting for this save to be uploaded, so the lab can be disconnected or removed.</p><p>Nothing is deleted; a save kept on the VM may be included in a later upload.</p><details class="caption"><summary>Details</summary><p>${esc(gitLabel(job))} · ${esc(job.id)}</p></details><div class="dialog-actions"><button class="button secondary" id="git-dismiss-cancel">Cancel</button><button class="button primary" id="git-dismiss-confirm">Keep snapshot only</button></div>`);
 $('git-dismiss-cancel').onclick=()=>dialog.close();$('git-dismiss-confirm').onclick=()=>opTask(dialog,async()=>{const result=await json('/git/jobs/'+encodeURIComponent(job.id)+'/dismiss','POST',{acknowledge:true});gitRememberJob(result);dialog.close();await gitShowJob(result.id,result);await refresh();if(gitTabActive())await gitShowRepository(true);});
}
async function gitPushPending(id=activeId){
 const context=await gitLoadContext(id,true),pending=gitLabJobs(id,context).filter(job=>gitPendingStates.has(job.status));
 if(!pending.length){notify('Nothing is waiting to be uploaded.');return;}
 if(pending.length===1){await gitShowJob(pending[0].id,pending[0]);return;}
 const dialog=opDialog('git-pending-dialog','Saves waiting to be uploaded',`<div class="op-history">${pending.map(job=>`<button class="button secondary" data-git-pending="${esc(job.id)}">${esc(gitSaveSentence(job))} · ${esc(gitWhen(job.finished||job.created))}</button>`).join('')}</div>`);
 for(const button of dialog.querySelectorAll('[data-git-pending]'))button.onclick=()=>opTask(dialog,()=>gitShowJob(button.dataset.gitPending));
}
async function gitUpdateRemote(id=activeId){
 const dialog=opDialog('git-update-dialog','Update from the repository','<p>Downloads the newest files from the online repository — for example versions your instructor added. Your running devices are not changed.</p><p class="form-help">If the VM\'s copy can\'t be updated automatically, nothing changes and the reason is shown.</p><div class="dialog-actions"><button class="button secondary" id="git-update-cancel">Cancel</button><button class="button primary" id="git-update-confirm">Update now</button></div>');
 $('git-update-cancel').onclick=()=>dialog.close();
 $('git-update-confirm').onclick=()=>opTask(dialog,async()=>{const result=await json('/labs/'+encodeURIComponent(id)+'/git/update','POST',{});dialog.close();await gitLoadContext(id,true);if(activeId===id&&gitTabActive())await gitShowRepository(true);notify(result.message||'Repository is up to date.');});
}
async function gitUnlink(id=activeId){
 const context=gitContexts.get(id),repoName=gitRepoName(gitRepository(context?.binding)),pending=gitLabJobs(id,context).some(job=>gitPendingStates.has(job.status));
 const dialog=opDialog('git-unlink-dialog',`Disconnect this lab from ${repoName}?`,`<p>Nothing is deleted. Your saved progress stays in ${esc(repoName)} and the configuration backups stay on this VM. To save again, choose a save location first.</p>${pending?'<p class="op-notice">Upload the save that is still waiting, or choose Keep snapshot only, before disconnecting.</p>':''}<div class="dialog-actions"><button class="button secondary" id="git-unlink-cancel">Cancel</button><button class="button danger" id="git-unlink-confirm">Disconnect</button></div>`);
 $('git-unlink-cancel').onclick=()=>dialog.close();$('git-unlink-confirm').onclick=()=>opTask(dialog,async()=>{await json('/labs/'+encodeURIComponent(id)+'/git/unlink','POST',{});dialog.close();gitContexts.delete(id);await refresh();await gitShowRepository(true);});
}
async function gitHistory(id=activeId){
 const data=await(await api('/labs/'+encodeURIComponent(id)+'/git/history')).json();
 const versions=data.versions||[],commits=data.commits||[];
 const dialog=opDialog('git-history-dialog','Saved versions & history',`<p>Every saved version of this lab and of the other labs in this repository. Open one to view, download or compare it, or apply it to the running lab (Junos only — the current configuration is backed up first and nothing reboots).</p><h3>Saved versions</h3><div class="op-history">${versions.map((version,index)=>`<button class="button secondary" data-git-version="${index}"><strong>${esc(version.label||version.name||version.path)}</strong><small>${esc(version.path)}${version.connected?' · this lab':''}</small></button>`).join('')||'<p>Nothing saved yet.</p>'}</div><h3>Save history</h3><div class="op-history">${commits.map((commit,index)=>`<button class="button secondary" data-git-commit="${index}"><strong>${esc(commit.message)}</strong><small>${esc(commit.time?gitWhen(commit.time*1000):'')} · <span class="mono">${esc((commit.commit||'').slice(0,10))}</span></small></button>`).join('')||'<p>No save history yet.</p>'}</div>`);
 for(const button of dialog.querySelectorAll('[data-git-version]'))button.onclick=()=>opTask(dialog,()=>gitViewVersion(id,versions[Number(button.dataset.gitVersion)]));
 for(const button of dialog.querySelectorAll('[data-git-commit]'))button.onclick=()=>opTask(dialog,()=>gitOpenCommit(id,commits[Number(button.dataset.gitCommit)],versions));
}
async function gitOpenCommit(id,commit,versions){
 const matching=gitLabJobs(id).filter(job=>job.commit===commit.commit&&['latest','baseline','checkpoint'].includes(job.target));
 // An unchanged save can reuse HEAD without producing the selected commit.
 const known=matching.find(job=>Array.isArray(job.changed_files)&&job.changed_files.length)||matching.find(job=>job.target==='latest');
 if(known)return gitViewVersion(id,{commit:commit.commit,path:gitTargetPath(known)});
 const paths=[...new Set(['latest','baseline',...versions.map(version=>version.path)])];
 const dialog=opDialog('git-commit-dialog','Which saved version?',`<p>${esc(commit.message||'Older save')}</p><p class="op-path">${esc(commit.commit)}</p><label for="git-commit-path">Which folder was saved at this point?</label><select id="git-commit-path">${paths.map(folder=>`<option value="${esc(folder)}">${esc(folder)}</option>`).join('')}</select><p class="form-help">Only folders that already existed at this save can be opened.</p><button class="button primary" id="git-commit-view">Open this version</button>`);
 $('git-commit-view').onclick=()=>opTask(dialog,()=>gitViewVersion(id,{commit:commit.commit,path:$('git-commit-path').value}));
}
async function gitCompareVersion(id,request,label){
 const result=await json('/labs/'+encodeURIComponent(id)+'/git/compare','POST',{commit:request.commit,path:request.path});
 opDialog('git-diff-dialog','Compared with your latest save',`<p>Shows how <strong>${esc(label||request.path)}</strong> differs from the last time you saved progress. To see what would change on the devices themselves, choose Apply to running lab… — the review lists the changes per device before anything is applied.</p>${gitDiffMarkup(result.files,'This version','Your latest save')}`);
}
async function gitViewVersion(id,version){
 const request={commit:version.commit,path:version.path},data=await json('/labs/'+encodeURIComponent(id)+'/git/version','POST',request);
 const files=data.files||[],name=version.label||version.name||version.path;
 const restoreBtn=data.restore_supported&&typeof restoreFromVersion==='function'?'<button class="button danger" id="git-version-restore">Apply to running lab…</button>':'';
 const restoreNote=data.restore_supported
  ?'<p class="form-help">This saved version can be applied to the running lab. The current configuration is backed up first and the devices are not rebooted.</p>'
  :'<p class="form-help">View or download only — this version was saved before live apply was available, so it cannot be loaded onto a running device.</p>';
 const dialog=opDialog('git-version-dialog','Saved version',`<p class="op-path">${esc(name)}</p><details class="caption"><summary>Details</summary><p class="mono">${esc(version.path)} · ${esc(version.commit)}</p></details><div class="actions">${restoreBtn}<button class="button secondary" id="git-version-compare">Compare with my latest save</button><button class="button primary" id="git-version-download">Download (ZIP)</button></div>${restoreNote}<details><summary>Technical details</summary><pre class="git-file-content" tabindex="0">${esc(JSON.stringify(data.manifest,null,2))}</pre></details><div class="git-version-files">${files.map(file=>`<details><summary>${esc(file.name)}</summary><pre class="git-file-content" tabindex="0">${esc(file.text)}</pre></details>`).join('')||'<p>No configuration files in this version.</p>'}</div>`);
 if(restoreBtn)$('git-version-restore').onclick=()=>opTask(dialog,async()=>{dialog.close();await restoreFromVersion(id,{type:'git',commit:version.commit,path:version.path},name);});
 $('git-version-compare').onclick=()=>opTask(dialog,()=>gitCompareVersion(id,request,name));
 $('git-version-download').onclick=()=>opTask(dialog,async()=>{const response=await api('/labs/'+encodeURIComponent(id)+'/git/version/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=attachmentName(response,'lab-version.zip');document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
}
function gitRunAction(action,id=activeId){
 if($('git-save-menu'))$('git-save-menu').open=false;
 if(typeof closeMenus==='function')closeMenus();
 return opTask(null,async()=>{
  if(action==='settings'){gitOpenRepository();return;}
  if(action==='refresh'){await gitShowRepository(true);return;}
  if(action==='load'){if(typeof showTab==='function')showTab('progress');const list=$('git-saved-versions');if(list&&typeof list.scrollIntoView==='function')list.scrollIntoView({block:'start',behavior:'smooth'});return;}
  // Every folder of the repository, with its own Apply, without changing where this lab saves.
  if(action==='browse'){const folder=$('git-change-folder');if(folder){folder.open=true;if(typeof folder.scrollIntoView==='function')folder.scrollIntoView({block:'start',behavior:'smooth'});}return;}
  if(action==='history'){await gitHistory(id);return;}
  if(action==='push'){await gitPushPending(id);return;}
  if(action==='update'){await gitUpdateRemote(id);return;}
  if(action==='unlink'){await gitUnlink(id);return;}
  if(action==='switch'){await gitSwitchRepository(id);return;}
  if(action==='connect'){await gitConnectByUrl(id);return;}
  await gitSaveOptions(action,id);
 });
}
if(typeof $==='function'&&$('git-progress-bar')){
 $('git-save-progress').onclick=()=>opTask(null,gitSaveProgress);
 if($('progress-save'))$('progress-save').onclick=()=>opTask(null,gitSaveProgress);
 $('git-repository-refresh').onclick=()=>opTask(null,()=>gitShowRepository(true));
 $('git-open-settings').onclick=gitOpenRepository;
 for(const button of gitActionButtons())button.onclick=()=>gitRunAction(button.dataset.gitAction);
 if($('git-saved-versions'))$('git-saved-versions').addEventListener('click',event=>{const button=event.target.closest('[data-git-version-action]');if(!button)return;const row=gitVersionRows[Number(button.dataset.gitVersion)];if(row)gitVersionAction(button.dataset.gitVersionAction,row);});
 if($('git-saves-list'))$('git-saves-list').addEventListener('click',event=>{const button=event.target.closest('[data-git-job-open],[data-git-job-upload],[data-git-job-keep]');if(button)opTask(null,()=>gitSavesAction(button));});
 document.addEventListener('click',event=>{const menu=$('git-save-menu');if(menu?.open&&!menu.contains(event.target))menu.open=false;});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('git-save-menu'))$('git-save-menu').open=false;});
}
