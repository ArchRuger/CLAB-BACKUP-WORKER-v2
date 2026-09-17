'use strict';
// Provider UI is intentionally separate from backups, SSH and the diagram editor.
const captureDialog=$('capture-dialog');
let captureRequest=0,captureTargets=[],captureLab='',captureNode='',captureHint='',captureStarting=false,captureLaunchId='';
// The saved topology map decides which interfaces a node shows first: the ports it is
// wired with. Every other live Linux interface waits behind a toggle.
let captureDrawing,captureMapInterfaces=[];
// null until the provider status is known; node/menu Capture actions are disabled
// only when the manager reports capture disabled, so the toolbar entry and the
// dialog's setup link stay reachable.
let captureEnabled=null;
function captureActionAttrs(){return captureEnabled===false?'disabled title="Packet capture is not set up on this VM. See Tools › Packet capture for details."':'';}
// The Tools card caption when the service is missing; Capture traffic itself stays clickable so the
// dialog can explain the state and link to the setup page.
function captureStatusLine(){return captureEnabled===false?'Packet capture is not set up on this VM. Ask your instructor or administrator.':'';}
function renderCaptureCaption(){const el=$('capture-caption');if(!el)return;const text=captureStatusLine();el.innerHTML=text?esc(text)+' <a href="/static/capture-setup.html" target="_blank" rel="noopener">Setup guide <span aria-hidden="true">↗</span></a>':'';el.hidden=!text;}
// The service's own hints predate the dialog's labels.
function captureMessage(text){return String(text||'').replace(/All host targets/g,'"Everything on the VM" under Advanced');}
(async()=>{try{captureEnabled=!!(await(await api('/capture/status')).json()).enabled;}catch{captureEnabled=null;}renderCaptureCaption();})();
// The device picker unfolds by itself when no device is selected and reads as an advanced option otherwise.
function captureAdvancedLabel(){const el=$('capture-advanced-label');if(el)el.textContent=captureSelected()?'Advanced: capture somewhere else':'Choose a device';}
function clearCaptureLaunch(){
 $('capture-launch').hidden=true;$('capture-launch').removeAttribute('href');
}
function invalidateCapture(){captureRequest++;captureLaunchId='';clearCaptureLaunch();}
captureDialog.addEventListener('close',invalidateCapture);
$('capture-close').onclick=()=>captureDialog.close();
function captureSelected(){return captureTargets.find(t=>t.id===$('capture-target').value);}
function captureChecked(){return ['capture-interfaces','capture-interfaces-all'].flatMap(id=>[...$(id).querySelectorAll('input:checked')].map(el=>el.value));}
// Prepare needs a target and at least one ticked interface; a matching imported
// port counts because it is rendered ticked.
function updateCapturePrepare(preselected=false){const target=captureSelected();$('capture-prepare').disabled=captureStarting||!(target&&(preselected||captureChecked().length));}
function mapInterfacesFor(drawing,node){
 if(!node||!drawing||!Array.isArray(drawing.links)||!Array.isArray(drawing.nodes))return [];
 const ids=new Set(drawing.nodes.filter(n=>n.inventory_name===node).map(n=>n.id));
 return [...new Set(drawing.links.flatMap(pair=>pair.filter(ep=>ids.has(ep.node)).map(ep=>ep.interface)))];
}
function captureBox(name,checked){return `<label class="capture-interface"><input type="checkbox" value="${esc(name)}" ${checked?'checked':''}> <span>${esc(name)}</span></label>`;}
function renderCaptureInterfaces(){
 invalidateCapture();const target=captureSelected();
 const live=target?target.interfaces:[],mapped=captureNode?captureMapInterfaces:[];
 const primary=mapped.filter(n=>live.includes(n)),missing=mapped.filter(n=>!live.includes(n));
 // A link endpoint arrives ticked; a node wired with exactly one port starts ticked too.
 const hinted=captureHint?(live.includes(captureHint)?captureHint:''):primary.length===1?primary[0]:'';
 const usePrimary=primary.length>0,rest=usePrimary?live.filter(n=>!primary.includes(n)):[];
 $('capture-primary-legend').textContent=usePrimary?'Connected interfaces':'Interfaces';captureAdvancedLabel();
 $('capture-interfaces').innerHTML=!target?'<p>Choose a device above, or open Capture traffic from a device on the map.</p>':(usePrimary?primary:live).map(n=>captureBox(n,n===hinted)).join('')||'<p>This device has no interfaces that can be captured.</p>';
 $('capture-interfaces-all').innerHTML=rest.map(n=>captureBox(n,false)).join('');
 $('capture-more').hidden=!rest.length;$('capture-more').open=false;
 $('capture-more-label').textContent=`Other interfaces on this device (${rest.length})`;
 updateCapturePrepare(!!hinted);
 if(!target)return;
 if(hinted)$('capture-status').textContent=`${hinted} is selected — start the capture when you are ready.`;
 else if(captureHint)$('capture-status').textContent=`The diagram calls this port ${captureHint}, but the VM lists no interface with that name. Tick the matching interface below — device port names (ge-0/0/0) often map to eth1, eth2…`;
 else if(missing.length)$('capture-status').textContent=`Diagram port${missing.length>1?'s':''} ${missing.join(', ')} ${missing.length>1?'were':'was'} not found on the VM. Choose from the interfaces listed.`;
 else if(primary.length>1)$('capture-status').textContent='Tick the interfaces to capture.';
}
$('capture-target').onchange=renderCaptureInterfaces;
for(const id of ['capture-interfaces','capture-interfaces-all'])$(id).onchange=()=>{invalidateCapture();updateCapturePrepare();$('capture-status').textContent='Selection changed — start a new capture for these interfaces.';};
// "(kind)" only matters when the whole VM is listed; inside a lab every row is a device.
function captureTargetLabel(t){
 const aliases=t.aliases||[],shown=aliases.slice(0,2).join(', ')+(aliases.length>2?` +${aliases.length-2} more`:'');
 const shared=aliases.length?' · also: '+esc(shown):'',loopback=t.interfaces.length===1&&t.interfaces[0]==='lo'?' · loopback only':'';
 const kind=$('capture-scope').value==='host'&&t.kind?` (${esc(t.kind)})`:'';
 return `${esc(t.name)}${t.prefix?' · '+esc(t.prefix):''}${kind} · ${t.interfaces.length} interfaces${shared}${loopback}`;
}
function filterCaptureTargets(){
 const previous=$('capture-target').value,query=$('capture-search').value.toLowerCase();
 const rows=captureTargets.filter(t=>[t.name,t.prefix,t.kind,...(t.aliases||[]),...t.interfaces].join(' ').toLowerCase().includes(query));
 $('capture-target').innerHTML='<option value="">Choose a device…</option>'+rows.map(t=>`<option value="${esc(t.id)}">${captureTargetLabel(t)}</option>`).join('');
 if(rows.some(t=>t.id===previous))$('capture-target').value=previous;
 else if(rows.length===1)$('capture-target').value=rows[0].id;
 renderCaptureInterfaces();
}
$('capture-search').oninput=filterCaptureTargets;
async function refreshCaptureTargets(){
 invalidateCapture();const request=captureRequest;
 captureTargets=[];$('capture-target').innerHTML='';$('capture-interfaces').innerHTML='';$('capture-interfaces-all').innerHTML='';$('capture-more').hidden=true;$('capture-prepare').disabled=true;$('capture-search').disabled=true;
 $('capture-status').textContent='Looking up interfaces on the VM…';
 try{
  const status=await(await api('/capture/status')).json();
  captureEnabled=!!status.enabled;
  if(request!==captureRequest||!captureDialog.open)return;
  // The session list is asked for only once the service is known to exist; a disabled service is explained without a request.
  refreshCaptureSessions();
  if(!status.enabled){$('capture-status').textContent=status.message;$('capture-search').disabled=false;$('capture-advanced').open=true;captureAdvancedLabel();renderCaptureCaption();return;}
  if(captureDrawing===undefined&&captureLab){try{captureDrawing=await(await api('/labs/'+captureLab+'/topology')).json();}catch{captureDrawing=null;}}
  captureMapInterfaces=mapInterfacesFor(captureDrawing,captureNode);
  const params=new URLSearchParams();
  if($('capture-scope').value!=='host'&&captureLab){params.set('lab_id',captureLab);if(captureNode)params.set('node',captureNode);}
  const data=await(await api('/capture/targets?'+params)).json();
  if(request!==captureRequest||!captureDialog.open)return;
  captureTargets=data.targets;$('capture-search').disabled=false;
  $('capture-status').textContent=data.targets.length?captureMessage(data.message):'No running device matched. If it is still starting, wait and click Refresh interfaces; otherwise open Advanced and choose "Everything on the VM".';
  filterCaptureTargets();
  // The node you clicked is the target; the selector only unfolds when that could not be resolved.
  $('capture-advanced').open=!captureSelected();captureAdvancedLabel();
 }catch(error){if(request===captureRequest&&captureDialog.open){$('capture-status').textContent=error.message;$('capture-search').disabled=false;$('capture-advanced').open=true;captureAdvancedLabel();}}
}
function openCapture(node='',hint='',ends=null){
 captureLab=activeId;captureNode=node;captureHint=hint;captureDrawing=undefined;captureMapInterfaces=[];
 if($('details-dialog').open)$('details-dialog').close();
 $('capture-search').value='';$('capture-scope').value='lab';$('capture-advanced').open=false;
 // A link opens on its first endpoint; the endpoint buttons switch to the other side.
 if(ends&&!node&&ends[0]?.node){captureNode=ends[0].node;captureHint=ends[0].interface;}
 const endpoint=ends?.find(ep=>ep.node&&ep.node===captureNode);
 $('capture-context').textContent=endpoint?`Link endpoint: ${endpoint.label}: ${endpoint.interface}`:captureNode?`Device: ${captureNode}${captureHint?' · port '+captureHint:''}`:ends?'Choose which end of the link to capture on.':current()?.name?`Lab ${current().name} — choose a device below`:'Choose a device below';
 $('capture-endpoints').innerHTML=ends?ends.map((ep,i)=>`<button type="button" class="button secondary" data-capture-end="${i}">${esc(ep.label)}: ${esc(ep.interface)}</button>`).join(''):'';
 $('capture-endpoints').onclick=ends?event=>{const button=event.target.closest('[data-capture-end]');if(!button)return;const ep=ends[Number(button.dataset.captureEnd)];captureNode=ep.node||'';captureHint=ep.interface;$('capture-context').textContent=`Link endpoint: ${ep.label}: ${ep.interface}${ep.node?'':' · this diagram node is not in the inventory — choose its target under Advanced'}`;$('capture-scope').value=ep.node?'lab':'host';$('capture-search').value='';refreshCaptureTargets();}:null;
 if(!captureDialog.open)captureDialog.showModal();
 refreshCaptureTargets();
}
$('capture-open').onclick=()=>openCapture();
$('capture-refresh').onclick=refreshCaptureTargets;
$('capture-scope').onchange=()=>{captureHint='';refreshCaptureTargets();};
$('capture-form').onsubmit=async event=>{
 event.preventDefault();if(captureStarting)return;clearCaptureLaunch();const target=captureSelected();
 const interfaces=captureChecked();
 if(!target||!interfaces.length){$('capture-status').textContent='Choose a device and tick at least one interface.';return;}
 const request=++captureRequest;captureStarting=true;$('capture-prepare').disabled=true;$('capture-status').textContent='Checking the interfaces and starting Wireshark on the VM…';
 if(!captureLaunchId)captureLaunchId=Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,'0')).join('');
 try{
  const result=await json('/capture/launch','POST',{target_id:target.id,interfaces,request_id:captureLaunchId});
  refreshCaptureSessions();
  if(request!==captureRequest||!captureDialog.open)return;
  if(!/^\/static\/capture-session\.html#[0-9a-f]{64}$/.test(result.url))throw new Error('Unsupported capture link — reopen Capture traffic and try again.');
  captureLaunchId=''; // A deliberate subsequent Start creates a new session; uncertain retries reuse their key.
  $('capture-launch').href=result.url;$('capture-launch').hidden=false;$('capture-status').textContent=result.message;
 }catch(error){if(request===captureRequest&&captureDialog.open)$('capture-status').textContent=error.message;}
 finally{captureStarting=false;updateCapturePrepare();}
};
$('capture-launch').onclick=()=>{$('capture-status').textContent='Wireshark opened in a new tab. The session and its saved files stay on the VM until you end it or it expires (2 hours).';};
let captureSessionRequest=0;
async function refreshCaptureSessions(){
 const request=++captureSessionRequest;
 if(captureEnabled===false){$('capture-sessions').innerHTML='<li>Packet capture is not set up on this VM, so there are no sessions to list.</li>';return;}
 try{
  const data=await(await api('/capture/sessions')).json();
  if(request!==captureSessionRequest)return;
  $('capture-sessions').innerHTML=(data.sessions||[]).map(s=>{
   if(!/^[0-9a-f]{64}$/.test(s.id))return '';
   return `<li><a href="/static/capture-session.html#${s.id}" target="_blank" rel="noopener">${esc(s.name)} · ${esc(s.interfaces.join(', '))}</a> <button type="button" class="button secondary" data-end-capture="${s.id}">End session</button></li>`;
  }).join('')||'<li>No capture sessions yet.</li>';
 }catch{$('capture-sessions').textContent='Could not list capture sessions — packet capture may not be set up on this VM. See Setup and troubleshooting.';}
}
// While the service is reported missing, Refresh list asks the manager again instead of repeating the local note.
$('capture-sessions-refresh').onclick=()=>captureEnabled===false?refreshCaptureTargets():refreshCaptureSessions();
$('capture-sessions').onclick=async event=>{
 const button=event.target.closest('[data-end-capture]');if(!button)return;
 if(!confirm('End this Wireshark session and delete its capture files? Download saved files first.'))return;
 button.disabled=true;
 try{await json('/capture/sessions/'+button.dataset.endCapture+'/end','POST',{});await refreshCaptureSessions();}
 catch(error){$('capture-status').textContent=error.message;button.disabled=false;}
};
function openLinkCapture(element){
 const pair=element.dataset.captureEndpoints;if(!pair)return;
 try{openCapture('', '', JSON.parse(pair));}
 catch{notify('Could not read this link. Open Tools › Packet capture and choose the interface there.');}
}
map.addEventListener('click',event=>{const element=event.target.closest('[data-capture-endpoints]');if(element)openLinkCapture(element);});
map.addEventListener('contextmenu',event=>{const element=event.target.closest('[data-capture-endpoints]');if(element){event.preventDefault();closeNodeMenu();openLinkCapture(element);}});
map.addEventListener('keydown',event=>{if(!['Enter',' '].includes(event.key))return;const element=event.target.closest('[data-capture-endpoints]');if(element){event.preventDefault();openLinkCapture(element);}});
