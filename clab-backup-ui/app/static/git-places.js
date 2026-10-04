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
// A registration on the VM is a lab folder only when a lab saves there: the asking lab's own, or one another
// lab is connected to. One no lab uses (guided setup registers a repository at its top level) is an ordinary
// folder here: no tag, it owns nothing and blocks nothing.
function gitIsLabFolder(registration,current){return !!registration&&(registration.id===current||!!registration.lab);}
// The nearest folder above `path` that is a saved-state folder Save progress writes inside a lab folder
// (latest, baseline, checkpoints, checkpoints/<name>), or null. A lab folder below one would write into
// those saves; the VM refuses it, so the browser does too.
function gitSavedStateAncestor(model,path){
 for(const ancestor of gitAncestors(path).slice().reverse()){const node=model.nodes.get(ancestor);if(node&&node.managed)return ancestor;}
 return null;
}
// The other registered lab folder (any registration, with or without a lab, never the asking lab's own)
// that lies inside what would be `path`'s saved states: path/latest, path/baseline, path/checkpoints (at the
// top level: latest, baseline, checkpoints), or below one. The VM refuses that choice, so the browser does too.
const GIT_SAVED_NAMES=['latest','baseline','checkpoints'];
function gitSavesHoldingLab(model,path,current){
 for(const dir of model.nodes.values()){
  if(!dir.registration||dir.registration.id===current||dir.path===path)continue;
  const rest=path===''?dir.path:dir.path.startsWith(path+'/')?dir.path.slice(path.length+1):null;
  if(rest!==null&&GIT_SAVED_NAMES.includes(rest.split('/')[0]))return dir.path;
 }
 return null;
}
// New folder…: a part directly below a registered lab folder (or the folder the asking lab saves to) may not be
// latest, baseline or checkpoints, because that is where the lab keeps its saves. Returns a sentence, or ''.
function gitNewFolderRefusal(model,joined,current){
 const parts=String(joined||'').split('/').filter(Boolean),own=current?gitLabFolder(model,current):null;
 for(let index=0;index<parts.length;index++){
  const base=parts.slice(0,index).join('/'),node=model.nodes.get(base);
  if(GIT_SAVED_NAMES.includes(parts[index])&&((node&&node.registration)||(own&&own.path===base)))return (base||'The top level')+' is a lab folder, and '+parts[index]+' inside it is where it keeps its saves. Choose another folder name.';
 }
 return '';
}
// Lab folders may sit inside, above or beside each other. What stays refused here: a saved state itself
// (latest, baseline, a checkpoint, any folder holding manifest.json), a folder below one, and the very
// folder another connected lab already saves in.
function gitFolderChoice(model,path,current){
 const dir=model.nodes.get(path);if(!dir)return {allowed:false,reason:'Choose a folder.'};
 // A snapshot folder named "latest" is never a destination itself: the choice resolves to its
 // parent (its own saves go to <parent>/latest), whatever the parent's own registration status.
 if(dir.name==='latest'&&dir.snapshot){
  const parentPath=path.includes('/')?path.slice(0,path.lastIndexOf('/')):'',parentChoice=gitFolderChoice(model,parentPath,current);
  const dest=parentPath?parentPath+'/latest':'latest';
  return {...parentChoice,target:parentPath,reason:('This is the saved state of '+(parentPath||'the repository')+'. Saves go to '+dest+'. '+parentChoice.reason).trim()};
 }
 if(dir.managed)return {allowed:false,reason:dir.managed==='checkpoint'?'This is a saved milestone. Choose a folder outside the lab folder that holds it.':'Save progress writes the '+dir.name+' folder itself. Choose the folder above it.',target:path};
 // Any other snapshot folder (a differently-named one, or one not yet marked "managed" because its
 // parent folder is not registered) is not a destination either: it already holds a saved configuration.
 if(dir.snapshot)return {allowed:false,reason:'This folder is a saved configuration (it holds manifest.json). Choose the folder above it or a folder beside it.',target:path};
 // A folder below an existing snapshot folder (an ancestor holds manifest.json) is refused the same
 // way the manager's own folder routes refuse it, naming the ancestor exactly as the manager does.
 const snapshotAncestor=gitSnapshotAncestor(model,path);
 if(snapshotAncestor)return {allowed:false,reason:snapshotAncestor+' is a saved configuration (it holds manifest.json). Choose the folder above it or a folder beside it.',target:path};
 const savedState=gitSavedStateAncestor(model,path);
 if(savedState!==null)return {allowed:false,reason:'This folder is inside '+savedState+', where Save progress keeps a lab’s saves. Choose a folder outside it.',target:path};
 const holding=gitSavesHoldingLab(model,path,current);
 if(holding!==null&&!(dir.registration&&dir.registration.id===current))return {allowed:false,reason:holding+' is a lab folder inside the place where this folder would keep its saves. Choose another folder.',target:path};
 if(dir.registration&&dir.registration.id===current)return {allowed:false,reason:'This lab already saves here.',target:path};
 if(dir.registration&&dir.registration.lab)return {allowed:false,reason:dir.registration.lab.name+' already saves here.',target:path};
 return {allowed:true,reason:'',target:path};
}
// New folder… works everywhere except inside a saved state: latest, baseline, checkpoints or a checkpoint,
// a folder that holds manifest.json, and any folder below one of those.
const GIT_NO_NEW_FOLDER='Folders cannot be created inside a saved state.';
function gitCanCreateIn(model,path,current){
 const dir=model.nodes.get(path);
 if(dir&&(dir.snapshot||dir.managed))return false;
 return !gitSnapshotAncestor(model,path)&&gitSavedStateAncestor(model,path)===null;
}
function gitFolderTag(dir,current,long=false){
 const registration=dir.registration;if(!gitIsLabFolder(registration,current))return '';
 if(registration.id===current)return '<b class="git-tag">This lab'+(long?' saves here':'')+'</b>';
 return '<b class="git-tag other">'+esc(registration.lab.name)+(long?' saves here':'')+'</b>';
}
function gitPlacesMarkup(model,view){
 const dir=model.nodes.get(view.selected)||model.root,repoName=view.repoName||'Repository';
 const chips=gitPathChips(dir.path).map((chip,index)=>`${index?'<span aria-hidden="true">›</span>':''}<button type="button" data-git-place="${esc(chip.path)}" ${chip.path===dir.path?'aria-current="page"':''}>${esc(chip.name||repoName)}</button>`).join('');
 // The outline's open branches come from view.expanded only. The folder this lab saves to carries
 // `current` (and the This lab tag) whether or not it is the browsed one (`selected`), and a closed branch
 // that contains it carries `holds-current`, so the destination stays findable without being forced open.
 const expanded=view.expanded||gitDefaultExpanded(model,view.current),own=gitLabFolder(model,view.current);
 const outline=node=>{const open=node.path===''||expanded.has(node.path),kids=node.dirs.length>0,label=node.name||repoName,isCurrent=!!own&&own.path===node.path,holds=!!own&&!open&&node.path!==own.path&&(node.path===''||own.path.startsWith(node.path+'/'));
  return `<details ${open?'open':''} class="${kids?'':'git-leaf'}"><summary data-git-place="${esc(node.path)}" class="${[node.path===dir.path?'selected':'',isCurrent?'current':'',holds?'holds-current':''].filter(Boolean).join(' ')}"${node.path===dir.path?' aria-current="true"':''}>${kids&&node.path!==''?`<button type="button" class="git-twist" data-git-twist="${esc(node.path)}" aria-expanded="${open?'true':'false'}" aria-label="${esc((open?'Collapse ':'Expand ')+label)}"></button>`:'<span class="git-twist-space" aria-hidden="true"></span>'}<i class="git-folder-icon ${gitIsLabFolder(node.registration,view.current)?'lab':node.managed?'managed':''}${node.pending?' pending':''}"></i><span class="git-outline-name" title="${esc(label)}">${esc(label)}</span>${gitFolderTag(node,view.current)}${holds?'<b class="git-tag holds" title="The folder this lab saves to is inside">This lab is inside</b>':''}</summary>${open&&kids?`<div class="git-outline-children">${node.dirs.map(outline).join('')}</div>`:''}</details>`;};
 const rows=[...dir.dirs.map(child=>{const lab=gitIsLabFolder(child.registration,view.current),desc=child.managed?gitManagedFolders[child.managed]:lab?'Lab folder':child.pending?'Empty folder':'Folder';
   return `<tr class="row folder" data-git-place="${esc(child.path)}"><td><span class="name"><i class="git-folder-icon ${lab?'lab':child.managed?'managed':''}${child.pending?' pending':''}"></i>${esc(child.name)}</span></td><td class="desc">${esc(desc)} ${gitFolderTag(child,view.current,true)}${child.pending?' <b class="git-tag pending">not in the repository until the first save</b>':''}</td><td class="size">${child.pending?'':esc(gitSize(child.size))}</td></tr>`;}),
  ...dir.files.map(file=>`<tr class="row"><td><span class="name"><i class="git-file-icon"></i>${esc(file.name)}</span></td><td class="desc">${esc(file.name==='manifest.json'?'Save details (which devices, when they were saved)':/\.(cfg|conf|txt|set)$/i.test(file.name)?'Device configuration':/\.(?:jcfg|eoscfg|xrcfg)$/i.test(file.name)?'Device configuration (can be applied to a running lab)':'File')}</td><td class="size">${esc(gitSize(file.size))}</td></tr>`)];
 const choice=gitFolderChoice(model,dir.path,view.current),creatable=gitCanCreateIn(model,dir.path,view.current);
 const savedAt=view.saved?.latest?view.saved.latest*1000:0;
 const saved=savedAt?'Last saved '+gitWhen(savedAt):own?'Not saved yet':'';
 // Browsing is not saving: say where the lab saves whenever another folder is being looked at.
 const elsewhere=own&&own.path!==dir.path?'This lab saves to '+(own.path||'the top of the repository')+'. Looking at other folders does not change that.':'';
 const technical=[view.head?'Showing the repository as of commit '+esc(String(view.head).slice(0,10)):'',view.truncated?'Large repository: list shortened to the first 4000 files':'',savedAt?'Last save '+esc(utcDisplay(savedAt)):''].filter(Boolean);
 const applySource=gitApplySource(dir),applyable=view.canApply&&!!applySource;
 const applyBtn=applyable?`<button type="button" class="button danger-outline" data-git-places-action="apply" title="${esc('Load this saved configuration onto the running lab (no reboot)')}">Apply to running lab…</button>`:'';
 const forgettable=view.canAct&&view.canForget&&dir.planned&&dir.pending&&!dir.registration&&!dir.dirs.length;
 const actions=view.canAct?`${applyBtn}${forgettable?'<button type="button" class="button ghost" data-git-places-action="forget" title="Remove this empty folder from the list. Nothing in the repository changes.">Remove empty folder</button>':''}<button type="button" class="button secondary" data-git-places-action="new" ${creatable?'':'disabled'} title="${esc(creatable?'Create a folder here':GIT_NO_NEW_FOLDER)}">New folder…</button><button type="button" class="button primary" data-git-places-action="use" ${choice.allowed?'':'disabled'} title="${esc(choice.reason)}">${esc(view.connected?'Save this lab here':'Choose this folder')}</button>`:applyBtn;
 const applyCaption=applyable?(dir.snapshot?'Applies this saved configuration to the running devices. They are not rebooted.':'Applies this folder’s latest save ('+applySource.path.replace(/^\//,'')+') to the running devices. They are not rebooted.'):'';
 const captions=[applyCaption,view.canAct&&!creatable?GIT_NO_NEW_FOLDER:''].filter(Boolean);
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

// ===========================================================================================================
// The folder chooser (docs/git-redesign/design/DRAWERS.md section 4). ONE component: the first-save panel's
// folder field, the Save location card and the folder browser's modes. It is hosted by the drawer
// (save-drawers.js: kinds `chooser` and `state`) and by the first-save panel; this file owns markup and the
// mapping from a DOM event to an action. The host owns the requests, the debounce and every piece of state.
// The page decides nothing about a folder: marks, sentences and questions are printed from the manager's
// answer for that folder (DESIGN.md 2.5, 7.4), and the correction echoed while typing is replaced by it.
//
// folderChooserMarkup(model, view) -> html. `model` = folderChooserModel(tree) (null while loading).
//   view.mode          'location' | 'state' | 'browse'
//   view.labName, view.repoName, view.repositories [{id,name}], view.repository   (the select shows only with 2 or more)
//   view.status        'loading' | 'ready' | 'error' | 'unreachable';  view.error the manager's sentence
//   view.value         the text of the path field (echo: folderEcho);  view.selected the picked path or null
//   view.answer        the answer for the typed path from POST .../places/check, else null (the tree's own answer
//                      for a listed path is used when this is null; with neither, "Checking…" is shown)
//   view.expanded      Set of open branches: the person's own (gitPlacesState-style helpers below); view.focus path
//   view.showAll       Set of paths whose branch lists every folder;  view.treeOpen  the state mode's fold
//   view.newFolder     null | {parent, value};  view.notice  a sentence for the answer line (already exists, ...)
//   view.question      null | {kind:'empty', name} | {kind:'same-name', name, beside}
//   view.pending       null | {count, summary}  question 3; `summary` is the upload sentence, '' until the review arrived
//   view.bring         the tick box of the bring-along line (default true);  view.unfinished a save has no commit yet
//   view.firstSave     true in the first-save panel (an answer with same_name then asks the same-name question)
//   view.busy          a place/state request runs;  view.refused  the manager's sentence for a refusal (Try again)
//   view.name          state mode: the name field;  view.showCancel false hides Cancel
// folderChooserEvent(type, event) -> null (not for the chooser) or one of:
//   {action:'select', path}  {action:'toggle', path}  {action:'focus', path}  {action:'typed', value, echo}
//   {action:'new-folder', parent}  {action:'new-input', value, echo}  {action:'new-add', value}  {action:'new-cancel'}
//   {action:'choice', choice}  ('', 'beside' or 'take': what the person chose; the host sends it as it is)
//   {action:'pending', pending}  ('upload': the host runs gitReviewJob(job,{upload:true}) and then posts pending '';
//   'keep': post pending 'keep'; the string 'upload' is never sent)
//   {action:'save'}  {action:'keep'} (close, nothing is sent)  {action:'cancel'}  {action:'bring', value}
//   {action:'repository', value}  {action:'name', value, echo}  {action:'use-another-name'}  {action:'initialize'}
//   {action:'retry'} (load the folders again)  {action:'again'} (send the refused request again)  {action:'vm'}
//   {action:'forget', path}  {action:'show-all', path}  {action:'tree-open', value}  {action:'load', path}  {action:'view', path}
// Enter in the path or name field returns the action of the primary button; a handled key calls preventDefault.
// ===========================================================================================================
const FOLDER_RESERVED=['latest','baseline','checkpoints'],FOLDER_BRANCH_CAP=200;
const FOLDER_UNSAFE=/[^A-Za-z0-9_.-]+/g,FOLDER_UNSAFE_ENDS=/^[^A-Za-z0-9_.-]+|[^A-Za-z0-9_.-]+$/g;
// The manager's clean_folder() (app/git_places.py), the same result for every input: '' is the top level, each
// part is trimmed of unsafe characters at its ends, every other run becomes one '-', what cannot start a name
// is stripped, empty parts go, `.git` becomes `git`. It never refuses. The manager's one error (more than 500
// characters) is answered here by cutting at 500, which the field's maxlength makes unreachable.
function folderClean(value){
 const parts=[];
 for(const raw of String(value??'').split('/')){
  let part=raw.replace(FOLDER_UNSAFE_ENDS,'').replace(FOLDER_UNSAFE,'-');
  if(part.toLowerCase()==='.git')part='git';
  part=part.replace(/^[.-]+/,'').slice(0,181);
  if(part)parts.push(part);
 }
 return parts.join('/').slice(0,500).replace(/\/+$/,'');
}
// What the field shows WHILE typing: folderClean, except that the last part keeps one trailing '-' for a space
// the person just typed ("my " reads "my-", so "my lab" can be typed) and one trailing '/' survives. Only an echo.
function folderEcho(value){
 const text=String(value??''),segments=text.split('/'),parts=[];
 segments.forEach((raw,index)=>{
  const last=index===segments.length-1;
  let part=raw.replace(/^[^A-Za-z0-9_.-]+/,'');
  if(!last)part=part.replace(/[^A-Za-z0-9_.-]+$/,'');
  part=part.replace(FOLDER_UNSAFE,'-');
  if(part.toLowerCase()==='.git')part='git';
  part=part.replace(/^[.-]+/,'').slice(0,181);
  if(part)parts.push(part);
 });
 let folder=parts.join('/');
 if(folder&&segments.length>1&&!segments[segments.length-1].replace(/^[^A-Za-z0-9_.-]+/,'').replace(/^[.-]+/,''))folder+='/';
 return folder.slice(0,500);
}
// The keyboard reducer of the tree (DRAWERS.md 4.8). rows: the visible rows [{path, level, kids, name}],
// expanded: Set of open paths. Focus moves; the selection and `expanded` only change through the returned
// `toggle` / `select`, which the host applies. null: the key is not the tree's.
function folderKey(rows,focusIndex,key,expanded){
 if(!rows||!rows.length)return null;
 const index=Math.min(Math.max(Number(focusIndex)||0,0),rows.length-1),row=rows[index],open=!!expanded&&expanded.has(row.path),stay={focus:index,toggle:null,select:null};
 switch(key){
  case 'ArrowDown':return {...stay,focus:Math.min(index+1,rows.length-1)};
  case 'ArrowUp':return {...stay,focus:Math.max(index-1,0)};
  case 'Home':return {...stay,focus:0};
  case 'End':return {...stay,focus:rows.length-1};
  case 'ArrowRight':
   if(!row.kids)return stay;
   if(!open)return row.path===''?stay:{...stay,toggle:row.path};
   return rows[index+1]&&rows[index+1].level>row.level?{...stay,focus:index+1}:stay;
  case 'ArrowLeft':{
   if(open&&row.kids&&row.path!=='')return {...stay,toggle:row.path};
   for(let up=index-1;up>=0;up--)if(rows[up].level<row.level)return {...stay,focus:up};
   return stay;}
  case 'Enter':case ' ':return {...stay,select:row.path};
 }
 if(typeof key==='string'&&key.length===1&&/\S/.test(key)){
  const letter=key.toLowerCase();
  for(let step=1;step<=rows.length;step++){const at=(index+step)%rows.length;if(String(rows[at].name||'').toLowerCase().startsWith(letter))return {...stay,focus:at};}
  return stay;
 }
 return null;
}
// The model of the tree answer (DESIGN.md 7.4): the nested folders from `files`, the optional helper `dirs`
// and every listed answer, plus the answers by path. `tree.folders` holds one answer per listed folder.
function folderChooserModel(tree){
 if(!tree||typeof tree!=='object')return null;
 const answers=new Map(),listed=[];
 for(const answer of Array.isArray(tree.folders)?tree.folders:[]){if(!answer||typeof answer!=='object')continue;const path=String(answer.path??answer.folder??'');answers.set(path,answer);if(path)listed.push(path);}
 for(const dir of Array.isArray(tree.dirs)?tree.dirs:[]){const path=typeof dir==='string'?dir:dir&&dir.path;if(typeof path==='string'&&path&&!path.startsWith('/'))listed.push(path);}
 const base=gitTreeModel(Array.isArray(tree.files)?tree.files:[],[],listed),below=new Map();
 const mark=node=>{let any=!!node.snapshot;for(const child of node.dirs)if(mark(child))any=true;below.set(node.path,any);return any;};
 mark(base.root);
 return {root:base.root,nodes:base.nodes,answers,below,tree};
}
// The folder this lab saves to in the tree (its answer of kind `own`), so a first display opens the way to it.
function folderOwnPath(model){
 if(!model)return '';
 for(const answer of model.answers.values())if(answer.kind==='own')return String(answer.path??answer.folder??'');
 const own=model.tree&&model.tree.own;
 return own&&typeof own==='object'?String(own.folder??own.path??''):'';
}
function folderDefaultExpanded(model){const open=new Set(['']),own=folderOwnPath(model);if(own){for(const path of gitAncestors(own))open.add(path);open.add(own);}return open;}
// The children a branch lists. A lab folder shows its other subfolders but not latest, baseline or checkpoints,
// a folder that holds a manifest is a leaf, and browse lists everything.
function folderChildren(model,node,mode,showAll,selected){
 let kids=node.dirs;
 if(model.extra&&model.extra.has(node.path))kids=kids.concat(model.extra.get(node.path));
 if(mode!=='browse'){
  if(node.snapshot&&node.path!=='')return {shown:[],more:0};
  const own=model.answers.get(node.path),labFolder=!!own&&['own','lab','own-before'].includes(own.kind);
  kids=kids.filter(child=>!(FOLDER_RESERVED.includes(child.name)&&(labFolder||model.below.get(child.path))));
 }
 if(showAll&&showAll.has(node.path)||kids.length<=FOLDER_BRANCH_CAP)return {shown:kids,more:0};
 const head=kids.slice(0,FOLDER_BRANCH_CAP),sel=String(selected||''),extra=kids.slice(FOLDER_BRANCH_CAP).filter(child=>sel===child.path||sel.startsWith(child.path+'/'));
 return {shown:head.concat(extra),more:kids.length};
}
// A typed path that is in no commit and in no list shows as a provisional row marked New at its place: the
// deepest folder that exists gets the missing parts as virtual children. The model itself is not changed.
function folderWithProvisional(model,path){
 if(!model||!path||model.nodes.has(path))return model;
 const extra=new Map(),parts=path.split('/');let at='',made=false;
 for(const part of parts){
  const next=at?at+'/'+part:part;
  if(!made&&model.nodes.has(next)){at=next;continue;}
  made=true;
  const virtual={path:next,name:part,dirs:[],files:[],snapshot:false,virtual:true};
  extra.set(at,(extra.get(at)||[]).concat([virtual]));at=next;
 }
 return {...model,extra};
}
// The rows that are on screen, in order: [{path, level, kids, name}].
function folderVisibleRows(model,view){
 const rows=[];if(!model)return rows;
 const mode=view.mode||'location',walk=(node,level)=>{
  const {shown}=folderChildren(model,node,mode,view.showAll,view.selected),open=node.path===''||!!node.virtual||!!(view.expanded&&view.expanded.has(node.path));
  rows.push({path:node.path,level,kids:shown.length>0,name:node.name||view.repoName||'Repository'});
  if(open)for(const child of shown)walk(child,level+1);
 };
 walk(model.root,1);return rows;
}
function folderTagFor(answer){
 if(!answer||!answer.mark)return '';
 const cls=answer.kind==='lab'?'git-tag other':answer.kind==='state'?'git-tag folder-state':'git-tag';
 return `<b class="${cls}">${esc(answer.mark)}</b>`;
}
function folderTreeMarkup(model,view){
 const mode=view.mode||'location',rows=folderVisibleRows(model,view),paths=new Set(rows.map(row=>row.path));
 const tab=paths.has(view.focus)?view.focus:paths.has(view.selected)?view.selected:'';
 const repo=view.repoName||'Repository',busy=view.busy;
 let placed=false;
 const rowHtml=()=>`<li role="none" class="folder-new"><label class="sr-only" for="folder-new">New folder in ${esc(view.newFolder.parent||repo)}</label><input id="folder-new" maxlength="500" autocomplete="off" spellcheck="false" value="${esc(view.newFolder.value||'')}"><button type="button" class="button secondary small" data-folder-action="new-add">Add</button><button type="button" class="button ghost small" data-folder-action="new-cancel">Cancel</button></li>`;
 const newRow=parent=>{if(!view.newFolder||placed||view.newFolder.parent!==parent)return '';placed=true;return rowHtml();};
 const item=(node,level)=>{
  const {shown,more}=folderChildren(model,node,mode,view.showAll,view.selected),root=node.path==='',open=root||!!node.virtual||!!(view.expanded&&view.expanded.has(node.path)),answer=model.answers.get(node.path);
  const kids=shown.length>0,selected=view.selected===node.path,label=node.name||repo;
  const cls=answer&&(answer.kind==='own'||answer.kind==='lab'||answer.kind==='own-before')?' lab':answer&&answer.kind==='state'?' managed':'',fresh=!root&&(!!node.virtual||(!!answer&&answer.exists===false));
  const twist=kids&&!root?`<span class="git-twist" data-folder-twist="${esc(node.path)}" aria-hidden="true"></span>`:'<span class="git-twist-space" aria-hidden="true"></span>';
  const row=`<span class="folder-row">${twist}<i class="git-folder-icon${cls}${fresh?' pending':''}"></i><span class="folder-name">${esc(label)}</span>${root?'<small>top level</small>':''}${folderTagFor(answer)}${fresh?'<b class="git-tag pending">New</b>':''}</span>`;
  let children='';
  if(open&&(kids||view.newFolder)){
   children=`<ul role="group">${shown.map(child=>item(child,level+1)).join('')}${more?`<li role="none" class="folder-more"><button type="button" class="link-button" data-folder-action="show-all" data-folder-path="${esc(node.path)}">Show all ${esc(Number(more).toLocaleString('en-US'))} folders</button></li>`:''}${newRow(node.path)}</ul>`;
  }
  return `<li role="treeitem" aria-level="${level}"${kids?` aria-expanded="${open?'true':'false'}"`:''} aria-selected="${selected?'true':'false'}" tabindex="${node.path===tab?'0':'-1'}" data-folder="${esc(node.path)}" data-folder-level="${level}" data-folder-label="${esc(label)}">${row}${children}</li>`;
 };
 const html=item(model.root,1);
 return `<ul class="folder-tree" role="tree" aria-label="${esc('Folders of '+repo)}" id="folder-tree"${busy?' aria-busy="true"':''}>${html}</ul>${view.newFolder&&!placed?`<ul class="folder-new-list" role="none">${rowHtml()}</ul>`:''}`;
}
// browse mode: what the selected folder holds, with the file listing of today's folder browser.
function folderListingMarkup(model,path){
 const dir=model.nodes.get(path||'');if(!dir)return '';
 const rows=[...dir.dirs.map(child=>`<tr class="row folder"><td><span class="name"><i class="git-folder-icon"></i>${esc(child.name)}</span></td><td class="size">${esc(gitSize(child.size))}</td></tr>`),...dir.files.map(file=>`<tr class="row"><td><span class="name"><i class="git-file-icon"></i>${esc(file.name)}</span></td><td class="size">${esc(gitSize(file.size))}</td></tr>`)];
 const source=gitApplySource(dir),buttons=source?`<div class="save-row"><button type="button" class="button secondary small" data-folder-action="load" data-folder-path="${esc(source.path)}">Load this state…</button><button type="button" class="button ghost small" data-folder-action="view" data-folder-path="${esc(source.path)}">View files</button></div>`:'';
 return `<div class="git-listing">${rows.length?`<table><thead><tr><th>Name</th><th>Size</th></tr></thead><tbody>${rows.join('')}</tbody></table>`:'<p class="git-empty-folder">Nothing saved here yet.</p>'}</div>${buttons}`;
}
function folderPlural(count,one,many){return count===1?one:many;}
// One answer in, one sentence, one note and the buttons out. Nothing here classifies a folder.
function folderAnswerView(answer,view){
 const mode=view.mode||'location',lab=view.labName||'This lab',repo=view.repoName||'the repository',out={sentence:'',note:'',buttons:[]};
 const save={label:mode==='state'?'Save state':'Save here',action:'save',primary:true};
 out.buttons=[save];
 const question=view.question;
 if(question&&question.kind==='empty'){
  out.sentence=`${question.name||repo} is empty. The manager adds a README.md file to start it.`;
  out.buttons=[{label:'Start the repository',action:'initialize',primary:true}];return out;
 }
 if(view.pending){
  const count=Number(view.pending.count)||1,summary=String(view.pending.summary||'');
  out.sentence=`${count} ${folderPlural(count,'save','saves')} of ${lab} ${folderPlural(count,'is','are')} waiting for upload.`;
  out.note=(summary||'Checking what this upload sends…')+' '+folderPlural(count,'That save stays','Those saves stay')+' on the VM and '+folderPlural(count,'stays','stay')+' part of the next upload.';
  out.buttons=[{label:'Upload it, then move',pending:'upload',disabled:!summary},{label:'Move and keep that save on the VM only',pending:'keep',primary:true}];return out;
 }
 if(question&&question.kind==='same-name'){
  out.sentence=`This repository already holds saves of a lab named ${question.name||lab}.`;
  out.buttons=[{label:'Continue there',choice:'take'},{label:'Save in '+(question.beside||''),choice:'beside',primary:true}];return out;
 }
 if(!answer)return out;
 const typed=String(answer.typed??''),folder=String(answer.folder??''),beside=String(answer.beside??''),sentences=[];
 if(answer.adjusted==='above-state')sentences.push(`${typed} is part of a saved state, so ${lab} saves in ${folder||'the top level'}, the lab folder above it.`);
 else if(answer.adjusted==='beside-files')sentences.push(`${typed} holds a folder named latest that the manager did not save, so ${lab} saves in ${folder}.`);
 const other=answer.lab&&answer.lab.name?String(answer.lab.name):'';
 if(mode==='state'){
  if(answer.kind==='state'){sentences.push(`“${answer.label||''}” already exists here.`);out.note='The older contents stay in the Git history.';out.buttons=[{label:'Replace it',choice:'take'},{label:'Use another name',action:'use-another-name',primary:true}];}
  else if(answer.kind==='own')sentences.push(`${lab} saves in ${typed}, so the state is saved in ${folder}.`);
  else if(answer.kind==='lab')sentences.push(`${other||'Another lab'} saves in ${typed}, so the state is saved in ${folder}.`);
  out.sentence=sentences.join(' ');return out;
 }
 switch(answer.kind){
  case 'own':sentences.push(`${lab} already saves here.`);out.buttons=[{label:'Keep saving here',action:'keep',primary:true}];break;
  case 'own-before':sentences.push(`${lab} saved here before and continues there.`);break;
  case 'lab':{
   sentences.push(other?`${other} saves here too.`:'This folder is already used for saves on the VM.');
   const suggest={label:'Save in '+beside,choice:'beside',primary:true};
   if(answer.collision){out.note=`${lab} gets a folder of its own inside it.`;out.buttons=[suggest];}
   else{out.note=`If you use this folder anyway, ${other||'the other lab'} is disconnected from it. Its saves stay as versions, and a save of it that is still waiting stays part of the next upload.`;out.buttons=[suggest,{label:'Use this folder anyway',choice:'take'}];}
   break;}
  case 'state':{
   sentences.push(`This folder holds the state “${answer.label||''}”.`);
   const aside={label:beside?'Save beside it in '+beside:'Save beside it',choice:'beside',primary:true};
   if(answer.layout==='flat'){out.note=`If you use this folder anyway, the state “${answer.label||''}” stays listed: its files are stored directly in the folder and are not replaced.`;out.buttons=[aside,{label:'Use this folder anyway',choice:'take'}];}
   else{out.note=`If you replace it, the next save of ${lab} replaces its files. The older contents stay in the Git history.`;out.buttons=[aside,{label:'Replace it',choice:'take'}];}
   break;}
  default:
   if(answer.adjusted==='above-state'||answer.adjusted==='beside-files')break;
   if(folder==='')sentences.push(`${lab} will save at the top level of ${repo}.`);
   else if(answer.exists===false)sentences.push(`${folder} is new. It appears in the repository with the first save.`);
 }
 if(view.firstSave&&answer.same_name){
  sentences.length=0;sentences.push(`This repository already holds saves of a lab named ${lab}.`);
  out.buttons=[{label:'Continue there',choice:'take'},{label:'Save in '+beside,choice:'beside',primary:true}];
 }
 out.sentence=sentences.join(' ');return out;
}
function folderButtonMarkup(button,view){
 const busy=!!view.busy,label=busy&&button.primary&&(button.action==='save'||button.choice!==undefined||button.pending!==undefined)?(view.mode==='state'?'Saving…':'Saving here…'):button.label;
 const data=button.pending!==undefined?`data-folder-pending="${esc(button.pending)}"`:button.choice!==undefined?`data-folder-choice="${esc(button.choice)}"`:`data-folder-action="${esc(button.action)}"`;
 return `<button type="button" class="button ${button.primary?'primary':'secondary'}" ${data}${button.primary?' data-folder-primary="1"':''}${busy||button.disabled?' disabled':''}>${esc(label)}</button>`;
}
function folderChooserMarkup(model,view){
 view=view||{};
 const mode=view.mode||'location',status=view.status||(model?'ready':'loading'),repo=view.repoName||'Repository',lab=view.labName||'This lab',busy=!!view.busy;
 const chosen=model?folderClean(view.value):'';
 const answer=view.answer&&typeof view.answer==='object'?view.answer:(model&&model.answers.get(chosen))||null;
 if(model&&mode!=='browse'&&status==='ready'){
  const target=answer&&answer.folder!==undefined&&answer.folder!==null?String(answer.folder):chosen;
  if(view.selected===undefined||view.selected===null)view={...view,selected:model.nodes.has(target)?target:null};
  model=folderWithProvisional(model,target);
 }
 const parts=[`<div class="folder-chooser" data-mode="${esc(mode)}">`];
 if(mode==='state'){
  parts.push(`<label for="state-name">Name</label><input id="state-name" maxlength="100" autocomplete="off" spellcheck="false" placeholder="start" value="${esc(view.name||'')}"><div class="save-row folder-names" role="group" aria-label="Common names">${['start','broken','final'].map(name=>`<button type="button" class="pill neutral" data-state-name="${name}" aria-pressed="${view.name===name?'true':'false'}">${name}</button>`).join('')}</div>`);
 }
 const repos=Array.isArray(view.repositories)?view.repositories:[];
 if(repos.length>1&&mode!=='browse')parts.push(`<label for="folder-repo">Repository</label><select id="folder-repo"${busy?' disabled':''}>${repos.map(item=>`<option value="${esc(item.id)}"${String(item.id)===String(view.repository)?' selected':''}>${esc(item.name||item.id)}</option>`).join('')}</select>`);
 const shown=answer&&answer.folder!==undefined&&answer.folder!==null?String(answer.folder):folderClean(view.value);
 if(mode!=='browse'){
  parts.push(`<label for="folder-path">Folder</label><input id="folder-path" maxlength="500" autocomplete="off" spellcheck="false" aria-describedby="folder-result folder-answer" value="${esc(view.value??'')}">`);
  parts.push(`<p class="git-destination-line" id="folder-result"><span>${mode==='state'?'The state is saved in':'Saves go to'}</span><code>${esc(repo)}</code><span aria-hidden="true">›</span><code>${esc(shown||'top level')}</code></p>`);
 }
 // The tree area: every state of 4.9.
 let tree='',reason='',tools='';
 if(status==='loading')reason='The folders are still loading.';
 if(status==='unreachable')reason='The lab VM cannot be reached, so its folders cannot be shown.';
 if(status==='loading')tree='<p role="status" class="git-empty-folder">Loading folders…</p>';
 else if(status==='unreachable')tree=`<p class="form-error" role="alert">${esc(reason)}</p><div class="save-row"><button type="button" class="button secondary small" data-folder-action="retry">Try again</button><button type="button" class="button ghost small" data-folder-action="vm">Check the VM connection…</button></div>`;
 else if(status==='error')tree=`<p class="form-error" role="alert">The folders could not be loaded.${view.error?' '+esc(view.error):''}</p><div class="save-row"><button type="button" class="button secondary small" data-folder-action="retry">Try again</button></div>`;
 else if(model)tree=folderTreeMarkup(model,view);
 let note='';
 if(status==='ready'&&model){
  const t=model.tree||{},empty=!(t.files||[]).length&&![...model.answers.keys()].some(Boolean)&&!model.root.dirs.length;
  if(empty)note=`${repo} is empty. ${lab} can save at the top level or in a new folder.`;
  else if(t.dirs_truncated||(t.truncated&&!Array.isArray(t.dirs)))note='This repository is very large and not every folder is listed. Type the path of a folder that is not shown.';
 }
 const treeBlock=`${tree}<p class="save-note" id="folder-tree-note"${note?'':' hidden'}>${esc(note)}</p>`;
 if(mode==='state')parts.push(`<details data-folder-details${view.treeOpen?' open':''}><summary>Put it somewhere else</summary>${treeBlock}`);
 else parts.push(treeBlock);
 parts.push(`<div class="save-row"><button type="button" class="button secondary small" data-folder-action="new" data-folder-parent="${esc(view.selected??'')}">New folder…</button></div>`);
 if(mode==='state')parts.push('</details>');
 if(mode==='browse'&&status==='ready'&&model)parts.push(folderListingMarkup(model,view.selected));
 if(mode!=='browse'){
  // The sentence, its note and its questions. The live region holds only the sentence; buttons are in the foot.
  const checking=!answer&&!view.question&&!view.pending&&(!!view.checking||status==='ready');
  const info=folderAnswerView(answer,{...view,mode,labName:lab,repoName:repo});
  const sentence=[view.notice||'',checking?'Checking…':info.sentence].filter(Boolean).join(' ');
  parts.push(`<p class="folder-answer" id="folder-answer" role="status" aria-live="polite">${esc(sentence)}</p>`);
  const forgettable=!!answer&&answer.kind==='free'&&answer.exists===false&&!!model&&model.answers.has(String(answer.path??answer.folder??''))&&mode==='location';
  const bring=answer&&answer.bring&&mode==='location'?answer.bring:null,unfinished=!!(view.unfinished||(bring&&bring.unfinished));
  const notes=[info.note,bring&&unfinished?`A save of this lab has not finished. Its files stay in ${bring.from||'the folder it leaves'}.`:''].filter(Boolean);
  parts.push(`<p class="save-note" id="folder-answer-note"${notes.length?'':' hidden'}>${esc(notes.join(' '))}</p>`);
  if(forgettable)parts.push(`<div class="save-row"><button type="button" class="button ghost small" data-folder-action="forget" data-folder-path="${esc(String(answer.path??answer.folder??''))}">Remove from the list</button></div>`);
  if(bring&&bring.offered&&!unfinished)parts.push(`<label class="checkbox-label" id="folder-move"><input type="checkbox" data-folder-bring${view.bring===false?'':' checked'}> Bring this lab’s saved files along</label>`);
  if(view.refused)parts.push(`<div class="save-row"><p class="form-error" role="alert" id="folder-refused">${esc(view.refused)}</p><button type="button" class="button secondary small" data-folder-action="again">Try again</button></div>`);
  const blocked=status==='loading'||status==='unreachable';
  const buttons=info.buttons.map(button=>folderButtonMarkup(blocked&&button.primary?{...button,disabled:true}:button,view)).join('');
  parts.push(`<div class="save-settings-foot" id="folder-foot">${view.showCancel===false?'':'<button type="button" class="button ghost small" data-folder-action="cancel">Cancel</button>'}${buttons}${blocked?`<span class="form-help" id="folder-reason">${esc(reason)}</span>`:''}</div>`);
  parts.push(mode==='state'?`<p class="save-note">Reads every included device now. Saved files can contain passwords or keys. Where ${esc(lab)} normally saves does not change.</p>`:'<p class="save-note">Saved files can contain passwords or keys.</p>');
 }
 parts.push('</div>');
 return parts.join('');
}
// ---- the event seam -----------------------------------------------------------------------------------------
function folderUp(event,selector){const target=event&&event.target;return target&&typeof target.closest==='function'?target.closest(selector):null;}
function folderAttr(element,name){return element&&typeof element.getAttribute==='function'?element.getAttribute(name):null;}
function folderRoot(event){return folderUp(event,'.folder-chooser');}
function folderInputValue(event,id){const root=folderRoot(event),input=root&&typeof root.querySelector==='function'?root.querySelector('#'+id):null;return input?String(input.value??''):'';}
function folderButtonAction(button,event){
 if(!button)return null;
 const data=button.dataset||{};
 if(data.folderPending!==undefined)return {action:'pending',pending:String(data.folderPending)};
 if(data.folderChoice!==undefined)return {action:'choice',choice:String(data.folderChoice)};
 if(data.stateName!==undefined){const value=String(data.stateName);return {action:'name',value,echo:folderEcho(value)};}
 const name=data.folderAction;
 if(name===undefined)return null;
 if(name==='new')return {action:'new-folder',parent:String(data.folderParent??'')};
 if(name==='new-add')return {action:'new-add',value:folderInputValue(event,'folder-new')};
 const out={action:String(name)};
 if(data.folderPath!==undefined)out.path=String(data.folderPath);
 return out;
}
function folderChooserEvent(type,event){
 if(!event)return null;
 const stop=()=>{if(typeof event.preventDefault==='function')event.preventDefault();};
 if(type==='click'){
  const twist=folderUp(event,'[data-folder-twist]');
  if(twist)return {action:'toggle',path:String(twist.dataset.folderTwist)};
  const button=folderUp(event,'[data-folder-pending],[data-folder-choice],[data-state-name],[data-folder-action]');
  if(button){if(button.disabled)return null;return folderButtonAction(button,event);}
  const row=folderUp(event,'.folder-row'),item=row&&folderUp(event,'[data-folder]');
  if(item)return {action:'select',path:String(item.dataset.folder)};
  return null;
 }
 if(type==='input'){
  const id=event.target&&event.target.id,value=String(event.target&&event.target.value!==undefined?event.target.value:'');
  if(id==='folder-path')return {action:'typed',value,echo:folderEcho(value)};
  if(id==='folder-new')return {action:'new-input',value,echo:folderEcho(value)};
  if(id==='state-name')return {action:'name',value,echo:folderEcho(value.replace(/\//g,'-'))};
  return null;
 }
 if(type==='change'){
  const target=event.target||{};
  if(target.id==='folder-repo')return {action:'repository',value:String(target.value??'')};
  if(target.dataset&&target.dataset.folderBring!==undefined)return {action:'bring',value:!!target.checked};
  return null;
 }
 if(type==='toggle'){
  const details=folderUp(event,'[data-folder-details]');
  return details?{action:'tree-open',value:!!details.open}:null;
 }
 if(type==='keydown'){
  const id=event.target&&event.target.id,key=event.key;
  if(id==='folder-new'){
   if(key==='Enter'){stop();return {action:'new-add',value:folderInputValue(event,'folder-new')};}
   if(key==='Escape'){stop();if(typeof event.stopPropagation==='function')event.stopPropagation();return {action:'new-cancel'};}
   return null;
  }
  if(id==='folder-path'||id==='state-name'){
   if(key!=='Enter')return null;
   const root=folderRoot(event),primary=root&&typeof root.querySelector==='function'?root.querySelector('[data-folder-primary]'):null;
   stop();
   return primary&&!primary.disabled?folderButtonAction(primary,event):null;
  }
  const item=folderUp(event,'[role="treeitem"]'),root=folderRoot(event);
  if(!item||!root||typeof root.querySelectorAll!=='function'||folderUp(event,'button,input,select'))return null;
  const items=[...root.querySelectorAll('[role="treeitem"]')],expanded=new Set(),rows=items.map(element=>{
   const path=String(element.dataset.folder??'');if(folderAttr(element,'aria-expanded')==='true')expanded.add(path);
   return {path,level:Number(element.dataset.folderLevel)||1,kids:folderAttr(element,'aria-expanded')!==null,name:String(element.dataset.folderLabel??'')};
  });
  const index=rows.findIndex(row=>row.path===String(item.dataset.folder??'')),moved=folderKey(rows,index,key,expanded);
  if(!moved||event.ctrlKey||event.metaKey||event.altKey)return null;
  stop();
  if(moved.toggle!==null)return {action:'toggle',path:moved.toggle};
  if(moved.select!==null)return {action:'select',path:moved.select};
  return {action:'focus',path:rows[moved.focus].path};
 }
 return null;
}
// Focus and scroll survive a re-render: the host calls the first before it replaces the markup and the second
// after (setMarkup keeps the typed text of the two fields).
function folderChooserSnapshot(root){
 if(!root||typeof document==='undefined')return null;
 const active=document.activeElement;if(!active||typeof root.contains!=='function'||!root.contains(active))return null;
 const item=typeof active.closest==='function'?active.closest('[role="treeitem"]'):null,tree=typeof root.querySelector==='function'?root.querySelector('#folder-tree'):null;
 const key=active.id?{id:active.id}:active.dataset&&active.dataset.folder!==undefined&&item===active?{path:active.dataset.folder}:active.dataset&&active.dataset.folderAction!==undefined?{action:active.dataset.folderAction,path:active.dataset.folderPath||''}:null;
 return {key,scroll:tree?tree.scrollTop:0};
}
function folderChooserRestore(root,snapshot){
 if(!root||!snapshot||typeof root.querySelectorAll!=='function')return false;
 const tree=root.querySelector('#folder-tree');if(tree&&snapshot.scroll)tree.scrollTop=snapshot.scroll;
 const key=snapshot.key;if(!key)return false;
 const all=[...root.querySelectorAll('[role="treeitem"],[id],[data-folder-action]')];
 const found=all.find(element=>key.id!==undefined?element.id===key.id:key.path!==undefined?element.dataset&&element.dataset.folder===key.path&&element.getAttribute&&element.getAttribute('role')==='treeitem':element.dataset&&element.dataset.folderAction===key.action&&(element.dataset.folderPath||'')===key.path);
 if(found&&typeof found.focus==='function'){found.focus();return true;}
 return false;
}
