'use strict';
// "Folders in this repository": the committed folders of a registered repository, read from the VM
// checkout, the lab folders registered on the VM, and the folders made through the manager that hold
// nothing yet (`planned`: Git has no empty folders, so these are shown as not in the repository yet). Pure helpers first (unit-tested in tests/test_git_places_ui.js), then the panel used by
// git-progress.js. The browser only sends registration IDs and folder names; the VM helper validates
// every path again.
const gitManagedFolders={latest:'Most recent save',baseline:'Baseline — the reference version you set',checkpoints:'Checkpoints · Named milestones',checkpoint:'Checkpoint — a milestone you saved'};
// expanded: the folders whose children show in the outline. It belongs to the student: nothing but their
// own clicks (and the first display of a repository) changes it, so a refresh never reopens or closes a branch.
const gitPlacesState={labId:'',bindingId:'',model:null,tree:null,selected:'',request:0,open:false,expanded:new Set(['']),expandedFor:'',revealed:''};
function gitSize(bytes){if(!Number.isFinite(bytes)||bytes<0)return '';if(bytes<1024)return bytes+' B';if(bytes<1048576)return (bytes/1024).toFixed(bytes<10240?1:0)+' KB';return (bytes/1048576).toFixed(1)+' MB';}
function gitFolderName(value){
 value=String(value??'').trim();
 if(!/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}$/.test(value)||value.toLowerCase()==='.git'||value==='.'||value==='..')throw new Error('Use letters, numbers, dashes, dots or underscores for the folder name, without slashes.');
 return value;
}
// A whole nested destination typed in one go, e.g. "Week-04/BGP/Final-State". Each
// segment obeys the single-folder rule; the manager and VM helper validate it again.
// latest, baseline and checkpoints are reserved names inside a lab folder (Save progress writes
// them there); a "latest" segment anywhere else in the path (e.g. "course/latest/working") is an
// ordinary folder name and stays allowed.
const GIT_RESERVED_FOLDER_MESSAGE='latest, baseline and checkpoints are the folders Save progress writes inside a lab folder. Choose the folder above them: its saves go to <parent>/latest.';
function gitFolderPath(value){
 const parts=String(value??'').trim().replace(/^\/+|\/+$/g,'').split('/').map(part=>part.trim()).filter(Boolean);
 if(!parts.length)throw new Error('Enter a folder name.');
 const last=parts[parts.length-1],last2=parts.length>1?parts[parts.length-2]:'';
 if(['latest','baseline','checkpoints'].includes(last)||last2==='checkpoints')throw new Error(GIT_RESERVED_FOLDER_MESSAGE);
 return parts.map(gitFolderName).join('/');
}
// The full repository-relative destination, joining an existing parent folder with new segments.
function gitDestinationPreview(parent,typed){
 let nested;try{nested=gitFolderPath(typed);}catch{nested='';}
 if(!nested)return '';
 return parent?parent+'/'+nested:nested;
}
function gitPathChips(path){const chips=[{name:'',path:''}];let current='';for(const part of String(path||'').split('/').filter(Boolean)){current=current?current+'/'+part:part;chips.push({name:part,path:current});}return chips;}
// '' and every folder above `path` ("a/b/c" → '', 'a', 'a/b').
function gitAncestors(path){const out=[''],parts=String(path||'').split('/').filter(Boolean);for(let i=1;i<parts.length;i++)out.push(parts.slice(0,i).join('/'));return out;}
// First display of a repository: the way down to the folder this lab saves to is open, and so is that
// folder. After that the set is only changed by gitToggleFolder and gitRevealFolder.
function gitDefaultExpanded(model,current){const own=gitLabFolder(model,current),open=new Set(['']);if(own){for(const path of gitAncestors(own.path))open.add(path);open.add(own.path);}return open;}
function gitToggleFolder(expanded,path){if(path==='')return expanded;if(expanded.has(path))expanded.delete(path);else expanded.add(path);return expanded;}
// Selecting a folder shows where it is (its ancestors open, and the folder itself so its contents are
// visible in the outline too); it never closes anything.
function gitRevealFolder(expanded,path){for(const parent of gitAncestors(path))expanded.add(parent);expanded.add(path);return expanded;}
// A refresh keeps what still exists.
function gitKeepExpanded(expanded,model){return new Set([...expanded].filter(path=>path===''||model.nodes.has(path)));}
function gitTreeModel(files,folders,planned){
 const nodes=new Map();
 const node=path=>{if(!nodes.has(path))nodes.set(path,{path,name:path.split('/').pop()||'',dirs:[],files:[],registration:null,planned:false,managed:'',pending:false,size:0,count:0});return nodes.get(path);};
 const ensure=path=>{let current='';for(const part of path.split('/').filter(Boolean)){const next=current?current+'/'+part:part,parent=node(current),child=node(next);if(!parent.dirs.includes(child))parent.dirs.push(child);current=next;}return node(current);};
 const root=node('');
 for(const file of files||[]){if(typeof file?.path!=='string'||!file.path||file.path.startsWith('/'))continue;const parts=file.path.split('/'),name=parts.pop();if(!name)continue;ensure(parts.join('/')).files.push({path:file.path,name,size:Number(file.size)||0});}
 for(const folder of folders||[]){if(!folder||typeof folder.prefix!=='string')continue;ensure(folder.prefix).registration=folder;}
 for(const prefix of planned||[]){if(typeof prefix!=='string'||!prefix||prefix.startsWith('/'))continue;ensure(prefix).planned=true;}
 const finish=dir=>{dir.dirs.sort((a,b)=>a.name.localeCompare(b.name));dir.files.sort((a,b)=>a.name.localeCompare(b.name));dir.size=dir.files.reduce((sum,file)=>sum+file.size,0);dir.count=dir.files.length;for(const child of dir.dirs){finish(child);dir.size+=child.size;dir.count+=child.count;}};
 finish(root);
 // pending: a lab folder or a planned folder that holds no saved file yet. It is real as a destination,
 // not as a directory or a commit; the panel says so.
 for(const dir of nodes.values()){if(dir.planned&&!dir.count)dir.pending=true;if(!dir.registration)continue;dir.pending=!dir.count;for(const child of dir.dirs){if(child.name==='latest'||child.name==='baseline'||child.name==='checkpoints'){child.managed=child.name;if(child.name==='checkpoints')for(const grandchild of child.dirs)grandchild.managed='checkpoint';}}}
 // A snapshot folder holds manifest.json among its own files, whatever its name or depth; the
 // manifest and its referenced files (not a name pattern) decide what can be applied. The root
 // folder ('') can be a snapshot too, when the repository itself was saved into directly.
 for(const dir of nodes.values())dir.snapshot=dir.files.some(file=>file.name==='manifest.json');
 // The legacy parent convenience: a folder that is not itself a snapshot, but whose latest/ child is.
 for(const dir of nodes.values()){const latest=dir.dirs.find(child=>child.name==='latest');dir.latestSnapshot=!!(latest&&latest.snapshot);}
 // dir.restorable stays for existing callers: true whenever the folder itself, or its legacy
 // latest/ convenience, resolves to an applyable snapshot (see gitApplySource).
 for(const dir of nodes.values())dir.restorable=!!gitApplySource(dir);
 return {root,nodes};
}
// The exact snapshot a folder applies: itself when it holds manifest.json, its latest/ child when
// only that is a snapshot (the legacy parent convenience — "Broken" with only "Broken/latest" saved),
// otherwise null. Nothing is ever substituted for a folder that is itself a snapshot. The path carries
// the wire form's one leading slash ('/' is the repository root itself); display text strips it again.
function gitApplySource(dir){
 if(!dir)return null;
 if(dir.snapshot)return {path:'/'+dir.path};
 if(dir.latestSnapshot)return {path:'/'+(dir.path?dir.path+'/latest':'latest')};
 return null;
}
function gitOwningFolder(model,path){let best=null;for(const dir of model.nodes.values()){if(!dir.registration)continue;if(dir.path===path||dir.path===''||path.startsWith(dir.path+'/')){if(!best||dir.path.length>best.path.length)best=dir;}}return best;}
function gitLabFolder(model,bindingId){return [...model.nodes.values()].find(dir=>dir.registration&&dir.registration.id===bindingId)||null;}
// The nearest ancestor folder (closest first, the repository root last) that holds manifest.json —
// mirrors the manager's snapshot_conflict: a folder cannot sit at, or below, an existing snapshot
// folder. `path` itself is never checked here (its own dir.snapshot is checked by the caller).
function gitSnapshotAncestor(model,path){
 for(const ancestor of gitAncestors(path).slice().reverse()){const node=model.nodes.get(ancestor);if(node&&node.snapshot)return ancestor;}
 return '';
}
function gitFolderChoice(model,path,current){
 const dir=model.nodes.get(path);if(!dir)return {allowed:false,reason:'Choose a folder.'};
 // A snapshot folder named "latest" is never a destination itself: the choice resolves to its
 // parent (its own saves go to <parent>/latest), whatever the parent's own registration status.
 if(dir.name==='latest'&&dir.snapshot){
  const parentPath=path.includes('/')?path.slice(0,path.lastIndexOf('/')):'',parentChoice=gitFolderChoice(model,parentPath,current);
  const dest=parentPath?parentPath+'/latest':'latest';
  return {...parentChoice,target:parentPath,reason:('This is the saved state of '+(parentPath||'the repository')+'. Saves go to '+dest+'. '+parentChoice.reason).trim()};
 }
 const owner=gitOwningFolder(model,path);
 if(dir.managed)return {allowed:false,reason:dir.managed==='checkpoint'?'This is a saved milestone. Choose a folder outside the lab folder that holds it.':'Save progress writes the '+dir.name+' folder itself. Choose the folder above it.',target:path};
 // Any other snapshot folder (a differently-named one, or one not yet marked "managed" because its
 // parent folder is not registered) is not a destination either: it already holds a saved configuration.
 if(dir.snapshot)return {allowed:false,reason:'This folder is a saved configuration (it holds manifest.json). Choose the folder above it or a folder beside it.',target:path};
 // A folder below an existing snapshot folder (an ancestor holds manifest.json) is refused the same
 // way the manager's own folder routes refuse it, naming the ancestor exactly as the manager does.
 const snapshotAncestor=gitSnapshotAncestor(model,path);
 if(snapshotAncestor)return {allowed:false,reason:snapshotAncestor+' is a saved configuration (it holds manifest.json). Choose the folder above it or a folder beside it.',target:path};
 if(owner&&owner.path!==path&&owner.registration.id!==current){const lab=owner.registration.lab;return {allowed:false,reason:'This folder is inside '+(lab?lab.name+"'s":'another')+' lab folder.',target:path};}
 if(dir.registration){
  if(dir.registration.id===current)return {allowed:false,reason:'This lab already saves here.',target:path};
  if(dir.registration.lab)return {allowed:false,reason:dir.registration.lab.name+' already saves here.',target:path};
  return {allowed:true,reason:'This lab folder is free — no lab saves here yet.',target:path};
 }
 const others=[...model.nodes.values()].filter(other=>other.registration&&other.registration.id!==current);
 if(path===''&&others.some(other=>other.path!==''))return {allowed:false,reason:'This repository already has lab folders for other labs. Pick a free one or create a new folder.',target:path};
 if(path!==''&&others.some(other=>other.path===''))return {allowed:false,reason:'Another lab saves at the top level of this repository, so subfolders cannot be used here.',target:path};
 if(path!==''&&others.some(other=>other.path.startsWith(path+'/')))return {allowed:false,reason:'This folder contains other lab folders.',target:path};
 return {allowed:true,reason:'',target:path};
}
function gitCanCreateIn(model,path,current){
 const dir=model.nodes.get(path);
 if(dir&&dir.snapshot)return false;
 if(gitSnapshotAncestor(model,path))return false;
 const owner=gitOwningFolder(model,path);
 if(dir&&dir.managed&&owner&&owner.registration.id===current)return false;
 return !owner||owner.registration.id===current;
}
function gitFolderTag(dir,current,long=false){
 const registration=dir.registration;if(!registration)return dir.pending?'':'';
 if(registration.id===current)return '<b class="git-tag">This lab'+(long?' saves here':'')+'</b>';
 if(registration.lab)return '<b class="git-tag other">'+esc(registration.lab.name)+(long?' saves here':'')+'</b>';
 return '<b class="git-tag other">Lab folder'+(long?' · available':'')+'</b>';
}
function gitPlacesWhen(value){if(!value)return '';const relative=typeof relativeTime==='function'?relativeTime(value):'';return relative||utcDisplay(value);}
function gitPlacesMarkup(model,view){
 const dir=model.nodes.get(view.selected)||model.root,repoName=view.repoName||'Repository';
 const chips=gitPathChips(dir.path).map((chip,index)=>`${index?'<span aria-hidden="true">›</span>':''}<button type="button" data-git-place="${esc(chip.path)}" ${chip.path===dir.path?'aria-current="page"':''}>${esc(chip.name||repoName)}</button>`).join('');
 // The outline's open branches come from view.expanded only. The folder this lab saves to carries
 // `current` (and the This lab tag) whether or not it is the browsed one (`selected`), and a closed branch
 // that contains it carries `holds-current`, so the destination stays findable without being forced open.
 const expanded=view.expanded||gitDefaultExpanded(model,view.current),own=gitLabFolder(model,view.current);
 const outline=node=>{const open=node.path===''||expanded.has(node.path),kids=node.dirs.length>0,label=node.name||repoName,isCurrent=!!own&&own.path===node.path,holds=!!own&&!open&&node.path!==own.path&&(node.path===''||own.path.startsWith(node.path+'/'));
  return `<details ${open?'open':''} class="${kids?'':'git-leaf'}"><summary data-git-place="${esc(node.path)}" class="${[node.path===dir.path?'selected':'',isCurrent?'current':'',holds?'holds-current':''].filter(Boolean).join(' ')}"${node.path===dir.path?' aria-current="true"':''}>${kids&&node.path!==''?`<button type="button" class="git-twist" data-git-twist="${esc(node.path)}" aria-expanded="${open?'true':'false'}" aria-label="${esc((open?'Collapse ':'Expand ')+label)}"></button>`:'<span class="git-twist-space" aria-hidden="true"></span>'}<i class="git-folder-icon ${node.registration?'lab':node.managed?'managed':''}${node.pending?' pending':''}"></i><span class="git-outline-name" title="${esc(label)}">${esc(label)}</span>${gitFolderTag(node,view.current)}${holds?'<b class="git-tag holds" title="The folder this lab saves to is inside">This lab is inside</b>':''}</summary>${open&&kids?`<div class="git-outline-children">${node.dirs.map(outline).join('')}</div>`:''}</details>`;};
 const rows=[...dir.dirs.map(child=>{const desc=child.managed?gitManagedFolders[child.managed]:child.registration?'Lab folder':child.pending?'Empty folder':'Folder';
   return `<tr class="row folder" data-git-place="${esc(child.path)}"><td><span class="name"><i class="git-folder-icon ${child.registration?'lab':child.managed?'managed':''}${child.pending?' pending':''}"></i>${esc(child.name)}</span></td><td class="desc">${esc(desc)} ${gitFolderTag(child,view.current,true)}${child.pending?' <b class="git-tag pending">not in the repository until the first save</b>':''}</td><td class="size">${child.pending?'':esc(gitSize(child.size))}</td></tr>`;}),
  ...dir.files.map(file=>`<tr class="row"><td><span class="name"><i class="git-file-icon"></i>${esc(file.name)}</span></td><td class="desc">${esc(file.name==='manifest.json'?'Save details (which devices, when they were saved)':/\.(cfg|conf|txt|set)$/i.test(file.name)?'Device configuration':/\.(?:jcfg|eoscfg|xrcfg)$/i.test(file.name)?'Device configuration (can be applied to a running lab)':'File')}</td><td class="size">${esc(gitSize(file.size))}</td></tr>`)];
 const choice=gitFolderChoice(model,dir.path,view.current),creatable=gitCanCreateIn(model,dir.path,view.current);
 const savedAt=view.saved?.latest?view.saved.latest*1000:0;
 const saved=savedAt?'Last saved '+gitPlacesWhen(savedAt):own?'Not saved yet':'';
 // Browsing is not saving: say where the lab saves whenever another folder is being looked at.
 const elsewhere=own&&own.path!==dir.path?'This lab saves to '+(own.path||'the top of the repository')+'. Looking at other folders does not change that.':'';
 const technical=[view.head?'Showing the repository as of commit '+esc(String(view.head).slice(0,10)):'',view.truncated?'Large repository: list shortened to the first 4000 files':'',savedAt?'Last save '+esc(utcDisplay(savedAt)):''].filter(Boolean);
 const applySource=gitApplySource(dir),applyable=view.canApply&&!!applySource;
 const applyBtn=applyable?`<button type="button" class="button danger-outline" data-git-places-action="apply" title="${esc('Load this saved configuration onto the running lab (no reboot)')}">Apply to running lab…</button>`:'';
 const forgettable=view.canAct&&view.canForget&&dir.planned&&dir.pending&&!dir.registration&&!dir.dirs.length;
 const actions=view.canAct?`${applyBtn}${forgettable?'<button type="button" class="button ghost" data-git-places-action="forget" title="Remove this empty folder from the list. Nothing in the repository changes.">Remove empty folder</button>':''}<button type="button" class="button secondary" data-git-places-action="new" ${creatable?'':'disabled'} title="${esc(creatable?'Create a folder here':'Folders cannot be created inside another lab’s folder')}">New folder…</button><button type="button" class="button primary" data-git-places-action="use" ${choice.allowed?'':'disabled'} title="${esc(choice.reason)}">${esc(view.connected?'Save this lab here':'Choose this folder')}</button>`:applyBtn;
 const applyCaption=applyable?(dir.snapshot?'Applies this saved configuration to the running devices. They are not rebooted.':'Applies this folder’s latest save ('+applySource.path.replace(/^\//,'')+') to the running devices. They are not rebooted.'):'';
 const captions=[applyCaption,view.canAct&&!creatable?'Folders cannot be created inside another lab’s folder.':''].filter(Boolean);
 return `<div class="git-places-head"><nav class="git-crumbs" aria-label="Repository folder">${chips}</nav><div class="actions">${actions}</div></div>${captions.length?`<p class="caption git-places-caption">${captions.map(esc).join(' ')}</p>`:''}
 <div class="git-places-body"><div class="git-outline" aria-label="Folders">${outline(model.root)}</div><div class="git-listing">${rows.length?`<table><thead><tr><th>Name</th><th>What it is</th><th>Size</th></tr></thead><tbody>${rows.join('')}</tbody></table>`:`<p class="git-empty-folder">${esc(dir.pending?'Nothing is saved here yet. The folder is kept by the manager and appears in the repository with the first save into it.':'Nothing saved here yet.')}</p>`}</div></div>
 <div class="git-places-foot"><span>${esc(saved)}${technical.length?`<details class="caption"><summary>Details</summary><p>${technical.join(' · ')}</p></details>`:''}</span><span>${esc([elsewhere,choice.reason].filter(Boolean).join(' '))}</span></div>`;
}
// options.tree: a tree the caller already fetched for this binding (the Progress tab reads it once for
// the Saved versions list and the browser). Otherwise the panel fetches it.
async function gitPlacesShow(container,labId,bindingId,options={}){
 const request=++gitPlacesState.request;
 let tree=options.tree||null;
 if(!tree){
  container.innerHTML='<p role="status" class="git-empty-folder">Loading folders…</p>';
  try{tree=await(await api('/git/repositories/'+encodeURIComponent(bindingId)+'/tree')).json();}
  catch(error){
   if(request!==gitPlacesState.request)return null;
   container.innerHTML=`<p class="form-error" role="alert">The folders could not be loaded. ${esc(error.message)}</p><p class="form-help">Check the VM connection (Manager ▾ › VM connection…), then try again.</p><div class="actions"><button type="button" class="button secondary" data-git-places-action="retry">Try again</button></div>`;
   const retry=container.querySelector('[data-git-places-action="retry"]');if(retry)retry.onclick=()=>{if(typeof gitShowRepository==='function')opTask(null,()=>gitShowRepository(true));};
   return null;
  }
 }
 if(request!==gitPlacesState.request)return null;
 const model=gitTreeModel(tree.files,tree.folders,tree.planned);
 // A repository seen for the first time (or another one) gets the default branches; a refresh of the
 // same one keeps the student's branches, selection and focus wherever the folders still exist.
 const checkout=String(tree.repository?.path||bindingId),fresh=gitPlacesState.expandedFor!==checkout;
 if(fresh||!model.nodes.has(gitPlacesState.selected))gitPlacesState.selected=gitLabFolder(model,options.current)?.path??'';
 gitPlacesState.expanded=fresh?gitDefaultExpanded(model,options.current):gitKeepExpanded(gitPlacesState.expanded,model);
 // A selection made by the page itself (a folder just created, the lab's new destination) is shown once;
 // one the student already saw is not reopened by a refresh.
 if(gitPlacesState.revealed!==gitPlacesState.selected){gitRevealFolder(gitPlacesState.expanded,gitPlacesState.selected);gitPlacesState.revealed=gitPlacesState.selected;}
 Object.assign(gitPlacesState,{labId,bindingId,model,tree,expandedFor:checkout});
 const draw=()=>{
  const active=typeof document!=='undefined'&&document.activeElement&&typeof container.contains==='function'&&container.contains(document.activeElement)?document.activeElement:null;
  const focus=active&&active.dataset?(active.dataset.gitTwist!==undefined?['gitTwist',active.dataset.gitTwist]:active.dataset.gitPlace!==undefined&&active.tagName==='SUMMARY'?['gitPlace',active.dataset.gitPlace]:null):null;
  const outlineBox=container.querySelector('.git-outline'),scroll=outlineBox?outlineBox.scrollTop:0;
  container.innerHTML=gitPlacesMarkup(model,{selected:gitPlacesState.selected,expanded:gitPlacesState.expanded,current:options.current,repoName:gitRepoName(tree.repository),head:tree.head,saved:tree.saved,truncated:tree.truncated,canAct:options.canAct!==false,connected:options.connected,canApply:!!options.onApply,canForget:!!options.onForget});
  const select=path=>{gitPlacesState.selected=path;gitPlacesState.revealed=path;gitRevealFolder(gitPlacesState.expanded,path);draw();};
  const toggle=path=>{gitToggleFolder(gitPlacesState.expanded,path);draw();};
  for(const element of container.querySelectorAll('[data-git-place]'))element.onclick=event=>{event.preventDefault();select(element.dataset.gitPlace);};
  for(const element of container.querySelectorAll('[data-git-twist]'))element.onclick=event=>{event.preventDefault();event.stopPropagation();toggle(element.dataset.gitTwist);};
  // Keyboard on a folder of the outline: Right opens it, Left closes it; Enter and Space select (the click above).
  for(const element of container.querySelectorAll('.git-outline summary[data-git-place]'))element.onkeydown=event=>{
   const path=element.dataset.gitPlace,node=model.nodes.get(path),open=gitPlacesState.expanded.has(path);
   if(!node||!node.dirs.length||path==='')return;
   if((event.key==='ArrowRight'&&!open)||(event.key==='ArrowLeft'&&open)){event.preventDefault();toggle(path);}
  };
  const box=container.querySelector('.git-outline');if(box&&scroll)box.scrollTop=scroll;
  if(focus){const again=[...container.querySelectorAll(focus[0]==='gitTwist'?'[data-git-twist]':'.git-outline summary[data-git-place]')].find(element=>element.dataset[focus[0]]===focus[1])||[...container.querySelectorAll('.git-outline summary[data-git-place]')].find(element=>element.dataset.gitPlace===focus[1]);if(again&&typeof again.focus==='function')again.focus();}
  const forget=container.querySelector('[data-git-places-action="forget"]');if(forget&&options.onForget)forget.onclick=()=>opTask(null,()=>options.onForget(gitPlacesState.selected,model,tree));
  const use=container.querySelector('[data-git-places-action="use"]'),create=container.querySelector('[data-git-places-action="new"]'),apply=container.querySelector('[data-git-places-action="apply"]');
  if(use&&options.onUse)use.onclick=()=>opTask(null,()=>options.onUse(gitFolderChoice(model,gitPlacesState.selected,options.current).target,model,tree));
  if(create&&options.onNew)create.onclick=()=>opTask(null,()=>options.onNew(gitPlacesState.selected,model,tree));
  if(apply&&options.onApply)apply.onclick=()=>opTask(null,()=>options.onApply(gitApplySource(model.nodes.get(gitPlacesState.selected))?.path,model,tree));
 };
 draw();return tree;
}
