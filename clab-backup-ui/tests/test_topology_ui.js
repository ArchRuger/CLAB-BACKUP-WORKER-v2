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
test('C05: impairedWires matches an end by interface or by port and returns the impaired ends; a wire impaired at both ends is one wire',()=>{
 const devices={ceos:{impairments:[{interface:'eth1',port:'Ethernet1',delay:'20ms',jitter:'5ms',loss:1.5,rate:1000,corruption:0.5}]},vsw:{impairments:[{interface:'eth3',port:'Ethernet3',delay:'',jitter:'',loss:10,rate:0,corruption:0}]}};
 const wires=[
  {ends:[{node:'ceos',label:'ceos',interface:'eth1'},{node:'vsw',label:'vsw',interface:'eth1'}]},
  {ends:[{node:'ceos',label:'ceos',interface:'Ethernet1'},{node:'vsw',label:'vsw',interface:'Ethernet3'}]},
  {ends:[{node:'vsw',label:'vsw',interface:'eth2'},{node:'other',label:'other',interface:'eth1'}]},
 ];
 const found=context.impairedWires(wires,devices);
 assert.deepEqual([...found.map(f=>f.index)],[0,1],'by interface name and by port name');
 assert.deepEqual(JSON.parse(JSON.stringify(found[0].ends.map(e=>[e.side,e.node,e.port]))),[[0,'ceos','Ethernet1']]);
 assert.equal(found[0].text,'impaired at ceos Ethernet1 (traffic leaving ceos): delay 20ms, jitter 5ms, loss 1.5%, rate 1000 kbit, corruption 0.5%');
 assert.deepEqual([...found[1].ends.map(e=>e.side)],[0,1],'both ends of one wire');assert.match(found[1].text,/; vsw Ethernet3 \(traffic leaving vsw\): loss 10%$/);
 assert.equal(context.impairedWires(wires,{}).length,0);assert.equal(context.impairedWires(null,null).length,0);
 assert.equal(context.impairmentSummary({delay:'0ms',jitter:'',loss:0,rate:0,corruption:0}),'','zero values say nothing');
});
test('C05: a wire keeps its endpoints in data-capture-endpoints and gains no impairment attribute from the badge (data-link-ends is device-only)',()=>{
 const nodes=new Map([['a',{id:'a',label:'a',inventory_name:'clab-x-a',x:0,y:0}],['b',{id:'b',label:'b',inventory_name:'clab-x-b',x:200,y:0}]]);
 const svg=context.topologyLink([{node:'a',interface:'eth1'},{node:'b',interface:'eth1'}],nodes,0,{});
 assert.match(svg,/data-capture-endpoints="\[\{&quot;node&quot;:&quot;clab-x-a&quot;,&quot;label&quot;:&quot;a&quot;,&quot;interface&quot;:&quot;eth1&quot;\}/);assert.doesNotMatch(svg,/impaired/);assert.match(svg,/data-link-ends="clab-x-a\|clab-x-b"/,'the one device-only data-link-ends contract: interfaces are read from data-capture-endpoints');
});
test('C05: every stroke rule on a topology wire path excludes the capture hit area, so an impaired link still opens Capture',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8');
 const rules=[...css.matchAll(/([^{}]*\.topology-wire[^{}]*)\{([^{}]*)\}/g)].filter(m=>/stroke/.test(m[2]));
 assert.ok(rules.some(m=>/\.impaired/.test(m[1])),'the impaired rule exists');
 for(const m of rules)for(const selector of m[1].split(',').map(x=>x.trim()).filter(x=>/path/.test(x)))assert.match(selector,/path:not\(\.capture-hit\)/,selector+' must exclude path.capture-hit');
 assert.match(css,/path\.capture-hit \{ stroke: transparent; stroke-width: 16; pointer-events: stroke; \}/);
});
const links=(settings={},fan=0,nodes)=>{const map=nodes||new Map([['a',{id:'a',label:'a',inventory_name:'n-a',x:0,y:0}],['b',{id:'b',label:'b',inventory_name:'n-b',x:200,y:0}]]);return context.topologyLink([{node:'a',interface:'eth1'},{node:'b',interface:'eth2'}],map,0,settings,fan);};
const pathsOf=svg=>[...svg.matchAll(/<path d="([^"]+)"\/>/g)].map(m=>m[1]);
test('C06: every wire carries data-link-ends (devices only), data-base (the title) and data-aria-base (the accessible name), the self-link too',()=>{
 const svg=links();
 assert.match(svg,/data-link-ends="n-a\|n-b"/);assert.match(svg,/data-base="a:eth1 — b:eth2"/);assert.match(svg,/<title>a:eth1 — b:eth2<\/title>/);
 assert.match(svg,/aria-label="Capture a:eth1 to b:eth2"/);assert.match(svg,/data-aria-base="Capture a:eth1 to b:eth2"/);
 assert.doesNotMatch(svg.match(/data-link-ends="[^"]*"/)[0],/eth/);
 const unmatched=links({},0,new Map([['a',{id:'m1',label:'a',x:0,y:0}],['b',{id:'m2',label:'b',inventory_name:'n-b',x:200,y:0}]]));
 assert.match(unmatched,/data-link-ends="#m1\|n-b"/,'an unmatched drawing node is #<map id>');
 const self=context.topologyLink([{node:'a',interface:'e1'},{node:'a',interface:'e2'}],new Map([['a',{id:'a',label:'a',inventory_name:'n-a',x:0,y:0}]]),0,{});
 assert.match(self,/data-link-ends="n-a\|n-a"/);assert.match(self,/data-base="a:e1 — a:e2"/);assert.match(self,/data-aria-base="Capture a:e1 to a:e2"/);
 const hostile=links({},0,new Map([['a',{id:'a"><x',label:'<i>',x:0,y:0}],['b',{id:'b',label:'b',inventory_name:'n-b',x:200,y:0}]]));
 assert.doesNotMatch(hostile,/<i>|"><x/);
});
test('C06: elbow links run along the longer axis first, keep the capture hit twin and rotate the labels on vertical runs',()=>{
 const level=links({linkStyle:'elbow'});
 assert.deepEqual(pathsOf(level),['M40 20H120V20H200']);assert.equal((level.match(/class="capture-hit"/g)||[]).length,1);
 const bent=links({linkStyle:'elbow'},0,new Map([['a',{id:'a',label:'a',x:0,y:0}],['b',{id:'b',label:'b',x:200,y:100}]]));
 assert.deepEqual(pathsOf(bent),['M40 20H120V120H200']);assert.match(bent,/class="capture-hit" d="M40 20H120V120H200"/);assert.doesNotMatch(bent,/rotate/);
 const tall=links({linkStyle:'elbow'},0,new Map([['a',{id:'a',label:'a',x:0,y:0}],['b',{id:'b',label:'b',x:60,y:300}]]));
 assert.deepEqual(pathsOf(tall),['M20 40V170H80V300']);assert.equal((tall.match(/transform="rotate\(-90 /g)||[]).length,2,'both labels sit on vertical runs');assert.doesNotMatch(tall,/NaN|Infinity/);
 const back=links({linkStyle:'elbow'},0,new Map([['a',{id:'a',label:'a',x:200,y:100}],['b',{id:'b',label:'b',x:0,y:0}]]));
 assert.deepEqual(pathsOf(back),['M200 120H120V20H40']);
 const self=context.topologyLink([{node:'a',interface:'e1'},{node:'a',interface:'e2'}],new Map([['a',{id:'a',label:'a',x:0,y:0}]]),0,{linkStyle:'elbow'});
 assert.match(self,/C/,'the self-link stays a loop');assert.equal((self.match(/class="capture-hit"/g)||[]).length,1);
});
test('C06: parallel links between the same two devices fan out by 12 px, whichever way each is listed; a lone link is untouched',()=>{
 const make=reversed=>({nodes:[{id:'a',label:'a',x:0,y:0},{id:'b',label:'b',x:200,y:0}],links:[[{node:'a',interface:'e1'},{node:'b',interface:'e1'}],reversed?[{node:'b',interface:'e2'},{node:'a',interface:'e2'}]:[{node:'a',interface:'e2'},{node:'b',interface:'e2'}]],decorations:[],settings:{}});
 const ys=d=>[...context.topologyMarkup(d).matchAll(/<path d="M[\d.]+ ([\d.-]+)L/g)].map(m=>Number(m[1]));
 assert.deepEqual(ys(make(false)),[14,26]);assert.deepEqual(ys(make(true)),[14,26],'a reversed listing lands on its own physical side');
 assert.match(context.topologyMarkup({...make(false),links:[make(false).links[0]]}),/M40 20L200 20/);
 const elbow=context.topologyMarkup({...make(false),settings:{linkStyle:'elbow'}});
 assert.equal(new Set([...elbow.matchAll(/<path d="(M[^"]+)"\/>/g)].map(m=>m[1])).size,2,'elbow links separate too');
 assert.match(links(),/M40 20L200 20/);
});
test('C06: boxed nodes draw an 80 px box (64 narrow) with the name inside, middle-truncated, the badge at its corner and the wire on its outline',()=>{
 const node=(label,opts)=>context.topologyNode({id:'R1',inventory_name:'n-R1',label,x:0,y:0,labelPosition:'top'},{},opts);
 const wide=node('router-one-long-name',{nodeStyle:'boxed'});
 assert.match(wide,/<rect class="device-box" x="-40" y="-40" width="80" height="80" rx="10"\/>/);assert.match(wide,/class="device-label device-label-boxed"/);
 assert.match(wide,/<text x="0" y="36" text-anchor="middle">route…name<\/text>/,'ten characters, cut in the middle; the label position is ignored');
 assert.match(wide,/aria-label="router-one-long-name"/);assert.match(wide,/<title>router-one-long-name — click/);assert.match(wide,/class="device-state-badge" transform="translate\(12 -12\)"/);
 const narrow=node('router-one-long-name',{nodeStyle:'boxed',boxSpacing:'narrow'});
 assert.match(narrow,/width="64" height="64" rx="8"/);assert.match(narrow,/>rout…ame</);assert.match(narrow,/translate\(4 -4\)/);
 assert.doesNotMatch(node('R1',{}),/device-box|device-label-boxed|device-state-badge/,'the icon style is unchanged');
 assert.equal(context.mapBoxedLabel('abc',10),'abc');assert.equal(context.mapBoxedLabel('abcdefghij',10),'abcdefghij');assert.equal(context.mapBoxedLabel('abcdefghijk',10),'abcde…hijk');
 const nodes=new Map([['a',{id:'a',label:'a',x:0,y:0,labelPosition:'right'}],['b',{id:'b',label:'b',x:300,y:0}]]);
 assert.match(links({nodeStyle:'boxed'},0,nodes),/M60 20L280 20/,'the wire meets the outline at radius 40');
 assert.match(links({nodeStyle:'boxed',boxSpacing:'narrow'},0,nodes),/M52 20L288 20/);
 const markup=context.topologyMarkup({nodes:[{id:'a',label:'a',x:0,y:0,inventory_name:'n'}],links:[],decorations:[],settings:{nodeStyle:'boxed'}});
 assert.match(markup,/device-box/);
});
test('C06: arrowheads are triangles in the line colour, the line stops at the base, sizes follow lineArrowSize, and a plain line is unchanged',()=>{
 const line=extra=>context.topologyDecoration({type:'line',x:0,y:0,width:100,height:0,x2:100,y2:0,borderColor:'#112233',...extra},0);
 assert.match(line({}),/<line x1="0" y1="0" x2="100" y2="0" /);assert.doesNotMatch(line({}),/polygon/);
 const end=line({lineEndArrow:true});
 assert.equal((end.match(/<polygon/g)||[]).length,1);assert.match(end,/x2="90"/);assert.match(end,/points="100,0 90,-4 90,4"/);assert.match(end,/class="line-arrow" points="[^"]+" fill="#112233"/);
 const both=line({lineStartArrow:true,lineEndArrow:true,lineArrowSize:20});
 assert.equal((both.match(/<polygon/g)||[]).length,2);assert.match(both,/x1="20" y1="0" x2="80"/);assert.match(both,/points="0,0 20,8 20,-8"/);
 assert.equal((line({lineStartArrow:true}).match(/<polygon/g)||[]).length,1);assert.match(line({lineStartArrow:true}),/x1="10"/);
 assert.doesNotMatch(line({lineEndArrow:'yes'}),/polygon/,'only true draws a head');
 assert.doesNotMatch(context.topologyDecoration({type:'line',x:5,y:5,width:0,height:0,x2:5,y2:5,lineEndArrow:true},0),/NaN|polygon/,'a zero-length line has no head');
});
test('C06: text backgrounds are rounded unless roundedBackground is false; groups order by zIndex, level, then nesting',()=>{
 const text=extra=>context.topologyDecoration({type:'text',x:0,y:0,width:100,height:40,text:'n',...extra},0);
 assert.match(text({}),/<rect x="0" y="0" width="100" height="40" rx="6"/);assert.match(text({roundedBackground:true}),/ rx="6"/);assert.doesNotMatch(text({roundedBackground:false}),/ rx="6"/);
 const g=(id,x,y,w,h,extra)=>({type:'group',id,x,y,width:w,height:h,text:id,...extra});
 const order=list=>[...context.topologyDecorationOrder(list)].map(o=>o.d.id);
 assert.deepEqual(order([g('inner',10,10,50,50),g('outer',0,0,200,200)]),['outer','inner'],'a nested group is drawn after the group it sits in');
 assert.deepEqual(order([g('hi',0,0,50,50,{level:3}),g('lo',100,0,50,50,{level:1}),g('mid',200,0,50,50,{level:2})]),['lo','mid','hi']);
 assert.deepEqual(order([g('a',0,0,50,50),g('b',100,0,50,50)]),['a','b'],'document order breaks ties');
 assert.deepEqual(order([g('g',0,0,50,50,{zIndex:-1}),{type:'text',id:'t',x:0,y:0,width:5,height:5,text:'t',zIndex:-2}]),['t','g'],'zIndex still comes first');
 const all=context.topologyMarkup({nodes:[],links:[],decorations:[g('inner',10,10,50,50),g('outer',0,0,200,200)],settings:{}});
 assert.ok(all.indexOf('data-decoration-index="1"')<all.indexOf('data-decoration-index="0"'),'the outer group (index 1) is in the markup first');
});
test('C06: the container glyph is a box with a lid, host stays the server glyph, and the editor icon list offers both',()=>{
 const glyph=icon=>/<path d="([^"]+)" class="device-symbol"/.exec(context.topologyNode({id:'x',label:'x',x:0,y:0,icon}))[1];
 assert.equal(glyph('container'),'M-13-9H13V13H-13ZM-13-3H13M-6-9V-13H6V-9');assert.notEqual(glyph('container'),glyph('router'));assert.equal(glyph('host'),glyph('server'));
 const page=fs.readFileSync(path.join(__dirname,'../app/static/map-editor-page.js'),'utf8');
 assert.match(page,/\['host','Host'\]/);assert.match(page,/\['container','Container'\]/);
});
test('C06: renderer CSS for link state and hover excludes the capture hit area; down is red dotted and written after the impaired rule',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8');
 const rules=[...css.matchAll(/([^{}]*\.topology-wire[^{}]*)\{([^{}]*)\}/g)].filter(m=>/stroke/.test(m[2]));
 const down=rules.find(m=>/\.link-down/.test(m[1])&&/stroke-dasharray: 2 4/.test(m[2]));assert.ok(down,'link-down rule');
 assert.match(down[2],/stroke: var\(--danger\)/);assert.match(down[2],/stroke-width: 3/);
 assert.ok(css.indexOf(down[0])>css.indexOf('.topology-wire.impaired path:not(.capture-hit)'),'down is written after impaired');
 assert.ok(rules.some(m=>/\.hover/.test(m[1])));
 for(const m of rules)for(const selector of m[1].split(',').map(x=>x.trim()).filter(x=>/path/.test(x)))assert.match(selector,/path:not\(\.capture-hit\)/,selector);
 assert.match(css,/\.map-device\.dimmed, \.topology-wire\.dimmed \{ opacity: \.25; \}/);assert.match(css,/\.device-box \{/);assert.ok(css.indexOf('.device-label.device-label-boxed text')>css.indexOf('.device-label text {'),'the boxed name rule is written after the generic label rule, or the name draws white on white');
});
