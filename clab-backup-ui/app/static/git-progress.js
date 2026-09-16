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
function gitRepoName(repo){return String(repo?.path||'').split('/').filter(Boolean).pop()||repo?.label||'Repository';}
function gitDestination(binding){const repo=gitRepository(binding);return [[gitRepoName(repo)||binding?.binding_id,repo.prefix?repo.prefix.replace(/\/$/,''):'','latest/'].filter(Boolean).join(' › '),repo.branch].filter(Boolean).join(' · ');}
function gitTargetPath(job){if(job.target==='move')return 'latest';return job.target==='checkpoint'?'checkpoints/'+job.checkpoint:job.target||'latest';}
function gitTargetLabel(job){if(job.target==='move')return 'Folder move → '+((job.snapshot_path||'').replace(/\/?latest$/,'')||'repository root');return job.target==='checkpoint'?'checkpoints/'+(job.checkpoint||''):job.target||'latest';}
let gitPendingSelection='';
function gitCompleteBackups(jobs,id,names){
 const required=new Set(names||[]);
 return jobs.filter(job=>required.size&&job.lab_id===id&&job.operation==='backup'&&['succeeded','partial'].includes(job.status)&&job.nodes?.length===required.size&&new Set(job.nodes.map(node=>node.name)).size===required.size&&job.nodes.every(node=>node.status==='succeeded'&&required.has(node.name)));
}
function gitSavePayload(values,requestId){return {request_id:requestId,target:values.target||'latest',checkpoint:values.checkpoint||'',push:values.push!==false,note:values.note||'',backup_job_id:values.backup_job_id||'',replace_baseline:values.replace_baseline===true,expected_baseline:values.expected_baseline||'',allow_removed:values.allow_removed===true};}
function gitRequestId(){const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return Array.from(bytes,n=>n.toString(16).padStart(2,'0')).join('');}
function gitJobMarkup(job){
 if(!job)return '<p>No Git saves yet. Save progress captures every device selected in Git repository settings.</p>';
 const changed=Array.isArray(job.changed_files)?job.changed_files.length:job.changed_files;
 return `<div class="git-job-summary"><span class="badge ${gitActiveStates.has(job.status)?'running':['synced','unchanged'].includes(job.status)?'good':['failed','capture_incomplete'].includes(job.status)?'bad':'warn'}">${esc(gitLabel(job))}</span><p>${esc(job.message||'')}</p><dl class="health-grid"><dt>Saved target</dt><dd>${esc(gitTargetLabel(job))}</dd><dt>Started</dt><dd>${esc(utcDisplay(job.created))}</dd>${job.commit?`<dt>Commit</dt><dd class="mono">${esc(job.commit)}</dd>`:''}${changed!==undefined?`<dt>Changed files</dt><dd>${esc(changed)}</dd>`:''}</dl></div>`;
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
 const activeBinding=!!binding,labName=(state.labs||[]).find(lab=>lab.id===id)?.name||'This lab',repoName=gitRepoName(repo);
 const preselect=gitPendingSelection&&repositories.some(value=>value.id===gitPendingSelection)?gitPendingSelection:binding?.binding_id||'';gitPendingSelection='';
 const option=value=>`<option value="${esc(value.id)}" ${value.id===preselect?'selected':''}>${esc(gitRepoName(value))} › ${esc(value.prefix||'repository root')} · ${esc(value.owner)} · ${esc(value.branch)}</option>`;
 $('git-repository-content').innerHTML=`${status.problem?`<p class="op-notice" role="status">${esc(status.problem)}</p>`:''}
 ${activeBinding?`<div class="git-repository-card"><p class="eyebrow">CONNECTED REPOSITORY</p><h3>${esc(repoName)}</h3>${repo.push_url?`<p class="op-path">Verified push destination: <code>${esc(repo.push_url)}</code></p>`:''}<p class="op-path">Branch ${esc(repo.branch||'')} · VM account ${esc(repo.owner||'')} · ${esc(repo.path||'')}</p><p class="git-destination-line"><span>${esc(labName)} saves to</span><code>${esc(repoName)}</code>${repo.prefix?`<span aria-hidden="true">›</span><code>${esc(repo.prefix)}</code>`:''}<span aria-hidden="true">›</span><code>latest/</code></p><p class="form-help">Save progress includes ${selected.size} configured devices. Scheduled backup selection is independent.</p><div class="actions"><button class="button secondary" data-git-repo-action="switch">Use a different repository…</button><button class="button secondary" data-git-repo-action="history">View changes / History</button><button class="button secondary" data-git-repo-action="update">Update from remote</button><button class="button secondary" data-git-repo-action="unlink">Disconnect</button></div><p class="form-help">Connected the wrong repository? Choose <strong>Use a different repository</strong>. Nothing is deleted from either repository, and files already saved stay where they are.</p></div>`:''}
 ${repositories.length||activeBinding?`<section class="git-places" aria-label="Where this lab lives"><div class="git-places-title"><h3>Where this lab lives</h3><p>${activeBinding?'The folders of the connected repository, as they are in Git right now. Select a folder and choose <strong>Save this lab here</strong> to move this lab, or create a new folder.':'The folders of the selected repository. Choose a folder for this lab, or create a new one, then confirm the connection below.'}</p></div><div id="git-places-panel"></div></section>`:''}
 ${repositories.length?`<form id="git-binding-form" class="git-binding-form"><h3>${activeBinding?'Devices and settings':'Connect this lab to Git'}</h3><label for="git-binding-id">Repository and folder</label><select id="git-binding-id" required>${!preselect?'<option value="">Choose a repository folder</option>':''}${repositories.map(option).join('')}</select><p id="git-binding-destination" class="op-path"></p><p class="form-help">Not the repository you want? <button type="button" class="text-button git-inline-action" data-git-repo-action="connect">Connect a repository by its URL</button></p>
 <fieldset class="git-node-scope"><legend>Devices included in every progress save</legend>${supported.map(node=>`<label class="checkbox-label"><input type="checkbox" name="git-node" value="${esc(node.name)}" ${selected.has(node.name)?'checked':''}> <span>${esc(node.short_name||node.name)} <small>${esc(platformLabel(node.platform))}</small></span></label>`).join('')||'<p>No supported configuration devices in this lab.</p>'}</fieldset>
 ${excluded.length?`<p class="form-help">Unsupported devices are excluded: ${excluded.map(node=>esc(node.short_name||node.name||node)).join(', ')}.</p>`:''}
 <p class="form-help">An offline included device makes the capture incomplete. Its previous configuration is never silently substituted.</p>
 <label class="checkbox-label"><input id="git-review-before-push" type="checkbox" ${binding?.review_before_push?'checked':''}> Review changes before pushing</label>
 <label id="git-exposure-label" class="checkbox-label"><input id="git-exposure" type="checkbox"> I understand that full device configurations, including any secrets they contain, will be committed and pushed to this repository.</label>
 <p class="form-help">Git runs as the registered VM account using its existing Git login and commit identity. Configure that login on the VM outside this application.</p><p class="form-error" role="alert"></p><div class="actions"><button type="submit" class="button primary" ${supported.length?'':'disabled'}>${activeBinding?'Save repository settings':'Connect repository'}</button></div></form>`:`<div class="blank-state"><h3>No repository connected to this VM yet</h3><p>Paste the HTTPS URL of your GitHub repository. The manager clones it on the VM with the GitHub login already set up there, creates this lab's folder and connects it.</p><div class="actions git-blank-actions"><button class="button primary" data-git-repo-action="connect">Connect a repository by URL</button></div><details><summary>Prefer the terminal wizard?</summary><p>From the release source directory on the VM, run guided setup as your ordinary account, without sudo:</p><pre class="git-setup-command">bash deploy/setup-git.sh</pre><p>The wizard handles checkout, Git login and registration. Refresh status after setup.</p></details></div>`}
 <section class="git-saves"><h3>Progress saves</h3><p>Every save links to its original configuration capture. Git history contains committed versions.</p><div id="git-saves-list">${gitLabJobs(id,context).map(job=>`<button class="git-saved-job" data-git-job="${esc(job.id)}"><strong>${esc(gitLabel(job))}</strong><span>${esc(utcDisplay(job.created))} · ${esc(gitTargetLabel(job))}${job.commit?' · '+esc(job.commit.slice(0,10)):''}</span></button>`).join('')||'<p>No Git progress saves yet.</p>'}</div></section>`;
 const form=$('git-binding-form'),panel=$('git-places-panel');
 const showPlaces=bindingId=>{
  if(!panel)return;
  if(!bindingId){panel.innerHTML='<p class="git-empty-folder">Choose a repository folder above to see what is in it.</p>';return;}
  const browsed=repositories.find(value=>value.id===bindingId),connected=!!binding&&!!browsed&&browsed.path===repo.path;
  gitPlacesShow(panel,id,bindingId,{current:binding?.binding_id||'',connected,onUse:(path,model,tree)=>gitUseFolder(id,path,model,tree),onNew:(path,model,tree)=>gitNewFolder(id,path,model,tree),onApply:typeof restoreFromFolder==='function'?(path,model,tree)=>restoreFromFolder(id,path,tree):undefined});
 };
 if(form){
  const change=()=>{const selectedRepo=repositories.find(value=>value.id===$('git-binding-id').value);$('git-binding-destination').textContent=selectedRepo?gitRegisteredDestination(selectedRepo):'';const changed=gitBindingChanged(binding,selectedRepo);$('git-exposure-label').hidden=!changed;$('git-exposure').required=changed;$('git-exposure').checked=false;showPlaces(selectedRepo?.id||binding?.binding_id||'');};
  $('git-binding-id').onchange=change;change();
  form.onsubmit=event=>{event.preventDefault();opTask(form,async()=>{
   const node_names=[...form.querySelectorAll('[name="git-node"]:checked')].map(input=>input.value);
   if(!node_names.length)throw new Error('Select at least one supported device for progress saves.');
   if(gitBindingChanged(binding,repositories.find(value=>value.id===$('git-binding-id').value))&&!$('git-exposure').checked)throw new Error('Acknowledge exporting full configurations to the selected repository.');
   await json('/labs/'+encodeURIComponent(id)+'/git','PUT',{binding_id:$('git-binding-id').value,node_names,review_before_push:$('git-review-before-push').checked});
   await gitShowRepository(true);await refresh();notify('Git repository connected. Save progress is ready.');
  });};
 }else if(activeBinding)showPlaces(binding.binding_id);
 for(const button of $('git-repository-content').querySelectorAll('[data-git-repo-action]'))button.onclick=()=>gitRunAction(button.dataset.gitRepoAction,id);
 for(const button of $('git-repository-content').querySelectorAll('[data-git-job]'))button.onclick=()=>opTask(null,()=>gitShowJob(button.dataset.gitJob));
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
  // Not connected to this repository yet: choose the folder, then confirm devices in the connection form.
  let registration=model.nodes.get(path)?.registration;
  if(!registration)registration=(await json('/git/repositories/'+encodeURIComponent(tree.repository.id)+'/folders','POST',{prefix:path})).repository;
  gitPendingSelection=registration.id;await gitShowRepository(true);
  notify('Folder chosen: '+target+'. Confirm the devices below to connect '+labName+'.');$('git-binding-form')?.scrollIntoView?.({block:'start',behavior:'smooth'});return;
 }
 const current=gitLabFolder(model,binding.binding_id),count=current?current.count:0,from=binding.repository?.prefix||'the repository root';
 const dialog=opDialog('git-folder-dialog','Save this lab here?',`<p><strong>${esc(labName)}</strong> will keep its progress in <code>${esc(repoName)}${path?' › '+esc(path):''}</code> from now on.</p>${count?`<label class="checkbox-label"><input id="git-move-files" type="checkbox" checked> Also move the ${count} files already saved under <code>${esc(from)}</code> into the new folder. This makes one commit and pushes it.</label>`:'<p class="form-help">Nothing is saved under the current folder yet, so there is nothing to move.</p>'}<p class="form-help">Earlier versions stay in Git history either way. Scheduled backups and the device selection do not change.</p><div class="dialog-actions"><button class="button secondary" id="git-folder-cancel">Cancel</button><button class="button primary" id="git-folder-confirm">Save here</button></div>`);
 $('git-folder-cancel').onclick=()=>dialog.close();
 $('git-folder-confirm').onclick=()=>opTask(dialog,async()=>{const move=!!$('git-move-files')?.checked;await gitApplyDestination(id,path,move,labName);dialog.close();});
}
async function gitNewFolder(id,parent,model,tree){
 const context=await gitLoadContext(id,true),binding=context.binding,repoName=gitRepoName(tree.repository),labName=gitLabName(id);
 const connected=!!binding&&binding.repository?.path===tree.repository?.path,current=connected?gitLabFolder(model,binding.binding_id):null,count=current?current.count:0,from=binding?.repository?.prefix||'the repository root';
 const dialog=opDialog('git-new-folder-dialog','New folder',`<p class="op-path">${esc(repoName)}${parent?' › '+esc(parent):''} › <em>new folder</em></p><label for="git-new-folder-name">Folder name</label><input id="git-new-folder-name" maxlength="360" placeholder="Week-04/BGP/Final-State" autocomplete="off" spellcheck="false"><p class="form-help">Letters, numbers, dashes, dots and underscores. Use <code>/</code> to create nested folders in one step. Git shows a folder once something is saved in it.</p><p class="git-destination-line" id="git-new-folder-result" hidden><span>Result</span><code></code></p>${connected?`<label class="checkbox-label"><input id="git-new-folder-use" type="checkbox" checked> Save ${esc(labName)} here from now on</label>${count?`<label class="checkbox-label"><input id="git-new-folder-move" type="checkbox" checked> Also move the ${count} files already saved under <code>${esc(from)}</code> into it. This makes one commit and pushes it.</label>`:''}`:'<p class="form-help">The folder is prepared for this lab. Confirm the devices below afterwards to connect it.</p>'}<div class="dialog-actions"><button class="button secondary" id="git-new-folder-cancel">Cancel</button><button class="button primary" id="git-new-folder-confirm">Create folder</button></div>`);
 const result=$('git-new-folder-result'),resultCode=result.querySelector('code');
 const preview=()=>{const full=gitDestinationPreview(parent,$('git-new-folder-name').value);result.hidden=!full;resultCode.textContent=full?repoName+' / '+full:'';};
 $('git-new-folder-name').oninput=preview;preview();
 $('git-new-folder-cancel').onclick=()=>dialog.close();
 $('git-new-folder-confirm').onclick=()=>opTask(dialog,async()=>{
  const nested=gitFolderPath($('git-new-folder-name').value),prefix=parent?parent+'/'+nested:nested;
  if(connected&&$('git-new-folder-use')?.checked){await gitApplyDestination(id,prefix,!!$('git-new-folder-move')?.checked,labName);dialog.close();return;}
  const created=await json('/git/repositories/'+encodeURIComponent(tree.repository.id)+'/folders','POST',{prefix});
  dialog.close();gitPlacesState.selected=prefix;if(!connected)gitPendingSelection=created.repository.id;await gitShowRepository(true);notify('Folder '+prefix+' is ready for a lab.');
 });
}
async function gitSwitchRepository(id){
 const [context,catalog]=await Promise.all([gitLoadContext(id,true),(await api('/git/repositories')).json()]);
 const binding=context.binding,repositories=(catalog.repositories||[]).filter(value=>value.id!==binding?.binding_id);
 const dialog=opDialog('git-switch-dialog','Use a different repository',`<p>Pick another repository already set up on this VM, or connect a new one by its URL. Files already saved in the current repository are not deleted.</p>${repositories.length?`<label for="git-switch-id">Repositories on this VM</label><select id="git-switch-id">${repositories.map(value=>`<option value="${esc(value.id)}">${esc(gitRepoName(value))} › ${esc(value.prefix||'repository root')} · ${esc(value.branch)}</option>`).join('')}</select><div class="dialog-actions"><button class="button secondary" id="git-switch-choose">Choose this repository</button></div>`:'<p class="form-help">No other repository is set up on this VM yet.</p>'}<h3>Connect a repository by URL</h3><p class="form-help">For a repository that is not on this VM yet. You need its HTTPS clone URL and the GitHub login already set up on the VM.</p><div class="dialog-actions"><button class="button primary" id="git-switch-connect">Connect by URL…</button></div>`);
 $('git-switch-choose')?.addEventListener('click',()=>opTask(dialog,async()=>{gitPendingSelection=$('git-switch-id').value;dialog.close();await gitShowRepository(true);notify('Choose the folder and confirm the devices below.');$('git-binding-form')?.scrollIntoView?.({block:'start',behavior:'smooth'});}));
 $('git-switch-connect').onclick=()=>{dialog.close();opTask(null,()=>gitConnectByUrl(id));};
}
function gitSuggestedFolder(name){return String(name||'lab').replace(/[^A-Za-z0-9_.-]+/g,'-').replace(/^[^A-Za-z0-9_]+/,'').replace(/-+$/,'').slice(0,60)||'lab';}
async function gitConnectByUrl(id){
 const context=await gitLoadContext(id,true),labName=gitLabName(id),suggested=gitSuggestedFolder(labName);
 const dialog=opDialog('git-connect-dialog','Connect a repository by URL',`<p>Paste the HTTPS clone URL from GitHub (Code › HTTPS). The manager clones it on the VM as its Git account, using the GitHub login already set up there. It never asks for a token or password.</p><label for="git-connect-url">Repository URL</label><input id="git-connect-url" placeholder="https://github.com/you/your-lab-repo" autocomplete="off" spellcheck="false"><label for="git-connect-folder">Folder for this lab <span class="muted">optional</span></label><input id="git-connect-folder" value="${esc(suggested)}" maxlength="180" autocomplete="off" spellcheck="false"><p class="form-help">One repository can hold several labs, each in its own folder. Clear it to save at the repository root of a single-lab repository.</p><label class="checkbox-label"><input id="git-connect-ack" type="checkbox"> I understand that full device configurations, including any secrets they contain, will be committed and pushed to this repository.</label><p class="form-help">If no commit name and email are set on the VM yet, the GitHub account's name and its private noreply address are used.</p><div class="dialog-actions"><button class="button secondary" id="git-connect-cancel">Cancel</button><button class="button primary" id="git-connect-confirm">Connect repository</button></div>`);
 $('git-connect-cancel').onclick=()=>dialog.close();
 $('git-connect-confirm').onclick=()=>opTask(dialog,async()=>{
  const url=$('git-connect-url').value.trim(),rawFolder=$('git-connect-folder').value.trim();
  if(!/^https:\/\/[^\s/]+\/\S+/.test(url))throw new Error('Paste the HTTPS clone URL, for example https://github.com/you/your-lab-repo.');
  // Normalise the same way as New folder so the submitted prefix matches what is validated.
  const folder=rawFolder?gitFolderPath(rawFolder):'';
  if(!$('git-connect-ack').checked)throw new Error('Acknowledge exporting full configurations to this repository.');
  const button=$('git-connect-confirm'),label=button.textContent;button.textContent='Connecting… this can take a minute';
  try{
   const result=await json('/labs/'+encodeURIComponent(id)+'/git/connect','POST',{url,prefix:folder,acknowledge:true,node_names:context.binding?.node_names||[],review_before_push:context.binding?.review_before_push||false});
   dialog.close();gitContexts.delete(id);gitPlacesState.selected=folder;await refresh();await gitShowRepository(true);notify(labName+' is connected to '+gitRepoName(result.binding?.repository)+'.');
  }finally{button.textContent=label;}
 });
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
 const dialog=opDialog('git-history-dialog','Lab versions and Git history',`<p>View, download or apply saved configuration versions. Open a Junos version to <strong>apply it to the running lab</strong>; the current configuration is backed up first and the node is not rebooted.</p><h3>Saved versions</h3><div class="op-history">${versions.map((version,index)=>`<button class="button secondary" data-git-version="${index}"><strong>${esc(version.name||version.path)}</strong><small>${esc(version.path)} · ${esc((version.commit||'').slice(0,10))}</small></button>`).join('')||'<p>No baseline, latest capture or checkpoints saved yet.</p>'}</div><h3>Commits</h3><div class="op-history">${commits.map((commit,index)=>`<button class="button secondary" data-git-commit="${index}"><strong>${esc(commit.message)}</strong><small>${esc((commit.commit||'').slice(0,10))} · ${esc(commit.time?gitTime(commit.time):'')}</small></button>`).join('')||'<p>No progress commits available.</p>'}</div>`);
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
 const restoreBtn=data.restore_supported&&typeof restoreFromVersion==='function'?'<button class="button danger" id="git-version-restore">Apply to running lab…</button>':'';
 const restoreNote=data.restore_supported
  ?'<p class="form-help">This version has a restore-grade Junos candidate. <strong>Apply to running lab</strong> loads it onto the running node (no reboot); the current configuration is backed up first.</p>'
  :'<p class="form-help">View or download only — this saved version predates live restore support, so it cannot be applied to a running device.</p>';
 const dialog=opDialog('git-version-dialog','Saved configuration version',`<p class="op-path">${esc(version.name||version.path)} · ${esc(version.commit)}</p><div class="actions">${restoreBtn}<button class="button secondary" id="git-version-compare">Compare with latest</button><button class="button primary" id="git-version-download">Download version (ZIP)</button></div>${restoreNote}<details><summary>Capture manifest</summary><pre class="git-file-content" tabindex="0">${esc(JSON.stringify(data.manifest,null,2))}</pre></details><div class="git-version-files">${files.map(file=>`<details><summary>${esc(file.name)}</summary><pre class="git-file-content" tabindex="0">${esc(file.text)}</pre></details>`).join('')||'<p>No configuration files in this version.</p>'}</div>`);
 if(restoreBtn)$('git-version-restore').onclick=()=>opTask(dialog,async()=>{dialog.close();await restoreFromVersion(id,{type:'git',commit:version.commit,path:version.path},version.name||version.path);});
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
  if(action==='switch'){await gitSwitchRepository(id);return;}
  if(action==='connect'){await gitConnectByUrl(id);return;}
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
