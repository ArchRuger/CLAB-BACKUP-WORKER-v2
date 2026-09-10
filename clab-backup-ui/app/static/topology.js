'use strict';
let mapKey='', mapRequest=0, mapBounds=[0,0,1000,600], mapBox=[...mapBounds];
const map=$('topology-map');
function setMapBox(){map.setAttribute('viewBox',mapBox.join(' '));}
function mapZoom(factor){const [x,y,w,h]=mapBox;if(w*factor<50||w*factor>400000)return;mapBox=[x+w*(1-factor)/2,y+h*(1-factor)/2,w*factor,h*factor];setMapBox();}
$('map-fit').onclick=()=>{mapBox=[...mapBounds];setMapBox();};
$('map-in').onclick=()=>mapZoom(.8);$('map-out').onclick=()=>mapZoom(1.25);
map.addEventListener('wheel',e=>{e.preventDefault();mapZoom(e.deltaY>0?1.15:1/1.15);},{passive:false});
let mapDrag=null;
map.addEventListener('pointerdown',e=>{if(e.button!==0)return;if(e.target.closest('[data-map-node]'))return;mapDrag={x:e.clientX,y:e.clientY,box:[...mapBox]};map.setPointerCapture(e.pointerId);});
map.addEventListener('pointermove',e=>{if(!mapDrag)return;const rect=map.getBoundingClientRect(),scale=Math.max(mapDrag.box[2]/rect.width,mapDrag.box[3]/rect.height);mapBox=[mapDrag.box[0]-(e.clientX-mapDrag.x)*scale,mapDrag.box[1]-(e.clientY-mapDrag.y)*scale,...mapDrag.box.slice(2)];setMapBox();});
for(const event of ['pointerup','pointercancel','lostpointercapture'])map.addEventListener(event,()=>mapDrag=null);
function mapAction(e){const node=e.target.closest('[data-map-node]');if(node?.dataset.mapNode)openDetails(node.dataset.mapNode);}
map.addEventListener('click',mapAction);map.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();mapAction(e);}});
const nodeMenu=$('node-context-menu');let contextLab='',contextNode=null;
function closeNodeMenu(restore=false){nodeMenu.hidden=true;if(restore)contextNode?.focus();contextNode=null;}
function openNodeMenu(element,x,y){
 const n=current()?.nodes.find(n=>n.name===element.dataset.mapNode);if(!n)return;
 contextLab=activeId;contextNode=element;
 nodeMenu.innerHTML=`<div class="context-node-name">${esc(n.short_name||n.name)}<small>${esc(n.address)}:${n.port}</small></div><button role="menuitem" data-terminal="${esc(n.name)}" ${n.ssh_ready?'':'disabled'}><span aria-hidden="true">›_</span> SSH <small>New tab ↗</small></button><button role="menuitem" data-backup="${esc(n.name)}" ${!busy()&&n.readiness==='Ready'?'':'disabled'}><span aria-hidden="true">↓</span> Back up configuration</button><button role="menuitem" data-details="${esc(n.name)}"><span aria-hidden="true">ⓘ</span> Node details</button>`;
 nodeMenu.hidden=false;nodeMenu.style.left=Math.max(8,Math.min(x,window.innerWidth-nodeMenu.offsetWidth-8))+'px';nodeMenu.style.top=Math.max(8,Math.min(y,window.innerHeight-nodeMenu.offsetHeight-8))+'px';nodeMenu.querySelector('button:not(:disabled)')?.focus();
}
map.addEventListener('contextmenu',e=>{const element=e.target.closest('[data-map-node]');if(!element)return;e.preventDefault();openNodeMenu(element,e.clientX,e.clientY);});
map.addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){const element=e.target.closest('[data-map-node]');if(element){e.preventDefault();const rect=element.getBoundingClientRect();openNodeMenu(element,rect.right,rect.top);}}});
nodeMenu.addEventListener('click',e=>{if(contextLab!==activeId){closeNodeMenu();return;}handleNodeAction(e);closeNodeMenu();});
nodeMenu.addEventListener('keydown',e=>{const buttons=[...nodeMenu.querySelectorAll('button:not(:disabled)')];if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const i=buttons.indexOf(document.activeElement);buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();}});
document.addEventListener('pointerdown',e=>{if(!nodeMenu.contains(e.target))closeNodeMenu();});
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;if(!nodeMenu.hidden){closeNodeMenu(true);return;}$('topology-view').classList.remove('map-expanded');$('map-expand').textContent='Expand map';});
window.addEventListener('resize',()=>closeNodeMenu());window.addEventListener('blur',()=>closeNodeMenu());
document.addEventListener('scroll',()=>closeNodeMenu(),true);
$('map-expand').onclick=()=>{const expanded=$('topology-view').classList.toggle('map-expanded');$('map-expand').textContent=expanded?'Close expanded map':'Expand map';closeNodeMenu();};
async function refreshMap(force=false){
 const labId=activeId,request=++mapRequest;if(!labId)return;
 try{const drawing=await(await api('/labs/'+labId+'/topology')).json();if(request!==mapRequest||activeId!==labId)return;
 const key=labId+JSON.stringify(drawing);if(!force&&key===mapKey)return;mapKey=key;closeNodeMenu();
 if(!drawing){map.innerHTML='';$('map-status').textContent='No map imported. Upload your annotations and lab topology to get started. The Nodes list remains available.';return;}
 const unmatched=drawing.nodes.filter(n=>!n.inventory_name).length;
 $('map-status').textContent=`${drawing.nodes.length} map nodes · ${drawing.links.length} links · ${unmatched} unmatched. ${drawing.skipped_links?drawing.skipped_links+' unsupported or one-ended links omitted. ':''}${drawing.has_links_source?'':'Import the lab topology with annotations to show wiring.'} Unmatched nodes have no connection actions.`;
 map.innerHTML=topologyMarkup(drawing);
 map.classList.toggle('labels-on-select',drawing.settings?.labelMode==='on-select');
 mapBounds=measureTopology(map);mapBox=[...mapBounds];setMapBox();
 if(drawing.schema!==2)$('map-status').textContent+=' Reimport the original annotations to recover styling discarded by the earlier importer.';

 }catch(e){if(request===mapRequest)$('map-status').textContent='Could not load map: '+e.message;}
}
$('import-map').onclick=()=>{$('map-form').reset();$('map-form').querySelector('.form-error').textContent='';$('map-dialog').showModal();};
$('cancel-map').onclick=()=>$('map-dialog').close();
$('map-form').addEventListener('submit',e=>{e.preventDefault();const labId=activeId;withForm(e.currentTarget,async()=>{await api('/labs/'+labId+'/topology',{method:'POST',body:new FormData(e.currentTarget)});$('map-dialog').close();if(activeId===labId)await refreshMap(true);notify('Topology imported.');});});
$('export-sessions').onclick=()=>{$('export-form').reset();$('export-form').querySelector('.form-error').textContent='';$('export-dialog').showModal();};
$('cancel-export').onclick=()=>$('export-dialog').close();
$('export-form').addEventListener('submit',e=>{e.preventDefault();const labId=activeId;withForm(e.currentTarget,async()=>{const response=await api('/labs/'+labId+'/superputty',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({include_passwords:$('export-passwords').checked})});const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=attachmentName(response,'sessions.xml');a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('export-dialog').close();});});

