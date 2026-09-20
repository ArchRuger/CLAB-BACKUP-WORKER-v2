const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const read=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8');
// A Storage like the browser's: string values, key(i), length.
function storage(){const map=new Map();return {getItem:k=>map.has(k)?map.get(k):null,setItem:(k,v)=>map.set(k,String(v)),removeItem:k=>map.delete(k),key:i=>[...map.keys()][i]??null,get length(){return map.size;}};}
function load(){const context=vm.createContext({console,crypto:require('node:crypto').webcrypto,TextEncoder,URLSearchParams,document:{getElementById:()=>null}});vm.runInContext(read('lab-builder-page.js'),context);vm.runInContext(read('operations.js'),context);
 // top-level const is not a property of the context; expose the tables the tests read
 for(const name of ['BUILDER_TEMPLATES','BUILDER_STARTERS','opLabels','opReviewCopy'])context[name]=vm.runInContext(name,context);
 return context;}
// The starters are a fixed, small YAML shape; read them without a YAML library so this file has no dependencies.
function starterShape(text){const nodes={},links=[];let node='';for(const line of text.split('\n')){let m;if((m=/^    ([A-Za-z0-9_.-]+):$/.exec(line))){node=m[1];nodes[node]={};}else if((m=/^      (kind|image): (.+)$/.exec(line)))nodes[node][m[1]]=m[2];else if((m=/^    - endpoints: \["([^"]+)", "([^"]+)"\]$/.exec(line)))links.push([m[1],m[2]]);}return {name:/^name: (.+)$/m.exec(text)[1],nodes,links};}

test('lab names follow the literal rule of the VM helper and stay short',()=>{
 const c=load();
 for(const good of ['lab1','My_Lab.v2','a','0start'])assert.equal(c.builderName(good),true,good);
 for(const bad of ['','-lead','.hidden','has space','a/b','../x','x'.repeat(61),7,null])assert.equal(c.builderName(bad),false,String(bad));
});
test('interface patterns count from one, or from the start the pattern names',()=>{
 const c=load();
 assert.equal(c.builderInterface('eth{n}',0),'eth1');assert.equal(c.builderInterface('eth{n}',2),'eth3');
 assert.equal(c.builderInterface('et-0/0/{n:0}',0),'et-0/0/0');assert.equal(c.builderInterface('Gi0/0/0/{n:0}',3),'Gi0/0/0/3');assert.equal(c.builderInterface('',1),'eth2');
});
test('starters are valid topologies whose links use each device interface once',()=>{
 const c=load();
 assert.equal(c.builderStarter('blank','empty').yaml,'name: empty\ntopology:\n  nodes: {}\n');assert.equal(c.builderStarter('blank','empty').annotations,'');
 for(const [id,nodes,links] of [['pair',2,1],['triangle',3,3]])for(const template of c.BUILDER_TEMPLATES){
  const made=c.builderStarter(id,'lab',template),doc={topology:starterShape(made.yaml)},ends=doc.topology.links.flat();
  assert.equal(Object.keys(doc.topology.nodes).length,nodes);assert.equal(doc.topology.links.length,links);assert.equal(new Set(ends).size,ends.length,'an interface is used twice: '+ends);
  for(const node of Object.values(doc.topology.nodes))assert.deepEqual(node,{kind:template.kind,image:template.image});
  assert.deepEqual(JSON.parse(made.annotations).nodeAnnotations.map(n=>n.id),Object.keys(doc.topology.nodes));
 }
 assert.match(c.builderStarter('triangle','x',c.BUILDER_TEMPLATES[1]).yaml,/"ptx1:et-0\/0\/0", "ptx2:et-0\/0\/0"/);
});
test('templates take the image this site already uses for their kind',()=>{
 const c=load(),list=c.builderTemplateList({arista_ceos:['n24l/ceos:4.35.0F','ceos:old'],nokia_srlinux:['ghcr.io/nokia/srlinux']});
 assert.equal(list.find(t=>t.kind==='arista_ceos').image,'n24l/ceos:4.35.0F');assert.equal(list.find(t=>t.kind==='linux').image,c.BUILDER_TEMPLATES.find(t=>t.kind==='linux').image);
 assert.ok(c.builderImages(list,{nokia_srlinux:['ghcr.io/nokia/srlinux']}).includes('ghcr.io/nokia/srlinux'));
});
test('a draft edited in another tab is never overwritten silently',()=>{
 const c=load(),s=storage();
 const first=c.draftWrite(s,{id:'new:lab',name:'lab',yaml:'name: lab\n',annotations:''},undefined);assert.equal(first.revision,1);
 const mine=c.draftWrite(s,{...first,yaml:'name: lab\n# mine\n'},first.revision);assert.equal(mine.revision,2);
 assert.throws(()=>c.draftWrite(s,{...first,yaml:'name: lab\n# the other tab\n'},first.revision),/another tab/);
 assert.equal(c.draftRead(s,'new:lab').yaml,'name: lab\n# mine\n');
 assert.deepEqual(Array.from(c.draftList(s),d=>d.id),['new:lab']);c.draftDelete(s,'new:lab');assert.equal(c.draftRead(s,'new:lab'),null);
 s.setItem('clab-builder:draft:broken','{not json');assert.equal(c.draftRead(s,'broken'),null);assert.equal(c.draftList(s).length,0);
 const full={...s,getItem:()=>null,setItem(){throw new Error('quota');}};assert.throws(()=>c.draftWrite(full,{id:'x',name:'x',yaml:'a'},undefined),/no room left/);
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
});
test('the first save publishes a new folder; later saves revise the versions that were opened',async()=>{
 const c=load(),hash=async t=>'sha:'+t;
 const first=await c.builderSaveRequest({root:'/srv/labs',yaml:'Y',annotations:' '},hash);
 assert.deepEqual(JSON.parse(JSON.stringify(first)),{action:'publish',options:{root:'/srv/labs',text:'Y'}});
 const again=await c.builderSaveRequest({root:'/srv/labs',yaml:'Y2',annotations:'A2',vm:{path:'/srv/labs/l/l.clab.yml',yaml:'Y',annotations:''}},hash);
 assert.deepEqual(JSON.parse(JSON.stringify(again)),{action:'revise',path:'/srv/labs/l/l.clab.yml',options:{text:'Y2',annotations:'A2',base:{yaml:'sha:Y',annotations:''}}});
 assert.equal(await c.builderHash('abc'),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
});
test('the builder opens in the folder being browsed, else in the project folder',()=>{
 const c=load(),roots=['/etc/containerlab','/srv/containerlab-node-manager/projects'];
 assert.equal(c.opBuilderRoot('/etc/containerlab/course/week1',roots),'/etc/containerlab');assert.equal(c.opBuilderRoot('',roots),'/srv/containerlab-node-manager/projects');
 assert.equal(c.opBuilderRoot('/etc/containerlabs',roots),'/srv/containerlab-node-manager/projects');assert.equal(c.opBuilderRoot('',undefined),'/srv/containerlab-node-manager/projects');
 assert.equal(c.opBuilderUrl({root:'/srv/x y',path:''}),'/static/lab-builder.html#root=%2Fsrv%2Fx+y');
 assert.equal(c.opLabels.publish,'Save lab to the VM');assert.match(c.opReviewCopy.revise.body(),/previous version is kept/);
});
// The page hides editor controls that cannot work in a builder by their test ids, because this editor
// version has no switch for them. When an editor upgrade renames one, this fails instead of the control
// silently coming back.
test('every editor control the page hides still exists in the bundled editor',()=>{
 const css=read('lab-builder.css'),ids=[...css.matchAll(/\[data-testid="([a-z-]+)"\]/g)].map(m=>m[1]);assert.ok(ids.length>=7,ids.join());
 const dir=path.join(__dirname,'../app/static/lab-builder/assets'),code=fs.readdirSync(dir).filter(f=>f.endsWith('.js')).map(f=>fs.readFileSync(path.join(dir,f),'utf8')).join('\n');
 for(const id of ids)assert.ok(code.includes(id),'the bundled editor no longer has '+id);
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
