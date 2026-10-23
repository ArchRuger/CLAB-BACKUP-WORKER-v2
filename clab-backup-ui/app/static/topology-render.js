'use strict';
// Pure SVG rendering: retain annotation geometry and styles in model coordinates. Colours the drawing
// does not define come from CSS (a fill attribute is emitted only for an imported value, so imported
// maps still look as drawn), and a device's state is a class the caller swaps afterwards
// (renderMapState in topology.js) — the markup is never rebuilt for a state change.
// A line with arrowheads (lineStartArrow, lineEndArrow, lineArrowSize): a filled triangle whose tip is the line's end and whose base is
// `size` back along the line, in the line's border colour; the line itself stops at the base so the tip is sharp.
function topologyLine(d,attrs){
 let x1=d.x,y1=d.y,x2=d.x2,y2=d.y2;
 const start=d.lineStartArrow===true,end=d.lineEndArrow===true,length=Math.hypot(x2-x1,y2-y1);
 if(!(start||end)||!(length>0))return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${attrs}/>`;
 const size=Math.min(Number(d.lineArrowSize)||10,length/((start?1:0)+(end?1:0))),ux=(x2-x1)/length,uy=(y2-y1)/length,half=size*.4,fill=esc(d.borderColor||'#78909c');
 const head=(tx,ty,dx,dy)=>`<polygon class="line-arrow" points="${tx},${ty} ${tx+dx*size-dy*half},${ty+dy*size+dx*half} ${tx+dx*size+dy*half},${ty+dy*size-dx*half}" fill="${fill}"/>`;
 let heads='';
 if(end){heads+=head(x2,y2,-ux,-uy);x2-=ux*size;y2-=uy*size;}
 if(start){heads+=head(d.x,d.y,ux,uy);x1+=ux*size;y1+=uy*size;}
 return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${attrs}/>${heads}`;
}
function topologyDecoration(d,index){
 const x=d.x,y=d.y,w=d.width,h=d.height,cx=x+w/2,cy=y+h/2;
 const dash=d.borderStyle==='dashed'?'6 4':d.borderStyle==='dotted'?'2 3':'';
 const attrs=`fill="${esc(d.fillColor||'transparent')}" fill-opacity="${d.fillOpacity??.22}" stroke="${esc(d.borderColor||'#78909c')}" stroke-width="${d.borderWidth??1}" stroke-dasharray="${dash}"`;
 let content='';
 if(d.type==='text'){
  const fs=d.fontSize||14,anchor=d.textAlign==='center'?'middle':d.textAlign==='right'?'end':'start',tx=d.textAlign==='center'?cx:d.textAlign==='right'?x+w-4:x+4;
  // Text stays text: no imported HTML, CSS, or executable image content.
  content=`<rect x="${x}" y="${y}" width="${w}" height="${h}"${d.roundedBackground===false?'':' rx="6"'} fill="${esc(d.backgroundColor||'transparent')}" fill-opacity="${d.fillOpacity??1}"/><text x="${tx}" y="${y+fs+4+(d.paragraphMargin??0)}" text-anchor="${anchor}" font-size="${fs}" font-family="${esc(d.fontFamily||'Arial')}" fill="${esc(d.fontColor||d.color||'#333')}" font-weight="${d.fontWeight||'normal'}" font-style="${d.fontStyle||'normal'}" text-decoration="${d.textDecoration||'none'}">${d.text.split('\n').map((line,i)=>`<tspan x="${tx}" dy="${i?fs*1.5:0}">${esc(line)}</tspan>`).join('')}</text>`;
 }else{
  if(d.type==='circle')content=`<ellipse cx="${cx}" cy="${cy}" rx="${w/2}" ry="${h/2}" ${attrs}/>`;
  else if(d.type==='line')content=topologyLine(d,attrs);
  else content=`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${d.cornerRadius??8}" ${attrs}/>`;
  if(d.text){const pos=d.labelPosition||'top-left',anchor=pos.includes('center')?'middle':pos.includes('right')?'end':'start';const tx=anchor==='middle'?cx:anchor==='end'?x+w-10:x+10;const ty=pos.startsWith('bottom')?y+h+18:y-7;content+=`<text x="${tx}" y="${ty}" text-anchor="${anchor}" fill="${esc(d.color||'#607d8b')}" font-size="${d.fontSize||12}" font-weight="${d.fontWeight||'normal'}">${esc(d.text)}</text>`;}
 }
 return `<g transform="rotate(${d.rotation||0} ${cx} ${cy})" class="topology-annotation" data-decoration-index="${index}">${content}</g>`;
}
// The state badge on a device: a dot at the body's top-right corner and one glyph per state. Every
// glyph is always in the markup; CSS shows the one matching the state-* class (check = ready,
// arc = starting or working, bang = attention or credentials, hollow = unavailable or neutral).
const TOPOLOGY_STATE_BADGE='<circle class="device-state-dot" cx="24" cy="-24" r="7"/><g class="device-state-glyph" transform="translate(24 -24)" aria-hidden="true"><path class="glyph-check" d="M-3.2 .2 -1 2.4 3.4-2.2"/><path class="glyph-arc" d="M0-3.6A3.6 3.6 0 1 1-3.1 1.8"/><path class="glyph-bang" d="M0-3.4V.6M0 2.4v.4"/><circle class="glyph-hollow" r="3.2"/></g>';
// The device glyph for the editor's icon names: switches (switch, leaf, spine, bridge), servers, computers
// (client, user equipment, controller: a screen on a stand), everything else the router's arrows.
function topologyGlyph(icon){
 const name=String(icon||'router').toLowerCase();
 if(/container/.test(name))return 'M-13-9H13V13H-13ZM-13-3H13M-6-9V-13H6V-9';
 if(/switch|leaf|spine|bridge/.test(name))return 'M-13-8H13M-13 8H13M8-13L13-8L8-3M-8 3L-13 8L-8 13';
 if(/server|linux|host/.test(name))return 'M-12-13H12V13H-12ZM-12-4H12M-12 4H12M-7-9H-3M-7 0H-3M-7 9H-3';
 if(/client|^ue$|controller|pc|laptop/.test(name))return 'M-13-11H13V6H-13ZM-6 12H6M0 6V12';
 return 'M-14-5H-5V-14M-9-10L-5-14L-1-10M5-14V-5H14M10-9L14-5L10-1M14 5H5V14M1 10L5 14L9 10M-5 14V5H-14M-10 1L-14 5L-10 9';
}
// Boxed node style (viewerSettings.nodeStyle 'boxed'): a square of 80 px around the 40 px icon (boxSpacing 'narrow': 64) with the name
// inside it; a link attaches to the box outline. topologyHalf is the distance from a node's centre to the outline a link leaves from.
function topologyHalf(settings){return settings&&settings.nodeStyle==='boxed'?(settings.boxSpacing==='narrow'?32:40):20;}
// The name inside a box, cut in the middle when it is longer than `max` characters (the full name stays in the title and the accessible name).
function mapBoxedLabel(text,max){
 const s=String(text??''),m=Math.max(3,max|0);if(s.length<=m)return s;
 const keep=m-1,head=Math.ceil(keep/2),tail=keep-head;return s.slice(0,head)+'…'+s.slice(s.length-tail);
}
// options.preview: the drawing is a file being looked at (the Topology file dialog's preview), not a lab's map.
// There is no inventory to match devices against, so a device is "in" when the topology file names it
// (in_topology, set by the parse endpoint) and nothing is drawn as a button or captioned "Not in this lab".
function topologyNode(n,states={},options={}){
 const preview=!!options.preview;
 const boxed=options.nodeStyle==='boxed',narrow=boxed&&options.boxSpacing==='narrow',half=topologyHalf({nodeStyle:options.nodeStyle,boxSpacing:options.boxSpacing});
 const size=40,r=size/2,matched=preview?n.in_topology!==false:!!n.inventory_name,state=(matched&&!preview&&states&&states[n.inventory_name])||'neutral';
 const icon=(n.icon||'router').toLowerCase();
 const path=topologyGlyph(icon);
 // Label placement, the editor's values: bottom (default), top, left, right, center (over the icon) and the four corners, where the
 // label sits diagonally off the icon's corner so a link leaving the icon's side never covers the name.
 const pos=n.labelPosition||'bottom';let tx=0,ty=r+15,anchor='middle';if(pos.includes('top'))ty=-r-9;if(pos==='left'){tx=-r-8;ty=5;anchor='end';}if(pos==='right'){tx=r+8;ty=5;anchor='start';}
 // center: the name sits over the icon (vertically centred on its middle); the default background is already near-opaque (style.css .device-label-bg).
 if(pos==='center'){tx=0;ty=5;anchor='middle';}
 if(pos.endsWith('-left')){tx=-r+6;anchor='end';}if(pos.endsWith('-right')){tx=r-6;anchor='start';}
 const rotation={up:0,right:90,down:180,left:270}[n.direction]||0;
 const label=String(n.label??n.id??'');
 const caption=preview?'Not in the topology file':'Not in this lab';
 const title=preview?(matched?label:`${label} is in the map file but not in the topology file`):matched?`${label} — click to open, right-click for more actions`:`${label} is drawn on the map but is not one of this lab's devices`;
 return `<g class="map-device state-${esc(state)}${matched?'':' unmatched'}" transform="translate(${n.x+20} ${n.y+20})" data-map-id="${esc(n.id)}" data-label="${esc(label)}" ${matched&&!preview?`data-map-node="${esc(n.inventory_name)}" tabindex="0" role="button" aria-haspopup="menu" aria-label="${esc(label)}"`:''}><title>${esc(title)}</title>${boxed?`<rect class="device-box" x="${-half}" y="${-half}" width="${half*2}" height="${half*2}" rx="${narrow?8:10}"/>`:''}<g transform="rotate(${rotation})"><rect class="device-body" x="${-r}" y="${-r}" width="${size}" height="${size}" rx="${n.iconCornerRadius??4}"${n.iconColor?` fill="${esc(n.iconColor)}"`:''}/><path d="${path}" class="device-symbol"/></g>${boxed?`<g class="device-label device-label-boxed"><rect class="device-label-bg" rx="3"/><text x="0" y="${half-4}" text-anchor="middle">${esc(mapBoxedLabel(label,narrow?8:10))}</text></g>`:pos==='none'?'':`<g class="device-label${pos==='center'?' device-label-center':''}"><rect class="device-label-bg"${n.labelBackgroundColor?` fill="${esc(n.labelBackgroundColor)}"`:''} rx="3"/><text x="${tx}" y="${ty}" text-anchor="${anchor}">${esc(label)}</text></g>`}${matched?'':`<text class="unmatched-label" y="${boxed?half+14:r+30}" text-anchor="middle">${caption}</text>`}${preview?'':boxed?`<g class="device-state-badge" transform="translate(${half-28} ${28-half})">${TOPOLOGY_STATE_BADGE}</g>`:TOPOLOGY_STATE_BADGE}</g>`;
}
// How far past the icon a wire leaving a device in direction (ux,uy) has to go before its interface label
// clears the device's own label: the label's height when it sits on that side (bottom, top), its width
// when it sits left or right; a corner label is met only by a wire leaving diagonally towards it.
function topologyLabelClearance(n,ux,uy){
 const pos=n.labelPosition||'bottom';if(pos==='none'||pos==='center')return 0;
 const text=String(n.label??n.id??''),width=Math.min(90,text.length*6.6+12);
 const toward={bottom:uy>.6,top:uy<-.6,left:ux<-.6,right:ux>.6}[pos];
 if(toward!==undefined)return toward?(pos==='bottom'||pos==='top'?18:width):0;
 // A corner label hangs off the icon's side: a wire leaving on that side (up for top-*, down for bottom-*) meets it
 // unless it clearly heads away from the corner horizontally.
 const vertical=pos.startsWith('top')?uy<-.5:uy>.5,horizontal=pos.endsWith('left')?ux<.3:ux>-.3;
 return vertical&&horizontal?18:0;
}
// How far a line leaving the centre of a square of half-width `half` along (ux,uy), displaced sideways by (sx,sy), runs before it leaves the square.
function topologyExit(ux,uy,sx,sy,half){
 const t=(u,o)=>Math.abs(u)>1e-9?(half-Math.sign(u)*o)/Math.abs(u):Infinity;
 return Math.max(0,Math.min(t(ux,sx),t(uy,sy)));
}
// `fan` is the sideways shift (px, along this link's own normal) that separates parallel links between the same two devices; the caller
// (topologyMarkup) gives each extra link 12 px. Straight links shift the whole line; elbow links shift the middle run and the two end runs.
function topologyLink(pair,nodes,index,settings,fan=0){
 const rawA=nodes.get(pair[0].node),rawB=nodes.get(pair[1].node);if(!rawA||!rawB)return '';
 const half=topologyHalf(settings),boxed=half>20,elbow=settings.linkStyle==='elbow';
 const ends=pair.map((ep,i)=>({node:[rawA,rawB][i].inventory_name||'',label:[rawA,rawB][i].label,interface:ep.interface}));
 const captureAttrs=`data-capture-endpoints="${esc(JSON.stringify(ends))}" tabindex="0" role="button" aria-label="Capture ${esc(ends.map(e=>e.label+':'+e.interface).join(' to '))}"`;
 const wirePath=d=>`<path class="capture-hit" d="${d}"/><path d="${d}"/>`;
 const a={...rawA,x:rawA.x+20,y:rawA.y+20},b={...rawB,x:rawB.x+20,y:rawB.y+20};
 // The wire's own words: data-base is its title, data-aria-base its accessible name, data-link-ends the two devices (device-only: the
 // inventory name, or #<map id> for a drawing node that is not a lab device) for Find and hover; interfaces stay in data-capture-endpoints.
 const base=a.label+':'+pair[0].interface+' — '+b.label+':'+pair[1].interface;
 const words=`data-link-ends="${esc((rawA.inventory_name||'#'+String(rawA.id??''))+'|'+(rawB.inventory_name||'#'+String(rawB.id??'')))}" data-base="${esc(base)}" data-aria-base="Capture ${esc(ends.map(e=>e.label+':'+e.interface).join(' to '))}"`;
 if(a.x===b.x&&a.y===b.y)return `<g class="topology-wire" ${captureAttrs} ${words}><title>${esc(base)}</title>${wirePath(`M${a.x-12} ${a.y-half}C${a.x-60} ${a.y-half-55},${a.x+60} ${a.y-half-55},${a.x+12} ${a.y-half}`)}</g>`;
 const dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy)||1,ux=dx/length,uy=dy/length;
 const label=(ep,x,cy,rotate)=>`<g class="interface-label"${rotate?` transform="rotate(-90 ${x} ${cy})"`:''}><rect rx="3"/><text x="${x}" y="${cy+3}" text-anchor="middle">${esc(ep.interface)}</text></g>`;
 const distance=pair[0].label_offset??settings.endpointOffset??20,hide=settings.labelMode==='hide';
 const clearance=(raw,x,y)=>boxed?0:topologyLabelClearance(raw,x,y);
 const open=`<g class="topology-wire" ${captureAttrs} ${words} data-source="${esc(a.id)}" data-target="${esc(b.id)}"><title>${esc(base)}</title>`;
 if(elbow){
  // One bend: along the longer axis first, so the first and last runs leave the icon (or box) on the side that faces the other device.
  const horizontal=Math.abs(dx)>=Math.abs(dy),sdx=dx<0?-1:1,sdy=dy<0?-1:1;
  if(horizontal){
   const shift=fan*sdx,ay=a.y+shift,by=b.y+shift,ax=a.x+sdx*half,bx=b.x-sdx*half,mx=(ax+bx)/2+shift;
   const dA=Math.min(half+clearance(rawA,sdx,0)+distance,Math.max(half+4,Math.abs(mx-a.x)-4)),dB=Math.min(half+clearance(rawB,-sdx,0)+distance,Math.max(half+4,Math.abs(mx-b.x)-4));
   return open+wirePath(`M${ax} ${ay}H${mx}V${by}H${bx}`)+(hide?'':label(pair[0],a.x+sdx*dA,ay)+label(pair[1],b.x-sdx*dB,by))+'</g>';
  }
  const shift=-fan*sdy,ax=a.x+shift,bx=b.x+shift,ay=a.y+sdy*half,by=b.y-sdy*half,my=(ay+by)/2+shift;
  const dA=Math.min(half+clearance(rawA,0,sdy)+distance,Math.max(half+4,Math.abs(my-a.y)-4)),dB=Math.min(half+clearance(rawB,0,-sdy)+distance,Math.max(half+4,Math.abs(my-b.y)-4));
  return open+wirePath(`M${ax} ${ay}V${my}H${bx}V${by}`)+(hide?'':label(pair[0],ax,a.y+sdy*dA,true)+label(pair[1],bx,b.y-sdy*dB,true))+'</g>';
 }
 const sx=-uy*fan,sy=ux*fan;
 const radiusA=fan?topologyExit(ux,uy,sx,sy,half):half/Math.max(Math.abs(ux),Math.abs(uy)),radiusB=fan?topologyExit(-ux,-uy,sx,sy,half):radiusA;
 // Each end's interface label sits past the icon and, when the device's own label is in the wire's way, past that label too.
 const offsetA=Math.min(length*.45,radiusA+clearance(rawA,ux,uy)+distance),offsetB=Math.min(length*.45,radiusB+clearance(rawB,-ux,-uy)+distance);
 return open+wirePath(`M${a.x+sx+ux*radiusA} ${a.y+sy+uy*radiusA}L${b.x+sx-ux*radiusB} ${b.y+sy-uy*radiusB}`)+(hide?'':label(pair[0],a.x+sx+ux*offsetA,a.y+sy+uy*offsetA)+label(pair[1],b.x+sx-ux*offsetB,b.y+sy-uy*offsetB))+'</g>';
}
// Parallel links between one pair of devices fan out by 12 px per extra link (centred), the same physical side whichever way a link is listed.
function topologyFans(links){
 const groups=new Map();
 links.forEach((p,i)=>{const x=String(p[0].node),y=String(p[1].node),key=x<y?x+'\n'+y:y+'\n'+x;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(i);});
 const fans=new Array(links.length).fill(0);
 for(const list of groups.values()){
  if(list.length<2)continue;
  list.forEach((i,rank)=>{const p=links[i];if(p[0].node===p[1].node)return;fans[i]=(rank-(list.length-1)/2)*12*(String(p[0].node)<String(p[1].node)?1:-1);});
 }
 return fans;
}
// Groups: lower zIndex first, then a higher `level`, then a group nested inside another group's bounds after the group it sits in, then document order.
// Everything that is not a group ranks with a level-1 group that is not nested, so maps without levels keep their old order.
function topologyDecorationOrder(list){
 const groups=list.filter(d=>d.type==='group');
 const inside=(d,g)=>d!==g&&d.x>=g.x&&d.y>=g.y&&d.x+d.width<=g.x+g.width&&d.y+d.height<=g.y+g.height&&!(d.x===g.x&&d.y===g.y&&d.width===g.width&&d.height===g.height);
 const rank=d=>d.type!=='group'?1000:(d.level||1)*1000+groups.filter(g=>inside(d,g)).length;
 return list.map((d,i)=>({d,i,z:d.zIndex||0,k:rank(d)})).sort((p,q)=>p.z-q.z||p.k-q.k||p.i-q.i);
}
// states: optional {inventory_name: state key}; callers without live state (the editor, the deploy
// preview) pass nothing and every device is neutral. Background and grid colours are attributes only
// when the drawing defines them, so the page's own surface shows through otherwise.
function topologyMarkup(drawing,states={},options={}){
 const nodes=new Map(drawing.nodes.map(n=>[n.id,n])),settings=drawing.settings||{},decos=topologyDecorationOrder(drawing.decorations),fans=topologyFans(drawing.links),nodeOptions={...options,nodeStyle:settings.nodeStyle,boxSpacing:settings.boxSpacing};
 return `<defs><pattern id="topology-grid" width="20" height="20" patternUnits="userSpaceOnUse"><circle class="topology-grid-dot" cx="1" cy="1" r=".6"${settings.gridColor?` fill="${esc(settings.gridColor)}"`:''}/></pattern></defs><rect class="topology-bg" x="-200000" y="-200000" width="400000" height="400000"${settings.background?` fill="${esc(settings.background)}"`:''}/><rect class="topology-grid" x="-200000" y="-200000" width="400000" height="400000" fill="url(#topology-grid)"/><g id="topology-scene">${decos.map(({d,i})=>topologyDecoration(d,i)).join('')}${drawing.links.map((p,i)=>topologyLink(p,nodes,i,settings,fans[i])).join('')}${drawing.nodes.map(n=>topologyNode(n,states,nodeOptions)).join('')}</g>`;
}
function measureTopology(svg){
 for(const group of svg.querySelectorAll('.device-label,.interface-label')){
  const rect=group.querySelector('rect'),box=group.querySelector('text').getBBox();
  for(const [key,value] of Object.entries({x:box.x-4,y:box.y-2,width:box.width+8,height:box.height+4}))rect.setAttribute(key,value);
 }
 const box=svg.querySelector('#topology-scene').getBBox();return [box.x-35,box.y-35,Math.max(200,box.width+70),Math.max(150,box.height+70)];
}
// Impairments on the map (C05 4.3). Pure: which wires carry a configured impairment, from the wires' own endpoints (the
// data-capture-endpoints JSON: [{node, label, interface}]) and the manager's answer (`devices`: {node: {impairments: [{interface,
// port, delay, jitter, loss, rate, corruption}]}}). An end is impaired when its device matches the node name and its interface equals
// the row's interface or its port; the impairment acts on traffic leaving that end's device.
function impairmentSummary(row){
 const parts=[];
 if(row.delay&&row.delay!=='0ms')parts.push('delay '+row.delay);
 if(row.jitter&&row.jitter!=='0ms')parts.push('jitter '+row.jitter);
 if(Number(row.loss)>0)parts.push('loss '+row.loss+'%');
 if(Number(row.rate)>0)parts.push('rate '+row.rate+' kbit');
 if(Number(row.corruption)>0)parts.push('corruption '+row.corruption+'%');
 return parts.join(', ');
}
function impairedWires(wires,devices){
 const found=[],byNode=devices&&typeof devices==='object'?devices:{};
 (wires||[]).forEach((wire,index)=>{
  const ends=[];
  (wire&&Array.isArray(wire.ends)?wire.ends:[]).forEach((end,side)=>{
   const device=end&&byNode[end.node];
   const row=device&&Array.isArray(device.impairments)?device.impairments.find(r=>r&&(r.interface===end.interface||r.port===end.interface)):null;
   if(!row)return;
   const label=String(end.label||end.node||''),port=String(row.port||row.interface||end.interface||'');
   ends.push({side,node:end.node,label,interface:end.interface,port,summary:impairmentSummary(row)});
  });
  if(ends.length)found.push({index,ends,text:'impaired at '+ends.map(e=>`${e.label} ${e.port} (traffic leaving ${e.label})${e.summary?': '+e.summary:''}`).join('; ')});
 });
 return found;
}
