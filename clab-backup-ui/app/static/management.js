'use strict';
let vmSyncBusy=false;
// All host output is rendered as text or escaped; credentials never enter state responses.
document.body.insertAdjacentHTML('beforeend', `
<dialog id="remove-lab-dialog"><form id="remove-lab-form">
 <div class="dialog-head"><span class="eyebrow">REMOVE SAVED WORKSPACE</span><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <h2>Remove lab from this manager?</h2><p id="remove-lab-name"></p>
 <input type="hidden" id="remove-lab-id"><input type="hidden" id="remove-lab-confirm-name">
 <p>This removes the imported nodes, map, saved credentials, schedule and backup history entries. Saved backup files and audit logs remain on disk.</p>
 <p>Your running containers and lab files on the VM are unaffected. The VM connection and other saved labs remain available.</p>
 <label class="checkbox-label"><input id="remove-lab-exclude" type="checkbox" checked> Keep this lab excluded from automatic import</label>
 <p class="form-help">Uncheck to test discovery: the deployed lab can return on the next discovery check. Otherwise, use Import again in the sidebar when ready.</p>
 <p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Cancel</button><button type="submit" class="button primary">Remove saved lab</button></div>
</form></dialog>
<dialog id="setup-dialog"><form id="setup-form">
 <div class="dialog-head"><span class="eyebrow">PERSISTENT LAB WORKSPACE</span><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div>
 <h2 id="setup-title">Import a lab</h2><p>Start with the original containerlab YAML. The workspace remains saved when the lab is stopped or removed.</p>
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
 <h2>VM connection</h2><p>This standalone manager inspects deployed labs over SSH every 30 seconds. Device SSH credentials are configured separately.</p>
 <div class="form-grid wide"><label>VM address<input id="vm-address" required placeholder="127.0.0.1"></label><label>SSH port<input id="vm-port" type="number" min="1" max="65535" value="22" required></label></div>
 <label>VM username<input id="vm-user" required maxlength="128" autocomplete="off"></label>
 <label>Authentication<select id="vm-auth"><option value="password">Password</option><option value="key">SSH private key</option></select></label>
 <div id="vm-password-fields"><label>VM password<input id="vm-password" type="password" autocomplete="new-password"></label></div>
 <div id="vm-key-fields" hidden><label>SSH private key<input id="vm-key" type="file"></label><label>Key passphrase<input id="vm-passphrase" type="password" autocomplete="new-password"></label></div>
 <p class="form-help">Leave credentials blank to retain them for the same account. Secrets are encrypted in persistent storage and are never displayed after saving.</p>
 <label>Inspection method<select id="vm-command"><option value="helper">Installed discovery and file helper (recommended)</option><option value="direct">Direct containerlab inspect (account already has permission)</option></select></label>
 <p class="form-help">Install the supplied VM setup script for the helper. The restricted helper reads deployment state and the original YAML, annotations, generated inventory and topology export. New labs import automatically. Direct inspection only discovers running nodes.</p>
 <label class="checkbox-label"><input id="vm-enabled" type="checkbox" checked> Enable automatic discovery</label>
 <p id="vm-fingerprint" class="form-help"></p><p class="form-help">The first successful connection trusts and saves the VM SSH fingerprint. Later key changes block discovery.</p>
 <label class="checkbox-label"><input id="vm-reset-key" type="checkbox"> Trust a replacement SSH host key on the next connection</label>
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
 $('vm-summary').textContent=!discovery.configured?'VM discovery is not configured.':!discovery.host.enabled?'VM discovery is paused.':discovery.connected?'VM connected · checks every 30s':(discovery.error||'VM status unknown; refresh discovery.');
 $('discovered-labs').innerHTML=(discovery.discovered||[]).filter(l=>!l.imported&&!l.excluded).map(l=>`<button class="side-button" data-setup-name="${esc(l.name)}">${esc(l.name)}<small>${discovery.connected?'Discovered':'Last seen'} · ${l.running}/${l.nodes} running · ${esc(discovery.file_errors?.[l.name]||'setup required')}</small></button>`).join('');
 $('excluded-labs').innerHTML=(discovery.ignored_labs||[]).length?'<p class="side-hint">Excluded from automatic import</p>'+(discovery.ignored_labs||[]).map(name=>`<button class="side-button" data-allow-import="${esc(name)}">${esc(name)}<small>Import again</small></button>`).join(''):'';
 if(!lab)return;
 $('remove-lab').disabled=state.jobs.some(j=>j.lab_id===lab.id&&['queued','running'].includes(j.status));
 const source=lab.vm_source, sync=$('sync-vm');
 sync.hidden=!lab.deployment_name;
 sync.disabled=vmSyncBusy||!discovery.connected||!source?.can_sync;
 $('vm-files-status').textContent=!lab.deployment_name?'':!discovery.connected?'VM file sync is unavailable until discovery reconnects.':!discovery.file_import_supported?'Automatic file import requires the updated VM helper. Manual uploads remain available.':source?('VM files: '+source.status+(source.synced_at?' · Last synced '+new Date(source.synced_at).toLocaleString():'')+(source.message?' · '+source.message:'')):(discovery.file_errors?.[lab.deployment_name]||'No deployed source files found. Saved workspace retained.');
 $('deployment-status').textContent=lab.deployment?.status||'Unlinked';
 $('deployment-message').textContent=lab.deployment?.message||'Link this workspace to a deployed lab.';
 $('deployment-checked').textContent=lab.deployment?.last_success?'Last successful inspection: '+new Date(lab.deployment.last_success).toLocaleString():'';
}
function openSetup(replace=false, deployedName=''){
 const lab=replace?current():null;$('setup-form').reset();$('setup-form').querySelector('.form-error').textContent='';
 $('setup-lab-id').value=lab?.id||'';$('setup-deployed-name').value=lab?.deployment_name||deployedName;
 $('setup-title').textContent=lab?'Update lab definition':'Import a lab';$('setup-dialog').showModal();
}
$('new-lab').onclick=$('add-lab').onclick=$('import-empty').onclick=()=>openSetup();
$('import-top').onclick=()=>current()?openImport(true):openSetup();
$('update-definition').onclick=()=>openSetup(true);
$('legacy-import').onclick=()=>{$('setup-dialog').close();openImport(!!$('setup-lab-id').value);};
$('discovered-labs').onclick=e=>{const b=e.target.closest('[data-setup-name]');if(b)openSetup(false,b.dataset.setupName);};
$('setup-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{
 const result=await(await api('/lab-definitions',{method:'POST',body:new FormData(e.target)})).json();
 activeId=result.id;sessionStorage.setItem('activeLab',activeId);tab='inventory';$('setup-dialog').close();$('setup-form').reset();await refresh();notify('Lab saved. Discovery updates automatic addresses when the lab is running.');
});};
function vmAuthFields(){$('vm-key-fields').hidden=$('vm-auth').value!=='key';$('vm-password-fields').hidden=$('vm-auth').value!=='password';}
$('vm-auth').onchange=vmAuthFields;
$('vm-settings').onclick=()=>{
 const h=state.discovery?.host||{};$('vm-form').reset();$('vm-form').querySelector('.form-error').textContent='';
 $('vm-address').value=h.address||'127.0.0.1';$('vm-port').value=h.port||22;$('vm-user').value=h.username||'clab-discovery';$('vm-auth').value=h.auth||'key';$('vm-command').value=h.command_mode||'helper';$('vm-enabled').checked=h.enabled!==false;
 $('vm-fingerprint').textContent=h.fingerprint?'Saved fingerprint: '+h.fingerprint:'No VM fingerprint saved yet.';vmAuthFields();$('vm-dialog').showModal();
};
$('vm-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{
 const file=$('vm-key').files[0];if(file&&file.size>65536)throw new Error('SSH key must be smaller than 64 KiB');
 await json('/host','PUT',{address:$('vm-address').value,port:Number($('vm-port').value),username:$('vm-user').value,auth:$('vm-auth').value,password:$('vm-password').value,private_key:file?await file.text():'',passphrase:$('vm-passphrase').value,command_mode:$('vm-command').value,enabled:$('vm-enabled').checked,reset_fingerprint:$('vm-reset-key').checked});
 const result=await json('/discovery/refresh','POST',{});await refresh();$('vm-password').value='';$('vm-key').value='';$('vm-passphrase').value='';
 if(result.error&&!result.checking){$('vm-form').querySelector('.form-error').textContent=result.error;return;}
 $('vm-dialog').close();notify(result.connected?'VM connected. Lab discovery is active.':'VM settings saved. Check the discovery status for the connection result.');
});};
$('vm-refresh').onclick=async()=>{const b=$('vm-refresh');b.disabled=true;b.textContent='Checking VM…';try{const result=await json('/discovery/refresh','POST',{});await refresh();notify(result.error||(!result.configured?'Configure the VM connection first.':result.connected?'Discovery updated.':'Discovery is paused or still checking.'));}catch(e){notify(e.message);}finally{b.disabled=false;b.textContent='Refresh discovery';}};
$('link-deployment').onclick=()=>{const lab=current();$('binding-form').querySelector('.form-error').textContent='';$('binding-name').value=lab.deployment_name||lab.name;$('binding-prefix').value=lab.container_prefix??'clab';$('deployment-names').innerHTML=(state.discovery?.discovered||[]).map(l=>`<option value="${esc(l.name)}"></option>`).join('');$('binding-dialog').showModal();};
$('binding-form').onsubmit=e=>{e.preventDefault();withForm(e.currentTarget,async()=>{await json('/labs/'+activeId+'/deployment','PUT',{deployed_name:$('binding-name').value.trim(),prefix:$('binding-prefix').value.trim()});$('binding-dialog').close();await refresh();notify('Deployment link saved.');});};

$('sync-vm').onclick=async()=>{
 const lab=current();if(!lab||vmSyncBusy)return;
 vmSyncBusy=true;
 const button=$('sync-vm');button.disabled=true;button.textContent='Syncing…';
 try{await json('/labs/'+lab.id+'/sync','POST',{});await refresh();notify('VM files synced. Saved connections, credentials and backup history retained.');}
 catch(error){notify(error.message);}
 finally{vmSyncBusy=false;button.textContent='Sync from VM';renderManagement();}
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
 if(activeId===id){activeId='';sessionStorage.removeItem('activeLab');tab='inventory';if($('details-dialog').open)$('details-dialog').close();}
 await refresh();
 notify(exclude?'Saved lab removed. Use Import again to rediscover it.':'Saved lab removed. Discovery can import the deployed lab again on its next check.');
});};
$('excluded-labs').onclick=async e=>{
 const button=e.target.closest('[data-allow-import]');if(!button||button.disabled)return;
 button.disabled=true;
 try{const result=await json('/discovery/allow-import','POST',{name:button.dataset.allowImport});await refresh();notify(result.error||'Automatic import enabled. Available VM files are imported during discovery.');}
 catch(error){notify(error.message);button.disabled=false;}
};
