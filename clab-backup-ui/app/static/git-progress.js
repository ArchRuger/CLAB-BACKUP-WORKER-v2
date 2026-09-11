'use strict';
// Git credentials stay with the registered VM account. The browser sends only
// registered binding IDs and structured actions; it never assembles shell commands.
const gitActiveStates=new Set(['queued','capturing','exporting','pushing']);
const gitPendingStates=new Set(['committed','push_pending','export_pending','review_pending','interrupted']);
const gitStateLabels={queued:'Waiting to save',capturing:'Capturing configurations',exporting:'Saving to repository',pushing:'Pushing to remote',synced:'Saved to Git',committed:'Saved on VM · not pushed',unchanged:'No configuration changes',push_pending:'Saved on VM · push pending',export_pending:'Snapshot saved · export pending',review_pending:'Saved on VM · review before pushing',interrupted:'Save interrupted · snapshot retained',capture_incomplete:'Capture incomplete',failed:'Save needs attention',dismissed:'Snapshot kept locally'};
const gitContexts=new Map(),gitLoads=new Map();
let gitViewLab='',gitViewRequest=0,gitWatch=null,gitWatchTimer=null,gitDialogJob='',gitSubmitting=false;
function gitLabel(job){return gitStateLabels[job?.status]||job?.status||'No progress saved yet';}
function gitJobTime(job){return job?.created||job?.finished||'';}
function gitTime(value){return utcDisplay(typeof value==='number'?value*1000:value);}
function gitLabJobs(id,context=gitContexts.get(id)){
 const jobs=new Map();for(const job of [...(context?.jobs||[]),...(state.git_jobs||[])])if(!job.lab_id||job.lab_id===id)jobs.set(job.id,{...jobs.get(job.id),...job});
 return [...jobs.values()].sort((a,b)=>gitJobTime(b).localeCompare(gitJobTime(a)));
}
function gitRepository(binding){return binding?.repository||{};}
function gitBindingChanged(binding,repository){return !binding||!repository||binding.binding_id!==repository.id||binding.revision!==repository.revision;}
function gitRegisteredDestination(repo){return [repo.owner,repo.path,[repo.remote,repo.branch].filter(Boolean).join(' / '),repo.push_url?'Push to '+repo.push_url:'',repo.prefix||'repository root'].filter(Boolean).join(' · ');}
function gitDestination(binding){const repo=gitRepository(binding);return [repo.label||repo.path||binding?.binding_id,repo.branch,repo.prefix?repo.prefix.replace(/\/$/,'')+'/latest/':'latest/'].filter(Boolean).join(' · ');}
function gitTargetPath(job){return job.target==='checkpoint'?'checkpoints/'+job.checkpoint:job.target||'latest';}
function gitCompleteBackups(jobs,id,names){
 const required=new Set(names||[]);
 return jobs.filter(job=>required.size&&job.lab_id===id&&job.operation==='backup'&&['succeeded','partial'].includes(job.status)&&job.nodes?.length===required.size&&new Set(job.nodes.map(node=>node.name)).size===required.size&&job.nodes.every(node=>node.status==='succeeded'&&required.has(node.name)));
}
function gitSavePayload(values,requestId){return {request_id:requestId,target:values.target||'latest',checkpoint:values.checkpoint||'',push:values.push!==false,note:values.note||'',backup_job_id:values.backup_job_id||'',replace_baseline:values.replace_baseline===true,expected_baseline:values.expected_baseline||'',allow_removed:values.allow_removed===true};}
function gitRequestId(){const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return Array.from(bytes,n=>n.toString(16).padStart(2,'0')).join('');}
function gitJobMarkup(job){
 if(!job)return '<p>No Git saves yet. Save progress captures every device selected in Git repository settings.</p>';
 const changed=Array.isArray(job.changed_files)?job.changed_files.length:job.changed_files;
 return `<div class="git-job-summary"><span class="badge ${gitActiveStates.has(job.status)?'running':['synced','unchanged'].includes(job.status)?'good':['failed','capture_incomplete'].includes(job.status)?'bad':'warn'}">${esc(gitLabel(job))}</span><p>${esc(job.message||'')}</p><dl class="health-grid"><dt>Saved target</dt><dd>${esc(job.target==='checkpoint'?'checkpoints/'+(job.checkpoint||''):job.target||'latest')}</dd><dt>Started</dt><dd>${esc(utcDisplay(job.created))}</dd>${job.commit?`<dt>Commit</dt><dd class="mono">${esc(job.commit)}</dd>`:''}${changed!==undefined?`<dt>Changed files</dt><dd>${esc(changed)}</dd>`:''}</dl></div>`;
}
function gitDiffMarkup(files,beforeLabel='Selected version',afterLabel='Latest saved version'){
 if(!files?.length)return '<p>No file differences in this version.</p>';
 return files.map(file=>`<details class="git-diff-file"><summary>${esc(file.name)} <span class="badge">${esc(file.status||'changed')}</span></summary><div class="git-diff-columns"><section><h3>${esc(beforeLabel)}</h3><pre tabindex="0">${esc(file.before??'File absent')}</pre></section><section><h3>${esc(afterLabel)}</h3><pre tabindex="0">${esc(file.after??'File absent')}</pre></section></div></details>`).join('');
}
async function gitLoadContext(id,force=false){
 if(gitLoads.has(id))return gitLoads.get(id);
 if(!force&&gitContexts.has(id))return gitContexts.get(id);
 const pending=(async()=>{const value=await(await api('/labs/'+encodeURIComponent(id)+'/git')).json();gitContexts.set(id,value);return value;})();
 gitLoads.set(id,pending);try{return await pending;}finally{gitLoads.delete(id);}
}
function renderGitProgress(){
 const bar=$('git-progress-bar');if(!bar)return;
 const lab=current();bar.hidden=!lab;if(!lab){clearTimeout(gitWatchTimer);gitWatch=null;return;}
 const context=gitContexts.get(lab.id),binding=context?.binding||lab.git_binding;
 const jobs=gitLabJobs(lab.id),last=jobs[0]||lab.git_status,active=jobs.find(job=>gitActiveStates.has(job.status));
 $('git-destination').textContent=binding?gitDestination(binding):'Connect a repository to save your lab progress';
 $('git-progress-status').textContent=last?[gitLabel(last),last.commit?last.commit.slice(0,10):'',last.created?utcDisplay(last.created):''].filter(Boolean).join(' · '):'Capture configurations, commit and push in one step.';
 $('git-save-progress').textContent=binding?'Save progress':'Connect Git repository';
 $('git-save-progress').disabled=gitSubmitting||!!active||(!!binding&&busy());
 $('git-save-progress').title=binding?'Capture the configured Git devices, commit and push to '+gitDestination(binding):'Choose a registered VM repository';
 $('git-save-menu').hidden=!binding;
 for(const button of $('git-save-menu').querySelectorAll('[data-git-action]'))button.disabled=(gitSubmitting||!!active)&&!['history','load','settings'].includes(button.dataset.gitAction);
 if(gitWatch&&gitWatch.lab_id!==lab.id&&!$('git-job-dialog')?.open){clearTimeout(gitWatchTimer);gitWatch=null;}
 if(active&&!gitWatch)gitStartWatch(active);
}
function gitOpenRepository(){showTab('git');if($('extra-views'))$('extra-views').open=false;}
async function gitShowRepository(force=false){
 const id=activeId,container=$('git-repository-content');if(!id||!container)return;
 if(gitViewLab===id&&!force)return;
 gitViewLab=id;const request=++gitViewRequest;container.innerHTML='<p role="status">Reading registered repositories and saved progress…</p>';
 try{
  const [context,catalog]=await Promise.all([gitLoadContext(id,true),(await api('/git/repositories')).json()]);
  if(request!==gitViewRequest||activeId!==id)return;
  gitRenderRepository(id,context,catalog);renderGitProgress();
 }catch(error){if(request===gitViewRequest)container.innerHTML=`<p class="form-error" role="alert">${esc(error.message)}</p><p>Check the VM connection and Git helper installation, then choose Refresh status.</p>`;}
}
function gitRenderRepository(id,context,catalog){
 const binding=context.binding,repo=gitRepository(binding),repositories=catalog.repositories||[],supported=context.supported_nodes||[],excluded=context.unsupported_nodes||[];
 const selected=new Set(binding?.node_names||supported.map(node=>node.name)),status=context.repository_status||{};
 const activeBinding=!!binding;
 $('git-repository-content').innerHTML=`${status.problem?`<p class="op-notice" role="status">${esc(status.problem)}</p>`:''}
 ${activeBinding?`<div class="git-repository-card"><h3>${esc(repo.label||binding.binding_id)}</h3><p class="op-path">${esc(repo.owner||'')} · ${esc(repo.path||'')}</p><p>${esc(repo.remote||'')} / ${esc(repo.branch||'')} · ${esc(repo.prefix||'(repository root)')}</p>${repo.push_url?`<p class="op-path">Verified push destination: <code>${esc(repo.push_url)}</code></p>`:''}<p class="form-help">Save progress includes ${selected.size} configured devices. Scheduled backup selection is independent.</p><div class="actions"><button class="button secondary" data-git-repo-action="history">View changes / History</button><button class="button secondary" data-git-repo-action="update">Update from remote</button><button class="button secondary" data-git-repo-action="unlink">Disconnect repository</button></div></div>`:''}
 ${repositories.length?`<form id="git-binding-form" class="git-binding-form"><h3>${activeBinding?'Repository settings':'Connect this lab to Git'}</h3><label for="git-binding-id">Registered working repository</label><select id="git-binding-id" required>${!activeBinding?'<option value="">Choose a repository</option>':''}${repositories.map(value=>`<option value="${esc(value.id)}" ${value.id===binding?.binding_id?'selected':''}>${esc(value.label||value.path)} · ${esc(value.owner)} · ${esc(value.branch)}</option>`).join('')}</select><p id="git-binding-destination" class="op-path"></p>
 <fieldset class="git-node-scope"><legend>Devices included in every progress save</legend>${supported.map(node=>`<label class="checkbox-label"><input type="checkbox" name="git-node" value="${esc(node.name)}" ${selected.has(node.name)?'checked':''}> <span>${esc(node.short_name||node.name)} <small>${esc(platformLabel(node.platform))}</small></span></label>`).join('')||'<p>No supported configuration devices in this lab.</p>'}</fieldset>
 ${excluded.length?`<p class="form-help">Unsupported devices are excluded: ${excluded.map(node=>esc(node.short_name||node.name||node)).join(', ')}.</p>`:''}
 <p class="form-help">An offline included device makes the capture incomplete. Its previous configuration is never silently substituted.</p>
 <label class="checkbox-label"><input id="git-review-before-push" type="checkbox" ${binding?.review_before_push?'checked':''}> Review changes before pushing</label>
 <label id="git-exposure-label" class="checkbox-label"><input id="git-exposure" type="checkbox"> I understand that full device configurations, including any secrets they contain, will be committed and pushed to this repository.</label>
 <p class="form-help">Git runs as the registered VM account using its existing Git login and commit identity. Configure that login on the VM outside this application.</p><p class="form-error" role="alert"></p><div class="actions"><button type="submit" class="button primary" ${supported.length?'':'disabled'}>${activeBinding?'Save repository settings':'Connect repository'}</button></div></form>`:`<div class="blank-state"><h3>No repositories registered on this VM</h3><p>Log in to Git on the VM as the repository owner, then register an existing checkout with the helper:</p><pre class="git-setup-command">sudo bash deploy/setup-git.sh --owner ben --repo /home/ben/labs/BENS-BGP-LAB</pre><p>Use your VM account and repository path. Refresh status after setup.</p></div>`}
 <section class="git-saves"><h3>Progress saves</h3><p>Every save links to its original configuration capture. Git history contains committed versions.</p><div id="git-saves-list">${gitLabJobs(id,context).map(job=>`<button class="git-saved-job" data-git-job="${esc(job.id)}"><strong>${esc(gitLabel(job))}</strong><span>${esc(utcDisplay(job.created))} · ${esc(job.target||'latest')}${job.checkpoint?' / '+esc(job.checkpoint):''}${job.commit?' · '+esc(job.commit.slice(0,10)):''}</span></button>`).join('')||'<p>No Git progress saves yet.</p>'}</div></section>`;
 const form=$('git-binding-form');
 if(form){
  const change=()=>{const selectedRepo=repositories.find(value=>value.id===$('git-binding-id').value);$('git-binding-destination').textContent=selectedRepo?gitRegisteredDestination(selectedRepo):'';const changed=gitBindingChanged(binding,selectedRepo);$('git-exposure-label').hidden=!changed;$('git-exposure').required=changed;$('git-exposure').checked=false;};
  $('git-binding-id').onchange=change;change();
  form.onsubmit=event=>{event.preventDefault();opTask(form,async()=>{
   const node_names=[...form.querySelectorAll('[name="git-node"]:checked')].map(input=>input.value);
   if(!node_names.length)throw new Error('Select at least one supported device for progress saves.');
   if(gitBindingChanged(binding,repositories.find(value=>value.id===$('git-binding-id').value))&&!$('git-exposure').checked)throw new Error('Acknowledge exporting full configurations to the selected repository.');
   await json('/labs/'+encodeURIComponent(id)+'/git','PUT',{binding_id:$('git-binding-id').value,node_names,review_before_push:$('git-review-before-push').checked});
   await gitShowRepository(true);await refresh();notify('Git repository connected. Save progress is ready.');
  });};
 }
 for(const button of $('git-repository-content').querySelectorAll('[data-git-repo-action]'))button.onclick=()=>gitRunAction(button.dataset.gitRepoAction,id);
 for(const button of $('git-repository-content').querySelectorAll('[data-git-job]'))button.onclick=()=>opTask(null,()=>gitShowJob(button.dataset.gitJob));
}
async function gitSubmitSave(id,values,requestId){
 if(gitSubmitting)return;
 gitSubmitting=true;renderGitProgress();
 const storageKey='git-save-request:'+id;
 // A lost response can be retried with the same request ID without capturing twice.
 let request=gitSavePayload(values,requestId||gitRequestId());
 if(!requestId){try{const previous=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(previous&&JSON.stringify({...previous,request_id:''})===JSON.stringify({...request,request_id:''}))request=previous;}catch{}sessionStorage.setItem(storageKey,JSON.stringify(request));}
 try{
  const job=await json('/labs/'+encodeURIComponent(id)+'/git/save','POST',request);
  if(!requestId)sessionStorage.removeItem(storageKey);
  gitRememberJob(job);await gitShowJob(job.id,job);await refresh();return job;
 }finally{gitSubmitting=false;renderGitProgress();}
}
async function gitSaveProgress(){
 const id=activeId;if(!id)return;
 const context=await gitLoadContext(id);
 if(!context.binding){gitOpenRepository();return;}
 await gitSubmitSave(id,{target:'latest',push:true});
}
async function gitSaveOptions(target,id=activeId){
 const context=await gitLoadContext(id,true);if(!context.binding){gitOpenRepository();return;}
 const baseline=target==='baseline',checkpoint=target==='checkpoint',local=target==='local';
 const label=baseline?'Set baseline':checkpoint?'Save checkpoint':local?'Save locally':'Save progress';
 const backups=gitCompleteBackups(state.jobs||[],id,context.binding.node_names),baselineRevision=context.repository_status?.baseline_revision||'';
 const dialog=opDialog('git-save-options',label,`<p class="op-path">${esc(gitDestination(context.binding))}</p>
 ${baseline?`<p>Choose one complete recorded capture for the baseline. This does not recapture devices or apply configurations.</p><label for="git-baseline-job">Saved configuration capture</label><select id="git-baseline-job" required><option value="">Choose a complete backup</option>${backups.map(job=>`<option value="${esc(job.id)}">${esc(utcDisplay(job.created))} · ${job.nodes.length} devices · ${esc(job.id)}</option>`).join('')}</select>${backups.length?'':'<p class="op-notice">No complete backup covers the configured devices. Save progress first, then set the baseline.</p>'}<p class="form-help">Older backups retain their recorded provenance. A successful capture alone does not verify restore compatibility.</p>${baselineRevision?'<label class="checkbox-label"><input type="checkbox" id="git-replace-baseline"> Replace the existing baseline with this selected capture. The previous version remains in Git history.</label>':''}`:`<p>${local?'Capture and commit to the VM repository without pushing.':'Capture the configured devices and preserve this milestone under checkpoints/ as well as latest/.'}</p>`}
 ${checkpoint?'<label for="git-checkpoint-name">Checkpoint name</label><input id="git-checkpoint-name" maxlength="100" placeholder="bgp-peering-working" pattern="[A-Za-z0-9][A-Za-z0-9_-]*"><p class="form-help">Use letters, numbers, underscores or hyphens. Checkpoint names cannot be reused.</p>':''}
 <label for="git-save-note">Note <span class="muted">optional</span></label><input id="git-save-note" maxlength="300" placeholder="What changed in this experiment?">
 ${local?'':'<label class="checkbox-label"><input id="git-save-push" type="checkbox" checked> Push after saving'+(context.binding.review_before_push?' (review preference still applies)':'')+'</label>'}
 <details><summary>Changed device scope</summary><label class="checkbox-label"><input id="git-allow-removed" type="checkbox"> Allow this save to remove previously managed config files for devices no longer in the configured scope. Their older versions remain in Git history.</label></details>
 <div class="dialog-actions"><button class="button secondary" id="git-save-cancel">Cancel</button><button class="button primary" id="git-save-confirm" ${baseline&&!backups.length?'disabled':''}>${label}</button></div>`);
 const requestId=gitRequestId();$('git-save-cancel').onclick=()=>dialog.close();
 $('git-save-confirm').onclick=()=>opTask(dialog,async()=>{
  const name=$('git-checkpoint-name')?.value.trim()||'',backup=$('git-baseline-job')?.value||'';
  if(checkpoint&&!/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(name))throw new Error('Enter a checkpoint name using letters, numbers, underscores or hyphens.');
  if(baseline&&!backup)throw new Error('Choose a complete saved capture.');
  if(baselineRevision&&baseline&&!$('git-replace-baseline').checked)throw new Error('Confirm replacing the existing baseline.');
  const values={target:local?'latest':target,checkpoint:name,push:local?false:$('git-save-push').checked,note:$('git-save-note').value.trim(),backup_job_id:backup,replace_baseline:baseline&&!!baselineRevision,expected_baseline:baseline?baselineRevision:'',allow_removed:$('git-allow-removed').checked};
  await gitSubmitSave(id,values,requestId);dialog.close();
 });
}
function gitRememberJob(job){
 const context=gitContexts.get(job.lab_id);if(context)context.jobs=[job,...(context.jobs||[]).filter(item=>item.id!==job.id)];
 state.git_jobs=[job,...(state.git_jobs||[]).filter(item=>item.id!==job.id)];
}
async function gitShowJob(id,known){
 const job=known||await(await api('/git/jobs/'+encodeURIComponent(id))).json();gitRememberJob(job);gitDialogJob=id;
 const dialog=opDialog('git-job-dialog','Lab progress save','<div id="git-job-detail"></div><div class="actions" id="git-job-actions"></div>');
 dialog.onclose=()=>{gitDialogJob='';};gitRenderJob(job);renderGitProgress();
 if(gitActiveStates.has(job.status))gitStartWatch(job);
}
function gitRenderJob(job){
 if(gitDialogJob!==job.id||!$('git-job-dialog')?.open)return;
 $('git-job-detail').innerHTML=gitJobMarkup(job);
 const pending=gitPendingStates.has(job.status),active=gitActiveStates.has(job.status),hasCommit=!!job.commit;
 $('git-job-actions').innerHTML=`${job.backup_job_id?'<button class="button secondary" data-git-job-action="backup">View configuration capture</button>':''}${hasCommit?'<button class="button secondary" data-git-job-action="review">Review changes</button>':''}${pending?`<button class="button primary" data-git-job-action="push">${hasCommit?'Push saved progress':'Retry export and push'}</button>${!hasCommit?'<button class="button secondary" data-git-job-action="local">Retry export locally</button>':''}<button class="button secondary" data-git-job-action="dismiss">Keep snapshot only</button>`:''}${active?'<p class="form-help" role="status">You can close this window. The save continues and its result remains in Git repository settings.</p>':''}`;
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
 const dialog=opDialog('git-diff-dialog','Review this save',`<p>Changes introduced by commit <code>${esc(job.commit)}</code>. Full configuration files can contain device secrets.</p>${gitDiffMarkup(result.files,'Before this save','Saved configuration')}<div class="dialog-actions"><button class="button secondary" id="git-review-files">View complete saved version</button>${gitPendingStates.has(job.status)?'<button class="button primary" id="git-review-push">Push saved progress</button>':''}</div>`);
 $('git-review-files').onclick=()=>opTask(dialog,()=>gitViewVersion(job.lab_id,{commit:job.commit,path:gitTargetPath(job)}));
 $('git-review-push')?.addEventListener('click',()=>opTask(dialog,async()=>{const next=await json('/git/jobs/'+encodeURIComponent(job.id)+'/retry','POST',{push:true});dialog.close();gitRememberJob(next);await gitShowJob(next.id,next);await refresh();}));
}
function gitStartWatch(job){
 if(gitWatch?.id===job.id)return;clearTimeout(gitWatchTimer);const watch={id:job.id,lab_id:job.lab_id};gitWatch=watch;
 const poll=async()=>{
  if(gitWatch!==watch)return;
  try{
   const value=await(await api('/git/jobs/'+encodeURIComponent(job.id))).json();if(gitWatch!==watch)return;
   gitRememberJob(value);gitRenderJob(value);renderGitProgress();
   if(gitActiveStates.has(value.status))gitWatchTimer=setTimeout(poll,1500);
   else{gitWatch=null;await refresh();if(tab==='git'&&activeId===value.lab_id)await gitShowRepository(true);}
  }catch(error){if(gitWatch===watch){gitWatch=null;if(gitDialogJob===job.id&&$('git-job-dialog')?.open)$('git-job-dialog').querySelector('.form-error').textContent=error.message+' Reopen this save to check its current state.';}}
 };gitWatchTimer=setTimeout(poll,1000);
}
async function gitDismissJob(job){
 const dialog=opDialog('git-dismiss-dialog','Keep this snapshot only?',`<p>Keep the configuration backup and any existing Git commits. Stop tracking this pending export or push so the lab can be disconnected or removed.</p><p>This does not delete files or undo a commit. Any local commit remains in the repository and may be included in a later push.</p><p>${esc(gitLabel(job))} · ${esc(job.id)}</p><div class="dialog-actions"><button class="button secondary" id="git-dismiss-cancel">Cancel</button><button class="button primary" id="git-dismiss-confirm">Keep snapshot only</button></div>`);
 $('git-dismiss-cancel').onclick=()=>dialog.close();$('git-dismiss-confirm').onclick=()=>opTask(dialog,async()=>{const result=await json('/git/jobs/'+encodeURIComponent(job.id)+'/dismiss','POST',{acknowledge:true});gitRememberJob(result);dialog.close();await gitShowJob(result.id,result);await refresh();if(tab==='git')await gitShowRepository(true);});
}
async function gitPushPending(id=activeId){
 const context=await gitLoadContext(id,true),pending=gitLabJobs(id,context).filter(job=>gitPendingStates.has(job.status));
 if(!pending.length){notify('No saved progress is waiting to be pushed.');return;}
 if(pending.length===1){await gitShowJob(pending[0].id,pending[0]);return;}
 const dialog=opDialog('git-pending-dialog','Saved progress awaiting a push',`<div class="op-history">${pending.map(job=>`<button class="button secondary" data-git-pending="${esc(job.id)}">${esc(gitLabel(job))} · ${esc(utcDisplay(job.created))}</button>`).join('')}</div>`);
 for(const button of dialog.querySelectorAll('[data-git-pending]'))button.onclick=()=>opTask(dialog,()=>gitShowJob(button.dataset.gitPending));
}
async function gitUpdateRemote(id=activeId){
 const dialog=opDialog('git-update-dialog','Update from remote','<p>Fetch the registered remote and fast-forward the current branch when the working repository is clean and its history allows it.</p><p>Your running devices are unchanged. A conflict keeps the existing checkout and reports what needs attention.</p><button class="button primary" id="git-update-confirm">Update from remote</button>');
 $('git-update-confirm').onclick=()=>opTask(dialog,async()=>{const result=await json('/labs/'+encodeURIComponent(id)+'/git/update','POST',{});dialog.close();await gitLoadContext(id,true);if(activeId===id&&tab==='git')await gitShowRepository(true);notify(result.message||'Repository updated from remote.');});
}
async function gitUnlink(id=activeId){
 const dialog=opDialog('git-unlink-dialog','Disconnect this repository?',`<p>Remove this lab's repository connection. Existing configuration backups and Git files remain available. Resolve or dismiss any pending saves before disconnecting.</p><div class="dialog-actions"><button class="button secondary" id="git-unlink-cancel">Cancel</button><button class="button primary" id="git-unlink-confirm">Disconnect repository</button></div>`);
 $('git-unlink-cancel').onclick=()=>dialog.close();$('git-unlink-confirm').onclick=()=>opTask(dialog,async()=>{await json('/labs/'+encodeURIComponent(id)+'/git/unlink','POST',{});dialog.close();gitContexts.delete(id);await refresh();await gitShowRepository(true);});
}
async function gitHistory(id=activeId){
 const data=await(await api('/labs/'+encodeURIComponent(id)+'/git/history')).json();
 const versions=data.versions||[],commits=data.commits||[];
 const dialog=opDialog('git-history-dialog','Lab versions and Git history',`<p>View or download saved configuration files. Loading a version into running devices requires device-specific restore validation and is not available in this release.</p><h3>Saved versions</h3><div class="op-history">${versions.map((version,index)=>`<button class="button secondary" data-git-version="${index}"><strong>${esc(version.name||version.path)}</strong><small>${esc(version.path)} · ${esc((version.commit||'').slice(0,10))}</small></button>`).join('')||'<p>No baseline, latest capture or checkpoints saved yet.</p>'}</div><h3>Commits</h3><div class="op-history">${commits.map((commit,index)=>`<button class="button secondary" data-git-commit="${index}"><strong>${esc(commit.message)}</strong><small>${esc((commit.commit||'').slice(0,10))} · ${esc(commit.time?gitTime(commit.time):'')}</small></button>`).join('')||'<p>No progress commits available.</p>'}</div>`);
 for(const button of dialog.querySelectorAll('[data-git-version]'))button.onclick=()=>opTask(dialog,()=>gitViewVersion(id,versions[Number(button.dataset.gitVersion)]));
 for(const button of dialog.querySelectorAll('[data-git-commit]'))button.onclick=()=>opTask(dialog,()=>gitOpenCommit(id,commits[Number(button.dataset.gitCommit)],versions));
}
async function gitOpenCommit(id,commit,versions){
 const matching=gitLabJobs(id).filter(job=>job.commit===commit.commit&&['latest','baseline','checkpoint'].includes(job.target));
 // An unchanged save can reuse HEAD without producing the selected commit.
 const known=matching.find(job=>Array.isArray(job.changed_files)&&job.changed_files.length)||matching.find(job=>job.target==='latest');
 if(known)return gitViewVersion(id,{commit:commit.commit,path:gitTargetPath(known)});
 const paths=[...new Set(['latest','baseline',...versions.map(version=>version.path)])];
 const dialog=opDialog('git-commit-dialog','Choose a saved folder',`<p>${esc(commit.message||'Historical configuration version')}</p><p class="op-path">${esc(commit.commit)}</p><label for="git-commit-path">Snapshot folder at this commit</label><select id="git-commit-path">${paths.map(folder=>`<option value="${esc(folder)}">${esc(folder)}</option>`).join('')}</select><p class="form-help">A folder must already exist at this commit. Choose another folder if this version predates it.</p><button class="button primary" id="git-commit-view">View saved files</button>`);
 $('git-commit-view').onclick=()=>opTask(dialog,()=>gitViewVersion(id,{commit:commit.commit,path:$('git-commit-path').value}));
}
async function gitViewVersion(id,version){
 const request={commit:version.commit,path:version.path},data=await json('/labs/'+encodeURIComponent(id)+'/git/version','POST',request);
 const files=data.files||[];
 const dialog=opDialog('git-version-dialog','Saved configuration version',`<p class="op-path">${esc(version.name||version.path)} · ${esc(version.commit)}</p><div class="actions"><button class="button secondary" id="git-version-compare">Compare with latest</button><button class="button primary" id="git-version-download">Download version (ZIP)</button></div><p class="form-help">These are the exact stored files. Downloading does not apply configurations to running devices.</p><details><summary>Capture manifest</summary><pre class="git-file-content" tabindex="0">${esc(JSON.stringify(data.manifest,null,2))}</pre></details><div class="git-version-files">${files.map(file=>`<details><summary>${esc(file.name)}</summary><pre class="git-file-content" tabindex="0">${esc(file.text)}</pre></details>`).join('')||'<p>No configuration files in this version.</p>'}</div>`);
 $('git-version-compare').onclick=()=>opTask(dialog,async()=>{const result=await json('/labs/'+encodeURIComponent(id)+'/git/compare','POST',request);opDialog('git-diff-dialog','Changes compared with latest',`<p>${esc(version.path)} at ${esc(version.commit)} compared with the latest saved configuration files.</p>${gitDiffMarkup(result.files)}`);});
 $('git-version-download').onclick=()=>opTask(dialog,async()=>{const response=await api('/labs/'+encodeURIComponent(id)+'/git/version/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=attachmentName(response,'lab-version.zip');document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
}
function gitRunAction(action,id=activeId){
 if($('git-save-menu'))$('git-save-menu').open=false;
 return opTask(null,async()=>{
  if(action==='settings'){gitOpenRepository();return;}
  if(action==='history'||action==='load'){await gitHistory(id);return;}
  if(action==='push'){await gitPushPending(id);return;}
  if(action==='update'){await gitUpdateRemote(id);return;}
  if(action==='unlink'){await gitUnlink(id);return;}
  await gitSaveOptions(action,id);
 });
}
if(typeof $==='function'&&$('git-progress-bar')){
 $('git-save-progress').onclick=()=>opTask(null,gitSaveProgress);
 $('git-repository-refresh').onclick=()=>opTask(null,()=>gitShowRepository(true));
 $('git-open-settings').onclick=gitOpenRepository;
 for(const button of $('git-save-menu').querySelectorAll('[data-git-action]'))button.onclick=()=>gitRunAction(button.dataset.gitAction);
 document.addEventListener('click',event=>{const menu=$('git-save-menu');if(menu?.open&&!menu.contains(event.target))menu.open=false;});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('git-save-menu'))$('git-save-menu').open=false;});
}
