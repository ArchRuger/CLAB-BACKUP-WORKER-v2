'use strict';
// The lab builder page. The editor itself is SR Labs' clab-ui, bundled under /static/lab-builder/ and
// mounted by lab-builder/src/main.tsx; everything the manager owns is here: the drafts (kept in this
// browser, never on the manager), the starters, the device templates and the reviewed save to the VM,
// which goes through the same preview and confirm as every other lab operation (operations.js).
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state={labs:[],jobs:[],operations:[]},activeId='',toastTimer,builderDraft=null,builderPending=null,builderMount=null,builderCaps=null,builderKnown={};
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6000);}
async function api(path,options={}){const response=await fetch('/api'+path,options);if(!response.ok){const value=await response.json().catch(()=>({}));throw new Error(value.detail||'Request failed.');}return response;}
async function json(path,method,data){return(await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).json();}
async function refresh(){state=await(await api('/state')).json();}

// --- names, templates, starters (pure) ---------------------------------------------------------------
const BUILDER_PREFIX='clab-builder:',BUILDER_FORMAT='clab-manager-lab-draft';
// The lab name becomes the folder and the file name on the VM, and containerlab puts it in every
// container name: the same literal rule the VM helper applies, kept short.
function builderName(value){return typeof value==='string'&&/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,59}$/.test(value);}
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
function builderInterface(pattern,index){const m=/\{n(?::(\d+))?\}/.exec(pattern||'eth{n}');if(!m)return (pattern||'eth')+index;return pattern.replace(m[0],String((m[1]===undefined?1:Number(m[1]))+index));}
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
function draftWrite(storage,draft,expected){
 const stored=draftRead(storage,draft.id);
 if(stored&&stored.revision!==expected)throw new Error('This draft was changed in another tab. Reload this page to continue from the newer version.');
 const next={...draft,revision:(expected||0)+1,updated:new Date().toISOString()};
 try{storage.setItem(BUILDER_PREFIX+'draft:'+draft.id,JSON.stringify(next));}catch{throw new Error('This browser has no room left to keep the draft. Download the draft, then delete older drafts.');}
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
function draftStatus(draft){
 if(!draft)return {tone:'neutral',text:''};
 if(!draft.vm)return {tone:'warn',text:'Draft · kept in this browser only · not on the VM yet'};
 const same=draft.vm.yaml===draft.yaml&&(draft.vm.annotations||'')===(draft.annotations||'');
 return same?{tone:'ok',text:'Saved on the VM',detail:draft.vm.path}:{tone:'warn',text:'Changes not saved to the VM yet',detail:draft.vm.path};
}
async function builderHash(text){const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');}
// The request the reviewed save sends: a new lab folder, or a revision of the versions this draft opened.
async function builderSaveRequest(draft,hash=builderHash){
 const layout=(draft.annotations||'').trim()?draft.annotations:undefined;
 if(!draft.vm)return {action:'publish',options:{root:draft.root,text:draft.yaml,annotations:layout}};
 return {action:'revise',path:draft.vm.path,options:{text:draft.yaml,annotations:layout,base:{yaml:await hash(draft.vm.yaml),annotations:draft.vm.annotations?await hash(draft.vm.annotations):''}}};
}

// --- the page ---------------------------------------------------------------------------------------
function builderTemplatesStored(){try{const v=JSON.parse(localStorage.getItem(BUILDER_PREFIX+'templates')||'null');if(v&&Array.isArray(v.list)&&v.list.length)return v;}catch{}return null;}
function builderRenderBar(){
 const s=draftStatus(builderDraft);$('builder-name').textContent=builderDraft?builderDraft.name:'';$('builder-status').textContent=s.text;$('builder-status').title=s.detail||'';$('builder-status').className='pill '+s.tone;
 const can=!!builderDraft&&builderCaps?.actions?.[builderDraft.vm?'revise':'publish']?.available;
 $('builder-save').disabled=!can;$('builder-save').textContent=builderDraft?.vm?'Save changes to the VM…':'Save to the VM…';
 for(const id of ['builder-yaml','builder-download'])$(id).disabled=!builderDraft;
 $('builder-helper-note').hidden=!builderCaps||!!builderCaps.actions?.publish?.available;
}
function builderProblem(message){$('builder-problem-text').textContent=message;$('builder-problem').hidden=false;}
// The editor's side of the page (see lab-builder/src/main.tsx).
const builderPage={
 persist(yaml,annotations){if(!builderDraft||(yaml===builderDraft.yaml&&annotations===(builderDraft.annotations||'')))return;builderDraft=draftWrite(localStorage,{...builderDraft,yaml,annotations},builderDraft.revision);builderRenderBar();},
 templates(){const stored=builderTemplatesStored();return stored?{list:stored.list,defaultName:stored.defaultName||''}:{list:builderTemplateList(builderKnown),defaultName:BUILDER_TEMPLATES[0].name};},
 saveTemplates(list,defaultName){try{localStorage.setItem(BUILDER_PREFIX+'templates',JSON.stringify({list,defaultName}));}catch{notify('This browser could not keep the device template.');}},
 images(){return builderImages(this.templates().list,builderKnown);},
 requestSave(){opTask(null,builderSave);},
 problem:builderProblem,
 ready(mount){builderMount=mount;if(builderDraft)builderOpenEditor();},
};
if(typeof window!=='undefined')window.labBuilderPage=builderPage;
let builderMounted=false;
function builderOpenEditor(){if(builderMounted||!builderMount||!builderDraft)return;builderMounted=true;$('builder-welcome').hidden=true;builderMount({id:builderDraft.id,name:builderDraft.name,yaml:builderDraft.yaml,annotations:builderDraft.annotations||''}).catch(e=>builderProblem(e.message));}
// One editor per page load: opening another draft reloads the page with it.
function builderGo(values){location.hash=new URLSearchParams(values).toString();location.reload();}
function builderUse(draft){builderDraft=draft;builderRenderBar();document.title=draft.name+' · Lab builder · Containerlab Node Manager';builderOpenEditor();}
function builderNewDialog(root){
 const roots=(builderCaps?.roots||[]).length?builderCaps.roots:[root],templates=builderPage.templates().list;
 const dialog=opDialog('builder-new','New lab',`<label>Lab name<input id="builder-new-name" maxlength="60" autocomplete="off" spellcheck="false"></label><p class="form-help">Letters, digits, dot, dash and underscore. The name becomes the lab folder on the VM and part of every device's container name.</p><label>Start from<select id="builder-new-starter">${BUILDER_STARTERS.map(s=>`<option value="${esc(s.id)}">${esc(s.label)}</option>`).join('')}</select></label><label>Device type for the starter<select id="builder-new-template">${templates.map((t,i)=>`<option value="${i}">${esc(t.name)} · ${esc(t.image||'')}</option>`).join('')}</select></label><label>Lab folder on the VM<select id="builder-new-root">${roots.map(r=>`<option ${r===root?'selected':''}>${esc(r)}</option>`).join('')}</select></label><div class="dialog-actions"><button class="button secondary" id="builder-new-cancel">Cancel</button><button class="button primary" id="builder-new-create">Create draft</button></div>`);
 $('builder-new-cancel').onclick=()=>dialog.close();
 $('builder-new-create').onclick=()=>opTask(dialog,async()=>{
  const name=$('builder-new-name').value.trim();if(!builderName(name))throw new Error('Choose a lab name made of letters, digits, dot, dash or underscore (up to 60 characters).');
  if((state.labs||[]).some(l=>(l.deployment_name||l.name)===name))throw new Error('A lab named '+name+' is already in My labs. Choose another name.');
  const id='new:'+name;if(draftRead(localStorage,id))throw new Error('This browser already has a draft named '+name+'. Open it from Drafts, or choose another name.');
  const made=builderStarter($('builder-new-starter').value,name,templates[Number($('builder-new-template').value)]);
  draftWrite(localStorage,{id,name,root:$('builder-new-root').value,...made},undefined);builderGo({draft:id});
 });
 $('builder-new-name').focus();
}
function builderDraftsDialog(){
 const drafts=draftList(localStorage);
 const dialog=opDialog('builder-drafts-dialog','Drafts in this browser',`<p class="form-help">Drafts are kept in this browser only. Download a draft to move it to another computer or to hand it in.</p>${drafts.length?`<div class="builder-draft-list">${drafts.map((d,i)=>`<p class="op-session-row"><strong>${esc(d.name)}</strong> <span class="pill ${esc(draftStatus(d).tone)}">${esc(d.vm?'on the VM':'draft')}</span> <small>${esc(typeof opWhen==='function'?opWhen(d.updated):d.updated)}</small> <button class="button secondary" data-draft-open="${i}">Open</button> <button class="button danger-outline" data-draft-delete="${i}">Delete draft</button></p>`).join('')}</div>`:'<p>No drafts yet.</p>'}<div class="dialog-actions"><button class="button secondary" id="builder-upload">Open a downloaded draft…</button><button class="button primary" id="builder-new-from-list">New lab…</button></div><input type="file" id="builder-upload-file" accept=".json,application/json" hidden>`);
 dialog.querySelectorAll('[data-draft-open]').forEach(b=>b.onclick=()=>builderGo({draft:drafts[Number(b.dataset.draftOpen)].id}));
 dialog.querySelectorAll('[data-draft-delete]').forEach(b=>b.onclick=()=>{const d=drafts[Number(b.dataset.draftDelete)];if(!confirm('Delete the draft '+d.name+' from this browser? Files already saved on the VM are not touched.'))return;draftDelete(localStorage,d.id);if(builderDraft&&builderDraft.id===d.id){location.hash='';location.reload();}else builderDraftsDialog();});
 $('builder-new-from-list').onclick=()=>{dialog.close();builderNewDialog(builderDraft?.root||opBuilderRoot('',builderCaps?.roots));};
 $('builder-upload').onclick=()=>$('builder-upload-file').click();
 $('builder-upload-file').onchange=e=>opTask(dialog,async()=>{
  const file=e.target.files[0];if(!file)return;if(file.size>1200*1024)throw new Error('This file is too large to be a lab draft.');
  const value=draftImport(await file.text()),id='new:'+value.name;
  if(draftRead(localStorage,id)&&!confirm('Replace the draft '+value.name+' that is already in this browser?'))return;
  draftDelete(localStorage,id);draftWrite(localStorage,{id,root:opBuilderRoot('',builderCaps?.roots),...value},undefined);builderGo({draft:id});
 });
}
function builderYamlDialog(){if(!builderDraft)return;const dialog=opDialog('builder-yaml-dialog','Topology (YAML) · '+builderDraft.name,`<p class="form-help">This is what the editor has built. It is read-only here; the same text is shown again before anything is saved to the VM.</p><pre class="op-output builder-yaml" id="builder-yaml-text" tabindex="0"></pre>`);$('builder-yaml-text').textContent=builderDraft.yaml;return dialog;}
function builderDownload(){if(!builderDraft)return;const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([draftExport(builderDraft)],{type:'application/json'}));link.download=builderDraft.name+'.lab-draft.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
async function builderSave(){
 if(!builderDraft)return;
 const request=await builderSaveRequest(builderDraft);builderPending={yaml:builderDraft.yaml,annotations:builderDraft.annotations||'',action:request.action};
 await opReview(request);
}
// Called by operations.js when a lab operation started from this page finishes.
function opJobDone(job){
 if(!builderPending||!builderDraft||job.action!==builderPending.action||job.status!=='succeeded'||!job.result?.published_path)return;
 const saved=builderPending,path=job.result.published_path;
 try{builderDraft=draftWrite(localStorage,{...builderDraft,vm:{path,yaml:saved.yaml,annotations:saved.annotations}},builderDraft.revision);}catch(e){builderProblem(e.message);}
 builderPending=null;builderRenderBar();
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
async function builderOpenFromVm(path){
 const source=await json('/operations/read','POST',{path});let layout='';
 try{layout=(await json('/operations/read','POST',{path:path+'.annotations.json'})).text||'';}catch{}
 const parsed=await json('/operations/parse-yaml','POST',{options:{text:source.text}});
 const id='vm:'+path,existing=draftRead(localStorage,id);
 // Keep working on the local draft only while it still descends from the version that is on the VM.
 if(existing&&existing.vm&&existing.vm.yaml===source.text&&(existing.vm.annotations||'')===layout)return existing;
 if(existing&&!confirm('The topology on the VM changed since your draft was made. Discard the draft in this browser and open the VM version?'))return existing;
 draftDelete(localStorage,id);
 return draftWrite(localStorage,{id,name:parsed.name,root:path.slice(0,path.lastIndexOf('/')),yaml:source.text,annotations:layout,vm:{path,yaml:source.text,annotations:layout}},undefined);
}
async function builderStart(){
 const params=new URLSearchParams(location.hash.slice(1));
 for(const [id,fn] of [['builder-save',()=>opTask(null,builderSave)],['builder-yaml',builderYamlDialog],['builder-download',builderDownload],['builder-drafts',builderDraftsDialog],['builder-welcome-new',()=>builderNewDialog(params.get('root')||opBuilderRoot('',builderCaps?.roots))],['builder-welcome-drafts',builderDraftsDialog],['builder-problem-reload',()=>location.reload()]])$(id).onclick=fn;
 builderRenderBar();
 try{
  await refresh();
  [builderCaps,builderKnown]=await Promise.all([opCapabilities().catch(()=>null),api('/operations/known-images').then(r=>r.json()).then(v=>v.images||{}).catch(()=>({}))]);
  if(params.get('path'))builderUse(await builderOpenFromVm(params.get('path')));
  else if(params.get('draft')&&draftRead(localStorage,params.get('draft')))builderUse(draftRead(localStorage,params.get('draft')));
  else{builderRenderBar();if(params.get('root'))builderNewDialog(params.get('root'));}
 }catch(e){$('builder-welcome-message').textContent=e.message;}
 builderRenderBar();
}
if(typeof document!=='undefined'&&document.addEventListener)document.addEventListener('DOMContentLoaded',builderStart);
