'use strict';
// Telemetry view and topology overlay. Reads the manager's session-only telemetry APIs;
// never talks to a device or a collector directly.
const TELE_STATES={disabled:'Off',waiting:'Waiting',configuring:'Configuring',connecting:'Connecting',streaming:'Streaming',stale:'Stale',unsupported:'Unsupported',failed:'Failed',unmonitored:'Unmonitored'};
const TELE_TONE={streaming:'good',failed:'bad',stale:'warn',waiting:'warn',configuring:'running',connecting:'running',unsupported:'neutral',disabled:'neutral',unmonitored:'neutral'};
const TELE_LINK_TITLES={up:'Link up (both ends report UP)','up-partial':'Link up on the observed end; the other end reports no telemetry',down:'Link down',stale:'Telemetry stale on this link; last known state shown',unknown:'No telemetry for this link yet'};
var teleState={lab:'',data:null,node:'',interface:'',peer:'',window:300,request:0,seriesRequest:0,fetched:0,series:null,peerSeries:null,busy:false};
function telemetryBadge(state){const label=TELE_STATES[state]||state||'Unknown';return `<span class="badge tele-badge ${esc(TELE_TONE[state]||'neutral')}">${esc(label)}</span>`;}
function telemetryLinkClass(link){return 'tele-'+(link&&link.status?link.status:'unknown')+(link&&link.mismatch?' tele-mismatch':'');}
function telemetryLinkTitle(link){
 if(!link)return TELE_LINK_TITLES.unknown;
 const ends=(link.ends||[]).map(e=>`${e.label}:${e.interface}${e.nos_interface&&e.nos_interface!==e.interface?' ('+e.nos_interface+')':''} ${e.state==='unknown'?'no data':e.state==='unsupported'?'unsupported':e.state.toUpperCase()}${e.state==='up'||e.state==='down'||e.state==='stale'?' · RX '+telemetryFormatRate(e.rx_bps,'bps')+' · TX '+telemetryFormatRate(e.tx_bps,'bps'):''}`);
 return (TELE_LINK_TITLES[link.status]||TELE_LINK_TITLES.unknown)+(link.mismatch?' · the two ends disagree':'')+'\n'+ends.join('\n');
}
// Grafana runs beside the manager on the VM (deploy/setup-telemetry.sh); the browser reaches it
// on the manager's own host name. Dashboard uids are fixed by the provisioned files.
function telemetryGrafanaUrl(data,uid,vars={}){
 if(!data?.grafana?.enabled||typeof location==='undefined')return '';
 const params=new URLSearchParams({'var-lab':data.lab_name||''});
 for(const [key,value] of Object.entries(vars))if(value)params.set('var-'+key,value);
 params.set('refresh','10s');
 return `${location.protocol}//${location.hostname}:${data.grafana.port}/d/${uid}?${params}`;
}
function telemetrySummaryText(data){
 const s=data.summary||{};
 if(!data.enabled)return data.unavailable||'Telemetry is unavailable in this manager.';
 if(!data.linked)return 'Telemetry is collected for labs linked to a VM deployment.';
 if(!data.settings.decided)return 'Automatic telemetry is not enabled for this lab yet.';
 if(!data.settings.auto)return 'Automatic telemetry is off for this lab. Turn it on in Telemetry settings to configure the nodes and stream counters.';
 const parts=[];for(const key of ['streaming','stale','waiting','configuring','connecting','failed','unsupported'])if(s[key])parts.push(`${s[key]} ${TELE_STATES[key].toLowerCase()}`);
 return `${s.status==='streaming'?'Streaming':s.status==='partial'?'Partially streaming':s.status==='failed'?'Needs attention':s.status==='unsupported'?'No supported nodes':'Waiting'} · ${s.total} supported node${s.total===1?'':'s'}${parts.length?' · '+parts.join(' · '):''}`;
}
function telemetryInterfaceRow(row,selected){
 const state=row.oper?`${esc(row.admin||'?')}/${esc(row.oper)}`:'<span class="status-neutral">n/a</span>';
 return `<tr class="${selected?'selected':''} ${row.fresh?'':'stale'}" data-tele-interface="${esc(row.name)}" tabindex="0"><td><strong>${esc(row.name)}</strong>${row.drawn&&row.drawn!==row.name?`<small>${esc(row.drawn)}</small>`:''}</td><td>${row.wired?esc(row.peer||'?')+':'+esc(row.peer_interface||'?'):'<span class="status-neutral">—</span>'}</td><td>${state}</td><td>${esc(telemetryFormatRate(row.rx_bps,'bps'))}</td><td>${esc(telemetryFormatRate(row.tx_bps,'bps'))}</td><td>${esc(telemetryFormatRate(row.rx_pps,'pps'))}</td><td>${esc(telemetryFormatRate(row.tx_pps,'pps'))}</td><td>${esc(telemetryFormatCount(row.totals?.['in-errors']))} / ${esc(telemetryFormatCount(row.totals?.['out-errors']))}</td><td>${esc(telemetryFormatCount(row.totals?.['in-discards']))} / ${esc(telemetryFormatCount(row.totals?.['out-discards']))}</td><td><span class="timestamp">${esc(telemetryAge(row.at))}${row.fresh?'':' · stale'}${row.resets?' · '+row.resets+' reset'+(row.resets>1?'s':''):''}</span></td></tr>`;
}
function telemetryPeerRow(row,selected){
 return `<tr class="${selected?'selected':''} ${row.fresh?'':'stale'}" data-tele-peer="${esc(row.peer)}" data-tele-instance="${esc(row.instance)}" tabindex="0"><td><strong>${esc(row.peer)}</strong></td><td>${esc(row.instance)}</td><td>${esc(row.afi||'n/a')}</td><td>${row.state?`<span class="badge ${row.state==='ESTABLISHED'?'good':'warn'}">${esc(row.state)}</span>`:'<span class="status-neutral">n/a</span>'}</td><td>${esc(telemetryFormatCount(row.received))}</td><td>${esc(telemetryFormatCount(row.sent))}</td><td><span class="timestamp">${esc(telemetryAge(row.at))}${row.fresh?'':' · stale'}</span></td></tr>`;
}
function telemetryGroupPill(name,group){
 const status=group?.status||'pending';const label=name==='bgp'?'BGP':'Interfaces';
 const tone=status==='streaming'?'good':status==='unsupported'||status==='failed'?'bad':status==='subscribed'?'running':'neutral';
 return `<span class="badge ${tone}" title="${esc(group?.message||'Not subscribed yet')}">${label}: ${esc(status==='pending'?'pending':status)}</span>`;
}
function telemetryNodeCard(n,selected){
 return `<button class="tele-node ${selected?'active':''}" data-tele-node="${esc(n.name)}"><span class="tele-node-name">${esc(n.short_name)}<small>${esc(n.label||n.platform||'unmapped kind')}</small></span>${telemetryBadge(n.state)}<span class="tele-node-message">${esc(n.message||'')}</span>${n.last_sample?`<span class="timestamp">Last sample ${esc(telemetryAge(n.last_sample))}</span>`:''}</button>`;
}
function telemetryDetail(n,data){
 if(!n)return '<div class="blank-state"><h2>Select a node</h2><p>Choose a node on the left to see its interfaces, rates and BGP neighbours.</p></div>';
 const groups=n.groups||{};
 const grafana=telemetryGrafanaUrl(data,'clab-interface',{node:n.short_name,interface:teleState.interface});
 const head=`<div class="tele-detail-head"><div><h3>${esc(n.short_name)} <small class="mono">${esc(n.name)}</small></h3><p>${telemetryBadge(n.state)} ${esc(n.message||'')}</p><p class="form-help">${n.endpoint?`gNMI ${esc(n.endpoint)} · ${n.transport==='tls'?'TLS (certificate not verified)':'plain text'} · `:''}${esc(n.method||(n.supported?'Waiting for the NOS':'No telemetry adapter for this kind'))}${n.applied?` · ${n.applied} configuration line${n.applied===1?'':'s'} added by the manager`:''}</p><p class="tele-groups">${telemetryGroupPill('interfaces',groups.interfaces)} ${telemetryGroupPill('bgp',groups.bgp)}${n.last_sample?` <span class="timestamp">Last sample ${esc(telemetryAge(n.last_sample))}${n.fresh?'':' · stale'}</span>`:''}</p></div><div class="actions">${grafana?`<a class="button secondary" href="${esc(grafana)}" target="_blank" rel="noopener">Grafana ↗</a>`:''}${['failed','stale','unsupported'].includes(n.state)&&n.supported?`<button class="button secondary" data-tele-retry="${esc(n.name)}">Retry now</button>`:''}</div></div>`;
 if(!n.interfaces.length&&!n.peers.length){
  const why=n.state==='streaming'||n.state==='connecting'?'Waiting for the first samples.':n.state==='unsupported'?'This node kind has no telemetry adapter; its links show as unknown on the map.':n.state==='disabled'?'Telemetry is off.':n.state==='failed'?'See the message above; Retry now checks the node again.':'Interfaces appear once the NOS answers and the gNMI session streams.';
  return head+`<div class="blank-state"><h2>No telemetry yet</h2><p>${esc(why)}</p></div>`;
 }
 const rows=n.interfaces.map(r=>telemetryInterfaceRow(r,r.name===teleState.interface)).join('');
 const peers=n.peers.length?`<h4>BGP neighbours</h4><div class="table-wrap"><table><thead><tr><th>Neighbour</th><th>Instance</th><th>AFI</th><th>State</th><th>Received</th><th>Sent</th><th>Updated</th></tr></thead><tbody>${n.peers.map(r=>telemetryPeerRow(r,r.peer===teleState.peer)).join('')}</tbody></table></div>`:groups.bgp?.status==='unsupported'?'<h4>BGP neighbours</h4><p class="form-help">BGP telemetry is unavailable on this node: '+esc(groups.bgp.message)+'</p>':groups.bgp?.status==='streaming'||groups.bgp?.status==='subscribed'?'<h4>BGP neighbours</h4><p class="form-help">Subscribed; the node has not reported a BGP neighbour yet.</p>':'';
 return head+`<h4>Interfaces</h4><div class="table-wrap tele-table"><table><thead><tr><th>Interface</th><th>Wired to</th><th>Admin/Oper</th><th>RX</th><th>TX</th><th>RX pkts</th><th>TX pkts</th><th>Errors in/out</th><th>Discards in/out</th><th>Sample</th></tr></thead><tbody>${rows}</tbody></table></div><p class="form-help">Rates come from counter deltas sampled every ${esc(data.sample_interval)} s; discards and errors are device counters, not measured end-to-end loss. Utilisation percentages are not shown because a virtual interface speed does not describe real throughput.</p><div id="telemetry-charts" class="tele-charts"></div>${peers}<div id="telemetry-peer-chart" class="tele-charts"></div>`;
}
function telemetryCharts(){
 const holder=$('telemetry-charts');if(!holder)return;
 const n=teleState.data?.nodes.find(x=>x.name===teleState.node);
 if(!n||!teleState.interface){holder.innerHTML=n&&n.interfaces?.length?'<p class="form-help">Select an interface row to chart it.</p>':'';return;}
 const points=teleState.series?.interface===teleState.interface&&teleState.series?.node===teleState.node?teleState.series.points:[];
 const now=Date.now()/1000,common={points,window:teleState.window,now};
 holder.innerHTML=`<p class="tele-chart-caption">${esc(teleState.interface)} · last ${teleState.window/60} min · ${points.length} samples</p>`
  +telemetryChart({...common,unit:'bps',title:'Bit rate',series:[{key:'rx_bps',label:'RX',color:'#157d91'},{key:'tx_bps',label:'TX',color:'#f15b40'}]})
  +telemetryChart({...common,unit:'pps',title:'Packet rate',series:[{key:'rx_pps',label:'RX',color:'#157d91'},{key:'tx_pps',label:'TX',color:'#f15b40'}]})
  +telemetryChart({...common,unit:'/s',title:'Errors and discards per second',series:[{key:'rx_errors',label:'RX errors',color:'#a13135'},{key:'tx_errors',label:'TX errors',color:'#d98b2b'},{key:'rx_discards',label:'RX discards',color:'#416377'},{key:'tx_discards',label:'TX discards',color:'#79b0bd'}]});
 const peerHolder=$('telemetry-peer-chart');
 if(peerHolder){const p=teleState.peerSeries;peerHolder.innerHTML=teleState.peer&&p&&p.peer===teleState.peer?`<p class="tele-chart-caption">BGP ${esc(teleState.peer)} prefixes</p>`+telemetryChart({points:p.points,window:teleState.window,now,unit:'',title:'Prefixes received and sent',series:[{key:'received',label:'Received',color:'#157d91'},{key:'sent',label:'Sent',color:'#f15b40'}]}):'';}
}
function renderTelemetryView(){
 const data=teleState.data,lab=current();
 if(!lab||!$('telemetry-view'))return;
 if(!data||data.lab_id!==lab.id){$('telemetry-banner').textContent='Loading telemetry…';$('telemetry-banner').className='tele-banner';$('telemetry-nodes').innerHTML='';$('telemetry-detail').innerHTML='';return;}
 const banner=$('telemetry-banner');banner.className='tele-banner '+(data.summary?.status||'disabled');
 const undecided=data.enabled&&data.linked&&!data.settings.decided;
 banner.innerHTML=`<strong>${esc(telemetrySummaryText(data))}</strong>${undecided?`<p>The manager can configure the gNMI service on supported nodes (cEOS, XRv9k, cJunosEvolved) with their saved logins and stream interface counters and BGP state into memory. Nothing is stored on disk; no dashboards to set up.</p><button class="button primary" id="telemetry-enable">Enable automatic telemetry</button>`:''}${data.enabled&&data.settings.auto?`<p class="form-help">${esc(data.method)} · ${data.stale_after} s without samples marks a node stale · last ${data.windows[data.windows.length-1]/60} minutes kept in memory only.</p>`:''}`;
 if(undecided)$('telemetry-enable').onclick=()=>telemetrySaveSettings(true,data.settings.profile_id||'');
 if(!teleState.node||!data.nodes.some(n=>n.name===teleState.node))teleState.node=(data.nodes.find(n=>n.state==='streaming')||data.nodes.find(n=>n.supported)||data.nodes[0])?.name||'';
 $('telemetry-nodes').innerHTML=data.nodes.map(n=>telemetryNodeCard(n,n.name===teleState.node)).join('')||'<p class="side-hint">No nodes in this lab.</p>';
 const node=data.nodes.find(n=>n.name===teleState.node);
 if(node&&teleState.interface&&!node.interfaces.some(r=>r.name===teleState.interface))teleState.interface='';
 if(node&&!teleState.interface)teleState.interface=(node.interfaces.find(r=>r.wired)||node.interfaces.find(r=>r.role==='physical')||node.interfaces[0])?.name||'';
 $('telemetry-detail').innerHTML=telemetryDetail(node,data);
 telemetryCharts();
 $('telemetry-status').textContent=`Updated ${new Date(data.generated_at).toLocaleTimeString()} · window ${teleState.window/60} min · samples every ${data.sample_interval} s.`;
 const grafana=$('telemetry-grafana');
 // The generated lab map (Flow panel) when the stack serves one for this lab, else the lab overview.
 if(grafana){const map=data.grafana?.map_uid||'';const url=telemetryGrafanaUrl(data,map||'clab-lab-overview');grafana.hidden=!url;if(url)grafana.href=url;else grafana.removeAttribute('href');grafana.textContent=map?'Open lab map in Grafana ↗':'Open Grafana ↗';}
}
function telemetryLegend(data){
 const legend=$('map-live-legend');if(!legend)return;
 const live=data&&data.enabled&&data.settings?.auto&&['streaming','partial','failed'].includes(data.summary?.status);
 legend.innerHTML=live?'Drag to pan · Live link state: <span class="tele-swatch up"></span>up <span class="tele-swatch partial"></span>up, one end observed <span class="tele-swatch down"></span>down <span class="tele-swatch stale"></span>stale <span class="tele-swatch unknown"></span>no telemetry':'Drag to pan · Links show imported wiring, not live status';
}
function applyTelemetryOverlay(){
 if(typeof map==='undefined'||!map||typeof map.querySelectorAll!=='function')return;
 const data=teleState.data,lab=current();
 const active=data&&lab&&data.lab_id===lab.id&&data.enabled&&data.settings?.auto;
 const links=active?data.links:[];const byIndex=new Map(links.map(l=>[l.index,l]));
 for(const wire of map.querySelectorAll('[data-link-index]')){
  const link=byIndex.get(Number(wire.dataset.linkIndex));
  wire.setAttribute('class','topology-wire '+(active?telemetryLinkClass(link):''));
  const title=wire.querySelector('title');if(title&&active)title.textContent=telemetryLinkTitle(link);
 }
 const nodes=new Map((active?data.nodes:[]).map(n=>[n.name,n]));
 for(const device of map.querySelectorAll('[data-map-node]')){
  const n=nodes.get(device.dataset.mapNode);
  const base=(device.getAttribute('class')||'').split(' ').filter(c=>c&&!c.startsWith('tele-')).join(' ');
  device.setAttribute('class',base+(n?' tele-'+n.state:''));
  const dot=device.querySelector('.tele-dot');if(dot)dot.querySelector?.('title');
  const title=device.querySelector('title');
  if(title&&n&&n.state!=='unmonitored')title.textContent=`${TELE_STATES[n.state]||n.state}: ${n.message||''}\nRight-click for SSH, telemetry and node actions: ${device.dataset.mapNode}`;
 }
 telemetryLegend(active?data:null);
}
async function refreshTelemetry(force=false){
 const lab=current();if(!lab||!$('telemetry-view'))return;
 const wanted=tab==='telemetry'||tab==='topology';
 if(!wanted&&!force)return;
 if(!force&&Date.now()-teleState.fetched<4500)return;
 const request=++teleState.request,labId=lab.id;
 try{
  const data=await(await api('/labs/'+labId+'/telemetry')).json();
  if(request!==teleState.request||activeId!==labId)return;
  teleState.data=data;teleState.lab=labId;teleState.fetched=Date.now();
  if(tab==='telemetry')renderTelemetryView();
  applyTelemetryOverlay();
  if(tab==='telemetry')await refreshTelemetrySeries();
 }catch(e){if(request===teleState.request&&$('telemetry-status'))$('telemetry-status').textContent='Could not load telemetry: '+e.message;}
}
async function refreshTelemetrySeries(){
 const lab=current();if(!lab||!teleState.node||!teleState.interface)return;
 const request=++teleState.seriesRequest,params=new URLSearchParams({node:teleState.node,interface:teleState.interface,window:String(teleState.window)});
 try{
  const series=await(await api('/labs/'+lab.id+'/telemetry/series?'+params)).json();
  if(request!==teleState.seriesRequest)return;
  teleState.series=series;
  if(teleState.peer){const node=teleState.data?.nodes.find(n=>n.name===teleState.node),row=node?.peers.find(p=>p.peer===teleState.peer);
   if(row){const q=new URLSearchParams({node:teleState.node,peer:teleState.peer,instance:row.instance,window:String(teleState.window)});teleState.peerSeries=await(await api('/labs/'+lab.id+'/telemetry/bgp-series?'+q)).json();}}
  telemetryCharts();
 }catch(e){if(request===teleState.seriesRequest){teleState.series=null;telemetryCharts();}}
}
function renderTelemetry(){
 const lab=current();
 if(!lab){teleState.data=null;return;}
 if(teleState.lab&&teleState.lab!==lab.id){teleState={...teleState,data:null,node:'',interface:'',peer:'',series:null,peerSeries:null};}
 if(tab==='telemetry')renderTelemetryView();
 refreshTelemetry().catch(()=>{});
}
function openTelemetry(node,iface=''){
 teleState.node=node||teleState.node;teleState.interface=iface||'';teleState.peer='';teleState.series=null;
 if($('details-dialog')?.open)$('details-dialog').close();
 showTab('telemetry');refreshTelemetry(true).catch(e=>notify(e.message));
}
async function telemetrySaveSettings(auto,profile){
 const lab=current();if(!lab)return;
 try{teleState.data=await json('/labs/'+lab.id+'/telemetry/settings','PUT',{auto,profile_id:profile||''});teleState.fetched=Date.now();renderTelemetryView();applyTelemetryOverlay();notify(auto?'Automatic telemetry enabled. Supported nodes are configured as they become ready.':'Automatic telemetry disabled; collection stopped.');}
 catch(e){notify(e.message);}
}
function openTelemetrySettings(){
 const data=teleState.data,lab=current();if(!lab||!data)return;
 const profiles=data.password_profiles||[];
 const dialog=opDialog('telemetry-settings-dialog','Telemetry settings',`<label class="checkbox-label"><input type="checkbox" id="tele-auto" ${data.settings.auto?'checked':''}> Automatic telemetry: configure the gNMI service on supported nodes and stream counters</label><p class="form-help">Applies to cEOS, XRv9k and cJunosEvolved nodes once they answer show version. The manager adds only the missing service lines with each NOS's own scoped commit and never saves the whole running configuration. Observations stay in memory (last 60 minutes) and are cleared on stop, destroy, redeploy or manager restart.</p><label>gNMI login<select id="tele-profile"><option value="">Each node's saved password login (profile, inventory or containerlab default)</option>${profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===data.settings.profile_id?'selected':''}>${esc(p.label)} · ${esc(p.platform)}</option>`).join('')}</select></label><p class="form-help">gNMI needs a username and password; nodes that log in with an SSH key need a password profile here. Secrets never leave the manager.</p><div class="dialog-actions"><button class="button secondary" id="tele-remove" ${data.settings.auto?'disabled title="Disable automatic telemetry first"':''}>Remove manager-added lines…</button><button class="button primary" id="tele-save">Save</button></div><p class="form-help">Remove deletes only the telemetry configuration lines this manager recorded as its own, on running nodes, over SSH. Disabling telemetry alone leaves the device configuration as it is.</p>`);
 $('tele-save').onclick=()=>opTask(dialog,async()=>{await telemetrySaveSettings($('tele-auto').checked,$('tele-profile').value);dialog.close();});
 $('tele-remove').onclick=()=>opTask(dialog,async()=>{if(!confirm('Remove the telemetry configuration lines the manager added on the running nodes of this lab?'))return;const result=await json('/labs/'+lab.id+'/telemetry/remove-config','POST',{});notify(result.started.length?`Removal started on ${result.started.join(', ')}.`:'Nothing to remove on running nodes.');dialog.close();await refreshTelemetry(true);});
}
if($('telemetry-view')){
 $('telemetry-nodes').addEventListener('click',e=>{const b=e.target.closest('[data-tele-node]');if(!b)return;teleState.node=b.dataset.teleNode;teleState.interface='';teleState.peer='';teleState.series=null;teleState.peerSeries=null;renderTelemetryView();refreshTelemetrySeries().catch(()=>{});});
 const pick=e=>{const iface=e.target.closest('[data-tele-interface]'),peer=e.target.closest('[data-tele-peer]'),retry=e.target.closest('[data-tele-retry]');
  if(retry){json('/labs/'+activeId+'/telemetry/retry','POST',{node:retry.dataset.teleRetry}).then(()=>{notify('Retry requested.');return refreshTelemetry(true);}).catch(err=>notify(err.message));return;}
  if(iface){teleState.interface=iface.dataset.teleInterface;renderTelemetryView();refreshTelemetrySeries().catch(()=>{});}
  if(peer){teleState.peer=peer.dataset.telePeer;renderTelemetryView();refreshTelemetrySeries().catch(()=>{});}};
 $('telemetry-detail').addEventListener('click',pick);
 $('telemetry-detail').addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.closest('[data-tele-interface],[data-tele-peer]')){e.preventDefault();pick(e);}});
 $('telemetry-window').onchange=()=>{teleState.window=Number($('telemetry-window').value)||300;renderTelemetryView();refreshTelemetrySeries().catch(()=>{});};
 $('telemetry-settings-open').onclick=openTelemetrySettings;
 $('telemetry-refresh').onclick=()=>refreshTelemetry(true).catch(e=>notify(e.message));
}
// Right-click on a link: capture either end or open its telemetry.
function openLinkMenu(element,x,y){
 let ends;try{ends=JSON.parse(element.dataset.captureEndpoints||'[]');}catch{return;}
 if(typeof nodeMenu==='undefined'||!nodeMenu)return;
 contextLab=activeId;contextNode=element;
 nodeMenu.innerHTML=`<div class="context-node-name">${esc(ends.map(e=>e.label+':'+e.interface).join(' — '))}<small>Link</small></div><button role="menuitem" data-link-capture="1" ${typeof captureActionAttrs==='function'?captureActionAttrs():''}>Capture packets</button>${ends.filter(e=>e.node).map((e,i)=>`<button role="menuitem" data-link-telemetry="${i}"><span aria-hidden="true">∿</span> Telemetry ${esc(e.label)}:${esc(e.interface)}</button>`).join('')}`;
 nodeMenu.hidden=false;nodeMenu.style.left=Math.max(8,Math.min(x,window.innerWidth-nodeMenu.offsetWidth-8))+'px';nodeMenu.style.top=Math.max(8,Math.min(y,window.innerHeight-nodeMenu.offsetHeight-8))+'px';
 nodeMenu.onclick=e=>{const b=e.target.closest('button');if(!b||b.disabled)return;nodeMenu.onclick=null;
  if(b.dataset.linkCapture){closeNodeMenu();if(typeof openLinkCapture==='function')openLinkCapture(element);return;}
  if(b.dataset.linkTelemetry!==undefined){const end=ends.filter(e=>e.node)[Number(b.dataset.linkTelemetry)];closeNodeMenu();const lab=current(),node=lab?.nodes.find(n=>n.name===end.node);const iface=lab&&typeof telemetryEndpointName==='function'?telemetryEndpointName(node?.platform,end.interface):'';openTelemetry(end.node,iface);}};
 nodeMenu.querySelector('button:not(:disabled)')?.focus();
}
// The interface the NOS reports for a wired port, from the server's link view when available.
function telemetryEndpointName(platform,drawn){
 const link=(teleState.data?.links||[]).flatMap(l=>l.ends).find(e=>e.interface===drawn&&e.nos_interface);
 return link?link.nos_interface:'';
}
