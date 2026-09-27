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
  clearTimeout:()=>{},setTimeout:()=>0,crypto:webcrypto,...extra});
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
 c.json=async()=>({targets:[oneTarget()],applicable:['r1'],takeover:[]});
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
