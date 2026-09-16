'use strict';
// Shared by the main workspace and independent VM-folder / SSH-launcher tabs.
const opLabels={deploy:'Deploy lab',redeploy:'Redeploy',destroy:'Destroy deployment',apply:'Apply topology',start:'Start lab nodes',stop:'Stop lab nodes',restart:'Restart lab nodes',save:'Save configurations (clab)',inspect:'Inspect lab','inspect-all':'View running lab details',create:'Create VM topology',delete:'Delete undeployed VM YAML',clone:'Clone repository'};
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
async function opCapabilities(){opCaps=await(await api('/operations/capabilities')).json();return opCaps;}
function opCommand(action,label=opLabels[action],options={}){
 const cap=opCaps?.actions?.[action], unavailable=cap&&!cap.available;
 return `<button class="button secondary" data-op-action="${esc(action)}" data-op-options="${esc(JSON.stringify(options))}" ${unavailable?'disabled':''}>${esc(label||action)}${unavailable?'<small>Unavailable on this VM</small>':''}</button>`;
}
// Destroy always runs containerlab destroy --cleanup: the containers go together with the generated
// lab folder (clab-<name>: TLS material, generated startup files), so the next deploy starts clean.
// The helper refuses the flag on a containerlab without it, so the flag is only sent when the
// installed command is known to have it or the capabilities could not be read at all.
function opDestroyOptions(caps=opCaps){return caps?.actions?.destroy?.cleanup===false?{}:{cleanup:true};}
async function openLabOperations(id=activeId){
 opMenuLab=id;const lab=state.labs.find(l=>l.id===id);if(!lab)return;
 const dialog=opDialog('lab-operations-dialog',lab.name,'<p>Checking installed VM commands…</p>');
 let problem='';try{await opCapabilities();}catch(e){opCaps=null;problem=e.message;}
 if(!dialog.open)return;
 const cleanup=['deploy','redeploy'].filter(a=>opCaps?.actions[a]?.cleanup).map(a=>opCommand(a,opLabels[a]+' + cleanup',{cleanup:true})).join('');
 opDialog(dialog.id,lab.name,`<p class="op-path">${esc(opPath(lab)||'Import the original VM lab files before using host commands.')}</p>${problem?`<p class="op-notice">${esc(problem)}</p>`:''}
 <div class="op-sections"><section><h3>Deployment & configuration</h3><div class="op-grid">${['deploy','redeploy','apply','start','stop','restart','inspect','save'].map(a=>opCommand(a)).join('')}${opCommand('destroy',opLabels.destroy,opDestroyOptions())}${cleanup}</div><p class="form-help">Destroy removes the containers and the generated lab folder (containerlab destroy --cleanup); redeploy keeps that folder unless you choose its cleanup variant. Containerlab save supports selected device kinds; manager backups remain in Backup history.</p></section>
 <section><h3>Workspace & access</h3><div class="op-grid"><button class="button secondary" data-local="ssh">SSH all nodes ↗</button><button class="button secondary" data-local="favorite">${lab.favorite?'Remove favorite':'Favorite lab'}</button><button class="button secondary" data-local="interactive">Edit topology diagram</button><button class="button secondary" data-local="telemetry">Telemetry settings…</button><button class="button secondary" data-local="history">Operation history</button>${opCommand('delete')}</div></section></div>`);
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
// Per-lab telemetry: on/off, the gNMI login profile, the removal of manager-added lines and
// the reason a node is not streaming. The data itself is read in Grafana, never here.
const teleStateLabels={disabled:'off',waiting:'waiting',configuring:'configuring',connecting:'connecting',streaming:'streaming',stale:'stale',unsupported:'unsupported',failed:'failed',unmonitored:'unmonitored'};
function telemetrySummaryText(data){
 const s=data.settings||{},sum=data.summary||{};
 if(!data.enabled)return data.unavailable||'The telemetry collector is disabled in this manager.';
 if(!data.linked)return 'Telemetry is collected for labs linked to a VM deployment; this lab is not linked.';
 if(!s.decided)return 'This lab was saved before automatic telemetry existed. Nothing is written to a device until you turn it on here.';
 if(!s.auto)return 'Automatic telemetry is off for this lab; Grafana shows nothing for it.';
 const parts=['streaming','stale','waiting','configuring','connecting','failed','unsupported'].filter(k=>sum[k]).map(k=>`${sum[k]} ${teleStateLabels[k]}`);
 return `Automatic telemetry is on: ${sum.total||0} supported node${sum.total===1?'':'s'}${parts.length?' · '+parts.join(' · '):''}. Read the data in Grafana.`;
}
// Grafana runs on the VM only while someone reads it; the manager starts it from the lab header's
// button and stops it after the idle time. Its state and a manual stop live in the same dialog.
function telemetryGrafanaText(g){
 if(!g)return 'Grafana: state unavailable.';
 if(!g.enabled)return 'Grafana: not installed on this manager.';
 if(g.running)return `Grafana: running on TCP ${g.port}${g.idle_minutes?`; stops after ${g.idle_minutes} minute${g.idle_minutes===1?'':'s'} without an open dashboard`:'; the automatic stop is off'}.`;
 if(g.running===false)return 'Grafana: stopped; it starts when you open it from the lab header.';
 return 'Grafana: not checked yet.';
}
async function openTelemetrySettings(id=activeId){
 const data=await(await api('/labs/'+id+'/telemetry')).json();
 let grafana=null;try{grafana=await(await api('/telemetry/grafana')).json();}catch{grafana=null;}
 const s=data.settings||{},profiles=data.password_profiles||[],usable=data.enabled&&data.linked;
 const failed=(data.nodes||[]).filter(n=>['failed','stale'].includes(n.state));
 const dialog=opDialog('telemetry-settings-dialog','Telemetry settings',`<p class="form-help">${esc(telemetrySummaryText(data))}</p>${failed.length?`<ul class="form-help">${failed.map(n=>`<li><strong>${esc(n.short_name||n.name)}</strong> (${esc(teleStateLabels[n.state]||n.state)}): ${esc(n.message||'')}</li>`).join('')}</ul>`:''}<p class="form-help" id="tele-grafana">${esc(telemetryGrafanaText(grafana))}${grafana?.running?' <button class="button secondary" id="tele-grafana-stop" type="button">Stop Grafana now</button>':''}</p><label class="checkbox-label"><input type="checkbox" id="tele-auto" ${s.auto?'checked':''} ${usable?'':'disabled'}> Automatic telemetry: configure the gNMI service on supported nodes and stream counters to Grafana</label><p class="form-help">Applies to cEOS, XRv9k and cJunosEvolved nodes once they answer show version. The manager adds only the missing service lines with each NOS's own scoped commit and never saves the whole running configuration. The manager keeps the last 15 minutes in memory for Prometheus to scrape; a stop, destroy, redeploy or removal clears it.</p><label>gNMI login<select id="tele-profile" ${usable?'':'disabled'}><option value="">Each node's saved password login (profile, inventory or containerlab default)</option>${profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===s.profile_id?'selected':''}>${esc(p.label)} · ${esc(p.platform)}</option>`).join('')}</select></label><p class="form-help">gNMI needs a username and password; nodes that log in with an SSH key need a password profile here. Secrets never leave the manager.</p><div class="dialog-actions">${failed.length?'<button class="button secondary" id="tele-retry">Retry failed nodes</button>':''}<button class="button secondary" id="tele-remove" ${s.auto||!usable?'disabled title="Disable automatic telemetry first"':''}>Remove manager-added lines…</button><button class="button primary" id="tele-save" ${usable?'':'disabled'}>Save</button></div><p class="form-help">Remove deletes only the telemetry configuration lines this manager recorded as its own, on running nodes, over SSH. Disabling telemetry alone leaves the device configuration as it is.</p>`);
 $('tele-save').onclick=()=>opTask(dialog,async()=>{const auto=$('tele-auto').checked;await json('/labs/'+id+'/telemetry/settings','PUT',{auto,profile_id:$('tele-profile').value||''});notify(auto?'Automatic telemetry enabled. Supported nodes are configured as they become ready; open Grafana to watch them.':'Automatic telemetry disabled; collection stopped.');dialog.close();await refresh();});
 $('tele-remove').onclick=()=>opTask(dialog,async()=>{if(!confirm('Remove the telemetry configuration lines the manager added on the running nodes of this lab?'))return;const result=await json('/labs/'+id+'/telemetry/remove-config','POST',{});notify(result.started.length?`Removal started on ${result.started.join(', ')}.`:'Nothing to remove on running nodes.');dialog.close();});
 if($('tele-retry'))$('tele-retry').onclick=()=>opTask(dialog,async()=>{await json('/labs/'+id+'/telemetry/retry','POST',{});notify('Retry requested for the failed nodes.');dialog.close();});
 if($('tele-grafana-stop'))$('tele-grafana-stop').onclick=()=>opTask(dialog,async()=>{const result=await json('/telemetry/grafana/stop','POST',{});$('tele-grafana').textContent=telemetryGrafanaText(result);notify('Grafana stopped on the VM; it starts again when you open it.');});
 return dialog;
}
async function opReview(request){
 const value=await json('/operations/preview','POST',request);
 const label=opLabels[value.action]||value.action;
 const dialog=opDialog('operation-review',label+'?',`<p><strong>${esc(value.name)}</strong></p><p class="op-path">${esc(value.path||'All deployed labs on the configured VM')}</p>
 ${value.warnings.map(w=>`<p class="op-notice">${esc(w)}</p>`).join('')}
 ${['stop','restart','redeploy','destroy','apply'].includes(value.action)?'<p class="op-notice">This can interrupt lab connectivity and open SSH sessions.</p>':''}
 ${value.action==='delete'?'<p class="op-notice">Deletes the original YAML on the VM after preserving a recovery copy. The saved manager workspace remains.</p>':''}
 <p>${value.action==='deploy'?'Creates and starts the devices defined in this topology.':value.affected.length+' deployed containers affected'}</p>${value.affected.length?`<details><summary>Affected containers</summary><ul>${value.affected.map(n=>`<li>${esc(n.name)} · ${esc(n.state)}</li>`).join('')}</ul></details>`:''}
 <details><summary>Containerlab command</summary><pre class="op-output">${esc((value.steps?.length?value.steps:[value.argv]).filter(a=>a.length).map(a=>a.map(v=>JSON.stringify(v)).join(' ')).join('\n')||label)}</pre></details>
 ${value.diff?`<details open><summary>YAML changes</summary><pre class="op-output">${esc(value.diff)}</pre></details>`:''}
 <p class="form-help">Confirm to run this action on the VM. If the topology or deployment changes, open this confirmation again.</p>
 <div class="dialog-actions"><button class="button secondary" id="op-cancel">Cancel</button><button class="button primary" id="op-confirm">${esc(label)}</button></div>`);
 $('op-cancel').onclick=()=>dialog.close();$('op-confirm').onclick=()=>opTask(dialog,async()=>{
  const job=await json('/operations/confirm','POST',{token:value.token});dialog.close();
  if($('op-editor')?.open)$('op-editor').close();await refresh();await opShowJob(job.id);
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
function opInspectionTable(rows){return `<div class="op-inspection"><table><caption>${rows.length} deployed nodes</caption><thead><tr>${['Topology','Lab','Node','Kind / image','State / health','IPv4 / IPv6'].map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.topology)||'—'}</td><td>${esc(r.lab)}</td><td>${esc(r.node)}</td><td>${esc(r.kind)}<small>${esc(r.image)}</small></td><td>${esc(r.state)}</td><td>${esc(r.ipv4)}<small>${esc(r.ipv6)}</small></td></tr>`).join('')}</tbody></table></div>`;}
// The outcome is what a reader looks for first: a large green (or red) banner names
// the action, the lab and the exit code before the raw command output.
function opJobBanner(job){
 const label=opLabels[job.action]||job.action,done=job.status==='succeeded',failed=['failed','interrupted'].includes(job.status);
 const detail=[job.name,job.exit_code===null||job.exit_code===undefined?'':'Exit '+job.exit_code,job.message].filter(Boolean).join(' · ');
 return {tone:done?'good':failed?'bad':'running',title:done?`✔ ${label} succeeded`:failed?`✖ ${label} ${job.status}`:`${label} ${job.status}…`,detail};
}
async function opShowJob(id){
 clearTimeout(opOutputTimer);
 const dialog=opDialog('operation-output','Operation output','<div id="op-job-banner" class="op-banner" hidden></div><pre class="op-output" id="op-job-output" tabindex="0"></pre><div id="op-job-result"></div>');
 const poll=async()=>{
  if(!dialog.open)return;
  try{
   const job=await(await api('/operations/'+id)).json();
   const banner=opJobBanner(job),shown=$('op-job-banner');shown.hidden=false;shown.className='op-banner '+banner.tone;shown.innerHTML=`<strong>${esc(banner.title)}</strong><span>${esc(banner.detail)}</span>`;
   const pre=$('op-job-output'),follow=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-30;pre.textContent=job.output||'Waiting for command output…';if(follow)pre.scrollTop=pre.scrollHeight;
   const rows=opInspectionRows(job.output||'');
   const inspectAction=['inspect','inspect-all'].includes(job.action);
   dialog.classList.toggle('inspection-dialog',inspectAction);
   const inspected=inspectAction&&job.status==='succeeded'&&rows.length;
   const emptyInspection=inspectAction&&job.status==='succeeded'&&/(^|\n)\s*(?:\[\s*\]|\{\s*\})\s*(?=\n|$)/.test(job.output||'');
   pre.hidden=!!inspected||emptyInspection;
   $('op-job-result').innerHTML=(inspected?opInspectionTable(rows):emptyInspection?'<p>No deployed nodes found.</p>':'')+(job.result?.recovery_path?`<p>Recovery copy: <code>${esc(job.result.recovery_path)}</code></p>`:'')+(job.result?.project_path?`<button class="button secondary" id="op-open-clone">Browse cloned lab topologies</button>`:'');
   $('op-open-clone')?.addEventListener('click',()=>opBrowse(job.result.project_path));
   if(['queued','running'].includes(job.status))opOutputTimer=setTimeout(poll,1000);else await refresh();
  }catch(e){dialog.querySelector('.form-error').textContent=e.message;}
 };dialog.onclose=()=>clearTimeout(opOutputTimer);await poll();
}
async function opHistory(labId=''){
 const jobs=await(await api('/operations')).json();
 const dialog=opDialog('operation-history','Operation history',`<p>Saved command output remains in persistent manager storage.</p><div class="op-history">${jobs.filter(j=>!labId||j.lab_id===labId).map(j=>`<button class="button secondary" data-job="${esc(j.id)}"><strong>${esc(j.name)} · ${esc(opLabels[j.action]||j.action)}</strong><small>${esc(j.status)} · ${esc(new Date(j.created).toLocaleString())}</small></button>`).join('')||'<p>No lab operations yet.</p>'}</div>`);
 dialog.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>opShowJob(b.dataset.job));
}
// Deploy lab keeps the manager in step with the VM: the workspace (nodes, map and VM
// source link) is saved before the command runs, so the lab is in the sidebar at once
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
 return id;
}
function openDeploy(){return opTask(null,()=>opBrowse());}
function opNewTab(values){const url='/static/workspace.html#'+new URLSearchParams(values);if(!window.open(url,'_blank'))opDialog('op-open-tab','Open workspace',`<p>Your browser may have blocked the new tab.</p><a class="button primary" href="${esc(url)}" target="_blank" rel="opener">Open workspace ↗</a>`);}
function opTopologyEntries(entries){return entries.filter(entry=>entry.directory||/\.clab\.ya?ml$/i.test(entry.name));}
async function opBrowse(path=''){
 const result=await json('/operations/browse','POST',{path});
 const dialog=opDialog('op-browser','Lab Topologies',`<p class="op-path">${esc(result.path||'Lab topology folders')}</p><div class="actions"><button class="button secondary" id="op-roots">Lab folders</button><button class="button secondary" id="op-up">Parent folder</button><button class="button secondary" id="op-create">New topology</button><button class="button secondary" id="op-clone">Clone repository</button><button class="button secondary" id="op-popular">Popular labs</button></div><div class="op-file-tree" id="op-file-tree" aria-label="Lab topology files"></div><p class="form-help">Expand a folder and select a .clab.yaml or .clab.yml topology to view or deploy. Other files are hidden. Each folder shows at most 500 matching entries.</p>`);
 const addEntries=(container,entries)=>{
  entries=opTopologyEntries(entries);
  if(!entries.length){container.textContent='No lab topologies or subfolders here.';return;}
  for(const entry of entries){
   if(entry.directory){
    const folder=document.createElement('details'),summary=document.createElement('summary'),children=document.createElement('div');
    summary.textContent=entry.name;children.className='op-tree-children';folder.append(summary,children);container.append(folder);
    let loaded=false,loading=false;
    folder.ontoggle=async()=>{if(!folder.open||loaded||loading)return;loading=true;children.textContent='Loading…';try{const listing=await json('/operations/browse','POST',{path:entry.path});children.replaceChildren();addEntries(children,listing.entries);loaded=true;}catch(e){children.textContent=e.message+' Close and reopen this folder to retry.';}finally{loading=false;}};
   }else{const button=document.createElement('button');button.className='op-tree-file';button.textContent='◇ '+entry.name;button.onclick=()=>opTask(dialog,()=>opEdit(entry.path));container.append(button);}
  }
 };
 addEntries($('op-file-tree'),result.entries);
 $('op-roots').onclick=()=>opTask(dialog,()=>opBrowse());$('op-up').onclick=()=>opTask(dialog,()=>opBrowse(result.parent||''));
 $('op-create').onclick=()=>opEdit('','',(result.path||'/srv/containerlab-node-manager/projects')+'/new-lab.clab.yaml');$('op-clone').onclick=()=>opClone();$('op-popular').onclick=()=>opTask(dialog,()=>opPopular());
 // Listing files does not depend on Containerlab's command help probes. Render
 // immediately; only the optional network controls need capabilities.
 const clone=$('op-clone'),popular=$('op-popular'),help=dialog.querySelector('.form-help');
 clone.disabled=true;popular.disabled=true;
 opCapabilities().then(caps=>{
  if(!clone.isConnected)return;
  clone.disabled=!caps.network||caps.actions?.clone?.available===false;popular.disabled=!caps.network;
  if(!caps.network)help.textContent+=' Online downloads are disabled. Enable --allow-downloads in VM setup for cloning and the catalog.';
 }).catch(()=>{
  if(!clone.isConnected)return;
  help.textContent+=' Files are available, but command checks failed. Open the Debug panel to check VM helpers. Online actions remain disabled.';
 });
}
async function opEdit(path,labId='',newPath=''){
 if(!path)labId='';
 const value=path?await json('/operations/read','POST',{path}):{text:'name: new-lab\ntopology:\n  nodes:\n    r1:\n      kind: linux\n      image: alpine:latest\n',path:newPath};
 const isYaml=/\.ya?ml$/i.test(value.path);
 opEditorContext={path:value.path,labId,isNew:!path};
 const dialog=opDialog('op-editor',path?'Lab topology':'Create lab topology',`<label>Absolute VM path<input id="op-edit-path" ${path?'readonly':''}></label><label>${isYaml?'Topology YAML':'File contents'}<textarea class="op-code" id="op-edit-text" spellcheck="false" ${path||!isYaml?'readonly':''}></textarea></label><p class="form-help">Choose Deploy lab to save this topology as a workspace and start its devices on the VM; the lab appears in the manager right away and SSH opens as the devices boot. Save to manager keeps the workspace without deploying. Existing files are read-only; edit them on the VM.</p><div class="actions">${isYaml?'<button class="button secondary" id="op-validate">Validate / preview topology</button>':''}${!path?'<button class="button primary" id="op-save-yaml">Review creation on VM</button>':''}${path&&isYaml?'<button class="button secondary" id="op-add-project">'+(labId?'Link topology':'Save to manager')+'</button><button class="button primary" id="op-deploy-project">Deploy lab</button>':''}</div>`);
 $('op-edit-path').value=value.path;$('op-edit-text').value=value.text;
 $('op-validate')?.addEventListener('click',()=>opTask(dialog,async()=>{const parsed=await opParse(path,$('op-edit-text').value);opMapPreview(parsed.drawing,parsed.name,parsed.annotations_used);}));
 $('op-save-yaml')?.addEventListener('click',()=>opTask(dialog,()=>opReview({action:'create',lab_id:labId,path:$('op-edit-path').value,options:{text:$('op-edit-text').value}})));
 $('op-add-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  // Always read the actual VM file; unsaved editor contents are not linked/imported.
  const source=await json('/operations/read','POST',{path}),parsed=await opParse(path,source.text);
  const confirm=opDialog('op-add-confirm',labId?'Link lab topology?':'Save lab to manager?',`<p>${esc(parsed.name)} · ${parsed.drawing.nodes.length} nodes${parsed.annotations_used?' · positions from the annotations file':''}</p><p class="op-path">${esc(path)}</p><p>This saves a manager workspace and links its original VM source. It does not deploy containers. Device credentials can be imported from discovered VM files after deployment.</p><button class="button primary" id="op-add-confirm-button">${labId?'Link topology':'Save lab'}</button>`);
  $('op-add-confirm-button').onclick=()=>opTask(confirm,async()=>{
   let id=labId;
   if(!id){const lab=await(await api('/lab-definitions',{method:'POST',body:opWorkspaceForm(path,source,parsed)})).json();id=lab.id;}
   await json('/labs/'+id+'/operations-settings','PUT',{path});activeId=id;sessionStorage.setItem('activeLab',id);confirm.close();dialog.close();await refresh();notify('Lab topology saved to the manager.');
  });
 }));
 $('op-deploy-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  const source=await json('/operations/read','POST',{path}),parsed=await opParse(path,source.text);
  const id=await opSaveWorkspace(path,source,parsed,labId);
  await opReview({action:'deploy',lab_id:id,path,name:parsed.name});
 }));
}
function opClone(url='',project=''){
 const dialog=opDialog('op-clone-dialog','Clone a lab repository','<label>HTTPS repository URL<input id="op-clone-url" type="url" placeholder="https://github.com/owner/repository"></label><label>New project folder name<input id="op-clone-name" maxlength="120"></label><p>Requires --allow-downloads on the VM. The destination is /srv/containerlab-node-manager/projects. Existing folders are never overwritten. After cloning, browse the project, review its files, and choose a topology to deploy.</p><button class="button primary" id="op-clone-review">Review clone</button>');
 $('op-clone-url').value=url;$('op-clone-name').value=project;
 $('op-clone-review').onclick=()=>opTask(dialog,()=>opReview({action:'clone',options:{url:$('op-clone-url').value,project:$('op-clone-name').value}}));
}
async function opPopular(){
 const data=await(await api('/operations/popular')).json();
 const dialog=opDialog('op-popular-dialog','Popular lab topologies','<p>SRL Labs repositories tagged clab-topo, ordered by GitHub stars. Cloning and deployment are separate reviewed steps.</p><div class="op-history">'+data.items.map((item,i)=>`<button class="button secondary" data-repo="${i}"><strong>${esc(item.name)}</strong><small>${esc(item.description)}</small></button>`).join('')+'</div>');
 dialog.querySelectorAll('[data-repo]').forEach(b=>b.onclick=()=>{const item=data.items[Number(b.dataset.repo)];opClone(item.url,item.name);});
}
function opMapPreview(drawing,name,positioned=false){
 const dialog=opDialog('op-map-preview','Topology preview · '+name,`<svg id="op-preview-map" class="topology-map op-layout-map" role="img" aria-label="Proposed topology"></svg><p>${positioned?'Wiring from the YAML, node positions from the annotations file beside it; the saved workspace starts from this layout.':'Wiring from the YAML; the nodes sit on the default grid because no annotations file was found beside the topology (Edit diagram moves them later).'}</p>`);
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
  const ok=quick.available&&(b.dataset.opAction==='redeploy'?status!=='Not deployed':running);
  opMenuState(b,!ok,quick.available?'The lab is not running':quick.reason);
 }
 if($('vm-projects')){const connected=!!state.discovery?.connected;opMenuState($('vm-projects'),!connected,'Connect the VM to browse its lab topologies');}
 if(busy()){for(const id of ['remove-lab','sync-vm','update-definition','link-deployment'])if($(id))$(id).disabled=true;}
 else{for(const id of ['update-definition','link-deployment'])if($(id))$(id).disabled=false;}
}
if($('import-top')){
 if(!$('lab-actions'))$('import-top').insertAdjacentHTML('beforebegin','<button class="button secondary" id="lab-actions" hidden>Lab actions ▾</button>');

 $('map-edit').onclick=()=>opTask(null,()=>opLayout(activeId));
 if($('deploy-empty'))$('deploy-empty').onclick=openDeploy;
 if($('lab-operations-all'))$('lab-operations-all').onclick=()=>openLabOperations();
 $('lab-actions').onclick=()=>openLabOperations();$('vm-projects').onclick=()=>openDeploy();$('lab-start').onclick=()=>opTask(null,()=>opQuickRun('start'));$('lab-destroy').onclick=()=>opTask(null,()=>opQuickRun('destroy'));$('operations-history').onclick=()=>opHistory();$('inspect-all').onclick=()=>opTask(null,()=>opReview({action:'inspect-all'}));
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
