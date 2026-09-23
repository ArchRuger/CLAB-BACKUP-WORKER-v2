// The retired telemetry feature leaves nothing in the manager UI except one migration notice: a lab
// banner naming the devices that still carry configuration lines the removed feature once added
// (lab.telemetry_retired, set by the backend only while such lines remain), and a dialog to review and
// remove them. Everything else the feature used to show (the Telemetry tool card, its menu item, the
// Grafana link and page) is gone — asserted here and in test_shell_ui.js, test_status_ui.js,
// test_readiness_ui.js and test_operations_ui.js, which each keep their own retained claims and lose
// only the telemetry-specific ones.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const STATIC=path.join(__dirname,'../app/static');

// setBanner (app.js) needs shell.js's noticeDismissed/dismissNotice, so this harness loads status.js,
// shell.js and app.js in production order — the same harness test_shell_ui.js uses for setBanner.
function bannerHarness(){
 const elements=new Map();
 function element(){
  const classes=new Set();
  return {dataset:{},value:'',innerHTML:'',textContent:'',title:'',open:false,disabled:false,hidden:false,className:'',attrs:{},listeners:{},
   addEventListener(name,fn){(this.listeners[name]=this.listeners[name]||[]).push(fn);},
   setAttribute(n,v){this.attrs[n]=String(v);},getAttribute(n){return n in this.attrs?this.attrs[n]:null;},removeAttribute(n){delete this.attrs[n];},
   classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c),toggle(c,force){const on=force===undefined?!classes.has(c):!!force;if(on)classes.add(c);else classes.delete(c);return on;}},
   showModal(){this.open=true;},close(){this.open=false;},appendChild(){},remove(){},click(){},reset(){},querySelector(){return null;},querySelectorAll(){return [];}};
 }
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},addEventListener(){},querySelectorAll(){return [];},querySelector(){return null;},createElement:element,body:element()};
 const session=new Map();
 const context=vm.createContext({document,sessionStorage:{getItem:k=>session.has(k)?session.get(k):null,setItem:(k,v)=>session.set(k,String(v)),removeItem:k=>session.delete(k)},localStorage:{getItem(){return null;},setItem(){},removeItem(){}},setTimeout:()=>0,clearTimeout(){},setInterval(){},URL:{createObjectURL:()=>'blob:fixture',revokeObjectURL(){}},URLSearchParams,Blob,console,location:{hash:'',pathname:'/',search:''},history:{pushState(){},replaceState(){}}});
 context.window=context;context.addEventListener=()=>{};
 vm.runInContext(fs.readFileSync(path.join(STATIC,'status.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(STATIC,'shell.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(STATIC,'app.js'),'utf8'),context);
 return {context,$:id=>document.getElementById(id)};
}
// app.js declares `let state`/`let activeId`: a plain property assignment on the context object (as
// other harnesses set on scripts that never shadow the name, e.g. shell.js's own `activeId`) does not
// reach that lexical binding here, so the active lab and its data are set by running an assignment
// inside the context itself, the same way the existing "topology rail" test in test_shell_ui.js does.
function setLab(context,lab,extra={}){
 vm.runInContext(`activeId='lab';state=${JSON.stringify({labs:[lab],jobs:[],operations:[],restore_jobs:[],git_jobs:[],platforms:{},loaded:true,...extra})};`,context);
}

test('the retired-telemetry notice names the short-named devices, adds the malformed caveat, and a running operation keeps precedence',()=>{
 const h=bannerHarness();
 const lab={id:'lab',name:'demo',nodes:[],deployment:{status:'Running'},telemetry_retired:{nodes:[{name:'clab-demo-cjunosevolved',short_name:'cjunosevolved'}],total:1,malformed:false}};
 setLab(h.context,lab);
 h.context.renderLabBanner();
 const banner=h.$('lab-banner'),text=h.$('lab-banner-text'),button=h.$('banner-retired-review');
 assert.equal(banner.hidden,false);
 assert.equal(text.textContent,'Configuration lines added by the retired telemetry feature are still on: cjunosevolved.');
 assert.equal(button.hidden,false);assert.equal(button.textContent,'Review and remove…');
 // Several devices: short names, comma separated.
 lab.telemetry_retired={nodes:[{name:'clab-demo-cjunosevolved',short_name:'cjunosevolved'},{name:'clab-demo-ceos',short_name:'ceos'}],total:2,malformed:false};
 setLab(h.context,lab);
 h.context.renderLabBanner();
 assert.equal(text.textContent,'Configuration lines added by the retired telemetry feature are still on: cjunosevolved, ceos.');
 // A stored ledger that could not be read adds the caveat sentence.
 lab.telemetry_retired.malformed=true;
 setLab(h.context,lab);
 h.context.renderLabBanner();
 assert.equal(text.textContent,'Configuration lines added by the retired telemetry feature are still on: cjunosevolved, ceos. A telemetry record of this lab could not be read and is kept for review.');
 // A running lab operation is a higher-priority notice and takes the banner instead.
 setLab(h.context,lab,{operations:[{id:'op1',lab_id:'lab',status:'running',action:'deploy',message:''}]});
 h.context.renderLabBanner();
 assert.doesNotMatch(text.textContent,/retired telemetry/,'the running-operation banner keeps precedence');
});

test('an empty, malformed-only record reads a plain sentence — no device list, no trailing colon',()=>{
 const h=bannerHarness();
 const lab={id:'lab',name:'demo',nodes:[],deployment:{status:'Running'},telemetry_retired:{nodes:[],total:0,malformed:true}};
 setLab(h.context,lab);
 h.context.renderLabBanner();
 const banner=h.$('lab-banner'),text=h.$('lab-banner-text');
 assert.equal(banner.hidden,false);
 assert.equal(text.textContent,'A telemetry record of this lab could not be read and is kept for review.');
 assert.doesNotMatch(text.textContent,/still on:/,'no device list and no trailing colon when there is nothing to name');
});

test('closing the retired-telemetry notice hides it for that exact set of devices; a different set reopens it',()=>{
 const h=bannerHarness();
 const lab={id:'lab',name:'demo',nodes:[],deployment:{status:'Running'},telemetry_retired:{nodes:[{name:'clab-demo-cjunosevolved',short_name:'cjunosevolved'}],total:1,malformed:false}};
 setLab(h.context,lab);
 h.context.renderLabBanner();
 const banner=h.$('lab-banner'),close=h.$('lab-banner-close');
 assert.equal(banner.hidden,false);
 close.onclick();
 setLab(h.context,lab);
 h.context.renderLabBanner();
 assert.equal(banner.hidden,true,'dismissed for the session, for this exact device list');
 lab.telemetry_retired={nodes:[{name:'clab-demo-cjunosevolved',short_name:'cjunosevolved'},{name:'clab-demo-ceos',short_name:'ceos'}],total:2,malformed:false};
 setLab(h.context,lab);
 h.context.renderLabBanner();
 assert.equal(banner.hidden,false,'a materially different device list is a different notice, shown again');
});

// operations.js alone (opDialog/opTask/json/api), the harness pattern of test_operations_ui.js.
function opRetiredHarness(data,removeResult,platforms={}){
 const elements=new Map();
 const makeEl=id=>({id,innerHTML:'',open:false,onclick:null,querySelector(){return {textContent:''};},querySelectorAll(){return [];},showModal(){this.open=true;},close(){this.open=false;}});
 // import-top absent skips operations.js's load-time menu wiring (the fake elements below have no
 // addEventListener), the same trick tests/test_operations_ui.js uses for a standalone load.
 const $=id=>{if(id==='import-top')return null;if(!elements.has(id))elements.set(id,makeEl(id));return elements.get(id);};
 const calls=[];
 const context=vm.createContext({$,esc,activeId:'lab',state:{labs:[{id:'lab',name:'demo'}],platforms},console,JSON,
  document:{createElement(){return makeEl('created');},body:{append(){}},querySelectorAll(){return [];}},
  api:async url=>{calls.push(url);return {json:async()=>data};},
  json:async(url,method,payload)=>{calls.push([url,method,payload]);return removeResult;},
  notify(message){calls.push(['notify',message]);},refresh:async()=>{calls.push('refresh');}});
 vm.runInContext(fs.readFileSync(path.join(STATIC,'operations.js'),'utf8'),context);
 return {context,$,calls};
}

test('the retired-telemetry dialog reads the record, escapes every device field, shows the reason a device cannot be cleaned up, and offers Forget only for a permanent reason',async()=>{
 const data={lab_id:'lab',lab_name:'demo',malformed:false,nodes:[
  {name:'clab-demo-cjunosevolved',short_name:'cjunosevolved',kind:'juniper_junos_evolved',lines:['set system services extension-service request-response grpc clear-text port 32767'],at:'2026-09-01T00:00:00Z',removable:true,reason:''},
  {name:'clab-demo-r2',short_name:'<r2>',kind:'unmapped-kind',lines:['line one'],at:'',removable:false,permanent:true,reason:'The device did not answer, so its configuration could not be read.'},
 ]};
 const h=opRetiredHarness(data,{results:[],remaining:2},{juniper_junos_evolved:{label:'Juniper cJunosEvolved'}});
 const dialog=await h.context.openTelemetryRetired('lab');
 assert.equal(h.calls[0],'/labs/lab/telemetry-retired');
 assert.equal(dialog.id,'telemetry-retired-dialog');
 assert.match(dialog.innerHTML,/Removing deletes only these lines on the running device, inside the device's own configuration session, and reads the device back\. Nothing else changes\./);
 assert.match(dialog.innerHTML,/<h4>cjunosevolved <span class="badge platform">Juniper cJunosEvolved<\/span><\/h4>/,'a kind in the existing vocabulary is labelled from it');
 assert.match(dialog.innerHTML,/<pre class="op-output">set system services extension-service request-response grpc clear-text port 32767<\/pre>/);
 assert.match(dialog.innerHTML,/<span class="badge platform">unmapped-kind<\/span>/,'a kind outside the vocabulary falls back to its raw name');
 assert.match(dialog.innerHTML,/&lt;r2&gt;/,'an untrusted short name is escaped');assert.doesNotMatch(dialog.innerHTML,/<r2>/);
 assert.match(dialog.innerHTML,/<p class="op-notice">The device did not answer, so its configuration could not be read\. <button type="button" class="button secondary small" id="op-retired-forget-1">Forget<\/button><\/p>/,'the reason is shown only for the node that is not removable, and a permanent one also gets a Forget button');
 assert.doesNotMatch(dialog.innerHTML,/id="op-retired-remove" disabled/,'at least one device is removable, so the button stays enabled');
});

test('an empty, malformed-only record shows one sentence and a button to forget it — no device list, no Remove action',async()=>{
 const h=opRetiredHarness({nodes:[],malformed:true},{});
 const dialog=await h.context.openTelemetryRetired('lab');
 assert.doesNotMatch(dialog.innerHTML,/No devices to show/);
 assert.match(dialog.innerHTML,/<p class="form-help">A telemetry record of this lab could not be read and is kept for review\.<\/p>/);
 assert.doesNotMatch(dialog.innerHTML,/still on:/,'no device list and no trailing colon when there is nothing to name');
 assert.doesNotMatch(dialog.innerHTML,/id="op-retired-remove"/,'nothing to remove when no device is recorded');
 assert.match(dialog.innerHTML,/id="op-retired-forget-malformed">Forget the unreadable record</);
});

test('devices and a malformed record together keep the combined sentence and add the same forget button for the malformed part',async()=>{
 const data={malformed:true,nodes:[{name:'clab-demo-r1',short_name:'r1',kind:'arista_ceos',lines:['line'],removable:true,reason:''}]};
 const h=opRetiredHarness(data,{});
 const dialog=await h.context.openTelemetryRetired('lab');
 assert.match(dialog.innerHTML,/<p class="op-notice">A telemetry record of this lab could not be read and is kept for review\. <button type="button" class="button secondary" id="op-retired-forget-malformed">Forget the unreadable record<\/button><\/p>/);
 assert.match(dialog.innerHTML,/id="op-retired-remove"/,'the device list keeps its own Remove action too');
});

test('forgetting an unreadable record posts {malformed:true}, reports the outcome and refreshes',async()=>{
 const h=opRetiredHarness({nodes:[],malformed:true},{forgotten:'malformed',remaining:[]});
 await h.context.openTelemetryRetired('lab');
 await h.$('op-retired-forget-malformed').onclick();
 assert.equal(JSON.stringify(h.calls[1]),JSON.stringify(['/labs/lab/telemetry-retired/forget','POST',{malformed:true}]));
 assert.match(h.$('op-retired-results').innerHTML,/The unreadable record was forgotten\./);
 assert.deepEqual(h.calls.filter(c=>Array.isArray(c)&&c[0]==='notify'),[['notify','Forgot the unreadable record.']]);
 assert.equal(h.calls.at(-1),'refresh');
});

test('forgetting one permanently un-removable device posts {node:name}, reports it and refreshes; a transient reason gets no Forget button',async()=>{
 const data={malformed:false,nodes:[
  {name:'clab-demo-cjunosevolved',short_name:'cjunosevolved',kind:'juniper_junos_evolved',lines:['line'],removable:false,permanent:true,reason:'This device is no longer part of the lab.'},
  {name:'clab-demo-r2',short_name:'r2',kind:'arista_ceos',lines:['line'],removable:false,permanent:false,reason:'The device is not running.'},
 ]};
 const h=opRetiredHarness(data,{forgotten:'clab-demo-cjunosevolved',remaining:['clab-demo-r2']});
 const dialog=await h.context.openTelemetryRetired('lab');
 assert.match(dialog.innerHTML,/id="op-retired-forget-0">Forget</,'a permanent reason gets a Forget button');
 assert.doesNotMatch(dialog.innerHTML,/id="op-retired-forget-1"/,'a transient reason gets none — its own text already says what to do');
 await h.$('op-retired-forget-0').onclick();
 assert.equal(JSON.stringify(h.calls[1]),JSON.stringify(['/labs/lab/telemetry-retired/forget','POST',{node:'clab-demo-cjunosevolved'}]));
 assert.match(h.$('op-retired-results').innerHTML,/cjunosevolved: forgotten\./);
 assert.deepEqual(h.calls.filter(c=>Array.isArray(c)&&c[0]==='notify'),[['notify','Forgot the record for cjunosevolved.']]);
 assert.equal(h.calls.at(-1),'refresh');
});

test('Remove from devices is disabled when no device can be cleaned up, and a transient reason gets no Forget button',async()=>{
 const data={nodes:[{name:'clab-demo-r1',short_name:'r1',kind:'arista_ceos',lines:['line'],removable:false,reason:'Turn telemetry back on first, or wait for the device to answer.'}],malformed:false};
 const h=opRetiredHarness(data,{results:[],remaining:1});
 const dialog=await h.context.openTelemetryRetired('lab');
 assert.match(dialog.innerHTML,/id="op-retired-remove" disabled>Remove from devices</);
 assert.doesNotMatch(dialog.innerHTML,/>Forget</);
});

test('the remove flow posts an empty body, reports each device by its short name, notifies a one-line summary and refreshes',async()=>{
 const data={nodes:[
  {name:'clab-demo-cjunosevolved',short_name:'cjunosevolved',kind:'juniper_junos_evolved',lines:['line'],removable:true,reason:''},
  {name:'clab-demo-r2',short_name:'<r2>',kind:'arista_ceos',lines:['line'],removable:false,reason:'Not reachable.'},
 ],malformed:false};
 const removeResult={results:[{name:'clab-demo-cjunosevolved',outcome:'removed',message:'Line removed and the device read back.'},{name:'clab-demo-r2',outcome:'failed',message:'The device did not answer.'}],remaining:1};
 const h=opRetiredHarness(data,removeResult);
 await h.context.openTelemetryRetired('lab');
 await h.$('op-retired-remove').onclick();
 assert.equal(JSON.stringify(h.calls[1]),JSON.stringify(['/labs/lab/telemetry-retired/remove','POST',{}]));
 const results=h.$('op-retired-results').innerHTML;
 assert.match(results,/cjunosevolved: removed — Line removed and the device read back\./);
 assert.match(results,/&lt;r2&gt;: failed — The device did not answer\./,'the results list uses the short name too, and is escaped');
 assert.deepEqual(h.calls.filter(c=>Array.isArray(c)&&c[0]==='notify'),[['notify','Removed telemetry configuration on 1 of 2 devices.']]);
 assert.equal(h.calls.at(-1),'refresh','refreshing lets the banner disappear once remaining reaches 0 on a later read');
});

test('nothing to remove reports plainly and still refreshes',async()=>{
 const data={nodes:[{name:'clab-demo-r1',short_name:'r1',kind:'arista_ceos',lines:['line'],removable:true,reason:''}],malformed:false};
 const h=opRetiredHarness(data,{results:[],remaining:0});
 await h.context.openTelemetryRetired('lab');
 await h.$('op-retired-remove').onclick();
 assert.deepEqual(h.calls.filter(c=>Array.isArray(c)&&c[0]==='notify'),[['notify','Nothing to remove on the running devices.']]);
 assert.equal(h.$('op-retired-results').innerHTML,'');
});

test('no static script or the shell page still calls a telemetry API route, mentions Grafana, or names the removed telemetry-settings dialog',()=>{
 const jsFiles=fs.readdirSync(STATIC).filter(name=>name.endsWith('.js'));
 assert.ok(jsFiles.includes('operations.js')&&jsFiles.includes('app.js'),'sanity: the directory listing is the real one');
 for(const name of [...jsFiles,'index.html','style.css']){
  const text=fs.readFileSync(path.join(STATIC,name),'utf8');
  assert.doesNotMatch(text,/\/telemetry\//,name+' still calls a telemetry API route');
  assert.doesNotMatch(text,/grafana/i,name+' still mentions Grafana');
  assert.doesNotMatch(text,/telemetry-settings/,name+' still names the removed telemetry settings dialog');
 }
 assert.equal(fs.existsSync(path.join(STATIC,'grafana.html')),false,'grafana.html is deleted, not just unreferenced');
 assert.equal(fs.existsSync(path.join(STATIC,'grafana.js')),false,'grafana.js is deleted, not just unreferenced');
});
