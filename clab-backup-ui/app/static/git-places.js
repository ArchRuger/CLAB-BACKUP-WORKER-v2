'use strict';
// "Where this lab lives": the committed folders of a registered repository, read from the VM checkout.
// Pure helpers first (unit-tested in tests/test_git_places_ui.js), then the panel used by git-progress.js.
// The browser only sends registration IDs and folder names; the VM helper validates every path again.
const gitManagedFolders={latest:'Most recent save',baseline:'Reference version set with Set baseline',checkpoints:'Named milestones',checkpoint:'Milestone saved with Save checkpoint'};
const gitPlacesState={labId:'',bindingId:'',model:null,tree:null,selected:'',request:0};
function gitSize(bytes){if(!Number.isFinite(bytes)||bytes<0)return '';if(bytes<1024)return bytes+' B';if(bytes<1048576)return (bytes/1024).toFixed(bytes<10240?1:0)+' KB';return (bytes/1048576).toFixed(1)+' MB';}
function gitFolderName(value){
 value=String(value??'').trim();
 if(!/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}$/.test(value)||value.toLowerCase()==='.git'||value==='.'||value==='..')throw new Error('Use letters, numbers, dashes, dots or underscores for the folder name, without slashes.');
 return value;
}
// A whole nested destination typed in one go, e.g. "Week-04/BGP/Final-State". Each
// segment obeys the single-folder rule; the manager and VM helper validate it again.
function gitFolderPath(value){
 const parts=String(value??'').trim().replace(/^\/+|\/+$/g,'').split('/').map(part=>part.trim()).filter(Boolean);
 if(!parts.length)throw new Error('Enter a folder name.');
 return parts.map(gitFolderName).join('/');
}
// The full repository-relative destination, joining an existing parent folder with new segments.
function gitDestinationPreview(parent,typed){
 let nested;try{nested=gitFolderPath(typed);}catch{nested='';}
 if(!nested)return '';
 return parent?parent+'/'+nested:nested;
}
function gitPathChips(path){const chips=[{name:'',path:''}];let current='';for(const part of String(path||'').split('/').filter(Boolean)){current=current?current+'/'+part:part;chips.push({name:part,path:current});}return chips;}
function gitTreeModel(files,folders){
 const nodes=new Map();
 const node=path=>{if(!nodes.has(path))nodes.set(path,{path,name:path.split('/').pop()||'',dirs:[],files:[],registration:null,managed:'',pending:false,size:0,count:0});return nodes.get(path);};
 const ensure=path=>{let current='';for(const part of path.split('/').filter(Boolean)){const next=current?current+'/'+part:part,parent=node(current),child=node(next);if(!parent.dirs.includes(child))parent.dirs.push(child);current=next;}return node(current);};
 const root=node('');
 for(const file of files||[]){if(typeof file?.path!=='string'||!file.path||file.path.startsWith('/'))continue;const parts=file.path.split('/'),name=parts.pop();if(!name)continue;ensure(parts.join('/')).files.push({path:file.path,name,size:Number(file.size)||0});}
 for(const folder of folders||[]){if(!folder||typeof folder.prefix!=='string')continue;ensure(folder.prefix).registration=folder;}
 const finish=dir=>{dir.dirs.sort((a,b)=>a.name.localeCompare(b.name));dir.files.sort((a,b)=>a.name.localeCompare(b.name));dir.size=dir.files.reduce((sum,file)=>sum+file.size,0);dir.count=dir.files.length;for(const child of dir.dirs){finish(child);dir.size+=child.size;dir.count+=child.count;}};
 finish(root);
 for(const dir of nodes.values()){if(!dir.registration)continue;dir.pending=!dir.count;for(const child of dir.dirs){if(child.name==='latest'||child.name==='baseline'||child.name==='checkpoints'){child.managed=child.name;if(child.name==='checkpoints')for(const grandchild of child.dirs)grandchild.managed='checkpoint';}}}
 return {root,nodes};
}
function gitOwningFolder(model,path){let best=null;for(const dir of model.nodes.values()){if(!dir.registration)continue;if(dir.path===path||dir.path===''||path.startsWith(dir.path+'/')){if(!best||dir.path.length>best.path.length)best=dir;}}return best;}
function gitLabFolder(model,bindingId){return [...model.nodes.values()].find(dir=>dir.registration&&dir.registration.id===bindingId)||null;}
function gitFolderChoice(model,path,current){
 const dir=model.nodes.get(path);if(!dir)return {allowed:false,reason:'Choose a folder.'};
 const owner=gitOwningFolder(model,path);
 if(dir.managed)return {allowed:false,reason:dir.managed==='checkpoint'?'This is a saved milestone. Choose a folder outside the lab folder that holds it.':'The lab manager fills '+dir.name+' folders itself. Choose the folder above it.'};
 if(owner&&owner.path!==path&&owner.registration.id!==current){const lab=owner.registration.lab;return {allowed:false,reason:'This folder is inside '+(lab?lab.name+"'s":'another')+' lab folder.'};}
 if(dir.registration){
  if(dir.registration.id===current)return {allowed:false,reason:'This lab already saves here.'};
  if(dir.registration.lab)return {allowed:false,reason:dir.registration.lab.name+' already saves here.'};
  return {allowed:true,reason:'A lab folder no lab is using.'};
 }
 const others=[...model.nodes.values()].filter(other=>other.registration&&other.registration.id!==current);
 if(path===''&&others.some(other=>other.path!==''))return {allowed:false,reason:'This repository already has lab folders. Pick one of them or create a new folder.'};
 if(path!==''&&others.some(other=>other.path===''))return {allowed:false,reason:'A lab saves at the root of this repository, so it cannot also use folders.'};
 if(path!==''&&others.some(other=>other.path.startsWith(path+'/')))return {allowed:false,reason:'This folder contains other lab folders.'};
 return {allowed:true,reason:''};
}
function gitCanCreateIn(model,path,current){const owner=gitOwningFolder(model,path);return !owner||owner.registration.id===current;}
function gitFolderTag(dir,current,long=false){
 const registration=dir.registration;if(!registration)return dir.pending?'':'';
 if(registration.id===current)return '<b class="git-tag">This lab'+(long?' saves here':'')+'</b>';
 if(registration.lab)return '<b class="git-tag other">'+esc(registration.lab.name)+(long?' saves here':'')+'</b>';
 return '<b class="git-tag other">Lab folder'+(long?' · not connected to a lab':'')+'</b>';
}
function gitPlacesMarkup(model,view){
 const dir=model.nodes.get(view.selected)||model.root,repoName=view.repoName||'Repository';
 const chips=gitPathChips(dir.path).map((chip,index)=>`${index?'<span aria-hidden="true">›</span>':''}<button type="button" data-git-place="${esc(chip.path)}" ${chip.path===dir.path?'aria-current="page"':''}>${esc(chip.name||repoName)}</button>`).join('');
 const outline=node=>{const open=node.path===''||dir.path===node.path||dir.path.startsWith(node.path+'/');
  return `<details ${open?'open':''} class="${node.dirs.length?'':'git-leaf'}"><summary data-git-place="${esc(node.path)}" class="${node.path===dir.path?'selected':''}"><i class="git-folder-icon ${node.registration?'lab':node.managed?'managed':''}${node.pending?' pending':''}"></i><span>${esc(node.name||repoName)}</span>${gitFolderTag(node,view.current)}</summary><div class="git-outline-children">${node.dirs.map(outline).join('')}</div></details>`;};
 const rows=[...dir.dirs.map(child=>{const desc=child.managed?gitManagedFolders[child.managed]:child.registration?(child.pending?'Lab folder · empty until its first save':'Lab folder'):'Folder';
   return `<tr class="row folder" data-git-place="${esc(child.path)}"><td><span class="name"><i class="git-folder-icon ${child.registration?'lab':child.managed?'managed':''}${child.pending?' pending':''}"></i>${esc(child.name)}</span></td><td class="desc">${esc(desc)} ${gitFolderTag(child,view.current,true)}${child.pending?' <b class="git-tag pending">created on first save</b>':''}</td><td class="size">${child.pending?'':esc(gitSize(child.size))}</td></tr>`;}),
  ...dir.files.map(file=>`<tr class="row"><td><span class="name"><i class="git-file-icon"></i>${esc(file.name)}</span></td><td class="desc">${esc(file.name==='manifest.json'?'Save details: devices, checksums, capture time':/\.(cfg|conf|txt|set)$/i.test(file.name)?'Device configuration':'File')}</td><td class="size">${esc(gitSize(file.size))}</td></tr>`)];
 const choice=gitFolderChoice(model,dir.path,view.current),creatable=gitCanCreateIn(model,dir.path,view.current);
 const saved=view.saved?.latest?'Last save '+utcDisplay(view.saved.latest*1000):view.current&&gitLabFolder(model,view.current)?'No save yet':'';
 const actions=view.canAct?`<button type="button" class="button secondary" data-git-places-action="new" ${creatable?'':'disabled'} title="${esc(creatable?'Create a folder here':'Folders cannot be created inside a lab folder')}">New folder…</button><button type="button" class="button primary" data-git-places-action="use" ${choice.allowed?'':'disabled'} title="${esc(choice.reason)}">${esc(view.connected?'Save this lab here':'Choose this folder')}</button>`:'';
 return `<div class="git-places-head"><nav class="git-crumbs" aria-label="Repository folder">${chips}</nav><div class="actions">${actions}</div></div>
 <div class="git-places-body"><div class="git-outline" aria-label="Folders">${outline(model.root)}</div><div class="git-listing">${rows.length?`<table><thead><tr><th>Name</th><th>What it is</th><th>Size</th></tr></thead><tbody>${rows.join('')}</tbody></table>`:`<p class="git-empty-folder">${esc(dir.pending?'This folder appears in the repository after the first save.':'Nothing here yet.')}</p>`}</div></div>
 <div class="git-places-foot"><span>${esc(saved)}${view.head?(saved?' · ':'')+'as of commit '+esc(String(view.head).slice(0,10)):''}${view.truncated?' · list shortened to the first 4000 files':''}</span><span>${choice.allowed?esc(choice.reason):esc(choice.reason)}</span></div>`;
}
async function gitPlacesShow(container,labId,bindingId,options={}){
 const request=++gitPlacesState.request;
 container.innerHTML='<p role="status" class="git-empty-folder">Reading the repository folders on the VM…</p>';
 let tree;
 try{tree=await(await api('/git/repositories/'+encodeURIComponent(bindingId)+'/tree')).json();}
 catch(error){if(request===gitPlacesState.request)container.innerHTML=`<p class="form-error" role="alert">${esc(error.message)}</p><p class="form-help">Check the VM connection and choose Refresh status.</p>`;return null;}
 if(request!==gitPlacesState.request)return null;
 const model=gitTreeModel(tree.files,tree.folders);
 if(gitPlacesState.bindingId!==bindingId||!model.nodes.has(gitPlacesState.selected))gitPlacesState.selected=gitLabFolder(model,options.current)?.path??'';
 Object.assign(gitPlacesState,{labId,bindingId,model,tree});
 const draw=()=>{
  container.innerHTML=gitPlacesMarkup(model,{selected:gitPlacesState.selected,current:options.current,repoName:gitRepoName(tree.repository),head:tree.head,saved:tree.saved,truncated:tree.truncated,canAct:options.canAct!==false,connected:options.connected});
  for(const element of container.querySelectorAll('[data-git-place]'))element.onclick=event=>{event.preventDefault();gitPlacesState.selected=element.dataset.gitPlace;draw();};
  const use=container.querySelector('[data-git-places-action="use"]'),create=container.querySelector('[data-git-places-action="new"]');
  if(use&&options.onUse)use.onclick=()=>opTask(null,()=>options.onUse(gitPlacesState.selected,model,tree));
  if(create&&options.onNew)create.onclick=()=>opTask(null,()=>options.onNew(gitPlacesState.selected,model,tree));
 };
 draw();return tree;
}
