'use strict';
// Network design (docs/NETWORK-DESIGN.md): a student designs addressing, routing and services on top
// of a lab's topology, generates per-device configuration with netlab and reviews it. The topology
// itself is never edited here; only the design intent (network_design.py) and its generations are.
// Pure functions first — the harness in tests/test_network_design_ui.js runs this file in a DOM-less
// vm context, so nothing above the "imperative wiring" section may touch document, window or a global
// other than esc/$/state at call time.

const DESIGN_MODULE_LABELS={ospf:'OSPF',bgp:'BGP',isis:'IS-IS',eigrp:'EIGRP',ripv2:'RIP',bfd:'BFD',dhcp:'DHCP',
 vlan:'VLANs',vrf:'VRFs',lag:'Link aggregation (LAG, LACP, MLAG)',stp:'Spanning tree',
 gateway:'First-hop gateway (VRRP, anycast)',vxlan:'VXLAN',evpn:'EVPN',mpls:'MPLS (LDP, BGP-LU, L3VPN, 6PE)',
 sr:'Segment routing (SR-MPLS)',srv6:'SRv6',routing:'Routing policies and static routes'};
const DESIGN_BUSY_GENERATION=['queued','running'];
const DESIGN_LEVEL_WORDS={verified_on_image:'Verified on this image',generated_not_live_tested:'Generated, not yet tested live',
 unsupported:'Not supported',blocked_missing_prerequisite:'Needs a prerequisite module'};
const DESIGN_LEVEL_CLASS={verified_on_image:'ok',generated_not_live_tested:'neutral',unsupported:'danger',blocked_missing_prerequisite:'warn'};
// The shape of design_intent.empty_intent(): dual stack, the manager's default pools, nothing chosen yet.
const DESIGN_DEFAULT_INTENT={schema:1,label:'',families:{ipv4:true,ipv6:true},
 addressing:{loopback:{ipv4:'10.255.0.0/24',ipv6:'2001:db8:ff::/48'},p2p:{ipv4:'10.1.0.0/16',ipv6:'2001:db8:1::/48',prefix:31},
 lan:{ipv4:'172.16.0.0/16',ipv6:'2001:db8:2::/48',prefix:24}},
 modules:[],nodes:{},links:{},vlans:{},vrfs:{},interfaces:{},allocations:{}};
function designEmptyIntent(){return JSON.parse(JSON.stringify(DESIGN_DEFAULT_INTENT));}
function designModuleLabel(id){return DESIGN_MODULE_LABELS[id]||String(id||'');}

// --- state words (status.js vocabulary style: pure, {key,label,pill,detail}) -----------------------------
// view carries {intent,summary,generations,problems,engine,draft}; draft is truthy while an unsaved
// edit is held in memory (network-design.js's designState.draft), never the containers' readiness or
// saved progress — those are the other tabs' words.
function designStateOf(lab,view){
 view=view||{};
 const engine=view.engine;
 if(engine&&engine.available===false)
  return {key:'engine',label:'Design engine unavailable',pill:'danger',detail:engine.diagnostic||engine.reason||'The design engine is not available on this manager.'};
 const generations=view.generations||[],newest=generations.length?generations[generations.length-1]:null;
 const generating=!!(view.summary&&view.summary.generating)||!!(newest&&DESIGN_BUSY_GENERATION.includes(newest.status));
 if(generating)return {key:'generating',label:'Generating the plan…',pill:'busy',detail:(newest&&newest.message)||'Waiting to generate.'};
 if(view.draft)return {key:'draft',label:'Unsaved changes',pill:'warn',detail:'Save the design to keep these changes.'};
 const problems=view.problems||[];
 if(problems.length)return {key:'problems',label:'The design has problems',pill:'danger',detail:problems[0].message||'Fix the problems below, then save again.'};
 if(newest&&newest.status==='interrupted')
  return {key:'interrupted',label:'The last plan was interrupted',pill:'warn',detail:newest.message||'The manager restarted while this plan was being generated. Generate it again.'};
 if(newest&&newest.status==='failed')return {key:'failed',label:'The last plan failed',pill:'danger',detail:newest.message||'The last plan did not finish. See its errors below.'};
 if(newest&&newest.status==='succeeded'&&view.summary&&view.summary.stale)
  return {key:'stale',label:'Plan is older than the design',pill:'warn',detail:'The design changed since this plan was generated. Generate it again to see the current plan.'};
 if(newest&&newest.status==='succeeded')return {key:'ready',label:'Plan ready to review',pill:'ok',detail:newest.message||'Generated successfully.'};
 return {key:'none',label:'No design yet',pill:'neutral',detail:"Choose addressing, protocols and services below, then Generate plan."};
}

// --- guided form <-> intent (design_intent.py schema 1) ----------------------------------------------
// designIntentFromForm keeps every field the guided controls do not own (links, vlans, vrfs, interfaces,
// allocations, label, schema, revision, ...): it clones `base` and only touches the keys below.
function designIntentFromForm(values,base){
 values=values||{};
 const intent=JSON.parse(JSON.stringify(base&&typeof base==='object'?base:designEmptyIntent()));
 intent.schema=1;
 intent.families={ipv4:!!values.ipv4,ipv6:!!values.ipv6};
 const pools=values.pools||{};
 intent.addressing={
  loopback:{ipv4:(pools.loopback&&pools.loopback.ipv4)||'',ipv6:(pools.loopback&&pools.loopback.ipv6)||''},
  p2p:{ipv4:(pools.p2p&&pools.p2p.ipv4)||'',ipv6:(pools.p2p&&pools.p2p.ipv6)||'',prefix:Number(pools.p2p&&pools.p2p.prefix)||31},
  lan:{ipv4:(pools.lan&&pools.lan.ipv4)||'',ipv6:(pools.lan&&pools.lan.ipv6)||'',prefix:Number(pools.lan&&pools.lan.prefix)||24}
 };
 const modules=[...new Set(values.modules||[])];
 intent.modules=modules;
 const has=id=>modules.includes(id);
 if(has('ospf'))intent.ospf={...(intent.ospf&&typeof intent.ospf==='object'?intent.ospf:{}),area:values.ospfArea||'0.0.0.0'};
 else delete intent.ospf;
 if(has('bgp'))intent.bgp={...(intent.bgp&&typeof intent.bgp==='object'?intent.bgp:{}),as:Number(values.bgpAs)||65000};
 else delete intent.bgp;
 if(has('isis'))intent.isis={...(intent.isis&&typeof intent.isis==='object'?intent.isis:{}),area:values.isisArea||'49.0001',type:values.isisType||'level-2'};
 else delete intent.isis;
 if(has('gateway'))intent.gateway={...(intent.gateway&&typeof intent.gateway==='object'?intent.gateway:{}),protocol:values.gatewayProtocol||'anycast'};
 else delete intent.gateway;
 const nodes={...(intent.nodes||{})};
 for(const device of values.devices||[]){
  const name=device&&device.name;if(!name)continue;
  const node={...(nodes[name]&&typeof nodes[name]==='object'?nodes[name]:{})};
  if(device.role&&device.role!=='router')node.role=device.role;else delete node.role;
  if(has('bgp')){
   const bgp={...(node.bgp&&typeof node.bgp==='object'?node.bgp:{})};
   if(values.bgpRr&&values.bgpRr===name)bgp.rr=true;else delete bgp.rr;
   if(Object.keys(bgp).length)node.bgp=bgp;else delete node.bgp;
  }
  if(Object.keys(node).length)nodes[name]=node;else delete nodes[name];
 }
 intent.nodes=nodes;
 return intent;
}
// The inverse of designIntentFromForm: what the guided controls should show for a stored (or draft) intent.
function designFormFromIntent(intent){
 intent=intent&&typeof intent==='object'?intent:{};
 const families=intent.families||{},addressing=intent.addressing||{};
 const loopback=addressing.loopback||{},p2p=addressing.p2p||{},lan=addressing.lan||{};
 const nodes=intent.nodes||{};
 let bgpRr='';
 const devices=Object.keys(nodes).sort().map(name=>{
  const node=nodes[name]||{};
  if(node&&node.bgp&&node.bgp.rr)bgpRr=name;
  return {name,role:node.role||'router'};
 });
 return {
  ipv4:families.ipv4!==false,ipv6:families.ipv6!==false,
  pools:{
   loopback:{ipv4:loopback.ipv4||'',ipv6:loopback.ipv6||''},
   p2p:{ipv4:p2p.ipv4||'',ipv6:p2p.ipv6||'',prefix:p2p.prefix||31},
   lan:{ipv4:lan.ipv4||'',ipv6:lan.ipv6||'',prefix:lan.prefix||24}
  },
  modules:[...(intent.modules||[])],
  ospfArea:(intent.ospf&&intent.ospf.area)||'0.0.0.0',
  bgpAs:(intent.bgp&&intent.bgp.as)||65000,
  bgpRr,
  isisArea:(intent.isis&&intent.isis.area)||'49.0001',
  isisType:(intent.isis&&intent.isis.type)||'level-2',
  gatewayProtocol:(intent.gateway&&intent.gateway.protocol)||'anycast',
  devices
 };
}

// --- markup: problems, modules, devices, ledger, history, files ---------------------------------------
function designProblemsMarkup(problems){
 if(!problems||!problems.length)return '';
 return '<ul>'+problems.map(p=>`<li><strong>${esc(p&&p.path||'')}</strong>: ${esc(p&&p.message||'')}</li>`).join('')+'</ul>';
}
function designModulesMarkup(modules,selected){
 const chosen=new Set(selected||[]);
 return (modules||[]).map(id=>`<label class="checkbox-label"><input type="checkbox" name="design-module" value="${esc(id)}" ${chosen.has(id)?'checked':''}> ${esc(designModuleLabel(id))}</label>`).join('');
}
function designRoleOptions(current){
 return ['router','host','exclude'].map(r=>`<option value="${r}" ${r===(current||'router')?'selected':''}>${r==='router'?'Router':r==='host'?'Host':'Exclude'}</option>`).join('');
}
function designDeviceRow(name,row,role){
 row=row||{};
 const reason=row.profile?'':(row.reason||'No design profile is mapped to this kind of device');
 const profileCell=row.profile?esc(row.profile):`<span class="status-neutral">${esc(reason)}</span>`;
 return `<tr><td>${esc(name)}</td><td>${esc(row.kind||'')}</td><td>${profileCell}</td>`+
  `<td><select data-design-role="${esc(name)}" ${row.profile?'':'disabled'} ${reason?`title="${esc(reason)}"`:''}>${designRoleOptions(role)}</select></td>`+
  `<td>${row.blocked?esc(row.blocked):''}</td></tr>`;
}
function designDevicesMarkup(nodes,roles){
 nodes=nodes||{};roles=roles||{};
 const names=Object.keys(nodes).sort();
 if(!names.length)return '<tr><td colspan="5" class="table-empty">This lab has no devices yet.</td></tr>';
 return names.map(name=>designDeviceRow(name,nodes[name],roles[name])).join('');
}
function designLedgerMarkup(allocations){
 allocations=allocations||{};
 const loopbacks=allocations.loopbacks||{},links=allocations.links||{};
 const deviceRows=Object.keys(loopbacks).sort().map(name=>`<tr><td>${esc(name)}</td><td class="mono">${esc(loopbacks[name].ipv4||'')}</td><td class="mono">${esc(loopbacks[name].ipv6||'')}</td></tr>`).join('');
 const linkRows=Object.keys(links).sort().map(key=>`<tr><td class="mono">${esc(key)}</td><td class="mono">${esc(links[key].ipv4||'')}</td><td class="mono">${esc(links[key].ipv6||'')}</td></tr>`).join('');
 if(!deviceRows&&!linkRows)return '<p class="caption">No allocations recorded yet. They appear here once a plan has been generated.</p>';
 return `<div class="table-wrap"><table><caption>Devices</caption><thead><tr><th>Device</th><th>Loopback IPv4</th><th>Loopback IPv6</th></tr></thead><tbody>${deviceRows||'<tr><td colspan="3" class="table-empty">None</td></tr>'}</tbody></table></div>`+
  `<div class="table-wrap"><table><caption>Links</caption><thead><tr><th>Link</th><th>Prefix IPv4</th><th>Prefix IPv6</th></tr></thead><tbody>${linkRows||'<tr><td colspan="3" class="table-empty">None</td></tr>'}</tbody></table></div>`;
}
function designHistoryWord(status){return {queued:'Waiting to start',running:'Generating…',succeeded:'Succeeded',failed:'Failed',interrupted:'Interrupted'}[status]||String(status||'');}
function designHistoryPill(status){return status==='succeeded'?'ok':status==='failed'?'danger':status==='interrupted'?'warn':DESIGN_BUSY_GENERATION.includes(status)?'busy':'neutral';}
function designHistoryMarkup(generations,now){
 const list=[...(generations||[])].reverse();
 if(!list.length)return '<p class="caption">No plans generated yet.</p>';
 return '<ul class="design-history-list">'+list.map(g=>`<li><span class="pill ${designHistoryPill(g.status)}">${esc(designHistoryWord(g.status))}</span> `+
  `<span>${esc(typeof relativeTime==='function'?relativeTime(g.finished||g.created,now):'')}</span> <span>${esc(g.message||'')}</span></li>`).join('')+'</ul>';
}
function designFileSize(bytes){bytes=Number(bytes)||0;return bytes<1024?bytes+' B':Math.round(bytes/1024)+' KiB';}
function designFilesMarkup(generation){
 if(!generation||generation.status!=='succeeded')return '<p class="caption">Generate a plan to see its files here.</p>';
 const artifacts=generation.artifacts||{};
 const names=Object.keys(artifacts).sort();
 if(!names.length)return '<p class="caption">This plan has no generated files.</p>';
 return names.map(name=>`<div class="design-file-group"><strong>${esc(name)}</strong><ul class="design-file-list">`+
  (artifacts[name]||[]).map((a,index)=>`<li><span>${esc(a.module||'')}</span> <span class="caption">${esc(designFileSize(a.size))}</span> `+
   `<button type="button" class="button secondary small" data-design-view-file="${esc(name)}" data-design-view-index="${index}">View</button></li>`).join('')+
  '</ul></div>').join('');
}
function designRenumberingMarkup(list){
 if(!list||!list.length)return '';
 return '<div class="table-wrap"><table><thead><tr><th>Kind</th><th>Name</th><th>Family</th><th>Before</th><th>After</th></tr></thead><tbody>'+
  list.map(r=>`<tr><td>${esc(r.kind||'')}</td><td>${esc(r.name||'')}</td><td>${esc(r.family||'—')}</td><td class="mono">${esc(r.before)}</td><td class="mono">${esc(r.after)}</td></tr>`).join('')+
  '</tbody></table></div>';
}

// --- generated plan and compatibility markup -----------------------------------------------------------
function designNeighbourText(interfaceEntry){
 return ((interfaceEntry&&interfaceEntry.neighbors)||[]).map(n=>n&&n.node).filter(Boolean).join(', ');
}
function designProtocolNotes(interfaceEntry){
 const notes=[];
 if(interfaceEntry.ospf&&typeof interfaceEntry.ospf==='object'){
  if(interfaceEntry.ospf.area!==undefined&&interfaceEntry.ospf.area!==null)notes.push('OSPF area '+interfaceEntry.ospf.area);
  if(interfaceEntry.ospf.passive)notes.push('OSPF passive');
 }
 if(interfaceEntry.isis&&typeof interfaceEntry.isis==='object'&&interfaceEntry.isis.passive)notes.push('IS-IS passive');
 if(interfaceEntry.bgp&&typeof interfaceEntry.bgp==='object')notes.push('BGP');
 return notes.join(' · ');
}
function designInterfaceRow(i){
 i=i||{};
 return `<tr><td>${esc(i.ifname||'')}</td><td>${esc(i.clab||'')}</td><td class="mono">${esc(i.ipv4||'')}</td><td class="mono">${esc(i.ipv6||'')}</td>`+
  `<td>${esc(designNeighbourText(i))}</td><td>${esc(designProtocolNotes(i))}</td></tr>`;
}
function designBgpTable(bgp){
 if(!bgp||!(bgp.neighbors||[]).length)return '';
 const rows=bgp.neighbors.map(n=>`<tr><td>${esc(n.name||'')}</td><td>${esc(n.as??'')}</td><td>${esc(n.type||'')}</td><td class="mono">${esc(n.ipv4||'')}</td><td class="mono">${esc(n.ipv6||'')}</td></tr>`).join('');
 return `<div class="table-wrap"><table><caption>BGP sessions</caption><thead><tr><th>Neighbour</th><th>AS</th><th>Type</th><th>IPv4</th><th>IPv6</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function designDeviceBlock(device){
 device=device||{};
 const loop=device.loopback||{};
 const interfaces=(device.interfaces||[]).map(designInterfaceRow).join('')||'<tr><td colspan="6" class="table-empty">No interfaces</td></tr>';
 return `<article class="design-device"><h4>${esc(device.name||'')}</h4><dl class="kv"><dt>Profile</dt><dd>${esc(device.device||'')}</dd>`+
  `<dt>Id</dt><dd>${esc(device.id??'')}</dd><dt>Loopback IPv4</dt><dd class="mono">${esc(loop.ipv4||'')}</dd>`+
  `<dt>Loopback IPv6</dt><dd class="mono">${esc(loop.ipv6||'')}</dd><dt>Router id</dt><dd class="mono">${esc(device.router_id||'')}</dd></dl>`+
  `<div class="table-wrap"><table><thead><tr><th>Interface</th><th>Containerlab port</th><th>IPv4</th><th>IPv6</th><th>Neighbour(s)</th><th>Protocol notes</th></tr></thead><tbody>${interfaces}</tbody></table></div>`+
  designBgpTable(device.bgp)+'</article>';
}
function designLinkRow(link){
 link=link||{};
 const prefix=link.prefix||{};
 const ends=(link.ends||[]).map(e=>esc(e.node||'')+(e.ifname?' ('+esc(e.ifname)+')':'')).join(' — ');
 return `<tr><td>${esc(link.index??'')}</td><td>${esc(link.type||'')}</td><td class="mono">${esc(prefix.ipv4||'')}</td><td class="mono">${esc(prefix.ipv6||'')}</td><td>${ends}</td></tr>`;
}
function designPlanMarkup(plan){
 if(!plan||!plan.devices)return '<p class="caption">Generate a plan to see it here.</p>';
 const devices=(plan.devices||[]).map(designDeviceBlock).join('');
 const links=(plan.links||[]).map(designLinkRow).join('')||'<tr><td colspan="5" class="table-empty">No links</td></tr>';
 return `<div class="design-plan-devices">${devices}</div><h4>Links</h4><div class="table-wrap"><table><thead><tr><th>Index</th><th>Type</th><th>Prefix IPv4</th><th>Prefix IPv6</th><th>Ends</th></tr></thead><tbody>${links}</tbody></table></div>`;
}
function designLevelWord(level,reason){
 if(level==='blocked_missing_prerequisite')return reason?'Needs '+reason.replace(/^'[^']*' requires /,''):'Needs a prerequisite module';
 return DESIGN_LEVEL_WORDS[level]||String(level||'');
}
// One row per device, one column per requested feature across every device, from generation.compatibility
// (design_capabilities.resolve() output): {feature,level,reason,evidence,profile}.
function designCompatibilityMarkup(generation){
 const compat=(generation&&generation.compatibility)||{};
 const names=Object.keys(compat);
 if(!names.length)return '<p class="caption">No compatibility information yet.</p>';
 const features=[...new Set(names.flatMap(n=>(compat[n]||[]).map(r=>r.feature)))].sort();
 const header=features.map(f=>`<th>${esc(f)}</th>`).join('');
 const rows=names.sort().map(name=>{
  const byFeature={};for(const r of compat[name]||[])byFeature[r.feature]=r;
  const cells=features.map(f=>{
   const r=byFeature[f];if(!r)return '<td>—</td>';
   const cls=DESIGN_LEVEL_CLASS[r.level]||'neutral';
   return `<td><span class="pill ${esc(cls)}" title="${esc(r.reason||'')}">${esc(designLevelWord(r.level,r.reason))}</span></td>`;
  }).join('');
  return `<tr><th scope="row">${esc(name)}</th>${cells}</tr>`;
 }).join('');
 return `<div class="table-wrap"><table class="design-compatibility"><thead><tr><th>Device</th>${header}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function designSafeRelative(value,now){return typeof relativeTime==='function'?relativeTime(value,now):'';}
// The generation's status line: "Plan generated 3 minutes ago", "Generating the plan…", etc.
function designGenerationLine(generation,now){
 if(!generation)return 'No plan generated yet.';
 const when=designSafeRelative(generation.finished,now)||designSafeRelative(generation.created,now);
 if(DESIGN_BUSY_GENERATION.includes(generation.status))return 'Generating the plan…'+(generation.message?' '+generation.message:'');
 if(generation.status==='succeeded')return 'Plan generated'+(when?' '+when:'')+'.';
 if(generation.status==='failed')return 'Plan generation failed'+(when?' '+when:'')+'.';
 if(generation.status==='interrupted')return 'Plan generation was interrupted'+(when?' '+when:'')+'.';
 return generation.message||String(generation.status||'');
}

// --- imperative wiring: fetch, poll, render, form, actions ---------------------------------------------
// designState is the module-level cache the spec calls for: {labId,view,plan,draft,loading,error}.
// view is the GET .../design document; plan is the plan.json of the newest succeeded generation (fetched
// separately, since network_design.py keeps it on disk, not on the lightweight generation record).
let designState={labId:'',view:null,plan:null,draft:null,draftDiscarded:false,loading:false,error:''};
let designWatch=null,designWatchTimer=null;
function designCurrentIntent(view){
 if(designState.draft&&designState.draft.intent)return designState.draft.intent;
 return (view&&view.intent)||designEmptyIntent();
}
function designStopWatch(){clearTimeout(designWatchTimer);designWatch=null;}
function designNewestGeneration(view){const g=(view&&view.generations)||[];return g.length?g[g.length-1]:null;}
function designApplyDraft(labId,view){
 designState.draftDiscarded=false;
 const stored=typeof readDesignDraft==='function'?readDesignDraft(labId):null;
 if(!stored){designState.draft=null;return;}
 const currentRevision=(view.intent&&view.intent.revision)||'';
 if(stored.revision===currentRevision)designState.draft=stored;
 else{designState.draft=null;designState.draftDiscarded=true;if(typeof clearDesignDraft==='function')clearDesignDraft(labId);}
}
async function designLoadPlan(labId,generationId){
 try{
  const data=await(await api('/labs/'+encodeURIComponent(labId)+'/design/generations/'+encodeURIComponent(generationId))).json();
  if(designState.labId===labId)designState.plan=data.plan||null;
 }catch{if(designState.labId===labId)designState.plan=null;}
}
async function designLoad(labId){
 designState={labId,view:null,plan:null,draft:null,draftDiscarded:false,loading:true,error:''};
 designRenderAll();
 try{
  const view=await(await api('/labs/'+encodeURIComponent(labId)+'/design')).json();
  if(designState.labId!==labId)return;
  designState.view=view;designState.loading=false;
  designApplyDraft(labId,view);
  const newest=designNewestGeneration(view);
  if(newest&&newest.status==='succeeded')await designLoadPlan(labId,newest.id);
  if(designState.labId!==labId)return;
  designRenderAll();designMaybeStartWatch();
 }catch(error){
  if(designState.labId!==labId)return;
  designState.loading=false;designState.error=error.message;designRenderAll();
 }
}
function designMaybeStartWatch(){
 const newest=designNewestGeneration(designState.view);
 if(!newest||!DESIGN_BUSY_GENERATION.includes(newest.status)){designStopWatch();return;}
 if(designWatch===designState.labId)return;
 designStopWatch();designWatch=designState.labId;
 const labId=designState.labId;
 const poll=async()=>{
  if(designWatch!==labId)return;
  try{
   const view=await(await api('/labs/'+encodeURIComponent(labId)+'/design')).json();
   if(designWatch!==labId||designState.labId!==labId)return;
   designState.view=view;
   const next=designNewestGeneration(view);
   if(next&&DESIGN_BUSY_GENERATION.includes(next.status)){designRenderAll();designWatchTimer=setTimeout(poll,2000);}
   else{
    designStopWatch();
    if(next&&next.status==='succeeded')await designLoadPlan(labId,next.id);
    designRenderAll();
    if(typeof refresh==='function')await refresh();
   }
  }catch{designStopWatch();}
 };
 designWatchTimer=setTimeout(poll,2000);
}
// --- form focus guard: never rewrite a guided control while the student is using it -------------------
function designFormFocused(){
 const form=$('design-form');
 return !!(form&&document.activeElement&&typeof form.contains==='function'&&form.contains(document.activeElement));
}
function designToggleModuleSettings(modules){
 const set=new Set(modules||[]);
 if($('design-ospf-settings'))$('design-ospf-settings').hidden=!set.has('ospf');
 if($('design-bgp-settings'))$('design-bgp-settings').hidden=!set.has('bgp');
 if($('design-isis-settings'))$('design-isis-settings').hidden=!set.has('isis');
 if($('design-gateway-settings'))$('design-gateway-settings').hidden=!set.has('gateway');
}
function designRenderDeviceOptions(view,values){
 const nodes=(view&&view.nodes)||{};
 const roles={};for(const d of values.devices)roles[d.name]=d.role;
 setMarkup($('design-devices'),designDevicesMarkup(nodes,roles));
 if($('design-bgp-rr')){
  const names=Object.keys(nodes).filter(n=>nodes[n]&&nodes[n].included&&(roles[n]||'router')==='router').sort();
  const options='<option value="">None</option>'+names.map(n=>`<option value="${esc(n)}" ${values.bgpRr===n?'selected':''}>${esc(n)}</option>`).join('');
  if($('design-bgp-rr').innerHTML!==options)$('design-bgp-rr').innerHTML=options;
  $('design-bgp-rr').value=values.bgpRr||'';
 }
}
function designSetControlValue(id,value){if($(id))$(id).value=value;}
function designRenderForm(view){
 const intent=designCurrentIntent(view);
 const values=designFormFromIntent(intent);
 if(!designFormFocused()){
  if($('design-ipv4'))$('design-ipv4').checked=values.ipv4;
  if($('design-ipv6'))$('design-ipv6').checked=values.ipv6;
  designSetControlValue('design-pool-loopback-ipv4',values.pools.loopback.ipv4);
  designSetControlValue('design-pool-loopback-ipv6',values.pools.loopback.ipv6);
  designSetControlValue('design-pool-p2p-ipv4',values.pools.p2p.ipv4);
  designSetControlValue('design-pool-p2p-ipv6',values.pools.p2p.ipv6);
  designSetControlValue('design-pool-p2p-prefix',values.pools.p2p.prefix);
  designSetControlValue('design-pool-lan-ipv4',values.pools.lan.ipv4);
  designSetControlValue('design-pool-lan-ipv6',values.pools.lan.ipv6);
  designSetControlValue('design-pool-lan-prefix',values.pools.lan.prefix);
  setMarkup($('design-modules'),designModulesMarkup((view&&view.modules)||[],values.modules));
  designSetControlValue('design-ospf-area',values.ospfArea);
  designSetControlValue('design-bgp-as',values.bgpAs);
  designSetControlValue('design-isis-area',values.isisArea);
  designSetControlValue('design-isis-type',values.isisType);
  designSetControlValue('design-gateway-protocol',values.gatewayProtocol);
  designRenderDeviceOptions(view,values);
  if($('design-advanced'))$('design-advanced').value=JSON.stringify(intent,null,2);
 }
 designToggleModuleSettings(values.modules);
 if($('design-ledger'))setMarkup($('design-ledger'),designLedgerMarkup(intent.allocations));
}
function designRenderHeader(lab,view){
 const st=designStateOf(lab,view);
 if($('design-state-pill')){$('design-state-pill').className='pill '+(st.pill||'neutral');$('design-state-pill').textContent=st.label;}
 if($('design-state-text'))$('design-state-text').textContent=st.label;
 if($('design-detail'))$('design-detail').textContent=designState.draftDiscarded
  ?'Your unsaved changes were older than the saved design and were discarded.':(st.detail||'');
 const engine=view&&view.engine,engineOk=!engine||engine.available!==false;
 if($('design-engine')){$('design-engine').hidden=engineOk;if($('design-engine-text'))$('design-engine-text').textContent=(engine&&engine.diagnostic)||'';}
 if($('design-generate')){
  const busy=st.key==='generating',noTopology=view&&view.has_topology===false;
  $('design-generate').disabled=busy||!engineOk||noTopology;
  $('design-generate').title=!engineOk?((engine&&engine.diagnostic)||'The design engine is not available.')
   :busy?'A plan is already being generated for this lab.'
   :noTopology?'This lab has no topology file yet.':'';
  menuReasonSafe($('design-generate'),$('design-generate').disabled?$('design-generate').title:'');
 }
}
function menuReasonSafe(el,text){if(typeof menuReason==='function')menuReason(el,text);}
function designRenderPlanCard(view){
 const newest=designNewestGeneration(view);
 if($('design-plan-status'))$('design-plan-status').textContent=designGenerationLine(newest,Date.now());
 setMarkup($('design-plan-errors'),((newest&&newest.errors)||[]).map(e=>`<li>${esc(e)}</li>`).join(''));
 if($('design-plan-errors-wrap'))$('design-plan-errors-wrap').hidden=!((newest&&newest.errors)||[]).length;
 setMarkup($('design-plan-warnings'),((newest&&newest.warnings)||[]).map(w=>`<li>${esc(w)}</li>`).join(''));
 if($('design-plan-warnings-wrap'))$('design-plan-warnings-wrap').hidden=!((newest&&newest.warnings)||[]).length;
 setMarkup($('design-plan-renumbering'),designRenumberingMarkup(newest&&newest.renumbering));
 if($('design-plan-renumbering-wrap'))$('design-plan-renumbering-wrap').hidden=!((newest&&newest.renumbering)||[]).length;
 if($('design-plan-collisions')){
  const fixes=newest&&newest.collision_fixes,count=fixes?Object.keys(fixes).length:0;
  $('design-plan-collisions').hidden=!count;
  $('design-plan-collisions').textContent=count?'Some link prefixes collided with pinned addresses and were reassigned automatically ('+count+(count===1?' link':' links')+').':'';
 }
 setMarkup($('design-compatibility'),designCompatibilityMarkup(newest));
 setMarkup($('design-plan-body'),newest&&newest.status==='succeeded'?designPlanMarkup(designState.plan):'<p class="caption">Generate a plan to see it here.</p>');
 if($('design-cancel'))$('design-cancel').hidden=!(newest&&DESIGN_BUSY_GENERATION.includes(newest.status));
}
function designUpdateDownloadLink(lab,view){
 if(!$('design-download'))return;
 const newest=designNewestGeneration(view),ok=!!lab&&!!newest&&newest.status==='succeeded';
 $('design-download').hidden=!ok;
 if(ok)$('design-download').href='/api/labs/'+encodeURIComponent(lab.id)+'/design/generations/'+encodeURIComponent(newest.id)+'/download';
}
function designRenderFiles(view){setMarkup($('design-files-body'),designFilesMarkup(designNewestGeneration(view)));}
function designRenderHistory(view){setMarkup($('design-history-body'),designHistoryMarkup(view&&view.generations,Date.now()));}
function designActiveView(lab){
 if(designState.labId===lab.id&&designState.view)return {...designState.view,draft:!!designState.draft};
 const design=lab&&lab.design;
 if(!design)return {generations:[],problems:[],summary:{present:false}};
 return {generations:design.generation?[design.generation]:[],problems:[],summary:design};
}
// The single entry point, called from app.js's render() behind a typeof guard. Fetches the design once
// per lab when the Design tab is shown; otherwise only the header reflects the /api/state summary.
function renderNetworkDesign(){
 const lab=current();
 if(!lab){designStopWatch();return;}
 if(typeof tab!=='undefined'&&tab==='design'&&designState.labId!==lab.id&&!designState.loading){designLoad(lab.id);return;}
 designRenderAll();
}
function designRenderAll(){
 const lab=current();if(!lab)return;
 const view=designActiveView(lab);
 designRenderHeader(lab,view);
 if(designState.labId===lab.id&&designState.view){
  designRenderForm(view);
  designRenderPlanCard(view);
  designRenderFiles(view);
  designRenderHistory(view);
 }
 designUpdateDownloadLink(lab,view);
 designMaybeStartWatch();
}

// --- reading the guided controls back into a plain values object --------------------------------------
function designRolesFromDom(){
 const map={};
 if(typeof document==='undefined'||typeof document.querySelectorAll!=='function')return map;
 for(const select of document.querySelectorAll('[data-design-role]'))map[select.dataset.designRole]=select.value;
 return map;
}
function designVal(id){return $(id)?$(id).value:'';}
function designReadFormValues(){
 const modulesEls=typeof document!=='undefined'&&typeof document.querySelectorAll==='function'
  ?[...document.querySelectorAll('#design-modules input[name="design-module"]:checked')]:[];
 const modules=modulesEls.map(i=>i.value);
 const roles=designRolesFromDom();
 const nodes=(designState.view&&designState.view.nodes)||{};
 const devices=Object.keys(nodes).map(name=>({name,role:roles[name]||'router'}));
 return {
  ipv4:!!($('design-ipv4')&&$('design-ipv4').checked),ipv6:!!($('design-ipv6')&&$('design-ipv6').checked),
  pools:{
   loopback:{ipv4:designVal('design-pool-loopback-ipv4'),ipv6:designVal('design-pool-loopback-ipv6')},
   p2p:{ipv4:designVal('design-pool-p2p-ipv4'),ipv6:designVal('design-pool-p2p-ipv6'),prefix:designVal('design-pool-p2p-prefix')},
   lan:{ipv4:designVal('design-pool-lan-ipv4'),ipv6:designVal('design-pool-lan-ipv6'),prefix:designVal('design-pool-lan-prefix')}
  },
  modules,
  ospfArea:designVal('design-ospf-area'),bgpAs:designVal('design-bgp-as'),bgpRr:designVal('design-bgp-rr'),
  isisArea:designVal('design-isis-area'),isisType:designVal('design-isis-type'),gatewayProtocol:designVal('design-gateway-protocol'),
  devices
 };
}
function designSetDraft(labId,intent){
 designState.draft={revision:(designState.view&&designState.view.intent&&designState.view.intent.revision)||'',intent};
 designState.draftDiscarded=false;
 if(typeof writeDesignDraft==='function')writeDesignDraft(labId,designState.draft);
}
function designOnGuidedChange(){
 const lab=current();if(!lab)return;
 const base=designCurrentIntent(designState.view);
 const intent=designIntentFromForm(designReadFormValues(),base);
 designSetDraft(lab.id,intent);
 designRenderForm(designState.view);
 designRenderHeader(lab,designActiveView(lab));
}
function designOnAdvancedChange(){
 const lab=current();if(!lab)return;
 const text=$('design-advanced')?$('design-advanced').value:'';
 let parsed;
 try{parsed=JSON.parse(text);}
 catch(error){setMarkup($('design-problems'),designProblemsMarkup([{path:'advanced',message:'This is not valid JSON: '+error.message}]));return;}
 if(!parsed||typeof parsed!=='object'||Array.isArray(parsed)){
  setMarkup($('design-problems'),designProblemsMarkup([{path:'advanced',message:'The design must be a JSON object.'}]));return;
 }
 setMarkup($('design-problems'),'');
 designSetDraft(lab.id,parsed);
 designRenderForm(designState.view);
 designRenderHeader(lab,designActiveView(lab));
}
async function designValidate(){
 const lab=current();if(!lab)return;
 const intent=designCurrentIntent(designState.view);
 try{
  const result=await json('/labs/'+encodeURIComponent(lab.id)+'/design/validate','POST',{intent,revision:''});
  setMarkup($('design-problems'),designProblemsMarkup(result.problems||[]));
  if(typeof notify==='function')notify((result.problems||[]).length?'The design has problems. See the list below.':'No problems found.');
 }catch(error){if(typeof notify==='function')notify(error.message);}
}
function designStaleMessage(message){return /changed since this page loaded|no saved design any more/i.test(String(message||''));}
async function designSave(){
 const lab=current();if(!lab)return;
 const intent=designCurrentIntent(designState.view);
 const revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
 try{
  // Validate first: the save route itself answers a fixed-string 400, not a structured problem list.
  const check=await json('/labs/'+encodeURIComponent(lab.id)+'/design/validate','POST',{intent,revision:''});
  if((check.problems||[]).length){
   setMarkup($('design-problems'),designProblemsMarkup(check.problems));
   designRenderHeader(lab,{...designActiveView(lab),problems:check.problems});
   return;
  }
  const view=await json('/labs/'+encodeURIComponent(lab.id)+'/design','PUT',{intent,revision});
  designState.view=view;designState.draft=null;designState.draftDiscarded=false;
  if(typeof clearDesignDraft==='function')clearDesignDraft(lab.id);
  setMarkup($('design-problems'),'');
  if(typeof notify==='function')notify('Design saved.');
  designRenderAll();
 }catch(error){
  if(designStaleMessage(error.message)){
   if(typeof showActionError==='function')showActionError(error.message);else if(typeof notify==='function')notify(error.message);
   await designLoad(lab.id);return;
  }
  if(typeof notify==='function')notify(error.message);
 }
}
async function designGenerate(){
 const lab=current();if(!lab)return;
 const revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
 try{
  await json('/labs/'+encodeURIComponent(lab.id)+'/design/generate','POST',{revision});
  await designLoad(lab.id);
  if(typeof refresh==='function')await refresh();
 }catch(error){if(typeof notify==='function')notify(error.message);}
}
async function designCancel(){
 const lab=current();if(!lab)return;
 const newest=designNewestGeneration(designState.view);if(!newest)return;
 try{
  await json('/labs/'+encodeURIComponent(lab.id)+'/design/generations/'+encodeURIComponent(newest.id)+'/cancel','POST',{});
  if(typeof notify==='function')notify('Cancelling…');
 }catch(error){if(typeof notify==='function')notify(error.message);}
}
function designRenumber(){
 const lab=current();if(!lab||typeof opDialog!=='function')return;
 const dialog=opDialog('design-renumber-dialog','Renumber this design',
  '<p>The manager forgets every device id, loopback and link address this design has pinned. The next generated plan allocates them again from the pools, and devices may get different addresses.</p>'+
  '<div class="dialog-actions"><button type="button" class="button secondary" data-op-close>Cancel</button><button type="button" class="button danger" id="design-renumber-run">Forget allocations</button></div>');
 const closeButtons=dialog.querySelectorAll?dialog.querySelectorAll('[data-op-close]'):[];
 for(const b of closeButtons)b.onclick=()=>dialog.close();
 if($('design-renumber-run'))$('design-renumber-run').onclick=()=>opTask(dialog,async()=>{
  const revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
  const view=await json('/labs/'+encodeURIComponent(lab.id)+'/design/renumber','POST',{revision});
  designState.view=view;dialog.close();designRenderAll();if(typeof notify==='function')notify('Allocation ledger cleared.');
 });
}
function designClearDesign(){
 const lab=current();if(!lab||typeof opDialog!=='function')return;
 const dialog=opDialog('design-clear-dialog','Remove this design',
  "<p>The saved network design for this lab is removed. Generated plans and their files are kept and still listed under History.</p>"+
  '<div class="dialog-actions"><button type="button" class="button secondary" data-op-close>Cancel</button><button type="button" class="button danger" id="design-clear-run">Remove design</button></div>');
 const closeButtons=dialog.querySelectorAll?dialog.querySelectorAll('[data-op-close]'):[];
 for(const b of closeButtons)b.onclick=()=>dialog.close();
 if($('design-clear-run'))$('design-clear-run').onclick=()=>opTask(dialog,async()=>{
  const revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
  const view=await json('/labs/'+encodeURIComponent(lab.id)+'/design/clear','POST',{revision});
  designState.view=view;designState.draft=null;if(typeof clearDesignDraft==='function')clearDesignDraft(lab.id);
  dialog.close();designRenderAll();if(typeof notify==='function')notify('Design removed.');
});
}
function designExport(){
 const lab=current();if(!lab||typeof window==='undefined'||typeof window.open!=='function')return;
 window.open('/api/labs/'+encodeURIComponent(lab.id)+'/design/export','_blank');
}
function designImportPrompt(){if($('design-import-file'))$('design-import-file').click();}
async function designImportFile(file){
 const lab=current();if(!lab||!file)return;
 const revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
 const data=new FormData();data.append('intent',file);data.append('revision',revision);
 try{
  const result=await(await api('/labs/'+encodeURIComponent(lab.id)+'/design/import',{method:'POST',body:data})).json();
  if(!result.imported){
   setMarkup($('design-problems'),designProblemsMarkup(result.problems||[]));
   if(typeof notify==='function')notify('The imported design has problems. See Advanced › Check below.');
   return;
  }
  designState.view=result;designState.draft=null;designState.draftDiscarded=false;
  if(typeof clearDesignDraft==='function')clearDesignDraft(lab.id);
  setMarkup($('design-problems'),'');
  if(typeof notify==='function')notify('Design imported.');
  designRenderAll();
 }catch(error){
  if(designStaleMessage(error.message))await designLoad(lab.id);
  if(typeof notify==='function')notify(error.message);
 }
}
async function designViewFile(node,index){
 const lab=current();if(!lab)return;
 const newest=designNewestGeneration(designState.view);if(!newest||typeof opDialog!=='function')return;
 try{
  const text=await(await api('/labs/'+encodeURIComponent(lab.id)+'/design/generations/'+encodeURIComponent(newest.id)+'/artifacts/'+encodeURIComponent(node)+'/'+encodeURIComponent(index))).text();
  const entry=((newest.artifacts||{})[node]||[])[index];
  opDialog('design-file-dialog',(entry&&entry.module?entry.module+' · ':'')+node,`<pre class="op-output">${esc(text)}</pre>`);
 }catch(error){if(typeof notify==='function')notify(error.message);}
}

// --- load-time wiring: only when the Design tab's static skeleton is on the page ----------------------
function initNetworkDesign(){
 const guidedIds=['design-ipv4','design-ipv6','design-pool-loopback-ipv4','design-pool-loopback-ipv6',
  'design-pool-p2p-ipv4','design-pool-p2p-ipv6','design-pool-p2p-prefix','design-pool-lan-ipv4','design-pool-lan-ipv6',
  'design-pool-lan-prefix','design-ospf-area','design-bgp-as','design-bgp-rr','design-isis-area','design-isis-type','design-gateway-protocol'];
 for(const id of guidedIds)if($(id))$(id).addEventListener('change',designOnGuidedChange);
 if($('design-modules'))$('design-modules').addEventListener('change',designOnGuidedChange);
 if($('design-devices'))$('design-devices').addEventListener('change',e=>{if(e.target&&e.target.dataset&&e.target.dataset.designRole!==undefined)designOnGuidedChange();});
 if($('design-advanced'))$('design-advanced').addEventListener('change',designOnAdvancedChange);
 if($('design-validate'))$('design-validate').onclick=()=>designValidate();
 if($('design-generate'))$('design-generate').onclick=()=>designGenerate();
 if($('design-save'))$('design-save').onclick=()=>designSave();
 if($('design-cancel'))$('design-cancel').onclick=()=>designCancel();
 if($('design-export'))$('design-export').onclick=()=>{if(typeof closeMenus==='function')closeMenus();designExport();};
 if($('design-import'))$('design-import').onclick=()=>{if(typeof closeMenus==='function')closeMenus();designImportPrompt();};
 if($('design-import-file'))$('design-import-file').addEventListener('change',e=>{
  const file=e.target.files&&e.target.files[0];e.target.value='';if(file)designImportFile(file);
 });
 if($('design-renumber'))$('design-renumber').onclick=()=>{if(typeof closeMenus==='function')closeMenus();designRenumber();};
 if($('design-clear'))$('design-clear').onclick=()=>{if(typeof closeMenus==='function')closeMenus();designClearDesign();};
 if($('design-files-body'))$('design-files-body').addEventListener('click',e=>{
  const b=e.target.closest('[data-design-view-file]');if(b)designViewFile(b.dataset.designViewFile,Number(b.dataset.designViewIndex));
 });
 if($('tools-design'))$('tools-design').onclick=()=>{if(typeof showTab==='function')showTab('design');};
}
if(typeof document!=='undefined'&&document.getElementById&&$('design-view'))initNetworkDesign();
