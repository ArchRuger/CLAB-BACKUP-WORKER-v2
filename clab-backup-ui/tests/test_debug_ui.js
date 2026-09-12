const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/debug.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(fetch){
 const elements=new Map(),downloads=[];let blob;
 const element=tag=>({tag,children:[],checked:false,disabled:false,value:'',textContent:'',
  append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},remove(){},click(){downloads.push(this.download);}});
 const get=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
 const context=vm.createContext({document:{getElementById:get,createElement:element,body:element('body')},fetch,Blob,
  URL:{createObjectURL:value=>{blob=value;return 'blob:fixture';},revokeObjectURL:()=>{}},setTimeout:fn=>fn()});
 vm.runInContext(source,context);
 return {context,get,downloads,blob:()=>blob};
}
const snapshot={generated_at:'2026-09-11T12:00:00+00:00',manager_version:'1.19.0',python_version:'3.12',packages:{},uptime_seconds:10,vm:{configured:false},saved_counts:{labs:0},requests:[
 {time:'UTC',id:'one',method:'POST',route:'/api/operations/browse',status:409,duration_ms:15},
 {time:'UTC',id:'two',method:'GET',route:'/api/operations/capabilities',status:200,duration_ms:20}]};

test('debug report renders metadata as text and failures filter works',async()=>{
 const f=fixture(async()=>({ok:true,json:async()=>({...snapshot,manager_version:'<script>untrusted</script>'})}));await tick();
 assert.equal(f.get('debug-summary').children[0].children[1].children[1].textContent,'<script>untrusted</script>');
 assert.equal(f.get('debug-requests').children.length,2);
 f.get('debug-errors').checked=true;f.get('debug-errors').onchange();
 assert.equal(f.get('debug-requests').children.length,1);
 assert.equal(f.get('debug-download').disabled,false);
});

test('read-only check disables running button, exports results and omits input path',async()=>{
 let resolveProbe,request;
 const f=fixture(async(url,options)=>{
  if(url.endsWith('/probe')){request=JSON.parse(options.body);return new Promise(resolve=>{resolveProbe=resolve;});}
  return {ok:true,json:async()=>snapshot};
 });await tick();
 f.get('debug-path').value='/private/fixture-path';
 const running=f.get('debug-probe-form').onsubmit({preventDefault(){}});
 assert.equal(f.get('debug-probe').disabled,true);assert.equal(request.path,'/private/fixture-path');
 resolveProbe({ok:true,json:async()=>({generated_at:snapshot.generated_at,checks:[{check:'browse',status:'pass',entry_count:1,duration_ms:10},{check:'capabilities',status:'fail',message:'Check VM setup.',duration_ms:20}]})});
 await running;assert.equal(f.get('debug-probe').disabled,false);
 assert.match(f.get('debug-checks').children[1].textContent,/FAIL/);
 f.get('debug-download').onclick();
 const report=JSON.parse(await f.blob().text());assert.equal(report.probe.checks.length,2);
 assert.doesNotMatch(JSON.stringify(report),/fixture-path/);assert.match(f.downloads[0],/^clab-debug-.*\.json$/);
});

test('failed probe clears prior result and leaves retry available',async()=>{
 let fail=false;
 const f=fixture(async(url)=>url.endsWith('/probe')?
  fail?{ok:false,status:409}:{ok:true,json:async()=>({checks:[],generated_at:'UTC'})}:
  {ok:true,json:async()=>snapshot});await tick();
 await f.context.debugRun({preventDefault(){}});fail=true;await f.context.debugRun({preventDefault(){}});
 assert.equal(f.get('debug-probe').disabled,false);assert.match(f.get('debug-checks').children[0].textContent,/HTTP 409/);
 f.context.debugDownload();assert.equal(JSON.parse(await f.blob().text()).probe,null);
});

test('debug flags audit write failures without displaying exception details',async()=>{
 const f=fixture(async()=>({ok:true,json:async()=>({...snapshot,audit_log_available:false})}));await tick();
 assert.equal(f.get('debug-summary').children[0].children[1].children[7].textContent,'Failed — check storage');
});
