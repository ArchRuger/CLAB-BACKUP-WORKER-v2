const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const read=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8');
// A Storage like the browser's: string values, key(i), length.
function storage(){const map=new Map();return {getItem:k=>map.has(k)?map.get(k):null,setItem:(k,v)=>map.set(k,String(v)),removeItem:k=>map.delete(k),key:i=>[...map.keys()][i]??null,get length(){return map.size;}};}
function load(win){const context=vm.createContext({console,...(win?{window:win}:{}),crypto:require('node:crypto').webcrypto,TextEncoder,URLSearchParams,document:{getElementById:()=>null}});vm.runInContext(read('lab-builder-page.js'),context);vm.runInContext(read('operations.js'),context);
 // top-level const is not a property of the context; expose the tables the tests read
 for(const name of ['BUILDER_TEMPLATES','opLabels','opReviewCopy'])context[name]=vm.runInContext(name,context);
 return context;}

test('lab names follow the literal rule of the VM helper and stay short',()=>{
 const c=load();
 for(const good of ['lab1','My_Lab.v2','a','0start'])assert.equal(c.builderName(good),true,good);
 for(const bad of ['','-lead','.hidden','has space','a/b','../x','x'.repeat(61),7,null])assert.equal(c.builderName(bad),false,String(bad));
});
test('a new draft is a blank topology with the lab name, and the templates list still names every kind and image',()=>{
 const c=load();
 assert.deepEqual(JSON.parse(JSON.stringify(c.builderBlank('empty'))),{yaml:'name: empty\ntopology:\n  nodes: {}\n',annotations:''});
 assert.deepEqual(JSON.parse(JSON.stringify(c.builderBlank('lab2'))),{yaml:'name: lab2\ntopology:\n  nodes: {}\n',annotations:''});
 // the starters are gone, but the device palette still needs a template for every driver the manager has,
 // each with a name and an image (the New lab dialog no longer chooses one; dragging the palette does)
 for(const kind of ['arista_ceos','juniper_cjunosevolved','juniper_vjunosswitch','juniper_vjunosrouter','cisco_xrv9k','linux']){
  const t=c.BUILDER_TEMPLATES.find(x=>x.kind===kind);assert.ok(t,kind);assert.ok(t.name&&t.image,kind);
 }
});
test('the four built-in network templates carry the requested n24l images and the cJunosEvolved env; every image splits into repository and tag',()=>{
 const c=load(),by=k=>c.BUILDER_TEMPLATES.find(t=>t.kind===k);
 assert.equal(by('juniper_cjunosevolved').image,'n24l/cjunosevolved:26.2R1.7-EVO');assert.equal(by('juniper_vjunosswitch').image,'n24l/vjunos-switch:23.2R1.14');
 assert.equal(by('juniper_vjunosrouter').image,'n24l/juniper_vjunos-router:26.2R1.7');assert.equal(by('juniper_vjunosrouter').name,'Juniper vJunos-router');assert.equal(by('juniper_vjunosrouter').pinned,true);assert.equal(by('juniper_vjunosrouter').interfacePattern,'ge-0/0/{n:0}');
 assert.equal(by('cisco_xrv9k').image,'n24l/cisco_xrv9k:24.3.1');assert.equal(by('arista_ceos').image,'n24l/ceos:4.35.0F');
 for(const t of c.BUILDER_TEMPLATES.filter(x=>x.pinned)){assert.match(t.image,/^n24l\/[a-z0-9_-]+:[^:\/]+$/,t.kind+' is a valid lower-case reference with a tag');}
 // Juniper's entrypoint writes the container hostname only under CPTX_AUTO_CONFIG
 assert.deepEqual(JSON.parse(JSON.stringify(by('juniper_cjunosevolved').env)),{CPTX_AUTO_CONFIG:'1'});
 for(const k of ['arista_ceos','juniper_vjunosswitch','juniper_vjunosrouter','cisco_xrv9k','linux'])assert.equal(by(k).env,undefined,k+' has no env');
});
test('pinned built-in templates keep their default; the known-image and VM-image preference applies to the Linux host',()=>{
 const c=load(),list=c.builderTemplateList({arista_ceos:['site/ceos:9','ceos:old'],linux:['alpine:3'],nokia_srlinux:['ghcr.io/nokia/srlinux']},['n24l/ceos:4.34.2F']);
 assert.equal(list.find(t=>t.kind==='arista_ceos').image,'n24l/ceos:4.35.0F','a pinned kind ignores the labs\' image');
 assert.equal(list.find(t=>t.kind==='linux').image,'alpine:3','the Linux host takes the image My labs use');
 assert.equal(c.builderTemplateList({},['ghcr.io/srl-labs/network-multitool:v2','ghcr.io/srl-labs/network-multitool:v3']).find(t=>t.kind==='linux').image,'ghcr.io/srl-labs/network-multitool:v3','then the highest matching VM image');
 assert.equal(c.builderTemplateList({},[]).find(t=>t.kind==='linux').image,'ghcr.io/srl-labs/network-multitool:latest');
 assert.ok(c.builderImages(list,{nokia_srlinux:['ghcr.io/nokia/srlinux']}).includes('ghcr.io/nokia/srlinux'));
});
test('stored templates are migrated once: only an untouched prior built-in default moves, nothing else',()=>{
 const c=load(),plain=v=>JSON.parse(JSON.stringify(v));
 const list=[{name:'Arista cEOS',kind:'arista_ceos',image:'ceos:4.35.0F'},{name:'Juniper cJunosEvolved',kind:'juniper_cjunosevolved',image:'cjunosevolved:26.2R1.7-EVO'},
  {name:'Juniper cJunosEvolved ',kind:'juniper_cjunosevolved',image:'cjunosevolved:26.2R1.7-EVO'},{name:'My ceos',kind:'arista_ceos',image:'ceos:4.35.0F'},
  {name:'Cisco XRv9k',kind:'cisco_xrv9k',image:'registry.example:5000/xr:9'},{name:'Linux host',kind:'linux',image:'ghcr.io/srl-labs/network-multitool:latest'},
  {name:'Juniper vJunos-switch',kind:'linux',image:'vrnetlab/juniper_vjunos-switch:23.2R1.14'}];
 const m=c.builderMigrateTemplates(list),out=plain(m.list);
 assert.equal(m.changed,true);assert.equal(out[0].image,'n24l/ceos:4.35.0F','prior default migrates');
 assert.deepEqual(out[1],{name:'Juniper cJunosEvolved',kind:'juniper_cjunosevolved',image:'n24l/cjunosevolved:26.2R1.7-EVO',env:{CPTX_AUTO_CONFIG:'1'}},'cJunosEvolved also gets the hostname env');
 for(const i of [2,3,4,5,6])assert.deepEqual(out[i],list[i],'entry '+i+' (renamed, custom, other image, linux, wrong kind) is untouched');
 const again=c.builderMigrateTemplates(out);assert.equal(again.changed,false);assert.deepEqual(plain(again.list),out,'idempotent');
 // an env or startup-config of the user's own is never touched or added to
 const own=[{name:'Juniper cJunosEvolved',kind:'juniper_cjunosevolved',image:'cjunosevolved:26.2R1.7-EVO',env:{X:'1'}},{name:'Juniper cJunosEvolved',kind:'juniper_cjunosevolved',image:'cjunosevolved:26.2R1.7-EVO',startupConfig:'/c.cfg'}];
 const o=plain(c.builderMigrateTemplates(own).list);assert.deepEqual(o[0].env,{X:'1'});assert.equal(o[1].env,undefined);assert.equal(o[0].image,'n24l/cjunosevolved:26.2R1.7-EVO');
 assert.deepEqual(plain(c.builderMigrateTemplates(null)),{list:[],changed:false});
});
test('templates(): the stored list is migrated once under a version marker, and a template stored later is not',()=>{
 const s=storage(),win={localStorage:s},c=load(win);
 s.setItem('clab-builder:templates',JSON.stringify({list:[{name:'Arista cEOS',kind:'arista_ceos',image:'ceos:4.35.0F'},{name:'Mine',kind:'linux',image:'a:1'}],defaultName:'Mine'}));
 const first=JSON.parse(JSON.stringify(win.labBuilderPage.templates()));assert.equal(first.list[0].image,'n24l/ceos:4.35.0F');assert.equal(first.defaultName,'Mine');assert.equal(s.getItem('clab-builder:templates-version'),'2');
 s.setItem('clab-builder:templates',JSON.stringify({list:[{name:'Arista cEOS',kind:'arista_ceos',image:'ceos:4.35.0F'}],defaultName:''}));
 assert.equal(win.labBuilderPage.templates().list[0].image,'ceos:4.35.0F','after the marker an old-looking template is the user\'s own');
});
test('a fresh browser\'s first template save is never migrated afterwards (the user\'s edit wins)',()=>{
 const s=storage(),win={localStorage:s},c=load(win);
 assert.equal(win.labBuilderPage.templates().list.find(t=>t.kind==='arista_ceos').image,'n24l/ceos:4.35.0F','defaults in use');
 assert.equal(s.getItem('clab-builder:templates-version'),'2','nothing stored: marked current');
 const s2=storage(),win2={localStorage:s2};load(win2);
 win2.labBuilderPage.saveTemplates([{name:'Arista cEOS',kind:'arista_ceos',image:'ceos:4.35.0F',binds:['a:/b']}],'');
 const t=win2.labBuilderPage.templates().list[0];
 assert.equal(t.image,'ceos:4.35.0F','an edit saved from this page keeps its image');assert.deepEqual(JSON.parse(JSON.stringify(t.binds)),['a:/b']);
});
test('templates prefer an image the VM has over the placeholder (Linux), the Image list offers the VM images, and the draft\'s images are read',()=>{
 const c=load(),vm=['n24l/ceos:4.34.2F','n24l/ceos:4.35.0F','ghcr.io/srl-labs/network-multitool:latest','other/thing:1'];
 const list=c.builderTemplateList({},vm);
 const plain=v=>JSON.parse(JSON.stringify(v));
 assert.ok(c.builderImages(list,{},vm).includes('other/thing:1'),'every VM image is offered in the Image list');
 assert.deepEqual(plain(c.builderYamlImages('name: x\ntopology:\n  kinds:\n    linux:\n      image: "alpine:3"\n  nodes:\n    a:\n      image: n24l/ceos:4.35.0F\n    b:\n      image: n24l/ceos:4.35.0F # same\n    c:\n      image: "{{ templated }}"\n')),['alpine:3','n24l/ceos:4.35.0F']);
 assert.deepEqual(plain(c.builderYamlImages('')),[]);
});
test('the image notice: concise text naming only problems, tone by severity, errors outrank successes',()=>{
 const c=load(),plain=v=>JSON.parse(JSON.stringify(v));
 const ok=r=>({reference:r,local:true,registry:'skipped'});
 const fine=c.builderImageSummary([ok('a:1'),ok('b:1'),{reference:'c:1',local:false,registry:'found'},ok('d:1'),ok('e:1')]);
 assert.deepEqual(plain(fine),{text:'Images checked: all 5 available on the VM or pullable from their registry.',tone:'info',warn:false});
 assert.doesNotMatch(fine.text,/a:1/,'no list of successes');
 const bad=c.builderImageSummary([ok('n24l/ceos:4.35.0F'),{reference:'vrnetlab/cisco_xrv9k:24.3.1',local:false,registry:'not-found'},{reference:'r.example/z:1',local:false,registry:'unreachable'}]);
 assert.equal(bad.tone,'error');assert.match(bad.text,/^Error: vrnetlab\/cisco_xrv9k:24\.3\.1 is not on the VM and no registry offers it/);assert.doesNotMatch(bad.text,/ceos/,'a good image is not named');assert.match(bad.text,/Also: r\.example\/z:1: its registry did not answer/);assert.match(c.builderImageSummary([{reference:'a:1',local:false,registry:'not-found'},{reference:'b:1',local:false,registry:'not-found'}]).text,/^Error: a:1, b:1 are not on the VM and no registry offers them/);
 assert.equal(c.builderImageSummary([{reference:'bad name',local:false,registry:'invalid'}]).tone,'error');
 const warn=c.builderImageSummary([ok('a:1'),{reference:'r.example/z:1',local:false,registry:'unreachable'}]);assert.equal(warn.tone,'warn');assert.match(warn.text,/^Warning: r\.example\/z:1/);
 assert.equal(c.builderImageSummary([{reference:'q:1',local:false,registry:'unknown'}]).tone,'warn');
 assert.equal(c.builderImageSummary([ok('a:1')]).text,'Image checked: available on the VM or pullable from its registry.');
 assert.deepEqual(plain(c.builderImageSummary([])),{text:'',tone:'info',warn:false});
 const none=c.builderImageSummary([{reference:'a:1',available:false,local:null,registry:'skipped'}]);assert.equal(none.tone,'warn');assert.match(none.text,/^Warning: images not checked\. This VM has no Docker client/);
 const html=read('lab-builder.html');assert.match(html,/id="builder-images"[^>]*hidden/,'the notice is on the page, empty until the manager answers');
 assert.match(html,/<button type="button"[^>]*id="builder-images-dismiss"[^>]*aria-label="[^"]+"/,'a real button dismisses it');
});
test('the image notice: stale answers are dropped, a dismissed result stays dismissed, a different result shows, a failed request is shown',async()=>{
 const c=load(),plain=v=>JSON.parse(JSON.stringify(v)),run=s=>vm.runInContext(s,c);
 const answer=images=>({images});let pending=null;
 c.json=()=>new Promise(r=>{pending=r;});
 run("builderDraft={id:'d1',yaml:''}");
 // stale seq: a second check started while the first was on its way
 let first=c.builderImageCheck(['a:1']);const resolveFirst=pending;let second=c.builderImageCheck(['a:1']);const resolveSecond=pending;
 resolveFirst(answer([{reference:'a:1',local:true,registry:'skipped'}]));assert.equal(await first,null,'the older answer is dropped');
 resolveSecond(answer([{reference:'a:1',local:false,registry:'not-found'}]));const r2=await second;assert.equal(r2.summary.tone,'error');
 // draft switch
 let third=c.builderImageCheck(['a:1']);run("builderDraft={id:'d2',yaml:''}");pending(answer([{reference:'a:1',local:true,registry:'skipped'}]));assert.equal(await third,null,'the answer of another draft is dropped');
 // dismissal is keyed by draft + refs + tone + text
 run("builderDraft={id:'d1',yaml:''}");
 const asked=async images=>{const p=c.builderImageCheck(['a:1']);pending(answer(images));return p;};
 const bad=await asked([{reference:'a:1',local:false,registry:'not-found'}]);
 run("builderImageDismissed="+JSON.stringify(bad.key));
 const same=await asked([{reference:'a:1',local:false,registry:'not-found'}]);assert.equal(same.key,bad.key,'the same answer has the same key (stays dismissed)');
 const other=await asked([{reference:'a:1',local:false,registry:'unreachable'}]);assert.notEqual(other.key,bad.key,'a different result is a new notice');
 run("builderDraft={id:'d9',yaml:''}");assert.notEqual((await asked([{reference:'a:1',local:false,registry:'not-found'}])).key,bad.key,'another draft is not covered by the dismissal');
 // an error in the batch is not masked by the successes beside it
 run("builderDraft={id:'d1',yaml:''}");
 const mixed=await asked([{reference:'a:1',local:true,registry:'skipped'},{reference:'b:1',local:false,registry:'invalid'},{reference:'c:1',local:true,registry:'skipped'}]);assert.equal(mixed.summary.tone,'error');
 // the request itself failing is shown
 c.json=()=>Promise.reject(new Error('The manager did not answer.'));const failed=await c.builderImageCheck(['a:1']);
 assert.equal(failed.summary.tone,'warn');assert.match(failed.summary.text,/^Warning: the images could not be checked \(The manager did not answer\.\)/);
 assert.equal(await c.builderImageCheck([]),null,'nothing to check');
});
test('a draft edited in another tab is never overwritten silently',()=>{
 const c=load(),s=storage();
 const first=c.draftWrite(s,{id:'new:lab',name:'lab',yaml:'name: lab\n',annotations:''},undefined);assert.ok(first.revision);
 const mine=c.draftWrite(s,{...first,yaml:'name: lab\n# mine\n'},first.revision);assert.notEqual(mine.revision,first.revision);
 assert.throws(()=>c.draftWrite(s,{...first,yaml:'name: lab\n# the other tab\n'},first.revision),/another tab/);
 assert.equal(c.draftRead(s,'new:lab').yaml,'name: lab\n# mine\n');
 assert.deepEqual(Array.from(c.draftList(s),d=>d.id),['new:lab']);c.draftDelete(s,'new:lab');assert.equal(c.draftRead(s,'new:lab'),null);
 s.setItem('clab-builder:draft:broken','{not json');assert.equal(c.draftRead(s,'broken'),null);assert.equal(c.draftList(s).length,0);
 const full={...s,getItem:()=>null,setItem(){throw new Error('quota');}};assert.throws(()=>c.draftWrite(full,{id:'x',name:'x',yaml:'a'},undefined),e=>e.code==='storage'&&/could not store/.test(e.message));
 // A draft deleted and made again (another tab, an import) never repeats a revision, so the tab that
 // still holds the old one is stopped instead of overwriting the new draft.
 const old=c.draftWrite(s,{id:'new:again',name:'again',yaml:'A1'},undefined);c.draftDelete(s,'new:again');c.draftWrite(s,{id:'new:again',name:'again',yaml:'B1'},undefined);
 assert.throws(()=>c.draftWrite(s,{...old,yaml:'A2'},old.revision),e=>e.code==='conflict');assert.equal(c.draftRead(s,'new:again').yaml,'B1');
});
test('a downloaded draft comes back unchanged and other files are refused',()=>{
 const c=load(),draft={id:'new:lab',name:'lab',yaml:'name: lab\ntopology:\n  nodes: {}\n',annotations:'{"nodeAnnotations":[]}',vm:{path:'/x'}};
 assert.deepEqual({...c.draftImport(c.draftExport(draft))},{name:'lab',yaml:draft.yaml,annotations:draft.annotations});
 for(const bad of ['','[]','{"format":"other"}',JSON.stringify({format:'clab-manager-lab-draft',yaml:'a',name:'bad name'}),JSON.stringify({format:'clab-manager-lab-draft',name:'lab',yaml:'x'.repeat(512*1024+1)})])assert.throws(()=>c.draftImport(bad),/draft/);
});
test('the status line tells a draft from a saved lab and from unsaved changes',()=>{
 const c=load(),vmCopy={path:'/srv/labs/lab/lab.clab.yml',yaml:'a',annotations:'b'};
 assert.match(c.draftStatus({yaml:'a'}).text,/not on the VM yet/);
 assert.equal(c.draftStatus({yaml:'a',annotations:'b',vm:vmCopy}).text,'Saved on the VM');assert.equal(c.draftStatus({yaml:'a',annotations:'b',vm:vmCopy}).detail,vmCopy.path);
 assert.match(c.draftStatus({yaml:'changed',annotations:'b',vm:vmCopy}).text,/not saved to the VM yet/);assert.match(c.draftStatus({yaml:'a',annotations:'moved',vm:vmCopy}).text,/not saved/);
 // the pill next to "Lab builder" carries this text; it is empty only while no draft is open, never for a real state
 assert.equal(c.draftStatus(null).text,'');assert.equal(c.draftStatus(null).tone,'neutral');
 for(const s of [c.draftStatus({yaml:'a'}),c.draftStatus({yaml:'a'},{yaml:'a',annotations:''}),c.draftStatus({yaml:'a',annotations:'b',vm:vmCopy}),c.draftStatus({yaml:'changed',annotations:'b',vm:vmCopy})])assert.notEqual(s.text,'');
});
test('the status pill is hidden with no text while no draft is open, and shown with its state otherwise',()=>{
 const p=page({answer:()=>({})});
 p.run('builderRenderBar()');
 assert.equal(p.el('builder-status').hidden,true);assert.equal(p.el('builder-status').textContent,'');
 p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);builderRenderBar();`);
 assert.equal(p.el('builder-status').hidden,false);assert.match(p.el('builder-status').textContent,/not on the VM yet/);
 assert.ok(read('lab-builder.html').includes('id="builder-status" role="status" hidden'),'hidden by default in the markup too, before the page\'s own script runs');
});
test('the first save publishes a new folder; later saves revise the versions that were opened',async()=>{
 const c=load(),hash=async t=>'sha:'+t;
 const first=await c.builderSaveRequest({root:'/srv/labs',yaml:'Y',annotations:' '},hash);
 assert.deepEqual(JSON.parse(JSON.stringify(first)),{action:'publish',options:{root:'/srv/labs',text:'Y'}});
 const again=await c.builderSaveRequest({root:'/srv/labs',yaml:'Y2',annotations:'A2',vm:{path:'/srv/labs/l/l.clab.yml',yaml:'Y',annotations:''}},hash);
 assert.deepEqual(JSON.parse(JSON.stringify(again)),{action:'revise',path:'/srv/labs/l/l.clab.yml',options:{text:'Y2',annotations:'A2',base:{yaml:'sha:Y',annotations:''}}});
 assert.equal(await c.builderHash('abc'),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
});
// --- the page itself, over a fake document: the behaviours a student depends on when something goes wrong ---
function page(options={}){
 const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,{id,textContent:'',hidden:false,disabled:false,title:'',className:'',value:'',focus(){},click(){},addEventListener(){},append(){},querySelector:()=>null,querySelectorAll:()=>[]});return elements.get(id);};
 const store=options.storage||storage(),calls=[],toasts=[],timers=[],forms=[];
 const context=vm.createContext({console,crypto:options.crypto||require('node:crypto').webcrypto,TextEncoder,URLSearchParams,FormData,Blob,setTimeout:fn=>timers.push(fn),clearTimeout(){},confirm:()=>options.confirm??true,alert(){},
  window:{localStorage:store},location:{hash:'',reload(){calls.push('reload');}},document:{title:'',getElementById:el,querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>el('made'),body:{append(){}}},
  fetch:async(url,init)=>{const body=init?.body&&typeof init.body==='string'?JSON.parse(init.body):null;calls.push([url,body]);if(init?.body&&typeof init.body!=='string'&&typeof init.body.entries==='function')forms.push([url,Object.fromEntries([...init.body.entries()].map(([k,v])=>[k,typeof v==='string'?v:'<file>']))]);const answer=await options.answer(url,body);if(answer instanceof Error)throw new TypeError('network');return {ok:!answer.refused,status:answer.status,json:async()=>answer.refused?{detail:answer.refused}:answer};}});
 vm.runInContext(read('lab-builder-page.js'),context);vm.runInContext(read('operations.js'),context);
 // operations.js dialogs need a real DOM; the page logic under test only needs to know one was asked for
 vm.runInContext("opDialog=(id,title,body)=>{const dialog={close(){},querySelector:()=>null,querySelectorAll:()=>[]};dialogs.push({id,title,body,dialog});return dialog;};notify=m=>toasts.push(m);",Object.assign(context,{dialogs:[],toasts}));
 return {c:context,el,store,calls,toasts,timers,forms,run:code=>vm.runInContext(code,context)};
}
const VM_PATH='/srv/labs/lab1/lab1.clab.yml',TOPOLOGY='name: lab1\ntopology:\n  nodes:\n    r1:\n      kind: linux\n';
test('the lab name is what the topology says: a new draft follows a rename, a saved lab is told to set it back',()=>{
 const c=load();
 assert.equal(c.builderYamlName('name: lab1\n'),'lab1');assert.equal(c.builderYamlName('# c\nname: "quoted"  # note\ntopology: {}\n'),'quoted');assert.equal(c.builderYamlName('topology: {}\n'),'');
 assert.equal(c.builderNameProblem({yaml:'name: lab1\n'}),'');
 assert.match(c.builderNameProblem({yaml:'name: bad name\n'}),/cannot be used/);assert.match(c.builderNameProblem({yaml:'topology: {}\n'}),/cannot be used/);
 assert.match(c.builderNameProblem({yaml:'name: other\n',vm:{yaml:'name: lab1\n'}}),/keeps its name: set it back to lab1/);assert.equal(c.builderNameProblem({yaml:'name: lab1\n# edit\n',vm:{yaml:'name: lab1\n'}}),'');
 const p=page({answer:()=>({})});p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);builderCaps={actions:{publish:{available:true},revise:{available:true}}};`);
 p.run(`builderPage.persist(${JSON.stringify(TOPOLOGY.replace('lab1','lab2'))},'')`);
 assert.equal(p.run('builderDraft.name'),'lab2');assert.equal(p.el('builder-name').textContent,'lab2');assert.equal(p.run('builderVmPath(builderDraft)'),'/srv/labs/lab2/lab2.clab.yml');assert.equal(p.el('builder-save').disabled,false);
 p.run(`builderPage.persist(${JSON.stringify(TOPOLOGY.replace('lab1','no good'))},'')`);
 assert.equal(p.run('builderDraft.name'),'lab2');assert.equal(p.el('builder-save').disabled,true);assert.match(p.el('builder-note-text').textContent,/cannot be used/);assert.equal(p.el('builder-note').hidden,false);
});
test('a change the browser could not store is never shown as kept, and Download draft still has it',()=>{
 const base=storage(),full={...base,getItem:k=>base.getItem(k),setItem(k,v){if(full.refuse)throw new Error('quota');base.setItem(k,v);},get length(){return base.length;}};
 const p=page({storage:full,answer:()=>({})});p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);builderCaps={actions:{publish:{available:true}}};builderRenderBar();`);
 assert.equal(p.el('builder-save').disabled,false);full.refuse=true;const edited=TOPOLOGY+'    r2:\n      kind: linux\n';
 assert.throws(()=>p.run(`builderPage.persist(${JSON.stringify(edited)},'')`),e=>e.code==='storage');
 assert.equal(p.el('builder-status').textContent,'Last change not kept in this browser');assert.match(p.el('builder-status').className,/danger/);assert.equal(p.el('builder-save').disabled,true);
 assert.equal(JSON.parse(p.run('draftExport({...builderDraft,...(builderUnstored||{})})')).yaml,edited,'the download must carry the newest work');
 // room again: the same texts are stored and the page restarts from the stored draft
 full.refuse=false;p.run('builderStoreAgain()');assert.equal(p.c.draftRead(base,'new:lab1').yaml,edited);assert.ok(p.calls.includes('reload'));assert.equal(p.run('builderUnstored'),null);
});
test('a save that already reached the VM marks the draft saved instead of leaving it a draft for ever',()=>{
 const p=page({answer:()=>({labs:[],jobs:[],operations:[]})});p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},saving:true},undefined);builderPending={yaml:builderDraft.yaml,annotations:'',action:'publish'};`);
 p.run(`opJobDone({action:'publish',status:'succeeded',result:{already_published:true}})`);
 assert.equal(p.run('builderDraft.vm.path'),VM_PATH);assert.equal(p.run('builderDraft.saving'),undefined);assert.equal(p.el('builder-status').textContent,'Saved on the VM');assert.equal(p.run('builderPending'),null);
 // a failed job leaves the draft a draft and clears the marker
 p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab3',name:'lab3',root:'/srv/labs',yaml:'name: lab3\\n',saving:true},undefined);builderPending={yaml:builderDraft.yaml,annotations:'',action:'publish'};opJobDone({action:'publish',status:'failed',result:{}})`);
 assert.equal(p.run('builderDraft.vm'),undefined);assert.equal(p.run('builderDraft.saving'),undefined);
});
test('a page that never heard how its save ended asks the VM on the next visit',async()=>{
 const p=page({answer:(url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:TOPOLOGY,sha256:'h1'}:{refused:'The selected VM path no longer exists.'}):{}});
 p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},saving:true},undefined);`);await p.run('builderReconcile()');
 assert.equal(p.run('builderDraft.vm.path'),VM_PATH);assert.equal(p.run('builderDraft.vm.hash'),'h1','the hash the VM gave is the base of the next revision');assert.equal(p.el('builder-status').textContent,'Saved on the VM');
 // a different file on the VM is not adopted silently; the marker is cleared so the VM is not asked again
 p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1b',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY+'# newer\n')},saving:true},undefined);`);await p.run('builderReconcile()');
 assert.equal(p.run('builderDraft.vm'),undefined);assert.equal(p.run('builderDraft.saving'),undefined);const reads=p.calls.length;await p.run('builderReconcile()');assert.equal(p.calls.length,reads);
 // the student kept editing after the save that got lost: what was sent is on the VM, so this is a saved lab with newer changes
 const sent=await p.c.builderHash(TOPOLOGY);p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1c',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY+'# after the save\n')},saving:{yaml:'${sent}',annotations:''}},undefined);`);await p.run('builderReconcile()');
 assert.equal(p.run('builderDraft.vm.yaml'),TOPOLOGY);assert.match(p.el('builder-status').textContent,/Changes not saved to the VM yet/);
 // a VM that cannot be asked right now is not a missing file: the question is kept for the next visit
 const down=page({answer:url=>url.endsWith('/operations/read')?{refused:'Cannot reach the VM operations helper. Check setup and SSH settings.'}:{}});
 down.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},saving:true},undefined);`);await down.run('builderReconcile()');
 assert.equal(down.run('builderDraft.saving'),true);assert.equal(down.run('builderDraft.vm'),undefined);
});
test('saving again works on a page opened as http://<VM address>, where the browser offers no crypto.subtle',async()=>{
 const c=load();
 for(const text of ['','abc','name: lab1\n','é'.repeat(300),'x'.repeat(55),'x'.repeat(56),'x'.repeat(64),'x'.repeat(100000)])assert.equal(c.builderSha256(new TextEncoder().encode(text)),require('node:crypto').createHash('sha256').update(text).digest('hex'),'length '+text.length);
 const p=page({crypto:{},answer:()=>({})});const request=await p.run(`builderSaveRequest({yaml:'Y2',annotations:'',vm:{path:'${VM_PATH}',yaml:'abc',annotations:''}})`);
 assert.equal(request.options.base.yaml,'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
});
test('while the problem overlay is up nothing is stored, whatever the editor still does',()=>{
 const p=page({answer:()=>({})});p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);builderProblem('This draft was changed in another tab.','conflict');`);
 assert.equal(p.el('root').inert,true);assert.throws(()=>p.run(`builderPage.persist(${JSON.stringify('name: lab1\ntopology:\n  nodes: {}\n')},'')`),e=>e.code==='conflict');
 assert.equal(p.c.draftRead(p.store,'new:lab1').yaml,TOPOLOGY,'the stored draft is untouched');assert.equal(p.el('builder-save').disabled,true);assert.match(p.run('builderUnstored.yaml'),/nodes: \{\}/,'and the download still has what the editor shows');
});
test('a refused save says what was kept, and offers the differences when the VM holds another version',async()=>{
 const onVm='name: lab1\ntopology:\n  nodes:\n    old: {kind: linux}\n';
 const p=page({answer:(url,body)=>url.endsWith('/operations/preview')?{refused:'A lab folder with this name already exists on the VM: /srv/labs/lab1. Choose another lab name.'}:url.endsWith('/operations/read')?(body.path===VM_PATH?{text:onVm,sha256:'raw-hash'}:{refused:'The selected VM path no longer exists.'}):{}});
 p.run(`builderCaps={actions:{publish:{available:true},revise:{available:true}}};builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);`);await p.run('builderSave()');
 const shown=p.c.dialogs.at(-1);assert.equal(shown.id,'builder-save-problem');assert.match(shown.body,/Nothing on the VM was changed\. Your draft is kept/);assert.match(shown.body,/Review the differences/);assert.match(shown.body,/Open the VM version/);
 assert.equal(p.run('builderDraft.vm'),undefined,'nothing is adopted before the student chooses');assert.equal(p.run('builderPending'),null);
 // Review the differences: the draft descends from the VM version (with the VM's hash) and the next request is a revision
 const before=p.calls.length;await p.el('builder-save-problem-compare').onclick();assert.equal(p.run('builderDraft.vm.yaml'),onVm);assert.equal(p.run('builderDraft.vm.hash'),'raw-hash');
 const sent=p.calls.slice(before).find(c=>Array.isArray(c)&&c[0].endsWith('/operations/preview'));assert.equal(sent[1].action,'revise');assert.equal(sent[1].options.base.yaml,'raw-hash');
 // a folder that carries another lab's name is never made the base of this draft
 const o=page({answer:(url,body)=>url.endsWith('/operations/preview')?{refused:'exists'}:url.endsWith('/operations/read')?(body.path===VM_PATH?{text:onVm.replace('name: lab1','name: somebody-else'),sha256:'x'}:{refused:'The selected VM path no longer exists.'}):{}});
 o.run(`builderCaps={actions:{publish:{available:true}}};builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);`);await o.run('builderSave()');
 assert.match(o.c.dialogs.at(-1).body,/belongs to a lab named somebody-else/);assert.doesNotMatch(o.c.dialogs.at(-1).body,/Review the differences/);
 // the same refusal with the same content on the VM is simply a saved lab
 const q=page({answer:(url,body)=>url.endsWith('/operations/preview')?{refused:'exists'}:url.endsWith('/operations/read')?(body.path===VM_PATH?{text:TOPOLOGY,sha256:'h'}:{refused:'The selected VM path no longer exists.'}):{}});
 q.run(`builderCaps={actions:{publish:{available:true}}};builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);`);await q.run('builderSave()');
 assert.equal(q.run('builderDraft.vm.path'),VM_PATH);assert.match(q.toasts.at(-1),/already on the VM/);
 // an unreachable manager is not mistaken for a missing file
 const r=page({answer:()=>new Error('down')});r.run(`builderCaps={actions:{publish:{available:true}}};builderDraft={id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}};builderDraft=draftWrite(builderStore,builderDraft,undefined);`);await r.run('builderSave()');
 assert.match(r.c.dialogs.at(-1).body,/Your draft is kept/);assert.doesNotMatch(r.c.dialogs.at(-1).body,/Review the differences/);
});
test('a revision sends the hashes the VM gave for the files it read (a byte-order mark is not in the text)',async()=>{
 const c=load(),hash=async t=>'text:'+t;
 const opened=await c.builderSaveRequest({yaml:'Y2',annotations:'A2',vm:{path:VM_PATH,yaml:'Y',annotations:'A',hash:'raw-yaml',layoutHash:'raw-layout'}},hash);
 assert.deepEqual(JSON.parse(JSON.stringify(opened.options.base)),{yaml:'raw-yaml',annotations:'raw-layout'});
 const own=await c.builderSaveRequest({yaml:'Y2',annotations:'A2',vm:{path:VM_PATH,yaml:'Y',annotations:'A'}},hash);assert.deepEqual(JSON.parse(JSON.stringify(own.options.base)),{yaml:'text:Y',annotations:'text:A'});
});
test('one draft per lab: opening the file a draft was saved to continues that draft',async()=>{
 const p=page({answer:(url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:TOPOLOGY,sha256:'h'}:{refused:'The selected VM path no longer exists.'}):url.endsWith('/operations/parse-yaml')?{name:'lab1'}:{}});
 p.run(`draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY+'# not saved yet\n')},vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:''}},undefined);`);
 const opened=await p.run(`builderOpenFromVm('${VM_PATH}')`);assert.equal(opened.id,'new:lab1');assert.match(opened.yaml,/not saved yet/);assert.equal(p.c.draftList(p.store).length,1);
 assert.equal(opened.vm.hash,'h','the base takes the hash the VM gave');
 // two drafts of one file left by an older version, and the VM moved on: opening leaves exactly one draft, the VM version
 const q=page({confirm:true,answer:(url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:TOPOLOGY+'# changed on the VM\n',sha256:'h2'}:{refused:'The selected VM path no longer exists.'}):url.endsWith('/operations/parse-yaml')?{name:'lab1'}:{}});
 q.run(`for(const id of ['vm:${VM_PATH}','new:lab1'])draftWrite(builderStore,{id,name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:''}},undefined);`);
 const fresh=await q.run(`builderOpenFromVm('${VM_PATH}')`);assert.match(fresh.yaml,/changed on the VM/);assert.equal(q.c.draftList(q.store).length,1);
 // a read that fails is an error with its reason, never an empty layout or a crash
 const r=page({answer:url=>url.endsWith('/operations/read')?{refused:'Cannot reach the VM operations helper. Check setup and SSH settings.'}:{}});await assert.rejects(r.run(`builderOpenFromVm('${VM_PATH}')`),/Cannot reach the VM/);
});
test('a downloaded draft is checked before it becomes a draft, and takes the name its topology carries',async()=>{
 const file=(name,yaml,annotations='')=>JSON.stringify({format:'clab-manager-lab-draft',version:1,name,yaml,annotations});
 const p=page({answer:(url,body)=>url.endsWith('/operations/parse-yaml')?(body.options.text.includes('[unclosed')?{refused:'Enter a valid literal Containerlab topology.'}:{name:'lab1'}):{}});
 const made=await p.run(`builderImportDraft(${JSON.stringify(file('another-name',TOPOLOGY,'{not json'))},'/srv/labs')`);
 assert.equal(made.draft.name,'lab1');assert.equal(p.run("builderDraftId('lab1')"),'new:lab1');assert.equal(made.draft.annotations,'');assert.match(made.note,/layout/);
 await assert.rejects(p.run(`builderImportDraft(${JSON.stringify(file('lab1','name: lab1\ntopology:\n  nodes:\n   - [unclosed\n'))},'/srv/labs')`),/cannot be read/);
 // the manager being away does not stop a student from opening their own file
 const offline=page({answer:()=>new Error('down')});assert.equal((await offline.run(`builderImportDraft(${JSON.stringify(file('x',TOPOLOGY))},'/srv/labs')`)).draft.name,'lab1');
});
test('a dropped topology/map pair is paired order-independently, and bad pairs are refused with the reason',()=>{
 const c=load(),f=(name,text)=>({name,size:text.length,text});
 const a=c.builderDropPair([f('lab.clab.yml','name: t\ntopology: {}\n'),f('lab.clab.yml.annotations.json','{}')]);
 assert.deepEqual(JSON.parse(JSON.stringify(a)),{yaml:'name: t\ntopology: {}\n',annotations:'{}',notice:''});
 // order independent: the map first, then the topology, gives the same pair
 assert.deepEqual(JSON.parse(JSON.stringify(c.builderDropPair([f('lab.clab.yml.annotations.json','{}'),f('lab.clab.yml','name: t\ntopology: {}\n')]))),JSON.parse(JSON.stringify(a)));
 // topology-only works: no map, no notice
 const onlyTopology=c.builderDropPair([f('lab.yaml','name: t\ntopology: {}\n')]);assert.deepEqual(JSON.parse(JSON.stringify(onlyTopology)),{yaml:'name: t\ntopology: {}\n',annotations:'',notice:''});
 // a map whose base name differs is used anyway, with a notice
 const mismatched=c.builderDropPair([f('lab.clab.yml','name: t\ntopology: {}\n'),f('other.annotations.json','{}')]);assert.match(mismatched.notice,/does not match/);
 // two topologies, no files, an unrelated file, two maps
 assert.throws(()=>c.builderDropPair([f('a.clab.yml','x'),f('b.clab.yml','y')]),/Drop one topology file at a time/);
 assert.throws(()=>c.builderDropPair([]),/Drop a lab file/);
 assert.throws(()=>c.builderDropPair([f('readme.txt','x')]),/containerlab topology file/);
 assert.throws(()=>c.builderDropPair([f('a.clab.yml','x'),f('a.annotations.json','{}'),f('b.annotations.json','{}')]),/up to two files/);
 // oversize: either file over 1 MiB is refused, named
 const big={name:'a.clab.yml',size:1024*1024+1,text:'x'};assert.throws(()=>c.builderDropPair([big]),/"a\.clab\.yml" is larger than 1 MiB/);
 // malformed JSON, and JSON that is not a single object, are refused with the parser's reason — unlike a
 // downloaded draft's annotations (builderImportDraft), a dropped pair's map is checked before it opens
 assert.throws(()=>c.builderDropPair([f('a.clab.yml','x'),f('a.annotations.json','not json')]),/not valid JSON/);
 assert.throws(()=>c.builderDropPair([f('a.clab.yml','x'),f('a.annotations.json','[1,2]')]),/one JSON object/);
});
test('dropping a lab file replaces the open draft only after a confirm when it has unsaved work, and needs none on the welcome page',async()=>{
 const file=(name,text)=>({name,size:text.length,text:async()=>text});
 const p=page({answer:(url,body)=>url.endsWith('/operations/parse-yaml')?{name:'lab2'}:{}});
 p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:''}},undefined);builderPage.persist(${JSON.stringify(TOPOLOGY+'# edit\n')},'')`);
 let asked=0;p.c.confirm=()=>{asked++;return false;};
 p.c.dropped=[file('lab2.clab.yml','name: lab2\ntopology:\n  nodes: {}\n')];
 await p.run('builderDropOpen(dropped)');
 assert.equal(asked,1,'a draft with unsaved work is never replaced without asking');
 assert.equal(p.c.draftList(p.store).some(d=>d.name==='lab2'),false,'declined: nothing new is written');
 p.c.confirm=()=>true;await p.run('builderDropOpen(dropped)');
 const made=p.c.draftList(p.store).find(d=>d.name==='lab2');
 assert.ok(made,'accepted: the dropped pair becomes a draft, exactly like an imported one');
 assert.equal(made.yaml,'name: lab2\ntopology:\n  nodes: {}\n');assert.equal(made.annotations,'');
 assert.ok(p.calls.includes('reload'),'the result opens in the editor like opening any other draft');
 // the welcome page (no draft open) has nothing to lose: dropping there needs no confirmation
 const q=page({answer:(url,body)=>url.endsWith('/operations/parse-yaml')?{name:'fresh'}:{}});
 let asked2=0;q.c.confirm=()=>{asked2++;return true;};
 q.c.dropped=[file('fresh.clab.yml','name: fresh\ntopology:\n  nodes: {}\n')];
 await q.run('builderDropOpen(dropped)');
 assert.equal(asked2,0);assert.ok(q.c.draftList(q.store).some(d=>d.name==='fresh'));
});
test('a dropped topology the manager cannot read is refused with the reason, and an unreachable manager does not stop it opening',async()=>{
 const file=(name,text)=>({name,size:text.length,text:async()=>text});
 const bad='name: lab1\ntopology:\n  nodes:\n   - [unclosed\n';
 const p=page({answer:(url,body)=>url.endsWith('/operations/parse-yaml')?{refused:'Enter a valid literal Containerlab topology.'}:{}});
 p.c.dropped=[file('lab1.clab.yml',bad)];
 await assert.rejects(p.run('builderDropOpen(dropped)'),/cannot be read/);
 const offline=page({answer:()=>new Error('down')});offline.c.dropped=[file('lab1.clab.yml',TOPOLOGY)];
 await offline.run('builderDropOpen(dropped)');assert.ok(offline.c.draftList(offline.store).some(d=>d.name==='lab1'));
});
test('Save is never off without the reason being on the page',()=>{
 const p=page({answer:()=>({})});p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);builderCapsError='The VM connection is not configured.';builderRenderBar();`);
 assert.equal(p.el('builder-save').disabled,true);assert.match(p.el('builder-note-text').textContent,/not available right now: The VM connection is not configured\./);assert.equal(p.el('builder-note').hidden,false);assert.equal(p.el('builder-note-retry').hidden,false);assert.equal(p.el('builder-save').title,p.el('builder-note-text').textContent);
 p.run(`builderCapsError='';builderCaps=null;builderRenderBar();`);assert.equal(p.el('builder-save').disabled,true);assert.match(p.el('builder-save').title,/Checking whether saving/);
 p.run(`builderCapsError='';builderCaps={actions:{publish:{available:false}}};builderRenderBar();`);assert.match(p.el('builder-note-text').textContent,/helper programs are older/);
 p.run(`builderCaps={actions:{publish:{available:true}}};builderRenderBar();`);assert.equal(p.el('builder-save').disabled,false);assert.equal(p.el('builder-note').hidden,true);
 // a lab that is deployed: said when the draft opens, not only when the save is refused
 p.run(`state.labs=[{id:'1',name:'lab1',vm_project_path:'${VM_PATH}',deployment:{status:'Running'}}];builderCaps.actions.revise={available:true};builderDraft=draftWrite(builderStore,{...builderDraft,vm:{path:'${VM_PATH}',yaml:builderDraft.yaml,annotations:''}},builderDraft.revision);builderRenderBar();`);
 assert.equal(p.el('builder-note-text').textContent,'This lab is running: saving changes the file and the map, not the devices; applying is a separate step.');assert.doesNotMatch(p.el('builder-note-text').textContent,/destroy/i);assert.equal(p.el('builder-save').disabled,false);
});
test('a browser that refuses storage still builds: the draft lives in the tab and the page says so',()=>{
 const p=page({answer:()=>({})});Object.defineProperty(p.c.window,'localStorage',{get(){throw new Error('denied');}});
 const q=vm.createContext({...p.c,window:p.c.window});vm.runInContext(read('lab-builder-page.js'),q);
 assert.match(vm.runInContext('builderStorageNote',q),/this tab only/);vm.runInContext("draftWrite(builderStore,{id:'new:t',name:'t',yaml:'name: t\\n'},undefined)",q);assert.equal(vm.runInContext("draftList(builderStore).length",q),1);
});
test('a renamed draft is known by its new name everywhere: its path, the duplicate check, a draft left by an older version',()=>{
 const p=page({answer:()=>({})});p.run(`builderDraft=draftWrite(builderStore,{id:'new:a',name:'a',root:'/srv/labs',yaml:'name: a\\n'},undefined);builderPage.persist('name: b\\ntopology: {}\\n','');`);
 assert.equal(p.run('builderVmPath(builderDraft)'),'/srv/labs/b/b.clab.yml');assert.equal(p.run("builderDraftId('a')").startsWith('new:a:'),true,'the first id is taken, another one is made');assert.equal(p.run("builderDraftId('c')"),'new:c');
 assert.deepEqual(Array.from(p.c.draftList(p.store),d=>d.name),['b']);
 // a draft that an older version left renamed in its topology only is put right when it opens
 p.run(`builderUse({id:'new:old',name:'old',root:'/srv/labs',yaml:'name: newer\\n',revision:'r'})`);assert.equal(p.run('builderDraft.name'),'newer');
});
test('the outcome of a save reaches the draft when its dialog was closed, and a second save waits for the first',async()=>{
 let status='running';const p=page({answer:url=>/\/operations\/job1$/.test(url)?{id:'job1',action:'publish',status,result:status==='succeeded'?{published_path:VM_PATH}:{}}:url.endsWith('/state')?{labs:[],jobs:[],operations:[]}:{}});
 p.run(`builderCaps={actions:{publish:{available:true}}};builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);builderPending={yaml:builderDraft.yaml,annotations:'',action:'publish'};opJobStarted({id:'job1',action:'publish'});`);
 const dialog={open:true,querySelector:()=>({textContent:''}),classList:{toggle(){}},close(){}};p.run('opDialog=()=>shown');p.c.shown=dialog;
 await p.run("opShowJob('job1')");assert.equal(p.timers.length,1,'a running job is polled again');
 dialog.open=false;dialog.onclose();await p.run('builderSave()');assert.match(p.toasts.at(-1),/previous save is still running/);assert.equal(p.run('builderPending.job'),'job1');
 status='succeeded';await p.timers.pop()();assert.equal(p.run('builderDraft.vm.path'),VM_PATH);assert.equal(p.el('builder-status').textContent,'Saved on the VM');
 // the result of another job is not taken for this one
 p.run(`builderPending={yaml:'x',annotations:'',action:'publish',job:'job2'};opJobDone({id:'job1',action:'publish',status:'succeeded',result:{published_path:'/other'}})`);assert.equal(p.run('builderPending.job'),'job2');
});
// A9: the native confirm() is gone. The student chooses in a dialog; Escape (or ×) keeps both and does nothing.
async function shown(p){for(let i=0;i<100&&!p.c.dialogs.length;i++)await new Promise(done=>setImmediate(done));return p.c.dialogs.at(-1);}
test('opening the VM version never discards a draft with unsaved changes unasked, whichever draft is newer',async()=>{
 const changed=TOPOLOGY+'# changed on the VM\n',answer=(url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:changed,sha256:'h2'}:{refused:'The selected VM path no longer exists.'}):url.endsWith('/operations/parse-yaml')?{name:'lab1'}:{};
 const seed=`draftWrite(builderStore,{id:'new:lab1:x',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY+'# my work\n')},vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:''}},undefined);draftWrite(builderStore,{id:'vm:${VM_PATH}',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:''}},undefined);`;
 let asked=0,focused='';const keep=page({answer});keep.c.confirm=()=>{asked++;return false;};keep.run(seed);keep.el('builder-old-vm').focus=()=>{focused='vm';};keep.el('builder-old-continue').focus=()=>{focused='continue';};
 const pending=keep.run(`builderOpenFromVm('${VM_PATH}')`);const dialog=await shown(keep);
 assert.equal(dialog.id,'builder-old-draft');assert.equal(asked,0,'no native confirm');
 assert.match(dialog.body,/Start from the VM version/);assert.match(dialog.body,/Continue my draft \(from /);assert.match(dialog.body,/Download my draft/);
 assert.equal(focused,'continue','Continue my draft (the non-destructive choice) is the focused default: Enter never discards the draft');
 dialog.dialog.onclose();const kept=await pending;
 assert.match(kept.yaml,/my work/,'Escape keeps both');assert.match(keep.c.draftRead(keep.store,'new:lab1:x').yaml,/my work/,'nothing was discarded');
 assert.equal(keep.run('builderContinued'),keep.c.draftRead(keep.store,'new:lab1:x').updated);
 // Continue my draft is the same, Start from the VM version removes the drafts
 const go=page({answer});go.run(seed);const p2=go.run(`builderOpenFromVm('${VM_PATH}')`);await shown(go);go.el('builder-old-continue').onclick();assert.match((await p2).yaml,/my work/);
 const drop=page({answer});drop.run(seed);const p3=drop.run(`builderOpenFromVm('${VM_PATH}')`);await shown(drop);drop.el('builder-old-vm').onclick();
 const fresh=await p3;assert.match(fresh.yaml,/changed on the VM/);assert.equal(drop.c.draftList(drop.store).length,1);assert.equal(drop.run('builderContinued'),'');
 // Download my draft offers the draft in the dialog without closing it
 const dl=page({answer});dl.run(seed);dl.run("var downloaded=[];builderDownloadDraft=d=>downloaded.push(d.id);");const p4=dl.run(`builderOpenFromVm('${VM_PATH}')`);await shown(dl);dl.el('builder-old-download').onclick();assert.deepEqual(JSON.parse(JSON.stringify(dl.run('downloaded'))),['new:lab1:x']);dl.el('builder-old-continue').onclick();await p4;
 // an unchanged VM file continues the stale draft, and says since when (no dialog)
 const same=page({answer:(url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:TOPOLOGY,sha256:'h'}:{refused:'The selected VM path no longer exists.'}):url.endsWith('/operations/parse-yaml')?{name:'lab1'}:{}});same.run(seed);
 const since=same.c.draftRead(same.store,'new:lab1:x').updated;
 const cont=await same.run(`builderOpenFromVm('${VM_PATH}')`);assert.match(cont.yaml,/my work/);assert.equal(same.c.dialogs.length,0);assert.equal(same.run('builderContinued'),since,'the date of the draft as the person left it');
 same.c.cont=cont;same.run('builderUse(cont)');assert.match(same.el('builder-line-text').textContent,/^Continuing your draft from .*; its changes are not on the VM yet\.$/);assert.equal(same.el('builder-line').hidden,false);
});
test('a save remembers where it went: a rename after a lost answer does not orphan the lab on the VM',async()=>{
 const p=page({answer:(url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:TOPOLOGY,sha256:'h1'}:{refused:'The selected VM path no longer exists.'}):{}});
 const sent=await p.c.builderHash(TOPOLOGY),renamed=TOPOLOGY.replace('name: lab1','name: lab2');
 p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab2',root:'/srv/labs',yaml:${JSON.stringify(renamed)},saving:{path:'${VM_PATH}',yaml:'${sent}',annotations:''}},undefined);`);await p.run('builderReconcile()');
 assert.equal(p.run('builderDraft.vm.path'),VM_PATH);assert.match(p.el('builder-note-text').textContent,/keeps its name: set it back to lab1/);
 // an "already saved" answer carries no path: the one the save was sent to is used, not the one the draft would get now
 p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab9',name:'lab9b',root:'/srv/labs',yaml:'name: lab9b\\n'},undefined);builderPending={yaml:'name: lab9\\n',annotations:'',action:'publish',path:'/srv/labs/lab9/lab9.clab.yml'};opJobDone({action:'publish',status:'succeeded',result:{already_published:true}})`);
 assert.equal(p.run('builderDraft.vm.path'),'/srv/labs/lab9/lab9.clab.yml');
});
test('Try to store it again also works when it was the page, not the editor, that could not store',()=>{
 const base=storage(),full={...base,getItem:k=>base.getItem(k),setItem(k,v){if(full.refuse)throw new Error('quota');base.setItem(k,v);},get length(){return base.length;}};
 const p=page({storage:full,answer:()=>({})});p.run(`builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);`);
 full.refuse=true;p.run("try{draftWrite(builderStore,{...builderDraft,saving:true},builderDraft.revision);}catch(e){builderProblem(e.message,e.code);}");assert.equal(p.el('builder-problem-retry').hidden,false);assert.equal(p.el('builder-save').disabled,true);
 p.run('builderStoreAgain()');assert.ok(!p.calls.includes('reload'),'still no room: nothing pretends otherwise');full.refuse=false;p.run('builderStoreAgain()');assert.ok(p.calls.includes('reload'));
});
test('the builder opens in the folder being browsed, else in the project folder',()=>{
 const c=load(),roots=['/etc/containerlab','/srv/containerlab-node-manager/projects'];
 assert.equal(c.opBuilderRoot('/etc/containerlab/course/week1',roots),'/etc/containerlab');assert.equal(c.opBuilderRoot('',roots),'/srv/containerlab-node-manager/projects');
 assert.equal(c.opBuilderRoot('/etc/containerlabs',roots),'/srv/containerlab-node-manager/projects');assert.equal(c.opBuilderRoot('',undefined),'/srv/containerlab-node-manager/projects');
 assert.equal(c.opBuilderUrl({root:'/srv/x y',path:''}),'/static/lab-builder.html#root=%2Fsrv%2Fx+y');
 // on the builder page a new fragment loads nothing by itself: the page is reloaded with it
 const moves=[];c.location={pathname:'/static/lab-builder.html',hash:'',assign:u=>moves.push(u),reload:()=>moves.push('reload')};c.opBuilderOpen({path:'/srv/l.clab.yml',root:''});assert.deepEqual([c.location.hash,...moves],['path=%2Fsrv%2Fl.clab.yml','reload']);
 c.location.pathname='/';moves.length=0;c.opBuilderOpen({root:'/srv'});assert.deepEqual(moves,['/static/lab-builder.html#root=%2Fsrv']);
 assert.equal(c.opLabels.publish,'Save lab to the VM');assert.match(c.opReviewCopy.revise.body(),/previous version is kept/);
});
test('a student with no labs finds the builder from the first page, and the builder page can preview a saved map',()=>{
 assert.match(read('index.html'),/<section class="home-start" id="home-start"[^]*?<a class="button primary" id="home-build" href="\/static\/lab-builder\.html">Open the lab builder<\/a>[^]*?<section id="empty"/);
 // "Deploy or add this lab…" opens the Topology file dialog on the builder page; its Preview topology needs the map renderer
 const html=read('lab-builder.html');assert.match(html,/topology-render\.js\?v=/);assert.ok(html.indexOf('lab-builder-page.js')<html.indexOf('operations.js'));
 for(const id of ['builder-note','builder-note-text','builder-note-retry','builder-hint','builder-problem-download','builder-problem-retry','builder-problem-reload','builder-templates-file'])assert.ok(html.includes('id="'+id+'"'),id);
});
// The page hides editor controls that cannot work in a builder by their test ids, because this editor
// version has no switch for them. When an editor upgrade renames one, this fails instead of the control
// silently coming back.
test('every editor control the page hides still exists in the bundled editor',()=>{
 const css=read('lab-builder.css'),ids=[...css.matchAll(/\[data-testid="([a-z-]+)"\]/g)].map(m=>m[1]);assert.ok(ids.length>=7,ids.join());
 assert.ok(ids.includes('navbar-about'),'the page hides the editor About entry (navbar-about)');
 const dir=path.join(__dirname,'../app/static/lab-builder/assets'),code=fs.readdirSync(dir).filter(f=>f.endsWith('.js')).map(f=>fs.readFileSync(path.join(dir,f),'utf8')).join('\n');
 // Context menu entries and palette tabs get their test id from a template (`context-menu-item-${id}`,
 // `panel-tab-${id}`): the bundle then holds the template and the id, not the joined string.
 for(const id of ids){const item=/^(context-menu-item|panel-tab)-(.+)$/.exec(id);assert.ok(item&&!code.includes(id)?code.includes(item[1]+'-${')&&code.includes('"'+item[2]+'"'):code.includes(id),'the bundled editor no longer has '+id);}
 assert.doesNotMatch(code,/new Function\(|\beval\(/,'the bundle must run under script-src self');
});
// The tracked build-time patches (lab-builder/patches.mjs): the committed bundle carries their outcome, and the
// pristine package (when node_modules is present) still carries every anchor exactly once. An editor upgrade
// that moves an anchor fails the build itself; this test fails when a bundle was committed without them.
test('the image is written as typed and the version is never filled in: the tracked editor patches are in the bundle',async()=>{
 const dir=path.join(__dirname,'../app/static/lab-builder/assets'),code=fs.readdirSync(dir).filter(f=>f.endsWith('.js')).map(f=>fs.readFileSync(path.join(dir,f),'utf8')).join('\n');
 assert.doesNotMatch(code,/\|\|"latest"\}/,'an empty version must not become :latest');
 assert.doesNotMatch(code,/\?\?\["latest"\]/,'an unknown image must offer no version');
 assert.doesNotMatch(code,/version:"latest"/,'an untagged or empty image must read as an empty version');
 assert.doesNotMatch(code,/\["latest"\]\)/,'a known untagged image must offer no version either');
 assert.match(code,/return ([A-Za-z_$]+)\?([A-Za-z_$]+)\?`\$\{\1\}:\$\{\2\}`:\1:""/,'the join writes image:version, or the image alone');
 // Items 5, 6 and 7: the corner options, the corner styles, the immediate apply and the map editor's device look.
 for(const label of ['"Top left"','"Top right"','"Bottom left"','"Bottom right"'])assert.ok(code.includes(label),'the Label Position select offers '+label);
 assert.match(code,/case"center":case"top-left":case"top-right":case"bottom-left":case"bottom-right":return/,'Center and a corner are known label positions');
 assert.ok(code.includes('"Center"')&&code.includes('value:"center"'),'the Label Position select offers Center');
 assert.match(code,/case"center":return\{\.\.\.[A-Za-z_$]+,top:"50%",left:"50%",maxWidth:"none",overflow:"visible",pointerEvents:"none"/,'a centred label sits over the icon and never takes a click');
 assert.ok(code.includes('rgba(0, 0, 0, 0.94)'),'the default background of a centred label is near-opaque');
 assert.ok(code.includes('"Device look"')&&code.includes('__CLAB_MAP_LOOK__'),'the map editor opens the node editor for the look');
 assert.ok(code.includes('"labelPosition","direction","icon","labelBackgroundColor"'),'the choices one clicks apply at once');
 const {PATCHES,applyPatches}=await import('../lab-builder/patches.mjs');
 assert.ok(PATCHES.length>=6);for(const p of PATCHES){assert.ok(p.file instanceof RegExp&&p.find&&p.replace&&p.why,'a patch names its file, anchor, replacement and reason');assert.notEqual(p.find,p.replace);}
 assert.throws(()=>applyPatches('chunk-TEX73Q7H.js','no anchors here'),/found 0 times/);
 const chunks=path.join(__dirname,'../lab-builder/node_modules/@containerlab/clab-ui/dist/chunks');
 if(fs.existsSync(chunks)){
  const files=fs.readdirSync(chunks);
  for(const p of PATCHES){const file=files.find(f=>p.file.test(f));assert.ok(file,'a chunk for '+p.why);const text=fs.readFileSync(path.join(chunks,file),'utf8');assert.equal(text.split(p.find).length-1,1,'anchor once in the pristine package: '+p.why);assert.ok(!text.includes(p.replace)||p.find.includes(p.replace),'the package on disk is never patched: '+p.why);}
 }else console.log('# lab-builder/node_modules absent: the anchors are checked by the build itself (npm ci && node build.mjs --check)');
});
test('the committed assets are the ones the manifest names, and the page loads only versioned entry files',()=>{
 const dir=path.join(__dirname,'../app/static/lab-builder'),manifest=JSON.parse(fs.readFileSync(path.join(dir,'manifest.json'),'utf8')),crypto=require('node:crypto');
 assert.deepEqual(fs.readdirSync(path.join(dir,'assets')).sort(),Object.keys(manifest.files).sort());
 for(const [name,sha] of Object.entries(manifest.files))assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(dir,'assets',name))).digest('hex'),sha,name);
 assert.match(fs.readFileSync(path.join(dir,'clab-ui.LICENSE'),'utf8'),/Apache License/);assert.match(fs.readFileSync(path.join(dir,'THIRD-PARTY-NOTICES.txt'),'utf8'),/elkjs .*EPL-2\.0/);
 const html=read('lab-builder.html');assert.doesNotMatch(html,/ style=|<style|\son[a-z]+=|https?:\/\//);
 for(const ref of html.matchAll(/(?:src|href)="(\/static\/[^"]+)"/g))if(!ref[1].endsWith('.svg')&&!ref[1].endsWith('.txt'))assert.match(ref[1],/\?v=\d+\.\d+\.\d+$/,ref[1]);
});
// C4: "View YAML" was a read-only dialog; the bar's YAML button now toggles the editable panel
// (lab-builder-yaml.js), which still shows exactly the draft's topology text: the newest one, unstored first.
test('the YAML button opens the editable panel, and the panel shows the draft’s own topology text',()=>{
 const html=read('lab-builder.html'),page=read('lab-builder-page.js');
 assert.ok(html.indexOf('lab-builder-page.js')<html.indexOf('lab-builder-yaml.js')&&html.indexOf('lab-builder-yaml.js')<html.indexOf('lab-builder/assets/main.js'),'the panel script loads after the page and before the editor');
 assert.match(html,/<button class="button secondary" id="builder-yaml" aria-expanded="false" aria-controls="builder-yaml-panel"[^>]*>YAML<\/button>/);
 assert.doesNotMatch(page+html,/builderYamlDialog|builder-yaml-text|View YAML/,'the read-only dialog is gone');
 assert.match(page,/\['builder-yaml',\(\)=>builderYamlPanelToggle\(\)\]/);assert.match(page,/\$\('root'\)\.insertAdjacentHTML\('afterend',builderYamlPanelMarkup\(\)\)/);
 const c=load();vm.runInContext(read('lab-builder-yaml.js'),c);const inits=[];c.builderYamlPanelInit=o=>inits.push(o);
 const editor={applyYaml(){},getYaml:()=>'',subscribe:()=>()=>{}};vm.runInContext('builderPage',c).attach(editor);
 assert.equal(inits.length,1);assert.equal(inits[0].editor,editor);
 assert.equal(inits[0].getDraftYaml(),'','no draft, no text');
 vm.runInContext("builderDraft={id:'new:lab',name:'lab',yaml:'name: lab\\ntopology: {}\\n',annotations:''};builderUnstored=null;",c);
 assert.equal(inits[0].getDraftYaml(),'name: lab\ntopology: {}\n','the text is the draft’s yaml');
 vm.runInContext("builderUnstored={yaml:'name: lab\\n# newer\\n',annotations:''};",c);
 assert.equal(inits[0].getDraftYaml(),'name: lab\n# newer\n','what the editor holds but could not store comes first');
 // The panel's open state reaches the bar button and the layout, from any way it closes.
 const attrs={},classes=new Set();c.document.getElementById=id=>id==='builder-yaml'?{setAttribute:(k,v)=>{attrs[k]=v;}}:{classList:{toggle:(n,on)=>on?classes.add(n):classes.delete(n)}};
 inits[0].onToggle(true);assert.equal(attrs['aria-expanded'],'true');assert.ok(classes.has('yaml-open'));
 inits[0].onToggle(false);assert.equal(attrs['aria-expanded'],'false');assert.ok(!classes.has('yaml-open'));
 // Escape or × with focus inside the panel hands focus back to the toggle; a close with focus elsewhere leaves it.
 const toggle={setAttribute:(k,v)=>{attrs[k]=v;},focused:0,focus(){this.focused++;}};c.document.getElementById=id=>id==='builder-yaml'?toggle:{classList:{toggle:(n,on)=>on?classes.add(n):classes.delete(n)}};
 inits[0].onToggle(false,false);assert.equal(toggle.focused,0);inits[0].onToggle(false,true);assert.equal(toggle.focused,1);inits[0].onToggle(true,true);assert.equal(toggle.focused,1,'opening never moves focus here');
 const css=read('lab-builder.css');assert.match(css,/\.builder-stage\.yaml-open #root\{right:/);assert.match(css,/\.builder-yaml-gutter,\.builder-yaml-editor\{[^}]*font:13px\/20px var\(--mono\)/,'gutter and text share their font metrics');
});
// The file drop zone listens on the whole stage. A device dragged from the editor's palette crosses the
// stage too: taking that drag over (preventDefault, dropEffect 'copy' against the palette's 'move') made
// the browser cancel the palette's drop, so no device could be dragged onto the canvas.
test('the file drop zone takes file drags only and leaves the palette’s drags to the editor',()=>{
 const c=load(),els={},tasks=[];
 c.document.getElementById=id=>els[id]||(els[id]={listeners:{},addEventListener(t,f){this.listeners[t]=f;}});
 c.opTask=(_,fn)=>tasks.push(fn);vm.runInContext('builderDropWire()',c);
 const drag=types=>({prevented:false,dataTransfer:{types,dropEffect:'move',files:types.includes('Files')?['f']:[]},preventDefault(){this.prevented=true;}});
 for(const id of ['builder-welcome','builder-stage']){
  const palette=drag(['application/reactflow','text/plain']);els[id].listeners.dragover(palette);els[id].listeners.drop(palette);
  assert.equal(palette.prevented,false,id+': a palette drag is not the page’s');assert.equal(palette.dataTransfer.dropEffect,'move');
  const file=drag(['Files']);els[id].listeners.dragover(file);assert.equal(file.prevented,true);assert.equal(file.dataTransfer.dropEffect,'copy');
  els[id].listeners.drop(file);assert.equal(file.prevented,true);
 }
 assert.equal(tasks.length,2,'only the two file drops open anything');
});

// ---- the topology check note under the bar (C08 S3, docs/parity-campaign/C08-DESIGN.md section 4.4) ---------------
const SCHEMA=JSON.parse(fs.readFileSync(path.join(__dirname,'../app/static/clab-schema/0.79.0.json'),'utf8'));
const isObj=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
function located(root){
 let n=0;
 const scalar=(v,line)=>({kind:'scalar',line,value:v,tag:v===null?'null':typeof v==='boolean'?'bool':typeof v==='number'?(Number.isInteger(v)?'int':'float'):'str'});
 const value=(v,keyLine)=>{if(isObj(v)&&Object.keys(v).length)return map(v,false);if(Array.isArray(v)&&v.length)return seq(v);if(Array.isArray(v))return {kind:'seq',line:keyLine,items:[]};if(isObj(v))return {kind:'map',line:keyLine,items:[]};return scalar(v,keyLine);};
 const map=(o,first)=>{const items=[];let line=0;Object.entries(o).forEach(([k,v],i)=>{const keyLine=i===0&&first?n:++n;if(i===0)line=keyLine;items.push({key:k,keyLine,value:value(v,keyLine)});});return {kind:'map',line,items};};
 const seq=a=>({kind:'seq',line:n+1,items:a.map(v=>{if(isObj(v)&&Object.keys(v).length){++n;return map(v,true);}++n;if(Array.isArray(v)&&v.length){const line=n,s=seq(v);s.line=line;return s;}return value(v,n);})});
 if(isObj(root)&&Object.keys(root).length)return map(root,false);
 return value(root,1);
}

const settle=()=>new Promise(r=>setImmediate(r));
const NOTE_TEXT='name: lab1\ntopology:\n  nodes:\n    a:\n      kind: arista_ceos\n      image: ceos:4.33\n      imge: x\n';
const NOTE_DOC={name:'lab1',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',imge:'x'}}}};
const CLEAN_DOC={name:'lab1',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33'}}}};
const LOOP_DOC={name:'lab1',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',stages:{create:{'wait-for':[{node:'b',stage:'healthy'}]}}},b:{kind:'linux',image:'x:1',stages:{create:{'wait-for':[{node:'a',stage:'create'}]}}}}}};
// A page with the check and the panel scripts beside it, a fake adapter handle and timers that remember their delay.
function notePage(doc=NOTE_DOC,{version='0.79.0'}={}){
 const fetched=[],p=page({answer:url=>{if(url.startsWith('/static/clab-schema/')){fetched.push(url);return SCHEMA;}return {images:[]};}});
 vm.runInContext(read('lab-builder-check.js'),p.c);vm.runInContext(read('lab-builder-yaml.js'),p.c);
 const timers=[];p.c.setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};
 const handle={located:[],doc,locateYaml(text){handle.located.push(text);return {tree:located(handle.doc)};}};p.c.handle=handle;
 p.run(`builderYaml.editor=handle;builderYamlContext({containerlab:${JSON.stringify(version)}});builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(NOTE_TEXT)}},undefined);`);
 p.fired=async()=>{const due=timers.splice(0);for(const t of due)t.fn();for(let i=0;i<4;i++)await settle();};
 p.timersNow=timers;p.fetched=fetched;p.handle=handle;return p;
}
test('persist() makes no synchronous check: the note’s timer is armed and the check runs only inside it',async()=>{
 const p=notePage();let located_=0;const orig=p.c.builderYamlLocate;p.c.builderYamlLocate=t=>{located_++;return orig(t);};
 const before=p.run('builderBlocked()');
 p.run(`builderPage.persist(${JSON.stringify(NOTE_TEXT+'# edit\n')},'')`);
 assert.equal(located_,0,'nothing parsed inside persist');assert.ok(p.timersNow.some(t=>t.ms===1200),'the note’s debounced timer');
 await p.fired();assert.ok(located_>=1,'the timer ran the check');
 assert.equal(p.run('builderBlocked()'),before,'advice never changes builderBlocked()');
});
test('the note shows one error with its line and message, Show in YAML and Dismiss; warnings alone show nothing',async()=>{
 const p=notePage();p.run('builderCheckStatus()');await p.fired();
 const note=p.el('builder-check');assert.equal(note.hidden,false);
 assert.equal(p.el('builder-check-text').textContent,'1 error containerlab will refuse when deploying: line 7, `imge` is not a device setting containerlab 0.79.0 knows. Did you mean `image`? Open YAML to see it.');
 const html=read('lab-builder.html');assert.match(html,/id="builder-check" role="status" hidden/);assert.match(html,/id="builder-check-show"[^>]*>Show in YAML</);assert.match(html,/id="builder-check-dismiss"[^>]*aria-label="[^"]+"[^>]*>Dismiss</);
 p.handle.doc=CLEAN_DOC;p.run('builderCheckStatus()');await p.fired();assert.equal(note.hidden,true,'a clean text hides it');
 const loose=notePage(NOTE_DOC,{version:'0.81.0'});loose.run('builderCheckStatus()');await loose.fired();assert.equal(loose.el('builder-check').hidden,true,'an unknown key is only a warning on another version');
});
test('an error that is an error on any version (a wait loop) shows although the version does not match',async()=>{
 const p=notePage(LOOP_DOC,{version:'0.81.0'});p.run('builderCheckStatus()');await p.fired();
 assert.equal(p.el('builder-check').hidden,false);assert.match(p.el('builder-check-text').textContent,/^1 error that keeps the deploy from finishing: line \d+, Devices wait for each other in a loop/);
});
test('two errors say how many and name the first',async()=>{
 const doc={name:'lab1',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',imge:'x',imgx:'y'}}}};
 const p=notePage(doc);p.run('builderCheckStatus()');await p.fired();assert.match(p.el('builder-check-text').textContent,/^2 errors containerlab will refuse when deploying: the first is line 7, /);
});
test('the schema is asked for once from the note, and the rules that need none run before it arrives',async()=>{
 const p=notePage();p.run('builderCheckStatus()');await p.fired();p.run('builderCheckStatus()');await p.fired();p.run('builderCheckStatus()');await p.fired();
 assert.equal(p.fetched.length,1,'one fetch for the page’s life');assert.match(p.fetched[0],/^\/static\/clab-schema\/0\.79\.0\.json/);
 // Before it arrives: a loop is found, a settings error is not.
 const q=notePage(LOOP_DOC);let release;const gate=new Promise(r=>{release=r;});const loopFetch=q.c.fetch;q.c.fetch=async(u,i)=>{if(String(u).startsWith('/static/clab-schema/'))await gate;return loopFetch(u,i);};
 q.run('builderCheckStatus()');for(const t of q.timersNow.splice(0))t.fn();await settle();assert.equal(q.el('builder-check').hidden,false,'shown with the schema-free rules');
 release();for(let i=0;i<4;i++)await settle();assert.equal(q.el('builder-check').hidden,false);
});
test('Dismiss is remembered for that draft, text and count, and focus goes to Save (or the YAML button)',async()=>{
 const p=notePage();let focused='';for(const id of ['builder-save','builder-yaml'])p.el(id).focus=()=>{focused=id;};
 p.el('builder-save').disabled=false;p.run('builderCheckStatus()');await p.fired();p.el('builder-check-dismiss').onclick();
 assert.equal(p.el('builder-check').hidden,true);assert.equal(focused,'builder-save');
 p.run('builderCheckStatus()');await p.fired();assert.equal(p.el('builder-check').hidden,true,'the same draft, text and count stay dismissed');
 p.handle.doc={name:'lab1',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',imge:'x',imgx:'y'}}}};p.run('builderCheckStatus()');await p.fired();assert.equal(p.el('builder-check').hidden,false,'another count is news again');
 p.el('builder-save').disabled=true;p.el('builder-check-dismiss').onclick();assert.equal(focused,'builder-yaml');
});
test('a locateYaml or builderCheck that throws hides the note and changes nothing else',async()=>{
 const p=notePage();p.run('builderCheckStatus()');await p.fired();assert.equal(p.el('builder-check').hidden,false);
 const blocked=p.run('builderBlocked()');
 p.handle.locateYaml=()=>{throw new RangeError('Maximum call stack size exceeded');};
 assert.doesNotThrow(()=>p.run(`builderPage.persist(${JSON.stringify(NOTE_TEXT+'# one\n')},'')`));await p.fired();
 assert.equal(p.el('builder-check').hidden,true);assert.equal(p.run('builderUnstored'),null);assert.equal(p.run('builderPaused'),null);assert.equal(p.run('builderBlocked()'),blocked);assert.equal(p.el('root').inert,undefined);
 assert.equal(p.run('builderDraft.yaml'),NOTE_TEXT+'# one\n','the edit was stored');
 p.handle.locateYaml=()=>({tree:located(NOTE_DOC)});p.c.builderCheck=()=>{throw new Error('boom');};
 assert.doesNotThrow(()=>p.run(`builderPage.persist(${JSON.stringify(NOTE_TEXT+'# two\n')},'')`));await p.fired();
 assert.equal(p.el('builder-check').hidden,true);assert.equal(p.run('builderUnstored'),null);assert.equal(p.run('builderPaused'),null);assert.equal(p.run('builderBlocked()'),blocked);
 // And a check that throws when the timer is armed cannot reach persist() either.
 p.c.setTimeout=()=>{throw new Error('no timers');};assert.doesNotThrow(()=>p.run('builderCheckStatus()'));
});
test('nothing is checked before an editor is attached',async()=>{
 const p=notePage();p.run('builderYaml.editor=null;builderCheckStatus()');await p.fired();assert.equal(p.el('builder-check').hidden,true);assert.equal(p.handle.located.length,0);
});
test('Show in YAML opens the panel with the caret on the finding when the panel is clean, and at its own list when it holds edits',async()=>{
 const p=notePage(),log=[];p.c.builderYamlPanelToggle=o=>{log.push(['toggle',o]);return true;};p.c.builderYamlGoto=(l,o)=>{log.push(['goto',l,o&&o.select]);};
 p.c.builderYamlPanelState=()=>({dirty:false,canvasChanged:false,applying:false});
 p.run('builderCheckStatus()');await p.fired();p.el('builder-check-show').onclick();
 assert.deepEqual(log,[['toggle',true],['goto',7,false]]);
 log.length=0;p.c.builderYamlPanelState=()=>({dirty:true,canvasChanged:false,applying:false});
 let focused=false;p.el('builder-yaml-list').querySelector=sel=>sel==='button'?{focus(){focused=true;}}:null;
 p.el('builder-check-show').onclick();assert.deepEqual(log,[['toggle',true]],'a dirty panel: the toggle only, the caret does not move');assert.equal(focused,true,'focus lands on the first problem');
});
test('the page’s capabilities reach the panel: the VM’s containerlab picks the schema',()=>{
 const p=notePage(),seen=[];p.c.builderYamlContext=c=>seen.push(c&&c.containerlab);
 p.c.opCapabilities=async()=>({containerlab:'0.79.0',actions:{}});
 return p.run('builderConnect()').then(()=>assert.deepEqual(seen,['0.79.0']));
});

test('an error the manager’s import refuses is worded as that, and the generic sentence counts only containerlab’s errors',async()=>{
 const base={name:'lab1',prefix:'${CLAB_PREFIX:=""}',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33'}}}};
 const p=notePage(base);p.run('builderCheckStatus()');await p.fired();
 assert.equal(p.el('builder-check').hidden,false);
 const text=p.el('builder-check-text').textContent;
 assert.match(text,/^1 error the manager’s import refuses: line 2, the manager’s import refuses this prefix /);assert.doesNotMatch(text,/containerlab will refuse/);
 const mixed=notePage({...base,topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',imge:'x'}}}});mixed.run('builderCheckStatus()');await mixed.fired();
 const both=mixed.el('builder-check-text').textContent;
 assert.match(both,/^1 error containerlab will refuse when deploying: line \d+, `imge` is not a device setting/);assert.match(both,/The manager’s import also refuses 1 more\.$/);
});
test('the note words wait errors as what happens (the deploy cannot finish), a mix as "stop the deploy", and keeps the refuse wording for the rest',async()=>{
 const wait={stages:{create:{'wait-for':[{node:'zz',stage:'create'}]}}};
 const w=notePage({...LOOP_DOC,topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',...wait}}}});w.run('builderCheckStatus()');await w.fired();
 const text=w.el('builder-check-text').textContent;assert.match(text,/^1 error that keeps the deploy from finishing: line \d+, There is no device named `zz`/);assert.doesNotMatch(text,/will refuse/);
 const mix=notePage({...LOOP_DOC,topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',imge:'x',...wait}}}});mix.run('builderCheckStatus()');await mix.fired();
 assert.match(mix.el('builder-check-text').textContent,/^2 errors that stop the deploy: the first is line \d+, /);
});
test('Dismiss is remembered across a reload in the tab (sessionStorage, per draft, text and count) until the text changes',async()=>{
 const session=(()=>{const m=new Map();return {getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>{m.set(k,String(v));},removeItem:k=>{m.delete(k);}};})();
 const first=notePage();first.c.window.sessionStorage=session;
 first.run('builderCheckStatus()');await first.fired();assert.equal(first.el('builder-check').hidden,false);
 first.el('builder-check-dismiss').onclick();assert.equal(first.el('builder-check').hidden,true);
 // A reload: a new page (nothing in memory) in the same tab.
 const second=notePage();second.c.window.sessionStorage=session;
 second.run('builderCheckStatus()');await second.fired();assert.equal(second.el('builder-check').hidden,true,'the same problems stay dismissed after a reload');
 second.handle.doc={name:'lab1',topology:{nodes:{a:{kind:'arista_ceos',image:'ceos:4.33',imge:'x',imgx:'y'}}}};second.run('builderCheckStatus()');await second.fired();
 assert.equal(second.el('builder-check').hidden,false,'other problems are news again');
 // A browser that refuses sessionStorage: Dismiss still works for the page’s life.
 const refused=notePage();Object.defineProperty(refused.c.window,'sessionStorage',{get(){throw new Error('denied');}});
 refused.run('builderCheckStatus()');await refused.fired();refused.el('builder-check-dismiss').onclick();
 assert.equal(refused.el('builder-check').hidden,true);refused.run('builderCheckStatus()');await refused.fired();assert.equal(refused.el('builder-check').hidden,true);
});

// ---- editing a lab's own file: the Topology view opens this page at #path=…&lab=<id> (docs/parity-campaign/TOPOLOGY-EDIT-DESIGN.md 12) ----
const LAB={id:'lab-1',name:'Parity',deployment_name:'parity',vm_project_path:VM_PATH,deployment:{status:'Running'},nodes:[{name:'a',runtime_state:'running'},{name:'b',runtime_state:'exited'}]};
const PREVIEW={action:'revise',name:'lab1',path:VM_PATH,token:'t1',warnings:[],affected:[],argv:[],steps:[],images:[],diff:'-a\n+b\n',deployed:true};
const labSettle=async()=>{for(let i=0;i<30;i++)await new Promise(done=>setImmediate(done));};
function labPage(status='Running',options={}){
 const p=page({answer:options.answer||(()=>({}))});
 p.run(`state.labs=[${JSON.stringify({...LAB,deployment:{status}})}];builderLabId='${options.lab===undefined?'lab-1':options.lab}';builderCaps={actions:{publish:{available:true},revise:{available:true,deployed:true}}};builderDraft=draftWrite(builderStore,{id:'vm:${VM_PATH}',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY+'# edited\n')},annotations:'',mapRevision:'r7',vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:''}},undefined);builderRenderBar();`);
 return p;
}
test('#lab: the title and the bar name the lab, Back to lab replaces My labs, and a plain line says the lab’s state without ever saying destroy',()=>{
 const p=labPage('Running'),line=()=>p.el('builder-line-text').textContent;
 assert.equal(p.run('document.title'),'Parity · Edit topology · Containerlab Node Manager');assert.equal(p.el('builder-name').textContent,'Editing Parity');
 assert.equal(p.el('builder-back').textContent,'← Back to lab');assert.equal(p.el('builder-back').href,'/#lab=lab-1&view=topology');
 const sentences={
  Running:'This lab is running on the VM (2 devices). Saving changes the file and the map, not the devices; applying is a separate step.',
  'Partially running':'Some devices of this lab are running on the VM (1 of 2). Saving changes the file and the map, not the devices; applying is a separate step.',
  Stopped:'This lab is stopped on the VM (2 devices). Saving changes the file and the map, not the devices; applying is a separate step.',
  'Not deployed':'This lab is not deployed.',
  Unknown:'Whether this lab is running is not known right now. Saving changes the file and the map, not any devices that may be running; applying is a separate step.',
 };
 for(const [status,text] of Object.entries(sentences)){const q=labPage(status);assert.equal(q.el('builder-line-text').textContent,text,status);assert.doesNotMatch(q.el('builder-line-text').textContent,/destroy/i);assert.equal(q.el('builder-line').hidden,false);}
 assert.equal(line(),sentences.Running);
 // the line is its own element: not a live region, and the older note under the bar does not repeat it
 assert.equal(p.el('builder-note').hidden,true);
 const html=read('lab-builder.html'),tag=/<p class="builder-line" id="builder-line"[^>]*>/.exec(html)[0];assert.doesNotMatch(tag,/role=|aria-live/);assert.match(tag,/ hidden/);
 // no lab (an old address), or a lab that left the manager: the file name and My labs
 for(const q of [labPage('Running',{lab:''}),labPage('Running',{lab:'gone'})]){assert.equal(q.el('builder-back').textContent,'← My labs');assert.equal(q.el('builder-back').href,'/');assert.equal(q.el('builder-name').textContent,'lab1');assert.equal(q.el('builder-line').hidden,true);assert.match(q.run('document.title'),/^lab1 · Lab builder/);}
});
test('#lab is kept in the address while the page moves between drafts and versions of the same file, and only then',()=>{
 const p=labPage('Running');
 p.run(`draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:'y',vm:{path:'${VM_PATH}',yaml:'y',annotations:''}},undefined);draftWrite(builderStore,{id:'new:other',name:'other',root:'/srv/labs',yaml:'y'},undefined);`);
 p.run("builderGo({draft:'new:lab1'})");assert.equal(new URLSearchParams(p.run('location.hash')).get('lab'),'lab-1','Drafts… › Open of this lab\'s draft');
 p.run(`builderGo({path:'${VM_PATH}'})`);assert.equal(new URLSearchParams(p.run('location.hash')).get('lab'),'lab-1','Open the VM version');
 p.run("builderGo({draft:'new:other'})");assert.equal(new URLSearchParams(p.run('location.hash')).get('lab'),null,'another lab\'s draft is not this lab');
});
test('with #lab the annotations are the manager\'s kept map document and its revision is remembered; the VM file\'s map hash stays the base of the stale check',async()=>{
 const read=(url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:TOPOLOGY,sha256:'h'}:body.path===VM_PATH+'.annotations.json'?{text:'{"vm":1}',sha256:'lh'}:{refused:'The selected VM path no longer exists.'}):url.endsWith('/operations/parse-yaml')?{name:'lab1'}:null;
 const p=page({answer:(url,body)=>read(url,body)||(url.endsWith('/labs/lab-1/map-document')?{name:'lab1',yaml:TOPOLOGY,annotations:'{"manager":1}',revision:'r7'}:{})});
 const d=await p.run(`builderOpenFromVm('${VM_PATH}','lab-1')`);
 assert.equal(d.annotations,'{"manager":1}');assert.equal(d.mapRevision,'r7');assert.equal(d.vm.annotations,'{"vm":1}');assert.equal(d.vm.layoutHash,'lh');
 const request=await p.c.builderSaveRequest(JSON.parse(JSON.stringify(d)),async t=>'sha:'+t);
 assert.equal(request.options.annotations,'{"manager":1}','the save writes the manager\'s document beside the file');assert.equal(request.options.base.annotations,'lh','the stale check compares the VM file\'s own map');
 // without #lab, or without a kept document, the VM file's map is used as before
 const none=page({answer:(url,body)=>read(url,body)||(url.endsWith('/map-document')?{name:'lab1',yaml:TOPOLOGY,annotations:'',revision:'r0'}:{})});
 const v=await none.run(`builderOpenFromVm('${VM_PATH}','lab-1')`);assert.equal(v.annotations,'{"vm":1}');assert.equal(v.mapRevision,undefined);
 const refused=page({answer:(url,body)=>read(url,body)||{refused:'Import a topology map first.',status:404}});
 assert.equal((await refused.run(`builderOpenFromVm('${VM_PATH}','lab-1')`)).annotations,'{"vm":1}');
 const plain=page({answer:(url,body)=>read(url,body)||{}});assert.equal((await plain.run(`builderOpenFromVm('${VM_PATH}')`)).annotations,'{"vm":1}');assert.ok(!plain.calls.some(c=>Array.isArray(c)&&/map-document/.test(c[0])),'no document is asked for without #lab');
 // a draft that continues takes the newer document while its own map is untouched; with map edits of its own it keeps them under a revision that is no longer current
 const seed=(annotations,extra='')=>`draftWrite(builderStore,{id:'vm:${VM_PATH}',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},annotations:${JSON.stringify(annotations)},mapRevision:'r1',${extra}vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:'{"vm":1}'}},undefined);`;
 const open=async(code)=>{const q=page({answer:(url,body)=>read(url,body)||(url.endsWith('/map-document')?{name:'lab1',yaml:TOPOLOGY,annotations:'{"manager":2}',revision:'r8'}:{})});q.run(code);return q.run(`builderOpenFromVm('${VM_PATH}','lab-1')`);};
 const untouched=await open(seed('{"vm":1}'));assert.equal(untouched.annotations,'{"manager":2}');assert.equal(untouched.mapRevision,'r8');
 const touched=await open(seed('{"mine":1}'));assert.equal(touched.annotations,'{"mine":1}');assert.equal(touched.mapRevision,'r1','a stale revision: the manager refuses the save until the person reopens');
 const old=await open(seed('{"mine":1}').replace("mapRevision:'r1',",''));assert.equal(old.mapRevision,'unknown','an older draft with map edits is never sent as current');
 const reopened=await open(seed('{"mine":1}','mapStale:true,'));assert.equal(reopened.annotations,'{"manager":2}');assert.equal(reopened.mapRevision,'r8');
});
test('a revision sends deployed:true whenever the helper offers it, the lab it belongs to and the map revision; the labs are read first',async()=>{
 const p=labPage('Stopped',{answer:(url,body)=>url.endsWith('/operations/preview')?PREVIEW:url.endsWith('/state')?{labs:[{...LAB,deployment:{status:'Stopped'}}],jobs:[],operations:[]}:{}});
 await p.run('builderSave()');
 const urls=p.calls.map(c=>c[0]),sent=p.calls.find(c=>c[0].endsWith('/operations/preview'))[1];
 assert.ok(urls.findIndex(u=>u.endsWith('/state'))>=0&&urls.findIndex(u=>u.endsWith('/state'))<urls.findIndex(u=>u.endsWith('/operations/preview')),'the state is read before the request');
 assert.equal(sent.action,'revise');assert.equal(sent.options.deployed,true,'also for a lab that is not running now: the helper judges');assert.equal(sent.lab_id,'lab-1');assert.equal(sent.map_revision,'r7');assert.equal(sent.path,VM_PATH);
 assert.equal(p.run('builderPending.deployed'),true,'the review\'s answer is kept with the pending save');
 // an older helper (no deployed flag in its capabilities) gets the old request; a lab no longer in the list a path-only one; publish none of it
 const old=labPage('Running',{answer:(url,body)=>url.endsWith('/operations/preview')?PREVIEW:url.endsWith('/state')?{labs:[],jobs:[],operations:[]}:{}});
 old.run("builderCaps={actions:{revise:{available:true}}}");await old.run('builderSave()');
 const o=old.calls.find(c=>c[0].endsWith('/operations/preview'))[1];assert.equal(o.options.deployed,undefined);assert.equal(o.lab_id,undefined);assert.equal(o.map_revision,undefined);
 const fresh=page({answer:(url)=>url.endsWith('/operations/preview')?{...PREVIEW,action:'publish',deployed:false}:{}});
 fresh.run(`builderCaps={actions:{publish:{available:true}}};builderDraft=draftWrite(builderStore,{id:'new:lab1',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)}},undefined);`);await fresh.run('builderSave()');
 const f=fresh.calls.find(c=>c[0].endsWith('/operations/preview'))[1];assert.equal(f.action,'publish');assert.equal(f.lab_id,undefined);assert.equal(f.options.deployed,undefined);
});
test('a lab that left the manager: the 404 is answered once with a path-only save; a moved map is explained with Reopen and Download',async()=>{
 let first=true;
 const p=labPage('Running',{answer:(url,body)=>url.endsWith('/operations/preview')?(body.lab_id&&first?(first=false,{refused:'Lab not found.',status:404}):PREVIEW):url.endsWith('/state')?{labs:[{...LAB}],jobs:[],operations:[]}:{}});
 await p.run('builderSave()');
 const previews=p.calls.filter(c=>c[0].endsWith('/operations/preview')).map(c=>c[1]);
 assert.equal(previews.length,2);assert.equal(previews[0].lab_id,'lab-1');assert.equal(previews[1].lab_id,undefined);assert.equal(previews[1].map_revision,undefined);assert.equal(previews[1].path,VM_PATH);
 assert.equal(p.run('builderLabId'),'','the page stops presenting itself as that lab');assert.ok(p.run('builderPending'),'the second review is the pending save');
 // 409: the sentence is in the save-problem dialog, nothing else is offered as a way on
 const text='The map changed in the manager since you opened Edit topology. Reopen it; your topology changes stay in this browser.';
 const q=labPage('Running',{answer:(url)=>url.endsWith('/operations/preview')?{refused:text,status:409}:url.endsWith('/state')?{labs:[{...LAB}],jobs:[],operations:[]}:{}});
 q.run("var downloads=0;builderDownload=()=>{downloads++;}");await q.run('builderSave()');
 const dialog=q.c.dialogs.at(-1);assert.equal(dialog.id,'builder-save-problem');assert.equal(q.el('builder-save-problem-text').textContent,text);
 assert.match(dialog.body,/Reopen/);assert.match(dialog.body,/Download my draft/);assert.doesNotMatch(dialog.body,/Review the differences|Open the VM version/);assert.match(dialog.body,/Nothing on the VM was changed/);
 q.el('builder-save-problem-download').onclick();assert.equal(q.run('downloads'),1);
 q.el('builder-save-problem-reopen').onclick();assert.equal(q.run('location.href'),'/#lab=lab-1&view=topology');assert.equal(q.run('builderDraft.mapStale'),true,'the next open takes the manager\'s map');
});
function savedJob(p,preview,extra={}){
 p.run(`builderPending={yaml:builderDraft.yaml,annotations:'',action:'revise',path:'${VM_PATH}',baseYaml:${JSON.stringify(extra.baseYaml===undefined?TOPOLOGY:extra.baseYaml)},deployed:${preview.deployed}};opJobStarted({id:'j1',action:'revise'});`);
 p.run(`opJobDone({id:'j1',action:'revise',status:'succeeded',result:{published_path:'${VM_PATH}'}})`);
}
test('a deployed save registers nothing, says the running lab is unchanged, shows the warning pill while the plan has changes and leads to the lab page\'s own review',async()=>{
 let plan={changed:true,failed:false,plan:{added:['r3'],links_added:['r3:eth1 - r1:eth2']}};
 const p=labPage('Running',{answer:url=>url.includes('/operations/apply-plan')?plan:url.endsWith('/state')?{labs:[{...LAB}],jobs:[],operations:[]}:{}});
 let focused=0;p.el('builder-review').focus=()=>{focused++;};
 savedJob(p,PREVIEW);
 assert.equal(p.toasts.at(-1),'Saved to the VM. The running lab is unchanged until you apply the changes.');
 assert.equal(p.el('builder-status').textContent,'Saved on the VM · not applied','before the plan is known nothing reads as applied');assert.equal(p.el('builder-status').className,'pill warn');
 assert.equal(p.el('builder-review').hidden,false);assert.equal(p.el('builder-review').href,'/#lab=lab-1&view=topology&review=apply');assert.match(read('lab-builder.html'),/<a class="button secondary" id="builder-review" href="\/" hidden>Back to lab and review changes…<\/a>/);
 assert.match(p.el('builder-line-text').textContent,/Checking what applying would change…/);
 assert.equal(focused,1,'focus moves to the control when no output dialog is open');
 await labSettle();
 assert.ok(p.calls.some(c=>c[0]==='/api/operations/apply-plan?lab_id=lab-1&refresh=1'),'the plan is read again for the lab');
 assert.ok(!p.calls.some(c=>/lab-definitions/.test(c[0]))&&p.forms.length===0,'a deployed save never registers the lab again');
 assert.equal(p.el('builder-status').textContent,'Saved on the VM · not applied');
 assert.match(p.el('builder-line-text').textContent,/^Saved on the VM, not applied\. The running lab differs from the file: r3 to create · 1 link to connect\. Back to lab and review changes… shows the plan; Lab actions ▾ › Apply topology changes… applies it\.$/);
 assert.ok(!/My labs now shows/.test(p.toasts.join('|')));
 // nothing to apply: the existing words, the control goes; a map-only save says so
 plan={changed:false,failed:false,plan:{}};await p.run("builderLabPlan('lab-1')");
 assert.equal(p.el('builder-status').textContent,'Saved on the VM');assert.equal(p.el('builder-status').className,'pill ok');assert.equal(p.el('builder-review').hidden,true);
 assert.match(p.el('builder-line-text').textContent,/Saved on the VM\. The running lab already matches the file: there is nothing to apply\./);
 p.run("builderAfter.mapOnly=true;builderRenderBar()");assert.match(p.el('builder-line-text').textContent,/Only the map layout changed, and the running lab matches the file: there is nothing to apply\./);
 // the plan could not be made or checked: still not applied, and the sentence says why
 plan={changed:false,failed:'unsupported',plan:null};await p.run("builderLabPlan('lab-1')");
 assert.equal(p.el('builder-status').textContent,'Saved on the VM · not applied');assert.match(p.el('builder-line-text').textContent,/The installed containerlab cannot show what applying will change; Lab actions ▾ › Apply topology changes… runs without a plan\./);
 plan={changed:false,failed:'error',error:'the file could not be read',plan:null};await p.run("builderLabPlan('lab-1')");
 assert.match(p.el('builder-line-text').textContent,/could not be checked: the file could not be read\. Lab actions ▾ › Apply topology changes… shows the review\./);
});
test('the focus waits for the output dialog to close (#15)',()=>{
 const p=labPage('Running',{answer:()=>({})});let focused=0,closed;
 p.el('builder-review').focus=()=>{focused++;};
 p.el('operation-output').open=true;p.el('operation-output').addEventListener=(kind,fn)=>{closed=fn;};
 savedJob(p,PREVIEW);assert.equal(focused,0,'not while the output is on screen');closed();
 assert.equal(p.timers.length>0,true);while(p.timers.length)p.timers.shift()();assert.equal(focused,1);
});
test('an undeployed save keeps the old behaviour: the lab is registered again with its deployed name and My labs says so',async()=>{
 const p=labPage('Not deployed',{answer:url=>url.endsWith('/labs/lab-1/map-document')?{name:'lab1',yaml:TOPOLOGY,annotations:'{"x":1}',revision:'r9'}:url.endsWith('/state')?{labs:[{...LAB,deployment:{status:'Not deployed'}}],jobs:[],operations:[]}:{}});
 savedJob(p,{...PREVIEW,deployed:false});await labSettle();
 assert.equal(p.forms.length,1);assert.equal(p.forms[0][0],'/api/lab-definitions');assert.equal(p.forms[0][1].lab_id,'lab-1');assert.equal(p.forms[0][1].deployed_name,'parity');
 assert.match(p.toasts.at(-1),/^My labs now shows the saved topology of Parity\.$/);assert.ok(!p.toasts.some(t=>/unchanged until you apply/.test(t)));
 assert.equal(p.el('builder-status').textContent,'Saved on the VM');assert.equal(p.el('builder-review').hidden,true);
 assert.equal(p.run('builderDraft.mapRevision'),'r7','the revision is taken over only when the manager now holds the map this page saved');
});
test('no page text tells the student to destroy the lab, and the notice for a running lab without #lab says what a save leaves alone',()=>{
 for(const file of ['lab-builder-page.js','lab-builder.html','lab-builder-check.js'])assert.doesNotMatch(read(file),/destroy/i,file);
});

// ---- the device templates come from the manager's catalog (T04b); BUILDER_TEMPLATES is the offline fallback ----
function catalogOf(templates,change=t=>t){return {entries:templates.map(change).map(t=>{const {name,kind,image,...rest}=t;return {kind,label:name,image,aliases:[],login_default:true,interfaces:null,capabilities:{},template:{name,...rest}};}),kinds:templates.map(t=>t.kind)};}
test('the default templates are the catalog\'s entries in the shape of BUILDER_TEMPLATES, and the built-in list is the fallback',()=>{
 const p=page({answer:()=>({})}),plain=v=>JSON.parse(JSON.stringify(v)),builtin=plain(p.run('BUILDER_TEMPLATES'));
 assert.deepEqual(plain(p.run('builderBaseTemplates()')),builtin,'no catalog: the built-in list');
 p.c.catalog=catalogOf(builtin);p.run('builderCatalogAnswer=catalog');
 assert.deepEqual(plain(p.run('builderCatalogTemplates(builderCatalogAnswer)')),builtin,'the catalog round-trips every field (name, kind, image, pinned, env, match, baseName, interfacePattern, icon)');
 const changed=catalogOf(builtin,t=>t.kind==='arista_ceos'?{...t,image:'n24l/ceos:9.9'}:t);p.c.catalog=changed;p.run('builderCatalogAnswer=catalog');
 assert.equal(plain(p.run('builderTemplateList({},[])')).find(t=>t.kind==='arista_ceos').image,'n24l/ceos:9.9','a pinned kind takes the catalog\'s image');
 // an entry without the template's shape is skipped, an empty catalog is no catalog
 p.c.catalog={entries:[{kind:'x'},{kind:'y',image:'i:1',template:{}},null,...catalogOf(builtin).entries.slice(0,1)]};p.run('builderCatalogAnswer=catalog');assert.equal(plain(p.run('builderBaseTemplates()')).length,1);
 p.c.catalog={entries:[]};p.run('builderCatalogAnswer=catalog');assert.deepEqual(plain(p.run('builderBaseTemplates()')),builtin);
});
test('stored templates keep precedence; catalog kinds the stored list lacks are appended, never replacing a stored entry',()=>{
 const s=storage(),win={localStorage:s},c=load(win),plain=v=>JSON.parse(JSON.stringify(v)),builtin=plain(c.BUILDER_TEMPLATES);
 const extra={name:'Nokia SR Linux',kind:'nokia_srlinux',image:'ghcr.io/nokia/srlinux:latest',match:['srlinux'],baseName:'srl',interfacePattern:'e1-{n}',icon:'switch'};
 vm.runInContext('builderCatalogAnswer='+JSON.stringify(catalogOf([...builtin,extra])),c);
 s.setItem('clab-builder:templates',JSON.stringify({list:[{name:'My host',kind:'linux',image:'alpine:3'},{name:'Arista cEOS',kind:'arista_ceos',image:'ceos:old'}],defaultName:'My host'}));
 s.setItem('clab-builder:templates-version','2');
 const got=plain(win.labBuilderPage.templates());
 assert.equal(got.defaultName,'My host');assert.deepEqual(got.list.slice(0,2).map(t=>[t.name,t.image]),[['My host','alpine:3'],['Arista cEOS','ceos:old']],'the stored entries stay first and unchanged');
 assert.deepEqual(got.list.slice(2).map(t=>t.kind),['juniper_cjunosevolved','juniper_vjunosswitch','juniper_vjunosrouter','juniper_vsrx','cisco_xrv9k','nokia_srlinux'],'every catalog kind missing from the stored list, once');
 assert.equal(got.list.filter(t=>t.kind==='linux').length,1,'a kind the stored list has is not appended again');
 assert.ok(win.labBuilderPage.images().includes('ghcr.io/nokia/srlinux:latest'));
 // without a catalog nothing is appended
 const q=storage(),w2={localStorage:q},c2=load(w2);q.setItem('clab-builder:templates',JSON.stringify({list:[{name:'Mine',kind:'linux',image:'a:1'}],defaultName:''}));q.setItem('clab-builder:templates-version','2');
 assert.equal(plain(w2.labBuilderPage.templates()).list.length,1);
});
test('the catalog is asked for at start beside the other calls, shared with the check, and a failure leaves the built-in list and a null the check can see',async()=>{
 const good=page({answer:url=>url.endsWith('/api/catalog')||url==='/api/catalog'?catalogOf([{name:'Linux host',kind:'linux',image:'a:1',match:[],baseName:'host',interfacePattern:'eth{n}',icon:'client'}]):{}});
 const got=await good.run('builderCatalogLoad()');assert.equal(got.entries.length,1);assert.equal(good.run('builderCatalogAnswer.entries.length'),1);assert.equal(good.run('window.builderCatalog.entries.length'),1);
 for(const answer of [{refused:'down',status:500},new Error('x'),{entries:[]},{}]){const bad=page({answer:()=>answer});assert.equal(await bad.run('builderCatalogLoad()'),null);assert.equal(bad.run('builderCatalogAnswer'),null);assert.equal(bad.run('window.builderCatalog'),null);}
 const source=read('lab-builder-page.js');assert.match(source,/Promise\.all\(\[builderConnect\(\),api\('\/operations\/known-images'\)[^]*?builderCatalogLoad\(\)\]\)/,'one race with the existing calls');
});

// ---- Undo and Redo in the bar (T05 gives the handle undo(), redo(), history() and a third subscribe argument) ----
test('the bar has Undo and Redo, shown when the handle has them, enabled from the history and answered through the handle; errors go to the toast',async()=>{
 const html=read('lab-builder.html');for(const id of ['builder-undo','builder-redo'])assert.match(html,new RegExp('<button class="button secondary" id="'+id+'" disabled hidden'));
 assert.ok(html.indexOf('id="builder-undo"')<html.indexOf('id="builder-save"'));
 const p=page({answer:()=>({})}),calls=[];let listener;
 const handle={subscribe:fn=>{listener=fn;return()=>{};},undo:async()=>{calls.push('undo');},redo:async()=>{calls.push('redo');throw new Error('The engine refused redo.');},history:async()=>({canUndo:true,canRedo:false})};
 p.c.handle=handle;p.run('builderHistoryWire(handle)');await labSettle();
 assert.equal(p.el('builder-undo').hidden,false);assert.equal(p.el('builder-redo').hidden,false);assert.equal(p.el('builder-undo').disabled,false);assert.equal(p.el('builder-redo').disabled,true);
 listener('y','a',{canUndo:false,canRedo:true});assert.equal(p.el('builder-undo').disabled,true);assert.equal(p.el('builder-redo').disabled,false);
 await p.run("builderHistoryStep('undo')");await p.run("builderHistoryStep('redo')");assert.deepEqual(calls,['undo','redo']);assert.equal(p.toasts.at(-1),'The engine refused redo.');
 // an adapter without them (an older bundle) shows no buttons
 const old=page({answer:()=>({})});old.c.handle={subscribe(){return()=>{};}};old.run('builderHistoryWire(handle)');assert.equal(old.el('builder-undo').hidden,true);assert.equal(old.el('builder-redo').hidden,true);
 assert.match(read('lab-builder-page.js'),/\['builder-undo',\(\)=>builderHistoryStep\('undo'\)\],\['builder-redo',\(\)=>builderHistoryStep\('redo'\)\]/);
});

// ---- T06-fix 4 to 7: the map base, the pristine pill, the focus after Undo ----
const NODE=(id,x)=>({id,position:{x,y:x},icon:'router'});
const ANN=(...nodes)=>JSON.stringify({nodeAnnotations:nodes});
function mapRead(file,doc,extra={}){
 return (url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:TOPOLOGY,sha256:'h'}:body.path===VM_PATH+'.annotations.json'?{text:file,sha256:'lh'}:{refused:'The selected VM path no longer exists.'}):url.endsWith('/operations/parse-yaml')?{name:'lab1'}:url.endsWith('/map-document')?doc:(extra.other&&extra.other(url,body))||{};
}
test('T06-fix 5/6: a device placed only in the VM file is carried into the adopted document, the manager\'s entries win, and a pristine open reads Saved on the VM',async()=>{
 const file=ANN(NODE('r1',1),NODE('r2',22)),doc={name:'lab1',yaml:TOPOLOGY,annotations:ANN(NODE('r1',100)),revision:'r5'};
 const p=page({answer:mapRead(file,doc)});
 const d=await p.run(`builderOpenFromVm('${VM_PATH}','lab-1')`),got=JSON.parse(d.annotations).nodeAnnotations;
 assert.deepEqual(JSON.parse(JSON.stringify(got)),[NODE('r1',100),NODE('r2',22)],'r1 from the manager, r2 from the VM file');
 assert.equal(d.mapRevision,'r5');assert.equal(d.vm.annotations,file,'the VM file text stays the stale-check base');assert.equal(d.vm.layoutHash,'lh');
 const request=await p.c.builderSaveRequest(JSON.parse(JSON.stringify(d)),async t=>'sha:'+t);assert.equal(request.options.base.annotations,'lh');
 p.c.d=d;p.run('builderUse(d)');
 assert.equal(p.el('builder-status').textContent,'Saved on the VM','a pristine open has nothing unsaved');
 // an edit shows the change, Undo back to the start clears it again
 const edited=ANN(NODE('r1',5),NODE('r2',22));
 p.run(`builderPage.persist(${JSON.stringify(d.yaml)},${JSON.stringify(edited)})`);assert.equal(p.el('builder-status').textContent,'Changes not saved to the VM yet');
 p.run(`builderPage.persist(${JSON.stringify(d.yaml)},${JSON.stringify(d.annotations)})`);assert.equal(p.el('builder-status').textContent,'Saved on the VM');
 // a draft made before the field existed (no mapBase) is compared with the VM file as before
 assert.equal(p.c.draftStatus({yaml:'a',annotations:'x',vm:{yaml:'a',annotations:'x'}}).text,'Saved on the VM');assert.equal(p.c.draftStatus({yaml:'a',annotations:'y',vm:{yaml:'a',annotations:'x'}}).text,'Changes not saved to the VM yet');
 // entries are merged only into a document that has none of that id; broken text is left alone
 assert.equal(p.c.builderMapComplete('not json',file),'not json');assert.equal(p.c.builderMapComplete(ANN(NODE('r1',1)),'{'),ANN(NODE('r1',1)));
});
test('T06-fix 4: after a save the map base moves to the saved map, and the next open takes the manager\'s current revision instead of a false 409',async()=>{
 const saved=ANN(NODE('r1',1),NODE('r2',22));
 const seed=`draftWrite(builderStore,{id:'vm:${VM_PATH}',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},annotations:${JSON.stringify(saved)},mapRevision:'r7',mapBase:${JSON.stringify(ANN(NODE('r1',1)))},vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:${JSON.stringify(ANN(NODE('r1',1)))}}},undefined);`;
 const p=page({answer:()=>({})});p.run(seed);p.run(`builderDraft=draftRead(builderStore,'vm:${VM_PATH}');builderMarkSaved('${VM_PATH}',{yaml:${JSON.stringify(TOPOLOGY)},annotations:${JSON.stringify(saved)}})`);
 assert.equal(p.run('builderDraft.mapBase'),saved,'builderMarkSaved moves the base');assert.equal(p.run('builderDraft.vm.annotations'),saved);
 // the manager's document moved on (the apply re-registered the lab) to the same map written another way
 const reordered=JSON.stringify({nodeAnnotations:[{icon:'router',position:{y:1,x:1},id:'r1'},{icon:'router',position:{y:22,x:22},id:'r2'}]});
 const q=page({answer:mapRead(saved,{name:'lab1',yaml:TOPOLOGY,annotations:reordered,revision:'r9'})});
 const later=p.store;for(const k of [...Array(later.length).keys()].map(i=>later.key(i)))q.store.setItem(k,later.getItem(k));
 const open=await q.run(`builderOpenFromVm('${VM_PATH}','lab-1')`);
 assert.equal(open.mapRevision,'r9','the next save carries the current revision');
 // a draft with edits of its own keeps them and takes the revision when the document is still what it started from
 const edited=page({answer:mapRead(saved,{name:'lab1',yaml:TOPOLOGY,annotations:reordered,revision:'r9'})});
 edited.run(seed.replace(`annotations:${JSON.stringify(saved)}`,`annotations:${JSON.stringify(ANN(NODE('r1',9),NODE('r2',22)))}`).replace(`mapBase:${JSON.stringify(ANN(NODE('r1',1)))}`,`mapBase:${JSON.stringify(saved)}`).replace(`annotations:${JSON.stringify(ANN(NODE('r1',1)))}}},undefined`,`annotations:${JSON.stringify(saved)}}},undefined`));
 const kept=await edited.run(`builderOpenFromVm('${VM_PATH}','lab-1')`);
 assert.equal(kept.mapRevision,'r9');assert.equal(JSON.parse(kept.annotations).nodeAnnotations[0].position.x,9,'its map edits stay');
 // a document that is no longer what the draft started from: the revision stays stale and the manager refuses first
 const other=page({answer:mapRead(ANN(NODE('r1',1)),{name:'lab1',yaml:TOPOLOGY,annotations:ANN(NODE('r1',77)),revision:'r10'})});
 other.run(seed.replace(`annotations:${JSON.stringify(saved)}`,`annotations:${JSON.stringify(ANN(NODE('r1',9)))}`));
 assert.equal((await other.run(`builderOpenFromVm('${VM_PATH}','lab-1')`)).mapRevision,'r7');
});
test('T06-fix 7: Undo and Redo keep focus in the bar when the pressed button turns disabled',()=>{
 const p=page({answer:()=>({})}),focus=[];
 for(const id of ['builder-undo','builder-redo','builder-save','builder-yaml'])p.el(id).focus=function(){focus.push(id);p.c.document.activeElement=this;};
 p.el('builder-save').disabled=true;
 p.run('builderHistorySet({canUndo:true,canRedo:false})');
 p.c.document.activeElement=p.el('builder-undo');p.run('builderHistorySet({canUndo:false,canRedo:true})');
 assert.deepEqual(focus,['builder-redo'],'the other history button when it is on');
 focus.length=0;p.c.document.activeElement=p.el('builder-redo');p.run('builderHistorySet({canUndo:false,canRedo:false})');
 assert.deepEqual(focus,['builder-yaml'],'else the first enabled control of the bar (Save is off here)');
 focus.length=0;p.c.document.activeElement=p.el('builder-save');p.run('builderHistorySet({canUndo:false,canRedo:false})');assert.deepEqual(focus,[],'focus elsewhere is left alone');
});
