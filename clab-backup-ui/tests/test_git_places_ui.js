const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const sources=['git-progress.js','git-places.js'].map(name=>fs.readFileSync(path.join(__dirname,'../app/static/'+name),'utf8'));
const same=(actual,expected)=>assert.equal(JSON.stringify(actual),JSON.stringify(expected));
const readStatic=name=>fs.readFileSync(path.join(__dirname,'../app/static/'+name),'utf8');
// The drawer that hosts the chooser and holds Save settings and All versions (the homes of the old Save location card and lists).
const drawersContext=()=>{const context=makeContext();for(const name of ['status.js','save-drawers.js'])vm.runInContext(readStatic(name),context);return context;};
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
test('folder rules: own, other lab, inside, managed, unused, root and subfolders side by side',()=>{
 const {gitTreeModel,gitFolderChoice,gitCanCreateIn}=makeContext(),model=gitTreeModel(files,folders);
 assert.equal(gitFolderChoice(model,'bgp','bgp').allowed,false);assert.match(gitFolderChoice(model,'bgp','bgp').reason,/already saves here/);
 assert.match(gitFolderChoice(model,'eth','bgp').reason,/Ethernet lab already saves here/);
 // bgp/latest holds manifest.json in the fixture, so choosing it now resolves to its parent (rule 3)
 // instead of the old "latest folder" wording; the target is the parent, and its own reason is folded in.
 assert.equal(gitFolderChoice(model,'bgp/latest','bgp').target,'bgp');
 assert.match(gitFolderChoice(model,'bgp/latest','bgp').reason,/This is the saved state of bgp\. Saves go to bgp\/latest\. This lab already saves here\./);
 assert.match(gitFolderChoice(model,'bgp/checkpoints/peering','other').reason,/saved milestone/);
 // Lab folders may sit inside, above or beside another lab's folder (the VM refuses only a folder inside its saved state).
 same(JSON.parse(JSON.stringify(gitFolderChoice(model,'bgp/docs','other'))),{allowed:true,reason:'',target:'bgp/docs'});
 assert.equal(gitFolderChoice(model,'bgp/docs','bgp').allowed,true,'a lab may move deeper inside its own folder; the old registration is retired');
 assert.match(gitFolderChoice(model,'eth','other').reason,/already saves here/);
 same(JSON.parse(JSON.stringify(gitFolderChoice(model,'free','bgp'))),{allowed:true,reason:'',target:'free'},'a registration no lab uses is an ordinary folder: allowed, and never called "free"');
 assert.equal(gitFolderChoice(model,'notes','bgp').allowed,true);
 same(JSON.parse(JSON.stringify(gitFolderChoice(model,'','bgp'))),{allowed:true,reason:'',target:''},'the top level above other labs\' folders is a folder of its own');
 assert.match(gitFolderChoice(model,'missing','bgp').reason,/Choose a folder/);
 assert.equal(gitFolderChoice(model,'free','bgp').target,'free','every result names its own target, not only the resolved ones');
 const rooted=gitTreeModel([{path:'latest/PE1.cfg',size:1},{path:'docs/a.md',size:1}],[{id:'root',label:'repo',prefix:'',lab:{id:'lab',name:'Root lab'}}]);
 assert.equal(gitFolderChoice(rooted,'docs','root').allowed,true,'a root lab may move into a subfolder because its old registration is retired');
 assert.equal(gitFolderChoice(rooted,'docs','other').allowed,true,'another lab may save in a subfolder beside a lab at the top level');
 // Still refused: a folder inside a saved state (here a planned folder below another lab's latest, which holds no manifest yet).
 const planned=gitTreeModel(files,folders,['eth/latest/notes']),below=gitFolderChoice(planned,'eth/latest/notes','bgp');
 assert.equal(below.allowed,false);assert.equal(below.reason,'This folder is inside eth/latest, where a lab’s saves are kept. Choose a folder outside it.');
 assert.equal(gitCanCreateIn(model,'','bgp'),true);assert.equal(gitCanCreateIn(model,'notes','bgp'),true);assert.equal(gitCanCreateIn(model,'eth','bgp'),true,'New folder works inside another lab\'s folder');assert.equal(gitCanCreateIn(model,'bgp','bgp'),true);assert.equal(gitCanCreateIn(rooted,'docs','other'),true);assert.equal(gitCanCreateIn(model,'bgp/docs','other'),true);
 assert.equal(gitCanCreateIn(model,'bgp/latest','bgp'),false,'nothing is created inside a saved configuration');
 assert.equal(gitCanCreateIn(model,'bgp/checkpoints','other'),false,'nor in a saved-state folder of another lab');assert.equal(gitCanCreateIn(planned,'eth/latest','bgp'),false);assert.equal(gitCanCreateIn(planned,'eth/latest/notes','bgp'),false,'nor below one');
});
test('the owner\'s defect (1.30.59): a repository registered at its top level by guided setup, used by no lab, is an ordinary folder',()=>{
 const context=makeContext(),files=[{path:'README.md',size:12},{path:'docs/notes.md',size:5}],folders=[{id:'setup-root',label:'Archtop-Lab',prefix:'',lab:null}];
 const model=context.gitTreeModel(files,folders,['UX-TEST-003']);
 for(const current of ['','other-binding']){   // the lab is not connected yet ('' as git-progress.js passes it), or saves elsewhere
  assert.equal(context.gitFolderTag(model.root,current),'','no tag on the top level');assert.equal(context.gitFolderTag(model.root,current,true),'');
  for(const path of ['','docs','UX-TEST-003']){
   assert.equal(context.gitCanCreateIn(model,path,current),true,'New folder… is enabled in '+(path||'the top level'));
   same(JSON.parse(JSON.stringify(context.gitFolderChoice(model,path,current))),{allowed:true,reason:'',target:path});
  }
  // The chooser (the old folder browser went with the tab): the manager's answers for such a repository are all `free`.
  for(const selected of ['','docs','UX-TEST-003']){
   const html=markup(context,chooserTree([ans(''),ans('docs'),ans('UX-TEST-003',{exists:false})],{files}),{value:selected,selected,repoName:'Archtop-Lab',labName:'UX-TEST-003'});
   assert.match(html,/<button type="button" class="button secondary small" data-folder-action="new" data-folder-parent="[^"]*">New folder…<\/button>/,'New folder… is enabled');
   assert.deepEqual(buttonsOf(html),['Cancel','Save here']);assert.doesNotMatch(foot(html),/disabled/);
   assert.doesNotMatch(html,/Lab folder/);assert.doesNotMatch(html,/class="git-folder-icon lab/);
   assert.doesNotMatch(html,/free|another lab|cannot be created|already has lab folders|cannot be used here/i,'no text calls it free or another lab\'s folder, and nothing contradicts that');
  }
 }
 // Once a lab is connected to that registration it is that lab's folder again, as before.
 const used=context.gitTreeModel(files,[{id:'setup-root',label:'Archtop-Lab',prefix:'',lab:{id:'lab-2',name:'UX-TEST-002'}}]);
 assert.match(context.gitFolderTag(used.root,''),/UX-TEST-002/);assert.match(context.gitFolderChoice(used,'','').reason,/^UX-TEST-002 already saves here\.$/);
 assert.equal(context.gitFolderChoice(used,'docs','').allowed,true,'and a folder below it is still a place of its own');assert.equal(context.gitCanCreateIn(used,'','',),true);
});
test('selecting a snapshot folder named latest resolves to its parent; any other snapshot folder is refused outright',()=>{
 const {gitTreeModel,gitFolderChoice}=makeContext();
 const model=gitTreeModel([
  {path:'working/latest/PE1.cfg',size:1},{path:'working/latest/manifest.json',size:1},   // the reported defect: an unregistered "latest" snapshot
  {path:'course/lab/latest/PE1.cfg',size:1},{path:'course/lab/latest/manifest.json',size:1},
  {path:'Final/PE1.cfg',size:1},{path:'Final/manifest.json',size:1},                     // a snapshot under any other name
 ],[{id:'lab-bind',prefix:'course/lab',lab:{id:'lab',name:'Course lab'}}]);
 // Unregistered parent: the choice resolves to "working", not "working/latest" (no lab folder ever nests inside its own snapshot).
 const resolved=gitFolderChoice(model,'working/latest','someone');
 assert.equal(resolved.target,'working');assert.equal(resolved.allowed,true);assert.match(resolved.reason,/This is the saved state of working\. Saves go to working\/latest\./);
 // The registered current lab's own latest resolves to its own folder, and reports that it already saves there.
 const own=gitFolderChoice(model,'course/lab/latest','lab-bind');
 assert.equal(own.target,'course/lab');assert.equal(own.allowed,false);assert.match(own.reason,/This lab already saves here\./);
 // Any other snapshot folder is not a destination.
 const final=gitFolderChoice(model,'Final','someone');
 assert.equal(final.allowed,false);assert.equal(final.target,'Final');
 assert.match(final.reason,/This folder is a saved configuration \(it holds manifest\.json\)\. Choose the folder above it or a folder beside it\./);
});
test('a folder below a saved configuration is refused too, walking every ancestor for manifest.json, with the manager\'s own sentence naming the ancestor',()=>{
 const {gitTreeModel,gitFolderChoice,gitCanCreateIn}=makeContext();
 const model=gitTreeModel([{path:'Final/manifest.json',size:1},{path:'Final/sub/notes.txt',size:1},{path:'Final/sub/deeper/notes.txt',size:1}],[]);
 const below=gitFolderChoice(model,'Final/sub','someone');
 assert.equal(below.allowed,false);assert.equal(below.target,'Final/sub');
 assert.match(below.reason,/^Final is a saved configuration \(it holds manifest\.json\)\. Choose the folder above it or a folder beside it\.$/,'the manager\'s own sentence, naming the ancestor, not "This folder"');
 assert.equal(gitCanCreateIn(model,'Final/sub','someone'),false,'nothing can be created below a saved configuration either');
 // Any depth below the snapshot is refused, not only its direct child.
 const deeper=gitFolderChoice(model,'Final/sub/deeper','someone');
 assert.equal(deeper.allowed,false);assert.match(deeper.reason,/^Final is a saved configuration/);
 // Above the snapshot (the repository root, not itself an ancestor conflict for its own children other than Final) is unaffected.
 assert.equal(gitFolderChoice(model,'','someone').allowed,true);
});
test('folder names are literal single segments',()=>{
 const {gitFolderName,folderClean}=makeContext();
 assert.equal(gitFolderName(' bgp-lab.v2 '),'bgp-lab.v2');
 for(const bad of ['','a/b','..','.git','.GIT','-x','a b','x'.repeat(182)])assert.throws(()=>gitFolderName(bad),/folder name/,bad);
 // The folder suggested for a lab is the manager's (clean_folder of its name, the first free one); the page's echo agrees with it.
 assert.equal(folderClean('BGP Theory to Practice!'),'BGP-Theory-to-Practice');assert.equal(folderClean('   '),'');
});
test('sizes read like a file browser',()=>{
 const {gitSize}=makeContext();
 assert.equal(gitSize(0),'0 B');assert.equal(gitSize(900),'900 B');assert.equal(gitSize(2048),'2.0 KB');assert.equal(gitSize(51200),'50 KB');assert.equal(gitSize(3*1048576),'3.0 MB');assert.equal(gitSize(-1),'');assert.equal(gitSize('x'),'');
});
test('the chooser escapes names and labels and says what each folder is',()=>{
 const context=makeContext(),attack='<img src=x onerror=alert(1)>';
 const tree=chooserTree([ans(''),ans(attack,{kind:'lab',lab:{id:'o',name:attack},mark:attack+' saves here',beside:attack+'/me'})],{files:[{path:attack+'/latest/'+attack+'.cfg',size:10},{path:attack+'/latest/manifest.json',size:1}],truncated:true,dirs_truncated:true});
 const root=markup(context,tree,{value:'',selected:'',repoName:attack,expanded:new Set(['',attack])});
 assert.doesNotMatch(root,/<img/);assert.match(root,/&lt;img src=x onerror=alert\(1\)&gt; saves here/);assert.match(root,/This repository is very large and not every folder is listed/);
 // New folder… works inside another lab's folder, and a lab folder never lists latest, baseline or checkpoints as places.
 const inside=markup(context,tree,{value:attack,selected:attack,repoName:attack,expanded:new Set(['',attack])});
 assert.doesNotMatch(inside,/<img/);assert.match(inside,/data-folder-action="new" data-folder-parent="&lt;img src=x onerror=alert\(1\)&gt;">New folder…/);assert.doesNotMatch(inside,/data-folder-action="new"[^>]* disabled/);
 assert.doesNotMatch(inside,/data-folder="[^"]*\/latest"/,'the saved-state folders of a lab folder are not offered as places');
 const mine=markup(context,chooserTree(baseFolders()),{value:'BGP',selected:'BGP'});
 assert.match(mine,/restore-square already saves here\./);assert.deepEqual(buttonsOf(mine),['Cancel','Keep saving here']);
 const fresh=markup(context,chooserTree(baseFolders()),{value:'notes',selected:'notes'});
 assert.deepEqual(buttonsOf(fresh),['Cancel','Save here']);
 // Browsing lists what a folder holds, files included, and changes nothing.
 const browse=markup(context,chooserTree(baseFolders()),{mode:'browse',value:'BGP',selected:'BGP/latest',expanded:new Set(['','BGP'])});
 assert.match(browse,/manifest\.json/);assert.match(browse,/PE1\.cfg/);assert.doesNotMatch(browse,/id="folder-foot"|Save here/);
});
test('an empty folder made through the manager stays in the tree, is told apart from a saved one, and can be chosen',()=>{
 const context=makeContext(),lab=[{id:'j2',label:'repo / JunOS-TEST-2',prefix:'JunOS-TEST-2',lab:{id:'lab',name:'Junos lab'}}];
 const without=context.gitTreeModel([{path:'JunOS-TEST-2/latest/r1.cfg',size:10}],lab);
 assert.equal(without.nodes.has('JunOS-TEST-2/working'),false,'this is the reported defect: nothing but the manager remembers an empty folder');
 const model=context.gitTreeModel([{path:'JunOS-TEST-2/latest/r1.cfg',size:10}],lab,['JunOS-TEST-2/working','JunOS-TEST-2/solution/week-1','JunOS-TEST-2','/bad','',7]);
 same(model.nodes.get('JunOS-TEST-2').dirs.map(d=>d.name),['latest','solution','working']);
 const working=model.nodes.get('JunOS-TEST-2/working');assert.equal(working.planned,true);assert.equal(working.pending,true);assert.equal(working.registration,null);
 assert.equal(model.nodes.get('JunOS-TEST-2').pending,false,'a planned folder that holds saved files is an ordinary folder');assert.equal(model.nodes.get('JunOS-TEST-2/solution').pending,false,'an unplanned parent is not flagged');assert.equal(model.nodes.get('JunOS-TEST-2/solution/week-1').pending,true);
 assert.equal(model.nodes.has('/bad'),false);assert.equal(model.nodes.size,6);
 const choice=context.gitFolderChoice(model,'JunOS-TEST-2/working','j2');assert.equal(choice.allowed,true,'a folder inside the lab\'s own folder is a valid destination for that lab');
 assert.equal(context.gitFolderChoice(model,'JunOS-TEST-2/working','someone-else').allowed,true,'and another lab may save in it too: lab folders may sit inside each other');
 // In the chooser a planned folder is marked New, is said to appear with the first save, and offers its removal from the list.
 const tree=chooserTree([ans(''),ans('JunOS-TEST-2',{kind:'own',mark:'This lab saves here'}),ans('JunOS-TEST-2/working',{exists:false}),ans('JunOS-TEST-2/solution')],{files:[{path:'JunOS-TEST-2/latest/r1.cfg',size:10},{path:'JunOS-TEST-2/solution/week-1/a.txt',size:1}]});
 const inside=markup(context,tree,{value:'JunOS-TEST-2/working',selected:'JunOS-TEST-2/working',expanded:new Set(['','JunOS-TEST-2'])});
 assert.match(inside,/data-folder="JunOS-TEST-2\/working"[^>]*><span class="folder-row">.*?<i class="git-folder-icon pending"><\/i><span class="folder-name">working<\/span><b class="git-tag pending">New<\/b>/);
 assert.match(inside,/JunOS-TEST-2\/working is new\. It appears in the repository with the first save\./);assert.deepEqual(buttonsOf(inside),['Cancel','Save here']);
 assert.match(inside,/data-folder-action="forget" data-folder-path="JunOS-TEST-2\/working">Remove from the list</);
 assert.doesNotMatch(markup(context,tree,{value:'JunOS-TEST-2/solution',selected:'JunOS-TEST-2/solution',expanded:new Set(['','JunOS-TEST-2'])}),/data-folder-action="forget"/,'a folder that is in the repository is not removable');
});
test('New folder…: a row in the tree at the place the folder will be; adding never changes where the lab saves; a name that exists is selected, never refused',()=>{
 const context=makeContext();
 // The button names the folder being looked at; the click and the keys become actions the drawer applies (POST …/folders/new).
 let html=markup(context,chooserTree(baseFolders()),{value:'BGP',selected:'BGP',expanded:new Set(['','BGP'])});
 assert.match(html,/data-folder-action="new" data-folder-parent="BGP">New folder…/);
 const button={dataset:{folderAction:'new',folderParent:'BGP'},disabled:false,closest(sel){return sel.includes('data-folder-action')?button:null;}};
 same(context.folderChooserEvent('click',{target:button}),{action:'new-folder',parent:'BGP'});
 html=markup(context,chooserTree(baseFolders()),{value:'BGP',selected:'BGP',expanded:new Set(['','BGP']),newFolder:{parent:'BGP',value:'solution'}});
 assert.match(html,/<li role="none" class="folder-new"><label class="sr-only" for="folder-new">New folder in BGP<\/label><input id="folder-new"[^>]*value="solution"><button[^>]*data-folder-action="new-add">Add<\/button><button[^>]*data-folder-action="new-cancel">Cancel<\/button><\/li>/);
 assert.match(html,/restore-square already saves here\./,'the destination is still the lab’s own: browsing and creating never change it');
 // A name that already exists is selected and said, never refused.
 html=markup(context,chooserTree(baseFolders()),{value:'BGP/week-2',selected:'BGP/week-2',expanded:new Set(['','BGP']),notice:'BGP/week-2 already exists. It is selected.'});
 assert.match(liveRegion(html),/^BGP\/week-2 already exists\. It is selected\./);assert.doesNotMatch(html,/id="folder-refused"/);
 const drawers=readStatic('save-drawers.js');
 assert.match(drawers,/'\/git\/repositories\/'\+drwEnc\(c\.repository\)\+'\/folders\/new','POST',\{lab_id:id,parent,name\}/);
});
test('the outline opens and closes by the student\'s own state: ancestors of the save location collapse, other branches stay open, selection never closes anything',()=>{
 const context=makeContext(),tree=[{path:'labs/BGP/work/latest/r1.cfg',size:1},{path:'labs/BGP/start/latest/r1.cfg',size:1},{path:'labs/VLAN/latest/s1.cfg',size:1},{path:'notes/a.md',size:1}];
 const model=context.gitTreeModel(tree,[{id:'me',prefix:'labs/BGP/work',lab:{id:'lab',name:'BGP'}}]);
 same(context.gitAncestors('labs/BGP/work'),['','labs','labs/BGP']);same(context.gitAncestors(''),['']);same(context.gitAncestors('x'),['']);
 const expanded=context.gitDefaultExpanded(model,'me');same([...expanded].sort(),['','labs','labs/BGP','labs/BGP/work'],'the first display leads to the folder the lab saves to');
 same([...context.gitDefaultExpanded(model,'nobody')],[''],'a lab without a folder here starts with the top level only');
 // The chooser's tree draws exactly this set: an ancestor of the save location can be collapsed and stays collapsed, another branch
 // opens without touching that, and selecting a folder never opens or closes one.
 const answers=[ans(''),ans('labs'),ans('labs/BGP'),ans('labs/BGP/work',{kind:'own',mark:'This lab saves here'}),ans('labs/BGP/start'),ans('labs/VLAN'),ans('notes')];
 const draw=(selected='labs/BGP/work')=>markup(context,chooserTree(answers,{files:tree}),{value:selected,selected,expanded});
 const openOf=html=>[...html.matchAll(/aria-expanded="true"[^>]*data-folder="([^"]*)"/g)].map(m=>m[1]);
 same(openOf(draw()),['','labs','labs/BGP']);
 context.gitToggleFolder(expanded,'labs/BGP');let html=draw();
 same(openOf(html),['','labs']);assert.doesNotMatch(html,/data-folder="labs\/BGP\/work"/,'its children are not drawn');
 context.gitToggleFolder(expanded,'labs/VLAN');html=draw('notes');
 same(openOf(html).sort(),['','labs','labs/VLAN'].sort(),'the other branch opened; selecting notes opened nothing more and closed nothing');assert.doesNotMatch(html,/aria-expanded="true"[^>]*data-folder="labs\/BGP"/);
 assert.match(html,/aria-selected="true"[^>]*data-folder="notes"/);
 context.gitToggleFolder(expanded,'labs/BGP');html=draw('labs/BGP/start');
 assert.match(html,/data-folder="labs\/BGP\/work"[^>]*>.*?This lab saves here/);assert.match(html,/aria-selected="true"[^>]*data-folder="labs\/BGP\/start"/);
 // The top level cannot be closed, leaves have no twisty, a refresh keeps what still exists
 context.gitToggleFolder(expanded,'');assert.ok(expanded.has(''));assert.doesNotMatch(html,/data-folder-twist=""/);
 expanded.add('gone/folder');same([...context.gitKeepExpanded(expanded,model)].includes('gone/folder'),false);assert.ok(context.gitKeepExpanded(expanded,model).has('labs/VLAN'));
 assert.doesNotMatch(markup(context,chooserTree([ans(''),ans('<img src=x>')],{files:[{path:'<img src=x>/sub/a.cfg',size:1}]}),{value:'',selected:'',expanded:new Set(['','<img src=x>'])}),/<img/);
});
test('the chooser keeps branches, selection and focus across a refresh of the same repository and starts another one from its own default',()=>{
 const context=makeContext();
 const answers=[ans(''),ans('labs'),ans('labs/BGP'),ans('labs/BGP/work',{kind:'own',mark:'This lab saves here'}),ans('labs/VLAN')];
 const files=[{path:'labs/BGP/work/latest/r1.cfg',size:1},{path:'labs/VLAN/notes/s1.cfg',size:1}];
 const first=context.folderChooserModel(chooserTree(answers,{files}));
 // The first display leads to the folder the lab saves to; after that the set belongs to the person.
 const expanded=context.folderDefaultExpanded(first);same([...expanded].sort(),['','labs','labs/BGP','labs/BGP/work']);
 context.gitToggleFolder(expanded,'labs/BGP');context.gitToggleFolder(expanded,'labs/VLAN');
 // A refresh brings a new tree (one more file); the host passes the same set, so nothing reopens and nothing closes.
 const again=context.folderChooserModel(chooserTree(answers,{files:[...files,{path:'labs/BGP/work/latest/r2.cfg',size:1}]}));
 const html=context.folderChooserMarkup(again,view({value:'labs/BGP/work',selected:'labs/BGP/work',expanded}));
 same([...html.matchAll(/aria-expanded="true"[^>]*data-folder="([^"]*)"/g)].map(m=>m[1]).sort(),['','labs','labs/VLAN']);
 assert.match(html,/aria-expanded="false"[^>]*data-folder="labs\/BGP"/,'the collapsed ancestor of the save location stays collapsed');
 // The drawer keeps the set in its own state and rebuilds only what changed, handing focus back (drwSet).
 const drawers=readStatic('save-drawers.js');
 assert.match(drawers,/c\.expanded=c\.model&&typeof folderDefaultExpanded==='function'\?folderDefaultExpanded\(c\.model\):new Set\(\[''\]\)/,'set once, when a repository is loaded');
 assert.match(drawers,/case 'toggle':if\(typeof gitToggleFolder==='function'\)gitToggleFolder\(c\.expanded,intent\.path\)/);
 // Another repository starts from its own default.
 same([...context.folderDefaultExpanded(context.folderChooserModel(chooserTree([ans(''),ans('x',{kind:'own'})],{files:[{path:'x/latest/a.cfg',size:1}]})))].sort(),['','x']);
});
test('Save settings names the folder path and offers Change folder…, the switch and the disconnect actions',()=>{
 const context=drawersContext();
 const html=context.saveSettingsMarkup('lab',{binding:{binding_id:'repo',node_names:['r1'],repository:{label:'x',path:'/home/ben/labs/Course-<Labs>',remote:'origin',branch:'main',prefix:'bgp',push_url:'https://github.com/ben/Course-Labs.git',owner:'ben'}},supported_nodes:[{name:'r1',platform:'arista_ceos'}],unsupported_nodes:[],repository_status:{ready:true}},{repositories:[]},{});
 assert.match(html,/<p class="git-destination-line"><code>Course-&lt;Labs&gt;<\/code>.*<code>bgp<\/code>.*<code>latest\/<\/code>/);
 assert.match(html,/data-save-action="folder">Change folder…/);assert.match(html,/data-git-repo-action="switch"/);assert.match(html,/data-git-repo-action="unlink"/);assert.match(html,/data-git-repo-action="connect"/);
 assert.doesNotMatch(html,/<Labs>/);
});
test('Save settings keeps its folds as the person left them and names its Git details; the folder chooser is one click away (Change folder…)',()=>{
 const context=drawersContext();
 const bound={binding:{binding_id:'repo',node_names:['r1'],repository:{label:'x',path:'/home/ben/labs/Course-Labs',remote:'origin',branch:'main',prefix:'bgp',push_url:'https://github.com/ben/Course-Labs.git',owner:'ben'}},supported_nodes:[{name:'r1',platform:'arista_ceos'}],unsupported_nodes:[],repository_status:{ready:true}};
 const render=()=>context.saveSettingsMarkup('lab',bound,{repositories:[]},{});
 assert.match(render(),/<details id="save-git-details" data-fold="settings:git" ><summary>Git details<\/summary>/,'folded on entry');
 assert.doesNotMatch(render(),/<summary>Technical details<\/summary>|git-change-folder/);
 vm.runInContext("saveDrawer.folds.set('settings:git',true)",context);
 assert.match(render(),/<details id="save-git-details" data-fold="settings:git" open>/,'a deliberate unfold survives the next render (the 4 s poll)');
 vm.runInContext("saveDrawer.folds.set('settings:git',false)",context);assert.match(render(),/data-fold="settings:git" >/);
 assert.match(readStatic('save-drawers.js'),/if\(action==='folder'\)\{saveDrawerOpen\('chooser',\{mode:'location',back:\{kind:'settings'/);
});
test('move jobs read as folder moves and open the latest folder',()=>{
 const {gitTargetLabel,gitTargetPath,gitFolderWords}=makeContext();
 assert.equal(gitTargetLabel({target:'move',snapshot_path:'courses/bgp/latest'}),'Folder move → courses/bgp');assert.equal(gitTargetLabel({target:'move',snapshot_path:'latest'}),'Folder move → repository root');
 assert.equal(gitTargetPath({target:'move',snapshot_path:'courses/bgp/latest'}),'latest');assert.equal(gitTargetLabel({target:'checkpoint',checkpoint:'x'}),'checkpoints/x');
 assert.equal(gitFolderWords({binding_id:'b',repository:{path:'/home/ben/labs/Course-Labs',prefix:'bgp',branch:'main'}}),'Course-Labs › bgp');
});
test('choosing a folder in a repository the lab is not connected to is one place request for that repository: no old folder route, no second form',()=>{
 const drawers=readStatic('save-drawers.js');
 assert.match(drawers,/const body=\{\.\.\.\(c\.address\?\{url\}:\{repository:c\.repository\}\),folder,choice:choice\|\|'',pending:pending\|\|''/);
 assert.match(drawers,/case 'repository':c\.repository=intent\.value;/,'the Repository select changes which repository the place request names');
 for(const name of ['git-progress.js','git-places.js','save-drawers.js','save-header.js'])assert.doesNotMatch(readStatic(name),/'\/folders','POST'|\/git','PUT'|\/git\/destination/,name);
 const context=makeContext();
 const html=markup(context,chooserTree(baseFolders()),{value:'notes',selected:'notes',repositories:[{id:'a',name:'Course-Labs'},{id:'b',name:'Other'}],repository:'b'});
 assert.match(html,/<option value="b" selected>Other<\/option>/);assert.deepEqual(buttonsOf(html),['Cancel','Save here']);
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
test('latest, baseline and checkpoints are reserved names inside a lab folder; a "latest" segment higher up is unrelated',()=>{
 const {gitFolderPath}=makeContext();
 for(const bad of ['latest','working/latest','x/baseline','x/checkpoints','x/checkpoints/one','Week-04/BGP/checkpoints/Final'])
  assert.throws(()=>gitFolderPath(bad),/latest, baseline and checkpoints are the folders a save writes/,bad);
 assert.equal(gitFolderPath('course/latest/working'),'course/latest/working','a "latest" segment that is not the last one or two segments is an ordinary folder name');
 assert.equal(gitFolderPath('checkpoints-log'),'checkpoints-log','only the exact reserved name is refused, not a name that merely contains it');
});
test('a folder is a saved configuration when it holds manifest.json, whatever its name or depth; a restore-shaped extension alone is not enough',()=>{
 const context=makeContext(),{gitTreeModel,gitApplySource,folderListingMarkup}=context;
 const manifestFiles=[
  {path:'labs/BGP-LAB/Final/PTX1.jcfg',size:200},{path:'labs/BGP-LAB/Final/manifest.json',size:300},         // holds manifest.json directly
  {path:'labs/BGP-LAB/Broken/latest/PTX1.jcfg',size:200},{path:'labs/BGP-LAB/Broken/latest/manifest.json',size:300}, // legacy convenience: only the latest/ child is a snapshot
  {path:'labs/BGP-LAB/Both/PTX1.jcfg',size:200},{path:'labs/BGP-LAB/Both/manifest.json',size:300},            // both the folder and its latest/ child are snapshots
  {path:'labs/BGP-LAB/Both/latest/PTX1.jcfg',size:200},{path:'labs/BGP-LAB/Both/latest/manifest.json',size:300},
  {path:'labs/BGP-LAB/eos/CEOS1.eoscfg',size:150},{path:'labs/BGP-LAB/eos/manifest.json',size:300},           // Arista EOS restore artifact, still needs the manifest
  {path:'labs/BGP-LAB/xr/XRV1.xrcfg',size:150},{path:'labs/BGP-LAB/xr/manifest.json',size:300},               // Cisco IOS XR restore artifact
  {path:'labs/BGP-LAB/NoManifest/PTX1.jcfg',size:200},                                                        // a .jcfg alone: no name pattern makes this a saved configuration
  {path:'manifest.json',size:300},                                                                            // the repository root can itself be a saved configuration
 ];
 const model=gitTreeModel(manifestFiles,[]);
 const final=model.nodes.get('labs/BGP-LAB/Final');assert.equal(final.snapshot,true);assert.equal(final.restorable,true);same(gitApplySource(final),{path:'/labs/BGP-LAB/Final'});
 const broken=model.nodes.get('labs/BGP-LAB/Broken');assert.equal(broken.snapshot,false);assert.equal(broken.latestSnapshot,true);assert.equal(broken.restorable,true,'the legacy parent convenience is still appliable');same(gitApplySource(broken),{path:'/labs/BGP-LAB/Broken/latest'});
 const both=model.nodes.get('labs/BGP-LAB/Both');assert.equal(both.snapshot,true);assert.equal(both.latestSnapshot,true);same(gitApplySource(both),{path:'/labs/BGP-LAB/Both'},'a folder that is itself a snapshot applies directly; nothing is substituted from its latest child');
 same(gitApplySource(model.nodes.get('labs/BGP-LAB/Both/latest')),{path:'/labs/BGP-LAB/Both/latest'},'the nested latest/ is also its own, separate, applyable row');
 assert.equal(model.nodes.get('labs/BGP-LAB/eos').restorable,true,'an EOS .eoscfg artifact is restorable once its folder holds manifest.json');
 assert.equal(model.nodes.get('labs/BGP-LAB/xr').restorable,true,'a Cisco IOS XR .xrcfg artifact is restorable once its folder holds manifest.json');
 const noManifest=model.nodes.get('labs/BGP-LAB/NoManifest');assert.equal(noManifest.snapshot,false);assert.equal(noManifest.restorable,false,'a restore-shaped extension without manifest.json is not a saved configuration');
 assert.equal(model.nodes.get('labs/BGP-LAB').restorable,false,'a parent folder is not itself restorable');
 assert.equal(model.root.snapshot,true);same(gitApplySource(model.root),{path:'/'},'the repository root is written "/" on the wire, never an empty string');
 // Browse the repository… offers Load this state… and View files for a folder that is or holds a saved state, from its exact source.
 const shown=folderListingMarkup(model,'labs/BGP-LAB/Final');
 assert.match(shown,/data-folder-action="load" data-folder-path="\/labs\/BGP-LAB\/Final">Load this state…<\/button>/);assert.match(shown,/data-folder-action="view" data-folder-path="\/labs\/BGP-LAB\/Final">View files/);
 assert.match(folderListingMarkup(model,'labs/BGP-LAB/Broken'),/data-folder-action="load" data-folder-path="\/labs\/BGP-LAB\/Broken\/latest">/,'a folder whose latest/ is the saved state loads that one');
 assert.doesNotMatch(folderListingMarkup(model,'labs/BGP-LAB/NoManifest'),/data-folder-action="load"/);assert.doesNotMatch(folderListingMarkup(model,'labs/BGP-LAB'),/data-folder-action="load"/);
});
test('Load this state… in Browse the repository… sends the exact resolved snapshot path, never a substituted one',()=>{
 const context=makeContext();
 const click=pathValue=>{const button={dataset:{folderAction:'load',folderPath:pathValue},disabled:false,closest(sel){return sel.includes('data-folder-action')?button:null;}};return context.folderChooserEvent('click',{target:button});};
 const model=context.gitTreeModel([{path:'Final/PTX1.jcfg',size:10},{path:'Final/manifest.json',size:10},{path:'Broken/latest/PTX1.jcfg',size:10},{path:'Broken/latest/manifest.json',size:10}],[]);
 const sources=['Final','Broken'].map(folder=>context.folderListingMarkup(model,folder).match(/data-folder-action="load" data-folder-path="([^"]*)"/)[1]);
 same(sources,['/Final','/Broken/latest']);
 same(sources.map(click),[{action:'load',path:'/Final'},{action:'load',path:'/Broken/latest'}]);
 // The drawer turns it into a folder source with the wire's one leading slash ('/' for the top level) and starts the confirmation.
 const drawers=readStatic('save-drawers.js');
 assert.match(drawers,/case 'load':\{const n=drwChooserNode\(intent\.path\);drwStartLoad\(\{type:'folder',commit:'',path:'\/'\+n\.path,backup_job_id:'',repository:n\.repository\},n\.name\);break;\}/);
 assert.match(drawers,/function drwChooserNode\(path\)\{\n const c=saveDrawer\.chooser,clean=drwBare\(path\)/);
});
test('saved versions come from the manager’s list of saved states: this lab first, then lab states, other labs folded; a lab without a save location is told so (All versions)',()=>{
 const context=drawersContext();context.gitWhen=value=>'when';
 const row=(pathValue,group,more={})=>({path:pathValue,commit:'c',name:pathValue.split('/').filter(part=>part!=='latest').pop(),group,lab:'',kind:'capture',saved_devices:1,loadable_devices:1,view_only:false,saved_at:'2026-09-11T12:00:00Z',...more});
 const list={head:'a'.repeat(40),lab_devices:1,states:[row('labs/BGP/work/latest','latest'),row('labs/BGP/work/checkpoints/ospf-done','checkpoint'),row('labs/BGP/work/baseline','baseline'),row('labs/BGP/Final','state',{name:'Final'}),row('labs/BGP/Broken/latest','state',{name:'Broken'}),
  row('labs/OTHER/latest','other-lab',{lab:'Other lab',name:'Other'}),row('zzz/old','state',{name:'Old',view_only:true,view_only_reason:'no-restore'})]};
 const html=context.saveVersionsMarkup({list,located:true,repoName:'Course-Labs',context:{repository_status:{}}});
 for(const heading of ['Your saves','Checkpoints','Starting point','Lab states'])assert.match(html,new RegExp('<h3 class="save-heading">'+heading+'</h3>'));
 assert.match(html,/<summary>Other labs in this repository \(1\)<\/summary>/);assert.match(html,/Full history…/);assert.match(html,/Browse the repository…/);
 assert.match(html,/<span>ospf-done<\/span>/);assert.match(html,/<span>Starting configuration<\/span>/);assert.match(html,/<span>Final<\/span>/);assert.match(html,/<span>Broken<\/span>/);
 assert.match(html,/View only: saved without the files needed to load it/,'a state that cannot be loaded says why');
 assert.doesNotMatch(html,/NoManifest/);
 assert.match(context.saveVersionsMarkup({list:null,located:false,repoName:''}),/This lab has not been saved yet\./);
});
test('recent saves: a waiting save offers Upload… and Details in its row, and every other save job is under Save activity (All versions)',()=>{
 const context=drawersContext();context.gitWhen=value=>'when';
 const attack='<img src=x onerror=alert(1)>';
 context.state.git_jobs=[{id:'p1',lab_id:'lab',status:'push_pending',target:'latest',commit:'abcdef1234567890',message:attack,note:attack,changed_files:['x'],snapshot_path:'bgp/latest',created:'2026-09-11T12:00:00Z'},
  {id:'u1',lab_id:'lab',status:'dismissed',target:'update',created:'2026-09-11T11:00:00Z'},{id:'c1',lab_id:'lab',status:'synced',pushed:true,target:'checkpoint',checkpoint:"ospf-done'",commit:'1234',created:'2026-09-11T10:00:00Z'}];
 vm.runInContext("saveDrawer.lab='lab';saveDrawer.openRow='job:p1';saveDrawer.folds.set('activity',true);",context);
 const html=context.saveVersionsMarkup({list:{head:'h',states:[]},located:true,repoName:'Course-Labs',context:{repository_status:{}}});
 assert.doesNotMatch(html,/<img/);assert.match(html,/&lt;img src=x/);
 assert.match(html,/<span class="save-why">Not uploaded yet<\/span>/);assert.match(html,/data-save-action="upload-job" data-save-row="job:p1" >Upload…/,'a waiting save is uploaded through What changed, never straight from its row');
 assert.match(html,/data-save-action="details" data-save-row="job:p1" >Details/);
 assert.match(html,/<summary>Save activity \(2\)<\/summary>/);assert.match(html,/Repository update/);assert.match(html,/Checkpoint &#39;ospf-done&#39;&#39;/,'the checkpoint name is escaped like every interpolation');
 assert.doesNotMatch(html,/data-save-action="upload-job" data-save-row="act:c1"/,'an uploaded save offers no upload');
});
test('the reverse direction: a folder is refused when another registered lab folder lies inside its saved states, naming that folder',()=>{
 const {gitTreeModel,gitFolderChoice,gitSavesHoldingLab}=makeContext();
 const model=gitTreeModel([{path:'course/readme.md',size:1}],[{id:'w',prefix:'course/latest/working',lab:{id:'x',name:'Other lab'}},{id:'mine',prefix:'mine',lab:{id:'lab',name:'My lab'}}]);
 const choice=gitFolderChoice(model,'course','mine');
 assert.equal(choice.allowed,false);assert.equal(choice.reason,'course/latest/working is a lab folder inside the place where this folder would keep its saves. Choose another folder.');
 assert.equal(gitSavesHoldingLab(model,'course','mine'),'course/latest/working');
 const unused=gitTreeModel([{path:'course/readme.md',size:1}],[{id:'w',prefix:'course/baseline',lab:null}]);
 assert.equal(gitFolderChoice(unused,'course','mine').allowed,false,'a registration no lab uses still counts for the VM');
 const top=gitTreeModel([{path:'a/b.md',size:1}],[{id:'w',prefix:'checkpoints/day',lab:{id:'x',name:'Other'}}]);
 assert.match(gitFolderChoice(top,'','mine').reason,/^checkpoints\/day is a lab folder inside/,'the top level has latest, baseline and checkpoints too');
 const own=gitTreeModel([{path:'course/readme.md',size:1}],[{id:'mine',prefix:'course/latest/working',lab:{id:'lab',name:'My lab'}}]);
 assert.equal(gitFolderChoice(own,'course','mine').allowed,true,'the asking lab\'s own registration is retired by the move, never a collision');
 const beside=gitTreeModel([{path:'course/readme.md',size:1}],[{id:'w',prefix:'course/latest2',lab:{id:'x',name:'Other'}},{id:'v',prefix:'course/docs',lab:{id:'y',name:'Third'}}]);
 assert.equal(gitFolderChoice(beside,'course','mine').allowed,true,'a folder merely beside or inside, not in a saved state, is fine');
});
test('New folder refusal: a name directly below a lab folder may not be latest, baseline or checkpoints',()=>{
 const {gitTreeModel,gitNewFolderRefusal}=makeContext(),model=gitTreeModel([{path:'eth/x.md',size:1},{path:'notes/a.md',size:1}],[{id:'e',prefix:'eth',lab:{id:'x',name:'Eth'}},{id:'u',prefix:'unused',lab:null}]);
 assert.match(gitNewFolderRefusal(model,'eth/latest/notes',''),/^eth is a lab folder, and latest inside it is where it keeps its saves/);
 assert.equal(gitNewFolderRefusal(model,'eth/docs/baseline',''),'','a reserved name deeper than the part directly below the lab folder is not this rule');
 assert.match(gitNewFolderRefusal(model,'unused/checkpoints/x',''),/^unused is a lab folder/);
 assert.equal(gitNewFolderRefusal(model,'notes/latest/x',''),'','a folder without a registration has no saves');
 assert.equal(gitNewFolderRefusal(model,'eth/week1',''),'');
 const rooted=gitTreeModel([{path:'a/b.md',size:1}],[{id:'r',prefix:'',lab:{id:'x',name:'Root'}}]);
 assert.match(gitNewFolderRefusal(rooted,'latest/notes',''),/^The top level is a lab folder, and latest inside it/);
 const mine=gitTreeModel([{path:'notes/a.md',size:1}],[{id:'me',prefix:'notes',lab:{id:'lab',name:'Me'}}]);
 assert.match(gitNewFolderRefusal(mine,'notes/baseline/x','me'),/^notes is a lab folder/,'the folder the asking lab saves to counts too');
});
test('New folder…: a name such as latest/notes inside a lab folder is never refused: the manager makes it in the lab folder above and the chooser says so',()=>{
 const context=makeContext();
 // The manager's answer for such a folder (POST …/folders/new returns it): the lab folder above the saved state is used.
 const html=markup(context,chooserTree([ans(''),ans('eth',{kind:'lab',lab:{id:'other',name:'Eth'},mark:'Eth saves here',beside:'eth/restore-square'})],{files:[{path:'eth/a.md',size:1}]}),
  {value:'eth/notes',selected:'eth/notes',answer:ans('eth/notes',{typed:'eth/latest/notes',adjusted:'above-state',exists:false})});
 assert.match(liveRegion(html),/^eth\/latest\/notes is part of a saved state, so restore-square saves in eth\/notes, the lab folder above it\./);
 assert.doesNotMatch(html,/id="folder-refused"/);assert.deepEqual(buttonsOf(html),['Cancel','Save here']);
 // The pure rule the old dialog used is kept for the tree's own marks.
 const model=context.gitTreeModel([{path:'eth/a.md',size:1}],[{id:'e',prefix:'eth',lab:{id:'other',name:'Eth'}}]);
 assert.match(context.gitNewFolderRefusal(model,'eth/latest/notes',''),/eth is a lab folder, and latest inside it is where it keeps its saves/);
});


// ---------------------------------------------------------------------------------------------------------------
// The folder chooser (docs/git-redesign/design/DRAWERS.md section 4, tests C1 to C14 that belong to this file).
// ---------------------------------------------------------------------------------------------------------------
// [typed, clean_folder(typed)] produced by the manager's own clean_folder() (app/git_places.py) over the HOSTILE
// list of tests/test_git_places.py plus the examples of DRAWERS.md 4.4; null: the manager's one error (> 500).
const CLEAN_TABLE=[["", ""], [" ", ""], ["/", ""], ["//", ""], ["a//b", "a/b"], ["a/b/", "a/b"], ["/a/b", "a/b"], [" a / b ", "a/b"], ["my lab", "my-lab"], ["UX TEST (3)", "UX-TEST-3"], ["\u00e9", ""], ["\u00dcbung/gr\u00f6\u00dfe", "bung/gr-e"], ["\u65e5\u672c\u8a9e", ""], ["a\\b", "a-b"], ["\\\\server\\share", "server-share"], ["..", ""], [".", ""], ["../..", ""], ["a/../b", "a/b"], ["a/./b", "a/b"], [".hidden", "hidden"], ["..hidden", "hidden"], ["-dash", "dash"], ["--", ""], ["-.-", ""], [".git", "git"], [".GIT", "git"], ["a/.git/b", "a/git/b"], [".Git/hooks", "git/hooks"], [".gitignore", "gitignore"], ["a\u0000b", "a-b"], ["a\nb", "a-b"], ["\t", ""], ["\u007f", ""], ["a\r\n/b", "a/b"], ["latest", "latest"], ["a/latest", "a/latest"], ["checkpoints/x", "checkpoints/x"], ["xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"], ["xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"], ["xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"], ["------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------a", "a"], ["ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab", "ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab/ab"], ["a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a", "a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a/a"], ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"], ["a?", "a"], ["?a", "a"], ["a?b", "a-b"], ["a-", "a-"], ["a.", "a."], ["a..b", "a..b"], ["~", ""], ["$(rm -rf)", "rm--rf"], ["a;b|c", "a-b-c"], ["a\u200bb", "a-b"], ["\ufeffa", "a"], ["a//////////////////////////////////////////////////b", "a/b"], [null, ""], [7, "7"], ["CON", "CON"], ["a:b", "a-b"], ["%2e%2e", "2e-2e"], ["a/%2f/b", "a/2f/b"], [" a / b ", "a/b"], ["Week 4//BGP lab/", "Week-4/BGP-lab"], ["a\\b", "a-b"], ["\u00e9", ""], ["gr\u00f6 \u00dfe", "gr-e"], ["a-", "a-"], ["a?", "a"], ["_x", "_x"], ["xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"], ["BGP/start", "BGP/start"], ["my lab", "my-lab"], ["UX TEST (3)", "UX-TEST-3"], ["CON", "CON"], [".GIT", "git"], ["a/.git/b", "a/git/b"]];
const ans=(path,more={})=>({path,folder:path,typed:path,kind:'free',exists:true,label:'',lab:null,layout:'',collision:false,adjusted:'',beside:'',mark:'',same_name:false,bring:{offered:false,files:0,from:''},...more});
const chooserTree=(folders,more={})=>({repository:{path:'/srv/course'},head:'abc1234567',truncated:false,saved:{},files:[{path:'README.md',size:3},{path:'BGP/latest/manifest.json',size:5},{path:'BGP/latest/PE1.cfg',size:5},{path:'BGP/week-2/a.txt',size:1},{path:'start/manifest.json',size:5},{path:'notes/a.md',size:1}],own:{},folders,...more});
const baseFolders=()=>[ans('',{mark:''}),ans('BGP',{kind:'own',mark:'This lab saves here'}),ans('BGP/week-2'),ans('notes'),ans('start',{kind:'state',label:'Start',layout:'flat',mark:'Lab state: Start',beside:'start/restore-square'}),ans('week-5',{exists:false})];
const view=(more={})=>({mode:'location',labName:'restore-square',repoName:'Course-Labs',status:'ready',value:'notes',expanded:new Set(['']),...more});
const markup=(context,tree,more={})=>context.folderChooserMarkup(context.folderChooserModel(tree),view(more));
const FORBIDDEN=/registration|prefix|overlap/i;
const foot=html=>html.slice(html.indexOf('id="folder-foot"'));
const liveRegion=html=>(html.match(/id="folder-answer"[^>]*>([^]*?)<\/p>/)||[])[1];
const buttonsOf=html=>[...foot(html).matchAll(/<button [^>]*>([^<]*)<\/button>/g)].map(m=>m[1]);

test('C2 folderClean equals the manager\'s clean_folder for the whole shared table, is idempotent and never throws',()=>{
 const {folderClean}=makeContext();
 let checked=0;
 for(const [typed,cleaned] of CLEAN_TABLE){
  if(cleaned===null){assert.ok(folderClean(typed).length<=500,'the one manager error is answered by a cut');continue;}
  assert.equal(folderClean(typed),cleaned,JSON.stringify(typed));
  assert.equal(folderClean(folderClean(typed)),cleaned,'idempotent '+JSON.stringify(typed));
  checked++;
 }
 assert.ok(checked>60);
 assert.equal(folderClean('Week 4//BGP lab/'),'Week-4/BGP-lab');
 assert.equal(folderClean('.git'),'git');assert.equal(folderClean('x'.repeat(182)),'x'.repeat(181));
 assert.equal(folderClean(undefined),'');assert.equal(folderClean(7),'7');
});
test('C2 folderEcho is only an echo: it keeps the space just typed as a dash and one trailing slash, and agrees with folderClean elsewhere',()=>{
 const {folderEcho,folderClean}=makeContext();
 assert.equal(folderEcho('my '),'my-');assert.equal(folderEcho('my lab'),'my-lab');assert.equal(folderEcho('Week 4//BGP lab/'),'Week-4/BGP-lab/');
 assert.equal(folderEcho('a/ '),'a/');assert.equal(folderEcho('a//'),'a/');assert.equal(folderEcho('a/b'),'a/b');assert.equal(folderEcho('/'),'');assert.equal(folderEcho('é'),'');
 for(const [typed,cleaned] of CLEAN_TABLE)if(cleaned!==null&&/[A-Za-z0-9_]$/.test(String(typed??'')))assert.equal(folderEcho(typed),cleaned,JSON.stringify(typed));
 for(const [typed] of CLEAN_TABLE)assert.equal(folderEcho(folderEcho(typed)).replace(/\/$/,''),folderEcho(typed).replace(/\/$/,''));
 assert.equal(folderClean(folderEcho('Week 4//BGP lab/')),'Week-4/BGP-lab');
});
test('C1 New folder… is present and enabled in every mode, every kind of answer and every state of the tree',()=>{
 const context=makeContext(),kinds=[ans('x'),ans('x',{kind:'own',mark:'This lab saves here'}),ans('x',{kind:'own-before'}),ans('x',{kind:'lab',lab:{id:'o',name:'Other'},beside:'x/restore-square',mark:'Other saves here'}),ans('x',{kind:'lab',collision:true,lab:null,beside:'x/r'}),ans('x',{kind:'state',label:'Start',layout:'latest',beside:'x/r'}),ans('x',{kind:'state',layout:'flat',beside:'x/r'}),ans('',{}),ans('x',{adjusted:'above-state',typed:'x/latest'}),ans('x',{exists:false})];
 const trees=[chooserTree(baseFolders()),chooserTree([ans('')],{files:[]}),chooserTree(baseFolders(),{truncated:true}),chooserTree(baseFolders(),{truncated:true,dirs:['a','b'],dirs_truncated:true})];
 let count=0;
 const enabled=html=>{const m=html.match(/<button [^>]*data-folder-action="new"[^>]*>/);assert.ok(m,'New folder… is missing');assert.ok(!/disabled/.test(m[0]),'New folder… is disabled');assert.match(html,/New folder…<\/button>/);count++;};
 for(const mode of ['location','state','browse'])for(const tree of trees)for(const answer of kinds)for(const extra of [{},{busy:true},{pending:{count:1,summary:''}},{question:{kind:'empty',name:'repo'}}])enabled(context.folderChooserMarkup(context.folderChooserModel(tree),view({mode,answer,...extra})));
 for(const status of ['loading','error','unreachable'])for(const mode of ['location','state','browse'])enabled(context.folderChooserMarkup(null,view({mode,status,error:'boom'})));
 for(const selected of ['','BGP','BGP/latest','BGP/latest/x','start','start/latest'])enabled(markup(context,chooserTree(baseFolders()),{selected,value:selected,expanded:new Set(['','BGP','start'])}));
 assert.ok(count>400);
});
test('C4 free, own, own-before: marks, sentences and the one button',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 let html=markup(context,tree,{value:'notes'});
 assert.equal(liveRegion(html),'');same(buttonsOf(html),['Cancel','Save here']);assert.match(html,/data-folder-action="save" data-folder-primary="1"/);
 html=markup(context,tree,{value:'week-5'});assert.equal(liveRegion(html),'week-5 is new. It appears in the repository with the first save.');
 assert.doesNotMatch(liveRegion(html),/(?:is|exists) in the repository/);
 html=markup(context,tree,{value:''});assert.equal(liveRegion(html),'restore-square will save at the top level of Course-Labs.');assert.match(html,/<code>top level<\/code>/);
 html=markup(context,tree,{value:'BGP',expanded:new Set(['','BGP'])});assert.equal(liveRegion(html),'restore-square already saves here.');same(buttonsOf(html),['Cancel','Keep saving here']);assert.match(html,/data-folder-action="keep"/);assert.doesNotMatch(foot(html),/disabled/);
 const before=chooserTree([ans(''),ans('old',{kind:'own-before'})],{files:[{path:'old/latest/manifest.json',size:1}]});
 html=markup(context,before,{value:'old'});assert.equal(liveRegion(html),'restore-square saved here before and continues there.');same(buttonsOf(html),['Cancel','Save here']);
});
test('C4 another lab: the identical folder has two buttons, a collision one, a folder nothing can name has its own sentence',()=>{
 const context=makeContext(),lab={id:'o',name:'BGP <b>'},tree=chooserTree([ans(''),ans('eth',{kind:'lab',lab,beside:'eth/restore-square',mark:'BGP <b> saves here'})]);
 let html=markup(context,tree,{value:'eth'});
 assert.equal(liveRegion(html),'BGP &lt;b&gt; saves here too.');same(buttonsOf(html),['Cancel','Save in eth/restore-square','Use this folder anyway']);
 assert.match(html,/data-folder-choice="beside" data-folder-primary="1"/);assert.match(html,/data-folder-choice="take"/);assert.doesNotMatch(html,/<b>x|BGP <b>/);
 assert.match(html,/If you use this folder anyway, BGP &lt;b&gt; is disconnected from it\. Its saves stay as versions, and a save of it that is still waiting stays part of the next upload\./);
 const collision=chooserTree([ans(''),ans('eth',{kind:'lab',collision:true,lab,beside:'eth/restore-square'})]);
 html=markup(context,collision,{value:'eth'});same(buttonsOf(html),['Cancel','Save in eth/restore-square']);assert.match(html,/restore-square gets a folder of its own inside it\./);assert.doesNotMatch(html,/data-folder-choice="take"/);
 const nobody=chooserTree([ans(''),ans('eth',{kind:'lab',collision:true,lab:null,beside:'eth/restore-square'})]);
 html=markup(context,nobody,{value:'eth'});assert.equal(liveRegion(html),'This folder is already used for saves on the VM.');same(buttonsOf(html),['Cancel','Save in eth/restore-square']);
});
test('C4 a saved state: Replace it for a latest layout, Use this folder anyway and the stays-listed note for a flat one',()=>{
 const context=makeContext();
 let tree=chooserTree([ans(''),ans('start',{kind:'state',label:'Start',layout:'latest',beside:'start/restore-square',mark:'Lab state: Start'})]);
 let html=markup(context,tree,{value:'start'});
 assert.equal(liveRegion(html),'This folder holds the state “Start”.');same(buttonsOf(html),['Cancel','Save beside it in start/restore-square','Replace it']);
 assert.match(html,/If you replace it, the next save of restore-square replaces its files\. The older contents stay in the Git history\./);assert.match(html,/<b class="git-tag folder-state">Lab state: Start<\/b>/);
 tree=chooserTree([ans(''),ans('start',{kind:'state',label:'Start',layout:'flat',beside:'start/restore-square',mark:'Lab state: Start'})]);
 html=markup(context,tree,{value:'start'});same(buttonsOf(html),['Cancel','Save beside it in start/restore-square','Use this folder anyway']);
 assert.match(html,/the state “Start” stays listed: its files are stored directly in the folder and are not replaced\./);assert.doesNotMatch(html,/Replace it/);
});
test('C4 an adjusted path says what happened and the result line shows the folder, never what was typed',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 let html=markup(context,tree,{value:'BGP/latest',answer:ans('BGP',{typed:'BGP/latest',adjusted:'above-state',kind:'own'})});
 assert.match(liveRegion(html),/^BGP\/latest is part of a saved state, so restore-square saves in BGP, the lab folder above it\. restore-square already saves here\.$/);
 assert.match(html,/<code>BGP<\/code><\/p>/);
 html=markup(context,tree,{value:'x/latest',answer:ans('x/restore-square',{typed:'x/latest',adjusted:'beside-files'})});
 assert.match(liveRegion(html),/^x\/latest holds a folder named latest that the manager did not save, so restore-square saves in x\/restore-square\.$/);assert.match(html,/<code>x\/restore-square<\/code>/);
 html=markup(context,tree,{value:'Week 4//BGP lab/',answer:ans('Week-4/BGP-lab',{typed:'Week 4//BGP lab/',adjusted:'corrected',exists:false})});
 assert.match(html,/<code>Week-4\/BGP-lab<\/code>/);assert.doesNotMatch(liveRegion(html),/part of a saved state/);
});
test('C3 until the answer arrives the echoed correction and a neutral Checking… are shown, never a guess',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 const html=markup(context,tree,{value:folderEchoOf(context,'Week 4//BGP lab/'),checking:true});
 assert.equal(liveRegion(html),'Checking…');assert.match(html,/<code>Week-4\/BGP-lab<\/code>/);same(buttonsOf(html),['Cancel','Save here']);
 assert.doesNotMatch(html,/is new|saves here too|holds the state/);
 const answered=markup(context,tree,{value:'Week-4/BGP-lab',answer:ans('Week-4/BGP-lab-2',{typed:'Week 4//BGP lab/'})});
 assert.match(answered,/<code>Week-4\/BGP-lab-2<\/code>/);assert.doesNotMatch(liveRegion(answered),/Checking/);
});
function folderEchoOf(context,value){return context.folderEcho(value);}
test('C7 the bring-along line is a real tick box offered only when the answer says so; an unfinished save replaces it with its sentence',()=>{
 const context=makeContext(),offered=chooserTree([ans(''),ans('new',{bring:{offered:true,files:3,from:'BGP'}})]);
 let html=markup(context,offered,{value:'new'});
 assert.match(html,/<label class="checkbox-label" id="folder-move"><input type="checkbox" data-folder-bring checked> Bring this lab’s saved files along<\/label>/);
 assert.doesNotMatch(markup(context,offered,{value:'new',bring:false}),/data-folder-bring checked/);
 html=markup(context,chooserTree([ans(''),ans('new')]),{value:'new'});assert.doesNotMatch(html,/Bring this lab/);
 const unfinished=chooserTree([ans(''),ans('new',{bring:{offered:false,files:3,from:'BGP'}})]);
 html=markup(context,unfinished,{value:'new',unfinished:true});
 assert.match(html,/A save of this lab has not finished\. Its files stay in BGP\./);assert.doesNotMatch(html,/Bring this lab|uploaded right away/);
 const both=markup(context,chooserTree([ans(''),ans('new',{bring:{offered:true,files:3,from:'BGP',unfinished:true}})]),{value:'new'});
 assert.doesNotMatch(both,/data-folder-bring/);assert.match(both,/has not finished/);
});
test('C6 question 3: the waiting save, the review sentence, Upload it then move waits for the review, Move and keep never does',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 let html=markup(context,tree,{value:'notes',pending:{count:1,summary:''}});
 assert.equal(liveRegion(html),'1 save of restore-square is waiting for upload.');
 assert.match(html,/Checking what this upload sends…/);
 assert.match(html,/<button [^>]*data-folder-pending="upload"[^>]* disabled>Upload it, then move<\/button>/);
 assert.match(html,/<button [^>]*data-folder-pending="keep" data-folder-primary="1">Move and keep that save on the VM only<\/button>/);
 assert.match(html,/That save stays on the VM and stays part of the next upload\./);
 html=markup(context,tree,{value:'notes',pending:{count:2,summary:'ceos changed. 4 lines added.'}});
 assert.equal(liveRegion(html),'2 saves of restore-square are waiting for upload.');assert.match(html,/ceos changed\. 4 lines added\./);
 assert.doesNotMatch(html,/data-folder-pending="upload"[^>]*disabled/);assert.doesNotMatch(html,/uploaded right away|must be uploaded first|Open restore-square/);
 same(buttonsOf(html),['Cancel','Upload it, then move','Move and keep that save on the VM only']);
});
test('the empty-repository and same-name questions carry their one-sentence answers',()=>{
 const context=makeContext(),tree=chooserTree([ans('')],{files:[]});
 let html=markup(context,tree,{value:'',question:{kind:'empty',name:'Course-Labs'}});
 assert.equal(liveRegion(html),'Course-Labs is empty. The manager adds a README.md file to start it.');same(buttonsOf(html),['Cancel','Start the repository']);assert.match(html,/data-folder-action="initialize"/);
 html=markup(context,chooserTree(baseFolders()),{value:'restore-square',question:{kind:'same-name',name:'restore-square',beside:'restore-square-2'}});
 assert.equal(liveRegion(html),'This repository already holds saves of a lab named restore-square.');same(buttonsOf(html),['Cancel','Continue there','Save in restore-square-2']);
 assert.match(html,/data-folder-choice="take"/);assert.match(html,/data-folder-choice="beside" data-folder-primary="1"/);
 html=markup(context,chooserTree([ans(''),ans('restore-square',{kind:'state',label:'Restore-square',same_name:true,beside:'restore-square-2'})]),{value:'restore-square',firstSave:true});
 same(buttonsOf(html),['Cancel','Continue there','Save in restore-square-2']);
});
test('C13 a large repository: only open branches are drawn, a branch lists 200 folders and offers the rest, the type-it note needs dirs_truncated',()=>{
 const context=makeContext(),dirs=Array.from({length:5000},(_,i)=>'d'+String(i).padStart(4,'0'));
 const tree=chooserTree([ans('')],{files:[{path:'README.md',size:1}],dirs,truncated:true});
 let html=markup(context,tree,{value:''});
 assert.equal((html.match(/role="treeitem"/g)||[]).length,201);assert.match(html,/Show all 5,000 folders/);assert.doesNotMatch(html,/very large/);
 const rows=context.folderVisibleRows(context.folderChooserModel(tree),view());assert.equal(rows.length,201);
 html=markup(context,tree,{value:'',showAll:new Set([''])});assert.equal((html.match(/role="treeitem"/g)||[]).length,5001);assert.doesNotMatch(html,/Show all/);
 html=markup(context,tree,{value:'d4999',selected:'d4999'});assert.match(html,/data-folder="d4999"/);
 // The manager's tree says so itself (`dirs_truncated`, without a `dirs` list): false means every folder is listed, whatever the file list.
 html=markup(context,chooserTree([ans('')],{truncated:true,dirs_truncated:false}),{value:''});assert.doesNotMatch(html,/very large/);
 html=markup(context,chooserTree([ans('')],{truncated:true,dirs_truncated:true}),{value:''});assert.match(html,/id="folder-tree-note">This repository is very large/);
 html=markup(context,chooserTree([ans('')],{dirs,truncated:true,dirs_truncated:true}),{value:''});assert.match(html,/id="folder-tree-note">This repository is very large and not every folder is listed\. Type the path of a folder that is not shown\.</);
 html=markup(context,chooserTree([ans('')],{truncated:true}),{value:''});assert.match(html,/not every folder is listed/);
 html=markup(context,chooserTree([ans('')],{dirs,truncated:true}),{value:''});assert.match(html,/id="folder-tree-note" hidden/);
});
test('C13 every folder is reached by the person through the tree: an open branch lists its children, a closed one none',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 let html=markup(context,tree,{expanded:new Set([''])});assert.doesNotMatch(html,/data-folder="BGP\/week-2"/);assert.match(html,/data-folder="BGP"[^>]*>/);assert.match(html,/aria-expanded="false"[^>]*data-folder="BGP"/);
 html=markup(context,tree,{expanded:new Set(['','BGP'])});assert.match(html,/data-folder="BGP\/week-2"/);assert.match(html,/aria-expanded="true"[^>]*data-folder="BGP"/);
});
test('C12 aria-expanded and the drawn children depend on `expanded` only: selecting never opens or closes a branch, a new answer keeps the set',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders()),open=new Set(['','BGP']),shape=html=>[...html.matchAll(/aria-expanded="(\w+)"[^>]*data-folder="([^"]*)"/g)].map(m=>m[2]+':'+m[1]).join('|');
 const first=markup(context,tree,{expanded:open,selected:'notes',value:'notes'});
 for(const path of ['','BGP','BGP/week-2','start','week-5']){assert.equal(shape(markup(context,tree,{expanded:open,selected:path,value:path,answer:ans(path,{kind:'own'})})),shape(first),path);}
 assert.ok(open.has('BGP')&&open.size===2,'the markup does not touch the set');
 const {gitRevealFolder,gitToggleFolder,gitKeepExpanded,gitAncestors}=context,set=new Set(['','notes']);
 gitRevealFolder(set,'BGP/week-2');same([...set].sort(),['','BGP','BGP/week-2','notes'].sort());
 gitToggleFolder(set,'notes');assert.equal(set.has('notes'),false);
 const kept=gitKeepExpanded(set,context.folderChooserModel(chooserTree(baseFolders(),{files:[{path:'BGP/week-2/a.txt',size:1}]})));
 assert.ok(kept.has('BGP')&&kept.has('BGP/week-2')&&!kept.has('notes'),'a new answer keeps what still exists');
 same(gitAncestors('a/b/c'),['','a','a/b']);
 same([...context.folderDefaultExpanded(context.folderChooserModel(tree))].sort(),['','BGP'].sort());
});
test('inside a saved state is not listed: a lab folder hides latest, baseline and checkpoints, a folder with a manifest is a leaf, browse lists everything',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders(),{files:[{path:'BGP/latest/manifest.json',size:1},{path:'BGP/other/x.txt',size:1},{path:'start/sub/y.txt',size:1},{path:'start/manifest.json',size:1},{path:'course/latest/working/z.txt',size:1}]}),open=new Set(['','BGP','start','course','course/latest']);
 let html=markup(context,tree,{expanded:open});
 assert.doesNotMatch(html,/data-folder="BGP\/latest"/);assert.match(html,/data-folder="BGP\/other"/);assert.doesNotMatch(html,/data-folder="start\/sub"/);
 assert.match(html,/data-folder="course\/latest"/,'a latest that is no saved state is an ordinary name');assert.match(html,/data-folder="course\/latest\/working"/);
 html=markup(context,tree,{expanded:open,mode:'browse'});assert.match(html,/data-folder="BGP\/latest"/);assert.match(html,/data-folder="start\/sub"/);
});
test('marks are the answer\'s own text, as tags; a folder in no commit carries New and is never worded as in the repository',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders()),html=markup(context,tree,{expanded:new Set(['','BGP']),value:'notes'});
 assert.match(html,/<b class="git-tag">This lab saves here<\/b>/);assert.match(html,/<b class="git-tag folder-state">Lab state: Start<\/b>/);
 assert.match(html,/data-folder="week-5"[^]*?<b class="git-tag pending">New<\/b>/);
 const labs=markup(context,chooserTree([ans(''),ans('eth',{kind:'lab',mark:'<i>Eth</i> saves here',lab:{id:'o',name:'Eth'},beside:'eth/x'})]),{value:'eth'});
 assert.match(labs,/<b class="git-tag other">&lt;i&gt;Eth&lt;\/i&gt; saves here<\/b>/);
 const planned=markup(context,tree,{value:'week-5',selected:'week-5'});assert.doesNotMatch(liveRegion(planned),/in the repository\./);
 const typed=markup(context,tree,{value:'brand/new',expanded:new Set(['']),answer:ans('brand/new',{exists:false})});
 assert.match(typed,/data-folder="brand\/new"[^]*?<b class="git-tag pending">New<\/b>/,'a typed path that is nowhere gets a provisional row marked New');
});
test('C10 the live region holds text only; the questions\' buttons are in the foot; no inline style, no disabled primary without a reason',()=>{
 const context=makeContext(),all=[];
 for(const answer of [ans('x'),ans('x',{kind:'lab',lab:{id:'o',name:'O'},beside:'x/r'}),ans('x',{kind:'state',label:'S',layout:'latest',beside:'x/r'}),ans('x',{kind:'own'})])
  for(const extra of [{},{pending:{count:1,summary:'s'}},{refused:'The VM is busy.'},{notice:'x already exists. It is selected.'}])all.push(markup(context,chooserTree(baseFolders()),{answer,value:'x',...extra}));
 for(const status of ['loading','error','unreachable'])all.push(context.folderChooserMarkup(null,view({status,error:'No answer.'})));
 for(const html of all){
  assert.doesNotMatch(liveRegion(html)??'',/[<]/);
  for(const m of html.matchAll(/role="(?:status|alert)"[^>]*>([^]*?)<\/(?:p|div)>/g))assert.doesNotMatch(m[1],/<(?:button|a|input|select)\b/);
  assert.doesNotMatch(html,/ style=/);
  const foots=html.includes('id="folder-foot"')?foot(html):'';
  if(/data-folder-primary="1"[^>]* disabled/.test(foots))assert.match(foots,/id="folder-reason">[^<]+</,'a disabled primary says why');
 }
});
test('4.9 loading, error and the VM unreachable: the visible reason and the action beside it',()=>{
 const context=makeContext();
 let html=context.folderChooserMarkup(null,view({status:'loading'}));
 assert.match(html,/<p role="status" class="git-empty-folder">Loading folders…<\/p>/);assert.match(html,/id="folder-path"/);assert.match(html,/data-folder-primary="1"[^>]* disabled/);assert.match(html,/id="folder-reason">The folders are still loading\.</);
 html=context.folderChooserMarkup(null,view({status:'error',error:'The VM said no.'}));
 assert.match(html,/The folders could not be loaded\. The VM said no\./);assert.match(html,/data-folder-action="retry">Try again/);assert.doesNotMatch(foot(html),/disabled/);
 html=context.folderChooserMarkup(null,view({status:'unreachable'}));
 assert.match(html,/The lab VM cannot be reached, so its folders cannot be shown\./);assert.match(html,/data-folder-action="retry">Try again/);assert.match(html,/data-folder-action="vm">Check the VM connection…/);
 assert.match(html,/data-folder-primary="1"[^>]* disabled/);assert.match(foot(html),/id="folder-reason">The lab VM cannot be reached/);
 html=markup(context,chooserTree([ans('')],{files:[]}),{value:'lab'});
 assert.match(html,/Course-Labs is empty\. restore-square can save at the top level or in a new folder\./);assert.doesNotMatch(foot(html),/disabled/);
 // A refusal whose cause the manager recorded reads like the chip: the sentence, the manager's own under Details, Try again, and
 // Update from the repository when that is what clears it (integration seam 13).
 html=markup(context,chooserTree(baseFolders()),{refused:'This checkout has commits that were not made by manager saves.',problem:{sentence:'Someone is working in this repository on the VM.',detail:'This checkout has commits that were not made by manager saves.',update:false}});
 assert.match(html,/id="folder-refused">Someone is working in this repository on the VM\.<\/p><button [^>]*data-folder-action="again">Try again<\/button><\/div><details id="folder-refused-details"><summary>Details<\/summary><p class="save-note">This checkout has commits that were not made by manager saves\.<\/p><\/details>/);
 html=markup(context,chooserTree(baseFolders()),{refused:'raw',problem:{sentence:'The online copy has changes this VM does not have.',detail:'raw',update:true}});
 assert.match(html,/id="folder-refused">The online copy has changes this VM does not have\.<\/p><button [^>]*data-folder-action="update">Update from the repository<\/button><button [^>]*data-folder-action="again">Try again/);
 html=markup(context,chooserTree(baseFolders()),{refused:'The lab VM is busy.'});assert.match(html,/id="folder-refused">The lab VM is busy\.<\/p><button [^>]*data-folder-action="again">Try again/);
 html=markup(context,chooserTree(baseFolders()),{busy:true});assert.match(html,/Saving here…/);assert.match(html,/aria-busy="true"/);
});
test('the Repository select appears with two or more repositories, and the escaped names',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 assert.doesNotMatch(markup(context,tree,{repositories:[{id:'a',name:'A'}]}),/folder-repo/);
 const html=markup(context,tree,{repositories:[{id:'a',name:'A <x>'},{id:'b',name:'B'}],repository:'b'});
 assert.match(html,/<select id="folder-repo">/);assert.match(html,/<option value="b" selected>B<\/option>/);assert.match(html,/A &lt;x&gt;/);
});
test('New folder: an inline row with its own field, Add and Cancel, placed under the parent that is looked at',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 let html=markup(context,tree,{expanded:new Set(['','BGP']),selected:'BGP',newFolder:{parent:'BGP',value:'week-<3>'}});
 assert.match(html,/data-folder-action="new" data-folder-parent="BGP">New folder…/);assert.match(html,/<li role="none" class="folder-new"><label class="sr-only" for="folder-new">New folder in BGP<\/label><input id="folder-new"[^>]*value="week-&lt;3&gt;">/);
 assert.ok(html.indexOf('data-folder="BGP/week-2"')<html.indexOf('id="folder-new"'));
 html=markup(context,tree,{expanded:new Set(['']),newFolder:{parent:'BGP/closed',value:''}});assert.match(html,/id="folder-new"/);
});
test('C14 state mode: name field and buttons, the destination in a fold with its tree, Save state, the state answers',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 let html=markup(context,tree,{mode:'state',value:'BGP/start',name:'start',answer:ans('BGP/start')});
 assert.match(html,/data-mode="state"/);assert.match(html,/<input id="state-name"[^>]*value="start">/);
 assert.match(html,/data-state-name="start" aria-pressed="true">start/);assert.match(html,/data-state-name="final" aria-pressed="false">final/);
 assert.match(html,/The state is saved in<\/span><code>Course-Labs<\/code>[^]*<code>BGP\/start<\/code>/);assert.match(html,/<details data-folder-details><summary>Put it somewhere else<\/summary>[^]*New folder…[^]*<\/details>/);
 same(buttonsOf(html),['Cancel','Save state']);assert.match(html,/Reads every included device now\. Saved files can contain passwords or keys\. Where restore-square normally saves does not change\./);
 assert.match(markup(context,tree,{mode:'state',treeOpen:true}),/<details data-folder-details open>/);
 html=markup(context,tree,{mode:'state',value:'start',name:'start',answer:ans('start',{kind:'state',label:'Start'})});
 assert.equal(liveRegion(html),'“Start” already exists here.');same(buttonsOf(html),['Cancel','Replace it','Use another name']);assert.match(html,/data-folder-choice="take"/);assert.match(html,/data-folder-action="use-another-name"/);assert.doesNotMatch(html,/Use this folder anyway/);
 html=markup(context,tree,{mode:'state',value:'BGP',name:'start',answer:ans('BGP/start',{typed:'BGP',kind:'own'})});assert.equal(liveRegion(html),'restore-square saves in BGP, so the state is saved in BGP/start.');same(buttonsOf(html),['Cancel','Save state']);
 // What the manager really answers for a lab's folder (git_places.place_answer, purpose state): the folder inside it, `adjusted: inside-lab`,
 // and the kind of THAT folder. The field shows what was typed and the result line the folder used, so one sentence says why they differ.
 html=markup(context,tree,{mode:'state',value:'BGP',name:'Inside',answer:ans('BGP/Inside',{typed:'BGP',kind:'free',adjusted:'inside-lab'})});assert.equal(liveRegion(html),'BGP is a lab’s save folder, so the state is saved in BGP/Inside.');same(buttonsOf(html),['Cancel','Save state']);
 html=markup(context,tree,{mode:'state',value:'BGP',name:'start',answer:ans('BGP/start',{typed:'BGP',kind:'state',label:'Start',adjusted:'inside-lab'})});assert.equal(liveRegion(html),'BGP is a lab’s save folder, so the state is saved in BGP/start. “Start” already exists here.');same(buttonsOf(html),['Cancel','Replace it','Use another name']);
 html=markup(context,tree,{mode:'state',value:'eth',name:'start',answer:ans('eth/start',{typed:'eth',kind:'lab',lab:{id:'o',name:'Ethernet'}})});assert.equal(liveRegion(html),'Ethernet saves in eth, so the state is saved in eth/start.');
 assert.match(markup(context,tree,{mode:'state',busy:true}),/Saving…/);
});
test('browse mode: no field and no primary button, the listing of the selected folder and Load this state… with the exact path',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 let html=markup(context,tree,{mode:'browse',selected:'start',expanded:new Set(['','start'])});
 assert.doesNotMatch(html,/id="folder-path"|data-folder-primary|id="folder-foot"/);assert.match(html,/data-folder-action="load" data-folder-path="\/start">Load this state…/);assert.match(html,/data-folder-action="view" data-folder-path="\/start">View files/);assert.match(html,/manifest\.json/);
 html=markup(context,tree,{mode:'browse',selected:'BGP',expanded:new Set(['','BGP'])});assert.match(html,/data-folder-path="\/BGP\/latest"/);
 html=markup(context,tree,{mode:'browse',selected:'notes'});assert.doesNotMatch(html,/Load this state/);
});
test('Remove from the list is offered for a folder the manager only lists, and never for one in a commit',()=>{
 const context=makeContext(),tree=chooserTree(baseFolders());
 assert.match(markup(context,tree,{value:'week-5'}),/data-folder-action="forget" data-folder-path="week-5">Remove from the list/);
 assert.doesNotMatch(markup(context,tree,{value:'notes'}),/Remove from the list/);
});
test('C9 the words registration, prefix and overlap occur in no chooser markup, for any answer, mode or state',()=>{
 const context=makeContext(),pool=[];
 const kinds=[{},{kind:'own',mark:'This lab saves here'},{kind:'own-before'},{kind:'lab',lab:{id:'o',name:'Other'},beside:'x/r',mark:'Other saves here'},{kind:'lab',collision:true,beside:'x/r'},{kind:'state',label:'S',layout:'latest',beside:'x/r',mark:'Lab state: S'},{kind:'state',label:'S',layout:'flat',beside:'x/r'},{adjusted:'above-state',typed:'x/latest'},{adjusted:'beside-files',typed:'x/latest'},{adjusted:'corrected'},{exists:false},{bring:{offered:true,files:1,from:'a'}},{bring:{offered:false,files:1,from:'a',unfinished:true}}];
 for(const mode of ['location','state','browse'])for(const more of kinds)for(const extra of [{},{pending:{count:2,summary:''}},{question:{kind:'empty',name:'r'}},{question:{kind:'same-name',name:'r',beside:'r-2'}},{refused:'x'},{busy:true},{newFolder:{parent:'',value:'a'}},{firstSave:true}])
  pool.push(markup(context,chooserTree(baseFolders(),{truncated:true}),{mode,answer:ans('x',more),value:'x',...extra}));
 for(const status of ['loading','error','unreachable'])for(const mode of ['location','state','browse'])pool.push(context.folderChooserMarkup(null,view({mode,status,error:'e'})));
 pool.push(markup(context,chooserTree([ans('')],{files:[]})));
 assert.ok(pool.length>300);
 for(const html of pool){assert.doesNotMatch(html,FORBIDDEN);assert.doesNotMatch(html,/ style=/);}
 const source=fs.readFileSync(path.join(__dirname,'../app/static/git-places.js'),'utf8'),chooser=source.slice(source.indexOf('// The folder chooser'));
 assert.doesNotMatch(chooser.replace(/\/\/[^\n]*/g,''),/registration|prefix|overlap/i,'no string of the chooser code uses the words');
});
test('C11 folderKey: every key of DRAWERS.md 4.8; moving focus never changes expanded or the selection',()=>{
 const {folderKey}=makeContext(),rows=[{path:'',level:1,kids:true,name:'Repo'},{path:'a',level:2,kids:true,name:'alpha'},{path:'a/b',level:3,kids:false,name:'beta'},{path:'c',level:2,kids:true,name:'charlie'},{path:'d',level:2,kids:false,name:'delta'}];
 const open=new Set(['','a']),keep=[...open],step=(i,key)=>folderKey(rows,i,key,open);
 same(step(0,'ArrowDown'),{focus:1,toggle:null,select:null});same(step(4,'ArrowDown'),{focus:4,toggle:null,select:null});same(step(2,'ArrowUp'),{focus:1,toggle:null,select:null});same(step(0,'ArrowUp'),{focus:0,toggle:null,select:null});
 same(step(2,'Home'),{focus:0,toggle:null,select:null});same(step(1,'End'),{focus:4,toggle:null,select:null});
 same(step(3,'ArrowRight'),{focus:3,toggle:'c',select:null},'Right opens a closed branch');same(step(1,'ArrowRight'),{focus:2,toggle:null,select:null},'Right on an open branch: first child');same(step(2,'ArrowRight'),{focus:2,toggle:null,select:null},'Right on a leaf: nothing');
 same(step(1,'ArrowLeft'),{focus:1,toggle:'a',select:null},'Left closes an open branch');same(step(2,'ArrowLeft'),{focus:1,toggle:null,select:null},'Left on a leaf: the parent');same(step(3,'ArrowLeft'),{focus:0,toggle:null,select:null});same(step(0,'ArrowLeft'),{focus:0,toggle:null,select:null});
 same(step(2,'Enter'),{focus:2,toggle:null,select:'a/b'});same(step(3,' '),{focus:3,toggle:null,select:'c'});
 same(step(0,'d'),{focus:4,toggle:null,select:null});same(step(4,'c'),{focus:3,toggle:null,select:null});same(step(0,'z'),{focus:0,toggle:null,select:null});
 assert.equal(step(0,'Tab'),null);assert.equal(step(0,'Escape'),null);assert.equal(folderKey([],0,'ArrowDown',open),null);
 same([...open],keep);
 for(const key of ['ArrowDown','ArrowUp','Home','End','a','d'])assert.equal(step(1,key).select,null,key+' never selects');
});
// A small DOM for the seam: an element knows its parents, its attributes and the few selectors the chooser uses.
function fakeDom(){
 const camel=name=>name.replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
 const attrOf=(el,name)=>name.startsWith('data-')?el.dataset[camel(name.slice(5))]:name==='id'?el.id:el.attrs[name];
 const simple=(el,sel)=>{
  let m;
  if((m=sel.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/)))return m[2]===undefined?attrOf(el,m[1])!==undefined:attrOf(el,m[1])===m[2];
  if((m=sel.match(/^\.([\w-]+)$/)))return el.cls.includes(m[1]);
  if((m=sel.match(/^#([\w-]+)$/)))return el.id===m[1];
  return el.tag===sel;
 };
 const matches=(el,sel)=>sel.split(',').some(part=>simple(el,part.trim()));
 const all=[];
 const make=(tag,{id='',cls=[],attrs={},data={},parent=null,value,checked,disabled,open}={})=>{
  const el={tag,id,cls,attrs,dataset:data,parent,value,checked,disabled,open,focused:false,prevented:0,
   closest(sel){for(let at=el;at;at=at.parent)if(matches(at,sel))return at;return null;},
   getAttribute:name=>{const v=attrOf(el,name);return v===undefined?null:v;},
   focus(){el.focused=true;},preventDefault(){el.prevented++;},contains:other=>{for(let at=other;at;at=at.parent)if(at===el)return true;return false;}};
  all.push(el);return el;
 };
 const root=make('div',{cls:['folder-chooser']});
 root.querySelectorAll=sel=>all.filter(el=>el!==root&&root.contains(el)&&matches(el,sel));
 root.querySelector=sel=>root.querySelectorAll(sel)[0]||null;
 return {make,root,all};
}
const fire=(context,type,target,more={})=>{let stopped=0;const event={target,key:more.key,preventDefault:()=>{target.prevented=(target.prevented||0)+1;},stopPropagation:()=>{stopped++;},...more};const out=context.folderChooserEvent(type,event);return {out,event,target,stopped};};
test('the event seam maps clicks: a row selects, a twist only toggles, the buttons name their choice',()=>{
 const context=makeContext(),dom=fakeDom(),{make,root}=dom;
 const li=make('li',{attrs:{role:'treeitem'},data:{folder:'BGP/week-2'},parent:root}),row=make('span',{cls:['folder-row'],parent:li}),name=make('span',{cls:['folder-name'],parent:row}),twist=make('span',{cls:['git-twist'],data:{folderTwist:'BGP'},parent:row});
 same(fire(context,'click',name).out,{action:'select',path:'BGP/week-2'});
 same(fire(context,'click',twist).out,{action:'toggle',path:'BGP'});
 const child=make('li',{attrs:{role:'treeitem'},data:{folder:'BGP/x'},parent:li}),crow=make('span',{cls:['folder-row'],parent:child});
 same(fire(context,'click',crow).out,{action:'select',path:'BGP/x'},'the innermost folder wins');
 same(fire(context,'click',make('ul',{attrs:{role:'group'},parent:li})).out,null,'the group between rows is not a row');
 const button=data=>make('button',{data,parent:root});
 same(fire(context,'click',button({folderChoice:'beside'})).out,{action:'choice',choice:'beside'});same(fire(context,'click',button({folderChoice:'take'})).out,{action:'choice',choice:'take'});
 same(fire(context,'click',button({folderPending:'keep'})).out,{action:'pending',pending:'keep'});same(fire(context,'click',button({folderPending:'upload'})).out,{action:'pending',pending:'upload'});
 same(fire(context,'click',button({folderAction:'save'})).out,{action:'save'});same(fire(context,'click',button({folderAction:'keep'})).out,{action:'keep'});same(fire(context,'click',button({folderAction:'cancel'})).out,{action:'cancel'});
 same(fire(context,'click',button({folderAction:'new',folderParent:'BGP'})).out,{action:'new-folder',parent:'BGP'});
 same(fire(context,'click',button({folderAction:'show-all',folderPath:'x'})).out,{action:'show-all',path:'x'});same(fire(context,'click',button({folderAction:'forget',folderPath:'w5'})).out,{action:'forget',path:'w5'});
 same(fire(context,'click',button({folderAction:'load',folderPath:'/start'})).out,{action:'load',path:'/start'});same(fire(context,'click',button({folderAction:'view',folderPath:'/start'})).out,{action:'view',path:'/start'});
 for(const name of ['retry','again','vm','initialize','use-another-name','new-cancel'])same(fire(context,'click',button({folderAction:name})).out,{action:name});
 same(fire(context,'click',button({stateName:'broken'})).out,{action:'name',value:'broken',echo:'broken'});
 assert.equal(fire(context,'click',make('button',{data:{folderAction:'save'},disabled:true,parent:root})).out,null,'a disabled button does nothing');
 const field=make('input',{id:'folder-new',value:'week 3',parent:root});
 same(fire(context,'click',button({folderAction:'new-add'})).out,{action:'new-add',value:'week 3'});
 assert.equal(context.folderChooserEvent('click',null),null);assert.equal(context.folderChooserEvent('click',{target:{}}),null);assert.equal(context.folderChooserEvent('wheel',{target:root}),null);
});
test('the event seam maps typing, the select, the tick box and the fold; Enter in a field presses the primary button',()=>{
 const context=makeContext(),dom=fakeDom(),{make,root}=dom;
 const path=make('input',{id:'folder-path',value:'Week 4//BGP lab/',parent:root});
 same(fire(context,'input',path).out,{action:'typed',value:'Week 4//BGP lab/',echo:'Week-4/BGP-lab/'});
 const added=make('input',{id:'folder-new',value:'a b',parent:root});
 same(fire(context,'input',added).out,{action:'new-input',value:'a b',echo:'a-b'});
 same(fire(context,'input',make('input',{id:'state-name',value:'my/state',parent:root})).out,{action:'name',value:'my/state',echo:'my-state'});
 same(fire(context,'change',make('select',{id:'folder-repo',value:'r2',parent:root})).out,{action:'repository',value:'r2'});
 same(fire(context,'change',make('input',{data:{folderBring:''},checked:false,parent:root})).out,{action:'bring',value:false});
 same(fire(context,'toggle',make('details',{data:{folderDetails:''},open:true,parent:root})).out,{action:'tree-open',value:true});
 const primary=make('button',{data:{folderChoice:'beside',folderPrimary:'1'},parent:root});
 let hit=fire(context,'keydown',path,{key:'Enter'});same(hit.out,{action:'choice',choice:'beside'});assert.ok(path.prevented>0);
 primary.disabled=true;assert.equal(fire(context,'keydown',path,{key:'Enter'}).out,null,'a disabled primary is not pressed');
 assert.equal(fire(context,'keydown',path,{key:'a'}).out,null);
 added.value='x';
 same(fire(context,'keydown',added,{key:'Enter'}).out,{action:'new-add',value:'x'});
 hit=fire(context,'keydown',added,{key:'Escape'});same(hit.out,{action:'new-cancel'});assert.equal(hit.stopped,1,'Escape in the new-folder field does not close the drawer');
});
test('C11 the tree keyboard through the seam: arrows move focus only, Right and Left toggle, Enter and Space select',()=>{
 const context=makeContext(),dom=fakeDom(),{make,root}=dom;
 const item=(path,level,expanded,label)=>make('li',{attrs:{role:'treeitem',...(expanded===null?{}:{'aria-expanded':expanded})},data:{folder:path,folderLevel:String(level),folderLabel:label},parent:root});
 const top=item('',1,'true','Repo'),a=item('a',2,'false','alpha'),b=item('b',2,'true','beta'),b1=item('b/1',3,null,'one');
 let hit=fire(context,'keydown',top,{key:'ArrowDown'});same(hit.out,{action:'focus',path:'a'});assert.equal(hit.target.prevented,1);
 same(fire(context,'keydown',a,{key:'ArrowRight'}).out,{action:'toggle',path:'a'});same(fire(context,'keydown',b,{key:'ArrowRight'}).out,{action:'focus',path:'b/1'});same(fire(context,'keydown',b,{key:'ArrowLeft'}).out,{action:'toggle',path:'b'});
 same(fire(context,'keydown',b1,{key:'ArrowLeft'}).out,{action:'focus',path:'b'});same(fire(context,'keydown',a,{key:'Enter'}).out,{action:'select',path:'a'});same(fire(context,'keydown',b,{key:' '}).out,{action:'select',path:'b'});
 same(fire(context,'keydown',top,{key:'End'}).out,{action:'focus',path:'b/1'});same(fire(context,'keydown',top,{key:'b'}).out,{action:'focus',path:'b'});
 assert.equal(fire(context,'keydown',top,{key:'Tab'}).out,null);assert.equal(fire(context,'keydown',top,{key:'ArrowDown',ctrlKey:true}).out,null);
 const field=make('input',{id:'other',parent:item('c',2,null,'c')});assert.equal(fire(context,'keydown',field,{key:'ArrowDown'}).out,null,'a field inside a row keeps its own keys');
});
test('focus and scroll survive a re-render: the snapshot names the focused row, the restore finds it again',()=>{
 const context=makeContext(),dom=fakeDom(),{make,root}=dom;
 const tree=make('ul',{id:'folder-tree',parent:root});tree.scrollTop=140;
 const first=make('li',{attrs:{role:'treeitem'},data:{folder:'a'},parent:tree}),second=make('li',{attrs:{role:'treeitem'},data:{folder:'b'},parent:tree});
 context.document={activeElement:second};
 const snap=context.folderChooserSnapshot(root);same(snap,{key:{path:'b'},scroll:140});
 const fresh=fakeDom(),t2=fresh.make('ul',{id:'folder-tree',parent:fresh.root}),a2=fresh.make('li',{attrs:{role:'treeitem'},data:{folder:'a'},parent:t2}),b2=fresh.make('li',{attrs:{role:'treeitem'},data:{folder:'b'},parent:t2});
 assert.equal(context.folderChooserRestore(fresh.root,snap),true);assert.equal(b2.focused,true);assert.equal(a2.focused,false);assert.equal(t2.scrollTop,140);
 const field=fresh.make('input',{id:'folder-path',parent:fresh.root});context.document={activeElement:field};
 assert.equal(context.folderChooserRestore(fresh.root,context.folderChooserSnapshot(fresh.root)),true);assert.equal(field.focused,true);
 context.document={activeElement:{}};assert.equal(context.folderChooserSnapshot(root),null);
});
test('the old folder browser went with the Progress tab (D1): the chooser is the one component, and the pure folder helpers stay defined',()=>{
 const context=makeContext();
 for(const gone of ['gitPlacesMarkup','gitPlacesShow','gitUseFolder','gitNewFolder','gitForgetFolder','gitApplyDestination','gitRenderRepository'])assert.equal(typeof context[gone],'undefined',gone);
 for(const name of ['gitFolderChoice','gitCanCreateIn','gitFolderPath','gitFolderName','gitDestinationPreview','gitNewFolderRefusal','gitFolderTag','gitPathChips','gitTreeModel','gitApplySource','gitSize','gitAncestors','gitDefaultExpanded','gitToggleFolder','gitRevealFolder','gitKeepExpanded','folderChooserMarkup','folderChooserEvent','folderClean','folderKey','folderChooserModel'])assert.equal(typeof context[name],'function',name);
 assert.equal(typeof vm.runInContext('gitPlacesState',context).expanded.has,'function');
});
test('S11-13 a typed path whose part names a file of the repository: the part got -2 and the sentence names the file',()=>{
 const context=makeContext();
 let html=markup(context,chooserTree(baseFolders()),{value:'README.md/x',answer:ans('README.md-2/x',{typed:'README.md/x',adjusted:'past-file',exists:false})});
 assert.match(html,/id="folder-answer"[^>]*>README\.md is a file in the repository, so restore-square saves in README\.md-2\/x\.<\/p>/);
 assert.match(html,/<code>README\.md-2\/x<\/code>/,'the result line shows the folder that is used');assert.match(html,/data-folder-action="save"[^>]*>Save here</);
 html=markup(context,chooserTree(baseFolders()),{value:'a/notes.txt',answer:ans('a/notes.txt-2',{typed:'a/notes.txt',adjusted:'past-file',exists:false})});
 assert.match(html,/>a\/notes\.txt is a file in the repository, so restore-square saves in a\/notes\.txt-2\.</);
});
test('S11-7 the chooser says where uploads of the selected repository go: its address without credentials, and its branch',()=>{
 const context=makeContext();vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/status.js'),'utf8'),context);
 const repositories=[{id:'a',name:'Course-Labs',remote:'https://github.com/ben/BENS-BGP-LAB.git',branch:'main'},{id:'b',name:'Other',remote:'https://github.com/x/<y>.git',branch:'dev'}];
 let html=markup(context,chooserTree(baseFolders()),{repositories,repository:'a'});
 assert.match(html,/<\/select><p class="save-note" id="folder-uploads">Uploads go to github\.com\/ben\/BENS-BGP-LAB, branch main\.<\/p>/);
 html=markup(context,chooserTree(baseFolders()),{repositories,repository:'b'});
 assert.match(html,/id="folder-uploads">Uploads go to github\.com\/x\/&lt;y&gt;, branch dev\.</,'escaped text, never markup');
 html=markup(context,chooserTree(baseFolders()),{repositories:[repositories[0]],repository:'a'});
 assert.doesNotMatch(html,/<select id="folder-repo"/);assert.match(html,/id="folder-uploads"/,'one repository: no select, the line stays');
 assert.doesNotMatch(markup(context,chooserTree(baseFolders()),{repositories:[{id:'a',name:'n'}],repository:'a'}),/folder-uploads/,'no address known: no line');
 assert.equal(context.saveUploadsText('https://token@github.com/o/r.git','main'),'Uploads go to github.com/o/r, branch main.');assert.equal(context.saveUploadsText('',''),'');
});
test('S11-5, S11-9 Connect by URL… in the chooser: an address field instead of the repository, no tree before it is connected, one button, questions as buttons',()=>{
 const context=makeContext();
 let html=markup(context,chooserTree(baseFolders()),{});
 assert.match(html,/<button type="button" class="button ghost small" data-folder-action="address-on">Connect by URL…<\/button>/);
 assert.doesNotMatch(markup(context,chooserTree(baseFolders()),{mode:'state',name:'x'}),/address-on/,'only where a lab is placed');
 html=markup(context,chooserTree(baseFolders()),{address:{value:'https://github.com/me/New.git'},value:'my-lab',repositories:[{id:'a',name:'A'}]});
 assert.match(html,/<label for="folder-url">Repository address \(HTTPS\)<\/label><input id="folder-url" value="https:\/\/github\.com\/me\/New\.git"/);
 assert.match(html,/data-folder-action="address-off">Use a repository on this VM</);assert.doesNotMatch(html,/id="folder-tree"|data-folder-action="new"/);
 assert.match(html,/<code>New<\/code><span aria-hidden="true">›<\/span><code>my-lab<\/code>/);
 assert.match(html,/<button type="button" class="button primary" data-folder-action="save" data-folder-primary="1">Connect and save here<\/button>/);
 assert.match(html,/Saved files can contain passwords or keys\./);assert.doesNotMatch(html,/Checking…/);
 html=markup(context,chooserTree(baseFolders()),{address:{value:'https://github.com/me/New.git'},value:'x',question:{kind:'empty',name:'New'}});
 assert.match(html,/New is empty\. The manager adds a README\.md file to start it\./);assert.match(html,/data-folder-action="initialize"[^>]*>Start the repository</);
 html=markup(context,chooserTree(baseFolders()),{address:{value:'https://github.com/me/New.git'},value:'x',answer:ans('x',{kind:'lab',lab:{id:'o',name:'Other'},beside:'x/restore-square'})});
 assert.match(html,/Other saves here too\./);assert.match(html,/data-folder-choice="beside"[^>]*>Save in x\/restore-square</);
 html=markup(context,chooserTree(baseFolders()),{address:{value:'nope'},value:'x',refused:'Paste the HTTPS address, for example https://github.com/you/your-lab-repo.'});
 assert.match(html,/id="folder-refused">Paste the HTTPS address/);
 // the events
 const el=(id,value)=>({target:{id,value}});
 assert.deepEqual(JSON.parse(JSON.stringify(context.folderChooserEvent('input',el('folder-url','https://x/y')))),{action:'url',value:'https://x/y'});
});
