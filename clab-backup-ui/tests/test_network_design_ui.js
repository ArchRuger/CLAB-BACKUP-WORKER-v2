// network-design.js: pure state words, the guided-form <-> intent round trip, and the plan/compatibility
// markup, run the same way tests/test_restore_ui.js drives restore.js — a vm context with a fake $, esc
// and state, no DOM. The draft helpers (shell.js) are covered at the bottom with a minimal document/window.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {webcrypto}=require('node:crypto');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const same=(a,b)=>assert.equal(JSON.stringify(a),JSON.stringify(b));
const source=fs.readFileSync(path.join(__dirname,'../app/static/network-design.js'),'utf8');
const statusSource=fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8');
// extra merges in overrides (e.g. a fake `document` for designApplyChooseSelection's DOM path); every
// other test keeps the plain DOM-less context the file header describes.
function ctx(extra){
 const context=vm.createContext({esc,state:{labs:[]},$:()=>null,api:async()=>({json:async()=>({})}),
  json:async()=>({}),opDialog:()=>({querySelectorAll:()=>[]}),opTask:async()=>{},refresh:async()=>{},notify:()=>{},
  setMarkup:()=>{},menuReason:()=>{},showActionError:()=>{},closeMenus:()=>{},showTab:()=>{},current:()=>null,
  clearTimeout:()=>{},setTimeout:()=>0,crypto:webcrypto,document:{activeElement:null,querySelectorAll:()=>[],querySelector:()=>null},...extra});
 vm.runInContext(statusSource,context);
 vm.runInContext(source,context);
 return context;
}

// --- designStateOf: every state key -------------------------------------------------------------------
test('designStateOf: no design yet',()=>{
 const c=ctx();
 const st=c.designStateOf({},{generations:[],problems:[]});
 assert.equal(st.key,'none');assert.equal(st.label,'No design yet');assert.equal(st.pill,'neutral');
});
test('designStateOf: a saved design with no plan yet is not "No design yet"',()=>{
 const c=ctx();
 const st=c.designStateOf({},{intent:{schema:1,modules:['ospf']},generations:[],problems:[]});
 assert.equal(st.key,'saved');assert.equal(st.label,'Design saved, no plan yet');assert.equal(st.pill,'neutral');assert.match(st.detail,/Generate plan/);
 assert.equal(c.designStateOf({},{intent:null,generations:[],problems:[]}).key,'none','no saved intent: still No design yet');
 assert.equal(c.designStateOf({},{intent:{schema:1},generations:[],problems:[],draft:true}).key,'draft','an unsaved edit still wins');
 assert.equal(c.designStateOf({},{intent:{schema:1},generations:[{id:'g',status:'succeeded'}],problems:[]}).key,'ready','a plan still wins');
});
test('the More menu items carry the reason the route would refuse, and none otherwise',()=>{
 const c=ctx();
 const plain=rows=>JSON.parse(JSON.stringify(rows));
 assert.deepEqual(plain(c.designMoreMenuReasons({intent:null},{key:'none'})),[['design-export','Save a design first.'],['design-import',''],['design-renumber','Save a design first.'],['design-clear','There is no design to remove.']]);
 assert.deepEqual(plain(c.designMoreMenuReasons({intent:{schema:1}},{key:'saved'})),[['design-export',''],['design-import',''],['design-renumber',''],['design-clear','']]);
 const wait='Wait for the plan being generated to finish.';
 assert.deepEqual(plain(c.designMoreMenuReasons({intent:{schema:1}},{key:'generating'})),[['design-export',''],['design-import',wait],['design-renumber',wait],['design-clear',wait]]);
 // designRenderHeader applies them: disabled, title and the visible menu-reason line.
 const els={},reasons=[];const el=id=>{if(!els[id])els[id]={id,disabled:false,title:'',textContent:'',className:'',hidden:false,querySelector:()=>null};return els[id];};
 const h=ctx({$:el,menuReason:(e,text)=>reasons.push([e.id,text])});
 h.designRenderHeader({},{intent:null,generations:[],problems:[],engine:{available:true}});
 assert.equal(els['design-export'].disabled,true);assert.equal(els['design-export'].title,'Save a design first.');assert.equal(els['design-import'].disabled,false);
 assert.ok(reasons.some(([id,text])=>id==='design-clear'&&text==='There is no design to remove.'));
 h.designRenderHeader({},{intent:{schema:1},generations:[],problems:[],engine:{available:true}});
 for(const id of ['design-export','design-import','design-renumber','design-clear'])assert.equal(els[id].disabled,false,id);
 assert.equal(els['design-state-text'].textContent,'Design saved, no plan yet');
});
test('designStateOf: unsaved changes (draft)',()=>{
 const c=ctx();
 const st=c.designStateOf({},{generations:[],problems:[],draft:true});
 assert.equal(st.key,'draft');assert.equal(st.label,'Unsaved changes');assert.equal(st.pill,'warn');
});
test('designStateOf: generating',()=>{
 const c=ctx();
 const st=c.designStateOf({},{generations:[{id:'g',status:'running',message:'Generating the plan'}],problems:[]});
 assert.equal(st.key,'generating');assert.equal(st.label,'Generating the plan…');assert.equal(st.pill,'busy');
 const queued=c.designStateOf({},{generations:[],problems:[],summary:{generating:true}});
 assert.equal(queued.key,'generating');
});
test('designStateOf: the design has problems',()=>{
 const c=ctx();
 const st=c.designStateOf({},{generations:[],problems:[{path:'bgp.as',message:'Give BGP an AS number.'}]});
 assert.equal(st.key,'problems');assert.equal(st.label,'The design has problems');assert.equal(st.pill,'danger');
 assert.match(st.detail,/Give BGP an AS number\./);
});
test('designStateOf: plan ready to review',()=>{
 const c=ctx();
 const st=c.designStateOf({},{intent:{schema:1},generations:[{id:'g',status:'succeeded',message:'Plan generated'}],problems:[]});
 assert.equal(st.key,'ready');assert.equal(st.label,'Plan ready to review');assert.equal(st.pill,'ok');
});
test('designStateOf: plan is older than the design (stale)',()=>{
 const c=ctx();
 const st=c.designStateOf({},{intent:{schema:1},generations:[{id:'g',status:'succeeded'}],problems:[],summary:{stale:true}});
 assert.equal(st.key,'stale');assert.equal(st.label,'Plan is older than the design');assert.equal(st.pill,'warn');
});
test('designStateOf: the last plan failed',()=>{
 const c=ctx();
 const st=c.designStateOf({},{intent:{schema:1},generations:[{id:'g',status:'failed',message:'The engine could not generate this plan.'}],problems:[]});
 assert.equal(st.key,'failed');assert.equal(st.label,'The last plan failed');assert.equal(st.pill,'danger');
 assert.match(st.detail,/could not generate/);
});
test('designStateOf: the last plan was interrupted',()=>{
 const c=ctx();
 const st=c.designStateOf({},{intent:{schema:1},generations:[{id:'g',status:'interrupted',message:'The manager restarted.'}],problems:[]});
 assert.equal(st.key,'interrupted');assert.equal(st.label,'The last plan was interrupted');assert.equal(st.pill,'warn');
});
test('designStateOf: design engine unavailable, and it wins over every other state',()=>{
 const c=ctx();
 const st=c.designStateOf({},{engine:{available:false,diagnostic:'netlab is not installed on this manager.'},
  generations:[{id:'g',status:'succeeded'}],problems:[{path:'x',message:'y'}],draft:true});
 assert.equal(st.key,'engine');assert.equal(st.label,'Design engine unavailable');assert.equal(st.pill,'danger');
 assert.match(st.detail,/netlab is not installed/);
});

// --- designIntentFromForm / designFormFromIntent ------------------------------------------------------
function baseIntent(){
 return {schema:1,revision:'abc123',label:'BGP lab',families:{ipv4:true,ipv6:true},
  addressing:{loopback:{ipv4:'10.255.0.0/24',ipv6:'2001:db8:ff::/48'},p2p:{ipv4:'10.1.0.0/16',ipv6:'2001:db8:1::/48',prefix:31},
   lan:{ipv4:'172.16.0.0/16',ipv6:'2001:db8:2::/48',prefix:24}},
  modules:[],targets:null,nodes:{},links:{r1:{prefix:{ipv4:'10.9.9.0/30'}}},vlans:{},vrfs:{v1:{id:10}},interfaces:{},
  allocations:{loopbacks:{r1:{ipv4:'10.255.0.1'}}}};
}
function formValues(overrides){
 return {ipv4:true,ipv6:true,pools:{loopback:{ipv4:'10.255.0.0/24',ipv6:'2001:db8:ff::/48'},
  p2p:{ipv4:'10.1.0.0/16',ipv6:'2001:db8:1::/48',prefix:31},lan:{ipv4:'172.16.0.0/16',ipv6:'2001:db8:2::/48',prefix:24}},
  modules:['ospf','bgp'],ospfArea:'0.0.0.0',bgpAs:65001,bgpRr:['r2'],isisArea:'49.0001',isisType:'level-2',
  gatewayProtocol:'anycast',devices:[{name:'r1',role:'router'},{name:'r2',role:'router'},{name:'r3',role:'exclude'}],
  ...overrides};
}
test('designIntentFromForm keeps every field the guided controls do not own',()=>{
 const c=ctx();
 const intent=c.designIntentFromForm(formValues(),baseIntent());
 assert.equal(intent.schema,1);assert.equal(intent.label,'BGP lab');
 same(intent.links,{r1:{prefix:{ipv4:'10.9.9.0/30'}}});
 same(intent.vrfs,{v1:{id:10}});
 same(intent.allocations,{loopbacks:{r1:{ipv4:'10.255.0.1'}}});
 assert.equal(intent.targets,null);
});
test('designIntentFromForm writes families, pools, modules, OSPF area, BGP AS and the rr flag',()=>{
 const c=ctx();
 const intent=c.designIntentFromForm(formValues(),baseIntent());
 same(intent.families,{ipv4:true,ipv6:true});
 same(intent.addressing.loopback,{ipv4:'10.255.0.0/24',ipv6:'2001:db8:ff::/48'});
 same(intent.addressing.p2p,{ipv4:'10.1.0.0/16',ipv6:'2001:db8:1::/48',prefix:31});
 same(intent.addressing.lan,{ipv4:'172.16.0.0/16',ipv6:'2001:db8:2::/48',prefix:24});
 same(intent.modules,['ospf','bgp']);
 same(intent.ospf,{area:'0.0.0.0'});
 same(intent.bgp,{as:65001});
 assert.equal(intent.nodes.r2.bgp.rr,true);
 assert.equal(intent.nodes.r1,undefined,'the non-rr router with no other setting needs no node entry');
});
test('designIntentFromForm writes IS-IS area/type and the gateway protocol only while their module is ticked',()=>{
 const c=ctx();
 const intent=c.designIntentFromForm(formValues({modules:['isis','gateway']}),baseIntent());
 same(intent.isis,{area:'49.0001',type:'level-2'});
 same(intent.gateway,{protocol:'anycast'});
 assert.equal(intent.ospf,undefined);assert.equal(intent.bgp,undefined);
});
test('designIntentFromForm: an excluded device gets role "exclude"; a router gets no role key',()=>{
 const c=ctx();
 const intent=c.designIntentFromForm(formValues(),baseIntent());
 assert.equal(intent.nodes.r3.role,'exclude');
 assert.equal(intent.nodes.r1,undefined,'a router with nothing else set carries no node entry at all');
 assert.equal((intent.nodes.r2||{}).role,undefined,'r2 is a router (only its bgp.rr flag is set)');
});
test('designIntentFromForm drops a module\'s settings when the module is unticked',()=>{
 const c=ctx();
 const withBgp=c.designIntentFromForm(formValues(),baseIntent());
 assert.ok(withBgp.bgp);assert.equal(withBgp.nodes.r2.bgp.rr,true);
 const withoutBgp=c.designIntentFromForm(formValues({modules:['ospf']}),baseIntent());
 assert.equal(withoutBgp.bgp,undefined,'the global bgp settings are dropped');
 assert.equal(withoutBgp.nodes.r2,undefined,'r2\'s bgp.rr flag is dropped along with the module');
});
test('designFormFromIntent is the inverse of designIntentFromForm for the fields the guided controls own',()=>{
 const c=ctx();
 const values=formValues();
 const intent=c.designIntentFromForm(values,baseIntent());
 const back=c.designFormFromIntent(intent);
 assert.equal(back.ipv4,values.ipv4);assert.equal(back.ipv6,values.ipv6);
 same(back.pools,values.pools);
 same(back.modules,values.modules);
 assert.equal(back.ospfArea,values.ospfArea);
 assert.equal(back.bgpAs,values.bgpAs);
 same(back.bgpRr,values.bgpRr);
 assert.ok(back.devices.some(d=>d.name==='r2'&&d.role==='router'));
 assert.ok(back.devices.some(d=>d.name==='r3'&&d.role==='exclude'));
});
test('designFormFromIntent reads defaults from an empty intent',()=>{
 const c=ctx();
 const values=c.designFormFromIntent(c.designEmptyIntent());
 assert.equal(values.ipv4,true);assert.equal(values.ipv6,true);
 assert.equal(values.pools.loopback.ipv4,'10.255.0.0/24');assert.equal(values.pools.p2p.prefix,31);assert.equal(values.pools.lan.prefix,24);
 same(values.modules,[]);assert.equal(values.ospfArea,'0.0.0.0');assert.equal(values.bgpAs,'','an empty intent has no AS: the field shows its placeholder, never a look-alike value');same(values.bgpRr,[]);
 assert.equal(values.isisArea,'49.0001');assert.equal(values.isisType,'level-2');assert.equal(values.gatewayProtocol,'anycast');
});

// --- designPlanMarkup ----------------------------------------------------------------------------------
test('designPlanMarkup escapes a device name and renders interface, neighbour and BGP rows',()=>{
 const c=ctx();
 const plan={devices:[{name:'<script>r1</script>',device:'eos',id:1,loopback:{ipv4:'10.255.0.1',ipv6:'2001:db8:ff::1'},router_id:'10.255.0.1',
   interfaces:[{ifname:'Ethernet1',clab:'eth1',ipv4:'10.1.0.1/31',ipv6:'',neighbors:[{node:'r2',ifname:'Ethernet1'}],ospf:{area:'0.0.0.0'}}],
   bgp:{as:65000,router_id:'10.255.0.1',rr:false,neighbors:[{name:'r2',as:65000,type:'ibgp',ipv4:'10.1.0.2',ipv6:''}]}}],
  links:[{index:0,type:'p2p',name:'r1-r2',prefix:{ipv4:'10.1.0.0/31',ipv6:''},ends:[{node:'r1',ifname:'Ethernet1'},{node:'r2',ifname:'Ethernet1'}]}]};
 const html=c.designPlanMarkup(plan);
 assert.doesNotMatch(html,/<script>r1<\/script>/);
 assert.match(html,/&lt;script&gt;r1&lt;\/script&gt;/);
 assert.match(html,/Ethernet1/);assert.match(html,/eth1/);assert.match(html,/10\.1\.0\.1\/31/);
 assert.match(html,/r2/);assert.match(html,/OSPF area 0\.0\.0\.0/);
 assert.match(html,/BGP sessions/);assert.match(html,/ibgp/);assert.match(html,/65000/);
 assert.match(html,/10\.1\.0\.0\/31/);
});
test('designPlanMarkup: no plan yet',()=>{
 const c=ctx();
 assert.match(c.designPlanMarkup(null),/Generate a plan/);
});

// --- designCompatibilityMarkup -------------------------------------------------------------------------
test('designCompatibilityMarkup renders the four levels in words with the reason in title',()=>{
 const c=ctx();
 const generation={compatibility:{r1:[
  {feature:'ipv4',level:'verified_on_image',reason:'validated on arista_ceos: verified_on_image',evidence:'e1',profile:'eos'},
  {feature:'evpn',level:'generated_not_live_tested',reason:"netlab renders this on profile 'eos' but it was not validated",evidence:'',profile:'eos'},
  {feature:'srv6',level:'unsupported',reason:'netlab has no SRv6 attributes for profile eos',evidence:'',profile:'eos'},
  {feature:'mlag',level:'blocked_missing_prerequisite',reason:"'mlag' requires module lag",evidence:'',profile:'eos'}]}};
 const html=c.designCompatibilityMarkup(generation);
 assert.match(html,/Verified on this image/);assert.match(html,/validated on arista_ceos: verified_on_image/);
 assert.match(html,/Generated, not yet tested live/);
 assert.match(html,/Not supported/);assert.match(html,/netlab has no SRv6 attributes/);
 assert.match(html,/Needs/);assert.match(html,/module lag/);
 assert.match(html,/title="validated on arista_ceos: verified_on_image"/);
 assert.match(html,/<th scope="row">r1<\/th>/);
});
test('designCompatibilityMarkup: nothing to show yet',()=>{
 const c=ctx();
 assert.match(c.designCompatibilityMarkup({compatibility:{}}),/No compatibility information yet\./);
 assert.match(c.designCompatibilityMarkup(null),/No compatibility information yet\./);
});

// --- designGenerationLine -------------------------------------------------------------------------------
test('designGenerationLine words for succeeded, failed, interrupted and running',()=>{
 const c=ctx(),now=Date.now();
 assert.match(c.designGenerationLine({status:'running',message:'Generating the plan'},now),/^Generating the plan…/);
 assert.match(c.designGenerationLine({status:'succeeded',finished:new Date(now-60000).toISOString()},now),/^Plan generated/);
 assert.match(c.designGenerationLine({status:'failed',finished:new Date(now-60000).toISOString(),message:'x'},now),/^Plan generation failed/);
 assert.match(c.designGenerationLine({status:'interrupted'},now),/^Plan generation was interrupted/);
 assert.equal(c.designGenerationLine(null,now),'No plan generated yet.');
});

// --- problems markup escapes path and message ------------------------------------------------------------
test('designProblemsMarkup escapes the path and the message',()=>{
 const c=ctx();
 const html=c.designProblemsMarkup([{path:'bgp.<as>',message:'Give BGP an AS number <here>.'}]);
 assert.doesNotMatch(html,/<as>|<here>/);
 assert.match(html,/&lt;as&gt;/);assert.match(html,/&lt;here&gt;/);
 assert.equal(c.designProblemsMarkup([]),'');
 assert.equal(c.designProblemsMarkup(null),'');
});

// --- designModulesMarkup / designDevicesMarkup: small sanity checks used by the form renderer -----------
test('designModulesMarkup ticks the selected modules and uses student words',()=>{
 const c=ctx();
 const html=c.designModulesMarkup(['ospf','bgp','lag'],['bgp']);
 assert.match(html,/value="ospf" > OSPF/,'ospf is not ticked');
 assert.match(html,/value="bgp" checked> BGP/,'bgp is ticked');
 assert.match(html,/Link aggregation \(LAG, LACP, MLAG\)/);
});
test('designDevicesMarkup shows the blocked reason and disables the role select without a profile',()=>{
 const c=ctx();
 const html=c.designDevicesMarkup({r1:{kind:'linux',included:false,reason:'No design profile is mapped to the containerlab kind linux'},
  r2:{kind:'arista_ceos',included:true,profile:'eos',blocked:'Link r2:eth9--r3:eth9 has an interface the manager cannot map'}},{r2:'exclude'});
 assert.match(html,/No design profile is mapped to the containerlab kind linux/);
 assert.match(html,/<select data-design-role="r1" aria-label="Role of r1" disabled/,'the select is named after its device (U-04) and disabled without a profile');
 assert.match(html,/<select data-design-role="r2"[^>]*>/);
 assert.doesNotMatch(html.match(/<select data-design-role="r2"[^>]*>/)[0],/disabled/,'a device with a profile keeps its role select enabled');
 assert.match(html,/value="exclude" selected/);
 assert.match(html,/cannot map/);
 assert.equal(c.designDevicesMarkup({},{}),'<tr><td colspan="5" class="table-empty">This lab has no devices yet.</td></tr>');
});

// --- milestone E: VRFs, VLANs, links (vrf/vlan attachment) and static routes -----------------------------
// Markup functions first (pure, escaping every interpolation), then designIntentFromForm's handling of
// the four families: round trip through an existing intent, an uncovered key kept, an empty row dropped,
// and the vrf/vlan/routing module auto-add rule.
test('designVrfsMarkup renders each VRF with its loopback checkbox and escapes a hostile name',()=>{
 const c=ctx();
 const html=c.designVrfsMarkup({red:{loopback:true},'"><img>':{}});
 assert.match(html,/data-design-vrf-key="red"/);
 assert.match(html,/data-design-vrf-field="loopback" checked/);
 assert.doesNotMatch(html,/<img>/);
 assert.match(html,/&quot;&gt;&lt;img&gt;/);
 assert.equal(c.designVrfsMarkup({}),'<tr><td colspan="3" class="table-empty">No VRFs yet.</td></tr>');
});
test('designVlansMarkup renders each VLAN\'s id and escapes a hostile name',()=>{
 const c=ctx();
 const html=c.designVlansMarkup({red:{id:100},'a<b':{id:200}});
 assert.match(html,/data-design-vlan-key="red"/);
 assert.match(html,/data-design-vlan-field="id" aria-label="VLAN id of red" value="100"/,'every row control is named (U-04)');
 assert.match(html,/data-design-vlan-field="name" aria-label="VLAN name" value="red"/);assert.match(html,/aria-label="Remove VLAN a&lt;b"/);
 assert.doesNotMatch(html,/a<b/);
 assert.match(html,/a&lt;b/);
 assert.equal(c.designVlansMarkup({}),'<tr><td colspan="3" class="table-empty">No VLANs yet.</td></tr>');
});
test('designLinksMarkup shows each link\'s ends, pre-selects its VRF/VLAN settings, and flags settings the table does not cover',()=>{
 const c=ctx();
 const links=[{key:'ceos:eth1--r2:eth1',endpoints:{ceos:{nos:'Ethernet1'},r2:{nos:'Ethernet1'}}},{key:'a--b',endpoints:{}}];
 const settings={'ceos:eth1--r2:eth1':{vrf:'red',prefix:{ipv4:'10.9.9.0/30'}}};
 const html=c.designLinksMarkup(links,settings,['red','blue'],['v100']);
 assert.match(html,/data-design-link-key="ceos:eth1--r2:eth1"/);
 assert.match(html,/ceos — r2/);
 assert.match(html,/<option value="red" selected>red<\/option>/);
 assert.match(html,/Also set under Advanced: prefix/);
 assert.match(html,/data-design-link-key="a--b"/);
 assert.equal(c.designLinksMarkup([],{},[],[]),'<tr><td colspan="5" class="table-empty">This lab has no designable links yet.</td></tr>');
});
test('designStaticMarkup shows each device\'s static routes with a discard or address next hop',()=>{
 const c=ctx();
 const nodes={r1:{routing:{static:[{ipv4:'192.0.2.0/24',nexthop:{discard:true}},{ipv6:'2001:db8::/32',nexthop:{ipv6:'2001:db8::1'}}]}}};
 const html=c.designStaticMarkup(nodes,['r1','r2']);
 assert.match(html,/data-design-static-key="r1:0"/);
 assert.match(html,/data-design-static-field="prefix" aria-label="Prefix of static route 1" value="192\.0\.2\.0\/24"/,'named per row (U-04)');
 assert.match(html,/aria-label="Device of static route 2"/);assert.match(html,/aria-label="Remove static route 1"/);
 assert.match(html,/option value="discard" selected/);
 assert.match(html,/data-design-static-key="r1:1"/);
 assert.match(html,/value="2001:db8::\/32"/);
 assert.match(html,/value="2001:db8::1"/);
 assert.equal(c.designStaticMarkup({},[]),'<tr><td colspan="5" class="table-empty">No static routes yet.</td></tr>');
});
test('designIntentFromForm VRFs: builds intent.vrfs, keeps an uncovered key, omits loopback when false, and drops an empty-name row',()=>{
 const c=ctx();
 const base={...c.designEmptyIntent(),vrfs:{red:{loopback:true,rd:'65000:1'},blue:{}}};
 const values={pools:{},modules:[],devices:[],vrfs:[
  {key:'red',name:'red',loopback:true},{key:'blue',name:'blue',loopback:false},{key:'',name:'',loopback:true}
 ],vlans:[],links:[],staticRoutes:[]};
 const intent=c.designIntentFromForm(values,base);
 same(intent.vrfs.red,{loopback:true,rd:'65000:1'});
 same(intent.vrfs.blue,{});
 assert.equal(Object.keys(intent.vrfs).length,2,'the blank row is dropped');
 assert.ok(intent.modules.includes('vrf'),'defining a VRF turns the vrf module on');
});
test('designIntentFromForm VRFs: renaming a VRF keeps its other settings under the new name',()=>{
 const c=ctx();
 const base={...c.designEmptyIntent(),vrfs:{red:{loopback:true,rd:'65000:1'}}};
 const values={pools:{},modules:[],devices:[],vrfs:[{key:'red',name:'crimson',loopback:true}],vlans:[],links:[],staticRoutes:[]};
 const intent=c.designIntentFromForm(values,base);
 assert.equal(intent.vrfs.red,undefined);
 same(intent.vrfs.crimson,{loopback:true,rd:'65000:1'});
});
test('designIntentFromForm VLANs: builds intent.vlans, keeps an uncovered key, and drops an empty-name row',()=>{
 const c=ctx();
 const base={...c.designEmptyIntent(),vlans:{red:{id:100,description:'servers'}}};
 const values={pools:{},modules:[],devices:[],vrfs:[],vlans:[
  {key:'red',name:'red',id:'100'},{key:'',name:'',id:'200'}
 ],links:[],staticRoutes:[]};
 const intent=c.designIntentFromForm(values,base);
 same(intent.vlans,{red:{id:100,description:'servers'}});
 assert.ok(intent.modules.includes('vlan'));
});
test('designIntentFromForm links: attaches a VRF, keeps the link\'s other settings, and drops the vrf key (not the link) when none is chosen',()=>{
 const c=ctx();
 const base={...c.designEmptyIntent(),links:{'r1:eth1--r2:eth1':{prefix:{ipv4:'10.9.9.0/30'},vrf:'red'}}};
 const values={pools:{},modules:[],devices:[],vrfs:[],vlans:[],links:[{key:'r1:eth1--r2:eth1',vrf:'red',vlanAccess:'',trunk:[]}],staticRoutes:[]};
 let intent=c.designIntentFromForm(values,base);
 same(intent.links['r1:eth1--r2:eth1'],{prefix:{ipv4:'10.9.9.0/30'},vrf:'red'});
 values.links[0].vrf='';
 intent=c.designIntentFromForm(values,intent);
 same(intent.links['r1:eth1--r2:eth1'],{prefix:{ipv4:'10.9.9.0/30'}});
});
test('designIntentFromForm links: sets vlan access or trunk (trunk wins over access), and drops a link with nothing set at all',()=>{
 const c=ctx();
 const base=c.designEmptyIntent();
 const values={pools:{},modules:[],devices:[],vrfs:[],vlans:[],staticRoutes:[],links:[
  {key:'a--b',vrf:'',vlanAccess:'red',trunk:[]},
  {key:'c--d',vrf:'',vlanAccess:'red',trunk:['red','blue']},
  {key:'e--f',vrf:'',vlanAccess:'',trunk:[]}
 ]};
 const intent=c.designIntentFromForm(values,base);
 same(intent.links['a--b'],{vlan:{access:'red'}});
 same(intent.links['c--d'],{vlan:{trunk:['red','blue']}});
 assert.equal(intent.links['e--f'],undefined,'a link with nothing set is dropped, not kept as {}');
 assert.ok(intent.modules.includes('vlan'));
});
test('designIntentFromForm static routes: builds routing.static per device, keeps other node settings, and drops an empty-prefix row',()=>{
 const c=ctx();
 const base={...c.designEmptyIntent(),nodes:{ceos:{role:'exclude'}}};
 const values={pools:{},modules:[],devices:[],vrfs:[],vlans:[],links:[],staticRoutes:[
  {origDevice:'ceos',device:'ceos',prefix:'192.0.2.0/24',nexthopType:'discard',nexthopAddress:''},
  {origDevice:'ceos',device:'ceos',prefix:'2001:db8::/32',nexthopType:'address',nexthopAddress:'2001:db8::1'},
  {origDevice:'ceos',device:'ceos',prefix:'',nexthopType:'discard',nexthopAddress:''}
 ]};
 const intent=c.designIntentFromForm(values,base);
 assert.equal(intent.nodes.ceos.role,'exclude','other per-node settings survive');
 same(intent.nodes.ceos.routing.static,[{ipv4:'192.0.2.0/24',nexthop:{discard:true}},{ipv6:'2001:db8::/32',nexthop:{ipv6:'2001:db8::1'}}]);
 assert.ok(intent.modules.includes('routing'));
});
test('designIntentFromForm static routes: an address next hop with no address is dropped',()=>{
 const c=ctx();
 const base=c.designEmptyIntent();
 const values={pools:{},modules:[],devices:[],vrfs:[],vlans:[],links:[],
  staticRoutes:[{origDevice:'r1',device:'r1',prefix:'10.0.0.0/24',nexthopType:'address',nexthopAddress:''}]};
 const intent=c.designIntentFromForm(values,base);
 assert.equal(intent.nodes.r1,undefined);
});
test('designIntentFromForm static routes: clearing every route drops routing.static but never removes the routing module automatically',()=>{
 const c=ctx();
 const base={...c.designEmptyIntent(),modules:['routing'],nodes:{r1:{routing:{static:[{ipv4:'10.0.0.0/24',nexthop:{discard:true}}]}}}};
 const values={pools:{},modules:['routing'],devices:[],vrfs:[],vlans:[],links:[],staticRoutes:[]};
 const intent=c.designIntentFromForm(values,base);
 assert.equal(intent.nodes.r1,undefined,'the node had nothing else set, so it is dropped along with the now-empty routing object');
 assert.ok(intent.modules.includes('routing'),'routing stays on because it was already selected (e.g. for BGP policy)');
});
test('designIntentFromForm: defining a VRF or VLAN does not duplicate a module that is already selected',()=>{
 const c=ctx();
 const base=c.designEmptyIntent();
 const values={pools:{},modules:['vrf','vlan'],devices:[],
  vrfs:[{key:'red',name:'red',loopback:false}],vlans:[{key:'blue',name:'blue',id:'200'}],links:[],staticRoutes:[]};
 const intent=c.designIntentFromForm(values,base);
 same(intent.modules,['vrf','vlan']);
});

// --- draft helpers (shell.js), driven with a minimal document/window ------------------------------------
function shellHarness(){
 const localStore=new Map(),sessionStore=new Map();
 const make=store=>({getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)});
 const document={querySelectorAll:()=>[],getElementById:()=>null,addEventListener(){}};
 const context=vm.createContext({document,window:{localStorage:make(localStore),sessionStorage:make(sessionStore),addEventListener(){}},
  location:{hash:''},history:{},setTimeout:()=>0,clearTimeout(){},console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/shell.js'),'utf8'),context);
 return context;
}
test('the design draft is written, read back by matching revision, and dropped when the revision moved on',()=>{
 const c=shellHarness();
 assert.equal(c.readDesignDraft('lab1'),null);
 const draft={revision:'rev-a',intent:{modules:['bgp']}};
 assert.equal(c.writeDesignDraft('lab1',draft),true);
 same(c.readDesignDraft('lab1'),draft);
 // A different lab's draft is unaffected.
 assert.equal(c.readDesignDraft('lab2'),null);
 assert.equal(c.clearDesignDraft('lab1'),true);
 assert.equal(c.readDesignDraft('lab1'),null);
});
test('a stored draft with no intent, or malformed JSON, reads back as no draft',()=>{
 const c=shellHarness();
 c.window.localStorage.setItem('clab.design.draft.lab1','not json');
 assert.equal(c.readDesignDraft('lab1'),null);
 c.window.localStorage.setItem('clab.design.draft.lab1',JSON.stringify({revision:'r'}));
 assert.equal(c.readDesignDraft('lab1'),null,'no intent key: not a usable draft');
 assert.equal(c.readDesignDraft(''),null);assert.equal(c.writeDesignDraft('',{}),false);assert.equal(c.clearDesignDraft(''),false);
});

// --- Apply to devices (design_apply.py, docs/netlab-integration/PROVISIONING.md §4-5) ------------------
function readyTarget(overrides){
 return {name:'r1',kind:'arista_ceos',eligible:true,reason:'',reachable:true,ready:true,no_op:false,
  protected:[{module:'initial',statement:'hostname r1',reason:'device identity, access or management'}],
  diff:['+router ospf 7','+ router-id 10.255.0.1'],added:['router ospf 7'],removed:[],stale:[],conflicts:[],
  expected:[],removals:[],kept_manual:[],skipped:[],counts:{added:2,removed:0,stale:0,conflicts:0,expected:0,removals:0,kept_manual:0},
  takeover:false,compatibility:[],...overrides};
}
test('designApplyDeviceMarkup: a ready device shows its counts and diff',()=>{
 const c=ctx();
 const html=c.designApplyDeviceMarkup(readyTarget());
 assert.match(html,/r1/);assert.match(html,/Added 2/);assert.match(html,/Removed 0/);
 assert.match(html,/router ospf 7/);
 assert.match(html,/Protected settings left out \(1\)/);assert.match(html,/hostname r1/);
});
test('designApplyDeviceMarkup: a conflict shows the take-over checkbox, and its note once taken over',()=>{
 const c=ctx();
 const target=readyTarget({conflicts:['no shutdown'],counts:{added:1,removed:0,stale:0,conflicts:1,expected:0,removals:0,kept_manual:0}});
 const untaken=c.designApplyDeviceMarkup(target,new Set());
 assert.match(untaken,/data-design-apply-takeover="r1"/);
 assert.doesNotMatch(untaken,/data-design-apply-takeover="r1" checked/);
 assert.doesNotMatch(untaken,/become the design/);
 const taken=c.designApplyDeviceMarkup(target,new Set(['r1']));
 assert.match(taken,/data-design-apply-takeover="r1" checked/);
 assert.match(taken,/become the design's/);
});
test('designApplyDeviceMarkup: an ineligible device shows its reason and nothing else',()=>{
 const c=ctx();
 const html=c.designApplyDeviceMarkup({name:'host1',kind:'linux',eligible:false,reason:'A support host is generated only, never applied.'});
 assert.match(html,/host1/);assert.match(html,/A support host is generated only, never applied\./);
 assert.doesNotMatch(html,/Added \d/);
});
test('designApplyDeviceMarkup: an unreachable/not-ready device shows its reason',()=>{
 const c=ctx();
 const html=c.designApplyDeviceMarkup({name:'r2',kind:'arista_ceos',eligible:true,reachable:true,ready:false,
  reason:'Another change is waiting for confirmation on this device.'});
 assert.match(html,/Another change is waiting for confirmation/);
});
test('designApplyDeviceMarkup: a no-op device says it already matches the plan',()=>{
 const c=ctx();
 const html=c.designApplyDeviceMarkup(readyTarget({no_op:true}));
 assert.match(html,/Already matches the plan\./);
 assert.doesNotMatch(html,/Added \d/);
});

test('designApplyCanSubmit: needs acknowledgement, an applicable device, and every conflict resolved',()=>{
 const c=ctx();
 const clean={applicable:['r1'],targets:[readyTarget()]};
 assert.equal(c.designApplyCanSubmit(clean,new Set(),false),false,'not acknowledged');
 assert.equal(c.designApplyCanSubmit(clean,new Set(),true),true);
 assert.equal(c.designApplyCanSubmit({applicable:[],targets:[readyTarget()]},new Set(),true),false,'nothing applicable');
 const conflicted={applicable:['r1'],targets:[readyTarget({conflicts:['no shutdown'],counts:{...readyTarget().counts,conflicts:1}})]};
 assert.equal(c.designApplyCanSubmit(conflicted,new Set(),true),false,'unresolved conflict blocks submit');
 assert.equal(c.designApplyCanSubmit(conflicted,new Set(['r1']),true),true,'taking the conflict over unblocks it');
});

test('designApplyRequestId returns a 32-character lowercase hex string, different each time',()=>{
 const c=ctx();
 const a=c.designApplyRequestId(),b=c.designApplyRequestId();
 assert.match(a,/^[0-9a-f]{32}$/);assert.match(b,/^[0-9a-f]{32}$/);assert.notEqual(a,b);
});
test('designApplyBody clamps confirm_minutes, sorts the take-over list, and reuses a supplied request id',()=>{
 const c=ctx();
 const body=c.designApplyBody({token:'tok',requestId:'a'.repeat(32),confirmMinutes:'99',takeover:new Set(['r2','r1']),acknowledged:true});
 assert.equal(body.token,'tok');assert.equal(body.request_id,'a'.repeat(32));assert.equal(body.confirm_minutes,30);
 same(body.takeover,['r1','r2']);assert.equal(body.acknowledged,true);
 assert.equal(c.designApplyBody({confirmMinutes:'0'}).confirm_minutes,2);
 assert.equal(c.designApplyBody({confirmMinutes:'5'}).confirm_minutes,5);
 assert.equal(c.designApplyBody({}).acknowledged,false);
 assert.match(c.designApplyBody({}).request_id,/^[0-9a-f]{32}$/,'a request id is generated when none is supplied');
});

test('designApplyProgressMarkup: every outcome word appears for its status',()=>{
 const c=ctx();
 const statuses=['verified','verify_mismatch','applied','no_op','failed','rolled_back','uncertain','interrupted','drifted','ineligible','pending','backing_up','applying','confirming'];
 const job={status:'partial',message:'m',targets:statuses.map(s=>({name:s,kind:'arista_ceos',status:s,stage:'applied',message:''}))};
 const html=c.designApplyProgressMarkup(job);
 for(const s of statuses)assert.match(html,new RegExp(c.designApplyOutcomeWord(s).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')),'missing word for status '+s);
});
test('designApplyProgressMarkup: a verify mismatch shows the missing/remaining counts',()=>{
 const c=ctx();
 const job={status:'partial',targets:[{name:'r1',kind:'arista_ceos',status:'verify_mismatch',stage:'applied',
  message:'Applied and confirmed, but the read-back differs.',verify:{missing:['a','b'],remaining:['c']}}]};
 const html=c.designApplyProgressMarkup(job);
 assert.match(html,/2 expected line\(s\) missing, 1 stale line\(s\) remaining\./);
});

test('designApplyOwnershipMarkup: shows the statement count, plan id, applied time and a pending flag',()=>{
 const c=ctx();
 const now=Date.now();
 const ownership={summary:{r1:{statements:3,generation_id:'0123456789abcdef',applied_at:new Date(now-60000).toISOString(),pending:false},
  r2:{statements:1,generation_id:'fedcba9876543210',applied_at:'',pending:true}},
  statements:{r1:['router ospf 7','router-id 10.255.0.1','network 10.255.0.1/32 area 0'],r2:['ip routing']}};
 const html=c.designApplyOwnershipMarkup(ownership);
 assert.match(html,/r1 — 3 setting\(s\)/);assert.match(html,/0123456789ab/);assert.match(html,/router ospf 7/);
 assert.match(html,/r2 — 1 setting\(s\)/);assert.match(html,/Read-back pending/);
 assert.match(c.designApplyOwnershipMarkup({}),/No settings are owned/);
});

test('designApplyLastLineMarkup: a settled job shows its word, a relative time and a Show button',()=>{
 const c=ctx();
 const now=Date.now();
 const html=c.designApplyLastLineMarkup({id:'job1',status:'succeeded',finished:new Date(now-120000).toISOString()},now);
 assert.match(html,/Applied/);assert.match(html,/data-design-apply-show="job1"/);
 const busy=c.designApplyLastLineMarkup({id:'job2',status:'applying',created:new Date(now-5000).toISOString()},now);
 assert.match(busy,/Applying…/);
 assert.equal(c.designApplyLastLineMarkup(null,now),'');
});

test('designApplyDisabledReason: no plan, not linked, a running job, and the ready case',()=>{
 const c=ctx();
 const lab={id:'lab1',deployment:{status:'Running'}};
 assert.match(c.designApplyDisabledReason(lab,{generations:[]},[]),/Generate a plan/);
 const view={generations:[{id:'g',status:'succeeded'}]};
 assert.equal(c.designApplyDisabledReason(lab,view,[]),'');
 assert.match(c.designApplyDisabledReason({id:'lab1',deployment:{status:'Unlinked'}},view,[]),/not matched to a running lab/);
 assert.match(c.designApplyDisabledReason(lab,view,[{lab_id:'lab1',status:'applying'}]),/already running/);
 assert.match(c.designApplyDisabledReason(lab,{...view,engine:{available:false,diagnostic:'netlab missing'}},[]),/netlab missing/);
});
// Audit L-15 follow-up: after a manager restart the server's public design job is `interrupted` with a non-empty
// `rechecking` (the devices still being read back); the page treats it as active, words it like the restore's, and keeps polling.
test('a design apply job read back after a restart is active: worded, refused for a new apply, no time on the last line',()=>{
 const c=ctx();
 const job={id:'d1',lab_id:'lab1',status:'interrupted',rechecking:['r1'],message:'Manager restarted while the design was being applied.',targets:[]};
 assert.equal(c.designApplyJobActive(job),true);
 for(const idle of [{status:'interrupted'},{status:'interrupted',rechecking:[]},{status:'interrupted',rechecking:true},{status:'failed',rechecking:['r1']},null])
  assert.equal(c.designApplyJobActive(idle),false,JSON.stringify(idle));
 assert.equal(c.designApplyJobActive({status:'applying'}),true);
 assert.match(c.designApplyProgressMarkup(job),/Checking the devices after a manager restart…/);
 assert.doesNotMatch(c.designApplyProgressMarkup(job),/>Interrupted/);
 assert.match(c.designApplyProgressMarkup({...job,rechecking:undefined}),/Interrupted/,'once the read-back is done the job is plainly interrupted');
 const now=Date.now();
 const line=c.designApplyLastLineMarkup({...job,finished:new Date(now-120000).toISOString()},now);
 assert.match(line,/Checking the devices after a manager restart…/);assert.doesNotMatch(line,/ago|·/);
 const lab={id:'lab1',deployment:{status:'Running'}},view={generations:[{id:'g',status:'succeeded'}]};
 assert.match(c.designApplyDisabledReason(lab,view,[job]),/still being read back/);
 assert.equal(c.designApplyDisabledReason(lab,view,[{...job,lab_id:'other'}]),'','another lab\'s read-back does not hold this one');
});
test('designApplyShowJob follows a job that is being read back after a restart until it settles',async()=>{
 const timers=[];let polls=0;
 const job={id:'d1',lab_id:'lab1',status:'interrupted',rechecking:['r1'],targets:[]};
 const dialog={showModal(){},close(){}};
 const c=ctx({state:{labs:[{id:'lab1'}],design_jobs:[job]},current:()=>({id:'lab1'}),
  $:id=>id==='design-apply-dialog'?dialog:null,
  setTimeout:fn=>{timers.push(fn);return timers.length;},
  api:async()=>{polls++;return {json:async()=>polls<2?{...job}:{...job,status:'failed',rechecking:undefined}};}});
 c.designApplyShowJob('d1');
 assert.equal(timers.length,1,'the watch starts for a rechecking job');
 await timers.shift()();
 assert.equal(timers.length,1,'still rechecking: polled again');
 await timers.shift()();
 assert.equal(timers.length,0,'settled: following stops');
 assert.equal(polls,2);
});
// Audit V1: the banner's "View progress" (and the plan card's Show) call designApplyShowJob from any tab. showModal() inside a
// display:none ancestor shows nothing and leaves the page inert, so the dialog sits at page level (after </main>, like the restore job
// dialog) and the modal opens over the tab the student is on: no tab switch, no history entry, and Back or a tab change while it is
// open can never hide it (review V1-back).
test('designApplyShowJob opens the modal over the current tab without switching tabs (banner action from Topology)',()=>{
 const job={id:'d1',lab_id:'lab1',status:'failed',targets:[]};
 const calls=[],dialog={close(){},showModal(){calls.push(['showModal']);}};
 const c=ctx({state:{labs:[{id:'lab1'}],design_jobs:[job]},current:()=>({id:'lab1'}),
  $:id=>id==='design-apply-dialog'?dialog:id==='experimental-design'?{open:false}:null,
  showTab:name=>calls.push(['showTab',name]),syncRoute:push=>calls.push(['syncRoute',push])});
 vm.runInContext("var tab='topology'",c);
 c.designApplyShowJob('d1');
 assert.deepEqual(calls,[['showModal']],'the banner action stays on the tab it was clicked on');
 calls.length=0;vm.runInContext("tab='advanced'",c);
 c.designApplyShowJob('d1');
 assert.deepEqual(calls,[['showModal']],'the plan card\'s Show works the same way');
});
test('V1: #design-apply-dialog is not inside the Advanced tab or the closed Network design details, so its modal is always visible',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 const at=html.indexOf('<dialog id="design-apply-dialog"');
 assert.ok(at>0,'the dialog exists');
 assert.ok(at>html.indexOf('</main>'),'it is after </main>: no hidden tab panel or <details> is its ancestor');
 assert.match(html.slice(at,at+200),/data-lab-dialog/,'it still closes when the page moves to another lab');
});
// Risk-review finding: designApplyDisabledReason ignored view.summary.stale (the same flag designStateOf
// already reads for "Plan is older than the design"), so a stale plan could be offered for applying.
test('designApplyDisabledReason: a stale succeeded plan is disabled with a reason to regenerate it; a fresh one is not',()=>{
 const c=ctx();
 const lab={id:'lab1',deployment:{status:'Running'}};
 const stale={generations:[{id:'g',status:'succeeded'}],summary:{stale:true}};
 assert.equal(c.designApplyDisabledReason(lab,stale,[]),'Generate the plan again: the design or the topology changed since this plan.');
 const fresh={generations:[{id:'g',status:'succeeded'}],summary:{stale:false}};
 assert.equal(c.designApplyDisabledReason(lab,fresh,[]),'');
 const noSummary={generations:[{id:'g',status:'succeeded'}]};
 assert.equal(c.designApplyDisabledReason(lab,noSummary,[]),'','no summary at all is not treated as stale');
});

// Risk-review finding: designApplyOpen was the only place that unticked #design-apply-ack, so a review
// re-run after Back->Review, or a take-over re-review, left a previous acknowledgement ticked for content
// the student had not seen yet. designApplyRenderReview is the shared render point for both paths.
test('designApplyRenderReview unticks the acknowledgement and recomputes Apply on every new review result',async()=>{
 const elements=new Map();
 const field=()=>({checked:false,disabled:false,textContent:'',hidden:false,value:5});
 const c=ctx({document:{querySelectorAll:sel=>sel==='[name="design-apply-target"]:checked'?[{value:'r1'}]:[]}});
 c.$=id=>elements.get(id)||(elements.set(id,field()),elements.get(id));
 const oneTarget=()=>({name:'r1',kind:'arista_ceos',eligible:true,reachable:true,ready:true,no_op:false,
  counts:{added:0,removed:0,stale:0,conflicts:0,expected:0,removals:0,kept_manual:0},diff:[],expected:[],
  removals:[],kept_manual:[],protected:[],compatibility:[],conflicts:[]});
 // The review is a job now: the POST answers {review_job}; a finished job carries the former synchronous answer as `review`.
 c.json=async()=>({review_job:{id:'j1',status:'done',started:'2026-10-03T10:00:00Z',finished:'2026-10-03T10:00:05Z',server_time:1791021605,targets:[{name:'r1',stage:'done',timeline:{}}],review:{targets:[oneTarget()],applicable:['r1'],takeover:[]}}});
 await c.designApplyRunReview();
 c.$('design-apply-ack').checked=true;c.designApplyUpdateRunButton();
 assert.equal(c.$('design-apply-run').disabled,false,'acknowledged and applicable: Apply is enabled');
 // Back to choose, then Review again: a fresh review must not inherit the previous tick.
 await c.designApplyRunReview();
 assert.equal(c.$('design-apply-ack').checked,false,'a fresh review unticks the acknowledgement');
 assert.equal(c.$('design-apply-run').disabled,true,'Apply is disabled again until re-acknowledged');
 // Tick it again, then a take-over re-review must also untick it.
 c.$('design-apply-ack').checked=true;c.designApplyUpdateRunButton();
 assert.equal(c.$('design-apply-run').disabled,false);
 await c.designApplyToggleTakeover('r1',true);
 assert.equal(c.$('design-apply-ack').checked,false,'a take-over re-review unticks the acknowledgement too');
 assert.equal(c.$('design-apply-run').disabled,true);
});

// Risk-review finding: design_apply.py's masked() caps added/removed/stale/conflicts/expected/removals/
// kept_manual samples at SAMPLE=40 while counts[...] keeps the real total; the dialog silently hid the
// rest. designApplyDeviceMarkup now appends "… and N more" whenever a shown sample is short of its count.
test('designApplyDeviceMarkup: a capped conflicts sample says how many more there are; an uncapped one does not',()=>{
 const c=ctx();
 const capped=readyTarget({conflicts:Array.from({length:40},(_,i)=>'conflict '+i),counts:{...readyTarget().counts,conflicts:45}});
 const html=c.designApplyDeviceMarkup(capped);
 assert.match(html,/… and 5 more/);
 const exact=readyTarget({conflicts:['no shutdown'],counts:{...readyTarget().counts,conflicts:1}});
 assert.doesNotMatch(c.designApplyDeviceMarkup(exact),/… and \d+ more/);
});
test('designApplyDeviceMarkup: capped expected/removal-command/kept-manual samples also say how many more there are',()=>{
 const c=ctx();
 const expected=readyTarget({expected:Array.from({length:40},(_,i)=>'expected '+i),counts:{...readyTarget().counts,expected:44}});
 assert.match(c.designApplyDeviceMarkup(expected),/… and 4 more/);
 const removals=readyTarget({removals:Array.from({length:40},(_,i)=>'no '+i),counts:{...readyTarget().counts,removals:41}});
 assert.match(c.designApplyDeviceMarkup(removals),/… and 1 more/);
 const keptManual=readyTarget({kept_manual:Array.from({length:40},(_,i)=>'kept '+i),counts:{...readyTarget().counts,kept_manual:50}});
 assert.match(c.designApplyDeviceMarkup(keptManual),/… and 10 more/);
});

// A device row whose `takeover` field (design_apply.py's per-target, server-confirmed flag — distinct
// from the dialog's own take-over Set) is true says so in words, so the student sees what the
// acknowledgement covers even without expanding the conflicts list.
test('designApplyDeviceMarkup: a device whose takeover is true says how many manual settings are being taken over',()=>{
 const c=ctx();
 const taken=readyTarget({takeover:true,conflicts:['no shutdown','logging on'],counts:{...readyTarget().counts,conflicts:2}});
 assert.match(c.designApplyDeviceMarkup(taken),/Taking over 2 manual setting\(s\)/);
 const untaken=readyTarget({takeover:false});
 assert.doesNotMatch(c.designApplyDeviceMarkup(untaken),/Taking over/);
});

// --- Export plan to Git… (git_progress.py export_design): #design-export-git is enabled only for a
// succeeded plan on a lab with a Git binding; its request body always carries push:true (the mandatory
// review, in git-progress.js, decides the upload — this file never uploads).
test('designExportGitReason: no succeeded plan, then a plan with no repository bound, then ready',()=>{
 const c=ctx();
 const lab={id:'lab1',git_binding:{binding_id:'b',repository:{path:'/repo',branch:'main'}}};
 assert.equal(c.designExportGitReason(lab,{generations:[]}),'Generate a plan first.');
 assert.equal(c.designExportGitReason(lab,{generations:[{id:'g',status:'running'}]}),'Generate a plan first.');
 const view={generations:[{id:'g',status:'succeeded'}]};
 assert.equal(c.designExportGitReason({id:'lab1'},view),'Save this lab once first (Save in the lab’s header): the export goes into the folder the lab saves to.');
 assert.equal(c.designExportGitReason(lab,view),'');
});
test('designExportGitDefaultCheckpoint takes the generation id\'s first 12 characters, prefixed',()=>{
 const c=ctx();
 assert.equal(c.designExportGitDefaultCheckpoint('0123456789abcdef'),'design-0123456789ab');
 assert.equal(c.designExportGitDefaultCheckpoint('short'),'design-short');
 assert.equal(c.designExportGitDefaultCheckpoint(''),'design-');
});
test('designExportGitValidCheckpoint matches the server\'s checkpoint pattern exactly',()=>{
 const c=ctx();
 assert.equal(c.designExportGitValidCheckpoint('OSPF-plan_1'),true);
 assert.equal(c.designExportGitValidCheckpoint('design-0123456789ab'),true);
 assert.equal(c.designExportGitValidCheckpoint('-leading-dash'),false);
 assert.equal(c.designExportGitValidCheckpoint('has space'),false);
 assert.equal(c.designExportGitValidCheckpoint('slash/here'),false);
 assert.equal(c.designExportGitValidCheckpoint(''),false);
});
test('designExportGitRequestId returns a 32-character lowercase hex string, different each time',()=>{
 const c=ctx();
 const a=c.designExportGitRequestId(),b=c.designExportGitRequestId();
 assert.match(a,/^[0-9a-f]{32}$/);assert.match(b,/^[0-9a-f]{32}$/);assert.notEqual(a,b);
});
test('designExportGitBody folds a pasted note to one line, caps it at 200 characters, and always sends push:true',()=>{
 const c=ctx();
 const body=c.designExportGitBody({requestId:'a'.repeat(32),checkpoint:'ospf-done',note:'  line one\r\nline two\ttab  '});
 assert.equal(body.request_id,'a'.repeat(32));assert.equal(body.checkpoint,'ospf-done');
 assert.equal(body.note,'line one line two tab');assert.equal(body.push,true);
 const long=c.designExportGitBody({checkpoint:'c',note:'x'.repeat(250)});
 assert.equal(long.note.length,200);
 assert.match(c.designExportGitBody({checkpoint:'c'}).request_id,/^[0-9a-f]{32}$/,'a request id is generated when none is supplied');
 assert.equal(c.designExportGitBody({checkpoint:'c'}).note,'');
});
test('designExportGitDestinationMarkup names the repository, branch and the checkpoint folder, and escapes every value',()=>{
 const c=ctx();
 const binding={repository:{path:'/home/me/labs/<img onerror=1>',branch:'main<script>',prefix:'JunOS-TEST-2/working'}};
 const html=c.designExportGitDestinationMarkup(binding,'OSPF<script>done');
 assert.doesNotMatch(html,/<script>|<img/);
 assert.match(html,/&lt;img onerror=1&gt;/);
 assert.match(html,/main&lt;script&gt;/);
 assert.match(html,/JunOS-TEST-2\/working\/checkpoints\/OSPF&lt;script&gt;done/);
 const rootRepo=c.designExportGitDestinationMarkup({repository:{path:'/r/Course-Labs',branch:'main'}},'baseline-1');
 assert.match(rootRepo,/<code>Course-Labs<\/code>/);assert.match(rootRepo,/checkpoints\/baseline-1/);
 assert.equal(c.designExportGitDestinationMarkup(null,'x'),c.designExportGitDestinationMarkup({},'x'),'a missing binding renders the same as an empty one');
});
test('designRenderExportGitButton disables #design-export-git with the reason as its title, mirroring #design-apply',()=>{
 const c=ctx();
 const els={'design-export-git':{disabled:false,title:''}};
 c.$=id=>els[id];
 c.designRenderExportGitButton({id:'lab1'},{generations:[]});
 assert.equal(els['design-export-git'].disabled,true);assert.equal(els['design-export-git'].title,'Generate a plan first.');
 const lab={id:'lab1',git_binding:{binding_id:'b',repository:{path:'/r'}}};
 c.designRenderExportGitButton(lab,{generations:[{id:'g',status:'succeeded'}]});
 assert.equal(els['design-export-git'].disabled,false);assert.equal(els['design-export-git'].title,'');
});

// --- the campaign's ten probes (docs/netlab-ui-qa/probes-report.md), each pinned ------------------------
// designState is a top-level `let` of the script: it is reached through the context, not as a property of it.
function stateOf(c){return vm.runInContext('designState',c);}
test('P1: an unrelated guided edit keeps the pools the form has no control for, and every extra pool key',()=>{
 const c=ctx();
 const base=baseIntent();
 base.addressing={loopback:{ipv4:'10.255.0.0/24',ipv6:'2001:db8:ff::/48'},p2p:{ipv4:'10.1.0.0/16',ipv6:'2001:db8:1::/48',prefix:31},
  lan:{ipv4:'172.16.0.0/16',ipv6:'2001:db8:2::/48',prefix:24,start:2,allocation:'sequential'},vrf_loopback:{ipv4:'10.2.0.0/24'},router_id:{ipv4:'10.0.0.0/24'}};
 const intent=c.designIntentFromForm(formValues({ospfArea:'0.0.0.1'}),base);
 same(intent.addressing.vrf_loopback,{ipv4:'10.2.0.0/24'});same(intent.addressing.router_id,{ipv4:'10.0.0.0/24'});
 assert.equal(intent.addressing.lan.start,2);assert.equal(intent.addressing.lan.allocation,'sequential');assert.equal(intent.addressing.lan.prefix,24);
 assert.equal(intent.ospf.area,'0.0.0.1');
 // A guided pool edit still lands.
 const edited=c.designIntentFromForm(formValues({pools:{...formValues().pools,lan:{ipv4:'172.17.0.0/16',ipv6:'',prefix:25}}}),base);
 assert.equal(edited.addressing.lan.ipv4,'172.17.0.0/16');assert.equal(edited.addressing.lan.prefix,25);assert.equal(edited.addressing.lan.start,2,'the key the form cannot edit is kept');
});
test('P2: several route reflectors survive an unrelated guided edit; the checklist is the truth only for the routers it shows',()=>{
 const c=ctx();
 const base=baseIntent();base.modules=['bgp'];base.bgp={as:65001};base.nodes={r1:{bgp:{rr:true}},r2:{bgp:{rr:true}},r9:{bgp:{rr:true},role:'router'}};
 const values=formValues({bgpAs:65002,bgpRr:['r1','r2'],bgpRrKnown:['r1','r2','r3'],devices:[{name:'r1',role:'router'},{name:'r2',role:'router'},{name:'r3',role:'router'},{name:'r9',role:'router'}]});
 const intent=c.designIntentFromForm(values,base);
 assert.equal(intent.bgp.as,65002);
 assert.equal(intent.nodes.r1.bgp.rr,true);assert.equal(intent.nodes.r2.bgp.rr,true,'both reflectors kept');
 assert.equal(intent.nodes.r9.bgp.rr,true,'a router the checklist does not show keeps its own flag');
 assert.equal(intent.nodes.r3,undefined,'a shown router that is not ticked is not a reflector');
 const unticked=c.designIntentFromForm(formValues({bgpRr:[],bgpRrKnown:['r1','r2'],devices:[{name:'r1',role:'router'},{name:'r2',role:'router'}]}),base);
 assert.equal(unticked.nodes.r1,undefined);assert.equal(unticked.nodes.r2,undefined,'unticking both removes both');
 // The inverse lists every reflector, and the markup shows one checkbox per router with the chosen ones ticked.
 same(c.designFormFromIntent(base).bgpRr,['r1','r2','r9']);
 const markup=c.designReflectorMarkup(['r1','r2','r3'],new Set(['r1','r3']));
 assert.equal((markup.match(/type="checkbox"/g)||[]).length,3);assert.match(markup,/value="r1" checked/);assert.match(markup,/value="r2" >/);assert.match(markup,/value="r3" checked/);
 assert.match(c.designReflectorMarkup([],new Set()),/No router to choose from yet/);
 // An older caller with one name as a string still works.
 assert.equal(c.designIntentFromForm(formValues({bgpRr:'r2'}),baseIntent()).nodes.r2.bgp.rr,true);
});
test('P10a: 0, a blank and a non-number are kept as typed for the server to name, never turned into 65000 or 31',()=>{
 const c=ctx();
 assert.equal(c.designIntentFromForm(formValues({bgpAs:'0'}),baseIntent()).bgp.as,0);
 assert.equal(c.designIntentFromForm(formValues({bgpAs:0}),baseIntent()).bgp.as,0);
 assert.equal(c.designIntentFromForm(formValues({bgpAs:''}),baseIntent()).bgp.as,undefined,'an empty field leaves the AS out');
 assert.equal(c.designIntentFromForm(formValues({bgpAs:'abc'}),baseIntent()).bgp.as,'abc');
 const blank=c.designIntentFromForm(formValues({pools:{...formValues().pools,p2p:{ipv4:'10.1.0.0/16',ipv6:'',prefix:''}}}),baseIntent());
 assert.equal(blank.addressing.p2p.prefix,'','a blank prefix stays blank');
 assert.equal(c.designFormFromIntent({bgp:{as:0},addressing:{p2p:{prefix:''}}}).bgpAs,0,'the form shows what is stored');
 assert.equal(c.designFormFromIntent({bgp:{as:0},addressing:{p2p:{prefix:''}}}).pools.p2p.prefix,'');
 assert.equal(c.designFormFromIntent({addressing:{}}).pools.p2p.prefix,31,'no prefix stored: the schema default shows');
 assert.equal(c.designNumberOrRaw('31'),31);assert.equal(c.designNumberOrRaw(' 7 '),7);assert.equal(c.designNumberOrRaw('x'),'x');assert.equal(c.designNumberOrRaw(''),'');assert.equal(c.designNumberOrRaw(undefined),undefined);
});
test('P10b: the module checkboxes are synced from the values on every render, even when the markup string did not change',()=>{
 const boxes=[{value:'vrf',checked:false},{value:'ospf',checked:true}];
 const container={querySelectorAll:()=>boxes};
 const c=ctx();
 c.designSyncChecked(container,'input',new Set(['vrf']));
 assert.equal(boxes[0].checked,true);assert.equal(boxes[1].checked,false);
 c.designSyncChecked(null,'input',new Set());c.designSyncChecked({},'input',new Set());
});
test('P3: text under Advanced that is not JSON blocks Save, Check and Generate, is named in the state line, and stays on screen',async()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,checked:false,innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 const calls=[];const errors=[];
 const c=ctx({$:el,setMarkup:(e,html)=>{if(e)e.innerHTML=html;},json:async(path,method,body)=>{calls.push([path,method,body]);return {};},showActionError:m=>errors.push(m),notify:m=>errors.push('notify:'+m),current:()=>({id:'lab-a',name:'A'})});
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r1',modules:[]},generations:[],problems:[],nodes:{}};
 el('design-advanced').value='{not json';
 c.designOnAdvancedChange();
 assert.equal(stateOf(c).advancedInvalid,true);
 assert.match(el('design-problems').innerHTML,/not valid JSON/);
 assert.equal(c.designStateOf({},c.designActiveView({id:'lab-a'})).key,'invalid');
 assert.equal(el('design-state-text').textContent,'Advanced JSON is not valid');
 await c.designSave();await c.designValidate();await c.designGenerate();
 assert.equal(calls.length,0,'nothing was sent while the text does not parse');
 assert.ok(errors.length>=3&&errors.every(e=>/Fix the JSON under Advanced/.test(e)),JSON.stringify(errors));
 c.designRenderForm(stateOf(c).view);
 assert.equal(el('design-advanced').value,'{not json','the text is not overwritten by the last good intent');
 el('design-advanced').value='{"schema":1,"modules":["ospf"]}';c.designOnAdvancedChange();
 assert.equal(stateOf(c).advancedInvalid,false);assert.ok(stateOf(c).draft,'valid text becomes the draft again');
 c.designDiscardDraft();assert.equal(stateOf(c).draft,null);assert.equal(el('design-discard').hidden,true);
});
test('P4: Generate with unsaved changes saves them first and says so; the download and import wait for a save',async()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 const calls=[],notes=[];
 const view={intent:{schema:1,revision:'r2',modules:['bgp'],bgp:{as:65099}},generations:[],problems:[],nodes:{}};
 const c=ctx({$:el,notify:m=>notes.push(m),current:()=>({id:'lab-a',name:'A'}),
  json:async(path,method,body)=>{calls.push([path,method,body]);if(path.endsWith('/design/validate'))return {problems:[]};if(method==='PUT')return view;return {};},
  api:async()=>({json:async()=>view}),refresh:async()=>{}});
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r1',modules:['bgp'],bgp:{as:65001}},generations:[],problems:[],nodes:{}};
 stateOf(c).draft={revision:'r1',intent:{schema:1,modules:['bgp'],bgp:{as:65099}}};
 await c.designGenerate();
 const methods=calls.map(x=>x[0].split('/design')[1]+' '+x[1]);
 same(methods,['/validate POST',' PUT','/generate POST'],'validate, save, then generate');
 assert.equal(calls[1][2].intent.bgp.as,65099,'the draft is what gets saved');assert.equal(calls[2][2].revision,'r2','the plan is generated from the saved revision');
 assert.ok(notes.some(n=>/Design saved\. Generating the plan/.test(n)));
 const reasons=Object.fromEntries(JSON.parse(JSON.stringify(c.designMoreMenuReasons({intent:{schema:1},draft:true},{key:'draft'}))));
 assert.match(reasons['design-export'],/the download is the saved design/);assert.match(reasons['design-import'],/Save or discard/);
 assert.equal(reasons['design-renumber'],'');
 assert.match(Object.fromEntries(JSON.parse(JSON.stringify(c.designMoreMenuReasons({intent:{schema:1},advancedInvalid:true},{key:'invalid'}))))['design-export'],/saved design/);
 // A draft whose validation fails never reaches generate.
 calls.length=0;stateOf(c).draft={revision:'r2',intent:{schema:1,modules:['bgp'],bgp:{as:0}}};
 const bad=ctx({$:el,setMarkup:(e,html)=>{if(e)e.innerHTML=html;},notify:()=>{},current:()=>({id:'lab-a',name:'A'}),json:async(path,method,body)=>{calls.push([path,method]);return path.endsWith('/validate')?{problems:[{path:'bgp.as',message:'no'}]}:{};}});
 stateOf(bad).labId='lab-a';stateOf(bad).view=stateOf(c).view;stateOf(bad).draft=stateOf(c).draft;
 await bad.designGenerate();same(calls.map(x=>x[1]),['POST']);assert.match(el('design-problems').innerHTML,/bgp\.as/);
});
test('P5: a save answered after the student moved to another lab never lands on that lab',async()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 const notes=[];let c;
 const labA={intent:{schema:1,revision:'a1',modules:['ospf'],ospf:{area:'9.9.9.9'}},generations:[],problems:[],nodes:{}};
 c=ctx({$:el,notify:m=>notes.push(m),current:()=>({id:stateOf(c).labId,name:stateOf(c).labId}),
  json:async(path,method)=>{if(path.endsWith('/validate'))return {problems:[]};if(method==='PUT'){stateOf(c).labId='lab-b';stateOf(c).view={intent:null,generations:[],problems:[],nodes:{}};return labA;}return {};}});
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'a0',modules:[]},generations:[],problems:[],nodes:{}};
 stateOf(c).draft={revision:'a0',intent:{schema:1,modules:['ospf'],ospf:{area:'9.9.9.9'}}};
 const saved=await c.designSave();
 assert.equal(saved,false);
 assert.equal(stateOf(c).view.intent,null,'lab B keeps its own (empty) design');
 assert.equal(stateOf(c).labId,'lab-b');assert.equal(notes.length,0,'no "Design saved." toast for a lab that is no longer open');
 // Validate, too.
 const c2=ctx({$:el,notify:m=>notes.push(m),current:()=>({id:'lab-a'}),json:async()=>{stateOf(c2).labId='lab-b';return {problems:[{path:'x',message:'from A'}]};}});
 stateOf(c2).labId='lab-a';stateOf(c2).view={intent:null,generations:[],problems:[],nodes:{}};
 el('design-problems').innerHTML='';await c2.designValidate();
 assert.equal(el('design-problems').innerHTML,'','lab A\'s problems never paint over lab B');
});
test('P6: a plan fetched for a generation that is no longer the one shown is discarded; History › View pins an earlier plan',async()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 const plans={g1:{devices:[{name:'g1-dev'}]},g2:{devices:[{name:'g2-dev'}]}};
 const c=ctx({$:el,current:()=>({id:'lab-a',name:'A'}),api:async path=>({json:async()=>({plan:plans[path.split('/').pop()]})}),refresh:async()=>{}});
 stateOf(c).labId='lab-a';
 stateOf(c).view={intent:{schema:1,revision:'r'},generations:[{id:'g1',status:'succeeded',finished:'2026-09-27T10:00:00Z'},{id:'g2',status:'succeeded',finished:'2026-09-27T11:00:00Z'}],problems:[],nodes:{}};
 await c.designLoadPlan('lab-a','g1');
 assert.equal(stateOf(c).plan,null,'g1 is not the newest: its late answer is dropped');
 await c.designLoadPlan('lab-a','g2');
 assert.equal(stateOf(c).plan.devices[0].name,'g2-dev');
 await c.designLoadPlan('lab-b','g2');assert.equal(stateOf(c).plan.devices[0].name,'g2-dev','another lab\'s answer is ignored');
 // The student opens g1 from History: the plan card, files and download follow it until Back to newest.
 await c.designViewGeneration('g1');
 assert.equal(stateOf(c).viewing,'g1');assert.equal(stateOf(c).plan.devices[0].name,'g1-dev');
 assert.match(el('design-plan-status').textContent,/Showing an earlier plan/);assert.equal(el('design-plan-newest').hidden,false);
 assert.match(el('design-download').href,/g1\/download$/);
 const history=c.designHistoryMarkup(stateOf(c).view.generations,Date.now(),'g1');
 assert.match(history,/data-design-view-generation="g2"/);assert.doesNotMatch(history,/data-design-view-generation="g1"/);assert.match(history,/Shown above/);
 await c.designViewGeneration('g2');
 assert.equal(stateOf(c).viewing,null,'the newest is not pinned');assert.equal(stateOf(c).plan.devices[0].name,'g2-dev');assert.equal(el('design-plan-newest').hidden,true);
});
test('P7: a failed progress poll is retried a bounded number of times with the student told, then stops with a way out',async()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 const timers=[];let fail=true;
 const c=ctx({$:el,current:()=>({id:'lab-a',name:'A'}),setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearTimeout:()=>{},
  api:async()=>{if(fail)throw new Error('HTTP 500');return {json:async()=>({intent:{schema:1},generations:[{id:'g',status:'succeeded'}],problems:[],nodes:{}})};},refresh:async()=>{}});
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1},generations:[{id:'g',status:'running'}],problems:[],nodes:{}};
 c.designMaybeStartWatch();
 assert.equal(timers.length,1);
 for(let attempt=1;attempt<=5;attempt++){
  await timers[timers.length-1].fn();
  assert.match(stateOf(c).pollProblem,new RegExp('attempt '+attempt+' of 5'));
  assert.equal(timers.length,attempt+1,'another try is scheduled');assert.equal(timers[timers.length-1].ms,2000*attempt,'with backoff');
  assert.equal(el('design-detail').textContent,stateOf(c).pollProblem,'the state line says so');
 }
 await timers[timers.length-1].fn();
 assert.equal(timers.length,6,'no seventh try: the watch stays stopped, and a render does not restart it');assert.match(stateOf(c).pollProblem,/after 5 retries/);
 assert.equal(stateOf(c).pollGaveUp,true);c.designRenderAll();assert.equal(timers.length,6);
 assert.equal(c.designStateOf({},c.designActiveView({id:'lab-a'})).key,'unknown');
 // A deliberate step (Generate again, opening the tab again) loads afresh; a recovered poll then clears the problem and finishes.
 fail=false;stateOf(c).pollGaveUp=false;c.designMaybeStartWatch();await timers[timers.length-1].fn();
 assert.equal(stateOf(c).pollProblem,'');assert.equal(stateOf(c).view.generations[0].status,'succeeded');
});
test('P8: a draft the browser could not keep is said so in red, instead of vanishing silently on reload',()=>{
 const c=ctx({writeDesignDraft:()=>false,current:()=>({id:'lab-a'})});
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r1'},generations:[],problems:[],nodes:{}};
 c.designSetDraft('lab-a',{schema:1});
 assert.equal(stateOf(c).draftUnsaved,true);
 const st=c.designStateOf({},c.designActiveView({id:'lab-a'}));
 assert.equal(st.key,'draft');assert.equal(st.pill,'danger');assert.match(st.detail,/could not be kept in this browser/);
 const ok=ctx({writeDesignDraft:()=>true,current:()=>({id:'lab-a'})});stateOf(ok).labId='lab-a';stateOf(ok).view=stateOf(c).view;
 ok.designSetDraft('lab-a',{schema:1});assert.equal(stateOf(ok).draftUnsaved,false);assert.equal(ok.designStateOf({},ok.designActiveView({id:'lab-a'})).pill,'warn');
});
test('P9: after Remove design the state says so and the kept plans are not presented as current',()=>{
 const c=ctx();
 const st=c.designStateOf({},{intent:null,generations:[{id:'g',status:'succeeded'}],problems:[]});
 assert.equal(st.key,'removed');assert.equal(st.label,'No design saved (earlier plans kept)');assert.match(st.detail,/removed/);
 assert.equal(c.designStateOf({},{intent:null,generations:[],problems:[]}).key,'none');
 const els={};const el=id=>{if(!els[id])els[id]={id,value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 const h=ctx({$:el});stateOf(h).labId='lab-a';stateOf(h).plan={devices:[{name:'d'}]};
 h.designRenderPlanCard({intent:null,generations:[{id:'g',status:'succeeded',finished:'2026-09-27T10:00:00Z'}]});
 assert.match(el('design-plan-status').textContent,/belongs to a design that was removed/);
});

test('P10b (browser path): a focused checkbox does not block the re-render that redraws the module it changed; a text field does',()=>{
 const form={contains:()=>true};
 const c=ctx({$:id=>id==='design-form'?form:null,document:{activeElement:{tagName:'INPUT',type:'checkbox'},querySelectorAll:()=>[],querySelector:()=>null}});
 assert.equal(c.designFormFocused(),false,'a checkbox being ticked never suppresses the redraw');
 const t=ctx({$:id=>id==='design-form'?form:null,document:{activeElement:{tagName:'INPUT',type:'text'},querySelectorAll:()=>[],querySelector:()=>null}});
 assert.equal(t.designFormFocused(),true,'a field being typed in does');
 const b=ctx({$:id=>id==='design-form'?form:null,document:{activeElement:{tagName:'BUTTON',type:'button'},querySelectorAll:()=>[],querySelector:()=>null}});
 assert.equal(b.designFormFocused(),false);
});
test('P8 (leave guard): the page asks before leaving only while an unsaved draft exists that the browser could not store',()=>{
 const c=ctx({writeDesignDraft:()=>false,current:()=>({id:'lab-a'})});
 assert.equal(c.designLeaveGuard(),false);
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r1'},generations:[],problems:[],nodes:{}};
 c.designSetDraft('lab-a',{schema:1});assert.equal(c.designLeaveGuard(),true);
 const kept=ctx({writeDesignDraft:()=>true,current:()=>({id:'lab-a'})});stateOf(kept).labId='lab-a';stateOf(kept).view=stateOf(c).view;
 kept.designSetDraft('lab-a',{schema:1});assert.equal(kept.designLeaveGuard(),false,'a stored draft survives a reload: no prompt');
 c.designDiscardDraft();assert.equal(c.designLeaveGuard(),false);
});

test('U-01: when another lab\'s design arrives, the form is redrawn even while a field has focus, and a stale form is never saved into the new lab',()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,checked:false,innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[],contains:()=>true};return els[id];};
 let blurred=0;const field={tagName:'INPUT',type:'text',blur(){blurred++;}};
 const written=[];
 const c=ctx({$:el,setMarkup:(e,html)=>{if(e)e.innerHTML=html;},document:{activeElement:field,querySelectorAll:()=>[],querySelector:()=>null},current:()=>({id:stateOf(c).labId,name:stateOf(c).labId}),
  writeDesignDraft:(labId,draft)=>{written.push([labId,draft.intent.ospf&&draft.intent.ospf.area]);return true;}});
 // Lab A's design is shown; the OSPF area field holds A's value and has focus.
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'a1',modules:['ospf'],ospf:{area:'9.9.9.9'}},generations:[],problems:[],nodes:{}};
 c.designRenderForm(stateOf(c).view);
 assert.equal(el('design-ospf-area').value,'9.9.9.9');assert.equal(stateOf(c).formLab,'lab-a');assert.equal(blurred,1,'the first draw of a lab also ignores focus');
 // A typed edit in A is kept from being overwritten by a background render (the existing guard).
 el('design-ospf-area').value='1.1.1.1';c.designRenderForm(stateOf(c).view);assert.equal(el('design-ospf-area').value,'1.1.1.1','the focused field is not rewritten for the same lab');
 // Lab B's design arrives while the field still has focus: the form is redrawn for B.
 stateOf(c).labId='lab-b';stateOf(c).view={intent:null,generations:[],problems:[],nodes:{}};stateOf(c).draft=null;
 c.designRenderForm(stateOf(c).view);
 assert.equal(stateOf(c).formLab,'lab-b');assert.equal(blurred,2,'the focused field is blurred so the guard cannot keep A\'s values');
 assert.equal(el('design-ospf-area').value,'0.0.0.0','B\'s (default) value is shown, not A\'s');
 // A change event that fires before B's form was drawn is never read back as B\'s edit.
 stateOf(c).formLab='lab-a';el('design-ospf-area').value='9.9.9.9';
 c.designOnGuidedChange();
 assert.equal(stateOf(c).draft,null,'no draft was built from the stale form');assert.equal(written.length,0);
 assert.equal(stateOf(c).formLab,'lab-b','the change redrew the form for the lab that is open');
});

test('QA-021: Remove design and Renumber act only for the lab they were opened from, with that lab\'s revision at open time, and are marked to close on a lab change',async()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,onclick:null,disabled:false,innerHTML:'',textContent:''};return els[id];};
 const calls=[],notices=[];let dialog=null,shown={id:'lab-a',name:'A'};
 const opDialog=(id)=>{dialog={id,attrs:{},closed:0,setAttribute(k,v){this.attrs[k]=v;},querySelectorAll:()=>[],querySelector:()=>null,close(){this.closed++;}};return dialog;};
 const c=ctx({$:el,opDialog,opTask:async(d,fn)=>fn(),json:async(url,method,body)=>{calls.push([url,method,body]);return {intent:null,generations:[],problems:[],nodes:{}};},
  notify:m=>notices.push(m),current:()=>shown,clearDesignDraft:()=>{}});
 c.activeId='lab-a';
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r-a'},generations:[],problems:[],nodes:{}};
 // 1. Opened in lab A; the page moves to lab B, whose design happens to share the revision. Confirming does nothing to A.
 c.designClearDesign();
 assert.equal(dialog.id,'design-clear-dialog');assert.equal('data-lab-dialog' in dialog.attrs,true,'the dialog is marked so a lab change closes it');
 c.activeId='lab-b';shown={id:'lab-b',name:'B'};stateOf(c).labId='lab-b';stateOf(c).view={intent:{schema:1,revision:'r-a'},generations:[],problems:[],nodes:{}};
 await el('design-clear-run').onclick();
 assert.deepEqual(calls,[],'no request was sent for either lab');assert.equal(dialog.closed,1,'the stale dialog closed');
 assert.match(notices[notices.length-1],/moved to another lab/);
 // 2. Opened and confirmed in lab A: the request names A and carries the revision the dialog was opened with, even if
 // the design was saved again meanwhile (the server then refuses the stale revision itself).
 c.activeId='lab-a';shown={id:'lab-a',name:'A'};stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r-a'},generations:[],problems:[],nodes:{}};
 c.designClearDesign();stateOf(c).view.intent.revision='r-a2';
 await el('design-clear-run').onclick();
 assert.equal(calls.length,1);assert.match(calls[0][0],/\/labs\/lab-a\/design\/clear$/);same(calls[0][2],{revision:'r-a'});
 assert.equal(notices[notices.length-1],'Design removed.');
 // 3. Renumber follows the same rule.
 stateOf(c).view={intent:{schema:1,revision:'r-a'},generations:[],problems:[],nodes:{}};
 c.designRenumber();assert.equal(dialog.id,'design-renumber-dialog');assert.equal('data-lab-dialog' in dialog.attrs,true);
 c.activeId='lab-b';shown={id:'lab-b',name:'B'};stateOf(c).labId='lab-b';
 await el('design-renumber-run').onclick();
 assert.equal(calls.length,1,'the stale Renumber sent nothing');assert.equal(dialog.closed,1);assert.match(notices[notices.length-1],/moved to another lab/);
 // A page that never defined activeId still refuses on designState.labId alone.
 c.activeId=undefined;stateOf(c).labId='lab-b';assert.equal(c.designDialogStillForLab('lab-a'),false,'the design state says another lab');
 shown={id:'lab-a',name:'A'};stateOf(c).labId='lab-a';assert.equal(c.designDialogStillForLab('lab-a'),true);shown={id:'lab-b',name:'B'};assert.equal(c.designDialogStillForLab('lab-a'),false,'the lab on screen says another lab');
});

test('U-10/U-15/U-16: Generate on nothing says why, the warnings fold carries its count, and a shared reason is said once',()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,innerHTML:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;},querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 const c=ctx({$:el,setMarkup:(e,html)=>{if(e)e.innerHTML=html;},current:()=>({id:'lab-a',name:'A'})});
 c.designRenderHeader({},{intent:null,generations:[],problems:[],engine:{available:true}});
 assert.equal(el('design-generate').disabled,true);assert.equal(el('design-generate').title,'Choose settings below and save the design first.');
 assert.match(el('design-detail').textContent,/save the design, then Generate plan/);
 c.designRenderHeader({},{intent:null,draft:true,generations:[],problems:[],engine:{available:true}});
 assert.equal(el('design-generate').disabled,false,'a draft can be generated (it is saved first)');
 stateOf(c).labId='lab-a';stateOf(c).plan=null;
 c.designRenderPlanCard({intent:{schema:1},generations:[{id:'g',status:'succeeded',warnings:['w1','w2']}]});
 assert.equal(el('design-plan-warnings-summary').textContent,'Warnings (2)');assert.equal(el('design-plan-warnings-wrap').hidden,false);
 // Both buttons off for the same reason: the export button points at Apply's caption and carries no second title.
 el('design-apply').title='Generate a plan first.';
 c.designRenderExportGitButton({id:'lab-a',git_binding:null},{intent:{schema:1},generations:[],problems:[]});
 assert.equal(el('design-export-git').disabled,true);assert.equal(el('design-export-git').title,'');assert.equal(el('design-export-git').attrs['aria-describedby'],'design-apply-reason');
});
test('U-05/U-06: the apply review names itself, explains an empty review in words and says why Apply is off',()=>{
 const c=ctx();
 const review={targets:[{name:'r1',kind:'eos',eligible:true,reachable:false,ready:false,reason:'Connectivity: NoValidConnectionsError'},{name:'r2',kind:'eos',eligible:true,reachable:false,ready:false,reason:'Connectivity: NoValidConnectionsError'}],applicable:[]};
 const html=c.designApplyReviewMarkup(review,new Set());
 assert.match(html,/<h3 id="design-apply-review-title" tabindex="-1">Review of 2 devices<\/h3>/);
 assert.match(html,/None of the 2 devices answered over SSH, so nothing can be applied/);
 assert.match(html,/Could not connect to this device over SSH \(is it running, and does its login work\? Devices › Test logins\)\. Connectivity: NoValidConnectionsError/);
 assert.equal(c.designApplyRunReason(review,new Set(),true),'Nothing can be applied: no chosen device is ready for this plan.');
 const ok={targets:[{name:'r1',kind:'eos',eligible:true,reachable:true,ready:true,counts:{added:1,conflicts:0}}],applicable:['r1']};
 assert.equal(c.designApplyRunReason(ok,new Set(),false),'Tick the acknowledgement above to enable Apply.');
 assert.equal(c.designApplyRunReason(ok,new Set(),true),'');
 const conflict={targets:[{name:'r1',kind:'eos',eligible:true,reachable:true,ready:true,counts:{added:1,conflicts:2}}],applicable:['r1']};
 assert.match(c.designApplyRunReason(conflict,new Set(),true),/Take over these settings/);assert.equal(c.designApplyRunReason(conflict,new Set(['r1']),true),'');
 assert.doesNotMatch(c.designApplyReviewMarkup(ok,new Set()),/nothing can be applied/);
});
test('U-07: removing a row gives focus to the table\'s Add button',()=>{
 const els={};const el=id=>{if(!els[id])els[id]={id,focused:0,focus(){this.focused++;},innerHTML:'',value:'',hidden:false,querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 const c=ctx({$:el,current:()=>({id:'lab-a'}),writeDesignDraft:()=>true});
 stateOf(c).labId='lab-a';stateOf(c).formLab='lab-a';stateOf(c).view={intent:{schema:1,vrfs:{red:{}},vlans:{v:{id:1}},nodes:{r1:{routing:{static:[{ipv4:'192.0.2.0/24',nexthop:{discard:true}}]}}}},generations:[],problems:[],nodes:{}};
 c.designRemoveVrf('red');assert.equal(el('design-vrf-add').focused,1);
 c.designRemoveVlan('v');assert.equal(el('design-vlan-add').focused,1);
 c.designRemoveStatic('r1:0');assert.equal(el('design-static-add').focused,1);
});

// --- QA-015 (stress finding R1): an older design answer that lands after a newer one is dropped ------------
test('QA-015: two overlapping loads of one lab, the older answer arriving last, leave the newer generation shown',async()=>{
 const held=[];
 const api=async url=>({json:()=>/\/review-jobs/.test(url)?Promise.resolve([]):/\/generations\//.test(url)?Promise.resolve({plan:{files:[]}}):new Promise(resolve=>held.push(resolve))});
 const c=ctx({api});
 const first=c.designLoad('lab-1'),second=c.designLoad('lab-1');
 await new Promise(r=>setImmediate(r));
 assert.equal(held.length,2,'both loads are in flight');
 const older={intent:{schema:1},generations:[{id:'g-old',status:'succeeded'}],problems:[]};
 const newer={intent:{schema:1},generations:[{id:'g-old',status:'succeeded'},{id:'g-new',status:'succeeded'}],problems:[]};
 held[1](newer);await second;
 let st=vm.runInContext('designState',c);
 assert.equal(st.view.generations.map(g=>g.id).join(','),'g-old,g-new','the newer answer is shown first');
 held[0](older);await first;
 st=vm.runInContext('designState',c);
 assert.equal(st.view.generations.map(g=>g.id).join(','),'g-old,g-new','the late older answer did not paint over it');
 assert.equal(st.loading,false);
 // A later load of the same lab is newer than both and is shown.
 const third=c.designLoad('lab-1');await new Promise(r=>setImmediate(r));held[2]({intent:{schema:1},generations:[],problems:[]});await third;
 assert.equal(vm.runInContext('designState',c).view.generations.length,0,'a genuinely newer answer still wins');
});
test('QA-015: the lab-switch guard still holds with the sequence guard in place',async()=>{
 const held=[];
 const api=async()=>({json:()=>new Promise(resolve=>held.push(resolve))});
 const c=ctx({api});
 const a=c.designLoad('lab-a'),b=c.designLoad('lab-b');
 await new Promise(r=>setImmediate(r));
 held[1]({intent:{schema:1},generations:[{id:'b1',status:'failed'}],problems:[]});await b;
 held[0]({intent:{schema:1},generations:[{id:'a1',status:'failed'}],problems:[]});await a;
 const st=vm.runInContext('designState',c);
 assert.equal(st.labId,'lab-b');assert.equal(st.view.generations[0].id,'b1');
});

// --- U-21: a module the design still needs says why it stays on when unticked ---------------------------------
test('U-21: designKeptModulesNotice names the modules kept on and why, and stays silent otherwise',()=>{
 const c=ctx();
 assert.equal(c.designKeptModulesNotice(['ospf'],['ospf']),'');
 assert.equal(c.designKeptModulesNotice(['ospf'],['ospf','vrf']),'The vrf module stays on while VRFs (or links in a VRF) are defined; remove them to turn it off.');
 assert.equal(c.designKeptModulesNotice([],['vlan','routing']),'The vlan module stays on while VLANs (or links in a VLAN) are defined; remove them to turn it off. The routing module stays on while static routes are defined; remove them to turn it off.');
 assert.equal(c.designKeptModulesNotice(['ospf'],['ospf','bgp']),'','a module the form simply does not list is not "kept": only the three the intent re-adds');
 assert.equal(c.designKeptModulesNotice(undefined,['vrf']),'');
});

// --- task 8: error summary, route-reflector grid markup, Experimental placement ---------------------------
function summaryEls(){
 const els={};
 const el=id=>{if(!els[id])els[id]={id,tagName:'INPUT',value:'',disabled:false,title:'',textContent:'',className:'',hidden:false,checked:false,innerHTML:'',attrs:{},focused:0,scrolled:0,
  setAttribute(n,v){this.attrs[n]=String(v);},getAttribute(n){return n in this.attrs?this.attrs[n]:null;},removeAttribute(n){delete this.attrs[n];},
  focus(){this.focused++;},scrollIntoView(){this.scrolled++;},querySelector:()=>null,querySelectorAll:()=>[]};return els[id];};
 return {els,el};
}
test('8b: a route reflector is a checkbox beside its name in a <span>, inside a grid with its own full-width row',()=>{
 const c=ctx();
 const markup=c.designReflectorMarkup(['r1','a-very-long-router-name-that-keeps-going-and-going'],new Set(['r1']));
 assert.equal((markup.match(/<label class="checkbox-label"><input type="checkbox" name="design-bgp-rr"/g)||[]).length,2);
 assert.match(markup,/><span>r1<\/span><\/label>/);assert.match(markup,/<span>a-very-long-router-name[^<]*<\/span>/);
 assert.match(c.designReflectorMarkup(['<b>'],new Set()),/<span>&lt;b&gt;<\/span>/,'the name is escaped');
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 assert.match(html,/<fieldset class="design-check-list design-rr-fieldset"><legend>Route reflectors<\/legend><div id="design-bgp-rr" class="design-rr-grid">/);
 assert.match(html,/Tick every router that reflects routes; none means a full mesh\./);
 const css=fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8');
 assert.match(css,/\.design-rr-fieldset\s*\{[^}]*flex:\s*1 1 100%/);assert.match(css,/\.design-rr-grid \.checkbox-label span\s*\{[^}]*overflow-wrap:\s*anywhere/);
});
test('8c: paths map to the controls that own them; unmapped paths open the Advanced editor',()=>{
 const c=ctx();const ids=(path,message)=>JSON.parse(JSON.stringify(c.designFieldsFor(path,message))).map(f=>f.id);
 same(ids('bgp.as'),['design-bgp-as']);same(ids('ospf.area'),['design-ospf-area']);same(ids('isis.area'),['design-isis-area']);
 same(ids('addressing.loopback.ipv6','x'),['design-pool-loopback-ipv6']);same(ids('addressing.p2p.ipv6'),['design-pool-p2p-ipv6']);same(ids('addressing.lan.ipv4'),['design-pool-lan-ipv4']);
 same(ids('addressing.p2p.prefix6'),['design-pool-p2p-prefix']);
 same(ids('addressing.lan.ipv6','ipv6 is switched off in this design; remove the prefix or enable the family'),['design-pool-lan-ipv6','design-ipv6'],'the pool the path names first, the family checkbox as the other fix');
 same(ids('nodes.r1.bgp.rr'),['design-bgp-rr']);
 same(ids('vlans.v10.id'),['design-advanced']);same(ids(''),['design-advanced']);
});
test('8c: failures parse to problems: structured list, the "Fix the design first" sentence, or one error item',()=>{
 const c=ctx();const plain=v=>JSON.parse(JSON.stringify(v));
 same(plain(c.designProblemsFromError({message:'Fix the design first: x',problems:[{path:'bgp.as',message:'Set an AS'}]})),{kind:'problems',problems:[{path:'bgp.as',message:'Set an AS'}]});
 same(plain(c.designProblemsFromError(new Error('Fix the design first: bgp.as: Set an AS; addressing.p2p.ipv6: ipv6 is switched off'))),{kind:'problems',problems:[{path:'bgp.as',message:'Set an AS'},{path:'addressing.p2p.ipv6',message:'ipv6 is switched off'}]});
 same(plain(c.designProblemsFromError(new Error('The manager did not respond. Try again.'))),{kind:'error',problems:[{path:'',message:'The manager did not respond. Try again.'}]});
 assert.equal(c.designSummaryTitle('save','problems',2),'Save design failed: 2 problems to fix');
 assert.equal(c.designSummaryTitle('generate','problems',1),'Generate plan failed: 1 problem to fix');
 assert.equal(c.designSummaryTitle('generate','error',1),'Generate plan failed');
 const html=c.designSummaryMarkup({action:'save',kind:'problems',problems:[{path:'bgp.as',message:'Set <an> AS'},{path:'vlans.v1.id',message:'Bad'}]});
 assert.match(html,/<h3 id="design-error-title">Save design failed: 2 problems to fix<\/h3>/);
 assert.match(html,/<strong>BGP AS number<\/strong>: Set &lt;an&gt; AS <button type="button" class="text-button design-error-go" data-design-goto="design-bgp-as">/);
 assert.match(html,/data-design-goto="design-advanced">Open the Advanced JSON editor/);
 const err=c.designSummaryMarkup({action:'generate',kind:'error',problems:[{path:'',message:'Down'}]});
 assert.match(err,/Try again/);assert.doesNotMatch(err,/data-design-goto/);
});
test('8c: a failed save shows one summary with focus and aria-invalid (read once, from the focused summary); a poll render never announces; a good save clears it',async()=>{
 const {els,el}=summaryEls();let validations=0;
 const c=ctx({$:el,setMarkup:(e,html)=>{if(e)e.innerHTML=html;},current:()=>({id:'lab-a',name:'A'}),
  json:async(path,method)=>{if(path.endsWith('/validate')){validations++;return validations===1?{problems:[{path:'bgp.as',message:'Give BGP an AS number.'},{path:'addressing.p2p.ipv6',message:'ipv6 is switched off in this design; remove the prefix or enable the family'}]}:{problems:[]};}
   return {intent:{schema:1,revision:'r2',modules:[]},generations:[],problems:[],nodes:{}};}});
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r1',modules:['bgp']},generations:[],problems:[],nodes:{}};
 el('design-bgp-as').attrs['aria-describedby']='design-bgp-as-help';
 assert.equal(await c.designSave(),false);
 const box=el('design-error-summary');
 assert.equal(box.hidden,false);assert.match(box.innerHTML,/Save design failed: 2 problems to fix/);assert.equal(box.focused,1,'focus moves to the summary');assert.equal(box.scrolled,1);
 assert.equal(el('design-bgp-as').attrs['aria-invalid'],'true');assert.equal(el('design-bgp-as').attrs['aria-describedby'],'design-bgp-as-help design-error-item-0');
 assert.equal(el('design-pool-p2p-ipv6').attrs['aria-invalid'],'true','the pool the path names carries the switched-off problem');
 assert.match(box.innerHTML,/Give BGP an AS number\./,'the first problem is read from the focused summary itself, so there is no second (hidden alert) announcement');
 const announced=box.innerHTML;
 assert.doesNotMatch(el('design-state-text').textContent+el('design-detail').textContent,/Give BGP an AS number/,'the header line does not repeat problems[0]');
 assert.match(el('design-problems').innerHTML,/addressing\.p2p\.ipv6/,'the full list stays as the secondary list');
 const live=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 assert.doesNotMatch(live,/id="design-problems"[^>]*role="alert"/);assert.doesNotMatch(live,/id="design-announce"/,'no hidden duplicate alert next to the focused summary');assert.match(live,/id="design-error-summary"[^>]*role="group"[^>]*aria-labelledby="design-error-title"[^>]*tabindex="-1"/,'the focused summary has an accessible name');
 c.designRenderAll();c.designRenderAll();
 assert.equal(box.innerHTML,announced);assert.equal(box.focused,1,'re-renders and polls never move focus');
 assert.equal(await c.designSave(),true);
 assert.equal(box.hidden,true);assert.equal(box.innerHTML,'');
 assert.equal(el('design-bgp-as').attrs['aria-invalid'],undefined);assert.equal(el('design-bgp-as').attrs['aria-describedby'],'design-bgp-as-help','the original description is restored');
 assert.equal(el('design-pool-p2p-ipv6').attrs['aria-describedby'],undefined);
});
test('8c: Generate without a draft shows the backend 400 problems (structured or sentence) and a lost connection gets Try again',async()=>{
 for(const failure of [Object.assign(new Error('Fix the design first: x'),{status:400,problems:[{path:'ospf.area',message:'Not an area'},{path:'isis.area',message:'Bad area'}]}),
  new Error('Fix the design first: ospf.area: Not an area; isis.area: Bad area')]){
  const {els,el}=summaryEls();
  const c=ctx({$:el,setMarkup:(e,html)=>{if(e)e.innerHTML=html;},current:()=>({id:'lab-a'}),json:async()=>{throw failure;}});
  stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r1',modules:['ospf']},generations:[],problems:[],nodes:{}};
  await c.designGenerate();
  assert.match(el('design-error-summary').innerHTML,/Generate plan failed: 2 problems to fix/);
  assert.match(el('design-error-summary').innerHTML,/data-design-goto="design-ospf-area"/);assert.match(el('design-error-summary').innerHTML,/data-design-goto="design-isis-area"/);
  assert.equal(el('design-ospf-area').attrs['aria-invalid'],'true');
 }
 const {els,el}=summaryEls();
 const c=ctx({$:el,setMarkup:(e,html)=>{if(e)e.innerHTML=html;},current:()=>({id:'lab-a'}),json:async()=>{throw new TypeError('Failed to fetch');}});
 stateOf(c).labId='lab-a';stateOf(c).view={intent:{schema:1,revision:'r1',modules:[]},generations:[],problems:[],nodes:{}};
 await c.designGenerate();
 assert.match(el('design-error-summary').innerHTML,/Generate plan failed<\/h3><ul><li id="design-error-item-0">The manager could not be reached \(network error\)\. Nothing was saved or started\./,'a lost connection is named in plain words, not the browser\'s "Failed to fetch"');assert.match(el('design-error-summary').innerHTML,/<button type="button" class="button secondary" data-design-retry="generate">Try again<\/button>/,'and a real Try again button re-runs Generate');
 assert.equal(el('design-error-summary').focused,1,'the failed Generate moves focus to its summary, which carries the title');
});
test('8f: the design loads only while Advanced is shown with Experimental open, stops its pollers otherwise, and never reads as cancelled',()=>{
 const {els,el}=summaryEls();let loads=0;
 const c=ctx({$:el,current:()=>({id:'lab-a'}),tab:'advanced',api:async()=>{loads++;return {json:async()=>({intent:null,generations:[],nodes:{}})};}});
 const view=()=>vm.runInContext('typeof tab',c);
 vm.runInContext("var tab='advanced'",c);
 c.renderNetworkDesign();assert.equal(loads,0,'closed details: nothing is fetched');
 el('experimental-design').open=true;c.renderNetworkDesign();assert.equal(loads,1,'open details on Advanced: the design loads');
 vm.runInContext("tab='tools'",c);c.renderNetworkDesign();
 assert.equal(c.designVisible(),false);assert.equal(vm.runInContext('designWatch',c),null,'the generation watch is stopped');
 vm.runInContext("tab='advanced'",c);stateOf(c).labId='lab-a';stateOf(c).loading=false;c.renderNetworkDesign();assert.equal(loads,2,'returning reloads (the view may be stale)');
 assert.equal(view(),'string');
 const source=fs.readFileSync(path.join(__dirname,'../app/static/network-design.js'),'utf8');
 assert.doesNotMatch(source,/tab==='design'|tools-design/);
});
test('8f: index.html has no Design tab or Tools card; Network design sits under Advanced › Experimental before the Danger zone, closed, labelled, as a region with a persistent warning',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 assert.doesNotMatch(html,/id="tab-design"|data-tab="design"|id="tools-design"|Design this lab/);
 const at=html.indexOf('id="experimental-design"'),danger=html.indexOf('class="panel danger-zone"'),advanced=html.indexOf('id="advanced-view"'),tools=html.indexOf('id="tools-view"');
 assert.ok(advanced>tools&&at>advanced&&at<danger,'inside Advanced, before the Danger zone');
 assert.match(html,/<details id="experimental-design" class="experimental-details">/,'closed by default');
 assert.match(html,/Experimental <span class="pill warn">Under construction \/ Under review<\/span>/);
 assert.match(html,/<section id="design-view" class="design-region" role="region" aria-labelledby="design-head-title">/);
 assert.doesNotMatch(html,/role="tabpanel" aria-labelledby="tab-design"/);
 assert.match(html,/id="design-experimental-banner" class="banner warn[^"]*"[^>]*><svg[\s\S]*?under construction and under review[^<]*, and it is not part of the supported lab workflow/);
 assert.doesNotMatch(html.slice(html.indexOf('id="design-experimental-banner"'),html.indexOf('id="design-head"')),/dismiss|close/i,'the warning cannot be dismissed');
});
test('8f: an old view=design route resolves to Advanced with Experimental opened, without a Design panel',()=>{
 const elements=new Map();const element=()=>({dataset:{},value:'',innerHTML:'',open:false,hidden:false,disabled:false,listeners:{},classList:{toggle(){}},setAttribute(){},addEventListener(){},scrollIntoView(){this.scrolled=true;}});
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},createElement:element,body:element()};
 const context=vm.createContext({document,sessionStorage:{getItem(){return null;},setItem(){}},setTimeout:()=>0,clearTimeout(){},setInterval(){},URLSearchParams,URL});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8'),context);
 vm.runInContext("PANELS.includes('design')",context);
 assert.equal(vm.runInContext("PANELS.includes('design')",context),false);
 vm.runInContext("setTab('design')",context);
 assert.equal(vm.runInContext('tab',context),'advanced');assert.equal(vm.runInContext('scrollTarget',context),'experimental-design');
 vm.runInContext("activeId='lab';state={labs:[{id:'lab',name:'L',nodes:[],profiles:[],defaults:{}}],jobs:[],platforms:{}};showTab('design')",context);
 assert.equal(document.getElementById('experimental-design').open,true,'the Experimental details is opened');
 assert.equal(document.getElementById('experimental-design').scrolled,true,'and scrolled into view');
 assert.equal(document.getElementById('design-view').hidden,false,'showTab does not toggle the region as a panel');
 assert.equal(vm.runInContext('tab',context),'advanced');
});

// --- 8a/8d: retired modules; 8e: the device review as a job ----------------------------------------------
const RETIRED_VIEW={retired:{eigrp:'EIGRP is retired.',ripv2:'RIP is retired.',vxlan:'VXLAN is retired.',evpn:'EVPN is under review.'},
 retired_status:{eigrp:'retired',ripv2:'retired',vxlan:'retired',evpn:'under_review'},retired_labels:{eigrp:'EIGRP',ripv2:'RIP',vxlan:'VXLAN',evpn:'EVPN'}};
test('8a: a retired module the design carries is a read-only "No longer offered" row with its reason and a Remove button; it is never offered',()=>{
 const c=ctx();const info=c.designRetiredInfo(RETIRED_VIEW);
 const html=c.designModulesMarkup(['ospf','bgp','vxlan'],['ospf','eigrp','evpn'],info);
 assert.equal((html.match(/name="design-module" value=/g)||[]).length,2,'the retired id in the offered list is not a choice');
 assert.doesNotMatch(html,/value="vxlan"/);
 assert.match(html,/name="design-module-retired" value="eigrp" checked disabled/);
 assert.match(html,/<span class="pill warn">No longer offered<\/span>/);assert.match(html,/Unavailable — under review/,'EVPN reads as under review');
 assert.match(html,/EIGRP is retired\./);assert.match(html,/data-design-retire-remove="eigrp"[^>]*>Remove from design/);
 assert.doesNotMatch(c.designModulesMarkup(['ospf'],['ospf'],info),/design-retired-row/,'no row when the design does not use one');
 assert.match(c.designModulesMarkup([],['eigrp'],c.designRetiredInfo({retired:{eigrp:'<b>x</b>'},retired_labels:{eigrp:'EIGRP'}})),/&lt;b&gt;x&lt;\/b&gt;/,'the reason is escaped');
 assert.equal(c.designModulesMarkup(['ospf'],['ospf']).includes('checkbox'),true,'no retired info: plain list as before');
 const notice=c.designRetiredNoticeMarkup({...RETIRED_VIEW,retired_in_design:[{path:'modules',module:'vxlan',message:'VXLAN is retired.'},{path:'links.a.vxlan',module:'vxlan',message:'x'}]});
 assert.match(notice,/This design still uses VXLAN\./);assert.match(notice,/<code>links\.a\.vxlan<\/code>/);assert.equal(c.designRetiredNoticeMarkup({retired_in_design:[]}),'');
});
test('8a: designIntentFromForm keeps a retired module the base already has, unless the student removed it',()=>{
 const c=ctx();const base={schema:1,modules:['ospf','vxlan'],links:{a:{vxlan:{vni:1}}}};
 const keep=c.designIntentFromForm({modules:['ospf'],retiredKnown:['vxlan','eigrp']},base);
 same(keep.modules,['ospf','vxlan']);assert.equal(keep.links.a.vxlan.vni,1);
 same(c.designIntentFromForm({modules:['ospf'],retiredKnown:['vxlan'],retiredRemoved:['vxlan']},base).modules,['ospf']);
 same(c.designIntentFromForm({modules:['ospf','bgp'],retiredKnown:[]},{schema:1,modules:['ospf']}).modules,['ospf','bgp'],'a retired id is only kept when the view names it retired');
 same(c.designIntentFromForm({modules:['ospf']},base).modules,['ospf'],'without retired info nothing is invented');
});
test('8a: removing a retired row drops the module from the draft',()=>{
 const {els,el}=summaryEls();const notes=[];
 const c=ctx({$:el,notify:m=>notes.push(m),setMarkup:(e,h)=>{if(e)e.innerHTML=h;},current:()=>({id:'lab-a'})});
 stateOf(c).labId='lab-a';stateOf(c).view={...RETIRED_VIEW,intent:{schema:1,revision:'r',modules:['ospf','eigrp']},generations:[],problems:[],nodes:{},modules:['ospf']};
 c.designRemoveRetired('eigrp');
 same(stateOf(c).draft.intent.modules,['ospf']);assert.match(notes[0],/Save the design/);
});
test('8a/8d: retired is worded, never "not supported"; an old plan row is checked against retired; Generate and Apply say why',()=>{
 const c=ctx();const info=c.designRetiredInfo(RETIRED_VIEW);
 assert.equal(c.designLevelWord('retired','r','retired'),'No longer offered');assert.equal(c.designLevelWord('retired','r','under_review'),'Under review');
 assert.equal(vm.runInContext('DESIGN_LEVEL_CLASS.retired',c),'warn');
 same(JSON.parse(JSON.stringify(c.designRowLevel({feature:'ripng',level:'verified_on_image'},info))),{level:'retired',policy:'retired'});
 same(JSON.parse(JSON.stringify(c.designRowLevel({feature:'evpn',level:'unsupported'},info))),{level:'retired',policy:'under_review'});
 same(JSON.parse(JSON.stringify(c.designRowLevel({feature:'ospf',level:'verified_on_image'},info))),{level:'verified_on_image',policy:''});
 const plan={compatibility:{r1:[{feature:'ospf',level:'verified_on_image'},{feature:'evpn',level:'unsupported',engine_level:'unsupported'},{feature:'ripng',level:'retired',policy:'retired'}]}};
 const html=c.designCompatibilityMarkup(plan,info);
 assert.match(html,/Under review/);assert.match(html,/No longer offered/);assert.doesNotMatch(html,/Not supported/);
 same(c.designPlanRetired({modules:['ospf','vxlan'],compatibility:{r1:[{feature:'ripng'}]}},info),['ripv2','vxlan']);
 const view={...RETIRED_VIEW,generations:[{id:'g',status:'succeeded',modules:['ospf','vxlan']}],summary:{}};
 const why=c.designApplyDisabledReason({deployment:{status:'Running'}},view,[]);
 assert.match(why,/This plan uses VXLAN, which is no longer offered, so it cannot be applied to devices/);
 assert.doesNotMatch(c.designApplyDisabledReason({deployment:{status:'Running'}},{...view,generations:[{id:'g',status:'succeeded',modules:['ospf']}]},[]),/no longer offered/);
 const {els,el}=summaryEls();
 const h=ctx({$:el,menuReason:()=>{}});
 h.designRenderHeader({},{intent:{schema:1},generations:[],problems:[],engine:{available:true},retired_in_design:[{path:'modules',module:'vxlan',message:'m'}]});
 assert.equal(el('design-generate').disabled,true);assert.match(el('design-generate').title,/no longer offered/);
});
test('8a: a Save/Import 400 or Generate 409 with {message,problems,retired} shows the sentence and the problems in the summary',()=>{
 const c=ctx();const plain=v=>JSON.parse(JSON.stringify(v));
 const err=Object.assign(new Error('RIP is no longer offered, so it cannot be added.'),{status:400,retired:['ripv2'],problems:[{path:'modules',message:'RIP is no longer offered'}]});
 const parsed=plain(c.designProblemsFromError(err));
 assert.equal(parsed.kind,'problems');assert.equal(parsed.lead,'RIP is no longer offered, so it cannot be added.');assert.equal(parsed.problems[0].path,'modules');
 const html=c.designSummaryMarkup({action:'save',kind:'problems',problems:parsed.problems,lead:parsed.lead,links:true});
 assert.match(html,/<p class="design-error-lead">RIP is no longer offered, so it cannot be added\.<\/p>/);assert.match(html,/data-design-goto="design-modules"/);
 const only=plain(c.designProblemsFromError(Object.assign(new Error('This design uses VXLAN.'),{status:409,retired:['vxlan']})));
 same(only.problems,[{path:'',message:'This design uses VXLAN.'}]);
 assert.equal(plain(c.designProblemsFromError(new Error('plain'))).lead,undefined,'no lead without retired');
});
function reviewJob(over){
 return {id:'j1',lab_id:'lab-a',generation_id:'g1',status:'running',started:'2026-10-03T10:00:00Z',finished:null,server_time:Date.parse('2026-10-03T10:00:23Z')/1000,
  progress:{settled:0,total:2},targets:[{name:'ceos',kind:'arista_ceos',stage:'connecting',timeline:{queued:1791021600,connecting:1791021610}},
  {name:'xr',kind:'cisco_xrv9k',stage:'queued',timeline:{queued:1791021600}}],...over};
}
test('8e: stage words, clocks and the overall line come from the contract and the server clock',()=>{
 const c=ctx();const job=reviewJob({server_time:1791021623});
 assert.equal(c.designReviewStageWord('staging'),'Trying the change (nothing is committed)…');assert.equal(c.designReviewStageWord('unreachable'),'Could not be reached');
 assert.equal(c.designReviewClock(83),'1:23');assert.equal(c.designReviewClock(-4),'0:00');
 assert.equal(c.designReviewOverall(job),'Reviewing 2 devices · 0:23');
 assert.equal(c.designReviewOverall({...job,status:'interrupted'}),'The review was interrupted. Review again.');
 assert.match(c.designReviewOverall({...job,status:'failed',message:'VM connection changed.'}),/The review could not finish: VM connection changed\. Review again\./);
 assert.equal(c.designReviewOverall({...job,status:'done',finished:'2026-10-03T10:00:31Z'}),'Review finished · 0:31');
 const row=c.designReviewRowMarkup({name:'xr',kind:'k',stage:'unreachable',message:'The device could not be reached over SSH.',timeline:{queued:5,settled:9}},job);
 assert.match(row,/Could not be reached/);assert.match(row,/The device could not be reached over SSH\./);assert.match(row,/0:04/);
 assert.match(c.designReviewRowMarkup(job.targets[0],job),/Connecting…/);assert.match(c.designReviewRowMarkup(job.targets[0],job),/0:13/,'elapsed in the current stage');
 assert.match(c.designReviewMarkup({targets:[{name:'<x>',stage:'queued',timeline:{}}]}),/&lt;x&gt;/);
});
test('8e: the live region announces stage changes and the final result, not every poll',()=>{
 const c=ctx();const first=reviewJob();const prev=c.designReviewStages(first);
 assert.equal(c.designReviewAnnouncement(first,prev),'','an unchanged poll says nothing');
 const next=reviewJob({targets:[{...first.targets[0],stage:'reading_config'},first.targets[1]]});
 assert.equal(c.designReviewAnnouncement(next,prev),'ceos: Reading the current configuration…');
 assert.match(c.designReviewAnnouncement({...next,status:'done',finished:'2026-10-03T10:00:40Z'},prev),/^Review finished/);
 assert.equal(c.designReviewAnnouncement(first,{}),'','the first sight of a device is not announced');
});
function reviewHarness(opts){
 opts=opts||{};
 const {els,el}=summaryEls();const timers=[];const calls=[];let seqNo=0;
 const replies=opts.replies||[];
 const c=ctx({$:el,setMarkup:(e,h)=>{if(e)e.innerHTML=h;},current:()=>({id:'lab-a',name:'A'}),
  setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:id=>{if(id)timers[id-1]=null;},
  json:async(path,method,body)=>{calls.push(['json',path,method,body]);const r=opts.post?await opts.post(body,calls):{review_job:reviewJob()};return r;},
  api:async path=>{calls.push(['api',path]);const r=await opts.get(path,calls);return {json:async()=>r};}});
 c.document.querySelectorAll=sel=>sel==='[name="design-apply-target"]:checked'?[{value:'ceos'},{value:'xr'}]:[];
 vm.runInContext("designApplyState.labId='lab-a';designApplyState.generationId='g1'",c);
 const tick=async()=>{const fn=timers.shift();if(fn)await fn();else await new Promise(r=>setImmediate(r));};
 return {c,els,el,timers,calls,tick};
}
test('8e: Review starts a job, shows the live log, follows it every ~1.5 s and hands job.review to the review step once done',async()=>{
 const stages=['connecting','reading_config','staging','done'];let n=0;
 const review={token:'tok',expires_in:600,generation_id:'g1',applicable:['ceos'],takeover:[],targets:[{name:'ceos',kind:'arista_ceos',eligible:true,reachable:true,ready:true,no_op:true,counts:{},compatibility:[]}]};
 const h=reviewHarness({get:async path=>{n++;const done=n>=3;return reviewJob({status:done?'done':'running',targets:[{name:'ceos',kind:'arista_ceos',stage:done?'done':stages[n],timeline:{queued:1791021600,settled:done?1791021620:undefined}}],review:done?review:undefined});}});
 await h.c.designApplyRunReview();
 const post=h.calls.find(x=>x[0]==='json');
 assert.match(post[1],/\/design\/generations\/g1\/review$/);assert.match(post[3].request_id,/^[0-9a-f]{32}$/);same(post[3].targets,['ceos','xr']);
 assert.equal(h.el('design-apply-reviewing-step').hidden,false,'the live log step is shown');
 assert.equal(h.el('design-apply-review-run').disabled,true);assert.match(h.el('design-apply-review-run').textContent,/Reviewing 2 devices…/);
 assert.match(h.el('design-review-overall').textContent,/^Reviewing 2 devices · 0:23/);assert.match(h.el('design-review-body').innerHTML,/Connecting…/);
 await h.tick();assert.match(h.el('design-review-body').innerHTML,/Reading the current configuration…/);
 assert.match(h.el('design-review-live').textContent,/ceos: Reading the current configuration…/);
 await h.tick();await h.tick();
 assert.equal(stateOf(h.c).labId,'','designState untouched');
 assert.equal(vm.runInContext('designApplyState.review.token',h.c),'tok','job.review is the review, token included');
 assert.equal(h.el('design-apply-review-step').hidden,false);assert.equal(h.el('design-apply-reviewing-step').hidden,true);
 assert.equal(h.el('design-apply-review-run').disabled,false,'the button is free again once the job settled');
 assert.doesNotMatch(h.el('design-review-body').innerHTML+h.el('design-review-overall').textContent+h.el('design-review-error').textContent,/cancel/i);
});
test('8e: a request id is fresh per click, and reused only to retry a lost answer',async()=>{
 let fail=true;const bodies=[];
 const h=reviewHarness({post:async body=>{bodies.push(body.request_id);if(fail&&bodies.length<=2)throw new TypeError('Failed to fetch');return {review_job:reviewJob({status:'failed',message:'x'})};},get:async()=>reviewJob()});
 await h.c.designApplyRunReview();assert.equal(h.el('design-apply-choose-error').textContent,'Failed to fetch');assert.equal(h.el('design-apply-review-run').disabled,false,'a failed start frees the button');
 await h.c.designApplyRunReview();
 assert.equal(bodies[0],bodies[1],'the retry after a lost answer reuses the id');
 fail=false;await h.c.designApplyRunReview();await h.c.designApplyRunReview();
 assert.equal(bodies[2],bodies[1],'a third attempt after another lost answer still retries the same request');
 assert.notEqual(bodies[3],bodies[2],'a fresh click after an answer is a new request');
});
test('8e: a 409 with review_job_id attaches to that job instead of starting another',async()=>{
 const h=reviewHarness({post:async()=>{throw Object.assign(new Error('A review of this lab is already running.'),{status:409,review_job_id:'jobX'});},get:async path=>reviewJob({id:'jobX'})});
 await h.c.designApplyRunReview();
 assert.equal(vm.runInContext('designApplyState.reviewJobId',h.c),'jobX');assert.equal(h.calls.filter(x=>x[0]==='json').length,1);
 assert.ok(h.calls.some(x=>x[0]==='api'&&/review-jobs\/jobX$/.test(x[1])));assert.equal(h.el('design-apply-reviewing-step').hidden,false);
});
test('8e: failed, interrupted, unreachable devices and a 404 read truthfully, with Review again',async()=>{
 const failedDevice=reviewJob({status:'done',finished:'2026-10-03T10:00:30Z',review:{token:'t',applicable:[],targets:[]},targets:[{name:'ceos',kind:'k',stage:'unreachable',message:'The device could not be reached over SSH.',timeline:{queued:1,settled:4}},{name:'xr',kind:'k',stage:'failed',message:'The device did not finish the review in time.',reason_code:'timeout',timeline:{queued:1,settled:540}}]});
 const a=reviewHarness({get:async()=>failedDevice,post:async()=>({review_job:reviewJob()})});
 await a.c.designApplyRunReview();await a.tick();
 assert.match(a.el('design-review-body').innerHTML+a.el('design-apply-review-body').innerHTML,/could not be reached over SSH/);
 const b=reviewHarness({post:async()=>({review_job:reviewJob()}),get:async()=>reviewJob({status:'interrupted'})});
 await b.c.designApplyRunReview();await b.tick();
 assert.equal(b.el('design-review-overall').textContent,'The review was interrupted. Review again.');assert.equal(b.el('design-review-again').hidden,false);assert.equal(b.el('design-apply-review-run').disabled,false);
 const c2=reviewHarness({post:async()=>({review_job:reviewJob()}),get:async()=>{throw Object.assign(new Error('gone'),{status:404});}});
 await c2.c.designApplyRunReview();await c2.tick();
 assert.equal(c2.el('design-review-error').textContent,'The review is no longer available; review again.');assert.equal(c2.el('design-review-again').hidden,false);
 assert.equal(c2.el('design-apply-review-run').disabled,false);
});
test('8e: closing the dialog stops following without saying cancelled; the plan card shows the running review and Show reattaches; a late answer never lands in another dialog',async()=>{
 let release;const gate=new Promise(r=>{release=r;});
 const h=reviewHarness({post:async()=>({review_job:reviewJob()}),get:async path=>{await gate;return reviewJob();}});
 await h.c.designApplyRunReview();
 assert.equal(h.el('design-review-running').hidden,false);assert.match(h.el('design-review-running').innerHTML,/Review running… <button[^>]*data-design-review-show="j1"/);
 const pending=h.tick();            // a poll is in flight
 h.c.designApplyClose();            // the dialog closes: following stops, a quiet watch keeps the plan card honest
 vm.runInContext("designApplyState.labId='lab-b';designApplyState.reviewJobId='other'",h.c);   // a different dialog opens
 release();await pending;
 assert.equal(vm.runInContext('designApplyState.reviewJob===null||designApplyState.reviewJob.id==="j1"',h.c),true);
 assert.doesNotMatch(h.el('design-review-overall').textContent+h.el('design-review-error').textContent+h.el('design-review-running').innerHTML,/cancel/i);
 assert.equal(vm.runInContext('designApplyState.reviewJobId',h.c),'other','the late answer did not touch the other dialog');
 const src=fs.readFileSync(path.join(__dirname,'../app/static/network-design.js'),'utf8');
 assert.doesNotMatch(src.slice(src.indexOf('const DESIGN_REVIEW_STAGE_WORDS'),src.indexOf('function designApplyRequestId')),/cancel/i);
});
test('8e: after a reload a running review is found on the plan card, and reopening Apply attaches to it',async()=>{
 const h=reviewHarness({get:async path=>/review-jobs$/.test(path)?[reviewJob()]:reviewJob()});
 vm.runInContext("designState.labId='lab-a'",h.c);
 await h.c.designReviewDiscover('lab-a');
 assert.equal(h.el('design-review-running').hidden,false);
 assert.ok(h.timers.length>=1,'a quiet watch follows it with the dialog closed');
 await h.c.designReviewReattach('lab-a','j1');
 assert.equal(vm.runInContext('designApplyState.reviewJobId',h.c),'j1');assert.equal(h.el('design-apply-reviewing-step').hidden,false);
});
const doneReview=()=>({token:'tok',expires_in:600,generation_id:'g1',applicable:['ceos'],takeover:[],targets:[{name:'ceos',kind:'arista_ceos',eligible:true,reachable:true,ready:true,no_op:true,counts:{},compatibility:[]}]});
const doneJob=(over)=>reviewJob({status:'done',finished:new Date().toISOString(),targets:[{name:'ceos',kind:'arista_ceos',stage:'done',timeline:{queued:1,settled:2}}],review:doneReview(),...over});
test('8e: a review that finishes while the dialog is closed is kept: the card says "Review finished — Show" while its token is valid, Show re-attaches and hands over the review; after expiry it disappears and reopening starts fresh',async()=>{
 const h=reviewHarness({post:async()=>({review_job:reviewJob()}),get:async()=>reviewJob()});
 await h.c.designApplyRunReview();
 h.c.designApplyClose();                                   // closed while it runs: a quiet watch follows it
 h.get=null;
 // the quiet poll now sees it done (another answer for the same job)
 const h2=reviewHarness({get:async path=>/review-jobs$/.test(path)?[{...doneJob(),review:undefined}]:doneJob()});
 vm.runInContext("designState.labId='lab-a'",h2.c);
 await h2.c.designReviewDiscover('lab-a');
 assert.equal(h2.el('design-review-running').hidden,false);assert.match(h2.el('design-review-running').innerHTML,/^Review finished — <button[^>]*data-design-review-show="j1"/);
 assert.equal(h2.timers.length>=1,true,'an expiry timer removes the line when the token runs out');
 assert.equal(h2.timers.some(f=>f)&&vm.runInContext("designReviewKnown.status",h2.c),'done');
 // reopening Apply attaches to the done job: GET returns the review, the review step shows
 vm.runInContext("designApplyState.reviewJobId=''",h2.c);
 await h2.c.designReviewReattach('lab-a','j1');
 assert.equal(h2.el('design-apply-review-step').hidden,false,'the review (with its token) is handed to the review step');
 assert.equal(vm.runInContext('designApplyState.review.token',h2.c),'tok');
 // after expiry the line is gone and nothing is attached
 vm.runInContext("designReviewKnown.until=Date.now()-1",h2.c);h2.c.designReviewRenderRunning('lab-a');
 assert.equal(h2.el('design-review-running').hidden,true);assert.equal(vm.runInContext("designReviewKnown.status",h2.c),'');
 // a list without a done job (expired on the server) forgets nothing it never knew, and a failed job offers no token
 const h3=reviewHarness({get:async path=>/review-jobs$/.test(path)?[reviewJob({status:'failed'})]:reviewJob({status:'failed'})});
 vm.runInContext("designState.labId='lab-a'",h3.c);await h3.c.designReviewDiscover('lab-a');
 assert.equal(vm.runInContext('designReviewKnown.status',h3.c),'','failed and interrupted jobs have no token and are not offered');
});
test('8e: a quiet poll that sees the job finish turns the running line into the finished line; submitting an apply consumes the review and clears the line',async()=>{
 let call=0;
 const h=reviewHarness({post:async()=>({review_job:reviewJob()}),get:async()=>{call++;return call<1?reviewJob():doneJob();}});
 await h.c.designApplyRunReview();
 h.c.designApplyClose();
 assert.match(h.el('design-review-running').innerHTML,/^Review running… /);
 await h.tick();await h.tick();
 assert.match(h.el('design-review-running').innerHTML,/^Review finished — <button/);
 vm.runInContext("designReviewForget()",h.c);h.c.designReviewRenderRunning('lab-a');
 assert.equal(h.el('design-review-running').hidden,true);
});
test('8e: aria-busy sits on the Review button only (never on the dialog, which would hold back its live log), and Review again returns focus to Review',async()=>{
 const h=reviewHarness({post:async()=>({review_job:reviewJob()}),get:async()=>reviewJob({status:'interrupted'})});
 for(const id of ['design-apply-last','design-apply-dialog','design-apply-review-body','design-apply-ack','design-advanced-details','design-review-running'])h.el(id).addEventListener=()=>{};
 h.c.initDesignApply();
 await h.c.designApplyRunReview();
 assert.equal(h.el('design-apply-review-run').attrs['aria-busy'],'true');assert.equal(h.el('design-apply-dialog').attrs['aria-busy'],undefined);
 await h.tick();
 assert.equal(h.el('design-apply-review-run').attrs['aria-busy'],undefined,'idle again: no aria-busy anywhere');
 h.el('design-apply-review-run').focused=0;
 h.el('design-review-again').onclick();
 assert.equal(h.el('design-apply-choose-step').hidden,false);assert.equal(h.el('design-apply-review-run').focused,1,'focus lands on Review after Review again');
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 assert.match(html,/id="design-review-close-note">[^<]*finished review stays available for 10 minutes/,'the note says how long a finished review is kept');
});
test('8e/8a: api() keeps problems, retired and review_job_id from an object detail and shows its message',async()=>{
 const context=vm.createContext({document:{getElementById:()=>({dataset:{},listeners:{},classList:{toggle(){}},addEventListener(){},setAttribute(){},scrollIntoView(){}}),querySelectorAll:()=>[],createElement:()=>({dataset:{},addEventListener(){},setAttribute(){}}),body:{}},fetch:async()=>({ok:false,status:409,json:async()=>({detail:{message:'A review is running.',review_job_id:'abc',problems:[{path:'p',message:'m'}],retired:['vxlan']}})}),URLSearchParams,URL,sessionStorage:{getItem(){return null;},setItem(){}},setTimeout:()=>0,clearTimeout(){},setInterval(){}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8'),context);
 const error=await vm.runInContext("api('/x').then(()=>null,e=>e)",context);
 assert.equal(error.message,'A review is running.');assert.equal(error.review_job_id,'abc');assert.equal(error.status,409);
 assert.equal(error.problems[0].path,'p');assert.equal(error.retired[0],'vxlan');
});

test('8c: a validation problem offers no Try again button (correct the fields instead); a server error does',()=>{
 const c=ctx({});
 const html=c.designSummaryMarkup({action:'save',kind:'problems',problems:[{path:'bgp.as',message:'Enter the BGP AS number'}],links:true});
 assert.doesNotMatch(html,/data-design-retry/);
 assert.match(c.designSummaryMarkup({action:'save',kind:'error',problems:[{path:'',message:'boom'}]}),/data-design-retry="save">Try again/);
 assert.doesNotMatch(c.designSummaryMarkup({action:'import',kind:'error',problems:[{path:'',message:'boom'}]}),/data-design-retry/,'an import is retried by choosing the file again');
});
test('8c: an IPv4-only design leaves blank IPv6 pools out, so the "remove the prefix or enable the family" advice can be followed',()=>{
 const c=ctx({});
 const blank={loopback:{ipv4:'10.255.0.0/24',ipv6:''},p2p:{ipv4:'10.1.0.0/16',ipv6:'',prefix:'31'},lan:{ipv4:'172.16.0.0/16',ipv6:'',prefix:'24'}};
 const off=JSON.parse(JSON.stringify(c.designIntentFromForm({ipv4:true,ipv6:false,pools:blank,modules:[],devices:[]},null)));
 for(const pool of ['loopback','p2p','lan'])assert.equal('ipv6' in off.addressing[pool],false,pool+': blank ipv6 with IPv6 off is left out');
 assert.equal(off.addressing.loopback.ipv4,'10.255.0.0/24');
 const on=JSON.parse(JSON.stringify(c.designIntentFromForm({ipv4:true,ipv6:true,pools:blank,modules:[],devices:[]},null)));
 assert.equal(on.addressing.loopback.ipv6,'','IPv6 on: a blank pool is still sent so the server names it');
 const kept=JSON.parse(JSON.stringify(c.designIntentFromForm({ipv4:true,ipv6:false,pools:{...blank,loopback:{ipv4:'10.255.0.0/24',ipv6:'2001:db8:ff::/48'}},modules:[],devices:[]},null)));
 assert.equal(kept.addressing.loopback.ipv6,'2001:db8:ff::/48','a typed prefix is never dropped silently (the server explains the conflict)');
});

// --- audit 2026-10-03 frontend-editor/a: M-16, L-35, L-36 ----------------------------------------------
test('M-16: View on a file of an earlier plan opens that plan\'s file, labelled from that plan, not the newest plan\'s',async()=>{
 const {el}=summaryEls();const paths=[],dialogs=[],notes=[];
 const c=ctx({$:el,setMarkup:(e,h)=>{if(e)e.innerHTML=h;},current:()=>({id:'lab-a',name:'A'}),notify:m=>notes.push(m),
  api:async p=>{paths.push(p);return {json:async()=>({plan:null}),text:async()=>'config of '+p};},
  opDialog:(id,title,body)=>{dialogs.push({id,title,body});return {querySelectorAll:()=>[]};}});
 stateOf(c).labId='lab-a';
 stateOf(c).view={intent:{schema:1,revision:'r'},problems:[],nodes:{},generations:[
  {id:'g1',status:'succeeded',artifacts:{r1:[{module:'ospf',size:10}]}},
  {id:'g2',status:'succeeded',artifacts:{r1:[{module:'bgp',size:10}]}}]};
 stateOf(c).viewing='g1';
 // The row remembers the plan it was drawn for, so a later change of the shown plan cannot redirect it.
 c.designRenderFiles(stateOf(c).view);
 const markup=el('design-files-body').innerHTML;
 assert.match(markup,/data-design-view-file="r1"/);assert.match(markup,/data-design-view-generation="g1"/);assert.doesNotMatch(markup,/data-design-view-generation="g2"/);
 await c.designViewFile('r1',0,'g1');
 assert.equal(paths.length,1);assert.match(paths[0],/\/design\/generations\/g1\/artifacts\/r1\/0$/,'the URL names the plan the row was rendered for');
 assert.equal(dialogs[0].title,'ospf · r1','the title and module label come from that plan');
 // The same button after the student went back to the newest plan in the meantime still means g1.
 stateOf(c).viewing=null;paths.length=0;await c.designViewFile('r1',0,'g1');
 assert.match(paths[0],/\/g1\//);
 // Without an id (an older caller) the plan being shown wins, never blindly the newest.
 stateOf(c).viewing='g1';paths.length=0;dialogs.length=0;await c.designViewFile('r1',0);
 assert.match(paths[0],/\/g1\//);assert.equal(dialogs[0].title,'ospf · r1');
 assert.equal(notes.length,0);
});
test('M-16: the Files list click handler passes the plan id of the row to designViewFile',()=>{
 assert.match(source,/designViewFile\(b\.dataset\.designViewFile,Number\(b\.dataset\.designViewIndex\),b\.dataset\.designViewGeneration\)/);
});

function applyFollowHarness(opts){
 opts=opts||{};
 const {els,el}=summaryEls();const timers=[],calls=[];let fail=opts.fail!==false;let jobStatus=opts.status||'applying';let refreshes=0;
 const c=ctx({$:el,setMarkup:(e,h)=>{if(e)e.innerHTML=h;},current:()=>({id:'lab-a',name:'A'}),
  setTimeout:(fn,ms)=>{const n=timers.length;timers.push({fn:async()=>{timers[n]=null;return fn();},ms});return timers.length;},clearTimeout:id=>{if(!opts.keepTimers&&id&&timers[id-1])timers[id-1]=null;},
  api:async p=>{calls.push(p);if(opts.hold&&/\/design\/apply\/jobs\//.test(p))await opts.hold();if(fail)throw new Error('HTTP 500');return {json:async()=>({id:'j1',lab_id:'lab-a',status:jobStatus,targets:[]})};},
  refresh:async()=>{refreshes++;}});
 c.state.design_jobs=[{id:'j1',lab_id:'lab-a',status:'applying',created:'2026-10-03T10:00:00Z'}];
 vm.runInContext("designApplyState.labId='lab-a';designApplyState.jobId='j1';designApplyState.step='progress';designApplyState.job={id:'j1',lab_id:'lab-a',status:'applying',targets:[]}",c);
 const last=()=>{for(let i=timers.length-1;i>=0;i--)if(timers[i])return timers[i];return null;};
 return {c,els,el,timers,calls,last,setFail:v=>{fail=v;},setStatus:s=>{jobStatus=s;},refreshes:()=>refreshes};
}
test('L-35: one failed poll does not freeze the Apply dialog: it is retried, said so, and a recovered poll continues',async()=>{
 const h=applyFollowHarness();
 h.c.designApplyStartWatch('j1');
 await h.last().fn();
 const body=h.el('design-apply-progress-body').innerHTML;
 assert.match(body,/attempt 1 of 5/);assert.match(body,/HTTP 500/);assert.match(body,/role="alert"/);
 assert.ok(h.last(),'another poll is scheduled');assert.equal(h.last().ms,2000);
 h.setFail(false);h.setStatus('done');
 await h.last().fn();
 assert.doesNotMatch(h.el('design-apply-progress-body').innerHTML,/attempt|no longer being followed/,'a recovered poll clears the line');
 assert.ok(h.refreshes()>=1,'a finished job refreshes the state');
});
test('L-35: after the bounded retries the dialog says following stopped and offers Check again, which really polls again',async()=>{
 const h=applyFollowHarness();
 h.c.designApplyStartWatch('j1');
 for(let i=0;i<5;i++)await h.last().fn();
 assert.match(h.el('design-apply-progress-body').innerHTML,/attempt 5 of 5/);
 await h.last().fn();
 const body=h.el('design-apply-progress-body').innerHTML;
 assert.match(body,/no longer being followed/i);assert.match(body,/data-design-apply-follow-retry/);assert.match(body,/Check again/);
 assert.equal(h.last(),null,'no endless polling behind the student\'s back');
 assert.ok(h.refreshes()>=1,'giving up still refreshes the state (the plan card\'s Last apply line)');
 const before=h.calls.length;
 h.setFail(false);h.setStatus('applying');
 h.c.designApplyFollowRetry();
 assert.ok(h.last(),'Check again restarts the watch');
 await h.last().fn();
 assert.equal(h.calls.length,before+1,'and polls');
 assert.doesNotMatch(h.el('design-apply-progress-body').innerHTML,/no longer being followed|data-design-apply-follow-retry/);
});
test('L-35: a closed dialog does not retry a failing poll',async()=>{
 // The guard under test is the one in the catch: a request already in flight when the dialog closes
 // and then fails must neither schedule another poll nor write an "attempt" line.
 let rejectRequest;const pending=new Promise((_,rej)=>{rejectRequest=rej;});
 const h=applyFollowHarness({fail:false,hold:()=>pending});
 h.c.designApplyStartWatch('j1');
 const first=h.timers[0];assert.ok(first,'the first poll is scheduled');
 const running=first.fn();                              // the poll starts: its request is now pending
 assert.equal(h.calls.length,1,'the request is in flight');
 h.c.designApplyStopWatch();                            // the dialog closes while it is pending
 const timersBefore=h.timers.length;
 rejectRequest(new Error('HTTP 500'));
 await running;
 assert.equal(h.timers.length,timersBefore,'no new timer is scheduled by the failed in-flight poll');
 assert.equal(h.last(),null);
 assert.doesNotMatch(h.el('design-apply-progress-body').innerHTML,/attempt/,'and no attempt line is written for a closed dialog');
 assert.equal(h.calls.length,1,'and nothing polls again');
});
test('L-35: closing the dialog before the first poll sends no request, even if the timer cannot be cancelled (the guard at the top of the poll)',async()=>{
 const h=applyFollowHarness({keepTimers:true});
 h.c.designApplyStartWatch('j1');
 const t=h.timers[0];assert.ok(t,'the first poll is scheduled');
 h.c.designApplyStopWatch();
 await t.fn();                                          // the timer fires anyway
 assert.equal(h.calls.length,0,'a closed dialog sends no poll');
 assert.equal(h.last(),null,'and schedules nothing');
});
test('L-35: giving up also reloads the ownership list, so it is not left stale until a later successful poll',async()=>{
 const h=applyFollowHarness();
 h.c.designApplyStartWatch('j1');
 for(let i=0;i<6;i++)await h.last().fn();
 assert.match(h.el('design-apply-progress-body').innerHTML,/no longer being followed/i);
 assert.ok(h.calls.some(p=>/\/labs\/lab-a\/design\/ownership$/.test(p)),'the ownership list is requested when following gives up');
});
test('L-35: the give-up line does not claim the apply is still running (after a manager restart it is "interrupted"), and points at Check again and Last apply',async()=>{
 const h=applyFollowHarness();
 h.c.designApplyStartWatch('j1');
 for(let i=0;i<6;i++)await h.last().fn();
 const body=h.el('design-apply-progress-body').innerHTML;
 assert.doesNotMatch(body,/keeps running|still running/i);
 assert.match(body,/real state is on the manager/i);assert.match(body,/Check again/);assert.match(body,/Last apply line under Generated plan/);assert.doesNotMatch(body,/plan card/i);
});

test('L-36: a failed plan fetch for a succeeded plan is worded as a failure with Try again, never as "Generate a plan"',async()=>{
 const {el}=summaryEls();let fail=true;let answer={plan:{devices:[{name:'r1'}],links:[]}};const paths=[];
 const c=ctx({$:el,setMarkup:(e,h)=>{if(e)e.innerHTML=h;},current:()=>({id:'lab-a',name:'A'}),
  api:async p=>{paths.push(p);if(fail)throw new Error('HTTP 500');return {json:async()=>answer};}});
 stateOf(c).labId='lab-a';
 const view={intent:{schema:1,revision:'r'},problems:[],nodes:{},generations:[{id:'g',status:'succeeded',finished:'2026-10-03T10:00:00Z',artifacts:{}}]};
 stateOf(c).view=view;
 await c.designLoadPlan('lab-a','g');
 c.designRenderPlanCard(view);
 let body=el('design-plan-body').innerHTML;
 assert.doesNotMatch(body,/Generate a plan/);assert.match(body,/could not be loaded/i);assert.match(body,/HTTP 500/);
 assert.match(body,/data-design-plan-retry/);assert.match(body,/Try again/);
 assert.match(body,/kept on the manager/i,'a failed fetch keeps its wording: the plan exists, the request failed');
 // A 200 answer without a plan (the manager could not read plan.json) is the same failure.
 fail=false;answer={plan:null};
 await c.designLoadPlan('lab-a','g');c.designRenderPlanCard(view);
 body=el('design-plan-body').innerHTML;assert.doesNotMatch(body,/Generate a plan/);assert.match(body,/data-design-plan-retry/);
 // ...but an unreadable file is not promised to be recoverable: no "kept on the manager", Try again plus generating again.
 assert.doesNotMatch(body,/kept on the manager/i);assert.match(body,/could not read/i);assert.match(body,/generate the plan again/i);
 // An earlier plan opened through History > View: generating again would make a different plan, so only Try again is offered.
 const two={intent:{schema:1,revision:'r'},problems:[],nodes:{},generations:[{id:'g0',status:'succeeded',finished:'2026-10-03T09:00:00Z',artifacts:{}},{id:'g',status:'succeeded',finished:'2026-10-03T10:00:00Z',artifacts:{}}]};
 stateOf(c).view=two;stateOf(c).viewing='g0';
 await c.designLoadPlan('lab-a','g0');c.designRenderPlanCard(two);
 body=el('design-plan-body').innerHTML;assert.match(body,/could not read/i);assert.match(body,/data-design-plan-retry/);assert.doesNotMatch(body,/generate the plan again/i);
 stateOf(c).viewing='';stateOf(c).view=view;
 await c.designLoadPlan('lab-a','g');
 // Try again fetches the shown plan again and draws it.
 answer={plan:{devices:[{name:'r1'}],links:[]}};paths.length=0;
 await c.designPlanRetry();
 assert.equal(paths.length,1);assert.match(paths[0],/\/design\/generations\/g$/);
 body=el('design-plan-body').innerHTML;assert.doesNotMatch(body,/data-design-plan-retry|could not be loaded/);assert.match(body,/r1/);
 // A plan that does not exist (nothing generated yet, or a failed one) keeps its old hint.
 const none={intent:{schema:1},problems:[],nodes:{},generations:[]};stateOf(c).view=none;stateOf(c).plan=null;stateOf(c).planError='';
 c.designRenderPlanCard(none);assert.match(el('design-plan-body').innerHTML,/Generate a plan to see it here/);
});
test('L-36: History > View of a plan whose fetch fails shows the failure for that plan, and a late answer for another plan is ignored',async()=>{
 const {el}=summaryEls();
 const c=ctx({$:el,setMarkup:(e,h)=>{if(e)e.innerHTML=h;},current:()=>({id:'lab-a',name:'A'}),api:async()=>{throw new Error('HTTP 502');}});
 stateOf(c).labId='lab-a';
 stateOf(c).view={intent:{schema:1,revision:'r'},problems:[],nodes:{},generations:[{id:'g1',status:'succeeded',finished:'2026-10-03T10:00:00Z'},{id:'g2',status:'succeeded',finished:'2026-10-03T11:00:00Z'}]};
 await c.designViewGeneration('g1');
 assert.match(el('design-plan-body').innerHTML,/could not be loaded/i);
 stateOf(c).planError='';
 await c.designLoadPlan('lab-a','g2');
 assert.equal(stateOf(c).planError,'','the answer for a plan that is not shown does not touch the shown plan\'s state');
});
