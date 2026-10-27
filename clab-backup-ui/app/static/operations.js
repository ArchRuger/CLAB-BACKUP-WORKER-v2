'use strict';
// Shared by the main workspace and independent VM-folder / SSH-launcher tabs.
// opLabels are the imperative student labels for every containerlab action (status.js keeps its own
// in-progress table for the header and the banner); the review dialog, the output window and the
// history rows all read from here so one operation has one name everywhere.
const opLabels={deploy:'Start lab',redeploy:'Redeploy lab',destroy:'Destroy lab',apply:'Apply topology changes',start:'Start devices',stop:'Stop devices',restart:'Restart all devices','restart-node':'Restart device','start-node':'Start device','stop-node':'Stop device',save:'Save device configurations',inspect:'Show running devices','inspect-all':'Running labs on the VM',create:'Create topology file',delete:'Delete topology file',clone:'Download lab',publish:'Save lab to the VM',revise:'Save topology changes'};
const opNodeActions=['restart-node','start-node','stop-node'];
const opLifecycle=['deploy','start','stop','restart','restart-node','start-node','stop-node','redeploy','destroy','apply'];
const opDisruptive=['stop','restart','restart-node','stop-node','redeploy','destroy','apply'];
let opCaps=null, opMenuLab='', opOutputTimer=null, opEditorContext=null;
// Every operation dialog is named by its own heading (screen readers announce the title, not "dialog"),
// and gives focus back to the control that opened it when it closes: `opener` names that control; without
// one, whatever had focus when the dialog opened (a keyboard user keeps their place either way).
function opDialog(id,title,body,opener){
 let dialog=$(id);if(!dialog){dialog=document.createElement('dialog');dialog.id=id;dialog.className='operations-dialog';document.body.append(dialog);
  if(typeof dialog.addEventListener==='function')dialog.addEventListener('close',()=>{const back=dialog._opener;dialog._opener=null;if(back&&typeof back.focus==='function'&&(typeof document==='undefined'||!document.body||typeof document.body.contains!=='function'||document.body.contains(back)))back.focus();});
 }
 if(!dialog.open){const active=typeof document!=='undefined'?document.activeElement:null;dialog._opener=opener||(active&&active!==document.body?active:null);}
 else if(opener)dialog._opener=opener;
 if(typeof dialog.setAttribute==='function')dialog.setAttribute('aria-labelledby',id+'-title');
 dialog.innerHTML=`<div class="dialog-head"><h2 id="${esc(id)}-title">${esc(title)}</h2><button class="icon-button" data-op-close aria-label="Close">×</button></div>${body}<p class="form-error" role="alert"></p>`;
 dialog.querySelector('[data-op-close]').onclick=()=>dialog.close();if(!dialog.open)dialog.showModal();return dialog;
}
async function opTask(dialog,fn){
 const error=dialog?.querySelector('.form-error');if(error)error.textContent='';
 const buttons=dialog?[...dialog.querySelectorAll('button:not(:disabled)')]:[];buttons.forEach(b=>b.disabled=true);
 try{return await fn();}catch(e){if(error){error.textContent=e.message;if(typeof error.scrollIntoView==='function')error.scrollIntoView({block:'nearest'});}else if(typeof showActionError==='function')showActionError(e.message);else notify(e.message);}finally{buttons.forEach(b=>b.disabled=false);}
}
function opPath(lab){return lab?.vm_project_path||lab?.vm_source?.files?.definition?.path||'';}
function opName(lab){return lab?.deployment_name||lab?.name||'';}
function opWhen(value){if(!value)return '';return typeof relativeTime==='function'?relativeTime(value):new Date(value).toLocaleString();}
function opStatusWord(status){return {succeeded:'Completed',failed:'Failed',interrupted:'Interrupted',cancelled:'Stopped by you',running:'Running',queued:'Waiting'}[status]||String(status||'');}
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
// Try again on a failed operation (the lab banner, app.js) repeats the request the student confirmed: the manager's job
// record carries no options, so opReview remembers the request by job id (shell.js rememberJobRequest). When none is known
// (a job from an earlier session), only an action with nothing to choose is repeated from its name: destroy with the
// default options, the lifecycle actions with none. deploy and redeploy may have been the clear-the-folder variant, and
// create, revise, publish and clone need text that is gone, so for those this returns null and the banner offers the dialog.
const opPlainRetry=['start','stop','restart','apply','inspect','inspect-all','save','delete'];
const opRedeployActions=['deploy','start','apply','restart'];
function opRetryRequest(job,labId){
 const stored=typeof jobRequest==='function'?jobRequest(job?.id):null;
 const chosen=typeof statusJobNodes==='function'?statusJobNodes(job):[];
 const withoutNodes=request=>{if(!request||!request.options||!('nodes' in request.options))return request;const {nodes,...rest}=request.options;return {...request,options:rest};};
 // A stopped deploy may have left some devices started: the repair is Redeploy lab, with the options the student confirmed.
 // Start, apply and restart end in the same aftermath (Redeploy lab), so they take the same way back.
 if(job?.status==='cancelled'&&opRedeployActions.includes(job.action))return stored&&stored.action===job.action?withoutNodes({...stored,action:'redeploy',lab_id:labId}):(job.action==='deploy'?null:{lab_id:labId,action:'redeploy',options:{}});
 if(stored&&stored.action===job.action)return {...stored,lab_id:labId,...(job.node&&!stored.node?{node:job.node}:{})};
 // A job limited to chosen devices (its public `nodes`) repeats for those devices alone, never as the whole-lab action: a destroy
 // takes no cleanup then (the two cannot combine); any other action with devices has no safe guess, so the banner opens the dialog.
 if(chosen.length){
  if(job.action==='destroy')return {lab_id:labId,action:'destroy',options:{nodes:chosen}};
  if(job.action==='save')return {lab_id:labId,action:'save',options:{nodes:chosen}};
  return null;
 }
 if(job?.action==='destroy')return {lab_id:labId,action:'destroy',options:opDestroyOptions()};
 // The three single-device actions never travel without their device, so they are not in opPlainRetry.
 if(opNodeActions.includes(job?.action)&&job.node)return {lab_id:labId,action:job.action,node:job.node,options:{}};
 if(opPlainRetry.includes(job?.action))return {lab_id:labId,action:job.action,options:{}};
 return null;
}
// Hide from Home takes the lab off the Home list and nothing else: the words say what stays (the lab, its
// devices, backups, saved progress and settings; the VM untouched) and the two ways back. Pure.
function opHideHelp(lab){
 if(lab&&lab.hidden)return 'This lab is hidden from Home. Show on Home puts its card back; nothing else changed while it was hidden.';
 const running=lab?.deployment?.status==='Running';
 return 'Hide from Home takes the card off Home only'+(running?' (the lab keeps running on the VM)':'')+': its devices, backups, saves and settings are kept and nothing on the VM changes. Add it again from Choose a file on the lab VM…, or show it under Manager ▾ › Labs found on the VM….';
}
function opHideNotice(lab){
 if(lab&&lab.hidden)return lab.name+' is back on Home.';
 return lab.name+' is hidden from Home'+(lab?.deployment?.status==='Running'?' and keeps running on the VM':'')+'. Add it again from Choose a file on the lab VM…, or Manager ▾ › Labs found on the VM….';
}
async function openLabOperations(id=activeId){
 opMenuLab=id;const lab=state.labs.find(l=>l.id===id);if(!lab)return;
 const dialog=opDialog('lab-operations-dialog',lab.name,'<p>Checking what this VM can do…</p>');
 let problem='';try{await opCapabilities();}catch(e){opCaps=null;problem=e.message;}
 if(!dialog.open)return;
 const path=opPath(lab);
 const cleanup=['deploy','redeploy'].filter(a=>opCaps?.actions[a]?.cleanup).map(a=>opCommand(a,(a==='deploy'?'Deploy lab':'Redeploy lab')+' and clear the lab folder…',{cleanup:true})).join('');
 opDialog(dialog.id,lab.name,`<p class="op-path">${path?'Topology file on the VM: '+esc(path):"This lab has no topology file on the VM yet. Import the lab's files (Advanced › Deployment details) to enable these actions."}</p>${problem?`<p class="op-notice">Couldn't check the VM's commands, so every action is shown; some may fail. Details: ${esc(problem)}</p>`:''}
 <div class="op-sections"><section><h3>Deployment</h3><div class="op-grid">${opCommand('deploy','Deploy lab')}${['redeploy','start','stop','restart','apply','inspect','save'].map(a=>opCommand(a)).join('')}</div><p class="form-help">Deploy creates and starts the devices; Start, Stop and Restart act on the running devices. "Save device configurations" uses containerlab's own save (supported device types only); your saves (Save in the lab’s header) are separate.</p></section>
 <section><h3>Lab tools</h3><div class="op-grid"><button class="button secondary" data-local="ssh"><span>Open all CLIs <span aria-hidden="true">↗</span></span></button><button class="button secondary" data-local="interactive">Edit map</button><button class="button secondary" data-local="history">Operation history…</button><button class="button secondary" data-local="favorite">${lab.favorite?'Remove from favourites':'Add to favourites'}</button><button class="button secondary" data-local="hide">${lab.hidden?'Show on Home':'Hide from Home'}</button></div><p class="form-help">${opHideHelp(lab)}</p></section>
 <section class="op-danger"><h3>Danger</h3><div class="op-grid">${opCommand('destroy','Destroy lab…',opDestroyOptions())}${cleanup}${opCommand('delete','Delete the topology file from the VM…')}</div><p class="form-help">Destroy removes the running devices and, when the installed containerlab supports cleanup, the lab's generated folder on the VM. Redeploy keeps that folder unless you choose the "clear the lab folder" variant.</p></section></div>`);
 dialog.querySelectorAll('[data-op-action]').forEach(b=>b.onclick=()=>{
  const action=b.dataset.opAction,options=JSON.parse(b.dataset.opOptions);
  opTask(dialog,()=>opReview({lab_id:id,action,options}));
 });
 dialog.querySelectorAll('[data-local]').forEach(b=>b.onclick=()=>opTask(dialog,async()=>{
  const action=b.dataset.local;
  if(action==='ssh')opNewTab({mode:'ssh',lab:id});
  if(action==='favorite'){await json('/labs/'+id+'/operations-settings','PUT',{favorite:!lab.favorite});await refresh();dialog.close();}
  if(action==='hide'){await json('/labs/'+id+'/operations-settings','PUT',{hidden:!lab.hidden});await refresh();dialog.close();notify(opHideNotice(lab));}
  if(action==='interactive')await opLayout(id);
  if(action==='history')await opHistory(id);
 }));
}
// Retired telemetry configuration: the manager once added a handful of configuration lines on some
// devices so it could collect live interface data; the feature is gone, but the lines it left stay on
// a device until removed. lab.telemetry_retired (app.js, the lab banner and the Lab actions ▾ menu
// item) names the short-named devices that still carry them; this dialog reads the full record (kind,
// the lines themselves, whether a device can be reached to remove them and, when not, why) and either
// removes the lines inside the device's own configuration session (reading the device back), or
// forgets an entry the manager can never remove automatically (`permanent`: the device left the lab,
// changed or unsupported kind, or lines outside the recorded shape) — or a whole record it could never
// read (`malformed`). A transient reason (device not running, login not proven) gets no forget button:
// the reason text already says what to do, and a fresh read may make it removable.
function retiredKindLabel(kind){return kind?((state.platforms||{})[kind]?.label||kind):'';}
async function openTelemetryRetired(id=activeId){
 const data=await(await api('/labs/'+id+'/telemetry-retired')).json();
 const nodes=data.nodes||[],removable=nodes.some(n=>n.removable),shortByName=Object.fromEntries(nodes.map(n=>[n.name,n.short_name||n.name]));
 const malformedButton='<button type="button" class="button secondary" id="op-retired-forget-malformed">Forget the unreadable record</button>';
 const rows=nodes.map((n,i)=>`<div class="op-retired-node"><h4>${esc(n.short_name||n.name)}${n.kind?` <span class="badge platform">${esc(retiredKindLabel(n.kind))}</span>`:''}</h4><pre class="op-output">${esc((n.lines||[]).join('\n'))}</pre>${!n.removable&&n.reason?`<p class="op-notice">${esc(n.reason)}${n.permanent?` <button type="button" class="button secondary small" id="op-retired-forget-${i}">Forget</button>`:''}</p>`:''}</div>`).join('');
 const body=nodes.length
  ?`<p class="form-help">Removing deletes only these lines on the running device, inside the device's own configuration session, and reads the device back. Nothing else changes.</p>${rows}${data.malformed?`<p class="op-notice">A telemetry record of this lab could not be read and is kept for review. ${malformedButton}</p>`:''}`
  :'<p class="form-help">A telemetry record of this lab could not be read and is kept for review.</p>';
 const dialog=opDialog('telemetry-retired-dialog','Retired telemetry configuration',`${body}<div id="op-retired-results"></div><div class="dialog-actions"><button class="button secondary" id="op-retired-close">Close</button>${nodes.length?`<button class="button primary" id="op-retired-remove" ${removable?'':'disabled'}>Remove from devices</button>`:malformedButton}</div>`);
 $('op-retired-close').onclick=()=>dialog.close();
 if(nodes.length)$('op-retired-remove').onclick=()=>opTask(dialog,async()=>{
  const result=await json('/labs/'+id+'/telemetry-retired/remove','POST',{});
  const results=result.results||[],removed=results.filter(r=>r.outcome==='removed').length;
  $('op-retired-results').innerHTML=results.length?'<ul>'+results.map(r=>`<li>${esc(shortByName[r.name]||r.name)}: ${esc(r.outcome)} — ${esc(r.message||'')}</li>`).join('')+'</ul>':'';
  notify(results.length?`Removed telemetry configuration on ${removed} of ${results.length} device${results.length===1?'':'s'}.`:'Nothing to remove on the running devices.');
  await refresh();
 });
 if(data.malformed)$('op-retired-forget-malformed').onclick=()=>opTask(dialog,async()=>{
  await json('/labs/'+id+'/telemetry-retired/forget','POST',{malformed:true});
  $('op-retired-results').innerHTML='<ul><li>The unreadable record was forgotten.</li></ul>';
  notify('Forgot the unreadable record.');
  await refresh();
 });
 nodes.forEach((n,i)=>{
  if(n.removable||!n.permanent)return;
  $('op-retired-forget-'+i).onclick=()=>opTask(dialog,async()=>{
   await json('/labs/'+id+'/telemetry-retired/forget','POST',{node:n.name});
   $('op-retired-results').innerHTML=`<ul><li>${esc(n.short_name||n.name)}: forgotten.</li></ul>`;
   notify(`Forgot the record for ${n.short_name||n.name}.`);
   await refresh();
  });
 });
 return dialog;
}
// What each action asks the student before it runs: title, one-sentence effect, confirm label.
const opReviewCopy={
 deploy:{title:n=>`Start ${n}?`,body:'Creates and starts the devices in this topology as its file describes them, including any hooks, mounts and image pulls. Nothing is deleted; device logins open as the devices boot.',confirm:'Start lab'},
 start:{title:n=>`Start ${n}'s stopped devices?`,body:'Stopped devices start again with their existing configuration.',confirm:'Start devices'},
 stop:{title:()=>'Stop devices?',body:'Devices stop but keep their startup configuration.',confirm:'Stop devices'},
 restart:{title:n=>`Restart every device of ${n}?`,body:'Every device of the lab restarts through containerlab: each container stops and starts again with its links kept. CLI sessions to the lab drop and traffic stops while they restart; configuration changes you have not saved on a device may not survive. Nothing is saved, backed up, reset or reapplied for you.',confirm:'Restart all devices',danger:true},
 // Restart device (one node): containerlab's own node-scoped restart, the operation the VS Code extension
 // runs. The text names the device and the lab, what is interrupted, and what is not done for the student.
 'restart-node':{title:(n,v)=>`Restart ${v?.node_label||'this device'}?`,body:v=>`Only ${v.node_label||'this device'} in ${v.name} restarts: containerlab stops it and starts it again with its links kept (containerlab restart --node). While it restarts, its CLI sessions drop and traffic through it stops, and neighbouring devices lose their adjacencies to it until it is back. Configuration changes you have not saved on the device may not survive. Nothing is saved, backed up, reset or reapplied for you.`,confirm:'Restart device',danger:true},
 // Start device and Stop device (one node): containerlab's node-scoped start and stop. The text names the device and the lab, what
 // is interrupted and what is not done for the student; known limits and neighbour notes arrive from the manager as warnings.
 'stop-node':{title:(n,v)=>`Stop ${v?.node_label||'this device'}?`,body:v=>`Only ${v.node_label||'this device'} in ${v.name} stops: containerlab stops its container and parks its links (containerlab stop --node). Its CLI sessions drop and traffic through it stops; neighbours lose their adjacencies to it until it starts again. Configuration changes you have not saved on the device may not survive. Nothing is saved, backed up, reset or reapplied for you.`,confirm:'Stop device',danger:true},
 'start-node':{title:(n,v)=>`Start ${v?.node_label||'this device'}?`,body:v=>`Only ${v.node_label||'this device'} in ${v.name} starts: containerlab starts its container and restores the links it parked (containerlab start --node). The device boots and reads Starting until it accepts a login again.`,confirm:'Start device'},
 redeploy:{title:n=>`Redeploy ${n}?`,body:'Devices are destroyed and started again from the topology; unsaved device changes are lost. Save first if you need them.',confirm:'Redeploy lab',danger:true,cleanup:" The lab's generated folder on the VM is cleared as well."},
 destroy:{title:n=>`Destroy ${n}?`,body:v=>`The running devices are removed from the VM${v.options?.cleanup?" and the lab's generated folder is deleted":''}. Configuration changes you have not saved are lost. Your saves, lab states and backups remain.`,confirm:'Destroy lab',danger:true},
 apply:{title:n=>`Apply topology changes to ${n}?`,body:'The running lab is updated to match the topology file. Devices removed from the file are destroyed; connectivity may be interrupted.',confirm:'Apply changes',danger:true},
 save:{title:()=>'Save device configurations on the VM?',body:'Each supported device writes its running configuration to its startup configuration on the VM (containerlab save). This is separate from Save in the lab’s header.',confirm:'Save configurations'},
 inspect:{title:n=>`Refresh the device list for ${n}`,body:"Reads the current state of this lab's devices from the VM. Nothing is changed.",confirm:'Show devices',readonly:true},
 'inspect-all':{title:()=>'Refresh the list of running labs on the VM',body:'Reads which labs are running on the VM. Nothing is changed.',confirm:'Show running labs',readonly:true,hideName:true},
 delete:{title:n=>`Delete ${n}'s topology file from the VM?`,body:v=>`${v.path||'The topology file'} is deleted after a recovery copy is kept. The lab stays in My labs and your saves are untouched. Only possible while the lab is not running.`,confirm:'Delete file',danger:true},
 create:{title:()=>'Create this topology file on the VM?',body:v=>`Writes ${v.path||'the file'} on the VM. No devices are started until you deploy it.`,confirm:'Create file'},
 publish:{title:n=>`Save ${n} to the VM?`,body:v=>`Creates the lab folder ${v.folder||''} on the VM with the topology file and the map layout. Nothing on the VM is overwritten and no devices are started until you deploy it.`,confirm:'Save lab',quiet:true},
 revise:{title:n=>`Save the changes to ${n}?`,body:()=>'Replaces the topology file and the map layout on the VM. A copy of the previous version is kept in the lab folder.',confirm:'Save changes',quiet:true},
 clone:{title:(n,v)=>`Download ${v?.options?.project||'this lab'}?`,body:v=>`Downloads ${v.options?.url||'the repository'} into the VM's lab folder as ${v.options?.project||'a new folder'}. Existing folders are never overwritten.`,confirm:'Download',hideName:true},
};
// The last-save line of a disruptive confirmation: when the lab was last saved (the newest save that read the devices), in red when
// never, when a lab operation or a load ran after it, and what still waits for upload. From the header chip's status functions.
function opSaveLine(lab,value){
 if(!lab||!opDisruptive.includes(value.action)||typeof saveChipState!=='function'||typeof statusCaptureSaves!=='function')return '';
 const cs=saveChipState(lab,state),save=statusCaptureSaves(lab,state)[0]||null,at=save?save.created||save.finished||'':'';
 const never=!save||!at;
 const lastOp=(state.operations||[]).filter(j=>j.lab_id===lab.id&&j.finished).sort((a,b)=>String(b.finished).localeCompare(String(a.finished)))[0];
 const stale=!never&&((lastOp&&new Date(at)<new Date(lastOp.finished))||!!cs.load);
 const waiting=cs.count?` ${cs.count===1?'1 save is':cs.count+' saves are'} not uploaded yet.`:'';
 const text=never?(lab.git_binding?'Never saved.':'Never saved — this lab has no save location yet.'):`Last saved ${opWhen(at)}.${cs.load?' A saved state was loaded since.':''}${waiting}`;
 return `<p class="op-save-line${never||stale?' danger':''}">${esc(text)}</p>`;
}
// One sentence per image of a reviewed topology, from the manager's answer (POST /api/operations/image-check):
// on the VM, pullable, not found anywhere (a deploy fails for its devices), or unanswered. Pure.
function opImageLine(item){
 const who=(item.nodes||[]).length?' ('+item.nodes.join(', ')+')':'';
 if(item.available===false)return item.reference+who+': this VM has no Docker client the manager can ask; checked at deploy time.';
 if(item.local)return item.reference+who+': on the VM.';
 if(item.registry==='found')return item.reference+who+': not on the VM yet; the deploy pulls it from its registry.';
 if(item.registry==='not-found')return item.reference+who+': not on the VM and no registry offers it (not there, or it needs a login on the VM). The deploy fails for '+((item.nodes||[]).length?(item.nodes||[]).join(', '):'its devices')+'.';
 if(item.registry==='invalid')return item.reference+who+': not a usable image name. The deploy fails for '+((item.nodes||[]).length?(item.nodes||[]).join(', '):'its devices')+'.';
 if(item.registry==='unreachable')return item.reference+who+': not on the VM; its registry did not answer, so the deploy would try to pull it.';
 return item.reference+who+': not on the VM; whether it can be pulled could not be checked.';
}
function opImageMissing(items){return (items||[]).filter(i=>i&&i.available!==false&&!i.local&&(i.registry==='not-found'||i.registry==='invalid'));}
// The images a student has to act on or know about: not on the VM and not pullable as far as the
// manager could tell (not found, unusable name, registry silent, unanswered), or the whole check
// unavailable. On the VM and pullable images need nothing, so they are not listed. Pure.
function opImageAttention(rows){return (rows||[]).filter(i=>i&&(i.available===false||(!i.local&&i.registry!=='found')));}
// Fills the review's image list once the manager has asked the VM; the review itself never waits for this.
// Only images that need attention are listed; with none the section stays absent, and a failed check says so once.
async function opReviewImages(dialog,images){
 const list=dialog.querySelector('#op-review-images'),status=dialog.querySelector('#op-review-images-status');if(!list||!images.length)return;
 const section=dialog.querySelector('#op-review-images-section');
 try{
  const value=await json('/operations/image-check','POST',{references:images.slice(0,16).map(i=>i.reference)});if(!dialog.open||!list.isConnected)return;
  const byRef=new Map((value.images||[]).map(i=>[i.reference,i])),rows=images.map(i=>({...i,...(byRef.get(i.reference)||{registry:'unknown',local:false})}));
  const attention=opImageAttention(rows);
  list.innerHTML=attention.map(r=>`<li class="${opImageMissing([r]).length?'op-image-missing':''}">${esc(opImageLine(r))}</li>`).join('');
  if(section){section.hidden=!attention.length;const summary=section.querySelector('summary');if(summary)summary.textContent=`Images needing attention (${attention.length})`;}
  if(status)status.remove();
  // The image is named once, in the list above with its reason; the one fix sentence sits directly under the heading.
  const missing=opImageMissing(rows),fix=dialog.querySelector('#op-review-images-fix');
  if(fix){fix.hidden=!missing.length;fix.textContent=missing.length?(missing.length===1?'The devices using it stay down after the deploy.':'The devices using them stay down after the deploy.')+' Choose an image the VM has, or load it on the VM first.':'';}
 }catch{if(dialog.open&&list.isConnected&&status){status.className='op-notice';status.textContent='Images could not be checked right now; the deploy reports any image it cannot pull.';}}
}
// The apply plan (C05 4.4), as the manager passes it (`value.plan`, or the pending-changes check's `plan`): created, started,
// restarted, recreated and removed devices, links to connect and link ends to disconnect, with the reason for a restart or a
// recreation. Pure functions: the review and the banner read the same words.
const OP_PLAN_SECTIONS=[['added','Create',''],['started','Start',''],['restarted','Restart',''],['recreated','Recreate','These devices are recreated: configuration you have not saved on them is lost.'],['removed','Remove','These devices are removed from the VM: their unsaved configuration is lost.'],['links_added','Links to connect',''],['endpoints_removed','Link ends to disconnect','']];
function opPlanList(plan,key){return Array.isArray(plan&&plan[key])?plan[key].map(String):[];}
function opPlanChanges(plan){return !!plan&&(plan.deploys_lab===true||OP_PLAN_SECTIONS.some(([key])=>opPlanList(plan,key).length>0));}
function opPlanMarkup(plan,failed){
 if(failed==='unsupported')return '<p class="op-notice">The installed containerlab cannot show what Apply will change; the command runs without a plan.</p>';
 if(failed||!plan||typeof plan!=='object')return '';
 const reasons=plan.reasons&&typeof plan.reasons==='object'?plan.reasons:{},limits=plan.limits&&typeof plan.limits==='object'?plan.limits:{};
 const lines=plan.deploys_lab===true?'<p>The lab is not running: Apply deploys the whole topology.</p>':'';
 if(!opPlanChanges(plan))return '<p class="op-plan-empty">Nothing to apply: the running lab already matches its topology file.</p>';
 return `<div class="op-plan" id="op-plan">${lines}${OP_PLAN_SECTIONS.map(([key,heading,note])=>{
  const names=opPlanList(plan,key);if(!names.length)return '';
  const withReason=key==='restarted'||key==='recreated';
  return `<h4>${esc(heading)} (${names.length})</h4>${note?`<p class="form-help">${esc(note)}</p>`:''}<ul>${names.map(n=>`<li>${esc(n)}${withReason&&reasons[n]?` <small class="op-plan-reason">· ${esc(reasons[n])}</small>`:''}${withReason&&limits[n]?`<br><small class="op-plan-reason">${esc(limits[n])}</small>`:''}</li>`).join('')}</ul>`;
 }).join('')}</div>`;
}
// The devices whose configuration a restart or a recreation loses (the manager lists them in `backup_first`): said above the plan.
function opBackupFirstMarkup(names){
 const list=Array.isArray(names)?names.map(String).filter(Boolean):[];
 return list.length?`<p class="op-notice" id="op-backup-first">Back up these devices first: ${esc(list.join(', '))} — their configuration is lost when they restart or are recreated. Save (lab header) or Back up configuration keeps it.</p>`:'';
}
// "r3 to create · r2 to recreate · 1 link to connect": the banner's detail line and the Deployment details line.
function opPlanSummary(plan){
 const part=(names,verb)=>names.length?(names.length<=2?names.join(', ')+' to '+verb:names.length+' devices to '+verb):'';
 const count=(names,one,many)=>names.length?names.length+' '+(names.length===1?one:many):'';
 return [part(opPlanList(plan,'added'),'create'),part(opPlanList(plan,'recreated'),'recreate'),part(opPlanList(plan,'started'),'start'),part(opPlanList(plan,'restarted'),'restart'),part(opPlanList(plan,'removed'),'remove'),count(opPlanList(plan,'links_added'),'link to connect','links to connect'),count(opPlanList(plan,'endpoints_removed'),'link end to disconnect','link ends to disconnect'),plan&&plan.deploys_lab===true?'the lab is not running':''].filter(Boolean).join(' · ');
}
function opHash(text){let hash=0;const s=String(text);for(let i=0;i<s.length;i++)hash=(hash*31+s.charCodeAt(i))>>>0;return hash.toString(36);}
// A dismissed pending-changes notice stays dismissed while the plan is the same and comes back when it differs: the identity is a
// digest of the canonical plan (every list sorted, the reasons' keys sorted); the check time is not part of it.
function opPlanIdentity(plan){
 const reasons=plan&&plan.reasons&&typeof plan.reasons==='object'?plan.reasons:{};
 const canon={deploys_lab:!!(plan&&plan.deploys_lab),...Object.fromEntries(OP_PLAN_SECTIONS.map(([key])=>[key,[...opPlanList(plan,key)].sort()])),reasons:Object.fromEntries(Object.keys(reasons).sort().map(k=>[k,String(reasons[k])]))};
 return opHash(JSON.stringify(canon));
}
// Run with options (C05 4.5): the controls of one review. Only the controls the installed command has; none at all → ''.
const OP_RUN_KEYS=['nodes','max_workers','skip_post_deploy','keep_mgmt_net','graceful'];
const OP_RUN_LIMIT_SECONDS=1250;
function opPlainOptions(options){const plain={...(options||{})};for(const key of OP_RUN_KEYS)delete plain[key];return plain;}
function opMaxWorkersProblem(value){
 const text=String(value??'').trim();if(!text)return '';
 return /^[1-9]\d{0,2}$/.test(text)&&Number(text)<=64?'':'Max workers must be a whole number from 1 to 64.';
}
// The request a form describes: the plain options (no chosen devices) or the chosen devices without Clean up (the two cannot combine).
function opMergeOptions(action,plain,form){
 const options={...(plain||{})};
 const nodes=Array.isArray(form.nodes)?form.nodes:[];
 if(nodes.length){options.nodes=nodes;delete options.cleanup;}
 else if(action==='destroy')Object.assign(options,opDestroyOptions());
 if(!opMaxWorkersProblem(form.maxWorkers)&&String(form.maxWorkers??'').trim())options.max_workers=Number(String(form.maxWorkers).trim());
 if(form.skip)options.skip_post_deploy=true;
 if(form.keep)options.keep_mgmt_net=true;
 if(form.graceful)options.graceful=true;
 return options;
}
function opGracefulNotice(options,count){
 const workers=options&&options.max_workers;
 if(!options||!options.graceful||!Number.isInteger(workers)||!(count>workers))return '';
 const seconds=120*Math.ceil(count/workers);
 return seconds>OP_RUN_LIMIT_SECONDS?`With these options the command may take longer than the manager waits for it (about ${Math.ceil(seconds/60)} minutes); choose more workers or leave Graceful stop off.`:'';
}
const OP_APPLY_RECREATE_HELP='Apply may also recreate the neighbours of a re-created device when their kind cannot add links live; the review lists them.';
function opOptionsForm(action,caps,lab,options={},open=false){
 const cap=caps&&caps.actions&&caps.actions[action];if(!cap)return '';
 const devices=(lab&&lab.nodes||[]).map(n=>({name:n.definition_node||n.short_name||n.name,label:n.short_name||n.definition_node||n.name}));
 const chosen=Array.isArray(options.nodes)?options.nodes:[];
 const parts=[];
 if(['deploy','destroy','save'].includes(action)&&cap.node_filter===true&&devices.length&&(action!=='deploy'||lab?.deployment?.status==='Not deployed')){
  const help={deploy:'Only possible before the lab is deployed; add the rest later with Apply topology changes.',destroy:'The devices you leave out keep running; the lab folder is kept. '+OP_APPLY_RECREATE_HELP,save:'Only the chosen devices save their configuration.'}[action];
  parts.push(`<fieldset class="op-opt-devices"><legend>Choose devices</legend>${devices.map((d,i)=>`<label class="checkbox-label" for="op-opt-node-${i}"><input type="checkbox" id="op-opt-node-${i}" data-opt-node="${esc(d.name)}" ${chosen.includes(d.name)?'checked':''}> ${esc(d.label)}</label>`).join('')}<p class="form-help">${esc(help)}</p></fieldset>`);
 }
 if(['deploy','redeploy','destroy'].includes(action)&&cap.max_workers===true)parts.push(`<div class="op-opt-row"><label for="op-opt-workers">Max workers</label><input type="number" id="op-opt-workers" min="1" max="64" step="1" inputmode="numeric" value="${Number.isInteger(options.max_workers)?options.max_workers:''}"><p class="form-help">How many devices containerlab creates at once. Leave empty for containerlab's default; 1 or 2 spares memory when devices are VMs.</p></div>`);
 if(['deploy','redeploy'].includes(action)&&cap.skip_post_deploy===true)parts.push(`<label class="checkbox-label" for="op-opt-skip"><input type="checkbox" id="op-opt-skip" ${options.skip_post_deploy?'checked':''}> Skip post-deploy actions</label>`);
 if(['redeploy','destroy'].includes(action)&&cap.keep_mgmt_net===true)parts.push(`<label class="checkbox-label" for="op-opt-keepnet"><input type="checkbox" id="op-opt-keepnet" ${options.keep_mgmt_net?'checked':''}> Keep the management network</label>`);
 if(['redeploy','destroy'].includes(action)&&cap.graceful===true)parts.push(`<label class="checkbox-label" for="op-opt-graceful"><input type="checkbox" id="op-opt-graceful" ${options.graceful?'checked':''}> Graceful stop</label><p class="form-help">Asks each device to shut down before removing it. A device that ignores the request is removed after two minutes, and with several devices the waits add up.</p>`);
 if(!parts.length)return '';
 return `<details class="op-options" id="op-run-options" ${open?'open':''}><summary>Run with options</summary><fieldset class="op-options-set" id="op-options-set">${parts.join('')}</fieldset><p class="form-help" id="op-options-status" role="status" aria-live="polite"></p></details>`;
}
function opReadForm(root){
 const all=selector=>[...root.querySelectorAll(selector)];
 const one=selector=>root.querySelector(selector);
 return {nodes:all('[data-opt-node]').filter(i=>i.checked).map(i=>i.dataset.optNode),maxWorkers:(one('#op-opt-workers')||{}).value||'',skip:!!(one('#op-opt-skip')||{}).checked,keep:!!(one('#op-opt-keepnet')||{}).checked,graceful:!!(one('#op-opt-graceful')||{}).checked};
}
// Every change of an option previews the exact request again (the review is the preview of that request, and the helper's digest binds it).
// The fold is disabled with "Checking…" meanwhile; each preview carries a sequence number (opPreviewSeq) and an older answer is dropped.
async function opOptionsChanged(dialog,request,opener,plain,target){
 const error=dialog.querySelector('.form-error'),set=dialog.querySelector('#op-options-set'),status=dialog.querySelector('#op-options-status'),confirm=dialog.querySelector('#op-confirm');
 const form=opReadForm(dialog),problem=opMaxWorkersProblem(form.maxWorkers);
 if(problem){if(error)error.textContent=problem;if(confirm){confirm.disabled=true;confirm.title='Fix the options above first';}return;}
 if(error)error.textContent='';
 // The old Confirm still holds the previous preview's token: it stays off until the new preview has replaced the dialog.
 if(confirm){confirm.disabled=true;confirm.title='Checking the new options…';}
 if(set)set.disabled=true;if(status)status.textContent='Checking…';
 try{await opReview({...request,options:opMergeOptions(request.action,plain,form)},opener,{keepOptionsOpen:true,focusId:target&&target.id||'',plain});}
 catch(e){
  if(set)set.disabled=false;if(status)status.textContent='';
  if(error)error.textContent=e.message;
  if(confirm){confirm.disabled=true;confirm.title='The options above were not accepted';}
 }
}
let opPreviewSeq=0;
async function opReview(request,opener,extra={}){
 const withOptions=['deploy','redeploy','destroy','save'].includes(request.action);
 // The fold needs the installed command's flags: the capabilities are read before the review, also when it opens from Start lab.
 if(withOptions&&!extra.keepOptionsOpen){try{await opCapabilities();}catch{/* the fold stays absent; the review still works */}}
 const seq=++opPreviewSeq;
 const value=await json('/operations/preview','POST',request);
 if(seq!==opPreviewSeq)return null;
 // The helper's plan carries no lab id; the request does.
 const labId=request.lab_id||value.lab_id||'';
 const label=opLabels[value.action]||value.action,copy=opReviewCopy[value.action]||{title:()=>label+'?',body:'',confirm:label};
 const lab=typeof current==='function'&&labId&&labId===activeId?current():null;
 const labOf=(state.labs||[]).find(l=>l.id===labId)||lab||null;
 const cleanup=!!request.options?.cleanup;
 const chosen=Array.isArray(request.options?.nodes)?request.options.nodes.map(String):[];
 const chosenText=typeof statusNodeNames==='function'?statusNodeNames(chosen):chosen.join(', ');
 const shownName=value.name||opName(lab)||'this lab';
 let title=typeof copy.title==='function'?copy.title(shownName,value):copy.title;
 let body=(typeof copy.body==='function'?copy.body(value):copy.body)+(cleanup&&copy.cleanup?copy.cleanup:'');
 if(chosen.length){
  if(value.action==='destroy'){title=`Destroy ${chosenText} in ${shownName}?`;body='The chosen devices are removed from the VM; the other devices and the lab folder stay. Configuration changes you have not saved on them are lost. Your saves, lab states and backups remain.';}
  if(value.action==='save'){
   title=chosen.length===1?`Save ${chosenText}'s running configuration as its startup configuration on the VM?`:`Save the configuration of ${chosenText} on the VM?`;
   body=(chosen.length===1?'containerlab save --node-filter writes it':'containerlab save --node-filter writes each of them')+'. This is separate from Save in the lab’s header and from the manager’s backups.';
  }
  if(value.action==='deploy'){title=`Start ${chosenText} in ${shownName}?`;body='Creates and starts only the chosen devices, as the topology file describes them. Add the rest later with Apply topology changes.';}
 }
 const technicalWarnings=value.warnings.filter(w=>/cleanup/i.test(w)),warnings=value.warnings.filter(w=>!technicalWarnings.includes(w));
 const disruptive=opDisruptive.includes(value.action);
 const isNode=opNodeActions.includes(value.action);
 // The apply review's plan: known, unknown (the installed containerlab cannot show it) or failed (its dry run could not read the file).
 const planKnown=value.action==='apply'&&!!value.plan&&typeof value.plan==='object'&&!value.plan_failed;
 const planEmpty=planKnown&&!opPlanChanges(value.plan);
 // Start lab (deploy) is the everyday, non-destructive action: its review shows the command plainly
 // instead of behind a fold, and skips the generic "this is checked again" caption other reviews keep.
 const plain=value.action==='deploy';
 // create's optional map file (an upload's saved layout) is written next to the topology; named here
 // so the student sees exactly what lands on the VM, whether or not it replaces one already there.
 const mapLine=value.action==='create'&&typeof request.options?.annotations==='string'?`<p>Saved map: <code>${esc((value.path||'').split('/').pop()+'.annotations.json')}</code>${warnings.some(w=>/Replaces the existing map file/.test(w))?' — replaces the existing map file (a recovery copy is kept)':' will be written next to the topology'}</p>`:'';
 // Only a real command (containerlab's argv or the reviewed steps) is shown; actions without one (create, publish,
 // revise, delete) have nothing to print, and with no devices or warnings either the section is left out.
 const command=(value.steps?.length?value.steps:[value.argv]).filter(a=>Array.isArray(a)&&a.length).map(a=>a.map(v=>JSON.stringify(v)).join(' ')).join('\n');
 const commandBlock=`${value.affected.length?`<h4>Devices</h4><ul>${value.affected.map(n=>`<li>${esc(n.name)} · ${esc(n.state)}</li>`).join('')}</ul>`:''}${command?`<h4>Command run on the VM</h4><pre class="op-output">${esc(command)}</pre>`:''}${technicalWarnings.map(w=>`<p class="op-notice">${esc(w)}</p>`).join('')}`;
 const images=Array.isArray(value.images)?value.images.filter(i=>i&&typeof i.reference==='string'):[];
 const imageBlock=images.length?`<p class="form-help" id="op-review-images-status" role="status" aria-live="polite">Checking images…</p><details open class="op-images" id="op-review-images-section" hidden><summary>Images needing attention</summary><p class="form-help" id="op-review-images-fix" hidden></p><ul id="op-review-images"></ul></details>`:'';
 const keptShort=Object.fromEntries((labOf&&labOf.nodes||[]).map(n=>[n.name,n.short_name||n.definition_node||n.name]));
 const kept=Array.isArray(value.kept)?value.kept.map(k=>keptShort[String(k)]||String(k)):[];
 const keptLine=kept.length&&(value.action==='destroy'||value.action==='save')?`<p class="op-kept">${value.action==='destroy'?'Left running':'Not saved'}: ${esc(kept.join(', '))}</p>`:'';
 const affectedVerb={'restart-node':'restarted','start-node':'started','stop-node':'stopped'}[value.action];
 const affectedLine=copy.readonly||copy.quiet||value.action==='deploy'?'':isNode?`<p>1 device affected: ${esc(value.node_label||'')} (${esc(value.affected[0]?.name||'')}, ${esc(value.affected[0]?.state||'')}). The other devices of ${esc(value.name)} are not ${affectedVerb}.</p>`:planKnown?'':`<p>${value.affected.length} running ${value.affected.length===1?'device':'devices'} affected</p>`;
 const plainOptions=extra.plain||opPlainOptions(request.options);
 const fold=withOptions?opOptionsForm(value.action,opCaps,labOf,request.options||{},!!extra.keepOptionsOpen):'';
 const deviceCount=chosen.length||(labOf&&labOf.nodes?labOf.nodes.length:value.affected.length);
 const graceful=opGracefulNotice(request.options,deviceCount);
 const confirmLabel=planEmpty||value.plan_failed==='error'?'Apply anyway':value.action==='destroy'&&chosen.length?`Destroy ${chosenText}`:copy.confirm||label;
 const confirmClass=planEmpty?'secondary':copy.danger||value.plan_failed==='error'?'danger':'primary';
 const generic=disruptive&&!planEmpty;
 const dialog=opDialog('operation-review',title,`${copy.hideName?'':`<p><strong>${esc(value.name)}</strong></p><p class="op-path">${esc(value.path||'All labs on the VM')}</p>`}
 ${warnings.map(w=>`<p class="op-notice">${esc(w)}</p>`).join('')}
 ${value.action==='apply'?opBackupFirstMarkup(value.backup_first)+opPlanMarkup(value.plan,value.plan_failed):''}
 <p>${esc(body)}</p>
 ${fold}
 ${graceful?`<p class="op-notice" id="op-graceful-notice">${esc(graceful)}</p>`:''}
 ${imageBlock}
 ${mapLine}
 ${generic&&!['destroy',...opNodeActions].includes(value.action)?'<p>Configuration changes you have not saved are lost.</p>':''}
 ${opSaveLine(lab,value)}
 ${generic&&!['restart',...opNodeActions].includes(value.action)?'<p class="op-notice">Open CLI sessions to this lab will disconnect.</p>':''}
 ${affectedLine}
 ${keptLine}
 ${plain||!commandBlock?commandBlock:`<details><summary>Technical details</summary>${commandBlock}</details>`}
 ${copy.quiet&&typeof request.options?.text==='string'?`<details ${value.diff?'':'open'}><summary>Topology that will be saved (YAML)</summary><pre class="op-output" id="op-review-yaml">${esc(request.options.text)}</pre></details>`:''}
 ${value.diff?`<details open><summary>Topology file changes</summary><pre class="op-output">${esc(value.diff)}</pre></details>`:''}
 ${plain?'':'<p class="form-help">Runs on the lab VM. If the lab changes before you confirm, this check is repeated.</p>'}
 <div class="dialog-actions"><button class="button secondary" id="op-cancel">Cancel</button>${lab&&lab.git_binding&&disruptive&&typeof gitSaveProgress==='function'?'<button class="button secondary" id="op-save-first">Save first</button>':''}<button class="button ${confirmClass}" id="op-confirm">${esc(confirmLabel)}</button></div>`,opener);
 $('op-cancel').onclick=()=>dialog.close();
 opReviewImages(dialog,images);
 const foldElement=dialog.querySelector('#op-run-options');
 if(foldElement&&typeof foldElement.addEventListener==='function')foldElement.addEventListener('change',event=>{opOptionsChanged(dialog,request,opener,plainOptions,event.target);});
 if(extra.focusId){const back=dialog.querySelector('#'+extra.focusId);if(back&&typeof back.focus==='function')back.focus();}
 if($('op-save-first'))$('op-save-first').onclick=()=>{dialog.close();opTask(null,gitSaveProgress);};
 $('op-confirm').onclick=()=>{if($('op-confirm').disabled)return undefined;return opTask(dialog,async()=>{
  const job=await json('/operations/confirm','POST',{token:value.token});dialog.close();
  if(typeof rememberJobRequest==='function')rememberJobRequest(job.id,{...request,lab_id:request.lab_id||labId});
  if(typeof opJobStarted==='function')opJobStarted(job);
  if(['start-node','stop-node'].includes(value.action))opNodeJobsSeen.add(job.id);
  // The file has been chosen and the operation runs: the file dialogs are done, and the folder browser
  // must not stay open over the lab page that now reports how the operation goes.
  for(const id of ['op-editor','op-browser'])if($(id)?.open)$(id).close();
  if(typeof selectLab==='function'&&labId&&labId!==activeId&&(state.labs||[]).some(l=>l.id===labId))selectLab(labId);
  // The job exists: a state refresh that fails must not keep its output (and its outcome) from being followed.
  try{await refresh();}catch{}
  // Starting a lab opens its live output right away — no second click for "View output" — but a
  // student who deliberately closes it is not interrupted again by the same launch.
  if(plain&&!chosen.length){await opShowJob(job.id,{auto:true});return;}
  // Lifecycle actions on the open lab report through the header and the banner ([View output]);
  // result-bearing actions open their output right away. A toast names the device, never the bare lab-wide verb.
  if(opLifecycle.includes(value.action)&&labId&&labId===activeId&&typeof renderLabBanner==='function'){
   const named=(value.action==='start-node'||value.action==='stop-node'||chosen.length)&&typeof operationLabel==='function'?operationLabel(value.action,{...job,node_label:job.node_label||value.node_label,nodes:job.nodes||chosen}):label;
   notify(named+'…');return;
  }
  await opShowJob(job.id);
 });};
 return dialog;
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
  rows.push({topology:n.absLabPath||n.labPath||label['clab-topo-file']||'',lab:n.lab_name||lab,node:n.name,kind:n.kind||'',image:n.image||'',state:[n.state||n.status||'unknown',n.health_status||n.health||''].filter(v=>typeof v==='string'&&v).join(' · '),ipv4:n.ipv4_address||'',ipv6:n.ipv6_address||'',id:typeof n.container_id==='string'?n.container_id.slice(0,12):'',owner:typeof n.owner==='string'?n.owner:''});
  if(rows.length>=10000)return rows;
 }}return rows;
}
// The six columns of the table keep their names and order (the Lab column included); ID and Owner are appended.
const OP_INSPECT_COLUMNS=[['topology','Topology'],['lab','Lab'],['node','Device'],['kind','Type / image'],['state','State / health'],['ipv4','IPv4 / IPv6'],['id','ID'],['owner','Owner']];
function opInspectionValue(row,key){return key==='kind'?row.kind+' '+row.image:key==='ipv4'?row.ipv4+' '+row.ipv6:String(row[key]??'');}
// Pure: a sorted copy (dir 'asc' or 'desc'; anything else keeps the order given), numbers compared as numbers.
function opInspectionSort(rows,key,dir){
 const list=rows.slice();if(!key||(dir!=='asc'&&dir!=='desc'))return list;
 const sign=dir==='desc'?-1:1;
 return list.map((row,index)=>({row,index})).sort((a,b)=>sign*opInspectionValue(a.row,key).localeCompare(opInspectionValue(b.row,key),undefined,{numeric:true,sensitivity:'base'})||a.index-b.index).map(x=>x.row);
}
// Pure: a case-insensitive substring over every column, the Lab included. No wildcard grammar.
function opInspectionFilter(rows,text){
 const needle=String(text||'').trim().toLowerCase();if(!needle)return rows;
 return rows.filter(row=>OP_INSPECT_COLUMNS.map(([key])=>opInspectionValue(row,key)).join(' ').toLowerCase().includes(needle));
}
function opInspectionIsRunning(row){return /^running\b/i.test(String(row&&row.state||''));}
// Counts only the running rows: a stopped or exited container is listed but is not a running device.
function opInspectionCaption(shown,all){
 const n=shown.filter(opInspectionIsRunning).length,m=all.filter(opInspectionIsRunning).length;
 return (n===m?String(m):n+' of '+m)+' running '+(m===1?'device':'devices');
}
function opInspectionHead(view){
 return '<tr>'+OP_INSPECT_COLUMNS.map(([key,label])=>{const sorted=view.key===key&&view.dir;return `<th scope="col" aria-sort="${sorted==='asc'?'ascending':sorted==='desc'?'descending':'none'}"><button type="button" class="op-sort" data-op-sort="${key}">${label}</button></th>`;}).join('')+'</tr>';
}
function opInspectionBody(rows){
 if(!rows.length)return `<tr><td colspan="${OP_INSPECT_COLUMNS.length}" class="op-inspection-empty">No device matches.</td></tr>`;
 return rows.map(r=>`<tr><td>${esc(r.topology)||'—'}</td><td>${esc(r.lab)}</td><td>${esc(r.node)}</td><td>${esc(r.kind)}<small>${esc(r.image)}</small></td><td>${esc(r.state)}</td><td>${esc(r.ipv4)}<small>${esc(r.ipv6)}</small></td><td class="mono">${esc(r.id)||'—'}</td><td>${esc(r.owner)||'—'}</td></tr>`).join('');
}
// view: {key, dir, filter} kept by the dialog that shows the table, so a repeated render keeps the person's sort and filter.
function opInspectionTable(rows,view={}){
 const shown=opInspectionSort(opInspectionFilter(rows,view.filter),view.key,view.dir);
 return `<div class="op-inspection-tools"><label for="op-inspect-filter">Filter devices</label><input type="search" id="op-inspect-filter" value="${esc(view.filter||'')}" autocomplete="off"></div><div class="op-inspection"><table><caption>${opInspectionCaption(shown,rows)}</caption><thead>${opInspectionHead(view)}</thead><tbody>${opInspectionBody(shown)}</tbody></table></div>`;
}
// Wire the filter box and the header buttons of a rendered table; only the table's own parts are redrawn, so typing keeps focus.
function opInspectionBind(root,rows,view){
 const filter=root&&root.querySelector?root.querySelector('#op-inspect-filter'):null,table=root&&root.querySelector?root.querySelector('table'):null;
 if(!filter||!table)return;
 const redraw=refocus=>{
  const shown=opInspectionSort(opInspectionFilter(rows,view.filter),view.key,view.dir);
  table.innerHTML=`<caption>${opInspectionCaption(shown,rows)}</caption><thead>${opInspectionHead(view)}</thead><tbody>${opInspectionBody(shown)}</tbody>`;
  if(refocus){const back=table.querySelector('[data-op-sort="'+refocus+'"]');if(back&&typeof back.focus==='function')back.focus();}
 };
 filter.addEventListener('input',()=>{view.filter=filter.value;redraw('');});
 table.addEventListener('click',event=>{
  const button=event.target&&event.target.closest?event.target.closest('[data-op-sort]'):null;if(!button)return;
  const key=button.dataset.opSort;
  if(view.key!==key){view.key=key;view.dir='asc';}else if(view.dir==='asc')view.dir='desc';else{view.key='';view.dir='';}
  redraw(key);
 });
}
// The outcome is what a reader looks for first: a large green (or red) banner names
// the action, the lab and the result before the raw command output; the exit code is a detail.
// A failure a student can act on, in words. Image references are shown as the topology names them
// (containerlab prints the registry it tried in front).
function opJobHint(job){
 if(!['failed','interrupted'].includes(job.status))return '';
 const images=[...new Set([...String(job.output||'').matchAll(/Failed to pull image\s+image=(\S+)/g)].map(m=>m[1].replace(/^docker\.io\/(library\/)?/,'')))];
 if(images.length)return 'The VM does not have '+(images.length>1?'these images':'this image')+' and could not download '+(images.length>1?'them':'it')+': '+images.join(', ')+'. Check the image name on the devices that use '+(images.length>1?'them':'it')+' (open the topology file and choose Edit topology…, then the device\'s Image field), or ask for the image to be installed on the VM.';
 return '';
}
// The imperative name of a job, wherever a job record is at hand: Start/Stop name their one device ("Stop ceos", never the bare
// "Stop device" a letter away from "Stop devices"), and a job limited to chosen devices (its public `nodes`) names them
// ("Destroy ceos"). Restart device keeps its table word. Pure.
const OP_PAST={'start-node':'started','stop-node':'stopped',destroy:'destroyed',save:'saved',deploy:'started'};
function opJobDevices(job){
 const action=job?.action;
 if((action==='start-node'||action==='stop-node')&&job.node_label)return String(job.node_label);
 if(['destroy','save','deploy'].includes(action)&&typeof statusJobNodes==='function'){const names=statusJobNodes(job);if(names.length)return statusNodeNames(names);}
 return '';
}
function opJobLabel(job){
 const who=opJobDevices(job),action=job?.action;
 if(!who)return opLabels[action]||action;
 return {'start-node':'Start','stop-node':'Stop',destroy:'Destroy',save:'Save',deploy:'Start'}[action]+' '+who;
}
function opJobBanner(job){
 const who=opJobDevices(job),label=opJobLabel(job),done=job.status==='succeeded',failed=['failed','interrupted'].includes(job.status),stopped=job.status==='cancelled';
 const detail=[job.name,job.node_label,job.message].filter(Boolean).join(' · ');
 if(who){
  const exit2=job.exit_code===null||job.exit_code===undefined?'':'Exit code '+job.exit_code;
  return {tone:done?'good':failed?'bad':stopped?'warn':'running',title:done?`✔ ${who} ${OP_PAST[job.action]}`:failed?`✖ ${label} ${job.status==='interrupted'?'interrupted':'failed'}`:stopped?`■ ${label} ended early: you stopped it`:`${typeof operationLabel==='function'?operationLabel(job.action,job):label}…`,detail,exit:exit2,...(opJobHint(job)?{hint:opJobHint(job)}:{})};
 }
 const exit=job.exit_code===null||job.exit_code===undefined?'':'Exit code '+job.exit_code;
 return {tone:done?'good':failed?'bad':stopped?'warn':'running',title:done?`✔ ${label} succeeded`:failed?`✖ ${label} ${job.status}`:stopped?`■ ${label} ended early: you stopped it`:`${label} ${job.status}…`,detail,exit,...(opJobHint(job)?{hint:opJobHint(job)}:{})};
}
// The Stop block of the output window. Pure: which of none | ask | asking | stopping applies. Only the actions that die with the
// helper's channel (STATUS_STOPPABLE, status.js) are ever offered, and only while the job is queued or running.
function opStopMode(job,asked,requested){
 const list=typeof STATUS_STOPPABLE!=='undefined'?STATUS_STOPPABLE:[];
 if(!job||!list.includes(job.action)||!['queued','running'].includes(job.status))return 'none';
 if(job.cancel_requested||requested)return 'stopping';
 return asked?'asking':'ask';
}
function opStopMarkup(mode,job){
 if(mode==='ask')return '<button type="button" class="button secondary small" id="op-stop-ask">Stop this operation…</button>';
 if(mode==='asking'){
  const label=opJobLabel(job),question=typeof statusStopQuestion==='function'?statusStopQuestion(job.action,label,job.name||'the lab'):`End the running command (${label}) on ${job.name||'the lab'}?`;
  return `<div role="group" aria-labelledby="op-stop-question"><p id="op-stop-question">${esc(question)}</p><div class="actions"><button type="button" class="button secondary small" id="op-stop-keep">Keep running</button><button type="button" class="button danger small" id="op-stop-confirm">Stop</button></div></div>`;
 }
 if(mode==='stopping')return '<p id="op-stop-status" role="status" tabindex="-1">Stopping… the manager has asked the lab VM to end the command.</p>';
 return '';
}
// The Copy output button: a click of its own (this page may not load shell.js), the Copied flip and announcement from
// clipboard.js (copyFeedback), and nothing to copy while the output is still "Waiting for the VM…".
function opBindCopyOutput(getOutput,id='op-copy-output'){
 const button=$(id);if(!button)return null;
 button.onclick=async()=>{
  const text=getOutput();if(!text||typeof copyText!=='function')return;
  const ok=await copyText(text,button);
  if(typeof copyFeedback==='function')copyFeedback(button,ok);
 };
 return button;
}
// Auto-opened right after a confirmed launch (Start lab today), with no second "View output" click; a
// student who closes it on purpose does not have it pop back up on the next poll tick — its job id goes
// into opClosedOutputs, and only an auto open ever checks that set. "View output" (no auto option) always
// shows it, however it was closed; a fresh launch is a different job id, so an older closed one never
// holds it back. Moving to another lab closes an auto-opened dialog instead of leaving it open over a lab
// it is not about, and — being closed the same way — it does not come back there on its own either.
const opClosedOutputs=new Set();
async function opShowJob(id,{auto=false,stop=false}={}){
 if(auto&&opClosedOutputs.has(id))return;
 clearTimeout(opOutputTimer);
 const dialog=opDialog('operation-output','Lab operation','<div id="op-job-banner" class="op-banner" tabindex="-1" hidden></div><div id="op-job-stop" class="op-stop" hidden></div>'+(typeof copyText==='function'?'<div class="op-output-tools"><button type="button" id="op-copy-output" class="button ghost small" data-label="Copy output" aria-label="Copy the command output" data-copy-target="op-job-output" disabled>Copy output</button><span class="copy-status" role="status"></span></div>':'')+'<pre class="op-output" id="op-job-output" tabindex="0"></pre><div id="op-job-result"></div>');
 // The sort and filter of a previous inspect run live on the reused dialog: every run starts with a clean view.
 dialog._inspectView={key:'',dir:'',filter:''};
 // Stop: the block is rebuilt only when its mode changes; focus moves only after the person's own action, or when the block they were in goes away.
 let latest=null,asked=stop,requested=false,shownMode='',focusNext=stop?'keep':'',lastOutput='';
 const copyOutputButton=opBindCopyOutput(()=>lastOutput);
 const renderStop=()=>{
  const box=$('op-job-stop');if(!box||!latest)return;
  const mode=opStopMode(latest,asked,requested);
  if(mode!==shownMode){
   const held=typeof document!=='undefined'&&document.activeElement&&typeof box.contains==='function'&&box.contains(document.activeElement);
   shownMode=mode;box.innerHTML=opStopMarkup(mode,latest);box.hidden=mode==='none';
   // A poll that turns the confirmation into Stopping… (the stop was requested elsewhere) removes the button that held focus.
   if(held&&mode==='stopping')focusNext='status';
   if(mode==='none'&&held){const banner=$('op-job-banner');if(banner&&typeof banner.focus==='function')banner.focus();}
   $('op-stop-ask')?.addEventListener('click',()=>{asked=true;focusNext='keep';renderStop();});
   $('op-stop-keep')?.addEventListener('click',()=>{asked=false;focusNext='ask';renderStop();});
   $('op-stop-confirm')?.addEventListener('click',async()=>{
    let sent=false;
    await opTask(dialog,async()=>{await json('/operations/'+id+'/cancel','POST',{});sent=true;});
    if(sent){requested=true;focusNext='status';}else{asked=false;focusNext='ask';}
    renderStop();
   });
  }
  const target={keep:'op-stop-keep',ask:'op-stop-ask',status:'op-stop-status'}[focusNext];
  if(target&&$(target)&&typeof $(target).focus==='function')$(target).focus();
  focusNext='';
 };
 // A page that acts on the outcome (the lab builder's opJobDone) hears it even when this dialog was closed
 // while the job ran; a poll that fails is repeated, because one lost answer must not hide how the job ended.
 let fails=0;const follows=typeof opJobDone==='function';
 const poll=async()=>{
  if(!dialog.open&&!follows)return;
  try{
   const job=await(await api('/operations/'+id)).json();fails=0;
   if(auto&&dialog.open&&job.lab_id&&typeof activeId==='string'&&activeId&&job.lab_id!==activeId)dialog.close();
   if(!dialog.open){if(['queued','running'].includes(job.status))opOutputTimer=setTimeout(poll,1000);else{await refresh();if(follows)opJobDone(job);}return;}
   const heading=dialog.querySelector('h2');if(heading)heading.textContent=opJobLabel(job)+(job.name?' · '+job.name:'');
   const banner=opJobBanner(job),shown=$('op-job-banner');shown.hidden=false;shown.className='op-banner '+banner.tone;shown.innerHTML=`<strong>${esc(banner.title)}</strong><span>${esc(banner.detail)}</span>${banner.exit?`<small class="${job.exit_code?'op-exit-bad':''}">${esc(banner.exit)}</small>`:''}${banner.hint?`<p class="op-banner-hint">${esc(banner.hint)}</p>`:''}`;
   latest=job;renderStop();
   const pre=$('op-job-output'),follow=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-30;pre.textContent=job.output||'Waiting for the VM…';lastOutput=job.output||'';if(copyOutputButton)copyOutputButton.disabled=!lastOutput;if(follow)pre.scrollTop=pre.scrollHeight;
   const rows=opInspectionRows(job.output||'');
   const inspectAction=['inspect','inspect-all'].includes(job.action);
   dialog.classList.toggle('inspection-dialog',inspectAction);
   const inspected=inspectAction&&job.status==='succeeded'&&rows.length;
   const emptyInspection=inspectAction&&job.status==='succeeded'&&/(^|\n)\s*(?:\[\s*\]|\{\s*\})\s*(?=\n|$)/.test(job.output||'');
   pre.hidden=!!inspected||emptyInspection;
   const inspectView=dialog._inspectView||(dialog._inspectView={key:'',dir:'',filter:''});
   $('op-job-result').innerHTML=(inspected?opInspectionTable(rows,inspectView):emptyInspection?'<p>No labs are running on the VM.</p>':'')+(job.result?.recovery_path?`<p>A recovery copy of the ${job.action==='revise'?'previous version':'deleted file'} was kept at <code>${esc(job.result.recovery_path)}</code>.</p>`:'')+(job.result?.project_path?`<button class="button primary" id="op-open-clone">Choose a topology from the downloaded lab</button>`:'')+(opPublishedPath(job)?(opDeployedSave(job)?opDeployedSaveMarkup(job):`<p>Saved as <code>${esc(opPublishedPath(job))}</code>. It is not running yet.</p>${opOnBuilder()?'<div id="op-published-block"></div>':'<button class="button primary" id="op-open-published">Deploy or add this lab…</button>'}`):'');
   if(inspected)opInspectionBind($('op-job-result'),rows,inspectView);
   if(opPublishedPath(job)&&opOnBuilder()&&!opDeployedSave(job))opRenderPublished(dialog,opPublishedPath(job));
   $('op-open-published')?.addEventListener('click',()=>opTask(dialog,()=>opEdit(opPublishedPath(job))));$('op-back-review')?.addEventListener('click',()=>opBackToReview(job));
   $('op-open-clone')?.addEventListener('click',()=>opBrowse(job.result.project_path));
   if(['queued','running'].includes(job.status))opOutputTimer=setTimeout(poll,1000);else{await refresh();if(typeof opJobDone==='function')opJobDone(job);}
  }catch(e){if(dialog.open)dialog.querySelector('.form-error').textContent=++fails<10?e.message+' Trying again…':e.message;else fails++;if(fails<10)opOutputTimer=setTimeout(poll,3000);else if(typeof opJobLost==='function')opJobLost(id);}
 };dialog.onclose=()=>{opClosedOutputs.add(id);if(!follows)clearTimeout(opOutputTimer);};await poll();
}
// The topology file a finished job left on the VM, to continue with "Deploy or add this lab…": the builder's
// save names it in its result; a created file (typed or uploaded) is the job's own path.
function opPublishedPath(job){if(!job||job.status!=='succeeded')return '';return job.result?.published_path||(job.action==='create'&&/\.ya?ml$/i.test(job.path||'')?job.path:'');}
// The lab builder's own save result offers the next step itself (Add to My labs without starting / Deploy
// now, then Deploy now / Go to My labs) instead of the generic Topology file dialog, which led back here.
// Every other page keeps "Deploy or add this lab…". The builder page is the one that defines builderGo.
function opOnBuilder(){return typeof builderGo==='function';}
function opLabAtPath(path){return (state.labs||[]).find(l=>opPath(l)===path)||null;}
function opPublishedMarkup(path,lab){
 const name=lab?(lab.name||opName(lab)):'';
 return lab
  ?`<p class="op-notice ok" id="op-published-status" tabindex="-1">✓ ${esc(name)} is in My labs. It is not running: adding a lab never starts its devices.</p><div class="actions"><button class="button primary" id="op-published-deploy">Deploy now</button><button class="button secondary" id="op-published-go" data-lab="${esc(lab.id)}">Go to My labs</button></div>`
  :`<p class="form-help">Add it to My labs to keep it with your other labs, or deploy it now (the deploy shows what it will do and asks you to confirm first).</p><div class="actions"><button class="button primary" id="op-published-add">Add to My labs without starting</button><button class="button secondary" id="op-published-deploy">Deploy now</button></div>`;
}
// One request at a time per file: a double click, or a second click while the first still runs, adds nothing twice.
const opPublishBusy=new Set();
function opRenderPublished(dialog,path,focus=false){
 const block=dialog.querySelector('#op-published-block');if(!block)return;
 const lab=opLabAtPath(path);block.innerHTML=opPublishedMarkup(path,lab);
 const guard=fn=>async()=>{if(opPublishBusy.has(path))return;opPublishBusy.add(path);try{await opTask(dialog,fn);}finally{opPublishBusy.delete(path);}};
 // Both the saved lab and its VM file are read fresh: a lab already in My labs for this file is reused, never imported twice.
 const prepare=async()=>{
  let lab=opLabAtPath(path);if(!lab){await refresh();lab=opLabAtPath(path);}
  const source=await json('/operations/read','POST',{path}),parsed=await opParse(path,source.text);
  return {lab,source,parsed};
 };
 block.querySelector('#op-published-add')?.addEventListener('click',guard(async()=>{
  const {lab,source,parsed}=await prepare();
  if(!lab)await opSaveWorkspace(path,source,parsed);
  await refresh();opRenderPublished(dialog,path,true);
 }));
 block.querySelector('#op-published-deploy')?.addEventListener('click',guard(async()=>{
  const {lab,source,parsed}=await prepare();
  const id=await opSaveWorkspace(path,source,parsed,lab?.id||'');
  await refresh();opRenderPublished(dialog,path);
  await opReview({action:'deploy',lab_id:id,path,name:parsed.name});
 }));
 // My labs is the list: drop the resume-this-lab hint opSaveWorkspace left, or / would reopen the lab page.
 block.querySelector('#op-published-go')?.addEventListener('click',()=>{try{sessionStorage.removeItem('activeLab');}catch{}location.assign('/');});
 if(focus)block.querySelector('#op-published-status')?.focus();
}
async function opHistory(labId=''){
 const jobs=await(await api('/operations')).json();
 const lab=labId?(state.labs||[]).find(l=>l.id===labId):null;
 const dialog=opDialog('operation-history','Operation history'+(lab?' · '+lab.name:''),`<p>Past lab operations and their output are kept on this manager.</p><div class="op-history">${jobs.filter(j=>!labId||j.lab_id===labId).map(j=>`<button class="button secondary" data-job="${esc(j.id)}"><strong>${esc(j.name)}${j.node_label&&!opJobDevices(j)?' · '+esc(j.node_label):''} · ${esc(opJobLabel(j))}</strong><small>${esc(opStatusWord(j.status))} · ${esc(opWhen(j.created))}</small></button>`).join('')||'<p>No lab operations yet. Starting, stopping or redeploying a lab shows up here.</p>'}</div>`);
 dialog.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>opShowJob(b.dataset.job));
}
// Deploy lab keeps the manager in step with the VM: the workspace (nodes, map and VM
// source link) is saved before the command runs, so the lab is in My labs at once
// and NOS logins are verified as soon as its containers start. Nothing to import.
// The VS Code extension keeps a topology's node positions and styling in <file>.annotations.json
// beside it. It is read with the topology so the preview and the saved workspace start from that
// layout instead of the default grid; a missing or unreadable file means the grid.
async function opReadAnnotations(path){
 if(!path)return '';
 try{return (await json('/operations/read','POST',{path:path+'.annotations.json'})).text||'';}catch{return '';}
}
// annotations: the map text to use (an upload's chosen map file); otherwise the VM file beside the topology.
async function opParse(path,text,annotations){
 if(annotations===undefined)annotations=await opReadAnnotations(path);
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
 activeId=id;try{sessionStorage.setItem('activeLab',id);}catch{/* blocked site data: the open lab is carried by activeId */}
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
function opBuilderOpen(values){if(location.pathname==='/static/lab-builder.html'&&typeof builderGo==='function')builderGo(Object.fromEntries(Object.entries(values).filter(([,v])=>v)));else location.assign(opBuilderUrl(values));}
// Returning from the lab builder: the VM topology file dialog the student left is remembered here, so
// the builder's "← My labs" link and the browser Back button — both a normal navigation back to this
// page — land on that dialog again, not only Home. A direct visit to the builder (the Build card's
// "Open the lab builder") sets no marker, so it still returns to My labs exactly as before. Only a VM
// file opens "Edit topology…" today (an upload has no such button, since it has no VM path yet
// to hand the builder); the marker is 'vm'-only until an upload gains that handoff. Consumed once, by
// this page's own load-time wiring below.
const OP_RETURN_KEY='op-return';
function opRemember(kind,values){try{sessionStorage.setItem(OP_RETURN_KEY,JSON.stringify({kind,...values}));}catch{/* private window or blocked storage: only this convenience is lost */}}
function opConsumeReturn(){
 let raw=null;try{raw=sessionStorage.getItem(OP_RETURN_KEY);sessionStorage.removeItem(OP_RETURN_KEY);}catch{return null;}
 if(!raw)return null;
 let value;try{value=JSON.parse(raw);}catch{return null;}
 return value&&typeof value==='object'&&value.kind==='vm'?value:null;
}
// The remembered VM file is reread fresh, so a save made in the builder shows up.
function opReopenReturn(value){
 if(!value)return;
 if(value.kind==='vm'&&value.path)return opEdit(value.path);
}
function openDeploy(){return opTask(null,()=>opBrowse());}
function opNewTab(values){const url='/static/workspace.html#'+new URLSearchParams(values);if(!window.open(url,'_blank'))opDialog('op-open-tab','Open the CLI launcher',`<p>Your browser blocked the new tab. Use this button instead:</p><a class="button primary" href="${esc(url)}" target="_blank" rel="opener">Open CLI launcher <span aria-hidden="true">↗</span></a>`);}
function opTopologyEntries(entries){return entries.filter(entry=>entry.directory||/\.clab\.ya?ml$/i.test(entry.name));}
// Sizes in the file tree and the images table: Docker-style decimal units, one decimal.
function opSize(bytes){
 const n=Number(bytes);if(!Number.isFinite(n)||n<0)return '';
 if(n<1000)return Math.round(n)+' B';
 const units=['kB','MB','GB','TB'];let size=n/1000,i=0;
 while(size>=1000&&i<units.length-1){size/=1000;i++;}
 return size.toFixed(1)+' '+units[i];
}
// Files mode (C03 4.4): the dialog opened for a lab on a VM whose helper reports `diagnostics`. It is a property of the dialog:
// every listing it makes sends files:true with the lab, keeps the title and help line, and lists the files the manager can show,
// so the node folders under clab-<lab>/ and their startup configurations are reachable. Topology files first.
function opFileEntries(entries){
 const rank=entry=>entry.kind==='topology'||(!entry.kind&&!entry.directory&&/\.clab\.ya?ml$/i.test(entry.name))?0:entry.directory?1:2;
 return entries.map((entry,index)=>({entry,index})).sort((a,b)=>rank(a.entry)-rank(b.entry)||a.index-b.index).map(x=>x.entry);
}
function opFileLabel(entry){return '◇ '+entry.name+(typeof entry.size==='number'?' · '+opSize(entry.size):'');}
// path: the folder to open; labId: opened as "Lab files · <lab>" starting in the lab's own folder (options.root: at the roots instead).
async function opBrowse(path='',labId='',options={}){
 const lab=labId?(state.labs||[]).find(l=>l.id===labId):null,labPath=opPath(lab);
 if(lab&&!opCaps){try{await opCapabilities();}catch{/* the dialog stays the topology browser */}}
 const files=!!lab&&opCaps?.diagnostics===true;
 // Files mode is bounded to this lab's own folder: no list of all lab folders, and Up stops there (other labs' files would be refused by the viewer).
 const labFolder=files&&labPath.includes('/')?labPath.slice(0,labPath.lastIndexOf('/')):'';
 if(lab&&!path&&!options.root&&labPath)path=labPath.includes('/')?labPath.slice(0,labPath.lastIndexOf('/')):'';
 const listing=folder=>json('/operations/browse','POST',files?{path:folder,files:true,lab_id:labId}:{path:folder});
 const result=await listing(path);
 const dialog=opDialog('op-browser',lab?'Lab files · '+lab.name:'Deploy a new lab',`<p class="op-path">${esc(result.path||'Lab folders on the VM')}</p><div class="actions">${files?'':'<button class="button secondary" id="op-roots">All lab folders</button>'}<button class="button secondary" id="op-up">Up one folder</button><button class="button secondary" id="op-build">Build a lab visually…</button><button class="button secondary" id="op-create">Write a new topology…</button><button class="button secondary" id="op-clone">Download a lab from GitHub…</button><button class="button secondary" id="op-popular">Browse popular labs…</button></div><div class="op-file-tree" id="op-file-tree" aria-label="${files?'Lab files':'Lab topology files'}"></div><p class="form-help">${files?'Files the manager can show (text and configuration files). Other files on the VM are not listed.':'Open a folder and pick a topology file (.clab.yaml) to view or deploy it. Only topology files are listed, up to 500 per folder.'}</p>${lab?'':'<p class="form-help">These are files on the lab VM. Is the topology file on your computer instead? <button type="button" class="link-button" id="op-browse-upload">Upload it from this computer…</button></p>'}`);
 {const upload=$('op-browse-upload');if(upload)upload.onclick=()=>{dialog.close();opUpload();};}
 const addEntries=(container,entries)=>{
  entries=files?opFileEntries(entries):opTopologyEntries(entries);
  if(!entries.length){container.textContent=files?'No files the manager can show in this folder.':'No topology files in this folder.';return;}
  for(const entry of entries){
   if(entry.directory){
    const folder=document.createElement('details'),summary=document.createElement('summary'),children=document.createElement('div');
    summary.textContent=entry.name;children.className='op-tree-children';folder.append(summary,children);container.append(folder);
    let loaded=false,loading=false;
    folder.ontoggle=async()=>{if(!folder.open||loaded||loading)return;loading=true;children.textContent='Loading…';try{const answer=await listing(entry.path);children.replaceChildren();addEntries(children,answer.entries);loaded=true;}catch(e){children.textContent=e.message+' Close and reopen this folder to retry.';}finally{loading=false;}};
   }else{const button=document.createElement('button');button.className='op-tree-file';button.textContent=files?opFileLabel(entry):'◇ '+entry.name;
    const topology=!files||entry.kind==='topology'||(!entry.kind&&/\.clab\.ya?ml$/i.test(entry.name));
    button.onclick=()=>opTask(dialog,()=>topology?opEdit(entry.path,lab?lab.id:''):opView(entry.path,labId));container.append(button);}
  }
 };
 addEntries($('op-file-tree'),result.entries);
 {const roots=$('op-roots');if(roots)roots.onclick=()=>opTask(dialog,()=>opBrowse());}
 {const up=$('op-up');if(files&&labFolder&&result.path===labFolder){up.disabled=true;up.title="This is the lab's folder";}}
 $('op-up').onclick=()=>opTask(dialog,()=>opBrowse(result.parent||'',files?labId:'',{root:!result.parent}));
 $('op-build').onclick=()=>opBuilderOpen({root:opBuilderRoot(result.path,opCaps?.roots)});
 $('op-create').onclick=()=>opEdit('','',(result.path||'/srv/containerlab-node-manager/projects')+'/new-lab.clab.yaml');$('op-clone').onclick=()=>opClone();$('op-popular').onclick=()=>opTask(dialog,()=>opPopular());
 // Listing files does not depend on Containerlab's command help probes. Render
 // immediately; only the optional network controls need capabilities.
 const clone=$('op-clone'),popular=$('op-popular'),help=dialog.querySelector('.form-help');
 clone.disabled=true;popular.disabled=true;
 opCapabilities().then(caps=>{
  if(!clone.isConnected)return;
  clone.disabled=!caps.network||caps.actions?.clone?.available===false;popular.disabled=!caps.network;
  if(!caps.network&&!files)help.textContent+=' Downloading labs from the internet is turned off on this VM. An administrator can enable it (--allow-downloads) in VM setup.';
 }).catch(()=>{
  if(!clone.isConnected)return;
  help.textContent+=' Files are available, but the VM command check failed — open Diagnostics for details. Online downloads stay off.';
 });
}
// A file of the lab's folder that is not a topology (a startup configuration, a map file): read-only, hidden lines said.
// The manager redacts lines with passwords, secrets and SNMP communities and shows at most the last 512 KiB.
async function opView(path,labId){
 const value=await json('/operations/view','POST',{lab_id:labId,path});
 const dialog=opDialog('op-editor','File on the VM',`<p class="op-path">${esc(value.name||path)}</p><p class="form-help">Lines with passwords, secrets or SNMP communities are hidden. This copy is for reading, not for loading onto a device.</p>${value.truncated?'<p class="op-notice">Showing the last 512 KiB of this file.</p>':''}${typeof copyText==='function'?'<div class="op-output-tools"><button type="button" id="op-copy-view" class="button ghost small" data-label="Copy" aria-label="Copy the file text" data-copy-target="op-view-text">Copy</button><span class="copy-status" role="status"></span></div>':''}<label for="op-view-text">File contents</label><textarea class="op-code" id="op-view-text" spellcheck="false" readonly></textarea>`);
 $('op-view-text').value=value.text||'';
 opBindCopyOutput(()=>value.text||'','op-copy-view');
}
// upload: {text, file} for a topology the student chose on their own computer (opUpload); it goes
// through the same review as a topology typed here.
async function opEdit(path,labId='',newPath='',upload=null){
 if(!path)labId='';
 const value=path?await json('/operations/read','POST',{path}):{text:upload?upload.text:'name: new-lab\ntopology:\n  nodes:\n    r1:\n      kind: linux\n      image: alpine:latest\n',path:newPath};
 const isYaml=/\.ya?ml$/i.test(value.path);
 opEditorContext={path:value.path,labId,isNew:!path};
 const dialog=opDialog('op-editor',path?'Topology file':upload?'Uploaded lab file':'New topology file',`${upload?`<p class="op-notice">Read from <strong>${esc(upload.file)}</strong> on this computer. Nothing is on the lab VM yet: <em>Create file on the VM…</em> shows what will be written and asks you to confirm; afterwards you can deploy it.</p>`:''}${upload&&upload.mapNotice?`<p class="op-notice">${esc(upload.mapNotice)}</p>`:''}<label>File location on the VM<input id="op-edit-path" ${path?'readonly':''}></label><label>${isYaml?'Topology (YAML)':'File contents'}<textarea class="op-code" id="op-edit-text" spellcheck="false" ${path||!isYaml?'readonly':''}></textarea></label><p class="form-help">Deploy lab adds this lab to My labs and starts its devices on the VM. Add without starting keeps it in My labs only. Existing files can't be edited as text here — use Edit topology…, or edit them on the VM.</p><div class="actions">${isYaml?'<button class="button secondary" id="op-validate">Preview topology</button>':''}${!path?'<button class="button primary" id="op-save-yaml">Create file on the VM…</button>':''}${path&&isYaml?'<button class="button secondary" id="op-build-edit" title="Devices and links, saved to the lab file on the VM; applying is a separate step">Edit topology…</button><button class="button secondary" id="op-add-project">'+(labId?'Link topology':'Add to My labs without starting')+'</button><button class="button primary" id="op-deploy-project">Deploy lab</button>':''}</div>`);
 $('op-edit-path').value=value.path;$('op-edit-text').value=value.text;
 // Leaving for the builder from a known VM file: remembered so the way back (its "← My labs" link,
 // or the browser Back button) reopens this same dialog with a fresh read, showing any saved edit.
 $('op-build-edit')?.addEventListener('click',()=>{opRemember('vm',{path,name:value.path.split('/').pop()});opBuilderOpen({path,lab:labId});});
 $('op-validate')?.addEventListener('click',()=>opTask(dialog,async()=>{const parsed=await opParse(path,$('op-edit-text').value,upload?upload.annotations||'':undefined);opMapPreview(parsed.drawing,parsed.name,parsed.annotations_used);}));
 $('op-save-yaml')?.addEventListener('click',()=>opTask(dialog,()=>opReview({action:'create',lab_id:labId,path:$('op-edit-path').value,options:{text:$('op-edit-text').value,...(upload&&upload.annotations?{annotations:upload.annotations}:{})}})));
 $('op-add-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  // Always read the actual VM file; unsaved editor contents are not linked/imported.
  const source=await json('/operations/read','POST',{path}),parsed=await opParse(path,source.text);
  const confirm=opDialog('op-add-confirm',labId?'Link lab topology?':`Add ${parsed.name} to My labs?`,`<p>${esc(parsed.name)} · ${parsed.drawing.nodes.length} devices${parsed.annotations_used?' · layout from the saved map file':''}</p><p class="op-path">${esc(path)}</p><p>Adds the lab to My labs and remembers where its topology file is on the VM. No devices are started. Device logins can be imported after the lab is deployed.</p><button class="button primary" id="op-add-confirm-button">${labId?'Link topology':'Add lab'}</button>`);
  $('op-add-confirm-button').onclick=()=>opTask(confirm,async()=>{
   let id=labId;
   if(!id){const lab=await(await api('/lab-definitions',{method:'POST',body:opWorkspaceForm(path,source,parsed)})).json();id=lab.id;}
   await json('/labs/'+id+'/operations-settings','PUT',{path});activeId=id;try{sessionStorage.setItem('activeLab',id);}catch{/* blocked site data: the open lab is carried by activeId */}confirm.close();dialog.close();await refresh();if(typeof selectLab==='function')selectLab(id);notify(parsed.name+' added to My labs.');
  });
 }));
 $('op-deploy-project')?.addEventListener('click',()=>opTask(dialog,async()=>{
  const source=await json('/operations/read','POST',{path}),parsed=await opParse(path,source.text);
  const id=await opSaveWorkspace(path,source,parsed,labId);
  await opReview({action:'deploy',lab_id:id,path,name:parsed.name});
 }));
}
// Deploy › Upload a file from this computer. The browser reads the file; the manager checks that it is a
// topology it can read back; the student sees the text and where it will go; the reviewed `create`
// operation writes it on the VM; "Deploy or add this lab…" continues as for any file on the VM.
const OP_UPLOAD_LIMIT=1024*1024;
function opUploadProblem(file){
 if(!file)return 'Choose a file first.';
 if(!/\.ya?ml$/i.test(file.name||''))return 'Choose a containerlab topology file. Its name ends in .clab.yaml, .clab.yml, .yaml or .yml.';
 if(!file.size)return 'This file is empty.';
 if(file.size>OP_UPLOAD_LIMIT)return 'This file is larger than 1 MiB, which is more than a topology file can be. Choose the .clab.yaml file itself, not an archive or a configuration dump.';
 return '';
}
// <trusted folder>/<lab name>.clab.yaml; the VM only creates files directly inside a lab folder it trusts.
function opUploadPath(root,name){const safe=String(name||'').replace(/[^A-Za-z0-9_.-]+/g,'-').replace(/^[^A-Za-z0-9_]+/,'').replace(/[-.]+$/,'').slice(0,80)||'uploaded-lab';return String(root||'/srv/containerlab-node-manager/projects').replace(/\/+$/,'')+'/'+safe+'.clab.yaml';}
// The optional saved map (annotations JSON) that can travel with an uploaded topology: a copied lab
// often has one beside its .clab.yaml, and without it the devices would land on the default grid.
const OP_UPLOAD_ANNOTATIONS_LIMIT=1024*1024;
function opUploadAnnotationsProblem(file){
 if(!file)return '';
 if(!/\.json$/i.test(file.name||''))return 'Choose the saved map file: a .json file, usually named <lab>.clab.yaml.annotations.json.';
 if(!file.size)return 'This map file is empty.';
 if(file.size>OP_UPLOAD_ANNOTATIONS_LIMIT)return 'This map file is larger than 1 MiB.';
 return '';
}
// Throws in the student's words when the text is not a single JSON object; returns it unchanged otherwise
// (the helper re-checks this on the VM; this is only the first, faster answer).
function opUploadAnnotationsParse(text){
 let value;try{value=JSON.parse(text);}catch{throw new Error('The map file is not valid JSON.');}
 if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('The map file must hold one JSON object, not a list or a plain value.');
 return text;
}
// The name the map file is written under on the VM: always beside the topology, regardless of what the
// chosen file on this computer was called (the same name the lab builder and the VS Code extension use).
function opUploadAnnotationsName(topologyPath){return String(topologyPath||'')+'.annotations.json';}
function opUploadAnnotationsNotice(file,topologyPath){
 if(!file)return '';
 const expected=opUploadAnnotationsName(topologyPath).split('/').pop();
 return file.name===expected?'':'The map file name does not match the topology name; it will be saved as '+expected+'.';
}
function opUpload(){
 const dialog=opDialog('op-upload','Upload a lab file from this computer','<p>Choose the lab\'s containerlab topology file (<code>.clab.yaml</code>) on <strong>this computer</strong>. It is shown to you next, and copied to the <strong>lab VM</strong> only after you confirm.</p><label for="op-upload-file">Topology file</label><div class="upload-field"><input id="op-upload-file" type="file" accept=".yaml,.yml"><small>YAML · up to 1 MiB</small></div><label for="op-upload-annotations">Saved map (annotations JSON, optional)</label><div class="upload-field"><input id="op-upload-annotations" type="file" accept=".json"><small>JSON · up to 1 MiB · optional</small></div><p class="form-help">If you copied a lab with its map file, add it here so device positions are kept.</p><p class="form-help">Only this one file is uploaded. Files it refers to (startup configurations, certificates) have to be on the lab VM already. Is the lab on the VM already? Use <em>Choose a file on the lab VM…</em> instead.</p><div class="dialog-actions"><button class="button secondary" id="op-upload-cancel">Cancel</button><button class="button primary" id="op-upload-next">Continue</button></div>');
 $('op-upload-cancel').onclick=()=>dialog.close();
 $('op-upload-next').onclick=()=>opTask(dialog,async()=>{
  const file=$('op-upload-file').files&&$('op-upload-file').files[0],problem=opUploadProblem(file);if(problem)throw new Error(problem);
  const mapFile=$('op-upload-annotations').files&&$('op-upload-annotations').files[0],mapProblem=opUploadAnnotationsProblem(mapFile);if(mapProblem)throw new Error(mapProblem);
  const text=await file.text();
  if(/\u0000/.test(text))throw new Error('This does not look like a text file. Choose the .clab.yaml topology file.');
  let parsed;try{parsed=await opParse('',text);}catch(error){throw new Error('This file is not a containerlab topology the manager can read: '+error.message);}
  const annotations=mapFile?opUploadAnnotationsParse(await mapFile.text()):'';
  let roots=[];try{roots=(await opCapabilities()).roots||[];}catch{roots=[];}
  const uploadPath=opUploadPath(opBuilderRoot('',roots),parsed.name);
  const mapNotice=mapFile?opUploadAnnotationsNotice(mapFile,uploadPath):'';
  dialog.close();await opEdit('','',uploadPath,{text,file:file.name,annotations,mapNotice});
 });
 return dialog;
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
// The map alone, sized to the dialog rather than the small fixed box other dialogs use (B3): the
// caption under it named nothing the student can act on, so the title is the only text. Fitting reuses
// the Topology tab's own bounding-box routine (measureTopology, topology-render.js — also sizes the
// device/interface label backgrounds) so a saved map and an unplaced grid both open already fit; a
// resize while the dialog stays open refits it, and the listener leaves with the dialog.
function opFitPreview(svg){
 if(!svg||typeof measureTopology!=='function')return;
 svg.setAttribute('viewBox',measureTopology(svg).join(' '));
 svg.setAttribute('preserveAspectRatio','xMidYMid meet');
}
function opMapPreview(drawing,name,positioned=false){
 const dialog=opDialog('op-map-preview','Topology preview · '+name,'<svg id="op-preview-map" class="topology-map op-layout-map" role="img" aria-label="Proposed topology"></svg>');
 dialog.classList.add('dialog-viewport');
 // A file being looked at, not a lab's map: no device is a button, none is "Not in this lab" (there is no
 // lab yet); a device the map file names but the topology file does not is captioned so.
 const svg=$('op-preview-map');svg.innerHTML=topologyMarkup(drawing,{},{preview:true});
 if(dialog._previewResize&&typeof window!=='undefined')window.removeEventListener('resize',dialog._previewResize);
 const fit=()=>opFitPreview(svg);
 dialog._previewResize=fit;
 if(typeof window!=='undefined')window.addEventListener('resize',fit);
 dialog.addEventListener('close',()=>{if(typeof window!=='undefined')window.removeEventListener('resize',fit);dialog._previewResize=null;},{once:true});
 if(typeof requestAnimationFrame==='function')requestAnimationFrame(fit);else fit();
 return dialog;
}
// Edit map. A lab whose topology text the manager has opens the full map editor (the lab builder's editor
// in map mode, map-editor.html): it edits the drawing only and leaves through its own Save / Back. A lab
// without one (imported from an inventory) keeps the simple dialog.
function opMapEditorUrl(id){return '/static/map-editor.html#lab='+encodeURIComponent(id);}
async function opLayout(id){const lab=(state.labs||[]).find(l=>l.id===id);if(lab&&lab.map_editor){location.assign(opMapEditorUrl(id));return;}return editDiagram(id);}
// The Edit topology… entry (owner #topology-edit; the menu items and the Tools card mirror it): '' when the lab's file can be opened in the
// lab builder, else the reason in student words. The first four answer before the capabilities load; a missing capability answer never blocks.
function opTopologyEditReason(lab,discovery,isBusy=false,caps=opCaps){
 if(!lab)return '';
 const path=opPath(lab),status=lab.deployment?.status,revise=caps?.actions?.revise,roots=Array.isArray(caps?.roots)?caps.roots.filter(r=>typeof r==='string'&&r):[];
 if(!path)return 'This lab has no topology file on the VM (Advanced › Deployment details)';
 if(!discovery?.connected)return 'Connect the VM first';
 if(revise&&revise.available===false)return typeof revise.reason==='string'&&revise.reason?revise.reason:'The VM helpers are older than the manager: refresh them (see Diagnostics)';
 if(isBusy)return 'Wait for the current operation to finish';
 if(!['Not deployed','Running','Stopped','Partially running'].includes(status))return 'Lab status is unknown — refresh the lab list';
 if(roots.length&&!roots.some(r=>path===r||path.startsWith(r.replace(/\/+$/,'')+'/')))return 'The topology file is outside the folders the manager may edit';
 return '';
}
// Edit topology…: the lab's own file in the lab builder, which brings the lab back to its Topology tab (#lab=<id>).
function opTopologyEdit(id){const lab=(state.labs||[]).find(l=>l.id===id);if(!lab||!opPath(lab))return false;opBuilderOpen({path:opPath(lab),lab:lab.id});return true;}
// reason / destroyReason say, in student words, why Start or Destroy is unavailable right now.
function opQuickActions(lab,discovery,isBusy=false){
 const status=lab?.deployment?.status, known=['Not deployed','Running','Stopped','Partially running'].includes(status);
 const available=!!lab&&!!opPath(lab)&&!!discovery?.connected&&known&&!isBusy;
 const blocked=!lab?'':!discovery?.connected?'Connect the VM first':isBusy?'Wait for the current operation to finish':!opPath(lab)?'This lab has no topology file on the VM (Advanced › Deployment details)':!known?'Lab status is unknown — refresh the lab list':'';
 return {startAction:status==='Not deployed'?'deploy':'start',canStart:available&&status!=='Running',canDestroy:available&&status!=='Not deployed',available,reason:blocked||(status==='Running'?'The lab is already running':''),destroyReason:blocked||(status==='Not deployed'?'Nothing to destroy — the lab is not running':'')};
}
// The single-device actions (Restart device, Start device, Stop device): whether the action is available for this device, and the
// reason when it is not — one answer for the map's right-click menu, the Devices table and the device panel. `own` says the reason is
// the device's own state (a running device's disabled Start needs no note beside the buttons). The first eight checks are shared; a
// stopped device is eligible for Restart (containerlab's start/restore path); a device the VM does not list is not. Capabilities not
// loaded yet count as available (the click loads them and checks again), only a loaded answer that lacks the action disables it.
const OP_NODE_VERBS={'restart-node':'restart','start-node':'start','stop-node':'stop'};
function opNodeChecks(lab,n,discovery,isBusy=false){
 const dev=n?.short_name||n?.name||'This device',status=lab?.deployment?.status;
 if(!lab||!n)return {ok:false,reason:'This device is not in the lab'};
 if(!discovery?.connected)return {ok:false,reason:'Connect the VM first'};
 if(isBusy)return {ok:false,reason:'Wait for the current operation to finish'};
 if(!opPath(lab))return {ok:false,reason:'This lab has no topology file on the VM (Advanced › Deployment details)'};
 if(!lab.deployment_name||status==='Unlinked')return {ok:false,reason:'The lab is not matched to a running lab'};
 if(status==='Unknown'||!status)return {ok:false,reason:'Lab status is unknown — refresh the lab list'};
 if(status==='Not deployed')return {ok:false,reason:'The lab is not running'};
 if(!n.discovered||n.runtime_state==='absent')return {ok:false,reason:`${dev} is not deployed on the VM`};
 return null;
}
function opNodeActionState(action,lab,n,discovery,isBusy=false){
 const shared=opNodeChecks(lab,n,discovery,isBusy);if(shared)return shared;
 const dev=n.short_name||n.name||'This device',verb=OP_NODE_VERBS[action]||'restart';
 if(action==='stop-node'&&n.runtime_state!=='running'&&n.runtime_state!=='unknown')return {ok:false,reason:`${dev} is not running`,own:true};
 if(action==='start-node'&&(!n.runtime_state||n.runtime_state==='running'))return {ok:false,reason:n.runtime_state==='running'?`${dev} is already running`:`${dev} is not deployed on the VM`,own:n.runtime_state==='running'};
 if(opCaps&&opCaps.actions&&opCaps.actions[action]?.available!==true)return {ok:false,reason:`Not available on this VM — its containerlab or helper cannot ${verb} one device (see Diagnostics)`};
 return {ok:true,reason:''};
}
function opRestartState(lab,n,discovery,isBusy=false){return opNodeActionState('restart-node',lab,n,discovery,isBusy);}
// Save this device's configuration (the device panel): containerlab save --node-filter for the one running device.
function opSaveNodeState(lab,n,discovery,isBusy=false){
 const shared=opNodeChecks(lab,n,discovery,isBusy);if(shared)return shared;
 const dev=n.short_name||n.name||'This device';
 if(n.runtime_state!=='running')return {ok:false,reason:`${dev} is not running`,own:true};
 const cap=opCaps&&opCaps.actions?opCaps.actions.save:null;
 if(opCaps&&opCaps.actions&&(!cap||cap.available!==true||cap.node_filter!==true))return {ok:false,reason:'Not available on this VM — its containerlab cannot save one device (see Diagnostics)'};
 return {ok:true,reason:''};
}
async function opRestartDevice(labId,name,opener){
 try{await opCapabilities();}catch{opCaps=null;}
 const lab=(state.labs||[]).find(l=>l.id===labId),n=lab?.nodes?.find(n=>n.name===name);
 const check=opRestartState(lab,n,state.discovery,busy());
 // The reason is the banner's headline (shell.js keeps this sentence as it is), not a folded detail.
 if(!check.ok){const text='Restart device… is not available: '+check.reason;if(typeof showActionError==='function')showActionError(text);else notify(text);return;}
 await opReview({lab_id:labId,action:'restart-node',node:name,options:{}},opener);
}
// Start device and Stop device: the same click path as Restart device — capabilities loaded first, eligibility checked again, then
// the review of exactly one device of one lab with no options.
async function opNodeAction(action,labId,name,opener){
 if(action==='restart-node')return opRestartDevice(labId,name,opener);
 if(!opNodeActions.includes(action))return;
 try{await opCapabilities();}catch{opCaps=null;}
 const lab=(state.labs||[]).find(l=>l.id===labId),n=lab?.nodes?.find(n=>n.name===name);
 const check=opNodeActionState(action,lab,n,state.discovery,busy());
 if(!check.ok){const text=opLabels[action]+'… is not available: '+check.reason;if(typeof showActionError==='function')showActionError(text);else notify(text);return;}
 await opReview({lab_id:labId,action,node:name,options:{}},opener);
}
async function opSaveNode(labId,name,opener){
 try{await opCapabilities();}catch{opCaps=null;}
 const lab=(state.labs||[]).find(l=>l.id===labId),n=lab?.nodes?.find(n=>n.name===name);
 const check=opSaveNodeState(lab,n,state.discovery,busy());
 if(!check.ok){const text='Save startup configuration… is not available: '+check.reason;if(typeof showActionError==='function')showActionError(text);else notify(text);return;}
 await opReview({lab_id:labId,action:'save',options:{nodes:[n.definition_node||n.short_name||n.name]}},opener);
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
// Images on this VM (C03 4.5): what Docker holds, how big and how old, and which of the student's labs name each image. Nothing is pulled or removed.
// Docker's CreatedAt ("2026-10-23 02:03:42 +0000 UTC") is not an ISO stamp; the manager may pass either.
function opCreatedDate(value){
 const text=String(value||'').trim();if(!text)return null;
 const m=/^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d:\d\d)/.exec(text);
 const date=new Date(m?m[1]+'T'+m[2]+'Z':text);
 return Number.isNaN(date.getTime())?null:date;
}
// Pure: the table rows. `missing` references are named by a lab but not on the VM; they carry no size or age.
function opImageRows(data){
 const used=data&&data.used_by&&typeof data.used_by==='object'?data.used_by:{},rows=[];
 const details=Array.isArray(data&&data.details)?data.details:[];
 const known=details.length?details:(Array.isArray(data&&data.images)?data.images:[]).map(reference=>({reference,size:'',created:''}));
 for(const item of known)rows.push({reference:String(item.reference||''),size:String(item.size||''),created:String(item.created||''),labs:Array.isArray(used[item.reference])?used[item.reference]:[],missing:false});
 for(const reference of Array.isArray(data&&data.missing)?data.missing:[])rows.push({reference:String(reference),size:'',created:'',labs:Array.isArray(used[reference])?used[reference]:[],missing:true});
 return rows;
}
function opImageFilter(rows,text,chip){
 const needle=String(text||'').trim().toLowerCase();
 return rows.filter(r=>(chip==='used'?r.labs.length>0:chip==='missing'?r.missing:true)&&(!needle||(r.reference+' '+r.labs.join(' ')).toLowerCase().includes(needle)));
}
function opImageTableBody(rows){
 if(!rows.length)return '<tr><td colspan="4">No images match.</td></tr>';
 return rows.map(r=>{const date=opCreatedDate(r.created);return `<tr><td class="mono">${esc(r.reference)}${r.missing?' <span class="pill danger">Missing</span>':''}</td><td>${esc(r.size)||'—'}</td><td${date?` title="${esc(date.toISOString().replace('T',' ').slice(0,19)+' UTC')}"`:''}>${date?esc(opWhen(date.toISOString())):esc(r.created)||'—'}</td><td>${r.labs.length?esc(r.labs.join(', ')):'—'}</td></tr>`;}).join('');
}
async function opImages(){
 const data=await(await api('/operations/images')).json();
 const rows=opImageRows(data),hasDetails=Array.isArray(data.details)&&data.details.length>0,view={text:'',chip:'all'};
 const chips=[['all','All'],['used','Used by my labs'],['missing','Missing']];
 const dialog=opDialog('op-images','Images on this VM',data.available===false?'<p>This VM has no Docker client the manager can ask, so its images cannot be listed.</p>':`<p class="form-help">The Docker images on the lab VM. Nothing is pulled or removed here.</p>${hasDetails||!rows.length?'':'<p class="form-help">Size and age need the updated VM helper.</p>'}<div class="op-inspection-tools"><label for="op-images-filter">Filter images</label><input type="search" id="op-images-filter" autocomplete="off"></div><div class="op-chips" role="group" aria-label="Show">${chips.map(([key,label])=>`<button type="button" class="button secondary small op-chip" data-op-chip="${key}" aria-pressed="${key==='all'}">${label}</button>`).join('')}</div><div class="op-inspection"><table><caption id="op-images-caption"></caption><thead><tr><th scope="col">Reference</th><th scope="col">Size</th><th scope="col">Created</th><th scope="col">Used by</th></tr></thead><tbody id="op-images-body"></tbody></table></div>`);
 if(data.available===false)return;
 const redraw=()=>{
  const shown=opImageFilter(rows,view.text,view.chip);
  $('op-images-body').innerHTML=opImageTableBody(shown);
  $('op-images-caption').textContent=shown.length===rows.length?rows.length+(rows.length===1?' image':' images'):shown.length+' of '+rows.length+' images';
 };
 redraw();
 $('op-images-filter').addEventListener('input',event=>{view.text=event.target.value;redraw();});
 for(const button of dialog.querySelectorAll('[data-op-chip]'))button.addEventListener('click',()=>{view.chip=button.dataset.opChip;for(const other of dialog.querySelectorAll('[data-op-chip]'))other.setAttribute('aria-pressed',String(other===button));redraw();});
}
// Pending changes and impairments (C05 4.3, 4.4). Both are read-only questions about the running lab, asked at exactly four moments
// and never on a timer: when a lab that is Running or Partially running becomes the open one ('open'), after an operation of that
// lab turned terminal ('job'), after a successful Sync topology from VM ('sync') and when Review changes… is chosen ('review').
const opPlanTriggers=['open','job','sync','review'];
const OP_TERMINAL=['succeeded','failed','interrupted','cancelled'];
let opPlanCache={}, opImpairmentCache={}, opWatchMemo={lab:'',active:false,jobs:[],sig:''}, opPlanSeq={}, opImpairSeq={};
// A sync rewrites the stored copy of the topology file; its digests change, which the page sees without a hook into the sync button.
function opSourceSignature(lab){const v=lab&&lab.vm_source;return v?JSON.stringify([v.status||'',v.synced_digest||'',v.digest||'']):'';}
// Pure: which trigger (if any) the current state calls for, and the memo to remember for the next look.
function opPlanDue(memo,lab,jobs){
 const active=!!lab&&['Running','Partially running'].includes(lab.deployment?.status);
 const terminal=lab?(jobs||[]).filter(j=>j&&j.lab_id===lab.id&&OP_TERMINAL.includes(j.status)).map(j=>j.id):[];
 const next={lab:lab?lab.id:'',active,jobs:terminal,sig:opSourceSignature(lab)};
 let reason='';
 if(active){
  if(memo.lab!==next.lab||!memo.active)reason='open';
  else if(terminal.some(id=>!memo.jobs.includes(id)))reason='job';
  else if(memo.sig!==next.sig)reason='sync';
 }
 return {reason,memo:next};
}
async function opLoadPlan(labId,refresh=false){
 const seq=opPlanSeq[labId]=(opPlanSeq[labId]||0)+1;
 try{
  const answer=await(await api('/operations/apply-plan?lab_id='+encodeURIComponent(labId)+(refresh?'&refresh=1':''))).json();
  if(seq===opPlanSeq[labId])opPlanCache[labId]={answer,error:'',at:Date.now()};
 }catch(e){if(seq===opPlanSeq[labId])opPlanCache[labId]={answer:null,error:e&&e.message||'The check failed.',at:Date.now()};}
 if(labId===activeId){if(typeof renderLabBanner==='function')renderLabBanner();opRenderPending(typeof current==='function'?current():null);}
 return opPlanCache[labId];
}
// The cached check when it found differences (a failed or unsupported check never claims any).
function opPendingChanges(lab){
 const entry=lab&&opPlanCache[lab.id],answer=entry&&entry.answer;
 return answer&&answer.changed===true&&!answer.failed&&answer.plan&&opPlanChanges(answer.plan)?answer:null;
}
async function opLoadImpairments(labId){
 if(opCaps&&opCaps.actions&&opCaps.actions.impairments?.available!==true){delete opImpairmentCache[labId];if(labId===activeId&&typeof renderMapImpairments==='function')renderMapImpairments(null);return null;}
 const seq=opImpairSeq[labId]=(opImpairSeq[labId]||0)+1;
 try{
  const answer=await(await api('/operations/impairments?lab_id='+encodeURIComponent(labId))).json();
  if(seq!==opImpairSeq[labId])return opImpairmentCache[labId]||null;
  opImpairmentCache[labId]=answer;
  if(labId===activeId&&typeof renderMapImpairments==='function')renderMapImpairments(answer);
  return answer;
 }catch{return opImpairmentCache[labId]||null;}
}
// Called by every render of the lab page (renderLabOperations): looks at the state and asks the VM only when a trigger fired.
// A Start device or Stop device job that finishes while the page is open says so in a toast (the banner and output stay).
const opNodeJobsSeen=new Set();
function opNodeJobToasts(lab,jobs){
 if(!lab)return;
 for(const job of jobs||[]){
  if(job.lab_id!==lab.id||!['start-node','stop-node'].includes(job.action))continue;
  if(['queued','running'].includes(job.status)){opNodeJobsSeen.add(job.id);continue;}
  if(!opNodeJobsSeen.has(job.id))continue;
  opNodeJobsSeen.delete(job.id);
  if(['succeeded','failed','interrupted'].includes(job.status))notify(opJobBanner(job).title);
 }
}
function opWatchLab(lab){
 opNodeJobToasts(lab,state.operations);
 const {reason,memo}=opPlanDue(opWatchMemo,lab,state.operations);opWatchMemo=memo;
 if(!lab)return;
 if(!memo.active){
  if(opImpairmentCache[lab.id]){delete opImpairmentCache[lab.id];if(typeof renderMapImpairments==='function')renderMapImpairments(null);}
  return;
 }
 if(!reason)return;
 const id=lab.id;
 if(state.discovery?.connected&&opPath(lab)&&lab.deployment_name)opLoadPlan(id,reason==='sync');
 (opCaps?Promise.resolve():opCapabilities().catch(()=>{opCaps=null;})).then(()=>opLoadImpairments(id));
}
async function opReviewChanges(labId){
 await opLoadPlan(labId,true);
 await opReview({lab_id:labId,action:'apply',options:{}});
}
// The lab banner's pending-changes notice (a Running lab) and the attention banner of a Partially running lab. The identity is a digest
// of the plan, so a dismissed notice stays dismissed while the plan is the same and comes back when it differs.
function opPendingBannerSpec(lab){
 if(!lab||lab.deployment?.status!=='Running')return null;
 const pending=opPendingChanges(lab);if(!pending)return null;
 return {tone:'info',icon:'info',text:'The topology file differs from the running lab.',detail:opPlanSummary(pending.plan),identity:'pending.'+opPlanIdentity(pending.plan),actions:{'banner-review':{label:'Review changes…',run:()=>opTask(null,()=>opReviewChanges(lab.id))}}};
}
// A Partially running lab offers Start, which cannot recreate a destroyed device: with devices to create or recreate (or link ends to
// remove) the plan's review is the way back; a device merely stopped (a `started`-only plan) keeps Start.
function opAttentionSpec(lab,spec){
 if(!lab||lab.deployment?.status!=='Partially running')return spec;
 const pending=opPendingChanges(lab);if(!pending)return spec;
 const plan=pending.plan;
 if(!(opPlanList(plan,'added').length||opPlanList(plan,'recreated').length||opPlanList(plan,'endpoints_removed').length))return spec;
 return {...spec,detail:opPlanSummary(plan),identity:'pending.'+opPlanIdentity(plan),actions:{'banner-review':{label:'Review changes…',run:()=>opTask(null,()=>opReviewChanges(lab.id))}}};
}
// Advanced › Deployment details: the same check in one line.
function opPendingMarkup(entry){
 if(!entry)return 'Not checked';
 const answer=entry.answer;
 if(!answer)return `Could not be checked: ${esc(entry.error||'the check failed')}`;
 if(answer.failed==='unsupported')return 'Not checked: the installed containerlab cannot compare the file with the running lab.';
 if(answer.failed)return `Could not be checked: ${esc(answer.error||'the topology file could not be read')}`;
 if(answer.changed===true&&answer.plan)return `Differs from the running lab: ${esc(opPlanSummary(answer.plan)||'see the review')} — <button type="button" class="button ghost small" data-pending-review>Review changes…</button>`;
 const at=answer.checked_at?opWhen(new Date(answer.checked_at*1000).toISOString()):'';
 return 'Matches the running lab'+(at?` (checked ${esc(at)})`:'');
}
function opRenderPending(lab){
 const element=$('deployment-pending');if(!element)return;
 const active=!!lab&&['Running','Partially running'].includes(lab.deployment?.status);
 const html=active?opPendingMarkup(opPlanCache[lab.id]):'Not checked (the lab is not running)';
 if(element._html!==html){element._html=html;element.innerHTML=html;}
}
// Clear impairments (the map caption): every impairment the manager lists for the lab, after one confirmation.
function opPlural(n,word){return `${n} ${word}${Number(n)===1?'':'s'}`;}
function opImpairmentCount(answer){
 const devices=answer&&answer.devices&&typeof answer.devices==='object'?Object.values(answer.devices):[];
 return {interfaces:devices.reduce((sum,d)=>sum+((d&&d.impairments)||[]).length,0),devices:devices.filter(d=>d&&(d.impairments||[]).length).length};
}
// The port label the Interfaces answer showed for a failed row's Linux interface (Ethernet1 for eth1), from the cached lab-wide read.
function opImpairmentPort(answer,failedRow){
 const devices=answer&&answer.devices&&typeof answer.devices==='object'?answer.devices:{};
 const entry=devices[failedRow&&failedRow.node]||Object.values(devices).find(d=>d&&(d.impairments||[]).some(i=>i.interface===(failedRow&&failedRow.interface)));
 const row=entry&&(entry.impairments||[]).find(i=>i.interface===(failedRow&&failedRow.interface));
 return row&&typeof row.port==='string'&&row.port?row.port:'';
}
async function opClearImpairments(labId=activeId){
 const lab=(state.labs||[]).find(l=>l.id===labId),count=opImpairmentCount(opImpairmentCache[labId]),shownBefore=opImpairmentCache[labId];
 if(!lab||!count.interfaces)return;
 // Focus returns to the map's Fit button: the Clear impairments button is hidden once nothing is impaired.
 const dialog=opDialog('op-clear-impairments',`Remove every impairment in ${lab.name} (${opPlural(count.interfaces,'interface')} on ${opPlural(count.devices,'device')})?`,'<p>Delay, jitter, loss, rate and corruption are removed from those interfaces. Nothing else on the devices changes.</p><p class="form-help" id="op-clear-status" role="status" aria-live="polite"></p><div class="dialog-actions"><button class="button secondary" id="op-clear-cancel">Cancel</button><button class="button danger" id="op-clear-confirm">Clear all</button></div>',$('map-fit')||undefined);
 $('op-clear-cancel').onclick=()=>dialog.close();
 $('op-clear-confirm').onclick=async()=>{
  const confirm=$('op-clear-confirm'),status=$('op-clear-status'),error=dialog.querySelector('.form-error');
  confirm.disabled=true;confirm.textContent='Clearing…';if(error)error.textContent='';
  try{
   const result=await json('/operations/impairments/clear','POST',{lab_id:labId});
   await opLoadImpairments(labId);
   const failed=Array.isArray(result.failed)?result.failed:[];
   if(!failed.length&&!(result.remaining||[]).length){dialog.close();notify(`${opPlural(result.cleared||0,'interface')} cleared.`);return;}
   const first=failed[0]||{},shown=(lab.nodes||[]).find(n=>n.name===first.node||n.definition_node===first.node),port=opImpairmentPort(opImpairmentCache[labId],first)||opImpairmentPort(shownBefore,first)||first.interface||'';
   status.textContent=`${result.cleared||0} of ${result.total||count.interfaces} interfaces cleared${failed.length?`; ${shown?.short_name||first.node||'a device'} ${port}: ${String(first.reason||'not cleared').replace(/\.+$/,'')}`:''}. Try again.`;
   confirm.disabled=false;confirm.textContent='Clear all';
  }catch(e){if(error)error.textContent=e.message;confirm.disabled=false;confirm.textContent='Clear all';}
 };
}
function renderLabOperations(){
 const lab=current(),quick=opQuickActions(lab,state.discovery,busy()),status=lab?.deployment?.status,running=['Running','Partially running'].includes(status);
 if($('lab-start'))opMenuState($('lab-start'),!quick.canStart,quick.reason,quick.startAction==='deploy'?'Start lab':'Start stopped devices',quick.startAction==='deploy'?'Deploy this topology and start its devices':'Start stopped devices in this lab');
 if($('lab-destroy')){$('lab-destroy').disabled=!quick.canDestroy;$('lab-destroy').title=quick.canDestroy?'':quick.destroyReason;}
 if($('lab-actions'))$('lab-actions').hidden=!current();
 opWatchLab(lab);opRenderPending(lab);
 const menu=$('lab-actions-menu');
 if(menu&&typeof menu.querySelectorAll==='function')for(const b of menu.querySelectorAll('[data-op-action]')){
  if(b.dataset.opVariant==='cleanup')b.hidden=opCaps?.actions?.redeploy?.cleanup!==true;
  const capability=opCaps?.actions?.[b.dataset.opAction],unavailable=capability&&capability.available===false;
  const ok=!unavailable&&quick.available&&(b.dataset.opAction==='redeploy'?status!=='Not deployed':running);
  opMenuState(b,!ok,unavailable?'Not available on this VM — see Diagnostics':quick.available?'The lab is not running':quick.reason);
 }
if($('topology-edit')){const reason=opTopologyEditReason(lab,state.discovery,busy());$('topology-edit').disabled=!!reason||!lab;$('topology-edit').title=reason||'Devices and links, saved to the lab file on the VM; applying is a separate step';}
 if($('vm-projects')){const connected=!!state.discovery?.connected;opMenuState($('vm-projects'),!connected,'Connect the VM to browse its lab topologies');}
 if($('manager-images')){const connected=!!state.discovery?.connected;opMenuState($('manager-images'),!connected,'Connect the VM to see its images');}
 // The banner (app.js) is the lowest-priority notice and a student can hide it for the session, so
 // this menu item is a second, always-reachable way to the same dialog: shown only while the lab has
 // something recorded, hidden (not merely disabled, so keyboard and pointer navigation both skip it).
 if($('menu-telemetry-retired'))$('menu-telemetry-retired').hidden=!lab?.telemetry_retired;
 // Busy controls carry their reason: the menu proxies and the Advanced buttons read it from the title.
 if(busy()){for(const id of ['remove-lab','sync-vm','update-definition','link-deployment'])if($(id)){$(id).disabled=true;$(id).title='Wait for the current operation to finish';}}
 else{for(const id of ['update-definition','link-deployment'])if($(id)){$(id).disabled=false;$(id).title='';}}
}
if($('import-top')){
 if(!$('lab-actions'))$('import-top').insertAdjacentHTML('beforebegin','<button class="button secondary" id="lab-actions" hidden>All lab operations…</button>');

 $('map-edit').onclick=()=>opTask(null,()=>opLayout(activeId));
 if($('topology-edit'))$('topology-edit').onclick=()=>{if(typeof closeMenus==='function')closeMenus();opTopologyEdit(activeId);};
 if($('lab-operations-all'))$('lab-operations-all').onclick=()=>openLabOperations();
 // Operation history for THIS lab from its menu and its Advanced tab; Manager ▾ keeps the history of every lab.
 for(const id of ['menu-operation-history','advanced-operation-history'])if($(id))$(id).onclick=()=>{if(typeof closeMenus==='function')closeMenus();opTask(null,()=>opHistory(activeId));};
 if($('menu-telemetry-retired'))$('menu-telemetry-retired').onclick=()=>{if(typeof closeMenus==='function')closeMenus();opTask(null,()=>openTelemetryRetired(activeId));};
 if($('manager-images'))$('manager-images').onclick=()=>opTask(null,()=>opImages());
 // The map caption's Clear impairments and the pending line's Review changes… (static markup in index.html, wired once).
 if($('map-impaired-clear'))$('map-impaired-clear').onclick=()=>opTask(null,()=>opClearImpairments(activeId));
 if($('deployment-pending'))$('deployment-pending').addEventListener('click',e=>{if(e.target.closest&&e.target.closest('[data-pending-review]'))opTask(null,()=>opReviewChanges(activeId));});
 $('lab-actions').onclick=()=>openLabOperations();$('vm-projects').onclick=()=>openDeploy();$('lab-start').onclick=()=>opTask(null,()=>opQuickRun('start'));$('lab-destroy').onclick=()=>opTask(null,()=>opQuickRun('destroy'));$('operations-history').onclick=()=>opTask(null,()=>opHistory());$('inspect-all').onclick=()=>opTask(null,()=>opReview({action:'inspect-all'}));
 // Lab actions ▾ lifecycle items go through the same preview/confirm flow as the operations dialog.
 const menu=$('lab-actions-menu');
 if(menu){
  menu.addEventListener('click',e=>{const b=e.target.closest('[data-op-action]');if(!b||b.disabled)return;if(typeof closeMenus==='function')closeMenus();
   opTask(null,async()=>{const lab=current();if(!lab)return;try{await opCapabilities();}catch{opCaps=null;}renderLabOperations();await opReview({lab_id:lab.id,action:b.dataset.opAction,options:JSON.parse(b.dataset.opOptions||'{}')});});});
  menu.addEventListener('menuopen',()=>{if(opCaps)return;opCapabilities().then(()=>renderLabOperations()).catch(()=>{});});
 }
 // The Manager menu's footer names the VM's containerlab; the capabilities answer is cached for a minute on the server.
 {const managerMenu=$('manager-menu-list');
  if(managerMenu)managerMenu.addEventListener('menuopen',()=>{opCapabilities().then(caps=>{const span=$('clab-version'),version=typeof caps?.containerlab==='string'&&/^\d+\.\d+\.\d+/.test(caps.containerlab)?caps.containerlab:'';if(span){span.textContent=version?' · containerlab '+version:'';span.hidden=!version;}}).catch(()=>{});});}
 $('labs').addEventListener('contextmenu',e=>{const lab=e.target.closest('[data-lab]');if(lab){e.preventDefault();openLabOperations(lab.dataset.lab);}});
 $('labs').addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){const lab=e.target.closest('[data-lab]');if(lab){e.preventDefault();openLabOperations(lab.dataset.lab);}}});
 // Coming back from the lab builder (its "← My labs" link, or the browser Back button): both are a
 // normal navigation to this page, so the dialog the student left is reopened once, here, on load.
 opTask(null,()=>opReopenReturn(opConsumeReturn()));
}

// A deployed save (revise with deployed:true) leaves the running lab unchanged: its output dialog says so and offers
// the one next step, the apply review, instead of Deploy now / Go to My labs (which would claim "not running").
// The job record does not say it (no `options`, and the helper's result carries no `deployed`): the builder page remembers that the review it
// confirmed was a deployed save (builderPending.deployed), and the dialog keeps that for the job while it is open and when it is shown again.
const opDeployedJobs=new Set();
function opDeployedSave(job){
 if(!job||job.action!=='revise')return false;
 if(job.deployed===true||job.options?.deployed===true||job.result?.deployed===true)return true;
 if(typeof builderPending!=='undefined'&&builderPending&&builderPending.deployed===true&&builderPending.job&&builderPending.job===job.id)opDeployedJobs.add(job.id);
 return opDeployedJobs.has(job.id);
}
function opBackToReviewLab(job){return (job&&job.lab_id)||opLabAtPath(opPublishedPath(job))?.id||'';}
function opBackToReviewHash(job){const id=opBackToReviewLab(job);return id?'/#lab='+encodeURIComponent(id)+'&view=topology&review=apply':'/';}
function opDeployedSaveMarkup(job){return `<p class="op-notice ok" id="op-published-status" tabindex="-1">Saved to the VM. The running lab is unchanged until you apply the changes.</p><div class="actions"><button class="button primary" id="op-back-review">Back to lab and review changes…</button></div>`;}
function opBackToReview(job){location.assign(opBackToReviewHash(job));}
