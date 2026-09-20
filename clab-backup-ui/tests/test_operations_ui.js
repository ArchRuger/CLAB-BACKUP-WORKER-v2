const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({$:()=>null,esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),context);
test('inspection table handles grouped JSON surrounded by CLI log lines',()=>{
 const raw='INFO inspecting\n'+JSON.stringify({training:[{name:'clab-training-r1',absLabPath:'/etc/lab.clab.yaml',kind:'cisco_xrv9k',image:'router:1',state:'running',health_status:'healthy',ipv4_address:'172.20.20.2/24',ipv6_address:'2001:db8::2/64'}]},null,2)+'\nFinished\n';
 const rows=context.opInspectionRows(raw);assert.equal(rows.length,1);
 assert.equal(rows[0].lab,'training');assert.equal(rows[0].state,'running · healthy');assert.equal(rows[0].topology,'/etc/lab.clab.yaml');
 const table=context.opInspectionTable(rows);assert.match(table,/router:1/);assert.match(table,/2001:db8::2\/64/);assert.match(table,/<th>State \/ health<\/th>/);
});
test('flat inspection rows use lab identity and escape untrusted output',()=>{
 const rows=context.opInspectionRows(JSON.stringify([{lab_name:'demo',name:'<script>bad</script>',labels:{'clab-topo-file':'/tmp/a.yaml'},state:'exited'}]));
 assert.equal(rows[0].lab,'demo');assert.equal(rows[0].topology,'/tmp/a.yaml');
 const table=context.opInspectionTable(rows);assert.doesNotMatch(table,/<script>/);assert.match(table,/&lt;script&gt;/);
});
test('incomplete, empty and failed inspection output falls back to diagnostics',()=>{
 for(const raw of ['[]','{}','Error: permission denied','{"lab":[','null'])assert.equal(context.opInspectionRows(raw).length,0);
});

test('topology browser retains folders and supported topology suffixes only',()=>{
 const entries=['demo.clab.yaml','other.clab.yml','UPPER.CLAB.YAML','demo.clab.yaml.annotations.json','ansible-inventory.yml','topology-data.json','notes.txt'].map(name=>({name,directory:false}));
 entries.push({name:'nested',directory:true});
 assert.deepEqual(Array.from(context.opTopologyEntries(entries),e=>e.name),['demo.clab.yaml','other.clab.yml','UPPER.CLAB.YAML','nested']);
});

test('quick start deploys absent labs, starts stopped labs and guards unknown or busy state',()=>{
 const lab={vm_project_path:'/etc/containerlab/demo.clab.yaml',deployment:{status:'Not deployed'}};
 let actions=context.opQuickActions(lab,{connected:true});
 assert.equal(actions.startAction,'deploy');assert.equal(actions.canStart,true);assert.equal(actions.canDestroy,false);
 lab.deployment.status='Stopped';actions=context.opQuickActions(lab,{connected:true});
 assert.equal(actions.startAction,'start');assert.equal(actions.canStart,true);assert.equal(actions.canDestroy,true);
 lab.deployment.status='Running';assert.equal(context.opQuickActions(lab,{connected:true}).canStart,false);
 for(const status of ['Unknown','Unlinked']){
  lab.deployment.status=status;actions=context.opQuickActions(lab,{connected:true});assert.equal(actions.canStart,false);assert.equal(actions.canDestroy,false);
 }
 lab.deployment.status='Stopped';
 for(const actions of [context.opQuickActions(lab,{connected:false}),context.opQuickActions(lab,{connected:true},true),context.opQuickActions({...lab,vm_project_path:''},{connected:true})]){
  assert.equal(actions.canStart,false);assert.equal(actions.canDestroy,false);
 }
});

test('operation output leads with a green success banner and a red failure banner',()=>{
 const good=context.opJobBanner({action:'deploy',name:'ceos-pair',status:'succeeded',exit_code:0,message:'Operation completed'});
 assert.equal(JSON.stringify(good),JSON.stringify({tone:'good',title:'✔ Start lab succeeded',detail:'ceos-pair · Operation completed',exit:'Exit code 0'}),'the exit code is a separate detail, never part of the headline');
 const bad=context.opJobBanner({action:'destroy',name:'ceos-pair',status:'failed',exit_code:1,message:'Host command returned an error'});
 assert.equal(bad.tone,'bad');assert.equal(bad.title,'✖ Destroy lab failed');assert.match(bad.detail,/Host command/);assert.equal(bad.exit,'Exit code 1');
 const running=context.opJobBanner({action:'inspect',name:'ceos-pair',status:'running',exit_code:null,message:'Executing on the VM'});
 assert.equal(running.tone,'running');assert.equal(running.title,'Show running devices running…');assert.equal(running.detail,'ceos-pair · Executing on the VM');assert.equal(running.exit,'');
 assert.equal(context.opJobBanner({action:'clone',name:'x',status:'interrupted',exit_code:null,message:'Manager restarted'}).tone,'bad');
 // A failure a student can act on is said in words: an image the VM does not have, named as the topology names it.
 const pull='INFO Pulling image image=docker.io/library/cjunosevolved:26.2R1.7-EVO\nERRO Failed to pull image image=docker.io/vrnetlab/juniper_vjunos-switch:23.2R1.14 err="pull access denied"\nERRO Failed to pull image image=docker.io/library/cjunosevolved:26.2R1.7-EVO err="pull access denied"\nERRO Failed to pull image image=ghcr.io/org/x:1 err="denied"\n';
 const hint=context.opJobBanner({action:'deploy',name:'l',status:'failed',exit_code:1,message:'Host command returned an error',output:pull}).hint;
 assert.match(hint,/these images .*: vrnetlab\/juniper_vjunos-switch:23\.2R1\.14, cjunosevolved:26\.2R1\.7-EVO, ghcr\.io\/org\/x:1\./);assert.match(hint,/Edit visually/);
 assert.equal(context.opJobBanner({action:'deploy',name:'l',status:'succeeded',exit_code:0,output:pull}).hint,undefined);assert.equal(bad.hint,undefined);
});
test('deploy lab saves the workspace first and reuses one that already tracks the deployment',async()=>{
 const registered=[],settings=[],items=new Map();
 const page=vm.createContext({$:()=>null,esc:String,state:{labs:[{id:'old',deployment_name:'ceos-pair',vm_project_path:'/etc/containerlab/ceos-pair/ceos-pair.clab.yaml'}]},activeId:'',
  sessionStorage:{setItem:(k,v)=>items.set(k,v),getItem:k=>items.get(k)},FormData:class{constructor(){this.parts=[];}append(...a){this.parts.push(a);}},Blob:class{constructor(parts){this.parts=parts;}},
  api:async(url,options)=>{registered.push({url,options});return {json:async()=>({id:'new'})};},
  json:async(url,method,data)=>{settings.push({url,method,data});return {};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),page);
 const source={text:'name: fresh\ntopology:\n  nodes:\n    r1:\n      kind: linux\n'};
 assert.equal(await page.opSaveWorkspace('/etc/containerlab/fresh/fresh.clab.yaml',source,{name:'fresh'}),'new');
 assert.equal(registered[0].url,'/lab-definitions');assert.equal(registered[0].options.method,'POST');
 assert.equal(registered[0].options.body.parts[0][2],'fresh.clab.yaml');
 assert.equal(JSON.stringify(settings[0]),JSON.stringify({url:'/labs/new/operations-settings',method:'PUT',data:{path:'/etc/containerlab/fresh/fresh.clab.yaml'}}));
 assert.equal(page.activeId,'new');assert.equal(items.get('activeLab'),'new');
 assert.equal(await page.opSaveWorkspace('/etc/containerlab/ceos-pair/ceos-pair.clab.yaml',source,{name:'ceos-pair'}),'old');
 assert.equal(registered.length,1,'an existing workspace is never registered twice');assert.equal(settings[1].url,'/labs/old/operations-settings');
 assert.equal(await page.opSaveWorkspace('/other.clab.yaml',source,{name:'other'},'given'),'given');
 assert.equal(registered.length,1);
});
test('deployment landing page opens topology browser only on an explicit click',async()=>{
 const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,{});return elements.get(id);};
 let browses=0;
 const page=vm.createContext({document:{getElementById:element,addEventListener:()=>{}},location:{hash:'#mode=folder'},URLSearchParams,
  fetch:async()=>({ok:true,json:async()=>({labs:[],jobs:[],operations:[]})}),opBrowse:async()=>browses++});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/workspace.js'),'utf8'),page);
 await page.launchWorkspace();
 assert.equal(browses,0);assert.equal(element('workspace-title').textContent,'Deploy a new lab');
});

test('browse renders before capabilities settle, survives failure and retries folders',async()=>{
 const elements=new Map();
 const element=()=>({children:[],isConnected:true,textContent:'',append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;}});
 const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
 let rejectCaps,folderCalls=0;
 const page=vm.createContext({$:id=>id==='import-top'?null:get(id),esc:String,document:{createElement:element},
  json:async(url,method,data)=>{
   if(data.path==='/root/nested'){
    if(++folderCalls===1)throw new Error('Temporary folder failure');
    return {entries:[{name:'lab.clab.yaml',path:'/root/nested/lab.clab.yaml',directory:false}]};
   }
   return {path:'/root',entries:[{name:'nested',path:'/root/nested',directory:true}]};
  },api:()=>new Promise((resolve,reject)=>{rejectCaps=reject;})});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),page);
 page.opDialog=()=>({querySelector:()=>get('help')});
 await page.opBrowse('/root');
 assert.equal(get('op-file-tree').children.length,1);
 assert.equal(get('op-clone').disabled,true);
 rejectCaps(new Error('Capability failure'));
 await new Promise(resolve=>setImmediate(resolve));
 assert.match(get('help').textContent,/Files are available/);
 const folder=get('op-file-tree').children[0];folder.open=true;await folder.ontoggle();
 assert.match(folder.children[1].textContent,/Close and reopen/);
 folder.open=false;await folder.ontoggle();folder.open=true;await folder.ontoggle();
 assert.equal(folderCalls,2);assert.equal(folder.children[1].children[0].textContent,'◇ lab.clab.yaml');
});

test('telemetry settings dialog reads the lab view, saves the setting and retries failed nodes',async()=>{
 const calls=[],elements=new Map();
 // Only the dialog and its controls exist; the workspace elements operations.js wires at load time do not.
 const el=id=>{if(!/^tele/.test(id))return null;if(!elements.has(id))elements.set(id,{id,innerHTML:'',checked:false,value:'',open:false,disabled:false,textContent:'',querySelector(){return {textContent:'',onclick:null};},querySelectorAll(){return [];},showModal(){this.open=true;},close(){this.open=false;}});return elements.get(id);};
 const view={enabled:true,linked:true,unavailable:'',settings:{auto:true,decided:true,profile_id:'p'},password_profiles:[{id:'p',label:'Ops',platform:'arista_ceos'}],
  summary:{total:2,streaming:1,failed:1},nodes:[{name:'clab-demo-r1',short_name:'r1',state:'streaming',message:'ok'},{name:'clab-demo-r2',short_name:'r2',state:'failed',message:'gNMI login refused'}]};
 const c=vm.createContext({$:el,esc:context.esc,activeId:'lab',state:{labs:[{id:'lab',name:'demo'}]},console,JSON,
  document:{createElement(){return el('created');},body:{append(){}},querySelectorAll(){return [];}},
  api:async url=>{calls.push(url);if(url==='/telemetry/grafana'&&grafana instanceof Error)throw grafana;return {json:async()=>url==='/telemetry/grafana'?grafana:view};},
  json:async(url,method,data)=>{calls.push([url,method,data]);return url==='/telemetry/grafana/stop'?{enabled:true,port:3000,running:false,idle_minutes:15}:{started:[]};},
  notify(){},refresh:async()=>{calls.push('refresh');},confirm:()=>true});
 let grafana={enabled:true,port:3000,running:true,idle_minutes:15};
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 const dialog=await c.openTelemetrySettings('lab');
 assert.equal(calls[0],'/labs/lab/telemetry');assert.equal(calls[1],'/telemetry/grafana');
 assert.match(dialog.innerHTML,/Telemetry is on: 2 supported devices · 1 streaming · 1 failed\. Open the network dashboard to see the data\./);
 assert.match(dialog.innerHTML,/<strong>r2<\/strong> \(failed\): gNMI login refused/);assert.doesNotMatch(dialog.innerHTML,/<strong>r1<\/strong>/);
 assert.match(dialog.innerHTML,/<option value="p" selected>Ops · arista_ceos<\/option>/);assert.match(dialog.innerHTML,/id="tele-retry"/);
 assert.match(dialog.innerHTML,/id="tele-remove" disabled/,'removal needs automatic telemetry off first');
 assert.match(dialog.innerHTML,/Dashboard: running \(port 3000\); stops automatically after 15 minutes without a viewer\./);assert.match(dialog.innerHTML,/id="tele-grafana-stop"/);
 await el('tele-grafana-stop').onclick();
 assert.equal(JSON.stringify(calls[2]),JSON.stringify(['/telemetry/grafana/stop','POST',{}]));
 assert.equal(el('tele-grafana').textContent,'Dashboard: stopped; it starts when you open it from Tools › Telemetry.');
 el('tele-auto').checked=false;el('tele-profile').value='';
 await el('tele-save').onclick();
 assert.equal(JSON.stringify(calls[3]),JSON.stringify(['/labs/lab/telemetry/settings','PUT',{auto:false,profile_id:''}]));assert.equal(calls[4],'refresh');assert.equal(dialog.open,false);
 await el('tele-retry').onclick();
 assert.equal(JSON.stringify(calls[5]),JSON.stringify(['/labs/lab/telemetry/retry','POST',{}]));
 grafana={enabled:true,port:3000,running:false,idle_minutes:0};
 assert.match((await c.openTelemetrySettings('lab')).innerHTML,/Dashboard: stopped; it starts when you open it from Tools › Telemetry\./);
 assert.doesNotMatch((await c.openTelemetrySettings('lab')).innerHTML,/tele-grafana-stop/);
 grafana=new Error('manager restarting');
 assert.match((await c.openTelemetrySettings('lab')).innerHTML,/Dashboard: status unavailable\./,'the dialog still opens when the Grafana state cannot be read');
 assert.equal(c.telemetryGrafanaText({enabled:true,port:3000,running:true,idle_minutes:0}),'Dashboard: running (port 3000); automatic stop is off.');
 assert.equal(c.telemetryGrafanaText({enabled:false}),'Dashboard: not installed on this VM.');
 assert.equal(c.telemetryGrafanaText({enabled:true,running:null}),'Dashboard: not checked yet.');
 grafana={enabled:true,port:3000,running:true,idle_minutes:15};
 view.settings={auto:false,decided:false};view.summary={total:0};view.nodes=[];
 const undecided=await c.openTelemetrySettings('lab');
 assert.match(undecided.innerHTML,/hasn’t been set up for this lab/);assert.doesNotMatch(undecided.innerHTML,/tele-retry/);
 view.enabled=false;view.unavailable='pygnmi is not installed in this image.';
 assert.match((await c.openTelemetrySettings('lab')).innerHTML,/pygnmi is not installed/);
 assert.match((await c.openTelemetrySettings('lab')).innerHTML,/id="tele-save" disabled/);
});
test('destroy asks for cleanup unless the installed containerlab is known to lack it',()=>{
 assert.equal(JSON.stringify(context.opDestroyOptions({actions:{destroy:{available:true,cleanup:true}}})),'{"cleanup":true}');
 assert.equal(JSON.stringify(context.opDestroyOptions(null)),'{"cleanup":true}','unknown capabilities still ask; the helper refuses an unsupported flag itself');
 assert.equal(JSON.stringify(context.opDestroyOptions({actions:{destroy:{available:true,cleanup:false}}})),'{}');
 const button=context.opCommand('destroy','Destroy deployment',context.opDestroyOptions({actions:{destroy:{cleanup:true}}}));
 assert.match(button,/data-op-action="destroy"/);assert.match(button,/data-op-options="\{&quot;cleanup&quot;:true\}"/);
});
test('the annotations file beside a topology places the preview and the saved workspace',async()=>{
 const calls=[],registered=[];
 const files={'/etc/containerlab/demo/demo.clab.yaml.annotations.json':'{"nodeAnnotations":[{"id":"r1","position":{"x":380,"y":360}}]}'};
 const page=vm.createContext({$:()=>null,esc:String,state:{labs:[]},activeId:'',sessionStorage:{setItem(){},getItem(){}},
  FormData:class{constructor(){this.parts=[];}append(...a){this.parts.push(a);}},Blob:class{constructor(parts,options){this.parts=parts;this.type=options?.type;}},
  api:async(url,options)=>{registered.push({url,options});return {json:async()=>({id:'new'})};},
  json:async(url,method,data)=>{calls.push([url,data]);
   if(url==='/operations/read'){if(!files[data.path])throw new Error('This path is outside the trusted lab roots.');return {text:files[data.path]};}
   if(url==='/operations/parse-yaml')return {name:'demo',drawing:{nodes:[{id:'r1'}]},annotations_used:/380/.test(data.options.annotations||'')};
   return {};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),page);
 const source={text:'name: demo\ntopology:\n  nodes:\n    r1:\n      kind: linux\n'};
 const placed=await page.opParse('/etc/containerlab/demo/demo.clab.yaml',source.text);
 assert.equal(calls[0][1].path,'/etc/containerlab/demo/demo.clab.yaml.annotations.json');
 assert.equal(calls[1][1].options.annotations,files[calls[0][1].path],'the file travels with the YAML to the parser');
 assert.equal(placed.annotations_used,true);assert.equal(placed.annotations,files[calls[0][1].path]);
 const form=page.opWorkspaceForm('/etc/containerlab/demo/demo.clab.yaml',source,placed);
 assert.deepEqual(form.parts.map(p=>[p[0],p[2]]),[['definition','demo.clab.yaml'],['annotations','demo.clab.yaml.annotations.json']]);
 assert.equal(form.parts[1][1].type,'application/json');
 // No file beside the topology (or an unreadable one): the grid, and nothing extra in the form.
 const grid=await page.opParse('/etc/containerlab/other/other.clab.yaml',source.text);
 assert.equal(grid.annotations_used,false);assert.equal(grid.annotations,'');
 assert.deepEqual(page.opWorkspaceForm('/etc/containerlab/other/other.clab.yaml',source,grid).parts.map(p=>p[0]),['definition']);
 assert.equal((await page.opParse('',source.text)).annotations,'','a new, unsaved topology has no file beside it');
 assert.equal(calls.filter(c=>c[0]==='/operations/read').length,2);
 await page.opSaveWorkspace('/etc/containerlab/demo/demo.clab.yaml',source,placed);
 assert.equal(registered[0].options.body.parts.length,2,'Deploy lab registers the annotations with the YAML');
});
