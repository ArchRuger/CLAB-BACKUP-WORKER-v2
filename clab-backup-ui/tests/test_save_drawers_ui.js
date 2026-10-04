// save-drawers.js: the one drawer (What changed, All versions, Save settings, the host of the folder chooser and of
// Save as a lab state, the differences of a load). The production script runs in a vm context with a fake `$`, fake
// requests and fakes for the functions of the other slices (gitReviewJob, loadChoose, folderChooserMarkup, ...), which
// the drawer reads at call time behind typeof guards. Events are driven through the drawer's own delegated handlers
// with small fake targets whose closest() understands the selectors the drawer uses.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/save-drawers.js'),'utf8');
const diffSource=fs.readFileSync(path.join(__dirname,'../app/static/diff-view.js'),'utf8');
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
const kebab=key=>key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase());
// A node of the fake DOM: tag, id, classes, data attributes, parent; closest() understands `#id`, `.class`, `tag`, `[data-x]` and their combinations.
function node(tag,{id='',cls='',data={},parent=null,disabled=false,value='',checked=false,name='',open=false}={}){
 const n={tagName:tag.toUpperCase(),tag,id,className:cls,dataset:{...data},parentElement:parent,disabled,value,checked,name,open,
  hasAttribute(a){return a==='open'?!!this.open:Object.keys(this.dataset).some(k=>'data-'+kebab(k)===a);},
  closest(selector){for(let c=this;c;c=c.parentElement)if(selector.split(',').some(part=>match(c,part.trim())))return c;return null;}};
 return n;
}
function match(n,part){
 const m=part.match(/^([a-z]+)?(#[\w-]+)?((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/);if(!m)return false;
 if(m[1]&&n.tag!==m[1])return false;if(m[2]&&n.id!==m[2].slice(1))return false;
 for(const cls of (m[3]||'').split('.').filter(Boolean))if(!String(n.className).split(/\s+/).includes(cls))return false;
 for(const attr of (m[4]||'').match(/\[[^\]]+\]/g)||[]){const [,name]=attr.match(/^\[([\w-]+)/);if(name==='data-fold'||name.startsWith('data-')){const key=name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase());if(!(key in n.dataset))return false;}}
 return true;
}
function harness({labs,jobs=[],routes={},extras={}}={}){
 const elements=new Map(),requests=[],calls=[],timers=[],notices=[];
 const element=id=>({id,innerHTML:'',textContent:'',hidden:false,open:false,scrollTop:0,dataset:{},listeners:{},tabIndex:0,
  addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn);},
  showModal(){this.open=true;},close(){if(!this.open)return;this.open=false;for(const fn of this.listeners.close||[])fn({});},
  contains(other){return other===this.__focusable;},querySelector(selector){return this.__found&&this.__found[selector]||null;},focus(){document.activeElement=this;}});
 const $=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
 const document={activeElement:null,createElement:()=>({click(){calls.push(['download-click']);},remove(){}}),body:{append(){}}};
 const lab={id:'lab',name:'restore-square',nodes:[],git_binding:{binding_id:'b'},git_status:{checked:true,ready:true,problem:'',waiting:0}};
 const context=vm.createContext({$,esc:escapeHtml,document,state:{labs:labs||[lab],git_jobs:jobs,jobs:[]},activeId:'lab',
  setTimeout:(fn)=>{timers.push(fn);return timers.length;},clearTimeout:id=>{if(id)timers[id-1]=null;},URL:{createObjectURL:()=>'blob:x',revokeObjectURL(){}},
  notify:message=>notices.push(message),refresh:async()=>{calls.push(['refresh']);},
  gitWhen:value=>value?'when '+value:'',gitRepoName:repo=>String(repo?.path||'').split('/').filter(Boolean).pop()||'repo',
  api:async(url,options={})=>{requests.push({url,options,method:options.method||'GET'});const handler=routes[(options.method||'GET')+' '+url.split('?')[0]]||routes[url];if(handler===undefined)throw Object.assign(new Error('no route '+url),{status:404});const value=typeof handler==='function'?await handler(url,options):handler;return {ok:true,json:async()=>value,blob:async()=>({}),headers:{get:()=>''}};},
  json:async(url,method,data)=>{requests.push({url,method,data});const handler=routes[method+' '+url];if(handler===undefined)throw Object.assign(new Error('no route '+method+' '+url),{status:404});return typeof handler==='function'?handler(data,url):handler;},
  ...extras});
 vm.runInContext(diffSource,context);vm.runInContext(source,context);const sd=vm.runInContext('saveDrawer',context);
 const dialog=$('save-drawer');dialog.__root=node('dialog',{id:'save-drawer'});
 const fire=(type,event)=>{for(const fn of dialog.listeners[type]||[])fn(event);};
 return {context,sd,$,dialog,requests,calls,timers,notices,lab,fire,
  async click(target){const event={type:'click',target,prevented:false,preventDefault(){this.prevented=true;}};fire('click',event);await settle();return event;},
  content:()=>$('save-drawer-content').innerHTML,actions:()=>$('save-drawer-actions').innerHTML,title:()=>$('save-drawer-title').textContent,meta:()=>$('save-drawer-meta').textContent,status:()=>$('save-drawer-status').textContent,
  button:(action,data={})=>node('button',{cls:'button',data:{saveAction:action,...data},parent:dialog.__root}),
  run:code=>vm.runInContext(code,context)};
}
function target(tag,options){const root=node('dialog',{id:'save-drawer'});return node(tag,{...options,parent:root});}
const netErr=(g,message)=>vm.runInContext('new TypeError('+JSON.stringify(message)+')',g.context);
const diff=(added=1,removed=0)=>({identical:false,added,removed,truncated:false,hunks:[{old_start:1,old_count:1,new_start:1,new_count:1,lines:[{type:'del',old:1,new:null,text:'old line'},{type:'add',old:null,new:1,text:'new line'}]}]});
const labJob=(over={})=>({id:'j1',lab_id:'lab',kind:'capture',target:'latest',status:'review_pending',pushed:false,commit:'a'.repeat(40),snapshot_path:'restore-square/latest',note:'ceos and xrv9k changed',
 changed_files:['restore-square/latest/ceos.cfg','restore-square/latest/ceos.eoscfg','restore-square/latest/xrv9k.cfg','restore-square/latest/topology.clab.yml','restore-square/latest/topology.clab.yml.annotations.json','restore-square/latest/manifest.json'],
 destination:{repository:'Course-Labs',branch:'main',path:'restore-square',remote:'https://github.com/me/Course-Labs.git'},backup_job_id:'cap1',capture_kept:true,capture_whole:true,created:'2026-10-01T10:00:00Z',...over});
const reviewFor=(job,over={})=>({files:[
 {name:'ceos.cfg',status:'changed',diff:diff(),role:'device',node:'ceos'},{name:'ceos.eoscfg',status:'changed',diff:diff(),role:'restore',node:'ceos'},
 {name:'xrv9k.cfg',status:'changed',diff:diff(),role:'device',node:'xrv9k'},{name:'topology.clab.yml',status:'changed',diff:diff(),role:'topology'},
 {name:'topology.clab.yml.annotations.json',status:'changed',diff:diff(),role:'map'},{name:'manifest.json',status:'changed',diff:diff(),role:'manifest'}].map(f=>({...f,path:'restore-square/latest/'+f.name})),
 summary:{devices:['ceos','xrv9k'],added:19,removed:1},head:'a'.repeat(40),upload_job:job.id,also_sends:[],...over});
const union=account=>[...new Set([...account.entries.flatMap(e=>e.paths),...account.rest])].sort();
const sameSet=(a,b)=>assert.deepEqual([...a].sort(),[...b].sort());

test('D1 every path of changed_files is accounted for: entries by role, a restore row is a line under its device, a gap is shown as rest',()=>{
 const h=harness(),job=labJob(),review=reviewFor(job),account=h.context.saveChangeAccount(job,review);
 sameSet(union(account),job.changed_files);assert.equal(account.rest.length,0);
 assert.deepEqual(Array.from(account.entries,e=>e.role),['device','device','topology','map','manifest']);
 const ceos=account.entries[0];assert.equal(ceos.title,'ceos');assert.equal(ceos.restore.name,'ceos.eoscfg');assert.equal(ceos.paths.length,2,'the human file and the restore file are one entry');
 // the restore file of a device whose human file did not change opens the device's entry itself and counts once
 const only=h.context.saveChangeAccount({...job,changed_files:['restore-square/latest/ceos.eoscfg']},{files:[{name:'ceos.eoscfg',status:'changed',diff:diff(),role:'restore',node:'ceos',path:'restore-square/latest/ceos.eoscfg'}]});
 assert.equal(only.entries.length,1);assert.equal(only.entries[0].sameText,true);assert.equal(only.entries[0].role,'device');
 // a row with no known role is listed as `other`; a path no row covers appears under rest
 const odd=h.context.saveChangeAccount({...job,changed_files:['restore-square/latest/notes.txt','restore-square/latest/lost.cfg']},{files:[{name:'notes.txt',status:'added',diff:diff(),path:'restore-square/latest/notes.txt'}]});
 assert.equal(odd.entries[0].role,'other');assert.deepEqual(Array.from(odd.rest),['restore-square/latest/lost.cfg']);
});
test('D1 the invariant holds for a checkpoint save, a starting point, a lab state, a rename, a removed device, a folder move and a map-only change',()=>{
 const h=harness(),f=(folder,name,role,node,status='changed')=>({name,path:folder+'/'+name,status,diff:diff(),role,node});
 const cases={
  checkpoint:{job:{snapshot_path:'lab/checkpoints/ospf',changed_files:['lab/latest/ceos.cfg','lab/latest/manifest.json','lab/checkpoints/ospf/ceos.cfg','lab/checkpoints/ospf/manifest.json']},files:[f('lab/checkpoints/ospf','ceos.cfg','device','ceos'),f('lab/checkpoints/ospf','manifest.json','manifest'),f('lab/latest','ceos.cfg','device','ceos'),f('lab/latest','manifest.json','manifest')]},
  baseline:{job:{snapshot_path:'lab/baseline',changed_files:['lab/baseline/ceos.cfg','lab/baseline/manifest.json']},files:[f('lab/baseline','ceos.cfg','device','ceos'),f('lab/baseline','manifest.json','manifest')]},
  state:{job:{snapshot_path:'BGP/start',changed_files:['BGP/start/ceos.cfg','BGP/start/manifest.json']},files:[f('BGP/start','ceos.cfg','device','ceos','added'),f('BGP/start','manifest.json','manifest','','added')]},
  rename:{job:{snapshot_path:'lab/latest',changed_files:['lab/latest/xr.set','lab/latest/xr.cfg']},files:[{...f('lab/latest','xr.cfg','device','xr'),renamed_from:'xr.set'}]},
  removed:{job:{snapshot_path:'lab/latest',changed_files:['lab/latest/old.cfg','lab/latest/manifest.json']},files:[f('lab/latest','old.cfg','device','old','removed'),f('lab/latest','manifest.json','manifest')]},
  move:{job:{target:'move',snapshot_path:'new/latest',changed_files:['old/latest/ceos.cfg','new/latest/ceos.cfg']},files:[f('new/latest','ceos.cfg','other')]},
  mapOnly:{job:{snapshot_path:'lab/latest',changed_files:['lab/latest/t.annotations.json','lab/latest/manifest.json']},files:[f('lab/latest','t.annotations.json','map'),f('lab/latest','manifest.json','manifest')]},
 };
 for(const [name,{job,files}] of Object.entries(cases)){
  const account=h.context.saveChangeAccount({id:'x',...job},{files});
  sameSet(union(account),job.changed_files);
  if(name==='checkpoint'){assert.equal(account.entries.filter(e=>e.title.includes('/')).length,2,'the copies in the other folder are rows titled by their path');}
  if(name==='move')assert.deepEqual(Array.from(account.rest),['old/latest/ceos.cfg'],'a path no row names stays visible');
  if(name==='removed')assert.equal(account.entries.find(e=>e.title==='old').status,'removed');
 }
});
test('D2 What changed: entries, wording, head buttons, the frozen destination, the passwords sentence, escaping',async()=>{
 const attack='<img src=x onerror=alert(1)>',job=labJob({note:attack,destination:{repository:'Old-Repo',branch:'main',path:'frozen/folder'}});
 const review=reviewFor(job,{files:reviewFor(job).files.map(f=>f.name==='ceos.cfg'?{...f,diff:{...diff(),hunks:[{old_start:1,old_count:1,new_start:1,new_count:1,lines:[{type:'add',old:null,new:1,text:'</pre><script>bad()</script>'}]}]}}:f)});
 const h=harness({jobs:[job],extras:{gitReviewData:async()=>review,saveChangeSentence:()=>'ceos and xrv9k changed. 19 lines added, 1 removed.'}});
 h.context.saveDrawerOpen('changes',{job});await settle();
 const html=h.content();
 assert.equal(h.title(),'What changed');assert.match(h.meta(),/19 lines added, 1 removed\. Not uploaded yet\.$/);
 assert.match(h.actions(),/data-save-action="upload"[^>]*>Upload</);assert.match(h.actions(),/data-save-action="not-now"/);assert.match(h.actions(),/data-save-action="files"/);
 assert.match(html,/To: <code>Old-Repo<\/code> <span aria-hidden="true">›<\/span> <code>frozen\/folder<\/code>/,'the saves own destination');
 assert.match(html,/Saved files can contain passwords or keys\./);assert.match(html,/Topology file/);assert.match(html,/Map <small>/);assert.match(html,/Save details/);
 assert.match(html,/Also uploaded for ceos|Also uploaded for &lt;img/);assert.match(html,/the file Load uses/);
 assert.doesNotMatch(html,/<img|<script>/);assert.match(html,/&lt;\/pre&gt;&lt;script&gt;bad\(\)&lt;\/script&gt;/);
 assert.equal(h.sd.kind,'changes');
});
test('D2 a design export has its own title and an uploaded save shows no action row and no other saves',async()=>{
 const design=labJob({kind:'design',target:'checkpoint',status:'synced',pushed:true});
 const h=harness({extras:{gitReviewData:async()=>reviewFor(design,{also_sends:[{job_id:'z',lab:'x',name:'z'}]})}});
 h.context.saveDrawerOpen('changes',{job:design});await settle();
 assert.equal(h.title(),'What this design export changed');assert.doesNotMatch(h.actions(),/data-save-action="upload"/);assert.match(h.meta(),/Uploaded to github\.com\.$/);
 assert.doesNotMatch(h.content(),/Also in this upload/);
});
test('D3 Also in this upload: one folded group per other save, opened with the review of its own job; a save the manager no longer keeps lists its paths',async()=>{
 const job=labJob(),other={id:'j2',lab_id:'x',created:'2026-10-01T08:00:00Z',changed_files:['OSPF/latest/r1.cfg']};
 const reviews={j1:reviewFor(job,{also_sends:[{job_id:'j2',lab:'OSPF-lab',name:'Topology changed',kind:'capture',target:'latest'},{commit:'9c1e2aa',name:'Save progress: week 3',files:['OSPF/latest/ceos.cfg','OSPF/latest/manifest.json']}]}),
  j2:{files:[{name:'r1.cfg',path:'OSPF/latest/r1.cfg',status:'changed',diff:diff(),role:'device',node:'r1'}],summary:null,head:'',upload_job:'j1',also_sends:[]}};
 const asked=[];const h=harness({jobs:[job,other],extras:{gitReviewData:async j=>{asked.push(j.id);return reviews[j.id];},saveChangeSentence:()=>'ok.'}});
 h.context.saveDrawerOpen('changes',{job});await settle();
 assert.match(h.content(),/This upload also sends 2 other saves: Topology changed \(OSPF-lab\), Save progress: week 3\./);
 assert.match(h.content(),/Also in this upload/);assert.equal((h.content().match(/data-save-also=/g)||[]).length,2);assert.doesNotMatch(h.content(),/data-save-also="job-j2"[^>]* open/);
 assert.deepEqual(asked,['j1'],'nothing is asked for a group until it is opened');
 const summary=node('summary',{parent:node('details',{data:{fold:'also:job-j2',saveAlso:'job-j2'},parent:node('dialog',{id:'save-drawer'})})});
 await h.click(summary);
 assert.deepEqual(asked,['j1','j2']);assert.match(h.content(),/r1\.cfg/);assert.match(h.content(),/data-save-also="job-j2" open/);
 const kept=node('summary',{parent:node('details',{data:{fold:'also:commit-9c1e2aa',saveAlso:'commit-9c1e2aa'},parent:node('dialog',{id:'save-drawer'})})});
 await h.click(kept);assert.deepEqual(asked,['j1','j2'],'a commit the manager does not hold asks nothing');
 assert.match(h.content(),/OSPF\/latest\/ceos\.cfg/);assert.match(h.content(),/a save the manager no longer keeps/);
});
test('D4 Upload calls gitReviewJob(job,{upload:true}) and nothing else; a 409 re-reads the review and keeps Upload enabled; no save at HEAD means no Upload',async()=>{
 const job=labJob(),sent=[];let review=reviewFor(job),fail=null;
 const h=harness({jobs:[job],extras:{gitReviewData:async()=>review,gitReviewJob:async(j,o)=>{sent.push([j.id,o]);if(fail){const e=new Error('Another save was made in this repository. Look at the changes again.');e.status=409;review=reviewFor(job,{also_sends:[{job_id:'n',lab:'o',name:'New save'}]});throw e;}return {id:'j1'};}}});
 h.context.saveDrawerOpen('changes',{job});await settle();
 fail=true;await h.click(h.button('upload'));
 assert.equal(sent.length,1);assert.equal(sent[0][1].upload,true);assert.equal(h.sd.kind,'changes','a refused upload leaves the drawer open');
 assert.match(h.content(),/Another save was made in this repository\. Look at the changes again\./);assert.match(h.content(),/New save/);assert.doesNotMatch(h.actions(),/disabled/);
 fail=false;await h.click(h.button('upload'));assert.equal(sent.length,2);assert.equal(h.dialog.open,false,'success closes the drawer');
 // somebody committed by hand: no save of the manager is at HEAD
 review=reviewFor(job,{upload_job:''});const g=harness({jobs:[job],extras:{gitReviewData:async()=>review,gitReviewJob:async()=>{throw new Error('must not upload');}}});
 g.context.saveDrawerOpen('changes',{job});await settle();
 assert.doesNotMatch(g.actions(),/data-save-action="upload"/);assert.match(g.actions(),/Someone is working in this repository on the VM\./);assert.match(g.actions(),/Details/);
});
test('D4 the drawer never sends an upload itself: no reviewed flag, no review cache, no job compare, no second sender',()=>{
 assert.doesNotMatch(source,/reviewed/);assert.doesNotMatch(source,/function gitReviewData|gitReviews/);assert.doesNotMatch(source,/[{,]\s*job_id\s*:/,'no request carries a job id to the compare route');
 assert.doesNotMatch(source,/push\s*:\s*true\s*,\s*reviewed/);
 const h=harness();assert.equal(h.context.gitReviewData,undefined);assert.equal(h.context.gitReviewJob,undefined);
});
test('D4 Upload stays disabled with its reason as visible text until the review has arrived',async()=>{
 const job=labJob();let release;const gate=new Promise(r=>{release=r;});
 const h=harness({jobs:[job],extras:{gitReviewData:async()=>{await gate;return reviewFor(job);}}});
 h.context.saveDrawerOpen('changes',{job});
 assert.match(h.actions(),/data-save-action="upload"[^>]*disabled/);assert.match(h.content(),/Reading what changed…/);
 release();await settle();assert.doesNotMatch(h.actions(),/data-save-action="upload"[^>]*disabled/);
});
test('D5 Not now sends saveAction("not-now", job, "drawer"), closes the drawer and shows no toast',async()=>{
 const job=labJob(),seen=[];
 const h=harness({jobs:[job],extras:{gitReviewData:async()=>reviewFor(job),saveAction:async(...args)=>{seen.push(args);}}});
 h.context.saveDrawerOpen('changes',{job});await settle();
 await h.click(h.button('not-now'));
 assert.equal(seen.length,1);assert.equal(seen[0][0],'not-now');assert.equal(seen[0][1].id,'j1');assert.equal(seen[0][2],'drawer');
 assert.equal(h.dialog.open,false);assert.equal(h.notices.length,0);
});
const states=(over={})=>({head:'f'.repeat(40),truncated:false,lab_devices:4,states:[
 {path:'restore-square/latest',commit:'f'.repeat(40),name:'Restore-square',group:'latest',lab:'restore-square',kind:'capture',layout:'latest',saved_at:'2026-10-01T10:00:00Z',saved_devices:4,loadable_devices:4,view_only:false,view_only_reason:''},
 {path:'restore-square/checkpoints/ospf-done',commit:'f'.repeat(40),name:'Ospf-done',group:'checkpoint',lab:'',kind:'capture',layout:'flat',saved_at:'2026-10-01T09:00:00Z',saved_devices:4,loadable_devices:4,view_only:false,view_only_reason:''},
 {path:'restore-square/checkpoints/design',commit:'f'.repeat(40),name:'Design',group:'checkpoint',lab:'',kind:'design',layout:'flat',saved_at:'2026-10-01T09:30:00Z',saved_devices:0,loadable_devices:0,view_only:true,view_only_reason:'design'},
 {path:'restore-square/baseline',commit:'f'.repeat(40),name:'Baseline',group:'baseline',lab:'',kind:'capture',layout:'flat',saved_at:'2026-09-30T09:00:00Z',saved_devices:4,loadable_devices:4,view_only:false,view_only_reason:''},
 {path:'BGP/start',commit:'f'.repeat(40),name:'Start',group:'state',lab:'',kind:'capture',layout:'flat',saved_at:'2026-09-01T09:00:00Z',saved_devices:2,loadable_devices:2,view_only:false,view_only_reason:''},
 {path:'BGP/old',commit:'f'.repeat(40),name:'Old',group:'state',lab:'',kind:'capture',layout:'flat',saved_at:'2026-09-01T08:00:00Z',saved_devices:2,loadable_devices:0,view_only:true,view_only_reason:'no_restore_data'},
 {path:'OSPF-lab/latest',commit:'f'.repeat(40),name:'Ospf-lab',group:'other-lab',lab:'OSPF-lab',kind:'capture',layout:'latest',saved_at:'2026-09-02T09:00:00Z',saved_devices:3,loadable_devices:3,view_only:false,view_only_reason:''}],...over});
const binding={binding_id:'b',node_names:['ceos','xrv9k'],repository:{path:'/home/me/Course-Labs',prefix:'restore-square/',branch:'main',owner:'student',push_url:'https://github.com/me/Course-Labs.git'}};
function versionsHarness({jobs=[],list=states(),context={},extras={},routes={}}={}){
 const loaded={binding,repository_status:{baseline_revision:'rev1'},supported_nodes:[{name:'ceos'},{name:'xrv9k'}],...context};
 return harness({jobs,routes:{'GET /labs/lab/restore/states':list,...routes},extras:{gitLoadContext:async()=>loaded,loadChoose:async(...a)=>{h.loads.push(a);},gitShowJob:async id=>{h.shown.push(id);},gitReviewJob:async(j,o)=>{h.reviewed.push([j.id,o]);},...extras}});
}
let h;
const ownJob=(id,note,over={})=>labJob({id,note,commit:id.padEnd(40,'e'),snapshot_path:'restore-square/latest',created:'2026-10-01T1'+id.slice(-1)+':00:00Z',finished:'2026-10-01T1'+id.slice(-1)+':05:00Z',...over});
async function openVersions(opts){h=versionsHarness(opts);h.loads=[];h.shown=[];h.reviewed=[];h.context.saveDrawerOpen('versions',{});await settle();return h;}
test('D6 All versions: the groups in order, rows named by the list, no "Everything else" fold, the open row shows the exact path and commit',async()=>{
 const jobs=[ownJob('j3','Third save'),ownJob('j2','Second save',{commit:'b'.repeat(40)})];
 await openVersions({jobs});
 const html=h.content();
 const order=['Your saves','Checkpoints','Starting point','Lab states','Other labs in this repository (1)'].map(t=>html.indexOf(t));
 assert.ok(order.every((n,i)=>n>=0&&(i===0||n>order[i-1])),'group order: '+order);
 assert.doesNotMatch(html,/Everything else|Elsewhere in this repository/);
 assert.match(html,/Third save/);assert.match(html,/Ospf-done/);assert.match(html,/Starting configuration/);assert.match(html,/>Start</);assert.match(html,/Choose a backup as starting point…/);assert.match(html,/Full history…/);assert.match(html,/Browse the repository…/);
 assert.equal(h.title(),'All versions');assert.match(h.meta(),/Everything saved for restore-square\. Choose one to load it\./);
 assert.doesNotMatch(html,/class="open"/,'every row starts closed');
 await h.click(node('button',{cls:'save-item',data:{saveRow:'job:j2'},parent:h.dialog.__root}));
 const open=h.content();assert.match(open,/aria-expanded="true"/);assert.match(open,/<code>Course-Labs<\/code> <span aria-hidden="true">›<\/span> <code>restore-square\/latest<\/code> · commit <code>bbbbbbb<\/code>/);
 assert.match(open,/Your save · 4 devices|Your save/);
});
test('D6 the newest own save has no "See what’s different"; a lab state says how many of the lab\'s devices it covers; a design export and a view-only state are view only with their reason as text',async()=>{
 await openVersions({jobs:[ownJob('j3','Third save'),ownJob('j2','Second save',{commit:'b'.repeat(40)})]});
 const rowKey=key=>h.click(node('button',{cls:'save-item',data:{saveRow:key},parent:h.dialog.__root}));
 await rowKey('job:j3');assert.doesNotMatch(h.content(),/See what’s different/);
 await rowKey('job:j2');assert.match(h.content(),/See what’s different/);
 await rowKey('state:BGP/start');assert.match(h.content(),/Lab state · covers 2 of your 4 devices/);
 const closed=await (async()=>{await rowKey('state:BGP/start');return h.content();})();
 assert.match(closed,/Design plan: view and download only/);assert.match(closed,/View only: saved without the files needed to load it/);
 await rowKey('state:restore-square/checkpoints/design');
 const design=h.content();assert.match(design,/data-save-action="files"/);assert.match(design,/data-save-action="zip"/);assert.match(design,/data-save-action="load"[^>]*disabled/);assert.doesNotMatch(design,/Keep as a checkpoint/);
});
test('D6 empty groups say what to do; a list failure is never worded as "not saved yet"; a lab without a save location lists lab states with the repository',async()=>{
 await openVersions({jobs:[],list:states({states:[]})});
 const empty=h.content();assert.match(empty,/No saves yet\. Save makes the first one\./);assert.match(empty,/No checkpoints yet\. Keep a save as a checkpoint to hold on to it\./);assert.match(empty,/No starting point yet\./);assert.match(empty,/No lab states in this repository yet\./);assert.doesNotMatch(empty,/<summary>Other labs|<summary>Save activity/);
 // the VM did not answer
 h=versionsHarness({routes:{'GET /labs/lab/restore/states':()=>{throw netErr(h,'network');}}});h.loads=[];h.context.saveDrawerOpen('versions',{});await settle();
 assert.match(h.content(),/The saved versions could not be loaded\./);assert.match(h.content(),/Try again/);assert.match(h.content(),/Check the VM connection…/);assert.doesNotMatch(h.content(),/not saved yet|No saves yet/);
 // no save location: the default repository of the places answer is asked for
 h=versionsHarness({context:{binding:null},routes:{'GET /labs/lab/git/places':{default:{repository:'r9',folder:'lab'},repositories:[{id:'r9',path:'/home/me/Shared'}]}}});h.loads=[];h.context.saveDrawerOpen('versions',{});await settle();
 assert.ok(h.requests.some(r=>/restore\/states\?repository=r9$/.test(r.url)));assert.match(h.content(),/This lab has not been saved yet\./);assert.doesNotMatch(h.content(),/Your saves/);assert.match(h.content(),/Lab states/);assert.match(h.content(),/Save as a lab state…/);
});
test('D6 the open row, an open fold and the first five saves survive a re-render (the poll)',async()=>{
 const jobs=['j9','j8','j7','j6','j5','j4','j3'].map((id,i)=>ownJob(id,'save '+id,{commit:id.padEnd(40,'1')}));
 await openVersions({jobs});
 assert.equal((h.content().match(/data-save-row="job:/g)||[]).length,5);assert.match(h.content(),/Show older saves/);
 await h.click(node('button',{cls:'save-item',data:{saveRow:'job:j8'},parent:h.dialog.__root}));
 const before=h.content();h.context.saveDrawerRender();h.context.saveDrawerRender();assert.equal(h.content(),before,'a poll with nothing new changes nothing');
 h.context.state.git_jobs=[...h.context.state.git_jobs];h.context.saveDrawerRender();assert.match(h.content(),/aria-expanded="true"/);
 assert.equal(h.sd.openRow,'job:j8');
});
test('D7 Details: every own save the manager holds has it, a row whose job is gone has none, a waiting row has Upload… first and Details; Upload… opens What changed without uploading',async()=>{
 const waiting=ownJob('j3','Waiting save'),done=ownJob('j2','Uploaded save',{status:'synced',pushed:true,commit:'b'.repeat(40)});
 await openVersions({jobs:[waiting,done]});
 const rowKey=key=>h.click(node('button',{cls:'save-item',data:{saveRow:key},parent:h.dialog.__root}));
 await rowKey('job:j3');const w=h.content();assert.match(w,/Not uploaded yet/);assert.ok(w.indexOf('data-save-action="upload-job"')>0&&w.indexOf('data-save-action="upload-job"')<w.indexOf('data-save-action="load"'),'Upload… is the first action');
 await h.click(h.button('upload-job',{saveRow:'job:j3'}));
 assert.deepEqual(h.reviewed.map(r=>[r[0],r[1]]),[['j3',undefined]],'Upload… calls gitReviewJob(job) without the upload option');
 h.context.saveDrawerOpen('versions',{});await settle();await rowKey('job:j2');assert.match(h.content(),/data-save-action="details"/);
 await h.click(h.button('details',{saveRow:'job:j2'}));assert.deepEqual(h.shown,['j2']);
 // a row from the list whose job was trimmed
 await openVersions({jobs:[]});await h.click(node('button',{cls:'save-item',data:{saveRow:'state:restore-square/latest'},parent:h.dialog.__root}));
 assert.doesNotMatch(h.content(),/data-save-action="details"|Keep as a checkpoint/);
});
test('D7 the Save activity fold holds every other job, open when one waits, and a failed attempt keeps a home',async()=>{
 const failed={id:'f1',lab_id:'lab',kind:'capture',target:'latest',status:'failed',message:'x',created:'2026-10-01T07:00:00Z'},move={id:'m1',lab_id:'lab',target:'move',status:'review_pending',commit:'c'.repeat(40),snapshot_path:'new/latest',changed_files:['x'],created:'2026-10-01T08:00:00Z'};
 await openVersions({jobs:[ownJob('j3','Own'),failed,move]});
 const html=h.content();assert.match(html,/<summary>Save activity \(2\)<\/summary>/);assert.match(html,/data-fold="activity" open/);
 await h.click(node('button',{cls:'save-item',data:{saveRow:'act:m1'},parent:h.dialog.__root}));
 assert.match(h.content(),/data-save-action="upload-job"/);assert.match(h.content(),/data-save-action="details"/);
});
test('D8 Keep as a checkpoint sends the save route\'s checkpoint target; Use as starting point sends backup_job_id, replace_baseline and expected_baseline; without a kept or whole capture both are disabled with their reason',async()=>{
 const sent=[],job=ownJob('j3','Own save');
 await openVersions({jobs:[job],extras:{gitSubmitSave:async(...a)=>{sent.push(a);return {};}}});
 const rowKey=key=>h.click(node('button',{cls:'save-item',data:{saveRow:key},parent:h.dialog.__root}));
 await rowKey('job:j3');await h.click(h.button('checkpoint',{saveRow:'job:j3'}));
 assert.match(h.content(),/Checkpoint name/);assert.match(h.content(),/Saved as: Own-save/);
 const input=node('input',{data:{saveField:'checkpoint-name'},value:'my check point!',parent:h.dialog.__root});h.fire('input',{target:input});assert.equal(input.value,'my-check-point');
 await h.click(h.button('checkpoint-keep',{saveRow:'job:j3'}));
 assert.equal(sent.length,1);assert.equal(sent[0][1].target,'checkpoint');assert.equal(sent[0][1].checkpoint,'my-check-point');assert.equal(sent[0][1].backup_job_id,'cap1');
 await openVersions({jobs:[job],extras:{gitSubmitSave:async(...a)=>{sent.push(a);return {};}}});await rowKey('job:j3');await h.click(h.button('baseline',{saveRow:'job:j3'}));
 assert.match(h.content(),/Make this save the starting point of restore-square\? No device is read or changed\./);assert.match(h.content(),/It replaces the current starting point, saved when 2026-09-30T09:00:00Z\. The previous one stays in the history\./);assert.match(h.content(),/Replace the starting point/);
 await h.click(h.button('baseline-confirm',{saveRow:'job:j3'}));
 const base=sent[1][1];assert.equal(base.target,'baseline');assert.equal(base.backup_job_id,'cap1');assert.equal(base.replace_baseline,true);assert.equal(base.expected_baseline,'rev1');
 // the capture is gone / lacks the topology
 await openVersions({jobs:[ownJob('j3','Own',{capture_kept:false})]});await rowKey('job:j3');
 assert.match(h.content(),/data-save-action="checkpoint"[^>]*disabled/);assert.match(h.content(),/data-save-action="baseline"[^>]*disabled/);assert.match(h.content(),/The capture of this save is no longer kept\. Save again to make a checkpoint\./);assert.match(h.content(),/data-save-action="save-again"/);
 await openVersions({jobs:[ownJob('j3','Own',{capture_whole:false})]});await rowKey('job:j3');assert.match(h.content(),/This capture does not include the topology\. Save again first\./);
});
test('D8 Choose a backup as starting point… is in the Starting point group, also without a starting point, and calls gitSaveOptions("baseline")',async()=>{
 const asked=[];
 await openVersions({jobs:[],list:states({states:[]}),extras:{gitSaveOptions:async(...a)=>{asked.push(a);}}});
 assert.match(h.content(),/No starting point yet\.[\s\S]*Choose a backup as starting point…/);
 await h.click(h.button('baseline-backup'));assert.deepEqual(asked,[['baseline','lab']]);assert.equal(h.dialog.open,false,'the dialog it opens replaces the drawer');
});
test('D9 every Load this state… calls loadChoose with a five-key source: folder for a state at HEAD, git with the commit for an older save',async()=>{
 await openVersions({jobs:[ownJob('j3','Newest',{commit:'f'.repeat(40)}),ownJob('j2','Older',{commit:'b'.repeat(40)})]});
 const rowKey=key=>h.click(node('button',{cls:'save-item',data:{saveRow:key},parent:h.dialog.__root}));
 await rowKey('job:j2');await h.click(h.button('load',{saveRow:'job:j2'}));
 assert.equal(h.loads.length,1);let [id,source,name]=h.loads[0];assert.equal(id,'lab');assert.deepEqual(Object.keys(source).sort(),['backup_job_id','commit','path','repository','type']);
 assert.equal(source.type,'git');assert.equal(source.commit,'b'.repeat(40));assert.equal(source.path,'/restore-square/latest');assert.equal(name,'Older');assert.equal(h.dialog.open,false,'the drawer closed before the confirmation');
 await openVersions({jobs:[ownJob('j3','Newest',{commit:'f'.repeat(40)})]});await rowKey('state:BGP/start');await h.click(h.button('load',{saveRow:'state:BGP/start'}));
 [id,source,name]=h.loads[0];assert.equal(source.type,'folder');assert.equal(source.path,'/BGP/start');assert.equal(source.commit,'f'.repeat(40));assert.equal(source.repository,'');assert.equal(name,'Start');
 // a view-only row cannot be loaded, whatever is clicked
 await openVersions({jobs:[]});await rowKey('state:BGP/old');await h.click(h.button('load',{saveRow:'state:BGP/old',}));assert.equal(h.loads.length,0);
 assert.doesNotMatch(source_,/loadState\(/);
});
const source_=source;
test('D9 where load.js is missing Load degrades to a sentence, never a throw',async()=>{
 await openVersions({jobs:[ownJob('j3','Newest')],extras:{loadChoose:undefined}});
 await h.click(node('button',{cls:'save-item',data:{saveRow:'job:j3'},parent:h.dialog.__root}));
 await h.click(h.button('load',{saveRow:'job:j3'}));assert.match(h.content(),/Loading a state is not available on this page\./);
});
test('D9 See what’s different and View files open their own view with Back, and Back returns to All versions with the row still open',async()=>{
 const jobs=[ownJob('j3','Newest',{commit:'f'.repeat(40)}),ownJob('j2','Older',{commit:'b'.repeat(40)})];
 await openVersions({jobs,routes:{'POST /labs/lab/git/compare':{files:[{name:'ceos.cfg',status:'changed',diff:diff()}]},'POST /labs/lab/git/version':{manifest:{files:[{path:'ceos.cfg',node:'ceos',restore_artifact:'ceos.eoscfg'},{path:'t.clab.yml',kind:'topology'}]},files:[{name:'ceos.cfg',text:'hostname ceos'},{name:'ceos.eoscfg',text:'x'},{name:'t.clab.yml',text:'name: t'}],restore_supported:true}},extras:{gitFilesDiffMarkup:files=>files.map(f=>`<details class="diff-file"><summary>${f.name}</summary></details>`).join('')}});
 const rowKey=key=>h.click(node('button',{cls:'save-item',data:{saveRow:key},parent:h.dialog.__root}));
 await rowKey('job:j2');await h.click(h.button('different',{saveRow:'job:j2'}));
 assert.equal(h.title(),'Different from your latest save');assert.match(h.meta(),/How Older differs from the last save of restore-square\. To see what would change on the devices, choose Load this state…: the devices are compared before anything is loaded\./);
 const compare=h.requests.find(r=>/git\/compare$/.test(r.url));assert.deepEqual(JSON.parse(JSON.stringify(compare.data)),{commit:'b'.repeat(40),path:'/restore-square/latest'});assert.match(h.content(),/ceos\.cfg/);
 assert.equal($hidden(h,'save-drawer-back'),false);
 await h.click(node('button',{id:'save-drawer-back',parent:h.dialog.__root}));assert.equal(h.title(),'All versions');await settle();
 await rowKey('job:j2');await h.click(h.button('files',{saveRow:'job:j2'}));
 assert.equal(h.title(),'View files');const files=h.content();assert.match(files,/Devices/);assert.match(files,/Topology and map/);assert.match(files,/Files Load uses \(1\)/);assert.match(files,/Save details/);assert.match(files,/hostname ceos/);
});
function $hidden(h,id){return h.$(id).hidden;}
test('D9 Download ZIP posts the version request with the repository of a lab without a save location',async()=>{
 await openVersions({jobs:[ownJob('j3','Newest')],routes:{'POST /labs/lab/git/version/download':{}}});
 await h.click(node('button',{cls:'save-item',data:{saveRow:'job:j3'},parent:h.dialog.__root}));await h.click(h.button('zip',{saveRow:'job:j3'}));
 const request=h.requests.find(r=>/version\/download$/.test(r.url));assert.ok(request);assert.deepEqual(JSON.parse(request.options.body),{commit:'j3'.padEnd(40,'e'),path:'/restore-square/latest'});assert.deepEqual(h.calls.filter(c=>c[0]==='download-click').length,1);
});
const settingsContext=(over={})=>({binding,repository_status:{ready:true,head:'abcdef0123456789'},supported_nodes:[{name:'ceos',short_name:'ceos',platform:'ceos'},{name:'xrv9k',platform:'xrv9k'}],unsupported_nodes:[{name:'clab-restore-square-host1',short_name:'host1'}],jobs:[],...over});
const catalog={repositories:[{id:'b',path:'/home/me/Course-Labs',prefix:'restore-square/'}]};
function settingsHarness({context=settingsContext(),jobs=[],routes={},extras={},lab={}}={}){
 const g=harness({jobs,routes:{'GET /git/repositories':catalog,...routes},extras:{gitLoadContext:async()=>context,...extras}});
 Object.assign(g.lab,lab);g.shown=[];return g;
}
test('D10 Save settings: the F15 controls, one Git details fold with the git-advanced ids, a folded fold, real tick boxes in a labelled fieldset',async()=>{
 const g=settingsHarness();g.context.saveDrawerOpen('settings',{});await settle();
 const html=g.content();
 assert.equal(g.title(),'Save settings');assert.match(g.meta(),/Where restore-square saves, and which devices each save includes\./);
 for(const text of ['Save location','Change folder…','Use a different repository…','Connect by URL…','Devices included in every save','Git details','Refresh status','Update from the repository','Disconnect this lab…','Save settings'])assert.ok(html.includes(text),text);
 assert.match(html,/data-git-repo-action="switch"/);assert.match(html,/data-git-repo-action="connect"/);assert.match(html,/data-git-repo-action="unlink"/);assert.match(html,/data-save-action="folder"/);
 assert.match(html,/<code>Course-Labs<\/code><span aria-hidden="true">›<\/span><code>restore-square<\/code>/);
 assert.match(html,/<input type="checkbox" name="git-node" value="ceos" checked>/);assert.match(html,/<legend class="sr-only">Devices included in every save<\/legend>/);
 for(const id of ['git-advanced-push-url','git-advanced-branch','git-advanced-owner','git-advanced-path','git-advanced-status','git-advanced-account'])assert.ok(html.includes('id="'+id+'"'),id);
 assert.match(html,/Verified push destination: <code>https:\/\/github\.com\/me\/Course-Labs\.git<\/code>/);assert.equal((html.match(/<details/g)||[]).length,1,'one fold');
 assert.match(html,/host1 can’t be included yet — configuration saves aren’t supported for its platform\./);assert.match(html,/If an included device can’t be reached, the save stops and nothing is written/);
 assert.doesNotMatch(html,/Nothing is uploaded without you|git-exposure|Registration details|review_before_push/);
});
test('D10 Save settings: no repository on the VM, no save location, a list failure, no topology file, a legacy folder, saving not possible',async()=>{
 let g=settingsHarness({context:{binding:null,supported_nodes:[]},routes:{'GET /git/repositories':{repositories:[]}}});g.context.saveDrawerOpen('settings',{});await settle();
 assert.match(g.content(),/Connect a repository by URL/);assert.match(g.content(),/Check again/);assert.match(g.content(),/Administrator setup \(terminal\)/);
 g=settingsHarness({context:{binding:null,supported_nodes:[]}});g.context.saveDrawerOpen('settings',{});await settle();
 assert.match(g.content(),/This lab has no save location yet\./);assert.match(g.content(),/Choose a place…/);assert.match(g.content(),/Connect by URL…/);assert.doesNotMatch(g.content(),/Devices included in every save/);
 g=settingsHarness({extras:{gitLoadContext:async()=>{throw netErr(g,'x');}}});g.context.saveDrawerOpen('settings',{});await settle();
 assert.match(g.content(),/The save settings could not be loaded\./);assert.match(g.content(),/Try again/);
 g=settingsHarness({lab:{topology_in_manager:false,git_status:{checked:true,ready:false,problem:'The VM account cannot upload to github.com.',waiting:0}}});g.context.saveDrawerOpen('settings',{});await settle();
 assert.match(g.content(),/This lab has no topology file in the manager, so saves hold device configurations only\./);assert.match(g.content(),/Update topology file…/);assert.match(g.content(),/<p class="banner warn">The VM account cannot upload to github\.com\.<\/p>/);
 g=settingsHarness({context:settingsContext({binding:{...binding,repository:{...binding.repository,prefix:'latest/'}}}),extras:{gitLegacyDestinationNotice:()=>'legacy sentence'}});g.context.saveDrawerOpen('settings',{});await settle();assert.match(g.content(),/legacy sentence/);
});
test('D11 a waiting save disables nothing: Save settings is enabled and sends the device selection at once (through the place route, never PUT …/git); the line says the save stays part of the next upload; Update from the repository gives way to Upload…',async()=>{
 const waiting=ownJob('j3','Waiting'),puts=[];
 const g=settingsHarness({jobs:[waiting],lab:{git_status:{checked:true,ready:true,problem:'',waiting:1}},routes:{'POST /labs/lab/git/place':data=>{puts.push(data);return {saved:true,binding:{},job:null};},'PUT /labs/lab/git':()=>{throw new Error('the old route must not be called');}}});
 g.context.saveDrawerOpen('settings',{});await settle();
 const html=g.content();assert.match(html,/1 save is waiting for upload\. It was made with the devices chosen before and stays part of the next upload\./);
 assert.doesNotMatch(html,/disabled/);assert.doesNotMatch(html,/Keep it on the VM only/);assert.doesNotMatch(html,/data-git-repo-action="update"/);assert.match(html,/Saves are waiting for upload in this repository\. Upload them before updating from the repository\./);assert.match(html,/data-save-action="upload-waiting"/);
 // device ticks are drawer state: unticking keeps the change through a poll and shows the removal sentence
 g.fire('change',{target:node('input',{name:'git-node',value:'xrv9k',checked:false,parent:g.dialog.__root})});
 g.context.saveDrawerRender();assert.match(g.content(),/<input type="checkbox" name="git-node" value="xrv9k" >/);assert.match(g.content(),/xrv9k is no longer included\. Its saved file is removed with the next save; older versions keep it\./);
 await g.click(g.button('save-settings'));
 assert.equal(puts.length,1);assert.deepEqual(JSON.parse(JSON.stringify(puts[0].node_names)),['ceos']);assert.equal(puts[0].repository,'b');assert.equal(puts[0].move_files,false);assert.equal(puts[0].choice,'');assert.equal(puts[0].acknowledge,true);assert.equal(typeof puts[0].folder,'string','the lab’s own folder: nothing moves');assert.deepEqual(g.notices,['Save settings updated.']);
 // every device unticked is an error under the list, not a disabled button
 g.fire('change',{target:node('input',{name:'git-node',value:'ceos',checked:false,parent:g.dialog.__root})});g.fire('change',{target:node('input',{name:'git-node',value:'xrv9k',checked:false,parent:g.dialog.__root})});await g.click(g.button('save-settings'));
 assert.match(g.content(),/<p class="form-error" role="alert" id="save-settings-error">Choose at least one device to include\.<\/p>/);assert.equal(puts.length,1);
 await openNoWaiting();
 async function openNoWaiting(){const k=settingsHarness();k.context.saveDrawerOpen('settings',{});await settle();assert.match(k.content(),/data-git-repo-action="update"/);assert.doesNotMatch(k.content(),/save-settings-waiting"/);}
});
test('D11 the dialogs of git-progress.js close the drawer first and Refresh status stays inside it; Disconnect is a single request through gitUnlink',async()=>{
 const ran=[];
 const g=settingsHarness({extras:{gitRunAction:async(a,id)=>{ran.push([a,id,g.dialog.open]);}}});g.context.saveDrawerOpen('settings',{});await settle();
 await g.click(node('button',{data:{gitRepoAction:'unlink'},parent:g.dialog.__root}));assert.deepEqual(ran,[['unlink','lab',false]]);
 g.context.saveDrawerOpen('settings',{});await settle();const before=g.requests.length;
 await g.click(node('button',{data:{gitRepoAction:'refresh'},parent:g.dialog.__root}));assert.equal(ran.length,1,'refresh is the drawer\'s own');assert.ok(g.requests.length>before);assert.equal(g.dialog.open,true);
});
test('D12 live regions hold only a sentence: no button, link, field or select inside role=status, aria-live or role=alert, in any kind or state',async()=>{
 const bad=html=>{const found=[];const re=/<(\w+)\b[^>]*(?:role="(?:status|alert)"|aria-live)[^>]*>([\s\S]*?)<\/\1>/g;let m;while((m=re.exec(html)))if(/<(button|a|input|select|textarea)\b/.test(m[2]))found.push(m[0].slice(0,80));return found;};
 const pages=[];
 const grab=g=>pages.push(g.content(),g.actions(),g.$('save-drawer-status').textContent);
 const job=labJob();let g=harness({jobs:[job],extras:{gitReviewData:async()=>reviewFor(job,{also_sends:[{job_id:'q',name:'<b>x</b>'}]}),saveChangeSentence:()=>'s.'}});g.context.saveDrawerOpen('changes',{job});await settle();grab(g);
 g=harness({jobs:[job],extras:{gitReviewData:async()=>{throw new Error('nope');}}});g.context.saveDrawerOpen('changes',{job});await settle();grab(g);
 await openVersions({jobs:[ownJob('j3','x',{capture_kept:false})]});await h.click(node('button',{cls:'save-item',data:{saveRow:'job:j3'},parent:h.dialog.__root}));grab(h);
 h=versionsHarness({routes:{'GET /labs/lab/restore/states':()=>{throw netErr(h,'n');}}});h.context.saveDrawerOpen('versions',{});await settle();grab(h);
 g=settingsHarness({lab:{git_status:{checked:true,ready:false,problem:'p',waiting:2}}});g.context.saveDrawerOpen('settings',{});await settle();grab(g);
 g.fire('change',{target:node('input',{name:'git-node',value:'ceos',checked:false,parent:g.dialog.__root})});g.fire('change',{target:node('input',{name:'git-node',value:'xrv9k',checked:false,parent:g.dialog.__root})});await g.click(g.button('save-settings'));grab(g);
 const all=pages.flatMap(bad);assert.deepEqual(all,[]);assert.ok(pages.some(p=>/role="alert"/.test(p)),'the scan covered an alert');
 assert.equal(source.match(/aria-live|role="status"/g),null,'the one live region is the static #save-drawer-status of index.html, not markup of this file');
});
test('D13 the markup uses the shared class names: none of the retired drawer, row or fold names, quiet actions are button ghost small',async()=>{
 assert.doesNotMatch(source,/save-quiet|save-h\b|save-open|save-fold|save-drawer-foot|\brx-|\bpx-|save-also"/);
 await openVersions({jobs:[ownJob('j3','x')]});await h.click(node('button',{cls:'save-item',data:{saveRow:'job:j3'},parent:h.dialog.__root}));
 assert.match(h.content(),/class="button ghost small" data-save-action="files"/);assert.match(h.content(),/class="save-item"/);assert.match(h.content(),/<li class="open">/);
});
test('D14 one drawer: opening a second kind replaces the first, Back goes one level (the draft survives), Escape goes back, then closes; a lab change closes it; focus returns',async()=>{
 const trigger=node('button',{id:'opener'});trigger.focus=function(){h2.context.document.activeElement=this;};trigger.isConnected=true;
 const h2=settingsHarness();h2.context.document.activeElement=trigger;h=h2;
 h2.context.saveDrawerOpen('settings',{});await settle();assert.equal(h2.dialog.open,true);assert.equal(h2.$('save-drawer-title').textContent,'Save settings');assert.equal(h2.$('save-drawer-back').hidden,true);
 assert.equal(h2.context.document.activeElement.id,'save-drawer-title','focus goes to the heading, not the close button');
 h2.fire('change',{target:node('input',{name:'git-node',value:'xrv9k',checked:false,parent:h2.dialog.__root})});
 h2.context.saveDrawerOpen('chooser',{mode:'location',back:{kind:'settings',options:{restore:true}}});await settle();
 assert.equal(h2.sd.kind,'chooser');assert.equal(h2.$('save-drawer-back').hidden,false);assert.equal(h2.$('save-drawer-title').textContent,'Where should restore-square save?');
 const cancel=event=>h2.fire('cancel',event);let prevented=0;
 cancel({preventDefault(){prevented++;}});await settle();assert.equal(prevented,1);assert.equal(h2.sd.kind,'settings','Escape went back one level');
 assert.match(h2.content(),/<input type="checkbox" name="git-node" value="xrv9k" >/,'the unticked box survived the round trip');
 cancel({preventDefault(){}});assert.equal(h2.dialog.open,false,'Escape on the first level closes');assert.equal(h2.context.document.activeElement,trigger,'focus returns to the opener');
 // when the opener is gone focus goes to the chip button
 h2.context.document.activeElement=null;const chip=h2.$('save-chip');h2.context.saveDrawerOpen('versions',{});await settle();h2.context.saveDrawerClose();assert.equal(h2.context.document.activeElement,chip);
 // the page moved to another lab
 h2.context.saveDrawerOpen('settings',{});await settle();h2.context.activeId='other';h2.context.saveDrawerRender();assert.equal(h2.dialog.open,false);
 // a refresh with no drawer open does nothing
 const before=h2.requests.length;await h2.context.saveDrawerRefresh(true);assert.equal(h2.requests.length,before);
});
test('D14 listeners sit on the dialog only: no window, document, location, history or storage listener in the script',()=>{
 assert.doesNotMatch(source,/window\.addEventListener|document\.addEventListener|addEventListener\('(popstate|hashchange)|localStorage|sessionStorage|history\.(pushState|replaceState|back)|\blocation\.(hash|href|assign|replace)/);
 const g=harness();assert.deepEqual(Object.keys(g.dialog.listeners).sort(),['cancel','change','click','close','input','keydown','toggle']);
});
test('D14 closing the header panels first: closeMenus is called behind a guard, and the drawer loads where it is missing',()=>{
 let closed=0;const g=harness({extras:{closeMenus:()=>{closed++;}}});g.context.saveDrawerOpen('state',{});assert.equal(closed,1);
 const bare=harness();bare.context.saveDrawerOpen('state',{});assert.equal(bare.dialog.open,true);
 assert.match(bare.content(),/The folder chooser is not available on this page\./,'a missing chooser degrades to a sentence');
});
const places=(over={})=>({repositories:[{id:'b',name:'Course-Labs',path:'/home/me/Course-Labs',current:true}],default:{repository:'b',folder:'BGP',answer:{kind:'free',folder:'BGP',typed:'BGP',exists:true},ask:false,beside:''},tree:{repository:'b',own:{folder:'restore-square',files:6},files:[],head:'f'.repeat(40),truncated:false,saved:[],folders:[{path:'',kind:'free',folder:'',typed:'',exists:true},{path:'restore-square',kind:'own',folder:'restore-square',typed:'restore-square',exists:true},{path:'BGP',kind:'free',folder:'BGP',typed:'BGP',exists:true}]},...over});
// Stubs of git-places.js (S10): the model holds the tree's answers by path; folderChooserEvent decodes the clicked fake control's data-act.
const chooserStubs=seen=>({
 folderClean:v=>String(v).replace(/\s+/g,'-').replace(/\/+/g,'/').replace(/\/$/,''),folderOwnPath:m=>m.tree.own?.folder||'',folderDefaultExpanded:()=>new Set(['','restore-square']),
 folderChooserModel:tree=>({tree,answers:new Map((tree.folders||[]).map(a=>[a.path,a])),nodes:new Map()}),
 folderChooserMarkup:(model,view)=>{seen.push({model,view});return `<div class="folder-chooser" data-mode="${view.mode}"><input id="folder-path" value="${escapeHtml(view.value)}"><p class="folder-answer" id="folder-answer" role="status" aria-live="polite">${escapeHtml(view.answer?.kind||'')}</p><div id="folder-foot"><button type="button">Save here</button></div></div>`;},
 folderChooserEvent:(type,event)=>{const t=event.target;const el=t&&t.closest?t.closest('[data-act]'):null;return el?JSON.parse(el.dataset.act):null;}});
function chooserHarness({extras={},routes={},jobs=[],...rest}={}){
 const seen=[];
 const g=harness({jobs,routes:{'GET /labs/lab/git/places':places(rest.places||{}),...routes},extras:{gitLoadContext:async()=>settingsContext(),...chooserStubs(seen),...extras}});
 g.seen=seen;g.act=(action,data={})=>g.click(node('button',{data:{act:JSON.stringify({action,...data})},parent:node('div',{cls:'folder-chooser',parent:g.dialog.__root})}));return g;
}
test('D14 the chooser kinds write folderChooserMarkup(model, view) into the drawer, fetch the tree from the places route and forward every event to folderChooserEvent',async()=>{
 const forwarded=[],g=chooserHarness({extras:{folderChooserEvent:(type,event)=>{forwarded.push(type);return type==='click'?{action:'select',path:'BGP'}:type==='keydown'?{action:'focus',path:'BGP'}:null;}}});
 g.context.saveDrawerOpen('chooser',{mode:'location'});await settle();
 assert.match(g.content(),/class="folder-chooser" data-mode="location"/);assert.equal(g.title(),'Where should restore-square save?');
 assert.ok(g.requests.some(r=>r.method==='GET'&&/\/labs\/lab\/git\/places$/.test(r.url)));
 const view=g.seen.at(-1).view;assert.equal(view.status,'ready');assert.equal(view.value,'restore-square','it starts in the lab\'s own folder');assert.equal(view.labName,'restore-square');assert.equal(view.repoName,'Course-Labs');
 const inside=node('li',{parent:node('div',{cls:'folder-chooser',parent:g.dialog.__root})});
 await g.click(inside);assert.deepEqual(forwarded,['click']);assert.equal(g.sd.chooser.selected,'BGP');assert.equal(g.sd.chooser.value,'BGP');assert.match(g.content(),/value="BGP"/);
 g.fire('keydown',{key:'ArrowDown',target:inside});await settle();assert.deepEqual(forwarded,['click','keydown']);assert.equal(g.sd.chooser.focus,'BGP');
 // an event outside the chooser is not forwarded
 await g.click(node('p',{parent:g.dialog.__root}));assert.equal(forwarded.length,2);
 assert.deepEqual(Object.keys(g.dialog.listeners).sort(),['cancel','change','click','close','input','keydown','toggle']);
});
test('C3 typing writes the echo at once and asks the check once, 250 ms after the last keystroke; the backend\'s folder replaces the echo; an older answer is ignored',async()=>{
 const asked=[];
 const g=chooserHarness({routes:{'POST /labs/lab/git/places/check':data=>{asked.push(data);return {kind:'free',folder:data.folder==='Week-4/BGP-lab'?'Week-4/BGP-lab':data.folder,typed:data.folder,exists:false};}}});
 g.context.saveDrawerOpen('chooser',{mode:'location'});await settle();const base=asked.length,c=g.sd.chooser;
 await g.act('typed',{value:'Week 4//BGP lab',echo:'Week-4/BGP-lab'});await g.act('typed',{value:'Week 4//BGP lab',echo:'Week-4/BGP-lab'});
 assert.equal(c.value,'Week-4/BGP-lab');assert.equal(asked.length,base,'nothing is asked while typing');
 g.timers[0]&&g.timers[0]();g.timers[1]&&g.timers[1]();await settle();
 assert.equal(asked.length,base+1);assert.deepEqual(JSON.parse(JSON.stringify(asked.at(-1))),{repository:'b',folder:'Week-4/BGP-lab',purpose:'save',name:''});assert.equal(c.answer.folder,'Week-4/BGP-lab');
 let release;const gate=new Promise(r=>{release=r;});
 g.context.api=async()=>({json:async()=>({})});
 const stale=g.context.drwChooserCheck('old');c.seq++;await settle();await stale;assert.notEqual(c.answerFor,'old');
});
test('C5 Save here posts one place request with the folder of the answer in use, choice and pending as given, acknowledge; nothing is sent without an answer; a {question} is shown, never an error',async()=>{
 const posts=[];let ask=true;
 const g=chooserHarness({routes:{'POST /labs/lab/git/place':data=>{posts.push(data);if(ask&&data.choice==='')return {question:{kind:'lab',folder:'BGP',lab:{id:'o',name:'Other'},beside:'BGP/restore-square',collision:false}};return {saved:true,binding:{},job:null};}}});
 g.context.saveDrawerOpen('chooser',{mode:'location'});await settle();const c=g.sd.chooser;
 await g.act('typed',{value:'typed/by/hand',echo:'typed/by/hand'});await g.act('save');assert.equal(posts.length,0,'without an answer for the typed path nothing is posted');
 await g.act('select',{path:'BGP'});await g.act('save');
 assert.equal(posts.length,1);assert.deepEqual(JSON.parse(JSON.stringify(posts[0])),{repository:'b',folder:'BGP',choice:'',pending:'',move_files:false,node_names:['ceos','xrv9k'],acknowledge:true});
 assert.equal(c.answer.kind,'lab','the question replaces the answer');assert.equal(c.refused,'');assert.equal(g.notices.length,0);assert.equal(g.dialog.open,true);
 ask=false;await g.act('choice',{choice:'beside'});
 assert.equal(posts.at(-1).choice,'beside');assert.deepEqual(g.notices,['restore-square now saves to Course-Labs › BGP.']);assert.equal(g.dialog.open,false);assert.ok(g.calls.some(x=>x[0]==='refresh'));
 // the typed path the VM could not check is still sent as typed (the place route decides)
 const k=chooserHarness({routes:{'POST /labs/lab/git/places/check':()=>{throw new Error('down');},'POST /labs/lab/git/place':data=>{posts.push(data);return {saved:true};}}});
 k.context.saveDrawerOpen('chooser',{mode:'location'});await settle();await k.act('typed',{value:'x y',echo:'x-y'});k.timers.at(-1)();await settle();await k.act('save');assert.equal(posts.at(-1).folder,'x-y');
 // a refusal is shown with Try again, which sends the same request again
 let fail=true;const r=chooserHarness({routes:{'POST /labs/lab/git/place':data=>{posts.push(data);if(fail)throw new Error('The VM could not be reached.');return {saved:true};}}});
 r.context.saveDrawerOpen('chooser',{mode:'location'});await settle();await r.act('select',{path:'BGP'});await r.act('save');assert.equal(r.sd.chooser.refused,'The VM could not be reached.');
 assert.equal(r.sd.chooser.problem,null,'without a recorded cause the manager’s sentence is shown as it is');
 // The manager recorded why the VM refused (lab.git_status, read again after the refusal): the chooser words it like the chip.
 r.context.saveProblem=lab=>({sentence:'Someone is working in this repository on the VM.',actions:[{action:'again'},{action:'details'}]});
 r.context.state.labs.find(l=>l.id==='lab').git_status={checked:'t',ready:false,problem:'The VM could not be reached.',code:'busy',waiting:0};
 await r.act('again');assert.deepEqual(JSON.parse(JSON.stringify(r.sd.chooser.problem)),{sentence:'Someone is working in this repository on the VM.',detail:'The VM could not be reached.',update:false});
 r.context.state.labs.find(l=>l.id==='lab').git_status={checked:'t',ready:false,problem:'x',code:'other',waiting:0};
 await r.act('again');assert.equal(r.sd.chooser.problem,null,'a cause the page cannot word stays the manager’s sentence');
 fail=false;await r.act('again');assert.equal(r.dialog.open,false);
});
test('C6 question 3: Upload it, then move uploads first through gitReviewJob(job,{upload:true}) and posts the place only after the upload finished; a failed upload posts nothing; Move and keep posts pending "keep"',async()=>{
 const waiting=ownJob('j3','Waiting'),posts=[],uploads=[];let outcome='synced',asked=false;
 const mk=()=>{asked=false;return chooserHarness({jobs:[waiting],routes:{'POST /labs/lab/git/place':data=>{posts.push(data);if(data.pending===''&&!asked){asked=true;return {question:{kind:'pending',count:1,names:['Waiting']}};}return {saved:true};},'GET /git/jobs/j3':()=>({id:'j3',status:outcome,pushed:outcome==='synced'}),
  'POST /labs/lab/git/places/check':data=>({kind:'free',folder:data.folder,typed:data.folder,exists:true})},extras:{gitReviewData:async()=>reviewFor(waiting),saveChangeSentence:()=>'ceos and xrv9k changed.',gitReviewJob:async(j,o)=>{uploads.push([j.id,o.upload,posts.length]);return {id:'j3',status:'queued'};}}});};
 let g=mk();g.context.saveDrawerOpen('chooser',{mode:'location'});await settle();
 await g.act('select',{path:'BGP'});await g.act('save');const c=g.sd.chooser;
 assert.equal(c.pending.count,1);assert.match(c.pending.summary,/ceos and xrv9k changed\./);
 outcome='push_pending';await g.act('pending',{pending:'upload'});assert.equal(uploads.length,1);assert.equal(uploads[0][1],true);assert.match(c.refused,/did not finish, so nothing moved/);
 assert.equal(posts.length,1,'a failed upload moved nothing');
 outcome='synced';await g.act('pending',{pending:'upload'});assert.equal(posts.length,2);assert.equal(posts[1].pending,'');assert.equal(uploads.at(-1)[2],1,'the place was posted after the upload');assert.ok(!posts.some(p=>p.pending==='upload'));
 g=mk();posts.length=0;g.context.saveDrawerOpen('chooser',{mode:'location'});await settle();await g.act('select',{path:'BGP'});await g.act('save');
 const before=uploads.length;await g.act('pending',{pending:'keep'});
 assert.equal(posts.at(-1).pending,'keep');assert.ok(!g.requests.some(r=>/dismiss/.test(r.url)));assert.equal(uploads.length,before,'keeping uploads nothing');
 // before the review arrived the button does nothing
 g=mk();g.context.saveDrawerOpen('chooser',{mode:'location'});await settle();g.sd.chooser.pending={count:1,summary:''};g.sd.chooser.pendingJob=waiting;g.sd.chooser.pendingReview=null;
 const n=uploads.length;await g.act('pending',{pending:'upload'});assert.equal(uploads.length,n);
});
test('C14 Save as a lab state: starts in the lab\'s own folder, the name follows into the path, the check carries purpose "state", Save posts request_id, folder, name and choice, Replace it sends "take"',async()=>{
 const posts=[],checks=[];
 const g=chooserHarness({routes:{'POST /labs/lab/git/places/check':data=>{checks.push(data);return {kind:'free',folder:data.folder,typed:data.folder,exists:false};},'POST /labs/lab/git/state':data=>{posts.push(data);return {id:'s1',lab_id:'lab',status:'queued'};}},
  extras:{gitRequestId:()=>'r'.repeat(32),gitRememberJob(){g.calls.push(['remember']);},gitStartWatch(){g.calls.push(['watch']);}}});
 g.context.saveDrawerOpen('state',{back:{kind:'versions',options:{restore:true}}});await settle();const c=g.sd.chooser;
 assert.equal(g.title(),'Save as a lab state');assert.match(g.meta(),/Saves restore-square as it is now into a folder of its own\. Where restore-square normally saves does not change\./);
 assert.equal(c.mode,'state');assert.equal(c.parent,'restore-square');assert.equal(c.value,'restore-square');
 await g.act('name',{value:'start',echo:'start'});assert.equal(c.value,'restore-square/start','the path follows the name');g.timers.at(-1)();await settle();assert.equal(checks.at(-1).purpose,'state');assert.equal(checks.at(-1).name,'start');assert.equal(checks.at(-1).folder,'restore-square/start');
 await g.act('typed',{value:'BGP/mine',echo:'BGP/mine'});await g.act('name',{value:'final',echo:'final'});assert.equal(c.value,'BGP/mine','an edited path is kept');
 await g.act('select',{path:'BGP'});assert.equal(c.value,'BGP/final','a picked folder becomes the parent');g.timers.at(-1)();await settle();
 await g.act('save');
 assert.deepEqual(JSON.parse(JSON.stringify(posts[0])),{request_id:'r'.repeat(32),repository:'b',folder:'BGP/final',name:'final',choice:''});
 assert.deepEqual(g.notices,['State Final saved in BGP/final.']);assert.equal(g.dialog.open,false);assert.ok(!g.requests.some(r=>/git\/place$/.test(r.url)),'never to the place route');
 // a state exists already: Replace it is the state route's choice "take"; a {question} is shown, not an error
 let q=true;const k=chooserHarness({routes:{'POST /labs/lab/git/places/check':data=>({kind:'state',folder:data.folder,typed:data.folder,label:'Start',layout:'latest'}),'POST /labs/lab/git/state':data=>{posts.push(data);return q?{question:{kind:'state',folder:'BGP/start',label:'Start',layout:'latest'}}:{id:'s2',status:'queued'};}},extras:{gitRequestId:()=>'q'.repeat(32)}});
 k.context.saveDrawerOpen('state',{});await settle();await k.act('name',{value:'start',echo:'start'});k.timers.at(-1)();await settle();await k.act('save');
 assert.equal(k.sd.chooser.answer.kind,'state');assert.equal(k.sd.chooser.refused,'');assert.equal(k.dialog.open,true);
 q=false;await k.act('choice',{choice:'take'});assert.equal(posts.at(-1).choice,'take');assert.equal(posts.at(-1).request_id,'q'.repeat(32));
});
test('browse mode: Load this state… goes through loadChoose with a five-key folder source, View files opens the files view and Back returns to the chooser; error states stay on screen',async()=>{
 const loads=[];
 const g=chooserHarness({extras:{loadChoose:async(...a)=>{loads.push(a);}},routes:{'POST /labs/lab/git/version':{manifest:{files:[]},files:[]}}});
 g.context.saveDrawerOpen('chooser',{mode:'browse',back:{kind:'versions',options:{restore:true}}});await settle();
 assert.equal(g.title(),'Browse the repository');assert.match(g.meta(),/Every folder of Course-Labs\. Looking at folders does not change where restore-square saves\./);
 await g.act('load',{path:'BGP/start'});assert.equal(loads.length,1);assert.deepEqual(Object.keys(loads[0][1]).sort(),['backup_job_id','commit','path','repository','type']);assert.equal(loads[0][1].path,'/BGP/start');assert.equal(loads[0][1].repository,'');assert.equal(g.dialog.open,false);
 const h3=chooserHarness({routes:{'POST /labs/lab/git/version':{manifest:{files:[]},files:[]}}});
 h3.context.saveDrawerOpen('chooser',{mode:'browse',back:{kind:'versions',options:{restore:true}}});await settle();
 await h3.act('view',{path:'BGP/start'});assert.equal(h3.title(),'View files');
 const body=h3.requests.find(r=>/git\/version$/.test(r.url)).data;assert.deepEqual(JSON.parse(JSON.stringify(body)),{commit:'f'.repeat(40),path:'/BGP/start'});
 await h3.click(node('button',{id:'save-drawer-back',parent:h3.dialog.__root}));await settle();assert.equal(h3.sd.kind,'chooser');assert.equal(h3.sd.chooser.mode,'browse');
 const bad=chooserHarness({routes:{'GET /labs/lab/git/places':()=>{throw netErr(bad,'x');}}});bad.context.saveDrawerOpen('chooser',{mode:'location'});await settle();
 assert.equal(bad.sd.chooser.status,'unreachable');assert.match(bad.content(),/folder-chooser/);
 const sick=chooserHarness({routes:{'GET /labs/lab/git/places':()=>{throw new Error('The VM said no.');}}});sick.context.saveDrawerOpen('chooser',{mode:'location'});await settle();
 assert.equal(sick.sd.chooser.status,'error');assert.equal(sick.sd.chooser.error,'The VM said no.');
 await sick.act('retry');assert.equal(sick.requests.filter(r=>/git\/places$/.test(r.url)).length,2);
});
test('chooser: a new folder is added through the check and the list, a name that exists is just selected, Remove from the list deletes, a repository switch reloads, the bring-along tick is sent as move_files',async()=>{
 const posted=[];
 const g=chooserHarness({routes:{'POST /labs/lab/git/places/check':data=>({kind:'free',folder:data.folder,typed:data.folder,exists:data.folder==='BGP'}),'POST /git/repositories/b/folders/new':data=>{posted.push(['add',data]);return {folder:data.parent+'/'+data.name,existed:false,answer:{kind:'free',folder:data.parent+'/'+data.name,exists:false}};},'DELETE /git/repositories/b/folders':data=>{posted.push(['del',data]);return {};},
  'POST /labs/lab/git/place':data=>{posted.push(['place',data]);return {saved:true};}}});
 g.context.saveDrawerOpen('chooser',{mode:'location'});await settle();
 await g.act('new-folder',{parent:'BGP'});assert.deepEqual(JSON.parse(JSON.stringify(g.sd.chooser.newFolder)),{parent:'BGP',value:''});
 await g.act('new-input',{value:'week 5',echo:'week-5'});await g.act('new-add',{value:'week-5'});
 assert.deepEqual(JSON.parse(JSON.stringify(posted[0])),['add',{lab_id:'lab',parent:'BGP',name:'week-5'}]);assert.equal(g.sd.chooser.value,'BGP/week-5');assert.equal(g.sd.chooser.newFolder,null);
 await g.act('new-folder',{parent:''});await g.act('new-cancel');assert.equal(g.sd.chooser.newFolder,null);
 await g.act('forget',{path:'BGP/week-5'});assert.deepEqual(JSON.parse(JSON.stringify(posted[1])),['del',{prefix:'BGP/week-5'}]);
 await g.act('bring',{value:false});g.sd.chooser.answer={kind:'free',folder:'BGP',bring:{offered:true,files:4,from:'old'}};g.sd.chooser.answerFor=g.sd.chooser.value;
 await g.act('save');assert.equal(posted.at(-1)[1].move_files,false);
});
test('the different kind: the drawer is the shell of load.js\'s view (its title, meta and markup with its own buttons); the drawer submits nothing itself',async()=>{
 const events=[];
 const view=review=>({title:'What\'s different',meta:review.name+' compared with what the devices run now',html:`<div class="save-row"><button type="button" class="button danger" data-load-action="diff-run">Load on 3 devices</button></div><p>${escapeHtml(review.name)}</p>`});
 const g=harness({extras:{loadDifferentMarkup:view,loadSubmit:async()=>{events.push('submit');}}});
 g.context.saveDrawerOpen('different',{review:{name:'Start'},onBack:()=>events.push('back'),onClose:()=>events.push('close')});
 assert.equal(g.title(),'What\'s different');assert.match(g.content(),/<p>Start<\/p>/);assert.match(g.content(),/data-load-action="diff-run"[^>]*>Load on 3 devices/);
 assert.equal(g.actions(),'','the buttons are load.js\'s own, inside its markup; the drawer adds none');
 assert.doesNotMatch(fs.readFileSync(path.join(__dirname,'..','app','static','save-drawers.js'),'utf8').split('\n').filter(line=>!/^\s*\/\//.test(line)).join('\n'),/loadSubmit\(/,'only load.js submits a load');
 g.context.saveDrawerBack();assert.deepEqual(events,['back']);assert.equal(g.dialog.open,false);
 g.context.saveDrawerOpen('different',{review:{name:'Start'},onClose:()=>events.push('close')});
 g.context.saveDrawerClose();assert.deepEqual(events,['back','close']);
 const plain=harness({extras:{loadDifferentMarkup:review=>`<p>${escapeHtml(review.name)}</p>`}});plain.context.saveDrawerOpen('different',{review:{name:'Old'},meta:'m'});assert.match(plain.content(),/<p>Old<\/p>/);
 const bare=harness();bare.context.saveDrawerOpen('different',{review:{}});assert.match(bare.content(),/The differences are not available on this page\./);
});
test('the poll keeps focus, caret and scroll: a rebuild puts focus back on the same control, and typed text lives in the drawer state',async()=>{
 await openVersions({jobs:[ownJob('j3','x')]});
 await h.click(node('button',{cls:'save-item',data:{saveRow:'job:j3'},parent:h.dialog.__root}));await h.click(h.button('checkpoint',{saveRow:'job:j3'}));
 const content=h.$('save-drawer-content');const field={id:'save-checkpoint-name',dataset:{saveField:'checkpoint-name'},selectionStart:2,selectionEnd:2,focus(){this.focused=true;},setSelectionRange(a,b){this.caret=[a,b];}};
 h.context.document.activeElement=field;content.__focusable=field;content.__found={'#save-checkpoint-name':field};
 h.fire('input',{target:node('input',{data:{saveField:'checkpoint-name'},value:'abc',parent:h.dialog.__root})});
 assert.match(h.content(),/value="abc"/,'typed text is state, written back by every rebuild');assert.equal(field.focused,true);assert.deepEqual(field.caret,[2,2]);
});
test('the head and the content are written without inline styles or handlers; every interpolated value is escaped',async()=>{
 const attack='"><img src=x onerror=alert(1)>';
 await openVersions({jobs:[ownJob('j3',attack)],list:states({states:[{...states().states[0],name:attack,path:attack}]})});
 await h.click(node('button',{cls:'save-item',data:{saveRow:'job:j3'},parent:h.dialog.__root}));
 const html=h.content();assert.doesNotMatch(html,/<img|style=|onclick=|onerror=\"/);assert.doesNotMatch(source,/style=|\.style\./);
});
// ---- S11 step 1: the gaps closed before the Progress tab goes ----
test('S11-15 Save as a lab state always sends the folder its Folder field shows: the default <the lab\'s folder>/<name>, never an empty folder by omission; an emptied field is the top level',async()=>{
 const posts=[];
 const g=chooserHarness({routes:{'POST /labs/lab/git/places/check':data=>({kind:'free',folder:data.folder,typed:data.folder,exists:false}),'POST /labs/lab/git/state':data=>{posts.push(data);return {id:'s1',lab_id:'lab',status:'queued'};}},extras:{gitRequestId:()=>'r'.repeat(32)}});
 g.context.saveDrawerOpen('state',{});await settle();const c=g.sd.chooser;
 await g.act('name',{value:'start',echo:'start'});
 await g.act('save');assert.equal(posts.length,0,'nothing is sent before the manager answered for the folder shown');
 g.timers.at(-1)();await settle();await g.act('save');
 assert.equal(posts.length,1);assert.equal(posts[0].folder,'restore-square/start','the default case carries the non-empty default');assert.equal(posts[0].name,'start');
 const k=chooserHarness({routes:{'POST /labs/lab/git/places/check':data=>({kind:'free',folder:data.folder,typed:data.folder,exists:true}),'POST /labs/lab/git/state':data=>{posts.push(data);return {id:'s2',lab_id:'lab',status:'queued'};}},extras:{gitRequestId:()=>'q'.repeat(32)}});
 k.context.saveDrawerOpen('state',{});await settle();await k.act('name',{value:'final',echo:'final'});await k.act('typed',{value:'',echo:''});k.timers.at(-1)();await settle();
 assert.equal(k.seen.at(-1).view.value,'','the field is empty because the person emptied it');await k.act('save');
 assert.equal(posts.at(-1).folder,'','then, and only then, the top level');assert.equal(posts.at(-1).name,'final');
});
test('S11-9 a repository by its address goes through the chooser and the place route with url: never POST …/git/connect; an empty repository is asked about and started on request',async()=>{
 const posts=[];let empty=true;
 const g=chooserHarness({routes:{'POST /labs/lab/git/place':data=>{posts.push(data);if(empty&&!data.initialize)return {question:{kind:'empty',name:'New-Empty'}};return {saved:true,binding:{repository:{path:'/home/me/New-Empty',prefix:'restore-square'}},job:null};},
  'POST /labs/lab/git/connect':()=>{throw new Error('the old route must not be called');}},extras:{saveStartBody:body=>({...body,initialize:true}),gitRepoName:repo=>String(repo.path||'').split('/').pop()}});
 g.context.saveDrawerOpen('chooser',{mode:'location',address:true});await settle();const c=g.sd.chooser;
 assert.deepEqual(JSON.parse(JSON.stringify(c.address)),{value:''});assert.equal(g.seen.at(-1).view.address.value,'');
 await g.act('save');assert.equal(posts.length,0);assert.match(c.refused,/Paste the HTTPS address/,'an address is needed before anything is sent');
 await g.act('url',{value:'https://github.com/me/New-Empty.git'});assert.equal(c.refused,'');
 await g.act('typed',{value:'my lab',echo:'my-lab'});assert.equal(g.requests.filter(r=>/places\/check$/.test(r.url)).length,0,'nothing is asked about a folder before the repository is connected');
 await g.act('save');
 assert.deepEqual(JSON.parse(JSON.stringify(posts[0])),{url:'https://github.com/me/New-Empty.git',folder:'my-lab',choice:'',pending:'',move_files:false,node_names:['ceos','xrv9k'],acknowledge:true});
 assert.equal(c.question.kind,'empty','the empty repository is a question with a button, never a raw refusal');assert.equal(g.dialog.open,true);
 await g.act('initialize');assert.equal(posts[1].url,'https://github.com/me/New-Empty.git');assert.equal(posts[1].initialize,true);assert.equal(posts[1].repository,undefined);
 assert.equal(g.dialog.open,false);assert.deepEqual(g.notices,['restore-square now saves to New-Empty › restore-square.']);
 // Back to a repository of the VM.
 const k=chooserHarness({});k.context.saveDrawerOpen('chooser',{mode:'location'});await settle();
 await k.act('address-on');assert.ok(k.sd.chooser.address);await k.act('address-off');assert.equal(k.sd.chooser.address,null);
});
test('S11-4, S11-9 Save settings: Connect by URL… opens the chooser\'s address field with Back to the settings; saving the devices never sends PUT …/git',async()=>{
 const g=settingsHarness({routes:{'GET /labs/lab/git/places':places()},extras:{...chooserStubs([]),gitRunAction(){throw new Error('the old connect dialog must not open');}}});
 g.context.saveDrawerOpen('settings',{});await settle();
 await g.click(node('button',{data:{gitRepoAction:'connect'},parent:g.dialog.__root}));await settle();
 assert.equal(g.sd.kind,'chooser');assert.ok(g.sd.chooser.address,'the address field');assert.equal(g.sd.back.kind,'settings');
 const source=require('node:fs').readFileSync(require('node:path').join(__dirname,'../app/static/save-drawers.js'),'utf8');
 assert.doesNotMatch(source,/'\/git','PUT'|\/git\/connect|\/git\/destination/);
});
