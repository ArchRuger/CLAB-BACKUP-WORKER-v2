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
 h.element('manager-vm-labs').onclick();assert.equal(h.element('vm-labs-dialog').open,true);
 const none=managementHarness({discovery:{configured:true,connected:true,host:{enabled:true},discovered:[{name:'old',imported:true}]}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/home.js'),'utf8'),none.context);none.context.renderManagement();
 assert.equal(none.element('manager-vm-labs-note').hidden,true);assert.equal(none.element('vm-labs-empty').hidden,false);assert.match(none.element('vm-labs-empty').textContent,/already in My labs/);
 const away=managementHarness({discovery:{configured:true,connected:false,host:{enabled:true}}});none.context.state=away.context.state;none.context.renderManagement();
 assert.match(none.element('vm-labs-empty').textContent,/does not answer/);
});

test('the landing page leads with deployment and lists labs already running on the VM',()=>{
 const h=managementHarness({discovery:{configured:true,connected:true,host:{enabled:true},discovered:[{name:'ceos-pair',nodes:2,running:2,imported:false},{name:'old',nodes:1,running:1,imported:true},{name:'gone',nodes:1,running:0,imported:false,excluded:true}]}});
 h.context.renderManagement();
 assert.equal(h.element('vm-connect-empty').hidden,true);assert.equal(h.element('deploy-empty').disabled,false);
 const list=h.element('empty-discovered-list').innerHTML;
 assert.match(list,/ceos-pair/);assert.doesNotMatch(list,/>old</);assert.match(list,/removed from this manager earlier/);
 assert.match(list,/data-setup-name="ceos-pair">Import/);
 assert.equal(h.element('empty-discovered').hidden,false);assert.equal(h.element('empty-vm-note').textContent,'');
 const unconfigured=managementHarness({discovery:{configured:false}});unconfigured.context.renderManagement();
 assert.equal(unconfigured.element('vm-connect-empty').hidden,false);assert.equal(unconfigured.element('deploy-empty').disabled,true);
 assert.match(unconfigured.element('empty-vm-note').textContent,/Connect this manager/);
 assert.equal(unconfigured.element('empty-discovered').hidden,true);
 const offline=managementHarness({discovery:{configured:true,connected:false,host:{enabled:true},error:'Cannot reach the VM SSH service.'}});offline.context.renderManagement();
 assert.equal(offline.element('deploy-empty').disabled,true);assert.match(offline.element('empty-vm-note').textContent,/Cannot reach the VM/);
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

test('the Grafana link goes through the start page with the lab map or overview path and hides without the stack',()=>{
 const {context,document}=appHarness();
 context.location={protocol:'http:',hostname:'10.0.0.5'};
 const link=document.getElementById('grafana-open');link.removeAttribute=function(name){delete this[name];};
 const lab={id:'lab',name:'bgp lab',nodes:[],telemetry:{grafana:{enabled:true,port:3000,map_uid:'clab-map-abc'}}};
 context.renderGrafanaLink(lab);
 assert.equal(link.hidden,false);assert.equal(link.innerHTML,'Open lab map <span aria-hidden="true">↗</span>','the arrow is decoration, outside the accessible name');
 assert.equal(link.href,'/static/grafana.html#path=%2Fd%2Fclab-map-abc%3Fvar-lab%3Dbgp%2Blab%26refresh%3D10s&title=bgp+lab');
 assert.equal(new URLSearchParams(link.href.split('#')[1]).get('path'),'/d/clab-map-abc?var-lab=bgp+lab&refresh=10s','only the dashboard path travels; the page builds the origin');
 assert.match(link.title,/starts on the VM when needed/);
 lab.telemetry.grafana.map_uid='';context.renderGrafanaLink(lab);
 assert.equal(new URLSearchParams(link.href.split('#')[1]).get('path'),'/d/clab-lab-overview?var-lab=bgp+lab&refresh=10s');assert.equal(link.innerHTML,'Open network dashboard <span aria-hidden="true">↗</span>');
 lab.telemetry.grafana.enabled=false;context.renderGrafanaLink(lab);
 assert.equal(link.hidden,true);assert.equal(link.href,undefined);
 context.renderGrafanaLink({id:'x',name:'unlinked',nodes:[],telemetry:{status:'unmonitored',total:0}});
 assert.equal(link.hidden,true);
});
