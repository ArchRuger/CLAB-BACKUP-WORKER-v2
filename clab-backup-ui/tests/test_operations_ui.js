const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({$:()=>null,esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),context);
test('a review names each image of the topology with what the VM said: on the VM, pullable, not found anywhere, unanswered',()=>{
 const line=item=>context.opImageLine(item);
 assert.equal(line({reference:'n24l/ceos:4.35.0F',nodes:['ceos1','ceos2'],local:true,registry:'skipped'}),'n24l/ceos:4.35.0F (ceos1, ceos2): on the VM.');
 assert.equal(line({reference:'ghcr.io/srl-labs/network-multitool:latest',nodes:['host1'],local:false,registry:'found'}),'ghcr.io/srl-labs/network-multitool:latest (host1): not on the VM yet; the deploy pulls it from its registry.');
 assert.equal(line({reference:'vrnetlab/cisco_xrv9k:24.3.1',nodes:['xr1'],local:false,registry:'not-found'}),'vrnetlab/cisco_xrv9k:24.3.1 (xr1): not on the VM and no registry offers it (not there, or it needs a login on the VM). The deploy fails for xr1.');
 assert.equal(line({reference:'bad name',nodes:['h1'],local:false,registry:'invalid'}),'bad name (h1): not a usable image name. The deploy fails for h1.');
 assert.equal(line({reference:'r.example/z:1',nodes:[],local:false,registry:'unreachable'}),'r.example/z:1: not on the VM; its registry did not answer, so the deploy would try to pull it.');
 assert.equal(line({reference:'a:1',local:false,registry:'unknown'}),'a:1: not on the VM; whether it can be pulled could not be checked.');
 assert.equal(line({reference:'a:1',available:false}),'a:1: this VM has no Docker client the manager can ask; checked at deploy time.');
 assert.deepEqual(context.opImageMissing([{reference:'a',local:true,registry:'skipped'},{reference:'b',local:false,registry:'not-found'},{reference:'c',local:false,registry:'not-found',available:false},{reference:'d',local:false,registry:'invalid'}]).map(i=>i.reference),['b','d']);
});
test('opImageAttention keeps only images a student must act on: not local and not pullable, or no Docker client at all',()=>{
 const refs=rows=>[...context.opImageAttention(rows)].map(i=>i.reference);
 assert.deepEqual(refs([
  {reference:'local',local:true,registry:'skipped'},{reference:'pullable',local:false,registry:'found'},
  {reference:'nf',local:false,registry:'not-found'},{reference:'bad',local:false,registry:'invalid'},{reference:'down',local:false,registry:'unreachable'},
  {reference:'unk',local:false,registry:'unknown'},{reference:'none',local:false},{reference:'nodocker',available:false},{reference:'nodocker-local',local:true,available:false},
 ]),['nf','bad','down','unk','none','nodocker','nodocker-local']);
 assert.deepEqual(refs([{reference:'a',local:true},{reference:'b',local:false,registry:'found'}]),[],'all clear: nothing to list');
 assert.deepEqual(refs(null),[]);
});
test('the review image check lists only attention rows, removes its status line, hides the section when all is clear and says once that a failed check failed',async()=>{
 const mk=()=>{
  const node={list:{innerHTML:'',isConnected:true},status:{removed:false,className:'',textContent:'',remove(){this.removed=true;}},summary:{textContent:''},fix:{hidden:true,textContent:''}};
  node.section={hidden:true,querySelector:()=>node.summary};
  node.dialog={open:true,querySelector:sel=>({'#op-review-images':node.list,'#op-review-images-status':node.status,'#op-review-images-section':node.section,'#op-review-images-fix':node.fix})[sel]||null};
  return node;
 };
 const run=async(answer)=>{const n=mk();context.json=async()=>{if(answer instanceof Error)throw answer;return answer;};
  await context.opReviewImages(n.dialog,[{reference:'a:1',nodes:['r1']},{reference:'b:2',nodes:['r2']},{reference:'c:3',nodes:[]}]);return n;};
 const clear=await run({images:[{reference:'a:1',local:true,registry:'skipped'},{reference:'b:2',local:false,registry:'found'},{reference:'c:3',local:true,registry:'skipped'}]});
 assert.equal(clear.status.removed,true);assert.equal(clear.section.hidden,true,'no empty Images heading');assert.equal(clear.list.innerHTML,'');assert.equal(clear.fix.hidden,true);
 const some=await run({images:[{reference:'a:1',local:true},{reference:'b:2',local:false,registry:'not-found'},{reference:'c:3',local:false,registry:'unreachable'}]});
 assert.equal(some.section.hidden,false);assert.equal(some.summary.textContent,'Images needing attention (2)');
 assert.match(some.list.innerHTML,/class="op-image-missing">b:2 \(r2\): not on the VM and no registry offers it/);assert.match(some.list.innerHTML,/c:3: not on the VM; its registry did not answer/);assert.doesNotMatch(some.list.innerHTML,/a:1/);
 assert.equal(some.fix.hidden,false);assert.equal(some.fix.textContent,'The devices using it stay down after the deploy. Choose an image the VM has, or load it on the VM first.','the single fix sentence sits under the list heading');assert.doesNotMatch(some.fix.textContent,/b:2/,'the image is named once, in the list');
 const failed=await run(new Error('boom'));
 assert.equal(failed.status.removed,false);assert.match(failed.status.textContent,/Images could not be checked right now; the deploy reports any image it cannot pull\./);assert.equal(failed.section.hidden,true);
 const stale=mk();stale.dialog.open=false;context.json=async()=>({images:[]});await context.opReviewImages(stale.dialog,[{reference:'a:1'}]);assert.equal(stale.status.removed,false,'a closed dialog is left alone');
});
test('inspection table handles grouped JSON surrounded by CLI log lines',()=>{
 const raw='INFO inspecting\n'+JSON.stringify({training:[{name:'clab-training-r1',absLabPath:'/etc/lab.clab.yaml',kind:'cisco_xrv9k',image:'router:1',state:'running',health_status:'healthy',ipv4_address:'172.20.20.2/24',ipv6_address:'2001:db8::2/64'}]},null,2)+'\nFinished\n';
 const rows=context.opInspectionRows(raw);assert.equal(rows.length,1);
 assert.equal(rows[0].lab,'training');assert.equal(rows[0].state,'running · healthy');assert.equal(rows[0].topology,'/etc/lab.clab.yaml');
 const table=context.opInspectionTable(rows);assert.match(table,/router:1/);assert.match(table,/2001:db8::2\/64/);assert.match(table,/<th scope="col" aria-sort="none"><button type="button" class="op-sort" data-op-sort="state">State \/ health<\/button><\/th>/);
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
 assert.match(hint,/these images .*: vrnetlab\/juniper_vjunos-switch:23\.2R1\.14, cjunosevolved:26\.2R1\.7-EVO, ghcr\.io\/org\/x:1\./);assert.match(hint,/choose Edit topology…/);
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
 // An upload has no "Edit topology…" button yet (it has no VM path to hand the builder), so a
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

test('L-31: confirming a review remembers the confirmed request by job id, and opRetryRequest hands it back for Try again',async()=>{
 const elements=new Map(),el=()=>({value:'',onclick:null,addEventListener(){},querySelector:()=>({textContent:''}),querySelectorAll:()=>[],hidden:false});
 const remembered=[];
 const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs:[],operations:[],git_jobs:[]},activeId:'',console,
  document:{body:{insertAdjacentHTML(){}},querySelectorAll:()=>[],getElementById:()=>null,createElement:()=>el()},
  location:{pathname:'/'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setTimeout:()=>0,clearTimeout(){},notify(){},refresh:async()=>{},current:()=>null,busy:()=>false,
  rememberJobRequest:(id,request)=>{remembered.push([id,request]);return true;},
  json:async(endpoint)=>endpoint==='/operations/preview'?{action:'destroy',name:'demo',path:'/etc/containerlab/demo.clab.yaml',token:'a'.repeat(32),warnings:[],affected:[],argv:[],steps:[],diff:''}:{id:'job-9',action:'destroy'}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 c.opDialog=(id,title,html)=>{for(const m of html.matchAll(/ id="([\w-]+)"/g))elements.set(m[1],el());return {id,open:true,close(){this.open=false;},querySelector:()=>({textContent:''}),querySelectorAll:()=>[]};};
 await c.opReview({action:'destroy',lab_id:'lab',options:{cleanup:true}});
 await elements.get('op-confirm').onclick();
 assert.equal(remembered.length,1);assert.equal(remembered[0][0],'job-9');
 assert.deepEqual(JSON.parse(JSON.stringify(remembered[0][1])),{action:'destroy',lab_id:'lab',options:{cleanup:true}},'the options the student confirmed, not the defaults');
 // With a stored request the retry is that request; without one only options-free actions are repeated from their name.
 c.jobRequest=id=>id==='job-9'?remembered[0][1]:null;
 assert.deepEqual(JSON.parse(JSON.stringify(c.opRetryRequest({id:'job-9',action:'destroy'},'lab'))),{action:'destroy',lab_id:'lab',options:{cleanup:true}});
 assert.deepEqual(JSON.parse(JSON.stringify(c.opRetryRequest({id:'x',action:'destroy'},'lab'))),{lab_id:'lab',action:'destroy',options:{cleanup:true}});
 assert.deepEqual(JSON.parse(JSON.stringify(c.opRetryRequest({id:'x',action:'restart-node',node:'clab-a-r1'},'lab'))),{lab_id:'lab',action:'restart-node',node:'clab-a-r1',options:{}});
 for(const action of ['deploy','redeploy','create','revise','publish','clone'])assert.equal(c.opRetryRequest({id:'x',action},'lab'),null,action+' is never repeated from its name alone');
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
 assert.doesNotMatch(dialogs.at(-1).html,/Command run on the VM|Technical details/,'create has no real command: no placeholder block and no empty Technical details');
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
 const fitCalls=[],resizeListeners=[],renderOptions=[];
 const dialogClasses=[];
 const dialogListeners={};
 const dialog={classList:{add(cls){dialogClasses.push(cls);}},addEventListener(type,fn){(dialogListeners[type]=dialogListeners[type]||[]).push(fn);},close(){(dialogListeners.close||[]).forEach(fn=>fn());}};
 const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),
  topologyMarkup:(drawing,states,options)=>{renderOptions.push(options);return '<g id="topology-scene" data-nodes="'+drawing.nodes.length+'"></g>';},
  measureTopology:svg=>{fitCalls.push(svg);return [10,20,30,40];},
  window:{addEventListener(type,fn){if(type==='resize')resizeListeners.push(fn);},removeEventListener(type,fn){const i=resizeListeners.indexOf(fn);if(i>=0)resizeListeners.splice(i,1);}},
  requestAnimationFrame:fn=>fn()});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 let capturedBody='',capturedTitle='';
 c.opDialog=(id,title,body)=>{capturedBody=body;capturedTitle=title;return dialog;};
 const returned=c.opMapPreview({nodes:[],links:[],decorations:[]},'demo',true);
 assert.equal(returned,dialog,'the dialog opDialog built is returned unchanged');
 assert.deepEqual(JSON.parse(JSON.stringify(renderOptions)),[{preview:true}],'the preview renders a file, not a lab map (no "Not in this lab", no buttons)');
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

test('Restart device is offered for a deployed device of a running or partly running lab, and every refusal has a reason',()=>{
 const lab={id:'a',name:'square',deployment_name:'square',vm_project_path:'/srv/p/square.clab.yml',deployment:{status:'Running'}};
 const dev={name:'clab-square-ceos',short_name:'ceos',discovered:true,runtime_state:'running'};
 const plain=o=>JSON.parse(JSON.stringify(o));
 assert.deepEqual(plain(context.opRestartState(lab,dev,{connected:true})),{ok:true,reason:''});
 assert.deepEqual(plain(context.opRestartState(lab,{...dev,runtime_state:'exited'},{connected:true})),{ok:true,reason:''},'a stopped device takes the start/restore path');
 assert.deepEqual(plain(context.opRestartState({...lab,deployment:{status:'Partially running'}},dev,{connected:true})),{ok:true,reason:''});
 assert.deepEqual(plain(context.opRestartState(lab,{...dev,ssh_ready:false,nos_login:{status:'failed'}},{connected:true})),{ok:true,reason:''},'a device whose login fails is exactly the one to restart');
 const cases=[
  [context.opRestartState(lab,dev,{connected:false}),'Connect the VM first'],
  [context.opRestartState(lab,dev,{connected:true},true),'Wait for the current operation to finish'],
  [context.opRestartState({...lab,vm_project_path:''},dev,{connected:true}),'This lab has no topology file on the VM (Advanced › Deployment details)'],
  [context.opRestartState({...lab,deployment_name:'',deployment:{status:'Unlinked'}},dev,{connected:true}),'The lab is not matched to a running lab'],
  [context.opRestartState({...lab,deployment:{status:'Unknown'}},dev,{connected:true}),'Lab status is unknown — refresh the lab list'],
  [context.opRestartState({...lab,deployment:{status:'Not deployed'}},dev,{connected:true}),'The lab is not running'],
  [context.opRestartState(lab,{...dev,discovered:false,runtime_state:'absent'},{connected:true}),'ceos is not deployed on the VM'],
  [context.opRestartState(null,dev,{connected:true}),'This device is not in the lab'],
  [context.opRestartState(lab,null,{connected:true}),'This device is not in the lab'],
 ];
 for(const [result,reason] of cases){assert.equal(result.ok,false,reason);assert.equal(result.reason,reason);}
 vm.runInContext("opCaps={actions:{'restart-node':{available:false}}}",context);
 assert.match(context.opRestartState(lab,dev,{connected:true}).reason,/cannot restart one device/);
 vm.runInContext("opCaps={actions:{'restart-node':{available:true}}}",context);assert.equal(context.opRestartState(lab,dev,{connected:true}).ok,true);
 vm.runInContext("opCaps={actions:{restart:{available:true}}}",context);assert.match(context.opRestartState(lab,dev,{connected:true}).reason,/cannot restart one device/,'an older helper that does not know the action keeps it off');
 vm.runInContext('opCaps=null',context);assert.equal(context.opRestartState(lab,dev,{connected:true}).ok,true,'capabilities not loaded yet: the server decides');
});

test('the Restart device review names the one device and the lab, what drops, and what is not done for the student',()=>{
 const copy=vm.runInContext("opReviewCopy['restart-node']",context);const value={action:'restart-node',name:'square',node:'clab-square-ceos',node_label:'ceos',affected:[{name:'clab-square-ceos',state:'running'}]};
 assert.equal(copy.title('square',value),'Restart ceos?');assert.equal(copy.confirm,'Restart device');assert.equal(copy.danger,true);
 const body=copy.body(value);
 assert.match(body,/^Only ceos in square restarts/);assert.match(body,/containerlab restart --node/);assert.match(body,/links kept/);
 assert.match(body,/CLI sessions drop and traffic through it stops/);assert.match(body,/neighbouring devices lose their adjacencies/);
 assert.match(body,/Configuration changes you have not saved on the device may not survive/);assert.match(body,/Nothing is saved, backed up, reset or reapplied for you\./);
 assert.doesNotMatch(body,/other devices are not affected|unaffected|no other traffic/i,'never promises that unrelated traffic is untouched');
 assert.equal(vm.runInContext("opLabels['restart-node']",context),'Restart device');assert.equal(vm.runInContext('opLabels.restart',context),'Restart all devices','the lab-wide action is named apart from the one-device action (U-17)');
 const whole=vm.runInContext("opReviewCopy.restart",context),wholeBody=typeof whole.body==='function'?whole.body({}):whole.body;assert.equal(whole.title('square'),'Restart every device of square?');assert.match(wholeBody,/Every device of the lab restarts through containerlab/);assert.match(wholeBody,/Nothing is saved, backed up, reset or reapplied/);
 assert.ok(vm.runInContext("opLifecycle.includes('restart-node')&&opDisruptive.includes('restart-node')",context));
 const banner=context.opJobBanner({action:'restart-node',name:'square',node_label:'ceos',status:'succeeded',exit_code:0,message:'Operation completed'});
 assert.equal(banner.title,'✔ Restart device succeeded');assert.equal(banner.detail,'square · ceos · Operation completed');
 const failed=context.opJobBanner({action:'restart-node',name:'square',node_label:'ceos',status:'failed',exit_code:1,message:'Host command returned an error'});
 assert.equal(failed.title,'✖ Restart device failed');assert.equal(failed.tone,'bad');
});

test('opRestartDevice re-checks eligibility, then reviews exactly one device of one lab with no options',async()=>{
 const calls=[];const c=vm.createContext({$:()=>null,esc:context.esc,state:{discovery:{connected:true},labs:[{id:'a',name:'square',deployment_name:'square',vm_project_path:'/srv/p/square.clab.yml',deployment:{status:'Running'},nodes:[{name:'clab-square-ceos',short_name:'ceos',discovered:true,runtime_state:'running'},{name:'clab-square-xrv9k',short_name:'xrv9k',discovered:false,runtime_state:'absent'}]}],jobs:[],operations:[],git_jobs:[]},busy:()=>false,notify:m=>calls.push(['notify',m]),renderLabBanner(){},showActionError:m=>calls.push(['error',m]),api:async()=>({json:async()=>({actions:{'restart-node':{available:true}}})}),json:async(path,method,data)=>{calls.push(['json',path,method,data]);return {};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 c.opReview=async request=>{calls.push(['review',request]);};
 await c.opRestartDevice('a','clab-square-ceos');
 assert.deepEqual(JSON.parse(JSON.stringify(calls.filter(x=>x[0]==='review'))),[['review',{lab_id:'a',action:'restart-node',node:'clab-square-ceos',options:{}}]]);
 await c.opRestartDevice('a','clab-square-xrv9k');
 assert.deepEqual(JSON.parse(JSON.stringify(calls.filter(x=>x[0]==='error'))),[['error','Restart device… is not available: xrv9k is not deployed on the VM']],'the reason is the banner sentence (U-18)');assert.equal(calls.filter(x=>x[0]==='review').length,1,'an ineligible device is never reviewed');
 await c.opRestartDevice('zzz','clab-square-ceos');assert.equal(calls.filter(x=>x[0]==='review').length,1);assert.equal(calls.filter(x=>x[0]==='error').at(-1)[1],'Restart device… is not available: This device is not in the lab');
});

test('U-02/U-03: an operation dialog is named by its heading and gives focus back to the control that opened it',()=>{
 const body={children:[],append(d){this.children.push(d);},contains:d=>true};const opener={focused:0,focus(){this.focused++;}};
 const dialogs={};
 const document={activeElement:opener,body,createElement:()=>{const d={open:false,attrs:{},listeners:{},innerHTML:'',setAttribute(k,v){this.attrs[k]=v;},addEventListener(n,fn){this.listeners[n]=fn;},querySelector(){return {onclick:null};},showModal(){this.open=true;},close(){this.open=false;this.listeners.close&&this.listeners.close();}};return d;}};
 const c=vm.createContext({$:id=>dialogs[id]||null,esc:context.esc,document,console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 const d=c.opDialog('operation-review','Restart ceos?','<p>body</p>');dialogs['operation-review']=d;
 assert.equal(d.attrs['aria-labelledby'],'operation-review-title');assert.match(d.innerHTML,/<h2 id="operation-review-title">Restart ceos\?<\/h2>/);
 d.close();assert.equal(opener.focused,1,'focus goes back to what had it');
 const other={focused:0,focus(){this.focused++;}};document.activeElement={};
 const d2=c.opDialog('operation-review','Again',"<p/>",other);d2.close();assert.equal(other.focused,1,'an explicit opener wins');assert.equal(opener.focused,1);
});

test('the builder page gets Add / Deploy now (then Deploy now / Go to My labs) in its save result; every other page keeps "Deploy or add this lab…"',async()=>{
 const run=async(builder,labs)=>{
  const elements=new Map();
  for(const id of ['op-job-banner','op-job-output','op-job-result'])elements.set(id,{hidden:false,className:'',textContent:'',innerHTML:'',scrollTop:0,scrollHeight:0,clientHeight:0,addEventListener(){}});
  const job={id:'j',action:'publish',name:'demo',status:'succeeded',output:'',result:{published_path:'/srv/p/demo/demo.clab.yml'}};
  const rendered=[];
  const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs},console,document:{getElementById:()=>null},setTimeout:()=>1,clearTimeout(){},
   api:async()=>({json:async()=>job}),refresh:async()=>{},...(builder?{builderGo(){}}:{})});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
  c.opDialog=()=>({open:true,classList:{toggle(){}},querySelector:()=>({textContent:''}),querySelectorAll:()=>[]});
  c.opRenderPublished=(d,p)=>rendered.push(p);
  await c.opShowJob('j');
  return {html:elements.get('op-job-result').innerHTML,rendered};
 };
 const main=await run(false,[]);
 assert.match(main.html,/id="op-open-published">Deploy or add this lab…/);assert.doesNotMatch(main.html,/op-published-block/);assert.deepEqual(main.rendered,[]);
 const builder=await run(true,[]);
 assert.match(builder.html,/id="op-published-block"/);assert.doesNotMatch(builder.html,/op-open-published/,'the generic dialog that looped back is not offered');
 assert.deepEqual(builder.rendered,['/srv/p/demo/demo.clab.yml']);
});

test('the builder hand-off markup: Add and Deploy now before the lab is in My labs; Deploy now and Go to My labs after, and adding never says it started anything',()=>{
 const c=vm.createContext({$:()=>null,esc:s=>String(s),state:{labs:[]},console,document:{getElementById:()=>null}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 const before=c.opPublishedMarkup('/srv/p/d.clab.yml',null);
 assert.match(before,/id="op-published-add">Add to My labs without starting/);assert.match(before,/id="op-published-deploy">Deploy now/);assert.doesNotMatch(before,/op-published-go/);
 const after=c.opPublishedMarkup('/srv/p/d.clab.yml',{id:'L1',name:'demo'});
 assert.match(after,/demo is in My labs\. It is not running/);assert.match(after,/id="op-published-deploy">Deploy now/);assert.match(after,/id="op-published-go" data-lab="L1">Go to My labs/);assert.doesNotMatch(after,/op-published-add/);
 c.state.labs=[{id:'L1',vm_project_path:'/srv/p/d.clab.yml'},{id:'L2',vm_project_path:'/srv/p/e.clab.yml'}];
 assert.equal(c.opLabAtPath('/srv/p/d.clab.yml').id,'L1','a lab already registered for the file is found and reused');assert.equal(c.opLabAtPath('/srv/p/none.clab.yml'),null);
});

test('deploy lab still opens the saved workspace when sessionStorage is blocked',async()=>{
 const page=vm.createContext({$:()=>null,esc:String,state:{labs:[{id:'old',deployment_name:'ceos-pair',vm_project_path:'/etc/containerlab/ceos-pair/ceos-pair.clab.yaml'}]},activeId:'',
  sessionStorage:{setItem(){throw new Error('SecurityError');},getItem(){throw new Error('SecurityError');}},
  api:async()=>({json:async()=>({id:'new'})}),json:async()=>({})});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),page);
 assert.equal(await page.opSaveWorkspace('/etc/containerlab/ceos-pair/ceos-pair.clab.yaml',{text:'name: x\n'},{name:'ceos-pair'}),'old');
 assert.equal(page.activeId,'old','the lab is open although the id could not be remembered for a reload');
});

test('no manager script writes or clears the remembered lab in sessionStorage without a guard (L-32)',()=>{
 for(const file of ['app.js','operations.js','management.js']){
  const source=fs.readFileSync(path.join(__dirname,'../app/static',file),'utf8');
  assert.doesNotMatch(source,/(?<!try\{)sessionStorage\.(setItem|removeItem)\('activeLab'/,file+': blocked site data throws SecurityError; shell.js shellSet/shellRemove or a try/catch must wrap the call');
 }
});

// C02: Stop a running lifecycle operation and Copy output. A tiny DOM: every id in written markup becomes an element, so the
// Stop block can rebuild itself and the test can click, focus and read it.
function stopHarness(jobs,{clipboard=true}={}){
 const elements=new Map(),log={focus:[],copies:[],feedback:[],posts:[],bodies:[]};
 let active=null;
 const make=id=>{
  const el={id,hidden:false,disabled:false,className:'',textContent:'',scrollTop:0,scrollHeight:0,clientHeight:0,children:new Set(),handlers:{},_html:'',
   get innerHTML(){return this._html;},
   set innerHTML(html){this._html=html;this.children.clear();for(const m of String(html).matchAll(/ id="([\w-]+)"/g)){const child=make(m[1]);this.children.add(child);}},
   addEventListener(name,fn){this.handlers[name]=fn;},focus(){active=this;log.focus.push(id);},
   contains(other){return other===this||this.children.has(other);}};
  elements.set(id,el);return el;
 };
 const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs:[]},activeId:'lab1',console,
  document:{getElementById:()=>null,get activeElement(){return active;}},setTimeout:()=>1,clearTimeout(){},
  api:async()=>({json:async()=>jobs.current}),refresh:async()=>{},
  json:async(url,method,body)=>{log.posts.push([url,method,body]);if(jobs.postError)throw new Error(jobs.postError);return {status:'running'};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),c);
 if(clipboard)vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/clipboard.js'),'utf8'),c);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 if(clipboard){c.copyText=async(text,source)=>{log.copies.push([text,source.id]);return jobs.copyOk!==false;};c.copyFeedback=(button,ok)=>log.feedback.push([button.id,ok]);}
 const dialog={id:'operation-output',open:true,classList:{toggle(){}},querySelector:()=>({textContent:''}),querySelectorAll:()=>[]};
 c.opDialog=(id,title,html)=>{for(const m of html.matchAll(/ id="([\w-]+)"/g))make(m[1]);log.html=html;return dialog;};
 const stopBox=()=>elements.get('op-job-stop');
 return {c,elements,log,dialog,box:stopBox,get:id=>elements.get(id)};
}
const stopJob=extra=>({id:'a',action:'deploy',name:'demo',lab_id:'lab1',status:'running',output:'',...extra});

test('C02: a stopped job reads Stopped by you in the history, a warning banner without a hint, and Try again turns a stopped deploy into a redeploy review',()=>{
 const c=vm.createContext({$:()=>null,esc:s=>String(s)});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 assert.equal(c.opStatusWord('cancelled'),'Stopped by you');
 const pull='level=error msg="Failed to pull image image=docker.io/library/x:1"';
 const banner=c.opJobBanner({action:'deploy',name:'demo',status:'cancelled',exit_code:null,message:'You stopped Start lab.',output:pull});
 assert.equal(banner.tone,'warn');assert.equal(banner.title,'■ Start lab ended early: you stopped it');assert.equal(banner.hint,undefined,'a stop is not a failure to explain');assert.equal(banner.exit,'');
 assert.equal(c.opJobBanner({action:'destroy',name:'demo',status:'failed',exit_code:1}).tone,'bad','failures keep their tone');
 c.jobRequest=id=>id==='j'?{action:'deploy',lab_id:'old',options:{cleanup:true}}:null;
 assert.deepEqual(JSON.parse(JSON.stringify(c.opRetryRequest({id:'j',action:'deploy',status:'cancelled'},'lab'))),{action:'redeploy',lab_id:'lab',options:{cleanup:true}},'same options, the redeploy review');
 assert.equal(c.opRetryRequest({id:'zz',action:'deploy',status:'cancelled'},'lab'),null,'no remembered request: the dialog, as for a failed deploy');
 assert.deepEqual(JSON.parse(JSON.stringify(c.opRetryRequest({id:'x',action:'destroy',status:'cancelled'},'lab'))),{lab_id:'lab',action:'destroy',options:{cleanup:true}},'every other stopped action repeats itself');
 assert.equal(c.opRetryRequest({id:'j',action:'deploy',status:'failed'},'lab').action,'deploy','a failed deploy is repeated as before');
 // start, apply and restart end in the same aftermath as a stopped deploy (Redeploy lab): the same redeploy review, the same options
 c.jobRequest=id=>({start:{action:'start',lab_id:'old',options:{}},apply:{action:'apply',lab_id:'old',options:{a:1}},restart:{action:'restart',lab_id:'old',options:{}}}[id]||null);
 for(const action of ['start','apply','restart'])assert.deepEqual(JSON.parse(JSON.stringify(c.opRetryRequest({id:action,action,status:'cancelled'},'lab'))),{action:'redeploy',lab_id:'lab',options:action==='apply'?{a:1}:{}},action+' becomes a redeploy review');
 assert.equal(c.opRetryRequest({id:'start',action:'start',status:'failed'},'lab').action,'start','a failed start is repeated as before');
 // a stopped start, apply or restart from an earlier session (no remembered request) still gets the one-click redeploy review; deploy stays null (its options may have been the cleanup variant)
 c.jobRequest=()=>null;
 for(const action of ['start','apply','restart'])assert.deepEqual(JSON.parse(JSON.stringify(c.opRetryRequest({id:'old-'+action,action,status:'cancelled'},'lab'))),{lab_id:'lab',action:'redeploy',options:{}},action+' without a stored request becomes a redeploy review');
 assert.equal(c.opRetryRequest({id:'old-deploy',action:'deploy',status:'cancelled'},'lab'),null,'deploy without a stored request is never guessed');
});

test('C02: the Stop block is offered only for stoppable actions while queued or running, and walks ask, confirmation, Stopping… with focus kept',async()=>{
 const jobs={current:stopJob({})},h=stopHarness(jobs);
 await h.c.opShowJob('a');
 assert.equal(h.box().hidden,false);assert.match(h.box().innerHTML,/id="op-stop-ask">Stop this operation…</);assert.doesNotMatch(h.box().innerHTML,/op-stop-confirm/);
 assert.deepEqual(h.log.focus,[],'opening the window moves no focus');
 h.get('op-stop-ask').handlers.click();
 assert.match(h.box().innerHTML,/End the running command \(Start lab\) on demo\? The manager asks the lab VM to end it now\. The lab may be only partly started; afterwards: Redeploy lab\./);
 assert.match(h.box().innerHTML,/id="op-stop-keep">Keep running</);assert.match(h.box().innerHTML,/class="button danger small" id="op-stop-confirm">Stop</);
 assert.match(h.box().innerHTML,/<div role="group" aria-labelledby="op-stop-question"><p id="op-stop-question">.*<\/p><div class="actions"><button[^>]*id="op-stop-keep">.*id="op-stop-confirm">Stop<\/button><\/div><\/div>/,'the question labels the group of its two buttons');
 assert.equal(h.log.focus.at(-1),'op-stop-keep','focus starts on the safe choice');
 h.get('op-stop-keep').handlers.click();
 assert.match(h.box().innerHTML,/op-stop-ask/);assert.equal(h.log.focus.at(-1),'op-stop-ask','Keep running returns focus to the ask button');
 h.get('op-stop-ask').handlers.click();
 await h.get('op-stop-confirm').handlers.click();
 assert.deepEqual(JSON.parse(JSON.stringify(h.log.posts)),[['/operations/a/cancel','POST',{}]]);
 assert.match(h.box().innerHTML,/<p id="op-stop-status" role="status" tabindex="-1">Stopping… the manager has asked the lab VM to end the command\.<\/p>/);
 assert.equal(h.log.focus.at(-1),'op-stop-status');
 // The record carries the request: a later poll with cancel_requested keeps the same block, and a reopened window shows it unasked.
 const before=h.log.focus.length;jobs.current=stopJob({cancel_requested:'2026-10-20T10:00:05Z'});
 await h.c.opShowJob('a');assert.match(h.box().innerHTML,/op-stop-status/);assert.equal(h.log.focus.length,before,'a reopened window does not steal focus');
});

test('C02: Stop is not drawn for actions that finish on their own or for finished jobs, and the block hands focus to the banner when it goes away under the person',async()=>{
 for(const action of ['create','delete','publish','revise','inspect']){
  const h=stopHarness({current:stopJob({action})});await h.c.opShowJob('a');
  assert.equal(h.box().hidden,true,action);assert.equal(h.box().innerHTML,'');
 }
 for(const status of ['succeeded','failed','cancelled','interrupted']){const h=stopHarness({current:stopJob({status})});await h.c.opShowJob('a');assert.equal(h.box().hidden,true,status);}
 const queued=stopHarness({current:stopJob({status:'queued'})});await queued.c.opShowJob('a');assert.match(queued.box().innerHTML,/op-stop-ask/,'queued can be stopped');
 // The block holds focus (the confirmation), then the job ends: focus moves to the job banner, not to the page.
 const jobs={current:stopJob({})},h=stopHarness(jobs);let poll;h.c.setTimeout=fn=>{poll=fn;return 1;};
 await h.c.opShowJob('a');h.get('op-stop-ask').handlers.click();assert.equal(h.log.focus.at(-1),'op-stop-keep');
 jobs.current=stopJob({status:'cancelled',message:'You stopped Start lab.'});await poll();
 assert.equal(h.box().hidden,true);assert.equal(h.log.focus.at(-1),'op-job-banner');assert.match(h.log.html,/id="op-job-banner" class="op-banner" tabindex="-1"/);
 assert.equal(h.get('op-job-banner').className,'op-banner warn');assert.match(h.get('op-job-banner').innerHTML,/ended early: you stopped it/);
});

test('C02: a poll that turns the confirmation into Stopping… moves focus from the vanished button to the status, and only then',async()=>{
 const jobs={current:stopJob({})},h=stopHarness(jobs);let poll;h.c.setTimeout=fn=>{poll=fn;return 1;};
 await h.c.opShowJob('a');h.get('op-stop-ask').handlers.click();assert.equal(h.log.focus.at(-1),'op-stop-keep');
 jobs.current=stopJob({cancel_requested:'2026-10-20T10:00:05Z'});await poll();
 assert.match(h.box().innerHTML,/op-stop-status/);assert.equal(h.log.focus.at(-1),'op-stop-status','focus does not fall to BODY');
 // nothing held focus (the person is reading the output): the change steals none
 const idleJobs={current:stopJob({})},h3=stopHarness(idleJobs);let p3;h3.c.setTimeout=fn=>{p3=fn;return 1;};
 await h3.c.opShowJob('a');idleJobs.current=stopJob({cancel_requested:'x'});await p3();assert.equal(h3.log.focus.length,0,'no focus was held, none is taken');
});
test('C02: opening with {stop:true} unfolds the confirmation on Keep running; a refused stop shows the error and brings the ask button back',async()=>{
 const jobs={current:stopJob({action:'destroy'})},h=stopHarness(jobs);
 await h.c.opShowJob('a',{stop:true});
 assert.match(h.box().innerHTML,/End the running command \(Destroy lab\) on demo\?.*only partly removed; afterwards: run Destroy lab again\./);assert.equal(h.log.focus.at(-1),'op-stop-keep');
 jobs.postError='This operation has already finished.';
 const errors=[];h.dialog.querySelector=sel=>sel==='.form-error'?{set textContent(v){errors.push(v);},get textContent(){return '';},scrollIntoView(){}}:{textContent:''};
 await h.get('op-stop-confirm').handlers.click();
 assert.ok(errors.includes('This operation has already finished.'),'the refusal lands in the dialog\'s error line');
 assert.match(h.box().innerHTML,/op-stop-ask/);assert.equal(h.log.focus.at(-1),'op-stop-ask');
});

test('C02: Copy output is disabled while the output is empty, copies the job output through its own click and flips through copyFeedback',async()=>{
 const jobs={current:stopJob({action:'inspect',output:''})},h=stopHarness(jobs);
 await h.c.opShowJob('a');
 assert.match(h.log.html,/<div class="op-output-tools"><button type="button" id="op-copy-output" class="button ghost small" data-label="Copy output" aria-label="Copy the command output" data-copy-target="op-job-output" disabled>Copy output<\/button><span class="copy-status" role="status"><\/span><\/div><pre class="op-output" id="op-job-output"/);
 assert.doesNotMatch(h.log.html,/data-copy=/,'no data-copy: the document-level delegation never copies this a second time');
 const button=h.get('op-copy-output');assert.equal(button.disabled,true,'Waiting for the VM… is never copied');
 await button.onclick();assert.deepEqual(h.log.copies,[]);
 jobs.current=stopJob({action:'inspect',output:'line 1\nline 2'});
 let poll;h.c.setTimeout=fn=>{poll=fn;return 1;};jobs.current.status='running';await h.c.opShowJob('a');
 const again=h.get('op-copy-output');assert.equal(again.disabled,false);
 await again.onclick();assert.deepEqual(h.log.copies,[['line 1\nline 2','op-copy-output']]);assert.deepEqual(h.log.feedback,[['op-copy-output',true]]);
 jobs.copyOk=false;await again.onclick();assert.deepEqual(h.log.feedback.at(-1),['op-copy-output',false],'a failed copy is reported, never shown as Copied');
 const bare=stopHarness({current:stopJob({output:'x'})},{clipboard:false});await bare.c.opShowJob('a');
 assert.doesNotMatch(bare.log.html,/op-copy-output/,'a page without clipboard.js has no dead button');
});

// ---- C03 (docs/parity-campaign/C03-DESIGN.md 4.2 to 4.5) ----------------------------------------------------------------------
const inspectRaw=JSON.stringify([
 {lab_name:'beta',name:'clab-beta-r2',kind:'ceos',image:'ceos:4.35',state:'running',health_status:'healthy',ipv4_address:'172.20.20.3/24',container_id:'0123456789abcdef0123',owner:'student',labels:{'clab-topo-file':'/p/beta.clab.yaml'}},
 {lab_name:'alpha',name:'clab-alpha-r10',kind:'linux',image:'alpine',state:'running',ipv4_address:'172.20.20.9/24',container_id:'ffffffffffffffff',owner:'root',labels:{'clab-topo-file':'/p/alpha.clab.yaml'}},
 {lab_name:'alpha',name:'clab-alpha-r9',kind:'linux',image:'alpine',state:'exited',ipv4_address:'172.20.20.8/24',container_id:'',labels:{}}]);
test('the inspect table keeps its six columns in order with the Lab column, then appends ID and Owner',()=>{
 const rows=context.opInspectionRows(inspectRaw);
 assert.equal(rows[0].id,'0123456789ab','the first 12 characters of the container id');assert.equal(rows[0].owner,'student');assert.equal(rows[2].id,'');assert.equal(rows[2].owner,'');
 const table=context.opInspectionTable(rows);
 const heads=[...table.matchAll(/data-op-sort="(\w+)">([^<]+)<\/button>/g)].map(m=>m[2]);
 assert.deepEqual(heads,['Topology','Lab','Device','Type / image','State / health','IPv4 / IPv6','ID','Owner']);
 assert.match(table,/<td class="mono">0123456789ab<\/td><td>student<\/td>/);
 assert.match(table,/<td class="mono">—<\/td><td>—<\/td>/,'an empty id or owner reads as a dash');
 assert.equal((table.match(/aria-sort="none"/g)||[]).length,8,'every header carries aria-sort and holds a button');
 assert.match(table,/<label for="op-inspect-filter">Filter devices<\/label><input type="search" id="op-inspect-filter"/,'the filter box has a visible label');
 assert.match(table,/<caption>2 running devices<\/caption>/,'the exited row is listed but not counted');
});
test('inspect sort is stable, numeric-aware and reversible; aria-sort follows the state',()=>{
 const rows=context.opInspectionRows(inspectRaw),names=list=>Array.from(list,r=>r.node);
 assert.deepEqual(names(context.opInspectionSort(rows,'node','asc')),['clab-alpha-r9','clab-alpha-r10','clab-beta-r2'],'r9 before r10');
 assert.deepEqual(names(context.opInspectionSort(rows,'node','desc')),['clab-beta-r2','clab-alpha-r10','clab-alpha-r9']);
 assert.deepEqual(names(context.opInspectionSort(rows,'lab','asc')),['clab-alpha-r10','clab-alpha-r9','clab-beta-r2'],'equal keys keep their order');
 assert.deepEqual(names(context.opInspectionSort(rows,'','asc')),names(rows),'no key keeps the order given');assert.deepEqual(names(context.opInspectionSort(rows,'node','')),names(rows));
 assert.deepEqual(names(rows),['clab-beta-r2','clab-alpha-r10','clab-alpha-r9'],'sorting copies, never reorders the input');
 const table=context.opInspectionTable(rows,{key:'lab',dir:'desc',filter:''});
 assert.match(table,/aria-sort="descending"><button type="button" class="op-sort" data-op-sort="lab">/);assert.equal((table.match(/aria-sort="none"/g)||[]).length,7);
 assert.match(context.opInspectionTable(rows,{key:'lab',dir:'asc'}),/aria-sort="ascending"><button[^>]*data-op-sort="lab"/);
});
test('inspect filter is a case-insensitive substring over every column, the Lab included; the caption says n of m',()=>{
 const rows=context.opInspectionRows(inspectRaw),names=list=>Array.from(list,r=>r.node);
 assert.deepEqual(names(context.opInspectionFilter(rows,'ALPHA')),['clab-alpha-r10','clab-alpha-r9'],'the Lab column is searched');
 assert.deepEqual(names(context.opInspectionFilter(rows,'0123456789AB')),['clab-beta-r2'],'the new ID column is searched');
 assert.deepEqual(names(context.opInspectionFilter(rows,'student')),['clab-beta-r2']);
 assert.deepEqual(names(context.opInspectionFilter(rows,'172.20.20.8')),['clab-alpha-r9']);
 assert.equal(context.opInspectionFilter(rows,'  ').length,3);assert.equal(context.opInspectionFilter(rows,'a*').length,0,'no wildcard grammar');
 const table=context.opInspectionTable(rows,{filter:'alpha'});
 assert.match(table,/<caption>1 of 2 running devices<\/caption>/);assert.match(table,/value="alpha"/);assert.doesNotMatch(table,/clab-beta-r2/);
 assert.match(context.opInspectionTable(rows,{filter:'"><b>'}),/value="&quot;&gt;&lt;b&gt;"/,'the filter text is escaped');
 assert.match(context.opInspectionTable([rows[0]]),/<caption>1 running device<\/caption>/);
 const none=context.opInspectionTable(rows,{filter:'zzz'});
 assert.match(none,/<caption>0 of 2 running devices<\/caption>/);assert.match(none,/<tbody><tr><td colspan="8" class="op-inspection-empty">No device matches\.<\/td><\/tr><\/tbody>/,'one row spanning the columns');
});
test('the inspect table redraws only its own parts when the filter or a header changes',()=>{
 const rows=context.opInspectionRows(inspectRaw),view={key:'',dir:'',filter:''},focused=[];
 const listeners={},table={innerHTML:'',addEventListener(type,fn){listeners['table:'+type]=fn;},querySelector:sel=>sel.includes('data-op-sort')?{focus(){focused.push(sel);}}:null};
 const filter={value:'',addEventListener(type,fn){listeners['filter:'+type]=fn;}};
 const root={querySelector:sel=>sel==='table'?table:filter};
 context.opInspectionBind(root,rows,view);
 filter.value='beta';listeners['filter:input']();assert.equal(view.filter,'beta');assert.match(table.innerHTML,/<caption>1 of 2 running devices<\/caption>/);assert.deepEqual(focused,[],'typing never moves focus');
 const click=key=>listeners['table:click']({target:{closest:()=>({dataset:{opSort:key}})}});
 click('node');assert.deepEqual([view.key,view.dir],['node','asc']);click('node');assert.equal(view.dir,'desc');click('node');assert.deepEqual([view.key,view.dir],['','']);
 click('lab');assert.deepEqual([view.key,view.dir],['lab','asc']);assert.match(focused.at(-1),/data-op-sort="lab"/,'focus returns to the header button that was used');
});

test('sizes read like Docker (kB, MB) and the files-mode labels carry them',()=>{
 assert.equal(context.opSize(0),'0 B');assert.equal(context.opSize(2100),'2.1 kB');assert.equal(context.opSize(3400000),'3.4 MB');assert.equal(context.opSize('x'),'');
 assert.equal(context.opFileLabel({name:'startup-config',size:2100}),'◇ startup-config · 2.1 kB');assert.equal(context.opFileLabel({name:'a.yaml'}),'◇ a.yaml');
 const entries=[{name:'notes.md',kind:'file',directory:false},{name:'clab-lab',kind:'directory',directory:true},{name:'lab.clab.yaml',kind:'topology',directory:false},{name:'lab.clab.yaml.annotations.json',kind:'file'}];
 assert.deepEqual(Array.from(context.opFileEntries(entries),e=>e.name),['lab.clab.yaml','clab-lab','notes.md','lab.clab.yaml.annotations.json'],'topology files first, then folders, then the other files in the order given');
});

function browseHarness({diagnostics=true}={}){
 const calls=[];
 const element=tag=>({tag,children:[],className:'',textContent:'',open:false,isConnected:true,disabled:false,append(...c){this.children.push(...c);},replaceChildren(){this.children=[];}});
 const nodes={};
 const get=id=>{if(!nodes[id])nodes[id]=Object.assign(element('x'),{id});return nodes[id];};
 const listing={'/srv/p/lab':[{name:'clab-lab',path:'/srv/p/lab/clab-lab',directory:true,kind:'directory'},{name:'lab.clab.yaml',path:'/srv/p/lab/lab.clab.yaml',kind:'topology',size:900},{name:'map.annotations.json',path:'/srv/p/lab/map.annotations.json',kind:'file',size:120}],
  '/srv/p/lab/clab-lab':[{name:'r1',path:'/srv/p/lab/clab-lab/r1',directory:true,kind:'directory'}],'/srv/p/lab/clab-lab/r1':[{name:'startup-config',path:'/srv/p/lab/clab-lab/r1/startup-config',kind:'file',size:2100}],'/srv/p':[{name:'lab',path:'/srv/p/lab',directory:true,kind:'directory'}],'':[{name:'projects',path:'/srv/p',directory:true,kind:'directory'}]};
 const c=vm.createContext({$:id=>/^(op-|help$|err$)/.test(id)?get(id):null,esc:v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),state:{labs:[{id:'L1',name:'lab one',vm_project_path:'/srv/p/lab/lab.clab.yaml'}]},document:{createElement:element},
  json:async(url,method,body)=>{calls.push([url,JSON.parse(JSON.stringify(body))]);return {path:body.path,parent:body.path&&body.path!=='/srv/p'?'/srv/p':'',entries:listing[body.path]||[]};}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 const dialog={querySelector:sel=>sel==='.form-help'?get('help'):get('err'),querySelectorAll:()=>[],open:true,close(){}};
 const dialogs=[];
 c.opDialog=(id,title,body)=>{dialogs.push({id,title,body});return dialog;};
 c.opCapabilities=async()=>{const caps={diagnostics,network:false,actions:{}};vm.runInContext('opCaps='+JSON.stringify(caps),c);return caps;};
 c.opViewed=[];c.opView=async(p,l)=>{c.opViewed.push([p,l]);};c.opEdit=async(p,l)=>{c.opViewed.push(['edit',p,l]);};
 return {c,calls,dialogs,get};
}
test('Lab files mode: every listing sends files:true with the lab, keeps the title and help, and reaches nested folders',async()=>{
 const h=browseHarness();
 await h.c.opBrowse('','L1');
 assert.deepEqual(h.calls[0],['/operations/browse',{path:'/srv/p/lab',files:true,lab_id:'L1'}],'the first listing starts in the lab folder');
 assert.equal(h.dialogs[0].title,'Lab files · lab one');assert.match(h.dialogs[0].body,/Files the manager can show \(text and configuration files\)\. Other files on the VM are not listed\./);
 const tree=h.get('op-file-tree');
 assert.equal(tree.children.length,3);
 const [topology,folder,other]=tree.children;
 assert.equal(topology.textContent,'◇ lab.clab.yaml · 900 B','topology files first');assert.equal(folder.tag,'details');assert.equal(other.textContent,'◇ map.annotations.json · 120 B');
 folder.open=true;await folder.ontoggle();
 assert.deepEqual(h.calls.at(-1),['/operations/browse',{path:'/srv/p/lab/clab-lab',files:true,lab_id:'L1'}],'folder expansion keeps files mode');
 const nested=folder.children[1].children[0];nested.open=true;await nested.ontoggle();
 const file=nested.children[1].children[0];
 assert.equal(file.textContent,'◇ startup-config · 2.1 kB','a node folder\'s startup configuration is reachable');
 await file.onclick();assert.deepEqual(Array.from(h.c.opViewed.at(-1)),['/srv/p/lab/clab-lab/r1/startup-config','L1'],'a non-topology file opens the read-only viewer');
 await topology.onclick();assert.deepEqual(Array.from(h.c.opViewed.at(-1)),['edit','/srv/p/lab/lab.clab.yaml','L1'],'a topology file opens as before');
 const up=h.get('op-up');
 assert.equal(up.disabled,true,'Up one folder stops at the lab folder');assert.equal(up.title,"This is the lab's folder");
 assert.doesNotMatch(h.dialogs[0].body,/id="op-roots"|All lab folders/,'files mode never lists all lab folders');
 // A listing below the lab folder (the dialog reopened there) can still go up, and keeps files mode.
 up.disabled=false;up.title='';await h.c.opBrowse('/srv/p/lab/clab-lab','L1');
 assert.equal(up.disabled,false,'below the lab folder Up is enabled');
 await up.onclick();assert.deepEqual(h.calls.at(-1),['/operations/browse',{path:'/srv/p',files:true,lab_id:'L1'}],'Up one folder keeps files mode');
 assert.equal(h.dialogs.at(-1).title,'Lab files · lab one');
});
test('the topology browser keeps All lab folders and an enabled Up; files mode never appends the downloads sentence',async()=>{
 const old=browseHarness({diagnostics:false});await old.c.opBrowse('','L1');
 assert.match(old.dialogs[0].body,/id="op-roots">All lab folders/);assert.notEqual(old.get('op-up').disabled,true);
 await old.get('op-roots').onclick();assert.deepEqual(old.calls.at(-1),['/operations/browse',{path:''}]);
 await new Promise(r=>setImmediate(r));
 assert.match(old.get('help').textContent,/Downloading labs from the internet is turned off/,'the deploy browser says it');
 const files=browseHarness();await files.c.opBrowse('','L1');await new Promise(r=>setImmediate(r));
 assert.doesNotMatch(files.get('help').textContent,/Downloading labs/,'files mode does not append it (network is off in this harness)');
});
test('without the diagnostics flag, or without a lab, Lab files is today\'s topology browser',async()=>{
 const old=browseHarness({diagnostics:false});await old.c.opBrowse('','L1');
 assert.deepEqual(old.calls[0],['/operations/browse',{path:'/srv/p/lab'}],'no files option for an older helper');
 assert.match(old.dialogs[0].body,/Only topology files are listed, up to 500 per folder\./);
 const none=browseHarness();await none.c.opBrowse('/srv/p');
 assert.deepEqual(none.calls[0],['/operations/browse',{path:'/srv/p'}],'no lab, no files mode');assert.equal(none.dialogs[0].title,'Deploy a new lab');
});

test('Images on this VM: rows from details, used_by and missing; chips and filter',()=>{
 const data={available:true,images:['alpine:latest','n24l/ceos:4.35.0F'],details:[{reference:'alpine:latest',id:'a',size:'7.8MB',created:'2026-10-23 02:03:42 +0000 UTC'},{reference:'n24l/ceos:4.35.0F',id:'b',size:'2.1GB',created:'2026-09-01T10:00:00Z'}],used_by:{'alpine:latest':['lab one','lab two'],'vrnetlab/xrv:1':['lab one']},missing:['vrnetlab/xrv:1']};
 const rows=context.opImageRows(data);
 assert.equal(rows.length,3);assert.deepEqual(Array.from(rows[0].labs),['lab one','lab two']);assert.equal(rows[2].missing,true);assert.equal(rows[2].size,'');assert.deepEqual(Array.from(rows[2].labs),['lab one']);
 assert.deepEqual(Array.from(context.opImageFilter(rows,'','used'),r=>r.reference),['alpine:latest','vrnetlab/xrv:1']);
 assert.deepEqual(Array.from(context.opImageFilter(rows,'','missing'),r=>r.reference),['vrnetlab/xrv:1']);
 assert.deepEqual(Array.from(context.opImageFilter(rows,'LAB TWO','all'),r=>r.reference),['alpine:latest'],'the filter also searches the lab names');
 assert.deepEqual(Array.from(context.opImageFilter(rows,'ceos','used'),r=>r.reference),[]);
 const old=context.opImageRows({available:true,images:['alpine:latest'],used_by:{}});
 assert.equal(old.length,1);assert.equal(old[0].size,'','a helper without details still lists the references');
 assert.equal(context.opImageRows(null).length,0);
 assert.equal(context.opCreatedDate('2026-10-23 02:03:42 +0000 UTC').toISOString(),'2026-10-23T02:03:42.000Z');assert.equal(context.opCreatedDate('nope'),null);assert.equal(context.opCreatedDate(''),null);
 const body=context.opImageTableBody(rows);
 assert.match(body,/<span class="pill danger">Missing<\/span>/);assert.match(body,/lab one, lab two/);assert.match(body,/title="2026-10-23 02:03:42 UTC"/);
 assert.match(context.opImageTableBody([{reference:'<i>x</i>',size:'',created:'',labs:['<b>'],missing:false}]),/&lt;i&gt;x&lt;\/i&gt;.*&lt;b&gt;/);
 assert.match(context.opImageTableBody([]),/No images match\./);
});

test('an inspect run starts with a clean sort and filter on the reused dialog',async()=>{
 const elements=new Map();
 for(const id of ['op-job-banner','op-job-output','op-job-result'])elements.set(id,{hidden:false,className:'',textContent:'',innerHTML:'',scrollTop:0,scrollHeight:0,clientHeight:0,addEventListener(){}});
 const dialog={open:true,classList:{toggle(){}},querySelector:()=>({textContent:''}),querySelectorAll:()=>[]};
 const job={id:'j',action:'inspect',name:'',status:'succeeded',output:'',result:{}};
 const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs:[]},console,document:{getElementById:()=>null},setTimeout:()=>1,clearTimeout(){},api:async()=>({json:async()=>job}),refresh:async()=>{}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 c.opDialog=()=>dialog;
 await c.opShowJob('j');
 Object.assign(dialog._inspectView,{key:'lab',dir:'desc',filter:'beta'});
 await c.opShowJob('j');
 assert.deepEqual({...dialog._inspectView},{key:'',dir:'',filter:''},'the next inspect run does not inherit the earlier view');
});

function managerMenuHarness(caps){
 const els=new Map();
 const get=id=>{if(!els.has(id)){const listeners={};els.set(id,{id,hidden:true,textContent:'',innerHTML:'',value:'',dataset:{},listeners,isConnected:true,classList:{toggle(){},add(){},remove(){}},
  addEventListener(type,fn){(listeners[type]=listeners[type]||[]).push(fn);},insertAdjacentHTML(){},querySelector:()=>null,querySelectorAll:()=>[],setAttribute(){},getAttribute:()=>null,removeAttribute(){}});}return els.get(id);};
 const c=vm.createContext({$:get,esc:v=>String(v??''),state:{labs:[],discovery:{connected:false}},document:{createElement:()=>({}),addEventListener(){},getElementById:()=>null},console,setTimeout:()=>1,clearTimeout(){},addEventListener(){},
  api:async()=>({json:async()=>({})}),json:async()=>({}),refresh:async()=>{}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 c.opCapabilities=async()=>caps();
 const open=async()=>{for(const fn of get('manager-menu-list').listeners.menuopen||[])fn();await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));};
 return {c,get,open};
}
test('Manager menu: opening it shows the VM\'s containerlab only for a well-formed version',async()=>{
 const good=managerMenuHarness(()=>({containerlab:'0.79.0'}));await good.open();
 assert.equal(good.get('clab-version').textContent,' · containerlab 0.79.0');assert.equal(good.get('clab-version').hidden,false);
 for(const [label,answer] of [['a malformed version',{containerlab:'bad'}],['a number',{containerlab:7}],['a non-object answer',7],['no answer',null]]){
  const h=managerMenuHarness(()=>answer);h.get('clab-version').textContent='stale';h.get('clab-version').hidden=false;await h.open();
  assert.equal(h.get('clab-version').textContent,'',label+' shows nothing');assert.equal(h.get('clab-version').hidden,true,label+' hides the span');
 }
 const failing=managerMenuHarness(()=>{throw new Error('no VM');});failing.get('clab-version').textContent='stale';await failing.open();
 assert.equal(failing.get('clab-version').textContent,'stale','a failed capabilities call leaves the footer as it was and throws nothing');
});
test('Images on this VM with no Docker client says so and wires nothing; the file viewer says when only the tail is shown',async()=>{
 const dialogs=[];
 const element=()=>({value:'',textContent:'',innerHTML:'',addEventListener(){},querySelectorAll:()=>[]});
 const els=new Map(),get=id=>{if(!els.has(id))els.set(id,element());return els.get(id);};
 const data={available:false};
 const c=vm.createContext({$:get,esc:v=>String(v??''),state:{labs:[]},document:{createElement:element},api:async()=>({json:async()=>data}),json:async()=>({name:'startup-config',text:'hostname r1',truncated:true})});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 c.opDialog=(id,title,body)=>{dialogs.push({id,title,body});return {querySelector:()=>null,querySelectorAll:()=>[]};};
 c.opBindCopyOutput=()=>{};
 await c.opImages();
 assert.equal(dialogs[0].title,'Images on this VM');assert.match(dialogs[0].body,/no Docker client the manager can ask/);assert.doesNotMatch(dialogs[0].body,/op-images-filter/,'no filter or table is drawn');
 await c.opView('/srv/p/lab/clab-lab/r1/startup-config','L1');
 assert.match(dialogs[1].body,/Showing the last 512 KiB of this file\./);assert.equal(get('op-view-text').value,'hostname r1');
});

// ---- C05: Start device, Stop device, the apply plan, Run with options, pending changes, node-filtered jobs -----------------------------
const c05={lab:{id:'a',name:'square',deployment_name:'square',vm_project_path:'/srv/p/square.clab.yml',deployment:{status:'Running'},nodes:[{name:'clab-square-ceos',short_name:'ceos',definition_node:'ceos',discovered:true,runtime_state:'running'},{name:'clab-square-vsw',short_name:'vsw',definition_node:'vsw',discovered:true,runtime_state:'exited'}]}};
const plainJson=o=>JSON.parse(JSON.stringify(o));
function c05Context({preview=async()=>({}),caps=null,labs=[c05.lab],operations=[]}={}){
 const calls=[],shown=[];
 const stubs=new Map(),el=id=>{if(id==='import-top')return null;if(!stubs.has(id))stubs.set(id,{id,onclick:null,focus(){},close(){},textContent:'',hidden:false,innerHTML:''});return stubs.get(id);};
 const c=vm.createContext({$:el,esc:context.esc,state:{discovery:{connected:true},labs,operations},busy:()=>false,activeId:'a',current:()=>labs[0],notify:m=>calls.push(['notify',m]),renderLabBanner(){},showActionError:m=>calls.push(['error',m]),
  json:async(url,method,body)=>{calls.push(['json',url,body]);return url==='/operations/preview'?preview(body):{id:'j1'};},refresh:async()=>{},
  api:async url=>{calls.push(['api',url]);if(url==='/operations/capabilities')return {json:async()=>caps};if(c.apiImpl)return {json:async()=>c.apiImpl(url)};throw new Error('no api');}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),c);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 c.opDialog=(id,title,body)=>{const dialog={id,title,body,open:true,close(){this.open=false;},querySelector:()=>null,querySelectorAll:()=>[]};shown.push(dialog);return dialog;};
 c.opReviewImages=()=>{};c.opTask=async(d,fn)=>fn();
 return {c,calls,shown,el};
}
const c05Caps={actions:{'start-node':{available:true},'stop-node':{available:true},impairments:{available:true},deploy:{available:true,node_filter:true,max_workers:true,skip_post_deploy:true},redeploy:{available:true,max_workers:true,skip_post_deploy:true,keep_mgmt_net:true,graceful:true},destroy:{available:true,cleanup:true,graceful:true,node_filter:true,max_workers:true,keep_mgmt_net:true},save:{available:true,node_filter:true},apply:{available:true}}};
const c05Value=(extra)=>({token:'tok',action:'apply',name:'square',path:'/srv/p/square.clab.yml',warnings:[],affected:[{name:'clab-square-ceos',state:'running'}],argv:['containerlab','deploy','-t','x'],...extra});

test('C05: Start device and Stop device are eligible by the device\'s own state, with reasons; unknown capabilities count as available and a loaded answer decides',()=>{
 const {c}=c05Context();const [ceos,vsw]=c05.lab.nodes,d={connected:true};
 assert.deepEqual(plainJson(c.opNodeActionState('stop-node',c05.lab,ceos,d)),{ok:true,reason:''});
 assert.deepEqual(plainJson(c.opNodeActionState('stop-node',c05.lab,vsw,d)),{ok:false,reason:'vsw is not running',own:true});
 assert.deepEqual(plainJson(c.opNodeActionState('start-node',c05.lab,vsw,d)),{ok:true,reason:''});
 assert.deepEqual(plainJson(c.opNodeActionState('start-node',c05.lab,ceos,d)),{ok:false,reason:'ceos is already running',own:true});
 assert.equal(c.opNodeActionState('stop-node',c05.lab,{...ceos,discovered:false,runtime_state:'absent'},d).reason,'ceos is not deployed on the VM');
 assert.equal(c.opNodeActionState('stop-node',c05.lab,ceos,{connected:false}).reason,'Connect the VM first');
 assert.equal(c.opNodeActionState('stop-node',c05.lab,ceos,d,true).reason,'Wait for the current operation to finish');
 vm.runInContext("opCaps={actions:{'restart-node':{available:true}}}",c);
 assert.equal(c.opNodeActionState('stop-node',c05.lab,ceos,d).reason,'Not available on this VM — its containerlab or helper cannot stop one device (see Diagnostics)');
 assert.equal(c.opNodeActionState('start-node',c05.lab,vsw,d).reason,'Not available on this VM — its containerlab or helper cannot start one device (see Diagnostics)');
 assert.equal(c.opNodeActionState('restart-node',c05.lab,ceos,d).ok,true);
 vm.runInContext("opCaps={actions:{'stop-node':{available:true}}}",c);assert.equal(c.opNodeActionState('stop-node',c05.lab,ceos,d).ok,true);
 vm.runInContext('opCaps=null',c);assert.equal(c.opNodeActionState('stop-node',c05.lab,ceos,d).ok,true,'capabilities not loaded: available');
 assert.deepEqual(plainJson(c.opRestartState(c05.lab,ceos,d)),plainJson(c.opNodeActionState('restart-node',c05.lab,ceos,d)),'opRestartState is the one-line wrapper');
});
test('C05: opNodeAction loads the capabilities, re-checks, then reviews exactly one device; a refusal is the banner sentence naming the action',async()=>{
 const {c,calls}=c05Context({caps:c05Caps});const reviews=[];c.opReview=async(r)=>{reviews.push(plainJson(r));};
 await c.opNodeAction('stop-node','a','clab-square-ceos');
 assert.deepEqual(reviews,[{lab_id:'a',action:'stop-node',node:'clab-square-ceos',options:{}}]);assert.ok(calls.some(x=>x[0]==='api'&&x[1]==='/operations/capabilities'));
 await c.opNodeAction('stop-node','a','clab-square-vsw');
 assert.equal(reviews.length,1);assert.deepEqual(calls.filter(x=>x[0]==='error').at(-1),['error','Stop device… is not available: vsw is not running']);
 await c.opNodeAction('start-node','a','clab-square-ceos');assert.equal(calls.filter(x=>x[0]==='error').at(-1)[1],'Start device… is not available: ceos is already running');
 await c.opNodeAction('start-node','a','clab-square-vsw');assert.equal(reviews.at(-1).action,'start-node');
});
test('C05: Save this device\'s configuration needs a running device and the node filter, and reviews a one-device save',async()=>{
 const {c,calls}=c05Context({caps:c05Caps});const [ceos,vsw]=c05.lab.nodes,d={connected:true};
 assert.equal(c.opSaveNodeState(c05.lab,ceos,d).ok,true);assert.equal(c.opSaveNodeState(c05.lab,vsw,d).reason,'vsw is not running');
 vm.runInContext("opCaps={actions:{save:{available:true,node_filter:false}}}",c);assert.match(c.opSaveNodeState(c05.lab,ceos,d).reason,/cannot save one device/);
 vm.runInContext('opCaps=null',c);assert.equal(c.opSaveNodeState(c05.lab,ceos,d).ok,true);
 const reviews=[];c.opReview=async r=>{reviews.push(plainJson(r));};await c.opSaveNode('a','clab-square-ceos');
 assert.deepEqual(reviews,[{lab_id:'a',action:'save',options:{nodes:['ceos']}}]);
});
test('C05: a job names its device or chosen devices: Stop ceos, ✔ ceos stopped, ✖ Stop ceos failed, Destroy ceos; Restart device keeps its word',()=>{
 const {c}=c05Context();
 assert.equal(c.opJobLabel({action:'stop-node',node_label:'ceos'}),'Stop ceos');assert.equal(c.opJobLabel({action:'start-node',node_label:'ceos'}),'Start ceos');
 assert.equal(c.opJobLabel({action:'stop-node'}),'Stop device','no device on the record: the table word');
 assert.equal(c.opJobLabel({action:'destroy',nodes:['ceos']}),'Destroy ceos');assert.equal(c.opJobLabel({action:'save',nodes:['ceos','vsw']}),'Save ceos, vsw');
 assert.equal(c.opJobLabel({action:'destroy'}),'Destroy lab');assert.equal(c.opJobLabel({action:'restart-node',node_label:'ceos'}),'Restart device');
 const job=extra=>({action:'stop-node',name:'square',node_label:'ceos',status:'succeeded',exit_code:0,message:'ok',...extra});
 assert.equal(c.opJobBanner(job()).title,'✔ ceos stopped');assert.equal(c.opJobBanner(job({action:'start-node'})).title,'✔ ceos started');
 assert.equal(c.opJobBanner(job({status:'failed'})).title,'✖ Stop ceos failed');assert.equal(c.opJobBanner(job({status:'failed'})).tone,'bad');
 assert.equal(c.opJobBanner(job({status:'running'})).title,'Stopping ceos…');
 assert.equal(c.opJobBanner(job({status:'cancelled'})).title,'■ Stop ceos ended early: you stopped it');
 assert.equal(c.opJobBanner({action:'destroy',nodes:['ceos'],name:'square',status:'succeeded'}).title,'✔ ceos destroyed');
 assert.equal(c.opJobBanner({action:'destroy',name:'square',status:'succeeded'}).title,'✔ Destroy lab succeeded');
});
test('C05: Try again for the three node actions carries the device, never opPlainRetry; a filtered destroy or save rebuilds from the job\'s nodes without Clean up',()=>{
 const {c}=c05Context();const retry=(job)=>plainJson(c.opRetryRequest(job,'a'));
 for(const action of ['restart-node','start-node','stop-node'])assert.deepEqual(retry({id:'x',action,node:'clab-square-ceos',status:'failed'}),{lab_id:'a',action,node:'clab-square-ceos',options:{}});
 assert.equal(c.opRetryRequest({id:'x',action:'stop-node',status:'failed'},'a'),null,'a node action without its device has no safe guess');
 assert.deepEqual(retry({id:'x',action:'destroy',nodes:['ceos'],status:'failed'}),{lab_id:'a',action:'destroy',options:{nodes:['ceos']}});
 assert.deepEqual(retry({id:'x',action:'save',nodes:['ceos','vsw'],status:'failed'}),{lab_id:'a',action:'save',options:{nodes:['ceos','vsw']}});
 assert.equal(c.opRetryRequest({id:'x',action:'deploy',nodes:['ceos'],status:'failed'},'a'),null,'a job with devices and no safe guess opens the dialog');
 assert.deepEqual(retry({id:'x',action:'destroy',status:'failed'}),{lab_id:'a',action:'destroy',options:{cleanup:true}},'the plain destroy is unchanged');
 assert.ok(!vm.runInContext("opPlainRetry.some(a=>a.endsWith('-node'))",c));
 c.jobRequest=id=>id==='s'?{lab_id:'a',action:'deploy',options:{nodes:['ceos'],max_workers:2}}:null;
 assert.deepEqual(retry({id:'s',action:'deploy',status:'cancelled'}),{lab_id:'a',action:'redeploy',options:{max_workers:2}},'a cancelled filtered deploy becomes a plain redeploy: redeploy takes no filter');
});
test('C05: the Stop device and Start device reviews say what happens, drop the lab-wide lines and name the one affected device',async()=>{
 const stop=c05Context({caps:c05Caps,preview:async()=>c05Value({action:'stop-node',node_label:'ceos',affected:[{name:'clab-square-ceos',state:'running'}]})});
 await stop.c.opReview({lab_id:'a',action:'stop-node',node:'clab-square-ceos',options:{}});
 const body=stop.shown.at(-1).body,title=stop.shown.at(-1).title;
 assert.equal(title,'Stop ceos?');
 assert.match(body,/Only ceos in square stops: containerlab stops its container and parks its links \(containerlab stop --node\)/);
 assert.match(body,/1 device affected: ceos \(clab-square-ceos, running\)\. The other devices of square are not stopped\./);
 assert.match(body,/id="op-confirm">Stop device</);assert.match(body,/button danger/);
 assert.doesNotMatch(body,/Configuration changes you have not saved are lost\.|Open CLI sessions to this lab will disconnect|running device affected|devices affected/);
 const start=c05Context({caps:c05Caps,preview:async()=>c05Value({action:'start-node',node_label:'vsw',affected:[{name:'clab-square-vsw',state:'exited'}]})});
 await start.c.opReview({lab_id:'a',action:'start-node',node:'clab-square-vsw',options:{}});
 assert.equal(start.shown.at(-1).title,'Start vsw?');assert.match(start.shown.at(-1).body,/1 device affected: vsw \(clab-square-vsw, exited\)\. The other devices of square are not started\./);
 assert.match(start.shown.at(-1).body,/id="op-confirm">Start device</);assert.doesNotMatch(start.shown.at(-1).body,/button danger/);
 assert.deepEqual(start.calls.filter(x=>x[0]==='notify'),[]);
 start.shown.at(-1);await start.el('op-confirm').onclick();
 assert.deepEqual(start.calls.filter(x=>x[0]==='notify').map(x=>x[1]),['Starting vsw…'],'the toast names the device');
 assert.equal(vm.runInContext("opDisruptive.includes('stop-node')&&!opDisruptive.includes('start-node')&&opLifecycle.includes('start-node')",start.c),true);
});
test('C05: the apply plan lists create, start, restart, recreate, remove and links in that order with reasons, and an empty plan says Nothing to apply',()=>{
 const {c}=c05Context();
 const plan={deploys_lab:false,added:['r3'],removed:['r9'],recreated:['r2'],started:['r4'],restarted:['r1'],links_added:['r1:eth1 -- r3:eth1'],endpoints_removed:['r9:eth1'],reasons:{r2:'config drift: Env',r1:'added link'}};
 const html=c.opPlanMarkup(plan,'');
 const order=[...html.matchAll(/<h4>([^<]+)</g)].map(m=>m[1]);
 assert.deepEqual(order,['Create (1)','Start (1)','Restart (1)','Recreate (1)','Remove (1)','Links to connect (1)','Link ends to disconnect (1)']);
 assert.match(html,/<li>r2 <small class="op-plan-reason">· config drift: Env<\/small><\/li>/);assert.match(html,/<li>r1 <small class="op-plan-reason">· added link<\/small><\/li>/);
 assert.match(html,/These devices are recreated: configuration you have not saved on them is lost\./);assert.match(html,/These devices are removed from the VM: their unsaved configuration is lost\./);
 assert.equal(c.opPlanMarkup({added:['r3']},'').includes('Start ('),false,'sections only when non-empty');
 assert.match(c.opPlanMarkup({deploys_lab:true,added:['a']},''),/The lab is not running: Apply deploys the whole topology\./);
 assert.equal(c.opPlanMarkup({added:[],reasons:{}},''),'<p class="op-plan-empty">Nothing to apply: the running lab already matches its topology file.</p>');
 assert.match(c.opPlanMarkup(null,'unsupported'),/The installed containerlab cannot show what Apply will change; the command runs without a plan\./);
 assert.equal(c.opPlanMarkup(null,'error'),'');
 assert.equal(c.opPlanSummary(plan),'r3 to create · r2 to recreate · r4 to start · r1 to restart · r9 to remove · 1 link to connect · 1 link end to disconnect');
 assert.equal(c.opPlanSummary({added:['a','b','c']}),'3 devices to create');assert.equal(c.opPlanSummary({added:[]}),'');
 assert.equal(c.opPlanIdentity({added:['a','b'],reasons:{x:'1',y:'2'}}),c.opPlanIdentity({reasons:{y:'2',x:'1'},added:['b','a'],checked_at:5}),'the same plan in another order is the same identity');
 assert.notEqual(c.opPlanIdentity({added:['a','b']}),c.opPlanIdentity({added:['a','b','c']}));
});
test('C05: the apply review shows the plan, keeps the generic loss and disconnect lines only while something changes, and offers Apply anyway for nothing to apply or a failed check',async()=>{
 const run=async value=>{const h=c05Context({caps:c05Caps,preview:async()=>c05Value(value)});await h.c.opReview({lab_id:'a',action:'apply',options:{}});return h.shown.at(-1).body;};
 const changes=await run({plan:{added:['r3'],reasons:{}},plan_failed:''});
 assert.match(changes,/<h4>Create \(1\)</);assert.match(changes,/Configuration changes you have not saved are lost\./);assert.match(changes,/Open CLI sessions to this lab will disconnect/);assert.match(changes,/id="op-confirm">Apply changes</);assert.match(changes,/button danger/);assert.doesNotMatch(changes,/running device affected/);
 const nothing=await run({plan:{added:[],reasons:{}},plan_failed:''});
 assert.match(nothing,/Nothing to apply: the running lab already matches its topology file\./);assert.doesNotMatch(nothing,/Configuration changes you have not saved are lost|Open CLI sessions/);
 assert.match(nothing,/button secondary" id="op-confirm">Apply anyway</);
 const failed=await run({plan:null,plan_failed:'error',warnings:['The topology file could not be read.']});
 assert.match(failed,/The topology file could not be read\./);assert.match(failed,/button danger" id="op-confirm">Apply anyway</);
 const unsupported=await run({plan:null,plan_failed:'unsupported'});
 assert.match(unsupported,/the command runs without a plan/);assert.match(unsupported,/id="op-confirm">Apply changes</);assert.match(unsupported,/Configuration changes you have not saved are lost\./);assert.match(unsupported,/1 running device affected/);
});
test('C05: Run with options shows only the controls the installed command has, per action, and Choose devices on deploy only while the lab is not deployed',()=>{
 const {c}=c05Context();const lab=c05.lab,idle={...lab,deployment:{status:'Not deployed'}};
 const ids=html=>[...html.matchAll(/id="(op-opt-[a-z-]+\d*)"/g)].map(m=>m[1]);
 assert.deepEqual(ids(c.opOptionsForm('destroy',c05Caps,lab,{})),['op-opt-node-0','op-opt-node-1','op-opt-workers','op-opt-keepnet','op-opt-graceful']);
 assert.deepEqual(ids(c.opOptionsForm('redeploy',c05Caps,lab,{})),['op-opt-workers','op-opt-skip','op-opt-keepnet','op-opt-graceful'],'redeploy takes no device filter');
 assert.deepEqual(ids(c.opOptionsForm('deploy',c05Caps,lab,{})),['op-opt-workers','op-opt-skip'],'a deployed lab cannot take a partial deploy');
 assert.deepEqual(ids(c.opOptionsForm('deploy',c05Caps,idle,{})),['op-opt-node-0','op-opt-node-1','op-opt-workers','op-opt-skip']);
 assert.deepEqual(ids(c.opOptionsForm('save',c05Caps,lab,{})),['op-opt-node-0','op-opt-node-1']);
 assert.equal(c.opOptionsForm('destroy',{actions:{destroy:{available:true}}},lab,{}),'','no flag, no fold');assert.equal(c.opOptionsForm('destroy',null,lab,{}),'');assert.equal(c.opOptionsForm('apply',c05Caps,lab,{}),'');
 const html=c.opOptionsForm('destroy',c05Caps,lab,{nodes:['ceos'],max_workers:2,graceful:true},true);
 assert.match(html,/<details class="op-options" id="op-run-options" open>/);assert.match(html,/data-opt-node="ceos" checked/);assert.doesNotMatch(html,/data-opt-node="vsw" checked/);assert.match(html,/id="op-opt-workers"[^>]*value="2"/);assert.match(html,/id="op-opt-graceful" checked/);
 assert.match(html,/The devices you leave out keep running; the lab folder is kept\./);assert.match(html,/removed after two minutes, and with several devices the waits add up/);
 assert.doesNotMatch(html,/style=/);
});
test('C05: option merging: chosen devices drop Clean up, no devices bring the plain defaults back, Max workers is a whole number from 1 to 64',()=>{
 const {c}=c05Context();vm.runInContext("opCaps={actions:{destroy:{cleanup:true}}}",c);const m=(a,p,f)=>plainJson(c.opMergeOptions(a,p,{nodes:[],maxWorkers:'',skip:false,keep:false,graceful:false,...f}));
 assert.deepEqual(m('destroy',{cleanup:true},{nodes:['ceos']}),{nodes:['ceos']});
 assert.deepEqual(m('destroy',{},{}),{cleanup:true},'unticking every device returns the plain Destroy lab request');
 assert.deepEqual(m('save',{},{nodes:['ceos','vsw'],maxWorkers:'3',skip:true,keep:true,graceful:true}),{nodes:['ceos','vsw'],max_workers:3,skip_post_deploy:true,keep_mgmt_net:true,graceful:true});
 assert.deepEqual(m('redeploy',{cleanup:true},{}),{cleanup:true});
 for(const bad of ['0','65','1.5','-1','abc','1e2'])assert.equal(c.opMaxWorkersProblem(bad),'Max workers must be a whole number from 1 to 64.',bad);
 for(const good of ['','1','64',' 8 '])assert.equal(c.opMaxWorkersProblem(good),'',good);
 assert.deepEqual(plainJson(c.opPlainOptions({cleanup:true,nodes:['a'],max_workers:2,graceful:true})),{cleanup:true});
 assert.equal(c.opGracefulNotice({graceful:true,max_workers:1},11),'With these options the command may take longer than the manager waits for it (about 22 minutes); choose more workers or leave Graceful stop off.');
 assert.equal(c.opGracefulNotice({graceful:true,max_workers:5},10),'');assert.equal(c.opGracefulNotice({graceful:false,max_workers:1},10),'');assert.equal(c.opGracefulNotice({graceful:true},10),'');
});
test('C05: a node-filtered destroy review names the devices, says what keeps running, offers no Clean up and shows the exact command; the fold re-previews the exact request',async()=>{
 const requests=[];
 const h=c05Context({caps:c05Caps,preview:async r=>{requests.push(plainJson(r));return c05Value({action:'destroy',kept:['clab-square-vsw'],argv:['containerlab','destroy','-t','x','--node-filter','ceos'],affected:[{name:'clab-square-ceos',state:'running'}]});}});
 await h.c.opReview({lab_id:'a',action:'destroy',options:{nodes:['ceos'],max_workers:2}});
 const body=h.shown.at(-1).body;
 assert.equal(h.shown.at(-1).title,'Destroy ceos in square?');assert.match(body,/The chosen devices are removed from the VM; the other devices and the lab folder stay\./);
 assert.match(body,/<p class="op-kept">Left running: vsw<\/p>/);assert.doesNotMatch(body,/clab-square-vsw/,'the review names short names, not containers');assert.match(body,/id="op-confirm">Destroy ceos</,'the button names the device of a filtered destroy');assert.match(body,/--node-filter/);assert.doesNotMatch(body,/lab folder is deleted|Clean up/);
 assert.match(body,/data-opt-node="ceos" checked/);assert.ok(h.calls.some(x=>x[0]==='api'&&x[1]==='/operations/capabilities'),'capabilities are read before the review');
 // a toast after confirming names the devices
 await h.el('op-confirm').onclick();assert.deepEqual(h.calls.filter(x=>x[0]==='notify').map(x=>x[1]),['Destroying ceos…']);
});
test('C05: a re-preview carries a sequence number: an answer older than the newest request is dropped and never shown',async()=>{
 const resolvers=[];
 const h=c05Context({caps:c05Caps,preview:r=>new Promise(res=>resolvers.push(()=>res(c05Value({action:'destroy',token:'t'+resolvers.length,affected:[]}))))});
 vm.runInContext('opCaps='+JSON.stringify(c05Caps),h.c);
 const first=h.c.opReview({lab_id:'a',action:'destroy',options:{cleanup:true}},undefined,{keepOptionsOpen:true});
 const second=h.c.opReview({lab_id:'a',action:'destroy',options:{nodes:['ceos']}},undefined,{keepOptionsOpen:true});
 await new Promise(r=>setImmediate(r));
 assert.equal(resolvers.length,2);resolvers[1]();await second;resolvers[0]();const dropped=await first;
 assert.equal(dropped,null,'the older answer is dropped');assert.equal(h.shown.length,1,'only the newest answer is shown');assert.match(h.shown[0].body,/data-opt-node="ceos" checked/);
});
test('C05: opOptionsChanged disables the fold with Checking…, previews the merged request, keeps the fold open and sends focus back; a refused preview disables Confirm and shows the sentence',async()=>{
 const els={err:{textContent:''},set:{disabled:false},status:{textContent:''},confirm:{disabled:false,title:''},workers:null};
 const map={'.form-error':'err','#op-options-set':'set','#op-options-status':'status','#op-confirm':'confirm'};
 const dialog={querySelector:sel=>sel==='#op-opt-workers'?els.workers:els[map[sel]]||null,querySelectorAll:sel=>sel==='[data-opt-node]'?[{checked:true,dataset:{optNode:'ceos'}},{checked:false,dataset:{optNode:'vsw'}}]:[]};
 const h=c05Context({caps:c05Caps});const previews=[];h.c.opReview=async(request,opener,extra)=>{previews.push([plainJson(request),plainJson(extra),els.set.disabled,els.status.textContent]);};
 await h.c.opOptionsChanged(dialog,{lab_id:'a',action:'destroy',options:{cleanup:true}},null,{cleanup:true},{id:'op-opt-node-0'});
 assert.deepEqual(previews,[[{lab_id:'a',action:'destroy',options:{nodes:['ceos']}},{keepOptionsOpen:true,focusId:'op-opt-node-0',plain:{cleanup:true}},true,'Checking…']]);
 h.c.opReview=async()=>{throw new Error("Choose devices from this lab's topology file: x is not in it.");};
 await h.c.opOptionsChanged(dialog,{lab_id:'a',action:'destroy',options:{}},null,{},{id:'op-opt-node-0'});
 assert.equal(els.set.disabled,false);assert.equal(els.status.textContent,'');assert.match(els.err.textContent,/is not in it/);assert.equal(els.confirm.disabled,true);
 els.err.textContent='';els.workers={value:'99'};let called=0;h.c.opReview=async()=>{called++;};
 await h.c.opOptionsChanged(dialog,{lab_id:'a',action:'destroy',options:{}},null,{},{id:'op-opt-workers'});
 assert.equal(called,0,'an invalid Max workers is not previewed');assert.equal(els.err.textContent,'Max workers must be a whole number from 1 to 64.');
});
test('C05: opPlanDue fires on exactly four triggers: open, a finished job, a sync and nothing else; never a timer',()=>{
 const {c}=c05Context();const lab=c05.lab,memo0={lab:'',active:false,jobs:[],sig:''};
 assert.deepEqual(plainJson(vm.runInContext('opPlanTriggers',c)),['open','job','sync','review']);
 let r=c.opPlanDue(memo0,lab,[]);assert.equal(r.reason,'open');
 let again=c.opPlanDue(r.memo,lab,[]);assert.equal(again.reason,'','no trigger without a change: a render every 4 s asks nothing');
 const jobs=[{id:'j1',lab_id:'a',status:'running'}];assert.equal(c.opPlanDue(again.memo,lab,jobs).reason,'','a running job is not a trigger');
 jobs[0].status='succeeded';r=c.opPlanDue(again.memo,lab,jobs);assert.equal(r.reason,'job');assert.equal(c.opPlanDue(r.memo,lab,jobs).reason,'','a terminal job triggers once');
 assert.equal(c.opPlanDue(r.memo,lab,[...jobs,{id:'j2',lab_id:'other',status:'succeeded'}]).reason,'','another lab\'s job is not ours');
 const synced={...lab,vm_source:{status:'Up to date',synced_digest:'d2',digest:'d2'}};
 const before=c.opPlanDue(memo0,{...lab,vm_source:{status:'Updates available',synced_digest:'d1',digest:'d2'}},[]);
 assert.equal(c.opPlanDue(before.memo,synced,[]).reason,'sync');
 assert.equal(c.opPlanDue(r.memo,{...lab,deployment:{status:'Not deployed'}},jobs).reason,'','a lab that is not running asks nothing');
 assert.equal(c.opPlanDue({...r.memo,lab:'zzz'},lab,jobs).reason,'open','opening another lab asks again');
 assert.equal(c.opPlanDue(memo0,null,[]).reason,'');
 assert.ok(!/setInterval|setTimeout/.test(vm.runInContext('[opWatchLab,opPlanDue,opLoadPlan,opLoadImpairments].map(String).join()',c)));
});
test('C05: opWatchLab asks the apply plan and the impairments once when a running lab opens, and Review changes… asks again with refresh=1',async()=>{
 const h=c05Context({caps:c05Caps});const asked=[];
 h.c.apiImpl=url=>{asked.push(url);return url.startsWith('/operations/apply-plan')?{changed:true,plan:{added:['r3'],reasons:{}},failed:'',checked_at:1}:{devices:{},interfaces:0,complete:true};};
 h.c.opWatchLab(c05.lab);await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
 assert.deepEqual(asked.sort(),['/operations/apply-plan?lab_id=a','/operations/impairments?lab_id=a']);
 h.c.opWatchLab(c05.lab);await new Promise(r=>setImmediate(r));assert.equal(asked.length,2,'the next render asks nothing');
 h.c.opReview=async()=>{asked.push('review');};await h.c.opReviewChanges('a');
 assert.deepEqual(asked.slice(2),['/operations/apply-plan?lab_id=a&refresh=1','review']);
 assert.equal(h.c.opPendingChanges(c05.lab).plan.added[0],'r3');
});
test('C05: the pending notice: a Running lab with differences offers Review changes… once per plan; a dismissed notice stays dismissed for the same plan and returns for a different one',()=>{
 const h=c05Context();const c=h.c,lab=c05.lab;
 assert.equal(c.opPendingBannerSpec(lab),null,'nothing checked: no notice');
 const set=(answer)=>vm.runInContext('opPlanCache='+JSON.stringify({a:{answer,error:'',at:1}}),c);
 set({changed:false,plan:{added:[]},failed:'',checked_at:1});assert.equal(c.opPendingBannerSpec(lab),null);
 set({changed:true,plan:{added:['r3'],recreated:['r2'],links_added:['x'],reasons:{r2:'config drift'}},failed:'',checked_at:1});
 const spec=c.opPendingBannerSpec(lab);
 assert.equal(spec.text,'The topology file differs from the running lab.');assert.equal(spec.detail,'r3 to create · r2 to recreate · 1 link to connect');assert.deepEqual(Object.keys(spec.actions),['banner-review']);assert.equal(spec.actions['banner-review'].label,'Review changes…');
 const first=spec.identity;set({changed:true,plan:{added:['r3'],recreated:['r2'],links_added:['x'],reasons:{r2:'config drift'}},failed:'',checked_at:99});
 assert.equal(c.opPendingBannerSpec(lab).identity,first,'the same plan re-checked keeps its identity (check time excluded)');
 set({changed:true,plan:{added:['r3','r4'],recreated:['r2'],links_added:['x'],reasons:{r2:'config drift'}},failed:'',checked_at:99});
 assert.notEqual(c.opPendingBannerSpec(lab).identity,first,'one more device is a different notice');
 assert.equal(c.opPendingBannerSpec({...lab,deployment:{status:'Partially running'}}),null,'a Partially running lab uses the attention branch');
 set({changed:false,plan:null,failed:'error',error:'x'});assert.equal(c.opPendingBannerSpec(lab),null,'a failed check never claims differences');
});
test('C05: a Partially running lab with a device to create or recreate offers Review changes… instead of Start; a started-only plan keeps Start',()=>{
 const {c}=c05Context();const lab={...c05.lab,deployment:{status:'Partially running'}};
 const base={tone:'danger',icon:'alert',text:'Some devices are not running.',actions:{'banner-start':{label:'Start stopped devices'}}};
 const set=plan=>vm.runInContext('opPlanCache='+JSON.stringify({a:{answer:{changed:true,plan,failed:''},error:'',at:1}}),c);
 assert.equal(plainJson(c.opAttentionSpec(lab,base)).actions['banner-start'].label,'Start stopped devices','no plan: Start');
 set({added:['ceos'],reasons:{}});let spec=plainJson(c.opAttentionSpec(lab,base));
 assert.deepEqual(Object.keys(spec.actions),['banner-review']);assert.equal(spec.detail,'ceos to create');assert.match(spec.identity,/^pending\./);assert.equal(spec.text,base.text);
 set({recreated:['ceos'],reasons:{}});assert.deepEqual(Object.keys(c.opAttentionSpec(lab,base).actions),['banner-review']);
 set({endpoints_removed:['a:eth1'],reasons:{}});assert.deepEqual(Object.keys(c.opAttentionSpec(lab,base).actions),['banner-review']);
 set({started:['vsw'],reasons:{}});assert.deepEqual(Object.keys(c.opAttentionSpec(lab,base).actions),['banner-start'],'a stopped device is started, not recreated');
 assert.equal(c.opAttentionSpec({...lab,deployment:{status:'Running'}},base),base);
});
test('C05: the Deployment details line reads Not checked, Matches, Differs with Review changes…, or could not be checked',()=>{
 const {c}=c05Context();
 assert.equal(c.opPendingMarkup(undefined),'Not checked');
 assert.match(c.opPendingMarkup({answer:{changed:false,plan:{},failed:'',checked_at:1700000000}}),/^Matches the running lab/);
 assert.match(c.opPendingMarkup({answer:{changed:true,plan:{added:['r3']},failed:''}}),/^Differs from the running lab: r3 to create — <button type="button" class="button ghost small" data-pending-review>Review changes…<\/button>$/);
 assert.equal(c.opPendingMarkup({answer:{changed:false,failed:'error',error:'Failed to read <x>'}}),'Could not be checked: Failed to read &lt;x&gt;');
 assert.match(c.opPendingMarkup({answer:{failed:'unsupported'}}),/^Not checked: the installed containerlab cannot compare/);
 assert.equal(c.opPendingMarkup({answer:null,error:'The VM is busy'}),'Could not be checked: The VM is busy');
});
test('C05: Lab actions ▾ has Apply topology changes… enabled on Running and Partially running through the shared rule',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 assert.match(html,/data-op-action="apply" data-op-options="\{\}" disabled><span>Apply topology changes…<\/span>/);
 const order=[...html.matchAll(/id="lab-actions-menu"[\s\S]*?<\/div>/g)][0][0];assert.ok(order.indexOf('Restart all devices')<order.indexOf('Apply topology changes')&&order.indexOf('Apply topology changes')<order.indexOf('menu-sep'));
 for(const status of ['Running','Partially running','Stopped','Not deployed']){
  const button={dataset:{opAction:'apply',opOptions:'{}'},disabled:true,title:'',querySelector:()=>null};
  const lab={...c05.lab,deployment:{status}};const h=c05Context({labs:[lab]});h.c.current=()=>lab;h.c.$=id=>id==='lab-actions-menu'?{querySelectorAll:()=>[button]}:null;
  h.c.renderLabOperations();assert.equal(button.disabled,!['Running','Partially running'].includes(status),status);
 }
});
test('C05: Clear impairments asks once, shows Clearing… while it runs, and reports a partial result with the way on',async()=>{
 const h=c05Context({caps:c05Caps});const els=h.el;
 vm.runInContext("opImpairmentCache={a:{devices:{'clab-square-ceos':{impairments:[{interface:'eth1'},{interface:'eth2'}]},'clab-square-vsw':{impairments:[{interface:'eth1'}]},x:{impairments:[]}},interfaces:3,complete:true}}",h.c);
 assert.deepEqual(plainJson(h.c.opImpairmentCount(vm.runInContext('opImpairmentCache.a',h.c))),{interfaces:3,devices:2});
 let release;h.c.json=async(url,method,body)=>{h.calls.push(['json',url,body]);await new Promise(r=>{release=r;});return {cleared:2,total:3,failed:[{node:'clab-square-vsw',interface:'eth1',reason:'Link not found.'}],remaining:[{node:'clab-square-vsw',interface:'eth1'}]};};
 h.c.opLoadImpairments=async()=>null;
 await h.c.opClearImpairments('a');
 assert.equal(h.shown.at(-1).title,'Remove every impairment in square (3 interfaces on 2 devices)?');
 const confirm=els('op-clear-confirm'),status=els('op-clear-status');const pending=confirm.onclick();
 await Promise.resolve();assert.equal(confirm.textContent,'Clearing…');assert.equal(confirm.disabled,true);
 release();await pending;
 assert.equal(status.textContent,'2 of 3 interfaces cleared; vsw eth1: Link not found. Try again.');
 assert.equal(confirm.disabled,false);assert.equal(confirm.textContent,'Clear all');assert.deepEqual(plainJson(h.calls.filter(x=>x[0]==='json'&&x[1].endsWith('/clear')).map(x=>x[2])),[{lab_id:'a'}]);
});

test('C05: a whole-lab destroy keeps the Destroy lab button; Save lists short names; the destroy device help pins the recreate sentence',async()=>{
 const h=c05Context({caps:c05Caps,preview:async r=>c05Value({action:r.action,kept:['clab-square-vsw'],affected:[]})});
 await h.c.opReview({lab_id:'a',action:'destroy',options:{}});
 assert.match(h.shown.at(-1).body,/id="op-confirm">Destroy lab</);
 await h.c.opReview({lab_id:'a',action:'save',options:{nodes:['ceos']}});
 assert.match(h.shown.at(-1).body,/<p class="op-kept">Not saved: vsw<\/p>/);
 const html=h.c.opOptionsForm('destroy',c05Caps,c05.lab,{});
 assert.match(html,/Apply may also recreate the neighbours of a re-created device when their kind cannot add links live; the review lists them\./);
});
test('C05 B1: Confirm is disabled with a reason while a Run-with-options re-preview is pending, and a click in that window sends nothing',async()=>{
 const els={err:{textContent:''},set:{disabled:false},status:{textContent:''},confirm:{disabled:false,title:''}};
 const map={'.form-error':'err','#op-options-set':'set','#op-options-status':'status','#op-confirm':'confirm'};
 const dialog={querySelector:sel=>els[map[sel]]||null,querySelectorAll:()=>[]};
 const h=c05Context({caps:c05Caps,preview:async()=>c05Value({action:'destroy',token:'old'})});
 await h.c.opReview({lab_id:'a',action:'destroy',options:{cleanup:true}});
 const confirmButton=h.el('op-confirm');
 let release;const during=[];
 h.c.opReview=()=>new Promise(res=>{during.push([els.confirm.disabled,els.confirm.title]);release=res;});
 const pending=h.c.opOptionsChanged(dialog,{lab_id:'a',action:'destroy',options:{}},null,{},{id:'op-opt-node-0'});
 assert.deepEqual(during,[[true,'Checking the new options…']],'Confirm is already off when the new preview starts');
 confirmButton.disabled=true;
 const before=h.calls.length;await confirmButton.onclick();
 assert.equal(h.calls.slice(before).filter(x=>x[0]==='json').length,0,'a click during the window sends nothing');
 release();await pending;
 confirmButton.disabled=false;await confirmButton.onclick();
 assert.deepEqual(plainJson(h.calls.filter(x=>x[0]==='json'&&x[1]==='/operations/confirm').map(x=>x[2])),[{token:'old'}],'a live button confirms');
});
test('C05: the sync trigger asks the apply plan with refresh; Stop device allows running and unknown',async()=>{
 const h=c05Context({caps:c05Caps});const asked=[];
 h.c.apiImpl=url=>{asked.push(url);return url.startsWith('/operations/apply-plan')?{changed:false,plan:null,failed:'',checked_at:1}:{devices:{},interfaces:0,complete:true};};
 const before={...c05.lab,vm_source:{status:'Updates available',synced_digest:'d1',digest:'d2'}},after={...c05.lab,vm_source:{status:'Up to date',synced_digest:'d2',digest:'d2'}};
 h.c.opWatchLab(before);await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
 assert.ok(asked.includes('/operations/apply-plan?lab_id=a'),'open: from the cache');
 asked.length=0;h.c.opWatchLab(after);await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
 assert.ok(asked.includes('/operations/apply-plan?lab_id=a&refresh=1'),'sync: the server cache is bypassed');
 const d={connected:true},[ceos]=c05.lab.nodes;
 assert.equal(h.c.opNodeActionState('stop-node',c05.lab,{...ceos,runtime_state:'unknown'},d).ok,true);
 assert.equal(h.c.opNodeActionState('stop-node',c05.lab,{...ceos,runtime_state:'exited'},d).ok,false);
});
test('C05: a partial Clear names the port, and the dialog returns focus to the map Fit button',async()=>{
 const h=c05Context({caps:c05Caps});const openers=[];
 const base=h.c.opDialog;h.c.opDialog=(id,title,body,opener)=>{openers.push(opener);return base(id,title,body,opener);};
 h.el('map-fit').marker='fit';
 vm.runInContext("opImpairmentCache={a:{devices:{'clab-square-vsw':{impairments:[{interface:'eth3',port:'Ethernet3'}]}},interfaces:1,complete:true}}",h.c);
 h.c.json=async()=>({cleared:0,total:1,failed:[{node:'clab-square-vsw',interface:'eth3',reason:'Link not found.'}],remaining:[]});
 h.c.opLoadImpairments=async()=>null;
 await h.c.opClearImpairments('a');
 assert.equal(openers[0].marker,'fit');
 await h.el('op-clear-confirm').onclick();
 assert.equal(h.el('op-clear-status').textContent,'0 of 1 interfaces cleared; vsw Ethernet3: Link not found. Try again.');
});
test('C05: a Start device or Stop device job that finishes while the page is open raises one toast; one already finished at load does not',()=>{
 const h=c05Context();const jobs=[{id:'j0',lab_id:'a',action:'stop-node',status:'succeeded',node_label:'vsw'}];
 h.c.opWatchLab(c05.lab);
 const toasts=()=>h.calls.filter(x=>x[0]==='notify').map(x=>x[1]);
 const run=list=>{h.c.state.operations=list;h.c.opWatchLab(c05.lab);};
 run(jobs);assert.deepEqual(toasts(),[],'finished before this page saw it running');
 run([{id:'j1',lab_id:'a',action:'stop-node',status:'running',node_label:'ceos'}]);assert.deepEqual(toasts(),[]);
 run([{id:'j1',lab_id:'a',action:'stop-node',status:'succeeded',node_label:'ceos'}]);assert.deepEqual(toasts(),['✔ ceos stopped']);
 run([{id:'j1',lab_id:'a',action:'stop-node',status:'succeeded',node_label:'ceos'}]);assert.equal(toasts().length,1,'once');
 run([{id:'j2',lab_id:'a',action:'start-node',status:'queued',node_label:'ceos'}]);
 run([{id:'j2',lab_id:'a',action:'start-node',status:'failed',node_label:'ceos'}]);assert.match(toasts()[1],/^✖ Start device failed|^✖ .*failed/);
});

// T06b (campaign 2, topology editing): the lab page's side of Edit topology…, the plan limits and the retired destroy sentence.
test('T06b: the Edit topology… entry opens the lab builder on the lab file with the lab id, and says why when it cannot',()=>{
 const lab={id:'demo',vm_project_path:'/srv/containerlab-node-manager/projects/demo/demo.clab.yml',deployment:{status:'Running'}},up={connected:true};
 const reason=(l,d,busy,caps)=>context.opTopologyEditReason(l,d,busy,caps);
 assert.equal(reason(lab,up,false,null),'','capabilities not loaded yet: the entry is offered, the server decides');
 assert.equal(reason(lab,up,false,{actions:{revise:{available:true,deployed:true}},roots:['/srv/containerlab-node-manager/projects']}),'');
 assert.equal(reason(null,up,false,null),'','no lab on screen: nothing to explain');
 assert.equal(reason({...lab,vm_project_path:''},up,false,null),'This lab has no topology file on the VM (Advanced › Deployment details)');
 assert.equal(reason(lab,{connected:false},false,null),'Connect the VM first');
 assert.match(reason(lab,up,false,{actions:{revise:{available:false}}}),/^The VM helpers are older than the manager/);
 assert.equal(reason(lab,up,false,{actions:{revise:{available:false,reason:'Not available on this VM'}}}),'Not available on this VM','a reason the capabilities carry wins');
 assert.equal(reason(lab,up,true,null),'Wait for the current operation to finish');
 assert.equal(reason({...lab,deployment:{status:'Unknown'}},up,false,null),'Lab status is unknown — refresh the lab list');
 assert.equal(reason(lab,up,false,{roots:['/etc/containerlab']}),'The topology file is outside the folders the manager may edit');
 assert.equal(reason({...lab,vm_project_path:'/etc/containerlab/x.clab.yml'},up,false,{roots:['/etc/containerlab/']}),'','a trailing slash on a root changes nothing');
 for(const status of ['Not deployed','Running','Stopped','Partially running'])assert.equal(reason({...lab,deployment:{status}},up,false,null),'',status);
  const navigated=[];const c=vm.createContext({$:()=>null,URLSearchParams,esc:context.esc,location:{pathname:'/',assign:u=>navigated.push(u)},state:{labs:[lab,{id:'bare',vm_project_path:''}]}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 assert.equal(c.opTopologyEdit('demo'),true);assert.deepEqual(navigated,['/static/lab-builder.html#path=%2Fsrv%2Fcontainerlab-node-manager%2Fprojects%2Fdemo%2Fdemo.clab.yml&lab=demo']);
 assert.equal(c.opTopologyEdit('bare'),false);assert.equal(c.opTopologyEdit('missing'),false);assert.equal(navigated.length,1,'no file, no lab: no navigation');
});
test('T06b: the Topology-file dialog offers Edit topology… (one name) and hands the builder the lab it belongs to',()=>{
 const src=fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8');
 assert.match(src,/id="op-build-edit"[^>]*>Edit topology…<\/button>/);assert.equal(src.includes('Open in Lab Builder…'),false,'one name for the entry everywhere');
 assert.match(src,/opBuilderOpen\(\{path,lab:labId\}\)/,'a dialog opened from a lab in My labs carries the lab; a free file has an empty id, which opBuilderUrl drops');
});
test('T06b: the plan prints a device\'s limit under its restart or recreate row, only there, and the limits never change the plan identity',()=>{
 const plan={restarted:['xr1'],recreated:['v1'],added:['r3'],reasons:{v1:'image changed'},limits:{xr1:'Restart keeps the configuration only after a commit on this kind.',v1:'A recreated vJunos starts empty.',r3:'never shown on a created row'}};
 const html=context.opPlanMarkup(plan,'');
 assert.match(html,/<li>xr1<br><small class="op-plan-reason">Restart keeps the configuration only after a commit on this kind\.<\/small><\/li>/);
 assert.match(html,/<li>v1 <small class="op-plan-reason">· image changed<\/small><br><small class="op-plan-reason">A recreated vJunos starts empty\.<\/small><\/li>/);
 assert.doesNotMatch(html,/never shown/);
 assert.equal(context.opPlanMarkup({restarted:['a'],limits:{a:'<b>x</b>'}},'').includes('&lt;b&gt;x&lt;/b&gt;'),true,'escaped');
 assert.doesNotThrow(()=>context.opPlanMarkup({restarted:['a'],limits:'text'},''));
 const {limits,...without}=plan;
 assert.equal(context.opPlanIdentity(plan),context.opPlanIdentity(without),'the same plan with other limits is the same plan');
 assert.equal(context.opPlanIdentity({...plan,limits:{xr1:'other'}}),context.opPlanIdentity(plan));
});
test('T06b: the apply review names the devices to back up first, above the plan, and says nothing when the list is empty',async()=>{
 const run=async value=>{const h=c05Context({caps:c05Caps,preview:async()=>c05Value(value)});await h.c.opReview({lab_id:'a',action:'apply',options:{}});return h.shown.at(-1).body;};
 const body=await run({plan:{restarted:['xr1'],reasons:{}},plan_failed:'',backup_first:['xr1','v<1>']});
 assert.match(body,/<p class="op-notice" id="op-backup-first">Back up these devices first: xr1, v&lt;1&gt; — their configuration is lost when they restart or are recreated\. Save \(lab header\) or Back up configuration keeps it\.<\/p>/);
 assert.ok(body.indexOf('id="op-backup-first"')<body.indexOf('id="op-plan"'),'above the plan');
 for(const none of [[],undefined,'xr1'])assert.doesNotMatch(await run({plan:{restarted:['xr1'],reasons:{}},plan_failed:'',backup_first:none}),/op-backup-first/,JSON.stringify(none));
 assert.equal(context.opBackupFirstMarkup(['a']).includes('Back up these devices first: a'),true);
});
test('T06b (A6): the revise review no longer says a deployed lab cannot be saved; the server\'s warnings carry the deployed sentences',()=>{
 const copy=vm.runInContext("opReviewCopy.revise",context),body=copy.body({});
 assert.equal(body,'Replaces the topology file and the map layout on the VM. A copy of the previous version is kept in the lab folder.');
 assert.doesNotMatch(body,/not deployed|destroy/i);
 const src=fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),top=fs.readFileSync(path.join(__dirname,'../app/static/topology.js'),'utf8');
 for(const [name,text] of [['operations.js',src],['topology.js',top]])assert.doesNotMatch(text,/(destroyed? (the lab )?first|only possible while the lab is not deployed)/i,name+' keeps no "destroy first" sentence about saving a topology');
});

// T06-fix 2: the output dialog of a deployed save never says "It is not running yet." and never offers Deploy now.
test('a deployed save (revise with deployed) says the running lab is unchanged and offers only Back to lab and review changes…',async()=>{
 const run=async(job,labs)=>{
  const elements=new Map(),assigned=[],listeners={};
  for(const id of ['op-job-banner','op-job-output','op-job-result'])elements.set(id,{hidden:false,className:'',textContent:'',innerHTML:'',scrollTop:0,scrollHeight:0,clientHeight:0,addEventListener(){}});
  elements.set('op-back-review',{addEventListener(name,fn){listeners[name]=fn;}});
  const rendered=[];
  const c=vm.createContext({$:id=>elements.get(id)||null,esc:s=>String(s),state:{labs},console,document:{getElementById:()=>null},setTimeout:()=>1,clearTimeout(){},location:{assign:u=>assigned.push(u)},
   api:async()=>({json:async()=>job}),refresh:async()=>{},builderGo(){}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
  c.opDialog=()=>({open:true,classList:{toggle(){}},querySelector:()=>({textContent:''}),querySelectorAll:()=>[]});
  c.opRenderPublished=(d,p)=>rendered.push(p);
  await c.opShowJob('j');
  return {html:elements.get('op-job-result').innerHTML,rendered,assigned,click:()=>listeners.click&&listeners.click()};
 };
 const labs=[{id:'L 1',vm_project_path:'/srv/p/demo/demo.clab.yml'}];
 for(const job of [{id:'j',action:'revise',name:'demo',lab_id:'L 1',status:'succeeded',output:'',options:{deployed:true},result:{published_path:'/srv/p/demo/demo.clab.yml'}},{id:'j',action:'revise',name:'demo',status:'succeeded',output:'',result:{published_path:'/srv/p/demo/demo.clab.yml',deployed:true}}]){
  const r=await run(job,labs);
  assert.match(r.html,/Saved to the VM\. The running lab is unchanged until you apply the changes\./);
  assert.match(r.html,/id="op-back-review">Back to lab and review changes…/);
  assert.doesNotMatch(r.html,/not running yet|op-published-deploy|op-published-go|op-published-block|op-open-published|Deploy now/,'no Deploy now for a lab that keeps running');
  assert.deepEqual(r.rendered,[],'the Add / Deploy block is not rendered');
  r.click();assert.deepEqual(r.assigned,['/#lab=L%201&view=topology&review=apply']);
 }
 const plain=await run({id:'j',action:'revise',name:'demo',status:'succeeded',output:'',result:{published_path:'/srv/p/demo/demo.clab.yml'}},labs);
 assert.match(plain.html,/It is not running yet\./,'a revision of a lab that was not deployed keeps the old words');assert.match(plain.html,/op-published-block/);
});

test('a deployed save is recognised from the builder page when the job record itself does not say so, and the memory is per job',async()=>{
 const c=vm.createContext({$:()=>null,esc:s=>String(s),state:{labs:[]},console,document:{getElementById:()=>null}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/operations.js'),'utf8'),c);
 const job={id:'j1',action:'revise',status:'succeeded',result:{published_path:'/p/a.clab.yml'}};
 assert.equal(c.opDeployedSave(job),false,'nothing says it');
 vm.runInContext("var builderPending={action:'revise',deployed:true,job:'j1'}",c);
 assert.equal(c.opDeployedSave(job),true);
 vm.runInContext("builderPending=null",c);assert.equal(c.opDeployedSave(job),true,'remembered once the page forgot the pending save');
 assert.equal(c.opDeployedSave({...job,id:'j2'}),false,'another job is not');assert.equal(c.opDeployedSave({...job,action:'publish'}),false);
 assert.equal(c.opDeployedSave({...job,id:'j3',deployed:true}),true,'the job record carries the flag (the manager sets it at confirm)');
});
