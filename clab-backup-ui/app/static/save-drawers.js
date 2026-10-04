'use strict';
// The one drawer of the Git save and load redesign (docs/git-redesign/design/DRAWERS.md): `dialog#save-drawer` shows
// What changed, All versions, Save settings, the folder chooser and Save as a lab state, and (for load.js) the
// differences of a load. One <dialog>, one head, one content at a time, so "one drawer open" holds by construction.
// The head is static markup; only text and `hidden` change. The content is written through drwSet(), a keyed
// setter like setMarkup that also puts focus, caret and scroll back after a rebuild, so the 4 second poll never
// moves focus, drops typed text, unticks a box or closes the open row (all of that lives in saveDrawer, not in the DOM).
// Other scripts' functions are read at call time behind typeof guards, so this file loads alone in Node.
// Names this file offers: saveDrawerOpen, saveDrawerRender, saveDrawerClose (and saveDrawerBack, saveDrawerRefresh).
// It never sends an upload itself: Upload is gitReviewJob(job,{upload:true}) of git-progress.js.
const DRW_KINDS=['changes','versions','settings','chooser','state','different','compare','files'];
const DRW_WAITING=['committed','review_pending','push_pending','interrupted'];
const DRW_ACTIVE=['queued','capturing','exporting','pushing'];
const saveDrawer={kind:'',lab:'',back:null,request:0,opener:null,openRow:'',data:null,draft:null,options:{},folds:new Map(),chooser:null};
function drwEl(id){return typeof $==='function'?$(id):null;}
function drwLabId(){return saveDrawer.lab||(typeof activeId==='string'?activeId:'');}
function drwLab(){const id=drwLabId();return (typeof state==='object'&&state&&Array.isArray(state.labs)?state.labs.find(l=>l.id===id):null)||null;}
function drwLabName(){return drwLab()?.name||(typeof gitLabName==='function'?gitLabName(drwLabId()):'This lab');}
function drwEnc(value){return encodeURIComponent(value);}
function drwJobs(){const id=drwLabId();if(typeof gitLabJobs==='function')return gitLabJobs(id);return ((typeof state==='object'&&state&&state.git_jobs)||[]).filter(job=>!job.lab_id||job.lab_id===id);}
function drwWaiting(job){return !!(job&&job.commit&&!job.pushed&&DRW_WAITING.includes(job.status));}
function drwWhen(value){if(!value)return '';return typeof gitWhen==='function'?gitWhen(value):String(value);}
function drwShort(commit){return String(commit||'').slice(0,7);}
function drwDevices(n){return Number.isFinite(n)?n+(n===1?' device':' devices'):'';}
function drwDir(path){const text=String(path||'');return text.includes('/')?text.slice(0,text.lastIndexOf('/')):'';}
function drwJoin(parent,name){return [parent,name].filter(Boolean).join('/');}
function drwBare(path){return String(path||'').replace(/^\/+|\/+$/g,'');}
function drwHost(job){const d=job?.destination||{},raw=d.remote||d.push_url||'';if(!raw)return 'the online copy';try{return new URL(raw).hostname||raw;}catch{return String(raw).replace(/^[a-z+]+:\/\//,'').replace(/^.*@/,'').replace(/[:/].*$/,'')||'the online copy';}}
function drwFold(key,fallback){return saveDrawer.folds.has(key)?saveDrawer.folds.get(key):fallback;}
function drwSay(text){const el=drwEl('save-drawer-status');if(el)el.textContent=text||'';}
function drwDiff(diff,oldLabel,newLabel){return typeof diffMarkup==='function'?diffMarkup(diff,{oldLabel,newLabel}):'<p class="save-note">The changes cannot be shown on this page.</p>';}
function drwAlsoSentence(rows){
 const list=(rows||[]).map(row=>row.lab&&row.job_id?`${row.name} (${row.lab})`:row.name||row.subject||'a save').filter(Boolean);
 return list.length?`This upload also sends ${list.length} other ${list.length===1?'save':'saves'}: ${list.join(', ')}.`:'';
}
// ---- What changed: the accounting of one save (DESIGN.md 3.4, DRAWERS.md 1.2) ----
// Every row of review.files becomes, or joins, one entry; a `restore` row is a line under its device and never a second
// change; a row with no known role is `other`, so a missing role cannot hide a file. `rest` is job.changed_files minus
// every path an entry stands for: it is empty with the ruled answer, and shown when the backend left a gap.
function saveChangeAccount(job,review){
 const files=Array.isArray(review?.files)?review.files:[],changed=Array.isArray(job?.changed_files)?job.changed_files.map(String):[];
 const primary=drwBare(job?.snapshot_path),entries=[],byKey=new Map();
 const entry=(key,make)=>{if(!byKey.has(key)){const e={...make(),key,paths:[]};byKey.set(key,e);entries.push(e);}return byKey.get(key);};
 const rows=files.map(f=>{const name=String(f?.name||''),own=typeof f?.path==='string'&&f.path;return {f,name,path:own?drwBare(f.path):name.includes('/')?drwBare(name):primary?drwJoin(primary,name):name,known:!!own||name.includes('/')||!!primary};});
 for(const {f,name,path} of rows){
  const folder=drwDir(path),role=['device','restore','topology','map','manifest'].includes(f.role)?f.role:'other';
  let target;
  if(primary&&folder!==primary)target=entry('copy:'+path,()=>({role:'other',title:path,file:name,status:f.status,diff:f.diff,restore:null,sameText:false}));
  else if(role==='device'){target=entry('device:'+(f.node||path),()=>({role:'device',title:f.node||name,node:f.node||'',file:name,status:f.status,diff:f.diff,restore:null,sameText:false}));if(target.sameText||!target.file){Object.assign(target,{file:name,status:f.status,diff:f.diff,sameText:false});}}
  else if(role==='restore'){target=entry('device:'+(f.node||path),()=>({role:'device',title:f.node||name,node:f.node||'',file:'',status:f.status,diff:null,restore:null,sameText:true}));target.restore={name,status:f.status,diff:f.diff};}
  else if(role==='topology')target=entry('topology:'+folder,()=>({role:'topology',title:'Topology file',file:name,status:f.status,diff:f.diff,restore:null,sameText:false}));
  else if(role==='map')target=entry('map:'+folder,()=>({role:'map',title:'Map',file:name,status:f.status,diff:f.diff,restore:null,sameText:false}));
  else if(role==='manifest')target=entry('manifest:'+folder,()=>({role:'manifest',title:'Save details',file:name,status:f.status,diff:f.diff,restore:null,sameText:false}));
  else target=entry('other:'+path,()=>({role:'other',title:name||path,file:name,status:f.status,diff:f.diff,restore:null,sameText:false}));
  target.paths.push(path);
 }
 const covered=new Set(entries.flatMap(e=>e.paths));
 // A row that names no folder (an older answer) is matched to a changed path by its file name.
 const rest=[];
 for(const path of changed){
  if(covered.has(path))continue;
  const row=rows.find(r=>!r.known&&(path===r.name||path.endsWith('/'+r.name)));
  if(row){const e=entries.find(x=>x.paths.includes(row.path));if(e){e.paths.push(path);covered.add(path);continue;}}
  rest.push(path);
 }
 return {entries,rest};
}
// The exact folder a save wrote: its own recorded path, else (a save from before that was recorded) the lab's folder joined with
// its target, as the old review window's "Open the full saved version" resolved it.
function drwJobPath(job){
 if(job&&job.snapshot_path)return drwBare(job.snapshot_path);
 const binding=drwLab()?.git_binding||(typeof gitContexts!=='undefined'&&gitContexts&&typeof gitContexts.get==='function'?gitContexts.get(drwLabId())?.binding:null);
 return typeof gitSnapshotPath==='function'&&typeof gitTargetPath==='function'&&job?drwBare(gitSnapshotPath(binding,gitTargetPath(job))):'';
}
function drwEntryMarkup(e){
 const word=typeof diffStatusWord==='function'?diffStatusWord(e.status):e.status==='added'?'added':e.status==='removed'?'removed':'changed';
 const small=e.file&&e.file!==e.title?` <small>${esc(e.file)}</small>`:'';
 let body;
 if(e.sameText)body=`<p class="save-note">The configuration text is the same. The file Load uses changed.</p>${e.restore?drwDiff(e.restore.diff,'Before this save','This save'):''}`;
 else{
  body=drwDiff(e.diff,'Before this save','This save');
  if(e.restore)body+=`<details data-fold="${esc('restore:'+e.key)}" ${drwFold('restore:'+e.key,false)?'open':''}><summary>${esc(`Also uploaded for ${e.title}: ${e.restore.name}, the file Load uses`)}</summary>${drwDiff(e.restore.diff,'Before this save','This save')}</details>`;
 }
 const identical=!e.sameText&&e.diff&&e.diff.identical&&!e.diff.truncated;
 const open=drwFold('entry:'+e.key,e.role!=='manifest'&&!identical);
 return `<details class="diff-file" data-fold="${esc('entry:'+e.key)}" ${open?'open':''}><summary>${esc(e.title)}${small} <span class="badge">${esc(word)}</span></summary><div class="diff-body">${body}</div></details>`;
}
function drwEntriesMarkup(account){return account.entries.map(drwEntryMarkup).join('');}
function drwRestPaths(paths){return paths.length?`<ul class="save-list">${paths.map(p=>`<li><code>${esc(p)}</code></li>`).join('')}</ul>`:'';}
function drwAlsoKey(row){return row.job_id?'job-'+row.job_id:'commit-'+(row.commit||row.name||'');}
function drwAlsoJob(row){return ((typeof state==='object'&&state&&state.git_jobs)||[]).find(j=>j.id===row.job_id)||{id:row.job_id,lab_id:drwLabId()};}
function drwAlsoMarkup(row,d){
 const key=drwAlsoKey(row),fold='also:'+key,open=drwFold(fold,false),got=d.also.get(key)||{};
 const name=row.name||row.subject||'A save',job=row.job_id?drwAlsoJob(row):null;
 const small=row.job_id?[row.lab,job&&(job.finished||job.created)?'saved '+drwWhen(job.finished||job.created):''].filter(Boolean).join(' · '):'a save the manager no longer keeps';
 let body='';
 if(open){
  if(!row.job_id){const paths=(row.files||row.paths||[]).map(p=>typeof p==='string'?p:p?.path||p?.name||'').filter(Boolean);body=paths.length?drwRestPaths(paths):'<p class="save-note">Its files are not listed.</p>';}
  else if(got.error)body=`<p class="save-note">${esc(name)} could not be read.</p><div class="save-row"><button type="button" class="button ghost small" data-save-action="also-retry" data-save-also="${esc(key)}">Try again</button></div>`;
  else if(got.review){const account=saveChangeAccount({...job,changed_files:job.changed_files||[]},got.review);body=drwEntriesMarkup(account)+drwRestPaths(account.rest)||'<p class="save-note">Nothing to show.</p>';}
  else body='<p class="save-note">Reading what changed…</p>';
 }
 return `<details data-fold="${esc(fold)}" data-save-also="${esc(key)}" ${open?'open':''}><summary>${esc(name)} <small>${esc(small)}</small></summary>${body}</details>`;
}
function drwChangesView(d){
 const job=d.job||{},review=d.review,design=job.kind==='design'||job.target==='design',uploaded=!!job.pushed||job.status==='synced';
 const summary=review?.summary||job.summary||null;
 let sentence=typeof saveChangeSentence==='function'&&summary?saveChangeSentence(summary):'';
 if(!sentence)sentence=job.note?job.note+'.':'Changes in this save.';
 const meta=`${sentence} ${uploaded?'Uploaded to '+drwHost(job)+'.':job.status==='dismissed'?'Kept on this VM.':'Not uploaded yet.'}`;
 const waiting=!uploaded&&drwWaiting(job);
 let actions='',reason='';
 if(waiting){
  const upload=review&&review.upload_job;
  if(!review&&!d.error)reason='Reading what changed…';
  if(review&&!upload)actions=`<p class="save-note">Someone is working in this repository on the VM.</p><div class="save-row"><button type="button" class="button ghost small" data-save-action="details">Details</button><button type="button" class="button ghost small" data-save-action="files">View files</button></div>`;
  else actions=`<button type="button" class="button primary" data-save-action="upload" ${!review||d.uploading?'disabled':''}>${d.uploading?'Uploading…':'Upload'}</button><button type="button" class="button ghost small" data-save-action="not-now" ${d.uploading?'disabled':''}>Not now</button><button type="button" class="button ghost small" data-save-action="files">View files</button>`;
 }else actions='<button type="button" class="button ghost small" data-save-action="files">View files</button>';
 const account=saveChangeAccount(job,review),dest=job.destination||{};
 const also=!uploaded&&review?review.also_sends||[]:[];
 const lead=job.target==='move'?`<p class="save-note">This moves the saved files of ${esc(drwLabName())}${typeof job.moved_from==='string'?' from '+esc(job.moved_from||'the top level'):''} to ${esc(typeof gitMoveFolder==='function'?gitMoveFolder(job):dest.path||'the new folder')}. No device file changes.</p>`:job.replaces_online===true?'<p class="save-note">The online copy held a newer save of this lab. This save replaces it.</p>':'';
 const to=dest.repository||dest.path?`<p class="save-kv">To: <code>${esc(dest.repository||'')}</code>${dest.path?` <span aria-hidden="true">›</span> <code>${esc(dest.path)}</code>`:''}</p>`:'';
 let content=drwNotices(d);
 if(reason)content+=`<p class="save-note">${esc(reason)}</p>`;
 content+=lead+to+'<p class="save-note">Saved files can contain passwords or keys.</p>';
 if(also.length)content+=`<p class="save-note" id="save-changes-also">${esc(drwAlsoSentence(also))}</p>`;
 if(!review&&!d.error)content+='<p class="save-note">Reading what changed…</p>';
 else if(review){
  content+=`<h3 class="save-heading">This save</h3>${account.entries.length?drwEntriesMarkup(account):'<p class="save-note">No file of this save changed.</p>'}`;
  if(account.rest.length||also.length)content+=`<h3 class="save-heading">Also in this upload</h3>${drwRestPaths(account.rest)}${also.map(row=>drwAlsoMarkup(row,d)).join('')}`;
 }
 return {title:design?'What this design export changed':'What changed',meta,actions,content};
}
function drwNotices(d){return (d.error?`<p class="form-error" role="alert">${esc(d.error)}</p>`:'')+(d.notice?`<p class="save-note">${esc(d.notice)}</p>`:'');}
async function drwLoadChanges(refresh){
 const d=saveDrawer.data,request=saveDrawer.request;if(!d||!d.job)return;
 if(typeof gitReviewData!=='function'){d.error='The changes cannot be read on this page.';saveDrawerRender();return;}
 if(!refresh){d.review=null;d.error='';}
 try{
  const review=await gitReviewData(d.job);
  if(request!==saveDrawer.request)return;
  d.review=review;d.error='';d.key=typeof gitWaitingKey==='function'?gitWaitingKey():'';drwSay('');
  if(typeof saveSeenReview==='function')saveSeenReview(saveDrawer.lab,d.job,review);   // what this drawer names is what an upload may send without another look
 }catch(error){if(request!==saveDrawer.request)return;d.error=error.message||'The changes could not be read.';}
 saveDrawerRender();
}
async function drwOpenAlso(key){
 const d=saveDrawer.data,row=(d.review?.also_sends||[]).find(r=>drwAlsoKey(r)===key);
 if(!row||!row.job_id||typeof gitReviewData!=='function')return;
 const got=d.also.get(key)||{};if(got.review&&!got.error)return;
 d.also.set(key,{});const request=saveDrawer.request;
 try{const review=await gitReviewData(drwAlsoJob(row));if(request!==saveDrawer.request)return;d.also.set(key,{review});}
 catch(error){if(request!==saveDrawer.request)return;d.also.set(key,{error:error.message||'error'});}
 saveDrawerRender();
}
async function drwUpload(){
 const d=saveDrawer.data;if(!d||d.uploading)return;
 if(typeof gitReviewJob!=='function'){d.error='Upload is not available on this page.';saveDrawerRender();return;}
 d.uploading=true;d.error='';d.notice='';drwSay('Uploading…');saveDrawerRender();
 try{await gitReviewJob(d.job,{upload:true});d.uploading=false;saveDrawerClose();return;}
 catch(error){
  d.uploading=false;
  if(error&&error.status===409){try{if(typeof gitReviewData==='function')d.review=await gitReviewData(d.job);}catch{/* the sentence below still shows */}d.notice=error.message;}
  else d.error=(error&&error.message)||'The upload did not start.';
 }
 drwSay('');saveDrawerRender();
}
// ---- All versions (DRAWERS.md 2) ----
function drwViewOnlyText(reason){return reason==='design'?'Design plan: view and download only':reason==='invalid'?'View only: its save details could not be read':'View only: saved without the files needed to load it';}
function drwSource(row,repository){
return {type:row.type,commit:row.commit||'',path:'/'+drwBare(row.path),backup_job_id:'',repository:repository||''};
}
function drwStateRow(s,group,list){
 const n=s.saved_devices,total=list?.lab_devices;
 const why=group==='yours'?'Your save'+(Number.isFinite(n)?` · ${drwDevices(n)} · topology and map included`:'')
  :group==='checkpoints'?'Checkpoint'+(Number.isFinite(n)?' · '+drwDevices(n):'')
  :group==='start'?'Starting point'+(Number.isFinite(n)?' · '+drwDevices(n):'')
  :group==='others'?'From '+(s.lab||'another lab')+(Number.isFinite(n)?' · '+drwDevices(n):'')
  :'Lab state'+(Number.isFinite(s.loadable_devices)&&Number.isFinite(total)?` · covers ${s.loadable_devices} of your ${total} devices`:Number.isFinite(n)?' · '+drwDevices(n):'');
 const design=s.kind==='design';
 return {key:'state:'+s.path,name:group==='start'?'Starting configuration':s.name||drwBare(s.path)||'Top level',when:drwWhen(s.saved_at),group,path:s.path,commit:s.commit||list?.head||'',type:'folder',job:null,
  viewOnly:!!s.view_only||design,reason:design?'design':s.view_only_reason||'',why,waiting:false,kind:s.kind||'capture',lab:s.lab||''};
}
// The groups of All versions from the lab's jobs and the states list. The page groups nothing itself: each state's
// `group` and `name` are the backend's; the jobs add the saves (names, Details, waiting rows) and the Save activity fold.
function drwVersionsModel(jobs,list,located){
 const states=Array.isArray(list?.states)?list.states:[],head=list?.head||'';
 const of=group=>states.filter(s=>s.group===group);
 const latestRow=of('latest')[0];
 const isOwn=job=>job.target==='latest'&&job.kind!=='state'&&job.kind!=='design'&&job.commit&&Array.isArray(job.changed_files)&&job.changed_files.length>0;
 const own=(jobs||[]).filter(isOwn);
 const yours=own.map((job,i)=>{
  const info=i===0&&latestRow&&drwBare(job.snapshot_path)===drwBare(latestRow.path)?latestRow:null,atHead=!!head&&job.commit===head;
  const base=info?drwStateRow(info,'yours',list):{key:'',name:'',group:'yours',why:'Your save',viewOnly:false,reason:''};
  return {...base,key:'job:'+job.id,name:job.note||base.name||'Save',when:drwWhen(job.finished||job.created),path:drwBare(job.snapshot_path),commit:job.commit,type:atHead?'folder':'git',job,waiting:drwWaiting(job),newest:i===0};
 });
 if(!yours.length&&latestRow)yours.push({...drwStateRow(latestRow,'yours',list),key:'state:'+latestRow.path,newest:true});
 const startRow=of('baseline')[0];
 const shownIds=new Set(own.map(j=>j.id));
 const activity=(jobs||[]).filter(job=>!shownIds.has(job.id)).map(job=>({key:'act:'+job.id,name:typeof gitSavedAs==='function'?gitSavedAs(job):job.note||'Save',when:drwWhen(job.finished||job.created),group:'activity',activity:true,job,waiting:drwWaiting(job),
  why:typeof gitSaveSentence==='function'?gitSaveSentence(job):job.status||'',path:drwBare(job.snapshot_path),commit:job.commit||'',viewOnly:false,reason:''}));
 return {head,located,labDevices:list?.lab_devices,yours,checkpoints:of('checkpoint').map(s=>drwStateRow(s,'checkpoints',list)),start:startRow?[drwStateRow(startRow,'start',list)]:[],
  states:of('state').map(s=>drwStateRow(s,'states',list)),others:of('other-lab').map(s=>drwStateRow(s,'others',list)),activity};
}
function drwCheckpointPlaceholder(row){const raw=String(row.name||'');return (typeof gitCheckpointName==='function'?gitCheckpointName(raw):raw.replace(/\s+/g,'-').replace(/[^A-Za-z0-9_-]/g,'').replace(/^[_-]+/,'')).slice(0,100);}
function drwRowButtons(row,ctx){
 const d=ctx.data,btn=(action,label,cls='button ghost small',extra='')=>`<button type="button" class="${cls}" data-save-action="${action}" data-save-row="${esc(row.key)}" ${extra}>${esc(label)}</button>`;
 const out=[];
 if(row.waiting&&row.job)out.push(`<div class="save-row">${btn('upload-job','Upload…','button primary')}${btn('details','Details')}</div>`);
 if(row.activity){if(!row.waiting)out.push(`<div class="save-row">${btn('details','Details')}</div>`);return out.join('');}
 const first=[btn('load','Load this state…','button secondary',row.viewOnly?'disabled':'')];
 if(ctx.hasOwn&&!row.newest)first.push(btn('different','See what’s different'));
 first.push(btn('files','View files'),btn('zip','Download ZIP'));
 out.push(`<div class="save-row">${first.join('')}</div>`);
 if(row.group==='yours'&&row.job){
  const job=row.job,ok=job.capture_kept&&job.capture_whole,reason=!job.capture_kept?'The capture of this save is no longer kept. Save again to make a checkpoint.':!job.capture_whole?'This capture does not include the topology. Save again first.':'';
  const second=[];
  if(ok){second.push(btn('checkpoint','Keep as a checkpoint'),btn('baseline','Use as starting point…'));}
  else second.push(btn('checkpoint','Keep as a checkpoint','button ghost small','disabled'),btn('baseline','Use as starting point…','button ghost small','disabled'));
  if(ctx.heldIds.has(job.id)&&!row.waiting)second.push(btn('details','Details'));
  out.push(`<div class="save-row">${second.join('')}</div>`);
  if(!ok)out.push(`<p class="save-note">${esc(reason)}</p><div class="save-row">${btn('save-again','Save')}</div>`);
  else if(d.checkpoint&&d.checkpoint.key===row.key){
   const typed=d.checkpoint.value||'',made=typed||drwCheckpointPlaceholder(row);
   out.push(`<div><label for="save-checkpoint-name">Checkpoint name</label><input id="save-checkpoint-name" data-save-field="checkpoint-name" maxlength="100" autocomplete="off" spellcheck="false" value="${esc(typed)}" placeholder="${esc(drwCheckpointPlaceholder(row))}"><p class="form-help">Saved as: ${esc(made)}</p><div class="save-row">${btn('checkpoint-keep','Keep','button primary')}${btn('checkpoint-cancel','Cancel')}</div></div>`);
  }
  else if(d.baseline===row.key){
   const rev=ctx.baselineRevision,startRow=ctx.model.start[0];
   out.push(`<div><p class="save-note">Make this save the starting point of ${esc(drwLabName())}? No device is read or changed.</p>${rev?`<p class="save-note">It replaces the current starting point${startRow&&startRow.when?', saved '+esc(startRow.when):''}. The previous one stays in the history.</p>`:''}<div class="save-row">${btn('baseline-confirm',rev?'Replace the starting point':'Use as starting point','button primary')}${btn('baseline-cancel','Cancel')}</div></div>`);
  }
 }
 return out.join('');
}
function drwRowMarkup(row,ctx,n){
 const open=saveDrawer.openRow===row.key,second=row.waiting&&!row.activity?'Not uploaded yet':row.viewOnly?drwViewOnlyText(row.reason):row.activity?row.why:'';
 const head=`<button type="button" class="save-item" aria-expanded="${open}" aria-controls="save-row-${n}" data-save-row="${esc(row.key)}"><span>${esc(row.name)}</span><span class="save-when">${esc(row.when)}</span>${second?`<span class="save-why">${esc(second)}</span>`:''}</button>`;
 if(!open)return `<li>${head}</li>`;
 const where=row.activity?'':`<p class="save-why">${esc(row.why)}</p><p class="save-kv"><code>${esc(ctx.repoName)}</code> <span aria-hidden="true">›</span> <code>${esc(row.path||'(top level)')}</code>${row.commit?` · commit <code>${esc(drwShort(row.commit))}</code>`:''}</p>`;
 return `<li class="open">${head}<div id="save-row-${n}">${where}${drwRowButtons(row,ctx)}</div></li>`;
}
function saveVersionsMarkup(d){
 const model=drwVersionsModel(drwJobs(),d.list,d.located);
 const ctx={data:d,model,repoName:d.repoName||'the repository',hasOwn:model.yours.length>0,heldIds:new Set(drwJobs().map(j=>j.id)),baselineRevision:d.context?.repository_status?.baseline_revision||''};
 let n=0;const list=rows=>`<ul class="save-list">${rows.map(row=>drwRowMarkup(row,ctx,++n)).join('')}</ul>`;
 const heading=text=>`<h3 class="save-heading">${esc(text)}</h3>`;
 const btn=(action,label)=>`<button type="button" class="button ghost small" data-save-action="${action}">${esc(label)}</button>`;
 const fold=(key,label,rows,fallbackOpen)=>rows.length?`<details data-fold="${esc(key)}" ${drwFold(key,fallbackOpen)?'open':''}><summary>${esc(label)} (${rows.length})</summary>${list(rows)}</details>`:'';
 let html=drwNotices(d);
 if(!d.located){html+=`<p class="save-note">This lab has not been saved yet.</p><div class="save-row">${btn('save-again','Save')}</div>`;}
 else{
  const older=d.older,yours=older?model.yours:model.yours.slice(0,5);
  html+=heading('Your saves')+(model.yours.length?list(yours)+(model.yours.length>5&&!older?`<div class="save-row">${btn('older','Show older saves')}</div>`:''):'<p class="save-note">No saves yet. Save makes the first one.</p>');
  html+=heading('Checkpoints')+(model.checkpoints.length?list(model.checkpoints):'<p class="save-note">No checkpoints yet. Keep a save as a checkpoint to hold on to it.</p>');
  html+=heading('Starting point')+(model.start.length?list(model.start):'<p class="save-note">No starting point yet.</p>')+`<div class="save-row">${btn('baseline-backup','Choose a backup as starting point…')}</div>`;
 }
 html+=`<div class="save-row">${'<h3 class="save-heading">Lab states</h3>'}${btn('state','Save as a lab state…')}</div>`+(model.states.length?list(model.states):'<p class="save-note">No lab states in this repository yet.</p>');
 html+=fold('others','Other labs in this repository',model.others,false)+fold('activity','Save activity',model.activity,model.activity.some(r=>r.waiting));
 html+=`<div class="save-foot">${btn('history','Full history…')}${btn('browse','Browse the repository…')}</div>`;
 return html;
}
function drwVersionsView(d){
 const title='All versions',meta=`Everything saved for ${drwLabName()}. Choose one to load it.`;
 if(d.loading)return {title,meta,actions:'',content:'<p class="save-note">Loading the saved versions…</p>'};
 if(d.failure)return {title,meta,actions:'',content:`<p class="save-note">The saved versions could not be loaded.</p>${d.failure.network?'':`<p class="form-help">${esc(d.failure.message)}</p>`}<div class="save-row"><button type="button" class="button secondary small" data-save-action="retry">Try again</button>${d.failure.network?'<button type="button" class="button ghost small" data-save-action="vm">Check the VM connection…</button>':''}</div>`};
 if(d.noRepository)return {title,meta,actions:'',content:`${drwNotices(d)}<p class="save-note">This lab has not been saved yet.</p><div class="save-row"><button type="button" class="button secondary small" data-save-action="save-again">Save</button></div><div class="save-foot"><button type="button" class="button ghost small" data-save-action="state">Save as a lab state…</button></div>`};
 return {title,meta,actions:'',content:saveVersionsMarkup(d)};
}
async function drwLoadVersions(){
 const d=saveDrawer.data,id=saveDrawer.lab,request=saveDrawer.request;d.loading=!d.list;d.failure=null;saveDrawerRender();
 try{
  const context=typeof gitLoadContext==='function'?await gitLoadContext(id,true):null;
  let repository=saveDrawer.options.repository||'',repoName='';
  if(context&&context.binding){repository='';repoName=typeof gitRepoName==='function'?gitRepoName(context.binding.repository):'';}
  else if(!repository){
   const places=await(await api('/labs/'+drwEnc(id)+'/git/places')).json();
   repository=places?.default?.repository||'';
   const found=(places?.repositories||[]).find(r=>r.id===repository);repoName=found&&typeof gitRepoName==='function'?gitRepoName(found):'';
  }
  if(request!==saveDrawer.request)return;
  d.context=context;d.located=!!(context&&context.binding);d.repository=repository;d.repoName=repoName||'the repository';
  if(!d.located&&!repository){d.noRepository=true;d.loading=false;drwSay('');saveDrawerRender();return;}
  d.noRepository=false;
  d.list=await(await api('/labs/'+drwEnc(id)+'/restore/states'+(repository?'?repository='+drwEnc(repository):''))).json();
  if(request!==saveDrawer.request)return;
  d.loading=false;drwSay('');
 }catch(error){if(request!==saveDrawer.request)return;d.loading=false;d.failure={message:error.message||'',network:error instanceof TypeError};}
 saveDrawerRender();
}
// A row's own request for the view, compare and download routes: the commit and path, and the repository when the lab has none of its own.
function drwVersionRequest(row,d){const body={commit:row.commit||d.list?.head||'',path:'/'+drwBare(row.path)};if(d.repository)body.repository=d.repository;return body;}
function drwFindRow(key){
 const d=saveDrawer.data,model=drwVersionsModel(drwJobs(),d.list,d.located);
 return [...model.yours,...model.checkpoints,...model.start,...model.states,...model.others,...model.activity].find(r=>r.key===key)||null;
}
async function drwDownload(request,fallback){
 const response=await api('/labs/'+drwEnc(drwLabId())+'/git/version/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
 const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
 link.href=url;link.download=typeof attachmentName==='function'?attachmentName(response,fallback||'lab-version.zip'):fallback||'lab-version.zip';
 document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function drwLoadSource(row,d){return drwSource(row,d.repository);}
function drwStartLoad(source,name){
 if(typeof loadChoose!=='function'){drwFailure('Loading a state is not available on this page.');return;}
 const id=drwLabId();saveDrawerClose();return loadChoose(id,source,name);
}
function drwFailure(message){const d=saveDrawer.data;if(d){d.error=message;saveDrawerRender();}else if(typeof notify==='function')notify(message);}
async function drwKeepCheckpoint(row){
 const d=saveDrawer.data,id=drwLabId(),typed=d.checkpoint?.value||'';
 if(typed&&!/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(typed))throw new Error('Enter a checkpoint name using letters, numbers, underscores or hyphens.');
 // Without the save's capture nothing is sent: the manager would read the devices again and write `latest` too.
 if(!row.job.backup_job_id)throw new Error('The capture of this save is no longer kept. Save again to make a checkpoint.');
 const values={target:'checkpoint',checkpoint:typed,push:true,note:'',backup_job_id:row.job.backup_job_id,allow_removed:true};
 if(typeof gitSubmitSave==='function')await gitSubmitSave(id,values,undefined,{quiet:true});
 else await json('/labs/'+drwEnc(id)+'/git/save','POST',{request_id:typeof gitRequestId==='function'?gitRequestId():'0'.repeat(32),target:'checkpoint',checkpoint:typed,push:true,note:'',backup_job_id:values.backup_job_id,replace_baseline:false,expected_baseline:'',allow_removed:true});
 d.checkpoint=null;saveDrawerClose();
}
async function drwUseBaseline(row){
 const d=saveDrawer.data,id=drwLabId(),rev=d.context?.repository_status?.baseline_revision||'';
 const values={target:'baseline',checkpoint:'',push:true,note:'',backup_job_id:row.job.backup_job_id||'',replace_baseline:!!rev,expected_baseline:rev,allow_removed:true};
 if(typeof gitSubmitSave==='function')await gitSubmitSave(id,values,undefined,{quiet:true});
 else await json('/labs/'+drwEnc(id)+'/git/save','POST',{request_id:typeof gitRequestId==='function'?gitRequestId():'0'.repeat(32),...values});
 d.baseline='';saveDrawerClose();
}
async function drwVersionAction(action,key){
 const d=saveDrawer.data,id=drwLabId();
 if(action==='older'){d.older=true;saveDrawerRender();return;}
 if(action==='retry'){await drwLoadVersions();return;}
 if(action==='vm'){saveDrawerClose();if(typeof openVmDialog==='function')openVmDialog();return;}
 if(action==='state'){saveDrawerOpen('state',{back:{kind:'versions',options:{restore:true}}});return;}
 if(action==='history'){saveDrawerClose();if(typeof gitHistory==='function')await gitHistory(id);return;}
 if(action==='browse'){saveDrawerOpen('chooser',{mode:'browse',back:{kind:'versions',options:{restore:true}}});return;}
 if(action==='baseline-backup'){saveDrawerClose();if(typeof gitSaveOptions==='function')await gitSaveOptions('baseline',id);return;}
 if(action==='save-again'){saveDrawerClose();if(typeof saveAction==='function')await saveAction('first-save',null,'drawer');else if(typeof gitSaveProgress==='function')await gitSaveProgress();return;}
 const row=key?drwFindRow(key):null;if(!row)return;
 if(action==='upload-job'){saveDrawerClose();if(typeof gitReviewJob==='function')await gitReviewJob(row.job);return;}
 if(action==='details'){saveDrawerClose();if(typeof gitShowJob==='function')await gitShowJob(row.job.id);return;}
 if(action==='load'){if(row.viewOnly)return;drwStartLoad(drwLoadSource(row,d),row.name);return;}
 if(action==='different'){saveDrawerOpen('compare',{row,name:row.name,repository:d.repository,back:{kind:'versions',options:{restore:true}}});return;}
 if(action==='files'){saveDrawerOpen('files',{row,name:row.name,repository:d.repository,back:{kind:'versions',options:{restore:true}}});return;}
 if(action==='zip'){await drwDownload(drwVersionRequest(row,d));return;}
 if(action==='checkpoint'){d.checkpoint={key:row.key,value:''};d.baseline='';saveDrawerRender();return;}
 if(action==='checkpoint-cancel'){d.checkpoint=null;saveDrawerRender();return;}
 if(action==='checkpoint-keep'){await drwKeepCheckpoint(row);return;}
 if(action==='baseline'){d.baseline=row.key;d.checkpoint=null;saveDrawerRender();return;}
 if(action==='baseline-cancel'){d.baseline='';saveDrawerRender();return;}
 if(action==='baseline-confirm'){await drwUseBaseline(row);return;}
}
// ---- View files, See what's different (rows of All versions and Full history) ----
// `shown`: 'topology' opens the topology file and the map from the start (View its topology of a Load confirmation).
function drwFilesMarkup(data,name,shown){
 const manifest=data.manifest||{},entries=Array.isArray(manifest.files)?manifest.files:[],files=new Map((data.files||[]).map(f=>[f.name,f.text]));
 const wanted=new Set(shown==='topology'?entries.filter(e=>e.kind==='topology'||e.kind==='annotations').map(e=>e.path):[]);
 const block=(path,label)=>`<details data-fold="${esc('file:'+path)}" ${drwFold('file:'+path,wanted.has(path))?'open':''}><summary>${esc(label||path)}</summary><pre class="git-file-content" tabindex="0">${esc(files.get(path)??'')}</pre></details>`;
 const devices=entries.filter(e=>e.node&&e.kind!=='topology'&&e.kind!=='annotations'),topo=entries.filter(e=>e.kind==='topology'||e.kind==='annotations');
 const artifacts=devices.map(e=>e.restore_artifact).filter(Boolean);
 const covered=new Set([...devices.map(e=>e.path),...topo.map(e=>e.path),...artifacts]);
 const other=[...files.keys()].filter(path=>!covered.has(path));
 let html=`<h3 class="save-heading">Devices</h3>${devices.length?devices.map(e=>block(e.path,`${e.short_name||e.node} · ${e.path}`)).join(''):'<p class="save-note">No device files in this state.</p>'}`;
 html+=`<h3 class="save-heading">Topology and map</h3>${topo.length?topo.map(e=>block(e.path,(e.kind==='annotations'?'Map · ':'Topology file · ')+e.path)).join(''):'<p class="save-note">Saved without its topology file.</p>'}`;
 if(artifacts.length)html+=`<details data-fold="files:load" ${drwFold('files:load',false)?'open':''}><summary>Files Load uses (${artifacts.length})</summary>${artifacts.map(p=>block(p)).join('')}</details>`;
 if(other.length)html+=other.map(p=>block(p)).join('');
 html+=`<details data-fold="files:details" ${drwFold('files:details',false)?'open':''}><summary>Save details</summary><pre class="git-file-content" tabindex="0">${esc(JSON.stringify(manifest,null,2))}</pre></details>`;
 return html;
}
async function drwLoadView(kind){
 const d=saveDrawer.data,id=saveDrawer.lab,request=saveDrawer.request,body={commit:d.source.commit,path:d.source.path};if(d.source.repository)body.repository=d.source.repository;
 try{
  const result=await json('/labs/'+drwEnc(id)+'/git/'+(kind==='compare'?'compare':'version'),'POST',body);
  if(request!==saveDrawer.request)return;
  d.result=result;d.loading=false;drwSay('');
 }catch(error){if(request!==saveDrawer.request)return;d.loading=false;d.error=error.message||'This could not be read.';}
 saveDrawerRender();
}
function drwCompareView(d){
 const title='Different from your latest save',meta=`How ${d.name} differs from the last save of ${drwLabName()}. To see what would change on the devices, choose Load this state…: the devices are compared before anything is loaded.`;
 if(d.loading)return {title,meta,actions:'',content:'<p class="save-note">Reading what changed…</p>'};
 if(d.error)return {title,meta,actions:'',content:drwNotices(d)};
 const files=d.result?.files||[];
 return {title,meta,actions:'',content:files.length?(typeof gitFilesDiffMarkup==='function'?gitFilesDiffMarkup(files,'This version','Your latest save'):files.map(f=>`<p>${esc(f.name)}</p>`).join('')):'<p class="save-note">No differences: this version matches your latest save.</p>'};
}
function drwFilesView(d){
 const title='View files',meta=`${d.name}${d.source.path?' · '+drwBare(d.source.path):''}${d.source.commit?' · commit '+drwShort(d.source.commit):''}`;
 if(d.loading)return {title,meta,actions:'',content:'<p class="save-note">Reading the saved files…</p>'};
 if(d.error)return {title,meta,actions:'',content:drwNotices(d)};
 return {title,meta,actions:'',content:drwFilesMarkup(d.result||{},d.name,d.shown)};
}
// ---- Save settings (DRAWERS.md 3) ----
const DRW_ADMIN_TEXT='On the VM, run this as your normal account (no sudo). It sets up the checkout and Git login. Then click Check again.';
function drwWaitingAnywhere(){const jobs=(typeof state==='object'&&state&&state.git_jobs)||[];return jobs.filter(drwWaiting);}
function saveSettingsMarkup(id,context,catalog,view={}){
 const binding=context?.binding,repo=typeof gitRepository==='function'?gitRepository(binding):binding?.repository||{},repositories=catalog?.repositories||[];
 const supported=context?.supported_nodes||[],excluded=context?.unsupported_nodes||[],labName=view.labName||drwLabName();
 const repoName=typeof gitRepoName==='function'?gitRepoName(repo):'the repository';
 const banner=view.problem?`<p class="banner warn">${esc(view.problem)}</p>`:'';
 if(!binding&&!repositories.length)return `<div class="save-settings">${banner}<div class="blank-state"><h3 class="save-heading">Choose where to save your progress</h3><p class="save-note">Connect a GitHub repository by pasting its HTTPS URL. The VM's Git login is used: you won't be asked for a password.</p><div class="save-row"><button type="button" class="button primary" data-git-repo-action="connect">Connect a repository by URL</button><button type="button" class="button secondary" data-git-repo-action="refresh">Check again</button></div><details data-fold="settings:admin" ${drwFold('settings:admin',false)?'open':''}><summary>Administrator setup (terminal)</summary><p>${esc(DRW_ADMIN_TEXT)}</p><pre class="git-setup-command">bash deploy/setup-git.sh</pre></details></div></div>`;
 if(!binding)return `<div class="save-settings">${banner}<h3 class="save-heading">Save location</h3><p class="save-note">This lab has no save location yet.</p><div class="save-row"><button type="button" class="button primary" data-save-action="folder">Choose a place…</button><button type="button" class="button secondary small" data-git-repo-action="connect">Connect by URL…</button></div></div>`;
 const ticks=view.ticks||new Set(binding.node_names||supported.map(n=>n.name)),prefix=String(repo.prefix||'').replace(/\/$/,'');
 const legacy=typeof gitLegacyDestinationNotice==='function'?gitLegacyDestinationNotice(binding):'';
 const label=node=>`<label class="checkbox-label"><input type="checkbox" name="git-node" value="${esc(node.name)}" ${ticks.has(node.name)?'checked':''}> <span>${esc(node.short_name||node.name)} <small>${esc(typeof platformLabel==='function'?platformLabel(node.platform):node.platform||'')}</small></span></label>`;
 const removed=(binding.node_names||[]).filter(name=>!ticks.has(name)).map(name=>(supported.find(n=>n.name===name)?.short_name)||name);
 const waiting=view.waiting||0,status=context.repository_status||{};
 const update=waiting>0?`<p class="save-note">Saves are waiting for upload in this repository. Upload them before updating from the repository.</p><div class="save-row"><button type="button" class="button secondary small" data-save-action="upload-waiting">Upload…</button><button type="button" class="button secondary small" data-git-repo-action="refresh">Refresh status</button></div>`
  :`<div class="save-row"><button type="button" class="button secondary small" data-git-repo-action="refresh">Refresh status</button><button type="button" class="button secondary small" data-git-repo-action="update">Update from the repository</button></div>`;
 const state_=!binding?'Not connected':status.problem?status.problem:status.ready?'Ready'+(status.head?' · at commit '+String(status.head).slice(0,10):''):'Not checked yet';
 return `<div class="save-settings">${banner}${view.notice?`<p class="save-note">${esc(view.notice)}</p>`:''}<h3 class="save-heading">Save location</h3>
<p class="git-destination-line"><code>${esc(repoName)}</code>${prefix?`<span aria-hidden="true">›</span><code>${esc(prefix)}</code>`:''}<span aria-hidden="true">›</span><code>latest/</code></p>${legacy?`<p class="save-note" id="git-legacy-notice">${esc(legacy)}</p>`:''}
<div class="save-row"><button type="button" class="button secondary small" data-save-action="folder">Change folder…</button><button type="button" class="button secondary small" data-git-repo-action="switch">Use a different repository…</button><button type="button" class="button secondary small" data-git-repo-action="connect">Connect by URL…</button></div>
<h3 class="save-heading">Devices included in every save</h3>
<fieldset class="git-node-scope"><legend class="sr-only">Devices included in every save</legend>${supported.map(label).join('')||'<p>No supported configuration devices in this lab.</p>'}</fieldset>
${excluded.length?`<p class="form-help">${excluded.map(n=>esc(n.short_name||n.name||n)).join(', ')} can’t be included yet — configuration saves aren’t supported for ${excluded.length===1?'its':'their'} platform.</p>`:''}
<p class="form-help">If an included device can’t be reached, the save stops and nothing is written — an older configuration is never saved in its place.</p>
${removed.map(name=>`<p class="form-help">${esc(name)} is no longer included. Its saved file is removed with the next save; older versions keep it.</p>`).join('')}
${view.noTopology?'<p class="form-help">This lab has no topology file in the manager, so saves hold device configurations only.</p><div class="save-row"><button type="button" class="button secondary small" data-save-action="topology">Update topology file…</button></div>':''}
${waiting?`<p class="save-note" id="save-settings-waiting">${waiting===1?'1 save is waiting for upload. It was made with the devices chosen before and stays part of the next upload.':waiting+' saves are waiting for upload. They were made with the devices chosen before and stay part of the next upload.'}</p>`:''}
<details id="save-git-details" data-fold="settings:git" ${drwFold('settings:git',false)?'open':''}><summary>Git details</summary>
<dl class="kv"><dt>Uploads go to</dt><dd id="git-advanced-push-url">${repo.push_url?`Verified push destination: <code>${esc(repo.push_url)}</code>`:'—'}</dd><dt>Branch</dt><dd id="git-advanced-branch">${esc(repo.branch||'—')}</dd><dt>VM account</dt><dd id="git-advanced-owner">${esc(repo.owner||'—')}</dd><dt>Checkout path</dt><dd id="git-advanced-path" class="mono">${esc(repo.path||'—')}</dd><dt>Status</dt><dd id="git-advanced-status">${esc(state_)}</dd></dl>
<p id="git-advanced-account" class="caption">${esc(`Git runs on the VM as ${repo.owner||'the registered account'} with the login configured there. This app never asks for a Git password.`)}</p>${update}</details>
<p class="form-error" role="alert" id="save-settings-error">${esc(view.error||'')}</p>
<p class="save-note" id="save-settings-exposure">Saved files can contain passwords or keys.</p>
<div class="save-settings-foot"><button type="button" class="link-button" data-git-repo-action="unlink">Disconnect this lab…</button><button type="button" class="button primary" data-save-action="save-settings"${supported.length?'':' disabled aria-describedby="save-settings-none"'}>Save settings</button></div>${supported.length?'':'<p class="save-note" id="save-settings-none">This lab has no device whose configuration can be saved, so there is nothing to choose.</p>'}</div>`;
}
function drwSettingsView(d){
 const title='Save settings',meta=`Where ${drwLabName()} saves, and which devices each save includes.`;
 if(d.loading)return {title,meta,actions:'',content:'<p class="save-note">Loading the save settings…</p>'};
 if(d.failure)return {title,meta,actions:'',content:`<p class="save-note">The save settings could not be loaded.</p>${d.failure.network?'':`<p class="form-help">${esc(d.failure.message)}</p>`}<div class="save-row"><button type="button" class="button secondary small" data-save-action="retry">Try again</button>${d.failure.network?'<button type="button" class="button ghost small" data-save-action="vm">Check the VM connection…</button>':''}</div>`};
 const lab=drwLab(),git=lab?.git_status,ticks=saveDrawer.draft&&saveDrawer.draft.ticks?saveDrawer.draft.ticks:null;
 const problem=git&&git.checked&&git.ready===false&&git.problem?git.problem:'';
 const waiting=Number.isFinite(git?.waiting)?git.waiting:drwWaitingAnywhere().length;
 return {title,meta,actions:'',content:saveSettingsMarkup(saveDrawer.lab,d.context,d.catalog,{ticks,waiting,problem,error:d.error,notice:d.notice,labName:drwLabName(),noTopology:lab?.topology_in_manager===false})};
}
async function drwLoadSettings(force){
 const d=saveDrawer.data,id=saveDrawer.lab,request=saveDrawer.request;d.loading=!d.context;d.failure=null;saveDrawerRender();
 try{
  const [context,catalog]=await Promise.all([typeof gitLoadContext==='function'?gitLoadContext(id,force!==false):Promise.resolve({}),api('/git/repositories').then(r=>r.json())]);
  if(request!==saveDrawer.request)return;
  d.context=context;d.catalog=catalog;d.loading=false;drwSay('');
 }catch(error){if(request!==saveDrawer.request)return;d.loading=false;d.failure={message:error.message||'',network:error instanceof TypeError};}
 saveDrawerRender();
}
async function drwSettingsAction(action){
 const d=saveDrawer.data,id=drwLabId();
 if(action==='retry'){await drwLoadSettings(true);return;}
 if(action==='vm'){saveDrawerClose();if(typeof openVmDialog==='function')openVmDialog();return;}
 if(action==='folder'){saveDrawerOpen('chooser',{mode:'location',back:{kind:'settings',options:{restore:true}}});return;}
 if(action==='topology'){saveDrawerClose();if(typeof opUpload==='function')await opUpload();return;}
 if(action==='upload-waiting'){const job=drwWaitingAnywhere()[0];if(job&&typeof gitReviewJob==='function'){saveDrawerClose();await gitReviewJob(job);}return;}
 if(action==='save-settings'){
  const binding=d.context?.binding,ticks=saveDrawer.draft&&saveDrawer.draft.ticks?[...saveDrawer.draft.ticks]:binding?.node_names||[];
  d.error='';d.notice='';
  if(!binding)return;
  if(!ticks.length){d.error='Choose at least one device to include.';saveDrawerRender();return;}
  // The devices of every save: the lab is placed again in the folder it has, with the new selection (the place route; nothing moves).
  const placed=await json('/labs/'+drwEnc(id)+'/git/place','POST',{repository:binding.binding_id,folder:drwBare(binding.repository?.prefix),choice:'',pending:'',move_files:false,node_names:ticks,acknowledge:true});
  if(!placed||!placed.saved)throw new Error('The devices could not be saved. Open Change folder… and choose the folder again.');
  saveDrawer.draft=null;if(typeof refresh==='function')await refresh();
  await drwLoadSettings(true);d.notice='Save settings updated.';drwSay('Save settings updated.');if(typeof notify==='function')notify('Save settings updated.');saveDrawerRender();
 }
}
// A data-git-repo-action button: refresh is this drawer's own; the dialogs of git-progress.js close the drawer first (they are centred dialogs).
async function drwRepoAction(action){
 const id=drwLabId();
 if(action==='refresh'){await saveDrawerRefresh(true);return;}
 // A repository by its address goes through the chooser and the place route, like the first save's address field: its questions
 // come back as buttons and an empty repository is started on request.
 if(action==='connect'){saveDrawerOpen('chooser',{mode:'location',address:true,back:saveDrawer.kind==='settings'?{kind:'settings',options:{restore:true}}:null});return;}
 saveDrawerClose();
 if(typeof gitRunAction==='function')await gitRunAction(action,id);
}
// ---- The folder chooser and Save as a lab state: this drawer holds the view and sends the requests; git-places.js draws and decodes ----
// `saveDrawer.chooser` IS the `view` of folderChooserMarkup(model, view) (git-places.js: mode, status, value, selected, answer,
// expanded, ...); the extra keys below (model, places, seq, timer, ...) are this host's own. folderChooserEvent(type, event)
// returns {action, ...}; every action is applied by drwChooserApply.
function drwChooserNew(mode,options){
 return {mode,status:'loading',error:'',value:options.folder||'',selected:null,answer:null,checking:false,expanded:new Set(['']),focus:'',showAll:new Set(),treeOpen:false,newFolder:null,notice:'',refused:'',problem:null,busy:false,
  question:options.question||null,pending:null,bring:true,unfinished:false,firstSave:false,name:'',showCancel:true,repositories:[],repository:options.repository||'',labName:'',repoName:'',
  model:null,places:null,context:null,seq:0,timer:0,pathTouched:false,parent:'',requestId:'',lastChoice:'',lastRequest:null,pendingJob:null,pendingReview:null,checkFailed:false,answerFor:null,
  address:options.address?{value:typeof options.address==='string'?options.address:''}:null,defaultFolder:'',
  then:typeof options.then==='function'?options.then:null};
}
// The folder a request names: the manager's answer for what the field shows (nothing is sent before it arrived, unless the check
// itself failed); for a repository given by its address, the field's own text corrected (the manager answers for it when it connects).
function drwChooserFolder(c){
 if(c.address)return c.answer&&typeof c.answer.folder==='string'?c.answer.folder:(typeof folderClean==='function'?folderClean(c.value):c.value);
 const answer=c.answer||(c.model&&c.model.answers&&typeof folderClean==='function'?c.model.answers.get(folderClean(c.value)):null);
 if(answer&&answer.folder!==undefined&&answer.folder!==null)return String(answer.folder);
 return c.checkFailed?(typeof folderClean==='function'?folderClean(c.value):c.value):null;
}
function drwChooserView(){
 const c=saveDrawer.chooser,labName=drwLabName(),mode=c.mode;
 c.labName=labName;
 const title=mode==='state'?'Save as a lab state':mode==='browse'?'Browse the repository':`Where should ${labName} save?`;
 const meta=mode==='state'?`Saves ${labName} as it is now into a folder of its own. Where ${labName} normally saves does not change.`:mode==='browse'?`Every folder of ${c.repoName||'the repository'}. Looking at folders does not change where ${labName} saves.`:'Pick a folder, type a path, or make a new folder.';
 const content=typeof folderChooserMarkup==='function'?folderChooserMarkup(c.model,c):'<p class="save-note">The folder chooser is not available on this page.</p>';
 return {title,meta,actions:'',content};
}
async function drwLoadChooser(){
 const c=saveDrawer.chooser,id=saveDrawer.lab,request=saveDrawer.request;c.status='loading';c.error='';drwDrawerRenderSoon();
 try{
  const context=typeof gitLoadContext==='function'?await gitLoadContext(id,false):null;
  const wanted=c.repository||'';
  const get=repo=>api('/labs/'+drwEnc(id)+'/git/places'+(repo?'?repository='+drwEnc(repo):'')).then(r=>r.json());
  // The first answer lists the repositories and the default place; the tree comes with `repository` (DESIGN.md 4).
  let places=await get(wanted);
  if(request!==saveDrawer.request)return;
  const listed=places.repositories||[],pick=wanted||(listed.find(r=>r.current)||{}).id||places.default?.repository||context?.binding?.binding_id||(listed[0]||{}).id||'';
  if(!places.tree&&pick){places=await get(pick);if(request!==saveDrawer.request)return;}
  c.context=context;c.places=places;c.repository=pick;
  c.repositories=(places.repositories||[]).map(r=>({id:r.id,name:r.name||(typeof gitRepoName==='function'?gitRepoName(r):r.id),remote:r.remote||'',branch:r.branch||''}));
  const found=c.repositories.find(r=>r.id===c.repository);c.repoName=found?found.name:'';
  c.model=typeof folderChooserModel==='function'&&places.tree?folderChooserModel(places.tree):null;
  const own=c.model&&typeof folderOwnPath==='function'?folderOwnPath(c.model):'';
  const base=context?.binding?own||String(context.binding.repository?.prefix||'').replace(/\/$/,''):places.default?.folder||'';
  c.parent=base;c.defaultFolder=places.default?.folder||base;
  if(c.mode==='state')c.value=drwJoin(base,typeof folderClean==='function'?folderClean(c.name):c.name);
  else if(!c.pathTouched&&!c.value)c.value=base;
  c.expanded=c.model&&typeof folderDefaultExpanded==='function'?folderDefaultExpanded(c.model):new Set(['']);
  if(typeof gitRevealFolder==='function')gitRevealFolder(c.expanded,drwDir(c.value));
  c.answer=!c.model&&!context?.binding&&c.value===(places.default?.folder||'')?places.default?.answer||null:null;
  c.status='ready';
  if(c.mode!=='browse'&&!c.address&&!(c.model&&c.model.answers.get(typeof folderClean==='function'?folderClean(c.value):c.value))&&!c.answer)drwChooserCheck(c.value);
  drwSay('');
 }catch(error){if(request!==saveDrawer.request)return;c.status=error instanceof TypeError?'unreachable':'error';c.error=c.status==='error'?error.message||'':'';}
 saveDrawerRender();
}
function drwDrawerRenderSoon(){saveDrawerRender();}
// A click on Save here or Save state made before the manager answered for the folder the field shows (right after typing a path,
// or after a name chip): the click is held, the button says the folder is being checked, and the click is carried out when the
// answer for that very value arrives. An answer that is a question is shown instead (its buttons are the answer); a new value
// drops the held click. Nothing is ever sent for a folder the manager has not answered for, and no click vanishes.
function drwChooserHold(kind){
 const c=saveDrawer.chooser,clean=value=>typeof folderClean==='function'?folderClean(value):String(value||''),value=clean(c.value);
 c.held={kind,value};clearTimeout(c.timer);c.timer=0;
 if(!(c.checking&&c.checkingFor===value))drwChooserCheck(value);else saveDrawerRender();
}
function drwChooserHeld(){
 const c=saveDrawer.chooser,held=c.held,clean=value=>typeof folderClean==='function'?folderClean(value):String(value||'');c.held=null;
 if(!held||c.busy||(c.mode!=='state'&&held.value!==clean(c.value)&&held.value!==clean(c.answer&&c.answer.typed)))return false;
 // Only an answer carries the click out: a check that failed leaves the button for a second click, and an answer that asks
 // (another lab's folder, a folder that holds a state) shows its buttons.
 if(!c.answer||['lab','state'].includes(String(c.answer.kind||'')))return false;
 if(held.kind==='state')drwChooserState('');else drwChooserPlace('','');
 return true;
}
async function drwChooserCheck(folder){
 const c=saveDrawer.chooser,id=saveDrawer.lab,seq=++c.seq,request=saveDrawer.request;c.checking=true;c.checkingFor=folder;
 try{
  const answer=await json('/labs/'+drwEnc(id)+'/git/places/check','POST',{repository:c.repository,folder,purpose:c.mode==='state'?'state':'save',name:c.mode==='state'?c.name:''});
  if(seq!==c.seq||request!==saveDrawer.request)return;
  c.answer=answer;c.checkFailed=false;
  if(answer&&typeof answer.folder==='string'&&c.mode!=='state'&&answer.folder!==c.value&&(typeof folderClean==='function'?folderClean(c.value):c.value)===folder)c.value=answer.folder;
  c.answerFor=c.value;
 }catch(error){if(seq!==c.seq||request!==saveDrawer.request)return;c.checkFailed=true;c.answer=null;c.notice='';}
 c.checking=false;c.checkingFor=null;
 if(!drwChooserHeld()){saveDrawerRender();if(c.answer&&(['lab','state'].includes(String(c.answer.kind||''))||c.answer.adjusted))drwChooserReveal();}
}
// The check asked 250 ms after the last keystroke. It is dropped when the field no longer shows that folder (a name typed while
// the chooser was still loading: the loaded chooser puts the name under the lab's folder and asks for that one itself), so an
// answer for an older folder never becomes the answer for what the field shows.
function drwChooserDebounce(folder){
 const c=saveDrawer.chooser,clean=value=>typeof folderClean==='function'?folderClean(value):String(value||'');clearTimeout(c.timer);
 c.timer=setTimeout(()=>{c.timer=0;if(saveDrawer.chooser!==c||clean(c.value)!==clean(folder))return;drwChooserCheck(folder);},250);
}
function drwChooserSelect(path){
 const c=saveDrawer.chooser;c.selected=path;c.question=null;c.notice='';c.answer=null;c.checkFailed=false;c.held=null;
 if(typeof gitRevealFolder==='function')gitRevealFolder(c.expanded,path);
 if(c.mode==='state'){c.parent=path;c.pathTouched=false;c.requestId='';c.value=drwJoin(path,typeof folderClean==='function'?folderClean(c.name):c.name);drwChooserDebounce(c.value);}
 else if(c.mode==='browse'){c.value=path;}
 else{c.value=path;c.pathTouched=true;if(!(c.model&&c.model.answers.get(path)))drwChooserCheck(path);}
 drwSay(path?'Folder '+path+' selected':'Top level selected');saveDrawerRender();
}
function drwChooserTyped(intent){
 const c=saveDrawer.chooser;c.value=intent.echo!==undefined?intent.echo:intent.value;c.selected=null;c.pathTouched=true;c.question=null;c.answer=null;c.answerFor=null;c.requestId='';c.checkFailed=false;c.held=null;c.notice='';
 const clean=typeof folderClean==='function'?folderClean(c.value):c.value;
 if(c.address){saveDrawerRender();return;}   // nothing to ask before the repository is connected
 if(c.mode==='state')c.parent=drwDir(clean);
 if(typeof gitRevealFolder==='function'&&c.model)gitRevealFolder(c.expanded,drwDir(clean));
 drwChooserDebounce(clean);saveDrawerRender();
}
function drwChooserName(intent){
 const c=saveDrawer.chooser;c.name=intent.echo!==undefined?intent.echo:intent.value;c.requestId='';c.question=null;c.held=null;
 if(!c.pathTouched){c.value=drwJoin(c.parent,typeof folderClean==='function'?folderClean(c.name):c.name);c.answer=null;c.answerFor=null;drwChooserDebounce(c.value);}
 saveDrawerRender();
}
async function drwAwaitUpload(job){
 for(let i=0;i<120;i++){
  const now=await(await api('/git/jobs/'+drwEnc(job.id))).json();
  if(now.pushed||now.status==='synced')return now;
  if(!DRW_ACTIVE.includes(now.status))throw new Error('The upload did not finish, so nothing moved.');
  await new Promise(resolve=>setTimeout(resolve,1500));
 }
 throw new Error('The upload is still running. Nothing moved.');
}
function drwChooserDone(result,message){
 const c=saveDrawer.chooser,then=c.then;
 if(message&&typeof notify==='function')notify(message);
 if(typeof gitContexts!=='undefined'&&gitContexts&&typeof gitContexts.delete==='function')gitContexts.delete(saveDrawer.lab);
 const back=saveDrawer.back,go=typeof refresh==='function'?refresh():Promise.resolve();
 return Promise.resolve(go).then(()=>{if(back&&back.kind&&saveDrawer.kind)saveDrawerBack();else saveDrawerClose();if(then)then(result);});
}
// One place request for Save here and every question button. `choice` and `pending` are what the person chose, as given.
async function drwChooserPlace(choice,pending,extra){
 const c=saveDrawer.chooser,id=saveDrawer.lab;if(c.busy)return;
 const folder=drwChooserFolder(c);if(folder===null){if(!choice&&!pending&&!extra)drwChooserHold('place');return;}
 const names=c.context?.binding?.node_names||(c.context?.supported_nodes||[]).map(n=>n.name);
 const answer=c.answer||(!c.address&&c.model&&c.model.answers.get(typeof folderClean==='function'?folderClean(c.value):c.value))||null;
 // A repository of the VM by its id, or one the VM does not have yet by its address (connected at its top level, then the lab is placed).
 const url=c.address?String(c.address.value||'').trim():'';
 if(c.address&&!/^https:\/\/[^\s/]+\/\S+/.test(url)){c.refused='Paste the HTTPS address, for example https://github.com/you/your-lab-repo.';c.problem=null;c.lastRequest=()=>drwChooserPlace(choice,pending,extra);saveDrawerRender();return;}
 const body={...(c.address?{url}:{repository:c.repository}),folder,choice:choice||'',pending:pending||'',move_files:!!(answer?.bring?.offered&&c.bring!==false),node_names:names,acknowledge:true,...(extra||{})};
 c.lastChoice=choice||'';c.lastRequest=()=>drwChooserPlace(choice,pending,extra);
 c.busy=true;c.refused='';c.problem=null;drwSay('Saving here…');saveDrawerRender();
 try{
  const result=await json('/labs/'+drwEnc(id)+'/git/place','POST',body);
  c.busy=false;
  if(result&&result.question){
   const q=result.question;drwSay('');
   if(q.kind==='pending'){c.question=null;c.pending={count:q.count||1,summary:''};await drwChooserPending();}
   else if(q.kind==='empty'||q.kind==='same-name')c.question=q;
   else{c.question=null;c.answer=q;c.answerFor=c.value;}
   saveDrawerRender();drwChooserReveal();return;
  }
  // The folder the manager placed the lab in (the one beside, for that answer), never the one that was asked about.
  const placed=result&&result.binding&&result.binding.repository?drwBare(result.binding.repository.prefix):folder;
  const where=c.address&&result&&result.binding&&typeof gitRepoName==='function'?gitRepoName(result.binding.repository):c.repoName;
  await drwChooserDone(result,`${drwLabName()} now saves to ${where||'the repository'} › ${placed||'top level'}.`);
 }catch(error){await drwChooserRefused(c,error,'The folder could not be set.');}
}
// A refused placement reads like the chip (PROMPT 6.5): after the refusal the state is read again and, when the manager recorded a
// cause the page can word (lab.git_status with a code other than `other`), the chooser shows saveProblem's sentence, the manager's
// own sentence under Details and, for an online copy that is ahead with nothing waiting, Update from the repository. Otherwise the
// manager's sentence as it is. Try again repeats the request either way.
async function drwChooserRefused(c,error,fallback){
 c.busy=false;c.refused=(error&&error.message)||fallback;c.problem=null;drwSay('');
 if(typeof refresh==='function'){try{await refresh();}catch{/* the poll catches up */}}
 const lab=drwLab(),git=lab&&lab.git_status;
 if(git&&git.ready===false&&git.code&&git.code!=='other'&&typeof saveProblem==='function'){
  const problem=saveProblem(lab,typeof state==='object'&&state?state:{});
  c.problem={sentence:problem.sentence,detail:c.refused,update:!!lab.git_binding&&(problem.actions||[]).some(a=>a.action==='update')};
 }
 if(saveDrawer.chooser===c){saveDrawerRender();drwChooserReveal();}
}
async function drwChooserUpdate(){
 const c=saveDrawer.chooser,id=saveDrawer.lab;if(!c||c.busy)return;
 c.busy=true;saveDrawerRender();
 try{const result=await json('/labs/'+drwEnc(id)+'/git/update','POST',{});c.busy=false;c.refused='';c.problem=null;if(typeof notify==='function')notify(result.message||'Repository is up to date.');if(c.lastRequest){await c.lastRequest();return;}}
 catch(error){c.busy=false;c.refused=(error&&error.message)||'The repository could not be updated.';c.problem=null;}
 saveDrawerRender();
}
async function drwChooserPending(){
 const c=saveDrawer.chooser,jobs=drwWaitingAnywhere(),job=jobs.find(j=>!j.lab_id||j.lab_id===saveDrawer.lab)||jobs[0]||null;
 c.pendingJob=job;c.pendingReview=null;
 if(!job||typeof gitReviewData!=='function')return;
 try{
  const review=await gitReviewData(job);c.pendingReview=review;
  const sentence=typeof saveChangeSentence==='function'?saveChangeSentence(review.summary||job.summary):'';
  c.pending={...c.pending,summary:[sentence,drwAlsoSentence(review.also_sends)].filter(Boolean).join(' ')||'This upload sends the waiting save.'};
 }catch{c.pending={...c.pending,summary:''};}
}
async function drwChooserUploadThenMove(){
 const c=saveDrawer.chooser;if(c.busy||!c.pendingJob||!c.pendingReview)return;
 if(typeof gitReviewJob!=='function'){c.refused='Upload is not available on this page.';saveDrawerRender();return;}
 c.busy=true;c.refused='';drwSay('Uploading…');saveDrawerRender();
 try{const job=await gitReviewJob(c.pendingJob,{upload:true});await drwAwaitUpload(job||c.pendingJob);}
 catch(error){c.busy=false;c.refused=error.message||'The upload did not finish, so nothing moved.';drwSay('');saveDrawerRender();return;}
 c.busy=false;await drwChooserPlace(c.lastChoice,'');
}
async function drwChooserState(choice){
 const c=saveDrawer.chooser,id=saveDrawer.lab;if(c.busy)return;
 // The folder the Folder field shows: the default <the lab's folder>/<the state's folder name>, what the person chose or typed, or
 // the top level when the person emptied the field (the line under it says so). Never an empty folder by omission.
 const folder=drwChooserFolder(c),name=typeof folderClean==='function'?folderClean(c.name):c.name;
 if(!name)return;
 if(folder===null){if(!choice)drwChooserHold('state');return;}
 if(!c.requestId)c.requestId=typeof gitRequestId==='function'?gitRequestId():'0'.repeat(32);
 c.lastRequest=()=>drwChooserState(choice);
 c.busy=true;c.refused='';drwSay('Saving the state…');saveDrawerRender();
 try{
  const result=await json('/labs/'+drwEnc(id)+'/git/state','POST',{request_id:c.requestId,repository:c.repository,folder,name,choice:choice||''});
  c.busy=false;
  if(result&&result.question){drwSay('');const q=result.question;if(q.kind==='empty'||q.kind==='same-name')c.question=q;else{c.question=null;c.answer=q;c.answerFor=c.value;}saveDrawerRender();return;}
  const label=name.charAt(0).toUpperCase()+name.slice(1);
  if(typeof gitRememberJob==='function'&&result&&result.id)gitRememberJob(result);
  if(typeof gitStartWatch==='function'&&result&&result.id)gitStartWatch(result,{quiet:true});
  if(typeof notify==='function')notify(`State ${label} saved in ${folder||'the top level'}.`);
  if(typeof refresh==='function')await refresh();
  saveDrawerClose();
 }catch(error){await drwChooserRefused(c,error,'The state could not be saved.');}
}
async function drwAddFolder(parent,name){
 const c=saveDrawer.chooser,id=saveDrawer.lab;
 try{
  const result=await json('/git/repositories/'+drwEnc(c.repository)+'/folders/new','POST',{lab_id:id,parent,name});
  const folder=String(result.folder??drwJoin(parent,name));
  const above=result.adjusted==='above-state'||(c.answer&&c.answer.adjusted==='above-state');   // the folder the person was in is part of a saved state
  c.newFolder=null;c.answer=result.answer||null;c.value=folder;c.selected=folder;c.answerFor=folder;
  // Inside a saved state a new folder is made in the lab folder above it, and the chooser says so (PROMPT 6.2).
  c.notice=result.existed?`${folder} already exists. It is selected.`:above?`A saved state holds no other folders, so the new folder is ${folder}, in the lab folder above it.`:'';
  if(typeof gitRevealFolder==='function')gitRevealFolder(c.expanded,folder);
  saveDrawerRender();
  // The field is gone: focus goes to the folder it made (the selected row of the tree), never to nothing.
  drwChooserFocus('[role="treeitem"][aria-selected="true"]')||drwChooserFocus('#folder-path');
  if(c.notice)drwChooserReveal();   // said, and it stays until the next action
 }catch(error){c.refused=error.message||'The folder could not be added.';saveDrawerRender();}
}
// Focus a control of the chooser after a change that removed the focused one. → whether it was found.
function drwChooserFocus(selector){
 const content=drwEl('save-drawer-content'),el=content&&typeof content.querySelector==='function'?content.querySelector(selector):null;
 if(!el||typeof el.focus!=='function')return false;
 el.focus();if(typeof el.scrollIntoView==='function')el.scrollIntoView({block:'nearest'});return true;
}
// A question, a refusal or a sentence about where a folder went arrived: its sentence and its buttons are brought into view (in a
// short window the tree pushes them below the fold) and the sentence is announced. Called after the render that shows them.
function drwChooserReveal(){
 const content=drwEl('save-drawer-content');if(!content||typeof content.querySelector!=='function')return false;
 const line=content.querySelector('#folder-refused')||content.querySelector('#folder-answer'),foot=content.querySelector('#folder-foot');
 const text=line?String(line.textContent||'').trim():'';if(!text)return false;
 for(const el of [line,foot])if(el&&typeof el.scrollIntoView==='function')el.scrollIntoView({block:'nearest'});
 drwSay(text);return true;
}
async function drwChooserForget(path){
 const c=saveDrawer.chooser;
 try{await json('/git/repositories/'+drwEnc(c.repository)+'/folders','DELETE',{prefix:path});c.value=drwDir(path);c.selected=null;c.answer=null;await drwLoadChooser();}
 catch(error){c.refused=error.message||'The folder could not be removed.';saveDrawerRender();}
}
function drwChooserNode(path){
 const c=saveDrawer.chooser,clean=drwBare(path),answer=c.model&&c.model.answers.get(clean);
 return {path:clean,name:(answer&&answer.label)||clean.split('/').pop()||'Top level',repository:c.repository===(c.context?.binding?.binding_id||'')?'':c.repository};
}
async function drwChooserApply(intent,event){
 const c=saveDrawer.chooser;if(!c||!intent||typeof intent!=='object')return false;
 switch(intent.action){
  case 'select':drwChooserSelect(intent.path);break;
  case 'toggle':if(typeof gitToggleFolder==='function')gitToggleFolder(c.expanded,intent.path);else if(c.expanded.has(intent.path))c.expanded.delete(intent.path);else c.expanded.add(intent.path);saveDrawerRender();break;
  // An arrow key in the tree: the roving tabindex moves AND the focus goes to that row (the render rebuilds the tree, so the
  // row is focused after it; Enter then selects the row the person sees focused, not the one that had focus before).
  case 'focus':c.focus=intent.path;saveDrawerRender();drwChooserFocus('[role="treeitem"][data-folder="'+String(intent.path).replace(/["\\]/g,'\\$&')+'"]');break;
  case 'typed':drwChooserTyped(intent);break;
  case 'name':drwChooserName(intent);break;
  case 'address-on':{c.address={value:''};c.answer=null;c.question=null;c.pending=null;c.refused='';c.problem=null;c.selected=null;c.newFolder=null;if(!c.pathTouched)c.value=c.defaultFolder||c.value;saveDrawerRender();drwChooserFocus('#folder-url');break;}
  case 'address-off':{c.address=null;c.answer=null;c.question=null;c.refused='';c.problem=null;saveDrawerRender();if(c.status==='ready')drwChooserCheck(typeof folderClean==='function'?folderClean(c.value):c.value);drwChooserFocus('[data-folder-action="address-on"]');break;}
  case 'url':if(c.address){c.address={value:String(intent.value??'')};c.answer=null;c.question=null;c.refused='';c.problem=null;saveDrawerRender();}break;
  case 'repository':c.repository=intent.value;c.value='';c.pathTouched=false;c.answer=null;await drwLoadChooser();break;
  case 'bring':c.bring=!!intent.value;saveDrawerRender();break;
  case 'tree-open':c.treeOpen=!!intent.value;break;
  case 'show-all':c.showAll.add(intent.path);saveDrawerRender();break;
  case 'new-folder':{c.newFolder={parent:String(intent.parent??''),value:''};saveDrawerRender();const field=drwEl('folder-new');if(field&&typeof field.focus==='function'){field.focus();if(typeof field.scrollIntoView==='function')field.scrollIntoView({block:'nearest'});}break;}
  case 'new-input':if(c.newFolder)c.newFolder={...c.newFolder,value:intent.echo!==undefined?intent.echo:intent.value};saveDrawerRender();break;
  case 'new-cancel':c.newFolder=null;saveDrawerRender();drwChooserFocus('[data-folder-action="new"]');break;
  case 'new-add':{const nf=c.newFolder,typed=intent.value!==undefined?intent.value:nf?.value||'';const name=typeof folderClean==='function'?folderClean(typed):typed;if(name)await drwAddFolder(nf?nf.parent:'',name);break;}
  case 'choice':if(c.mode==='state')await drwChooserState(intent.choice);else await drwChooserPlace(intent.choice,'');break;
  case 'pending':if(intent.pending==='upload')await drwChooserUploadThenMove();else await drwChooserPlace(c.lastChoice,'keep');break;
  // Start the repository: save-header.js writes the one flag that starts an empty repository (saveStartBody).
  case 'initialize':if(typeof saveStartBody==='function')await drwChooserPlace(c.lastChoice,'',saveStartBody({}));else{c.refused='The repository cannot be started from this page.';saveDrawerRender();}break;
  case 'save':if(c.mode==='state')await drwChooserState('');else await drwChooserPlace('','');break;
  case 'keep':drwDrawerClose_();break;
  case 'cancel':if(saveDrawer.back)saveDrawerBack();else saveDrawerClose();break;
  case 'use-another-name':{c.question=null;c.answer=null;saveDrawerRender();const input=drwEl('state-name');if(input&&typeof input.focus==='function'){input.focus();if(typeof input.select==='function')input.select();}break;}
  case 'retry':await drwLoadChooser();break;
  case 'again':if(c.lastRequest){c.refused='';c.problem=null;await c.lastRequest();}break;
  case 'update':await drwChooserUpdate();break;
  case 'vm':saveDrawerClose();if(typeof openVmDialog==='function')openVmDialog();break;
  case 'forget':await drwChooserForget(intent.path);break;
  case 'load':{const n=drwChooserNode(intent.path);drwStartLoad({type:'folder',commit:'',path:'/'+n.path,backup_job_id:'',repository:n.repository},n.name);break;}
  case 'view':{const n=drwChooserNode(intent.path),back=saveDrawer.back;saveDrawerOpen('files',{row:{path:n.path,commit:c.places?.tree?.head||''},name:n.name,repository:n.repository,back:{kind:'chooser',options:{mode:'browse',restore:true,keep:c,back}}});break;}
  default:return false;
 }
 return true;
}
function drwDrawerClose_(){saveDrawerClose();}
// ---- The different kind: load.js's differences of a load (loadDifferentMarkup(review)) in this shell ----
function drwDifferentView(d){
 // load.js owns this view: {title, meta, html}. Its markup carries its own buttons (Load on n devices, Back) with
 // data-load-action, which load.js handles through its own listener on the drawer; nothing here submits a load.
 const o=d.options||{},view=typeof loadDifferentMarkup==='function'&&o.review?loadDifferentMarkup(o.review):null;
 if(!view)return {title:o.title||'What’s different',meta:o.meta||'',actions:'',content:'<p class="save-note">The differences are not available on this page.</p>'};
 if(typeof view==='string')return {title:o.title||'What’s different',meta:o.meta||'',actions:'',content:view};
 return {title:view.title||o.title||'What’s different',meta:view.meta||o.meta||'',actions:'',content:view.html||''};
}
// ---- The shell ----
function drwView(){
 const d=saveDrawer.data||{};
 switch(saveDrawer.kind){
  case 'changes':return drwChangesView(d);
  case 'versions':return drwVersionsView(d);
  case 'settings':return drwSettingsView(d);
  case 'chooser':case 'state':return drwChooserView();
  case 'compare':return drwCompareView(d);
  case 'files':return drwFilesView(d);
  case 'different':return drwDifferentView(d);
 }
 return {title:'',meta:'',actions:'',content:''};
}
function drwFocusKey(active){
 if(!active||!active.dataset)return null;
 if(active.id)return {selector:'#'+active.id};
 const parts=Object.keys(active.dataset).map(k=>`[data-${k.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())}="${String(active.dataset[k]).replace(/["\\]/g,'\\$&')}"]`);
 if(active.name)parts.push(`[name="${String(active.name).replace(/["\\]/g,'\\$&')}"]`);
 if(active.name&&active.value!==undefined&&active.type==='checkbox')parts.push(`[value="${String(active.value).replace(/["\\]/g,'\\$&')}"]`);
 const tag=String(active.tagName||'').toLowerCase();
 return parts.length?{selector:tag+parts.join('')}:null;
}
// Like setMarkup (same `_markup` bookkeeping), and after a rebuild focus, caret and scroll are put back.
function drwSet(el,html){
 if(!el)return false;if(el._markup===html)return false;
 const active=typeof document!=='undefined'?document.activeElement:null;
 const inside=active&&typeof el.contains==='function'&&el.contains(active),key=inside?drwFocusKey(active):null;
 const caret=inside&&typeof active.selectionStart==='number'?[active.selectionStart,active.selectionEnd]:null,top=el.scrollTop;
 el.innerHTML=html;el._markup=html;
 if(key&&typeof el.querySelector==='function'){const next=el.querySelector(key.selector);if(next&&typeof next.focus==='function'){next.focus({preventScroll:true});if(caret&&typeof next.setSelectionRange==='function'){try{next.setSelectionRange(caret[0],caret[1]);}catch{/* not a text field */}}}}
 if(top)el.scrollTop=top;
 return true;
}
function drwText(el,value){if(el&&el.textContent!==value)el.textContent=value;}
// Called by render() on every poll, and after every change of this file's own state.
function saveDrawerRender(){
 const dialog=drwEl('save-drawer');if(!dialog||!dialog.open||!saveDrawer.kind)return;
 if(saveDrawer.lab&&typeof activeId==='string'&&activeId&&activeId!==saveDrawer.lab){saveDrawerClose();return;}
 if(saveDrawer.kind==='changes'&&saveDrawer.data&&saveDrawer.data.review&&typeof gitWaitingKey==='function'&&saveDrawer.data.key!==gitWaitingKey()&&!saveDrawer.data.stale){saveDrawer.data.stale=true;saveDrawer.data.key=gitWaitingKey();drwLoadChanges(true).then(()=>{if(saveDrawer.data)saveDrawer.data.stale=false;});}
 const view=drwView();
 drwText(drwEl('save-drawer-title'),view.title);drwText(drwEl('save-drawer-meta'),view.meta||'');
 const actions=drwEl('save-drawer-actions');if(actions){drwSet(actions,view.actions||'');actions.hidden=!view.actions;}
 const back=drwEl('save-drawer-back');if(back)back.hidden=!saveDrawer.back;
 drwSet(drwEl('save-drawer-content'),view.content||'');
}
function saveDrawerOpen(kind,options={}){
 if(!DRW_KINDS.includes(kind))return;
 const dialog=drwEl('save-drawer');if(!dialog)return;
 if(typeof closeMenus==='function')closeMenus();
 if(typeof closeDialogsExcept==='function')closeDialogsExcept('save-drawer');
 const first=!dialog.open,keepDraft=saveDrawer.kind==='settings'&&kind==='chooser';
 if(first)saveDrawer.opener=options.opener||(typeof document!=='undefined'?document.activeElement:null)||null;
 else if(options.opener)saveDrawer.opener=options.opener;
 if(saveDrawer.chooser&&saveDrawer.chooser.timer)clearTimeout(saveDrawer.chooser.timer);
 const onClose=saveDrawer.options&&saveDrawer.options.onClose&&saveDrawer.kind==='different'&&kind!=='different'?saveDrawer.options.onClose:null;
 saveDrawer.request++;saveDrawer.kind=kind;saveDrawer.options=options;saveDrawer.lab=typeof activeId==='string'?activeId:'';
 // The differences of a load carry load.js's own Back (the confirmation with the same ticks): the head shows no second one.
 saveDrawer.back=options.back||(typeof options.onBack==='function'?{fn:options.onBack}:null);
 if(first||(!keepDraft&&!options.restore))saveDrawer.draft=null;
 if(first||kind!=='versions'||!options.restore)saveDrawer.openRow=options.openRow||'';
 saveDrawer.chooser=null;
 if(kind==='changes')saveDrawer.data={job:options.job||null,review:null,error:'',notice:'',uploading:false,also:new Map(),key:''};
 else if(kind==='versions')saveDrawer.data={list:null,context:null,repository:options.repository||'',repoName:'',located:false,loading:true,failure:null,noRepository:false,older:false,checkpoint:null,baseline:'',error:'',notice:''};
 else if(kind==='settings')saveDrawer.data={context:null,catalog:null,loading:true,failure:null,error:'',notice:''};
 else if(kind==='chooser'||kind==='state'){saveDrawer.data={};saveDrawer.chooser=options.keep||drwChooserNew(kind==='state'?'state':options.mode==='browse'?'browse':'location',options);}
 else if(kind==='compare'||kind==='files'){
  const row=options.row||{};saveDrawer.data={name:options.name||row.name||'',source:{commit:row.commit||options.commit||'',path:'/'+drwBare(row.path||options.path),repository:options.repository||''},loading:true,error:'',result:null,shown:options.file||''};
 }
 else if(kind==='different')saveDrawer.data={options};
 if(onClose)onClose();
 if(first&&typeof dialog.showModal==='function')dialog.showModal();
 else if(first)dialog.open=true;
 saveDrawerRender();
 const heading=drwEl('save-drawer-title');
 if(heading){heading.tabIndex=-1;if(typeof heading.focus==='function')heading.focus();}
 drwSay(kind==='versions'?'Loading the saved versions…':kind==='settings'?'Loading the save settings…':kind==='changes'?'Reading what changed…':kind==='compare'||kind==='files'?'Reading…':'');
 if(kind==='changes')drwLoadChanges(false);
 else if(kind==='versions')drwLoadVersions();
 else if(kind==='settings')drwLoadSettings(true);
 else if((kind==='chooser'||kind==='state')&&!options.keep)drwLoadChooser();
 else if(kind==='compare')drwLoadView('compare');
 else if(kind==='files')drwLoadView('files');
}
function saveDrawerBack(){
 const back=saveDrawer.back;if(!back)return;
 if(back.fn){const fn=back.fn;saveDrawer.options={};saveDrawer.back=null;saveDrawerClose();fn();return;}
 const kind=back.kind,options={...(back.options||{}),back:back.options&&back.options.back!==undefined?back.options.back:null};
 if(kind==='changes'&&back.options&&back.options.job)options.job=back.options.job;
 saveDrawerOpen(kind,{...options,restore:true});
}
function saveDrawerRefresh(force){
 const dialog=drwEl('save-drawer');if(!dialog||!dialog.open||!saveDrawer.kind)return Promise.resolve();
 const kind=saveDrawer.kind;
 if(kind==='changes')return drwLoadChanges(true);
 if(kind==='versions')return drwLoadVersions();
 if(kind==='settings')return drwLoadSettings(force!==false);
 if(kind==='chooser'||kind==='state')return drwLoadChooser();
 saveDrawerRender();return Promise.resolve();
}
// Everything a closed drawer forgets; `notify` is false when load.js already knows (Back of the different kind).
function saveDrawerReset(notifyClose){
 const options=saveDrawer.options||{},was=saveDrawer.kind,opener=saveDrawer.opener;
 if(saveDrawer.chooser&&saveDrawer.chooser.timer)clearTimeout(saveDrawer.chooser.timer);
 saveDrawer.request++;saveDrawer.kind='';saveDrawer.back=null;saveDrawer.openRow='';saveDrawer.data=null;saveDrawer.draft=null;saveDrawer.chooser=null;saveDrawer.opener=null;saveDrawer.folds.clear();saveDrawer.options={};
 for(const id of ['save-drawer-content','save-drawer-actions']){const el=drwEl(id);if(el)el._markup=undefined;}
 drwSay('');
 if(notifyClose&&was==='different'&&typeof options.onClose==='function')options.onClose();
 return opener;
}
function saveDrawerClosed(){
 if(!saveDrawer.kind)return;
 const opener=saveDrawerReset(true);
 let target=opener&&typeof opener.focus==='function'&&opener.isConnected!==false&&!opener.hidden?opener:null;
 if(target&&typeof target.getClientRects==='function'&&target.getClientRects().length===0)target=null;
 if(!target)target=drwEl('save-chip');
 if(target&&typeof target.focus==='function')target.focus();
}
function saveDrawerClose(){
 const dialog=drwEl('save-drawer');
 if(dialog&&dialog.open&&typeof dialog.close==='function')dialog.close();
 if(saveDrawer.kind)saveDrawerClosed();
}
// ---- Events: one delegated listener per type on the dialog itself ----
function drwInChooser(target){return !!(target&&typeof target.closest==='function'&&target.closest('.folder-chooser'));}
async function drwRun(fn){try{return await fn();}catch(error){const message=(error&&error.message)||'That did not work. Try again.';if(saveDrawer.data&&saveDrawer.kind!=='chooser'&&saveDrawer.kind!=='state'){saveDrawer.data.error=message;saveDrawerRender();}else if(saveDrawer.chooser){saveDrawer.chooser.refused=message;saveDrawerRender();}else if(typeof notify==='function')notify(message);}}
async function saveDrawerClick(event){
 const t=event&&event.target;if(!t||typeof t.closest!=='function')return;
 const dialog=drwEl('save-drawer');
 if(dialog&&t===dialog){saveDrawerClose();return;}
 if(t.closest('#save-drawer-back')){saveDrawerBack();return;}
 if(t.closest('#save-drawer-close')){saveDrawerClose();return;}
 if(saveDrawer.chooser&&drwInChooser(t)){const intent=typeof folderChooserEvent==='function'?folderChooserEvent('click',event):null;await drwRun(()=>drwChooserApply(intent,event));return;}
 const summary=t.closest('summary');
 if(summary){
  const details=typeof summary.closest==='function'?summary.closest('details[data-fold]'):null;
  if(details&&details.dataset&&details.dataset.fold){
   if(typeof event.preventDefault==='function')event.preventDefault();
   const key=details.dataset.fold,open=typeof details.hasAttribute==='function'?details.hasAttribute('open'):!!details.open;
   saveDrawer.folds.set(key,!open);
   if(!open&&key.startsWith('also:')&&saveDrawer.kind==='changes')drwOpenAlso(key.slice(5));
   saveDrawerRender();
  }
  return;
 }
 const repo=t.closest('[data-git-repo-action]');
 if(repo){await drwRun(()=>drwRepoAction(repo.dataset.gitRepoAction));return;}
 const rowButton=t.closest('[data-save-row]'),actionButton=t.closest('[data-save-action]');
 if(actionButton){
  const action=actionButton.dataset.saveAction,key=actionButton.dataset.saveRow||'';
  if(actionButton.disabled)return;
  await drwRun(()=>drwAction_(action,key,actionButton));return;
 }
 if(rowButton&&saveDrawer.kind==='versions'){const key=rowButton.dataset.saveRow;saveDrawer.openRow=saveDrawer.openRow===key?'':key;saveDrawer.data.checkpoint=null;saveDrawer.data.baseline='';saveDrawerRender();}
}
// The click on a data-save-action, by kind. The shared actions of the head (Upload, Not now) are served here too.
async function drwAction_(action,key,button){
 const kind=saveDrawer.kind,d=saveDrawer.data;
 if(kind==='changes'){
  if(action==='upload'){await drwUpload();return;}
  if(action==='not-now'){const job=d.job;if(typeof saveAction==='function')await saveAction('not-now',job,'drawer');saveDrawerClose();return;}
  if(action==='files'){const job=d.job;saveDrawerOpen('files',{row:{path:drwJobPath(job),commit:job.commit},name:job.note||'This save',back:{kind:'changes',options:{job}}});return;}
  if(action==='details'){saveDrawerClose();if(typeof gitShowJob==='function')await gitShowJob(d.job.id);return;}
  if(action==='also-retry'){const key2=button&&button.dataset.saveAlso;if(key2){d.also.delete(key2);await drwOpenAlso(key2);}return;}
  return;
 }
 if(kind==='versions'){await drwVersionAction(action,key);return;}
 if(kind==='settings'){await drwSettingsAction(action);return;}
}
function saveDrawerInput(event){
 const t=event&&event.target;if(!t)return;
 if(saveDrawer.chooser&&drwInChooser(t)){const intent=typeof folderChooserEvent==='function'?folderChooserEvent('input',event):null;drwRun(()=>drwChooserApply(intent,event));return;}
 if(t.dataset&&t.dataset.saveField==='checkpoint-name'&&saveDrawer.data){
  const clean=typeof gitCheckpointName==='function'?gitCheckpointName(t.value):String(t.value||'').replace(/\s+/g,'-').replace(/[^A-Za-z0-9_-]/g,'').replace(/^[_-]+/,'');
  if(t.value!==clean)t.value=clean;
  if(saveDrawer.data.checkpoint)saveDrawer.data.checkpoint.value=clean;saveDrawerRender();
 }
}
function saveDrawerChange(event){
 const t=event&&event.target;if(!t)return;
 if(saveDrawer.chooser&&drwInChooser(t)){const intent=typeof folderChooserEvent==='function'?folderChooserEvent('change',event):null;drwRun(()=>drwChooserApply(intent,event));return;}
 if(saveDrawer.kind==='settings'&&t.name==='git-node'){
  const ctx=saveDrawer.data.context,binding=ctx&&ctx.binding;if(!binding)return;
  const ticks=saveDrawer.draft&&saveDrawer.draft.ticks?new Set(saveDrawer.draft.ticks):new Set(binding.node_names||[]);
  if(t.checked)ticks.add(t.value);else ticks.delete(t.value);
  saveDrawer.draft={ticks};saveDrawer.data.error='';saveDrawerRender();
 }
}
function saveDrawerKey(event){
 const t=event&&event.target;
 if(!(saveDrawer.chooser&&t&&drwInChooser(t)&&typeof folderChooserEvent==='function'))return;
 const intent=folderChooserEvent('keydown',event);
 if(intent)drwRun(()=>drwChooserApply(intent,event));
}
function saveDrawerToggle(event){
 const t=event&&event.target;
 if(!(saveDrawer.chooser&&t&&drwInChooser(t)&&typeof folderChooserEvent==='function'))return;
 const intent=folderChooserEvent('toggle',event);
 if(intent)drwRun(()=>drwChooserApply(intent,event));
}
function saveDrawerCancel(event){
 if(event&&typeof event.preventDefault==='function')event.preventDefault();
 if(saveDrawer.back)saveDrawerBack();else saveDrawerClose();
}
if(typeof $==='function'&&$('save-drawer')){
 const dialog=$('save-drawer');
 dialog.addEventListener('click',saveDrawerClick);
 dialog.addEventListener('input',saveDrawerInput);
 dialog.addEventListener('change',saveDrawerChange);
 dialog.addEventListener('keydown',saveDrawerKey);
 dialog.addEventListener('toggle',saveDrawerToggle,true);
 dialog.addEventListener('cancel',saveDrawerCancel);
 dialog.addEventListener('close',()=>{if(!dialog.open)saveDrawerClosed();});
}
