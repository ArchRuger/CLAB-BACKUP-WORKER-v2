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
