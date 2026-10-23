'use strict';
// Provider UI is intentionally separate from backups, SSH and the diagram editor.
const captureDialog=$('capture-dialog');
let captureRequest=0,captureTargets=[],captureLab='',captureNode='',captureHint='',captureStarting=false,captureLaunchId='';
// Dialog modes: 'device' (a device and its interfaces; also the Tools card with a device chosen under Advanced) and
// 'link' (both ends of a wire, one checkbox each). captureOptions is {preset, end} from openCapture; captureLimit is the
// service's slot cap (read with the status, 4 when it does not say); captureStarted lists what a partial result already
// started (interface names in device mode, end indexes in link mode); captureLinks are the viewer links on show.
let captureMode='device',captureEnds=[],captureEndInfo=[],captureOptions={},captureLimit=4,captureConnected=[];
let captureStarted=[],captureFirstPlan=null,captureLinks=[],captureEnding=false;
let captureSessionsState={rows:[],fetched:false},captureSessionsHtml=null;
// captureDone: a full success is on screen, so Start waits for a changed selection. captureOpener: where focus returns when the dialog closes.
let captureDone=false,captureOpener=null;
// The saved topology map decides which interfaces a node shows first: the ports it is
// wired with. Every other live Linux interface waits behind a toggle.
let captureDrawing,captureMapInterfaces=[],captureMapCapture={};
// null until the provider status is known; node/menu Capture actions are disabled
// only when the manager reports capture disabled, so the toolbar entry and the
// dialog's setup link stay reachable.
let captureEnabled=null;
function captureActionAttrs(){return captureEnabled===false?'disabled title="Packet capture is not set up on this VM. See Tools › Packet capture for details."':'';}
// The Tools card caption when the service is missing; Capture traffic itself stays clickable so the
// dialog can explain the state and link to the setup page.
function captureStatusLine(){return captureEnabled===false?'Packet capture is not set up on this VM. Ask your instructor or administrator.':'';}
function renderCaptureCaption(){const el=$('capture-caption');if(!el)return;const text=captureStatusLine();el.innerHTML=text?esc(text)+' <a href="/static/capture-setup.html" target="_blank" rel="noopener">Setup guide <span aria-hidden="true">↗</span></a>':'';el.hidden=!text;paintCaptureCard();}
// The service's own hints predate the dialog's labels.
function captureMessage(text){return String(text||'').replace(/All host targets/g,'"Everything on the VM" under Advanced');}
(async()=>{try{captureEnabled=!!(await(await api('/capture/status')).json()).enabled;}catch{captureEnabled=null;}renderCaptureCaption();})();
// The device picker unfolds by itself when no device is selected and reads as an advanced option otherwise (link mode never unfolds it).
function captureAdvancedLabel(){const el=$('capture-advanced-label');if(el)el.textContent=captureMode==='link'||captureSelected()?'Advanced: capture somewhere else':'Choose a device';}
function setCaptureMode(mode){captureMode=mode;if(typeof captureDialog.setAttribute==='function')captureDialog.setAttribute('data-mode',mode);$('capture-ends').hidden=mode!=='link';}
function clearCaptureLaunch(){captureLinks=[];const el=$('capture-launches');el.innerHTML='';el.hidden=true;}
function invalidateCapture(){captureRequest++;captureDone=false;captureLaunchId='';captureStarted=[];captureFirstPlan=null;clearCaptureLaunch();}
// Closing the dialog returns focus to what opened it: the wire (found again by its ends when the map was redrawn) for a wire or a menu item.
function restoreCaptureFocus(){
 const opener=captureOpener;captureOpener=null;if(!opener)return;
 let el=opener.el;
 if(el&&el.isConnected===false&&opener.key&&typeof map.querySelectorAll==='function')el=[...map.querySelectorAll('[data-capture-endpoints]')].find(e=>e.dataset.captureEndpoints===opener.key)||null;
 if(el&&typeof el.focus==='function')el.focus();
}
captureDialog.addEventListener('close',()=>{invalidateCapture();restoreCaptureFocus();});
$('capture-close').onclick=()=>captureDialog.close();
function captureSelected(){return captureTargets.find(t=>t.id===$('capture-target').value);}
function captureChecked(){return ['capture-interfaces','capture-interfaces-all'].flatMap(id=>[...$(id).querySelectorAll('input:checked')].map(el=>el.value));}
function captureTickedNames(){return captureChecked().filter(n=>!captureStarted.includes(n));}
function captureTickedEnds(){return [...$('capture-ends-list').querySelectorAll('input:checked')].map(el=>Number(el.dataset.captureEnd)).filter(i=>!captureStarted.includes(i));}
function captureSeparate(){return !!$('capture-openas-each').checked;}
function captureIsTap(name){return /^tap\d+$/i.test(name);}
// The device as the student knows it (the short name), the container name when the inventory does not say.
function captureDeviceName(name){const node=typeof current==='function'?current()?.nodes?.find(n=>n.name===name):null;return (node&&(node.short_name||node.name))||name;}
// The plan before Start: pure. mode 'device': ticked = interface names, device = its name. mode 'link': ends = the ticked
// ends as {label, port, veth, targetId}; separate matters only when both ends are on one device.
function captureSummary(mode,ticked,separate,ends,device){
 if(mode==='link'){
  const list=ends||[],named=e=>`${e.label} ${e.port}${e.veth&&e.veth!==e.port?` (${e.veth})`:''}`;
  if(!list.length)return {sessions:0,button:'Start capture',text:'Tick at least one end of the link.'};
  if(list.length===1)return {sessions:1,button:'Start capture',text:`One end: ${named(list[0])}.`};
  if(list[0].targetId===list[1].targetId){
   const veths=[...new Set(list.map(e=>e.veth))];
   if(separate&&veths.length>1)return {sessions:2,button:'Start 2 captures',text:`Both ends are on ${list[0].label}: one Wireshark per interface, ${veths.join(', ')} (2 sessions).`};
   return {sessions:1,button:'Start capture',text:`Both ends are on ${list[0].label}: one Wireshark for ${veths.join(', ')}.`};
  }
  return {sessions:2,button:'Start 2 captures',text:`Both ends of the link: ${named(list[0])} and ${named(list[1])}, one Wireshark each (2 sessions).`};
 }
 const names=(ticked||[]).join(', '),n=(ticked||[]).length,on=device?` on ${device}`:'';
 if(!n)return {sessions:0,button:'Start capture',text:''};
 if(separate&&n>1)return {sessions:n,button:`Start ${n} captures`,text:`One Wireshark per interface: ${names}${on} (${n} sessions).`};
 return {sessions:1,button:'Start capture',text:n>1?`One Wireshark for ${names}${on} (or one Wireshark per interface, under Open as).`:`One Wireshark for ${names}${on}.`};
}
// One end of a link as the plan and the request need it (only a resolved end has a veth and a target).
function captureEndDescriptor(i){const x=captureEndInfo[i];return x&&x.ok?{index:i,label:x.ep.label,port:x.ep.interface,veth:x.veth,targetId:x.target.id,node:x.ep.node}:null;}
// The plan for what is ticked: the summary, the request entries (target + interface names only) and which end each entry covers.
function capturePlan(ticked){
 if(captureMode==='link'){
  const ends=ticked.map(captureEndDescriptor).filter(Boolean),same=ends.length===2&&ends[0].targetId===ends[1].targetId,separate=same&&captureSeparate();
  const sum=captureSummary('link',[],separate,ends);
  let entries,entryEnds;
  if(same&&!separate){entries=[{target_id:ends[0].targetId,interfaces:[...new Set(ends.map(e=>e.veth))]}];entryEnds=[ends.map(e=>e.index)];}
  else{entries=ends.map(e=>({target_id:e.targetId,interfaces:[e.veth]}));entryEnds=ends.map(e=>[e.index]);}
  return {...sum,entries,entryEnds,openAs:same,separate,ends,ticked:ends.map(e=>e.index),label:ends.map(e=>`${e.label} ${e.port}`).join(' + ')};
 }
 const target=captureSelected(),separate=ticked.length>1&&captureSeparate(),device=target?captureDeviceName(target.name):'';
 const sum=captureSummary('device',ticked,separate,null,device);
 const entries=!target||!ticked.length?[]:separate?ticked.map(n=>({target_id:target.id,interfaces:[n]})):[{target_id:target.id,interfaces:ticked}];
 return {...sum,entries,entryEnds:entries.map(e=>e.interfaces),openAs:ticked.length>1,separate,ends:[],ticked:[...ticked],label:`${device} ${ticked.join(', ')}`.trim()};
}
// Start needs a target (or a resolvable end) and at least one ticked interface; `initial` is what the last render ticked
// (the boxes are not in the DOM yet in a harness), otherwise the DOM decides. Returns the plan.
function updateCapturePrepare(initial){
 const link=captureMode==='link',ticked=Array.isArray(initial)?initial:link?captureTickedEnds():captureTickedNames(),plan=capturePlan(ticked);
 $('capture-prepare').disabled=captureStarting||captureDone||!ticked.length||(!link&&!captureSelected());
 $('capture-prepare').textContent=captureStarted.length?`Start the remaining ${plan.sessions}`:plan.button;
 $('capture-openas').hidden=!plan.openAs;
 return plan;
}
function mapInterfacesFor(drawing,node){
 if(!node||!drawing||!Array.isArray(drawing.links)||!Array.isArray(drawing.nodes))return [];
 const ids=new Set(drawing.nodes.filter(n=>n.inventory_name===node).map(n=>n.id));
 return [...new Set(drawing.links.flatMap(pair=>pair.filter(ep=>ids.has(ep.node)).map(ep=>ep.interface)))];
}
// The container veth each of this node's drawn ports maps to, as computed server-side
// (app/topology.py bind_drawing) from containerlab's own per-kind port order — never guessed
// here. A port with no recognised mapping (unknown kind, or a shape container_interface does
// not understand) is simply absent from the result.
function mapCaptureInterfacesFor(drawing,node){
 if(!node||!drawing||!Array.isArray(drawing.links)||!Array.isArray(drawing.nodes))return {};
 const ids=new Set(drawing.nodes.filter(n=>n.inventory_name===node).map(n=>n.id));
 const result={};
 for(const pair of drawing.links)for(const ep of pair)if(ids.has(ep.node)&&ep.capture_interface)result[ep.interface]=ep.capture_interface;
 return result;
}
// A remembered selection applies only when the dialog was opened without a specific port in mind: a hint, a chosen end or a
// preset is the student's current intent and wins. The same condition governs writing it (a one-time choice never rewrites it).
function captureMemoryAllowed(){return !captureHint&&!captureOptions.preset&&!captureOptions.both&&captureOptions.end==null;}
// A box carries the container interface (what the capture runs on) and, when the diagram names that
// port differently (ge-0/0/0 on eth1), the device's own port name beside it. A started one (after a partial result) is disabled.
function captureBox(name,checked,port,done){return `<label class="capture-interface"><input type="checkbox" value="${esc(name)}"${checked&&!done?' checked':''}${done?' disabled':''}> <span>${esc(name)}</span>${port&&port!==name?` <small>${esc(port)}</small>`:''}${done?' <small>started (open it above)</small>':''}</label>`;}
// opts: {keep:true} repaints without resetting the request or the status; {ticked:[…]} ticks exactly those.
function renderCaptureInterfaces(opts){
 const keep=!!(opts&&opts.keep);if(!keep)invalidateCapture();const target=captureSelected();
 const live=target?target.interfaces:[];
 // The diagram's ports are compared with the VM's list through their container names (ge-0/0/0 is eth1 on
 // a vJunos, Gi0/0/0/0 is eth1 on an XRv9k): a port whose veth the VM lists is a connected interface, and
 // "not found" is said only of a port whose veth really is absent. A port with no known mapping is looked
 // for under its own name, as a linux node's eth1 is.
 const ports=captureNode?captureMapInterfaces:[],veth=port=>captureMapCapture[port]||port;
 const portOf={};for(const port of ports)portOf[veth(port)]=port;
 const mapped=[...new Set(ports.map(veth))];
 const primary=mapped.filter(n=>live.includes(n)),missing=ports.filter(port=>!live.includes(veth(port)));
 // The tap device is the VM side of a vJunos-style image's own management link; the veth
 // (ethN) is what containerlab's Wireshark integration captures on, so a mapped port is never
 // preselected onto a tapN name even if discovery happens to list one.
 const isTap=captureIsTap;
 const mappedHint=captureHint?captureMapCapture[captureHint]||'':'';
 // A link endpoint arrives ticked once its container interface is confirmed live; a node
 // wired with exactly one port starts ticked too.
 let hinted='',hintReason='';
 if(captureHint){
  if(mappedHint&&!isTap(mappedHint)&&live.includes(mappedHint))hinted=mappedHint;
  else if(!mappedHint&&live.includes(captureHint))hinted=captureHint;
  else if(mappedHint)hintReason=`The VM lists no ${mappedHint} for ${captureHint} yet: the node may still be starting, or the topology changed. Tick the interface to use.`;
  else hintReason=`The diagram calls this port ${captureHint}, but the VM lists no interface with that name. Tick the matching interface below — device port names (ge-0/0/0) often map to eth1, eth2…`;
 }else if(primary.length===1)hinted=primary[0];
 const usePrimary=primary.length>0,rest=usePrimary?live.filter(n=>!primary.includes(n)):[];
 // What is ticked: the caller's list, a preset (C03's Capture all connected), the remembered selection (live names only), or the hint.
 let ticked=[],restored=false,presetMissing=[],memory=null;
 if(opts&&opts.ticked)ticked=opts.ticked.filter(n=>live.includes(n));
 else if(captureOptions.preset){ticked=captureOptions.preset.filter(n=>live.includes(n));presetMissing=captureOptions.preset.filter(n=>!live.includes(n));}
 else{
  memory=target&&captureMemoryAllowed()&&typeof captureMemory==='function'?captureMemory(captureLab,'node:'+target.name):null;
  const kept=memory?memory.interfaces.filter(n=>live.includes(n)):[];
  if(kept.length){ticked=kept;restored=true;}else{memory=null;if(hinted)ticked=[hinted];}
 }
 const done=n=>captureStarted.includes(n);
 $('capture-primary-legend').textContent=usePrimary?'Connected interfaces':'Interfaces';captureAdvancedLabel();
 $('capture-interfaces').innerHTML=!target?'<p>Choose a device above, or open Capture traffic from a device on the map.</p>':(usePrimary?primary:live).map(n=>captureBox(n,ticked.includes(n),portOf[n],done(n))).join('')||'<p>This device has no interfaces that can be captured.</p>';
 $('capture-interfaces-all').innerHTML=rest.map(n=>captureBox(n,ticked.includes(n),portOf[n],done(n))).join('');
 // Never tick a box out of sight: a preset or the memory that ticks one under the toggle opens it.
 $('capture-more').hidden=!rest.length;$('capture-more').open=rest.some(n=>ticked.includes(n))||(keep&&!!$('capture-more').open&&!!rest.length);
 $('capture-more-label').textContent=`Other interfaces on this device (${rest.length})`;
 captureConnected=usePrimary?primary.filter(n=>!isTap(n)&&n!=='eth0'&&n!=='lo'):[];
 $('capture-presets').hidden=!(usePrimary&&primary.length>=2);
 if(!keep){const separate=memory?memory.separate:(typeof captureOpenAs==='function'?captureOpenAs()==='each':false);$('capture-openas-one').checked=!separate;$('capture-openas-each').checked=separate;}
 const plan=updateCapturePrepare(ticked);
 if(keep||!target)return plan;
 const lead=restored?'Your last selection here was restored. ':'';
 if(restored)$('capture-status').textContent=lead+plan.text;
 else if(captureOptions.preset)$('capture-status').textContent=(presetMissing.length?`Diagram port${presetMissing.length>1?'s':''} ${presetMissing.join(', ')} ${presetMissing.length>1?'were':'was'} not found on the VM. Choose from the interfaces listed. `:'')+plan.text;
 else if(hinted&&hinted===mappedHint&&hinted!==captureHint)$('capture-status').textContent=`Capturing ${captureNode} port ${captureHint} (container interface ${hinted}) — start the capture when you are ready.`;
 else if(hinted)$('capture-status').textContent=`${hinted} is selected — start the capture when you are ready.`;
 else if(hintReason)$('capture-status').textContent=hintReason;
 else if(missing.length)$('capture-status').textContent=`Diagram port${missing.length>1?'s':''} ${missing.join(', ')} ${missing.length>1?'were':'was'} not found on the VM. Choose from the interfaces listed.`;
 else if(primary.length>1)$('capture-status').textContent='Tick the interfaces to capture.';
 return plan;
}
// Where a link end lands: its target (the container the diagram node is), the veth the diagram port maps to, or the reason it cannot be captured now.
function resolveCaptureEnd(ep){
 const info={ep,ok:false,reason:'',veth:'',target:null};
 if(!ep.node){info.reason='this diagram node is not in the inventory — choose its device under Advanced';return info;}
 const target=captureTargets.find(t=>t.name===ep.node);
 if(!target||!(target.interfaces||[]).length){info.reason=`${ep.label} is not running on the VM (no live interfaces), so this end cannot be captured now.`;return info;}
 const mapped=mapCaptureInterfacesFor(captureDrawing,ep.node)[ep.interface]||'',live=target.interfaces;
 if(mapped){
  if(captureIsTap(mapped)||!live.includes(mapped)){info.reason=`The VM lists no ${mapped} for ${ep.interface} yet: the device may still be starting, or the topology changed.`;return info;}
  info.veth=mapped;
 }else if(live.includes(ep.interface))info.veth=ep.interface;
 else{info.reason=`The diagram calls this port ${ep.interface}, but the VM lists no interface with that name.`;return info;}
 info.ok=true;info.target=target;info.reason=`${info.veth} live`;return info;
}
function captureLinkScope(){return 'link:'+captureEnds.map(e=>`${e.node||e.label}:${e.interface}`).join('|');}
// Link mode: one checkbox per end, ticked when the VM lists its interface; an end that cannot be captured says why and offers
// the old way (Choose the interface on <device>…). opts as renderCaptureInterfaces; ticked are end indexes.
function renderCaptureEnds(opts){
 const keep=!!(opts&&opts.keep);if(!keep)invalidateCapture();
 captureEndInfo=captureEnds.map(resolveCaptureEnd);
 const info=captureEndInfo,okIndexes=info.map((x,i)=>x.ok?i:-1).filter(i=>i>=0);
 let ticked=[],restored=false,memory=null;
 if(opts&&opts.ticked)ticked=opts.ticked.filter(i=>info[i]&&info[i].ok);
 else if(captureOptions.end!=null)ticked=okIndexes.filter(i=>i===captureOptions.end);
 else{
  memory=captureMemoryAllowed()&&typeof captureMemory==='function'?captureMemory(captureLab,captureLinkScope()):null;
  const kept=memory&&memory.ends?okIndexes.filter(i=>memory.ends[i]):[];
  if(kept.length){ticked=kept;restored=true;}else{memory=null;ticked=okIndexes;}
 }
 const row=(x,i)=>{
  // The veth is printed only when it differs from the port (as captureBox does); a live end needs no sentence, a started one is a line of its own.
  const done=captureStarted.includes(i),text=done?'Started: open it with the link below.':x.ok?'':x.reason;
  return `<div class="capture-end"><label class="capture-interface"><input type="checkbox" data-capture-end="${i}"${ticked.includes(i)&&!done?' checked':''}${x.ok&&!done?'':' disabled'}> <span>${esc(x.ep.label)}: ${esc(x.ep.interface)}</span>${x.ok&&x.veth!==x.ep.interface?` <small>${esc(x.veth)}</small>`:''}</label>`
   +(text?`<p class="form-help">${esc(text)}</p>`:'')
   +(x.ok||done?'':`<button type="button" class="button secondary small" data-capture-choose="${i}">Choose the interface on ${esc(x.ep.label)}…</button>`)+'</div>';
 };
 $('capture-ends-list').innerHTML=info.map(row).join('');
 captureAdvancedLabel();
 if(!keep){const separate=memory?memory.separate:(typeof captureOpenAs==='function'?captureOpenAs()==='each':false);$('capture-openas-one').checked=!separate;$('capture-openas-each').checked=separate;}
 const plan=updateCapturePrepare(ticked);
 if(keep)return plan;
 $('capture-status').textContent=!okIndexes.length?'Neither end of this link is on the VM right now. Start the lab, or choose the interface by hand below.':(restored?'Your last selection here was restored. ':'')+plan.text;
 return plan;
}
$('capture-target').onchange=()=>{
 const target=captureSelected();
 if(captureMode==='link'){
  // Choosing a device under Advanced leaves link mode for that device.
  if(!target){renderCaptureEnds();return;}
  setCaptureMode('device');captureEnds=[];captureNode=target.name;captureHint='';captureOptions={};
  captureMapInterfaces=mapInterfacesFor(captureDrawing,captureNode);captureMapCapture=mapCaptureInterfacesFor(captureDrawing,captureNode);
  $('capture-context').textContent=`Device: ${captureNode}`;
 }
 renderCaptureInterfaces();
};
// A change of the selection (a box, Open as, a preset) is a new capture: the request id, the started marks and the links reset,
// and the plan is said in the status line.
function captureSelectionChanged(ticks){
 const wasPartial=captureStarted.length>0,link=captureMode==='link';invalidateCapture();
 let ticked=ticks||(link?captureTickedEnds():captureChecked());
 if(wasPartial||ticks)link?renderCaptureEnds({keep:true,ticked}):renderCaptureInterfaces({keep:true,ticked});
 const plan=updateCapturePrepare(link?ticked:ticked.filter(n=>captureSelected()&&captureSelected().interfaces.includes(n)));
 $('capture-status').textContent=plan.text||(link?'Tick at least one end of the link.':'Choose a device and tick at least one interface.');
}
for(const id of ['capture-interfaces','capture-interfaces-all'])$(id).onchange=()=>captureSelectionChanged();
$('capture-ends').onchange=()=>captureSelectionChanged();
$('capture-openas').onchange=()=>captureSelectionChanged();
$('capture-all').onclick=()=>captureSelectionChanged(captureConnected.slice());
$('capture-none').onclick=()=>captureSelectionChanged([]);
// The old endpoint button, kept per end: leave link mode for device mode on that end, with today's hint and sentences.
$('capture-ends').onclick=event=>{
 const button=event.target&&event.target.closest?event.target.closest('[data-capture-choose]'):null;if(!button)return;
 const ep=captureEnds[Number(button.dataset.captureChoose)];if(!ep)return;
 captureNode=ep.node||'';captureHint=ep.interface;captureOptions={};captureEnds=[];setCaptureMode('device');
 $('capture-context').textContent=captureNode?`Device: ${captureNode} · port ${ep.interface}`:`Link endpoint: ${ep.label}: ${ep.interface} · this diagram node is not in the inventory — choose its target under Advanced`;
 $('capture-scope').value=ep.node?'lab':'host';
 refreshCaptureTargets();
};
// "(kind)" only matters when the whole VM is listed; inside a lab every row is a device.
function captureTargetLabel(t){
 const aliases=t.aliases||[],shown=aliases.slice(0,2).join(', ')+(aliases.length>2?` +${aliases.length-2} more`:'');
 const shared=aliases.length?' · also: '+esc(shown):'',loopback=t.interfaces.length===1&&t.interfaces[0]==='lo'?' · loopback only':'';
 const kind=$('capture-scope').value==='host'&&t.kind?` (${esc(t.kind)})`:'';
 return `${esc(t.name)}${t.prefix?' · '+esc(t.prefix):''}${kind} · ${t.interfaces.length} interfaces${shared}${loopback}`;
}
function filterCaptureTargets(){
 const previous=$('capture-target').value,rows=captureTargets;
 $('capture-target').innerHTML='<option value="">Choose a device…</option>'+rows.map(t=>`<option value="${esc(t.id)}">${captureTargetLabel(t)}</option>`).join('');
 if(rows.some(t=>t.id===previous))$('capture-target').value=previous;
 else if(rows.length===1&&captureMode!=='link')$('capture-target').value=rows[0].id;
 if(captureMode==='link')renderCaptureEnds();else renderCaptureInterfaces();
}
async function refreshCaptureTargets(){
 invalidateCapture();const request=captureRequest;
 captureTargets=[];$('capture-target').innerHTML='';$('capture-interfaces').innerHTML='';$('capture-interfaces-all').innerHTML='';$('capture-ends-list').innerHTML='';$('capture-more').hidden=true;$('capture-presets').hidden=true;$('capture-prepare').disabled=true;
 $('capture-status').textContent='Looking up interfaces on the VM…';
 try{
  const status=await(await api('/capture/status')).json();
  captureEnabled=!!status.enabled;
  if(request!==captureRequest||!captureDialog.open)return;
  // The session list is asked for only once the service is known to exist; a disabled service is explained without a request.
  refreshCaptureSessions();
  if(!status.enabled){$('capture-status').textContent=status.message;$('capture-advanced').open=true;captureAdvancedLabel();renderCaptureCaption();return;}
  try{const health=await(await api('/capture/health')).json(),max=health&&health.max_sessions;captureLimit=Number.isInteger(max)&&max>=1&&max<=64?max:4;}catch{captureLimit=4;}
  if(request!==captureRequest||!captureDialog.open)return;
  if(captureDrawing===undefined&&captureLab){try{captureDrawing=await(await api('/labs/'+captureLab+'/topology')).json();}catch{captureDrawing=null;}}
  captureMapInterfaces=mapInterfacesFor(captureDrawing,captureNode);
  captureMapCapture=mapCaptureInterfacesFor(captureDrawing,captureNode);
  const params=new URLSearchParams();
  if($('capture-scope').value!=='host'&&captureLab){params.set('lab_id',captureLab);if(captureNode&&captureMode!=='link')params.set('node',captureNode);}
  const data=await(await api('/capture/targets?'+params)).json();
  if(request!==captureRequest||!captureDialog.open)return;
  captureTargets=data.targets;
  $('capture-status').textContent=data.targets.length?captureMessage(data.message):'No running device matched. If it is still starting, wait and click Refresh interfaces; otherwise open Advanced and choose "Everything on the VM".';
  filterCaptureTargets();
  // The node you clicked is the target; the selector only unfolds when that could not be resolved (never in link mode: both ends are the targets).
  if(captureMode!=='link')$('capture-advanced').open=!captureSelected();
  captureAdvancedLabel();
 }catch(error){if(request===captureRequest&&captureDialog.open){$('capture-status').textContent=error.message;$('capture-advanced').open=true;captureAdvancedLabel();}}
}
// openCapture(node, hint, ends, options): ends = the two ends of a wire ([{node, label, interface}]) opens link mode;
// options.end (0/1) opens link mode with that end only; options.preset (interface names) ticks exactly those on node.
function openCapture(node='',hint='',ends=null,options=null){
 captureLab=activeId;captureNode=node;captureHint=hint;captureOptions=options||{};captureDrawing=undefined;captureMapInterfaces=[];captureMapCapture={};
 if($('details-dialog').open)$('details-dialog').close();
 $('capture-scope').value='lab';$('capture-advanced').open=false;
 const link=Array.isArray(ends)&&ends.length===2&&!node;
 captureEnds=link?ends:[];setCaptureMode(link?'link':'device');
 $('capture-context').textContent=link?`Link: ${ends[0].label}: ${ends[0].interface} — ${ends[1].label}: ${ends[1].interface}`:node?`Device: ${node}${hint?' · port '+hint:''}`:current()?.name?`Lab ${current().name} — choose a device below`:'Choose a device below';
 if(!captureDialog.open)captureDialog.showModal();
 refreshCaptureTargets();
}
$('capture-open').onclick=()=>openCapture();
$('capture-refresh').onclick=refreshCaptureTargets;
$('capture-scope').onchange=()=>{captureHint='';captureOptions={};refreshCaptureTargets();};
// Slots are counted before anything starts, in the sentence that names a way out for the mode. The server repeats the check;
// a retry that keeps its request id skips this one (the server leaves that request's own sessions out of the count).
const captureWireshark=n=>`${n} Wireshark ${n===1?'session':'sessions'}`;
async function captureSlotRefusal(plan,retry){
 const planned=plan.entries.length,distinct=new Set(plan.entries.map(e=>e.target_id)).size;
 if(planned>captureLimit)return `${planned} separate Wireshark sessions are more than the limit of ${captureLimit} at a time. Untick interfaces, or open one Wireshark for all of them.`;
 if(retry)return '';
 let own;
 try{const data=await(await api('/capture/sessions')).json();own=(data.sessions||[]).length;}catch{return '';}
 if(planned===1)return own>=captureLimit?`You already have ${captureWireshark(own)} running from this browser, the limit at a time. End a session under Your capture sessions first.`:'';
 if(own+planned<=captureLimit)return '';
 return distinct>1
  ?`You already have ${captureWireshark(own)} running from this browser; both ends would pass the limit of ${captureLimit} at a time. End a session under Your capture sessions, or untick one end.`
  :`You already have ${captureWireshark(own)} running from this browser; ${planned} more would pass the limit of ${captureLimit} at a time. End a session under Your capture sessions, untick interfaces, or open one Wireshark for all of them.`;
}
function paintCaptureLaunches(){
 const el=$('capture-launches');
 el.innerHTML=captureLinks.map(l=>`<a class="button primary" data-capture-open="${esc(l.label)}" target="_blank" rel="noopener" href="${esc(l.url)}">Open Wireshark${l.label?': '+esc(l.label):''} <span aria-hidden="true">↗</span></a>`).join('');
 el.hidden=!captureLinks.length;
}
// What a full success remembers: the ticked set and the mode as started, under the same condition that lets memory be read.
function captureRememberNow(plan){
 if(!plan||!captureMemoryAllowed()||typeof rememberCapture!=='function')return;
 if(captureMode==='link')rememberCapture(captureLab,captureLinkScope(),{interfaces:plan.ends.map(e=>e.veth),separate:!!plan.separate,ends:[0,1].map(i=>plan.ticked.includes(i))});
 else{const target=captureSelected();if(target)rememberCapture(captureLab,'node:'+target.name,{interfaces:plan.ticked,separate:!!plan.separate});}
 if(plan.openAs&&typeof rememberOpenAs==='function')rememberOpenAs(plan.separate?'each':'one');
}
// Which submitted entry a refusal belongs to: by its position ("Capture 2 of 2"), else by its interfaces.
function captureRefusedIndex(refusal,entries){
 const n=Number(String(refusal.position||'').match(/Capture (\d+)/)?.[1]);
 if(n>=1&&n<=entries.length)return n-1;
 return entries.findIndex(e=>e.interfaces.join('/')===(refusal.interfaces||[]).join('/'));
}
$('capture-form').onsubmit=async event=>{
 event.preventDefault();if(captureStarting)return;
 const link=captureMode==='link',plan=capturePlan(link?captureTickedEnds():captureTickedNames());
 if(!plan.entries.length){$('capture-status').textContent=link?'Tick at least one end of the link.':'Choose a device and tick at least one interface.';return;}
 const retry=!!captureLaunchId;if(!retry)clearCaptureLaunch();
 const request=++captureRequest;captureStarting=true;$('capture-prepare').disabled=true;$('capture-status').textContent='Checking the interfaces and starting Wireshark on the VM…';
 if(!captureLaunchId){captureLaunchId=Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,'0')).join('');captureFirstPlan=plan;}
 try{
  const refusal=await captureSlotRefusal(plan,retry);
  if(request!==captureRequest||!captureDialog.open)return;
  if(refusal){if(!retry){captureLaunchId='';captureFirstPlan=null;}$('capture-status').textContent=refusal;return;}
  // A narrowed retry keeps the set form even with one entry: only the set form derives the per-entry service ids from the request id.
  const setForm=plan.entries.length>1||(captureFirstPlan&&captureFirstPlan.entries.length>1);
  const body=!setForm?{target_id:plan.entries[0].target_id,interfaces:plan.entries[0].interfaces,request_id:captureLaunchId}:{captures:plan.entries,request_id:captureLaunchId};
  const result=await json('/capture/launch','POST',body);
  refreshCaptureSessions();
  if(request!==captureRequest||!captureDialog.open)return;
  const list=Array.isArray(result.sessions)&&result.sessions.length?result.sessions:result.url?[{url:result.url,id:result.id}]:[];
  if(!list.length||list.some(s=>!/^\/static\/capture-session\.html#[0-9a-f]{64}$/.test(s.url)))throw new Error('Unsupported capture link — reopen Capture traffic and try again.');
  for(const s of list)if(!captureLinks.some(l=>l.url===s.url))captureLinks.push({url:s.url,label:s.label||(list.length===1&&plan.entries.length===1?plan.label:'')});
  paintCaptureLaunches();
  const refused=Array.isArray(result.refused)?result.refused:[];
  if(!refused.length){
   // A full success: the next Start is a new capture; whatever a partial result had marked is cleared and the boxes come back.
   const first=captureFirstPlan||plan,wasPartial=captureStarted.length>0;
   captureRememberNow(first);captureLaunchId='';captureStarted=[];captureFirstPlan=null;
   if(wasPartial)link?renderCaptureEnds({keep:true,ticked:first.ticked}):renderCaptureInterfaces({keep:true,ticked:first.ticked});
   captureDone=true;   // another Start waits for a changed selection: a second press would silently start another set
  }else{
   // A partial result: the request id stays (the remaining entries answer idempotently); what started is marked and unticked.
   const refusedAt=refused.map(r=>captureRefusedIndex(r,plan.entries));
   const startedNow=plan.entries.flatMap((e,i)=>refusedAt.includes(i)?[]:plan.entryEnds[i]);
   captureStarted=[...captureStarted,...startedNow];
   const remaining=plan.ticked.filter(x=>!startedNow.includes(x));
   if(link)renderCaptureEnds({keep:true,ticked:remaining});else renderCaptureInterfaces({keep:true,ticked:remaining});
  }
  // Whatever is listed is what is running: after a narrowed retry the single-session sentence would undercount.
  $('capture-status').textContent=captureDone?(captureLinks.length>1?`${captureLinks.length} Wireshark sessions started on the VM. Open each with its link below.`:result.message)+' Change the selection to start another capture.':result.message;
 }catch(error){if(request===captureRequest&&captureDialog.open)$('capture-status').textContent=error.message;}
 finally{captureStarting=false;updateCapturePrepare();}
};
$('capture-launches').onclick=event=>{
 const link=event.target&&typeof event.target.closest==='function'?event.target.closest('[data-capture-open]'):null;if(!link)return;
 const label=link.dataset&&link.dataset.captureOpen;
 $('capture-status').textContent=`Wireshark opened in a new tab${label?' for '+label:''}. The session and its saved files stay on the VM until you end it or it expires (2 hours).`;
};
// The sessions: one row per Wireshark the manager can name (device, port, lab), an upper bound for the time left (an idle
// session is reaped after 15 minutes), and the same list feeds the Tools card caption.
let captureSessionRequest=0;
function captureRowLabel(s){
 const ports=Array.isArray(s.ports)?s.ports:[],interfaces=Array.isArray(s.interfaces)?s.interfaces:[];
 if(!s.lab)return `${s.name} · ${interfaces.join(', ')}`;
 const shown=ports.length?ports:interfaces,differs=shown.join(', ')!==interfaces.join(', ');
 return `${s.device||s.name} ${shown.join(', ')}${differs?` (${interfaces.join(', ')})`:''} · ${s.lab}`;
}
function captureTimeLeft(seconds){const minutes=Math.floor((Number(seconds)||0)/60);if(minutes<1)return 'less than 1 min';return minutes<60?`${minutes} min`:`${Math.floor(minutes/60)} h${minutes%60?` ${minutes%60} min`:''}`;}
// The Tools card's caption and button, and the dialog's End all my sessions, follow one list.
// The list is rewritten only when its markup changed, so a focused End session button survives a refresh that found nothing new.
function paintCaptureSessionList(html){if(html===captureSessionsHtml)return;captureSessionsHtml=html;$('capture-sessions').innerHTML=html;}
function paintCaptureCard(){
 const n=captureSessionsState.rows.length,show=captureEnabled!==false&&n>0,caption=$('capture-sessions-caption');
 if(caption){caption.textContent=show?`${plural(n,'Wireshark session')} running from this browser.`:'';caption.hidden=!show;}
 for(const id of ['tools-capture-end-all','capture-end-all']){const button=$(id);if(button)button.hidden=!show;}
}
async function refreshCaptureSessions(){
 const request=++captureSessionRequest;
 if(captureEnabled===false){captureSessionsState={rows:[],fetched:true};paintCaptureCard();paintCaptureSessionList('<li>Packet capture is not set up on this VM, so there are no sessions to list.</li>');return true;}
 try{
  const data=await(await api('/capture/sessions')).json();
  if(request!==captureSessionRequest)return;
  captureSessionsState={rows:(data.sessions||[]).filter(s=>/^[0-9a-f]{64}$/.test(s.id)),fetched:true};
  paintCaptureSessionList(captureSessionsState.rows.map(s=>{
   const time=typeof s.remaining_seconds==='number'?` <span class="caption">at most ${esc(captureTimeLeft(s.remaining_seconds))} left (15 min once its viewer is closed)</span>`:'';
   return `<li><a href="/static/capture-session.html#${s.id}" target="_blank" rel="noopener">${esc(captureRowLabel(s))}</a>${time} <button type="button" class="button secondary" data-end-capture="${s.id}">End session</button></li>`;
  }).join('')||'<li>No capture sessions yet.</li>');
  paintCaptureCard();return true;
 }catch{captureSessionsState={rows:[],fetched:true};paintCaptureCard();paintCaptureSessionList('Could not list capture sessions — packet capture may not be set up on this VM. See Setup and troubleshooting.');return false;}
}
// Where focus goes when an action removed the control that had it (a row's End session, End all): the next row, else Refresh list.
function settleCaptureFocus(){
 const active=typeof document!=='undefined'?document.activeElement:null;if(active&&active!==document.body)return;
 if(!captureDialog.open)return;
 const next=typeof $('capture-sessions').querySelector==='function'?$('capture-sessions').querySelector('[data-end-capture]'):null,target=next||$('capture-sessions-refresh');
 if(target&&typeof target.focus==='function')target.focus();
}
// While the service is reported missing, Refresh list asks the manager again instead of repeating the local note.
$('capture-sessions-refresh').onclick=()=>captureEnabled===false?refreshCaptureTargets():refreshCaptureSessions();
$('capture-sessions').onclick=async event=>{
 const button=event.target.closest('[data-end-capture]');if(!button)return;
 if(!confirm('End this Wireshark session and delete its capture files? Download saved files first.'))return;
 button.disabled=true;
 try{await json('/capture/sessions/'+button.dataset.endCapture+'/end','POST',{});await refreshCaptureSessions();settleCaptureFocus();}
 catch(error){$('capture-status').textContent=error.message;button.disabled=false;}
};
// End all my sessions: one confirmation, one manager route (the owner's sessions only); the result is said in the dialog's
// status line and, when the dialog is closed (the Tools card), as a notice.
function captureSay(text){$('capture-status').textContent=text;if(!captureDialog.open&&typeof notify==='function')notify(text);}
async function endAllCaptureSessions(button){
 if(captureEnding)return;
 captureEnding=true;button.disabled=true;
 const label=button.textContent;
 try{
  // The list is read again before asking: the confirmation names what will be ended now, not what the Tools tab listed earlier.
  if(await refreshCaptureSessions()===false){captureSay('Could not list capture sessions, so none were ended. Try Refresh list.');return;}
  const n=captureSessionsState.rows.length;
  if(!n){captureSay('No capture sessions to end.');return;}
  if(!confirm(n===1?'End the 1 Wireshark session started from this browser and delete its capture files? Download saved files first.':`End all ${n} Wireshark sessions started from this browser and delete their capture files? Download saved files first.`))return;
  button.textContent='Ending…';
  try{
   const result=await json('/capture/sessions/end-all','POST',{}),ended=Number(result.ended)||0,failed=Array.isArray(result.failed)?result.failed:[];
   captureSay(failed.length?`Ended ${plural(ended,'session')}; ${failed.length} could not be ended: ${failed[0].detail||`Could not end ${failed[0].label}; try End session on its row.`}`:ended?`Ended ${plural(ended,'session')}.`:'No capture sessions to end.');
  }catch(error){captureSay(error.message);}
  await refreshCaptureSessions();
 }
 finally{
  captureEnding=false;button.textContent=label;button.disabled=false;
  // The button hides when nothing is left; focus goes to a control that is still there instead of the page body.
  if(button.hidden){const next=captureDialog.open?$('capture-sessions-refresh'):$('capture-open');if(next&&typeof next.focus==='function')next.focus();}
 }
}
for(const id of ['capture-end-all','tools-capture-end-all'])if($(id))$(id).onclick=()=>endAllCaptureSessions($(id));
// The wire menu (#link-context-menu, handled like the node menu): shell.js closes it on an outside pointerdown, on resize,
// blur and scroll, and leaves Escape to this menu's own keydown. closeLinkMenu is called by shell.js without arguments.
const linkMenu=$('link-context-menu');let linkMenuLab='',linkMenuWire=null,linkMenuEnds=null;
function closeLinkMenu(restore=false){
 if(!linkMenu||linkMenu.hidden)return;
 linkMenu.hidden=true;const wire=linkMenuWire;linkMenuWire=null;linkMenuEnds=null;
 if(restore&&wire&&typeof wire.focus==='function')wire.focus();
}
function captureEndsOf(element){
 try{const ends=JSON.parse(element.dataset.captureEndpoints);if(Array.isArray(ends)&&ends.length===2)return ends;}catch{}
 notify('Could not read this link. Open Tools › Packet capture and choose the interface there.');return null;
}
function openLinkCapture(element,options){
 const ends=captureEndsOf(element);if(!ends)return;
 closeLinkMenu();   // Enter on a wire while its menu is open closes the menu first
 captureOpener={el:element,key:element.dataset&&element.dataset.captureEndpoints};
 openCapture('','',ends,options);
}
function openLinkMenu(element,x,y){
 const ends=captureEndsOf(element);if(!ends||!linkMenu)return;
 if(typeof closeNodeMenu==='function')closeNodeMenu();
 const attrs=typeof captureActionAttrs==='function'?captureActionAttrs():'',off=/\bdisabled\b/.test(attrs);
 const reason=off?'<small>Packet capture isn’t set up on this VM yet — see Tools › Packet capture.</small>':'';
 const item=(data,text)=>`<button type="button" role="menuitem" ${data} ${attrs}>${text}${reason}</button>`;
 linkMenu.innerHTML=`<div class="context-node-name">${esc(ends[0].label)}: ${esc(ends[0].interface)} — ${esc(ends[1].label)}: ${esc(ends[1].interface)}</div>`
  +item('data-link-both','Capture both ends…')
  +ends.map((ep,i)=>item(`data-link-end="${i}"`,`Capture ${esc(ep.label)}: ${esc(ep.interface)}…`)).join('');
 linkMenuLab=activeId;linkMenuWire=element;linkMenuEnds=ends;
 linkMenu.hidden=false;
 if(linkMenu.style&&typeof window!=='undefined'){linkMenu.style.left=Math.max(8,Math.min(x,window.innerWidth-linkMenu.offsetWidth-8))+'px';linkMenu.style.top=Math.max(8,Math.min(y,window.innerHeight-linkMenu.offsetHeight-8))+'px';}
 // With every item off the menu itself takes focus, so its own keydown can close it with Escape or Tab.
 const first=linkMenu.querySelector('button:not(:disabled)'),target=first||linkMenu;if(typeof target.focus==='function')target.focus();
}
if(linkMenu){
 linkMenu.addEventListener('click',event=>{
  const button=event.target&&typeof event.target.closest==='function'?event.target.closest('button'):null;if(!button||button.disabled)return;
  if(linkMenuLab!==activeId){closeLinkMenu();return;}
  const ends=linkMenuEnds,wire=linkMenuWire;closeLinkMenu();if(!ends)return;
  captureOpener=wire?{el:wire,key:wire.dataset&&wire.dataset.captureEndpoints}:null;
  // A menu item is a hint, not a click on the wire: it ignores the remembered selection (design 3.6).
  if(button.dataset.linkEnd!==undefined)openCapture('','',ends,{end:Number(button.dataset.linkEnd)});else openCapture('','',ends,{both:true});
 });
 linkMenu.addEventListener('keydown',event=>{
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeLinkMenu(true);return;}
  if(event.key==='Tab'){closeLinkMenu(true);return;}
  if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
  event.preventDefault();
  const buttons=[...linkMenu.querySelectorAll('button:not(:disabled)')],i=buttons.indexOf(event.target);
  buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(i+(event.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();
 });
}
map.addEventListener('click',event=>{const element=event.target.closest('[data-capture-endpoints]');if(element)openLinkCapture(element);});
map.addEventListener('contextmenu',event=>{const element=event.target.closest('[data-capture-endpoints]');if(element){event.preventDefault();openLinkMenu(element,event.clientX,event.clientY);}});
map.addEventListener('keydown',event=>{
 const element=event.target.closest('[data-capture-endpoints]');if(!element)return;
 if(['Enter',' '].includes(event.key)){event.preventDefault();openLinkCapture(element);return;}
 if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10')){event.preventDefault();const rect=element.getBoundingClientRect();openLinkMenu(element,rect.right,rect.top);}
});
