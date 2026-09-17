const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const sources=['git-progress.js','git-places.js'].map(name=>fs.readFileSync(path.join(__dirname,'../app/static/'+name),'utf8'));
const same=(actual,expected)=>assert.equal(JSON.stringify(actual),JSON.stringify(expected));
function makeContext(){
 const context=vm.createContext({$:()=>null,state:{labs:[],jobs:[],git_jobs:[],platforms:{}},activeId:'lab',
  esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  utcDisplay:value=>new Date(value).toISOString(),platformLabel:()=>'EOS',crypto:{getRandomValues:bytes=>bytes.fill(1)},
  sessionStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},refresh:async()=>{},clearTimeout:()=>{},setTimeout:()=>0});
 for(const source of sources)vm.runInContext(source,context);
 return context;
}
const files=[{path:'README.md',size:12},{path:'bgp/latest/PE1.cfg',size:100},{path:'bgp/latest/manifest.json',size:300},{path:'bgp/checkpoints/peering/PE1.cfg',size:90},{path:'bgp/checkpoints/peering/manifest.json',size:300},{path:'bgp/docs/readme.md',size:10},{path:'notes/week1.md',size:5}];
const folders=[{id:'bgp',label:'repo / bgp',prefix:'bgp',lab:{id:'lab',name:'BGP lab'}},{id:'eth',label:'repo / eth',prefix:'eth',lab:{id:'other',name:'Ethernet lab'}},{id:'free',label:'repo / free',prefix:'free',lab:null}];

test('the tree model nests committed files, sorts them and marks lab and managed folders',()=>{
 const {gitTreeModel}=makeContext(),model=gitTreeModel(files,folders);
 same(model.root.dirs.map(d=>d.name),['bgp','eth','free','notes']);
 const bgp=model.nodes.get('bgp');assert.equal(bgp.registration.id,'bgp');assert.equal(bgp.count,5);assert.equal(bgp.size,800);assert.equal(bgp.pending,false);
 same(bgp.dirs.map(d=>d.managed),['checkpoints','','latest']);assert.equal(model.nodes.get('bgp/checkpoints/peering').managed,'checkpoint');
 assert.equal(model.nodes.get('eth').pending,true);assert.equal(model.nodes.get('free').pending,true);
 same(model.nodes.get('bgp/latest').files.map(f=>f.name),['manifest.json','PE1.cfg']);
 assert.equal(gitTreeModel([{path:'/etc/passwd',size:1},{path:'x/',size:1},null],[{prefix:5}]).root.dirs.length,0);
});
test('path chips start at the repository root',()=>{
 const {gitPathChips}=makeContext();
 same(gitPathChips('courses/bgp'),[{name:'',path:''},{name:'courses',path:'courses'},{name:'bgp',path:'courses/bgp'}]);
 same(gitPathChips(''),[{name:'',path:''}]);
});
test('folder rules: own, other lab, inside, managed, unused, root versus subfolders',()=>{
 const {gitTreeModel,gitFolderChoice,gitCanCreateIn}=makeContext(),model=gitTreeModel(files,folders);
 assert.equal(gitFolderChoice(model,'bgp','bgp').allowed,false);assert.match(gitFolderChoice(model,'bgp','bgp').reason,/already saves here/);
 assert.match(gitFolderChoice(model,'eth','bgp').reason,/Ethernet lab already saves here/);
 assert.match(gitFolderChoice(model,'bgp/latest','bgp').reason,/latest folder/);
 assert.match(gitFolderChoice(model,'bgp/checkpoints/peering','other').reason,/saved milestone/);
 assert.match(gitFolderChoice(model,'bgp/docs','other').reason,/inside BGP lab's lab folder/);
 assert.equal(gitFolderChoice(model,'bgp/docs','bgp').allowed,true,'a lab may move deeper inside its own folder; the old registration is retired');
 assert.match(gitFolderChoice(model,'eth','other').reason,/already saves here/);
 assert.equal(gitFolderChoice(model,'free','bgp').allowed,true);
 assert.equal(gitFolderChoice(model,'notes','bgp').allowed,true);
 assert.match(gitFolderChoice(model,'','bgp').reason,/already has lab folders/);
 assert.match(gitFolderChoice(model,'missing','bgp').reason,/Choose a folder/);
 const rooted=gitTreeModel([{path:'latest/PE1.cfg',size:1},{path:'docs/a.md',size:1}],[{id:'root',label:'repo',prefix:'',lab:{id:'lab',name:'Root lab'}}]);
 assert.equal(gitFolderChoice(rooted,'docs','root').allowed,true,'a root lab may move into a subfolder because its old registration is retired');
 assert.match(gitFolderChoice(rooted,'docs','other').reason,/inside Root lab's lab folder/);
 assert.equal(gitCanCreateIn(model,'','bgp'),true);assert.equal(gitCanCreateIn(model,'notes','bgp'),true);assert.equal(gitCanCreateIn(model,'eth','bgp'),false);assert.equal(gitCanCreateIn(model,'bgp','bgp'),true);assert.equal(gitCanCreateIn(rooted,'docs','other'),false);
});
test('folder names are literal single segments',()=>{
 const {gitFolderName,gitSuggestedFolder}=makeContext();
 assert.equal(gitFolderName(' bgp-lab.v2 '),'bgp-lab.v2');
 for(const bad of ['','a/b','..','.git','.GIT','-x','a b','x'.repeat(182)])assert.throws(()=>gitFolderName(bad),/folder name/,bad);
 assert.equal(gitSuggestedFolder('BGP Theory to Practice!'),'BGP-Theory-to-Practice');assert.equal(gitSuggestedFolder('   '),'lab');
});
test('sizes read like a file browser',()=>{
 const {gitSize}=makeContext();
 assert.equal(gitSize(0),'0 B');assert.equal(gitSize(900),'900 B');assert.equal(gitSize(2048),'2.0 KB');assert.equal(gitSize(51200),'50 KB');assert.equal(gitSize(3*1048576),'3.0 MB');assert.equal(gitSize(-1),'');assert.equal(gitSize('x'),'');
});
test('the browser markup escapes names and labels and explains each folder',()=>{
 const context=makeContext(),attack='<img src=x onerror=alert(1)>';
 const model=context.gitTreeModel([{path:attack+'/latest/'+attack+'.cfg',size:10}],[{id:'evil',label:attack,prefix:attack,lab:{id:'o',name:attack}}]);
 const root=context.gitPlacesMarkup(model,{selected:'',current:'me',repoName:attack,head:'abcdef1234567890',saved:{latest:1789128000},truncated:true,canAct:true,connected:true});
 assert.doesNotMatch(root,/<img/);assert.match(root,/&lt;img src=x onerror=alert\(1\)&gt; saves here/);assert.match(root,/shortened to the first 4000 files/);assert.match(root,/as of commit abcdef1234/);
 const inside=context.gitPlacesMarkup(model,{selected:attack,current:'me',repoName:attack,head:'',saved:{},canAct:true,connected:true});
 assert.doesNotMatch(inside,/<img/);assert.match(inside,/Most recent save/);assert.match(inside,/aria-current="page">&lt;img/);assert.match(inside,/data-git-places-action="new" disabled/);
 const mine=context.gitTreeModel(files,folders),own=context.gitPlacesMarkup(mine,{selected:'bgp',current:'bgp',repoName:'repo',head:'a',saved:{latest:1},canAct:true,connected:true});
 assert.match(own,/data-git-places-action="use" disabled/);assert.match(own,/This lab already saves here/);assert.match(own,/Named milestones/);
 const latest=context.gitPlacesMarkup(mine,{selected:'bgp/latest',current:'bgp',repoName:'repo',head:'a',saved:{latest:1},canAct:true,connected:true});
 assert.match(latest,/Save details/);assert.match(latest,/Device configuration/);
 const fresh=context.gitPlacesMarkup(mine,{selected:'notes',current:'bgp',repoName:'repo',head:'a',saved:{},canAct:true,connected:false});
 assert.match(fresh,/data-git-places-action="use"  title="">Choose this folder/);
 assert.doesNotMatch(context.gitPlacesMarkup(mine,{selected:'',current:'',repoName:'repo',canAct:false}),/data-git-places-action/);
});
test('the connected card names the folder path and offers the switch and disconnect actions',()=>{
 const context=makeContext(),container={innerHTML:'',querySelectorAll:()=>[]};
 context.$=id=>id==='git-repository-content'?container:null;context.state.labs=[{id:'lab',name:'BGP <lab>'}];
 context.gitRenderRepository('lab',{binding:{binding_id:'repo',node_names:['r1'],repository:{label:'x',path:'/home/ben/labs/Course-Labs',remote:'origin',branch:'main',prefix:'bgp',push_url:'https://github.com/ben/Course-Labs.git',owner:'ben'}},supported_nodes:[{name:'r1',platform:'arista_ceos'}]},{repositories:[{id:'repo',label:'x',path:'/home/ben/labs/Course-Labs',owner:'ben',branch:'main',prefix:'bgp',revision:'r'}]});
 assert.match(container.innerHTML,/BGP &lt;lab&gt; saves to<\/span><code>Course-Labs<\/code>.*<code>bgp<\/code>.*<code>latest\/<\/code>/);
 assert.match(container.innerHTML,/data-git-repo-action="switch"/);assert.match(container.innerHTML,/data-git-repo-action="unlink"/);assert.match(container.innerHTML,/id="git-places-panel"/);assert.match(container.innerHTML,/data-git-repo-action="connect"/);
 assert.doesNotMatch(container.innerHTML,/<lab>/);
});
test('move jobs read as folder moves and open the latest folder',()=>{
 const {gitTargetLabel,gitTargetPath,gitDestination}=makeContext();
 assert.equal(gitTargetLabel({target:'move',snapshot_path:'courses/bgp/latest'}),'Folder move → courses/bgp');assert.equal(gitTargetLabel({target:'move',snapshot_path:'latest'}),'Folder move → repository root');
 assert.equal(gitTargetPath({target:'move',snapshot_path:'courses/bgp/latest'}),'latest');assert.equal(gitTargetLabel({target:'checkpoint',checkpoint:'x'}),'checkpoints/x');
 assert.equal(gitDestination({binding_id:'b',repository:{path:'/home/ben/labs/Course-Labs',prefix:'bgp',branch:'main'}}),'Course-Labs › bgp › latest/ · main');
});
test('choosing a folder in a repository the lab is not connected to prepares the form instead of moving',async()=>{
 const context=makeContext(),calls=[],container={innerHTML:'',querySelectorAll:()=>[]};let shown=0;
 context.gitLoadContext=async()=>({binding:{binding_id:'elsewhere',repository:{path:'/home/ben/labs/Other'}}});
 context.json=async(endpoint,method,payload)=>{calls.push({endpoint,method,payload});return {repository:{id:'new-folder',prefix:payload.prefix}};};
 context.gitShowRepository=async()=>{shown++;};context.notify=()=>{};
 const model=context.gitTreeModel(files,folders);
 await context.gitUseFolder('lab','notes',model,{repository:{id:'repo',path:'/home/ben/labs/Course-Labs'}});
 assert.equal(calls[0].endpoint,'/git/repositories/repo/folders');assert.equal(calls[0].payload.prefix,'notes');assert.equal(shown,1);
 context.$=id=>id==='git-repository-content'?container:null;
 context.gitRenderRepository('lab',{binding:null,supported_nodes:[]},{repositories:[{id:'repo',label:'x',path:'/p',owner:'ben',branch:'main',prefix:'',revision:'r'},{id:'new-folder',label:'x / notes',path:'/p',owner:'ben',branch:'main',prefix:'notes',revision:'r2'}]});
 assert.match(container.innerHTML,/<option value="new-folder" selected>/,'the chosen folder is preselected in the connection form');
 await context.gitUseFolder('lab','free',model,{repository:{id:'repo',path:'/home/ben/labs/Course-Labs'}});
 assert.equal(calls.length,1,'an existing registration is reused without a request');assert.equal(shown,2);
});
test('nested folder helpers validate each segment and preview the full destination',()=>{
 const {gitFolderPath,gitDestinationPreview,gitFolderName}=makeContext();
 assert.equal(gitFolderPath('Week-04/BGP/Final-State'),'Week-04/BGP/Final-State');
 assert.equal(gitFolderPath(' /Week-04//BGP/ '),'Week-04/BGP','trims and collapses stray slashes');
 assert.throws(()=>gitFolderPath(''),/Enter a folder name/);
 assert.throws(()=>gitFolderPath('ok/../escape'),/letters, numbers/);
 assert.throws(()=>gitFolderPath('ok/.git/x'),/letters, numbers/);
 assert.throws(()=>gitFolderName('a/b'),/without slashes/);
 assert.equal(gitDestinationPreview('CCNP-SP','Week-04/BGP/Final-State'),'CCNP-SP/Week-04/BGP/Final-State');
 assert.equal(gitDestinationPreview('','BGP-Lab'),'BGP-Lab');
 assert.equal(gitDestinationPreview('CCNP-SP','  '),'','an empty or invalid entry previews nothing');
 assert.equal(gitDestinationPreview('CCNP-SP','bad/..'),'');
});
test('a folder whose latest carries a restore artifact is appliable from the browser',()=>{
 const {gitTreeModel,gitPlacesMarkup}=makeContext();
 const restoreFiles=[
  {path:'labs/BGP-LAB/Broken/latest/PTX1.set',size:100},
  {path:'labs/BGP-LAB/Broken/latest/PTX1.jcfg',size:200},
  {path:'labs/BGP-LAB/Broken/latest/manifest.json',size:300},
  {path:'labs/BGP-LAB/working/latest/PTX1.set',size:100},        // no .jcfg -> not restorable
  {path:'labs/BGP-LAB/working/latest/manifest.json',size:300},
 ];
 const model=gitTreeModel(restoreFiles,[]);
 assert.equal(model.nodes.get('labs/BGP-LAB/Broken').restorable,true);
 assert.equal(model.nodes.get('labs/BGP-LAB/working').restorable,false);
 assert.equal(model.nodes.get('labs/BGP-LAB').restorable,false,'a parent folder is not itself restorable');
 // Apply shows for a restorable folder when the browser passes an apply handler.
 const shown=gitPlacesMarkup(model,{selected:'labs/BGP-LAB/Broken',canApply:true,canAct:true});
 assert.match(shown,/data-git-places-action="apply"/);
 assert.match(shown,/Apply to running lab/);
 // Hidden for a non-restorable folder or when applying is not offered.
 assert.doesNotMatch(gitPlacesMarkup(model,{selected:'labs/BGP-LAB/working',canApply:true,canAct:true}),/data-git-places-action="apply"/);
 assert.doesNotMatch(gitPlacesMarkup(model,{selected:'labs/BGP-LAB/Broken',canApply:false,canAct:true}),/data-git-places-action="apply"/);
});
test('saved versions come from the repository tree: this lab first, instructor folders beside it, apply only where a restore artifact exists',()=>{
 const context=makeContext();
 const versionFiles=[
  {path:'labs/BGP/work/latest/PE1.cfg',size:10},{path:'labs/BGP/work/latest/PE1.jcfg',size:20},{path:'labs/BGP/work/latest/manifest.json',size:5},
  {path:'labs/BGP/work/checkpoints/ospf-done/PE1.cfg',size:10},{path:'labs/BGP/work/checkpoints/ospf-done/manifest.json',size:5},
  {path:'labs/BGP/work/baseline/PE1.cfg',size:10},{path:'labs/BGP/work/baseline/manifest.json',size:5},
  {path:'labs/BGP/solution/latest/PE1.cfg',size:10},{path:'labs/BGP/solution/latest/PE1.jcfg',size:20},{path:'labs/BGP/solution/latest/manifest.json',size:5},
  {path:'labs/BGP/start/latest/PE1.cfg',size:10},{path:'labs/BGP/start/latest/manifest.json',size:5},
  {path:'labs/OTHER/latest/R1.cfg',size:10},{path:'labs/OTHER/latest/R1.jcfg',size:20},{path:'labs/OTHER/latest/manifest.json',size:5}];
 const versionFolders=[{id:'work',label:'repo / work',prefix:'labs/BGP/work',lab:{id:'lab',name:'BGP lab'}},{id:'other',label:'repo / other',prefix:'labs/OTHER',lab:{id:'o',name:'Other lab'}}];
 const tree={head:'a'.repeat(40),files:versionFiles,folders:versionFolders,saved:{latest:1789128000,baseline:1789100000,checkpoints:null},repository:{path:'/home/ben/labs/Course-Labs'}};
 const model=context.gitTreeModel(tree.files,tree.folders);
 const binding={binding_id:'work',repository:{path:'/home/ben/labs/Course-Labs',prefix:'labs/BGP/work',branch:'main'}};
 context.state.git_jobs=[{id:'cp',lab_id:'lab',target:'checkpoint',checkpoint:'ospf-done',status:'synced',note:'adjacencies up',created:'2026-09-11T12:00:00Z',finished:'2026-09-11T12:01:00Z'}];
 const groups=context.gitVersionGroups('lab',{binding},model,tree,null);
 assert.equal(groups.latest.length,1);assert.equal(groups.latest[0].name,'Latest');same(groups.latest[0].apply,{folder:'labs/BGP/work'});assert.equal(groups.latest[0].compare,false);same(groups.latest[0].view,{commit:tree.head,path:'latest'});
 assert.equal(groups.checkpoints[0].name,'ospf-done');assert.equal(groups.checkpoints[0].note,'adjacencies up');assert.equal(groups.checkpoints[0].apply,null);same(groups.checkpoints[0].view,{commit:tree.head,path:'checkpoints/ospf-done'});
 assert.equal(groups.baseline[0].name,'Baseline');same(groups.baseline[0].view,{commit:tree.head,path:'baseline'});
 same(groups.reference.map(r=>[r.caption,!!r.apply]),[['labs/BGP/solution',true],['labs/BGP/start',false]],'sibling folders with a latest save; apply only with a .jcfg');
 same(groups.reference.map(r=>r.view.path),['labs/BGP/solution/latest','labs/BGP/start/latest']);
 same(groups.others.map(r=>[r.name,r.caption,!!r.apply]),[['Other lab','labs/OTHER',true]],'other labs are listed under their own name');
 const rooted=context.gitTreeModel([{path:'latest/PE1.cfg',size:1},{path:'latest/PE1.jcfg',size:1},{path:'latest/manifest.json',size:1}],[{id:'root',label:'repo',prefix:'',lab:{id:'lab',name:'Root lab'}}]);
 const rootGroups=context.gitVersionGroups('lab',{binding:{binding_id:'root',repository:{path:'/p',prefix:''}}},rooted,{head:'b'.repeat(40),files:[],folders:[],saved:{}},null);
 same(rootGroups.latest[0].apply,{version:{type:'git',commit:'b'.repeat(40),path:'latest'}},'a lab saving at the top level applies its latest through the version path');
 const fromHistory=context.gitVersionGroups('lab',{binding},null,null,{versions:[{path:'labs/BGP/work/latest',commit:'c',connected:true,label:'x'},{path:'labs/BGP/solution/latest',commit:'c',connected:false,label:'solution · latest'}]});
 assert.equal(fromHistory.latest[0].name,'Latest');assert.equal(fromHistory.reference[0].caption,'labs/BGP/solution/latest');
 const el={innerHTML:'',querySelectorAll:()=>[]};context.$=id=>id==='git-saved-versions'?el:null;
 context.gitRenderVersions('lab',{binding},model,tree,null);
 assert.match(el.innerHTML,/<h3>Latest<\/h3>/);assert.match(el.innerHTML,/data-git-version-action="apply"/);assert.match(el.innerHTML,/Compare with my latest save/);assert.match(el.innerHTML,/Full history…/);assert.match(el.innerHTML,/Instructor and reference versions/);assert.match(el.innerHTML,/<summary>Other labs in this repository \(1\)<\/summary>/);
 assert.match(el.innerHTML,/No checkpoints yet/.test(el.innerHTML)?/No checkpoints yet/:/ospf-done/);
 context.gitRenderVersions('lab',{binding:null},null,null,null);assert.match(el.innerHTML,/Choose a save location first/);
});
test('recent saves rows explain each save and offer upload or keep-snapshot-only while one is pending',()=>{
 const context=makeContext();const list={innerHTML:'',querySelectorAll:()=>[]};context.$=id=>id==='git-saves-list'?list:null;
 const attack='<img src=x onerror=alert(1)>';
 const jobs=[{id:'p1',lab_id:'lab',status:'push_pending',target:'latest',commit:'abcdef1234567890',message:attack,created:'2026-09-11T12:00:00Z'},{id:'u1',lab_id:'lab',status:'dismissed',target:'update',created:'2026-09-11T11:00:00Z'},{id:'c1',lab_id:'lab',status:'synced',target:'checkpoint',checkpoint:'ospf-done',pushed:true,created:'2026-09-11T10:00:00Z'}];
 context.gitRenderSaves('lab',{binding:{binding_id:'b',repository:{path:'/home/ben/labs/Course-Labs',prefix:'bgp'}},jobs});
 assert.doesNotMatch(list.innerHTML,/<img/);assert.match(list.innerHTML,/&lt;img src=x/);
 assert.match(list.innerHTML,/data-git-job="p1"/);assert.match(list.innerHTML,/Saved on this VM — upload needs attention/);assert.match(list.innerHTML,/data-git-job-upload="p1">Upload now/);assert.match(list.innerHTML,/data-git-job-keep="p1">Keep snapshot only/);
 assert.match(list.innerHTML,/Repository updated/);assert.match(list.innerHTML,/Checkpoint &#39;ospf-done&#39; saved/,'the checkpoint name is escaped like every interpolation');assert.doesNotMatch(list.innerHTML,/data-git-job-upload="c1"/,'an uploaded save has nothing to upload');
 assert.match(list.innerHTML,/Course-Labs › bgp/);
 context.gitRenderSaves('lab',{binding:null,jobs:[]});assert.match(list.innerHTML,/Saves appear here once this lab has a save location/);
});
