'use strict';
// The lab builder page. The editor itself is SR Labs' clab-ui, bundled under /static/lab-builder/ and
// mounted by lab-builder/src/main.tsx; everything the manager owns is here: the drafts (kept in this
// browser, never on the manager), the device templates and the reviewed save to the VM, which goes
// through the same preview and confirm as every other lab operation (operations.js).
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state={labs:[],jobs:[],operations:[]},activeId='',toastTimer,builderDraft=null,builderPending=null,builderMount=null,builderCaps=null,builderCapsError='',builderKnown={},builderVmImages=[];
// The lab this page edits (#lab=<id>), the manager's device catalog (null until it answers or when it did not), the date of a continued
// draft, what a deployed save left behind ({deployed, mapOnly}) and the editor's handle (undo, redo).
let builderLabId='',builderCatalogAnswer=null,builderContinued='',builderAfter=null,builderEditor=null;
// What the editor holds while this browser could not store it (null while everything is stored).
let builderUnstored=null;
// Set while the problem overlay is up: nothing the editor still does is stored over it (its keyboard
// shortcuts work on the whole document, so the overlay alone does not stop them).
let builderPaused=null;
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6000);}
async function api(path,options={}){let response;try{response=await fetch('/api'+path,options);}catch{throw Object.assign(new Error('The manager did not answer. Check that it is running and that this computer can reach it.'),{network:true});}if(!response.ok){const value=await response.json().catch(()=>({}));throw Object.assign(new Error(value.detail||'Request failed.'),{status:response.status});}return response;}
async function json(path,method,data){
 const value=await(await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).json();
 // The review's own answer says whether the save met a deployed lab (operations.js does not hand it back).
 if(path==='/operations/preview'&&typeof builderPreviewSeen==='function')builderPreviewSeen(data,value);
 return value;
}
async function refresh(){state=await(await api('/state')).json();}

// --- names and device templates (pure) --------------------------------------------------------------
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
// image: the default image of the kind. For the four built-in network kinds (pinned) it is the site's
// requested constant and always wins; for the others (the Linux host) it is a placeholder in the shape the
// image usually has, and builderTemplateList prefers, per kind, an image the topologies in My labs use, then
// one the VM already has, then the placeholder. match: the repository names (last path component, lower
// case) under which this VM may hold such an image.
// The requested names are "N24l/..." in the email; a Docker repository must be lower case, so the namespace
// is n24l (the tags are unchanged).
const BUILDER_TEMPLATES=[
 {name:'Arista cEOS',kind:'arista_ceos',image:'n24l/ceos:4.35.0F',pinned:true,match:['ceos'],baseName:'ceos',interfacePattern:'eth{n}',icon:'switch'},
 {name:'Juniper cJunosEvolved',kind:'juniper_cjunosevolved',image:'n24l/cjunosevolved:26.2R1.7-EVO',pinned:true,env:{CPTX_AUTO_CONFIG:'1'},match:['cjunosevolved'],baseName:'ptx',interfacePattern:'et-0/0/{n:0}',icon:'pe'},
 {name:'Juniper vJunos-switch',kind:'juniper_vjunosswitch',image:'n24l/vjunos-switch:23.2R1.14',pinned:true,match:['vjunos-switch','juniper_vjunos-switch','vjunosswitch'],baseName:'sw',interfacePattern:'ge-0/0/{n:0}',icon:'switch'},
 {name:'Juniper vJunos-router',kind:'juniper_vjunosrouter',image:'n24l/juniper_vjunos-router:26.2R1.7',pinned:true,match:['vjunos-router','juniper_vjunos-router','vjunosrouter'],baseName:'rtr',interfacePattern:'ge-0/0/{n:0}',icon:'pe'},
 {name:'Juniper vSRX',kind:'juniper_vsrx',image:'n24l/juniper_vsrx:23.2R2.21',pinned:true,match:['vsrx','juniper_vsrx'],baseName:'srx',interfacePattern:'ge-0/0/{n:0}',icon:'pe'},
 {name:'Cisco XRv9k',kind:'cisco_xrv9k',image:'n24l/cisco_xrv9k:24.3.1',pinned:true,match:['cisco_xrv9k','xrv9k'],baseName:'xr',interfacePattern:'Gi0/0/0/{n:0}',icon:'pe'},
 {name:'Linux host',kind:'linux',image:'ghcr.io/srl-labs/network-multitool:latest',match:['network-multitool'],baseName:'host',interfacePattern:'eth{n}',icon:'client'},
];
// cJunosEvolved env: containerlab passes this kind no hostname, and Juniper's /entrypoint.sh replaces the
// `host-name HOSTNAME;` of its default config with the container's hostname only under CPTX_AUTO_CONFIG
// (first boot only). The entrypoint checks it before a startup-config, so it is never added to a template or
// node that has a startup-config of its own, and it applies to new nodes created from the template only.
// The built-in constants before the n24l defaults. A stored template is moved to the new default once (see
// builderMigrateTemplates) only when it is still exactly the old built-in one.
const BUILDER_PREVIOUS_IMAGES={arista_ceos:['ceos:4.35.0F'],juniper_cjunosevolved:['cjunosevolved:26.2R1.7-EVO'],juniper_vjunosswitch:['vrnetlab/juniper_vjunos-switch:23.2R1.14'],cisco_xrv9k:['vrnetlab/cisco_xrv9k:24.3.1']};
const BUILDER_TEMPLATES_VERSION='2';
// list: stored device templates. Returns {list,changed}; only an entry that carries a built-in name AND its kind
// AND one of that kind's previous built-in images gets the new default image, everything else (renamed,
// customised, other kinds, imported) is returned untouched.
function builderMigrateTemplates(list){
 let changed=false;
 const out=(Array.isArray(list)?list:[]).map(t=>{
  const built=t&&BUILDER_TEMPLATES.find(b=>b.pinned&&b.name===t.name&&b.kind===t.kind);
  if(built&&(BUILDER_PREVIOUS_IMAGES[built.kind]||[]).includes(t.image)){
   changed=true;const next={...t,image:built.image};
   if(built.env&&!t.env&&!t.startupConfig)next.env={...built.env};
   return next;
  }
  return t;
 });
 return {list:out,changed};
}
// The VM image that fits a template: its repository's last path component is one of the template's match
// names (case-insensitive); among several, the highest tag (plain string order, so 4.35.0F after 4.34.2F).
function builderVmImageFor(template,vmImages){
 const names=(template.match||[]).map(m=>m.toLowerCase());if(!names.length)return '';
 const fits=(vmImages||[]).filter(i=>typeof i==='string'&&names.includes(i.split('@')[0].replace(/:[^/]*$/,'').split('/').pop().toLowerCase())).sort();
 return fits.length?fits[fits.length-1]:'';
}
// known: {kind:[image,…]} from the topologies already in My labs; vmImages: the images on the VM.
// The manager's catalog (GET /api/catalog) is the source of the default templates; BUILDER_TEMPLATES stays as the offline fallback
// and tests/test_catalog.py keeps the two equal. An entry that does not have the template's shape is skipped.
function builderCatalogTemplates(catalog){
 const out=[];
 for(const e of Array.isArray(catalog&&catalog.entries)?catalog.entries:[]){
  const t=e&&e.template;
  if(!e||typeof e.kind!=='string'||!e.kind||typeof e.image!=='string'||!e.image||!t||typeof t.name!=='string'||!t.name)continue;
  const item={name:t.name,kind:e.kind,image:e.image};
  if(t.pinned===true)item.pinned=true;
  if(t.env&&typeof t.env==='object'&&!Array.isArray(t.env))item.env={...t.env};
  if(Array.isArray(t.match))item.match=t.match.filter(m=>typeof m==='string');
  for(const key of ['baseName','interfacePattern','icon'])if(typeof t[key]==='string')item[key]=t[key];
  out.push(item);
 }
 return out;
}
function builderBaseTemplates(){const list=builderCatalogTemplates(builderCatalogAnswer);return list.length?list:BUILDER_TEMPLATES;}
// Stored templates keep precedence; a catalog kind the stored list has no template for is appended (never replacing a stored entry).
function builderAppendCatalog(list,known,vmImages){
 const have=new Set(list.map(t=>t&&t.kind)),add=builderCatalogTemplates(builderCatalogAnswer).filter(t=>!have.has(t.kind)).map(t=>t.kind);
 return add.length?list.concat(builderTemplateList(known,vmImages).filter(t=>add.includes(t.kind))):list;
}
function builderTemplateList(known,vmImages){return builderBaseTemplates().map(t=>({...t,image:t.pinned?t.image:(known&&known[t.kind]&&known[t.kind][0])||builderVmImageFor(t,vmImages)||t.image}));}
function builderImages(templates,known,vmImages){return [...new Set([...templates.map(t=>t.image),...Object.values(known||{}).flat(),...(vmImages||[])].filter(i=>typeof i==='string'&&i))];}
// The images a draft's topology names (an `image:` line per device or kind; templated values left out).
function builderYamlImages(yaml){
 const found=new Set();for(const m of String(yaml||'').matchAll(/^[ \t-]*image:[ \t]*["']?([^"'\s#]+)/gm))if(!m[1].includes('{{'))found.add(m[1]);
 return [...found].slice(0,16);
}
// The one notice under the bar from the manager's answers (POST /api/operations/image-check). tone: 'info' when
// every image is available (on the VM or pullable), 'warn' when something could not be checked, 'error' when a
// deploy would fail (a reference no registry offers, or no usable name). Only the problematic references are named;
// an error outranks a warning, a warning outranks the all-fine line, so a failure is never hidden by a success.
function builderImageSummary(results){
 const list=(Array.isArray(results)?results:[]).filter(r=>r&&typeof r==='object');if(!list.length)return {text:'',tone:'info',warn:false};
 if(list.some(r=>r.available===false))return {text:'Warning: images not checked. This VM has no Docker client the manager can ask, so they are checked at deploy time.',tone:'warn',warn:true};
 const missing=[],invalid=[],silent=[],unknown=[];
 for(const r of list){
  if(r.local)continue;
  if(r.registry==='not-found')missing.push(r.reference);else if(r.registry==='invalid')invalid.push(r.reference);
  else if(r.registry==='unreachable')silent.push(r.reference);else if(r.registry!=='found')unknown.push(r.reference);
 }
 const join=a=>a.join(', '),errors=[],warnings=[];
 if(missing.length)errors.push(join(missing)+(missing.length>1?' are':' is')+' not on the VM and no registry offers '+(missing.length>1?'them':'it')+' (not there, or a login on the VM is needed)');
 if(invalid.length)errors.push(join(invalid)+(invalid.length>1?' are not usable image names':' is not a usable image name'));
 if(silent.length)warnings.push(join(silent)+': its registry did not answer, a deploy would try to pull '+(silent.length>1?'them':'it'));
 if(unknown.length)warnings.push(join(unknown)+': not on the VM and could not be checked');
 if(errors.length)return {text:'Error: '+errors.join('; ')+'. A deploy fails until the image is on the VM or another one is chosen.'+(warnings.length?' Also: '+warnings.join('; ')+'.':''),tone:'error',warn:true};
 if(warnings.length)return {text:'Warning: '+warnings.join('; ')+'.',tone:'warn',warn:true};
 return {text:list.length===1?'Image checked: available on the VM or pullable from its registry.':'Images checked: all '+list.length+' available on the VM or pullable from their registry.',tone:'info',warn:false};
}
// What is shown stays until it is dismissed or the next different result replaces it. A dismissed result is
// remembered by draft + references + tone + text, so the same answer on a later check does not come back.
function builderImageKey(draftId,refs,summary){return [draftId,refs.join(','),summary.tone,summary.text].join('|');}
// A new lab always begins as a blank canvas; devices come from dragging the palette's templates
// (BUILDER_TEMPLATES above, which also feed builderPage.templates()/images()) onto it, not from a
// starter shape.
function builderBlank(name){return {yaml:'name: '+name+'\ntopology:\n  nodes: {}\n',annotations:''};}

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
 const same=!draftUnsaved(draft);
 return same?{tone:'ok',text:'Saved on the VM',detail:draft.vm.path}:{tone:'warn',text:'Changes not saved to the VM yet',detail:draft.vm.path};
}
// SHA-256 of a text. Browsers offer crypto.subtle to secure contexts only, and the manager is normally opened
// as http://<VM address>, which is none: the plain implementation below is then the one that runs.
function builderSha256(bytes){
 const K=[],H=[];for(let n=2,i=0;i<64;n++){let prime=true;for(let d=2;d*d<=n;d++)if(n%d===0){prime=false;break;}if(!prime)continue;if(i<8)H[i]=Math.floor((Math.sqrt(n)%1)*4294967296);K[i++]=Math.floor((Math.cbrt(n)%1)*4294967296);}
 const length=bytes.length,total=(length+9+63)&~63,data=new Uint8Array(total),view=new DataView(data.buffer),w=new Uint32Array(64);
 data.set(bytes);data[length]=0x80;view.setUint32(total-8,Math.floor(length/536870912));view.setUint32(total-4,(length<<3)>>>0);
 const rot=(x,n)=>(x>>>n)|(x<<(32-n));
 for(let o=0;o<total;o+=64){
  for(let i=0;i<16;i++)w[i]=view.getUint32(o+i*4);
  for(let i=16;i<64;i++){const a=w[i-15],b=w[i-2];w[i]=(w[i-16]+(rot(a,7)^rot(a,18)^(a>>>3))+w[i-7]+(rot(b,17)^rot(b,19)^(b>>>10)))>>>0;}
  let [a,b,c,d,e,f,g,h]=H;
  for(let i=0;i<64;i++){const t1=(h+(rot(e,6)^rot(e,11)^rot(e,25))+((e&f)^(~e&g))+K[i]+w[i])>>>0,t2=((rot(a,2)^rot(a,13)^rot(a,22))+((a&b)^(a&c)^(b&c)))>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}
  [a,b,c,d,e,f,g,h].forEach((v,i)=>{H[i]=(H[i]+v)>>>0;});
 }
 return H.map(v=>v.toString(16).padStart(8,'0')).join('');
}
async function builderHash(text){
 const bytes=new TextEncoder().encode(text);
 if(typeof crypto==='undefined'||!crypto.subtle)return builderSha256(bytes);
 return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
}
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
// A list saved from this page was edited against the current defaults: never migrate it afterwards.
function builderMarkTemplatesCurrent(){try{builderStore.setItem(BUILDER_PREFIX+'templates-version',BUILDER_TEMPLATES_VERSION);}catch{}}
function builderTemplatesStored(){
 try{
  const v=JSON.parse(builderStore.getItem(BUILDER_PREFIX+'templates')||'null');
  // Nothing stored: the current defaults are in use, so there is nothing to migrate later either.
  if(!(v&&Array.isArray(v.list)&&v.list.length)){builderMarkTemplatesCurrent();return null;}
  // Once per browser (marker): move still-default built-in templates to the n24l images.
  if(builderStore.getItem(BUILDER_PREFIX+'templates-version')!==BUILDER_TEMPLATES_VERSION){
   const m=builderMigrateTemplates(v.list);
   try{if(m.changed)builderStore.setItem(BUILDER_PREFIX+'templates',JSON.stringify({...v,list:m.list}));builderStore.setItem(BUILDER_PREFIX+'templates-version',BUILDER_TEMPLATES_VERSION);}catch{return {...v,list:m.list};}
   return {...v,list:m.list};
  }
  return v;
 }catch{}
 return null;
}
// The topology file a draft is, or will be, on the VM: the same derivation as the VM helper's.
function builderVmPath(draft){if(draft.vm)return draft.vm.path;const named=builderYamlName(draft.yaml),name=builderName(named)?named:draft.name;return draft.root+'/'+name+'/'+name+'.clab.yml';}
// A draft that is not on the VM yet carries the name its topology has (Lab settings can rename it).
function builderNamed(draft){const named=builderYamlName(draft.yaml);return !draft.vm&&builderName(named)&&named!==draft.name?{...draft,name:named}:draft;}
// Why Save is off, in words ('' when it is on). The same text is the button's tooltip and the note under the bar.
function builderBlocked(){
 if(!builderDraft)return '';
 if(builderUnstored||builderPaused)return 'Your last change is not stored in this browser yet, so it cannot be saved to the VM.';
 const name=builderNameProblem(builderDraft);if(name)return name;
 if(!builderCaps&&!builderCapsError)return 'Checking whether saving to the VM is available…';
 if(builderCapsError)return 'Saving to the VM is not available right now: '+builderCapsError+' You can keep building; the draft stays in this browser and can be downloaded.';
 if(builderCaps&&!builderCaps.actions?.[builderDraft.vm?'revise':'publish']?.available)return "Saving to the VM is not available: the VM's helper programs are older than this manager. Ask an administrator to run start-manager.sh on the VM. You can still build and download a draft.";
 return '';
}
// Worth knowing before the work is done, not only when the save is refused.
function builderNotice(){
 // With #lab the line under the bar says it (builderLine).
 if(!builderDraft?.vm||builderLab())return '';const lab=(state.labs||[]).find(l=>opPath(l)===builderDraft.vm.path);
 return lab&&/^(running|starting|partial)/i.test(lab.deployment?.status||'')?'This lab is running: saving changes the file and the map, not the devices; applying is a separate step.':'';
}
// --- the lab this page edits (#lab=<id>) -------------------------------------------------------------------------------------------
// A lab that left the manager while the page was open is no longer "the lab": the bar falls back to the file name and My labs.
function builderLab(){return builderLabId?(state.labs||[]).find(l=>l.id===builderLabId)||null:null;}
function builderLabUrl(extra){return '/#lab='+encodeURIComponent(builderLabId)+'&view=topology'+(extra||'');}
function builderLabRunning(lab){return !!lab&&['Running','Partially running'].includes(lab.deployment?.status);}
function builderDate(value){const d=new Date(value);return Number.isNaN(d.getTime())?String(value||''):d.toLocaleString();}
function builderTitle(){
 const lab=builderLab();
 return builderDraft?(lab?lab.name+' · Edit topology':builderDraft.name+' · Lab builder')+' · Containerlab Node Manager':'Lab builder · Containerlab Node Manager';
}
// The plan the last deployed save left (operations.js reads it with opLoadPlan): changes, or a check that gave no answer.
function builderPlanAnswer(lab){const entry=lab&&opPlanCache[lab.id];return entry&&entry.answer?entry.answer:null;}
function builderPlanChanges(lab){const a=builderPlanAnswer(lab);return !!a&&a.changed===true&&!a.failed&&!!a.plan&&opPlanChanges(a.plan);}
// True while a deployed lab runs something other than the saved file, or after a deployed save while nobody knows yet.
function builderNotApplied(lab){
 if(!builderLabRunning(lab))return false;
 if(builderPlanChanges(lab))return true;
 if(!builderAfter||!builderAfter.deployed)return false;
 const a=builderPlanAnswer(lab);return !a||!!a.failed;
}
function builderLabState(lab){
 const status=lab.deployment?.status||'',nodes=lab.nodes||[],n=nodes.length,devices=n+' device'+(n===1?'':'s');
 const tail=' Saving changes the file and the map, not the devices; applying is a separate step.';
 if(status==='Running')return 'This lab is running on the VM ('+devices+').'+tail;
 if(status==='Partially running')return 'Some devices of this lab are running on the VM ('+nodes.filter(x=>x.runtime_state==='running').length+' of '+n+').'+tail;
 if(status==='Stopped')return 'This lab is stopped on the VM ('+devices+').'+tail;
 if(status==='Not deployed')return 'This lab is not deployed.';
 return 'Whether this lab is running is not known right now.'+tail.replace('the devices','any devices that may be running');
}
// What the plan says about the file just saved (or saved earlier) against the running lab; '' when there is nothing to say yet.
function builderPlanSentence(lab){
 const after=!!builderAfter&&builderAfter.deployed;
 if(!after&&!builderPlanChanges(lab))return '';
 if(!builderLabRunning(lab))return 'Saved on the VM. The devices are not running, so there is no running lab to compare the file with.';
 const entry=opPlanCache[lab.id],a=entry&&entry.answer;
 if(!entry)return 'Saved on the VM. Checking what applying would change…';
 if(!a)return 'Saved on the VM. What applying would change could not be checked ('+(entry.error||'no answer')+'). Back to lab and review changes… asks again.';
 if(a.failed==='unsupported')return 'Saved on the VM. The installed containerlab cannot show what applying will change; Lab actions ▾ › Apply topology changes… runs without a plan.';
 if(a.failed)return 'Saved on the VM. What applying would change could not be checked: '+(a.error||'the topology file could not be read')+'. Lab actions ▾ › Apply topology changes… shows the review.';
 if(builderPlanChanges(lab))return (after?'Saved on the VM, not applied. ':'')+'The running lab differs from the file: '+opPlanSummary(a.plan)+'. Back to lab and review changes… shows the plan; Lab actions ▾ › Apply topology changes… applies it.';
 return builderAfter&&builderAfter.mapOnly?'Saved on the VM. Only the map layout changed, and the running lab matches the file: there is nothing to apply.':'Saved on the VM. The running lab already matches the file: there is nothing to apply.';
}
// The one plain line under the bar (its own element, not a live region): the lab's state, the plan, a continued draft.
function builderLine(){
 const lab=builderLab(),parts=[];
 if(lab){
  const plan=builderPlanSentence(lab);
  parts.push(plan&&builderAfter&&builderAfter.deployed?plan:[builderLabState(lab),plan].filter(Boolean).join(' '));
 }else if(builderAfter&&builderAfter.deployed)parts.push('Saved on the VM. The running lab is unchanged until you apply the changes.');
 if(builderContinued&&builderHasUnsaved())parts.push('Continuing your draft from '+builderDate(builderContinued)+'; its changes are not on the VM yet.');
 return parts.join(' ');
}
function builderRenderBar(){
 const lab=builderLab(),base=draftStatus(builderDraft,builderUnstored),s=lab&&base.tone==='ok'&&builderNotApplied(lab)?{...base,tone:'warn',text:'Saved on the VM · not applied'}:base;
 $('builder-name').textContent=builderDraft?(lab?'Editing '+lab.name:builderDraft.name):'';
 const back=$('builder-back');back.textContent=lab?'← Back to lab':'← My labs';back.href=lab?builderLabUrl():'/';
 if(builderDraft)document.title=builderTitle();$('builder-status').textContent=s.text;$('builder-status').title=[s.text,s.detail].filter(Boolean).join(' · ');$('builder-status').className='pill '+s.tone;
 // Nothing to say when no draft is open: the pill carries no text then, so it stays out of the way
 // (and out of the accessibility tree) instead of showing an empty, colourless chip.
 $('builder-status').hidden=!s.text;
 const blocked=builderBlocked(),can=!!builderDraft&&!blocked;
 $('builder-save').disabled=!can;$('builder-save').title=blocked;$('builder-save').textContent=builderDraft?.vm?'Save changes to the VM…':'Save to the VM…';
 for(const id of ['builder-yaml','builder-download'])$(id).disabled=!builderDraft;
 const note=blocked||builderNotice()||builderStorageNote;$('builder-note-text').textContent=note;$('builder-note').hidden=!note||!!builderUnstored;$('builder-note-retry').hidden=!builderCapsError||note!==blocked;
 const line=builderLine(),review=lab&&builderNotApplied(lab);
 $('builder-line-text').textContent=line;$('builder-review').hidden=!review;if(review)$('builder-review').href=builderLabUrl('&review=apply');
 $('builder-line').hidden=!line&&!review;
}
function builderHint(){const hint=$('builder-hint');if(hint)hint.hidden=!builderMounted||!!document.querySelector('.react-flow__node');}
function builderProblem(message,code){builderPaused=builderPaused||Object.assign(new Error(message),{code});$('root').inert=true;$('builder-problem-text').textContent=message;$('builder-problem-retry').hidden=code!=='storage';$('builder-problem').hidden=false;$('builder-problem-download').focus();builderRenderBar();}
// The editor's side of the page (see lab-builder/src/main.tsx).
const builderPage={
 // Throws when the pair could not be stored; the editor then reports the edit as failed and the page
 // keeps what the editor holds (builderUnstored) so that Download draft still gives the newest work.
 persist(yaml,annotations){
  if(!builderDraft)return;setTimeout(builderHint,0);
  if(builderPaused){builderUnstored={yaml,annotations};builderRenderBar();throw builderPaused;}
  if(!builderUnstored&&yaml===builderDraft.yaml&&annotations===(builderDraft.annotations||''))return;
  try{builderDraft=draftWrite(builderStore,builderNamed({...builderDraft,yaml,annotations}),builderDraft.revision);builderUnstored=null;}
  catch(e){builderUnstored={yaml,annotations};builderRenderBar();throw e;}
  document.title=builderTitle();builderRenderBar();builderImageStatus();builderCheckStatus();
 },
 templates(){const stored=builderTemplatesStored();return stored?{list:builderAppendCatalog(stored.list,builderKnown,builderVmImages),defaultName:stored.defaultName||''}:{list:builderTemplateList(builderKnown,builderVmImages),defaultName:BUILDER_TEMPLATES[0].name};},
 saveTemplates(list,defaultName){try{builderStore.setItem(BUILDER_PREFIX+'templates',JSON.stringify({list,defaultName}));builderMarkTemplatesCurrent();}catch{notify('This browser could not keep the device template.');}},
 images(){return builderImages(this.templates().list,builderKnown,builderVmImages);},
 // The palette's Import templates: the editor leaves the file dialog to its host.
 chooseTemplates(){return new Promise((resolve,reject)=>{const input=$('builder-templates-file');input.value='';input.oncancel=()=>resolve(null);input.onchange=()=>{const file=input.files[0];if(!file)resolve(null);else if(file.size>1200*1024)reject(new Error('This file is too large to be a template file.'));else file.text().then(resolve,reject);};input.click();});},
 notify,
 requestSave(){opTask(null,builderSave);},
 problem(message,code){builderProblem(message,code);},
 ready(mount){builderMount=mount;if(builderDraft)builderOpenEditor();},
 // The editor's topology text handle (applyYaml, getYaml, checkYaml, subscribe): the YAML panel's engine.
 attach(editor){if(typeof builderYamlPanelInit==='function')builderYamlPanelInit(builderYamlOptions(editor));builderHistoryWire(editor);builderCheckStatus();},
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
// #lab stays in the address while the page moves between drafts and versions of the same file (Drafts… › Open, Open the VM version).
function builderKeepLab(values){
 if(!builderLabId||values.lab)return values;
 const mine=builderDraft&&builderVmPath(builderDraft),target=values.draft?draftRead(builderStore,values.draft):null;
 return (values.path&&values.path===mine)||(target&&target.vm&&target.vm.path===mine)?{...values,lab:builderLabId}:values;
}
// One editor per page load: opening another draft reloads the page with it.
function builderGo(values){
 // Without browser storage a reload would lose the draft; before an editor is mounted none is needed.
 const kept=builderStorageNote&&!builderMounted&&values.draft?draftRead(builderStore,values.draft):null;
 if(!kept&&builderStorageNote&&builderMounted&&!confirm('This browser does not store drafts, and opening another lab reloads the page: the drafts of this tab are lost unless you downloaded them. Continue?'))return;
 location.hash=new URLSearchParams(builderKeepLab(values)).toString();
 if(kept){document.querySelectorAll('dialog[open]').forEach(d=>d.close());builderUse(kept);}else location.reload();
}
function builderUse(draft){builderDraft=builderNamed(draft);builderRenderBar();document.title=builderTitle();builderOpenEditor();builderImageStatus();builderCheckStatus();}
// The background image check: after every stored change (debounced) the draft's images are sent to the manager,
// which asks the VM once per image and keeps the answers. The answer is dropped when the draft or the request
// number changed while it was on its way. The editor is never waited on; a request that fails is shown too.
let builderImageTimer=null,builderImageSeq=0,builderImageDismissed='',builderImageShown='';
// Runs one check; resolves {key,summary} for the answer to show, or null when it is stale (or there is nothing to check).
async function builderImageCheck(refs){
 const draftId=builderDraft?builderDraft.id:'',seq=++builderImageSeq;
 if(!refs.length)return null;
 let summary;
 try{summary=builderImageSummary((await json('/operations/image-check','POST',{references:refs})).images);}
 catch(e){summary={text:'Warning: the images could not be checked ('+((e&&e.message)||'the manager did not answer')+'). They are checked again after the next change; a deploy still fails if an image is missing.',tone:'warn',warn:true};}
 if(seq!==builderImageSeq||!builderDraft||builderDraft.id!==draftId)return null;
 return summary.text?{key:builderImageKey(draftId,refs,summary),summary}:null;
}
function builderImageRender(result){
 const slot=$('builder-images');if(!slot)return;
 if(!result){builderImageShown='';slot.hidden=true;return;}
 if(result.key===builderImageDismissed){builderImageShown='';slot.hidden=true;return;}
 builderImageShown=result.key;slot.className='builder-images'+(result.summary.tone==='error'?' error':result.summary.tone==='warn'?' warn':'');
 slot.setAttribute('role',result.summary.tone==='error'?'alert':'status');
 if($('builder-images-lead'))$('builder-images-lead').hidden=result.summary.tone!=='info';   // warning and error say Warning:/Error: in their own text
 $('builder-images-text').textContent=result.summary.text;slot.hidden=false;
}
function builderImageDismiss(){
 builderImageDismissed=builderImageShown;builderImageShown='';const slot=$('builder-images');if(slot)slot.hidden=true;
 // The button just left the page: focus goes to the next thing the student does, Save (or the YAML button when Save is off).
 const next=!$('builder-save').disabled?$('builder-save'):$('builder-yaml');if(next&&!next.disabled)next.focus();
}
function builderImageStatus(){
 if(!$('builder-images'))return;
 if(builderImageTimer)clearTimeout(builderImageTimer);
 builderImageTimer=setTimeout(async()=>{
  builderImageTimer=null;const refs=builderDraft?builderYamlImages(builderDraft.yaml):[];
  const result=await builderImageCheck(refs);
  if(result)builderImageRender(result);else if(!refs.length)builderImageRender(null);
 },builderDraft?1200:0);
}
if(typeof document!=='undefined'&&document.getElementById('builder-images-dismiss'))$('builder-images-dismiss').onclick=builderImageDismiss;
// The topology check note (docs/parity-campaign/C08-DESIGN.md section 4.4): after a stored change, the errors in the stored text that
// containerlab will refuse when the lab is deployed, in one line under the bar, so a student who never opens the YAML panel still learns
// before saving. Advice only: it never changes builderBlocked(). builderCheckStatus() only arms a timer; the check runs inside the timer
// and a throw anywhere in it hides the note and nothing else, so an advisory check can never pause the builder (persist() is untouched).
let builderNoteTimer=null,builderNoteSeq=0,builderNoteDismissed='',builderNoteShown='',builderNoteLine=0;
function builderNoteHash(text){let h=5381;for(let i=0;i<text.length;i++)h=((h<<5)+h+text.charCodeAt(i))|0;return (h>>>0).toString(36)+':'+text.length;}
// The dismissed note is remembered for the browser tab's life (sessionStorage, per draft, text and count: the note's own key), so a reload keeps the same
// problems dismissed until the text changes. A browser that refuses storage just forgets it.
function builderNoteSession(){try{const s=window.sessionStorage;return s&&typeof s.getItem==='function'?s:null;}catch{return null;}}
function builderNoteStored(){try{const s=builderNoteSession();return s?s.getItem(BUILDER_PREFIX+'note-dismissed')||'':'';}catch{return '';}}
function builderNoteRemember(key){try{const s=builderNoteSession();if(s&&key)s.setItem(BUILDER_PREFIX+'note-dismissed',key);}catch{}}
// `errors` counts what containerlab refuses; `first` is the first of them. The manager's own refusals (finding.refuser === 'manager') are counted apart.
// `waits` counts how many of the errors are wait-* codes: containerlab's validate and deploy --dry-run accept those and the deploy
// then never finishes, so a note made of them alone says what happens, not that containerlab refuses.
function builderNoteSentence(errors,first,manager,waits){
 let message=String(first.message||'').trim();if(!/[.!?]$/.test(message))message+='.';
 if(!errors)return (manager===1?'1 error':manager+' errors')+' the manager’s import refuses: '+(manager===1?'':'the first is ')+'line '+first.line+', '+message+' Open YAML to see it.';
 const kind=!waits?' containerlab will refuse when deploying:':waits>=errors?(errors===1?' that keeps':' that keep')+' the deploy from finishing:':(errors===1?' that stops':' that stop')+' the deploy:';
 return errors+' error'+(errors===1?'':'s')+kind+' '+(errors===1?'':'the first is ')+'line '+first.line+', '+message+' Open YAML to see it.'
  +(manager?' The manager’s import also refuses '+manager+' more.':'');
}
function builderNoteRender(result){
 const slot=$('builder-check');if(!slot)return;
 if(!result||result.key===builderNoteDismissed||result.key===builderNoteStored()){builderNoteShown='';builderNoteLine=0;slot.hidden=true;return;}
 builderNoteShown=result.key;builderNoteLine=result.line;$('builder-check-text').textContent=result.text;slot.hidden=false;
}
// The note for a list of findings: every error, whatever the version match (a wait loop, an unknown endpoint, a missing kind are errors on any VM).
function builderNoteFor(draft,text,list){
 const errors=builderCheckSummary(list).errors,listed=list.filter(f=>f.severity==='error'&&f.code!=='more'&&f.line>0);
 const manager=listed.filter(f=>f.refuser==='manager').length,mine=listed.filter(f=>f.refuser!=='manager'),first=mine[0]||listed[0];
 if(!errors||!first)return null;
 // The generic sentence counts containerlab's errors only; an error the manager's own import refuses is worded as that.
 const clab=Math.max(0,errors-manager);
 return {key:[draft.id,builderNoteHash(text),errors].join('|'),text:builderNoteSentence(clab,first,manager,list.filter(f=>f.severity==='error'&&f.refuser!=='manager'&&/^wait-/.test(String(f.code))).length),line:first.line};
}
async function builderNoteRun(){
 const seq=++builderNoteSeq;
 try{
  const draft=builderDraft;if(!draft||typeof builderYamlLocate!=='function'||typeof builderCheckSummary!=='function'){builderNoteRender(null);return;}
  const text=builderYamlDraft(),located=builderYamlLocate(text);
  if(!located||!located.tree){builderNoteRender(null);return;}
  const wasLoaded=typeof builderYamlSchemaNow==='function'&&!!builderYamlSchemaNow();
  const loading=typeof builderYamlSchema==='function'?builderYamlSchema():null;
  builderNoteRender(builderNoteFor(draft,text,builderYamlRun(located.tree)));
  // Until the schema arrives only the rules that need none have run; run again once it is here.
  if(loading&&!wasLoaded&&!builderYamlSchemaNow()){
   const data=await loading;
   if(data&&seq===builderNoteSeq&&builderDraft&&builderDraft.id===draft.id&&builderYamlDraft()===text)builderNoteRender(builderNoteFor(draft,text,builderYamlRun(located.tree)));
  }
 }catch{try{builderNoteRender(null);}catch{}}
}
function builderCheckStatus(){
 try{
  if(!$('builder-check'))return;
  if(builderNoteTimer)clearTimeout(builderNoteTimer);
  builderNoteTimer=setTimeout(()=>{builderNoteTimer=null;builderNoteRun();},builderDraft?1200:0);
 }catch{}
}
function builderNoteDismiss(){
 builderNoteDismissed=builderNoteShown;builderNoteRemember(builderNoteDismissed);builderNoteShown='';const slot=$('builder-check');if(slot)slot.hidden=true;
 const next=!$('builder-save').disabled?$('builder-save'):$('builder-yaml');if(next&&!next.disabled)next.focus();
}
// Show in YAML: opens the panel. A clean panel gets the caret on the finding's line; a panel with unapplied edits (its lines differ from the
// stored text) opens at its own Problems list instead and moves nothing.
function builderNoteShow(){
 const state=typeof builderYamlPanelState==='function'?builderYamlPanelState():null,dirty=!!state&&(state.dirty||state.canvasChanged||state.applying),line=builderNoteLine;
 builderYamlPanelToggle(true);
 if(!dirty){builderYamlGoto(line,{select:false});return;}
 const first=$('builder-yaml-list')&&$('builder-yaml-list').querySelector('button');if(first)first.focus();
}
if(typeof document!=='undefined'&&document.getElementById('builder-check-dismiss')){$('builder-check-dismiss').onclick=builderNoteDismiss;$('builder-check-show').onclick=builderNoteShow;}
// The id of a new draft. A draft renamed in the editor keeps its first id, so that id can be taken by another name.
function builderDraftId(name){const id='new:'+name;return draftRead(builderStore,id)?id+':'+draftToken():id;}
function builderNewDialog(root){
 const roots=(builderCaps?.roots||[]).length?builderCaps.roots:[root];
 const dialog=opDialog('builder-new','New lab',`<label>Lab name<input id="builder-new-name" maxlength="60" autocomplete="off" spellcheck="false"></label><p class="form-help">Letters, digits, dot, dash and underscore. The name becomes the lab folder on the VM and part of every device's container name. The lab starts as a blank canvas; drag devices from the palette to build it.</p><label>Lab folder on the VM<select id="builder-new-root">${roots.map(r=>`<option ${r===root?'selected':''}>${esc(r)}</option>`).join('')}</select></label><div class="dialog-actions"><button class="button secondary" id="builder-new-cancel">Cancel</button><button class="button primary" id="builder-new-create">Create draft</button></div>`);
 $('builder-new-cancel').onclick=()=>dialog.close();
 const create=()=>opTask(dialog,async()=>{
  const name=$('builder-new-name').value.trim();if(!builderName(name))throw new Error('Choose a lab name made of letters, digits, dot, dash or underscore (up to 60 characters).');
  if((state.labs||[]).some(l=>(l.deployment_name||l.name)===name))throw new Error('A lab named '+name+' is already in My labs. Choose another name.');
  if(draftList(builderStore).some(d=>d.name===name))throw new Error('This browser already has a draft named '+name+'. Open it from Drafts, or choose another name.');
  const id=builderDraftId(name);
  draftWrite(builderStore,{id,name,root:$('builder-new-root').value,...builderBlank(name)},undefined);builderGo({draft:id});
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
 return {draft:{root,...value,name},note};
}

// --- drag-and-drop (and the "Open lab files…" picker), on the welcome page or on the canvas ---------
// 1-2 files, order independent: a containerlab topology and, optionally, its saved map. The map is
// recognised by name only (*.annotations.json, the name this builder and the VS Code extension both
// write) and its JSON is checked here, the same rule as operations.js opUploadAnnotationsParse, kept
// local because this page's own scripts do not assume operations.js has already run. The topology's
// YAML is checked by the manager instead (builderDropOpen), exactly like a downloaded draft
// (builderImportDraft above) or an uploaded file (operations.js opUpload).
const BUILDER_DROP_LIMIT=1024*1024;
function builderMapText(text){
 let value;try{value=JSON.parse(text);}catch{throw new Error('The map file is not valid JSON.');}
 if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('The map file must hold one JSON object, not a list or a plain value.');
 return text;
}
// Pure over {name,size,text} descriptors (the caller has already read the files), so pairing, the
// file-count and size rules and the map's JSON can be tested without a browser File or the manager.
function builderDropPair(files){
 const list=[...(files||[])];
 if(!list.length)throw new Error('Drop a lab file, or use Open lab files… to choose one.');
 if(list.length>2)throw new Error('Drop one topology file, optionally with its saved map (up to two files).');
 const isMap=f=>/\.annotations\.json$/i.test(f.name||''),isYaml=f=>!isMap(f)&&/\.ya?ml$/i.test(f.name||'');
 const topologies=list.filter(isYaml),maps=list.filter(isMap),other=list.filter(f=>!isYaml(f)&&!isMap(f));
 if(other.length)throw new Error('Drop a containerlab topology file (.clab.yml or .yaml) and, optionally, its saved map (a *.annotations.json file).');
 if(!topologies.length)throw new Error('Drop a containerlab topology file (.clab.yml or .yaml).');
 if(topologies.length>1)throw new Error('Drop one topology file at a time.');
 if(maps.length>1)throw new Error('Drop one map file at a time.');
 const topology=topologies[0],map=maps[0]||null;
 for(const f of [topology,map])if(f&&f.size>BUILDER_DROP_LIMIT)throw new Error('"'+f.name+'" is larger than 1 MiB, which is more than a lab file can be.');
 let notice='';
 if(map){
  const base=topology.name.replace(/\.ya?ml$/i,'').toLowerCase();
  if(!map.name.toLowerCase().startsWith(base))notice='The map file name does not match the topology file name; it is used anyway.';
  builderMapText(map.text);
 }
 return {yaml:topology.text,annotations:map?map.text:'',notice};
}
// Whether the open draft holds work the VM does not have: a drop over it then needs a confirmation
// first, so a drop target never loses work by accident. Nothing to lose when no draft is open.
function builderHasUnsaved(){return !!builderDraft&&draftStatus(builderDraft,builderUnstored).tone!=='ok';}
// The drop (or picker) handler: reads the files, pairs and checks them, then opens the result exactly
// as builderImportDraft does for a downloaded draft — one browser draft, checked by the manager, with
// its map kept — and, when a draft was already open with work not on the VM, only after a confirm.
async function builderDropOpen(fileList){
 const files=await Promise.all([...(fileList||[])].map(async f=>({name:f.name,size:f.size,text:await f.text()})));
 const pair=builderDropPair(files);
 if(builderHasUnsaved()&&!confirm('Replace the current draft with the dropped lab?'))return;
 let name=builderYamlName(pair.yaml);
 try{name=(await json('/operations/parse-yaml','POST',{options:{text:pair.yaml}})).name||name;}catch(e){if(!e.network)throw new Error('This topology cannot be read: '+e.message);}
 if(!builderName(name))throw new Error('This lab file has no usable lab name.');
 const root=builderDraft?.root||opBuilderRoot('',builderCaps?.roots);
 const old=draftList(builderStore).filter(d=>d.name===name&&!d.vm);
 if(old.length&&!confirm(old.length>1?'Replace the '+old.length+' drafts named '+name+' that are already in this browser?':'Replace the draft '+name+' that is already in this browser?'))return;
 const made=draftWrite(builderStore,{id:'new:'+name+':'+draftToken(),name,root,yaml:pair.yaml,annotations:pair.annotations},undefined);
 for(const d of old)draftDelete(builderStore,d.id);if(pair.notice)notify(pair.notice);builderGo({draft:made.id});
}
// Drag-and-drop targets: the welcome card before a draft is open, the whole stage (which holds the
// welcome card or the mounted editor) once one is — one set of listeners covers both, because the
// welcome card hides as soon as the editor mounts.
function builderDropWire(){
 // Only a drag that carries files is ours: a device dragged from the editor's palette onto the canvas passes
 // through the stage too, and taking it over (dropEffect 'copy' against the palette's 'move') cancels that drop.
 const files=e=>!!e.dataTransfer&&Array.from(e.dataTransfer.types||[]).includes('Files');
 const prevent=e=>{if(!files(e))return;e.preventDefault();e.dataTransfer.dropEffect='copy';};
 const drop=e=>{if(!files(e))return;e.preventDefault();opTask(null,()=>builderDropOpen(e.dataTransfer.files));};
 for(const id of ['builder-welcome','builder-stage']){const el=$(id);if(!el)continue;el.addEventListener('dragover',prevent);el.addEventListener('drop',drop);}
 $('builder-drop-file').onchange=()=>{const files=[...$('builder-drop-file').files];$('builder-drop-file').value='';opTask(null,()=>builderDropOpen(files));};
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
  const old=draftList(builderStore).filter(d=>d.name===draft.name&&!d.vm);
  if(old.length&&!confirm(old.length>1?'Replace the '+old.length+' drafts named '+draft.name+' that are already in this browser?':'Replace the draft '+draft.name+' that is already in this browser?'))return;
  // Written first: a browser that cannot store the new draft keeps the old ones.
  const made=draftWrite(builderStore,{...draft,id:'new:'+draft.name+':'+draftToken()},undefined);for(const d of old)draftDelete(builderStore,d.id);if(note)alert(note);builderGo({draft:made.id});
 });
}
// The editable YAML panel (lab-builder-yaml.js) drives the editor's engine through the adapter's handle; the
// page only places it, feeds it the draft's newest text and mirrors its open state in the bar and the layout.
function builderYamlDraft(){return builderDraft?(builderUnstored||builderDraft).yaml:'';}
// hadFocus: focus sat inside the panel when it closed (Escape or ×); it returns to the toggle, as the shortcuts dialog says.
function builderYamlShown(open,hadFocus){
 const toggle=$('builder-yaml');toggle.setAttribute('aria-expanded',String(!!open));$('builder-stage').classList.toggle('yaml-open',!!open);
 if(!open&&hadFocus&&typeof toggle.focus==='function')toggle.focus();
}
function builderYamlOptions(editor){return {editor,getDraftYaml:builderYamlDraft,onApplied:()=>builderRenderBar(),onToggle:builderYamlShown};}
// The newest work, also when this browser could not store it.
function builderDownload(){if(builderDraft)builderDownloadDraft({...builderDraft,...(builderUnstored||{})});}
function builderDownloadDraft(draft){const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([draftExport(draft)],{type:'application/json'}));link.download=draft.name+'.lab-draft.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
// Storing again what the editor holds; the editor itself restarts from the stored draft.
function builderStoreAgain(){if(!builderDraft)return;try{builderDraft=draftWrite(builderStore,builderNamed({...builderDraft,...(builderUnstored||{})}),builderDraft.revision);builderUnstored=null;location.reload();}catch(e){builderProblem(e.message,e.code);}}
function builderSame(a,b){return !!a&&!!b&&a.yaml===b.yaml&&(a.annotations||'')===(b.annotations||'');}
// The manager answers a missing file and an unreachable VM with the same status; the helper's wording for
// a missing path is the difference (tests/test_lab_operations.py pins it).
function builderAbsent(error){return !error.network&&/no longer exists/.test(error.message||'');}
// The topology and layout that are on the VM now; null when the topology file is not there. Anything
// else that goes wrong is thrown: "could not read" must never pass for "not there" or "no layout".
async function builderVmRead(path){
 let source,layout=null;
 try{source=await json('/operations/read','POST',{path});}catch(e){if(builderAbsent(e))return null;throw e;}
 try{layout=await json('/operations/read','POST',{path:path+'.annotations.json'});}catch(e){if(!builderAbsent(e))throw e;}
 return {yaml:source.text,annotations:layout?.text||'',hash:source.sha256||'',layoutHash:layout?.text?layout.sha256||'':''};
}
function builderMarkSaved(path,texts){builderDraft=draftWrite(builderStore,{...builderDraft,saving:undefined,mapBase:texts.annotations||'',vm:{path,yaml:texts.yaml,annotations:texts.annotations||'',...(texts.hash?{hash:texts.hash,layoutHash:texts.layoutHash||''}:{})}},builderDraft.revision);builderRenderBar();}
// A save the VM refused. When the file on the VM is not the version this draft knows (an earlier save whose
// answer never arrived, an edit on the VM, another computer), the way on is to look at the differences.
async function builderSaveRefused(error){
 // The manager's map moved on since this page opened (Edit map, Arrange, another save): the topology changes stay in this browser.
 if(error.status===409&&/map changed in the manager/i.test(error.message||'')){builderMapChanged(error);return;}
 const path=builderVmPath(builderDraft);let found=null;
 if(!error.network)try{found=await builderVmRead(path);}catch{}
 if(found&&builderSame(found,builderDraft)){builderMarkSaved(path,found);notify('This lab is already on the VM with the same content.');return;}
 // Only a file that is this lab can become the draft's base: a folder that carries another lab's name is not.
 const other=found&&builderYamlName(found.yaml)!==builderYamlName(builderDraft.yaml)?builderYamlName(found.yaml):'',differs=found&&!other&&!builderSame(found,builderDraft.vm);
 const dialog=opDialog('builder-save-problem','Not saved to the VM',`<p id="builder-save-problem-text"></p><p>Nothing on the VM was changed. Your draft is kept in this browser.</p>${other?`<p>The file <code>${esc(path)}</code> on the VM belongs to a lab named ${esc(other)}. Give this draft another lab name in the editor's Lab settings (the gear button), then save.</p>`:''}${differs?`<p>The VM has a different version of <code>${esc(path)}</code> than this draft started from. That can be an earlier save from this page whose answer never arrived, or a change made on the VM. You can look at the differences and decide, or open the VM version (this draft stays in Drafts).</p>`:''}<div class="dialog-actions"><button class="button secondary" id="builder-save-problem-close">Close</button>${differs?`<button class="button secondary" id="builder-save-problem-open">Open the VM version</button><button class="button primary" id="builder-save-problem-compare">Review the differences…</button>`:''}</div>`);
 $('builder-save-problem-text').textContent=error.message;$('builder-save-problem-close').onclick=()=>dialog.close();
 if(!differs)return;
 $('builder-save-problem-open').onclick=()=>builderGo({path});
 // From here the draft descends from the version that is on the VM, so the next save is a reviewed
 // revision: it shows the differences, keeps a recovery copy and, for a lab with devices, says what it leaves alone.
 $('builder-save-problem-compare').onclick=()=>opTask(dialog,async()=>{builderDraft=draftWrite(builderStore,{...builderDraft,vm:{path,...found}},builderDraft.revision);builderRenderBar();dialog.close();await builderSave();});
}
function builderMapChanged(error){
 const dialog=opDialog('builder-save-problem','Not saved to the VM',`<p id="builder-save-problem-text"></p><p>Nothing on the VM was changed. Your topology changes stay in this browser.</p><div class="dialog-actions"><button class="button secondary" id="builder-save-problem-close">Close</button><button class="button secondary" id="builder-save-problem-download">Download my draft</button><button class="button primary" id="builder-save-problem-reopen">Reopen</button></div>`);
 $('builder-save-problem-text').textContent=error.message;$('builder-save-problem-close').onclick=()=>dialog.close();
 $('builder-save-problem-download').onclick=builderDownload;
 // Reopen: back to the lab, where Edit topology… reads the manager's map again; this draft takes it over and keeps its topology text.
 $('builder-save-problem-reopen').onclick=()=>{try{builderDraft=draftWrite(builderStore,{...builderDraft,mapStale:true},builderDraft.revision);}catch{}location.href=builderLab()?builderLabUrl():'/';};
}
// The review's answer, kept with the pending save (see json()): a deployed save does not re-register the lab afterwards.
function builderPreviewSeen(request,value){
 if(!builderPending||!request||request.action!==builderPending.action||request.action!=='revise'||!value)return;
 builderPending.deployed=value.deployed===true;
}
// A revision also carries the lab it belongs to and the map revision it started from, when the page knows them (the manager
// answers 404 "Lab not found" for a lab that left, and 409 when the map moved on).
function builderSaveExtras(request,lab){
 if(request.action!=='revise')return request;
 if(builderCaps?.actions?.revise?.deployed===true)request.options.deployed=true;
 if(lab){
  request.lab_id=lab.id;
  const revision=builderDraft.mapRevision;if(revision!==undefined&&revision!=='')request.map_revision=revision;
 }
 return request;
}
async function builderSave(){
 if(!builderDraft||builderBlocked())return;
 if(builderPending?.job){notify('The previous save is still running on the VM. Its result will show here.');return;}
 const request=await builderSaveRequest(builderDraft);
 // The labs and their states as they are now, before the request says what it knows about them.
 try{await refresh();}catch{}
 const lab=builderLab()||(state.labs||[]).find(l=>opPath(l)===builderVmPath(builderDraft))||null;
 builderSaveExtras(request,lab);
 builderPending={yaml:builderDraft.yaml,annotations:builderDraft.annotations||'',action:request.action,path:builderVmPath(builderDraft),baseYaml:builderDraft.vm?builderDraft.vm.yaml:''};
 // Remembered with the draft (as hashes of what is sent): if this page never hears the outcome, the next
 // visit asks the VM and recognises its own save, also after further edits.
 try{builderDraft=draftWrite(builderStore,{...builderDraft,saving:{path:builderPending.path,yaml:await builderHash(builderPending.yaml),annotations:builderPending.annotations?await builderHash(builderPending.annotations):''}},builderDraft.revision);}catch(e){builderPending=null;builderProblem(e.message,e.code);return;}
 try{await opReview(request);}
 catch(e){
  if(request.lab_id&&e.status===404&&/lab not found/i.test(e.message||'')){
   // The lab left the manager since the page opened: a path-only save, as before the page knew labs.
   delete request.lab_id;delete request.map_revision;builderLabId='';builderRenderBar();
   try{await opReview(request);return;}catch(again){e=again;}
  }
  builderPending=null;await builderSaveRefused(e);
 }
}
// Called by operations.js when the review was confirmed and the job exists.
function opJobStarted(job){if(builderPending&&job.action===builderPending.action)builderPending.job=job.id;}
// Called by operations.js when a lab operation started from this page finishes.
function opJobDone(job){
 if(!builderPending||!builderDraft||job.action!==builderPending.action||(builderPending.job&&job.id&&job.id!==builderPending.job))return;
 const saved=builderPending,done=job.status==='succeeded'&&(job.result?.published_path||job.result?.already_published),path=job.result?.published_path||saved.path||builderVmPath(builderDraft);builderPending=null;
 try{if(done)builderMarkSaved(path,saved);else builderDraft=draftWrite(builderStore,{...builderDraft,saving:undefined},builderDraft.revision);}catch(e){builderProblem(e.message,e.code);}
 builderRenderBar();if(!done)return;
 const lab=(state.labs||[]).find(l=>opPath(l)===path);
 // A deployed save changed the file and the map, not the devices: the manager keeps the lab as it runs until an apply succeeds,
 // so nothing is registered again here and nothing reads as applied.
 if(saved.action==='revise'&&saved.deployed){builderDeployedSaved(saved,lab||builderLab());return;}
 // A lab that is already in My labs keeps the devices and the map it was registered with. After a
 // revision the manager takes the new topology and layout, so its own map and device list follow.
 if(lab&&saved.action==='revise')opTask(null,async()=>{
  const form=new FormData(),name=path.split('/').pop();form.append('lab_id',lab.id);
  form.append('definition',new Blob([saved.yaml],{type:'text/yaml'}),name);
  if(saved.annotations)form.append('annotations',new Blob([saved.annotations],{type:'application/json'}),name+'.annotations.json');
  if(lab.deployment_name)form.append('deployed_name',lab.deployment_name);
  await api('/lab-definitions',{method:'POST',body:form});await refresh();notify('My labs now shows the saved topology of '+lab.name+'.');
  // The registration made a new map revision: the next save starts from it.
  if(lab.id===builderLabId)try{
   const doc=await builderMapDocument(lab.id);
   if(doc&&doc.annotations===saved.annotations)builderDraft=draftWrite(builderStore,{...builderDraft,mapRevision:doc.revision,mapBase:doc.annotations},builderDraft.revision);
  }catch{}
 });
}
// After a deployed save: the toast, the plan read again for the lab (the old answer was about the old file), and focus on the control
// that leads to the lab page's own apply review once the output dialog is closed.
function builderDeployedSaved(saved,lab){
 builderAfter={deployed:true,mapOnly:saved.yaml===saved.baseYaml};
 notify('Saved to the VM. The running lab is unchanged until you apply the changes.');
 if(builderLabRunning(lab))delete opPlanCache[lab.id];
 builderRenderBar();
 const review=$('builder-review'),output=$('operation-output'),focus=()=>{if(!review.hidden&&typeof review.focus==='function')review.focus();};
 if(output&&output.open&&typeof output.addEventListener==='function')output.addEventListener('close',()=>setTimeout(focus,0),{once:true});else focus();
 if(builderLabRunning(lab))builderLabPlan(lab.id);
}
// The plan for the running lab: asked when the page opens with #lab and after a deployed save (opLoadPlan keeps the answer).
async function builderLabPlan(labId){
 try{await opLoadPlan(labId,true);}catch{}
 builderRenderBar();
}
// Called by operations.js when it gave up following a job (the manager did not answer for a while).
function opJobLost(){if(!builderPending?.job)return;builderPending=null;opTask(null,builderReconcile);}
// A save was started from this draft and this page never heard how it ended (closed tab, lost connection).
// The marker stays until the VM could actually be asked.
async function builderReconcile(){
 if(!builderDraft?.saving||builderPending)return;
 const sent=builderDraft.saving,path=(typeof sent==='object'&&sent.path)||builderVmPath(builderDraft);let found;
 try{found=await builderVmRead(path);}catch{return;}
 const same=async()=>typeof sent==='object'&&sent.yaml===await builderHash(found.yaml)&&(sent.annotations||'')===(found.annotations?await builderHash(found.annotations):'');
 try{
  if(found&&builderSame(found,builderDraft))builderMarkSaved(path,found);
  // what was sent is on the VM and the draft moved on since: a saved lab with newer changes here
  else if(found&&await same())builderMarkSaved(path,found);
  else builderDraft=draftWrite(builderStore,{...builderDraft,saving:undefined},builderDraft.revision);
 }catch{}
 builderRenderBar();
}
// The manager's kept map document of a lab (what Edit map and Arrange edit): {annotations, revision}, or null when the lab has none.
async function builderMapDocument(labId){
 try{
  const doc=await(await api('/labs/'+encodeURIComponent(labId)+'/map-document')).json();
  return doc&&typeof doc.annotations==='string'&&doc.annotations.trim()?{annotations:doc.annotations,revision:doc.revision}:null;
 }catch{return null;}
}
// The same map document, read as data: key order and spacing do not make two documents different.
function builderMapCanon(value){if(Array.isArray(value))return value.map(builderMapCanon);if(value&&typeof value==='object'){const out={};for(const k of Object.keys(value).sort())out[k]=builderMapCanon(value[k]);return out;}return value;}
function builderMapSame(a,b){
 if((a||'')===(b||''))return true;
 try{return JSON.stringify(builderMapCanon(JSON.parse(a)))===JSON.stringify(builderMapCanon(JSON.parse(b)));}catch{return false;}
}
// The manager's document does not change on a deployed save, but the VM file's map does (a device added in the editor has its place only
// there). A device the file's map knows and the document does not keeps the file's entry (position, look); the manager's entries win.
function builderMapComplete(docText,fileText){
 if(!docText||!fileText||docText===fileText)return docText;
 try{
  const doc=JSON.parse(docText),file=JSON.parse(fileText);let added=false;
  if(!doc||typeof doc!=='object'||Array.isArray(doc)||!file||typeof file!=='object'||Array.isArray(file))return docText;
  for(const key of ['nodeAnnotations','networkNodeAnnotations']){
   if(!Array.isArray(file[key]))continue;
   const have=new Set((Array.isArray(doc[key])?doc[key]:[]).map(n=>n&&n.id));
   for(const entry of file[key])if(entry&&typeof entry.id==='string'&&!have.has(entry.id)){if(!Array.isArray(doc[key]))doc[key]=[];doc[key].push(entry);have.add(entry.id);added=true;}
  }
  return added?JSON.stringify(doc,null,2):docText;
 }catch{return docText;}
}
// Opening with #lab starts the next save from the manager's current map document. A draft whose own map is untouched (or that was told the
// map moved and reopened) takes the document and its revision. A draft with map edits of its own keeps them, and takes only the new revision
// when the document is still what the draft started from; otherwise it keeps a revision that is no longer current, so the manager refuses
// the save first and the person decides (Reopen or Download).
function builderAdoptMap(draft,doc){
 if(!doc||draft.mapRevision===doc.revision)return draft;
 const base=draftMapBaseline(draft),vmMap=(draft.vm&&draft.vm.annotations)||'',merged=builderMapComplete(doc.annotations,vmMap);
 if(builderMapSame(draft.annotations||'',base)||draft.mapStale)return draftWrite(builderStore,{...draft,annotations:merged,mapRevision:doc.revision,mapBase:merged,mapStale:undefined},draft.revision);
 if(builderMapSame(merged,base))return draftWrite(builderStore,{...draft,mapRevision:doc.revision},draft.revision);
 return {...draft,mapRevision:draft.mapRevision===undefined?'unknown':draft.mapRevision};
}
// The VM file changed since a draft with changes was made: nothing is decided for the person. Escape or × keeps both (the draft stays).
function builderOldDraft(draft,count){
 return new Promise(resolve=>{
  const dialog=opDialog('builder-old-draft','Your draft and the VM file differ',`<p>The topology on the VM changed since your draft was made, and ${count>1?count+' drafts of this lab in this browser have':'the draft has'} changes that are not on the VM.</p><p>Start from the VM version to work on the file as it is now: ${count>1?'those drafts are':'the draft is'} then removed from this browser. Continue your draft to keep your changes; saving then shows the differences. Download my draft first to keep a copy.</p><div class="dialog-actions"><button class="button secondary" id="builder-old-download">Download my draft</button><button class="button secondary" id="builder-old-continue">Continue my draft (from ${esc(builderDate(draft.updated))})</button><button class="button primary" id="builder-old-vm">Start from the VM version</button></div>`);
  let settled=false;const done=value=>{if(settled)return;settled=true;resolve(value);dialog.close();};
  $('builder-old-vm').onclick=()=>done('vm');$('builder-old-continue').onclick=()=>done('draft');$('builder-old-download').onclick=()=>builderDownloadDraft(draft);
  dialog.onclose=()=>done('draft');
  $('builder-old-continue').focus();   // the non-destructive choice: Enter never discards the draft
 });
}
async function builderOpenFromVm(path,labId=''){
 const found=await builderVmRead(path);if(!found)throw new Error('This topology file is no longer on the VM: '+path);
 const parsed=await json('/operations/parse-yaml','POST',{options:{text:found.yaml}});
 // With #lab the map is the manager's kept document; the VM file's map hash still goes in as the base of the stale check.
 const mapDoc=labId?await builderMapDocument(labId):null;
 // One draft per lab: the drafts that were saved to this path from this browser, or opened from it (newest first).
 // A draft with changes that are not on the VM comes first: it is the one that holds work.
 const drafts=draftList(builderStore).filter(d=>d.vm&&d.vm.path===path),dirty=drafts.filter(draftUnsaved),existing=dirty[0]||drafts[0]||null;
 // Keep working on the local draft only while it still descends from the version that is on the VM. Its
 // base takes the hashes the VM gave now (the page's own save knows the texts only).
 builderContinued='';
 if(existing&&builderSame(existing.vm,found)){
  if(dirty.includes(existing))builderContinued=existing.updated;
  return builderAdoptMap(existing.vm.hash===found.hash?existing:draftWrite(builderStore,{...existing,vm:{path,...found}},existing.revision),mapDoc);
 }
 if(dirty.length&&await builderOldDraft(existing,dirty.length)!=='vm'){builderContinued=existing.updated;return builderAdoptMap(existing,mapDoc);}
 for(const d of drafts)draftDelete(builderStore,d.id);draftDelete(builderStore,'vm:'+path);
 return draftWrite(builderStore,{id:'vm:'+path,name:parsed.name,root:path.slice(0,path.lastIndexOf('/')),yaml:found.yaml,annotations:mapDoc?builderMapComplete(mapDoc.annotations,found.annotations):found.annotations,vm:{path,...found},...(mapDoc?{mapRevision:mapDoc.revision,mapBase:builderMapComplete(mapDoc.annotations,found.annotations)}:{})},undefined);
}
// The manager's device catalog: the templates and the check's interface rules come from it. window.builderCatalog is the answer, or null
// when it did not load (the check's caption says so); the built-in templates stay the fallback.
async function builderCatalogLoad(){
 let answer=null;
 try{const v=await(await api('/catalog')).json();answer=v&&Array.isArray(v.entries)&&v.entries.length?v:null;}catch{answer=null;}
 builderCatalogAnswer=answer;if(typeof window!=='undefined')window.builderCatalog=answer;
 try{builderCheckStatus();}catch{}
 return answer;
}
// Undo and Redo: the editor's own, through the handle the adapter gives (shown only when it has them).
// A button that turns disabled while it holds focus would drop focus to the page: it goes to the other history button when that is on,
// else to the first enabled control of the bar.
function builderHistorySet(h){
 const undo=$('builder-undo'),redo=$('builder-redo'),active=typeof document!=='undefined'?document.activeElement:null;
 undo.disabled=!(h&&h.canUndo);redo.disabled=!(h&&h.canRedo);
 const lost=active&&[undo,redo].find(b=>b===active&&b.disabled);if(!lost)return;
 const other=lost===undo?redo:undo,target=!other.disabled&&!other.hidden?other:['builder-save','builder-yaml','builder-download','builder-drafts'].map($).find(b=>b&&!b.disabled&&!b.hidden);
 if(target&&typeof target.focus==='function')target.focus();
}
function builderHistoryWire(editor){
 builderEditor=editor;
 if(!$('builder-undo')||!$('builder-redo'))return;
 const can=!!editor&&typeof editor.undo==='function'&&typeof editor.redo==='function';
 for(const id of ['builder-undo','builder-redo'])$(id).hidden=!can;
 if(!can)return;
 builderHistorySet(null);
 if(typeof editor.subscribe==='function')editor.subscribe((yaml,annotations,history)=>builderHistorySet(history));
 if(typeof editor.history==='function')Promise.resolve().then(()=>editor.history()).then(builderHistorySet).catch(()=>{});
}
async function builderHistoryStep(step){
 if(!builderEditor||typeof builderEditor[step]!=='function')return;
 try{await builderEditor[step]();if(typeof builderEditor.history==='function')builderHistorySet(await builderEditor.history());}catch(e){notify((e&&e.message)||'The editor could not '+step+' that.');}
}
async function builderConnect(){
 try{builderCaps=await opCapabilities();builderCapsError='';}catch(e){builderCaps=null;builderCapsError=e.message;}
 builderRenderBar();
 // The VM's containerlab version picks the schema and the severities of the YAML check; the advice never blocks the page.
 try{if(typeof builderYamlContext==='function')builderYamlContext(builderCaps);builderCheckStatus();}catch{}
}
async function builderStart(){
 const params=new URLSearchParams(location.hash.slice(1));
 builderLabId=params.get('lab')||'';
 for(const [id,fn] of [['builder-save',()=>opTask(null,builderSave)],['builder-yaml',()=>builderYamlPanelToggle()],['builder-undo',()=>builderHistoryStep('undo')],['builder-redo',()=>builderHistoryStep('redo')],['builder-download',builderDownload],['builder-drafts',builderDraftsDialog],['builder-welcome-new',()=>builderNewDialog(params.get('root')||opBuilderRoot('',builderCaps?.roots))],['builder-welcome-drafts',builderDraftsDialog],['builder-drop-pick',()=>$('builder-drop-file').click()],['builder-problem-reload',()=>location.reload()],['builder-problem-download',builderDownload],['builder-problem-retry',builderStoreAgain],['builder-note-retry',()=>opTask(null,builderConnect)]])$(id).onclick=fn;
 builderDropWire();
 $('root').insertAdjacentHTML('afterend',builderYamlPanelMarkup());builderYamlPanelInit(builderYamlOptions(null));
 builderRenderBar();
 // The editor takes its device templates when it opens, and they carry the images this site already uses,
 // so the manager is asked first. A draft is in this browser: it opens even when the manager never answers.
 const asked=(async()=>{await refresh();[,builderKnown,builderVmImages]=await Promise.all([builderConnect(),api('/operations/known-images').then(r=>r.json()).then(v=>v.images||{}).catch(()=>({})),api('/operations/images').then(r=>r.json()).then(v=>Array.isArray(v.images)?v.images:[]).catch(()=>[]),builderCatalogLoad()]);})();
 await Promise.race([asked.catch(()=>{}),new Promise(done=>setTimeout(done,5000))]);
 const local=params.get('draft')?draftRead(builderStore,params.get('draft')):null;
 if(local)builderUse(local);else if(params.get('draft'))$('builder-welcome-message').textContent='That draft is not in this browser. Drafts stay in the browser they were made in: open a downloaded draft file, or start a new lab.';
 try{
  await asked;
  if(params.get('path'))builderUse(await builderOpenFromVm(params.get('path'),builderLabId));
  else if(!local&&params.get('root'))builderNewDialog(params.get('root'));
  await builderReconcile();
 }catch(e){if(builderDraft){builderCapsError=builderCapsError||e.message;}else $('builder-welcome-message').textContent=e.message;}
 builderRenderBar();
 // What applying would change, for a running lab: the pill and the line under the bar follow when it answers.
 const lab=builderLab();if(builderDraft&&lab&&builderLabRunning(lab))builderLabPlan(lab.id);
}
if(typeof document!=='undefined'&&document.addEventListener)document.addEventListener('DOMContentLoaded',builderStart);
// The map text a draft counts as unchanged against: what it opened with (the manager's document, completed from the VM file) or what
// it saved last; the VM file's own map text for a draft that took neither. The hash sent as base.annotations is always the VM file's.
function draftMapBaseline(draft){return draft.mapBase!==undefined?draft.mapBase:(draft.vm&&draft.vm.annotations)||'';}
function draftUnsaved(draft){return !!draft.vm&&(draft.vm.yaml!==draft.yaml||(draft.annotations||'')!==draftMapBaseline(draft));}
