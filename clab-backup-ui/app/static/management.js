'use strict';
let vmSyncBusy=false;
// Lists that re-render on the 4 s poll go through app.js's setMarkup so focus survives; the harness has no setMarkup.
function mgmtMarkup(el,html){if(!el)return;if(typeof setMarkup==='function')setMarkup(el,html);else el.innerHTML=html;}
// All host output is rendered as text or escaped; credentials never enter state responses.
document.body.insertAdjacentHTML('beforeend', `
<dialog id="auto-import-dialog"><form id="auto-import-form">
 <div class="dialog-head"><span class="eyebrow">IMPORT FROM VM</span><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <h2>Import this discovered lab?</h2><p id="auto-import-summary"></p>
 <p>The manager will save the lab definition, available layout and inventory credentials in persistent storage. The backup schedule starts as Manual.</p>
 <div id="auto-import-files"></div><p id="auto-import-warnings" class="form-help"></p>
 <p id="auto-import-excluded" hidden>This also removes the lab from your excluded list. Previous workspace settings and backup history are not restored.</p>
 <p class="form-error" role="alert"></p>
 <div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Import lab</button></div>
</form></dialog>
<dialog id="remove-lab-dialog"><form id="remove-lab-form">
 <div class="dialog-head"><span class="eyebrow">REMOVE SAVED WORKSPACE</span><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <h2>Remove lab from this manager?</h2><p id="remove-lab-name"></p>
 <input type="hidden" id="remove-lab-id"><input type="hidden" id="remove-lab-confirm-name">
 <p>This removes the imported nodes, map, saved credentials, schedule and backup history entries. Saved backup files and audit logs remain on disk.</p>
 <p>Your running containers and lab files on the VM are unaffected. The VM connection and other saved labs remain available.</p>
 <label class="checkbox-label"><input id="remove-lab-exclude" type="checkbox" checked> Keep this lab excluded from automatic import</label>
 <p class="form-help">Uncheck to test discovery: the deployed lab can return as Ready to import on the next check, and still requires confirmation. Otherwise, use Import again in the sidebar when ready.</p>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Remove saved lab</button></div>
</form></dialog>
<dialog id="setup-dialog"><form id="setup-form">
 <div class="dialog-head"><span class="eyebrow">PERSISTENT LAB WORKSPACE</span><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <h2 id="setup-title">Import a lab</h2><p>For a detected lab, try automatic import from the VM first. Use the file fields for manual import. The workspace remains saved when the lab is stopped or removed.</p>
 <button type="button" class="button secondary" id="setup-auto-import">Try automatic import from VM</button>
 <input type="hidden" name="lab_id" id="setup-lab-id">
 <label>Lab definition (.clab.yaml)<input name="definition" type="file" accept=".yaml,.yml" required></label>
 <label>Deployed lab name <span class="muted">optional</span><input name="deployed_name" id="setup-deployed-name" maxlength="120" placeholder="Use the name in the YAML"></label>
 <p class="form-help">Use an override if you deploy with a different lab name. Existing saved labs with this deployment name are updated in place.</p>
 <label>Topology annotations <span class="muted">optional</span><input name="annotations" type="file" accept=".json"></label>
 <p class="form-help">Without annotations, a simple map is generated. Importing does not deploy containers. Use VM connection to discover node addresses, then add NOS credentials.</p>
 <button type="button" class="button secondary" id="legacy-import">Import an Ansible inventory instead</button>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Save lab</button></div>
</form></dialog>
<dialog id="vm-dialog"><form id="vm-form">
 <div class="dialog-head"><span class="eyebrow">VM DISCOVERY</span><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <h2>VM connection</h2><p><a href="/vm-connection-guide" target="_blank" rel="noopener">VM setup and troubleshooting guide ↗</a></p><p>This standalone manager inspects deployed labs over SSH every 30 seconds. Device SSH credentials are configured separately.</p>
 <div class="form-grid wide"><label>VM address<input id="vm-address" required placeholder="127.0.0.1"></label><label>SSH port<input id="vm-port" type="number" min="1" max="65535" value="22" required></label></div>
 <label>VM username<input id="vm-user" required maxlength="128" autocomplete="off"></label>
 <label>VM password<input id="vm-password" type="password" autocomplete="current-password" maxlength="4096"></label>
 <p class="form-help">Create the clab-discovery password in the VM terminal during setup, then enter it here. Leave blank to retain a saved password for the same account. It is encrypted in the VM's persistent manager storage.</p>
 <p id="vm-password-migration" class="form-help" hidden>This connection previously used an SSH key. Run sudo bash deploy/setup-discovery.sh on the VM to create its password, then enter that password here.</p>
 <label>Inspection method<select id="vm-command"><option value="helper">Installed discovery and file helper (recommended)</option><option value="direct">Direct inspection + SFTP (existing VM account)</option></select></label>
 <p class="form-help">Install the supplied VM setup script for the helper. The restricted helper reads deployment state and the original YAML, annotations, generated inventory and topology export. New labs appear for import confirmation. Direct mode reads these files through SFTP with the same VM account. The installed helper supports root-owned lab files.</p>
 <label class="checkbox-label"><input id="vm-enabled" type="checkbox" checked> Enable automatic discovery</label>
 <p id="vm-fingerprint" class="form-help"></p><p class="form-help">The first successful connection trusts and saves the VM SSH fingerprint. Later key changes block discovery.</p>
 <label class="checkbox-label"><input id="vm-reset-key" type="checkbox" checked> Trust a replacement SSH host key on the next connection</label>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Save and test connection</button></div>
</form></dialog>
<dialog id="binding-dialog"><form id="binding-form">
 <div class="dialog-head"><span class="eyebrow">DEPLOYMENT MATCHING</span><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <h2>Link deployed lab</h2><p>Associate this saved workspace with a lab on the configured VM. Existing inventory addresses stay manual until changed in Edit connection.</p>
 <label>Deployed lab name<input id="binding-name" maxlength="120" list="deployment-names"></label><datalist id="deployment-names"></datalist>
 <label>Container prefix<input id="binding-prefix" maxlength="120" value="clab"></label><p class="form-help">Usually clab. An empty prefix matches bare node names. Leave the deployed name empty to unlink discovery.</p>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Save link</button></div>
</form></dialog>`);
document.querySelectorAll('[data-dismiss]').forEach(button=>button.onclick=()=>button.closest('dialog').close());

function renderManagement(){
 const discovery=state.discovery||{}, lab=current();
 $('vm-summary').textContent=!discovery.configured?'VM discovery is not configured.':!discovery.host.enabled?'VM discovery is paused.':discovery.helper_update_required?'VM connected · helper update required. On the VM, run sudo bash deploy/start-manager.sh from the current source.':discovery.connected?'VM connected · checks every 30s':(discovery.error||'VM status unknown; refresh discovery.');
 mgmtMarkup($('discovered-labs'),(discovery.discovered||[]).filter(l=>!l.imported&&!l.excluded).map(l=>`<button class="side-button" data-setup-name="${esc(l.name)}">${esc(l.name)}<small>${discovery.connected?'Running on the VM':'Last seen on the VM'} · ${l.running} of ${l.nodes} devices running · ${esc(discovery.file_errors?.[l.name]||(discovery.pending_imports?.[l.name]?'Ready to import — confirm to add it to My labs':'Add to My labs'))}</small></button>`).join(''));
 const reports=discovery.file_reports||{};
 mgmtMarkup($('discovery-file-list'),Object.entries(reports).map(([name,files])=>`<p><strong>${esc(name)}</strong></p>${Object.entries(files).map(([kind,file])=>`<p>${esc(kind)}: ${esc(file.message)}<small>${(file.paths||[]).map(esc).join('<br>')}</small></p>`).join('')}`).join('')||'<p>No file checks yet. Use Manager › Refresh lab list. If it stays empty the VM helper may need an update (Manager › Diagnostics).</p>');
 mgmtMarkup($('excluded-labs'),(discovery.ignored_labs||[]).length?'<p class="side-hint">Removed from this manager earlier</p>'+(discovery.ignored_labs||[]).map(name=>`<div class="empty-lab"><button class="side-button" data-allow-import="${esc(name)}">${esc(name)}<small>Import again · or stop hiding it so it appears automatically</small></button><button type="button" class="button secondary small" data-clear-exclusion="${esc(name)}">Stop hiding</button></div>`).join(''):'');
 maybePromptVmConnection();
 renderLanding(discovery,lab);
 if(!lab)return;
 $('remove-lab').disabled=state.jobs.some(j=>j.lab_id===lab.id&&['queued','running'].includes(j.status));
 const source=lab.vm_source, sync=$('sync-vm');
 sync.hidden=!lab.deployment_name;
 sync.disabled=vmSyncBusy||!discovery.connected||!source?.can_sync;
 $('vm-files-status').textContent=!lab.deployment_name?'':!discovery.connected?'VM file sync is unavailable until discovery reconnects.':!discovery.file_import_supported?'Update the installed VM helper to enable file transfer, or use direct inspection + SFTP. Manual uploads remain available.':source?('VM files: '+source.status+(source.synced_at?' · Last synced '+new Date(source.synced_at).toLocaleString():'')+(source.message?' · '+source.message:'')):(discovery.file_errors?.[lab.deployment_name]||'No deployed source files found. Saved workspace retained.');
 $('deployment-status').textContent=lab.deployment?.status||'Unlinked';
 $('deployment-message').textContent=lab.deployment?.message||'Link this workspace to a deployed lab.';
 $('deployment-checked').textContent=lab.deployment?.last_success?new Date(lab.deployment.last_success).toLocaleString():'';
 renderNosReadiness(lab);
}
// Container state alone never proves a NOS is usable; the readiness monitor's verdict
// sits under the deployment status in plain words.
function renderNosReadiness(lab){
 const nos=lab.nos_readiness||{status:'idle'};
 $('deployment-nos').className='deployment-nos '+nos.status;
 $('deployment-nos').textContent=nos.status==='ready'?`NOS ready · ${nos.ready}/${nos.total} devices accept SSH login`:nos.status==='booting'?`NOS booting · ${nos.ready}/${nos.total} devices accept SSH login so far. SSH and the login test open automatically when they answer.`:nos.status==='failed'?`NOS login failed on ${nos.failed} of ${nos.total} devices · assign credentials, then Test login`:'';
}
// Deploy-first landing page: connect the VM, then deploy or pick up a running lab.
function renderLanding(discovery,lab){
 if(lab||!$('deploy-empty'))return;
 const configured=!!discovery.configured,connected=!!discovery.connected;
 $('vm-connect-empty').hidden=configured;
 $('deploy-empty').disabled=!connected;
 $('deploy-empty').title=connected?'':'Connect the lab VM to browse its topology files.';
 if($('home-deploy')){$('home-deploy').disabled=!connected;$('home-deploy').title=$('deploy-empty').title;}
 if($('home-deploy-reason')){$('home-deploy-reason').textContent=$('deploy-empty').title;$('home-deploy-reason').hidden=connected;}
 // Home keeps a VM prompt even when labs exist: cards read "Status unknown" without one.
 if($('home-vm-banner')){const note=!configured?'Connect this manager to your lab VM first. Starting labs, finding running labs and opening device CLIs all use that connection.':!connected?(discovery.error||'Waiting for the lab VM to answer. Deploy becomes available as soon as it does.'):'';$('home-vm-banner').hidden=!note;if($('home-vm-banner-text'))$('home-vm-banner-text').textContent=note;if($('home-vm-connect'))$('home-vm-connect').textContent=configured?'VM connection…':'Connect the VM';}
 $('empty-vm-note').textContent=!configured?'Connect this manager to your containerlab VM first. Deployment, discovery and node logins all run over that connection.':!connected?(discovery.error||'Waiting for the VM connection. Deployment opens as soon as discovery answers.'):'';
 const running=(discovery.discovered||[]).filter(l=>!l.imported);
 $('empty-discovered').hidden=!running.length;
 mgmtMarkup($('empty-discovered-list'),running.map(l=>`<div class="empty-lab"><div><strong>${esc(l.name)}</strong><small>${l.running}/${l.nodes} containers running${l.excluded?' · removed from this manager earlier':''}</small></div><button type="button" class="button secondary" data-setup-name="${esc(l.name)}">Import</button></div>`).join(''));
}
function openSetup(replace=false, deployedName=''){
 const lab=replace?current():null;$('setup-form').reset();$('setup-form').querySelector('.form-error').textContent='';
 deployedName=deployedName||(state.discovery?.discovered||[]).find(l=>!l.imported&&!l.excluded)?.name||'';
 $('setup-lab-id').value=lab?.id||'';$('setup-deployed-name').value=lab?.deployment_name||deployedName;
 $('setup-auto-import').hidden=replace||!deployedName||!state.discovery?.configured;
 $('setup-title').textContent=lab?'Update lab definition':'Import a lab';$('setup-dialog').showModal();
}
$('new-lab').onclick=$('import-empty').onclick=()=>openSetup();
$('import-inventory-empty').onclick=()=>openImport();
$('vm-connect-empty').onclick=()=>openVmDialog();
if($('home-vm-connect'))$('home-vm-connect').onclick=()=>openVmDialog();
$('empty-discovered-list').onclick=e=>{const b=e.target.closest('[data-setup-name]');if(b)importDiscovered(b.dataset.setupName);};
$('import-top').onclick=()=>current()?openImport(true):openDeploy();
$('update-definition').onclick=()=>openSetup(true);
$('legacy-import').onclick=()=>{$('setup-dialog').close();openImport(!!$('setup-lab-id').value);};
$('discovered-labs').onclick=e=>{const b=e.target.closest('[data-setup-name]');if(b)importDiscovered(b.dataset.setupName);};
$('setup-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{
 const result=await(await api('/lab-definitions',{method:'POST',body:new FormData(e.target)})).json();
 $('setup-dialog').close();$('setup-form').reset();await refresh();if(typeof selectLab==='function')selectLab(result.id);else{activeId=result.id;sessionStorage.setItem('activeLab',activeId);}notify('Lab added. Device addresses fill in automatically while the lab is running.');
});};
function openVmDialog(){
 const h=state.discovery?.host||{};$('vm-form').reset();$('vm-form').querySelector('.form-error').textContent='';
 $('vm-address').value=h.address||'127.0.0.1';$('vm-port').value=h.port||22;$('vm-user').value=h.username||'clab-discovery';$('vm-command').value=h.command_mode||'helper';$('vm-enabled').checked=h.enabled!==false;
 // Lab VMs get rebuilt and re-keyed; trusting the replacement key on the next
 // connection is the default so a rebuilt VM reconnects without a second visit here.
 $('vm-reset-key').checked=true;
 $('vm-fingerprint').textContent=h.fingerprint?'Saved fingerprint: '+h.fingerprint:'No VM fingerprint saved yet.';$('vm-password-migration').hidden=h.auth!=='key';$('vm-password').required=!h.auth||h.auth!=='password';$('vm-dialog').showModal();
}
$('vm-settings').onclick=openVmDialog;
// The VM connection is what makes discovery, operations and Git work, so prompt for
// it once on first load when nothing is configured yet. A configured connection, or a
// connection the viewer dismissed this session, is never reopened automatically.
let vmPromptShown=false;
function maybePromptVmConnection(){
 if(vmPromptShown)return;
 const discovery=state.discovery;
 if(!discovery||discovery.configured)return;
 vmPromptShown=true;
 if(!$('vm-dialog').open&&!(typeof document.querySelector==='function'&&document.querySelector('dialog[open]')))openVmDialog();
}
$('vm-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{
 await json('/host','PUT',{address:$('vm-address').value,port:Number($('vm-port').value),username:$('vm-user').value,auth:'password',password:$('vm-password').value,command_mode:$('vm-command').value,enabled:$('vm-enabled').checked,reset_fingerprint:$('vm-reset-key').checked});
 $('vm-password').value='';$('vm-password').required=false;
 const result=await json('/discovery/refresh','POST',{});await refresh();
 if((result.error||result.helper_update_required)&&!result.checking){$('vm-form').querySelector('.form-error').textContent=result.error||'Connected, but the installed VM helper is outdated. On the VM, run sudo bash deploy/start-manager.sh from the current source, then retry.';return;}
 $('vm-dialog').close();notify(result.connected?'VM connected. Lab discovery is active.':'VM settings saved. Check the discovery status for the connection result.');
});};
$('vm-refresh').onclick=async()=>{const b=$('vm-refresh'),label=(b.dataset&&b.dataset.label)||b.textContent;b.disabled=true;b.textContent='Checking the lab VM…';try{const result=await json('/discovery/refresh','POST',{});await refresh();notify(result.error||(!result.configured?'Connect the lab VM first (Manager › VM connection…).':result.connected?'Lab list refreshed.':'Automatic checks are paused or still running.'));}catch(e){notify(e.message);}finally{b.disabled=false;b.textContent=label;}};
$('link-deployment').onclick=()=>{const lab=current();$('binding-form').querySelector('.form-error').textContent='';$('binding-name').value=lab.deployment_name||lab.name;$('binding-prefix').value=lab.container_prefix??'clab';$('deployment-names').innerHTML=(state.discovery?.discovered||[]).map(l=>`<option value="${esc(l.name)}"></option>`).join('');$('binding-dialog').showModal();};
$('binding-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{await json('/labs/'+activeId+'/deployment','PUT',{deployed_name:$('binding-name').value.trim(),prefix:$('binding-prefix').value.trim()});$('binding-dialog').close();await refresh();notify('Deployment link saved.');});};

$('sync-vm').onclick=async()=>{
 const lab=current();if(!lab||vmSyncBusy)return;
 vmSyncBusy=true;
 const button=$('sync-vm'),label=(button.dataset&&button.dataset.label)||button.textContent;button.disabled=true;button.textContent='Syncing…';
 try{await json('/labs/'+lab.id+'/sync','POST',{});await refresh();notify('Topology updated from the VM. Device logins, saved progress and backups are kept.');}
 catch(error){notify(error.message);}
 finally{vmSyncBusy=false;button.textContent=label;renderManagement();}
};

$('remove-lab').onclick=()=>{
 const lab=current();if(!lab)return;
 $('remove-lab-form').reset();$('remove-lab-form').querySelector('.form-error').textContent='';
 $('remove-lab-id').value=lab.id;$('remove-lab-confirm-name').value=lab.name;
 $('remove-lab-name').textContent=lab.name;$('remove-lab-dialog').showModal();
};
$('remove-lab-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{
 const id=$('remove-lab-id').value, exclude=$('remove-lab-exclude').checked;
 await json('/labs/'+encodeURIComponent(id),'DELETE',{name:$('remove-lab-confirm-name').value,prevent_reimport:exclude});
 $('remove-lab-dialog').close();
 if(activeId===id){if(typeof goHome==='function')goHome();else{activeId='';sessionStorage.removeItem('activeLab');if($('details-dialog').open)$('details-dialog').close();}}
 await refresh();
 notify(exclude?'Lab removed. You can add it back from Home › Also running on the VM.':'Lab removed. It can be offered for import again after confirmation.');
});};
$('excluded-labs').onclick=e=>{
 const clear=e.target.closest('[data-clear-exclusion]');if(clear){openExclusionMenu(clear.dataset.clearExclusion);return;}
 const button=e.target.closest('[data-allow-import]');if(button)importDiscovered(button.dataset.allowImport);
};

let autoImportBusy=false, importPreview=null;
$('auto-import-dialog').addEventListener('close',()=>{importPreview=null;});
async function importDiscovered(name){
 if(autoImportBusy)return;
 autoImportBusy=true;$('setup-auto-import').disabled=true;
 notify('Reading deployed lab files from the VM…');
 try{
  const preview=await json('/discovery/import-preview','POST',{name});
  if($('setup-dialog').open)$('setup-dialog').close();
  importPreview=preview;
  $('auto-import-form').querySelector('.form-error').textContent='';
  $('auto-import-summary').textContent=preview.name+' · '+preview.nodes+' nodes · '+preview.links+' links';
  $('auto-import-files').innerHTML=Object.entries(preview.files).map(([kind,file])=>`<p><strong>${esc(kind)}</strong><br><small>${esc(file.path)}</small></p>`).join('');
  $('auto-import-warnings').textContent=[...(preview.warnings||[]),preview.missing.length?'Unavailable optional files: '+preview.missing.join(', '):''].filter(Boolean).join(' ');
  $('auto-import-excluded').hidden=!preview.excluded;
  $('auto-import-dialog').showModal();
  notify('Review the lab files and confirm to save this workspace.');
 }catch(error){
  if(!$('setup-dialog').open)openSetup(false,name);
  $('setup-form').querySelector('.form-error').textContent='Automatic import: '+error.message+' You can retry or upload the files below.';
  notify('Automatic import needs attention. Check the file details or upload manually.');
  await refresh();
 }finally{autoImportBusy=false;$('setup-auto-import').disabled=false;}
}
$('auto-import-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{
 const preview=importPreview;if(!preview)throw new Error('Preview the lab again before importing.');
 const lab=await json('/discovery/import','POST',{name:preview.name,token:preview.token});
 $('auto-import-dialog').close();await refresh();if(typeof selectLab==='function')selectLab(lab.id);else{activeId=lab.id;sessionStorage.setItem('activeLab',activeId);}notify('Lab added from the VM files.');
});};
$('setup-auto-import').onclick=()=>importDiscovered($('setup-deployed-name').value);

// Manager-only actions never invoke commands on the VM.
$('manager-settings').onclick=()=>{
 const dialog=opDialog('manager-settings-dialog','Manager settings',`<h3>Start fresh</h3><p>Remove all imported labs, device credentials, schedules, saved backup files, job and operation history, logs, and discovery exclusions from this manager.</p><p><strong>Your VM connection, SSH key and trusted fingerprint are retained.</strong> Running labs, original VM files and the installed helper account stay as they are.</p><p>Discovery will offer deployed labs for import again. Each import still requires confirmation.</p><p>Close SSH sessions and wait for active jobs before resetting.</p><label>Type RESET to confirm<input id="manager-reset-confirm" autocomplete="off" spellcheck="false"></label><div class="dialog-actions"><button class="button secondary" id="manager-reset-cancel">Cancel</button><button class="button primary" id="manager-reset" disabled>Start fresh</button></div>`);
 $('manager-reset-cancel').onclick=()=>dialog.close();$('manager-reset-confirm').oninput=()=>{$('manager-reset').disabled=$('manager-reset-confirm').value!=='RESET';};
 $('manager-reset').onclick=()=>opTask(dialog,async()=>{
  await json('/manager/reset','POST',{confirmation:$('manager-reset-confirm').value});
  if(typeof goHome==='function')goHome();else{activeId='';sessionStorage.removeItem('activeLab');}importPreview=null;opCaps=null;
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
  await refresh();notify('Manager data cleared. VM connection retained; deployed labs can be imported again.');
 });
};
function openExclusionMenu(name){
 const dialog=opDialog('exclusion-menu','Excluded lab',`<p>${esc(name)}</p><p>Clear forgets this exclusion so discovery can offer the lab again. This does not import or change the lab.</p><button class="button primary" id="clear-exclusion">Clear exclusion</button>`);
 $('clear-exclusion').onclick=()=>opTask(dialog,async()=>{await json('/discovery/forget-exclusion','POST',{name});dialog.close();await refresh();notify('Exclusion cleared. The lab can appear for import again.');});
}
$('excluded-labs').addEventListener('contextmenu',e=>{const button=e.target.closest('[data-allow-import]');if(button){e.preventDefault();openExclusionMenu(button.dataset.allowImport);}});
$('excluded-labs').addEventListener('keydown',e=>{const button=e.target.closest('[data-allow-import]');if(button&&(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10'))){e.preventDefault();openExclusionMenu(button.dataset.allowImport);}});
$('map-ssh-all').onclick=()=>{const lab=current();if(lab)opNewTab({mode:'ssh',lab:lab.id});};
$('map-backup-all').onclick=()=>{
 const lab=current();if(!lab)return;
 const ready=lab.nodes.filter(n=>n.readiness==='Ready'),skipped=lab.nodes.filter(n=>n.readiness!=='Ready');
 const dialog=opDialog('backup-all-review','Back up all configurations',`<p>${ready.length} of ${lab.nodes.length} nodes are ready for a configuration backup. This includes ready nodes that are unchecked in the inventory.</p>${skipped.length?'<p>These nodes will be skipped:</p><ul>'+skipped.map(n=>`<li>${esc(n.short_name||n.name)} · ${esc(n.readiness)}</li>`).join('')+'</ul>':''}<button class="button primary" id="backup-all-confirm" ${ready.length&&!busy()?'':'disabled'}>Back up ${ready.length} nodes</button>`);
 $('backup-all-confirm').onclick=()=>opTask(dialog,async()=>{await json('/labs/'+lab.id+'/jobs','POST',{operation:'backup',node_names:ready.map(n=>n.name)});dialog.close();await refresh();notify('Configuration backup started. View progress in Backup history.');});
};
