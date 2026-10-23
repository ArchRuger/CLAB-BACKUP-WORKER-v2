'use strict';
let mapKey='', mapRequest=0, mapBounds=[0,0,1000,600], mapBox=[...mapBounds], mapLab='';
const map=$('topology-map');
const MAP_STATE_KEYS=['ready','starting','attention','unavailable','credentials','working','neutral'];
const mapPlural=(n,word)=>typeof plural==='function'?plural(n,word):`${n} ${word}${Number(n)===1?'':'s'}`;
// The one-line hint under the map: the fixed sentence, plus (only when they apply) the skipped-links
// and schema warnings that used to sit behind a "Details" toggle — a student cannot act on either, but
// they are worth a sentence, not a click.
const TOPOLOGY_HINT='Click a device to open it. Click a link to capture its traffic. Right-click for more actions.';
function setMapBox(){map.setAttribute('viewBox',mapBox.join(' '));}
function mapZoom(factor){const [x,y,w,h]=mapBox;if(w*factor<50||w*factor>400000)return;mapBox=[x+w*(1-factor)/2,y+h*(1-factor)/2,w*factor,h*factor];setMapBox();}
$('map-fit').onclick=()=>{mapBox=[...mapBounds];setMapBox();};
$('map-in').onclick=()=>mapZoom(.8);$('map-out').onclick=()=>mapZoom(1.25);
map.addEventListener('wheel',e=>{e.preventDefault();mapZoom(e.deltaY>0?1.15:1/1.15);},{passive:false});
let mapDrag=null;
map.addEventListener('pointerdown',e=>{if(e.button!==0)return;if(e.target.closest('[data-map-node],[data-capture-endpoints]'))return;mapDrag={x:e.clientX,y:e.clientY,box:[...mapBox]};map.setPointerCapture(e.pointerId);});
map.addEventListener('pointermove',e=>{if(!mapDrag)return;const rect=map.getBoundingClientRect(),scale=Math.max(mapDrag.box[2]/rect.width,mapDrag.box[3]/rect.height);mapBox=[mapDrag.box[0]-(e.clientX-mapDrag.x)*scale,mapDrag.box[1]-(e.clientY-mapDrag.y)*scale,...mapDrag.box.slice(2)];setMapBox();});
for(const event of ['pointerup','pointercancel','lostpointercapture'])map.addEventListener(event,()=>mapDrag=null);
// Left-click, Enter and Space on a matched device open the device panel; unmatched devices carry no
// data-map-node and stay non-interactive (their <title> says why).
function mapAction(e){const node=e.target.closest('[data-map-node]');if(node?.dataset.mapNode)openDetails(node.dataset.mapNode);}
map.addEventListener('click',mapAction);map.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();mapAction(e);}});
// Device state on the map. deviceState() (status.js) decides the words; here the state-* class of each
// drawn device is swapped on the 4 s poll with classList, never by rebuilding the SVG, so zoom, focus
// and an open context menu survive. Every device of a lab with an operation in progress reads as
// "working" until it accepts a login again.
function mapDeviceState(n){return typeof deviceState==='function'?deviceState(n):{key:n.ssh_ready?'ready':'neutral',label:n.ssh_ready?'Ready':'',detail:'',pill:n.ssh_ready?'ok':'neutral'};}
function mapStateKey(n,lab){
 const ds=mapDeviceState(n);let key=MAP_STATE_KEYS.includes(ds.key)?ds.key:'neutral';
 // A lab-wide operation puts every device that is not ready to "working"; Restart device names its one
 // device (job.node), and the other devices keep their own state.
 if(!n.ssh_ready&&typeof labStateOf==='function'){const ls=labStateOf(lab);if(ls.key==='working'&&(!ls.job?.node||ls.job.node===n.name))key='working';}
 return {key,ds};
}
function renderMapState(){
 renderRailTest();
 const lab=typeof current==='function'?current():null;if(!lab||!map||typeof map.querySelectorAll!=='function')return 0;
 let updated=0;
 for(const el of map.querySelectorAll('[data-map-node]')){
  const n=(lab.nodes||[]).find(n=>n.name===el.dataset.mapNode);if(!n)continue;
  const {key,ds}=mapStateKey(n,lab),label=el.dataset.label||n.short_name||n.name,ready=ds.key==='ready'||!ds.label;
  if(!el.classList.contains('state-'+key)){for(const k of MAP_STATE_KEYS)el.classList.remove('state-'+k);el.classList.add('state-'+key);updated++;}
  const name=ready?label:`${label} · ${ds.label}`;
  if(el.getAttribute('aria-label')!==name)el.setAttribute('aria-label',name);
  const title=typeof el.querySelector==='function'?el.querySelector('title'):null,text=ready?`${label} — click to open, right-click for more actions`:`${label} · ${ds.label}. ${ds.detail||''}`.trim();
  if(title&&title.textContent!==text)title.textContent=text;
 }
 return updated;
}
function applyMapStates(){return renderMapState();}
// Impairments on the map (C05 4.3): a class on the wire group (style.css strokes only paths that are not the capture hit area), the
// end and its values in the wire's title and aria-label, and a caption that counts wires. Re-applied after every map render from the
// cached answer, so a re-render never drops the badge until the next fetch.
function mapWireEnds(group){
 try{const value=JSON.parse(group.getAttribute('data-capture-endpoints')||'[]');return Array.isArray(value)?value:[];}catch{return [];}
}
function mapWireImpairedText(group,text){
 // C06's mapWireText(group) composes the title and aria-label from a base plus clauses; without it the clause is appended here.
 if(text)group.setAttribute('data-impaired-text',text);else group.removeAttribute('data-impaired-text');
 if(typeof mapWireText==='function'){mapWireText(group);return;}
 const title=typeof group.querySelector==='function'?group.querySelector('title'):null;
 if(group.getAttribute('data-base-label')===null)group.setAttribute('data-base-label',group.getAttribute('aria-label')||'');
 if(title&&group.getAttribute('data-base-title')===null)group.setAttribute('data-base-title',title.textContent);
 const baseLabel=group.getAttribute('data-base-label'),baseTitle=group.getAttribute('data-base-title');
 if(title&&baseTitle!==null)title.textContent=text?baseTitle+' · '+text:baseTitle;
 group.setAttribute('aria-label',text?baseLabel+' · '+text:baseLabel);
}
// One composition point for a wire's words (C06 3.0): <title> is the renderer's data-base plus the clauses, aria-label is its
// data-aria-base ("Capture a:if to b:if") plus the same clauses. The clauses are two optional attributes: data-state-text (map-tools.js,
// link state) and data-impaired-text (renderMapImpairments above). Either feature writes its attribute and calls this; neither rewrites
// the other's words. Returns the title text.
function mapWireText(group){
 const title=typeof group.querySelector==='function'?group.querySelector('title'):null;
 if(group.getAttribute('data-base')===null)group.setAttribute('data-base',title?title.textContent:'');
 if(group.getAttribute('data-aria-base')===null)group.setAttribute('data-aria-base',group.getAttribute('aria-label')||'');
 const clauses=[group.getAttribute('data-state-text'),group.getAttribute('data-impaired-text')].filter(Boolean);
 const text=[group.getAttribute('data-base'),...clauses].join(' · ');
 if(title&&title.textContent!==text)title.textContent=text;
 const aria=[group.getAttribute('data-aria-base'),...clauses].join(' · ');
 if(group.getAttribute('aria-label')!==aria)group.setAttribute('aria-label',aria);
 return text;
}
function renderMapImpairments(answer){
 if(!map||typeof map.querySelectorAll!=='function'||typeof impairedWires!=='function')return 0;
 if(answer===undefined)answer=typeof opImpairmentCache!=='undefined'&&typeof activeId==='string'?opImpairmentCache[activeId]:null;
 const groups=[...map.querySelectorAll('.topology-wire')];
 const hits=impairedWires(groups.map(g=>({ends:mapWireEnds(g)})),answer&&answer.devices);
 const byIndex=new Map(hits.map(h=>[h.index,h]));
 groups.forEach((group,index)=>{
  const hit=byIndex.get(index);
  group.classList.toggle('impaired',!!hit);
  const text=hit?hit.text:'';
  if((group.getAttribute('data-impaired-text')||'')!==text||(!text&&group.getAttribute('data-base-title')!==null))mapWireImpairedText(group,text);
 });
 const interfaces=answer&&Number.isInteger(answer.interfaces)?answer.interfaces:hits.reduce((sum,h)=>sum+h.ends.length,0);
 const caption=$('map-impaired'),clear=$('map-impaired-clear');
 const counted=hits.length?mapPlural(hits.length,'link')+' impaired':interfaces?mapPlural(interfaces,'interface')+' impaired':'';
 const text=counted?counted+(answer&&answer.complete===false?' · some devices not read':''):(answer&&answer.complete===false?'Impairments: some devices not read':'');
 if(caption){caption.textContent=text;caption.hidden=!text;caption.title=counted?mapPlural(interfaces,'interface')+' with an impairment':'';}
 if(clear){clear.hidden=!interfaces;}
 return hits.length;
}
// "Test logins": a lab-wide SSH login refresh beside the Devices heading — the rail's sticky h2 and
// the Devices tab heading both carry it (node_services.py POST …/ssh-check-all). It only starts real
// login tests and never marks a device ready by itself: deviceState()'s 'checking' pill and the
// existing 4 s poll are what move a device on to Ready once it actually answers, or back to its
// previous reason when it does not. Both buttons mirror whichever check is really running, derived
// from the lab's own devices, so a check started from the other button, another browser tab or the
// automatic monitor's own probe disables them too.
function railTestButtons(){return ['rail-test-logins','devices-test-logins'].map(id=>$(id)).filter(Boolean);}
function railTestActive(lab){return (lab&&lab.nodes||[]).some(n=>n.nos_login&&n.nos_login.status==='checking');}
function renderRailTest(){
 const active=railTestActive(typeof current==='function'?current():null);
 for(const button of railTestButtons()){button.disabled=active;button.textContent=active?'Testing…':'Test logins';}
 return active;
}
async function runRailTest(){
 const lab=typeof current==='function'?current():null;if(!lab||typeof json!=='function')return;
 for(const button of railTestButtons()){button.disabled=true;button.textContent='Testing…';}
 try{
  const result=await json('/labs/'+lab.id+'/ssh-check-all','POST',{});
  const started=(result&&result.started)||0,skipped=(result&&result.skipped)||[];
  if(typeof notify==='function')notify(started?`Testing the SSH login of ${mapPlural(started,'device')}…`+(skipped.length?` ${mapPlural(skipped.length,'device')} skipped — see each device for why.`:''):'No device is ready to test right now. Add credentials under Devices first.');
 }catch(e){if(typeof notify==='function')notify(e.message);}
 if(typeof refresh==='function')await refresh().catch(()=>{});
 renderRailTest();
}
for(const id of ['rail-test-logins','devices-test-logins'])if($(id))$(id).onclick=runRailTest;
const nodeMenu=$('node-context-menu');let contextLab='',contextNode=null;
function closeNodeMenu(restore=false){nodeMenu.hidden=true;if(restore)contextNode?.focus();contextNode=null;}
function nodeMenuReason(text){return text?`<small>${esc(text)}</small>`:'';}
// Why Back up configuration is unavailable, in the student's words (readiness is backup eligibility).
function nodeBackupReason(n){
 if(busy())return 'Another task is running';
 if(n.readiness==='Ready')return '';
 return n.readiness==='Needs credentials'?'Add credentials first':n.readiness==='Choose NOS'?'Choose the network OS first':n.readiness==='Lab unavailable'?'The lab is not running':'Not available right now';
}
// Stop device and Start device beside Restart device: the same eligibility function the Devices table and the device panel ask.
function nodeMenuAction(action,label,n,danger){
 if(typeof opNodeActionState!=='function')return '';
 const check=opNodeActionState(action,current(),n,state.discovery,busy());
 return `<button type="button" role="menuitem" data-node-action="${esc(action)}" data-node="${esc(n.name)}"${danger?' class="danger"':''} ${check.ok?'':`disabled title="${esc(check.reason)}"`}>${esc(label)}${check.ok?'':nodeMenuReason(check.reason)}</button>`;
}
// The right-click menu: the device's state in the header (its address stays in the device panel), the
// actions in the order students use them, and a visible reason under every disabled item.
function openNodeMenu(element,x,y){
 const n=current()?.nodes.find(n=>n.name===element.dataset.mapNode);if(!n)return;
 contextLab=activeId;contextNode=element;
 const ds=mapDeviceState(n),captureAttrs=typeof captureActionAttrs==='function'?captureActionAttrs():'',captureOff=/\bdisabled\b/.test(captureAttrs),backupReason=nodeBackupReason(n);
 // Restart device (one node, operations.js): the same eligibility the Devices view uses, with its reason.
 const restart=typeof opRestartState==='function'?opRestartState(current(),n,state.discovery,busy()):{ok:false,reason:'Not available on this page'};
 const consoleItem=typeof consoleState==='function'?consoleState(n):{offered:false};
 nodeMenu.innerHTML=`<div class="context-node-name">${esc(n.short_name||n.name)}<span class="pill ${esc(ds.pill||'neutral')}">${esc(ds.label)}</span></div>`
 +`<button type="button" role="menuitem" data-terminal="${esc(n.name)}" ${n.ssh_ready?'':`disabled title="${esc(ds.detail)}"`}>Open CLI <span class="external" aria-hidden="true">↗</span>${n.ssh_ready?'':nodeMenuReason(ds.detail)}</button>`
 +(consoleItem.offered?`<button type="button" role="menuitem" data-console="${esc(n.name)}" ${consoleItem.ok?'':`disabled title="${esc(consoleItem.reason)}"`}>Console <span class="external" aria-hidden="true">↗</span>${consoleItem.ok?'':nodeMenuReason(consoleItem.reason)}</button>`:'')
 +`<button type="button" role="menuitem" data-capture="${esc(n.name)}" ${captureAttrs}>Capture traffic…${captureOff?nodeMenuReason('Packet capture isn’t set up on this VM yet — see Tools › Packet capture.'):''}</button>`
 +`<button type="button" role="menuitem" data-backup="${esc(n.name)}" ${backupReason?`disabled title="${esc(backupReason)}"`:''}>Back up configuration${nodeMenuReason(backupReason)}</button>`
 +`<button type="button" role="menuitem" data-restart="${esc(n.name)}" class="danger" ${restart.ok?'':`disabled title="${esc(restart.reason)}"`}>Restart device…${restart.ok?'':nodeMenuReason(restart.reason)}</button>`
 +nodeMenuAction('stop-node','Stop device…',n,true)+nodeMenuAction('start-node','Start device…',n,false)
 +`<button type="button" role="menuitem" data-details="${esc(n.name)}">Device details</button>`;
 nodeMenu.hidden=false;nodeMenu.style.left=Math.max(8,Math.min(x,window.innerWidth-nodeMenu.offsetWidth-8))+'px';nodeMenu.style.top=Math.max(8,Math.min(y,window.innerHeight-nodeMenu.offsetHeight-8))+'px';nodeMenu.querySelector('button:not(:disabled)')?.focus();
}
map.addEventListener('contextmenu',e=>{const element=e.target.closest('[data-map-node]');if(!element)return;e.preventDefault();openNodeMenu(element,e.clientX,e.clientY);});
map.addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){const element=e.target.closest('[data-map-node]');if(element){e.preventDefault();const rect=element.getBoundingClientRect();openNodeMenu(element,rect.right,rect.top);}}});
nodeMenu.addEventListener('click',e=>{if(contextLab!==activeId){closeNodeMenu();return;}handleNodeAction(e);closeNodeMenu();});
nodeMenu.addEventListener('keydown',e=>{const buttons=[...nodeMenu.querySelectorAll('button:not(:disabled)')];if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const i=buttons.indexOf(document.activeElement);buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();}});
document.addEventListener('pointerdown',e=>{if(!nodeMenu.contains(e.target))closeNodeMenu();});
// Escape order: the node menu first; shell.js closes any open menu before this handler runs (and stops
// the event); only then does Escape leave the expanded map.
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;if(!nodeMenu.hidden){closeNodeMenu(true);return;}if(typeof closeMenus==='function'&&closeMenus())return;setMapExpanded(false);});
window.addEventListener('resize',()=>closeNodeMenu());window.addEventListener('blur',()=>closeNodeMenu());
document.addEventListener('scroll',()=>closeNodeMenu(),true);
function setMapExpanded(expanded){
 const view=$('topology-view'),button=$('map-expand');if(!view)return false;
 view.classList.toggle('map-expanded',expanded);
 if(button)button.textContent=expanded?'Close expanded map':(button.dataset&&button.dataset.label)||'Expand';
 return expanded;
}
$('map-expand').onclick=()=>{setMapExpanded(!$('topology-view').classList.contains('map-expanded'));closeNodeMenu();};
// The stage shows one of: the loading skeleton (first fetch for a lab), the empty state (no map
// imported) or the map. Map tools only work with a map; the proxies mirror the reason.
function mapStage(kind){
 if($('map-loading'))$('map-loading').hidden=kind!=='loading';
 if($('map-empty'))$('map-empty').hidden=kind!=='empty';
 map.hidden=kind!=='map';
 const off=kind!=='map';
 for(const id of ['map-fit','map-in','map-out','map-expand'])if($(id)){$(id).disabled=off;$(id).title=off?'No map yet':'';}
 if($('map-edit')){$('map-edit').disabled=off;$('map-edit').title=off?'Import a map first.':'';}
 // C06: Find, the three map-tool menu items (each with its visible reason) and the chips follow the stage.
 if($('map-find')){$('map-find').disabled=off;$('map-find').title=off?'No map yet':'Name, address or platform';}
 for(const id of ['map-picture','map-drawio-export','map-arrange']){const el=$(id);if(!el)continue;el.disabled=off;el.title=off?'No map yet':'';const small=typeof el.querySelector==='function'?el.querySelector('.menu-reason'):null;if(small){small.textContent=off?'No map yet':'';small.hidden=!off;}}
 if(off){for(const id of ['map-links','map-find-count','map-link-hover'])if($(id))$(id).hidden=true;}else if($('map-links'))$('map-links').hidden=false;
 if(off&&$('topology-hint'))$('topology-hint').textContent=TOPOLOGY_HINT;
 if(typeof syncProxies==='function')syncProxies();
}
// Caption under the map in plain words; anything a student cannot act on goes into the hint (see above).
function mapCaption(drawing){
 const unmatched=drawing.nodes.filter(n=>!n.inventory_name).length,devices=drawing.nodes.length-unmatched;
 let text=`${mapPlural(devices,'device')} · ${mapPlural(drawing.links.length,'link')}`;
 if(unmatched)text+=` · ${unmatched} drawn but not in this lab`;
 if(!drawing.has_links_source)text+='. Links aren’t shown yet — import the lab topology file with the map to draw them.';
 const notes=[];
 if(drawing.skipped_links)notes.push(`${mapPlural(drawing.skipped_links,'link')} could not be drawn (unsupported or one-ended).`);
 if(drawing.schema!==3)notes.push('Some map styling and port labels could not be shown. Re-import the original map files to restore them.');
 return {text,notes};
}
async function refreshMap(force=false){
 const labId=activeId,request=++mapRequest;if(!labId)return;
 // C06: re-check the link-state run conditions on every visit and render, before the unchanged-drawing early return (idempotent; it fetches nothing itself).
 if(typeof mapLinkSchedule==='function')mapLinkSchedule();
 if(mapLab!==labId){mapLab=labId;mapKey='';mapStage('loading');$('map-status').textContent='';}
 try{const drawing=await(await api('/labs/'+labId+'/topology')).json();if(request!==mapRequest||activeId!==labId)return;
 const key=labId+JSON.stringify(drawing);if(!force&&key===mapKey)return;
 // A hidden panel (a map imported or saved from another tab, or a tab switched during the fetch) cannot be measured: getBBox() answers an empty box. Leave the key unset so showTab() renders and measures on the next visit.
 if($('topology-view')?.hidden){mapKey='';return;}
 mapKey=key;closeNodeMenu();
 if(!drawing){map.innerHTML='';$('map-status').textContent='';mapStage('empty');if(typeof mapToolsRendered==='function')mapToolsRendered(null);return;}
 mapStage('map');
 const caption=mapCaption(drawing);$('map-status').textContent=caption.text;
 if($('topology-hint'))$('topology-hint').textContent=caption.notes.length?TOPOLOGY_HINT+' '+caption.notes.join(' '):TOPOLOGY_HINT;
 map.innerHTML=topologyMarkup(drawing);
 map.classList.toggle('labels-on-select',drawing.settings?.labelMode==='on-select');
 mapBounds=measureTopology(map);mapBox=[...mapBounds];setMapBox();
 renderMapState();renderMapImpairments();
 if(typeof mapToolsRendered==='function')mapToolsRendered(drawing);
 }catch(e){if(request===mapRequest){if($('map-loading'))$('map-loading').hidden=true;$('map-status').textContent='The map could not be loaded. '+e.message;}}
}
$('import-map').onclick=()=>{$('map-form').reset();$('map-form').querySelector('.form-error').textContent='';$('map-dialog').showModal();};
$('cancel-map').onclick=()=>$('map-dialog').close();
$('map-form').addEventListener('submit',e=>{e.preventDefault();const labId=activeId;withForm(e.currentTarget,async()=>{await api('/labs/'+labId+'/topology',{method:'POST',body:new FormData(e.currentTarget)});$('map-dialog').close();if(activeId===labId)await refreshMap(true);notify('Map imported.');});});
$('export-sessions').onclick=()=>{$('export-form').reset();$('export-form').querySelector('.form-error').textContent='';$('export-dialog').showModal();};
$('cancel-export').onclick=()=>$('export-dialog').close();
$('export-form').addEventListener('submit',e=>{e.preventDefault();const labId=activeId;withForm(e.currentTarget,async()=>{const response=await api('/labs/'+labId+'/superputty',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({include_passwords:$('export-passwords').checked})});const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=attachmentName(response,'sessions.xml');a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('export-dialog').close();});});
