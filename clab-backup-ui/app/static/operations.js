'use strict';
// Shared by the main workspace and independent VM-folder / SSH-launcher tabs.
// opLabels are the imperative student labels for every containerlab action (status.js keeps its own
// in-progress table for the header and the banner); the review dialog, the output window and the
// history rows all read from here so one operation has one name everywhere.
const opLabels={deploy:'Start lab',redeploy:'Redeploy lab',destroy:'Destroy lab',apply:'Apply topology changes',start:'Start devices',stop:'Stop devices',restart:'Restart devices',save:'Save device configurations',inspect:'Show running devices','inspect-all':'Running labs on the VM',create:'Create topology file',delete:'Delete topology file',clone:'Download lab',publish:'Save lab to the VM',revise:'Save topology changes'};
const opLifecycle=['deploy','start','stop','restart','redeploy','destroy','apply'];
const opDisruptive=['stop','restart','redeploy','destroy','apply'];
let opCaps=null, opMenuLab='', opOutputTimer=null, opEditorContext=null;
function opDialog(id,title,body){
 let dialog=$(id);if(!dialog){dialog=document.createElement('dialog');dialog.id=id;dialog.className='operations-dialog';document.body.append(dialog);}
 dialog.innerHTML=`<div class="dialog-head"><h2>${esc(title)}</h2><button class="icon-button" data-op-close aria-label="Close">×</button></div>${body}<p class="form-error" role="alert"></p>`;
 dialog.querySelector('[data-op-close]').onclick=()=>dialog.close();if(!dialog.open)dialog.showModal();return dialog;
}
async function opTask(dialog,fn){
 const error=dialog?.querySelector('.form-error');if(error)error.textContent='';
 const buttons=dialog?[...dialog.querySelectorAll('button:not(:disabled)')]:[];buttons.forEach(b=>b.disabled=true);
 try{return await fn();}catch(e){if(error)error.textContent=e.message;else if(typeof showActionError==='function')showActionError(e.message);else notify(e.message);}finally{buttons.forEach(b=>b.disabled=false);}
}
function opPath(lab){return lab?.vm_project_path||lab?.vm_source?.files?.definition?.path||'';}
function opName(lab){return lab?.deployment_name||lab?.name||'';}
function opWhen(value){if(!value)return '';return typeof relativeTime==='function'?relativeTime(value):new Date(value).toLocaleString();}
function opStatusWord(status){return {succeeded:'Completed',failed:'Failed',interrupted:'Interrupted',running:'Running',queued:'Waiting'}[status]||String(status||'');}
async function opCapabilities(){opCaps=await(await api('/operations/capabilities')).json();return opCaps;}
function opCommand(action,label=opLabels[action],options={}){
 const cap=opCaps?.actions?.[action], unavailable=cap&&!cap.available;
 return `<button class="button ${['destroy','delete'].includes(action)?'danger-outline':'secondary'}" data-op-action="${esc(action)}" data-op-options="${esc(JSON.stringify(options))}" ${unavailable?'disabled':''}>${esc(label||action)}${unavailable?'<small>Not available on this VM — see Diagnostics</small>':''}</button>`;
}
// Destroy always runs containerlab destroy --cleanup: the containers go together with the generated
// lab folder (clab-<name>: TLS material, generated startup files), so the next deploy starts clean.
// The helper refuses the flag on a containerlab without it, so the flag is only sent when the
// installed command is known to have it or the capabilities could not be read at all.
function opDestroyOptions(caps=opCaps){return caps?.actions?.destroy?.cleanup===false?{}:{cleanup:true};}
async function openLabOperations(id=activeId){
 opMenuLab=id;const lab=state.labs.find(l=>l.id===id);if(!lab)return;
 const dialog=opDialog('lab-operations-dialog',lab.name,'<p>Checking what this VM can do…</p>');
 let problem='';try{await opCapabilities();}catch(e){opCaps=null;problem=e.message;}
 if(!dialog.open)return;
 const path=opPath(lab);
 const cleanup=['deploy','redeploy'].filter(a=>opCaps?.actions[a]?.cleanup).map(a=>opCommand(a,(a==='deploy'?'Deploy lab':'Redeploy lab')+' and clear the lab folder…',{cleanup:true})).join('');
 opDialog(dialog.id,lab.name,`<p class="op-path">${path?'Topology file on the VM: '+esc(path):"This lab has no topology file on the VM yet. Import the lab's files (Advanced › Deployment details) to enable these actions."}</p>${problem?`<p class="op-notice">Couldn't check the VM's commands, so every action is shown; some may fail. Details: ${esc(problem)}</p>`:''}
 <div class="op-sections"><section><h3>Deployment</h3><div class="op-grid">${opCommand('deploy','Deploy lab')}${['redeploy','start','stop','restart','apply','inspect','save'].map(a=>opCommand(a)).join('')}</div><p class="form-help">Deploy creates and starts the devices; Start, Stop and Restart act on the running devices. "Save device configurations" uses containerlab's own save (supported device types only); your Save progress snapshots are separate.</p></section>
 <section><h3>Lab tools</h3><div class="op-grid"><button class="button secondary" data-local="ssh"><span>Open all CLIs <span aria-hidden="true">↗</span></span></button><button class="button secondary" data-local="interactive">Edit map</button><button class="button secondary" data-local="telemetry">Telemetry settings…</button><button class="button secondary" data-local="history">Operation history…</button><button class="button secondary" data-local="favorite">${lab.favorite?'Remove from favourites':'Add to favourites'}</button></div></section>
 <section class="op-danger"><h3>Danger</h3><div class="op-grid">${opCommand('destroy','Destroy lab…',opDestroyOptions())}${cleanup}${opCommand('delete','Delete the topology file from the VM…')}</div><p class="form-help">Destroy removes the running devices and, when the installed containerlab supports cleanup, the lab's generated folder on the VM. Redeploy keeps that folder unless you choose the "clear the lab folder" variant.</p></section></div>`);
 dialog.querySelectorAll('[data-op-action]').forEach(b=>b.onclick=()=>{
  const action=b.dataset.opAction,options=JSON.parse(b.dataset.opOptions);
  opTask(dialog,()=>opReview({lab_id:id,action,options}));
 });
 dialog.querySelectorAll('[data-local]').forEach(b=>b.onclick=()=>opTask(dialog,async()=>{
  const action=b.dataset.local;
  if(action==='ssh')opNewTab({mode:'ssh',lab:id});
  if(action==='favorite'){await json('/labs/'+id+'/operations-settings','PUT',{favorite:!lab.favorite});await refresh();dialog.close();}
  if(action==='interactive')await opLayout(id);
  if(action==='telemetry'){dialog.close();await openTelemetrySettings(id);}
  if(action==='history')await opHistory(id);
 }));
}
// Per-lab telemetry: on/off, the login used for gNMI, the removal of manager-added lines and
// the reason a node is not streaming. The data itself is read in the network dashboard, never here.
const teleStateLabels={disabled:'off',waiting:'waiting',configuring:'configuring',connecting:'connecting',streaming:'streaming',stale:'stale',unsupported:'unsupported',failed:'failed',unmonitored:'unmonitored'};
function telemetrySummaryText(data){
 const s=data.settings||{},sum=data.summary||{};
 if(!data.enabled)return 'Telemetry is not installed on this VM.';
 if(!data.linked)return "Telemetry only works for labs running on the VM; this lab isn't linked to a running lab yet.";
 if(!s.decided)return 'Telemetry hasn’t been set up for this lab. Nothing changes on any device until you turn it on.';
 if(!s.auto)return 'Telemetry is off for this lab, so the network dashboard shows nothing for it.';
 const parts=['streaming','stale','waiting','configuring','connecting','failed','unsupported'].filter(k=>sum[k]).map(k=>`${sum[k]} ${teleStateLabels[k]}`);
 return `Telemetry is on: ${sum.total||0} supported device${sum.total===1?'':'s'}${parts.length?' · '+parts.join(' · '):''}. Open the network dashboard to see the data.`;
}
// The dashboard runs on the VM only while someone reads it; the manager starts it from Tools › Telemetry
// and stops it after the idle time. Its state and a manual stop live in the same dialog.
function telemetryGrafanaText(g){
 if(!g)return 'Dashboard: status unavailable.';
 if(!g.enabled)return 'Dashboard: not installed on this VM.';
 if(g.running)return `Dashboard: running (port ${g.port})${g.idle_minutes?`; stops automatically after ${g.idle_minutes} minute${g.idle_minutes===1?'':'s'} without a viewer`:'; automatic stop is off'}.`;
 if(g.running===false)return 'Dashboard: stopped; it starts when you open it from Tools › Telemetry.';
 return 'Dashboard: not checked yet.';
}
async function openTelemetrySettings(id=activeId){
 const data=await(await api('/labs/'+id+'/telemetry')).json();
 let grafana=null;try{grafana=await(await api('/telemetry/grafana')).json();}catch{grafana=null;}
 const s=data.settings||{},profiles=data.password_profiles||[],usable=data.enabled&&data.linked;
 const failed=(data.nodes||[]).filter(n=>['failed','stale'].includes(n.state));
 const dialog=opDialog('telemetry-settings-dialog','Telemetry settings',`<p class="form-help">${esc(telemetrySummaryText(data))}</p>${!data.enabled&&data.unavailable?`<details class="caption"><summary>Details</summary><p>${esc(data.unavailable)}</p></details>`:''}${failed.length?`<p class="form-help">Devices that need attention:</p><ul class="form-help">${failed.map(n=>`<li><strong>${esc(n.short_name||n.name)}</strong> (${esc(teleStateLabels[n.state]||n.state)}): ${esc(n.message||'')}</li>`).join('')}</ul>`:''}<p class="form-help" id="tele-grafana">${esc(telemetryGrafanaText(grafana))}${grafana?.running?' <button class="button secondary" id="tele-grafana-stop" type="button">Stop the dashboard now</button>':''}</p><label class="checkbox-label"><input type="checkbox" id="tele-auto" ${s.auto?'checked':''} ${usable?'':'disabled'}> Collect live interface statistics from this lab's devices (shown in the network dashboard)</label><p class="form-help">Works on Arista cEOS, Cisco XRv9k and Juniper cJunosEvolved devices once they finish starting. The manager adds only the few configuration lines needed for streaming and never overwrites your configuration. Data is kept for 15 minutes; stopping, destroying or redeploying the lab clears it.</p><label>Login used for telemetry<select id="tele-profile" ${usable?'':'disabled'}><option value="">Same login as the CLI (saved credentials)</option>${profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===s.profile_id?'selected':''}>${esc(p.label)} · ${esc(p.platform)}</option>`).join('')}</select></label><p class="form-help">Telemetry needs a username and password. Devices that log in with an SSH key need a password profile here. Passwords never leave the manager.</p><div class="dialog-actions">${failed.length?'<button class="button secondary" id="tele-retry">Retry failed devices</button>':''}<button class="button danger-outline" id="tele-remove" ${s.auto||!usable?'disabled title="Turn telemetry off first"':''}>Remove telemetry configuration from devices…</button><button class="button primary" id="tele-save" ${usable?'':'disabled'}>Save</button></div><p class="form-help">Remove deletes only the lines this manager added, on running devices. Turning telemetry off leaves the device configuration as it is.</p>`);
 $('tele-save').onclick=()=>opTask(dialog,async()=>{const auto=$('tele-auto').checked;await json('/labs/'+id+'/telemetry/settings','PUT',{auto,profile_id:$('tele-profile').value||''});notify(auto?'Telemetry turned on. Supported devices are set up as they become ready — open the network dashboard to watch them.':'Telemetry turned off; collection stopped.');dialog.close();await refresh();});
 $('tele-remove').onclick=()=>opTask(dialog,async()=>{const lab=state.labs.find(l=>l.id===id);if(!confirm(`Remove the telemetry configuration lines this manager added on ${lab?lab.name+"'s":'the'} running devices? Your own configuration is not touched.`))return;const result=await json('/labs/'+id+'/telemetry/remove-config','POST',{});notify(result.started.length?`Removing telemetry configuration on ${result.started.join(', ')}.`:'Nothing to remove on the running devices.');dialog.close();});
 if($('tele-retry'))$('tele-retry').onclick=()=>opTask(dialog,async()=>{await json('/labs/'+id+'/telemetry/retry','POST',{});notify('Retrying telemetry on the failed devices.');dialog.close();});
 if($('tele-grafana-stop'))$('tele-grafana-stop').onclick=()=>opTask(dialog,async()=>{const result=await json('/telemetry/grafana/stop','POST',{});$('tele-grafana').textContent=telemetryGrafanaText(result);notify('Dashboard stopped; it starts again when you open it.');});
 return dialog;
}
// What each action asks the student before it runs: title, one-sentence effect, confirm label.
const opReviewCopy={
 deploy:{title:n=>`Start ${n}?`,body:'Creates and starts the devices in this topology. Nothing is deleted; device logins open as the devices boot.',confirm:'Start lab'},
 start:{title:n=>`Start ${n}'s stopped devices?`,body:'Stopped devices start again with their existing configuration.',confirm:'Start devices'},
 stop:{title:()=>'Stop devices?',body:'Devices stop but keep their startup configuration.',confirm:'Stop devices'},
 restart:{title:()=>'Restart devices?',body:'Devices restart from their startup configuration. Open CLI sessions disconnect.',confirm:'Restart devices',danger:true},
 redeploy:{title:n=>`Redeploy ${n}?`,body:'Devices are destroyed and started again from the topology; unsaved device changes are lost. Save progress first if you need them.',confirm:'Redeploy lab',danger:true,cleanup:" The lab's generated folder on the VM is cleared as well."},
 destroy:{title:n=>`Destroy ${n}?`,body:v=>`The running devices are removed from the VM${v.options?.cleanup?" and the lab's generated folder is deleted":''}. Configuration changes you have not saved are lost. Your saved progress, checkpoints and backups remain.`,confirm:'Destroy lab',danger:true},
 apply:{title:n=>`Apply topology changes to ${n}?`,body:'The running lab is updated to match the topology file. Devices removed from the file are destroyed; connectivity may be interrupted.',confirm:'Apply changes',danger:true},
 save:{title:()=>'Save device configurations on the VM?',body:'Each supported device writes its running configuration to its startup configuration on the VM (containerlab save). This is separate from Save progress.',confirm:'Save configurations'},
 inspect:{title:n=>`Refresh the device list for ${n}`,body:"Reads the current state of this lab's devices from the VM. Nothing is changed.",confirm:'Show devices',readonly:true},
 'inspect-all':{title:()=>'Refresh the list of running labs on the VM',body:'Reads which labs are running on the VM. Nothing is changed.',confirm:'Show running labs',readonly:true,hideName:true},
 delete:{title:n=>`Delete ${n}'s topology file from the VM?`,body:v=>`${v.path||'The topology file'} is deleted after a recovery copy is kept. The lab stays in My labs and your saved progress is untouched. Only possible while the lab is not running.`,confirm:'Delete file',danger:true},
 create:{title:()=>'Create this topology file on the VM?',body:v=>`Writes ${v.path||'the file'} on the VM. No devices are started until you deploy it.`,confirm:'Create file'},
 publish:{title:n=>`Save ${n} to the VM?`,body:v=>`Creates the lab folder ${v.folder||''} on the VM with the topology file and the map layout. Nothing on the VM is overwritten and no devices are started until you deploy it.`,confirm:'Save lab',quiet:true},
 revise:{title:n=>`Save the changes to ${n}?`,body:()=>'Replaces the topology file and the map layout on the VM. A copy of the previous version is kept in the lab folder. Only possible while the lab is not deployed.',confirm:'Save changes',quiet:true},
 clone:{title:(n,v)=>`Download ${v?.options?.project||'this lab'}?`,body:v=>`Downloads ${v.options?.url||'the repository'} into the VM's lab folder as ${v.options?.project||'a new folder'}. Existing folders are never overwritten.`,confirm:'Download',hideName:true},
};
// The last-save line of a disruptive confirmation: when the student last saved progress, in red when
// never or when a lab operation ran after the last save.
function opSaveLine(lab,value){
 if(!lab||!opDisruptive.includes(value.action)||typeof progressState!=='function')return '';
 const ps=progressState(lab,state.git_jobs||[]);
 const never=!lab.git_binding||!ps.at;
 const lastOp=(state.operations||[]).filter(j=>j.lab_id===lab.id&&j.finished).sort((a,b)=>String(b.finished).localeCompare(String(a.finished)))[0];
 const stale=!never&&lastOp&&new Date(ps.at)<new Date(lastOp.finished);
 const text=never?(lab.git_binding?'Never saved.':'Never saved — this lab has no save location yet.'):`Last saved ${opWhen(ps.at)} to Git.`;
 return `<p class="op-save-line${never||stale?' danger':''}">${esc(text)}</p>`;
}
async function opReview(request){
 const value=await json('/operations/preview','POST',request);
 // The helper's plan carries no lab id; the request does.
 const labId=request.lab_id||value.lab_id||'';
 const label=opLabels[value.action]||value.action,copy=opReviewCopy[value.action]||{title:()=>label+'?',body:'',confirm:label};
 const lab=typeof current==='function'&&labId&&labId===activeId?current():null;
 const cleanup=!!request.options?.cleanup;
 const title=typeof copy.title==='function'?copy.title(value.name||opName(lab)||'this lab',value):copy.title;
 const body=(typeof copy.body==='function'?copy.body(value):copy.body)+(cleanup&&copy.cleanup?copy.cleanup:'');
 const technicalWarnings=value.warnings.filter(w=>/cleanup/i.test(w)),warnings=value.warnings.filter(w=>!technicalWarnings.includes(w));
 const disruptive=opDisruptive.includes(value.action);
 const dialog=opDialog('operation-review',title,`${copy.hideName?'':`<p><strong>${esc(value.name)}</strong></p><p class="op-path">${esc(value.path||'All labs on the VM')}</p>`}
 ${warnings.map(w=>`<p class="op-notice">${esc(w)}</p>`).join('')}
 <p>${esc(body)}</p>
 ${disruptive&&value.action!=='destroy'?'<p>Configuration changes you have not saved are lost.</p>':''}
 ${opSaveLine(lab,value)}
 ${disruptive?'<p class="op-notice">Open CLI sessions to this lab will disconnect.</p>':''}
 ${copy.readonly||copy.quiet||value.action==='deploy'?'':`<p>${value.affected.length} running ${value.affected.length===1?'device':'devices'} affected</p>`}
 <details><summary>Technical details</summary>${value.affected.length?`<h4>Devices</h4><ul>${value.affected.map(n=>`<li>${esc(n.name)} · ${esc(n.state)}</li>`).join('')}</ul>`:''}<h4>Command run on the VM</h4><pre class="op-output">${esc((value.steps?.length?value.steps:[value.argv]).filter(a=>a.length).map(a=>a.map(v=>JSON.stringify(v)).join(' ')).join('\n')||label)}</pre>${technicalWarnings.map(w=>`<p class="op-notice">${esc(w)}</p>`).join('')}</details>
 ${copy.quiet&&typeof request.options?.text==='string'?`<details ${value.diff?'':'open'}><summary>Topology that will be saved (YAML)</summary><pre class="op-output" id="op-review-yaml">${esc(request.options.text)}</pre></details>`:''}
 ${value.diff?`<details open><summary>Topology file changes</summary><pre class="op-output">${esc(value.diff)}</pre></details>`:''}
 <p class="form-help">Runs on the lab VM. If the lab changes before you confirm, this check is repeated.</p>
 <div class="dialog-actions"><button class="button secondary" id="op-cancel">Cancel</button>${lab&&lab.git_binding&&disruptive&&typeof gitSaveProgress==='function'?'<button class="button secondary" id="op-save-first">Save progress first</button>':''}<button class="button ${copy.danger?'danger':'primary'}" id="op-confirm">${esc(copy.confirm||label)}</button></div>`);
 $('op-cancel').onclick=()=>dialog.close();
 if($('op-save-first'))$('op-save-first').onclick=()=>{dialog.close();opTask(null,gitSaveProgress);};
 $('op-confirm').onclick=()=>opTask(dialog,async()=>{
  const job=await json('/operations/confirm','POST',{token:value.token});dialog.close();
  if($('op-editor')?.open)$('op-editor').close();
  if(typeof selectLab==='function'&&labId&&labId!==activeId&&(state.labs||[]).some(l=>l.id===labId))selectLab(labId);
  await refresh();
  // Lifecycle actions on the open lab report through the header and the banner ([View output]);
  // result-bearing actions open their output right away.
  if(opLifecycle.includes(value.action)&&labId&&labId===activeId&&typeof renderLabBanner==='function'){notify(label+'…');return;}
  await opShowJob(job.id);
 });
}
function opInspectionRows(output){
 let value;
 try{value=JSON.parse(output);}catch{
  // Containerlab may print informational lines before/after the JSON payload.
  const lines=output.split('\n');
  for(let start=0;start<Math.min(lines.length,100);start++){
   if(!/^[\s]*[\[{]/.test(lines[start]))continue;
   for(let end=lines.length;end>Math.max(start,lines.length-100);end--){try{value=JSON.parse(lines.slice(start,end).join('\n'));break;}catch{}}
   if(value!==undefined)break;
  }
 }
 if(!value||typeof value!=='object')return [];
 const groups=Array.isArray(value)?[['',value]]:Object.entries(value),rows=[];
 for(const [lab,nodes] of groups){if(!Array.isArray(nodes))continue;for(const n of nodes){
  if(!n||typeof n!=='object'||!n.name)continue;
  const label=n.labels||{};
  rows.push({topology:n.absLabPath||n.labPath||label['clab-topo-file']||'',lab:n.lab_name||lab,node:n.name,kind:n.kind||'',image:n.image||'',state:[n.state||n.status||'unknown',n.health_status||n.health||''].filter(v=>typeof v==='string'&&v).join(' · '),ipv4:n.ipv4_address||'',ipv6:n.ipv6_address||''});
  if(rows.length>=10000)return rows;
 }}return rows;
}
function opInspectionTable(rows){return `<div class="op-inspection"><table><caption>${rows.length} running ${rows.length===1?'device':'devices'}</caption><thead><tr>${['Topology','Lab','Device','Type / image','State / health','IPv4 / IPv6'].map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.topology)||'—'}</td><td>${esc(r.lab)}</td><td>${esc(r.node)}</td><td>${esc(r.kind)}<small>${esc(r.image)}</small></td><td>${esc(r.state)}</td><td>${esc(r.ipv4)}<small>${esc(r.ipv6)}</small></td></tr>`).join('')}</tbody></table></div>`;}
// The outcome is what a reader looks for first: a large green (or red) banner names
// the action, the lab and the result before the raw command output; the exit code is a detail.
function opJobBanner(job){
 const label=opLabels[job.action]||job.action,done=job.status==='succeeded',failed=['failed','interrupted'].includes(job.status);
 const detail=[job.name,job.message].filter(Boolean).join(' · ');
 const exit=job.exit_code===null||job.exit_code===undefined?'':'Exit code '+job.exit_code;
 return {tone:done?'good':failed?'bad':'running',title:done?`✔ ${label} succeeded`:failed?`✖ ${label} ${job.status}`:`${label} ${job.status}…`,detail,exit};
}
async function opShowJob(id){
 clearTimeout(opOutputTimer);
 const dialog=opDialog('operation-output','Lab operation','<div id="op-job-banner" class="op-banner" hidden></div><pre class="op-output" id="op-job-output" tabindex="0"></pre><div id="op-job-result"></div>');
 // A page that acts on the outcome (the lab builder's opJobDone) hears it even when this dialog was closed
 // while the job ran; a poll that fails is repeated, because one lost answer must not hide how the job ended.
 let fails=0;const follows=typeof opJobDone==='function';
 const poll=async()=>{
  if(!dialog.open&&!follows)return;
  try{
   const job=await(await api('/operations/'+id)).json();fails=0;
   if(!dialog.open){if(['queued','running'].includes(job.status))opOutputTimer=setTimeout(poll,1000);else{await refresh();opJobDone(job);}return;}
   const heading=dialog.querySelector('h2');if(heading)heading.textContent=(opLabels[job.action]||job.action)+(job.name?' · '+job.name:'');
   const banner=opJobBanner(job),shown=$('op-job-banner');shown.hidden=false;shown.className='op-banner '+banner.tone;shown.innerHTML=`<strong>${esc(banner.title)}</strong><span>${esc(banner.detail)}</span>${banner.exit?`<small class="${job.exit_code?'op-exit-bad':''}">${esc(banner.exit)}</small>`:''}`;
   const pre=$('op-job-output'),follow=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-30;pre.textContent=job.output||'Waiting for the VM…';if(follow)pre.scrollTop=pre.scrollHeight;
   const rows=opInspectionRows(job.output||'');
   const inspectAction=['inspect','inspect-all'].includes(job.action);
   dialog.classList.toggle('inspection-dialog',inspectAction);
   const inspected=inspectAction&&job.status==='succeeded'&&rows.length;
   const emptyInspection=inspectAction&&job.status==='succeeded'&&/(^|\n)\s*(?:\[\s*\]|\{\s*\})\s*(?=\n|$)/.test(job.output||'');
   pre.hidden=!!inspected||emptyInspection;
   $('op-job-result').innerHTML=(inspected?opInspectionTable(rows):emptyInspection?'<p>No labs are running on the VM.</p>':'')+(job.result?.recovery_path?`<p>A recovery copy of the ${job.action==='revise'?'previous version':'deleted file'} was kept at <code>${esc(job.result.recovery_path)}</code>.</p>`:'')+(job.result?.project_path?`<button class="button primary" id="op-open-clone">Choose a topology from the downloaded lab</button>`:'')+(job.status==='succeeded'&&job.result?.published_path?`<p>Saved as <code>${esc(job.result.published_path)}</code>. It is not running yet.</p><button class="button primary" id="op-open-published">Deploy or add this lab…</button>`:'');
   $('op-open-published')?.addEventListener('click',()=>opTask(dialog,()=>opEdit(job.result.published_path)));
   $('op-open-clone')?.addEventListener('click',()=>opBrowse(job.result.project_path));
   if(['queued','running'].includes(job.status))opOutputTimer=setTimeout(poll,1000);else{await refresh();if(typeof opJobDone==='function')opJobDone(job);}
  }catch(e){if(dialog.open)dialog.querySelector('.form-error').textContent=++fails<10?e.message+' Trying again…':e.message;else fails++;if(fails<10)opOutputTimer=setTimeout(poll,3000);}
 };dialog.onclose=()=>{if(!follows)clearTimeout(opOutputTimer);};await poll();
}
async function opHistory(labId=''){
 const jobs=await(await api('/operations')).json();
 const lab=labId?(state.labs||[]).find(l=>l.id===labId):null;
 const dialog=opDialog('operation-history','Operation history'+(lab?' · '+lab.name:''),`<p>Past lab operations and their output are kept on this manager.</p><div class="op-history">${jobs.filter(j=>!labId||j.lab_id===labId).map(j=>`<button class="button secondary" data-job="${esc(j.id)}"><strong>${esc(j.name)} · ${esc(opLabels[j.action]||j.action)}</strong><small>${esc(opStatusWord(j.status))} · ${esc(opWhen(j.created))}</small></button>`).join('')||'<p>No lab operations yet. Starting, stopping or redeploying a lab shows up here.</p>'}</div>`);
 dialog.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>opShowJob(b.dataset.job));
}
// Deploy lab keeps the manager in step with the VM: the workspace (nodes, map and VM
// source link) is saved before the command runs, so the lab is in My labs at once
// and NOS logins are verified as soon as its containers start. Nothing to import.
// The VS Code extension keeps a topology's node positions and styling in <file>.annotations.json
// beside it. It is read with the topology so the preview, the saved workspace and the Grafana map
// start from that layout instead of the default grid; a missing or unreadable file means the grid.
async function opReadAnnotations(path){
 if(!path)return '';
 try{return (await json('/operations/read','POST',{path:path+'.annotations.json'})).text||'';}catch{return '';}
}
async function opParse(path,text){
 const annotations=await opReadAnnotations(path);
 const parsed=await json('/operations/parse-yaml','POST',{options:{text,annotations}});
 return {...parsed,annotations:parsed.annotations_used?annotations:''};
}
function opWorkspaceForm(path,source,parsed){
 const form=new FormData(),name=path.split('/').pop();
 form.append('definition',new Blob([source.text],{type:'text/yaml'}),name);
 if(parsed?.annotations)form.append('annotations',new Blob([parsed.annotations],{type:'application/json'}),name+'.annotations.json');
 return form;
}
async function opSaveWorkspace(path,source,parsed,labId=''){
 let id=labId||(state.labs||[]).find(l=>l.deployment_name===parsed.name||opPath(l)===path)?.id||'';
 if(!id)id=(await(await api('/lab-definitions',{method:'POST',body:opWorkspaceForm(path,source,parsed)})).json()).id;
 await json('/labs/'+id+'/operations-settings','PUT',{path});
 activeId=id;sessionStorage.setItem('activeLab',id);
 // On the main page the lab becomes the open lab through the router (history entry, Continue card).
 if(typeof selectLab==='function'&&typeof render==='function')selectLab(id);
 return id;
}
// The lab builder is its own page (static/lab-builder.html). root: the trusted lab folder a new lab
// goes into (the one being browsed, else the manager's project folder); path: an existing topology.
function opBuilderRoot(path,roots){
 const list=(roots||[]).filter(r=>typeof r==='string'&&r),inside=list.filter(r=>path===r||String(path||'').startsWith(r+'/')).sort((a,b)=>b.length-a.length)[0];
 return inside||list.find(r=>r==='/srv/containerlab-node-manager/projects')||list[0]||'/srv/containerlab-node-manager/projects';
}
function opBuilderUrl(values){return '/static/lab-builder.html#'+new URLSearchParams(Object.fromEntries(Object.entries(values).filter(([,v])=>v)));}
// On the builder page itself only the fragment changes, which loads nothing: the page has one editor per load.
function opBuilderOpen(values){const url=opBuilderUrl(values),here=location.pathname==='/static/lab-builder.html';location.assign(url);if(here)location.reload();}
function openDeploy(){return opTask(null,()=>opBrowse());}
function opNewTab(values){const url='/static/workspace.html#'+new URLSearchParams(values);if(!window.open(url,'_blank'))opDialog('op-open-tab','Open the CLI launcher',`<p>Your browser blocked the new tab. Use this button instead:</p><a class="button primary" href="${esc(url)}" target="_blank" rel="opener">Open CLI launcher <span aria-hidden="true">↗</span></a>`);}
function opTopologyEntries(entries){return entries.filter(entry=>entry.directory||/\.clab\.ya?ml$/i.test(entry.name));}
// path: the folder to open; labId: opened as "Lab files · <lab>" starting in the lab's own folder.
async function opBrowse(path='',labId=''){
 const lab=labId?(state.labs||[]).find(l=>l.id===labId):null,labPath=opPath(lab);
 if(lab&&!path&&labPath)path=labPath.includes('/')?labPath.slice(0,labPath.lastIndexOf('/')):'';
 const result=await json('/operations/browse','POST',{path});
 const dialog=opDialog('op-browser',lab?'Lab files · '+lab.name:'Deploy a new lab',`<p class="op-path">${esc(result.path||'Lab folders on the VM')}</p><div class="actions"><button class="button secondary" id="op-roots">All lab folders</button><button class="button secondary" id="op-up">Up one folder</button><button class="button secondary" id="op-build">Build a lab visually…</button><button class="button secondary" id="op-create">Write a new topology…</button><button class="button secondary" id="op-clone">Download a lab from GitHub…</button><button class="button secondary" id="op-popular">Browse popular labs…</button></div><div class="op-file-tree" id="op-file-tree" aria-label="Lab topology files"></div><p class="form-help">Open a folder and pick a topology file (.clab.yaml) to view or deploy it. Only topology files are listed, up to 500 per folder.</p>${lab?'':'<p class="form-help">Have lab files on your computer instead? Use Manager ▾ › Import lab files….</p>'}`);
 const addEntries=(container,entries)=>{
  entries=opTopologyEntries(entries);
  if(!entries.length){container.textContent='No topology files in this folder.';return;}
  for(const entry of entries){
   if(entry.directory){
    const folder=document.createElement('details'),summary=document.createElement('summary'),children=document.createElement('div');
    summary.textContent=entry.name;children.className='op-tree-children';folder.append(summary,children);container.append(folder);
    let loaded=false,loading=false;
    folder.ontoggle=async()=>{if(!folder.open||loaded||loading)return;loading=true;children.textContent='Loading…';try{const listing=await json('/operations/browse','POST',{path:entry.path});children.replaceChildren();addEntries(children,listing.entries);loaded=true;}catch(e){children.textContent=e.message+' Close and reopen this folder to retry.';}finally{loading=false;}};
   }else{const button=document.createElement('button');button.className='op-tree-file';button.textContent='◇ '+entry.name;button.onclick=()=>opTask(dialog,()=>opEdit(entry.path,lab?lab.id:''));container.append(button);}
  }
 };
 addEntries($('op-file-tree'),result.entries);
 $('op-roots').onclick=()=>opTask(dialog,()=>opBrowse());$('op-up').onclick=()=>opTask(dialog,()=>opBrowse(result.parent||''));
 $('op-build').onclick=()=>opBuilderOpen({root:opBuilderRoot(result.path,opCaps?.roots)});
 $('op-create').onclick=()=>opEdit('','',(result.path||'/srv/containerlab-node-manager/projects')+'/new-lab.clab.yaml');$('op-clone').onclick=()=>opClone();$('op-popular').onclick=()=>opTask(dialog,()=>opPopular());
 // Listing files does not depend on Containerlab's command help probes. Render
 // immediately; only the optional network controls need capabilities.
 const clone=$('op-clone'),popular=$('op-popular'),help=dialog.querySelector('.form-help');
 clone.disabled=true;popular.disabled=true;
 opCapabilities().then(caps=>{
  if(!clone.isConnected)return;
  clone.disabled=!caps.network||caps.actions?.clone?.available===false;popular.disabled=!caps.network;
  if(!caps.network)help.textContent+=' Downloading labs from the internet is turned off on this VM. An administrator can enable it (--allow-downloads) in VM setup.';
 }).catch(()=>{
  if(!clone.isConnected)return;
  help.textContent+=' Files are available, but the VM command check failed — open Diagnostics for details. Online downloads stay off.';
 });
}
async function opEdit(path,labId='',newPath=''){
 if(!path)labId='';
 const value=path?await json('/operations/read','POST',{path}):{text:'name: new-lab\ntopology:\n  nodes:\n    r1:\n      kind: linux\n      image: alpine:latest\n',path:newPath};
 const isYaml=/\.ya?ml$/i.test(value.path);
 opEditorContext={path:value.path,labId,isNew:!path};
 const dialog=opDialog('op-editor',path?'Topology file':'New topology file',`<label>File location on the VM<input id="op-edit-path" ${path?'readonly':''}></label><label>${isYaml?'Topology (YAML)':'File contents'}<textarea class="op-code" id="op-edit-text" spellcheck="false" ${path||!isYaml?'readonly':''}></textarea></label><p class="form-help">Deploy lab adds this lab to My labs and starts its devices on the VM. Add without starting keeps it in My labs only. Existing files can't be edited as text here — use Edit visually, or edit them on the VM.</p><div class="actions">${isYaml?'<button class="button secondary" id="op-validate">Preview topology</button>':''}${!path?'<button class="button primary" id="op-save-yaml">Create file on the VM…</button>':''}${path&&isYaml?'<button class="button secondary" id="op-build-edit">Edit visually…</button><button class="button secondary" id="op-add-project">'+(labId?'Link topology':'Add to My labs without starting')+'</button><button class="button primary" id="op-deploy-project">Deploy lab</button>':''}</div>`);
 $('op-edit-path').value=value.path;$('op-edit-text').value=value.text;
 $('op-build-edit')?.addEventListener('click',()=>opBuilderOpen({path}));
 $('op-validate')?.addEventListener('click',()=>opTask(dialog,async()=>{const parsed=await opParse(path,$('op-edit-text').value);opMapPreview(parsed.drawing,parsed.name,parsed.annotations_used);}));
 $('op-save-yaml')?.addEventListener('click',()=>opTask(dialog,()=>opReview({action:'create',lab_id:labId,path:$('op-edit-path').value,options:{text:$('op-edit-text').value}})));
 $('op-add-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  // Always read the actual VM file; unsaved editor contents are not linked/imported.
  const source=await json('/operations/read','POST',{path}),parsed=await opParse(path,source.text);
  const confirm=opDialog('op-add-confirm',labId?'Link lab topology?':`Add ${parsed.name} to My labs?`,`<p>${esc(parsed.name)} · ${parsed.drawing.nodes.length} devices${parsed.annotations_used?' · layout from the saved map file':''}</p><p class="op-path">${esc(path)}</p><p>Adds the lab to My labs and remembers where its topology file is on the VM. No devices are started. Device logins can be imported after the lab is deployed.</p><button class="button primary" id="op-add-confirm-button">${labId?'Link topology':'Add lab'}</button>`);
  $('op-add-confirm-button').onclick=()=>opTask(confirm,async()=>{
   let id=labId;
   if(!id){const lab=await(await api('/lab-definitions',{method:'POST',body:opWorkspaceForm(path,source,parsed)})).json();id=lab.id;}
   await json('/labs/'+id+'/operations-settings','PUT',{path});activeId=id;sessionStorage.setItem('activeLab',id);confirm.close();dialog.close();await refresh();if(typeof selectLab==='function')selectLab(id);notify(parsed.name+' added to My labs.');
  });
 }));
 $('op-deploy-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  const source=await json('/operations/read','POST',{path}),parsed=await opParse(path,source.text);
  const id=await opSaveWorkspace(path,source,parsed,labId);
  await opReview({action:'deploy',lab_id:id,path,name:parsed.name});
 }));
}
function opClone(url='',project=''){
 const dialog=opDialog('op-clone-dialog','Download a lab from GitHub','<label>Repository address<input id="op-clone-url" type="url" placeholder="https://github.com/owner/repository"></label><label>Folder name on the VM<input id="op-clone-name" maxlength="120"></label><p>The lab is downloaded into the VM\'s lab folder (/srv/containerlab-node-manager/projects). Existing folders are never overwritten. Afterwards pick a topology from it to deploy. Needs internet downloads enabled on the VM.</p><button class="button primary" id="op-clone-review">Download…</button>');
 $('op-clone-url').value=url;$('op-clone-name').value=project;
 $('op-clone-review').onclick=()=>opTask(dialog,()=>opReview({action:'clone',options:{url:$('op-clone-url').value,project:$('op-clone-name').value}}));
}
async function opPopular(){
 const data=await(await api('/operations/popular')).json();
 const dialog=opDialog('op-popular-dialog','Popular labs','<p>Community containerlab labs on GitHub (tagged clab-topo, most-starred first). Downloading and deploying are separate steps you confirm.</p><div class="op-history">'+data.items.map((item,i)=>`<button class="button secondary" data-repo="${i}"><strong>${esc(item.name)}</strong><small>${esc(item.description)}</small></button>`).join('')+'</div>');
 dialog.querySelectorAll('[data-repo]').forEach(b=>b.onclick=()=>{const item=data.items[Number(b.dataset.repo)];opClone(item.url,item.name);});
}
function opMapPreview(drawing,name,positioned=false){
 const dialog=opDialog('op-map-preview','Topology preview · '+name,`<svg id="op-preview-map" class="topology-map op-layout-map" role="img" aria-label="Proposed topology"></svg><p>${positioned?'Wiring from the topology file; device positions from its saved map file.':'Wiring from the topology file. Devices sit on a default grid — arrange them later with Edit map.'}</p>`);
 const svg=$('op-preview-map');svg.innerHTML=topologyMarkup(drawing);svg.setAttribute('viewBox',measureTopology(svg).join(' '));return dialog;
}
async function opLayout(id){return editDiagram(id);}
// reason / destroyReason say, in student words, why Start or Destroy is unavailable right now.
function opQuickActions(lab,discovery,isBusy=false){
 const status=lab?.deployment?.status, known=['Not deployed','Running','Stopped','Partially running'].includes(status);
 const available=!!lab&&!!opPath(lab)&&!!discovery?.connected&&known&&!isBusy;
 const blocked=!lab?'':!discovery?.connected?'Connect the VM first':isBusy?'Wait for the current operation to finish':!opPath(lab)?'This lab has no topology file on the VM (Advanced › Deployment details)':!known?'Lab status is unknown — refresh the lab list':'';
 return {startAction:status==='Not deployed'?'deploy':'start',canStart:available&&status!=='Running',canDestroy:available&&status!=='Not deployed',available,reason:blocked||(status==='Running'?'The lab is already running':''),destroyReason:blocked||(status==='Not deployed'?'Nothing to destroy — the lab is not running':'')};
}
async function opQuickRun(kind){
 const lab=current(),actions=opQuickActions(lab,state.discovery,busy());
 if(!lab||!(kind==='start'?actions.canStart:actions.canDestroy))return;
 let options={};
 if(kind!=='start'){try{await opCapabilities();}catch{opCaps=null;}options=opDestroyOptions();}
 await opReview({lab_id:lab.id,action:kind==='start'?actions.startAction:'destroy',options});
}
// Menu items carry their label in a <span> and the reason they are disabled in a visible <small class="menu-reason">.
function opMenuState(button,disabled,reason,label,hint=''){
 if(!button)return;button.disabled=!!disabled;button.title=disabled?reason||'':hint;
 if(typeof button.querySelector!=='function')return;
 const text=button.querySelector('span');if(text&&label!==undefined)text.textContent=label;
 const small=button.querySelector('.menu-reason');if(small){small.textContent=disabled?reason||'':'';small.hidden=!(disabled&&reason);}
}
function renderLabOperations(){
 const lab=current(),quick=opQuickActions(lab,state.discovery,busy()),status=lab?.deployment?.status,running=['Running','Partially running'].includes(status);
 if($('lab-start'))opMenuState($('lab-start'),!quick.canStart,quick.reason,quick.startAction==='deploy'?'Start lab':'Start stopped devices',quick.startAction==='deploy'?'Deploy this topology and start its devices':'Start stopped devices in this lab');
 if($('lab-destroy')){$('lab-destroy').disabled=!quick.canDestroy;$('lab-destroy').title=quick.canDestroy?'':quick.destroyReason;}
 if($('lab-actions'))$('lab-actions').hidden=!current();
 const menu=$('lab-actions-menu');
 if(menu&&typeof menu.querySelectorAll==='function')for(const b of menu.querySelectorAll('[data-op-action]')){
  if(b.dataset.opVariant==='cleanup')b.hidden=opCaps?.actions?.redeploy?.cleanup!==true;
  const capability=opCaps?.actions?.[b.dataset.opAction],unavailable=capability&&capability.available===false;
  const ok=!unavailable&&quick.available&&(b.dataset.opAction==='redeploy'?status!=='Not deployed':running);
  opMenuState(b,!ok,unavailable?'Not available on this VM — see Diagnostics':quick.available?'The lab is not running':quick.reason);
 }
 if($('vm-projects')){const connected=!!state.discovery?.connected;opMenuState($('vm-projects'),!connected,'Connect the VM to browse its lab topologies');}
 // Busy controls carry their reason: the menu proxies and the Advanced buttons read it from the title.
 if(busy()){for(const id of ['remove-lab','sync-vm','update-definition','link-deployment'])if($(id)){$(id).disabled=true;$(id).title='Wait for the current operation to finish';}}
 else{for(const id of ['update-definition','link-deployment'])if($(id)){$(id).disabled=false;$(id).title='';}}
}
if($('import-top')){
 if(!$('lab-actions'))$('import-top').insertAdjacentHTML('beforebegin','<button class="button secondary" id="lab-actions" hidden>All lab operations…</button>');

 $('map-edit').onclick=()=>opTask(null,()=>opLayout(activeId));
 if($('deploy-empty'))$('deploy-empty').onclick=openDeploy;
 if($('lab-operations-all'))$('lab-operations-all').onclick=()=>openLabOperations();
 // Operation history for THIS lab from its menu and its Advanced tab; Manager ▾ keeps the history of every lab.
 for(const id of ['menu-operation-history','advanced-operation-history'])if($(id))$(id).onclick=()=>{if(typeof closeMenus==='function')closeMenus();opTask(null,()=>opHistory(activeId));};
 $('lab-actions').onclick=()=>openLabOperations();$('vm-projects').onclick=()=>openDeploy();$('lab-start').onclick=()=>opTask(null,()=>opQuickRun('start'));$('lab-destroy').onclick=()=>opTask(null,()=>opQuickRun('destroy'));$('operations-history').onclick=()=>opTask(null,()=>opHistory());$('inspect-all').onclick=()=>opTask(null,()=>opReview({action:'inspect-all'}));
 // Lab actions ▾ lifecycle items go through the same preview/confirm flow as the operations dialog.
 const menu=$('lab-actions-menu');
 if(menu){
  menu.addEventListener('click',e=>{const b=e.target.closest('[data-op-action]');if(!b||b.disabled)return;if(typeof closeMenus==='function')closeMenus();
   opTask(null,async()=>{const lab=current();if(!lab)return;try{await opCapabilities();}catch{opCaps=null;}renderLabOperations();await opReview({lab_id:lab.id,action:b.dataset.opAction,options:JSON.parse(b.dataset.opOptions||'{}')});});});
  menu.addEventListener('menuopen',()=>{if(opCaps)return;opCapabilities().then(()=>renderLabOperations()).catch(()=>{});});
 }
 $('labs').addEventListener('contextmenu',e=>{const lab=e.target.closest('[data-lab]');if(lab){e.preventDefault();openLabOperations(lab.dataset.lab);}});
 $('labs').addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){const lab=e.target.closest('[data-lab]');if(lab){e.preventDefault();openLabOperations(lab.dataset.lab);}}});
}
