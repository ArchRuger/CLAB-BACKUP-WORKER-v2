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
const DESIGN_POLL_RETRIES=5;
const DESIGN_LEVEL_WORDS={verified_on_image:'Verified on this image',generated_not_live_tested:'Generated, not yet tested live',
 unsupported:'Not supported',blocked_missing_prerequisite:'Needs a prerequisite module',retired:'No longer offered'};
const DESIGN_LEVEL_CLASS={verified_on_image:'ok',generated_not_live_tested:'neutral',unsupported:'danger',blocked_missing_prerequisite:'warn',retired:'warn'};
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
 // The watch gave up after its retries: the plan may still be generating, but nothing here knows, so the state says so
 // (no busy pill for something that is not being watched).
 if(generating&&view.pollGaveUp)return {key:'unknown',label:'Plan progress unknown',pill:'warn',detail:view.pollProblem||'Could not check the plan\'s progress. Reload the page, or open Advanced → Experimental → Network design again.'};
 if(generating)return {key:'generating',label:'Generating the plan…',pill:'busy',detail:view.pollProblem||(newest&&newest.message)||'Waiting to generate.'};
 // The Advanced editor holds text that is not JSON: nothing acts on it until it parses (the last good
 // intent is not silently used behind it), and the student is told so here, not only in the problems list.
 if(view.advancedInvalid)return {key:'invalid',label:'Advanced JSON is not valid',pill:'danger',detail:'Fix the JSON under Advanced (or Discard changes) before saving, checking or generating.'};
 if(view.draft&&view.draftUnsaved)return {key:'draft',label:'Unsaved changes',pill:'danger',detail:'Your changes could not be kept in this browser (its storage is unavailable). Save the design now, or they are lost when you leave this page.'};
 if(view.draft)return {key:'draft',label:'Unsaved changes',pill:'warn',detail:'Save the design to keep these changes, or Discard changes to go back to the saved design.'};
 const problems=view.problems||[];
 if(problems.length)return {key:'problems',label:'The design has problems',pill:'danger',detail:view.errorSummary?'The problems are listed in the summary below.':problems[0].message||'Fix the problems below, then save again.'};
 if(view.pollProblem)return {key:'unknown',label:'Plan progress unknown',pill:'warn',detail:view.pollProblem};
 // No saved design but earlier plans: they belong to a design that was removed, and must not read as current.
 if(!view.intent&&generations.length)return {key:'removed',label:'No design saved (earlier plans kept)',pill:'neutral',detail:'The design was removed. Its earlier plans stay under History for reference; save a new design to generate again.'};
 if(newest&&newest.status==='interrupted')
  return {key:'interrupted',label:'The last plan was interrupted',pill:'warn',detail:newest.message||'The manager restarted while this plan was being generated. Generate it again.'};
 if(newest&&newest.status==='failed')return {key:'failed',label:'The last plan failed',pill:'danger',detail:newest.message||'The last plan did not finish. See its errors below.'};
 if(newest&&newest.status==='succeeded'&&view.summary&&view.summary.stale)
  return {key:'stale',label:'Plan is older than the design',pill:'warn',detail:'The design changed since this plan was generated. Generate it again to see the current plan.'};
 if(newest&&newest.status==='succeeded')return {key:'ready',label:'Plan ready to review',pill:'ok',detail:newest.message||'Generated successfully.'};
 // A saved design with no plan yet is not "no design": the student's Save worked, and the next step is Generate plan.
 if(view.intent)return {key:'saved',label:'Design saved, no plan yet',pill:'neutral',detail:'The design is saved. Generate plan to calculate its addressing and routing.'};
 return {key:'none',label:'No design yet',pill:'neutral',detail:"Choose addressing, protocols and services below, save the design, then Generate plan."};
}

// --- guided form <-> intent (design_intent.py schema 1) ----------------------------------------------
// designIntentFromForm keeps every field the guided controls do not own (links, vlans, vrfs, interfaces,
// allocations, label, schema, revision, ...): it clones `base` and only touches the keys below.
function designIntentFromForm(values,base){
 values=values||{};
 const intent=JSON.parse(JSON.stringify(base&&typeof base==='object'?base:designEmptyIntent()));
 intent.schema=1;
 intent.families={ipv4:!!values.ipv4,ipv6:!!values.ipv6};
 // Pools are merged into what `base` has: the three guided pools keep every key the form has no control
 // for (start, allocation, prefix6, …) and any other pool the schema allows (vrf_loopback, router_id) is
 // left untouched. A blank or odd prefix stays what was typed, so the server names the problem instead of a
 // look-alike default appearing.
 const pools=values.pools||{};
 const addressing={...(intent.addressing&&typeof intent.addressing==='object'?intent.addressing:{})};
 const pool=(name,withPrefix)=>{
  const current=addressing[name]&&typeof addressing[name]==='object'?addressing[name]:{};
  const given=pools[name]||{};
  const next={...current,ipv4:given.ipv4||'',ipv6:given.ipv6||''};
  // A blank address for a family that is switched off is left out: the server's "remove the prefix or enable the
  // family" advice must be followable. A blank one for an enabled family is sent, so the server names it.
  for(const fam of ['ipv4','ipv6'])if(!intent.families[fam]&&!next[fam])delete next[fam];
  if(withPrefix){
   if(given.prefix===undefined)delete next.prefix;else next.prefix=designNumberOrRaw(given.prefix);
  }
  return next;
 };
 addressing.loopback=pool('loopback',false);addressing.p2p=pool('p2p',true);addressing.lan=pool('lan',true);
 intent.addressing=addressing;
 // A retired module the base intent already carries is kept (never silently dropped, like bgpRrKnown) unless
 // the student removed it (values.retiredRemoved); the form only controls the modules it offers.
 const retiredKnown=new Set(values.retiredKnown||[]),retiredGone=new Set(values.retiredRemoved||[]);
 const keptRetired=((base&&base.modules)||[]).filter(m=>retiredKnown.has(m)&&!retiredGone.has(m));
 const modules=[...new Set([...(values.modules||[]),...keptRetired])];
 intent.modules=modules;
 const has=id=>modules.includes(id);
 if(has('ospf'))intent.ospf={...(intent.ospf&&typeof intent.ospf==='object'?intent.ospf:{}),area:values.ospfArea||'0.0.0.0'};
 else delete intent.ospf;
 if(has('bgp')){
  const bgp={...(intent.bgp&&typeof intent.bgp==='object'?intent.bgp:{})};
  // The AS is what the student typed: an empty field leaves the AS out (the server asks for one), 0 or a
  // non-number is kept as typed and refused by name — never silently replaced by 65000.
  if(values.bgpAs===''||values.bgpAs===undefined||values.bgpAs===null)delete bgp.as;else bgp.as=designNumberOrRaw(values.bgpAs);
  intent.bgp=bgp;
 }
 else delete intent.bgp;
 if(has('isis'))intent.isis={...(intent.isis&&typeof intent.isis==='object'?intent.isis:{}),area:values.isisArea||'49.0001',type:values.isisType||'level-2'};
 else delete intent.isis;
 if(has('gateway'))intent.gateway={...(intent.gateway&&typeof intent.gateway==='object'?intent.gateway:{}),protocol:values.gatewayProtocol||'anycast'};
 else delete intent.gateway;
 const nodes={...(intent.nodes||{})};
 // Route reflectors: the guided control is a checklist (every router can be one), so its checked set is
 // the whole truth for the routers it shows (bgpRrKnown); a device it does not show keeps its own flag. An
 // older caller may still pass one name as a string.
 const rrs=new Set(Array.isArray(values.bgpRr)?values.bgpRr:values.bgpRr?[values.bgpRr]:[]);
 const rrKnown=Array.isArray(values.bgpRrKnown)?new Set(values.bgpRrKnown):null;
 for(const device of values.devices||[]){
  const name=device&&device.name;if(!name)continue;
  const node={...(nodes[name]&&typeof nodes[name]==='object'?nodes[name]:{})};
  if(device.role&&device.role!=='router')node.role=device.role;else delete node.role;
  if(has('bgp')){
   const bgp={...(node.bgp&&typeof node.bgp==='object'?node.bgp:{})};
   if(rrs.has(name))bgp.rr=true;else if(!rrKnown||rrKnown.has(name))delete bgp.rr;
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
// A form field's text as a number when it is one, else as typed (so validation can name it). '' stays ''.
function designNumberOrRaw(value){
 if(value===''||value===null||value===undefined)return value===undefined?undefined:'';
 if(typeof value==='number')return value;
 const text=String(value).trim();
 return /^-?\d+$/.test(text)?Number(text):text;
}
// The inverse of designIntentFromForm: what the guided controls should show for a stored (or draft) intent.
function designFormFromIntent(intent){
 intent=intent&&typeof intent==='object'?intent:{};
 const families=intent.families||{},addressing=intent.addressing||{};
 const loopback=addressing.loopback||{},p2p=addressing.p2p||{},lan=addressing.lan||{};
 const nodes=intent.nodes||{};
 const bgpRr=[];
 const devices=Object.keys(nodes).sort().map(name=>{
  const node=nodes[name]||{};
  if(node&&node.bgp&&node.bgp.rr)bgpRr.push(name);
  return {name,role:node.role||'router'};
 });
 // Numbers show as stored: an intent without a prefix shows the schema default, but a blank or odd value the
 // student typed shows as typed (the server has named the problem), never a look-alike default.
 const shown=(value,fallback)=>value===undefined||value===null?fallback:value;
 return {
  ipv4:families.ipv4!==false,ipv6:families.ipv6!==false,
  pools:{
   loopback:{ipv4:loopback.ipv4||'',ipv6:loopback.ipv6||''},
   p2p:{ipv4:p2p.ipv4||'',ipv6:p2p.ipv6||'',prefix:shown(p2p.prefix,31)},
   lan:{ipv4:lan.ipv4||'',ipv6:lan.ipv6||'',prefix:shown(lan.prefix,24)}
  },
  modules:[...(intent.modules||[])],
  ospfArea:(intent.ospf&&intent.ospf.area)||'0.0.0.0',
  bgpAs:intent.bgp&&intent.bgp.as!==undefined&&intent.bgp.as!==null?intent.bgp.as:'',
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
// --- error summary: what a failed Save design / Generate plan / Check / Import tells the student ---------
// A validation path maps to the control that owns it (the guided form), else to the Advanced JSON editor.
const DESIGN_POOL_LABELS={loopback:'Loopbacks',p2p:'Point-to-point links',lan:'Shared links'};
const DESIGN_ACTION_LABELS={save:'Save design',generate:'Generate plan',check:'Check',import:'Import design file',advanced:'Advanced JSON'};
const DESIGN_ADVANCED_FIELD={id:'design-advanced',label:'the Advanced JSON editor',advanced:true};
// -> [{id,label,advanced?}]: the first entry is the field the path names (it gets aria-invalid); a second one is another way to fix it.
function designFieldsFor(path,message){
 path=String(path||'');message=String(message||'');
 let m=/^addressing\.(loopback|p2p|lan)\.(ipv4|ipv6|prefix|prefix6)$/.exec(path);
 if(m){
  const family=m[2]==='ipv4'||m[2]==='ipv6'?m[2]:'',field=m[2]==='prefix6'?'prefix':m[2];
  if(field==='prefix'&&m[1]==='loopback')return [DESIGN_ADVANCED_FIELD];
  const pool={id:'design-pool-'+m[1]+'-'+field,label:DESIGN_POOL_LABELS[m[1]]+': '+(family?family.replace('ipv','IPv')+' pool':'allocation size')};
  if(family&&/switched off/i.test(message))return [pool,{id:'design-'+family,label:family.replace('ipv','IPv')+' checkbox'}];
  return [pool];
 }
 if(path==='bgp.as')return [{id:'design-bgp-as',label:'BGP AS number'}];
 if(path==='ospf.area')return [{id:'design-ospf-area',label:'OSPF area'}];
 if(path==='isis.area')return [{id:'design-isis-area',label:'IS-IS area'}];
 if(path==='isis.type')return [{id:'design-isis-type',label:'IS-IS level'}];
 if(path==='gateway.protocol')return [{id:'design-gateway-protocol',label:'First-hop gateway protocol'}];
 if(path==='modules')return [{id:'design-modules',label:'Protocols and services'}];
 if(path==='families'||/^families\./.test(path))return [{id:'design-ipv4',label:'IPv4 and IPv6 checkboxes'}];
 if(/^nodes\.[^.]+\.bgp(\.|$)/.test(path))return [{id:'design-bgp-rr',label:'Route reflectors'}];
 return [DESIGN_ADVANCED_FIELD];
}
// Splits what a failed call said into {kind,problems}: a structured list (error.problems, from detail
// {message,problems}) wins; else the "Fix the design first: path: msg; path: msg" sentence is parsed; anything else
// (a lost connection, a 500) is one item of kind "error".
function designProblemsFromError(error){
 const message=String(error&&error.message||'');
 const retired=Array.isArray(error&&error.retired)&&error.retired.length;
 // A retired-module refusal ({message,problems,retired}): the sentence leads, the problems are the items.
 if(retired&&!(Array.isArray(error.problems)&&error.problems.length))return {kind:'problems',problems:[{path:'',message}]};
 if(error&&Array.isArray(error.problems)&&error.problems.length){
  const parsed={kind:'problems',problems:error.problems.map(p=>({path:String(p&&p.path||''),message:String(p&&p.message||'')}))};
  if(retired&&message)parsed.lead=message;
  return parsed;
 }
 const m=/^Fix the design first:\s*([\s\S]+)$/.exec(message);
 if(m)return {kind:'problems',problems:m[1].split(/;\s+/).filter(Boolean).map(part=>{const i=part.indexOf(': ');return i>0?{path:part.slice(0,i),message:part.slice(i+2)}:{path:'',message:part};})};
 // fetch() rejects with a bare TypeError ("Failed to fetch", "NetworkError …", "Load failed") when the manager is unreachable.
 const network=(error&&error.name==='TypeError')||/^(Failed to fetch|NetworkError|Load failed)/.test(message);
 return {kind:'error',problems:[{path:'',message:network?'The manager could not be reached (network error). Nothing was saved or started.':message||'Something went wrong.'}]};
}
function designSummaryTitle(action,kind,count){
 const label=DESIGN_ACTION_LABELS[action]||DESIGN_ACTION_LABELS.save;
 if(kind!=='problems')return label+' failed';
 const words=count+' problem'+(count===1?'':'s')+' to fix';
 return action==='check'?'Check found '+words:action==='advanced'?'The Advanced JSON is not valid':label+' failed: '+words;
}
function designSummaryHint(kind,links){
 if(kind!=='problems')return 'Your entries are kept. Try again; if it keeps failing, reload the page.';
 return links?'Your entries are kept. Correct the fields named here, then try again.':'Your entries are kept. Fix the file you imported, then import it again.';
}
// summary: {action,kind,problems,links}. Items carry stable ids so the controls they name can point back with aria-describedby.
function designSummaryItems(summary){
 const links=summary.links!==false&&summary.kind==='problems';
 return summary.problems.map((p,i)=>({id:'design-error-item-'+i,path:p.path,message:p.message,fields:links?designFieldsFor(p.path,p.message):[]}));
}
// A failure that is not a validation problem (network, server) can be retried from the summary itself.
const DESIGN_RETRY_ACTIONS=['save','generate','check'];
function designSummaryMarkup(summary){
 const items=designSummaryItems(summary),title=designSummaryTitle(summary.action,summary.kind,items.length);
 const li=item=>{
  const name=item.fields.length&&!item.fields[0].advanced?item.fields[0].label:item.path;
  const head=name?`<strong>${esc(name)}</strong>: `:'';
  const go=item.fields.map((f,i)=>`<button type="button" class="text-button design-error-go" data-design-goto="${esc(f.id)}">${esc(i?'or go to the '+f.label:f.advanced?'Open '+f.label:'Go to the field')}</button>`).join(' ');
  return `<li id="${esc(item.id)}">${head}${esc(item.message)} ${go}</li>`;
 };
 return `<h3 id="design-error-title">${esc(title)}</h3>${summary.lead?`<p class="design-error-lead">${esc(summary.lead)}</p>`:''}<ul>${items.map(li).join('')}</ul><p class="form-help">${esc(designSummaryHint(summary.kind,summary.links!==false))}</p>${summary.kind!=='problems'&&DESIGN_RETRY_ACTIONS.includes(summary.action)?`<button type="button" class="button secondary" data-design-retry="${esc(summary.action)}">Try again</button>`:''}`;
}
// The modules a student may choose, then one read-only row per retired module the design still carries (ticked,
// disabled, the backend's reason, a Remove button). A retired module is never offered as a new choice.
function designModulesMarkup(modules,selected,info){
 const chosen=new Set(selected||[]),reasons=(info&&info.reasons)||{};
 const offered=(modules||[]).filter(id=>!Object.prototype.hasOwnProperty.call(reasons,id));
 const boxes=offered.map(id=>`<label class="checkbox-label"><input type="checkbox" name="design-module" value="${esc(id)}" ${chosen.has(id)?'checked':''}> ${esc(designModuleLabel(id))}</label>`).join('');
 const rows=[...chosen].filter(id=>Object.prototype.hasOwnProperty.call(reasons,id)).sort().map(id=>{
  const label=(info.labels&&info.labels[id])||designModuleLabel(id);
  return `<div class="design-retired-row"><label class="checkbox-label"><input type="checkbox" name="design-module-retired" value="${esc(id)}" checked disabled> <span>${esc(label)}</span> <span class="pill warn">${esc(designRetiredWord(id,info))}</span></label>`+
   `<p class="form-help">${esc(reasons[id])}</p><button type="button" class="button secondary small" data-design-retire-remove="${esc(id)}" aria-label="Remove ${esc(label)} from the design">Remove from design</button></div>`;
 }).join('');
 return boxes+rows;
}
// Where the saved design still uses a retired module (view.retired_in_design: [{path,module,message}]).
function designRetiredNoticeMarkup(view){
 const used=(view&&view.retired_in_design)||[];
 if(!used.length)return '';
 const info=designRetiredInfo(view);
 const ids=[...new Set(used.map(u=>u.module))];
 const names=ids.map(id=>(info.labels&&info.labels[id])||designModuleLabel(id));
 return `<p><strong>This design still uses ${esc(names.join(', '))}.</strong> It stays readable and downloadable, but no new plan can be generated from it until you remove ${ids.length===1?'it':'them'}. Earlier plans are kept.</p>`+
  `<details><summary>Where it is used (${used.length})</summary><ul>${used.map(u=>`<li><code>${esc(u.path||'')}</code>: ${esc(u.message||'')}</li>`).join('')}</ul></details>`;
}
function designRoleOptions(current){
 return ['router','host','exclude'].map(r=>`<option value="${r}" ${r===(current||'router')?'selected':''}>${r==='router'?'Router':r==='host'?'Host':'Exclude'}</option>`).join('');
}
function designDeviceRow(name,row,role){
 row=row||{};
 const reason=row.profile?'':(row.reason||'No design profile is mapped to this kind of device');
 const profileCell=row.profile?esc(row.profile):`<span class="status-neutral">${esc(reason)}</span>`;
 return `<tr><td>${esc(name)}</td><td>${esc(row.kind||'')}</td><td>${profileCell}</td>`+
  `<td><select data-design-role="${esc(name)}" aria-label="Role of ${esc(name)}" ${row.profile?'':'disabled'} ${reason?`title="${esc(reason)}"`:''}>${designRoleOptions(role)}</select></td>`+
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
 return `<tr data-design-vrf-key="${esc(name)}"><td><input type="text" class="mono" data-design-vrf-field="name" aria-label="VRF name" value="${esc(name)}" maxlength="16" pattern="^[A-Za-z_][A-Za-z0-9_]{0,15}$" title="Up to 16 characters: letters, digits and underscores, starting with a letter or an underscore" placeholder="red"></td>`+
  `<td><label class="checkbox-label"><input type="checkbox" data-design-vrf-field="loopback" ${vrf.loopback?'checked':''}> Loopback</label></td>`+
  `<td><button type="button" class="button secondary small" data-design-vrf-remove="${esc(name)}" aria-label="Remove VRF ${esc(name)}">Remove</button></td></tr>`;
}
function designVrfsMarkup(vrfs){
 vrfs=vrfs&&typeof vrfs==='object'?vrfs:{};
 const names=Object.keys(vrfs).sort();
 if(!names.length)return '<tr><td colspan="3" class="table-empty">No VRFs yet.</td></tr>';
 return names.map(name=>designVrfRow(name,vrfs[name])).join('');
}
function designVlanRow(name,vlan){
 vlan=vlan||{};
 return `<tr data-design-vlan-key="${esc(name)}"><td><input type="text" class="mono" data-design-vlan-field="name" aria-label="VLAN name" value="${esc(name)}" maxlength="16" pattern="^[A-Za-z_][A-Za-z0-9_]{0,15}$" title="Up to 16 characters: letters, digits and underscores, starting with a letter or an underscore" placeholder="red"></td>`+
  `<td><input type="number" min="1" max="4094" data-design-vlan-field="id" aria-label="VLAN id of ${esc(name)}" value="${vlan.id!=null?esc(vlan.id):''}"></td>`+
  `<td><button type="button" class="button secondary small" data-design-vlan-remove="${esc(name)}" aria-label="Remove VLAN ${esc(name)}">Remove</button></td></tr>`;
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
  `<td><select data-design-link-field="vrf" aria-label="VRF of link ${esc(designLinkEnds(link))}">${vrfOptions}</select></td>`+
  `<td><select data-design-link-field="vlan-access" aria-label="Access VLAN of link ${esc(designLinkEnds(link))}">${accessOptions}</select></td>`+
  `<td><input type="text" class="mono" data-design-link-field="vlan-trunk" aria-label="Trunk VLANs of link ${esc(designLinkEnds(link))}, comma-separated" value="${esc(trunk.join(','))}" placeholder="names, comma-separated"></td>`+
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
 return `<tr data-design-static-key="${esc(device+':'+index)}"><td><select data-design-static-field="device" aria-label="Device of static route ${index+1}">${designStaticDeviceOptions(device,deviceNames)}</select></td>`+
  `<td><input type="text" class="mono" data-design-static-field="prefix" aria-label="Prefix of static route ${index+1}" value="${esc(prefix)}" placeholder="192.0.2.0/24"></td>`+
  `<td><select data-design-static-field="nexthop-type" aria-label="Next hop type of static route ${index+1}"><option value="discard" ${discard?'selected':''}>Discard</option><option value="address" ${discard?'':'selected'}>Address</option></select></td>`+
  `<td><input type="text" class="mono" data-design-static-field="nexthop-address" aria-label="Next hop address of static route ${index+1}" value="${esc(address)}" ${discard?'disabled':''} placeholder="192.0.2.1"></td>`+
  `<td><button type="button" class="button secondary small" data-design-static-remove="${esc(device+':'+index)}" aria-label="Remove static route ${index+1}">Remove</button></td></tr>`;
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
// One row per generation, newest first; every row can be opened (View) so an earlier plan, its files and its
// errors stay reachable after a newer one exists. `shownId` marks the one the plan card shows right now.
function designHistoryMarkup(generations,now,shownId){
 const list=[...(generations||[])].reverse();
 if(!list.length)return '<p class="caption">No plans generated yet.</p>';
 return '<ul class="design-history-list">'+list.map(g=>`<li><span class="pill ${designHistoryPill(g.status)}">${esc(designHistoryWord(g.status))}</span> `+
  `<span>${esc(typeof relativeTime==='function'?relativeTime(g.finished||g.created,now):'')}</span> <span>${esc(g.message||'')}</span> `+
  (g.id===shownId?'<span class="caption">Shown above</span>':`<button type="button" class="button secondary small" data-design-view-generation="${esc(g.id)}">View</button>`)+'</li>').join('')+'</ul>';
}
function designFileSize(bytes){bytes=Number(bytes)||0;return bytes<1024?bytes+' B':Math.round(bytes/1024)+' KiB';}
function designFilesMarkup(generation){
 if(!generation||generation.status!=='succeeded')return '<p class="caption">Generate a plan to see its files here.</p>';
 const artifacts=generation.artifacts||{};
 const names=Object.keys(artifacts).sort();
 if(!names.length)return '<p class="caption">This plan has no generated files.</p>';
 return names.map(name=>`<div class="design-file-group"><strong>${esc(name)}</strong><ul class="design-file-list">`+
  (artifacts[name]||[]).map((a,index)=>`<li><span>${esc(a.module||'')}</span> <span class="caption">${esc(designFileSize(a.size))}</span> `+
   `<button type="button" class="button secondary small" data-design-view-file="${esc(name)}" data-design-view-index="${index}" aria-label="View ${esc(name)} ${esc(a.module||'')}">View</button></li>`).join('')+
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
// The retired authoring modules (design_intent.RETIRED): the view carries {retired:{id:reason}, retired_status:{id:'retired'|'under_review'},
// retired_labels}. EVPN is "under review", never "retired".
const DESIGN_RETIRED_FEATURE={ripng:'ripv2'};
function designRetiredInfo(view){
 view=view||{};
 return {reasons:view.retired&&typeof view.retired==='object'?view.retired:{},status:view.retired_status||{},labels:view.retired_labels||{}};
}
function designRetiredWord(id,info){return info&&info.status&&info.status[id]==='under_review'?'Unavailable — under review':'No longer offered';}
// A compatibility row's level and policy; a row of an old plan whose feature is retired reads as retired too.
function designRowLevel(row,info){
 row=row||{};
 if(row.level==='retired')return {level:'retired',policy:row.policy||''};
 const id=DESIGN_RETIRED_FEATURE[row.feature]||row.feature;
 if(info&&info.reasons&&Object.prototype.hasOwnProperty.call(info.reasons,id))return {level:'retired',policy:(info.status&&info.status[id])||'retired'};
 return {level:row.level,policy:row.policy||''};
}
// The retired module ids a plan still carries (generation.modules plus the features of its compatibility rows).
function designPlanRetired(generation,info){
 const reasons=(info&&info.reasons)||{},found=new Set();
 for(const m of (generation&&generation.modules)||[])if(Object.prototype.hasOwnProperty.call(reasons,m))found.add(m);
 for(const rows of Object.values((generation&&generation.compatibility)||{}))for(const r of rows||[]){const id=DESIGN_RETIRED_FEATURE[r&&r.feature]||(r&&r.feature);if(Object.prototype.hasOwnProperty.call(reasons,id))found.add(id);}
 return [...found].sort();
}
function designLevelWord(level,reason,policy){
 if(level==='retired')return policy==='under_review'?'Under review':'No longer offered';
 if(level==='blocked_missing_prerequisite')return reason?'Needs '+reason.replace(/^'[^']*' requires /,''):'Needs a prerequisite module';
 return DESIGN_LEVEL_WORDS[level]||String(level||'');
}
// One row per device, one column per requested feature across every device, from generation.compatibility
// (design_capabilities.resolve() output): {feature,level,reason,evidence,profile}.
function designCompatibilityMarkup(generation,info){
 const compat=(generation&&generation.compatibility)||{};
 const names=Object.keys(compat);
 if(!names.length)return '<p class="caption">No compatibility information yet.</p>';
 const features=[...new Set(names.flatMap(n=>(compat[n]||[]).map(r=>r.feature)))].sort();
 const header=features.map(f=>`<th>${esc(f)}</th>`).join('');
 const rows=names.sort().map(name=>{
  const byFeature={};for(const r of compat[name]||[])byFeature[r.feature]=r;
  const cells=features.map(f=>{
   const r=byFeature[f];if(!r)return '<td>—</td>';
   const row=designRowLevel(r,info),cls=DESIGN_LEVEL_CLASS[row.level]||'neutral';
   return `<td><span class="pill ${esc(cls)}" title="${esc(row.level==='retired'&&info&&info.reasons&&info.reasons[DESIGN_RETIRED_FEATURE[r.feature]||r.feature]||r.reason||'')}">${esc(designLevelWord(row.level,r.reason,row.policy))}</span></td>`;
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
function designApplyCompatMarkup(compatibility,info){
 const rows=compatibility||[];
 if(!rows.length)return '';
 return '<ul class="design-apply-compat">'+rows.map(r=>{const row=designRowLevel(r,info);return `<li><span class="pill ${esc(DESIGN_LEVEL_CLASS[row.level]||'neutral')}" title="${esc(r.reason||'')}">${esc(r.feature||'')}: ${esc(designLevelWord(row.level,r.reason,row.policy))}</span></li>`;}).join('')+'</ul>';
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
function designApplyDeviceMarkup(target,takeover,info){
 target=target||{};takeover=takeover||new Set();
 const heading=`<h4>${esc(target.name||'')} <span class="caption">${esc(target.kind||'')}</span></h4>`;
 const compat=designApplyCompatMarkup(target.compatibility,info);
 if(!target.eligible)return `<article class="design-apply-device">${heading}<p class="form-help">${esc(target.reason||'This device is not part of the plan.')}</p>${compat}</article>`;
 if(!target.reachable||!target.ready)return `<article class="design-apply-device">${heading}<p class="form-help">${esc(designApplyReasonText(target.reason||'This device could not be reviewed.'))}</p>${compat}</article>`;
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
function designApplyReviewMarkup(review,takeover,info){
 if(!review||!review.targets||!review.targets.length)return '<p class="caption">Choose at least one device to review.</p>';
 return `<h3 id="design-apply-review-title" tabindex="-1">Review of ${review.targets.length===1?'one device':review.targets.length+' devices'}</h3>`+designApplyReviewSummary(review)+review.targets.map(t=>designApplyDeviceMarkup(t,takeover,info)).join('');
}
// Why Apply is off right now, under the button (never a silent disabled button).
function designApplyRunReason(review,takeover,acknowledged){
 if(!review)return '';
 if(!(review.applicable||[]).length)return 'Nothing can be applied: no chosen device is ready for this plan.';
 takeover=takeover||new Set();
 if((review.targets||[]).some(t=>t.ready&&(t.counts&&t.counts.conflicts)&&!takeover.has(t.name)))return 'A device has conflicts with manual configuration: tick "Take over these settings" on it, or choose other devices.';
 if(!acknowledged)return 'Tick the acknowledgement above to enable Apply.';
 return '';
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
// --- the device review as a job (design_apply.py review jobs): stages in student wording, elapsed times, one line per device ---
const DESIGN_REVIEW_STAGE_WORDS={queued:'Waiting',connecting:'Connecting…',checking_pending:'Checking for unconfirmed changes…',rendering:'Preparing the configuration…',
 reading_config:'Reading the current configuration…',staging:'Trying the change (nothing is committed)…',restaging:'Trying again with the take-over…',
 done:'Reviewed',failed:'Not reviewed',unreachable:'Could not be reached',not_eligible:'Not part of the review'};
const DESIGN_REVIEW_FINAL=['done','failed','unreachable','not_eligible'];
const DESIGN_REVIEW_UNAVAILABLE='The review is no longer available; review again.';
function designReviewStageWord(stage){return DESIGN_REVIEW_STAGE_WORDS[stage]||String(stage||'');}
function designReviewClock(seconds){seconds=Math.max(0,Math.floor(Number(seconds)||0));return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');}
// Seconds since the job started (to its end when finished), from the server's own clock so a skewed browser clock cannot lie.
function designReviewElapsed(job){
 job=job||{};
 const start=Date.parse(job.started||'')/1000;if(!Number.isFinite(start))return 0;
 const end=job.finished?Date.parse(job.finished)/1000:Number(job.server_time);
 return Number.isFinite(end)?Math.max(0,end-start):0;
}
// A device's own time: from queued to settled when it is final, else since its current stage began.
function designReviewTargetElapsed(target,job){
 const t=(target&&target.timeline)||{},now=Number(job&&job.server_time);
 if(DESIGN_REVIEW_FINAL.includes(target&&target.stage)){
  if(Number.isFinite(t.settled)&&Number.isFinite(t.queued))return Math.max(0,t.settled-t.queued);
  return null;
 }
 const since=t[target&&target.stage];
 return Number.isFinite(since)&&Number.isFinite(now)?Math.max(0,now-since):null;
}
function designReviewOverall(job){
 job=job||{};
 const total=(job.progress&&job.progress.total)||(job.targets||[]).length,settled=(job.progress&&job.progress.settled)||0;
 const clock=designReviewClock(designReviewElapsed(job));
 if(job.status==='running')return 'Reviewing '+total+(total===1?' device':' devices')+' · '+clock+(settled?' · '+settled+' of '+total+' finished':'');
 if(job.status==='done')return 'Review finished · '+clock;
 if(job.status==='interrupted')return 'The review was interrupted. Review again.';
 const why=job.message?String(job.message).trim():'';
 return 'The review could not finish'+(why?': '+why:'.')+(/review again/i.test(why)?'':' Review again.');
}
function designReviewRowMarkup(target,job){
 target=target||{};
 const elapsed=designReviewTargetElapsed(target,job);
 const cls=target.stage==='done'?'ok':target.stage==='failed'||target.stage==='unreachable'?'danger':target.stage==='not_eligible'?'neutral':'busy';
 const reason=(target.stage==='failed'||target.stage==='unreachable'||target.stage==='not_eligible')&&target.message?`<small class="design-review-reason">${esc(target.message)}</small>`:'';
 return `<tr data-design-review-device="${esc(target.name||'')}"><td><strong>${esc(target.name||'')}</strong> <span class="caption">${esc(target.kind||'')}</span></td>`+
  `<td><span class="pill ${cls}">${esc(designReviewStageWord(target.stage))}</span>${reason}</td><td>${elapsed===null?'':esc(designReviewClock(elapsed))}</td></tr>`;
}
function designReviewMarkup(job){
 const rows=((job&&job.targets)||[]).map(t=>designReviewRowMarkup(t,job)).join('')||'<tr><td colspan="3" class="table-empty">No devices.</td></tr>';
 return `<div class="table-wrap"><table class="design-review-log"><thead><tr><th>Device</th><th>Step</th><th>Time</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
// What the polite live region says after a poll: only devices whose stage changed since the last poll, or the final result.
function designReviewAnnouncement(job,previous){
 job=job||{};previous=previous||{};
 if(job.status&&job.status!=='running')return designReviewOverall(job);
 const changed=(job.targets||[]).filter(t=>previous[t.name]!==undefined&&previous[t.name]!==t.stage).map(t=>t.name+': '+designReviewStageWord(t.stage));
 return changed.join('; ');
}
function designReviewStages(job){const map={};for(const t of (job&&job.targets)||[])map[t.name]=t.stage;return map;}
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
 const info=designRetiredInfo(view),gone=designPlanRetired(newest,info);
 if(gone.length)return 'This plan uses '+gone.map(id=>(info.labels&&info.labels[id])||designModuleLabel(id)).join(', ')+', which '+(gone.every(id=>info.status[id]==='under_review')?'is not available':'is no longer offered')+', so it cannot be applied to devices. The plan stays viewable and downloadable; remove it from the design and generate a new plan to apply.';
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
let designState={labId:'',view:null,plan:null,draft:null,draftDiscarded:false,loading:false,error:'',viewing:null,advancedInvalid:false,pollProblem:'',draftUnsaved:false,pollGaveUp:false,formLab:'',summary:null,invalid:[]};
// Answers land in request order only by luck: every read of the design takes a sequence number when it is sent,
// and an answer is shown only if nothing newer has been shown since (an older answer that arrives late is
// dropped, never painted over a newer generation). A write (save, import, renumber, clear) is the newest truth
// by construction and marks everything sent before it stale.
let designViewSeq=0,designViewApplied=0;
function designViewRequest(){return ++designViewSeq;}
function designViewFresh(labId,seq){if(designState.labId!==labId||seq<=designViewApplied)return false;designViewApplied=seq;return true;}
function designViewWritten(labId){return designViewFresh(labId,designViewRequest());}
// The generation the plan card, files and download show: the one the student chose under History, else the newest.
function designViewedGeneration(view){
 const generations=(view&&view.generations)||[];
 if(designState.viewing){const found=generations.find(g=>g.id===designState.viewing);if(found)return found;}
 return generations.length?generations[generations.length-1]:null;
}
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
// The plan for one generation is fetched separately; the answer counts only if that generation is still the one
// shown (the lab and the generation may both have moved on while it was in flight).
function designPlanWanted(labId,generationId){
 if(designState.labId!==labId)return false;
 const shown=designViewedGeneration(designState.view);
 return !!shown&&shown.id===generationId;
}
async function designLoadPlan(labId,generationId){
 try{
  const data=await(await api('/labs/'+encodeURIComponent(labId)+'/design/generations/'+encodeURIComponent(generationId))).json();
  if(designPlanWanted(labId,generationId))designState.plan=data.plan||null;
 }catch{if(designPlanWanted(labId,generationId))designState.plan=null;}
}
async function designLoad(labId){
 designClearSummary();
 designState={labId,view:null,plan:null,draft:null,draftDiscarded:false,loading:true,error:'',viewing:null,advancedInvalid:false,pollProblem:'',draftUnsaved:false,pollGaveUp:false,formLab:designState.formLab||'',summary:null,invalid:[]};
 designRenderAll();
 const seq=designViewRequest();
 try{
  const view=await(await api('/labs/'+encodeURIComponent(labId)+'/design')).json();
  if(!designViewFresh(labId,seq))return;
  designState.view=view;designState.loading=false;
  designApplyDraft(labId,view);
  const newest=designNewestGeneration(view);
  if(newest&&newest.status==='succeeded')await designLoadPlan(labId,newest.id);
  if(designState.labId!==labId)return;
  designRenderAll();designMaybeStartWatch();
  designReviewDiscover(labId);
 }catch(error){
  if(designState.labId!==labId)return;
  designState.loading=false;designState.error=error.message;designRenderAll();
 }
}
function designMaybeStartWatch(){
 const newest=designNewestGeneration(designState.view);
 if(!newest||!DESIGN_BUSY_GENERATION.includes(newest.status)){designStopWatch();return;}
 // After the bounded retries the watch stays stopped (no endless polling behind the student's back) until a
 // deliberate step: Generate plan again, or opening the tab again, both of which load the design afresh.
 if(designState.pollGaveUp){designStopWatch();return;}
 if(designWatch===designState.labId)return;
 designStopWatch();designWatch=designState.labId;
 const labId=designState.labId;let failures=0;
 const poll=async()=>{
  if(designWatch!==labId)return;
  const seq=designViewRequest();
  try{
   const view=await(await api('/labs/'+encodeURIComponent(labId)+'/design')).json();
   if(designWatch!==labId||designState.labId!==labId)return;
   if(!view||typeof view!=='object'||!Array.isArray(view.generations))throw new Error('The manager answered with something that is not a design.');
   if(!designViewFresh(labId,seq)){designWatchTimer=setTimeout(poll,2000);return;}
   designState.view=view;failures=0;designState.pollProblem='';
   const next=designNewestGeneration(view);
   if(next&&DESIGN_BUSY_GENERATION.includes(next.status)){designRenderAll();designWatchTimer=setTimeout(poll,2000);}
   else{
    designStopWatch();
    if(next&&next.status==='succeeded')await designLoadPlan(labId,next.id);
    designRenderAll();
    if(typeof refresh==='function')await refresh();
   }
  }catch(error){
   // A failed poll (a lost connection, a 500, a bad answer) is retried a bounded number of times with the
   // student told so; after that the watch stops and the state says the progress is unknown, with a way out.
   if(designWatch!==labId||designState.labId!==labId)return;
   failures++;
   if(failures<=DESIGN_POLL_RETRIES){
    designState.pollProblem='Could not check the plan\'s progress (attempt '+failures+' of '+DESIGN_POLL_RETRIES+'): '+(error&&error.message||'no answer')+'. Trying again…';
    designRenderAll();designWatchTimer=setTimeout(poll,2000*failures);
   }else{
    designStopWatch();designState.pollGaveUp=true;
    designState.pollProblem='Could not check the plan\'s progress after '+DESIGN_POLL_RETRIES+' retries. Reload the page, or open Advanced → Experimental → Network design again, to see where it stands.';
    designRenderAll();
   }
  }
 };
 designWatchTimer=setTimeout(poll,2000);
}
// --- form focus guard: never rewrite a guided control while the student is using it -------------------
function designFormFocused(){
 // Only a field being typed in blocks a re-render: a focused button (Add VRF, remove) or a focused checkbox or
 // radio (a module ticked by hand keeps focus; the form must still redraw what that tick meant) must not keep
 // its own change from showing.
 const form=$('design-form');const active=document.activeElement;
 if(!form||!active||typeof form.contains!=='function'||!form.contains(active))return false;
 const type=String(active.type||'').toLowerCase();
 return ['INPUT','TEXTAREA','SELECT'].includes(String(active.tagName||'').toUpperCase())&&!['button','checkbox','radio'].includes(type);
}
// shell.js asks before the page is left: true while an unsaved draft exists that the browser could not store
// (the only copy of the student's edit is in this page).
function designLeaveGuard(){return !!(designState.draft&&designState.draftUnsaved);}
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
  const chosen=new Set(Array.isArray(values.bgpRr)?values.bgpRr:values.bgpRr?[values.bgpRr]:[]);
  // Re-rendering the grid must not drop a keyboard user's place: refocus the checkbox they were on.
  const focused=typeof document!=='undefined'&&document.activeElement&&document.activeElement.name==='design-bgp-rr'?document.activeElement.value:null;
  if(setMarkup($('design-bgp-rr'),designReflectorMarkup(names,chosen))&&focused!==null){const again=[...$('design-bgp-rr').querySelectorAll('input[name="design-bgp-rr"]')].find(i=>i.value===focused);if(again&&typeof again.focus==='function')again.focus();}
  designSyncChecked($('design-bgp-rr'),'input[name="design-bgp-rr"]',chosen);
 }
}
function designSetControlValue(id,value){if($(id))$(id).value=value;}
// One checkbox per router; several reflectors are as normal as one (the form never collapses them).
function designReflectorMarkup(names,chosen){
 chosen=chosen||new Set();
 if(!(names||[]).length)return '<p class="caption">No router to choose from yet.</p>';
 return names.map(n=>`<label class="checkbox-label"><input type="checkbox" name="design-bgp-rr" value="${esc(n)}" ${chosen.has(n)?'checked':''}><span>${esc(n)}</span></label>`).join('');
}
// setMarkup() skips an unchanged string, so a checkbox the student toggled by hand and the form then put
// back would keep its stale look: the live `checked` property is set from the values every render.
function designSyncChecked(container,selector,chosen){
 if(!container||typeof container.querySelectorAll!=='function')return;
 for(const box of container.querySelectorAll(selector))box.checked=chosen.has(box.value);
}
function designRenderForm(view){
 const intent=designCurrentIntent(view);
 const values=designFormFromIntent(intent);
 // The focus guard protects a field the student is typing in — for the lab the form already shows. When the
 // design of another lab arrives (a lab switch, browser Back with a field still focused), the form is redrawn
 // whatever has focus, so the controls can never show one lab's settings under another lab's name.
 const switched=designState.formLab!==designState.labId;
 if(switched){designState.formLab=designState.labId;const active=typeof document!=='undefined'?document.activeElement:null;if(active&&typeof active.blur==='function'&&$('design-form')&&typeof $('design-form').contains==='function'&&$('design-form').contains(active))active.blur();}
 if(switched||!designFormFocused()){
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
  setMarkup($('design-modules'),designModulesMarkup((view&&view.modules)||[],values.modules,designRetiredInfo(view)));
  if($('design-retired-notice')){const note=designRetiredNoticeMarkup(view);setMarkup($('design-retired-notice'),note);$('design-retired-notice').hidden=!note;}
  designSyncChecked($('design-modules'),'input[name="design-module"]',new Set(values.modules));
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
  // Text that does not parse stays on screen for the student to fix; it is never overwritten by the last good intent.
  if($('design-advanced')&&!designState.advancedInvalid)$('design-advanced').value=JSON.stringify(intent,null,2);
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
  const busy=st.key==='generating',noTopology=view&&view.has_topology===false,nothing=!(view&&view.intent)&&!(view&&view.draft);
  const usedRetired=((view&&view.retired_in_design)||[]).length>0&&!(view&&view.draft);
  $('design-generate').disabled=busy||!engineOk||noTopology||nothing||usedRetired;
  $('design-generate').title=!engineOk?((engine&&engine.diagnostic)||'The design engine is not available.')
   :busy?'A plan is already being generated for this lab.'
   :noTopology?'This lab has no topology file yet.'
   :nothing?'Choose settings below and save the design first.'
   :usedRetired?'This design still uses a module that is no longer offered. Remove it under Design settings, save, then generate.':'';
  menuReasonSafe($('design-generate'),$('design-generate').disabled?$('design-generate').title:'');
 }
 // The More menu explains itself like Generate plan, Apply to devices… and Export plan to Git… do: the
 // reasons mirror what the routes refuse (no design → 404 on export, renumber and remove; a plan being
 // generated → 409 on import, renumber and remove), so a click never ends in an unexplained error tab.
 for(const [id,reason] of designMoreMenuReasons(view,st)){const el=$(id);if(!el)continue;el.disabled=!!reason;el.title=reason;menuReasonSafe(el,reason);}
 if($('design-discard'))$('design-discard').hidden=!(view&&(view.draft||view.advancedInvalid));
}
// [id, reason] for the More menu's four items; '' enables the item. Pure, so the tests can pin it.
function designMoreMenuReasons(view,st){
 const saved=!!(view&&view.intent),generating=!!(st&&st.key==='generating'),wait='Wait for the plan being generated to finish.';
 const draft=!!(view&&(view.draft||view.advancedInvalid)),unsaved='Save or discard your unsaved changes first.';
 return [['design-export',!saved?'Save a design first.':draft?'Save the design first: the download is the saved design, not your unsaved changes.':''],
  ['design-import',generating?wait:draft?unsaved:''],['design-renumber',!saved?'Save a design first.':generating?wait:''],['design-clear',!saved?'There is no design to remove.':generating?wait:'']];
}
function menuReasonSafe(el,text){if(typeof menuReason==='function')menuReason(el,text);}
function designRenderPlanCard(view){
 const newest=designViewedGeneration(view),latest=designNewestGeneration(view);
 if($('design-plan-status')){
  let line=designGenerationLine(newest,Date.now());
  if(newest&&latest&&newest.id!==latest.id)line='Showing an earlier plan ('+(designSafeRelative(newest.finished||newest.created,Date.now())||'')+'), not the newest. '+line;
  if(newest&&!(view&&view.intent))line+=' This plan belongs to a design that was removed; it is kept for reference only.';
  $('design-plan-status').textContent=line;
 }
 if($('design-plan-newest'))$('design-plan-newest').hidden=!(newest&&latest&&newest.id!==latest.id);
 setMarkup($('design-plan-errors'),((newest&&newest.errors)||[]).map(e=>`<li>${esc(e)}</li>`).join(''));
 if($('design-plan-errors-wrap'))$('design-plan-errors-wrap').hidden=!((newest&&newest.errors)||[]).length;
 setMarkup($('design-plan-warnings'),((newest&&newest.warnings)||[]).map(w=>`<li>${esc(w)}</li>`).join(''));
 if($('design-plan-warnings-wrap'))$('design-plan-warnings-wrap').hidden=!((newest&&newest.warnings)||[]).length;
 if($('design-plan-warnings-summary'))$('design-plan-warnings-summary').textContent='Warnings ('+((newest&&newest.warnings)||[]).length+')';
 setMarkup($('design-plan-renumbering'),designRenumberingMarkup(newest&&newest.renumbering));
 if($('design-plan-renumbering-wrap'))$('design-plan-renumbering-wrap').hidden=!((newest&&newest.renumbering)||[]).length;
 if($('design-plan-collisions')){
  const fixes=newest&&newest.collision_fixes,count=fixes?Object.keys(fixes).length:0;
  $('design-plan-collisions').hidden=!count;
  $('design-plan-collisions').textContent=count?'Some link prefixes collided with pinned addresses and were reassigned automatically ('+count+(count===1?' link':' links')+').':'';
 }
 setMarkup($('design-compatibility'),designCompatibilityMarkup(newest,designRetiredInfo(view)));
 setMarkup($('design-plan-body'),newest&&newest.status==='succeeded'?designPlanMarkup(designState.plan):'<p class="caption">Generate a plan to see it here.</p>');
 if($('design-cancel'))$('design-cancel').hidden=!(newest&&DESIGN_BUSY_GENERATION.includes(newest.status));
}
function designUpdateDownloadLink(lab,view){
 if(!$('design-download'))return;
 const newest=designViewedGeneration(view),ok=!!lab&&!!newest&&newest.status==='succeeded';
 $('design-download').hidden=!ok;
 if(ok)$('design-download').href='/api/labs/'+encodeURIComponent(lab.id)+'/design/generations/'+encodeURIComponent(newest.id)+'/download';
}
function designRenderFiles(view){setMarkup($('design-files-body'),designFilesMarkup(designViewedGeneration(view)));}
function designRenderHistory(view){const shown=designViewedGeneration(view);setMarkup($('design-history-body'),designHistoryMarkup(view&&view.generations,Date.now(),shown&&shown.id));}
// History › View: the plan card, files and download switch to that generation until Back to newest (or a new plan).
async function designViewGeneration(generationId){
 const lab=current();if(!lab)return;
 const labId=lab.id,generations=(designState.view&&designState.view.generations)||[];
 const found=generations.find(g=>g.id===generationId);if(!found)return;
 const latest=designNewestGeneration(designState.view);
 designState.viewing=latest&&latest.id===generationId?null:generationId;
 designState.plan=null;
 if(found.status==='succeeded')await designLoadPlan(labId,generationId);
 if(designState.labId!==labId)return;
 designRenderAll();
}
function designActiveView(lab){
 if(designState.labId===lab.id&&designState.view)return {...designState.view,draft:!!designState.draft,draftUnsaved:!!designState.draftUnsaved,advancedInvalid:!!designState.advancedInvalid,pollProblem:designState.pollProblem||'',pollGaveUp:!!designState.pollGaveUp,errorSummary:!!designState.summary};
 const design=lab&&lab.design;
 if(!design)return {generations:[],problems:[],summary:{present:false}};
 return {generations:design.generation?[design.generation]:[],problems:[],summary:design};
}
// The single entry point, called from app.js's render() behind a typeof guard. Fetches the design once
// per lab while Advanced → Experimental → Network design is open; otherwise it stops its pollers and paints nothing.
// The design lives under Advanced → Experimental, in a <details> that starts closed. It is "visible" only on
// the Advanced tab with that <details> open; otherwise the pollers stop (the generation or apply itself keeps
// running on the manager, and /api/state still reports it) and the next open loads the design afresh.
let designSuspended=false;
function designVisible(){
 const box=$('experimental-design');
 return typeof tab!=='undefined'&&tab==='advanced'&&!!box&&box.open===true;
}
function designSuspend(){
 designStopWatch();
 const dialog=$('design-apply-dialog');
 if(!(dialog&&dialog.open)){designApplyStopWatch();designReviewStopWatch();}
 designSuspended=true;
}
function renderNetworkDesign(){
 const lab=current();
 if(!lab){designStopWatch();return;}
 if(!designVisible()){designSuspend();return;}
 // Coming back after the view was closed (or the tab left) reloads, unless the only copy of an unsaved edit is in memory.
 if(designSuspended){designSuspended=false;if(!designLeaveGuard()&&!designState.loading){designLoad(lab.id);return;}}
 if(designState.labId!==lab.id&&!designState.loading){designLoad(lab.id);return;}
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
function designCheckedValues(containerId,name,all=false){
 const container=$(containerId);if(!container||typeof container.querySelectorAll!=='function')return [];
 return [...container.querySelectorAll('input[name="'+name+'"]'+(all?'':':checked'))].map(i=>i.value);
}
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
  modules,retiredKnown:Object.keys((designState.view&&designState.view.retired)||{}),
  ospfArea:designVal('design-ospf-area'),bgpAs:designVal('design-bgp-as'),bgpRr:designCheckedValues('design-bgp-rr','design-bgp-rr'),bgpRrKnown:designCheckedValues('design-bgp-rr','design-bgp-rr',true),
  isisArea:designVal('design-isis-area'),isisType:designVal('design-isis-type'),gatewayProtocol:designVal('design-gateway-protocol'),
  devices,
  vrfs:designVrfsFromDom(),vlans:designVlansFromDom(),links:designLinksFromDom(),staticRoutes:designStaticFromDom()
 };
}
function designSetDraft(labId,intent){
 designState.draft={revision:(designState.view&&designState.view.intent&&designState.view.intent.revision)||'',intent};
 designState.draftDiscarded=false;
 // writeDesignDraft answers false when the browser's storage refused (quota, a private window): the draft
 // then lives in memory only, and the state line says so instead of the edit vanishing on the next reload.
 designState.draftUnsaved=typeof writeDesignDraft==='function'?writeDesignDraft(labId,designState.draft)===false:false;
}
// Back to the saved design: the draft (in memory and in browser storage) and any unparsable Advanced text go.
function designDiscardDraft(){
 const lab=current();if(!lab)return;
 designState.draft=null;designState.draftDiscarded=false;designState.draftUnsaved=false;designState.advancedInvalid=false;
 if(typeof clearDesignDraft==='function')clearDesignDraft(lab.id);
 setMarkup($('design-problems'),'');
 designRenderAll();
 if(typeof notify==='function')notify('Unsaved changes discarded.');
}
// A module the student unticked but the design still needs (VRFs, VLANs or static routes are defined) is kept on
// by designIntentFromForm and the box is redrawn ticked; the student is told why instead of watching it bounce.
const DESIGN_MODULE_KEPT={vrf:'VRFs (or links in a VRF) are defined',vlan:'VLANs (or links in a VLAN) are defined',routing:'static routes are defined'};
function designKeptModulesNotice(ticked,modules){
 if(!Array.isArray(ticked)||!Array.isArray(modules))return '';
 const kept=modules.filter(m=>!ticked.includes(m)&&DESIGN_MODULE_KEPT[m]);
 if(!kept.length)return '';
 return kept.map(m=>'The '+m+' module stays on while '+DESIGN_MODULE_KEPT[m]+'; remove them to turn it off.').join(' ');
}
function designOnGuidedChange(){
 const lab=current();if(!lab)return;
 // A change event from a form that was drawn for another lab (or not drawn yet for this one) is not this lab's
 // edit: redraw instead of reading it back.
 if(designState.formLab!==lab.id||designState.labId!==lab.id){designRenderAll();return;}
 const base=designCurrentIntent(designState.view);
 const values=designReadFormValues();
 const intent=designIntentFromForm(values,base);
 designSetDraft(lab.id,intent);
 designRenderForm(designState.view);
 designRenderHeader(lab,designActiveView(lab));
 const kept=designKeptModulesNotice(values.modules,intent.modules);
 if(kept&&typeof notify==='function')notify(kept);
}
function designOnAdvancedChange(){
 const lab=current();if(!lab)return;
 const text=$('design-advanced')?$('design-advanced').value:'';
 let parsed;
 // Text that does not parse is remembered as invalid: the state line says so, Save/Check/Generate refuse,
 // and the text stays on screen for the student to fix (nothing acts on the last good intent behind it).
 try{parsed=JSON.parse(text);}
 catch(error){designState.advancedInvalid=true;setMarkup($('design-problems'),designProblemsMarkup([{path:'advanced',message:'This is not valid JSON: '+error.message}]));designRenderHeader(lab,designActiveView(lab));return;}
 if(!parsed||typeof parsed!=='object'||Array.isArray(parsed)){
  designState.advancedInvalid=true;setMarkup($('design-problems'),designProblemsMarkup([{path:'advanced',message:'The design must be a JSON object.'}]));designRenderHeader(lab,designActiveView(lab));return;
 }
 designState.advancedInvalid=false;
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
// Remove from design on a retired row: only the module entry goes; where it is still used (the notice lists the paths) is
// removed under Advanced, and Save says so if anything remains.
function designRemoveRetired(id){
 const intent=designCurrentIntent(designState.view);
 designApplyIntentPatch({modules:(intent.modules||[]).filter(m=>m!==id)});
 if(typeof notify==='function')notify('Removed from the design. Save the design to keep this change.');
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
function designFocus(id){const el=$(id);if(el&&typeof el.focus==='function')el.focus();}
function designRemoveVrf(name){
 const base=designCurrentIntent(designState.view);
 const vrfs={...(base.vrfs||{})};delete vrfs[name];
 designApplyIntentPatch({vrfs});designFocus('design-vrf-add');
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
 designApplyIntentPatch({vlans});designFocus('design-vlan-add');
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
 designApplyIntentPatch({nodes});designFocus('design-static-add');
}
// The Advanced editor holds text that is not JSON: no action may run on the last good intent behind it.
function designAdvancedBlocked(){
 if(!designState.advancedInvalid)return false;
 const message='Fix the JSON under Advanced first (it is not valid), or use Discard changes to go back to the saved design.';
 if(typeof showActionError==='function')showActionError(message);else if(typeof notify==='function')notify(message);
 return true;
}
// --- error summary: DOM side ---------------------------------------------------------------------------
// One summary under the action buttons, announced once per new submission (designSummarySeq) through a
// visually hidden live region that is set only here — never by a poll or a re-render — and focused, so a
// keyboard or screen-reader student lands on it. Cleared by the next successful check, save or generate.
let designSummarySeq=0;
function designControlFor(id){
 const el=$(id);if(!el)return null;
 if(typeof el.tagName==='string'&&['INPUT','SELECT','TEXTAREA'].includes(el.tagName.toUpperCase()))return el;
 return typeof el.querySelector==='function'?el.querySelector('input,select,textarea'):null;
}
function designClearInvalid(){
 for(const mark of designState.invalid||[]){
  const el=mark.el;if(!el||typeof el.removeAttribute!=='function')continue;
  el.removeAttribute('aria-invalid');
  if(mark.prior)el.setAttribute('aria-describedby',mark.prior);else el.removeAttribute('aria-describedby');
 }
 designState.invalid=[];
}
function designClearSummary(){
 designClearInvalid();designState.summary=null;
 const box=$('design-error-summary');
 if(box){setMarkup(box,'');box.hidden=true;}
}
function designShowSummary(action,parsed,options){
 options=options||{};
 designClearInvalid();
 const summary={action,kind:parsed.kind,problems:parsed.problems,links:options.links!==false,lead:parsed.lead||''};
 designState.summary=summary;designSummarySeq++;
 const box=$('design-error-summary');
 if(box){setMarkup(box,designSummaryMarkup(summary));box.hidden=false;}
 // aria-invalid and aria-describedby on the mapped controls (the first field an item names).
 const described=new Map();
 for(const item of designSummaryItems(summary)){
  const field=item.fields[0];if(!field||field.advanced)continue;
  const el=designControlFor(field.id);if(!el)continue;
  if(!described.has(el))described.set(el,[]);described.get(el).push(item.id);
 }
 designState.invalid=[];
 for(const [el,ids] of described){
  if(typeof el.setAttribute!=='function')continue;
  const prior=typeof el.getAttribute==='function'?el.getAttribute('aria-describedby')||'':'';
  designState.invalid.push({el,prior});
  el.setAttribute('aria-invalid','true');el.setAttribute('aria-describedby',(prior?prior+' ':'')+ids.join(' '));
 }
 if(box){
  if(typeof box.focus==='function')box.focus();
  if(typeof box.scrollIntoView==='function')box.scrollIntoView({block:'nearest'});
 }
 const lab=current();if(lab)designRenderHeader(lab,{...designActiveView(lab),problems:summary.kind==='problems'?summary.problems:[]});
}
function designGotoField(id){
 let el=designControlFor(id)||$(id);
 const box=$('design-advanced-details');
 if(el&&typeof el.closest==='function'&&el.closest('[hidden]'))el=null;
 if(!el||id==='design-advanced'){if(box)box.open=true;el=$('design-advanced');}
 if(!el)return;
 if(typeof el.scrollIntoView==='function')el.scrollIntoView({block:'center'});
 if(typeof el.focus==='function')el.focus();
}
async function designValidate(){
 const lab=current();if(!lab||designAdvancedBlocked())return;
 const labId=lab.id,intent=designCurrentIntent(designState.view);
 try{
  const result=await json('/labs/'+encodeURIComponent(labId)+'/design/validate','POST',{intent,revision:''});
  if(designState.labId!==labId)return;   // the student moved to another lab meanwhile: nothing of this lands there
  setMarkup($('design-problems'),designProblemsMarkup(result.problems||[]));
  // validate also lists where a retired module is used ({path,module,message,new}): Generate refuses any of them.
  const found=[...(result.problems||[]),...(result.retired||[]).map(r=>({path:String(r.path||''),message:String(r.message||'')}))];
  if(found.length)designShowSummary('check',{kind:'problems',problems:found});
  else{designClearSummary();designRenderHeader(lab,designActiveView(lab));if(typeof notify==='function')notify('No problems found.');}
 }catch(error){if(designState.labId===labId)designShowSummary('check',designProblemsFromError(error));}
}
function designStaleMessage(message){return /changed since this page loaded|no saved design any more/i.test(String(message||''));}
// Saves the current intent (draft or saved) for the lab that is open now. Resolves true when saved. Every
// answer is applied only if the same lab is still open: a save answered late, after the student moved to
// another lab, must never repaint that lab with this one's design.
async function designSave(options){
 options=options||{};
 const lab=current();if(!lab||designAdvancedBlocked())return false;
 const labId=lab.id,intent=designCurrentIntent(designState.view);
 const revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
 try{
  // Validate first: the save route itself answers a fixed-string 400, not a structured problem list.
  const check=await json('/labs/'+encodeURIComponent(labId)+'/design/validate','POST',{intent,revision:''});
  if(designState.labId!==labId)return false;
  if((check.problems||[]).length){
   setMarkup($('design-problems'),designProblemsMarkup(check.problems));
   designShowSummary(options.action||'save',{kind:'problems',problems:check.problems});
   return false;
  }
  const view=await json('/labs/'+encodeURIComponent(labId)+'/design','PUT',{intent,revision});
  if(!designViewWritten(labId))return false;
  designState.view=view;designState.draft=null;designState.draftDiscarded=false;designState.draftUnsaved=false;
  if(typeof clearDesignDraft==='function')clearDesignDraft(labId);
  setMarkup($('design-problems'),'');designClearSummary();
  if(!options.quiet&&typeof notify==='function')notify('Design saved.');
  designRenderAll();
  return true;
 }catch(error){
  if(designState.labId!==labId)return false;
  if(designStaleMessage(error.message)){
   if(typeof showActionError==='function')showActionError(error.message);else if(typeof notify==='function')notify(error.message);
   await designLoad(labId);return false;
  }
  designShowSummary(options.action||'save',designProblemsFromError(error));
  return false;
 }
}
// Generate plan works on the saved design; unsaved changes are saved first, explicitly, so the plan never
// quietly comes from an older version than the form shows. A new plan is always shown as the newest.
async function designGenerate(){
 const lab=current();if(!lab||designAdvancedBlocked())return;
 const labId=lab.id;
 if(designState.draft){
  const saved=await designSave({quiet:true,action:'generate'});
  if(!saved||designState.labId!==labId)return;
  if(typeof notify==='function')notify('Design saved. Generating the plan…');
 }
 const revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
 try{
  await json('/labs/'+encodeURIComponent(labId)+'/design/generate','POST',{revision});
  if(designState.labId!==labId)return;
  designClearSummary();designState.viewing=null;
  await designLoad(labId);
  if(typeof refresh==='function')await refresh();
 }catch(error){
  if(designState.labId!==labId)return;
  const parsed=designProblemsFromError(error);
  if(parsed.kind==='problems')setMarkup($('design-problems'),designProblemsMarkup(parsed.problems));
  designShowSummary('generate',parsed);
 }
}
async function designCancel(){
 const lab=current();if(!lab)return;
 const newest=designNewestGeneration(designState.view);if(!newest)return;
 try{
  await json('/labs/'+encodeURIComponent(lab.id)+'/design/generations/'+encodeURIComponent(newest.id)+'/cancel','POST',{});
  if(typeof notify==='function')notify('Cancelling…');
 }catch(error){if(typeof notify==='function')notify(error.message);}
}
// A Remove design or Renumber dialog speaks for the lab it was opened from, with that lab's design revision
// at that moment. When the page has moved to another lab meanwhile (browser Back, a link) it must do nothing:
// two labs can share a design revision (it hashes the content), so the revision alone would not protect the
// other lab (QA-021). The dialog is also marked so a lab change closes it (closeLabDialogs in shell.js).
function designDialogStillForLab(labId){
 const shown=typeof activeId==='string'?activeId:(typeof current==='function'&&current()?current().id:'');
 return !!labId&&designState.labId===labId&&(!shown||shown===labId);
}
function designMarkLabDialog(dialog){if(dialog&&typeof dialog.setAttribute==='function')dialog.setAttribute('data-lab-dialog','');return dialog;}
const DESIGN_DIALOG_MOVED='The page moved to another lab while this dialog was open. Nothing was changed; open it again from that lab.';
function designRenumber(){
 const lab=current();if(!lab||typeof opDialog!=='function')return;
 const labId=lab.id,revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
 const dialog=designMarkLabDialog(opDialog('design-renumber-dialog','Renumber this design',
  '<p>The manager forgets every device id, loopback and link address this design has pinned. The next generated plan allocates them again from the pools, and devices may get different addresses.</p>'+
  '<p class="form-help">This cannot be undone here: download the design file first if you want to keep the current addresses. Devices already configured keep what they have until you apply a new plan.</p>'+
  '<div class="dialog-actions"><button type="button" class="button secondary" data-op-close>Cancel</button><button type="button" class="button danger" id="design-renumber-run">Forget allocations</button></div>'));
 const closeButtons=dialog.querySelectorAll?dialog.querySelectorAll('[data-op-close]'):[];
 for(const b of closeButtons)b.onclick=()=>dialog.close();
 if($('design-renumber-run'))$('design-renumber-run').onclick=()=>opTask(dialog,async()=>{
  if(!designDialogStillForLab(labId)){dialog.close();if(typeof notify==='function')notify(DESIGN_DIALOG_MOVED);return;}
  const view=await json('/labs/'+encodeURIComponent(labId)+'/design/renumber','POST',{revision});
  dialog.close();if(!designViewWritten(labId))return;
  designState.view=view;designRenderAll();if(typeof notify==='function')notify('Allocation ledger cleared.');
 });
}
function designClearDesign(){
 const lab=current();if(!lab||typeof opDialog!=='function')return;
 const labId=lab.id,revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
 const dialog=designMarkLabDialog(opDialog('design-clear-dialog','Remove this design',
  "<p>The saved network design for this lab is removed. Generated plans and their files are kept and still listed under History.</p>"+
  '<p class="form-help">This cannot be undone here: download the design file first if you may want it back. Devices already configured keep their configuration; nothing is changed on them.</p>'+
  '<div class="dialog-actions"><button type="button" class="button secondary" data-op-close>Cancel</button><button type="button" class="button danger" id="design-clear-run">Remove design</button></div>'));
 const closeButtons=dialog.querySelectorAll?dialog.querySelectorAll('[data-op-close]'):[];
 for(const b of closeButtons)b.onclick=()=>dialog.close();
 if($('design-clear-run'))$('design-clear-run').onclick=()=>opTask(dialog,async()=>{
  if(!designDialogStillForLab(labId)){dialog.close();if(typeof notify==='function')notify(DESIGN_DIALOG_MOVED);return;}
  const view=await json('/labs/'+encodeURIComponent(labId)+'/design/clear','POST',{revision});
  dialog.close();if(!designViewWritten(labId))return;
  designState.view=view;designState.draft=null;designState.draftUnsaved=false;designState.advancedInvalid=false;designState.viewing=null;
  if(typeof clearDesignDraft==='function')clearDesignDraft(labId);
  designRenderAll();if(typeof notify==='function')notify('Design removed.');
});
}
function designExport(){
 const lab=current();if(!lab||typeof window==='undefined'||typeof window.open!=='function')return;
 window.open('/api/labs/'+encodeURIComponent(lab.id)+'/design/export','_blank');
}
function designImportPrompt(){if($('design-import-file'))$('design-import-file').click();}
async function designImportFile(file){
 const lab=current();if(!lab||!file)return;
 const labId=lab.id,revision=(designState.view&&designState.view.intent&&designState.view.intent.revision)||'';
 const data=new FormData();data.append('intent',file);data.append('revision',revision);
 try{
  const result=await(await api('/labs/'+encodeURIComponent(labId)+'/design/import',{method:'POST',body:data})).json();
  if(!designViewWritten(labId))return;
  if(!result.imported){
   setMarkup($('design-problems'),designProblemsMarkup(result.problems||[]));
   designShowSummary('import',{kind:'problems',problems:result.problems||[]},{links:false});
   return;
  }
  designState.view=result;designState.draft=null;designState.draftDiscarded=false;designState.draftUnsaved=false;designState.advancedInvalid=false;
  if(typeof clearDesignDraft==='function')clearDesignDraft(labId);
  setMarkup($('design-problems'),'');designClearSummary();
  if(typeof notify==='function')notify('Design imported.');
  designRenderAll();
 }catch(error){
  if(designState.labId!==labId)return;
  if(designStaleMessage(error.message)){await designLoad(labId);if(typeof notify==='function')notify(error.message);return;}
  designShowSummary('import',designProblemsFromError(error),{links:false});
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
let designApplyState={labId:'',step:'choose',generationId:'',nodes:{},selected:new Set(),takeover:new Set(),review:null,requestId:'',jobId:'',job:null,reviewJobId:'',reviewJob:null,reviewStages:{},starting:false};
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
 if(typeof $('design-apply').setAttribute==='function')$('design-apply').setAttribute('aria-describedby','design-apply-reason');
 designApplyRenderLast(lab.id);
 designReviewRenderRunning(lab.id);
}
function designRenderExportGitButton(lab,view){
 if(!$('design-export-git'))return;
 const reason=designExportGitReason(lab,view);
 $('design-export-git').disabled=!!reason;
 // The same reason for both buttons ("Generate a plan first.") is said once, under Apply, not twice.
 const applyReason=$('design-apply')?$('design-apply').title:'';
 $('design-export-git').title=reason&&reason===applyReason?'':reason;
 if(typeof $('design-export-git').setAttribute==='function')$('design-export-git').setAttribute('aria-describedby',reason&&reason===applyReason?'design-apply-reason':'design-export-git-reason');
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
 if($('design-apply-reviewing-step'))$('design-apply-reviewing-step').hidden=step!=='reviewing';
 designApplyUpdateReviewButton();
}
function designApplyRenderChoose(){setMarkup($('design-apply-choose-body'),designApplyChooseMarkup(designApplyState.nodes,designApplyState.selected));}
function designApplyOpen(){
 const lab=current();if(!lab||!$('design-apply-dialog'))return;
 const view=designActiveView(lab),newest=designNewestGeneration(view);
 if(!newest||newest.status!=='succeeded')return;
 const nodes=view.nodes||{};
 designApplyState={labId:lab.id,step:'choose',generationId:newest.id,nodes,selected:designApplyDefaultSelection(nodes),
  takeover:new Set(),review:null,requestId:designApplyRequestId(),jobId:'',job:null,reviewJobId:'',reviewJob:null,reviewStages:{},starting:false};
 if($('design-apply-choose-error'))$('design-apply-choose-error').textContent='';
 if($('design-apply-review-error'))$('design-apply-review-error').textContent='';
 if($('design-apply-ack'))$('design-apply-ack').checked=false;
 if($('design-apply-minutes'))$('design-apply-minutes').value=5;
 designApplyRenderChoose();designApplyShowStep('choose');
 $('design-apply-dialog').showModal();
 // A review of this lab that is still running is picked up again, never started a second time.
 if(designReviewIsKnown(lab.id))designReviewReattach(lab.id,designReviewKnown.jobId);
}
function designApplyChooseSelection(){
 if(typeof document==='undefined'||typeof document.querySelectorAll!=='function')return [...designApplyState.selected];
 return [...document.querySelectorAll('[name="design-apply-target"]:checked')].map(i=>i.value);
}
// The review is a job: POST returns {review_job} at once, and the dialog follows GET .../review-jobs/{id} (about every
// 1.5 s) until it settles. Closing the dialog only stops following; nothing here cancels or says it cancelled.
let designReviewWatch=null,designReviewTimer=null,designReviewSeq=0;
let designReviewKnown={labId:'',jobId:'',status:''},designReviewRequest={sig:'',id:'',retry:false};
const DESIGN_REVIEW_POLL_MS=1500,DESIGN_REVIEW_QUIET_MS=4000,DESIGN_REVIEW_RETRIES=5;
function designReviewStopWatch(){clearTimeout(designReviewTimer);designReviewWatch=null;}
function designReviewMatches(labId,jobId){return designApplyState.labId===labId&&designApplyState.reviewJobId===jobId;}
function designApplyReviewRunning(){return !!designApplyState.starting||!!(designApplyState.reviewJob&&designApplyState.reviewJob.status==='running');}
// The Review button stays disabled while a job runs and says how many devices; the button itself is aria-busy.
function designApplyUpdateReviewButton(){
 const button=$('design-apply-review-run'),running=designApplyReviewRunning();
 const count=designApplyState.reviewJob?((designApplyState.reviewJob.targets||[]).length):designApplyChooseSelection().length;
 if(button){button.disabled=running;button.textContent=running?'Reviewing '+count+(count===1?' device…':' devices…'):'Review';}
 if(button&&typeof button.setAttribute==='function'){if(running)button.setAttribute('aria-busy','true');else if(typeof button.removeAttribute==='function')button.removeAttribute('aria-busy');}   // on the button only: aria-busy on the dialog would hold back its polite live log
}
function designReviewRender(){
 const job=designApplyState.reviewJob;
 if($('design-review-overall'))$('design-review-overall').textContent=designReviewOverall(job);
 setMarkup($('design-review-body'),designReviewMarkup(job));
 const settled=!!job&&job.status!=='running';
 if($('design-review-again'))$('design-review-again').hidden=!(settled&&job.status!=='done')&&!designApplyState.reviewGone;
 if($('design-review-close-note'))$('design-review-close-note').hidden=settled||!!designApplyState.reviewGone;
}
function designReviewSay(text){if(text&&$('design-review-live')){$('design-review-live').textContent='';$('design-review-live').textContent=text;}}
// A review is kept known while it runs and, once done, while its token is valid (600 s from the job's end, the contract's
// expires_in): the plan card then says "Review finished" with Show. After that it is forgotten and reopening starts fresh.
const DESIGN_REVIEW_TOKEN_MS=600000;
let designReviewExpiryTimer=null;
function designReviewForget(){designReviewKnown={labId:'',jobId:'',status:''};clearTimeout(designReviewExpiryTimer);designReviewExpiryTimer=null;}
function designReviewDoneValid(){return designReviewKnown.status==='done'&&Number(designReviewKnown.until||0)>Date.now();}
function designReviewIsKnown(labId){return designReviewKnown.labId===labId&&(designReviewKnown.status==='running'||designReviewDoneValid());}
function designReviewRenderRunning(labId){
 const el=$('design-review-running');if(!el)return;
 if(designReviewKnown.status==='done'&&!designReviewDoneValid())designReviewForget();
 const running=designReviewKnown.labId===labId&&designReviewKnown.status==='running',finished=designReviewKnown.labId===labId&&designReviewDoneValid();
 el.hidden=!(running||finished);
 if(running||finished)setMarkup(el,(running?'Review running… ':'Review finished — ')+'<button type="button" class="button secondary small" data-design-review-show="'+esc(designReviewKnown.jobId)+'">Show</button>');
}
// Remembers a running or done job (done with the moment its token expires); a failed or interrupted one has no token and is forgotten.
function designReviewKnow(job){
 clearTimeout(designReviewExpiryTimer);designReviewExpiryTimer=null;
 if(job.status!=='running'&&job.status!=='done'){designReviewForget();}
 else{
  const ended=Date.parse(job.finished||''),until=job.status==='done'?(Number.isFinite(ended)?ended:Date.now())+((job.review&&Number(job.review.expires_in))||600)*1000:0;
  designReviewKnown={labId:job.lab_id||designApplyState.labId,jobId:job.id,status:job.status,until};
  if(job.status==='done'){
   const ms=Math.max(0,until-Date.now())+50;
   designReviewExpiryTimer=setTimeout(()=>{if(designReviewKnown.status==='done'&&!designReviewDoneValid()){designReviewForget();const l=current();if(l)designReviewRenderRunning(l.id);}},ms);
  }
 }
 const lab=current();if(lab)designReviewRenderRunning(lab.id);
}
function designReviewAttach(job){
 designApplyState.reviewJobId=job.id;designApplyState.reviewJob=job;designApplyState.reviewStages=designReviewStages(job);designApplyState.reviewGone=false;designApplyState.starting=false;
 designReviewKnow(job);
 if($('design-review-error'))$('design-review-error').textContent='';
 designApplyShowStep('reviewing');designReviewRender();
 const dialog=$('design-apply-dialog');if(dialog&&'scrollTop' in dialog)dialog.scrollTop=0;
 designFocus('design-review-title');
 if(job.status==='running')designReviewStartWatch(designApplyState.labId,job.id,false);
 else if(job.status==='done'&&!job.review)designReviewStartWatch(designApplyState.labId,job.id,false,0);
 else designReviewSettled(job);
}
function designReviewApplyJob(job){
 const say=designReviewAnnouncement(job,designApplyState.reviewStages);
 designApplyState.reviewJob=job;designApplyState.reviewStages=designReviewStages(job);
 designReviewKnow(job);designReviewRender();designReviewSay(say);
}
// A job that ended: done hands its review (with the token) to the review step exactly as the old synchronous answer was
// used; failed and interrupted keep the dialog on the log with their sentence and Review again.
function designReviewSettled(job){
 designApplyUpdateReviewButton();
 if(job.status!=='done'){designReviewRender();return;}
 const review=job.review;
 if(!review){if($('design-review-error'))$('design-review-error').textContent=DESIGN_REVIEW_UNAVAILABLE;designApplyState.reviewGone=true;designReviewRender();return;}
 designApplyState.review=review;designApplyState.takeover=new Set(review.takeover||[]);
 designApplyRenderReview();designApplyShowStep('review');
 const dialog=$('design-apply-dialog');if(dialog&&'scrollTop' in dialog)dialog.scrollTop=0;
 designFocus('design-apply-review-title');
}
// quiet=true follows a job with the dialog closed (the plan card's "Review running…" line), slower and without painting the dialog.
function designReviewStartWatch(labId,jobId,quiet,delay){
 designReviewStopWatch();designReviewWatch=jobId;
 let failures=0;
 const poll=async()=>{
  if(designReviewWatch!==jobId)return;
  try{
   const job=await(await api('/labs/'+encodeURIComponent(labId)+'/design/review-jobs/'+encodeURIComponent(jobId))).json();
   if(designReviewWatch!==jobId)return;
   failures=0;
   if(quiet){
    if(designReviewKnown.jobId===jobId)designReviewKnow(job);
    if(job.status==='running')designReviewTimer=setTimeout(poll,DESIGN_REVIEW_QUIET_MS);else designReviewStopWatch();
    return;
   }
   if(!designReviewMatches(labId,jobId)){designReviewStopWatch();return;}   // a reopened or different dialog: this answer is not for it
   designReviewApplyJob(job);
   if(job.status==='running')designReviewTimer=setTimeout(poll,DESIGN_REVIEW_POLL_MS);
   else{designReviewStopWatch();designReviewSettled(job);}
  }catch(error){
   if(designReviewWatch!==jobId)return;
   if(error&&error.status===404){
    designReviewStopWatch();
    if(designReviewKnown.jobId===jobId)designReviewForget();
    const lab=current();if(lab)designReviewRenderRunning(lab.id);
    if(!quiet&&designReviewMatches(labId,jobId)){
     designApplyState.reviewGone=true;designApplyState.starting=false;designApplyState.reviewJob=null;designApplyUpdateReviewButton();
     if($('design-review-error'))$('design-review-error').textContent=DESIGN_REVIEW_UNAVAILABLE;
     if($('design-review-overall'))$('design-review-overall').textContent='';
     setMarkup($('design-review-body'),'');designReviewRender();
    }
    return;
   }
   failures++;
   if(failures>=DESIGN_REVIEW_RETRIES){
    designReviewStopWatch();
    if(!quiet&&designReviewMatches(labId,jobId)&&$('design-review-error'))$('design-review-error').textContent='Could not check the review\'s progress. Close this window and open Apply to devices again to look again; the review itself keeps running.';
    return;
   }
   designReviewTimer=setTimeout(poll,DESIGN_REVIEW_POLL_MS*failures);
  }
 };
 designReviewTimer=setTimeout(poll,delay===undefined?(quiet?DESIGN_REVIEW_QUIET_MS:DESIGN_REVIEW_POLL_MS):delay);
}
// Reopening Apply while a review runs: fetch the job once and attach to it.
async function designReviewReattach(labId,jobId){
 try{
  const job=await(await api('/labs/'+encodeURIComponent(labId)+'/design/review-jobs/'+encodeURIComponent(jobId))).json();
  if(designApplyState.labId!==labId||designApplyState.reviewJobId)return;
  designReviewAttach(job);
 }catch(error){
  if(designApplyState.labId!==labId)return;
  if(error&&error.status===404){designReviewForget();const lab=current();if(lab)designReviewRenderRunning(lab.id);}
  if($('design-apply-choose-error'))$('design-apply-choose-error').textContent=error&&error.status===404?DESIGN_REVIEW_UNAVAILABLE:(error&&error.message)||'';
 }
}
// After a load: a review of this lab that a reload (or another window) left running is found and shown on the plan card.
async function designReviewDiscover(labId){
 try{
  const list=await(await api('/labs/'+encodeURIComponent(labId)+'/design/review-jobs')).json();
  const jobs=Array.isArray(list)?list:(list&&Array.isArray(list.jobs)?list.jobs:[]);
  if(designState.labId!==labId)return;
  // The list is newest first and holds running jobs and jobs that finished less than 600 s ago (without review or token): a
  // running one wins, else the newest done one, whose token is still valid by that rule; GET fetches its review on Show.
  const running=jobs.find(j=>j&&j.status==='running'),done=jobs.find(j=>j&&j.status==='done');
  if(running){
   designReviewKnow({...running,lab_id:labId});
   const dialog=$('design-apply-dialog');
   if(!(dialog&&dialog.open)&&designReviewWatch!==running.id)designReviewStartWatch(labId,running.id,true);
  }else if(done&&!(designReviewKnown.labId===labId&&designReviewKnown.jobId!==done.id&&designReviewKnown.status==='running')){designReviewKnow({...done,lab_id:labId});}
  else if(designReviewKnown.labId===labId&&designReviewKnown.status==='running'){designReviewForget();designReviewRenderRunning(labId);}
 }catch{/* the plan card simply shows no running review */}
}
// Starts a review of `targets` (and re-reviews after a take-over change). errorId names the element that says why it did not start.
async function designApplyReviewFlow(targets,takeover,errorId){
 const labId=designApplyState.labId,generationId=designApplyState.generationId;
 const seq=++designReviewSeq;
 const sig=JSON.stringify([labId,generationId,targets,takeover]);
 // A new click is a new request; only a retry after a lost answer (no HTTP status) reuses its id, so the server returns the same job.
 const id=designReviewRequest.sig===sig&&designReviewRequest.retry?designReviewRequest.id:designApplyRequestId();
 designReviewRequest={sig,id,retry:false};
 designApplyState.starting=true;designApplyState.reviewJob=null;designApplyState.reviewJobId='';designApplyUpdateReviewButton();
 const fail=message=>{if($(errorId))$(errorId).textContent=message;};
 try{
  let job;
  try{job=(await json('/labs/'+encodeURIComponent(labId)+'/design/generations/'+encodeURIComponent(generationId)+'/review','POST',{targets,takeover,request_id:id})).review_job;}
  catch(error){
   // A review of this lab already runs: follow that one.
   if(error&&error.status===409&&error.review_job_id){
    if(seq!==designReviewSeq||designApplyState.labId!==labId)return;
    const running=await(await api('/labs/'+encodeURIComponent(labId)+'/design/review-jobs/'+encodeURIComponent(error.review_job_id))).json();
    if(seq!==designReviewSeq||designApplyState.labId!==labId)return;
    designReviewAttach(running);return;
   }
   throw error;
  }
  if(seq!==designReviewSeq||designApplyState.labId!==labId)return;   // a late answer never lands in a reopened or other dialog
  if(!job)throw new Error('The manager did not start the review. Try again.');
  designReviewAttach(job);
 }catch(error){
  if(seq!==designReviewSeq||designApplyState.labId!==labId)return;
  if(!(error&&error.status))designReviewRequest.retry=true;
  designApplyState.starting=false;designApplyUpdateReviewButton();
  fail(error.message);
 }
}
async function designApplyRunReview(){
 const targets=designApplyChooseSelection();
 designApplyState.selected=new Set(targets);
 if($('design-apply-choose-error'))$('design-apply-choose-error').textContent='';
 if(!targets.length){if($('design-apply-choose-error'))$('design-apply-choose-error').textContent='Choose at least one device.';return;}
 if(designApplyReviewRunning())return;
 await designApplyReviewFlow(targets,[...designApplyState.takeover].filter(n=>targets.includes(n)).sort(),'design-apply-choose-error');
}
// A device's reason in the review, in words: the server's exception names are kept in the details.
function designApplyReasonText(reason){
 const text=String(reason||'');
 if(/NoValidConnections|Connectivity:|Connection refused|timed out|Errno/i.test(text))return 'Could not connect to this device over SSH (is it running, and does its login work? Devices › Test logins). '+text;
 if(/Authentication|password|credential/i.test(text))return 'The device refused the saved login. Check its credentials under Devices. '+text;
 return text;
}
// One line above the devices when none of them can be applied to, so the student sees why before scrolling.
function designApplyReviewSummary(review){
 if(!review||!(review.targets||[]).length)return '';
 if((review.applicable||[]).length)return '';
 const total=review.targets.length,unreachable=review.targets.filter(t=>t.eligible&&!(t.reachable&&t.ready)).length;
 if(unreachable===total)return `<p class="form-error">None of the ${total===1?'device':total+' devices'} answered over SSH, so nothing can be applied. Check that the lab is running and the logins work (Devices › Test logins), then Back and Review again.</p>`;
 return `<p class="form-error">Nothing can be applied: ${unreachable?unreachable+' of '+total+' devices did not answer over SSH and the rest':'every device'} already match the plan or cannot take part. Back to choose other devices, or close.</p>`;
}
// The sole render point for the review step (a fresh review from designApplyRunReview's Back->Review,
// and a take-over re-review from designApplyToggleTakeover both land here): a new review result is
// content the student has not acknowledged yet, so the checkbox — the dialog's only other clearing
// point is designApplyOpen — is unticked again and the Apply button recomputed from that.
function designApplyRenderReview(){
 setMarkup($('design-apply-review-body'),designApplyReviewMarkup(designApplyState.review,designApplyState.takeover,designRetiredInfo(designState.view)));
 if($('design-apply-ack'))$('design-apply-ack').checked=false;
 designApplyUpdateRunButton();
}
function designApplyUpdateRunButton(){
 const ack=!!($('design-apply-ack')&&$('design-apply-ack').checked);
 if($('design-apply-run'))$('design-apply-run').disabled=!designApplyCanSubmit(designApplyState.review,designApplyState.takeover,ack);
 if($('design-apply-run-reason')){const why=designApplyRunReason(designApplyState.review,designApplyState.takeover,ack);$('design-apply-run-reason').textContent=why;$('design-apply-run-reason').hidden=!why;}
}
// A conflict's take-over checkbox: the token binds the take-over list, so the review must run again.
async function designApplyToggleTakeover(name,checked){
 if(checked)designApplyState.takeover.add(name);else designApplyState.takeover.delete(name);
 if(designApplyReviewRunning())return;
 const targets=(designApplyState.review&&designApplyState.review.targets||[]).map(t=>t.name);
 await designApplyReviewFlow(targets,[...designApplyState.takeover].sort(),'design-apply-review-error');
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
  designReviewForget();{const l=current();if(l)designReviewRenderRunning(l.id);}   // the token is single-use: the plan card no longer offers this review
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
// The dialog was closed (button, Escape or backdrop): following stops; a running review keeps running and the plan card keeps its line.
function designReviewDialogClosed(){
 designReviewStopWatch();
 const lab=current();
 if(lab&&designReviewKnown.labId===lab.id&&designReviewKnown.status==='running')designReviewStartWatch(lab.id,designReviewKnown.jobId,true);
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
function designApplyClose(){designApplyStopWatch();designReviewDialogClosed();if($('design-apply-dialog')&&typeof $('design-apply-dialog').close==='function')$('design-apply-dialog').close();}
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
 if($('design-apply-dialog'))$('design-apply-dialog').addEventListener('close',designReviewDialogClosed);
 if($('design-review-again'))$('design-review-again').onclick=()=>{designApplyState.reviewJob=null;designApplyState.reviewJobId='';designApplyState.reviewGone=false;if($('design-review-error'))$('design-review-error').textContent='';designApplyShowStep('choose');designFocus('design-apply-review-run');};
 if($('design-review-running'))$('design-review-running').addEventListener('click',e=>{if(e.target&&e.target.closest&&e.target.closest('[data-design-review-show]'))designApplyOpen();});
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

// --- load-time wiring: only when the design region's static skeleton is on the page ----------------------
function initNetworkDesign(){
 const guidedIds=['design-ipv4','design-ipv6','design-pool-loopback-ipv4','design-pool-loopback-ipv6',
  'design-pool-p2p-ipv4','design-pool-p2p-ipv6','design-pool-p2p-prefix','design-pool-lan-ipv4','design-pool-lan-ipv6',
  'design-pool-lan-prefix','design-ospf-area','design-bgp-as','design-bgp-rr','design-isis-area','design-isis-type','design-gateway-protocol'];
 for(const id of guidedIds)if($(id))$(id).addEventListener('change',designOnGuidedChange);
 if($('design-modules'))$('design-modules').addEventListener('change',designOnGuidedChange);
 if($('design-modules'))$('design-modules').addEventListener('click',e=>{const b=e.target&&e.target.closest&&e.target.closest('[data-design-retire-remove]');if(b)designRemoveRetired(b.dataset.designRetireRemove);});
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
 if($('design-discard'))$('design-discard').onclick=()=>designDiscardDraft();
 if($('design-plan-newest'))$('design-plan-newest').onclick=()=>{const latest=designNewestGeneration(designState.view);if(latest)designViewGeneration(latest.id);};
 if($('design-history-body'))$('design-history-body').addEventListener('click',e=>{const b=e.target&&e.target.closest&&e.target.closest('[data-design-view-generation]');if(b)designViewGeneration(b.dataset.designViewGeneration);});
 if($('design-bgp-rr'))$('design-bgp-rr').addEventListener('change',()=>designOnGuidedChange());
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
 if($('design-error-summary'))$('design-error-summary').addEventListener('click',e=>{const r=e.target&&e.target.closest&&e.target.closest('[data-design-retry]');if(r){const run={save:()=>designSave(),generate:()=>designGenerate(),check:()=>designValidate()}[r.dataset.designRetry];if(run)run();return;}const b=e.target&&e.target.closest&&e.target.closest('[data-design-goto]');if(b)designGotoField(b.dataset.designGoto);});
 if($('experimental-design'))$('experimental-design').addEventListener('toggle',()=>{if(typeof renderNetworkDesign==='function')renderNetworkDesign();});
 initDesignApply();
 initDesignExportGit();
}
if(typeof document!=='undefined'&&document.getElementById&&$('design-view'))initNetworkDesign();
