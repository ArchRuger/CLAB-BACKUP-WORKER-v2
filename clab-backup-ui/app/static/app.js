'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state={labs:[],jobs:[],platforms:{}}, activeId=sessionStorage.getItem('activeLab')||'', tab='topology', toastTimer;
const current=()=>state.labs.find(l=>l.id===activeId);
const busy=()=>state.jobs.some(j=>['queued','running'].includes(j.status))||(state.operations||[]).some(j=>['queued','running'].includes(j.status))||(state.git_jobs||[]).some(j=>['queued','capturing','exporting','pushing'].includes(j.status));
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(path,options={}){
 const headers={...(options.headers||{})};
 const response=await fetch('/api'+path,{...options,headers});
 if(!response.ok){let data;try{data=await response.json();}catch{data={detail:'Request failed'};}
 throw new Error(typeof data.detail==='string'?data.detail:'Check the form fields and try again.');}
 return response;
}
async function json(path,method,data){return (await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).json();}
async function refresh(){const response=await api('/state');state=await response.json();if(!current())activeId=state.labs[0]?.id||'';render();if(tab==='logs')await refreshLogs();}
function selectLab(id){if($('details-dialog').open)$('details-dialog').close();activeId=id;tab='topology';sessionStorage.setItem('activeLab',id);$('search').value='';$('log-job').value='';render();}
function platformLabel(kind){return state.platforms[kind]?.label||(kind==='ssh'?'Generic SSH / Linux':'Unmapped');}
function badge(status){const type=['Ready','succeeded','reachable'].includes(status)?'good':['failed','unreachable','interrupted'].includes(status)?'bad':['queued','running'].includes(status)?'running':'warn';return `<span class="badge ${type}">${esc(status)}</span>`;}
function profileName(lab,node){const id=node.profile_id||lab.defaults[node.platform||'ssh'];return lab.profiles.find(p=>p.id===id)?.label||(node.inventory_credentials?'From inventory':'Not configured');}
function render(){
 const lab=current();
 $('labs').innerHTML=state.labs.length?[...state.labs].sort((a,b)=>Number(!!b.favorite)-Number(!!a.favorite)).map(l=>`<button class="lab-item ${l.id===activeId?'active':''}" data-lab="${esc(l.id)}">${l.favorite?'★ ':''}${esc(l.name)}<small>${l.nodes.length} nodes · ${esc(l.deployment?.status||'Unlinked')}</small></button>`).join(''):'<p class="side-hint">Your labs will appear here.</p>';
 const version=state.version||'1.16.0';$('app-version').textContent='v'+version;
 if($('supported-release'))$('supported-release').textContent='Supported device types as of release '+version;
 $('worker-state').textContent=(state.git_jobs||[]).some(j=>['queued','capturing','exporting','pushing'].includes(j.status))?'Saving lab progress':busy()?'SSH job in progress':'Worker idle';
 $('empty').hidden=!!lab;$('lab-content').hidden=!lab;
 $('title').textContent=lab?.name||'Your next lab starts here.';$('breadcrumb').textContent=lab?.name||'Overview';
 $('subtitle').textContent=lab?'Your nodes, connections, and configuration history.':'Import your nodes. Connect, experiment, and keep your configurations close.';
 $('import-top').textContent=lab?'↑ Replace inventory':'↑ Import inventory';
 $('updated').textContent=lab?'Inventory updated '+new Date(lab.updated).toLocaleString():'No inventory loaded';
 if(typeof renderManagement==='function')renderManagement();
 if(typeof renderLabOperations==='function')renderLabOperations();
 if(typeof renderGitProgress==='function')renderGitProgress();
 if(!lab)return;
 $('node-count').textContent=lab.nodes.length;
 $('map-ssh-all').disabled=!lab.nodes.some(n=>n.ssh_ready);
 $('map-backup-all').disabled=busy()||!lab.nodes.some(n=>n.readiness==='Ready');
 const enabled=lab.nodes.filter(n=>n.enabled), ready=enabled.filter(n=>n.readiness==='Ready');
 $('enabled-count').textContent=enabled.length;$('ready-count').textContent=ready.length;
 $('schedule-summary').textContent=lab.interval?(lab.deployment&& !['Running','Unlinked'].includes(lab.deployment.status)?'Paused · ':'')+lab.interval+' min':'Manual';
 $('test').disabled=$('backup').disabled=busy()||!enabled.length||ready.length!==enabled.length;
 $('test').title=$('backup').title=ready.length!==enabled.length?'Complete credentials for enabled nodes':'';
 $('inventory-caption').textContent=lab.source+' · '+enabled.length+' selected';
 renderNodes();renderProfiles();renderJobs();showTab(tab);refreshHealth();
 if(document.activeElement!==$('interval'))$('interval').value=lab.interval;
}
function renderNodes(){const lab=current();if(!lab)return;const term=$('search').value.toLowerCase();const nodes=lab.nodes.filter(n=>(n.name+' '+n.address+' '+platformLabel(n.platform)).toLowerCase().includes(term));
 const markup=nodes.map(n=>{const h=nodeHealth(n.name);return `<tr><td><input type="checkbox" data-enable="${esc(n.name)}" ${n.enabled?'checked':''} ${!n.platform?'disabled':''} aria-label="Include ${esc(n.name)}"></td><td><button class="node-name" data-details="${esc(n.name)}">${esc(n.short_name||n.name)}</button><span class="endpoint">${esc(n.address)}:${n.port}</span></td><td><span class="badge platform">${esc(platformLabel(n.platform))}</span><span class="secondary-text">${esc(profileName(lab,n))}</span></td><td>${h?.ssh?badge(h.ssh.status):'<span class="status-neutral">Not checked</span>'}<span class="timestamp">${h?.ssh?.at?esc(utcDisplay(h.ssh.at)):'Run a login check'}</span></td><td>${h?.backup?badge(h.backup.status):'<span class="status-neutral">No backup yet</span>'}<span class="timestamp">${h?.backup?.at?esc(utcDisplay(h.backup.at)):''}</span></td><td><div class="node-actions">${nodeActions(n)}</div></td></tr>`;}).join('')||'<tr><td colspan="6" class="table-empty">No matching nodes. Try another name, address, or platform.</td></tr>';if($('nodes')._markup!==markup){$('nodes').innerHTML=markup;$('nodes')._markup=markup;}
}
function nodeActions(n,details=false){return `<button class="ssh-action" data-terminal="${esc(n.name)}" ${!n.ssh_ready?'disabled title="Assign credentials first"':''}>SSH <span aria-hidden="true">↗</span></button><button data-backup="${esc(n.name)}" ${busy()||n.readiness!=='Ready'?'disabled title="Requires a supported NOS, credentials, and an idle worker"':''}>Back up</button>${details?`<button data-check="${esc(n.name)}" ${!n.ssh_ready?'disabled':''}>Test login</button><button data-edit="${esc(n.name)}">Edit connection</button>`:`<button class="details-action" data-details="${esc(n.name)}" aria-label="Details for ${esc(n.name)}">Details <span aria-hidden="true">→</span></button>`}`;}

function renderProfiles(){const lab=current();$('profiles').innerHTML=lab.profiles.length?lab.profiles.map(p=>`<article class="profile-card"><span class="badge">${esc(platformLabel(p.platform))}</span><h3>${esc(p.label)}</h3><p>${esc(p.username)}</p><span class="profile-type">${p.auth==='key'?'SSH private key':'Password authentication'}</span>${lab.defaults[p.platform]===p.id?'<small>Default for this NOS</small>':''}</article>`).join(''):'<div class="blank-state"><h2>Add your NOS credentials</h2><p>Create a profile for each platform that needs one.<br>Credentials included in the uploaded inventory work automatically.</p></div>';}
function renderJobs(){
 const lab=current();const opened=new Set([...document.querySelectorAll('.job[open]')].map(e=>e.dataset.job));
 const jobs=state.jobs.filter(j=>j.lab_id===lab.id);
 $('jobs').innerHTML=jobs.length?jobs.map(j=>{
 const finished=!['queued','running'].includes(j.status);
 const available=j.operation==='backup'&&finished&&j.nodes.some(n=>n.status==='succeeded'&&n.download_name);
 return `<details class="job" data-job="${esc(j.id)}" ${opened.has(j.id)?'open':''}>
 <summary><div class="job-title"><strong>${j.operation==='test'?'NOS login test':'Configuration backup'}</strong><small>${esc(utcDisplay(j.started||j.created))} · ${j.nodes.length} nodes</small></div>${badge(j.status)}</summary>
 <div class="job-body"><p>${esc(j.message)}</p><button class="button secondary" data-logs="${esc(j.id)}">View action logs</button>
 ${j.nodes.map((n,index)=>`<div class="job-result"><strong>${esc(n.short_name||n.name)}</strong>${badge(n.status)}
 ${n.message?`<p>${esc(n.message)}</p>`:''}
 ${n.captured_at?`<small>Captured ${esc(utcDisplay(n.captured_at))}${n.capture_time_source==='legacy job time'?' (historical job timestamp)':''}</small>`:''}
 ${j.operation==='backup'&&finished&&n.status==='succeeded'&&n.download_name?`<div class="device-download"><code>${esc(n.download_name)}</code><button class="button secondary" data-download="${esc(j.id)}" data-node-index="${index}" data-filename="${esc(n.download_name)}">↓ Download config</button></div>`:''}</div>`).join('')}
 ${available?`<div class="archive-download"><button class="button secondary" data-download="${esc(j.id)}" data-filename="${esc(j.archive_name)}">↓ Download all (ZIP)</button><small>${esc(j.archive_name)} · UTC</small></div>`:''}
 </div></details>`;
 }).join(''):'<div class="blank-state"><h2>No jobs yet</h2><p>Test the NOS login, then run a backup. Individual configurations and full archives appear here.</p></div>';
}
function utcDisplay(value){const date=new Date(value);return Number.isNaN(date.getTime())?'Time unavailable':date.toISOString().replace('T',' ').slice(0,19)+' UTC';}
function showTab(value){tab=value;if($('extra-views-label')){$('extra-views-label').textContent=tab==='credentials'?'Credentials':tab==='logs'?'Action logs':tab==='git'?'Git repository':'More';$('extra-views-label').classList.toggle('active',['credentials','logs','git'].includes(tab));}document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===tab);b.setAttribute('aria-selected',b.dataset.tab===tab);});for(const name of ['inventory','topology','credentials','backups','logs','git'])if($(name+'-view'))$(name+'-view').hidden=name!==tab;if(tab==='topology'&&typeof refreshMap==='function')refreshMap();if(tab==='git'&&typeof gitShowRepository==='function')gitShowRepository();}
function openImport(replace=false){$('import-form').reset();$('import-form').querySelector('.form-error').textContent='';const lab=replace?current():null;$('import-lab-id').value=lab?.id||'';$('lab-name').value=lab?.name||'';$('import-title').textContent=lab?'Replace lab inventory':'Import a lab';$('import-dialog').showModal();}
function platformOptions(includeUnknown=false){return (includeUnknown?'<option value="">Choose network OS</option>':'')+Object.entries(state.platforms).map(([id,p])=>`<option value="${esc(id)}">${esc(p.label)}</option>`).join('');}
function openProfile(){if(!current())return;$('profile-form').reset();$('profile-form').querySelector('.form-error').textContent='';$('profile-platform').innerHTML=platformOptions()+'<option value="ssh">Generic SSH / Linux (terminal only)</option>';toggleAuth();$('profile-dialog').showModal();}
function toggleEnable(){$('enable-fields').hidden=$('profile-platform').value!=='arista_ceos';}
function toggleAuth(){toggleEnable();const isKey=$('auth-type').value==='key';$('password-fields').hidden=isKey;$('key-fields').hidden=!isKey;$('private-key').required=isKey;}
function openNode(name){const lab=current(),n=lab.nodes.find(n=>n.name===name);if(!n)return;$('node-form').querySelector('.form-error').textContent='';$('node-title').textContent=n.name;$('node-name').value=n.name;$('node-short-name').value=n.short_name||'';$('node-address').value=n.address;$('node-port').value=n.port;$('node-endpoint-mode').value=n.endpoint_mode||'manual';$('node-endpoint-mode').disabled=!lab.deployment_name;$('node-platform').innerHTML=platformOptions(true);$('node-platform').value=n.platform;$('node-enabled').checked=n.enabled;$('node-profile').innerHTML='<option value="">NOS default / inventory credentials</option>'+lab.profiles.map(p=>`<option value="${esc(p.id)}">${esc(p.label)} · ${esc(p.username)}</option>`).join('');$('node-profile').value=n.profile_id;$('node-dialog').showModal();}
async function withForm(form,fn){const button=form.querySelector('button[type=submit]');button.disabled=true;const error=form.querySelector('.form-error');if(error)error.textContent='';try{await fn();}catch(e){if(error)error.textContent=e.message;else notify(e.message);}finally{button.disabled=false;}}
$('new-lab').onclick=$('import-empty').onclick=()=>openImport();$('import-top').onclick=()=>openImport(!!current());
document.querySelectorAll('.close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{showTab(b.dataset.tab);if($('extra-views'))$('extra-views').open=false;if(tab==='logs')refreshLogs().catch(e=>notify(e.message));});
$('labs').addEventListener('click',e=>{const b=e.target.closest('[data-lab]');if(b)selectLab(b.dataset.lab);});
$('search').oninput=renderNodes;
async function handleNodeAction(e){const b=e.target.closest('button');if(!b||b.disabled)return;
 if(b.dataset.edit){$('details-dialog').close();openNode(b.dataset.edit);}
 if(b.dataset.details)openDetails(b.dataset.details);
 if(b.dataset.terminal){const url='/static/terminal.html#'+new URLSearchParams({lab:activeId,node:b.dataset.terminal,label:current().name});window.open(url,'_blank');}
 if(b.dataset.backup){$('details-dialog').close();startJob('backup',[b.dataset.backup]);}
 if(b.dataset.check){const labId=activeId;b.disabled=true;try{const result=await json('/labs/'+labId+'/ssh-check','POST',{name:b.dataset.check});notify(result.message);if(activeId===labId)await refreshHealth();}catch(error){notify(error.message);}finally{b.disabled=false;}}
}
$('nodes').addEventListener('click',handleNodeAction);
$('details-actions').addEventListener('click',handleNodeAction);
$('nodes').addEventListener('change',async e=>{const name=e.target.dataset.enable;if(!name)return;const n=current().nodes.find(n=>n.name===name);try{await json('/labs/'+activeId+'/node','PUT',{name:n.name,address:n.address,port:n.port,platform:n.platform,profile_id:n.profile_id,enabled:e.target.checked});await refresh();}catch(error){e.target.checked=n.enabled;notify(error.message);renderNodes();}});
$('import-form').addEventListener('submit',e=>{e.preventDefault();withForm(e.currentTarget,async()=>{const data=new FormData(e.currentTarget);const result=await(await api('/inventory',{method:'POST',body:data})).json();activeId=result.id;sessionStorage.setItem('activeLab',activeId);$('import-dialog').close();$('import-form').reset();tab='inventory';await refresh();notify('Inventory imported. Review the nodes and credentials.');});});
$('add-profile').onclick=openProfile;$('auth-type').onchange=toggleAuth;$('profile-platform').onchange=toggleEnable;
$('profile-form').addEventListener('submit',e=>{e.preventDefault();withForm(e.currentTarget,async()=>{const data=new FormData(e.currentTarget);data.set('make_default',$('make-default').checked?'true':'false');await api('/labs/'+activeId+'/profiles',{method:'POST',body:data});$('profile-dialog').close();$('profile-form').reset();await refresh();notify('NOS credentials saved.');});});
$('node-form').addEventListener('submit',e=>{e.preventDefault();withForm(e.currentTarget,async()=>{await json('/labs/'+activeId+'/node','PUT',{name:$('node-name').value,short_name:$('node-short-name').value,address:$('node-address').value,port:Number($('node-port').value),endpoint_mode:$('node-endpoint-mode').value,platform:$('node-platform').value,profile_id:$('node-profile').value,enabled:$('node-enabled').checked});$('node-dialog').close();await refresh();notify('Connection updated.');});});
$('schedule-form').addEventListener('submit',e=>{e.preventDefault();withForm(e.currentTarget,async()=>{await json('/labs/'+activeId+'/schedule','PUT',{interval:Number($('interval').value)});await refresh();notify('Backup schedule saved.');});});
async function startJob(operation,node_names){try{await json('/labs/'+activeId+'/jobs','POST',{operation,...(node_names?{node_names}:{})});tab='backups';await refresh();notify(operation==='test'?'Testing NOS login with show version.':'Backup started.');}catch(e){notify(e.message);}}
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
 if(logButton){$('log-job').value=logButton.dataset.logs;$('log-level').value='';$('log-node').value='';showTab('logs');await refreshLogs();return;}
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
function openDetails(name){detailName=name;renderDetails();$('details-dialog').showModal();}
function renderDetails(){
 const n=current()?.nodes.find(n=>n.name===detailName);if(!n){$('details-dialog').close();return;}
 const h=nodeHealth(n.name);$('details-title').textContent=n.short_name||n.name;
 $('details-endpoint').textContent=n.address+':'+n.port;
 const actions=nodeActions(n,true);if($('details-actions')._markup!==actions){$('details-actions').innerHTML=actions;$('details-actions')._markup=actions;}
 $('details-info').innerHTML=`<section class="drawer-section"><h3>Connection settings</h3><dl class="health-grid"><dt>Inventory name</dt><dd class="mono">${esc(n.name)}</dd><dt>Network OS</dt><dd>${esc(platformLabel(n.platform))}</dd><dt>Credential profile</dt><dd>${esc(profileName(current(),n))}</dd><dt>Backup selection</dt><dd>${n.enabled?'Included in lab backups':'Excluded from lab backups'}</dd><dt>Backup readiness</dt><dd>${esc(n.readiness||'Choose NOS')}</dd></dl></section><section class="drawer-section"><h3>Last SSH check</h3><div class="connection-result">${h?.ssh?badge(h.ssh.status):'<span class="status-neutral">Not checked</span>'}<p>${esc(h?.ssh?.message||'Run Test login to verify SSH access with the saved credentials.')}</p>${h?.ssh?.at?`<time>${esc(utcDisplay(h.ssh.at))}</time>`:''}</div><p class="form-help">A login check verifies authentication at that time. It does not continuously monitor the node.</p></section>`;
 const backups=state.jobs.filter(j=>j.lab_id===activeId&&j.operation==='backup'&&!['queued','running'].includes(j.status));
 const entries=backups.flatMap(j=>j.nodes.map((node,index)=>({j,node,index}))).filter(x=>x.node.name===n.name&&x.node.status==='succeeded'&&x.node.download_name);
 $('node-history').innerHTML=entries.length?entries.map(({j,node,index},i)=>`<div class="device-download"><div><strong>${i===0?'Latest successful backup':'Backup'}</strong><small>${esc(utcDisplay(node.captured_at||j.finished||j.created))}</small><code>${esc(node.download_name)}</code></div><button class="button secondary" data-download="${esc(j.id)}" data-node-index="${index}" data-filename="${esc(node.download_name)}">Download config</button></div>`).join(''):'<p>No saved configurations for this node.</p>';
}
$('node-history').addEventListener('click',handleDownload);
let logEvents=[], logRequest=0;

async function refreshLogs(){
 const request=++logRequest;
 const params=new URLSearchParams({lab_id:$('log-scope').value==='lab'?activeId:'',job_id:$('log-job').value.trim(),level:$('log-level').value,node:$('log-node').value.trim(),limit:'1000'});
 try{const data=await(await api('/logs?'+params)).json();if(request!==logRequest)return;logEvents=data.events;
 $('log-rows').innerHTML=logEvents.map(e=>`<tr><td>${esc(e.time)}<br>${esc(e.level)}</td><td>${esc(e.node||'Worker')}<br><small>${esc(e.job_id)}</small></td><td>${esc(e.action)}</td><td class="log-message">${esc(e.message)}</td></tr>`).join('');
 $('log-status').textContent=`${logEvents.length} events shown (latest 1,000 matching events). Updated ${new Date().toLocaleTimeString()}.`;
 }catch(e){$('log-status').textContent='Could not refresh logs: '+e.message;}
}
for(const id of ['log-scope','log-level','log-node','log-job'])$(id).addEventListener('change',refreshLogs);
$('refresh-logs').onclick=refreshLogs;
$('download-logs').onclick=()=>{const blob=new Blob([logEvents.map(e=>JSON.stringify(e)).join('\n')+'\n'],{type:'application/x-ndjson'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='backup-action-logs.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
refresh().catch(e=>notify(e.message));
setInterval(()=>{refresh().catch(()=>{});},4000);
