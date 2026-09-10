'use strict';
// Shared by the main workspace and independent VM-folder / SSH-launcher tabs.
const opLabels={deploy:'Deploy',redeploy:'Redeploy',destroy:'Destroy deployment',apply:'Apply topology',start:'Start lab nodes',stop:'Stop lab nodes',restart:'Restart lab nodes',save:'Save configurations (clab)',inspect:'Inspect lab','inspect-all':'Inspect all labs',write:'Save VM YAML',create:'Create VM topology',delete:'Delete undeployed VM YAML',clone:'Clone repository',fcli:'Run fcli'};
let opCaps=null, opMenuLab='', opOutputTimer=null, opEditorContext=null;
function opDialog(id,title,body){
 let dialog=$(id);if(!dialog){dialog=document.createElement('dialog');dialog.id=id;dialog.className='operations-dialog';document.body.append(dialog);}
 dialog.innerHTML=`<div class="dialog-head"><span class="eyebrow">LAB OPERATIONS</span><button class="icon-button" data-op-close aria-label="Close">×</button></div><h2>${esc(title)}</h2>${body}<p class="form-error" role="alert"></p>`;
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
 opDialog(dialog.id,lab.name,`<p class="op-path">${esc(opPath(lab)||'Select a VM project before using host commands.')}</p>${problem?`<p class="op-notice">${esc(problem)}</p>`:''}
 <div class="op-sections"><section><h3>Deployment & configuration</h3><div class="op-grid">${['deploy','redeploy','apply','start','stop','restart','inspect','save','destroy'].map(a=>opCommand(a)).join('')}${cleanup}</div><p class="form-help">Destroy removes containers. Cleanup also removes generated lab artifacts. Containerlab save supports selected device kinds; manager backups remain in Backup history.</p></section>
 <section><h3>Workspace & access</h3><div class="op-grid"><button class="button secondary" data-local="ssh">SSH all nodes ↗</button><button class="button secondary" data-local="yaml">Edit VM YAML</button><button class="button secondary" data-local="link">Select / link VM project</button><button class="button secondary" data-local="path">Copy VM topology path</button><button class="button secondary" data-local="folder">Open VM folder ↗</button><button class="button secondary" data-local="favorite">${lab.favorite?'Remove favorite':'Favorite lab'}</button><button class="button secondary" data-local="layout">Edit topology layout</button><button class="button secondary" data-local="horizontal">Export draw.io · horizontal</button><button class="button secondary" data-local="vertical">Export draw.io · vertical</button><button class="button secondary" data-local="interactive">Interactive draw.io layout</button><button class="button secondary" data-local="history">Operation history</button>${opCommand('delete')}</div></section>
 <section><h3>Lab sharing</h3><div class="op-grid">${['sshx','gotty'].map(tool=>['attach','detach','reattach'].map(verb=>opCommand(tool+'-'+verb,tool.toUpperCase()+' · '+verb)).join('')).join('')}<button class="button secondary" data-local="sharing">Open / copy sharing links</button></div><p class="form-help">Requires --allow-sharing during VM setup and compatible Containerlab tools. GoTTY uses a separate VM port; SSHX requires its external relay.</p></section>
 <section><h3>SR Linux fcli</h3><div class="op-grid"><button class="button secondary" data-local="fcli" ${!lab.nodes.some(n=>n.kind==='nokia_srlinux')||!opCaps?.actions.fcli?.available?'disabled':''}>Select query…</button></div><p class="form-help">Requires SR Linux nodes and the nornir-srl image loaded on the VM. No image pull occurs automatically.</p></section></div>`);
 dialog.querySelectorAll('[data-op-action]').forEach(b=>b.onclick=()=>{
  const action=b.dataset.opAction,options=JSON.parse(b.dataset.opOptions);
  if(action.startsWith('gotty-')&&!action.endsWith('detach'))return opGotty(id,action);
  opTask(dialog,()=>opReview({lab_id:id,action,options}));
 });
 dialog.querySelectorAll('[data-local]').forEach(b=>b.onclick=()=>opTask(dialog,async()=>{
  const action=b.dataset.local;
  if(action==='ssh')opNewTab({mode:'ssh',lab:id});
  if(action==='yaml'){if(!opPath(lab))throw new Error('Select / link a VM project first.');await opEdit(opPath(lab),id);}
  if(action==='link')await opBrowse('',id);
  if(action==='path'){if(!opPath(lab))throw new Error('No VM project is linked.');await opCopy(opPath(lab));}
  if(action==='folder'){if(!opPath(lab))throw new Error('No VM project is linked.');opNewTab({mode:'folder',path:opPath(lab).replace(/\/[^/]+$/,''),lab:id});}
  if(action==='favorite'){await json('/labs/'+id+'/operations-settings','PUT',{favorite:!lab.favorite});await refresh();dialog.close();}
  if(action==='layout'||action==='interactive')await opLayout(id,action==='interactive');
  if(['horizontal','vertical'].includes(action))await opDownload(id,action);
  if(action==='history'||action==='sharing')await opHistory(id);
  if(action==='fcli')opFcli(id);
 }));
}
async function opReview(request){
 const value=await json('/operations/preview','POST',request);
 const label=opLabels[value.action]||value.action;
 const dialog=opDialog('operation-review','Review: '+label,`<p><strong>${esc(value.name)}</strong></p><p class="op-path">${esc(value.path||'All deployed labs on the configured VM')}</p>
 ${value.warnings.map(w=>`<p class="op-notice">${esc(w)}</p>`).join('')}
 ${['stop','restart','redeploy','destroy','apply'].includes(value.action)?'<p class="op-notice">This can interrupt lab connectivity and open SSH sessions.</p>':''}
 ${value.action==='delete'?'<p class="op-notice">Deletes the original YAML on the VM after preserving a recovery copy. The saved manager workspace remains.</p>':''}
 <p>${value.affected.length} deployed containers in this lab</p>${value.affected.length?`<details><summary>Affected containers</summary><ul>${value.affected.map(n=>`<li>${esc(n.name)} · ${esc(n.state)}</li>`).join('')}</ul></details>`:''}
 <pre class="op-output">${esc((value.steps?.length?value.steps:[value.argv]).filter(a=>a.length).map(a=>a.map(v=>JSON.stringify(v)).join(' ')).join('\n')||label)}</pre>
 ${value.diff?`<details open><summary>YAML changes</summary><pre class="op-output">${esc(value.diff)}</pre></details>`:''}
 <p class="form-help">This review expires in five minutes. Changes to the topology or deployment require a new review.</p>
 <div class="dialog-actions"><button class="button secondary" id="op-cancel">Cancel</button><button class="button primary" id="op-confirm">Confirm ${esc(label.toLowerCase())}</button></div>`);
 $('op-cancel').onclick=()=>dialog.close();$('op-confirm').onclick=()=>opTask(dialog,async()=>{
  const job=await json('/operations/confirm','POST',{token:value.token});dialog.close();
  if($('op-editor')?.open)$('op-editor').close();await refresh();await opShowJob(job.id);
 });
}
async function opShowJob(id){
 clearTimeout(opOutputTimer);
 const dialog=opDialog('operation-output','Operation output','<p id="op-job-state"></p><pre class="op-output" id="op-job-output" tabindex="0"></pre><div id="op-job-result"></div>');
 const poll=async()=>{
  if(!dialog.open)return;
  try{
   const job=await(await api('/operations/'+id)).json();
   $('op-job-state').textContent=[job.name,opLabels[job.action]||job.action,job.status,job.exit_code===null?'':'Exit '+job.exit_code,job.message].filter(Boolean).join(' · ');
   const pre=$('op-job-output'),follow=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-30;pre.textContent=job.output||'Waiting for command output…';if(follow)pre.scrollTop=pre.scrollHeight;
   const links=[...new Set([...(job.result?.sharing_links||[]),...((job.output||'').match(/https?:\/\/[^\s<>"'\x1b]+/g)||[])].map(link=>link.replaceAll('HOST_IP',location.hostname)))].filter(value=>{try{return !new URL(value).username;}catch{return false;}}).slice(0,20);
   $('op-job-result').innerHTML=(job.result?.recovery_path?`<p>Recovery copy: <code>${esc(job.result.recovery_path)}</code></p>`:'')+(job.result?.project_path?`<button class="button secondary" id="op-open-clone">Browse cloned project</button>`:'')+links.map((link,i)=>`<p><a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(link)}</a> <button class="button secondary" data-copy-link="${i}">Copy link</button></p>`).join('');
   $('op-open-clone')?.addEventListener('click',()=>opBrowse(job.result.project_path));
   dialog.querySelectorAll('[data-copy-link]').forEach(b=>b.onclick=()=>opCopy(links[Number(b.dataset.copyLink)]));
   if(['queued','running'].includes(job.status))opOutputTimer=setTimeout(poll,1000);else await refresh();
  }catch(e){dialog.querySelector('.form-error').textContent=e.message;}
 };dialog.onclose=()=>clearTimeout(opOutputTimer);await poll();
}
async function opHistory(labId=''){
 const jobs=await(await api('/operations')).json();
 const dialog=opDialog('operation-history','Operation history',`<p>Saved command output remains in persistent manager storage. Sharing links appear in the corresponding attach / reattach output.</p><div class="op-history">${jobs.filter(j=>!labId||j.lab_id===labId).map(j=>`<button class="button secondary" data-job="${esc(j.id)}"><strong>${esc(j.name)} · ${esc(opLabels[j.action]||j.action)}</strong><small>${esc(j.status)} · ${esc(new Date(j.created).toLocaleString())}</small></button>`).join('')||'<p>No lab operations yet.</p>'}</div>`);
 dialog.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>opShowJob(b.dataset.job));
}
function opGotty(lab_id,action){
 const dialog=opDialog('op-options','GoTTY terminal sharing','<label>VM listening port<input id="gotty-port" type="number" min="1024" max="65535" value="8082"></label><p>Allow this port through the VM firewall only where you intend to share terminal access.</p><button class="button primary" id="gotty-review">Review operation</button>');
 $('gotty-review').onclick=()=>opTask(dialog,()=>opReview({lab_id,action,options:{port:Number($('gotty-port').value)}}));
}
function opFcli(lab_id){
 const queries=['bgp-peers','bgp-rib','ipv4-rib','lldp','mac','ni','subif','sys-info'];
 const dialog=opDialog('op-options','SR Linux fcli','<label>Query<select id="fcli-preset">'+queries.map(q=>`<option>${q}</option>`).join('')+'<option value="custom">Custom query</option></select></label><label>Query and options<input id="fcli-query" value="bgp-peers" maxlength="1000"></label><p class="form-help">Supply an fcli subcommand and its options. Docker arguments and shell commands are not accepted.</p><button class="button primary" id="fcli-review">Review query</button>');
 $('fcli-preset').onchange=()=>{if($('fcli-preset').value!=='custom')$('fcli-query').value=$('fcli-preset').value;};
 $('fcli-review').onclick=()=>opTask(dialog,()=>opReview({lab_id,action:'fcli',options:{query:$('fcli-query').value}}));
}
async function opCopy(text){
 try{await navigator.clipboard.writeText(text);notify('Copied.');}
 catch{const dialog=opDialog('op-copy','Copy text','<label>Select and copy<input id="op-copy-value" readonly></label>');$('op-copy-value').value=text;$('op-copy-value').select();}
}
function opNewTab(values){const url='/static/workspace.html#'+new URLSearchParams(values);if(!window.open(url,'_blank'))opDialog('op-open-tab','Open workspace',`<p>Your browser may have blocked the new tab.</p><a class="button primary" href="${esc(url)}" target="_blank" rel="opener">Open workspace ↗</a>`);}
async function opBrowse(path='',linkLab=''){
 const result=await json('/operations/browse','POST',{path});
 const caps=await opCapabilities();
 const dialog=opDialog('op-browser',linkLab?'Select a VM project':'VM projects',`<p class="op-path">${esc(result.path||'Trusted project roots')}</p><div class="actions"><button class="button secondary" id="op-roots">Project roots</button><button class="button secondary" id="op-up">Parent folder</button><button class="button secondary" id="op-create">New topology</button><button class="button secondary" id="op-clone">Clone repository</button><button class="button secondary" id="op-popular">Popular labs</button></div><div class="op-file-list">${result.entries.map((entry,i)=>`<button class="button secondary" data-entry="${i}">${entry.directory?'▸':'◇'} ${esc(entry.name)}</button>`).join('')||'<p>No files in this folder.</p>'}</div><p class="form-help">Browse existing VM files, or clone a complete project. Review YAML, startup configs, binds and hooks before deployment. At most 500 entries are shown.</p>`);
 $('op-roots').onclick=()=>opTask(dialog,()=>opBrowse('',linkLab));$('op-up').onclick=()=>opTask(dialog,()=>opBrowse(result.parent||'',linkLab));
 $('op-create').onclick=()=>opEdit('',linkLab,(result.path||'/srv/containerlab-node-manager/projects')+'/new-lab.clab.yaml');$('op-clone').onclick=()=>opClone();$('op-popular').onclick=()=>opTask(dialog,()=>opPopular());
 if(!caps.network||caps.actions.clone?.available===false){$('op-clone').disabled=true;$('op-clone').title='Requires git and --allow-downloads in VM setup.';}
 if(!caps.network){$('op-popular').disabled=true;$('op-popular').title='Requires --allow-downloads in VM setup.';dialog.querySelector('.form-help').textContent+=' Online downloads are disabled; enable --allow-downloads on the VM to use the catalog or cloning.';}
 dialog.querySelectorAll('[data-entry]').forEach(b=>b.onclick=()=>opTask(dialog,async()=>{
  const entry=result.entries[Number(b.dataset.entry)];if(entry.directory)return opBrowse(entry.path,linkLab);
  await opEdit(entry.path,linkLab);
 }));
}
async function opEdit(path,labId='',newPath=''){
 if(!path)labId='';
 const value=path?await json('/operations/read','POST',{path}):{text:'name: new-lab\ntopology:\n  nodes:\n    r1:\n      kind: linux\n      image: alpine:latest\n',path:newPath};
 const isYaml=/\.ya?ml$/i.test(value.path);
 opEditorContext={path:value.path,labId,isNew:!path};
 const dialog=opDialog('op-editor',path?'VM project file':'Create topology',`<label>Absolute VM path<input id="op-edit-path" ${path?'readonly':''}></label><label>${isYaml?'Topology YAML':'File contents'}<textarea class="op-code" id="op-edit-text" spellcheck="false" ${!isYaml?'readonly':''}></textarea></label><p class="form-help">Saving edits the VM source. Apply or redeploy is a separate operation. Recovery copies are preserved on the VM. New YAML can reference only files already present in this project.</p><div class="actions">${isYaml?'<button class="button secondary" id="op-validate">Validate / preview topology</button><button class="button primary" id="op-save-yaml">Review save to VM</button>':''}${path&&isYaml?'<button class="button secondary" id="op-add-project">'+(labId?'Link this project':'Add project to manager')+'</button><button class="button secondary" id="op-deploy-project">Review deployment</button>':''}<button class="button secondary" id="op-copy-path">Copy path</button></div>`);
 $('op-edit-path').value=value.path;$('op-edit-text').value=value.text;
 $('op-copy-path').onclick=()=>opCopy($('op-edit-path').value);
 $('op-validate')?.addEventListener('click',()=>opTask(dialog,async()=>{const parsed=await json('/operations/parse-yaml','POST',{options:{text:$('op-edit-text').value}});opMapPreview(parsed.drawing,parsed.name);}));
 $('op-save-yaml')?.addEventListener('click',()=>opTask(dialog,()=>opReview({action:path?'write':'create',lab_id:labId,path:$('op-edit-path').value,options:{text:$('op-edit-text').value}})));
 $('op-add-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  // Always read the actual VM file; unsaved editor contents are not linked/imported.
  const source=await json('/operations/read','POST',{path}),parsed=await json('/operations/parse-yaml','POST',{options:{text:source.text}});
  const confirm=opDialog('op-add-confirm',labId?'Link VM project?':'Add project to manager?',`<p>${esc(parsed.name)} · ${parsed.drawing.nodes.length} nodes</p><p class="op-path">${esc(path)}</p><p>This saves a manager workspace and links its original VM source. It does not deploy containers. Device credentials can be imported from discovered VM files after deployment.</p><button class="button primary" id="op-add-confirm-button">${labId?'Link project':'Add project'}</button>`);
  $('op-add-confirm-button').onclick=()=>opTask(confirm,async()=>{
   let id=labId;
   if(!id){const form=new FormData();form.append('definition',new Blob([source.text],{type:'text/yaml'}),path.split('/').pop());const lab=await(await api('/lab-definitions',{method:'POST',body:form})).json();id=lab.id;}
   await json('/labs/'+id+'/operations-settings','PUT',{path});activeId=id;sessionStorage.setItem('activeLab',id);confirm.close();dialog.close();await refresh();notify('VM project linked.');
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
 const dialog=opDialog('op-popular-dialog','Popular Containerlab projects','<p>SRL Labs repositories tagged clab-topo, ordered by GitHub stars. Cloning and deployment are separate reviewed steps.</p><div class="op-history">'+data.items.map((item,i)=>`<button class="button secondary" data-repo="${i}"><strong>${esc(item.name)}</strong><small>${esc(item.description)}</small></button>`).join('')+'</div>');
 dialog.querySelectorAll('[data-repo]').forEach(b=>b.onclick=()=>{const item=data.items[Number(b.dataset.repo)];opClone(item.url,item.name);});
}
function opMapPreview(drawing,name){
 const dialog=opDialog('op-map-preview','Topology preview · '+name,'<svg id="op-preview-map" class="topology-map op-layout-map" role="img" aria-label="Proposed topology"></svg><p>This previews YAML structure. Imported annotations remain in the saved map until explicitly replaced.</p>');
 const svg=$('op-preview-map');svg.innerHTML=topologyMarkup(drawing);svg.setAttribute('viewBox',measureTopology(svg).join(' '));return dialog;
}
async function opDownload(id,layout){
 const response=await api('/labs/'+id+'/drawio?layout='+layout),url=URL.createObjectURL(await response.blob()),a=document.createElement('a');
 a.href=url;a.download=attachmentName(response,'topology.drawio');a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function opLayout(id,exportMode=false){
 const drawing=await(await api('/labs/'+id+'/topology')).json();if(!drawing)throw new Error('Import a topology map first.');
 const dialog=opDialog('op-layout-editor',exportMode?'Interactive draw.io layout':'Edit topology layout',`<p>Drag nodes on the map or enter coordinates. Links follow the nodes. Use Edit VM YAML to add or remove nodes and links. Saved layout changes stay in the manager; the original annotations file is retained.</p><svg id="op-layout-map" class="topology-map op-layout-map" aria-label="Editable lab topology"></svg><details><summary>Node coordinates</summary><div class="op-coordinates">${drawing.nodes.map((n,i)=>`<label>${esc(n.alias)}<input type="number" data-x="${i}" aria-label="${esc(n.alias)} X" value="${n.x}"><input type="number" data-y="${i}" aria-label="${esc(n.alias)} Y" value="${n.y}"></label>`).join('')}</div></details><div class="dialog-actions"><button class="button primary" id="op-layout-save">${exportMode?'Save layout & export draw.io':'Save layout'}</button></div>`);
 const svg=$('op-layout-map');let bounds=null,drag=null;
 const render=()=>{svg.innerHTML=topologyMarkup(drawing);svg.querySelectorAll('[data-map-id]').forEach(el=>{el.removeAttribute('aria-haspopup');el.setAttribute('aria-label','Move '+el.dataset.mapId);el.querySelector('title').textContent='Drag to reposition, or use the coordinate fields below.';});const measured=measureTopology(svg);if(!bounds)bounds=measured;svg.setAttribute('viewBox',bounds.join(' '));};render();
 const point=e=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());};
 svg.onpointerdown=e=>{if(e.button!==0)return;const el=e.target.closest('[data-map-id]');if(!el)return;const node=drawing.nodes.find(n=>n.id===el.dataset.mapId);if(!node)return;e.preventDefault();drag={node,p:point(e),x:node.x,y:node.y};svg.setPointerCapture(e.pointerId);};
 svg.onpointermove=e=>{if(!drag)return;const p=point(e);drag.node.x=Math.round(drag.x+p.x-drag.p.x);drag.node.y=Math.round(drag.y+p.y-drag.p.y);render();};
 const release=()=>{if(!drag)return;const i=drawing.nodes.indexOf(drag.node);dialog.querySelector(`[data-x="${i}"]`).value=drag.node.x;dialog.querySelector(`[data-y="${i}"]`).value=drag.node.y;drag=null;};
 svg.onpointerup=release;svg.onpointercancel=release;svg.onlostpointercapture=release;
 dialog.querySelectorAll('[data-x],[data-y]').forEach(input=>input.onchange=()=>{const axis=input.hasAttribute('data-x')?'x':'y',i=Number(input.dataset[axis]),value=Number(input.value);if(Number.isFinite(value)&&Math.abs(value)<=100000){drawing.nodes[i][axis]=value;render();}});
 $('op-layout-save').onclick=()=>opTask(dialog,async()=>{await json('/labs/'+id+'/layout','PUT',{positions:Object.fromEntries(drawing.nodes.map(n=>[n.id,[n.x,n.y]]))});if(exportMode)await opDownload(id,'interactive');dialog.close();if(typeof refreshMap==='function'&&id===activeId)await refreshMap(true);notify('Layout saved.');});
}
function renderLabOperations(){
 if($('lab-actions'))$('lab-actions').hidden=!current();
 if($('operation-summary')){const running=(state.operations||[]).filter(j=>['queued','running'].includes(j.status));$('operation-summary').textContent=running.length?'Lab command running · view operation history':'';}
 if(busy()){for(const id of ['remove-lab','sync-vm','update-definition','link-deployment'])if($(id))$(id).disabled=true;}
 else{for(const id of ['update-definition','link-deployment'])if($(id))$(id).disabled=false;}
}
if($('import-top')){
 $('import-top').insertAdjacentHTML('beforebegin','<button class="button secondary" id="lab-actions">Lab actions ▾</button>');
 $('vm-refresh').insertAdjacentHTML('afterend','<button class="side-button" id="vm-projects">VM projects ↗</button><button class="side-button" id="operations-history">Operation history</button><button class="side-button" id="inspect-all">Inspect all labs</button><p class="side-hint" id="operation-summary" role="status"></p>');
 $('lab-actions').onclick=()=>openLabOperations();$('vm-projects').onclick=()=>opNewTab({mode:'folder'});$('operations-history').onclick=()=>opHistory();$('inspect-all').onclick=()=>opTask(null,()=>opReview({action:'inspect-all'}));
 $('labs').addEventListener('contextmenu',e=>{const lab=e.target.closest('[data-lab]');if(lab){e.preventDefault();openLabOperations(lab.dataset.lab);}});
 $('labs').addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){const lab=e.target.closest('[data-lab]');if(lab){e.preventDefault();openLabOperations(lab.dataset.lab);}}});
}
