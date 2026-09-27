// network-design.js: pure state words, the guided-form <-> intent round trip, and the plan/compatibility
// markup, run the same way tests/test_restore_ui.js drives restore.js — a vm context with a fake $, esc
// and state, no DOM. The draft helpers (shell.js) are covered at the bottom with a minimal document/window.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const same=(a,b)=>assert.equal(JSON.stringify(a),JSON.stringify(b));
const source=fs.readFileSync(path.join(__dirname,'../app/static/network-design.js'),'utf8');
const statusSource=fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8');
function ctx(){
 const context=vm.createContext({esc,state:{labs:[]},$:()=>null,api:async()=>({json:async()=>({})}),
  json:async()=>({}),opDialog:()=>({querySelectorAll:()=>[]}),opTask:async()=>{},refresh:async()=>{},notify:()=>{},
  setMarkup:()=>{},menuReason:()=>{},showActionError:()=>{},closeMenus:()=>{},showTab:()=>{},current:()=>null,
  clearTimeout:()=>{},setTimeout:()=>0});
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
 const st=c.designStateOf({},{generations:[{id:'g',status:'succeeded',message:'Plan generated'}],problems:[]});
 assert.equal(st.key,'ready');assert.equal(st.label,'Plan ready to review');assert.equal(st.pill,'ok');
});
test('designStateOf: plan is older than the design (stale)',()=>{
 const c=ctx();
 const st=c.designStateOf({},{generations:[{id:'g',status:'succeeded'}],problems:[],summary:{stale:true}});
 assert.equal(st.key,'stale');assert.equal(st.label,'Plan is older than the design');assert.equal(st.pill,'warn');
});
test('designStateOf: the last plan failed',()=>{
 const c=ctx();
 const st=c.designStateOf({},{generations:[{id:'g',status:'failed',message:'The engine could not generate this plan.'}],problems:[]});
 assert.equal(st.key,'failed');assert.equal(st.label,'The last plan failed');assert.equal(st.pill,'danger');
 assert.match(st.detail,/could not generate/);
});
test('designStateOf: the last plan was interrupted',()=>{
 const c=ctx();
 const st=c.designStateOf({},{generations:[{id:'g',status:'interrupted',message:'The manager restarted.'}],problems:[]});
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
  modules:['ospf','bgp'],ospfArea:'0.0.0.0',bgpAs:65001,bgpRr:'r2',isisArea:'49.0001',isisType:'level-2',
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
 assert.equal(back.bgpRr,values.bgpRr);
 assert.ok(back.devices.some(d=>d.name==='r2'&&d.role==='router'));
 assert.ok(back.devices.some(d=>d.name==='r3'&&d.role==='exclude'));
});
test('designFormFromIntent reads defaults from an empty intent',()=>{
 const c=ctx();
 const values=c.designFormFromIntent(c.designEmptyIntent());
 assert.equal(values.ipv4,true);assert.equal(values.ipv6,true);
 assert.equal(values.pools.loopback.ipv4,'10.255.0.0/24');assert.equal(values.pools.p2p.prefix,31);assert.equal(values.pools.lan.prefix,24);
 same(values.modules,[]);assert.equal(values.ospfArea,'0.0.0.0');assert.equal(values.bgpAs,65000);
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
 assert.match(html,/<select data-design-role="r1" disabled/);
 assert.match(html,/<select data-design-role="r2"[^>]*>/);
 assert.doesNotMatch(html.match(/<select data-design-role="r2"[^>]*>/)[0],/disabled/,'a device with a profile keeps its role select enabled');
 assert.match(html,/value="exclude" selected/);
 assert.match(html,/cannot map/);
 assert.equal(c.designDevicesMarkup({},{}),'<tr><td colspan="5" class="table-empty">This lab has no devices yet.</td></tr>');
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
