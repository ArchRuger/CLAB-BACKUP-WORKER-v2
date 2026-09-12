'use strict';
// Provider UI is intentionally separate from backups, SSH and the diagram editor.
const captureDialog=$('capture-dialog');
let captureRequest=0,captureTargets=[],captureLab='',captureNode='',captureHint='',captureTimer;
function clearCaptureLaunch(){
 clearTimeout(captureTimer);$('capture-launch').hidden=true;$('capture-launch').removeAttribute('href');
}
function invalidateCapture(){captureRequest++;clearCaptureLaunch();}
captureDialog.addEventListener('close',invalidateCapture);
$('capture-close').onclick=()=>captureDialog.close();
function captureSelected(){return captureTargets.find(t=>t.id===$('capture-target').value);}
function renderCaptureInterfaces(){
 invalidateCapture();const target=captureSelected();
 $('capture-interfaces').innerHTML=target?.interfaces.map(n=>`<label class="capture-interface"><input type="checkbox" value="${esc(n)}" ${captureHint===n?'checked':''}> <span>${esc(n)}</span></label>`).join('')||'<p>No capturable interfaces in this namespace.</p>';
 $('capture-prepare').disabled=!target?.interfaces.length;
 if(captureHint)$('capture-status').textContent=target?.interfaces.includes(captureHint)?`Selected live interface ${captureHint}.`:`Imported port ${captureHint} is not a live Linux interface name here. Select its Linux interface explicitly; NOS aliases can differ.`;
}
$('capture-target').onchange=renderCaptureInterfaces;
$('capture-interfaces').onchange=()=>{invalidateCapture();$('capture-prepare').disabled=!captureSelected()?.interfaces.length;$('capture-status').textContent='Selection changed. Prepare the capture again.';};
function filterCaptureTargets(){
 const previous=$('capture-target').value,query=$('capture-search').value.toLowerCase();
 const rows=captureTargets.filter(t=>[t.name,t.prefix,t.kind,...t.interfaces].join(' ').toLowerCase().includes(query));
 $('capture-target').innerHTML='<option value="">Choose a capture target</option>'+rows.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}${t.prefix?' · '+esc(t.prefix):''} (${esc(t.kind)}) · ${t.interfaces.length} interfaces</option>`).join('');
 if(rows.some(t=>t.id===previous))$('capture-target').value=previous;
 else if(rows.length===1)$('capture-target').value=rows[0].id;
 renderCaptureInterfaces();
}
$('capture-search').oninput=filterCaptureTargets;
async function refreshCaptureTargets(){
 invalidateCapture();const request=captureRequest;
 captureTargets=[];$('capture-target').innerHTML='';$('capture-interfaces').innerHTML='';$('capture-prepare').disabled=true;$('capture-search').disabled=true;
 $('capture-status').textContent='Discovering live capture targets…';
 try{
  const status=await(await api('/capture/status')).json();
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
 event.preventDefault();clearCaptureLaunch();const target=captureSelected();
 const interfaces=[...$('capture-interfaces').querySelectorAll('input:checked')].map(el=>el.value);
 if(!target||!interfaces.length){$('capture-status').textContent='Choose a target and at least one interface.';return;}
 const request=++captureRequest;$('capture-prepare').disabled=true;$('capture-status').textContent='Checking the selected namespace and interfaces…';
 try{
  const result=await json('/capture/launch','POST',{target_id:target.id,interfaces});
  if(request!==captureRequest||!captureDialog.open)return;
  // Defense in depth; only the provider's workstation protocol is navigable.
  if(!/^packetflix:wss?:\/\//.test(result.uri))throw new Error('Unsupported capture launch address.');
  $('capture-launch').href=result.uri;$('capture-launch').hidden=false;$('capture-status').textContent=result.message;
  captureTimer=setTimeout(()=>{clearCaptureLaunch();$('capture-status').textContent='Launch link expired. Prepare again to refresh the capture target.';},60000);
 }catch(error){if(request===captureRequest&&captureDialog.open)$('capture-status').textContent=error.message;}
 finally{if(request===captureRequest)$('capture-prepare').disabled=false;}
};
$('capture-launch').onclick=()=>{
 // No success claim: the browser cannot detect a native handler or live stream.
 $('capture-status').textContent='Wireshark handoff requested. Accept the browser prompt. If nothing opens, use Capture setup to install cshargextcap.';
};
function openLinkCapture(element){
 const pair=element.dataset.captureEndpoints;if(!pair)return;
 try{const ends=JSON.parse(pair);openCapture('', '', ends);$('capture-context').textContent='Choose either link endpoint below, then select its live Linux interface.';}
 catch{notify('Could not read this link. Use Capture packets to browse live interfaces.');}
}
map.addEventListener('click',event=>{const element=event.target.closest('[data-capture-endpoints]');if(element)openLinkCapture(element);});
map.addEventListener('contextmenu',event=>{const element=event.target.closest('[data-capture-endpoints]');if(element){event.preventDefault();closeNodeMenu();openLinkCapture(element);}});
map.addEventListener('keydown',event=>{if(!['Enter',' '].includes(event.key))return;const element=event.target.closest('[data-capture-endpoints]');if(element){event.preventDefault();openLinkCapture(element);}});
