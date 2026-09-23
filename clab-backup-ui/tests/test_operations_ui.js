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
 assert.match(hint,/these images .*: vrnetlab\/juniper_vjunos-switch:23\.2R1\.14, cjunosevolved:26\.2R1\.7-EVO, ghcr\.io\/org\/x:1\./);assert.match(hint,/Open in Lab Builder…/);
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

test('an uploaded lab file is checked in plain words, gets a location inside a trusted lab folder, and goes through the same reviewed create as a typed one',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8');
 const elements=new Map(),dialogs=[],calls=[],el=()=>({value:'',files:[],onclick:null,addEventListener(){},querySelector:()=>({textContent:''}),hidden:false});
 const context=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs:[]},activeId:'',console,document:{body:{insertAdjacentHTML(){}},querySelectorAll:()=>[],getElementById:()=>null,createElement:()=>el()},
  location:{pathname:'/'},sessionStorage:{getItem:()=>null,setItem(){}},setTimeout:()=>0,clearTimeout(){},notify(){},refresh:async()=>{},current:()=>null,busy:()=>false,
  json:async(endpoint,method,payload)=>{calls.push({endpoint,payload});if(endpoint==='/operations/parse-yaml'){if(/broken/.test(payload.options.text))throw new Error('Line 2: mapping values are not allowed here.');return {name:'Week 04: BGP/final',drawing:{nodes:[]},annotations_used:false};}return {};},
  api:async()=>({json:async()=>({roots:['/etc/containerlab','/srv/containerlab-node-manager/projects'],actions:{}})})});
 vm.runInContext(source,context);
 context.opDialog=(id,title,html)=>{for(const m of html.matchAll(/ id="([\w-]+)"/g))elements.set(m[1],el());const d={id,title,html,open:true,close(){this.open=false;},querySelector:()=>({textContent:''})};dialogs.push(d);return d;};
 context.opTask=async(dialog,fn)=>fn();
 assert.equal(context.opUploadProblem(null),'Choose a file first.');assert.match(context.opUploadProblem({name:'lab.zip',size:10}),/Its name ends in \.clab\.yaml/);
 assert.equal(context.opUploadProblem({name:'lab.clab.yaml',size:0}),'This file is empty.');assert.match(context.opUploadProblem({name:'big.yml',size:1024*1024+1}),/larger than 1 MiB/);assert.equal(context.opUploadProblem({name:'ok.clab.yml',size:1024*1024}),'');
 assert.equal(context.opUploadPath('/srv/containerlab-node-manager/projects/','Week 04: BGP/final'),'/srv/containerlab-node-manager/projects/Week-04-BGP-final.clab.yaml','no path separators or spaces from a lab name reach the path');
 assert.equal(context.opUploadPath('','../../etc'),'/srv/containerlab-node-manager/projects/etc.clab.yaml');assert.equal(context.opUploadPath('/r','***'),'/r/uploaded-lab.clab.yaml');
 context.opUpload();const upload=dialogs[0];assert.match(upload.html,/on <strong>this computer<\/strong>[^]*copied to the <strong>lab VM<\/strong> only after you confirm/);
 const next=elements.get('op-upload-next').onclick;
 await assert.rejects(next(),/Choose a file first/);
 elements.get('op-upload-file').files=[{name:'notes.txt',size:5,text:async()=>'x'}];await assert.rejects(next(),/Its name ends in/);
 elements.get('op-upload-file').files=[{name:'lab.clab.yaml',size:9,text:async()=>'name: x\nbroken: : :'}];await assert.rejects(next(),/not a containerlab topology the manager can read: Line 2/);
 elements.get('op-upload-file').files=[{name:'lab.clab.yaml',size:4,text:async()=>'a\u0000b'}];await assert.rejects(next(),/does not look like a text file/);
 assert.equal(dialogs.length,1,'a refused file opens nothing further');assert.ok(!calls.some(c=>/create|operations$/.test(c.endpoint)),'and nothing is sent to the VM');
 const text='name: bgp\ntopology:\n  nodes: {}\n';elements.get('op-upload-file').files=[{name:'bgp.clab.yaml',size:text.length,text:async()=>text}];await next();
 assert.equal(upload.open,false);const editor=dialogs[1];assert.equal(editor.title,'Uploaded lab file');assert.match(editor.html,/Read from <strong>bgp\.clab\.yaml<\/strong> on this computer\. Nothing is on the lab VM yet/);
 assert.equal(elements.get('op-edit-text').value,text);assert.equal(elements.get('op-edit-path').value,'/srv/containerlab-node-manager/projects/Week-04-BGP-final.clab.yaml');
 assert.match(editor.html,/id="op-save-yaml">Create file on the VM…/,'the only way on is the reviewed create');assert.doesNotMatch(editor.html,/id="op-deploy-project"/,'nothing can be deployed before the file is on the VM');
 assert.ok(!calls.some(c=>c.endpoint==='/operations/read'),'an upload reads nothing from the VM');
});

test('a finished create or builder save names the file to continue with; nothing else and no failure does',()=>{
 const context=vm.createContext({$:()=>null,esc:s=>String(s),state:{labs:[]},console,document:{body:{insertAdjacentHTML(){}},querySelectorAll:()=>[],getElementById:()=>null},location:{pathname:'/'},sessionStorage:{getItem:()=>null,setItem(){}},setTimeout:()=>0,clearTimeout(){}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),context);
 const p=context.opPublishedPath;
 assert.equal(p({status:'succeeded',action:'create',path:'/srv/p/bgp.clab.yaml',result:{exit_code:0}}),'/srv/p/bgp.clab.yaml');
 assert.equal(p({status:'succeeded',action:'publish',path:'',result:{published_path:'/srv/p/x/x.clab.yml'}}),'/srv/p/x/x.clab.yml');
 assert.equal(p({status:'failed',action:'create',path:'/srv/p/bgp.clab.yaml'}),'');assert.equal(p({status:'running',action:'create',path:'/srv/p/bgp.clab.yaml'}),'');
 assert.equal(p({status:'succeeded',action:'deploy',path:'/srv/p/bgp.clab.yaml'}),'','a deployed lab is running: nothing to deploy or add');assert.equal(p({status:'succeeded',action:'delete',path:'/srv/p/bgp.clab.yaml'}),'');assert.equal(p(null),'');
});

test('an optional saved map for an upload is checked the same plain way as the topology file itself',()=>{
 assert.equal(context.opUploadAnnotationsProblem(null),'','optional: choosing nothing is never a problem');
 assert.match(context.opUploadAnnotationsProblem({name:'map.txt',size:5}),/\.json file/);
 assert.equal(context.opUploadAnnotationsProblem({name:'map.json',size:0}),'This map file is empty.');
 assert.match(context.opUploadAnnotationsProblem({name:'map.json',size:1024*1024+1}),/larger than 1 MiB/);
 assert.equal(context.opUploadAnnotationsProblem({name:'map.json',size:1024*1024}),'');
 assert.throws(()=>context.opUploadAnnotationsParse('not json'),/not valid JSON/);
 assert.throws(()=>context.opUploadAnnotationsParse('[1,2]'),/one JSON object, not a list/);
 assert.throws(()=>context.opUploadAnnotationsParse('"text"'),/one JSON object/);
 assert.equal(context.opUploadAnnotationsParse('{"nodeAnnotations":[]}'),'{"nodeAnnotations":[]}','a valid object is returned unchanged');
 const path='/srv/containerlab-node-manager/projects/bgp.clab.yaml';
 assert.equal(context.opUploadAnnotationsName(path),path+'.annotations.json');
 assert.equal(context.opUploadAnnotationsNotice(null,path),'','nothing chosen: no notice');
 assert.equal(context.opUploadAnnotationsNotice({name:'bgp.clab.yaml.annotations.json'},path),'','the exact expected name: no notice');
 assert.equal(context.opUploadAnnotationsNotice({name:'other-name.json'},path),'The map file name does not match the topology name; it will be saved as bgp.clab.yaml.annotations.json.');
});

test('the dialog left for the lab builder is remembered and reopened once, on this page\'s own load; a plain visit leaves no marker',async()=>{
 const store=new Map();
 const page=vm.createContext({$:()=>null,sessionStorage:{setItem:(k,v)=>store.set(k,v),getItem:k=>store.has(k)?store.get(k):null,removeItem:k=>store.delete(k)}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),page);
 assert.equal(page.opConsumeReturn(),null,'nothing remembered yet');
 page.opRemember('vm',{path:'/etc/containerlab/demo.clab.yaml',name:'demo.clab.yaml'});
 const value=page.opConsumeReturn();
 // Built inside the vm context: compared by content (deepEqual sees a cross-realm object as unequal).
 assert.equal(JSON.stringify(value),JSON.stringify({kind:'vm',path:'/etc/containerlab/demo.clab.yaml',name:'demo.clab.yaml'}));
 assert.equal(page.opConsumeReturn(),null,'consumed once: a second read finds nothing, so a later, unrelated load never reopens it');
 // An upload has no "Open in Lab Builder…" button yet (it has no VM path to hand the builder), so a
 // remembered 'upload' marker is never produced by this page; opConsumeReturn refuses one anyway.
 store.set('op-return',JSON.stringify({kind:'upload',path:'/srv/containerlab-node-manager/projects/bgp.clab.yaml',name:'bgp.clab.yaml',text:'name: bgp\n'}));
 assert.equal(page.opConsumeReturn(),null,'an upload marker is not a kind this page reopens');
 for(const bad of ['{not json','null','"just text"',JSON.stringify({kind:'other'})]){store.set('op-return',bad);assert.equal(page.opConsumeReturn(),null,bad);}
 assert.equal(page.opConsumeReturn(),null);
 // A page that never left for the builder (a direct visit, or storage that refuses reads) never reopens anything.
 const broken=vm.createContext({$:()=>null,sessionStorage:{getItem(){throw new Error('blocked');},setItem(){throw new Error('blocked');},removeItem(){}}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),broken);
 assert.equal(broken.opConsumeReturn(),null);assert.doesNotThrow(()=>broken.opRemember('vm',{path:'/x'}));
});

test('reopening a remembered dialog rereads a VM file fresh; an upload marker (never produced today) is ignored',async()=>{
 const calls=[];
 const page=vm.createContext({$:()=>null});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),page);
 // opEdit is a real function of the script itself; replaced after load, the same way these tests
 // already replace opDialog, so opReopenReturn's call to it is observed without the dialog machinery.
 page.opEdit=(...args)=>{calls.push(args);return Promise.resolve();};
 await page.opReopenReturn(null);assert.equal(calls.length,0,'nothing to reopen: opEdit is not called at all');
 await page.opReopenReturn({kind:'vm',path:'/etc/containerlab/demo.clab.yaml',name:'demo.clab.yaml'});
 assert.equal(JSON.stringify(calls[0]),JSON.stringify(['/etc/containerlab/demo.clab.yaml']),'a VM file is reread, not restored from a stale copy');
 await page.opReopenReturn({kind:'upload',path:'/srv/containerlab-node-manager/projects/bgp.clab.yaml',name:'bgp.clab.yaml',text:'name: bgp\n'});
 assert.equal(calls.length,1,'an upload marker calls nothing: the upload dialog has no builder handoff to reopen');
 await page.opReopenReturn({kind:'vm',path:''});assert.equal(calls.length,1,'an incomplete marker calls nothing');
});

test('the deploy review shows the command directly and drops the trust warning and repeat-check caption that other reviews keep',async()=>{
 const elements=new Map(),el=()=>({value:'',onclick:null,addEventListener(){},querySelector:()=>({textContent:''}),querySelectorAll:()=>[],hidden:false});
 const dialogs=[];
 const previews={
  deploy:{action:'deploy',name:'demo',path:'/etc/containerlab/demo.clab.yaml',token:'a'.repeat(32),warnings:[],affected:[],argv:['/usr/bin/containerlab','deploy','-t','/etc/containerlab/demo.clab.yaml','--name','demo'],steps:[],diff:''},
  destroy:{action:'destroy',name:'demo',path:'/etc/containerlab/demo.clab.yaml',token:'b'.repeat(32),warnings:['Runs this trusted topology with host privileges, including its configured hooks, mounts and image pulls.'],affected:[{name:'demo-r1',state:'running'}],argv:['/usr/bin/containerlab','destroy','-t','/etc/containerlab/demo.clab.yaml'],steps:[],diff:''},
 };
 const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs:[],operations:[],git_jobs:[]},activeId:'',console,
  document:{body:{insertAdjacentHTML(){}},querySelectorAll:()=>[],getElementById:()=>null,createElement:()=>el()},
  location:{pathname:'/'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setTimeout:()=>0,clearTimeout(){},notify(){},refresh:async()=>{},current:()=>null,busy:()=>false,
  json:async(endpoint,method,payload)=>endpoint==='/operations/preview'?previews[payload.action]:{}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 c.opDialog=(id,title,html)=>{for(const m of html.matchAll(/ id="([\w-]+)"/g))elements.set(m[1],el());const d={id,title,html,open:true,close(){this.open=false;},querySelector:()=>({textContent:''}),querySelectorAll:()=>[]};dialogs.push(d);return d;};
 await c.opReview({action:'deploy',lab_id:'',name:'demo'});
 const deployHtml=dialogs.at(-1).html;
 assert.doesNotMatch(deployHtml,/host privileges/,'the deploy review drops the trust warning');
 assert.doesNotMatch(deployHtml,/this check is repeated/,'the deploy review drops the repeat-check caption');
 assert.doesNotMatch(deployHtml,/<details><summary>Technical details/,'the command is not folded away');
 assert.match(deployHtml,/<h4>Command run on the VM<\/h4><pre class="op-output">"\/usr\/bin\/containerlab" "deploy" "-t" "\/etc\/containerlab\/demo\.clab\.yaml" "--name" "demo"<\/pre>/);
 await c.opReview({action:'destroy',lab_id:'',name:'demo'});
 const destroyHtml=dialogs.at(-1).html;
 assert.match(destroyHtml,/host privileges/,'other reviews keep the trust warning');
 assert.match(destroyHtml,/this check is repeated/,'other reviews keep the repeat-check caption');
 assert.match(destroyHtml,/<details><summary>Technical details<\/summary>/,'other reviews still fold the command away');
});

test('the create review names the map file it will write, and whether it replaces one already there',async()=>{
 const elements=new Map(),el=()=>({value:'',onclick:null,addEventListener(){},querySelector:()=>({textContent:''}),querySelectorAll:()=>[],hidden:false});
 const dialogs=[];
 const previews={
  fresh:{action:'create',name:'training',path:'/srv/labs/training.clab.yaml',token:'a'.repeat(32),warnings:[],affected:[],argv:[],steps:[],diff:''},
  replace:{action:'create',name:'training',path:'/srv/labs/training.clab.yaml',token:'b'.repeat(32),warnings:['Replaces the existing map file next to this topology; a recovery copy of it is kept.'],affected:[],argv:[],steps:[],diff:''},
  none:{action:'create',name:'training',path:'/srv/labs/training.clab.yaml',token:'c'.repeat(32),warnings:[],affected:[],argv:[],steps:[],diff:''},
 };
 const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs:[],operations:[],git_jobs:[]},activeId:'',console,
  document:{body:{insertAdjacentHTML(){}},querySelectorAll:()=>[],getElementById:()=>null,createElement:()=>el()},
  location:{pathname:'/'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setTimeout:()=>0,clearTimeout(){},notify(){},refresh:async()=>{},current:()=>null,busy:()=>false,
  json:async(endpoint,method,payload)=>endpoint==='/operations/preview'?previews[payload.name]:{}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 c.opDialog=(id,title,html)=>{for(const m of html.matchAll(/ id="([\w-]+)"/g))elements.set(m[1],el());const d={id,title,html,open:true,close(){this.open=false;},querySelector:()=>({textContent:''}),querySelectorAll:()=>[]};dialogs.push(d);return d;};
 await c.opReview({action:'create',lab_id:'',name:'fresh',path:'/srv/labs/training.clab.yaml',options:{text:'name: training\n',annotations:'{}'}});
 assert.match(dialogs.at(-1).html,/Saved map: <code>training\.clab\.yaml\.annotations\.json<\/code> will be written next to the topology/);
 await c.opReview({action:'create',lab_id:'',name:'replace',path:'/srv/labs/training.clab.yaml',options:{text:'name: training\n',annotations:'{}'}});
 assert.match(dialogs.at(-1).html,/Saved map: <code>training\.clab\.yaml\.annotations\.json<\/code> — replaces the existing map file \(a recovery copy is kept\)/);
 await c.opReview({action:'create',lab_id:'',name:'none',path:'/srv/labs/training.clab.yaml',options:{text:'name: training\n'}});
 assert.doesNotMatch(dialogs.at(-1).html,/Saved map:/,'no annotations option at all: no line about a map file');
});

test('the operation output opens the moment Start lab is confirmed, does not pop back up once closed on purpose, and a fresh launch or View output still work',async()=>{
 const elements=new Map();
 for(const id of ['op-job-banner','op-job-output','op-job-result'])elements.set(id,{hidden:false,className:'',textContent:'',innerHTML:'',scrollTop:0,scrollHeight:0,clientHeight:0});
 const jobs={a:{id:'a',action:'deploy',name:'demo',lab_id:'lab1',status:'running',output:''},b:{id:'b',action:'deploy',name:'demo',lab_id:'lab1',status:'running',output:''}};
 const timers=[];
 const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs:[]},activeId:'lab1',console,
  document:{getElementById:()=>null},setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},
  api:async url=>({json:async()=>jobs[url.split('/').pop()]}),refresh:async()=>{}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 const dialogs={};
 c.opDialog=id=>{if(!dialogs[id])dialogs[id]={id,open:true,onclose:null,classList:{toggle(){}},close(){if(this.open){this.open=false;if(typeof this.onclose==='function')this.onclose();}},querySelector:()=>({textContent:''}),querySelectorAll:()=>[]};else dialogs[id].open=true;return dialogs[id];};
 await c.opShowJob('a',{auto:true});
 assert.equal(dialogs['operation-output'].open,true,'opens right away, no second click');
 dialogs['operation-output'].close();
 await c.opShowJob('a',{auto:true});
 assert.equal(dialogs['operation-output'].open,false,'a deliberately closed dialog is not reopened automatically for the same launch');
 await c.opShowJob('a');
 assert.equal(dialogs['operation-output'].open,true,'View output always reopens it');
 dialogs['operation-output'].close();
 await c.opShowJob('b',{auto:true});
 assert.equal(dialogs['operation-output'].open,true,'a fresh launch (a different job id) opens again');
 // Moving to another lab closes an auto-opened dialog for it, and it does not come back on its own there.
 const tick=timers.pop();c.activeId='lab2';await tick();
 assert.equal(dialogs['operation-output'].open,false,'navigating away closes it');
 c.activeId='lab1';await c.opShowJob('b',{auto:true});
 assert.equal(dialogs['operation-output'].open,false,'still not reopened for that same job once it left');
});

test('the topology preview drops the caption in both branches, sizes the dialog to the viewport, and fits the map on open',()=>{
 const elements=new Map();
 const makeSvg=()=>{const attrs={};return {setAttribute(name,value){attrs[name]=value;},getAttribute:name=>attrs[name]};};
 elements.set('op-preview-map',makeSvg());
 const fitCalls=[],resizeListeners=[];
 const dialogClasses=[];
 const dialogListeners={};
 const dialog={classList:{add(cls){dialogClasses.push(cls);}},addEventListener(type,fn){(dialogListeners[type]=dialogListeners[type]||[]).push(fn);},close(){(dialogListeners.close||[]).forEach(fn=>fn());}};
 const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),
  topologyMarkup:drawing=>'<g id="topology-scene" data-nodes="'+drawing.nodes.length+'"></g>',
  measureTopology:svg=>{fitCalls.push(svg);return [10,20,30,40];},
  window:{addEventListener(type,fn){if(type==='resize')resizeListeners.push(fn);},removeEventListener(type,fn){const i=resizeListeners.indexOf(fn);if(i>=0)resizeListeners.splice(i,1);}},
  requestAnimationFrame:fn=>fn()});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 let capturedBody='',capturedTitle='';
 c.opDialog=(id,title,body)=>{capturedBody=body;capturedTitle=title;return dialog;};
 const returned=c.opMapPreview({nodes:[],links:[],decorations:[]},'demo',true);
 assert.equal(returned,dialog,'the dialog opDialog built is returned unchanged');
 assert.equal(capturedTitle,'Topology preview · demo','the title stays, only the caption goes');
 assert.doesNotMatch(capturedBody,/<p>/,'no caption paragraph — the positioned branch');
 assert.doesNotMatch(capturedBody,/Wiring from the topology file/);
 assert.match(capturedBody,/^<svg id="op-preview-map" class="topology-map op-layout-map"/,'the map is the whole body');
 assert.deepEqual(dialogClasses,['dialog-viewport'],'sized to the viewport, not the dialog default');
 assert.equal(fitCalls.length,1,'fit runs once on open (via requestAnimationFrame)');
 assert.equal(fitCalls[0],elements.get('op-preview-map'));
 assert.equal(elements.get('op-preview-map').getAttribute('viewBox'),'10 20 30 40','the viewBox comes from the reused bounding-box routine');
 assert.equal(elements.get('op-preview-map').getAttribute('preserveAspectRatio'),'xMidYMid meet');
 assert.equal(resizeListeners.length,1,'refits on a resize while the dialog stays open');
 resizeListeners[0]();
 assert.equal(fitCalls.length,2);
 dialog.close();
 assert.equal(resizeListeners.length,0,'the resize listener leaves with the dialog');
 c.opMapPreview({nodes:[],links:[],decorations:[]},'fresh',false);
 assert.doesNotMatch(capturedBody,/<p>/,'no caption paragraph — the unpositioned branch either');
 assert.doesNotMatch(capturedBody,/default grid/);
});
