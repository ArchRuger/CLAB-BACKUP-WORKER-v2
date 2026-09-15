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
 assert.match(gitFolderChoice(model,'bgp/latest','bgp').reason,/fills latest folders itself/);
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
 assert.match(latest,/Save details: devices, checksums, capture time/);assert.match(latest,/Device configuration/);
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
