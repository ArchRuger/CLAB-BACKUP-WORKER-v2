const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const read=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8');
// A Storage like the browser's: string values, key(i), length.
function storage(){const map=new Map();return {getItem:k=>map.has(k)?map.get(k):null,setItem:(k,v)=>map.set(k,String(v)),removeItem:k=>map.delete(k),key:i=>[...map.keys()][i]??null,get length(){return map.size;}};}
function load(){const context=vm.createContext({console,crypto:require('node:crypto').webcrypto,TextEncoder,URLSearchParams,document:{getElementById:()=>null}});vm.runInContext(read('lab-builder-page.js'),context);vm.runInContext(read('operations.js'),context);
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
 for(const kind of ['arista_ceos','juniper_cjunosevolved','juniper_vjunosswitch','cisco_xrv9k','linux']){
  const t=c.BUILDER_TEMPLATES.find(x=>x.kind===kind);assert.ok(t,kind);assert.ok(t.name&&t.image,kind);
 }
});
test('templates take the image this site already uses for their kind',()=>{
 const c=load(),list=c.builderTemplateList({arista_ceos:['n24l/ceos:4.35.0F','ceos:old'],nokia_srlinux:['ghcr.io/nokia/srlinux']});
 assert.equal(list.find(t=>t.kind==='arista_ceos').image,'n24l/ceos:4.35.0F');assert.equal(list.find(t=>t.kind==='linux').image,c.BUILDER_TEMPLATES.find(t=>t.kind==='linux').image);
 assert.ok(c.builderImages(list,{nokia_srlinux:['ghcr.io/nokia/srlinux']}).includes('ghcr.io/nokia/srlinux'));
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
 const store=options.storage||storage(),calls=[],toasts=[],timers=[];
 const context=vm.createContext({console,crypto:options.crypto||require('node:crypto').webcrypto,TextEncoder,URLSearchParams,FormData,Blob,setTimeout:fn=>timers.push(fn),clearTimeout(){},confirm:()=>options.confirm??true,alert(){},
  window:{localStorage:store},location:{hash:'',reload(){calls.push('reload');}},document:{title:'',getElementById:el,querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>el('made'),body:{append(){}}},
  fetch:async(url,init)=>{const body=init?.body&&typeof init.body==='string'?JSON.parse(init.body):null;calls.push([url,body]);const answer=await options.answer(url,body);if(answer instanceof Error)throw new TypeError('network');return {ok:!answer.refused,json:async()=>answer.refused?{detail:answer.refused}:answer};}});
 vm.runInContext(read('lab-builder-page.js'),context);vm.runInContext(read('operations.js'),context);
 // operations.js dialogs need a real DOM; the page logic under test only needs to know one was asked for
 vm.runInContext("opDialog=(id,title,body)=>{dialogs.push({id,title,body});return {close(){},querySelector:()=>null,querySelectorAll:()=>[]};};notify=m=>toasts.push(m);",Object.assign(context,{dialogs:[],toasts}));
 return {c:context,el,store,calls,toasts,timers,run:code=>vm.runInContext(code,context)};
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
 assert.match(p.el('builder-note-text').textContent,/lab1 is deployed\..*after the lab is destroyed/);assert.equal(p.el('builder-save').disabled,false);
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
test('opening the VM version never discards a draft with unsaved changes unasked, whichever draft is newer',async()=>{
 const changed=TOPOLOGY+'# changed on the VM\n',answer=(url,body)=>url.endsWith('/operations/read')?(body.path===VM_PATH?{text:changed,sha256:'h2'}:{refused:'The selected VM path no longer exists.'}):url.endsWith('/operations/parse-yaml')?{name:'lab1'}:{};
 const seed=`draftWrite(builderStore,{id:'new:lab1:x',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY+'# my work\n')},vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:''}},undefined);draftWrite(builderStore,{id:'vm:${VM_PATH}',name:'lab1',root:'/srv/labs',yaml:${JSON.stringify(TOPOLOGY)},vm:{path:'${VM_PATH}',yaml:${JSON.stringify(TOPOLOGY)},annotations:''}},undefined);`;
 let asked=0;const keep=page({answer});keep.c.confirm=()=>{asked++;return false;};keep.run(seed);
 const kept=await keep.run(`builderOpenFromVm('${VM_PATH}')`);assert.equal(asked,1,'the student is asked');assert.match(kept.yaml,/my work/);assert.match(keep.c.draftRead(keep.store,'new:lab1:x').yaml,/my work/,'Cancel keeps the work');
 const drop=page({answer});drop.c.confirm=()=>true;drop.run(seed);const fresh=await drop.run(`builderOpenFromVm('${VM_PATH}')`);assert.match(fresh.yaml,/changed on the VM/);assert.equal(drop.c.draftList(drop.store).length,1);
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
 const dir=path.join(__dirname,'../app/static/lab-builder/assets'),code=fs.readdirSync(dir).filter(f=>f.endsWith('.js')).map(f=>fs.readFileSync(path.join(dir,f),'utf8')).join('\n');
 // Context menu entries and palette tabs get their test id from a template (`context-menu-item-${id}`,
 // `panel-tab-${id}`): the bundle then holds the template and the id, not the joined string.
 for(const id of ids){const item=/^(context-menu-item|panel-tab)-(.+)$/.exec(id);assert.ok(item&&!code.includes(id)?code.includes(item[1]+'-${')&&code.includes('"'+item[2]+'"'):code.includes(id),'the bundled editor no longer has '+id);}
 assert.doesNotMatch(code,/new Function\(|\beval\(/,'the bundle must run under script-src self');
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
