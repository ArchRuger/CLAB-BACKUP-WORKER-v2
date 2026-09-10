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
