'use strict';
// The lab builder page. The editor itself is SR Labs' clab-ui, bundled under /static/lab-builder/ and
// mounted by lab-builder/src/main.tsx; everything the manager owns is here: the drafts (kept in this
// browser, never on the manager), the starters, the device templates and the reviewed save to the VM,
// which goes through the same preview and confirm as every other lab operation (operations.js).
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state={labs:[],jobs:[],operations:[]},activeId='',toastTimer,builderDraft=null,builderPending=null,builderMount=null,builderCaps=null,builderCapsError='',builderKnown={};
// What the editor holds while this browser could not store it (null while everything is stored).
let builderUnstored=null;
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6000);}
async function api(path,options={}){let response;try{response=await fetch('/api'+path,options);}catch{throw Object.assign(new Error('The manager did not answer. Check that it is running and that this computer can reach it.'),{network:true});}if(!response.ok){const value=await response.json().catch(()=>({}));throw new Error(value.detail||'Request failed.');}return response;}
async function json(path,method,data){return(await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).json();}
async function refresh(){state=await(await api('/state')).json();}

// --- names, templates, starters (pure) ---------------------------------------------------------------
const BUILDER_PREFIX='clab-builder:',BUILDER_FORMAT='clab-manager-lab-draft';
// The lab name becomes the folder and the file name on the VM, and containerlab puts it in every
// container name: the same literal rule the VM helper applies, kept short.
function builderName(value){return typeof value==='string'&&/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,59}$/.test(value);}
// The lab name as the topology text has it. The editor's Lab settings can change it, so the text is the authority.
function builderYamlName(yaml){const m=/^name:[ \t]*(.*)$/m.exec(yaml||'');if(!m)return '';const v=m[1].replace(/\s+#.*$/,'').trim();return /^(".*"|'.*')$/.test(v)?v.slice(1,-1):v;}
// Why this draft cannot be saved under the name its topology carries ('' when it can).
function builderNameProblem(draft){
 if(!draft)return '';const name=builderYamlName(draft.yaml),fixed=draft.vm?builderYamlName(draft.vm.yaml):'';
 if(fixed&&name!==fixed)return 'The lab name was changed to '+(name||'nothing')+'. A lab that is on the VM keeps its name: set it back to '+fixed+' in the editor\'s Lab settings (the gear button), then save.';
 if(!builderName(name))return 'The lab name '+(name?'"'+name+'" ':'')+'cannot be used. Use letters, digits, dot, dash and underscore (up to 60 characters) in the editor\'s Lab settings (the gear button).';
 return '';
}
const BUILDER_TEMPLATES=[
 {name:'Arista cEOS',kind:'arista_ceos',image:'ceos:4.35.0F',baseName:'ceos',interfacePattern:'eth{n}',icon:'switch'},
 {name:'Juniper cJunosEvolved',kind:'juniper_cjunosevolved',image:'cjunosevolved:26.2R1.7-EVO',baseName:'ptx',interfacePattern:'et-0/0/{n:0}',icon:'pe'},
 {name:'Juniper vJunos-switch',kind:'juniper_vjunosswitch',image:'vrnetlab/juniper_vjunos-switch:23.2R1.14',baseName:'sw',interfacePattern:'ge-0/0/{n:0}',icon:'switch'},
 {name:'Cisco XRv9k',kind:'cisco_xrv9k',image:'vrnetlab/cisco_xrv9k:24.3.1',baseName:'xr',interfacePattern:'Gi0/0/0/{n:0}',icon:'pe'},
 {name:'Linux host',kind:'linux',image:'ghcr.io/srl-labs/network-multitool:latest',baseName:'host',interfacePattern:'eth{n}',icon:'client'},
];
// known: {kind:[image,…]} from the topologies already in My labs; the first one replaces the default.
function builderTemplateList(known){return BUILDER_TEMPLATES.map(t=>({...t,image:(known&&known[t.kind]&&known[t.kind][0])||t.image}));}
function builderImages(templates,known){return [...new Set([...templates.map(t=>t.image),...Object.values(known||{}).flat()].filter(i=>typeof i==='string'&&i))];}
// eth{n} counts from 1, {n:0} from the given start: the pattern grammar of the editor's templates.
function builderInterface(pattern,index){const p=pattern||'eth{n}',m=/\{n(?::(\d+))?\}/.exec(p);if(!m)return p+(index+1);return p.replace(m[0],String((m[1]===undefined?1:Number(m[1]))+index));}
const BUILDER_STARTERS=[{id:'blank',label:'Blank canvas',nodes:0,links:[]},{id:'pair',label:'Two devices, one link',nodes:2,links:[[0,1]]},{id:'triangle',label:'Three devices in a triangle',nodes:3,links:[[0,1],[1,2],[2,0]]}];
function builderStarter(id,name,template){
 const shape=BUILDER_STARTERS.find(s=>s.id===id)||BUILDER_STARTERS[0],t=template||BUILDER_TEMPLATES[0],used=Array(shape.nodes).fill(0);
 const names=used.map((_,i)=>t.baseName+(i+1)),spot=[[260,120],[520,120],[390,320]];
 const next=i=>builderInterface(t.interfacePattern,used[i]++);
 const links=shape.links.map(([a,b])=>`    - endpoints: ["${names[a]}:${next(a)}", "${names[b]}:${next(b)}"]\n`);
 const yaml=`name: ${name}\ntopology:\n  nodes:${names.length?'\n'+names.map(n=>`    ${n}:\n      kind: ${t.kind}\n      image: ${t.image}\n`).join(''):' {}\n'}${links.length?'  links:\n'+links.join(''):''}`;
 const annotations=names.length?JSON.stringify({nodeAnnotations:names.map((n,i)=>({id:n,position:{x:spot[i][0],y:spot[i][1]},icon:t.icon}))},null,2):'';
 return {yaml,annotations};
}

// --- drafts: this browser only (pure over a Storage-like object) -------------------------------------
function draftRead(storage,id){try{const d=JSON.parse(storage.getItem(BUILDER_PREFIX+'draft:'+id)||'null');return d&&typeof d==='object'&&typeof d.yaml==='string'?d:null;}catch{return null;}}
// expected: the revision this tab last saw. A different stored revision means another tab edited the draft.
// The revision is a token, not a counter: a draft deleted and made again elsewhere never repeats one.
function draftToken(){return Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10);}
function draftWrite(storage,draft,expected){
 const stored=draftRead(storage,draft.id);
 if(stored&&stored.revision!==expected)throw Object.assign(new Error('This draft was changed in another tab. Reload this page to continue from the newer version, or download the version shown here first.'),{code:'conflict'});
 const next={...draft,revision:draftToken(),updated:new Date().toISOString()};
 try{storage.setItem(BUILDER_PREFIX+'draft:'+draft.id,JSON.stringify(next));}catch{throw Object.assign(new Error('This browser could not store your last change (its storage is full or switched off). Download this version so nothing is lost, delete older drafts, then try again.'),{code:'storage'});}
 return next;
}
function draftList(storage){const out=[];for(let i=0;i<storage.length;i++){const key=storage.key(i);if(key&&key.startsWith(BUILDER_PREFIX+'draft:')){const d=draftRead(storage,key.slice((BUILDER_PREFIX+'draft:').length));if(d)out.push(d);}}return out.sort((a,b)=>String(b.updated).localeCompare(String(a.updated)));}
function draftDelete(storage,id){storage.removeItem(BUILDER_PREFIX+'draft:'+id);}
function draftExport(draft){return JSON.stringify({format:BUILDER_FORMAT,version:1,name:draft.name,yaml:draft.yaml,annotations:draft.annotations||''},null,1);}
function draftImport(text){
 let value;try{value=JSON.parse(text);}catch{throw new Error('This file is not a lab builder draft.');}
 if(!value||value.format!==BUILDER_FORMAT||typeof value.yaml!=='string'||value.yaml.length>512*1024||typeof (value.annotations??'')!=='string'||(value.annotations||'').length>512*1024)throw new Error('This file is not a lab builder draft.');
 if(!builderName(value.name))throw new Error('The draft has no usable lab name.');
 return {name:value.name,yaml:value.yaml,annotations:value.annotations||''};
}
// Where the draft stands against the VM: never saved, saved and unchanged, or saved with newer edits.
function draftStatus(draft,unstored){
 if(!draft)return {tone:'neutral',text:''};
 if(unstored)return {tone:'danger',text:'Last change not kept in this browser'};
 if(!draft.vm)return {tone:'warn',text:'Draft · kept in this browser only · not on the VM yet'};
 const same=draft.vm.yaml===draft.yaml&&(draft.vm.annotations||'')===(draft.annotations||'');
 return same?{tone:'ok',text:'Saved on the VM',detail:draft.vm.path}:{tone:'warn',text:'Changes not saved to the VM yet',detail:draft.vm.path};
}
async function builderHash(text){const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');}
// The request the reviewed save sends: a new lab folder, or a revision of the versions this draft opened.
async function builderSaveRequest(draft,hash=builderHash){
 const layout=(draft.annotations||'').trim()?draft.annotations:undefined;
 if(!draft.vm)return {action:'publish',options:{root:draft.root,text:draft.yaml,annotations:layout}};
 // The hashes the VM gave when the files were read (they cover the bytes, e.g. a byte-order mark the text
 // no longer has); after this page's own save the files are exactly the texts.
 return {action:'revise',path:draft.vm.path,options:{text:draft.yaml,annotations:layout,base:{yaml:draft.vm.hash||await hash(draft.vm.yaml),annotations:draft.vm.annotations?draft.vm.layoutHash||await hash(draft.vm.annotations):''}}};
}

// --- the page ---------------------------------------------------------------------------------------
// A browser that refuses storage (private mode, blocked site data) still lets the student build: the draft
// then lives in this tab only, and the page says so.
let builderStorageNote='';
function builderMemoryStorage(){const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i]??null,getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>{m.set(k,String(v));},removeItem:k=>{m.delete(k);}};}
const builderStore=(()=>{try{const s=window.localStorage;s.getItem(BUILDER_PREFIX+'probe');return s;}catch{builderStorageNote='This browser does not let the page store drafts (private window or blocked site data). Your work lives in this tab only: download the draft before you close or reload it.';return builderMemoryStorage();}})();
function builderTemplatesStored(){try{const v=JSON.parse(builderStore.getItem(BUILDER_PREFIX+'templates')||'null');if(v&&Array.isArray(v.list)&&v.list.length)return v;}catch{}return null;}
// The topology file a draft is, or will be, on the VM: the same derivation as the VM helper's.
function builderVmPath(draft){return draft.vm?draft.vm.path:draft.root+'/'+draft.name+'/'+draft.name+'.clab.yml';}
// Why Save is off, in words ('' when it is on). The same text is the button's tooltip and the note under the bar.
function builderBlocked(){
 if(!builderDraft)return '';
 if(builderUnstored)return 'Your last change is not stored in this browser yet, so it cannot be saved to the VM.';
 const name=builderNameProblem(builderDraft);if(name)return name;
 if(builderCapsError)return 'Saving to the VM is not available right now: '+builderCapsError+' You can keep building; the draft stays in this browser and can be downloaded.';
 if(builderCaps&&!builderCaps.actions?.[builderDraft.vm?'revise':'publish']?.available)return "Saving to the VM is not available: the VM's helper programs are older than this manager. Ask an administrator to run start-manager.sh on the VM. You can still build and download a draft.";
 return '';
}
// Worth knowing before the work is done, not only when the save is refused.
function builderNotice(){
 if(!builderDraft?.vm)return '';const lab=(state.labs||[]).find(l=>opPath(l)===builderDraft.vm.path);
 return lab&&/^(running|starting|partial)/i.test(lab.deployment?.status||'')?lab.name+' is deployed. You can edit the draft, but it can only be saved to the VM after the lab is destroyed (My labs → the lab → Destroy). Nothing in the running lab changes while you edit.':'';
}
function builderRenderBar(){
 const s=draftStatus(builderDraft,builderUnstored);$('builder-name').textContent=builderDraft?builderDraft.name:'';$('builder-status').textContent=s.text;$('builder-status').title=s.detail||'';$('builder-status').className='pill '+s.tone;
 const blocked=builderBlocked(),can=!!builderDraft&&!!builderCaps&&!blocked;
 $('builder-save').disabled=!can;$('builder-save').title=blocked;$('builder-save').textContent=builderDraft?.vm?'Save changes to the VM…':'Save to the VM…';
 for(const id of ['builder-yaml','builder-download'])$(id).disabled=!builderDraft;
 const note=blocked||builderNotice()||builderStorageNote;$('builder-note-text').textContent=note;$('builder-note').hidden=!note||!!builderUnstored;$('builder-note-retry').hidden=!builderCapsError||note!==blocked;
}
function builderHint(){const hint=$('builder-hint');if(hint)hint.hidden=!builderMounted||!!document.querySelector('.react-flow__node');}
function builderProblem(message,code){$('builder-problem-text').textContent=message;$('builder-problem-retry').hidden=code!=='storage';$('builder-problem').hidden=false;$('builder-problem-download').focus();}
// The editor's side of the page (see lab-builder/src/main.tsx).
const builderPage={
 // Throws when the pair could not be stored; the editor then reports the edit as failed and the page
 // keeps what the editor holds (builderUnstored) so that Download draft still gives the newest work.
 persist(yaml,annotations){
  if(!builderDraft)return;setTimeout(builderHint,0);
  if(!builderUnstored&&yaml===builderDraft.yaml&&annotations===(builderDraft.annotations||''))return;
  // A draft that is not on the VM yet takes the name its topology carries (Lab settings can rename it).
  const named=builderYamlName(yaml),name=!builderDraft.vm&&builderName(named)?named:builderDraft.name;
  try{builderDraft=draftWrite(builderStore,{...builderDraft,name,yaml,annotations},builderDraft.revision);builderUnstored=null;}
  catch(e){builderUnstored={yaml,annotations};builderRenderBar();throw e;}
  document.title=builderDraft.name+' · Lab builder · Containerlab Node Manager';builderRenderBar();
 },
 templates(){const stored=builderTemplatesStored();return stored?{list:stored.list,defaultName:stored.defaultName||''}:{list:builderTemplateList(builderKnown),defaultName:BUILDER_TEMPLATES[0].name};},
 saveTemplates(list,defaultName){try{builderStore.setItem(BUILDER_PREFIX+'templates',JSON.stringify({list,defaultName}));}catch{notify('This browser could not keep the device template.');}},
 images(){return builderImages(this.templates().list,builderKnown);},
 // The palette's Import templates: the editor leaves the file dialog to its host.
 chooseTemplates(){return new Promise((resolve,reject)=>{const input=$('builder-templates-file');input.value='';input.oncancel=()=>resolve(null);input.onchange=()=>{const file=input.files[0];if(!file)resolve(null);else if(file.size>1200*1024)reject(new Error('This file is too large to be a template file.'));else file.text().then(resolve,reject);};input.click();});},
 notify,
 requestSave(){opTask(null,builderSave);},
 problem(message,code){builderProblem(message,code);},
 ready(mount){builderMount=mount;if(builderDraft)builderOpenEditor();},
};
if(typeof window!=='undefined')window.labBuilderPage=builderPage;
let builderMounted=false;
function builderOpenEditor(){
 if(builderMounted||!builderMount||!builderDraft)return;builderMounted=true;$('builder-welcome').hidden=true;
 builderMount({id:builderDraft.id,name:builderDraft.name,yaml:builderDraft.yaml,annotations:builderDraft.annotations||''}).then(()=>setTimeout(builderHint,600)).catch(e=>{
  // A topology the editor cannot read is not opened at all: it would accept edits and keep none of them.
  if(e.code!=='unreadable'){builderProblem(e.message);return;}
  $('builder-welcome').hidden=false;$('builder-welcome-message').textContent='This topology cannot be edited visually: '+e.message+' Correct the file as text (on the VM, or in the downloaded draft), then open it again. Nothing was changed.';
 });
}
// One editor per page load: opening another draft reloads the page with it.
function builderGo(values){
 location.hash=new URLSearchParams(values).toString();
 // Without browser storage a reload would lose the draft; before an editor is mounted none is needed.
 const kept=builderStorageNote&&!builderMounted&&values.draft?draftRead(builderStore,values.draft):null;
 if(kept){document.querySelectorAll('dialog[open]').forEach(d=>d.close());builderUse(kept);}else location.reload();
}
function builderUse(draft){builderDraft=draft;builderRenderBar();document.title=draft.name+' · Lab builder · Containerlab Node Manager';builderOpenEditor();}
function builderNewDialog(root){
 const roots=(builderCaps?.roots||[]).length?builderCaps.roots:[root],templates=builderPage.templates().list;
 const dialog=opDialog('builder-new','New lab',`<label>Lab name<input id="builder-new-name" maxlength="60" autocomplete="off" spellcheck="false"></label><p class="form-help">Letters, digits, dot, dash and underscore. The name becomes the lab folder on the VM and part of every device's container name.</p><label>Start from<select id="builder-new-starter">${BUILDER_STARTERS.map(s=>`<option value="${esc(s.id)}">${esc(s.label)}</option>`).join('')}</select></label><label>Device type for the starter<select id="builder-new-template">${templates.map((t,i)=>`<option value="${i}">${esc(t.name)} · ${esc(t.image||'')}</option>`).join('')}</select></label><p class="form-help">The image name is a suggestion taken from your labs or from the usual default. The builder does not check that the image is installed on the VM; you can change it on each device.</p><label>Lab folder on the VM<select id="builder-new-root">${roots.map(r=>`<option ${r===root?'selected':''}>${esc(r)}</option>`).join('')}</select></label><div class="dialog-actions"><button class="button secondary" id="builder-new-cancel">Cancel</button><button class="button primary" id="builder-new-create">Create draft</button></div>`);
 $('builder-new-cancel').onclick=()=>dialog.close();
 const create=()=>opTask(dialog,async()=>{
  const name=$('builder-new-name').value.trim();if(!builderName(name))throw new Error('Choose a lab name made of letters, digits, dot, dash or underscore (up to 60 characters).');
  if((state.labs||[]).some(l=>(l.deployment_name||l.name)===name))throw new Error('A lab named '+name+' is already in My labs. Choose another name.');
  const id='new:'+name;if(draftRead(builderStore,id))throw new Error('This browser already has a draft named '+name+'. Open it from Drafts, or choose another name.');
  const made=builderStarter($('builder-new-starter').value,name,templates[Number($('builder-new-template').value)]);
  draftWrite(builderStore,{id,name,root:$('builder-new-root').value,...made},undefined);builderGo({draft:id});
 });
 $('builder-new-create').onclick=create;$('builder-new-name').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();create();}};
 $('builder-new-name').focus();
}
// A downloaded draft: checked by the manager's own topology parser before it becomes a draft, so a file
// the editor cannot draw is refused with the reason instead of opening as an empty canvas.
async function builderImportDraft(text,root){
 const value=draftImport(text);let name=builderYamlName(value.yaml)||value.name,note='';
 try{name=(await json('/operations/parse-yaml','POST',{options:{text:value.yaml}})).name||name;}catch(e){if(!e.network)throw new Error('The topology in this draft cannot be read: '+e.message);}
 if(!builderName(name))throw new Error('The topology in this draft has no usable lab name.');
 if(value.annotations){try{JSON.parse(value.annotations);}catch{value.annotations='';note='The map layout in this file could not be read, so the devices are placed automatically.';}}
 return {draft:{id:'new:'+name,root,...value,name},note};
}
function builderDraftsDialog(){
 const drafts=draftList(builderStore);
 const dialog=opDialog('builder-drafts-dialog','Drafts in this browser',`<p class="form-help">Drafts are kept in this browser only. Download a draft to move it to another computer or to hand it in.</p>${drafts.length?`<div class="builder-draft-list">${drafts.map((d,i)=>`<p class="op-session-row"><strong>${esc(d.name)}</strong> <span class="pill ${esc(draftStatus(d).tone)}">${esc(d.vm?draftStatus(d).tone==='ok'?'on the VM':'on the VM · newer changes here':'draft')}</span> <small>${esc(typeof opWhen==='function'?opWhen(d.updated):d.updated)}</small> <button class="button secondary" data-draft-open="${i}">Open</button> <button class="button danger-outline" data-draft-delete="${i}">Delete draft</button></p>`).join('')}</div>`:'<p>No drafts yet.</p>'}<div class="dialog-actions"><button class="button secondary" id="builder-upload">Open a downloaded draft…</button><button class="button primary" id="builder-new-from-list">New lab…</button></div><input type="file" id="builder-upload-file" accept=".json,application/json" hidden>`);
 dialog.querySelectorAll('[data-draft-open]').forEach(b=>b.onclick=()=>builderGo({draft:drafts[Number(b.dataset.draftOpen)].id}));
 dialog.querySelectorAll('[data-draft-delete]').forEach(b=>b.onclick=()=>{const d=drafts[Number(b.dataset.draftDelete)];if(!confirm('Delete the draft '+d.name+' from this browser? Files already saved on the VM are not touched.'))return;draftDelete(builderStore,d.id);if(builderDraft&&builderDraft.id===d.id){location.hash='';location.reload();}else builderDraftsDialog();});
 $('builder-new-from-list').onclick=()=>{dialog.close();builderNewDialog(builderDraft?.root||opBuilderRoot('',builderCaps?.roots));};
 $('builder-upload').onclick=()=>$('builder-upload-file').click();
 $('builder-upload-file').onchange=e=>opTask(dialog,async()=>{
  const file=e.target.files[0];if(!file)return;if(file.size>1200*1024)throw new Error('This file is too large to be a lab draft.');
  const {draft,note}=await builderImportDraft(await file.text(),opBuilderRoot('',builderCaps?.roots));
  if(draftRead(builderStore,draft.id)&&!confirm('Replace the draft '+draft.name+' that is already in this browser?'))return;
  draftDelete(builderStore,draft.id);draftWrite(builderStore,draft,undefined);if(note)alert(note);builderGo({draft:draft.id});
 });
}
function builderYamlDialog(){if(!builderDraft)return;const dialog=opDialog('builder-yaml-dialog','Topology (YAML) · '+builderDraft.name,`<p class="form-help">This is what the editor has built. It is read-only here; the same text is shown again before anything is saved to the VM.</p><pre class="op-output builder-yaml" id="builder-yaml-text" tabindex="0"></pre>`);$('builder-yaml-text').textContent=(builderUnstored||builderDraft).yaml;return dialog;}
// The newest work, also when this browser could not store it.
function builderDownload(){if(!builderDraft)return;const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([draftExport({...builderDraft,...(builderUnstored||{})})],{type:'application/json'}));link.download=builderDraft.name+'.lab-draft.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
// Storing again what the editor holds; the editor itself restarts from the stored draft.
function builderStoreAgain(){if(!builderDraft||!builderUnstored)return;try{builderDraft=draftWrite(builderStore,{...builderDraft,...builderUnstored},builderDraft.revision);builderUnstored=null;location.reload();}catch(e){builderProblem(e.message,e.code);}}
function builderSame(a,b){return !!a&&!!b&&a.yaml===b.yaml&&(a.annotations||'')===(b.annotations||'');}
// The topology and layout that are on the VM now; null when the file is not there or cannot be read.
async function builderVmRead(path){
 let source;try{source=await json('/operations/read','POST',{path});}catch{return null;}
 let layout=null;try{layout=await json('/operations/read','POST',{path:path+'.annotations.json'});}catch{}
 return {yaml:source.text,annotations:layout?.text||'',hash:source.sha256||'',layoutHash:layout?.text?layout.sha256||'':''};
}
function builderMarkSaved(path,texts){builderDraft=draftWrite(builderStore,{...builderDraft,saving:undefined,vm:{path,yaml:texts.yaml,annotations:texts.annotations||''}},builderDraft.revision);builderRenderBar();}
// A save the VM refused. When the file on the VM is not the version this draft knows (an earlier save whose
// answer never arrived, an edit on the VM, another computer), the way on is to look at the differences.
async function builderSaveRefused(error){
 const path=builderVmPath(builderDraft),found=error.network?null:await builderVmRead(path);
 if(found&&builderSame(found,builderDraft)){builderMarkSaved(path,found);notify('This lab is already on the VM with the same content.');return;}
 const differs=found&&!builderSame(found,builderDraft.vm);
 const dialog=opDialog('builder-save-problem','Not saved to the VM',`<p id="builder-save-problem-text"></p><p>Nothing on the VM was changed. Your draft is kept in this browser.</p>${differs?`<p>The VM has a different version of <code>${esc(path)}</code> than this draft started from. That can be an earlier save from this page whose answer never arrived, or a change made on the VM. You can look at the differences and decide, or open the VM version (this draft stays in Drafts).</p>`:''}<div class="dialog-actions"><button class="button secondary" id="builder-save-problem-close">Close</button>${differs?`<button class="button secondary" id="builder-save-problem-open">Open the VM version</button><button class="button primary" id="builder-save-problem-compare">Review the differences…</button>`:''}</div>`);
 $('builder-save-problem-text').textContent=error.message;$('builder-save-problem-close').onclick=()=>dialog.close();
 if(!differs)return;
 $('builder-save-problem-open').onclick=()=>builderGo({path});
 // From here the draft descends from the version that is on the VM, so the next save is a reviewed
 // revision: it shows the differences, keeps a recovery copy and is refused while the lab is deployed.
 $('builder-save-problem-compare').onclick=()=>opTask(dialog,async()=>{builderDraft=draftWrite(builderStore,{...builderDraft,vm:{path,...found}},builderDraft.revision);builderRenderBar();dialog.close();await builderSave();});
}
async function builderSave(){
 if(!builderDraft||builderBlocked())return;
 const request=await builderSaveRequest(builderDraft);builderPending={yaml:builderDraft.yaml,annotations:builderDraft.annotations||'',action:request.action};
 // Remembered with the draft: if this page never hears the outcome, the next visit asks the VM.
 try{builderDraft=draftWrite(builderStore,{...builderDraft,saving:true},builderDraft.revision);}catch(e){builderPending=null;builderProblem(e.message,e.code);return;}
 try{await opReview(request);}catch(e){builderPending=null;await builderSaveRefused(e);}
}
// Called by operations.js when a lab operation started from this page finishes.
function opJobDone(job){
 if(!builderPending||!builderDraft||job.action!==builderPending.action)return;
 const saved=builderPending,done=job.status==='succeeded'&&(job.result?.published_path||job.result?.already_published),path=job.result?.published_path||builderVmPath(builderDraft);builderPending=null;
 try{if(done)builderMarkSaved(path,saved);else builderDraft=draftWrite(builderStore,{...builderDraft,saving:undefined},builderDraft.revision);}catch(e){builderProblem(e.message,e.code);}
 builderRenderBar();if(!done)return;
 // A lab that is already in My labs keeps the devices and the map it was registered with. After a
 // revision the manager takes the new topology and layout, so its own map and device list follow.
 const lab=(state.labs||[]).find(l=>opPath(l)===path);
 if(lab&&saved.action==='revise')opTask(null,async()=>{
  const form=new FormData(),name=path.split('/').pop();form.append('lab_id',lab.id);
  form.append('definition',new Blob([saved.yaml],{type:'text/yaml'}),name);
  if(saved.annotations)form.append('annotations',new Blob([saved.annotations],{type:'application/json'}),name+'.annotations.json');
  await api('/lab-definitions',{method:'POST',body:form});await refresh();notify('My labs now shows the saved topology of '+lab.name+'.');
 });
}
// A save was started from this draft and this page never heard how it ended (closed tab, lost connection).
async function builderReconcile(){
 if(!builderDraft?.saving||builderPending)return;
 const path=builderVmPath(builderDraft),found=await builderVmRead(path);
 try{if(found&&builderSame(found,builderDraft))builderMarkSaved(path,found);else builderDraft=draftWrite(builderStore,{...builderDraft,saving:undefined},builderDraft.revision);}catch{}
 builderRenderBar();
}
async function builderOpenFromVm(path){
 const found=await builderVmRead(path);if(!found)await json('/operations/read','POST',{path});  // the second call carries the reason
 const parsed=await json('/operations/parse-yaml','POST',{options:{text:found.yaml}});
 // One draft per lab: the draft that was saved to this path from this browser, else the one opened from it.
 const existing=draftList(builderStore).find(d=>d.vm&&d.vm.path===path)||null;
 // Keep working on the local draft only while it still descends from the version that is on the VM.
 if(existing&&builderSame(existing.vm,found))return existing;
 if(existing&&!builderSame(existing,existing.vm)&&!confirm('The topology on the VM changed since your draft was made, and the draft has changes that are not on the VM.\n\nOK opens the VM version and discards the draft in this browser.\nCancel keeps your draft: you can download it, or save it and review the differences.'))return existing;
 if(existing)draftDelete(builderStore,existing.id);
 return draftWrite(builderStore,{id:'vm:'+path,name:parsed.name,root:path.slice(0,path.lastIndexOf('/')),yaml:found.yaml,annotations:found.annotations,vm:{path,...found}},undefined);
}
async function builderConnect(){
 try{builderCaps=await opCapabilities();builderCapsError='';}catch(e){builderCaps=null;builderCapsError=e.message;}
 builderRenderBar();
}
async function builderStart(){
 const params=new URLSearchParams(location.hash.slice(1));
 for(const [id,fn] of [['builder-save',()=>opTask(null,builderSave)],['builder-yaml',builderYamlDialog],['builder-download',builderDownload],['builder-drafts',builderDraftsDialog],['builder-welcome-new',()=>builderNewDialog(params.get('root')||opBuilderRoot('',builderCaps?.roots))],['builder-welcome-drafts',builderDraftsDialog],['builder-problem-reload',()=>location.reload()],['builder-problem-download',builderDownload],['builder-problem-retry',builderStoreAgain],['builder-note-retry',()=>opTask(null,builderConnect)]])$(id).onclick=fn;
 builderRenderBar();
 // A draft is in this browser: it opens whether or not the manager answers.
 const local=params.get('draft')?draftRead(builderStore,params.get('draft')):null;
 if(local)builderUse(local);else if(params.get('draft'))$('builder-welcome-message').textContent='That draft is not in this browser. Drafts stay in the browser they were made in: open a downloaded draft file, or start a new lab.';
 try{
  await refresh();
  [,builderKnown]=await Promise.all([builderConnect(),api('/operations/known-images').then(r=>r.json()).then(v=>v.images||{}).catch(()=>({}))]);
  if(params.get('path'))builderUse(await builderOpenFromVm(params.get('path')));
  else if(!local&&params.get('root'))builderNewDialog(params.get('root'));
  await builderReconcile();
 }catch(e){if(builderDraft){builderCapsError=builderCapsError||e.message;}else $('builder-welcome-message').textContent=e.message;}
 builderRenderBar();
}
if(typeof document!=='undefined'&&document.addEventListener)document.addEventListener('DOMContentLoaded',builderStart);
