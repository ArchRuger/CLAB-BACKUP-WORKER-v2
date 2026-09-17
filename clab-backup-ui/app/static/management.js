'use strict';
let vmSyncBusy=false;
// Lists that re-render on the 4 s poll go through app.js's setMarkup so focus survives; the harness has no setMarkup.
function mgmtMarkup(el,html){if(!el)return;if(typeof setMarkup==='function')setMarkup(el,html);else el.innerHTML=html;}
// All host output is rendered as text or escaped; credentials never enter state responses.
document.body.insertAdjacentHTML('beforeend', `
<dialog id="auto-import-dialog"><form id="auto-import-form">
 <div class="dialog-head"><h2 id="auto-import-title">Add this lab to My labs?</h2><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <p id="auto-import-summary"></p>
 <p>The topology, map layout and any device logins found in the lab files on the VM are copied into this manager. Automatic backups stay off until you turn them on.</p>
 <h3>Files found on the VM</h3><div id="auto-import-files"></div><p id="auto-import-warnings" class="form-help"></p>
 <p id="auto-import-excluded" hidden>This lab was removed from the manager earlier. Adding it again starts from the VM files; earlier settings and backup history are not restored.</p>
 <p class="form-error" role="alert"></p>
 <div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Add lab</button></div>
</form></dialog>
<dialog id="remove-lab-dialog"><form id="remove-lab-form">
 <div class="dialog-head"><h2 id="remove-lab-title">Remove this lab from the manager?</h2><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <p id="remove-lab-name"></p>
 <input type="hidden" id="remove-lab-id"><input type="hidden" id="remove-lab-confirm-name">
 <p>This removes the lab from My labs: its device list, map, saved device logins, backup schedule and backup history entries. Backup files stay on this VM's disk.</p>
 <p>Nothing on the lab VM changes: the running devices and the topology files stay. Progress you saved to Git stays in the repository.</p>
 <label class="checkbox-label"><input id="remove-lab-exclude" type="checkbox" checked> Don't offer this lab for import again</label>
 <p class="form-help">Untick it if you want the lab to reappear under "Also running on the VM" on the Home page. Either way, adding it back needs your confirmation.</p>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button danger">Remove lab</button></div>
</form></dialog>
<dialog id="setup-dialog"><form id="setup-form">
 <div class="dialog-head"><h2 id="setup-title">Import lab files</h2><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <p>If the lab is already running on the VM, let the manager read its files. Otherwise choose the files yourself. The lab stays in My labs even when it is stopped.</p>
 <button type="button" class="button secondary" id="setup-auto-import">Read the files from the VM</button>
 <input type="hidden" name="lab_id" id="setup-lab-id">
 <label>Topology file (.clab.yaml)<input name="definition" type="file" accept=".yaml,.yml" required></label>
 <label>Lab name on the VM <span class="muted">optional</span><input name="deployed_name" id="setup-deployed-name" maxlength="120" placeholder="Use the name in the file"></label>
 <p class="form-help">Only needed if the lab was deployed under a different name than the one in the file. An existing lab with that name is updated in place.</p>
 <label>Map layout file <span class="muted">optional, .json</span><input name="annotations" type="file" accept=".json"></label>
 <p class="form-help">Without it a simple map is drawn. Importing does not start any devices; device addresses fill in automatically once the lab is running and the VM is connected.</p>
 <button type="button" class="button secondary" id="legacy-import">Import an Ansible inventory instead</button>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary" id="setup-submit">Add lab</button></div>
</form></dialog>
<dialog id="vm-dialog"><form id="vm-form">
 <div class="dialog-head"><h2>VM connection</h2><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <p>This is the machine that runs your labs. The manager signs in to it over SSH to find running labs, start them and open device CLIs. Usually set up once by the instructor.</p>
 <p><a href="/vm-connection-guide" target="_blank" rel="noopener">VM setup and troubleshooting guide <span aria-hidden="true">↗</span></a></p>
 <div class="form-grid wide"><label>VM address<input id="vm-address" required placeholder="127.0.0.1"></label><label>SSH port<input id="vm-port" type="number" min="1" max="65535" value="22" required></label></div>
 <label>VM username<input id="vm-user" required maxlength="128" autocomplete="off"></label>
 <label>VM password<input id="vm-password" type="password" autocomplete="current-password" maxlength="4096"></label>
 <p class="form-help">Create the clab-discovery password in the VM terminal during setup, then enter it here. Leave blank to keep a saved password for the same account. It is stored encrypted in the VM's persistent manager storage.</p>
 <p id="vm-password-migration" class="form-help" hidden>This connection previously used an SSH key. Run sudo bash deploy/setup-discovery.sh on the VM to create its password, then enter that password here.</p>
 <label>Inspection method<select id="vm-command"><option value="helper">Installed discovery and file helper (recommended)</option><option value="direct">Direct inspection + SFTP (existing VM account)</option></select></label>
 <p class="form-help">Install the supplied VM setup script for the helper. The restricted helper reads deployment state and the original YAML, annotations, generated inventory and topology export. New labs appear for import confirmation. Direct mode reads these files through SFTP with the same VM account. The installed helper supports root-owned lab files.</p>
 <label class="checkbox-label"><input id="vm-enabled" type="checkbox" checked> Check the VM automatically for running labs</label>
 <p id="vm-fingerprint" class="form-help"></p><p class="form-help">The first successful connection trusts and saves the VM SSH fingerprint. Later key changes block discovery.</p>
 <label class="checkbox-label"><input id="vm-reset-key" type="checkbox" checked> Trust a replacement SSH host key on the next connection</label>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Save and test connection</button></div>
</form></dialog>
<dialog id="binding-dialog"><form id="binding-form">
 <div class="dialog-head"><h2>Link to a running lab</h2><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <p>Tell the manager which lab on the VM this workspace belongs to. Normally this is matched automatically; use it when the lab was deployed under a different name. Device addresses stay as they are until you change them in Edit connection.</p>
 <label>Lab name on the VM<input id="binding-name" maxlength="120" list="deployment-names"></label><datalist id="deployment-names"></datalist>
 <label>Container prefix<input id="binding-prefix" maxlength="120" value="clab"></label><p class="form-help">Leave as clab unless the lab was deployed with a custom prefix. Clear the lab name to unlink.</p>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Save link</button></div>
</form></dialog>`);
document.querySelectorAll('[data-dismiss]').forEach(button=>button.onclick=()=>button.closest('dialog').close());

// The VM status line under Manager ▾, in the student's words; the admin command stays in a <small>.
function vmSummaryMarkup(discovery){
 if(!discovery.configured)return 'Lab VM: not connected. Choose VM connection… to set it up.';
 if(!discovery.host.enabled)return 'Lab VM: automatic checks paused.';
 if(discovery.helper_update_required)return 'Lab VM: connected, but its helper needs an update.<br><small>On the VM run: sudo bash deploy/start-manager.sh</small>';
 if(discovery.connected)return 'Lab VM: connected';
 return 'Lab VM: cannot be reached.<br><small>'+esc(discovery.error||'Status unknown — try Refresh lab list.')+'</small>';
}
// "Topology files on the VM: …" for Advanced › Deployment details, from vm_source.status.
function vmFilesStatus(lab,discovery){
 const source=lab.vm_source;
 if(!lab.deployment_name)return '';
 if(!discovery.connected)return 'Topology files: cannot check until the lab VM answers.';
 if(!discovery.file_import_supported)return 'Topology files: the VM helper needs an update before files can be read (or choose "Direct + SFTP" in VM connection…). Uploading files yourself still works.';
 if(!source)return discovery.file_errors?.[lab.deployment_name]||'No topology files found on the VM for this lab. Your workspace is kept.';
 const words={'Up to date':'Topology files on the VM: up to date','Updates available':'Topology files on the VM: newer than this workspace — use Lab actions ▾ › Sync topology from VM','Imported with warnings':'Topology files on the VM: imported with warnings (see Details)','Files unavailable':'Topology files on the VM: not found','VM unavailable':'Topology files on the VM: cannot check, the VM is not reachable'}[source.status]||('Topology files on the VM: '+source.status);
 return words+(source.synced_at?' · Last synced '+new Date(source.synced_at).toLocaleString():'')+(source.message?' · '+source.message:'');
}
function renderManagement(){
 const discovery=state.discovery||{}, lab=current();
 mgmtMarkup($('vm-summary'),vmSummaryMarkup(discovery));
 mgmtMarkup($('discovered-labs'),(discovery.discovered||[]).filter(l=>!l.imported&&!l.excluded).map(l=>`<button class="side-button" data-setup-name="${esc(l.name)}">${esc(l.name)}<small>${discovery.connected?'Running on the VM':'Last seen on the VM'} · ${l.running} of ${l.nodes} devices running · ${esc(discovery.file_errors?.[l.name]||(discovery.pending_imports?.[l.name]?'Ready to import — confirm to add it to My labs':'Add to My labs'))}</small></button>`).join(''));
 const reports=discovery.file_reports||{};
 const fileMarkup=Object.entries(reports).map(([name,files])=>`<p><strong>${esc(name)}</strong></p>${Object.entries(files).map(([kind,file])=>`<p>${esc(kind)}: ${esc(file.message)}<small>${(file.paths||[]).map(esc).join('<br>')}</small></p>`).join('')}`).join('')||'<p>No file checks yet. Use Manager ▾ › Refresh lab list. If it stays empty the VM helper may need an update (Manager ▾ › Diagnostics).</p>';
 mgmtMarkup($('discovery-file-list'),fileMarkup);
 // The same reports (every lab on the VM, imported ones included) stay reachable under Advanced › Deployment details.
 mgmtMarkup($('advanced-file-list'),fileMarkup);
 mgmtMarkup($('excluded-labs'),(discovery.ignored_labs||[]).length?'<p class="side-hint">Removed from this manager earlier</p>'+(discovery.ignored_labs||[]).map(name=>`<div class="empty-lab"><button class="side-button" data-allow-import="${esc(name)}">${esc(name)}<small>Import again · or stop hiding it so it appears automatically</small></button><button type="button" class="button secondary small" data-clear-exclusion="${esc(name)}">Stop hiding</button></div>`).join(''):'');
 maybePromptVmConnection();
 renderLanding(discovery,lab);
 if(!lab)return;
 const jobRunning=state.jobs.some(j=>j.lab_id===lab.id&&['queued','running'].includes(j.status));
 $('remove-lab').disabled=jobRunning;$('remove-lab').title=jobRunning?'Wait for the running backup or login test to finish.':'';
 const source=lab.vm_source, sync=$('sync-vm');
 sync.hidden=!lab.deployment_name;
 sync.disabled=vmSyncBusy||!discovery.connected||!source?.can_sync;
 sync.title=vmSyncBusy?'Sync already running':!discovery.connected?'Connect the VM first':!source?.can_sync?"This lab's files cannot be synced — see Advanced › Deployment details":'';
 if(!vmSyncBusy){const label=(sync.dataset&&sync.dataset.label)||'Sync topology from VM';sync.textContent=source?.status==='Updates available'?label+' (updates available)':label;}
 $('vm-files-status').textContent=vmFilesStatus(lab,discovery);
 $('deployment-status').textContent=lab.deployment?.status||'Unlinked';
 $('deployment-message').textContent=lab.deployment?.message||'Not linked to a running lab. Use Link to a running lab….';
 $('deployment-checked').textContent=lab.deployment?.last_success?'Last checked on the VM: '+new Date(lab.deployment.last_success).toLocaleString():'';
 renderNosReadiness(lab);
}
// Container state alone never proves a NOS is usable; the readiness monitor's verdict
// sits under the deployment status in plain words.
function renderNosReadiness(lab){
 const nos=lab.nos_readiness||{status:'idle'};
 $('deployment-nos').className='deployment-nos '+nos.status;
 $('deployment-nos').textContent=nos.status==='ready'?`NOS ready · ${nos.ready}/${nos.total} devices accept SSH login`:nos.status==='booting'?`NOS booting · ${nos.ready}/${nos.total} devices accept SSH login so far. SSH and the login test open automatically when they answer.`:nos.status==='failed'?`NOS login failed on ${nos.failed} of ${nos.total} devices · assign credentials, then Test login`:'';
}
// Deploy-first Home: connect the VM, then deploy or pick up a running lab.
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
 $('empty-vm-note').textContent=!configured?'Connect this manager to your lab VM first. Starting labs, finding running labs and opening device CLIs all use that connection.':!connected?(discovery.error||'Waiting for the lab VM to answer. Deploy becomes available as soon as it does.'):'';
 const running=(discovery.discovered||[]).filter(l=>!l.imported);
 $('empty-discovered').hidden=!running.length;
 mgmtMarkup($('empty-discovered-list'),running.map(l=>`<div class="empty-lab"><div><strong>${esc(l.name)}</strong><small>${l.running} of ${l.nodes} devices running${l.excluded?' · removed from this manager earlier':''}</small></div><button type="button" class="button secondary" data-setup-name="${esc(l.name)}">Import</button></div>`).join(''));
}
function openSetup(replace=false, deployedName=''){
 const lab=replace?current():null;$('setup-form').reset();$('setup-form').querySelector('.form-error').textContent='';
 deployedName=deployedName||(state.discovery?.discovered||[]).find(l=>!l.imported&&!l.excluded)?.name||'';
 $('setup-lab-id').value=lab?.id||'';$('setup-deployed-name').value=lab?.deployment_name||deployedName;
 $('setup-auto-import').hidden=replace||!deployedName||!state.discovery?.configured;
 $('setup-title').textContent=lab?'Update the topology file':'Import lab files';if($('setup-submit'))$('setup-submit').textContent=lab?'Update lab':'Add lab';$('setup-dialog').showModal();
}
$('new-lab').onclick=$('import-empty').onclick=()=>openSetup();
if($('home-import'))$('home-import').onclick=()=>openSetup();
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
 $('vm-dialog').close();notify(result.connected?'Lab VM connected.':'VM settings saved. See the status line under Manager ▾.');
});};
$('vm-refresh').onclick=async()=>{const b=$('vm-refresh'),label=(b.dataset&&b.dataset.label)||b.textContent;b.disabled=true;b.textContent='Checking the lab VM…';try{const result=await json('/discovery/refresh','POST',{});await refresh();notify(result.error||(!result.configured?'Connect the lab VM first (Manager ▾ › VM connection…).':result.connected?'Lab list refreshed.':'Automatic checks are paused or still running.'));}catch(e){notify(e.message);}finally{b.disabled=false;b.textContent=label;}};
$('link-deployment').onclick=()=>{const lab=current();$('binding-form').querySelector('.form-error').textContent='';$('binding-name').value=lab.deployment_name||lab.name;$('binding-prefix').value=lab.container_prefix??'clab';$('deployment-names').innerHTML=(state.discovery?.discovered||[]).map(l=>`<option value="${esc(l.name)}"></option>`).join('');$('binding-dialog').showModal();};
$('binding-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{await json('/labs/'+activeId+'/deployment','PUT',{deployed_name:$('binding-name').value.trim(),prefix:$('binding-prefix').value.trim()});$('binding-dialog').close();await refresh();notify('Link saved.');});};

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
 if($('remove-lab-title'))$('remove-lab-title').textContent='Remove '+lab.name+' from this manager?';
 $('remove-lab-name').textContent='';$('remove-lab-dialog').showModal();
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
 notify('Reading the lab files on the VM…');
 try{
  const preview=await json('/discovery/import-preview','POST',{name});
  if($('setup-dialog').open)$('setup-dialog').close();
  importPreview=preview;
  $('auto-import-form').querySelector('.form-error').textContent='';
  if($('auto-import-title'))$('auto-import-title').textContent='Add '+preview.name+' to My labs?';
  $('auto-import-summary').textContent=preview.nodes+' devices · '+preview.links+' links';
  $('auto-import-files').innerHTML=Object.entries(preview.files).map(([kind,file])=>`<p><strong>${esc(kind)}</strong><br><small>${esc(file.path)}</small></p>`).join('');
  $('auto-import-warnings').textContent=[...(preview.warnings||[]),preview.missing.length?'Unavailable optional files: '+preview.missing.join(', '):''].filter(Boolean).join(' ');
  $('auto-import-excluded').hidden=!preview.excluded;
  $('auto-import-dialog').showModal();
  notify('Check the files, then confirm to add the lab.');
 }catch(error){
  if(!$('setup-dialog').open)openSetup(false,name);
  $('setup-form').querySelector('.form-error').textContent='Automatic import: '+error.message+' You can retry, or choose the files below.';
  notify("Automatic import didn't work. Read the message in the dialog, or choose the files yourself.");
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
 const dialog=opDialog('manager-settings-dialog','Manager settings',`<h3>Start fresh</h3><p>Remove all imported labs, device credentials, schedules, saved backup files, job and operation history, logs, and discovery exclusions from this manager.</p><p><strong>Your VM connection and trusted fingerprint are kept.</strong> Running labs, original VM files and the installed helper account stay as they are.</p><p>Labs running on the VM are offered for import again. Each import still needs your confirmation.</p><p>Close CLI sessions and wait for running jobs before resetting.</p><label>Type RESET to confirm<input id="manager-reset-confirm" autocomplete="off" spellcheck="false"></label><div class="dialog-actions"><button class="button secondary" id="manager-reset-cancel">Cancel</button><button class="button danger" id="manager-reset" disabled>Start fresh</button></div>`);
 $('manager-reset-cancel').onclick=()=>dialog.close();$('manager-reset-confirm').oninput=()=>{$('manager-reset').disabled=$('manager-reset-confirm').value!=='RESET';};
 $('manager-reset').onclick=()=>opTask(dialog,async()=>{
  await json('/manager/reset','POST',{confirmation:$('manager-reset-confirm').value});
  if(typeof goHome==='function')goHome();else{activeId='';sessionStorage.removeItem('activeLab');}importPreview=null;opCaps=null;
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
  await refresh();notify('Manager data cleared. The VM connection is kept; labs on the VM can be added again.');
 });
};
function openExclusionMenu(name){
 const dialog=opDialog('exclusion-menu','Hidden lab',`<p><strong>${esc(name)}</strong></p><p>This lab was removed from the manager and is hidden from automatic import. Stop hiding it so it can appear under "Also running on the VM" again. Nothing is imported or changed on the VM.</p><button class="button primary" id="clear-exclusion">Stop hiding</button>`);
 $('clear-exclusion').onclick=()=>opTask(dialog,async()=>{await json('/discovery/forget-exclusion','POST',{name});dialog.close();await refresh();notify('The lab can appear for import again.');});
}
$('excluded-labs').addEventListener('contextmenu',e=>{const button=e.target.closest('[data-allow-import]');if(button){e.preventDefault();openExclusionMenu(button.dataset.allowImport);}});
$('excluded-labs').addEventListener('keydown',e=>{const button=e.target.closest('[data-allow-import]');if(button&&(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10'))){e.preventDefault();openExclusionMenu(button.dataset.allowImport);}});
$('map-ssh-all').onclick=()=>{const lab=current();if(lab)opNewTab({mode:'ssh',lab:lab.id});};
// Back up every device that can be backed up right now, whether or not it is ticked for scheduled
// backups; the review is only shown when some device would be skipped.
function readinessReason(value){return {'Choose NOS':'network OS not chosen','Needs credentials':'needs credentials','Lab unavailable':'not running'}[value]||String(value||'not ready');}
$('map-backup-all').onclick=()=>{
 const lab=current();if(!lab)return;
 const ready=lab.nodes.filter(n=>n.readiness==='Ready'),skipped=lab.nodes.filter(n=>n.readiness!=='Ready');
 const run=async(dialog)=>{await json('/labs/'+lab.id+'/jobs','POST',{operation:'backup',node_names:ready.map(n=>n.name)});if(dialog)dialog.close();await refresh();notify(`Backing up ${ready.length} ${ready.length===1?'device':'devices'}. Progress is under Tools › Configuration backups.`);};
 if(ready.length&&!skipped.length&&!busy()){opTask(null,()=>run(null));return;}
 const dialog=opDialog('backup-all-review','Back up all configurations',`<p>${ready.length} of ${lab.nodes.length} devices can be backed up now, including devices not selected for scheduled backups.</p>${skipped.length?'<p>These devices will be skipped:</p><ul>'+skipped.map(n=>`<li>${esc(n.short_name||n.name)} · ${esc(readinessReason(n.readiness))}</li>`).join('')+'</ul>':''}<button class="button primary" id="backup-all-confirm" ${ready.length&&!busy()?'':'disabled'}>Back up ${ready.length} ${ready.length===1?'device':'devices'}</button>`);
 $('backup-all-confirm').onclick=()=>opTask(dialog,()=>run(dialog));
};
