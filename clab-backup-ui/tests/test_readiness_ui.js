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
  assert.equal(get('lab-banner-text').textContent,'Replacing configuration did not finish.');assert.equal(get('banner-dismiss').hidden,false);
  assert.equal(get('worker-state').hidden,true);
 }
 paint({restore_jobs:[{id:'r1',lab_id:'lab',status:'applying',message:'Applying.'}]});
 assert.equal(get('lab-banner-text').textContent,'Replacing configuration…','a running restore keeps its words');assert.equal(get('worker-state').textContent,'Replacing configuration…');
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
