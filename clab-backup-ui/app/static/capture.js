'use strict';
// Provider UI is intentionally separate from backups, SSH and the diagram editor.
const captureDialog=$('capture-dialog');
let captureRequest=0,captureTargets=[],captureLab='',captureNode='',captureHint='',captureStarting=false,captureLaunchId='';
// null until the provider status is known; node/menu Capture actions are disabled
// only when the manager reports capture disabled, so the toolbar entry and the
// dialog's setup link stay reachable.
let captureEnabled=null;
function captureActionAttrs(){return captureEnabled===false?'disabled title="Packet capture is not enabled. Open Capture packets for setup."':'';}
(async()=>{try{captureEnabled=!!(await(await api('/capture/status')).json()).enabled;}catch{captureEnabled=null;}})();
function clearCaptureLaunch(){
 $('capture-launch').hidden=true;$('capture-launch').removeAttribute('href');
}
function invalidateCapture(){captureRequest++;captureLaunchId='';clearCaptureLaunch();}
captureDialog.addEventListener('close',invalidateCapture);
$('capture-close').onclick=()=>captureDialog.close();
function captureSelected(){return captureTargets.find(t=>t.id===$('capture-target').value);}
function captureChecked(){return [...$('capture-interfaces').querySelectorAll('input:checked')].map(el=>el.value);}
// Prepare needs a target and at least one ticked interface; a matching imported
// port counts because it is rendered ticked.
function updateCapturePrepare(preselected=false){const target=captureSelected();$('capture-prepare').disabled=captureStarting||!(target&&(preselected||captureChecked().length));}
function renderCaptureInterfaces(){
 invalidateCapture();const target=captureSelected();
 $('capture-interfaces').innerHTML=!target?'<p>Choose a capture target above.</p>':target.interfaces.map(n=>`<label class="capture-interface"><input type="checkbox" value="${esc(n)}" ${captureHint===n?'checked':''}> <span>${esc(n)}</span></label>`).join('')||'<p>No capturable interfaces in this namespace.</p>';
 updateCapturePrepare(!!(captureHint&&target?.interfaces.includes(captureHint)));
 if(captureHint)$('capture-status').textContent=target?.interfaces.includes(captureHint)?`Selected live interface ${captureHint}.`:`Imported port ${captureHint} is not a live Linux interface name here. Select its Linux interface explicitly; NOS aliases can differ.`;
}
$('capture-target').onchange=renderCaptureInterfaces;
$('capture-interfaces').onchange=()=>{invalidateCapture();updateCapturePrepare();$('capture-status').textContent='Selection changed. Start a capture for these interfaces.';};
function captureTargetLabel(t){
 const aliases=t.aliases||[],shown=aliases.slice(0,2).join(', ')+(aliases.length>2?` +${aliases.length-2} more`:'');
 const shared=aliases.length?' · shares namespace with '+esc(shown):'',loopback=t.interfaces.length===1&&t.interfaces[0]==='lo'?' · loopback only':'';
 return `${esc(t.name)}${t.prefix?' · '+esc(t.prefix):''} (${esc(t.kind)}) · ${t.interfaces.length} interfaces${shared}${loopback}`;
}
function filterCaptureTargets(){
 const previous=$('capture-target').value,query=$('capture-search').value.toLowerCase();
 const rows=captureTargets.filter(t=>[t.name,t.prefix,t.kind,...(t.aliases||[]),...t.interfaces].join(' ').toLowerCase().includes(query));
 $('capture-target').innerHTML='<option value="">Choose a capture target</option>'+rows.map(t=>`<option value="${esc(t.id)}">${captureTargetLabel(t)}</option>`).join('');
 if(rows.some(t=>t.id===previous))$('capture-target').value=previous;
 else if(rows.length===1)$('capture-target').value=rows[0].id;
 renderCaptureInterfaces();
}
$('capture-search').oninput=filterCaptureTargets;
async function refreshCaptureTargets(){
 invalidateCapture();const request=captureRequest;
 captureTargets=[];$('capture-target').innerHTML='';$('capture-interfaces').innerHTML='';$('capture-prepare').disabled=true;$('capture-search').disabled=true;
 $('capture-status').textContent='Discovering live capture targets…';
 refreshCaptureSessions();
 try{
  const status=await(await api('/capture/status')).json();
  captureEnabled=!!status.enabled;
  if(request!==captureRequest||!captureDialog.open)return;
  if(!status.enabled){$('capture-status').textContent=status.message;$('capture-search').disabled=false;return;}
  const params=new URLSearchParams();
  if($('capture-scope').value!=='host'&&captureLab){params.set('lab_id',captureLab);if(captureNode)params.set('node',captureNode);}
  const data=await(await api('/capture/targets?'+params)).json();
  if(request!==captureRequest||!captureDialog.open)return;
  captureTargets=data.targets;$('capture-search').disabled=false;
  $('capture-status').textContent=data.targets.length?data.message:'No live target matched. Refresh after starting the node, or choose All host targets to select its namespace explicitly.';
  filterCaptureTargets();
 }catch(error){if(request===captureRequest&&captureDialog.open){$('capture-status').textContent=error.message;$('capture-search').disabled=false;}}
}
function openCapture(node='',hint='',ends=null){
 captureLab=activeId;captureNode=node;captureHint=hint;
 if($('details-dialog').open)$('details-dialog').close();
 $('capture-search').value='';$('capture-scope').value='lab';
 $('capture-context').textContent=node?`Node: ${node}${hint?' · imported port: '+hint:''}`:`Lab: ${current()?.name||'All targets'}`;
 $('capture-endpoints').innerHTML=ends?ends.map((ep,i)=>`<button type="button" class="button secondary" data-capture-end="${i}">${esc(ep.label)}: ${esc(ep.interface)}</button>`).join(''):'';
 $('capture-endpoints').onclick=ends?event=>{const button=event.target.closest('[data-capture-end]');if(!button)return;const ep=ends[Number(button.dataset.captureEnd)];captureNode=ep.node||'';captureHint=ep.interface;$('capture-context').textContent=`Link endpoint: ${ep.label}: ${ep.interface}${ep.node?'':' · unmatched map node; select the namespace explicitly'}`;$('capture-scope').value=ep.node?'lab':'host';$('capture-search').value='';refreshCaptureTargets();}:null;
 if(!captureDialog.open)captureDialog.showModal();
 refreshCaptureTargets();
}
$('capture-open').onclick=()=>openCapture();
$('capture-refresh').onclick=refreshCaptureTargets;
$('capture-scope').onchange=()=>{captureHint='';refreshCaptureTargets();};
$('capture-form').onsubmit=async event=>{
 event.preventDefault();if(captureStarting)return;clearCaptureLaunch();const target=captureSelected();
 const interfaces=[...$('capture-interfaces').querySelectorAll('input:checked')].map(el=>el.value);
 if(!target||!interfaces.length){$('capture-status').textContent='Choose a target and at least one interface.';return;}
 const request=++captureRequest;captureStarting=true;$('capture-prepare').disabled=true;$('capture-status').textContent='Checking interfaces and starting Wireshark on the VM…';
 if(!captureLaunchId)captureLaunchId=Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,'0')).join('');
 try{
  const result=await json('/capture/launch','POST',{target_id:target.id,interfaces,request_id:captureLaunchId});
  refreshCaptureSessions();
  if(request!==captureRequest||!captureDialog.open)return;
  if(!/^\/static\/capture-session\.html#[0-9a-f]{64}$/.test(result.url))throw new Error('Unsupported capture launch address.');
  captureLaunchId=''; // A deliberate subsequent Start creates a new session; uncertain retries reuse their key.
  $('capture-launch').href=result.url;$('capture-launch').hidden=false;$('capture-status').textContent=result.message;
 }catch(error){if(request===captureRequest&&captureDialog.open)$('capture-status').textContent=error.message;}
 finally{captureStarting=false;updateCapturePrepare();}
};
$('capture-launch').onclick=()=>{$('capture-status').textContent='Browser viewer opened. Sessions and saved files remain on the VM until ended or expired.';};
let captureSessionRequest=0;
async function refreshCaptureSessions(){
 const request=++captureSessionRequest;
 try{
  const data=await(await api('/capture/sessions')).json();
  if(request!==captureSessionRequest)return;
  $('capture-sessions').innerHTML=(data.sessions||[]).map(s=>{
   if(!/^[0-9a-f]{64}$/.test(s.id))return '';
   return `<li><a href="/static/capture-session.html#${s.id}" target="_blank" rel="noopener">${esc(s.name)} · ${esc(s.interfaces.join(', '))}</a> <button type="button" class="button secondary" data-end-capture="${s.id}">End session</button></li>`;
  }).join('')||'<li>No sessions in this browser.</li>';
 }catch{$('capture-sessions').textContent='Browser capture service unavailable or disabled. See Capture setup.';}
}
$('capture-sessions-refresh').onclick=refreshCaptureSessions;
$('capture-sessions').onclick=async event=>{
 const button=event.target.closest('[data-end-capture]');if(!button)return;
 if(!confirm('End this Wireshark session and delete its temporary captures? Download saved files first.'))return;
 button.disabled=true;
 try{await json('/capture/sessions/'+button.dataset.endCapture+'/end','POST',{});await refreshCaptureSessions();}
 catch(error){$('capture-status').textContent=error.message;button.disabled=false;}
};
function openLinkCapture(element){
 const pair=element.dataset.captureEndpoints;if(!pair)return;
 try{const ends=JSON.parse(pair);openCapture('', '', ends);$('capture-context').textContent='Choose either link endpoint below, then select its live Linux interface.';}
 catch{notify('Could not read this link. Use Capture packets to browse live interfaces.');}
}
map.addEventListener('click',event=>{const element=event.target.closest('[data-capture-endpoints]');if(element)openLinkCapture(element);});
map.addEventListener('contextmenu',event=>{const element=event.target.closest('[data-capture-endpoints]');if(element){event.preventDefault();closeNodeMenu();openLinkCapture(element);}});
map.addEventListener('keydown',event=>{if(!['Enter',' '].includes(event.key))return;const element=event.target.closest('[data-capture-endpoints]');if(element){event.preventDefault();openLinkCapture(element);}});
