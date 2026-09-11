'use strict';
function diagramAnnotation(type,x=0,y=0){return {type,text:type==='text'?'New text':'',x,y,width:type==='text'?240:200,height:type==='text'?70:120,x2:x+200,y2:y+120,
 fillColor:'#79e8f6',fillOpacity:.22,borderColor:'#416377',borderWidth:2,borderStyle:'solid',cornerRadius:8,color:'#416377',labelPosition:'top-left',
 fontSize:18,fontColor:'#193340',fontFamily:'Arial',fontWeight:'normal',fontStyle:'normal',textDecoration:'none',textAlign:'left',backgroundColor:'transparent',paragraphMargin:0,rotation:0,zIndex:type==='text'?1:-1};}
function diagramPayload(drawing){return {positions:Object.fromEntries(drawing.nodes.map(n=>[n.id,[n.x,n.y]])),decorations:drawing.decorations,revision:drawing.revision};}
function diagramMove(item,dx,dy){
 const x=Math.max(-100000,Math.min(100000,Math.round(item.x+dx))),y=Math.max(-100000,Math.min(100000,Math.round(item.y+dy)));
 if(item.type==='line'){item.x2=Math.max(-100000,Math.min(100000,item.x2+x-item.x));item.y2=Math.max(-100000,Math.min(100000,item.y2+y-item.y));}
 item.x=x;item.y=y;
}
async function editDiagram(id){
 let drawing=await(await api('/labs/'+id+'/topology')).json();if(!drawing)throw new Error('Import a topology map first.');
 const dialog=opDialog('op-layout-editor','Edit topology diagram',`<p>Add text, boxes, circles and lines. Select an item to edit its appearance or drag it on the canvas. Save keeps changes in this manager. Download JSON to reuse annotations with your VM topology; draw.io exports an editable diagram.</p>
 <div class="diagram-toolbar"><button class="button secondary" data-add-shape="text">Add text</button><button class="button secondary" data-add-shape="rectangle">Add box</button><button class="button secondary" data-add-shape="circle">Add circle</button><button class="button secondary" data-add-shape="line">Add line</button><button class="button secondary" id="diagram-undo" disabled>Undo</button><button class="button secondary" id="diagram-fit">Fit diagram</button></div>
 <div class="diagram-workspace"><svg id="op-layout-map" class="topology-map op-layout-map" aria-label="Editable lab topology"></svg>
 <form id="diagram-properties" class="diagram-properties"><label>Select item<select id="diagram-selection"></select></label><p id="diagram-empty">Select an item on the canvas or add an annotation.</p>
 <fieldset id="diagram-fields" disabled><legend>Selected item</legend><div class="diagram-fields"><label>X<input data-prop="x" type="number" min="-100000" max="100000" step="any"></label><label>Y<input data-prop="y" type="number" min="-100000" max="100000" step="any"></label></div>
 <div id="diagram-annotation-fields"><label>Text / label<textarea data-prop="text" maxlength="4000" rows="3"></textarea></label>
 <div class="diagram-fields"><label>Width<input data-prop="width" type="number" min="1" max="100000" step="any"></label><label>Height<input data-prop="height" type="number" min="1" max="100000" step="any"></label><label>End X<input data-prop="x2" type="number" min="-100000" max="100000" step="any"></label><label>End Y<input data-prop="y2" type="number" min="-100000" max="100000" step="any"></label><label>Font size<input data-prop="fontSize" type="number" min="6" max="160" step="any"></label><label>Text color<input data-prop="fontColor" type="color"></label><label>Fill color<input data-prop="fillColor" type="color"></label><label>Fill opacity<input data-prop="fillOpacity" type="number" min="0" max="1" step=".05"></label><label>Border color<input data-prop="borderColor" type="color"></label><label>Border width<input data-prop="borderWidth" type="number" min="0" max="20" step="any"></label></div>
 <label>Border style<select data-prop="borderStyle"><option>solid</option><option>dashed</option><option>dotted</option><option>double</option></select></label><label>Text alignment<select data-prop="textAlign"><option>left</option><option>center</option><option>right</option></select></label><label>Font weight<select data-prop="fontWeight"><option>normal</option><option>bold</option></select></label>
 <button type="button" class="button danger-outline" id="diagram-delete">Remove annotation</button></div></fieldset></form></div>
 <p id="diagram-state" role="status">No unsaved changes.</p><div id="diagram-discard" hidden><p>Discard unsaved diagram changes?</p><button class="button secondary" id="diagram-keep">Keep editing</button><button class="button danger-outline" id="diagram-discard-confirm">Discard changes</button></div>
 <div class="dialog-actions"><button class="button secondary" id="diagram-cancel">Cancel</button><button class="button secondary" id="op-layout-json">Download annotations JSON</button><button class="button secondary" id="op-layout-export">Export draw.io</button><button class="button primary" id="op-layout-save">Save diagram</button></div>`);
 const svg=$('op-layout-map'),history=[];let selected='',bounds=null,drag=null,dirty=false;
 const item=()=>selected.startsWith('n:')?drawing.nodes[Number(selected.slice(2))]:selected.startsWith('a:')?drawing.decorations[Number(selected.slice(2))]:null;
 const changed=()=>{dirty=true;$('diagram-state').textContent='Unsaved changes';$('diagram-undo').disabled=!history.length;};
 const checkpoint=()=>{history.push(JSON.stringify(drawing));if(history.length>30)history.shift();changed();};
 const properties=()=>{
  const n=item(),annotation=selected.startsWith('a:');$('diagram-fields').disabled=!n;$('diagram-empty').hidden=!!n;$('diagram-annotation-fields').hidden=!annotation;
  $('diagram-selection').innerHTML='<option value="">Choose an item</option>'+drawing.nodes.map((n,i)=>`<option value="n:${i}">Node: ${esc(n.label||n.alias)}</option>`).join('')+drawing.decorations.map((d,i)=>`<option value="a:${i}">${esc(d.type)}: ${esc(d.text?.slice(0,50)||'Annotation '+(i+1))}</option>`).join('');
  $('diagram-selection').value=selected;
  dialog.querySelectorAll('[data-prop]').forEach(input=>{
   const key=input.dataset.prop;let value=n?.[key]??'';
   if(input.type==='color'&&!/^#[a-f\d]{6}$/i.test(value))value='#416377';
   input.value=value;input.closest('label').hidden=annotation&&((['x2','y2'].includes(key)&&n.type!=='line')||(['width','height'].includes(key)&&n.type==='line')||(['borderColor','borderWidth','borderStyle'].includes(key)&&n.type==='text'));
  });
 };
 const render=()=>{
  svg.innerHTML=topologyMarkup(drawing);svg.querySelectorAll('[data-map-id]').forEach((el,i)=>{el.removeAttribute('aria-haspopup');el.dataset.diagramNode=String(i);el.classList.toggle('diagram-selected',selected==='n:'+i);el.querySelector('title').textContent='Select or drag to reposition';});
  svg.querySelectorAll('[data-decoration-index]').forEach(el=>el.classList.toggle('diagram-selected',selected==='a:'+el.dataset.decorationIndex));
  const measured=measureTopology(svg);if(!bounds)bounds=measured;svg.setAttribute('viewBox',bounds.join(' '));
 };
 const choose=value=>{selected=value;properties();render();};
 $('diagram-selection').onchange=e=>choose(e.target.value);
 $('diagram-properties').onsubmit=e=>e.preventDefault();
 dialog.querySelectorAll('[data-prop]').forEach(input=>input.oninput=input.onchange=()=>{
  const n=item();if(!n||!input.checkValidity())return;
  const key=input.dataset.prop,value=input.type==='number'?Number(input.value):input.value;
  if(input.type==='number'&&(!input.value||!Number.isFinite(value)))return;
  if(n[key]===value)return;
  checkpoint();if(key==='x'||key==='y')diagramMove(n,key==='x'?value-n.x:0,key==='y'?value-n.y:0);else n[key]=value;
  if(key==='fontColor')n.color=value;
  if(key==='fillColor'&&n.type==='text')n.backgroundColor=value;
  if(key==='textAlign'&&n.type!=='text')n.labelPosition=(n.labelPosition||'top-left').replace(/left|center|right/,value);
  if(n.type==='text'&&['text','fontSize'].includes(key))n.height=Math.max(n.height,n.text.split('\n').length*n.fontSize*1.5+8);
  render();
 });
 dialog.querySelectorAll('[data-add-shape]').forEach(button=>button.onclick=()=>{
  if(drawing.decorations.length>=2000){notify('The diagram supports at most 2000 annotations.');return;}
  checkpoint();drawing.decorations.push(diagramAnnotation(button.dataset.addShape,Math.round(bounds[0]+bounds[2]/2-100),Math.round(bounds[1]+bounds[3]/2-60)));choose('a:'+(drawing.decorations.length-1));
 });
 $('diagram-delete').onclick=()=>{if(!selected.startsWith('a:'))return;checkpoint();drawing.decorations.splice(Number(selected.slice(2)),1);choose('');};
 $('diagram-undo').onclick=()=>{if(!history.length)return;drawing=JSON.parse(history.pop());changed();choose('');};
 $('diagram-fit').onclick=()=>{bounds=null;render();};
 const point=e=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());};
 svg.onpointerdown=e=>{
  if(e.button!==0)return;const el=e.target.closest('[data-map-id],[data-decoration-index]');if(!el)return;
  const value=el.hasAttribute('data-map-id')?'n:'+el.dataset.diagramNode:'a:'+el.dataset.decorationIndex,p=point(e);choose(value);
  drag={p,original:{...item()},snapshot:JSON.stringify(drawing),moved:false};e.preventDefault();svg.setPointerCapture(e.pointerId);
 };
 svg.onpointermove=e=>{if(!drag)return;const p=point(e),n=item();if(Math.abs(p.x-drag.p.x)+Math.abs(p.y-drag.p.y)<1&&!drag.moved)return;
  drag.moved=true;Object.assign(n,drag.original);diagramMove(n,p.x-drag.p.x,p.y-drag.p.y);render();};
 const release=()=>{if(!drag)return;if(drag.moved){history.push(drag.snapshot);if(history.length>30)history.shift();changed();}drag=null;properties();};
 svg.onpointerup=release;svg.onpointercancel=release;svg.onlostpointercapture=release;
 const close=()=>{if(dirty){$('diagram-discard').hidden=false;$('diagram-keep').focus();}else dialog.close();};
 dialog.querySelector('[data-op-close]').onclick=close;$('diagram-cancel').onclick=close;
 dialog.oncancel=e=>{e.preventDefault();close();};$('diagram-keep').onclick=()=>$('diagram-discard').hidden=true;$('diagram-discard-confirm').onclick=()=>dialog.close();
 const payload=()=>{if(!$('diagram-properties').reportValidity())throw new Error('Correct the highlighted diagram field.');return diagramPayload(drawing);};
 const download=async(kind,fallback)=>{const response=await api('/labs/'+id+'/'+kind,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=attachmentName(response,fallback);a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 $('op-layout-export').onclick=()=>opTask(dialog,()=>download('drawio','topology.drawio'));
 $('op-layout-json').onclick=()=>opTask(dialog,()=>download('annotations','topology.annotations.json'));
 $('op-layout-save').onclick=()=>opTask(dialog,async()=>{await json('/labs/'+id+'/layout','PUT',payload());dirty=false;dialog.close();if(typeof refreshMap==='function'&&id===activeId)await refreshMap(true);notify('Diagram saved.');});
 render();properties();
}
