'use strict';
// map-editor-page.js — Edit map: the lab builder's editor over the map of a lab that is already in My labs.
// The adapter (lab-builder/src/main.tsx) runs the editor in its view mode with `mapOnly`, refuses every
// command that is not annotation-only and hands each settled state to persist(). This page only ever
// sends the annotations document to PUT /api/labs/<id>/map-document; it cannot send a topology, and it
// has no route to the VM, to deployment or to the builder's drafts.
const $=id=>document.getElementById(id);
let mapLab='',mapDoc=null,mapBaseline=null,mapCurrent='',mapMount=null,mapMounted=false,mapSaving=false,mapPaused=false,toastTimer;
// Undo / redo belong to the page: the editor has none in its view mode. mapEditor is the adapter's handle for
// putting a whole document into the running editor; mapApplying marks the persist() that such a step causes.
let mapEditor=null,mapApplying=false,mapHistory={entries:[],index:-1,at:0};
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6000);}
async function api(path,options={}){
 let response;try{response=await fetch('/api'+path,options);}catch{throw Object.assign(new Error('The manager did not answer. Check that it is running, then try again.'),{network:true});}
 if(!response.ok){let detail='';try{detail=(await response.json()).detail;}catch{detail='';}throw Object.assign(new Error(typeof detail==='string'&&detail?detail:'The manager answered '+response.status+'.'),{status:response.status});}
 return response;
}
// Pure helpers (tests/test_map_editor_ui.js)
function mapLabFromHash(hash){const id=new URLSearchParams(String(hash||'').replace(/^#/,'')).get('lab')||'';return /^[A-Za-z0-9_-]{1,64}$/.test(id)?id:'';}
function mapBackUrl(id){return id?'/#lab='+encodeURIComponent(id)+'&view=topology':'/';}
function mapIsDirty(baseline,current){return baseline!==null&&current!==baseline;}
function mapFileName(name){return (String(name||'lab').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/^[ .]+|[ .]+$/g,'')||'lab').slice(0,150)+'.clab.yaml.annotations.json';}
function mapStatusView(state){return state.paused?{text:'Editing paused',pill:'bad'}:state.saving?{text:'Saving…',pill:'busy'}:state.dirty?{text:'Unsaved changes',pill:'warn'}:{text:'Saved in the manager',pill:'ok'};}
// What a map file must be before it may replace the map: one JSON object of at most 1 MiB with an annotations key.
function mapImportProblem(name,text){
 if(!/\.json$/i.test(name||''))return 'Choose a map file. Its name ends in .annotations.json.';
 if(!text.trim())return 'This file is empty.';
 if(text.length>1024*1024)return 'This file is larger than 1 MiB, which is more than a map file can be.';
 let data;try{data=JSON.parse(text);}catch{return 'This file is not valid JSON, so it is not a map file.';}
 if(!data||typeof data!=='object'||Array.isArray(data)||!['nodeAnnotations','networkNodeAnnotations','freeTextAnnotations','groupStyleAnnotations','freeShapeAnnotations'].some(key=>key in data))return 'This JSON file is not a containerlab map file (.annotations.json).';
 return '';
}
// The history of the annotations document, as a value (pure; tests drive it directly). A new state drops what
// could have been redone. States that follow each other within MAP_HISTORY_MERGE ms are one step (typing in
// a text, a drag that settles twice); the step that Undo returns to is never overwritten that way.
const MAP_HISTORY_LIMIT=60,MAP_HISTORY_MERGE=700;
function mapHistoryPush(history,text,now){
 const entries=history.entries.slice(0,history.index+1);
 if(entries.length&&entries[entries.length-1]===text)return {...history,entries,index:entries.length-1};
 const merge=entries.length>1&&history.index===history.entries.length-1&&history.merged!==false&&now-history.at<MAP_HISTORY_MERGE;
 if(merge)entries[entries.length-1]=text;else entries.push(text);
 while(entries.length>MAP_HISTORY_LIMIT)entries.shift();
 return {entries,index:entries.length-1,at:now};
}
function mapHistoryStep(history,delta){const index=history.index+delta;return index<0||index>=history.entries.length?null:{...history,index,at:0,merged:false};}
// The device look: how a device is drawn, which the editor keeps in the device's nodeAnnotations entry. The
// editor's own form for it belongs to its topology editing (not offered in Edit map), so the page has one.
// Values are the editor's (its NODE_TYPE_SET, NODE_LABEL_POSITION_OPTIONS, NODE_DIRECTION_OPTIONS).
const MAP_ICONS=[['pe','Router'],['dcgw','Gateway router'],['leaf','Leaf switch'],['spine','Spine switch'],['super-spine','Super-spine switch'],['switch','Switch'],['bridge','Bridge'],['server','Server'],['client','Client'],['controller','Controller'],['cloud','Cloud'],['pon','PON'],['rgw','Residential gateway'],['ue','User equipment']];
const MAP_LABEL_POSITIONS=[['bottom','Below the icon'],['top','Above the icon'],['left','Left of the icon'],['right','Right of the icon']];
const MAP_LABEL_DIRECTIONS=[['right','Horizontal'],['down','Rotated 90°'],['left','Rotated 180°'],['up','Rotated 270°']];
const MAP_LOOK_KEYS=['icon','iconColor','iconCornerRadius','labelPosition','direction','labelBackgroundColor'];
function mapLookDevices(text){let data;try{data=JSON.parse(text);}catch{return [];}return (Array.isArray(data&&data.nodeAnnotations)?data.nodeAnnotations:[]).filter(n=>n&&typeof n.id==='string'&&n.id).map(n=>({id:n.id,label:typeof n.label==='string'&&n.label?n.label:n.id,look:Object.fromEntries(MAP_LOOK_KEYS.filter(k=>n[k]!==undefined&&n[k]!=='').map(k=>[k,n[k]]))}));}
// A look as the form gives it, checked against what the editor accepts; '' or undefined means "the default".
function mapLookClean(look){
 const out={},color=v=>typeof v==='string'&&/^#[0-9a-f]{6}$/i.test(v);
 if(look.icon){if(!MAP_ICONS.some(([id])=>id===look.icon))throw new Error('Choose one of the listed icons.');out.icon=look.icon;}
 if(look.iconColor){if(!color(look.iconColor))throw new Error('The icon colour is not a colour.');out.iconColor=look.iconColor.toLowerCase();}
 if(look.iconCornerRadius!==''&&look.iconCornerRadius!==undefined&&look.iconCornerRadius!==null){const r=Number(look.iconCornerRadius);if(!Number.isInteger(r)||r<0||r>20)throw new Error('The corner radius is a whole number from 0 to 20.');out.iconCornerRadius=r;}
 if(look.labelPosition){if(!MAP_LABEL_POSITIONS.some(([id])=>id===look.labelPosition))throw new Error('Choose one of the listed label positions.');out.labelPosition=look.labelPosition;}
 if(look.direction){if(!MAP_LABEL_DIRECTIONS.some(([id])=>id===look.direction))throw new Error('Choose one of the listed text directions.');out.direction=look.direction;}
 if(look.labelBackgroundColor){if(look.labelBackgroundColor!=='transparent'&&!color(look.labelBackgroundColor))throw new Error('The label background is not a colour.');out.labelBackgroundColor=look.labelBackgroundColor.toLowerCase();}
 return out;
}
// The document with one device's look replaced. Only that entry's six look keys change: its id, position,
// group and every other key, every other entry and every other part of the document stay as they are.
function mapApplyLook(text,id,look){
 const data=JSON.parse(text),clean=mapLookClean(look);
 if(!data||typeof data!=='object'||Array.isArray(data))throw new Error('The map document is not readable.');
 const entry=(Array.isArray(data.nodeAnnotations)?data.nodeAnnotations:[]).find(n=>n&&n.id===id);
 if(!entry)throw new Error('This device is not on the map.');
 for(const key of MAP_LOOK_KEYS){if(clean[key]===undefined)delete entry[key];else entry[key]=clean[key];}
 return JSON.stringify(data,null,2);
}
// A link's own label distance: the editor keeps it in edgeAnnotations, found by the link's endpoints in the
// topology's order (its buildEdgeKey), and clamps it to 0–60. Its own form for it is topology editing.
function mapLinkKey(link){return [link.source,link.sourceEndpoint||'',link.target,link.targetEndpoint||''].join('|');}
function mapLinkLabel(link){return link.source+':'+(link.sourceEndpoint||'?')+'  ↔  '+link.target+':'+(link.targetEndpoint||'?');}
// links: the manager's drawing, [[{node,interface},{node,interface}], …] in the topology's order.
function mapLinks(links,text){
 let data;try{data=JSON.parse(text);}catch{data={};}
 const stored=new Map((Array.isArray(data&&data.edgeAnnotations)?data.edgeAnnotations:[]).filter(e=>e&&typeof e==='object').map(e=>[mapLinkKey(e),e]));
 return (links||[]).filter(pair=>Array.isArray(pair)&&pair.length===2&&pair.every(end=>end&&typeof end.node==='string')).map(pair=>{
  const link={source:pair[0].node,sourceEndpoint:pair[0].interface||'',target:pair[1].node,targetEndpoint:pair[1].interface||''},entry=stored.get(mapLinkKey(link));
  return {...link,own:!!entry&&entry.endpointLabelOffsetEnabled===true,offset:entry&&Number.isFinite(entry.endpointLabelOffset)?entry.endpointLabelOffset:20};
 });
}
function mapApplyLinkOffset(text,link,own,offset){
 const data=JSON.parse(text);if(!data||typeof data!=='object'||Array.isArray(data))throw new Error('The map document is not readable.');
 const value=String(offset??'').trim()===''?NaN:Number(offset);if(own&&(!Number.isInteger(value)||value<0||value>60))throw new Error('The distance is a whole number from 0 to 60.');
 const list=Array.isArray(data.edgeAnnotations)?data.edgeAnnotations:[],key=mapLinkKey(link),at=list.findIndex(e=>e&&typeof e==='object'&&mapLinkKey(e)===key);
 if(own){const entry={...(at>=0?list[at]:{source:link.source,sourceEndpoint:link.sourceEndpoint,target:link.target,targetEndpoint:link.targetEndpoint}),endpointLabelOffsetEnabled:true,endpointLabelOffset:value};if(at>=0)list[at]=entry;else list.push(entry);}
 else if(at>=0){const {endpointLabelOffsetEnabled:_e,endpointLabelOffset:_o,...rest}=list[at];if(Object.keys(rest).every(k=>['id','source','target','sourceEndpoint','targetEndpoint'].includes(k)))list.splice(at,1);else list[at]=rest;}
 if(list.length||Array.isArray(data.edgeAnnotations))data.edgeAnnotations=list;
 return JSON.stringify(data,null,2);
}
function mapDirty(){return mapIsDirty(mapBaseline,mapCurrent);}
async function mapTravel(delta){
 const next=mapHistoryStep(mapHistory,delta);if(!next||!mapEditor||mapApplying||mapSaving||mapPaused)return false;
 mapApplying=true;mapRenderBar();
 try{await mapEditor.applyAnnotations(next.entries[next.index]);mapHistory=next;return true;}
 catch(error){notify((delta<0?'Undo':'Redo')+' did not work: '+error.message);return false;}
 finally{mapApplying=false;mapRenderBar();}
}
function mapRenderBar(){
 const ready=mapMounted&&!mapPaused,view=mapStatusView({paused:mapPaused,saving:mapSaving,dirty:mapDirty()});
 $('map-status').textContent=mapDoc?view.text:'';$('map-status').className='pill '+view.pill;$('map-status').hidden=!mapDoc;
 $('map-save').disabled=!ready||mapSaving||!mapDirty();$('map-save').title=!ready?'':mapDirty()?'':'There is nothing to save.';
 $('map-download').disabled=!mapDoc;$('map-import').disabled=!ready||mapSaving;
 const steady=ready&&!mapSaving&&!mapApplying&&!!mapEditor;
 $('map-look').disabled=!steady;$('map-link').disabled=!steady;
 $('map-undo').disabled=!steady||mapHistory.index<=0;$('map-redo').disabled=!steady||mapHistory.index>=mapHistory.entries.length-1;
 $('map-drawio').disabled=!ready;$('map-drawio').title=mapDirty()?'The export is made from the saved map: save first.':'';
}
function mapProblem(message){mapPaused=true;$('root').inert=true;$('builder-problem-text').textContent=message;$('builder-problem').hidden=false;mapRenderBar();}
function mapDownload(){const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([mapCurrent||mapDoc.annotations],{type:'application/json'}));link.download=mapFileName(mapDoc.name);document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000);}
async function mapSave(){
 if(!mapDoc||mapSaving||mapPaused||!mapDirty())return false;
 mapSaving=true;mapRenderBar();const sent=mapCurrent;
 try{
  const result=await(await api('/labs/'+encodeURIComponent(mapLab)+'/map-document',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({annotations:sent,revision:mapDoc.revision})})).json();
  mapDoc={...mapDoc,annotations:sent,revision:result.revision};mapBaseline=sent;notify('Map saved. The lab’s Topology tab shows it.');return true;
 }catch(error){
  // Nothing was saved. A 409 means the map changed elsewhere (another tab, a sync): the student keeps this version as a file.
  notify(error.status===409?error.message+' Download this map if you want to keep it, then reload.':'The map was not saved: '+error.message);return false;
 }finally{mapSaving=false;mapRenderBar();}
}
function mapLeave(){if(!mapDirty()||mapPaused){location.assign(mapBackUrl(mapLab));return;}$('map-leave').showModal();}
async function mapImport(){
 const file=$('map-import-file').files&&$('map-import-file').files[0],error=$('map-import-error');error.textContent='';
 if(!file){error.textContent='Choose a file first.';return;}
 const text=await file.text(),problem=mapImportProblem(file.name,text);if(problem){error.textContent=problem;return;}
 try{await api('/labs/'+encodeURIComponent(mapLab)+'/map-document',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({annotations:text,revision:mapDoc.revision})});}
 catch(e){error.textContent='The map was not replaced: '+e.message;return;}
 mapBaseline=mapCurrent;location.reload();
}
function mapLookFill(){
 const devices=mapLookDevices(mapCurrent),chosen=$('map-look-device').value,device=devices.find(d=>d.id===chosen)||devices[0];if(!device)return;
 const look=device.look,bg=look.labelBackgroundColor||'';
 $('map-look-device').value=device.id;$('map-look-icon').value=look.icon||'';$('map-look-radius').value=look.iconCornerRadius??'';
 $('map-look-color').value=look.iconColor||'#0066ff';$('map-look-color-default').checked=!look.iconColor;$('map-look-color').disabled=!look.iconColor;
 $('map-look-bg-transparent').checked=bg==='transparent';$('map-look-bg-default').checked=!bg;$('map-look-bg').value=bg&&bg!=='transparent'?bg:'#454545';$('map-look-bg').disabled=!bg||bg==='transparent';
 $('map-look-position').value=look.labelPosition||'';$('map-look-direction').value=look.direction||'';$('map-look-error').textContent='';
}
function mapLookOpen(){
 const devices=mapLookDevices(mapCurrent);if(!devices.length){notify('This map has no devices to style.');return;}
 const options=(list,blank)=>(blank?'<option value="">'+blank+'</option>':'')+list.map(([id,label])=>'<option value="'+id+'">'+label+'</option>').join('');
 $('map-look-icon').innerHTML=options(MAP_ICONS,'Default (by the kind of device)');$('map-look-position').innerHTML=options(MAP_LABEL_POSITIONS,'Default (below the icon)');$('map-look-direction').innerHTML=options(MAP_LABEL_DIRECTIONS,'Default (horizontal)');
 const select=$('map-look-device');select.replaceChildren(...devices.map(d=>{const o=document.createElement('option');o.value=d.id;o.textContent=d.label===d.id?d.id:d.label+' ('+d.id+')';return o;}));
 // The device selected on the canvas, when there is one
 const picked=document.querySelector('.react-flow__node-topology-node.selected'),id=picked&&(picked.getAttribute('data-id')||String(picked.getAttribute('data-testid')||'').replace(/^rf__node-/,''));
 if(id&&devices.some(d=>d.id===id))select.value=id;
 mapLookFill();$('map-look-dialog').showModal();
}
async function mapLookApply(){
 const error=$('map-look-error');error.textContent='';
 const bg=$('map-look-bg-transparent').checked?'transparent':$('map-look-bg-default').checked?'':$('map-look-bg').value;
 const look={icon:$('map-look-icon').value,iconColor:$('map-look-color-default').checked?'':$('map-look-color').value,iconCornerRadius:$('map-look-radius').value,labelPosition:$('map-look-position').value,direction:$('map-look-direction').value,labelBackgroundColor:bg};
 let next;try{next=mapApplyLook(mapCurrent,$('map-look-device').value,look);}catch(e){error.textContent=e.message;return;}
 if(next===mapCurrent||JSON.stringify(JSON.parse(next))===JSON.stringify(JSON.parse(mapCurrent))){notify('Nothing changed for this device.');return;}
 // An ordinary edit: the editor takes the document, persist() records the step, Undo takes it back.
 try{await mapEditor.applyAnnotations(next);notify('Look applied to '+$('map-look-device').value+'. Save map keeps it.');}catch(e){error.textContent='The look was not applied: '+e.message;}
}
let mapLinkList=[];
function mapLinkFill(){const link=mapLinkList[Number($('map-link-select').value)]||mapLinkList[0];if(!link)return;$('map-link-own').checked=link.own;$('map-link-offset').value=link.offset;$('map-link-offset').disabled=!link.own;$('map-link-error').textContent='';}
async function mapLinkOpen(){
 let drawing;try{drawing=await(await api('/labs/'+encodeURIComponent(mapLab)+'/topology')).json();}catch(error){notify('The links could not be read: '+error.message);return;}
 mapLinkList=mapLinks(drawing&&drawing.links,mapCurrent);if(!mapLinkList.length){notify('This lab has no links.');return;}
 const select=$('map-link-select');select.replaceChildren(...mapLinkList.map((link,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=mapLinkLabel(link)+(link.own?'  ·  own distance '+link.offset:'');return o;}));
 // The link selected on the canvas: the editor numbers links in the topology's order (Clab-Link<n>)
 const picked=document.querySelector('.react-flow__edge.selected'),m=picked&&/Clab-Link(\d+)$/.exec(picked.getAttribute('data-testid')||picked.getAttribute('data-id')||'');
 if(m&&mapLinkList[Number(m[1])])select.value=m[1];
 mapLinkFill();$('map-link-dialog').showModal();
}
async function mapLinkApply(){
 const error=$('map-link-error'),index=Number($('map-link-select').value),link=mapLinkList[index];error.textContent='';if(!link)return;
 let next;try{next=mapApplyLinkOffset(mapCurrent,link,$('map-link-own').checked,$('map-link-offset').value);}catch(e){error.textContent=e.message;return;}
 if(JSON.stringify(JSON.parse(next))===JSON.stringify(JSON.parse(mapCurrent))){notify('Nothing changed for this link.');return;}
 try{await mapEditor.applyAnnotations(next);mapLinkList=mapLinks(mapLinkList.map(l=>[{node:l.source,interface:l.sourceEndpoint},{node:l.target,interface:l.targetEndpoint}]),mapCurrent);notify('Label distance applied to '+mapLinkLabel(link)+'. Save map keeps it.');}
 catch(e){error.textContent='The distance was not applied: '+e.message;}
}
const labBuilderPage={
 // Called by the adapter after every settled edit, before the editor hears the answer. The first call is the
 // editor's own reading of the document and becomes the baseline; a changed topology text is refused.
 persist(yaml,annotations){
  if(!mapDoc||yaml!==mapDoc.yaml)throw Object.assign(new Error('The map editor does not change the topology. That edit was not kept.'),{code:'topology'});
  if(mapBaseline===null)mapBaseline=annotations;mapCurrent=annotations;
  // A state the page itself put into the editor (undo, redo) is already in the history.
  if(!mapApplying)mapHistory=mapHistoryPush(mapHistory,annotations,Date.now());
  mapRenderBar();
 },
 attach(editor){mapEditor=editor;mapRenderBar();},
 templates(){return {list:[],defaultName:''};},saveTemplates(){},images(){return [];},chooseTemplates:async()=>null,
 notify,requestSave(){mapSave();},problem(message){mapProblem(message);},
 ready(mount){mapMount=mount;mapOpen();}
};
window.labBuilderPage=labBuilderPage;
async function mapOpen(){
 if(!mapMount||!mapDoc||mapMounted)return;
 mapMounted=true;$('map-welcome').hidden=true;
 try{await mapMount({id:'map:'+mapLab,name:mapDoc.name,yaml:mapDoc.yaml,annotations:mapDoc.annotations,mapOnly:true});}
 catch(error){mapMounted=false;$('map-welcome').hidden=false;$('map-welcome-text').textContent='The map editor could not open this lab’s topology: '+error.message;}
 // The palette opens on its device tab, which is inert here: show the drawing tools instead.
 let tries=0;const annotate=()=>{const tab=document.querySelector('[data-testid="panel-tab-annotations"]');if(tab)tab.click();else if(++tries<40)setTimeout(annotate,100);};if(mapMounted)annotate();
 mapRenderBar();
}
async function mapStart(){
 mapLab=mapLabFromHash(location.hash);$('map-back').href=$('map-welcome-back').href=mapBackUrl(mapLab);
 if(!mapLab){$('map-welcome-text').textContent='No lab was named. Open a lab and choose Edit map.';mapRenderBar();return;}
 try{mapDoc=await(await api('/labs/'+encodeURIComponent(mapLab)+'/map-document')).json();}
 catch(error){$('map-welcome-text').textContent=error.message;mapRenderBar();return;}
 $('map-name').textContent=mapDoc.name;document.title='Edit map · '+mapDoc.name+' · Containerlab Node Manager';mapCurrent=mapDoc.annotations;
 mapRenderBar();mapOpen();
}
if(typeof document!=='undefined'&&$('map-save')){
 $('map-save').onclick=()=>mapSave();$('map-download').onclick=mapDownload;$('map-problem-download').onclick=mapDownload;$('map-problem-reload').onclick=()=>{mapBaseline=mapCurrent;location.reload();};
 $('map-drawio').onclick=()=>{if(mapDirty()){notify('Save the map first: the draw.io export is made from the saved map.');return;}location.assign('/api/labs/'+encodeURIComponent(mapLab)+'/drawio');};
 $('map-back').onclick=e=>{e.preventDefault();mapLeave();};
 $('map-leave-stay').onclick=()=>$('map-leave').close();$('map-leave-discard').onclick=()=>{mapBaseline=mapCurrent;location.assign(mapBackUrl(mapLab));};
 $('map-leave-save').onclick=async()=>{$('map-leave').close();if(await mapSave())location.assign(mapBackUrl(mapLab));};
 $('map-import').onclick=()=>{$('map-import-error').textContent='';$('map-import-file').value='';$('map-import-dialog').showModal();};
 $('map-import-cancel').onclick=()=>$('map-import-dialog').close();$('map-import-confirm').onclick=()=>mapImport();
 $('map-link').onclick=()=>mapLinkOpen();$('map-link-close').onclick=()=>$('map-link-dialog').close();$('map-link-select').onchange=mapLinkFill;$('map-link-own').onchange=()=>{$('map-link-offset').disabled=!$('map-link-own').checked;};
 $('map-link-form').onsubmit=e=>{e.preventDefault();mapLinkApply();};
 $('map-look').onclick=mapLookOpen;$('map-look-close').onclick=()=>$('map-look-dialog').close();$('map-look-device').onchange=mapLookFill;
 $('map-look-form').onsubmit=e=>{e.preventDefault();mapLookApply();};
 $('map-look-color-default').onchange=()=>{$('map-look-color').disabled=$('map-look-color-default').checked;};
 $('map-look-bg-default').onchange=$('map-look-bg-transparent').onchange=e=>{if(e.target.checked)(e.target.id==='map-look-bg-default'?$('map-look-bg-transparent'):$('map-look-bg-default')).checked=false;$('map-look-bg').disabled=$('map-look-bg-default').checked||$('map-look-bg-transparent').checked;};
 $('map-undo').onclick=()=>mapTravel(-1);$('map-redo').onclick=()=>mapTravel(1);
 // Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl/Cmd+Y, except while typing in a field (the field's own undo applies there).
 window.addEventListener('keydown',e=>{
  if(!(e.ctrlKey||e.metaKey)||e.altKey)return;const key=e.key.toLowerCase(),target=e.target;
  if(target&&(target.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName||'')))return;
  if(key==='z'||key==='y'){e.preventDefault();e.stopPropagation();mapTravel(key==='y'||e.shiftKey?1:-1);}
 },true);
 window.addEventListener('beforeunload',e=>{if(mapDirty()&&!mapPaused){e.preventDefault();e.returnValue='';}});
 mapStart();
}
