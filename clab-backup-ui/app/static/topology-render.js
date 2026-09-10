'use strict';
// Pure SVG rendering: retain annotation geometry and styles in model coordinates.
function topologyDecoration(d){
 const x=d.x,y=d.y,w=d.width,h=d.height,cx=x+w/2,cy=y+h/2;
 const dash=d.borderStyle==='dashed'?'6 4':d.borderStyle==='dotted'?'2 3':'';
 const attrs=`fill="${esc(d.fillColor||'transparent')}" fill-opacity="${d.fillOpacity??.22}" stroke="${esc(d.borderColor||'#78909c')}" stroke-width="${d.borderWidth??1}" stroke-dasharray="${dash}"`;
 let content='';
 if(d.type==='text'){
  const fs=d.fontSize||14,anchor=d.textAlign==='center'?'middle':d.textAlign==='right'?'end':'start',tx=d.textAlign==='center'?cx:d.textAlign==='right'?x+w-4:x+4;
  // Text stays text: no imported HTML, CSS, or executable image content.
  content=`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${esc(d.backgroundColor||'transparent')}"/><text x="${tx}" y="${y+fs+4+(d.paragraphMargin??0)}" text-anchor="${anchor}" font-size="${fs}" font-family="${esc(d.fontFamily||'Arial')}" fill="${esc(d.fontColor||d.color||'#333')}" font-weight="${d.fontWeight||'normal'}" font-style="${d.fontStyle||'normal'}" text-decoration="${d.textDecoration||'none'}">${d.text.split('\n').map((line,i)=>`<tspan x="${tx}" dy="${i?fs*1.5:0}">${esc(line)}</tspan>`).join('')}</text>`;
 }else{
  if(d.type==='circle')content=`<ellipse cx="${cx}" cy="${cy}" rx="${w/2}" ry="${h/2}" ${attrs}/>`;
  else if(d.type==='line')content=`<line x1="${x}" y1="${y}" x2="${d.x2}" y2="${d.y2}" ${attrs}/>`;
  else content=`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${d.cornerRadius??8}" ${attrs}/>`;
  if(d.text){const pos=d.labelPosition||'top-left',anchor=pos.includes('center')?'middle':pos.includes('right')?'end':'start';const tx=anchor==='middle'?cx:anchor==='end'?x+w-10:x+10;const ty=pos.startsWith('bottom')?y+h+18:y-7;content+=`<text x="${tx}" y="${ty}" text-anchor="${anchor}" fill="${esc(d.color||'#607d8b')}" font-size="12">${esc(d.text)}</text>`;}
 }
 return `<g transform="rotate(${d.rotation||0} ${cx} ${cy})" class="topology-annotation">${content}</g>`;
}
function topologyNode(n){
 const size=40,r=size/2,color=n.iconColor||'#0066ff';
 const icon=(n.icon||'router').toLowerCase();
 const path=icon.includes('switch')?'M-13-8H13M-13 8H13M8-13L13-8L8-3M-8 3L-13 8L-8 13':icon.includes('server')||icon.includes('linux')||icon.includes('host')?'M-12-13H12V13H-12ZM-12-4H12M-12 4H12M-7-9H-3M-7 0H-3M-7 9H-3':'M-14-5H-5V-14M-9-10L-5-14L-1-10M5-14V-5H14M10-9L14-5L10-1M14 5H5V14M1 10L5 14L9 10M-5 14V5H-14M-10 1L-14 5L-10 9';
 const pos=n.labelPosition||'bottom';let tx=0,ty=r+15,anchor='middle';if(pos.includes('top'))ty=-r-9;if(pos==='left'){tx=-r-8;ty=5;anchor='end';}if(pos==='right'){tx=r+8;ty=5;anchor='start';}
 const rotation={up:0,right:90,down:180,left:270}[n.direction]||0;
 return `<g class="map-device ${n.inventory_name?'':'unmatched'}" transform="translate(${n.x+20} ${n.y+20})" data-map-id="${esc(n.id)}" ${n.inventory_name?`data-map-node="${esc(n.inventory_name)}" tabindex="0" role="button" aria-haspopup="menu" aria-label="Open ${esc(n.label)} actions"`:''}><title>${esc(n.inventory_name?'Right-click for SSH and node actions: '+n.inventory_name:'Unmatched node — no inventory connection')}</title><g transform="rotate(${rotation})"><rect class="device-body" x="${-r}" y="${-r}" width="${size}" height="${size}" rx="${n.iconCornerRadius??4}" fill="${esc(color)}"/><path d="${path}" class="device-symbol"/></g>${pos==='none'?'':`<g class="device-label"><rect class="device-label-bg" fill="${esc(n.labelBackgroundColor||'#454545')}" rx="3"/><text x="${tx}" y="${ty}" text-anchor="${anchor}">${esc(n.label)}</text></g>`}${n.inventory_name?'':`<text class="unmatched-label" y="${r+30}" text-anchor="middle">Unmatched</text>`}</g>`;
}
function topologyLink(pair,nodes,index,settings){
 const rawA=nodes.get(pair[0].node),rawB=nodes.get(pair[1].node);if(!rawA||!rawB)return '';
 const a={...rawA,x:rawA.x+20,y:rawA.y+20},b={...rawB,x:rawB.x+20,y:rawB.y+20};
 if(a.x===b.x&&a.y===b.y)return `<g class="topology-wire"><title>${esc(a.label+':'+pair[0].interface+' — '+b.label+':'+pair[1].interface)}</title><path d="M${a.x-12} ${a.y-20}C${a.x-60} ${a.y-75},${a.x+60} ${a.y-75},${a.x+12} ${a.y-20}"/></g>`;
 const dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy)||1,ux=dx/length,uy=dy/length;
 const radius=20/Math.max(Math.abs(ux),Math.abs(uy));
 const offset=Math.min(length*.45,radius+(pair[0].label_offset??settings.endpointOffset??20));
 const label=(ep,x,y)=>`<g class="interface-label"><rect rx="3"/><text x="${x}" y="${y}" text-anchor="middle">${esc(ep.interface)}</text></g>`;
 return `<g class="topology-wire" data-source="${esc(a.id)}" data-target="${esc(b.id)}"><title>${esc(a.label+':'+pair[0].interface+' — '+b.label+':'+pair[1].interface)}</title><path d="M${a.x+ux*radius} ${a.y+uy*radius}L${b.x-ux*radius} ${b.y-uy*radius}"/>${settings.labelMode==='hide'?'':label(pair[0],a.x+ux*offset,a.y+uy*offset+3)+label(pair[1],b.x-ux*offset,b.y-uy*offset+3)}</g>`;
}
function topologyMarkup(drawing){
 const nodes=new Map(drawing.nodes.map(n=>[n.id,n])),settings=drawing.settings||{},decos=[...drawing.decorations].sort((a,b)=>(a.zIndex||0)-(b.zIndex||0));
 return `<defs><pattern id="topology-grid" width="20" height="20" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".6" fill="${esc(settings.gridColor||'#d2cbb5')}"/></pattern></defs><rect x="-200000" y="-200000" width="400000" height="400000" fill="${esc(settings.background||'#fdf6e3')}"/><rect x="-200000" y="-200000" width="400000" height="400000" fill="url(#topology-grid)"/><g id="topology-scene">${decos.map(topologyDecoration).join('')}${drawing.links.map((p,i)=>topologyLink(p,nodes,i,settings)).join('')}${drawing.nodes.map(topologyNode).join('')}</g>`;
}
function measureTopology(svg){
 for(const group of svg.querySelectorAll('.device-label,.interface-label')){
  const rect=group.querySelector('rect'),box=group.querySelector('text').getBBox();
  for(const [key,value] of Object.entries({x:box.x-4,y:box.y-2,width:box.width+8,height:box.height+4}))rect.setAttribute(key,value);
 }
 const box=svg.querySelector('#topology-scene').getBBox();return [box.x-35,box.y-35,Math.max(200,box.width+70),Math.max(150,box.height+70)];
}
