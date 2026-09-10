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

test('deployment landing page opens topology browser only on an explicit click',async()=>{
 const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,{});return elements.get(id);};
 let browses=0;
 const page=vm.createContext({document:{getElementById:element,addEventListener:()=>{}},location:{hash:'#mode=folder'},URLSearchParams,
  fetch:async()=>({ok:true,json:async()=>({labs:[],jobs:[],operations:[]})}),opBrowse:async()=>browses++});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/workspace.js'),'utf8'),page);
 await page.launchWorkspace();
 assert.equal(browses,0);assert.equal(element('workspace-title').textContent,'Deploy New Lab');
});
