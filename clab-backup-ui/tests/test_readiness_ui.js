// Deploy-first landing page, NOS readiness gating and default-login labels in the UI.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function appHarness(){
 const elements=new Map();
 function element(){return {dataset:{},value:'',innerHTML:'',textContent:'',title:'',open:false,disabled:false,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},showModal(){this.open=true;},appendChild(){},remove(){},click(){}};}
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},createElement:element,body:element()};
 const items=new Map();
 const context=vm.createContext({document,sessionStorage:{getItem:k=>items.get(k),setItem:(k,v)=>items.set(k,v)},setTimeout:()=>0,clearTimeout(){},setInterval(){},URL:{createObjectURL:()=>'blob:fixture',revokeObjectURL(){}},URLSearchParams,Blob,console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/app.js'),'utf8'),context);
 context.fetch=async()=>({ok:true,status:200,headers:{get:()=>''},json:async()=>({labs:[],jobs:[],platforms:{}})});
 return {context,document};
}
function managementHarness(state,activeId=''){
 const elements=new Map(),element=id=>{
  if(!elements.has(id))elements.set(id,{value:'',hidden:false,checked:false,required:false,disabled:false,innerHTML:'',textContent:'',className:'',title:'',open:false,reset(){},querySelector(){return {textContent:''};},showModal(){this.open=true;},close(){this.open=false;},addEventListener(){}});
  return elements.get(id);
 };
 const context=vm.createContext({$:element,esc,state:{labs:[],jobs:[],...state},activeId,busy:()=>false,
  document:{body:{insertAdjacentHTML(){}},querySelectorAll(){return [];},addEventListener(){}},
  withForm(){},json:async()=>({}),refresh:async()=>{},notify(){},openImport(){},openDeploy(){},opDialog(){},opTask(){},opNewTab(){}});
 context.current=()=>context.state.labs.find(l=>l.id===context.activeId);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/management.js'),'utf8'),context);
 return {element,context};
}

test('SSH actions wait for the NOS to answer and explain why they are disabled',()=>{
 const h=appHarness();
 const booting=vm.runInContext(`nodeActions({name:'r1',ssh_ready:false,login_configured:true,readiness:'Ready',nos_login:{status:'booting'}},true)`,h.context);
 assert.match(booting,/data-terminal="r1" disabled title="r1 is still starting/);
 const bootingDrawer=vm.runInContext(`nodeDrawerActions({name:'r1',ssh_ready:false,login_configured:true,readiness:'Ready',nos_login:{status:'booting'}})`,h.context);
 assert.match(bootingDrawer,/data-check="r1" >Test login/,'a configured login can still be tested by hand');
 const ready=vm.runInContext(`nodeActions({name:'r1',ssh_ready:true,login_configured:true,readiness:'Ready',nos_login:{status:'ready'}})`,h.context);
 assert.match(ready,/data-terminal="r1" >Open CLI/);
 const failed=vm.runInContext(`nodeActions({name:'r1',ssh_ready:false,login_configured:true,nos_login:{status:'failed'}},true)`,h.context);
 assert.match(failed,/SSH login failed with the saved credentials/);
 const legacy=vm.runInContext(`nodeDrawerActions({name:'r1',ssh_ready:true})`,h.context);
 assert.match(legacy,/data-check="r1" >Test login/,'older state without login_configured keeps the previous behaviour');
});

test('containerlab default logins are named in the credential column',()=>{
 const h=appHarness();
 assert.equal(vm.runInContext(`profileName({profiles:[],defaults:{}},{platform:'arista_ceos',credential_source:'default'})`,h.context),'Containerlab default login');
 assert.equal(vm.runInContext(`profileName({profiles:[],defaults:{}},{platform:'arista_ceos',inventory_credentials:true})`,h.context),'From inventory');
 assert.equal(vm.runInContext(`profileName({profiles:[{id:'p',label:'Ops'}],defaults:{arista_ceos:'p'}},{platform:'arista_ceos',credential_source:'profile'})`,h.context),'Ops');
 assert.equal(vm.runInContext(`profileName({profiles:[],defaults:{}},{platform:''})`,h.context),'Not configured');
});

test('Manager › Labs found on the VM lists what Home used to: labs to add, hidden labs with Stop hiding, and the file checks',()=>{
 const h=managementHarness({discovery:{configured:true,connected:true,host:{enabled:true},discovered:[{name:'ceos-pair',nodes:2,running:2,imported:false},{name:'old',nodes:1,running:1,imported:true},{name:'gone',nodes:1,running:0,imported:false,excluded:true}],ignored_labs:['gone'],file_reports:{'ceos-pair':{definition:{message:'Found',paths:['/labs/a.clab.yml']}}}}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/home.js'),'utf8'),h.context);
 h.context.renderManagement();
 assert.equal(h.element('manager-vm-labs-note').textContent,'1 not in My labs · 1 hidden');assert.equal(h.element('manager-vm-labs-note').hidden,false);
 assert.match(h.element('discovered-labs').innerHTML,/data-setup-name="ceos-pair">ceos-pair<small>Running on the VM · 2 of 2 devices running · Add to My labs/);
 assert.doesNotMatch(h.element('discovered-labs').innerHTML,/>old<|>gone</);
 assert.match(h.element('excluded-labs').innerHTML,/data-allow-import="gone"/);assert.match(h.element('excluded-labs').innerHTML,/data-clear-exclusion="gone">Stop hiding/);
 assert.match(h.element('discovery-file-list').innerHTML,/\/labs\/a\.clab\.yml/);assert.equal(h.element('vm-labs-empty').hidden,true);
 assert.equal(h.element('hidden-labs').innerHTML,'','no lab hidden from Home, no list');
 h.element('manager-vm-labs').onclick();assert.equal(h.element('vm-labs-dialog').open,true);
 const hiddenLab=managementHarness({labs:[{id:'h1',name:'BEN-TEST',hidden:true,nodes:[],deployment:{status:'Not deployed'}},{id:'v1',name:'shown',nodes:[]}],discovery:{configured:true,connected:true,host:{enabled:true},discovered:[{name:'BEN-TEST',imported:true},{name:'shown',imported:true}]}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/home.js'),'utf8'),hiddenLab.context);
 hiddenLab.context.renderManagement();
 assert.equal(hiddenLab.element('manager-vm-labs-note').textContent,'1 hidden','a lab hidden from Home counts under the menu entry');
 assert.match(hiddenLab.element('hidden-labs').innerHTML,/<p class="side-hint">Hidden from Home<\/p>/);
 assert.match(hiddenLab.element('hidden-labs').innerHTML,/data-open-hidden="h1">BEN-TEST<small>Still in My labs/);
 assert.match(hiddenLab.element('hidden-labs').innerHTML,/data-show-lab="h1">Show on Home/);
 assert.doesNotMatch(hiddenLab.element('hidden-labs').innerHTML,/>shown</);
 assert.equal(hiddenLab.element('vm-labs-empty').hidden,true,'the dialog is not empty while a lab is hidden');
 const none=managementHarness({discovery:{configured:true,connected:true,host:{enabled:true},discovered:[{name:'old',imported:true}]}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/home.js'),'utf8'),none.context);none.context.renderManagement();
 assert.equal(none.element('manager-vm-labs-note').hidden,true);assert.equal(none.element('vm-labs-empty').hidden,false);assert.match(none.element('vm-labs-empty').textContent,/already in My labs/);
 const away=managementHarness({discovery:{configured:true,connected:false,host:{enabled:true}}});none.context.state=away.context.state;none.context.renderManagement();
 assert.match(none.element('vm-labs-empty').textContent,/does not answer/);
});

test('the landing page leads with deployment and lists labs already running on the VM',()=>{
 const h=managementHarness({discovery:{configured:true,connected:true,host:{enabled:true},discovered:[{name:'ceos-pair',nodes:2,running:2,imported:false},{name:'old',nodes:1,running:1,imported:true},{name:'gone',nodes:1,running:0,imported:false,excluded:true}]}});
 h.context.renderManagement();
 assert.equal(h.element('vm-connect-empty').hidden,true);assert.equal(h.element('home-deploy').disabled,false);assert.equal(h.element('home-upload').disabled,false);assert.equal(h.element('home-deploy-reason').hidden,true);
 const list=h.element('empty-discovered-list').innerHTML;
 assert.match(list,/ceos-pair/);assert.doesNotMatch(list,/>old</);assert.match(list,/removed from this manager earlier/);
 assert.match(list,/data-setup-name="ceos-pair">Import/);
 assert.equal(h.element('empty-discovered').hidden,false);assert.equal(h.element('empty-vm-note').textContent,'');
 const unconfigured=managementHarness({discovery:{configured:false}});unconfigured.context.renderManagement();
 assert.equal(unconfigured.element('vm-connect-empty').hidden,false);assert.equal(unconfigured.element('home-deploy').disabled,true);assert.equal(unconfigured.element('home-upload').disabled,true,'an upload ends on the lab VM too');
 assert.match(unconfigured.element('home-deploy-reason').textContent,/^Connect the lab VM first: deploying needs it\. Building a lab works without it\.$/);assert.equal(unconfigured.element('home-deploy-reason').hidden,false);
 assert.match(unconfigured.element('empty-vm-note').textContent,/Connect this manager/);
 assert.equal(unconfigured.element('empty-discovered').hidden,true);
 const offline=managementHarness({discovery:{configured:true,connected:false,host:{enabled:true},error:'Cannot reach the VM SSH service.'}});offline.context.renderManagement();
 assert.equal(offline.element('home-deploy').disabled,true);assert.match(offline.element('home-deploy-reason').textContent,/^Waiting for the lab VM to answer/);assert.match(offline.element('empty-vm-note').textContent,/Cannot reach the VM/);
});

test('the deployment bar reports NOS readiness in plain words',()=>{
 const lab={id:'lab',name:'demo',nodes:[],deployment:{status:'Running'},nos_readiness:{status:'booting',ready:1,total:2,booting:1,failed:0}};
 const h=managementHarness({discovery:{configured:true,connected:true,host:{enabled:true}},labs:[lab]},'lab');
 h.context.renderManagement();
 assert.match(h.element('deployment-nos').textContent,/NOS booting · 1\/2 devices/);assert.equal(h.element('deployment-nos').className,'deployment-nos booting');
 lab.nos_readiness={status:'ready',ready:2,total:2,booting:0,failed:0};h.context.renderManagement();
 assert.match(h.element('deployment-nos').textContent,/NOS ready · 2\/2 devices accept SSH login/);
 lab.nos_readiness={status:'failed',ready:1,total:2,booting:0,failed:1};h.context.renderManagement();
 assert.match(h.element('deployment-nos').textContent,/NOS login failed on 1 of 2 devices/);
 delete lab.nos_readiness;h.context.renderManagement();
 assert.equal(h.element('deployment-nos').textContent,'');
});

test('Restart device… sits with the per-device actions and reaches the shared operation with the lab and the device',async()=>{
 const h=appHarness();
 const n={name:'r1',short_name:'R1',ssh_ready:true,login_configured:true,readiness:'Ready',nos_login:{status:'ready'},discovered:true,runtime_state:'running'};
 assert.match(vm.runInContext('nodeActions('+JSON.stringify(n)+',true)',h.context),/data-restart="r1" disabled title="Not available on this page"/,'without operations.js the button explains itself');
 const asked=[];h.context.opRestartState=(lab,node,discovery,isBusy)=>{asked.push({node:node.name,isBusy});return {ok:true,reason:''};};
 const html=vm.runInContext('nodeActions('+JSON.stringify(n)+',true)',h.context);
 assert.match(html,/<button class="danger-action" data-restart="r1" >Restart device…<\/button>/);assert.deepEqual(asked,[{node:'r1',isBusy:false}]);
 assert.ok(html.indexOf('data-backup')<html.indexOf('data-restart'),'after Back up configuration');
 assert.doesNotMatch(html,/data-details/,'the panel variant has no Details button');
 const row=vm.runInContext('nodeActions('+JSON.stringify(n)+')',h.context);assert.ok(row.indexOf('data-restart')<row.indexOf('data-details'),'the table variant keeps Details last');
 h.context.opRestartState=()=>({ok:false,reason:'The lab is not running'});
 assert.match(vm.runInContext('nodeActions('+JSON.stringify(n)+',true)',h.context),/data-restart="r1" disabled title="The lab is not running"/);
 const ran=[];h.context.opTask=async(dialog,fn)=>{await fn();};h.context.opRestartDevice=async(labId,name,opener)=>{ran.push([labId,name,opener]);};vm.runInContext("activeId='lab-a'",h.context);
 const dialog=h.document.getElementById('details-dialog');dialog.open=true;dialog.close=()=>{dialog.open=false;};
 const button={disabled:false,dataset:{restart:'r1'},closest:()=>null};
 await h.context.handleNodeAction({target:{closest:()=>button}});
 assert.deepEqual(ran,[['lab-a','r1',button]],'the panel button is the control the review gives focus back to (U-02)');assert.equal(dialog.open,true,'the device panel stays open under the review');
 await h.context.handleNodeAction({target:{closest:()=>({disabled:true,dataset:{restart:'r1'}})}});assert.equal(ran.length,1,'a disabled button does nothing');
});

test('U-09: the device panel says in words why Restart device… or Back up configuration is unavailable',()=>{
 const h=appHarness();
 const n={name:'r1',short_name:'R1',ssh_ready:true,readiness:'Needs credentials'};
 h.context.opRestartState=()=>({ok:false,reason:'The lab is not running'});h.context.nodeBackupReason=()=>'Add credentials first';h.context.captureStatusLine=()=>'';
 assert.equal(h.context.nodeActionNotes(n),'Restart device… is not available: The lab is not running. Back up configuration is not available: Add credentials first.');
 h.context.opRestartState=()=>({ok:true,reason:''});h.context.nodeBackupReason=()=>'';
 assert.equal(h.context.nodeActionNotes(n),'');
 h.context.captureStatusLine=()=>'Packet capture is not set up on this VM.';assert.equal(h.context.nodeActionNotes(n),'Packet capture is not set up on this VM.');
 assert.match(vm.runInContext('nodeActions({name:"clab-x-r1",short_name:"r1",ssh_ready:true})',h.context),/aria-label="Details for r1"/,'Details is named after the device, not its container (U-19)');
});

// Audit M-11 follow-up: the readiness monitor skips a lab with no deployment_name, so the drawer must not promise an automatic check there.
test('M-11: the device drawer promises an automatic login check only for a lab the readiness monitor watches',()=>{
 const h=appHarness(),auto=/checked automatically/,hand=/Test login \(under Advanced\) checks the saved credentials now\./;
 const linked=vm.runInContext(`detailsLoginHelp({deployment_name:'clab-x'},{name:'r1',nos_login:{status:'booting'}})`,h.context);
 assert.match(linked,auto);assert.match(linked,hand);
 for(const [lab,node] of [[{deployment_name:''},{name:'r1',nos_login:{status:'unmonitored'}}],[{},{name:'r1'}],[{deployment_name:'clab-x'},{name:'r1',nos_login:{status:'unmonitored'}}]]){
  const text=h.context.detailsLoginHelp(lab,node);
  assert.doesNotMatch(text,auto,JSON.stringify([lab,node]));assert.equal(text,'Test login (under Advanced) checks the saved credentials now.');
 }
 assert.match(h.context.detailsLoginHelp({deployment_name:'clab-x'},{name:'r1'}),auto,'an older payload without nos_login keeps the sentence for a linked lab');
});
test('M-11: the open drawer of an inventory-import lab shows the stored message without the automatic-check sentence',()=>{
 const h=appHarness();
 const n={name:'r1',short_name:'R1',address:'10.0.0.1',port:22,platform:'arista_ceos',enabled:true,readiness:'Ready',nos_login:{status:'unmonitored',message:'SSH readiness is only monitored for labs linked to a VM deployment.'}};
 const lab={id:'lab-a',name:'Imported',nodes:[n],profiles:[],defaults:{}};
 vm.runInContext(`state.labs=[${JSON.stringify(lab)}];activeId='lab-a';detailName='r1';healthState={lab:'lab-a',nodes:[{name:'r1',ssh:${JSON.stringify(n.nos_login)}}]};`,h.context);
 h.document.getElementById('details-dialog').open=true;
 h.context.renderDetails();
 const html=h.document.getElementById('details-status-raw-body').innerHTML;
 assert.match(html,/<p>SSH readiness is only monitored for labs linked to a VM deployment\.<\/p>/,'the drawer still shows the message it stored');
 assert.doesNotMatch(html,/checked automatically/);assert.match(html,/Test login \(under Advanced\) checks the saved credentials now\./);
 lab.deployment_name='clab-x';n.nos_login={status:'booting',message:'Container is running.'};
 vm.runInContext(`state.labs=[${JSON.stringify(lab)}];healthState={lab:'lab-a',nodes:[{name:'r1',ssh:${JSON.stringify(n.nos_login)}}]};`,h.context);h.context.renderDetails();
 assert.match(h.document.getElementById('details-status-raw-body').innerHTML,/checked automatically until they accept a login/);
});

test('adding a lab by files survives blocked sessionStorage in the fallback branch without the router',async()=>{
 const blocked={getItem(){throw new Error('SecurityError');},setItem(){throw new Error('SecurityError');},removeItem(){throw new Error('SecurityError');}};
 const h=managementHarness({labs:[],discovery:{configured:true,connected:true,host:{enabled:true}}});
 h.context.sessionStorage=blocked;h.context.FormData=class{};h.context.notify=()=>{};
 h.context.api=async()=>({json:async()=>({id:'made'})});
 let running;h.context.withForm=(form,fn)=>{running=fn();};
 const setup=h.element('setup-form');
 setup.onsubmit({preventDefault(){},currentTarget:{},target:{}});await running;
 assert.equal(h.context.activeId,'made','the new lab is open although the id could not be stored');
});

// L-10 follow-up: after a restart an interrupted job that still reads devices back holds the lab (409); the page says so.
test('L-10 follow-up: a restore reading devices back after a restart is shown as running work in the banner and the worker line',()=>{
 const h=appHarness(),get=id=>h.document.getElementById(id);
 const lab={id:'lab',name:'L',nodes:[],profiles:[],defaults:{},deployment:{status:'Running'},nos_readiness:{status:'idle'}};
 const job=extra=>({id:'rs-r',lab_id:'lab',status:'interrupted',created:'2026-09-16T11:30:00Z',finished:'2026-09-16T11:31:00Z',message:'Manager restarted during a restore. It is checking the devices that were being changed.',...extra});
 const paint=s=>vm.runInContext(`state=${JSON.stringify({labs:[lab],jobs:[],platforms:{},...s})};activeId='lab';renderLabBanner();renderWorkerState();`,h.context);
 paint({restore_jobs:[job({rechecking:true})]});
 assert.equal(get('lab-banner').hidden,false);assert.equal(get('lab-banner-text').textContent,'Checking the devices after a manager restart…');
 assert.equal(get('lab-banner').className,'banner info','work in progress, not an error');
 assert.equal(get('lab-banner-detail-text').textContent,job({}).message);
 assert.equal(get('banner-restore').hidden,false);assert.equal(get('banner-restore').textContent,'View progress');
 assert.equal(get('banner-dismiss').hidden,true,'running work is never dismissed');
 assert.equal(get('worker-state').textContent,'Checking devices after a restart…');assert.equal(get('worker-state').hidden,false);
 // Read back, or stored by an older manager without the field: the finished job it was, with Dismiss and Details.
 for(const done of [job({rechecking:false}),job({})]){
  paint({restore_jobs:[done]});
  assert.equal(get('lab-banner-text').textContent,'Loading a saved state did not finish.');assert.equal(get('banner-dismiss').hidden,false);
  assert.equal(get('worker-state').hidden,true);
 }
 paint({restore_jobs:[{id:'r1',lab_id:'lab',status:'applying',message:'Applying.'}]});
 assert.equal(get('lab-banner-text').textContent,'Loading a saved state…','a running load keeps its words');assert.equal(get('worker-state').textContent,'Loading…','the worker line words it as the chip does');
 // A design apply's read-back (its `rechecking` lists the devices) holds its lab the same way.
 paint({design_jobs:[{id:'d1',lab_id:'lab',status:'interrupted',rechecking:['r1'],message:'Manager restarted while the design was being applied.'}]});
 assert.equal(get('lab-banner-text').textContent,'Checking the devices after a manager restart…');
 assert.equal(get('banner-output').hidden,false);assert.equal(get('banner-output').textContent,'View progress');assert.equal(get('banner-restore').hidden,true);
 assert.equal(get('worker-state').textContent,'Checking devices after a restart…');
 paint({design_jobs:[{id:'d1',lab_id:'lab',status:'interrupted',message:'Read back afterwards.'}]});
 assert.equal(get('lab-banner').hidden,true,'read back: nothing is held');assert.equal(get('worker-state').hidden,true);
});

// Audit V3 (the M-14 pattern on the Git-problem banner): the x on problem A must not hide a later, different problem B of the
// same lab. The banner no longer reports a save location problem at all (owner decision D1: the header chip carries it, and a
// chip cannot be closed), so the claim holds through the chip: every problem is stated, and a different one states itself anew.
test('V3: a save location problem is the chip\'s, never a closable banner; a different problem of the lab is stated again',()=>{
 const h=appHarness(),get=id=>h.document.getElementById(id);
 const lab={id:'lab',name:'L',nodes:[],profiles:[],defaults:{},deployment:{status:'Running'},nos_readiness:{status:'idle'},git_binding:{repository:{push_url:'https://github.com/x/y.git'}}};
 const paint=status=>vm.runInContext(`state=${JSON.stringify({labs:[{...lab,git_status:status}],jobs:[],git_jobs:[],restore_jobs:[],platforms:{}})};activeId='lab';renderLabBanner();`,h.context);
 const chip=()=>vm.runInContext(`(()=>{const lab=state.labs[0],cs=saveChipState(lab,state,Date.now()),p=saveProblem(lab,state);return {key:cs.key,text:cs.text,sentence:p.sentence};})()`,h.context);
 paint({checked:'2026-10-04T12:00:00+00:00',ready:false,problem:'The push URL rejected the VM account.',code:'account',waiting:0});
 assert.equal(get('lab-banner').hidden,true,'no banner for a save location problem');
 const first=chip();assert.equal(first.key,'cant');assert.equal(first.text,'Can\u2019t save');assert.ok(first.sentence);
 paint({checked:'2026-10-04T12:00:04+00:00',ready:false,problem:'The push URL rejected the VM account.',code:'account',waiting:0});
 assert.deepEqual(chip(),first,'the same problem reads the same on the next poll');
 paint({checked:'2026-10-04T12:00:08+00:00',ready:false,problem:'Cannot reach the VM Git helper.',code:'vm',waiting:0});
 const second=chip();assert.equal(second.key,'cant');assert.notEqual(second.sentence,first.sentence,'a different problem states itself');
 assert.equal(get('lab-banner').hidden,true);
});

// C02: Stop in the lab banner, the stopped job in the vocabulary sites of app.js, and the Copy buttons of the device drawer.
test('C02: the banner offers Stop only while the job is queued or running, stoppable and not yet asked to stop; a stop reads as a warning badge and Dismiss clears it',()=>{
 const h=appHarness(),get=id=>h.document.getElementById(id);
 const lab={id:'lab',name:'L',nodes:[],profiles:[],defaults:{},deployment:{status:'Running'},nos_readiness:{status:'idle'}};
 const opened=[];h.context.opShowJob=(id,opts)=>opened.push([id,opts]);
 const paint=ops=>vm.runInContext(`state=${JSON.stringify({labs:[lab],jobs:[],platforms:{},operations:ops})};activeId='lab';renderLabBanner();`,h.context);
 const job=extra=>({id:'op-1',lab_id:'lab',action:'deploy',status:'running',created:'2026-10-20T10:00:00Z',message:'Executing on the VM',...extra});
 paint([job({})]);
 assert.equal(get('banner-stop').hidden,false);assert.equal(get('banner-stop').textContent,'Stop…');assert.equal(get('banner-output').hidden,false);
 get('banner-stop').onclick();assert.equal(opened.length,1);assert.equal(opened[0][0],'op-1');assert.equal(opened[0][1].stop,true,'opens the output with the confirmation unfolded');
 paint([job({status:'queued'})]);assert.equal(get('banner-stop').hidden,false);
 paint([job({cancel_requested:'2026-10-20T10:00:05Z'})]);assert.equal(get('banner-stop').hidden,true,'already asked: no second Stop');assert.equal(get('banner-output').hidden,false);
 for(const action of ['create','delete','publish','revise','inspect']){paint([job({action})]);assert.equal(get('banner-stop').hidden,true,action+' has no Stop');}
 paint([job({status:'succeeded',finished:'2026-10-20T10:01:00Z'})]);assert.equal(get('banner-stop').hidden,true,'a finished job has none');
 assert.ok(vm.runInContext('BANNER_BUTTONS["lab-banner"]',h.context).includes('banner-stop'));
});
test('C02: badge(cancelled) is a warning in the student\'s words, and a dismissed stopped job leaves the needs-attention set',()=>{
 const h=appHarness();
 const html=vm.runInContext("badge('cancelled')",h.context);
 assert.match(html,/class="badge warn"/);assert.match(html,/>Stopped by you</);assert.match(html,/title="cancelled"/);
 h.context.isDismissed=id=>id==='gone';
 vm.runInContext(`state={labs:[],jobs:[],platforms:{},operations:[{id:'gone',status:'cancelled'},{id:'kept',status:'cancelled'},{id:'f',status:'failed'},{id:'ok',status:'succeeded'}],restore_jobs:[{id:'gone',status:'partial'}]}`,h.context);
 assert.deepEqual([...vm.runInContext('dismissedSet()',h.context)],['gone'],'a stopped job the student dismissed is in the set');
 h.context.isDismissed=()=>true;
 assert.deepEqual([...vm.runInContext('dismissedSet()',h.context)].sort(),['f','gone','kept'],'every status of the three sets of status.js counts, a succeeded job never');
});
test('C02: the device drawer facts carry Copy buttons for the name, endpoint, address, kind and image; absent facts have none; IPv6 is bracketed; values are escaped',()=>{
 const h=appHarness(),get=id=>h.document.getElementById(id);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/clipboard.js'),'utf8'),h.context);
 const show=n=>{const lab={id:'lab',name:'L',nodes:[n],profiles:[],defaults:{},deployment:{status:'Running'}};vm.runInContext(`state.labs=[${JSON.stringify(lab)}];activeId='lab';detailName=${JSON.stringify(n.name)};`,h.context);get('details-dialog').open=true;h.context.renderDetails();return get('details-info').innerHTML;};
 const html=show({name:'clab-l-r1',short_name:'r1',address:'172.20.20.2',port:22,platform:'arista_ceos',kind:'ceos',image:'ceos:4.32',enabled:true});
 const targets=[...html.matchAll(/data-copy="([^"]*)" data-copy-target="([^"]*)"/g)].map(m=>[m[1],m[2]]);
 assert.deepEqual(targets,[['clab-l-r1','details-fact-name'],['172.20.20.2:22','details-fact-endpoint'],['172.20.20.2','details-fact-address'],['ceos','details-fact-kind'],['ceos:4.32','details-fact-image']]);
 for(const id of ['details-fact-name','details-fact-endpoint','details-fact-address','details-fact-kind','details-fact-image'])assert.match(html,new RegExp(`id="${id}"`),id+' exists for the button to select');
 assert.match(html,/aria-label="Copy address only"/);
 // two Copy buttons in the Address row must differ to the eye: the second reads Copy address, its label contains the visible words, and the flip restores it
 const row=html.match(/<dt>Address<\/dt><dd>.*?<\/dd>/)[0];assert.deepEqual([...row.matchAll(/data-label="([^"]*)"[^>]*>([^<]*)<\/button>/g)].map(m=>[m[1],m[2]]),[['Copy','Copy'],['Copy address','Copy address']]);assert.match(html,/<dt>Container kind<\/dt>/);assert.match(html,/<dt>Image<\/dt>/);
 assert.match(html,/<dt>Name in lab files<\/dt>/);assert.match(html,/<dt>Network OS<\/dt>/);assert.match(html,/<dt>Login credentials<\/dt>/,'the other facts stay');
 const v6=show({name:'r6',address:'3fff::5',port:22,platform:'arista_ceos',enabled:true});
 assert.match(v6,/data-copy="\[3fff::5\]:22" data-copy-target="details-fact-endpoint"/);assert.match(v6,/data-copy="3fff::5" data-copy-target="details-fact-address"/);
 assert.doesNotMatch(v6,/Container kind|<dt>Image/,'kind and image rows are absent when the node names none');
 const bare=show({name:'r7',address:'',port:22,platform:'arista_ceos',enabled:true});
 assert.doesNotMatch(bare,/details-fact-address/);assert.doesNotMatch(bare,/data-copy-target="details-fact-kind"/);
 const nasty=show({name:'a"b<i>',address:'10.0.0.1',port:22,platform:'arista_ceos',image:'x"y',kind:'k',enabled:true});
 assert.doesNotMatch(nasty,/a"b<i>/);assert.match(nasty,/data-copy="a&quot;b&lt;i&gt;"/);assert.match(nasty,/data-copy="x&quot;y"/);
 assert.equal(get('details-endpoint').textContent,'10.0.0.1:22','the header endpoint is untouched');
 h.context.copyButton=undefined;
 assert.doesNotMatch(show({name:'r1',address:'1.1.1.1',port:22,platform:'arista_ceos',enabled:true}),/data-copy/,'a page without clipboard.js shows the facts without buttons');
});

// ---- C04: the serial console button and the Container section of the device panel ----
const VRT={name:'clab-parity-vrt',short_name:'vrt',address:'172.20.20.112',port:22,platform:'juniper_junos',kind:'juniper_vjunosrouter',image:'vrnetlab/vjunos-router:25.2',enabled:true,ssh_ready:false,login_configured:true,readiness:'Ready',nos_login:{status:'booting'},
 container:'clab-parity-vrt',console:true,console_hold:'',discovered_id:'0123456789ab',discovered_ipv4:'172.20.20.112',discovered_ipv6:'3fff:172:20:20::112',discovered_image:'vrnetlab/vjunos-router:25.2',runtime_state:'running',runtime_status:'Up 2 hours (healthy)'};
const HELD={key:'starting',text:'vrt is still starting: its launcher uses the console until the device reports healthy. Try again once it is healthy; if the device panel has a Logs section, it shows the boot.'};
function drawer(h,n,{facts}={}){
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/clipboard.js'),'utf8'),h.context);
 const lab={id:'lab',name:'parity',nodes:[n],profiles:[],defaults:{},deployment:{status:'Running'}};
 vm.runInContext(`state.labs=[${JSON.stringify(lab)}];activeId='lab';detailName=${JSON.stringify(n.name)};`,h.context);
 h.context.diagnosticsFacts=facts===undefined?undefined:()=>facts;
 h.document.getElementById('details-dialog').open=true;h.context.renderDetails();
 return {info:()=>h.document.getElementById('details-info').innerHTML,live:()=>h.document.getElementById('details-container-live').innerHTML,get:id=>h.document.getElementById(id)};
}
test('C04: consoleState mirrors the server decision and never derives a reason of its own',()=>{
 const h=appHarness(),state=n=>vm.runInContext('consoleState('+JSON.stringify(n)+')',h.context);
 assert.deepEqual({...state({name:'ceos',console:false,console_hold:''})},{offered:false,ok:false,reason:'',key:''});
 assert.equal(state(null).offered,false);assert.equal(state({name:'old'}).offered,false,'an older manager sends no console field');
 assert.deepEqual({...state({console:true,console_hold:HELD})},{offered:true,ok:false,reason:HELD.text,key:'starting'});
 assert.deepEqual({...state({console:true,console_hold:''})},{offered:true,ok:true,reason:'',key:''});
 assert.equal(state({console:true,console_hold:{key:'x',text:''}}).ok,true,'a hold without a sentence is no hold');
});
test('C04: Console sits after Open CLI in the panel and the table, only for a kind that has one, disabled with the server reason while Open CLI says Starting',()=>{
 const h=appHarness(),act=(n,d)=>vm.runInContext('nodeActions('+JSON.stringify(n)+','+d+')',h.context);
 const html=act(VRT,true);
 assert.match(html,/data-terminal="clab-parity-vrt"[^>]*>Open CLI[\s\S]*<button class="console-action" data-console="clab-parity-vrt" >Console <span aria-hidden="true">↗<\/span><\/button><button data-capture/,'enabled when the server holds nothing, right after Open CLI');
 assert.match(html,/data-terminal="clab-parity-vrt" disabled title="[^"]*still starting/,'Open CLI keeps its own state');
 const held=act({...VRT,console_hold:HELD},true);
 assert.match(held,/data-console="clab-parity-vrt" disabled title="vrt is still starting: its launcher uses the console/);
 assert.equal(act({...VRT,console:false},true).includes('data-console'),false,'no button for cEOS or cJunosEvolved');
 assert.equal(act({...VRT,console:undefined,container:undefined},true).includes('data-console'),false);
 assert.match(act(VRT,false),/data-console=/,'the technical table has it too');
 const row=n=>vm.runInContext('deviceRow('+JSON.stringify(n)+','+(n.__rail?'true':'false')+')',h.context);
 h.document.getElementById('details-dialog').open=false;
 assert.match(row(VRT),/data-console="clab-parity-vrt"/);assert.ok(row(VRT).indexOf('data-terminal')<row(VRT).indexOf('data-console')&&row(VRT).indexOf('data-console')<row(VRT).indexOf('class="details-action"'));
 assert.equal(row({...VRT,__rail:true}).includes('data-console'),false,'the rail keeps Open CLI only');
 assert.equal(row({...VRT,console:false}).includes('data-console'),false);
 h.context.current=()=>({id:'lab',nodes:[]});
 assert.match(h.context.nodeActionNotes({...VRT,console_hold:HELD}),/^Console is not available: vrt is still starting/,'the reason is visible text for keyboard and touch users');
 assert.doesNotMatch(h.context.nodeActionNotes(VRT),/Console/);
});
test('C04: Console opens the terminal page in console mode in a new tab',async()=>{
 const h=appHarness(),opened=[];h.context.window={open:(u,t)=>opened.push([u,t])};
 vm.runInContext(`activeId='lab';state.labs=[{id:'lab',name:'par ity',nodes:[]}];`,h.context);
 const button=name=>({closest:()=>button.self,disabled:false,dataset:{console:name}});
 await h.context.handleNodeAction({target:{closest:()=>button('clab-parity-vrt')}});
 assert.equal(opened.length,1);assert.equal(opened[0][1],'_blank');
 const url=new URL('http://x'+opened[0][0].replace('#','?'));assert.equal(opened[0][0].split('#')[0],'/static/terminal.html');
 assert.equal(url.searchParams.get('lab'),'lab');assert.equal(url.searchParams.get('node'),'clab-parity-vrt');assert.equal(url.searchParams.get('label'),'par ity');assert.equal(url.searchParams.get('protocol'),'console');
 await h.context.handleNodeAction({target:{closest:()=>({disabled:true,dataset:{console:'x'}})}});assert.equal(opened.length,1,'a disabled button opens nothing');
});
test('C04: the C02 drawer facts, rewritten with every claim kept: Copy targets in document order, kind and image labels, optional rows, brackets, escaping',()=>{
 const h=appHarness(),get=id=>h.document.getElementById(id);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/clipboard.js'),'utf8'),h.context);
 const show=n=>{const lab={id:'lab',name:'L',nodes:[n],profiles:[],defaults:{},deployment:{status:'Running'}};vm.runInContext(`state.labs=[${JSON.stringify(lab)}];activeId='lab';detailName=${JSON.stringify(n.name)};`,h.context);get('details-dialog').open=true;h.context.renderDetails();return get('details-info').innerHTML;};
 const html=show({name:'clab-l-r1',short_name:'r1',address:'172.20.20.2',port:22,platform:'arista_ceos',kind:'ceos',image:'ceos:4.32',enabled:true,container:'clab-l-r1',discovered_id:'abcdef012345',discovered_ipv4:'172.20.20.2',discovered_ipv6:'3fff::2',discovered_image:'ceos:4.32'});
 const targets=[...html.matchAll(/data-copy="([^"]*)" data-copy-target="([^"]*)"/g)].map(m=>[m[1],m[2]]);
 assert.deepEqual(targets,[['clab-l-r1','details-fact-name'],['172.20.20.2:22','details-fact-endpoint'],['172.20.20.2','details-fact-address'],['clab-l-r1','details-fact-container'],['abcdef012345','details-fact-id'],['ceos','details-fact-kind'],['ceos:4.32','details-fact-image'],['172.20.20.2','details-fact-ipv4'],['3fff::2','details-fact-ipv6']]);
 for(const id of ['details-fact-name','details-fact-endpoint','details-fact-address','details-fact-container','details-fact-id','details-fact-kind','details-fact-image','details-fact-ipv4','details-fact-ipv6'])assert.match(html,new RegExp(`id="${id}"`),id+' exists for the button to select');
 assert.match(html,/aria-label="Copy address only"/);
 const row=html.match(/<dt>Address<\/dt><dd>.*?<\/dd>/)[0];assert.deepEqual([...row.matchAll(/data-label="([^"]*)"[^>]*>([^<]*)<\/button>/g)].map(m=>[m[1],m[2]]),[['Copy','Copy'],['Copy address','Copy address']]);
 assert.match(html,/<dt>Container kind<\/dt><dd><span class="mono" id="details-fact-kind">ceos/);assert.match(html,/<dt>Image<\/dt><dd><span class="mono" id="details-fact-image">ceos:4.32/);
 assert.ok(html.indexOf('<h3>Container</h3>')<html.indexOf('<dt>Container kind</dt>'),'kind and image moved into the Container section');
 assert.ok(html.indexOf('<h3>Connection</h3>')<html.indexOf('<dt>Address</dt>')&&html.indexOf('<dt>Address</dt>')<html.indexOf('<h3>Container</h3>'));
 assert.match(html,/<dt>Name in lab files<\/dt>/);assert.match(html,/<dt>Network OS<\/dt>/);assert.match(html,/<dt>Login credentials<\/dt>/,'the other facts stay');
 const v6=show({name:'r6',address:'3fff::5',port:22,platform:'arista_ceos',enabled:true,container:''});
 assert.match(v6,/data-copy="\[3fff::5\]:22" data-copy-target="details-fact-endpoint"/);assert.match(v6,/data-copy="3fff::5" data-copy-target="details-fact-address"/);
 assert.doesNotMatch(v6,/Container kind|<dt>Image/,'kind and image rows are absent when the node names none');
 const bare=show({name:'r7',address:'',port:22,platform:'arista_ceos',enabled:true,container:'clab-l-r7'});
 assert.doesNotMatch(bare,/details-fact-address/);assert.doesNotMatch(bare,/data-copy-target="details-fact-kind"/);assert.doesNotMatch(bare,/<dt>Image/);
 const nasty=show({name:'a"b<i>',address:'10.0.0.1',port:22,platform:'arista_ceos',image:'x"y',kind:'k',enabled:true,container:'c"<b>',discovered_id:'i<d>'});
 assert.doesNotMatch(nasty,/a"b<i>|c"<b>|i<d>/);assert.match(nasty,/data-copy="a&quot;b&lt;i&gt;"/);assert.match(nasty,/data-copy="x&quot;y"/);assert.match(nasty,/data-copy="c&quot;&lt;b&gt;"/);
 assert.equal(get('details-endpoint').textContent,'10.0.0.1:22','the header endpoint is untouched');
 h.context.copyButton=undefined;
 assert.doesNotMatch(show({name:'r1',address:'1.1.1.1',port:22,platform:'arista_ceos',enabled:true}),/data-copy/,'a page without clipboard.js shows the facts without buttons');
});
test('C04: the Container section of a linked device: rows, the "topology names" line, the Console row wordings, State in its own element',()=>{
 const h=appHarness(),d=drawer(h,VRT);
 const html=d.info();
 for(const label of ['Container','ID','Container kind','Image','Addresses','Console'])assert.match(html,new RegExp(`<dt>${label}</dt>`),label);
 assert.match(html,/id="details-fact-container">clab-parity-vrt</);assert.match(html,/id="details-fact-id">0123456789ab</);
 assert.match(html,/id="details-fact-ipv4">172\.20\.20\.112</);assert.match(html,/id="details-fact-ipv6">3fff:172:20:20::112</);
 assert.match(html,/<dt>Console<\/dt><dd>Serial, port 5000 \(Console ↗ above\)<\/dd>/);
 assert.doesNotMatch(html,/topology names/,'no second line when the running image is the topology image');
 assert.match(html,/<dl class="health-grid" id="details-container-live"><\/dl>/);
 assert.match(d.live(),/<dt>State<\/dt><dd>running · Up 2 hours \(healthy\)<\/dd>/);assert.doesNotMatch(html,/Up 2 hours/,'State is not in the static markup');
 const local=drawer(appHarness(),{...VRT,discovered_image:'localhost/vjunos-router:ivy'}).info();
 assert.match(local,/id="details-fact-image">localhost\/vjunos-router:ivy<\/span>.*<small class="secondary-text">topology names vrnetlab\/vjunos-router:25\.2<\/small>/);
 assert.match(local,/data-copy="localhost\/vjunos-router:ivy" data-copy-target="details-fact-image"/,'Copy takes the running image');
 const noId=drawer(appHarness(),{...VRT,discovered_id:'',discovered_ipv4:'',discovered_ipv6:''}).info();
 assert.match(noId,/<dt>ID<\/dt><dd>Not reported<\/dd>/);assert.match(noId,/<dt>Addresses<\/dt><dd>No address reported<\/dd>/);assert.doesNotMatch(noId,/details-fact-id|details-fact-ipv/);
 const v4only=drawer(appHarness(),{...VRT,discovered_ipv6:''}).info();assert.match(v4only,/details-fact-ipv4/);assert.doesNotMatch(v4only,/details-fact-ipv6/);
 const none=drawer(appHarness(),{...VRT,kind:'arista_ceos',console:false,container:'clab-parity-ceos'}).info();assert.match(none,/<dt>Console<\/dt><dd>None for this kind<\/dd>/);
 const unknown=drawer(appHarness(),{...VRT,kind:'',console:false}).info();assert.match(unknown,/<dt>Console<\/dt><dd>Not known: the manager has no topology kind for this device<\/dd>/);assert.doesNotMatch(unknown,/<dt>Container kind/);
 const gone=drawer(appHarness(),{...VRT,runtime_state:'absent',runtime_status:''});assert.match(gone.live(),/<dt>State<\/dt><dd>Not on the VM<\/dd>/);
});
test('C04: a device the manager knows no container for shows one sentence, kind and image only when known, and no discovered value',()=>{
 const n={...VRT,container:'',console:false,console_hold:'',discovered_id:'stale1',discovered_ipv4:'10.9.9.9',discovered_image:'stale:img'};
 const h=appHarness(),d=drawer(h,n),html=d.info();
 assert.match(html,/<h3>Container<\/h3><p class="caption">Container facts come from the VM\. This lab is not linked to a running lab \(Advanced › Link to a running lab…\)\.<\/p>/);
 assert.match(html,/<dt>Container kind<\/dt>/);assert.match(html,/id="details-fact-image">vrnetlab\/vjunos-router:25\.2</,'the topology image, not the stale discovered one');
 assert.doesNotMatch(html,/<dt>ID<\/dt>|<dt>State|<dt>Addresses|<dt>Console|stale1|10\.9\.9\.9|stale:img|details-container-live/);
 assert.equal(d.live(),'','no State row');
 const bare=drawer(appHarness(),{name:'inv',address:'1.1.1.1',port:22,platform:'arista_ceos',enabled:true,container:''}).info();
 assert.match(bare,/Container facts come from the VM/);assert.doesNotMatch(bare.slice(bare.indexOf('<h3>Container</h3>')),/<dt>/,'a device with no kind or image has only the sentence');
 const old=drawer(appHarness(),{name:'old',address:'1.1.1.1',port:22,platform:'arista_ceos',enabled:true}).info();
 assert.doesNotMatch(old,/<h3>Container<\/h3>|not linked/,'an older manager without the field gets no section and no claim');
 const oldKind=drawer(appHarness(),{name:'old',address:'1.1.1.1',port:22,platform:'arista_ceos',enabled:true,kind:'ceos',image:'ceos:1'}).info();
 assert.match(oldKind,/<h3>Container<\/h3>/);assert.match(oldKind,/<dt>Container kind/);assert.doesNotMatch(oldKind,/not linked|<dt>ID/,'topology facts alone, no claim about linking');
});
test('C04: the live rows appear only while diagnosticsFacts returns facts, and are gone when it returns null or is undefined',()=>{
 const facts={present:true,id:'x',pid:4242,status:'running',health:'healthy',started:'2026-10-23T02:03:04.5Z',ports:[{container:'22/tcp',host:'2222'},{container:'830/tcp',host:'8300'}]};
 const on=drawer(appHarness(),VRT,{facts}).live();
 assert.match(on,/<dt>Process<\/dt><dd>4242<\/dd>/);assert.match(on,/<dt>Health<\/dt><dd>healthy<\/dd>/);assert.match(on,/<dt>Started<\/dt><dd>2026-10-23 02:03:04 UTC<\/dd>/);
 assert.match(on,/<dt>Published ports<\/dt><dd><div class="mono">2222 → 22\/tcp<\/div><div class="mono">8300 → 830\/tcp<\/div><\/dd>/);assert.match(on,/From the Interfaces or Logs section while it is open\./);
 const bare=drawer(appHarness(),VRT,{facts:{present:true,pid:0,health:'',started:'',ports:[]}}).live();assert.match(bare,/no health check/);assert.match(bare,/<dt>Published ports<\/dt><dd>none<\/dd>/);
 for(const off of [null,{present:false}]){const live=drawer(appHarness(),VRT,{facts:off}).live();assert.doesNotMatch(live,/Process|Health|From the Interfaces/);assert.match(live,/State/);}
 const h=appHarness(),d=drawer(h,VRT);assert.match(d.info(),/<h3>Container<\/h3>/,'the section renders without diagnosticsFacts defined');
 const calls=[];h.context.diagnosticsFacts=key=>{calls.push(key);return facts;};h.context.renderDetails();assert.deepEqual(calls,['lab/clab-parity-vrt']);assert.match(d.live(),/Process/);
 h.context.diagnosticsFacts=()=>null;h.context.renderDetails();assert.doesNotMatch(d.live(),/Process/,'the live rows drop at once');
});
test('C04: focus survives the poll: a status change rewrites only the live rows, never the static markup with the Copy buttons',()=>{
 const h=appHarness(),writes={info:0,live:0},info=h.document.getElementById('details-info'),live=h.document.getElementById('details-container-live');
 for(const [el,key] of [[info,'info'],[live,'live']]){let value='';Object.defineProperty(el,'innerHTML',{get:()=>value,set:v=>{value=v;writes[key]++;}});}
 const d=drawer(h,VRT),copyButton={tag:'the focused Copy button'};h.document.activeElement=copyButton;
 const staticBefore=info.innerHTML,infoWrites=writes.info,liveWrites=writes.live;
 for(const status of ['Up 2 hours (healthy)','Up 2 hours (unhealthy)','Up 3 hours (healthy)']){
  vm.runInContext(`state.labs[0].nodes[0].runtime_status=${JSON.stringify(status)};`,h.context);h.context.renderDetails();
 }
 assert.equal(h.document.activeElement,copyButton,'the same element is still focused');
 assert.equal(info.innerHTML,staticBefore);assert.equal(writes.info,infoWrites,'the static markup was not rewritten');
 assert.match(live.innerHTML,/Up 3 hours \(healthy\)/);assert.ok(writes.live>liveWrites,'the volatile rows were');
 const liveBefore=writes.live;h.context.renderDetails();assert.equal(writes.live,liveBefore,'an unchanged render writes nothing');
 vm.runInContext(`state.labs[0].nodes[0].discovered_ipv4='172.20.20.99';`,h.context);h.context.renderDetails();assert.ok(writes.info>infoWrites,'a changed static value does rebuild the static rows');
});

test('C05: the lab banner offers Review changes… for a pending plan on a Running lab, replaces Start on a Partially running lab with a device to create, and keeps Start for a started-only plan',()=>{
 const h=appHarness(),get=id=>h.document.getElementById(id);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),h.context);
 const lab=status=>({id:'lab',name:'L',nodes:[],profiles:[],defaults:{},deployment:{status},nos_readiness:{status:'idle'}});
 const paint=(status,plan,dismissed=[])=>{h.context.noticeDismissed=key=>dismissed.some(d=>key.includes(d));vm.runInContext(`state=${JSON.stringify({labs:[lab(status)],jobs:[],platforms:{},operations:[]})};activeId='lab';opPlanCache=${JSON.stringify(plan?{lab:{answer:{changed:true,plan,failed:''},error:'',at:1}}:{})};renderLabBanner();`,h.context);};
 paint('Running',{added:['r3'],reasons:{}});
 assert.equal(get('banner-review').hidden,false);assert.equal(get('banner-review').textContent,'Review changes…');assert.equal(get('lab-banner-text').textContent,'The topology file differs from the running lab.');assert.equal(get('lab-banner-detail-text').textContent,'r3 to create');
 paint('Running',null);assert.equal(get('lab-banner').hidden,true,'no differences: no notice');
 const identity=h.context.opPlanIdentity({added:['r3'],reasons:{}});
 paint('Partially running',{added:['r3'],reasons:{}});
 assert.equal(get('banner-review').hidden,false,'a destroyed device needs the plan\'s review');assert.equal(get('banner-start').hidden,true,'Start cannot recreate it');assert.equal(get('lab-banner-detail-text').textContent,'r3 to create');
 paint('Partially running',{started:['r2'],reasons:{}});
 assert.equal(get('banner-start').hidden,false,'a stopped device is started');assert.equal(get('banner-review').hidden,true);
 assert.ok(vm.runInContext('BANNER_BUTTONS["lab-banner"]',h.context).includes('banner-review'));
 assert.ok(typeof identity==='string'&&identity.length>0);
});

test('showTab refreshes the capture sessions for the Tools view only, also through the arrow keys and when the function is absent',()=>{
 const h=appHarness();let refreshed=0;
 vm.runInContext("state={labs:[{id:'l',name:'L',nodes:[],jobs:[]}],jobs:[],platforms:{},loaded:true};activeId='l';",h.context);
 h.context.syncRoute=()=>{};
 assert.doesNotThrow(()=>vm.runInContext("showTab('tools')",h.context),'the page loads and shows Tools without capture.js');
 h.context.refreshCaptureSessions=()=>{refreshed++;};
 vm.runInContext("showTab('devices')",h.context);assert.equal(refreshed,0,'other views do not ask');
 vm.runInContext("showTab('tools')",h.context);assert.equal(refreshed,1);
 // ArrowRight from the Devices tab lands on Tools: the keyboard path asks too
 for(const name of ['topology','devices','tools','advanced']){const el=h.document.getElementById('tab-'+name);el.dataset.tab=name;el.focus=function(){h.document.activeElement=this;};}
 h.document.activeElement=h.document.getElementById('tab-devices');
 vm.runInContext("showTab('devices')",h.context);refreshed=0;
 h.context.tabKeydown({key:'ArrowRight',preventDefault(){}});
 assert.equal(refreshed,1,'ArrowRight from Devices shows Tools and refreshes once');
});

test('C09: the Devices search uses textMatch: case, address and platform still match, a trailing space no longer hides every device, the empty sentences keep their words',()=>{
 const h=appHarness();
 const nodes=[{name:'R1',address:'172.20.20.2',port:22,platform:'arista_ceos',readiness:'Ready',ssh_ready:true,enabled:true},{name:'sw2',port:22,platform:'juniper_vjunosrouter',readiness:'Ready',ssh_ready:true,enabled:true}];
 vm.runInContext(`activeId='a';devicesTechnical=true;state={labs:[{id:'a',nodes:${JSON.stringify(nodes)},profiles:[],defaults:{}}],jobs:[],platforms:{juniper_vjunosrouter:{label:'Juniper vJunos-router'},arista_ceos:{label:'Arista cEOS'}}};`,h.context);
 const table=term=>{h.document.getElementById('search').value=term;vm.runInContext('devicesTechnical=true;renderNodes();',h.context);const t=h.document.getElementById('nodes').innerHTML;return ['R1','sw2'].filter(n=>t.includes('data-enable="'+n+'"'));};
 const list=term=>{h.document.getElementById('search').value=term;vm.runInContext('devicesTechnical=false;renderDeviceList();',h.context);return h.document.getElementById('device-list').innerHTML;};
 assert.match(list('r1'),/R1/);assert.doesNotMatch(list('r1'),/sw2/,'R1 is found by r1');
 assert.match(list('172.20'),/R1/,'an address matches');assert.doesNotMatch(list('172.20'),/sw2/);
 assert.match(list('r1 '),/R1/,'a trailing space matches (the trim)');assert.match(list('   '),/sw2/);
 assert.match(list('undefined'),/No devices match\. Try another name, address or platform\./,'a device with no address is not found by the word undefined');
 assert.match(list('zzz'),/No devices match\. Try another name, address or platform\./);
 assert.deepEqual(table('r1 '),['R1'],'the technical table matches by name with a trailing space');assert.deepEqual(table('JUNIPER'),['sw2'],'by platform label, any case');assert.deepEqual(table('172.20'),['R1']);assert.deepEqual(table(''),['R1','sw2']);assert.deepEqual(table('undefined'),[]);
 vm.runInContext(`state={labs:[{id:'a',nodes:[],profiles:[],defaults:{}}],jobs:[],platforms:{}};`,h.context);
 assert.match(list(''),/<li class="table-empty">|No devices|This lab has no devices/);
});
