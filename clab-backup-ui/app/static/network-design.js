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
 // VRFs, VLANs, links (vrf/vlan attachment) and static routes are guided fields like any other above,
 // but a caller that knows nothing about them (an older `values` object, or a test built before this
 // milestone) omits the key entirely rather than sending an empty list — that must leave the intent's
 // vrfs/vlans/links/nodes exactly as `base` had them, same as every other field this function does not
 // own. Only an explicit array (including an empty one, meaning "no rows in this table right now")
 // replaces what is there.
 let newVrfs=intent.vrfs&&typeof intent.vrfs==='object'?intent.vrfs:{};
 if(values.vrfs!==undefined){
  // intent.vrfs={name:{loopback:true|false,...}}; loopback omitted when false; any other key a VRF
  // object already has (rd, id, import, export) is merged in by the row's original key, never replaced.
  // A row with no name (never saved, or cleared by the student) is dropped.
  const existingVrfs=newVrfs;newVrfs={};
  for(const row of values.vrfs){
   const name=String((row&&row.name)||'').trim();if(!name)continue;
   const key=(row&&row.key)||name;
   const original=existingVrfs[key]&&typeof existingVrfs[key]==='object'?existingVrfs[key]:{};
   const vrf={...original};
   if(row.loopback)vrf.loopback=true;else delete vrf.loopback;
   newVrfs[name]=vrf;
  }
  intent.vrfs=newVrfs;
 }
 let newVlans=intent.vlans&&typeof intent.vlans==='object'?intent.vlans:{};
 if(values.vlans!==undefined){
  // intent.vlans={name:{id:N,...}}, merged the same way.
  const existingVlans=newVlans;newVlans={};
  for(const row of values.vlans){
   const name=String((row&&row.name)||'').trim();if(!name)continue;
   const key=(row&&row.key)||name;
   const original=existingVlans[key]&&typeof existingVlans[key]==='object'?existingVlans[key]:{};
   const vlan={...original};
   const id=Number(row&&row.id);
   if(Number.isFinite(id)&&id>0)vlan.id=id;else delete vlan.id;
   newVlans[name]=vlan;
  }
  intent.vlans=newVlans;
 }
 let newLinks=intent.links&&typeof intent.links==='object'?intent.links:{};
 if(values.links!==undefined){
  // Only `vrf` and `vlan` are touched; every other per-link setting (prefix, pool, modules, …) carries
  // over untouched. A link left with nothing at all (no vrf, no vlan, no other setting) is dropped rather
  // than kept as an empty object; a link not shown in this table (a stale key) is never touched.
  const existingLinks=newLinks;newLinks={...existingLinks};
  for(const row of values.links){
   const key=row&&row.key;if(!key)continue;
   const original=existingLinks[key]&&typeof existingLinks[key]==='object'?existingLinks[key]:{};
   const link={...original};
   if(row.vrf)link.vrf=row.vrf;else delete link.vrf;
   const trunk=(row.trunk||[]).map(v=>String(v).trim()).filter(Boolean);
   if(trunk.length)link.vlan={trunk};
   else if(row.vlanAccess)link.vlan={access:row.vlanAccess};
   else delete link.vlan;
   if(Object.keys(link).length)newLinks[key]=link;else delete newLinks[key];
  }
  intent.links=newLinks;
 }
 let staticByDevice=null;
 if(values.staticRoutes!==undefined){
  // intent.nodes[device].routing.static=[{ipv4|ipv6:prefix,nexthop:{discard:true}|{ipv4|ipv6:address}}].
  // A row with no prefix, no device, or an address next hop with no address is dropped. Every other
  // per-node setting (role, bgp, …) carries over untouched.
  staticByDevice={};
  for(const row of values.staticRoutes){
   const prefix=String((row&&row.prefix)||'').trim();if(!prefix)continue;
   const device=String((row&&(row.device||row.origDevice))||'').trim();if(!device)continue;
   const family=prefix.includes(':')?'ipv6':'ipv4';
   let nexthop;
   if(row.nexthopType==='discard')nexthop={discard:true};
   else{
    const address=String((row&&row.nexthopAddress)||'').trim();if(!address)continue;
    nexthop={[family]:address};
   }
   (staticByDevice[device]=staticByDevice[device]||[]).push({[family]:prefix,nexthop});
  }
  for(const device of new Set([...Object.keys(nodes),...Object.keys(staticByDevice)])){
   const hadStatic=!!(nodes[device]&&nodes[device].routing&&Array.isArray(nodes[device].routing.static));
   if(!staticByDevice[device]&&!hadStatic)continue;
   const node={...(nodes[device]&&typeof nodes[device]==='object'?nodes[device]:{})};
   const routing={...(node.routing&&typeof node.routing==='object'?node.routing:{})};
   if(staticByDevice[device])routing.static=staticByDevice[device];else delete routing.static;
   if(Object.keys(routing).length)node.routing=routing;else delete node.routing;
   if(Object.keys(node).length)nodes[device]=node;else delete nodes[device];
  }
  intent.nodes=nodes;
 }
 // The server refuses a link's vrf, or any VLAN, while its module is off (design_intent.py's own rule for
 // vlans/vrfs defined at all, and for a link referencing one); mirrored here so defining or attaching one
 // turns its module on. Gated on this call having actually touched that table (values.vrfs/vlans/links
 // undefined, e.g. an older caller, must leave `modules` alone even if `base` already carried VRFs/VLANs
 // from before this milestone existed). Never removed automatically — including `routing`, once a static
 // route exists — because a module can stay wanted for other reasons (BGP policy also lives under
 // `routing`) even after every route using it is deleted.
 const linksUseVrf=values.links!==undefined&&Object.values(newLinks).some(l=>l&&l.vrf);
 const linksUseVlan=values.links!==undefined&&Object.values(newLinks).some(l=>l&&l.vlan);
 if(((values.vrfs!==undefined&&Object.keys(newVrfs).length)||linksUseVrf)&&!modules.includes('vrf'))modules.push('vrf');
 if(((values.vlans!==undefined&&Object.keys(newVlans).length)||linksUseVlan)&&!modules.includes('vlan'))modules.push('vlan');
 if(staticByDevice&&Object.keys(staticByDevice).length&&!modules.includes('routing'))modules.push('routing');
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

// --- VRFs, VLANs, links (vrf/vlan attachment) and static routes: milestone E guided controls ----------
// Each table renders straight from the intent (never from cached form state) so an Advanced edit shows up
// here immediately; edits write back through designIntentFromForm, keyed by the *original* name/key
// (data-design-*-key on each row) so a row being renamed still merges onto the object it came from.
function designVrfRow(name,vrf){
 vrf=vrf||{};
 return `<tr data-design-vrf-key="${esc(name)}"><td><input type="text" class="mono" data-design-vrf-field="name" value="${esc(name)}" pattern="^[A-Za-z_][A-Za-z0-9_]{0,63}$" placeholder="red"></td>`+
  `<td><label class="checkbox-label"><input type="checkbox" data-design-vrf-field="loopback" ${vrf.loopback?'checked':''}> Loopback</label></td>`+
  `<td><button type="button" class="button secondary small" data-design-vrf-remove="${esc(name)}">Remove</button></td></tr>`;
}
function designVrfsMarkup(vrfs){
 vrfs=vrfs&&typeof vrfs==='object'?vrfs:{};
 const names=Object.keys(vrfs).sort();
 if(!names.length)return '<tr><td colspan="3" class="table-empty">No VRFs yet.</td></tr>';
 return names.map(name=>designVrfRow(name,vrfs[name])).join('');
}
function designVlanRow(name,vlan){
 vlan=vlan||{};
 return `<tr data-design-vlan-key="${esc(name)}"><td><input type="text" class="mono" data-design-vlan-field="name" value="${esc(name)}" pattern="^[A-Za-z_][A-Za-z0-9_]{0,63}$" placeholder="red"></td>`+
  `<td><input type="number" min="1" max="4094" data-design-vlan-field="id" value="${vlan.id!=null?esc(vlan.id):''}"></td>`+
  `<td><button type="button" class="button secondary small" data-design-vlan-remove="${esc(name)}">Remove</button></td></tr>`;
}
function designVlansMarkup(vlans){
 vlans=vlans&&typeof vlans==='object'?vlans:{};
 const names=Object.keys(vlans).sort();
 if(!names.length)return '<tr><td colspan="3" class="table-empty">No VLANs yet.</td></tr>';
 return names.map(name=>designVlanRow(name,vlans[name])).join('');
}
function designLinkEnds(link){
 link=link||{};
 const names=Object.keys(link.endpoints||{}).sort();
 if(names.length)return names.join(' — ');
 return String(link.key||'').split('--').map(e=>e.split(':')[0]).filter(Boolean).join(' — ');
}
// A link's settings this table does not cover (prefix, pool, per-endpoint overrides, other modules):
// shown as a caption so a student editing the guided table knows there is more to this link under Advanced.
function designLinkOtherKeysCaption(settings){
 const covered=new Set(['vrf','vlan']);
 const extra=Object.keys(settings||{}).filter(k=>!covered.has(k));
 return extra.length?`<p class="caption">Also set under Advanced: ${esc(extra.sort().join(', '))}</p>`:'';
}
function designLinkVrfVlanRow(link,settings,vrfNames,vlanNames){
 link=link||{};settings=settings&&typeof settings==='object'?settings:{};vrfNames=vrfNames||[];vlanNames=vlanNames||[];
 const key=link.key||'';
 const vrfOptions='<option value="">None</option>'+vrfNames.map(n=>`<option value="${esc(n)}" ${settings.vrf===n?'selected':''}>${esc(n)}</option>`).join('');
 const vlan=settings.vlan&&typeof settings.vlan==='object'?settings.vlan:{};
 const access=typeof vlan.access==='string'?vlan.access:'';
 const accessOptions='<option value="">None</option>'+vlanNames.map(n=>`<option value="${esc(n)}" ${access===n?'selected':''}>${esc(n)}</option>`).join('');
 const trunk=Array.isArray(vlan.trunk)?vlan.trunk:[];
 return `<tr data-design-link-key="${esc(key)}"><td class="mono">${esc(designLinkEnds(link))}</td>`+
  `<td><select data-design-link-field="vrf">${vrfOptions}</select></td>`+
  `<td><select data-design-link-field="vlan-access">${accessOptions}</select></td>`+
  `<td><input type="text" class="mono" data-design-link-field="vlan-trunk" value="${esc(trunk.join(','))}" placeholder="red,blue"></td>`+
  `<td>${designLinkOtherKeysCaption(settings)}</td></tr>`;
}
function designLinksMarkup(links,linkSettings,vrfNames,vlanNames){
 links=Array.isArray(links)?links:[];linkSettings=linkSettings&&typeof linkSettings==='object'?linkSettings:{};
 const rows=links.filter(l=>l&&l.key).map(l=>designLinkVrfVlanRow(l,linkSettings[l.key],vrfNames,vlanNames)).join('');
 return rows||'<tr><td colspan="5" class="table-empty">This lab has no designable links yet.</td></tr>';
}
function designStaticDeviceOptions(current,deviceNames){
 const names=new Set(deviceNames||[]);if(current)names.add(current);
 return [...names].sort().map(n=>`<option value="${esc(n)}" ${n===current?'selected':''}>${esc(n)}</option>`).join('');
}
function designStaticRouteRow(device,route,index,deviceNames){
 route=route&&typeof route==='object'?route:{};
 const family=route.ipv6!==undefined?'ipv6':'ipv4';
 const prefix=route[family]||'';
 const nexthop=route.nexthop&&typeof route.nexthop==='object'?route.nexthop:{};
 const discard=!!nexthop.discard;
 const address=discard?'':(nexthop.ipv6!==undefined?nexthop.ipv6:(nexthop.ipv4!==undefined?nexthop.ipv4:''));
 return `<tr data-design-static-key="${esc(device+':'+index)}"><td><select data-design-static-field="device">${designStaticDeviceOptions(device,deviceNames)}</select></td>`+
  `<td><input type="text" class="mono" data-design-static-field="prefix" value="${esc(prefix)}" placeholder="192.0.2.0/24"></td>`+
  `<td><select data-design-static-field="nexthop-type"><option value="discard" ${discard?'selected':''}>Discard</option><option value="address" ${discard?'':'selected'}>Address</option></select></td>`+
  `<td><input type="text" class="mono" data-design-static-field="nexthop-address" value="${esc(address)}" ${discard?'disabled':''} placeholder="192.0.2.1"></td>`+
  `<td><button type="button" class="button secondary small" data-design-static-remove="${esc(device+':'+index)}">Remove</button></td></tr>`;
}
function designStaticMarkup(nodes,deviceNames){
 nodes=nodes&&typeof nodes==='object'?nodes:{};
 const rows=[];
 for(const device of Object.keys(nodes).sort()){
  const list=nodes[device]&&nodes[device].routing&&Array.isArray(nodes[device].routing.static)?nodes[device].routing.static:[];
  list.forEach((route,index)=>rows.push(designStaticRouteRow(device,route,index,deviceNames)));
 }
 return rows.join('')||'<tr><td colspan="5" class="table-empty">No static routes yet.</td></tr>';
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

// --- Apply to devices (design_apply.py, docs/netlab-integration/PROVISIONING.md §4-5): the review and
// apply dialog on the plan card. Pure markup and word tables first; DOM wiring is in its own section
// below, after the imperative wiring for the rest of the tab.
const DESIGN_APPLY_JOB_BUSY=['queued','preflight','backing_up','applying','confirming','verifying'];
const DESIGN_APPLY_STAGE_WORDS={queued:'Waiting',backing_up:'Backing up first',connecting:'Connecting',
 applying:'Staging the change',armed:'Change armed',confirming:'Confirming',verifying:'Reading back',applied:'Applied'};
const DESIGN_APPLY_OUTCOME_WORDS={verified:'Applied and verified',verify_mismatch:'Applied, read-back differs',
 applied:'Applied',no_op:'Already matched',failed:'Not changed',rolled_back:'Undone by the device',
 uncertain:'Outcome unknown',interrupted:'Interrupted',drifted:'Changed since the review',ineligible:'Not running',
 pending:'Waiting',backing_up:'Backing up',applying:'Applying',confirming:'Confirming'};
const DESIGN_APPLY_JOB_WORDS={succeeded:'Applied',partial:'Partly applied',failed:'Not applied',
 needs_attention:'Needs attention',interrupted:'Interrupted'};
const DESIGN_APPLY_OK=new Set(['verified','no_op','succeeded']);
const DESIGN_APPLY_WARN=new Set(['verify_mismatch','partial']);
const DESIGN_APPLY_DANGER=new Set(['failed','rolled_back','uncertain','needs_attention','drifted']);
const DESIGN_APPLY_BUSY_STATUS=new Set(['pending','backing_up','applying','confirming','verifying','queued','preflight']);
function designApplyStageWord(stage){return DESIGN_APPLY_STAGE_WORDS[stage]||String(stage||'');}
function designApplyOutcomeWord(status){return DESIGN_APPLY_OUTCOME_WORDS[status]||String(status||'');}
function designApplyJobWord(status){return DESIGN_APPLY_JOB_BUSY.includes(status)?'Applying…':(DESIGN_APPLY_JOB_WORDS[status]||String(status||''));}
function designApplyPillClass(status){
 if(DESIGN_APPLY_OK.has(status))return 'ok';
 if(DESIGN_APPLY_WARN.has(status))return 'warn';
 if(DESIGN_APPLY_DANGER.has(status))return 'danger';
 if(DESIGN_APPLY_BUSY_STATUS.has(status))return 'busy';
 return 'neutral';
}
// One checkbox per device the plan includes (generation.nodes[name]: included, role, kind, blocked). A
// support host (role 'host') or a device the plan could not map (blocked) is listed unchecked and disabled.
function designApplyChooseMarkup(nodes,selected){
 nodes=nodes||{};selected=selected||new Set();
 const names=Object.keys(nodes).filter(n=>nodes[n]&&nodes[n].included).sort();
 if(!names.length)return '<p class="caption">This plan has no devices to apply.</p>';
 return names.map(name=>{
  const row=nodes[name]||{};
  const reason=row.role==='host'?'A support host is generated only, never applied.':(row.blocked||'');
  const checked=!reason&&selected.has(name);
  return `<label class="checkbox-label ${reason?'disabled':''}"><input type="checkbox" name="design-apply-target" value="${esc(name)}" ${reason?'disabled':''} ${checked?'checked':''}>`+
   `<span><strong>${esc(name)}</strong> <span class="caption">${esc(row.kind||'')}</span>${reason?`<small>${esc(reason)}</small>`:''}</span></label>`;
 }).join('');
}
// The compatibility rows of one device, reusing designLevelWord/DESIGN_LEVEL_CLASS from the plan card.
function designApplyCompatMarkup(compatibility){
 const rows=compatibility||[];
 if(!rows.length)return '';
 return '<ul class="design-apply-compat">'+rows.map(r=>`<li><span class="pill ${esc(DESIGN_LEVEL_CLASS[r.level]||'neutral')}" title="${esc(r.reason||'')}">${esc(r.feature||'')}: ${esc(designLevelWord(r.level,r.reason))}</span></li>`).join('')+'</ul>';
}
// design_apply.py's masked() caps added/removed/stale/conflicts/expected/removals/kept_manual samples at
// SAMPLE=40 while counts[...] keeps the real total; when the sample is shorter than its count, whichever
// block below ends with this line says so instead of silently hiding the rest.
function designApplyMoreLine(shown,count){
 const more=(count||0)-(shown||0);
 return more>0?`<p class="caption">… and ${esc(more)} more</p>`:'';
}
// One device's review block: eligibility/reachability/readiness reason when not ready, the counts line,
// protected settings, diff, expected changes, removal commands, conflicts (with the take-over choice)
// and kept-manual containers. `takeover` is the Set of device names the student chose to take over.
function designApplyDeviceMarkup(target,takeover){
 target=target||{};takeover=takeover||new Set();
 const heading=`<h4>${esc(target.name||'')} <span class="caption">${esc(target.kind||'')}</span></h4>`;
 const compat=designApplyCompatMarkup(target.compatibility);
 if(!target.eligible)return `<article class="design-apply-device">${heading}<p class="form-help">${esc(target.reason||'This device is not part of the plan.')}</p>${compat}</article>`;
 if(!target.reachable||!target.ready)return `<article class="design-apply-device">${heading}<p class="form-help">${esc(target.reason||'This device could not be reviewed.')}</p>${compat}</article>`;
 if(target.no_op)return `<article class="design-apply-device">${heading}<p class="form-help">Already matches the plan.</p>${compat}</article>`;
 const counts=target.counts||{};
 const countsLine=`Added ${counts.added||0} · Removed ${counts.removals||0} · Stale ${counts.stale||0} · Conflicts ${counts.conflicts||0} · Expected ${counts.expected||0}`;
 // Server-confirmed on this review response (design_apply.py's per-target `takeover`), independent of the
 // dialog's own take-over selection below — shown so the acknowledgement's scope is never a guess.
 const takingOver=target.takeover?`<p class="caption">Taking over ${esc(counts.conflicts||(target.conflicts||[]).length||0)} manual setting(s)</p>`:'';
 const protectedList=(target.protected||[]).length
  ?`<details class="design-apply-protected"><summary>Protected settings left out (${target.protected.length})</summary><ul>${target.protected.map(p=>`<li><strong>${esc(p.module||'')}</strong>: ${esc(p.statement||'')} — ${esc(p.reason||'')}</li>`).join('')}</ul></details>` :'';
 const diffPre=(target.diff||[]).length?`<pre class="mono design-apply-diff">${target.diff.map(esc).join('\n')}</pre>`:'<p class="caption">No differences.</p>';
 const expectedList=(target.expected||[]).length?`<details><summary>Expected changes (${target.expected.length})</summary><ul>${target.expected.map(e=>`<li class="mono">${esc(e)}</li>`).join('')}</ul>${designApplyMoreLine(target.expected.length,counts.expected)}</details>`:'';
 const removalsList=(target.removals||[]).length?`<details><summary>Removal commands (${target.removals.length})</summary><pre class="mono design-apply-diff">${target.removals.map(esc).join('\n')}</pre>${designApplyMoreLine(target.removals.length,counts.removals)}</details>`:'';
 const takenOver=takeover.has(target.name);
 const conflictsBlock=(target.conflicts||[]).length
  ?`<div class="design-apply-conflict"><p class="form-help">Conflicts with manual configuration on this device.</p><ul>${target.conflicts.map(c=>`<li class="mono">${esc(c)}</li>`).join('')}</ul>${designApplyMoreLine(target.conflicts.length,counts.conflicts)}`+
   `<label class="checkbox-label"><input type="checkbox" data-design-apply-takeover="${esc(target.name)}" ${takenOver?'checked':''}> Take over these settings on this device</label>`+
   (takenOver?"<p class=\"caption\">These manual settings will be replaced and become the design's.</p>":'')+'</div>':'';
 const keptManual=(target.kept_manual||[]).length?`<details><summary>Kept — manual configuration underneath (${target.kept_manual.length})</summary><ul>${target.kept_manual.map(k=>`<li class="mono">${esc(k)}</li>`).join('')}</ul>${designApplyMoreLine(target.kept_manual.length,counts.kept_manual)}</details>`:'';
 return `<article class="design-apply-device">${heading}<p class="caption">${esc(countsLine)}</p>${takingOver}${protectedList}<h5>Differences</h5>${diffPre}${expectedList}${removalsList}${conflictsBlock}${keptManual}${compat}</article>`;
}
function designApplyReviewMarkup(review,takeover){
 if(!review||!review.targets||!review.targets.length)return '<p class="caption">Choose at least one device to review.</p>';
 return review.targets.map(t=>designApplyDeviceMarkup(t,takeover)).join('');
}
// Enabled only when acknowledged, the review has something applicable, and every ready device with a
// conflict is either taken over or resolved (design_apply.review()'s own `applicable` rule, checked
// again here so a stale take-over choice cannot slip through).
function designApplyCanSubmit(review,takeover,acknowledged){
 if(!acknowledged||!review)return false;
 if(!(review.applicable||[]).length)return false;
 takeover=takeover||new Set();
 return !(review.targets||[]).some(t=>t.ready&&(t.counts&&t.counts.conflicts)&&!takeover.has(t.name));
}
function designApplyRequestId(){
 const bytes=new Uint8Array(16);
 if(typeof crypto!=='undefined'&&crypto&&typeof crypto.getRandomValues==='function')crypto.getRandomValues(bytes);
 else for(let i=0;i<bytes.length;i++)bytes[i]=Math.floor(Math.random()*256);
 return Array.from(bytes,n=>n.toString(16).padStart(2,'0')).join('');
}
function designApplyClampMinutes(value){
 const n=parseInt(value,10);
 return Math.min(30,Math.max(2,Number.isFinite(n)?n:5));
}
// The apply request body from the dialog's state; the request id is generated once per dialog (kept in
// designApplyState) so a retry after a network error is idempotent on the server.
function designApplyBody(opts){
 opts=opts||{};
 return {token:opts.token||'',confirm_minutes:designApplyClampMinutes(opts.confirmMinutes),
  request_id:opts.requestId||designApplyRequestId(),takeover:[...(opts.takeover||[])].sort(),acknowledged:!!opts.acknowledged};
}
function designApplyTargetRow(t){
 t=t||{};
 const verify=t.verify&&((t.verify.missing||[]).length||(t.verify.remaining||[]).length)
  ?`<p class="form-help">${esc((t.verify.missing||[]).length)} expected line(s) missing, ${esc((t.verify.remaining||[]).length)} stale line(s) remaining.</p>`:'';
 const keptManual=(t.kept_manual||[]).length?`<p class="caption">${esc(t.kept_manual.length)} setting(s) kept — manual configuration underneath.</p>`:'';
 const persistence=t.persistence==='not_saved'?'<p class="form-help">Applied, but not saved as startup configuration; a restart would lose it.</p>':'';
 return `<tr><td>${esc(t.name||'')}</td><td>${esc(t.kind||'')}</td><td>${esc(designApplyStageWord(t.stage))}</td>`+
  `<td><span class="pill ${esc(designApplyPillClass(t.status))}">${esc(designApplyOutcomeWord(t.status))}</span></td>`+
  `<td>${esc(t.message||'')}${verify}${keptManual}${persistence}</td></tr>`;
}
function designApplyProgressMarkup(job){
 job=job||{};
 const rows=(job.targets||[]).map(designApplyTargetRow).join('')||'<tr><td colspan="5" class="table-empty">No devices.</td></tr>';
 const progress=job.progress&&job.progress.total?`<p class="caption">${esc(job.progress.settled||0)} of ${esc(job.progress.total)} settled</p>`:'';
 return `<p class="caption">${esc(designApplyJobWord(job.status))}${job.message?' — '+esc(job.message):''}</p>${progress}`+
  `<div class="table-wrap"><table><thead><tr><th>Device</th><th>Kind</th><th>Stage</th><th>Outcome</th><th>Message</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
// The plan card's "last apply" line: the newest apply job of this lab, in words, with a Show button
// that reopens the dialog on that job's progress step.
function designApplyLastLineMarkup(job,now){
 if(!job)return '';
 const busy=DESIGN_APPLY_JOB_BUSY.includes(job.status);
 const when=designSafeRelative(job.finished||job.created,now);
 return `Last apply: ${esc(designApplyJobWord(job.status))}${when&&!busy?' · '+esc(when):''} `+
  `<button type="button" class="button secondary small" data-design-apply-show="${esc(job.id)}">Show</button>`;
}
// Under Advanced: per device, how many statements the design owns, from which plan, and whether a
// read-back is still pending; a <details> lists the (masked) statements themselves.
function designApplyOwnershipDeviceMarkup(name,summary,statements){
 summary=summary||{};statements=statements||[];
 const pending=summary.pending?' <span class="pill warn">Read-back pending</span>':'';
 const applied=designSafeRelative(summary.applied_at,Date.now());
 return `<details class="design-apply-owned"><summary>${esc(name)} — ${esc(summary.statements||0)} setting(s)${pending}</summary>`+
  `<p class="caption">Plan ${esc(String(summary.generation_id||'').slice(0,12))}${applied?' · applied '+esc(applied):''}</p>`+
  `<pre class="mono design-apply-diff">${statements.map(esc).join('\n')}</pre></details>`;
}
function designApplyOwnershipMarkup(ownership){
 ownership=ownership||{};
 const summary=ownership.summary||{},statements=ownership.statements||{};
 const names=Object.keys(summary).sort();
 if(!names.length)return '<p class="caption">No settings are owned by the design on any device yet.</p>';
 return names.map(n=>designApplyOwnershipDeviceMarkup(n,summary[n],statements[n])).join('');
}
// Why #design-apply is disabled, or '' when it is not (main.py's data-proxy-reason caption reads this
// button's .title automatically): no succeeded plan, a stale one (view.summary.stale — the same flag
// designStateOf reads for "Plan is older than the design"), the lab not linked/deployed, an apply
// already running for this lab, or the design engine unavailable.
function designApplyDisabledReason(lab,view,jobs){
 view=view||{};
 const engine=view.engine;
 if(engine&&engine.available===false)return engine.diagnostic||engine.reason||'The design engine is not available on this manager.';
 const newest=designNewestGeneration(view);
 if(!newest||newest.status!=='succeeded')return 'Generate a plan first.';
 if(view.summary&&view.summary.stale)return 'Generate the plan again: the design or the topology changed since this plan.';
 const status=(lab&&lab.deployment&&lab.deployment.status)||'Unlinked';
 if(status==='Unlinked')return 'This lab is not matched to a running lab.';
 if(status==='Unknown')return 'The lab VM cannot be reached right now.';
 if(status==='Not deployed'||status==='Stopped')return 'The lab is not running.';
 const running=(jobs||[]).some(j=>lab&&j.lab_id===lab.id&&DESIGN_APPLY_JOB_BUSY.includes(j.status));
 if(running)return 'An apply is already running for this lab.';
 return '';
}

// --- Export plan to Git… (git_progress.py export_design): a Git save of kind `design` into
// checkpoints/<name> of the lab's bound repository, holding the design file, the plan, the netlab
// topology, the endpoint mapping and every generated device file — never a backup, never a restore
// source. Like every other upload, it stops at review_pending; the review and the retry that actually
// uploads stay entirely in git-progress.js (gitReviewJob is the only sender of
// {push:true,reviewed:true}) — this file only ever sends the export request itself.
const DESIGN_EXPORT_CHECKPOINT_RE=/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/;
function designExportGitDefaultCheckpoint(generationId){return 'design-'+String(generationId||'').slice(0,12);}
function designExportGitValidCheckpoint(name){return DESIGN_EXPORT_CHECKPOINT_RE.test(String(name??''));}
function designExportGitRequestId(){const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return Array.from(bytes,n=>n.toString(16).padStart(2,'0')).join('');}
// A single-line note (a pasted newline or tab folds to a space, never rejected here), capped at the
// server's 200-character limit; left blank the server writes its own note naming the plan.
function designExportGitNote(value){return String(value??'').replace(/[\r\n\t]+/g,' ').replace(/\s+/g,' ').trim().slice(0,200);}
// Why #design-export-git is disabled, or '' when it is not (index.html's data-proxy-reason caption
// reads this button's .title automatically, the same pattern #design-apply uses).
function designExportGitReason(lab,view){
 const newest=designNewestGeneration(view||{});
 if(!newest||newest.status!=='succeeded')return 'Generate a plan first.';
 if(!lab||!lab.git_binding)return 'Bind this lab to a repository under Progress first.';
 return '';
}
// The repository's short name, the same rule git-progress.js's gitRepoName uses (kept local: this
// file's pure functions are tested without git-progress.js loaded).
function designExportGitRepoName(repo){return String(repo&&repo.path||'').split('/').filter(Boolean).pop()||(repo&&repo.label)||'Repository';}
// `<repository> › <branch> › <folder>` for the export dialog, the folder always ending in
// checkpoints/<name> — the export's own destination, distinct from the lab's latest/ save folder.
function designExportGitDestinationMarkup(binding,checkpoint){
 const repo=(binding&&binding.repository)||{};
 const folder=(repo.prefix?String(repo.prefix).replace(/\/$/,'')+'/':'')+'checkpoints/'+String(checkpoint||'');
 return `<p class="git-destination-line"><span>Saving to</span><code>${esc(designExportGitRepoName(repo))}</code>`+
  `<span aria-hidden="true">›</span><code>${esc(repo.branch||'')}</code><span aria-hidden="true">›</span><code>${esc(folder)}</code></p>`;
}
// The exact POST body of /design/generations/{id}/git: a fresh hex request id unless one is carried
// over (a retried submit reuses it so the server's replay check recognises it), the checkpoint as
// typed, the note trimmed to one line, and push always true — an export always stops at review_pending
// and is never uploaded by this file (see the header comment above).
function designExportGitBody(values){
 values=values||{};
 return {request_id:values.requestId||designExportGitRequestId(),checkpoint:values.checkpoint||'',note:designExportGitNote(values.note),push:true};
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
 // Only a field being typed in blocks a re-render: a focused button (Add VRF, remove) must not keep its own change from showing.
 const form=$('design-form');const active=document.activeElement;
 if(!form||!active||typeof form.contains!=='function'||!form.contains(active))return false;
 return ['INPUT','TEXTAREA','SELECT'].includes(String(active.tagName||'').toUpperCase())&&String(active.type||'').toLowerCase()!=='button';
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
  setMarkup($('design-vrfs'),designVrfsMarkup(intent.vrfs));
  setMarkup($('design-vlans'),designVlansMarkup(intent.vlans));
  setMarkup($('design-links'),designLinksMarkup((view&&view.links)||[],intent.links,Object.keys(intent.vrfs||{}).sort(),Object.keys(intent.vlans||{}).sort()));
  setMarkup($('design-static'),designStaticMarkup(intent.nodes,designRouterDeviceNames(view,values)));
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
 designRenderApplyButton(lab,view);
 designRenderExportGitButton(lab,view);
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
// One reader per new table, each scoped to its own tbody id so a stray element elsewhere on the page
// (there is none, but the next table added should keep the habit) cannot be picked up by mistake.
function designRowsIn(containerId,rowSelector){
 if(typeof document==='undefined'||typeof document.querySelectorAll!=='function')return [];
 const container=$(containerId);if(!container||typeof container.querySelectorAll!=='function')return [];
 return [...container.querySelectorAll(rowSelector)];
}
function designVrfsFromDom(){
 return designRowsIn('design-vrfs','[data-design-vrf-key]').map(row=>{
  const nameEl=row.querySelector('[data-design-vrf-field="name"]'),loopbackEl=row.querySelector('[data-design-vrf-field="loopback"]');
  return {key:row.dataset.designVrfKey,name:nameEl?nameEl.value:'',loopback:!!(loopbackEl&&loopbackEl.checked)};
 });
}
function designVlansFromDom(){
 return designRowsIn('design-vlans','[data-design-vlan-key]').map(row=>{
  const nameEl=row.querySelector('[data-design-vlan-field="name"]'),idEl=row.querySelector('[data-design-vlan-field="id"]');
  return {key:row.dataset.designVlanKey,name:nameEl?nameEl.value:'',id:idEl?idEl.value:''};
 });
}
function designLinksFromDom(){
 return designRowsIn('design-links','[data-design-link-key]').map(row=>{
  const vrfEl=row.querySelector('[data-design-link-field="vrf"]'),accessEl=row.querySelector('[data-design-link-field="vlan-access"]'),
   trunkEl=row.querySelector('[data-design-link-field="vlan-trunk"]');
  const trunk=trunkEl&&trunkEl.value?trunkEl.value.split(',').map(s=>s.trim()).filter(Boolean):[];
  return {key:row.dataset.designLinkKey,vrf:vrfEl?vrfEl.value:'',vlanAccess:accessEl?accessEl.value:'',trunk};
 });
}
function designStaticFromDom(){
 return designRowsIn('design-static','[data-design-static-key]').map(row=>{
  const [origDevice]=String(row.dataset.designStaticKey||'').split(':');
  const deviceEl=row.querySelector('[data-design-static-field="device"]'),prefixEl=row.querySelector('[data-design-static-field="prefix"]'),
   typeEl=row.querySelector('[data-design-static-field="nexthop-type"]'),addressEl=row.querySelector('[data-design-static-field="nexthop-address"]');
  return {origDevice,device:deviceEl?deviceEl.value:origDevice,prefix:prefixEl?prefixEl.value:'',
   nexthopType:typeEl?typeEl.value:'discard',nexthopAddress:addressEl?addressEl.value:''};
 });
}
// The designable routers of this lab (view.nodes, the adapter's device list — not values.devices, which
// only names devices the intent already has a setting for): the same rule designRenderDeviceOptions uses
// for the BGP route-reflector list, reused here for the static-route table's device options.
function designRouterDeviceNames(view,values){
 const nodes=(view&&view.nodes)||{};
 const roles={};for(const d of (values&&values.devices)||[])roles[d.name]=d.role;
 return Object.keys(nodes).filter(n=>nodes[n]&&nodes[n].included&&(roles[n]||'router')==='router').sort();
}
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
  devices,
  vrfs:designVrfsFromDom(),vlans:designVlansFromDom(),links:designLinksFromDom(),staticRoutes:designStaticFromDom()
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
// --- VRF/VLAN/static-route Add and Remove: these mutate the draft intent directly (never through
// designReadFormValues/designIntentFromForm) so a brand-new row is never dropped as "empty" before the
// student has had a chance to fill it in. A following edit anywhere on the form goes through the normal
// guided-change pipeline as usual and drops it then if it is still empty.
function designNextName(existing,prefix){
 existing=existing||{};let n=1;while(existing[prefix+n]!==undefined)n++;return prefix+n;
}
function designApplyIntentPatch(patch){
 const lab=current();if(!lab)return;
 const intent={...designCurrentIntent(designState.view),...patch};
 designSetDraft(lab.id,intent);
 designRenderForm(designState.view);
 designRenderHeader(lab,designActiveView(lab));
}
function designAddVrf(){
 const base=designCurrentIntent(designState.view);
 const vrfs={...(base.vrfs||{})};
 vrfs[designNextName(vrfs,'vrf')]={};
 designApplyIntentPatch({vrfs});
}
function designRemoveVrf(name){
 const base=designCurrentIntent(designState.view);
 const vrfs={...(base.vrfs||{})};delete vrfs[name];
 designApplyIntentPatch({vrfs});
}
function designNextVlanId(vlans){
 const used=new Set(Object.values(vlans||{}).map(v=>v&&v.id).filter(n=>typeof n==='number'));
 let id=1;while(used.has(id)&&id<4094)id++;return id;
}
function designAddVlan(){
 const base=designCurrentIntent(designState.view);
 const vlans={...(base.vlans||{})};
 vlans[designNextName(vlans,'vlan')]={id:designNextVlanId(vlans)};
 designApplyIntentPatch({vlans});
}
function designRemoveVlan(name){
 const base=designCurrentIntent(designState.view);
 const vlans={...(base.vlans||{})};delete vlans[name];
 designApplyIntentPatch({vlans});
}
function designAddStaticRoute(){
 const base=designCurrentIntent(designState.view);
 const routers=designRouterDeviceNames(designState.view,designReadFormValues());
 if(!routers.length)return;
 const device=routers[0];
 const nodes={...(base.nodes||{})};
 const node={...(nodes[device]&&typeof nodes[device]==='object'?nodes[device]:{})};
 const routing={...(node.routing&&typeof node.routing==='object'?node.routing:{})};
 routing.static=[...(Array.isArray(routing.static)?routing.static:[]),{ipv4:'',nexthop:{discard:true}}];
 node.routing=routing;nodes[device]=node;
 designApplyIntentPatch({nodes});
}
function designRemoveStatic(key){
 const [device,indexText]=String(key||'').split(':');
 const index=Number(indexText);
 const base=designCurrentIntent(designState.view);
 const nodes={...(base.nodes||{})};
 const node=nodes[device];
 if(!node||!node.routing||!Array.isArray(node.routing.static))return;
 const list=[...node.routing.static];list.splice(index,1);
 const routing={...node.routing};
 if(list.length)routing.static=list;else delete routing.static;
 const newNode={...node};
 if(Object.keys(routing).length)newNode.routing=routing;else delete newNode.routing;
 if(Object.keys(newNode).length)nodes[device]=newNode;else delete nodes[device];
 designApplyIntentPatch({nodes});
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

// --- Apply to devices: dialog state, fetch/poll and DOM wiring -----------------------------------------
// designApplyState is the dialog's own cache, separate from designState (which never survives an
// applied generation being superseded by a new one): {labId,step,generationId,nodes,selected,takeover,
// review,requestId,jobId,job}. requestId is generated once per dialog open so a retry after a network
// error resubmits the same idempotent request.
let designApplyState={labId:'',step:'choose',generationId:'',nodes:{},selected:new Set(),takeover:new Set(),review:null,requestId:'',jobId:'',job:null};
let designApplyWatch=null,designApplyWatchTimer=null;
function designApplyJobsOf(labId){return ((typeof state!=='undefined'&&state.design_jobs)||[]).filter(j=>j.lab_id===labId);}
function designApplyNewestJob(labId){const jobs=designApplyJobsOf(labId);return jobs.length?jobs[jobs.length-1]:null;}
function designApplyDefaultSelection(nodes){
 return new Set(Object.keys(nodes||{}).filter(n=>nodes[n]&&nodes[n].included&&nodes[n].role!=='host'&&!nodes[n].blocked));
}
function designRenderApplyButton(lab,view){
 if(!$('design-apply'))return;
 const reason=designApplyDisabledReason(lab,view,designApplyJobsOf(lab.id));
 $('design-apply').disabled=!!reason;
 $('design-apply').title=reason;
 designApplyRenderLast(lab.id);
}
function designRenderExportGitButton(lab,view){
 if(!$('design-export-git'))return;
 const reason=designExportGitReason(lab,view);
 $('design-export-git').disabled=!!reason;
 $('design-export-git').title=reason;
}
function designApplyRenderLast(labId){
 if(!$('design-apply-last'))return;
 const job=designApplyNewestJob(labId);
 $('design-apply-last').hidden=!job;
 if(job)setMarkup($('design-apply-last'),designApplyLastLineMarkup(job,Date.now()));
}
function designApplyShowStep(step){
 designApplyState.step=step;
 if($('design-apply-choose-step'))$('design-apply-choose-step').hidden=step!=='choose';
 if($('design-apply-review-step'))$('design-apply-review-step').hidden=step!=='review';
 if($('design-apply-progress-step'))$('design-apply-progress-step').hidden=step!=='progress';
}
function designApplyRenderChoose(){setMarkup($('design-apply-choose-body'),designApplyChooseMarkup(designApplyState.nodes,designApplyState.selected));}
function designApplyOpen(){
 const lab=current();if(!lab||!$('design-apply-dialog'))return;
 const view=designActiveView(lab),newest=designNewestGeneration(view);
 if(!newest||newest.status!=='succeeded')return;
 const nodes=view.nodes||{};
 designApplyState={labId:lab.id,step:'choose',generationId:newest.id,nodes,selected:designApplyDefaultSelection(nodes),
  takeover:new Set(),review:null,requestId:designApplyRequestId(),jobId:'',job:null};
 if($('design-apply-choose-error'))$('design-apply-choose-error').textContent='';
 if($('design-apply-review-error'))$('design-apply-review-error').textContent='';
 if($('design-apply-ack'))$('design-apply-ack').checked=false;
 if($('design-apply-minutes'))$('design-apply-minutes').value=5;
 designApplyRenderChoose();designApplyShowStep('choose');
 $('design-apply-dialog').showModal();
}
function designApplyChooseSelection(){
 if(typeof document==='undefined'||typeof document.querySelectorAll!=='function')return [...designApplyState.selected];
 return [...document.querySelectorAll('[name="design-apply-target"]:checked')].map(i=>i.value);
}
async function designApplyRunReview(){
 const targets=designApplyChooseSelection();
 designApplyState.selected=new Set(targets);
 if($('design-apply-choose-error'))$('design-apply-choose-error').textContent='';
 if(!targets.length){if($('design-apply-choose-error'))$('design-apply-choose-error').textContent='Choose at least one device.';return;}
 try{
  const review=await json('/labs/'+encodeURIComponent(designApplyState.labId)+'/design/generations/'+encodeURIComponent(designApplyState.generationId)+'/review',
   'POST',{targets,takeover:[...designApplyState.takeover].filter(n=>targets.includes(n))});
  designApplyState.review=review;designApplyState.takeover=new Set(review.takeover||[]);
  designApplyRenderReview();designApplyShowStep('review');
 }catch(error){if($('design-apply-choose-error'))$('design-apply-choose-error').textContent=error.message;}
}
// The sole render point for the review step (a fresh review from designApplyRunReview's Back->Review,
// and a take-over re-review from designApplyToggleTakeover both land here): a new review result is
// content the student has not acknowledged yet, so the checkbox — the dialog's only other clearing
// point is designApplyOpen — is unticked again and the Apply button recomputed from that.
function designApplyRenderReview(){
 setMarkup($('design-apply-review-body'),designApplyReviewMarkup(designApplyState.review,designApplyState.takeover));
 if($('design-apply-ack'))$('design-apply-ack').checked=false;
 designApplyUpdateRunButton();
}
function designApplyUpdateRunButton(){
 const ack=!!($('design-apply-ack')&&$('design-apply-ack').checked);
 if($('design-apply-run'))$('design-apply-run').disabled=!designApplyCanSubmit(designApplyState.review,designApplyState.takeover,ack);
}
// A conflict's take-over checkbox: the token binds the take-over list, so the review must run again.
async function designApplyToggleTakeover(name,checked){
 if(checked)designApplyState.takeover.add(name);else designApplyState.takeover.delete(name);
 const targets=(designApplyState.review&&designApplyState.review.targets||[]).map(t=>t.name);
 try{
  const review=await json('/labs/'+encodeURIComponent(designApplyState.labId)+'/design/generations/'+encodeURIComponent(designApplyState.generationId)+'/review',
   'POST',{targets,takeover:[...designApplyState.takeover]});
  designApplyState.review=review;designApplyState.takeover=new Set(review.takeover||[]);
  designApplyRenderReview();
 }catch(error){if($('design-apply-review-error'))$('design-apply-review-error').textContent=error.message;}
}
async function designApplySubmit(){
 if($('design-apply-review-error'))$('design-apply-review-error').textContent='';
 const ack=!!($('design-apply-ack')&&$('design-apply-ack').checked);
 const minutes=$('design-apply-minutes')?$('design-apply-minutes').value:5;
 const body=designApplyBody({token:designApplyState.review&&designApplyState.review.token,requestId:designApplyState.requestId,
  confirmMinutes:minutes,takeover:designApplyState.takeover,acknowledged:ack});
 try{
  const job=await json('/labs/'+encodeURIComponent(designApplyState.labId)+'/design/apply','POST',body);
  designApplyState.job=job;designApplyState.jobId=job.id;
  designApplyRenderProgress();designApplyShowStep('progress');
  designApplyStartWatch(job.id);
  if(typeof refresh==='function')await refresh();
 }catch(error){if($('design-apply-review-error'))$('design-apply-review-error').textContent=error.message;}
}
function designApplyRenderProgress(){setMarkup($('design-apply-progress-body'),designApplyProgressMarkup(designApplyState.job));}
function designApplyStopWatch(){clearTimeout(designApplyWatchTimer);designApplyWatch=null;}
function designApplyStartWatch(jobId){
 if(designApplyWatch===jobId)return;designApplyStopWatch();designApplyWatch=jobId;
 const poll=async()=>{
  if(designApplyWatch!==jobId)return;
  try{
   const job=await(await api('/design/apply/jobs/'+encodeURIComponent(jobId))).json();
   if(designApplyWatch!==jobId)return;
   designApplyState.job=job;
   if(designApplyState.jobId===jobId&&designApplyState.step==='progress')designApplyRenderProgress();
   if(DESIGN_APPLY_JOB_BUSY.includes(job.status)){designApplyWatchTimer=setTimeout(poll,2000);}
   else{
    designApplyStopWatch();
    if(typeof refresh==='function')await refresh();
    designApplyRenderLast(job.lab_id);
    designApplyLoadOwnership();
   }
  }catch{designApplyStopWatch();}
 };
 designApplyWatchTimer=setTimeout(poll,2000);
}
// Reopens the dialog on a past (or still-running) job's progress step, from the plan card's "Show".
function designApplyShowJob(jobId){
 const lab=current();if(!lab||!$('design-apply-dialog'))return;
 const job=((typeof state!=='undefined'&&state.design_jobs)||[]).find(j=>j.id===jobId)||null;
 designApplyState.labId=lab.id;designApplyState.jobId=jobId;designApplyState.job=job;
 designApplyRenderProgress();designApplyShowStep('progress');
 $('design-apply-dialog').showModal();
 if(job&&DESIGN_APPLY_JOB_BUSY.includes(job.status))designApplyStartWatch(jobId);
}
function designApplyClose(){designApplyStopWatch();if($('design-apply-dialog')&&typeof $('design-apply-dialog').close==='function')$('design-apply-dialog').close();}
async function designApplyLoadOwnership(){
 const lab=current();if(!lab||!$('design-ownership'))return;
 try{
  const data=await(await api('/labs/'+encodeURIComponent(lab.id)+'/design/ownership')).json();
  if(current()&&current().id===lab.id)setMarkup($('design-ownership'),designApplyOwnershipMarkup(data));
 }catch{setMarkup($('design-ownership'),'<p class="caption">Could not load owned settings.</p>');}
}
function initDesignApply(){
 if($('design-apply'))$('design-apply').onclick=()=>designApplyOpen();
 if($('design-apply-review-run'))$('design-apply-review-run').onclick=()=>designApplyRunReview();
 if($('design-apply-back'))$('design-apply-back').onclick=()=>designApplyShowStep('choose');
 if($('design-apply-run'))$('design-apply-run').onclick=()=>designApplySubmit();
 if($('design-apply-ack'))$('design-apply-ack').addEventListener('change',designApplyUpdateRunButton);
 if($('design-apply-review-body'))$('design-apply-review-body').addEventListener('change',e=>{
  const cb=e.target&&e.target.closest&&e.target.closest('[data-design-apply-takeover]');
  if(cb)designApplyToggleTakeover(cb.dataset.designApplyTakeover,cb.checked);
 });
 if($('design-apply-last'))$('design-apply-last').addEventListener('click',e=>{
  const b=e.target&&e.target.closest&&e.target.closest('[data-design-apply-show]');
  if(b)designApplyShowJob(b.dataset.designApplyShow);
 });
 if($('design-apply-dialog'))for(const b of $('design-apply-dialog').querySelectorAll('[data-design-apply-close]'))b.onclick=()=>designApplyClose();
 if($('design-advanced-details'))$('design-advanced-details').addEventListener('toggle',()=>{if($('design-advanced-details').open)designApplyLoadOwnership();});
}

// --- Export plan to Git…: dialog state and DOM wiring. requestId is generated once per dialog open,
// same as designApplyState.requestId, so a retry after a network error resubmits the same request.
let designExportGitState={labId:'',generationId:'',requestId:''};
function designExportGitUpdateDestination(binding){
 if($('design-export-git-destination'))setMarkup($('design-export-git-destination'),designExportGitDestinationMarkup(binding,$('design-export-git-checkpoint')?$('design-export-git-checkpoint').value:''));
}
function designExportGitOpen(){
 const lab=current();if(!lab||!$('design-export-git-dialog'))return;
 const view=designActiveView(lab),newest=designNewestGeneration(view);
 if(designExportGitReason(lab,view)||!newest)return;
 designExportGitState={labId:lab.id,generationId:newest.id,requestId:designExportGitRequestId()};
 if($('design-export-git-checkpoint'))$('design-export-git-checkpoint').value=designExportGitDefaultCheckpoint(newest.id);
 if($('design-export-git-note'))$('design-export-git-note').value='';
 if($('design-export-git-error'))$('design-export-git-error').textContent='';
 designExportGitUpdateDestination(lab.git_binding);
 $('design-export-git-dialog').showModal();
}
function designExportGitClose(){if($('design-export-git-dialog')&&typeof $('design-export-git-dialog').close==='function')$('design-export-git-dialog').close();}
// On success this hands the job straight to git-progress.js's own quiet watch (gitStartWatch), the
// same path a plain Save progress takes: it polls the job and, once the export reaches review_pending,
// opens the mandatory review itself (gitReviewJob) — this file never opens the review or uploads
// directly, and never sends {push:true,reviewed:true}.
async function designExportGitSubmit(){
 if($('design-export-git-error'))$('design-export-git-error').textContent='';
 const checkpoint=String($('design-export-git-checkpoint')?$('design-export-git-checkpoint').value:'').trim();
 if(!designExportGitValidCheckpoint(checkpoint)){
  if($('design-export-git-error'))$('design-export-git-error').textContent='Use a checkpoint name containing letters, numbers, hyphens or underscores.';
  return;
 }
 const body=designExportGitBody({requestId:designExportGitState.requestId,checkpoint,note:$('design-export-git-note')?$('design-export-git-note').value:''});
 try{
  const job=await json('/labs/'+encodeURIComponent(designExportGitState.labId)+'/design/generations/'+encodeURIComponent(designExportGitState.generationId)+'/git','POST',body);
  designExportGitClose();
  if(typeof gitRememberJob==='function')gitRememberJob(job);
  if(typeof showTab==='function')showTab('progress');
  if(typeof gitStartWatch==='function')gitStartWatch(job,{quiet:true});
  if(typeof refresh==='function')await refresh();
 }catch(error){if($('design-export-git-error'))$('design-export-git-error').textContent=error.message;}
}
function initDesignExportGit(){
 if($('design-export-git'))$('design-export-git').onclick=()=>designExportGitOpen();
 if($('design-export-git-checkpoint'))$('design-export-git-checkpoint').addEventListener('input',()=>designExportGitUpdateDestination(current()&&current().git_binding));
 if($('design-export-git-confirm'))$('design-export-git-confirm').onclick=()=>designExportGitSubmit();
 if($('design-export-git-dialog'))for(const b of $('design-export-git-dialog').querySelectorAll('[data-design-export-git-close]'))b.onclick=()=>designExportGitClose();
}

// --- load-time wiring: only when the Design tab's static skeleton is on the page ----------------------
function initNetworkDesign(){
 const guidedIds=['design-ipv4','design-ipv6','design-pool-loopback-ipv4','design-pool-loopback-ipv6',
  'design-pool-p2p-ipv4','design-pool-p2p-ipv6','design-pool-p2p-prefix','design-pool-lan-ipv4','design-pool-lan-ipv6',
  'design-pool-lan-prefix','design-ospf-area','design-bgp-as','design-bgp-rr','design-isis-area','design-isis-type','design-gateway-protocol'];
 for(const id of guidedIds)if($(id))$(id).addEventListener('change',designOnGuidedChange);
 if($('design-modules'))$('design-modules').addEventListener('change',designOnGuidedChange);
 if($('design-devices'))$('design-devices').addEventListener('change',e=>{if(e.target&&e.target.dataset&&e.target.dataset.designRole!==undefined)designOnGuidedChange();});
 if($('design-vrfs')){
  $('design-vrfs').addEventListener('change',e=>{if(e.target&&e.target.dataset&&e.target.dataset.designVrfField!==undefined)designOnGuidedChange();});
  $('design-vrfs').addEventListener('click',e=>{const b=e.target&&e.target.closest&&e.target.closest('[data-design-vrf-remove]');if(b)designRemoveVrf(b.dataset.designVrfRemove);});
 }
 if($('design-vrf-add'))$('design-vrf-add').onclick=()=>designAddVrf();
 if($('design-vlans')){
  $('design-vlans').addEventListener('change',e=>{if(e.target&&e.target.dataset&&e.target.dataset.designVlanField!==undefined)designOnGuidedChange();});
  $('design-vlans').addEventListener('click',e=>{const b=e.target&&e.target.closest&&e.target.closest('[data-design-vlan-remove]');if(b)designRemoveVlan(b.dataset.designVlanRemove);});
 }
 if($('design-vlan-add'))$('design-vlan-add').onclick=()=>designAddVlan();
 if($('design-links'))$('design-links').addEventListener('change',e=>{if(e.target&&e.target.dataset&&e.target.dataset.designLinkField!==undefined)designOnGuidedChange();});
 if($('design-static')){
  $('design-static').addEventListener('change',e=>{if(e.target&&e.target.dataset&&e.target.dataset.designStaticField!==undefined)designOnGuidedChange();});
  $('design-static').addEventListener('click',e=>{const b=e.target&&e.target.closest&&e.target.closest('[data-design-static-remove]');if(b)designRemoveStatic(b.dataset.designStaticRemove);});
 }
 if($('design-static-add'))$('design-static-add').onclick=()=>designAddStaticRoute();
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
 initDesignApply();
 initDesignExportGit();
}
if(typeof document!=='undefined'&&document.getElementById&&$('design-view'))initNetworkDesign();
