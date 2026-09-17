const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({esc:value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/topology-render.js'),'utf8'),context);
test('annotation dimensions, text size and group opacity are preserved',()=>{
 const svg=context.topologyDecoration({type:'group',x:10,y:20,width:300,height:180,fillColor:'#ffaa99',fillOpacity:.4,borderWidth:2,text:'Lab',labelPosition:'bottom-center'});
 assert.match(svg,/width="300"/);assert.match(svg,/fill-opacity="0.4"/);assert.match(svg,/x="160" y="218"/);
 const text=context.topologyDecoration({type:'text',x:10,y:20,width:300,height:80,text:'<script>\nNote',fontSize:28,fontColor:'#112233',fontWeight:'bold'});
 assert.match(text,/font-size="28"/);assert.match(text,/&lt;script&gt;/);assert.doesNotMatch(text,/<script>/);
});
test('map nodes expose the exact inventory identity and imported label placement',()=>{
 const svg=context.topologyNode({id:'R1',inventory_name:'clab-lab-R1',label:'R1',x:30,y:40,labelPosition:'top'});
 assert.match(svg,/data-map-node="clab-lab-R1"/);assert.match(svg,/aria-haspopup="menu"/);assert.match(svg,/y="-29"/);
 const unbound=context.topologyNode({id:'R1',label:'R1',x:30,y:40});assert.doesNotMatch(unbound,/data-map-node=/);
});
test('endpoint labels can be hidden without removing wiring',()=>{
 const nodes=new Map([['r1',{id:'r1',label:'r1',x:0,y:0}],['r2',{id:'r2',label:'r2',x:200,y:100}]]);
 const svg=context.topologyLink([{node:'r1',interface:'eth1'},{node:'r2',interface:'eth2'}],nodes,0,{labelMode:'hide'});
 assert.match(svg,/<path/);assert.doesNotMatch(svg,/interface-label/);
});
test('coincident node coordinates do not produce invalid SVG geometry',()=>{
 const nodes=new Map([['r1',{label:'r1',x:40,y:60}],['r2',{label:'r2',x:40,y:60}]]);
 const svg=context.topologyLink([{node:'r1',interface:'eth1'},{node:'r2',interface:'eth1'}],nodes,0,{});
 assert.match(svg,/<path/);assert.doesNotMatch(svg,/NaN|Infinity/);
});
test('real lab icons use top-left annotations while links connect icon centers',()=>{
 const svg=context.topologyNode({id:'PE1',label:'PE1',x:60,y:100,inventory_name:'clab-BGP_TheoryToPractice-PE1'});
 assert.match(svg,/translate\(80 120\)/);
 const nodes=new Map([['a',{label:'a',x:60,y:100}],['b',{label:'b',x:220,y:100}]]);
 const edge=context.topologyLink([{node:'a',interface:'Gi0/0/0/3'},{node:'b',interface:'Gi0/0/0/1'}],nodes,0,{});
 assert.match(edge,/M100 120L220 120/);
});
test('state classes and colours: neutral by default, from the states map when given, CSS defaults unless the drawing sets colours',()=>{
 const plain=context.topologyNode({id:'R1',inventory_name:'clab-lab-R1',label:'R1',x:0,y:0});
 assert.match(plain,/class="map-device state-neutral"/);assert.equal((plain.match(/device-state-dot/g)||[]).length,1);assert.match(plain,/class="device-state-glyph"/);
 assert.doesNotMatch(plain,/device-body[^>]*fill=/,'the body colour comes from CSS unless imported');assert.doesNotMatch(plain,/device-label-bg[^>]*fill=/);
 assert.match(plain,/aria-label="R1"/);assert.match(plain,/<title>R1 — click to open, right-click for more actions<\/title>/);
 const ready=context.topologyNode({id:'R1',inventory_name:'clab-lab-R1',label:'R1',x:0,y:0,iconColor:'#123456',labelBackgroundColor:'#654321'},{'clab-lab-R1':'ready'});
 assert.match(ready,/class="map-device state-ready"/);assert.match(ready,/device-body[^>]*fill="#123456"/);assert.match(ready,/device-label-bg[^>]*fill="#654321"/);
 const unmatched=context.topologyNode({id:'X',label:'X',x:0,y:0},{X:'ready'});
 assert.match(unmatched,/class="map-device state-neutral unmatched"/);assert.match(unmatched,/>Not in this lab</);assert.match(unmatched,/X is drawn on the map but is not one of this lab/);
 const drawing={nodes:[{id:'a',label:'a',x:0,y:0,inventory_name:'n1'},{id:'b',label:'b',x:100,y:0}],links:[],decorations:[],settings:{}};
 const markup=context.topologyMarkup(drawing);
 assert.match(markup,/<rect class="topology-bg"/);assert.doesNotMatch(markup,/topology-bg"[^>]*fill=/);assert.doesNotMatch(markup,/#fdf6e3|#d2cbb5/);assert.doesNotMatch(markup,/topology-grid-dot"[^>]*fill=/);
 assert.match(markup,/state-neutral"[^>]*data-map-node="n1"/);
 const coloured=context.topologyMarkup({...drawing,settings:{background:'#123456',gridColor:'#abcdef'}},{n1:'attention'});
 assert.match(coloured,/topology-bg"[^>]*fill="#123456"/);assert.match(coloured,/topology-grid-dot"[^>]*fill="#abcdef"/);assert.match(coloured,/class="map-device state-attention"/);
});
test('legacy un-sized notes retain paragraph spacing inside their imported group',()=>{
 const svg=context.topologyDecoration({type:'text',x:18.9,y:-93.4,width:260,height:99,text:'Line one\nLine two\nLine three',fontSize:14,paragraphMargin:14,fontFamily:'Arial'});
 assert.match(svg,/y="-61.400000000000006"|y="-61.4"/);
 assert.match(svg,/font-family="Arial"/);
});
