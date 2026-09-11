'use strict';
// Shared by the main workspace and independent VM-folder / SSH-launcher tabs.
const opLabels={deploy:'Deploy lab',redeploy:'Redeploy',destroy:'Destroy deployment',apply:'Apply topology',start:'Start lab nodes',stop:'Stop lab nodes',restart:'Restart lab nodes',save:'Save configurations (clab)',inspect:'Inspect lab','inspect-all':'View running lab details',create:'Create VM topology',delete:'Delete undeployed VM YAML',clone:'Clone repository'};
let opCaps=null, opMenuLab='', opOutputTimer=null, opEditorContext=null;
function opDialog(id,title,body){
 let dialog=$(id);if(!dialog){dialog=document.createElement('dialog');dialog.id=id;dialog.className='operations-dialog';document.body.append(dialog);}
 dialog.innerHTML=`<div class="dialog-head"><span class="eyebrow">NODE MANAGER</span><button class="icon-button" data-op-close aria-label="Close">×</button></div><h2>${esc(title)}</h2>${body}<p class="form-error" role="alert"></p>`;
 dialog.querySelector('[data-op-close]').onclick=()=>dialog.close();if(!dialog.open)dialog.showModal();return dialog;
}
async function opTask(dialog,fn){
 const error=dialog?.querySelector('.form-error');if(error)error.textContent='';
 const buttons=dialog?[...dialog.querySelectorAll('button:not(:disabled)')]:[];buttons.forEach(b=>b.disabled=true);
 try{return await fn();}catch(e){if(error)error.textContent=e.message;else notify(e.message);}finally{buttons.forEach(b=>b.disabled=false);}
}
function opPath(lab){return lab?.vm_project_path||lab?.vm_source?.files?.definition?.path||'';}
function opName(lab){return lab?.deployment_name||lab?.name||'';}
async function opCapabilities(){opCaps=await(await api('/operations/capabilities')).json();return opCaps;}
function opCommand(action,label=opLabels[action],options={}){
 const cap=opCaps?.actions?.[action], unavailable=cap&&!cap.available;
 return `<button class="button secondary" data-op-action="${esc(action)}" data-op-options="${esc(JSON.stringify(options))}" ${unavailable?'disabled':''}>${esc(label||action)}${unavailable?'<small>Unavailable on this VM</small>':''}</button>`;
}
async function openLabOperations(id=activeId){
 opMenuLab=id;const lab=state.labs.find(l=>l.id===id);if(!lab)return;
 const dialog=opDialog('lab-operations-dialog',lab.name,'<p>Checking installed VM commands…</p>');
 let problem='';try{await opCapabilities();}catch(e){opCaps=null;problem=e.message;}
 if(!dialog.open)return;
 const cleanup=['deploy','redeploy','destroy'].filter(a=>opCaps?.actions[a]?.cleanup).map(a=>opCommand(a,opLabels[a]+' + cleanup',{cleanup:true})).join('');
 opDialog(dialog.id,lab.name,`<p class="op-path">${esc(opPath(lab)||'Import the original VM lab files before using host commands.')}</p>${problem?`<p class="op-notice">${esc(problem)}</p>`:''}
 <div class="op-sections"><section><h3>Deployment & configuration</h3><div class="op-grid">${['deploy','redeploy','apply','start','stop','restart','inspect','save','destroy'].map(a=>opCommand(a)).join('')}${cleanup}</div><p class="form-help">Destroy removes containers. Cleanup also removes generated lab artifacts. Containerlab save supports selected device kinds; manager backups remain in Backup history.</p></section>
 <section><h3>Workspace & access</h3><div class="op-grid"><button class="button secondary" data-local="ssh">SSH all nodes ↗</button><button class="button secondary" data-local="favorite">${lab.favorite?'Remove favorite':'Favorite lab'}</button><button class="button secondary" data-local="interactive">Edit topology diagram</button><button class="button secondary" data-local="history">Operation history</button>${opCommand('delete')}</div></section></div>`);
 dialog.querySelectorAll('[data-op-action]').forEach(b=>b.onclick=()=>{
  const action=b.dataset.opAction,options=JSON.parse(b.dataset.opOptions);
  opTask(dialog,()=>opReview({lab_id:id,action,options}));
 });
 dialog.querySelectorAll('[data-local]').forEach(b=>b.onclick=()=>opTask(dialog,async()=>{
  const action=b.dataset.local;
  if(action==='ssh')opNewTab({mode:'ssh',lab:id});
  if(action==='favorite'){await json('/labs/'+id+'/operations-settings','PUT',{favorite:!lab.favorite});await refresh();dialog.close();}
  if(action==='interactive')await opLayout(id);
  if(action==='history')await opHistory(id);
 }));
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
async function opShowJob(id){
 clearTimeout(opOutputTimer);
 const dialog=opDialog('operation-output','Operation output','<p id="op-job-state"></p><pre class="op-output" id="op-job-output" tabindex="0"></pre><div id="op-job-result"></div>');
 const poll=async()=>{
  if(!dialog.open)return;
  try{
   const job=await(await api('/operations/'+id)).json();
   $('op-job-state').textContent=[job.name,opLabels[job.action]||job.action,job.status,job.exit_code===null?'':'Exit '+job.exit_code,job.message].filter(Boolean).join(' · ');
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
 const dialog=opDialog('op-editor',path?'Lab topology':'Create lab topology',`<label>Absolute VM path<input id="op-edit-path" ${path?'readonly':''}></label><label>${isYaml?'Topology YAML':'File contents'}<textarea class="op-code" id="op-edit-text" spellcheck="false" ${path||!isYaml?'readonly':''}></textarea></label><p class="form-help">View the topology, then choose Deploy lab to create and start its devices on the VM. Saving to the manager alone does not deploy it. Existing files are read-only; edit them on the VM.</p><div class="actions">${isYaml?'<button class="button secondary" id="op-validate">Validate / preview topology</button>':''}${!path?'<button class="button primary" id="op-save-yaml">Review creation on VM</button>':''}${path&&isYaml?'<button class="button secondary" id="op-add-project">'+(labId?'Link topology':'Save to manager')+'</button><button class="button primary" id="op-deploy-project">Deploy lab</button>':''}</div>`);
 $('op-edit-path').value=value.path;$('op-edit-text').value=value.text;
 $('op-validate')?.addEventListener('click',()=>opTask(dialog,async()=>{const parsed=await json('/operations/parse-yaml','POST',{options:{text:$('op-edit-text').value}});opMapPreview(parsed.drawing,parsed.name);}));
 $('op-save-yaml')?.addEventListener('click',()=>opTask(dialog,()=>opReview({action:'create',lab_id:labId,path:$('op-edit-path').value,options:{text:$('op-edit-text').value}})));
 $('op-add-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  // Always read the actual VM file; unsaved editor contents are not linked/imported.
  const source=await json('/operations/read','POST',{path}),parsed=await json('/operations/parse-yaml','POST',{options:{text:source.text}});
  const confirm=opDialog('op-add-confirm',labId?'Link lab topology?':'Save lab to manager?',`<p>${esc(parsed.name)} · ${parsed.drawing.nodes.length} nodes</p><p class="op-path">${esc(path)}</p><p>This saves a manager workspace and links its original VM source. It does not deploy containers. Device credentials can be imported from discovered VM files after deployment.</p><button class="button primary" id="op-add-confirm-button">${labId?'Link topology':'Save lab'}</button>`);
  $('op-add-confirm-button').onclick=()=>opTask(confirm,async()=>{
   let id=labId;
   if(!id){const form=new FormData();form.append('definition',new Blob([source.text],{type:'text/yaml'}),path.split('/').pop());const lab=await(await api('/lab-definitions',{method:'POST',body:form})).json();id=lab.id;}
   await json('/labs/'+id+'/operations-settings','PUT',{path});activeId=id;sessionStorage.setItem('activeLab',id);confirm.close();dialog.close();await refresh();notify('Lab topology saved to the manager.');
  });
 }));
 $('op-deploy-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  const source=await json('/operations/read','POST',{path}),parsed=await json('/operations/parse-yaml','POST',{options:{text:source.text}});
  await opReview({action:'deploy',lab_id:labId,path,name:parsed.name});
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
function opMapPreview(drawing,name){
 const dialog=opDialog('op-map-preview','Topology preview · '+name,'<svg id="op-preview-map" class="topology-map op-layout-map" role="img" aria-label="Proposed topology"></svg><p>This previews YAML structure. Imported annotations remain in the saved map until explicitly replaced.</p>');
 const svg=$('op-preview-map');svg.innerHTML=topologyMarkup(drawing);svg.setAttribute('viewBox',measureTopology(svg).join(' '));return dialog;
}
async function opLayout(id){return editDiagram(id);}
function opQuickActions(lab,discovery,isBusy=false){
 const status=lab?.deployment?.status, known=['Not deployed','Running','Stopped','Partially running'].includes(status);
 const available=!!lab&&!!opPath(lab)&&!!discovery?.connected&&known&&!isBusy;
 return {startAction:status==='Not deployed'?'deploy':'start',canStart:available&&status!=='Running',canDestroy:available&&status!=='Not deployed'};
}
async function opQuickRun(kind){
 const lab=current(),actions=opQuickActions(lab,state.discovery,busy());
 if(!lab||!(kind==='start'?actions.canStart:actions.canDestroy))return;
 await opReview({lab_id:lab.id,action:kind==='start'?actions.startAction:'destroy'});
}
function renderLabOperations(){
 const quick=opQuickActions(current(),state.discovery,busy());
 if($('lab-start')){$('lab-start').disabled=!quick.canStart;$('lab-start').title=quick.startAction==='deploy'?'Deploy this topology and start its devices':'Start stopped devices in this lab';}
 if($('lab-destroy'))$('lab-destroy').disabled=!quick.canDestroy;
 if($('lab-actions'))$('lab-actions').hidden=!current();
 if($('operation-summary')){const running=(state.operations||[]).filter(j=>['queued','running'].includes(j.status));$('operation-summary').textContent=running.length?'Lab command running · view operation history':'';}
 if(busy()){for(const id of ['remove-lab','sync-vm','update-definition','link-deployment'])if($(id))$(id).disabled=true;}
 else{for(const id of ['update-definition','link-deployment'])if($(id))$(id).disabled=false;}
}
if($('import-top')){
 $('import-top').insertAdjacentHTML('beforebegin','<button class="button secondary" id="lab-actions">Lab actions ▾</button>');

 $('map-edit').onclick=()=>opTask(null,()=>opLayout(activeId));
 $('lab-actions').onclick=()=>openLabOperations();$('vm-projects').onclick=()=>location.assign('/static/workspace.html#mode=folder');$('lab-start').onclick=()=>opTask(null,()=>opQuickRun('start'));$('lab-destroy').onclick=()=>opTask(null,()=>opQuickRun('destroy'));$('operations-history').onclick=()=>opHistory();$('inspect-all').onclick=()=>opTask(null,()=>opReview({action:'inspect-all'}));
 $('labs').addEventListener('contextmenu',e=>{const lab=e.target.closest('[data-lab]');if(lab){e.preventDefault();openLabOperations(lab.dataset.lab);}});
 $('labs').addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){const lab=e.target.closest('[data-lab]');if(lab){e.preventDefault();openLabOperations(lab.dataset.lab);}}});
}
