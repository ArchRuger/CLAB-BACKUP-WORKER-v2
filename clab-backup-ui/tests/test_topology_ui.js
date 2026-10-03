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
test('the four corner label positions sit diagonally off the icon, anchored away from it (item 6)',()=>{
 const at=pos=>{const svg=context.topologyNode({id:'R1',inventory_name:'clab-lab-R1',label:'R1',x:0,y:0,labelPosition:pos});const m=/<text x="(-?\d+)" y="(-?\d+)" text-anchor="(\w+)">R1<\/text>/.exec(svg);return m?[Number(m[1]),Number(m[2]),m[3]]:null;};
 assert.deepEqual(at('top-left'),[-14,-29,'end']);assert.deepEqual(at('top-right'),[14,-29,'start']);
 assert.deepEqual(at('bottom-left'),[-14,35,'end']);assert.deepEqual(at('bottom-right'),[14,35,'start']);
 assert.deepEqual(at('bottom'),[0,35,'middle']);assert.deepEqual(at('top'),[0,-29,'middle']);assert.deepEqual(at('left'),[-28,5,'end']);assert.deepEqual(at('right'),[28,5,'start']);
 assert.deepEqual(at('sideways'),[0,35,'middle'],'an unknown value draws at the bottom, like the editor');
});
test('a centred label sits over the icon, on a near-opaque background, with no clearance for any wire',()=>{
 const svg=context.topologyNode({id:'R1',inventory_name:'clab-lab-R1',label:'R1',x:0,y:0,labelPosition:'center'});
 assert.match(svg,/<text x="0" y="5" text-anchor="middle">R1<\/text>/);assert.match(svg,/class="device-label device-label-center"/);
 assert.match(fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8'),/\.device-label-bg \{ fill-opacity: \.9[2-9]/,'the label box is near-opaque');
 const clear=(dx,dy)=>{const nodes=new Map([['a',{id:'a',label:'a-long-device-name',x:0,y:0,labelPosition:'center'}],['b',{id:'b',label:'b',x:dx,y:dy}]]);return Number(/<text x="(-?[\d.]+)" y="(-?[\d.]+)"/.exec(context.topologyLink([{node:'a',interface:'e1'},{node:'b',interface:'e1'}],nodes,0,{}))[1]);};
 assert.equal(context.topologyLabelClearance({label:'x',labelPosition:'center'},0,1),0);assert.equal(context.topologyLabelClearance({label:'x',labelPosition:'center'},1,0),0);
 assert.equal(clear(300,0),60);
});
test('a preview draws a file, not a lab: no device is a button or "Not in this lab", a device only the map file names is captioned so, and the state badge is absent (item 8)',()=>{
 const inFile=context.topologyNode({id:'R1',label:'R1',x:0,y:0,in_topology:true},{},{preview:true});
 assert.doesNotMatch(inFile,/unmatched|Not in this lab|role="button"|data-map-node|device-state-dot/);assert.match(inFile,/<title>R1<\/title>/);
 const mapOnly=context.topologyNode({id:'ghost',label:'ghost',x:0,y:0,in_topology:false},{},{preview:true});
 assert.match(mapOnly,/class="map-device state-neutral unmatched"/);assert.match(mapOnly,/>Not in the topology file</);assert.doesNotMatch(mapOnly,/Not in this lab|role="button"/);
 const labMap=context.topologyNode({id:'R1',label:'R1',x:0,y:0,in_topology:true},{});
 assert.match(labMap,/unmatched/);assert.match(labMap,/>Not in this lab</,'without preview the inventory binding still decides');
 const whole=context.topologyMarkup({nodes:[{id:'a',label:'a',x:0,y:0,in_topology:true}],links:[],decorations:[]},{},{preview:true});
 assert.doesNotMatch(whole,/Not in this lab|role="button"/);
});
test('the device glyph follows the editor\'s icon names: switches, servers, computers, else the router arrows (item 8)',()=>{
 const glyph=icon=>/<path d="([^"]+)" class="device-symbol"/.exec(context.topologyNode({id:'x',label:'x',x:0,y:0,icon}))[1];
 assert.equal(glyph('leaf'),glyph('switch'));assert.equal(glyph('spine'),glyph('switch'));assert.equal(glyph('bridge'),glyph('switch'));
 assert.equal(glyph('server'),glyph('linux'));assert.equal(glyph('client'),glyph('ue'));assert.equal(glyph('client'),glyph('controller'));
 assert.notEqual(glyph('client'),glyph('server'));assert.notEqual(glyph('client'),glyph('pe'));assert.equal(glyph('pe'),glyph('router'));assert.equal(glyph('dcgw'),glyph('router'));assert.equal(glyph(undefined),glyph('router'));
});
test('an interface label clears the device label that sits in the wire\'s way, and nothing else moves (item 8)',()=>{
 const y=(pos,dy)=>{const nodes=new Map([['a',{id:'a',label:'a',x:0,y:0,labelPosition:pos}],['b',{id:'b',label:'b',x:0,y:dy}]]);const svg=context.topologyLink([{node:'a',interface:'eth1'},{node:'b',interface:'eth1'}],nodes,0,{});return [...svg.matchAll(/<text x="(-?[\d.]+)" y="(-?[\d.]+)" text-anchor="middle">eth1/g)].map(m=>[Number(m[1]),Number(m[2])]);};
 const [downBottom,upperEnd]=y('bottom',300);
 assert.deepEqual([downBottom,upperEnd],[[20,81],[20,283]],'a wire going down from a bottom label: its label starts 18 px further; the other end (label at the bottom, wire arriving from above) is untouched');
 assert.deepEqual(y('top',300)[0],[20,63],'a wire going down past a top label is not in its way');
 assert.deepEqual(y('bottom',-300)[0],[20,-17],'a wire going up from a bottom label is not in its way');
 assert.deepEqual(y('top',-300)[0],[20,-35],'a wire going up from a top label clears it');
 const side=(pos,dx)=>{const nodes=new Map([['a',{id:'a',label:'name',x:0,y:0,labelPosition:pos}],['b',{id:'b',label:'b',x:dx,y:0}]]);const svg=context.topologyLink([{node:'a',interface:'e1'},{node:'b',interface:'e1'}],nodes,0,{});return Number(/<text x="(-?[\d.]+)"/.exec(svg)[1]);};
 assert.equal(side('right',300),60+Math.min(90,4*6.6+12),'a wire going right past a right label clears the label\'s width');assert.equal(side('left',300),60);
 assert.equal(side('bottom-right',300),60,'a corner label is not met by a wire leaving sideways');
 const corner=(pos,dx,dy)=>{const nodes=new Map([['a',{id:'a',label:'a',x:0,y:0,labelPosition:pos}],['b',{id:'b',label:'b',x:dx,y:dy}]]);const m=/<text x="(-?[\d.]+)" y="(-?[\d.]+)"/.exec(context.topologyLink([{node:'a',interface:'e1'},{node:'b',interface:'e1'}],nodes,0,{}));return [Number(m[1]),Number(m[2])];};
 assert.ok(corner('bottom-right',300,300)[0]>20+Math.SQRT1_2*(20/Math.SQRT1_2+20),'a wire leaving diagonally towards a corner label clears it');
 assert.deepEqual(corner('top-right',40,-120).map(Math.round),[38,-31],'a wire leaving almost straight up, a little to the right, meets a top-right label and clears it (capped at 45% of a short wire)');
 assert.deepEqual(corner('top-right',-40,-120).map(Math.round),[7,-16],'the same wire leaning left passes beside the label: no clearance');
 assert.deepEqual(corner('top-right',-120,-40).map(Math.round),[-19,10],'a wire leaving to the upper left, mostly sideways, is clear of a top-right label');
 assert.deepEqual(corner('bottom-left',0,300),[20,81],'a wire straight down meets a bottom-left label');
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
