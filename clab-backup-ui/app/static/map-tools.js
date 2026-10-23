'use strict';
// Map tools on the Topology tab (C06): link state (a class swap on the wires, polled while the tab is shown), Find, link hover,
// Download picture, Export to draw.io and Arrange devices with its one Undo. topology.js calls three hooks into this file
// (mapLinkSchedule, mapToolsRendered, mapWireText lives there); device-diagnostics.js and shell.js call mapLinkVisibility and
// mapLinkDrawerClosed behind typeof guards, so this file adds no window/document listener (shell.js owns those).
// Names: mapTool*, mapLink*, mapFind*, mapHover*, mapPicture*, mapDrawio*, mapArrange* (no collision with topology.js's map* names).
const MAP_LINK_INTERVAL=10000, MAP_LINK_OFF='Link state off: ';
const MAP_LINK_UNLINKED='This lab is not linked to a lab on the VM. Link it under Advanced › Link to a running lab… to see link state.';
const MAP_LINK_NOT_RUNNING='Links are drawn from the topology file; the lab is not running.';
const MAP_LINK_RUNNING=['Running','Partially running'];
const MAP_PICTURE_PROPS=['fill','fill-opacity','stroke','stroke-width','stroke-dasharray','stroke-linecap','stroke-linejoin','opacity','font-family','font-size','font-weight','display','visibility','text-anchor'];
const MAP_PICTURE_DEFAULTS={'fill':'rgb(0, 0, 0)','fill-opacity':'1','stroke':'none','stroke-width':'1px','stroke-dasharray':'none','stroke-linecap':'butt','stroke-linejoin':'miter','opacity':'1','display':'inline','visibility':'visible','text-anchor':'start'};
const MAP_PICTURE_MAX=8192;
let mapToolsLab='', mapToolsDrawing=null, mapToolsCaption='', mapToolsChipHtml=null;
let mapLinkCache={}, mapLinkPoll={timer:0,inFlight:false,plan:null,lastAt:0,epoch:0,fresh:true,stopped:'',off:'',status:'',message:'',mode:''};
let mapArrangeUndo=null, mapHoverWire=null, mapPictureBusy=false;
const mapToolsPlural=(n,word)=>typeof plural==='function'?plural(n,word):`${n} ${word}${Number(n)===1?'':'s'}`;
const mapToolsEl=id=>typeof $==='function'?$(id):null;
const mapToolsGroups=()=>map&&typeof map.querySelectorAll==='function'?[...map.querySelectorAll('.topology-wire')]:[];
const mapToolsDevices=()=>map&&typeof map.querySelectorAll==='function'?[...map.querySelectorAll('.map-device')]:[];
function mapToolsPad(n){return String(n).padStart(2,'0');}
function mapLinkAsOf(ms){if(!ms)return '';const d=new Date(ms);return mapToolsPad(d.getHours())+':'+mapToolsPad(d.getMinutes());}
// ---- Pure: the matcher ---------------------------------------------------------------------------------------------------------
// One result per drawn wire (a link whose two drawing nodes both exist, in the order the renderer draws them). An end is up, down
// (state kept), missing (device listed, no such interface), not-running (device not listed) or unknown (not a lab device, no container
// name, or the answer is unavailable). A wire is down when any end is down, missing or not-running; up when both ends are up.
function mapLinkEnd(point,node,answer){
 const base={label:node?String(node.label??node.id??''):'',interface:String(point.interface??''),name:'',end:'unknown',state:'',vm:false};
 if(!answer||answer.available===false||!node||!node.inventory_name)return base;
 const device=answer.devices&&answer.devices[node.inventory_name];
 if(!device)return base;
 base.vm=device.vm===true;
 if(device.listed===false)return {...base,end:'not-running'};
 const row=(device.interfaces||[]).find(r=>r&&(r.name===point.interface||r.alias===point.interface||r.port===point.interface||(point.capture_interface&&r.name===point.capture_interface)));
 if(!row)return {...base,end:'missing'};
 return {...base,name:String(row.name||''),end:row.state==='up'?'up':'down',state:String(row.state||'down')};
}
function mapLinkStates(drawing,answer){
 const nodes=new Map(((drawing&&drawing.nodes)||[]).map(n=>[n.id,n])),out=[],counts={up:0,down:0,unknown:0};
 ((drawing&&drawing.links)||[]).forEach((pair,index)=>{
  const a=nodes.get(pair[0].node),b=nodes.get(pair[1].node);if(!a||!b)return;
  const ends=[mapLinkEnd(pair[0],a,answer),mapLinkEnd(pair[1],b,answer)];
  const bad=ends.some(e=>['down','missing','not-running'].includes(e.end));
  const state=bad?'down':ends.every(e=>e.end==='up')?'up':'unknown';
  counts[state]++;out.push({index,state,ends});
 });
 return {wires:out,counts};
}
// The wire's state clause (data-state-text). Both ends in the same non-up state are worded once, no device blamed.
function mapLinkClause(wire){
 if(wire.state==='unknown'){return wire.ends.some(e=>e.end==='unknown'&&e.label&&e.unlisted)?'not checked (no container name)':'';}
 if(wire.state==='up'){
  const vms=wire.ends.filter(e=>e.vm).map(e=>e.label);
  return vms.length?`connected (the VM's link to ${[...new Set(vms)].join(' and ')}; a port shut down inside ${[...new Set(vms)].join(' and ')} may not show here)`:'up';
 }
 const bad=wire.ends.filter(e=>['down','missing','not-running'].includes(e.end));
 if(bad.length===2&&bad[0].end==='down'&&bad[1].end==='down'&&bad[0].state===bad[1].state)return `down at both ends (${bad[0].state}: one side may be shut down)`;
 const parts=bad.map(e=>e.end==='not-running'?`${e.label} is not running`:e.end==='missing'?`${e.label} ${e.interface} is missing on the device`:`${e.label} ${e.interface} is ${e.state}`);
 return 'down: '+[...new Set(parts)].join(' · ');
}
function mapLinkChipText(counts,anyVm){
 const total=counts.up+counts.down+counts.unknown;if(!total)return '';
 let text=`Links: ${counts.up} ${anyVm?'connected':'up'}`;
 if(counts.down)text+=` · ${counts.down} down`;
 if(counts.unknown)text+=` · ${counts.unknown} not checked`;
 return text;
}
// ---- Link state: apply and clear -----------------------------------------------------------------------------------------------------
function mapLinkSetWire(group,state,text){
 group.classList.toggle('link-up',state==='up');group.classList.toggle('link-down',state==='down');
 if((group.getAttribute('data-state-text')||'')===(text||''))return;
 if(text)group.setAttribute('data-state-text',text);else group.removeAttribute('data-state-text');
 if(typeof mapWireText==='function')mapWireText(group);
}
function mapLinkClear(){
 for(const group of mapToolsGroups())mapLinkSetWire(group,'',''); // never touches impaired or data-impaired-text
}
// Marks the unlisted lab devices (a lab device the answer carries no entry for) so the clause can say why a wire was not checked.
function mapLinkApply(answer,asOf){
 const drawing=mapToolsDrawing;if(!drawing)return null;
 const result=mapLinkStates(drawing,answer),groups=mapToolsGroups(),nodes=new Map(drawing.nodes.map(n=>[n.id,n]));
 result.wires.forEach(w=>{const pair=drawing.links[w.index];w.ends.forEach((e,i)=>{const node=nodes.get(pair[i].node);e.unlisted=!!(node&&node.inventory_name&&answer&&answer.available!==false&&!(answer.devices&&answer.devices[node.inventory_name]));});});
 groups.forEach((group,i)=>{
  const w=result.wires[i];if(!w){mapLinkSetWire(group,'','');return;}
  const clause=mapLinkClause(w);
  mapLinkSetWire(group,w.state,clause&&asOf&&w.state!=='unknown'?`${clause} (as of ${asOf})`:clause);
 });
 const anyVm=Object.values((answer&&answer.devices)||{}).some(d=>d&&d.vm===true);
 return {...result,anyVm};
}
// ---- The chip ------------------------------------------------------------------------------------------------------------------------
function mapLinkLegend(anyVm,impaired){
 return `<span class="map-legend"><svg viewBox="0 0 24 8" aria-hidden="true"><path class="legend-down" d="M0 4H24"/></svg>${esc(anyVm?'dotted red = down (container link)':'dotted red = down')}</span>`
  +(impaired?`<span class="map-legend"><svg viewBox="0 0 24 8" aria-hidden="true"><path class="legend-impaired" d="M0 4H24"/></svg>${esc('dashed amber = impaired')}</span>`:'');
}
function mapToolsChip(){
 const el=mapToolsEl('map-links');if(!el)return;
 const poll=mapLinkPoll,drawing=mapToolsDrawing;let html='';
 if(drawing&&!(map&&map.hidden)){
  html+=poll.message?`<span class="map-links-state">${esc(poll.message)}</span>`:'';
  if(poll.stopped)html+=` <button type="button" class="button ghost small" data-map-link-retry="${esc(poll.stopped)}">${poll.stopped==='resume'?'Resume':'Retry'}</button>`;
  if(poll.legend)html+=mapLinkLegend(poll.legend.anyVm,poll.legend.impaired);
  if(mapArrangeUndo&&mapArrangeUndo.lab===activeId)html+=` <button type="button" class="button ghost small" data-map-arrange-undo="1">Undo arrange</button>`;
  else if(drawing.placed===false&&(drawing.nodes||[]).length>=2)html+=`<span class="map-links-state">${poll.message?' · ':''}Devices sit on the default grid.</span> <button type="button" class="button ghost small" id="map-arrange-hint">Arrange devices…</button>`;
 }
 if(html===mapToolsChipHtml)return;
 mapToolsChipHtml=html;el.innerHTML=html;
}
function mapLinkSay(message,legend){
 const poll=mapLinkPoll;poll.message=message;poll.legend=legend||null;mapToolsChip();
}
// ---- The poll ------------------------------------------------------------------------------------------------------------------------
function mapLinkPlan(){const plan=typeof diagPlan==='function'?diagPlan(Date.now()):{interval:MAP_LINK_INTERVAL,errors:0,startedAt:Date.now()};return {...plan,interval:MAP_LINK_INTERVAL,floor:MAP_LINK_INTERVAL};}
// What the poll may do right now. kind 'off' = a sentence, classes cleared, no request; 'idle' = silently nothing (tab, hidden page,
// open drawer, no map); 'run' = poll.
function mapLinkConditions(){
 const lab=typeof current==='function'?current():null;
 if(!lab)return {kind:'idle'};
 const status=lab.deployment&&lab.deployment.status;
 const linked=!!lab.deployment_name||(status&&status!=='Unlinked');
 if(!linked)return {kind:'off',key:'unlinked',text:MAP_LINK_OFF+MAP_LINK_UNLINKED};
 if(!MAP_LINK_RUNNING.includes(status))return {kind:'off',key:'not running',text:MAP_LINK_NOT_RUNNING};
 const view=mapToolsEl('topology-view'),dialog=mapToolsEl('details-dialog');
 if(typeof tab==='string'&&tab!=='topology')return {kind:'idle'};
 if(view&&view.hidden)return {kind:'idle'};
 if(!mapToolsDrawing||!map||map.hidden)return {kind:'idle'};
 if(typeof pageVisible==='function'&&!pageVisible())return {kind:'idle'};
 if(dialog&&dialog.open)return {kind:'idle'};
 return {kind:'run'};
}
function mapLinkStopTimer(){clearTimeout(mapLinkPoll.timer);mapLinkPoll.timer=0;}
function mapToolsReset(){
 const poll=mapLinkPoll;mapLinkStopTimer();poll.epoch++;
 Object.assign(poll,{inFlight:false,plan:null,lastAt:0,fresh:true,stopped:'',off:'',message:'',legend:null});
 mapLinkCache={};mapArrangeUndo=null;mapHoverClear();mapToolsDrawing=null;
 const find=mapToolsEl('map-find');if(find)find.value='';
 const count=mapToolsEl('map-find-count');if(count){count.textContent='';count.hidden=true;}
 mapToolsChipHtml=null;
 const chip=mapToolsEl('map-links');if(chip)chip.innerHTML='';
 for(const group of mapToolsGroups())mapLinkSetWire(group,'','');
 for(const el of mapToolsDevices())el.classList.remove('dimmed');
}
function mapToolsLabCheck(){if(mapToolsLab!==activeId){const had=mapToolsLab;mapToolsLab=activeId;if(had!=='' || mapToolsDrawing)mapToolsReset();}}
function mapLinkSchedule(){
 mapToolsLabCheck();
 const poll=mapLinkPoll;if(poll.inFlight)return;
 const c=mapLinkConditions();
 if(c.kind==='off'){
  if(poll.off!==c.key){mapLinkStopTimer();poll.off=c.key;poll.mode='';poll.fresh=true;poll.stopped='';poll.plan=null;delete mapLinkCache[activeId];mapLinkClear();mapLinkSay(c.text,null);}
  return;
 }
 if(poll.off){poll.off='';poll.message='';}
 if(c.kind==='idle'){if(poll.timer){mapLinkStopTimer();poll.fresh=true;}return;}
 if(poll.timer||poll.stopped||poll.mode==='unavailable')return;
 const delay=poll.fresh||!mapLinkCache[activeId]||!poll.plan?0:poll.plan.interval;
 if(poll.fresh||!poll.plan){poll.plan=mapLinkPlan();}
 poll.timer=setTimeout(mapLinkRun,delay);
}
async function mapLinkFetch(labId){return (await api('/operations/link-state?lab_id='+encodeURIComponent(labId))).json();}
async function mapLinkRun(){
 const poll=mapLinkPoll;poll.timer=0;
 const c=mapLinkConditions();
 if(c.kind!=='run'){poll.fresh=true;if(c.kind==='off')mapLinkSchedule();return;}
 const labId=activeId,epoch=poll.epoch;poll.inFlight=true;poll.fresh=false;
 let result;
 try{result={ok:true,data:await mapLinkFetch(labId)};}
 catch(e){result={ok:false,status:e&&e.status?e.status:0,message:e&&e.message?e.message:''};}
 poll.inFlight=false;
 if(epoch!==poll.epoch||activeId!==labId)return;
 // 409 is the manager's own helper sentence (an old helper): colours off with that sentence, no more polling, like available:false.
 if(!result.ok&&result.status===409&&result.message){poll.mode='unavailable';poll.timer=0;delete mapLinkCache[labId];mapLinkClear();mapLinkSay(MAP_LINK_OFF+result.message,null);return;}
 const next=typeof diagPollNext==='function'?diagPollNext(poll.plan||mapLinkPlan(),result.ok?{ok:true}:{ok:false,status:result.status},Date.now()):{plan:poll.plan,delay:MAP_LINK_INTERVAL,stop:''};
 poll.plan=next.plan;
 if(result.ok){
  const answer=result.data||{};
  if(answer.available===false){
   poll.mode='unavailable';delete mapLinkCache[labId];mapLinkClear();
   mapLinkSay(MAP_LINK_OFF+String(answer.text||'Link state is not available here.'),null);
   return;
  }
  poll.mode='';poll.lastAt=Date.now();mapLinkCache[labId]=answer;
  mapLinkShow(answer,'');
 }else{
  const asOf=mapLinkAsOf(poll.lastAt),cached=mapLinkCache[labId];
  if(next.stop){
   poll.stopped=next.stop;
   if(cached)mapLinkApply(cached,asOf);
   mapLinkSay(`Link state ${next.stop==='resume'?'paused':'stopped'}${asOf?` (as of ${asOf})`:''}.`,poll.legend);
   return;
  }
  mapLinkSay('Link state paused, retrying…',poll.legend);
 }
 if(next.stop){
  poll.stopped=next.stop;const asOf=mapLinkAsOf(poll.lastAt);
  if(mapLinkCache[labId])mapLinkApply(mapLinkCache[labId],asOf);
  mapLinkSay(`Link state paused${asOf?` (as of ${asOf})`:''}.`,poll.legend);
  return;
 }
 poll.timer=setTimeout(mapLinkRun,next.delay);
}
function mapLinkShow(answer,asOf){
 const applied=mapLinkApply(answer,asOf);if(!applied)return;
 const impaired=typeof opImpairmentCount==='function'&&typeof opImpairmentCache!=='undefined'&&opImpairmentCount(opImpairmentCache[activeId])>0;
 mapLinkSay(mapLinkChipText(applied.counts,applied.anyVm),{anyVm:applied.anyVm,impaired});
}
// Retry / Resume: a fresh plan and one fetch now.
function mapLinkRestart(){
 const poll=mapLinkPoll;mapLinkStopTimer();poll.stopped='';poll.fresh=true;poll.plan=null;poll.mode='';
 mapLinkSay('Link state paused, retrying…',poll.legend);mapLinkSchedule();
}
// device-diagnostics.js calls this when the page becomes visible again: a poll that fell asleep gets one fresh fetch.
function mapLinkVisibility(){
 const poll=mapLinkPoll;
 if(poll.timer&&poll.plan&&Date.now()-poll.lastAt>=poll.plan.interval){mapLinkStopTimer();poll.fresh=true;}
 mapLinkSchedule();
}
// shell.js calls this when the device drawer closes: one fresh fetch and the plan again.
function mapLinkDrawerClosed(){
 const poll=mapLinkPoll;if(poll.inFlight)return;
 mapLinkStopTimer();poll.fresh=true;mapLinkSchedule();
}
// ---- Hook: the map was rebuilt -----------------------------------------------------------------------------------------------
function mapToolsRendered(drawing){
 mapToolsLabCheck();
 mapToolsDrawing=drawing||null;mapToolsCaption=(mapToolsEl('map-status')||{}).textContent||'';
 mapHoverClear();
 if(mapArrangeUndo&&(!drawing||drawing.revision!==mapArrangeUndo.revision))mapArrangeUndo=null;
 if(drawing){
  const cached=mapLinkCache[activeId];
  if(cached&&!mapLinkPoll.off&&mapLinkPoll.mode!=='unavailable')mapLinkApply(cached,mapLinkPoll.stopped?mapLinkAsOf(mapLinkPoll.lastAt):'');
  mapFindApply();
 }
 mapToolsChip();
 mapLinkSchedule();
}
// ---- Find ----------------------------------------------------------------------------------------------------------------------
function mapFindHaystack(el,lab){
 const label=el.dataset&&el.dataset.label||el.getAttribute('data-label')||'';
 const name=el.dataset&&el.dataset.mapNode||el.getAttribute('data-map-node')||'';
 const n=name&&lab?(lab.nodes||[]).find(x=>x.name===name):null;
 if(!n)return String(label).toLowerCase();
 const platform=typeof platformLabel==='function'?platformLabel(n.platform):String(n.platform??'');
 return `${n.name} ${n.address??''} ${platform} ${label}`.toLowerCase();
}
function mapFindApply(raw){
 const input=mapToolsEl('map-find'),count=mapToolsEl('map-find-count');
 const typed=String(raw!==undefined?raw:(input?input.value:'')).trim(),term=typed.toLowerCase();
 const lab=typeof current==='function'?current():null,devices=mapToolsDevices();let matches=0;
 const hidden=new Set();
 for(const el of devices){
  const match=!term||mapFindHaystack(el,lab).includes(term);
  el.classList.toggle('dimmed',!match);if(match)matches++;
  if(!match){const name=el.getAttribute('data-map-node'),id=el.getAttribute('data-map-id');hidden.add(name||('#'+id));}
 }
 for(const group of mapToolsGroups()){
  const ends=String(group.getAttribute('data-link-ends')||'').split('|');
  group.classList.toggle('dimmed',!!term&&ends.length===2&&hidden.has(ends[0])&&hidden.has(ends[1]));
 }
 if(count){
  const text=!term?'':!matches?`No device matches "${typed}"`:`${matches} of ${devices.length} ${matches===1?"devices matches":"devices match"}`;
  if(count.textContent!==text)count.textContent=text;
  count.hidden=!term;
 }
 return matches;
}
function mapFindFit(){
 const found=mapToolsDevices().filter(el=>!el.classList.contains('dimmed'));
 const points=found.map(el=>String(el.getAttribute('transform')||'').match(/translate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)/)).filter(Boolean).map(m=>[Number(m[1]),Number(m[2])]);
 if(!points.length){mapBox=[...mapBounds];setMapBox();return false;}
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),pad=60+20;
 const x=Math.min(...xs)-pad,y=Math.min(...ys)-pad,w=Math.max(200,Math.max(...xs)-Math.min(...xs)+pad*2),h=Math.max(150,Math.max(...ys)-Math.min(...ys)+pad*2);
 mapBox=[x,y,w,h];setMapBox();return true;
}
function mapFindKey(e){
 const input=mapToolsEl('map-find');
 if(e.key==='Enter'){e.preventDefault();mapFindApply();mapFindFit();return;}
 if(e.key==='Escape'&&input&&input.value!==''){input.value='';mapFindApply();e.preventDefault();e.stopPropagation();}
}
// ---- Link hover ----------------------------------------------------------------------------------------------------------------
function mapHoverClear(){
 for(const el of [...mapToolsGroups(),...mapToolsDevices()]){el.classList.remove('hover');el.classList.remove('hover-end');}
 mapHoverWire=null;
 const line=mapToolsEl('map-link-hover');if(line){line.textContent='';line.hidden=true;}
}
function mapHoverSet(wire){
 if(mapHoverWire===wire)return;
 mapHoverClear();mapHoverWire=wire;wire.classList.add('hover');
 const ends=String(wire.getAttribute('data-link-ends')||'').split('|');
 for(const el of mapToolsDevices()){const name=el.getAttribute('data-map-node'),id=el.getAttribute('data-map-id');if(ends.includes(name||('#'+id)))el.classList.add('hover-end');}
 const line=mapToolsEl('map-link-hover');
 if(line){line.textContent=typeof mapWireText==='function'?mapWireText(wire):String(wire.getAttribute('data-base')||'');line.hidden=false;}
}
function mapHoverEvent(e,leaving){
 const wire=e.target&&typeof e.target.closest==='function'?e.target.closest('.topology-wire'):null;if(!wire)return;
 if(!leaving){mapHoverSet(wire);return;}
 const to=e.relatedTarget;if(to&&typeof wire.contains==='function'&&wire.contains(to))return;
 if(mapHoverWire===wire)mapHoverClear();
}
// ---- Dialog helpers --------------------------------------------------------------------------------------------------------------
async function mapToolsRun(form,status,fn){
 const submit=form&&typeof form.querySelector==='function'?form.querySelector('button[type=submit]'):null;
 if(submit)submit.disabled=true;if(status)status.textContent='';
 try{await fn();}catch(e){if(status)status.textContent=e&&e.message?e.message:'That did not work. Try again.';else if(typeof notify==='function')notify(e.message);}
 finally{if(submit)submit.disabled=false;}
}
function mapToolsSay(sentence){
 const status=mapToolsEl('map-status');
 if(status){status.textContent=sentence;const kept=mapToolsCaption;setTimeout(()=>{if(status.textContent===sentence)status.textContent=kept;},8000);}
 if(typeof notify==='function')notify(sentence);
}
function mapToolsLabName(){const lab=typeof current==='function'?current():null;return String((lab&&lab.name)||'lab').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,150)||'lab';}
function mapToolsSave(blob,name){
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;
 if(document.body&&typeof document.body.append==='function')document.body.append(a);
 a.click();if(typeof a.remove==='function')a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);return name;
}
// ---- Download picture ----------------------------------------------------------------------------------------------------------
const mapPictureStateClass=c=>/^(link-up|link-down|impaired|hover|hover-end|dimmed)$/.test(c)||c.startsWith('state-');
// Removes hover, hover-end and dimming from the live map (and, with the state off, every state class, putting each device on
// state-neutral) so computed styles describe the picture, not the moment; returns the function that puts every class list back.
function mapPictureNeutral(svg,stateOff){
 const saved=[],all=[svg,...svg.querySelectorAll('*')];
 for(const el of all){
  const before=el.getAttribute('class');if(before===null)continue;
  const list=before.split(/\s+/).filter(Boolean);
  const kept=list.filter(c=>!['hover','hover-end','dimmed'].includes(c)&&!(stateOff&&mapPictureStateClass(c)));
  if(stateOff&&list.some(c=>c.startsWith('state-')))kept.push('state-neutral');
  if(kept.join(' ')!==list.join(' ')){saved.push([el,before]);el.setAttribute('class',kept.join(' '));}
 }
 const line=mapToolsEl('map-link-hover'),hoverText=line?line.textContent:'';if(line)line.textContent='';
 return ()=>{for(const [el,before] of saved)el.setAttribute('class',before);if(line)line.textContent=hoverText;};
}
// Builds the picture's <svg> from the live map: neutralise, clone, read computed styles of the live elements, restore (finally), then
// strip and inline on the clone. `options`: {state, whole, background}; `readStyle(el)` answers getPropertyValue (getComputedStyle).
function mapPictureSvg(live,options,readStyle,bounds){
 const stateOn=!!options.state,restore=mapPictureNeutral(live,!stateOn);
 let clone,liveAll,snapshot;
 try{
  clone=live.cloneNode(true);liveAll=[live,...live.querySelectorAll('*')];
  snapshot=liveAll.map(el=>{const cs=readStyle(el),o={};for(const p of MAP_PICTURE_PROPS)o[p]=cs.getPropertyValue(p);return o;});
 }finally{restore();}
 const cloneAll=[clone,...clone.querySelectorAll('*')];
 cloneAll.forEach((el,i)=>{
  if(i===0||!el.parentNode)return;
  const tag=String(el.localName||el.tagName||'').toLowerCase(),classes=String(el.getAttribute('class')||'').split(/\s+/);
  const drop=classes.includes('capture-hit')||tag==='title'||(!stateOn&&(classes.includes('device-state-dot')||classes.includes('device-state-glyph')||classes.includes('device-state-badge')))
   ||(!options.background&&(classes.includes('topology-bg')||classes.includes('topology-grid')))||snapshot[i].display==='none';
  if(drop){el.parentNode.removeChild(el);return;}
  const style=snapshot[i];
  for(const p of MAP_PICTURE_PROPS){
   const v=style[p];if(!v||v===MAP_PICTURE_DEFAULTS[p])continue;
   if(['font-family','font-size','font-weight'].includes(p)&&tag!=='text')continue;
   el.setAttribute(p,v);
  }
  if(options.background&&(classes.includes('topology-bg')||classes.includes('topology-grid'))){for(const [k,v] of Object.entries({x:bounds[0],y:bounds[1],width:bounds[2],height:bounds[3]}))el.setAttribute(k,String(v));}
 });
 for(const el of cloneAll){
  if(!el.parentNode&&el!==clone)continue;
  for(const name of [...(el.getAttributeNames?el.getAttributeNames():[])]){
   if(name==='tabindex'||name==='role'||name.startsWith('aria-')||name.startsWith('data-'))el.removeAttribute(name);
  }
  const before=el.getAttribute('class');
  if(before!==null){const kept=before.split(/\s+/).filter(c=>c&&!mapPictureStateClass(c));if(kept.length)el.setAttribute('class',kept.join(' '));else el.removeAttribute('class');}
 }
 clone.removeAttribute('hidden');clone.removeAttribute('class');
 const [x,y,w,h]=bounds.map(v=>Math.round(v*100)/100);
 clone.setAttribute('viewBox',`${x} ${y} ${w} ${h}`);clone.setAttribute('width',String(Math.round(w)));clone.setAttribute('height',String(Math.round(h)));
 clone.setAttribute('xmlns','http://www.w3.org/2000/svg');
 return {svg:clone,width:Math.round(w),height:Math.round(h),box:[x,y,w,h]};
}
function mapPictureText(svg){return new XMLSerializer().serializeToString(svg);}
function mapPictureRender(options){
 const bounds=options.whole?[...mapBounds]:[...mapBox];
 const built=mapPictureSvg(map,options,el=>getComputedStyle(el),bounds);
 try{if(typeof renderMapState==='function')renderMapState();}finally{mapToolsRendered(mapToolsDrawing);}
 return {...built,text:mapPictureText(built.svg)};
}
function mapPicturePng(text,width,height,background){
 return new Promise((resolve,reject)=>{
  const longest=Math.max(width,height);
  if(longest>MAP_PICTURE_MAX){reject(new Error('The map is too large for a PNG here (over 8192 px). Download the SVG.'));return;}
  const scale=Math.min(2,MAP_PICTURE_MAX/longest),fail=()=>reject(new Error('The PNG could not be made in this browser. Download the SVG instead.'));
  const image=new Image();
  image.onload=()=>{
   try{
    const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(width*scale));canvas.height=Math.max(1,Math.round(height*scale));
    const g=canvas.getContext('2d');if(!g){fail();return;}
    if(background){g.fillStyle='#ffffff';g.fillRect(0,0,canvas.width,canvas.height);}
    g.drawImage(image,0,0,canvas.width,canvas.height);
    canvas.toBlob(blob=>blob?resolve(blob):fail(),'image/png');
   }catch{fail();}
  };
  image.onerror=fail;
  image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(text);
 });
}
async function mapPictureDownload(){
 const checked=id=>!!(mapToolsEl(id)&&mapToolsEl(id).checked);
 const options={png:checked('map-picture-png'),whole:checked('map-picture-whole'),background:checked('map-picture-background'),state:checked('map-picture-state')};
 const built=mapPictureRender(options),base=mapToolsLabName()+'-map';
 let name;
 if(options.png){const blob=await mapPicturePng(built.text,built.width,built.height,options.background);name=mapToolsSave(blob,base+'.png');}
 else name=mapToolsSave(new Blob([built.text],{type:'image/svg+xml'}),base+'.svg');
 const dialog=mapToolsEl('map-picture-dialog');if(dialog)dialog.close();
 if(typeof notify==='function')notify(`Picture saved as ${name}.`);
 return name;
}
// ---- Export to draw.io ---------------------------------------------------------------------------------------------------------
function mapDrawioFile(layout){return mapToolsLabName()+(layout==='rows'||layout==='columns'?'-'+layout:'')+'.drawio';}
async function mapDrawioDownload(){
 const lab=typeof current==='function'?current():null;if(!lab)throw new Error('Open a lab first.');
 const checked=id=>!!(mapToolsEl(id)&&mapToolsEl(id).checked);
 const layout=checked('map-drawio-layout-rows')?'rows':checked('map-drawio-layout-columns')?'columns':'map',theme=checked('map-drawio-theme-print')?'print':'manager';
 const response=await api(`/labs/${encodeURIComponent(lab.id)}/drawio?layout=${layout}&theme=${theme}`);
 const name=mapToolsSave(await response.blob(),attachmentName(response,mapDrawioFile(layout)));
 const dialog=mapToolsEl('map-drawio-dialog');if(dialog)dialog.close();
 if(typeof notify==='function')notify(`Saved ${name}.`);
 return name;
}
// ---- Arrange devices and its one Undo ------------------------------------------------------------------------------------------
const MAP_ARRANGE_DONE={rows:'Devices arranged in rows.',columns:'Devices arranged in columns.',ring:'Devices arranged in a ring.'};
function mapArrangeOpen(){
 const drawing=mapToolsDrawing,dialog=mapToolsEl('map-arrange-dialog');if(!drawing||!dialog)return;
 const groups=(drawing.decorations||[]).filter(d=>d.type==='group').length,note=mapToolsEl('map-arrange-groups');
 if(note){note.textContent=groups?(groups===1?'1 group will no longer surround its devices.':`${groups} groups will no longer surround their devices.`):'';note.hidden=!groups;}
 const noLinks=!(drawing.links||[]).length,reason=mapToolsEl('map-arrange-reason');
 if(reason)reason.hidden=!noLinks;
 const status=mapToolsEl('map-arrange-status');if(status)status.textContent='';
 mapArrangeButtons(false);
 dialog.showModal();
}
function mapArrangeButtons(busy){
 const noLinks=!((mapToolsDrawing&&mapToolsDrawing.links)||[]).length;
 for(const el of (mapToolsEl('map-arrange-dialog')||{querySelectorAll:()=>[]}).querySelectorAll('[data-arrange]')){
  const mode=el.getAttribute('data-arrange');el.disabled=busy||(noLinks&&mode!=='ring');
  if(!el.getAttribute('data-label'))el.setAttribute('data-label',el.textContent);
  el.textContent=busy?'Arranging…':el.getAttribute('data-label');
 }
}
async function mapArrangeRun(mode){
 const drawing=mapToolsDrawing,labId=activeId,status=mapToolsEl('map-arrange-status');
 if(!drawing||!MAP_ARRANGE_DONE[mode])return;
 if(status)status.textContent='';mapArrangeButtons(true);
 try{
  const answer=await json('/labs/'+labId+'/arrange','POST',{mode,revision:drawing.revision});
  mapArrangeUndo=answer&&answer.undo?{lab:labId,revision:answer.revision}:null;
  const dialog=mapToolsEl('map-arrange-dialog');if(dialog)dialog.close();
  if(activeId===labId)await refreshMap(true);
  if(typeof notify==='function')notify(MAP_ARRANGE_DONE[mode]);
 }catch(e){
  if(e&&e.status===412){mapArrangeUndo=null;if(activeId===labId)refreshMap(true);}
  if(status)status.textContent=e&&e.message?e.message:'The devices could not be arranged.';
  mapArrangeButtons(false);
 }
}
async function mapArrangeUndoRun(){
 const undo=mapArrangeUndo,labId=activeId;if(!undo||undo.lab!==labId)return;
 try{
  await json('/labs/'+labId+'/arrange','POST',{undo:true,revision:undo.revision});
  mapArrangeUndo=null;mapToolsChip();if(activeId===labId)await refreshMap(true);
  if(typeof notify==='function')notify('Arrangement undone.');
 }catch(e){
  if(e&&e.status===412){mapArrangeUndo=null;mapToolsChip();if(activeId===labId)await refreshMap(true);}
  mapToolsSay(e&&e.message?e.message:'The arrangement could not be undone.');
  mapToolsChip();
 }
}
// ---- Wiring (element listeners only; window and document listeners live in shell.js) ----------------------------------------------
function mapToolsWire(){
 const on=(id,type,fn)=>{const el=mapToolsEl(id);if(el&&typeof el.addEventListener==='function')el.addEventListener(type,fn);};
 on('map-find','input',()=>mapFindApply());
 on('map-find','keydown',mapFindKey);
 if(map&&typeof map.addEventListener==='function'){
  map.addEventListener('pointerover',e=>mapHoverEvent(e,false));map.addEventListener('pointerout',e=>mapHoverEvent(e,true));
  map.addEventListener('focusin',e=>mapHoverEvent(e,false));map.addEventListener('focusout',e=>mapHoverEvent(e,true));
 }
 on('map-links','click',e=>{
  const t=e.target&&typeof e.target.closest==='function'?e.target:null;if(!t)return;
  if(t.closest('[data-map-link-retry]'))mapLinkRestart();
  else if(t.closest('[data-map-arrange-undo]'))mapArrangeUndoRun();
  else if(t.closest('#map-arrange-hint'))mapArrangeOpen();
 });
 on('map-picture','click',()=>{const f=mapToolsEl('map-picture-form');if(f&&f.reset)f.reset();const s=mapToolsEl('map-picture-status');if(s)s.textContent='';mapToolsEl('map-picture-dialog').showModal();});
 on('cancel-map-picture','click',()=>mapToolsEl('map-picture-dialog').close());
 on('map-picture-form','submit',e=>{e.preventDefault();mapToolsRun(mapToolsEl('map-picture-form'),mapToolsEl('map-picture-status'),mapPictureDownload);});
 on('map-drawio-export','click',()=>{const f=mapToolsEl('map-drawio-form');if(f&&f.reset)f.reset();const s=mapToolsEl('map-drawio-status');if(s)s.textContent='';mapToolsEl('map-drawio-dialog').showModal();});
 on('cancel-map-drawio','click',()=>mapToolsEl('map-drawio-dialog').close());
 on('map-drawio-form','submit',e=>{e.preventDefault();mapToolsRun(mapToolsEl('map-drawio-form'),mapToolsEl('map-drawio-status'),mapDrawioDownload);});
 on('map-arrange','click',mapArrangeOpen);
 on('cancel-map-arrange','click',()=>mapToolsEl('map-arrange-dialog').close());
 for(const mode of ['rows','columns','ring'])on('map-arrange-'+mode,'click',()=>mapArrangeRun(mode));
}
mapToolsWire();
// The page scripts run in order, but a /topology answer can land before this one has run: refreshMap then drew the map with no hook in place, and its unchanged-drawing early return would never call mapToolsRendered (no chip, no link-state poll, no Find). A drawn map (mapKey set) is drawn once more with the hooks present.
if(typeof mapKey==='string'&&mapKey&&typeof refreshMap==='function')refreshMap(true);
