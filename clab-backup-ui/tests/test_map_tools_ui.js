// map-tools.js (C06): link state (matcher, wire words, chip, poll), Find, link hover, Download picture, Export to draw.io and Arrange
// devices with its Undo. The DOM is a small fake tree (just what the production script touches); topology.js and
// device-diagnostics.js load into the same context, as on the page, so mapWireText and diagPollNext are the real ones.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const src=name=>fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8');
class El{
 constructor(tag='div',attrs={}){this.tagName=tag;this.localName=tag;this.attrs={...attrs};this.children=[];this.parentNode=null;this.hidden=false;this.disabled=false;this.value='';this.checked=false;this.open=false;this.listeners={};this.text='';this.html='';this.focused=0;this.id=attrs.id||'';
  const self=this;this.classList={add:c=>self._cls(l=>l.add(c)),remove:c=>self._cls(l=>l.delete(c)),contains:c=>self._list().includes(c),toggle(c,force){const on=force===undefined?!self._list().includes(c):!!force;self._cls(l=>on?l.add(c):l.delete(c));return on;}};}
 _list(){return String(this.attrs.class||'').split(/\s+/).filter(Boolean);}
 _cls(fn){const set=new Set(this._list());fn(set);if(set.size)this.attrs.class=[...set].join(' ');else delete this.attrs.class;}
 get textContent(){return this.children.length&&!this.text?this.children.map(c=>c.textContent).join(''):this.text;}
 set textContent(v){this.text=String(v);this.children=[];}
 get innerHTML(){return this.html;}set innerHTML(v){this.html=String(v);}
 get dataset(){const o={};for(const [k,v] of Object.entries(this.attrs))if(k.startsWith('data-'))o[k.slice(5).replace(/-(\w)/g,(_,c)=>c.toUpperCase())]=v;return o;}
 getAttribute(n){return n in this.attrs?this.attrs[n]:null;}setAttribute(n,v){this.attrs[n]=String(v);}removeAttribute(n){delete this.attrs[n];}getAttributeNames(){return Object.keys(this.attrs);}
 append(...kids){for(const k of kids){k.parentNode=this;this.children.push(k);}return this;}
 removeChild(k){this.children=this.children.filter(c=>c!==k);k.parentNode=null;}
 all(){const out=[];for(const c of this.children){out.push(c,...c.all());}return out;}
 querySelectorAll(sel){const all=this.all();if(sel==='*')return all;return all.filter(e=>e.is(sel));}
 querySelector(sel){return this.querySelectorAll(sel)[0]||null;}
 is(sel){return sel.split(',').some(s=>{s=s.trim();if(s.startsWith('.'))return this._list().includes(s.slice(1));if(s.startsWith('#'))return this.attrs.id===s.slice(1);if(s.startsWith('['))return s.slice(1,-1)in this.attrs;return this.tagName===s;});}
 closest(sel){for(let e=this;e;e=e.parentNode)if(e.is(sel))return e;return null;}
 contains(o){for(let e=o;e;e=e.parentNode)if(e===this)return true;return false;}
 cloneNode(){const c=new El(this.tagName,this.attrs);c.text=this.text;for(const k of this.children)c.append(k.cloneNode());return c;}
 addEventListener(t,fn){(this.listeners[t]=this.listeners[t]||[]).push(fn);}
 fire(t,e={}){const ev={target:this,preventDefault(){ev.prevented=true;},stopPropagation(){ev.stopped=true;},...e};for(const fn of this.listeners[t]||[])fn(ev);return ev;}
 focus(){this.focused++;}showModal(){this.open=true;}close(){this.open=false;}reset(){}click(){this.clicked=(this.clicked||0)+1;}remove(){}
}
const dev=(id,label,name,x,y,extra={})=>new El('g',{class:'map-device state-ready','data-map-id':id,'data-label':label,...(name?{'data-map-node':name}:{}),transform:`translate(${x} ${y})`,...extra});
const wire=(a,b,ia,ib,ends)=>{const g=new El('g',{class:'topology-wire','data-link-ends':ends,'data-base':`${a}:${ia} — ${b}:${ib}`,'data-aria-base':`Capture ${a}:${ia} to ${b}:${ib}`,'aria-label':`Capture ${a}:${ia} to ${b}:${ib}`,'data-capture-endpoints':'[]'});const t=new El('title');t.text=`${a}:${ia} — ${b}:${ib}`;g.append(t,new El('path',{class:'capture-hit',d:'M0 0'}),new El('path',{d:'M0 0'}));return g;};
const drawing=(over={})=>({revision:'r1',placed:true,nodes:[{id:'1',label:'a',inventory_name:'a'},{id:'2',label:'b',inventory_name:'b'},{id:'3',label:'x',inventory_name:null},{id:'4',label:'c',inventory_name:'c'}],
 links:[[{node:'1',interface:'eth1',capture_interface:'eth1'},{node:'2',interface:'Ethernet1',capture_interface:'eth1'}],[{node:'2',interface:'ge-0/0/1',capture_interface:'eth2'},{node:'3',interface:'e1'}],[{node:'1',interface:'eth2',capture_interface:'eth2'},{node:'4',interface:'eth1',capture_interface:'eth1'}]],decorations:[],...over});
const row=(name,state='up',extra={})=>({name,alias:'',state,port:'',role:'data',...extra});
const answer=(over={})=>({available:true,devices:{a:{listed:true,interfaces:[row('eth1'),row('eth2')]},b:{listed:true,interfaces:[row('eth1',"up",{port:'Ethernet1'}),row('eth2','up',{port:'ge-0/0/1'})]},c:{listed:true,interfaces:[row('eth1')]}},listed:3,of:3,fetched_at:1,...over});
function harness({dw=drawing(),status='Running',deployment_name='lab-x',tab='topology',visible=true,drawnBefore=false}={}){
 const els=new Map(),$=id=>{if(!els.has(id))els.set(id,new El('div',{id}));return els.get(id);};
 const svg=new El('svg',{id:'topology-map'});els.set('topology-map',svg);
 const bg=new El('rect',{class:'topology-bg'}),grid=new El('rect',{class:'topology-grid'}),scene=new El('g',{id:'topology-scene'});
 svg.append(bg,grid,scene);
 const labs=[{id:'L1',name:'Lab: 1',deployment_name,deployment:{status},nodes:[{name:'a',address:'10.0.0.1',platform:'ceos'},{name:'b',address:'10.0.0.2',platform:'junos'},{name:'c',address:'10.0.0.3',platform:'ceos'}]}];
 const timers=[],requests=[],clock={t:1700000000000},downloads=[],handlers=[],docSpy=[];
 for(const m of ['rows','columns','ring']){const b=$('map-arrange-'+m);b.attrs['data-arrange']=m;b.text=m[0].toUpperCase()+m.slice(1);$('map-arrange-dialog').append(b);}
 const nodeMenu=$('node-context-menu');nodeMenu.hidden=true;
 const document={activeElement:null,body:new El('body'),addEventListener(n){docSpy.push(n);},querySelector:()=>null,querySelectorAll:()=>[],createElement:t=>{const e=new El(t);e.click=function(){downloads.push({name:this.download,href:this.href});};return e;}};
 const ctx={$,esc,document,window:{innerWidth:1366,innerHeight:768,addEventListener(){}},console,JSON,Blob,URLSearchParams,Math,Promise,Set,Map,Object,Array,String,Number,Error,RegExp,
  state:{labs,discovery:{connected:true},platforms:{ceos:{label:'Arista cEOS'},junos:{label:'Juniper'}}},activeId:'L1',tab,
  setTimeout:(fn,ms)=>{timers.push({fn,ms,live:true});return timers.length;},clearTimeout:id=>{if(timers[id-1])timers[id-1].live=false;},
  Date:class extends Date{static now(){return clock.t;}constructor(...a){super(...(a.length?a:[clock.t]));}},
  busy:()=>false,openDetails(){},handleNodeAction(){},closeMenus:()=>false,syncProxies(){},
  pageVisible:()=>ctx.visible,visible,
  URL:{createObjectURL:b=>{ctx.blobs.push(b);return 'blob:x';},revokeObjectURL(){}},blobs:[],
  XMLSerializer:class{serializeToString(e){return e.__ser();}},
  notify(m){ctx.toasts.push(m);},toasts:[],
  attachmentName:(r,f)=>{const m=(r.headers.get('Content-Disposition')||'').match(/filename="([^"]+)"/);return m?m[1]:f;},
  api:async url=>{requests.push(url);const h=handlers.find(h=>url.startsWith(h.prefix));if(!h)throw Object.assign(new Error('no handler '+url),{status:500});return h.fn(url);},
  json:async(p,m,d)=>{requests.push(p);ctx.posts.push({p,m,d});const h=handlers.find(h=>p.startsWith(h.prefix));if(!h)throw Object.assign(new Error('no handler '+p),{status:500});return h.fn(p,d);},posts:[],
  refreshMap:async()=>{ctx.refreshes++;},refreshes:0,
  topologyMarkup:()=>'',measureTopology:()=>[0,0,1000,600]};
 const context=vm.createContext(ctx);
 ctx.current=()=>ctx.state.labs.find(l=>l.id===ctx.activeId);
 vm.runInContext(src('status.js'),context);
 vm.runInContext(src('device-diagnostics.js'),context);
 vm.runInContext(src('topology.js'),context);
 ctx.refreshMap=async force=>{ctx.refreshes++;ctx.refreshForce=force;};
 if(drawnBefore)vm.runInContext("mapKey='L1'+JSON.stringify({})",context);
 const docBefore=docSpy.length;
 vm.runInContext(src('map-tools.js'),context,{filename:'map-tools.js'});
 const h={context,$,svg,scene,timers,requests,clock,downloads,labs,docSpy,docAdded:docSpy.length-docBefore,
  on(prefix,fn){handlers.unshift({prefix,fn});},
  get:n=>vm.runInContext(n,context),
  live:()=>timers.filter(t=>t.live),
  async fire(){const t=h.live()[0];assert.ok(t,'a timer is waiting');t.live=false;t.fn();await tick();await tick();},
  render(d=dw){
   scene.children=[];
   const w=[];
   for(const l of d.links){const [p,q]=l,na=d.nodes.find(n=>n.id===p.node),nb=d.nodes.find(n=>n.id===q.node);
    w.push(wire(na.label,nb.label,p.interface,q.interface,(na.inventory_name||'#'+na.id)+'|'+(nb.inventory_name||'#'+nb.id)));}
   scene.append(...w,...d.nodes.map((n,i)=>dev(n.id,n.label,n.inventory_name,i*100,20)));
   $('map-status').textContent='caption';
   svg.hidden=false;context.mapToolsRendered(d);return w;
  }};
 return h;
}
const rt=v=>v===undefined?v:JSON.parse(JSON.stringify(v));
const same=(a,b,m)=>assert.deepEqual(rt(a),rt(b),m);
const tick=()=>new Promise(r=>setImmediate(r));
const classes=el=>el.attrs.class||'';

test('mapLinkStates: up, down with the state word, missing, not-running, unknown; alias, port and capture_interface land; an unmatched node is never down',()=>{
 const h=harness(),d=drawing();
 const r=h.context.mapLinkStates(d,answer());
 same(r.wires.map(w=>w.state),['up','unknown','up']);
 same(r.counts,{up:2,down:0,unknown:1});
 assert.equal(r.wires[0].ends[1].end,'up','Ethernet1 lands through port');
 const down=h.context.mapLinkStates(d,answer({devices:{...answer().devices,b:{listed:true,interfaces:[row('eth1','dormant',{port:'Ethernet1'})]}}}));
 assert.equal(down.wires[0].state,'down');assert.equal(down.wires[0].ends[1].state,'dormant');
 const missing=h.context.mapLinkStates(d,answer({devices:{...answer().devices,b:{listed:true,interfaces:[]}}}));
 assert.equal(missing.wires[0].ends[1].end,'missing');assert.equal(missing.wires[0].state,'down');
 const off=h.context.mapLinkStates(d,answer({devices:{...answer().devices,c:{listed:false,interfaces:[]}}}));
 assert.equal(off.wires[2].ends[1].end,'not-running');assert.equal(off.wires[2].state,'down');
 const unavailable=h.context.mapLinkStates(d,{available:false});
 same(unavailable.counts,{up:0,down:0,unknown:3});
 const capture=h.context.mapLinkStates({nodes:d.nodes,links:[[{node:'1',interface:'Ethernet9',capture_interface:'eth1'},{node:'4',interface:'eth1'}]]},answer());
 assert.equal(capture.wires[0].state,'up','capture_interface matches the listed name');
 const skip=h.context.mapLinkStates({nodes:d.nodes,links:[[{node:'1',interface:'eth1'},{node:'99',interface:'eth1'}]]},answer());
 assert.equal(skip.wires.length,0,'a link the renderer cannot draw is not counted');
});

test('wire clauses: one down end named, both ends in one state worded once, two states both named, missing and not running, up and the VM wording',()=>{
 const h=harness(),c=h.context;
 const end=(label,interface_,e,state='',vm=false)=>({label,interface:interface_,end:e,state,vm});
 assert.equal(c.mapLinkClause({state:'down',ends:[end('vrt','ge-0/0/1','down','dormant'),end('cjunos','et-0/0/0','up')]}),'down: vrt ge-0/0/1 is dormant');
 assert.equal(c.mapLinkClause({state:'down',ends:[end('a','e1','down','dormant'),end('b','e2','down','dormant')]}),'down at both ends (dormant: one side may be shut down)');
 assert.equal(c.mapLinkClause({state:'down',ends:[end('vrt','ge-0/0/1','down','dormant'),end('cjunos','et-0/0/0','down','down')]}),'down: vrt ge-0/0/1 is dormant · cjunos et-0/0/0 is down');
 assert.equal(c.mapLinkClause({state:'down',ends:[end('a','e1','up'),end('cjunos','et-0/0/0','missing')]}),'down: cjunos et-0/0/0 is missing on the device');
 assert.equal(c.mapLinkClause({state:'down',ends:[end('ceos','e1','not-running'),end('b','e2','up')]}),'down: ceos is not running');
 assert.equal(c.mapLinkClause({state:'up',ends:[end('a','e1','up'),end('b','e2','up')]}),'up');
 assert.equal(c.mapLinkClause({state:'up',ends:[end('a','e1','up'),end('vsw','e2','up','',true)]}),"connected (the VM's link to vsw; a port shut down inside vsw may not show here)");
 assert.equal(c.mapLinkClause({state:'unknown',ends:[end('a','e1','unknown')]}),'');
 assert.equal(c.mapLinkChipText({up:5,down:0,unknown:0},false),'Links: 5 up');
 assert.equal(c.mapLinkChipText({up:4,down:1,unknown:2},false),'Links: 4 up · 1 down · 2 not checked');
 assert.equal(c.mapLinkChipText({up:4,down:1,unknown:0},true),'Links: 4 connected · 1 down');
 assert.equal(c.mapLinkChipText({up:0,down:0,unknown:0},false),'');
});

test('mapLinkApply toggles only link-up and link-down, writes data-state-text, leaves impaired alone and mapWireText joins both clauses',()=>{
 const h=harness();const wires=h.render();
 wires[0].setAttribute('data-impaired-text','impaired at a eth1 (traffic leaving a): delay 20ms');wires[0].classList.add('impaired');
 h.context.mapLinkApply(answer());
 assert.ok(wires[0].classList.contains('link-up')&&wires[0].classList.contains('impaired'));
 assert.equal(wires[0].getAttribute('data-impaired-text').startsWith('impaired at a'),true);
 assert.equal(wires[0].querySelector('title').textContent,'a:eth1 — b:Ethernet1 · up · impaired at a eth1 (traffic leaving a): delay 20ms');
 assert.equal(wires[0].getAttribute('aria-label'),'Capture a:eth1 to b:Ethernet1 · up · impaired at a eth1 (traffic leaving a): delay 20ms','the accessible name keeps its "to"');
 assert.equal(wires[1].getAttribute('data-state-text'),null,'an unknown wire has no clause');assert.equal(classes(wires[1]),'topology-wire');
 h.context.mapLinkApply(answer({devices:{...answer().devices,b:{listed:true,interfaces:[row('eth1','dormant',{port:'Ethernet1'})]}}}),'14:02');
 assert.ok(wires[0].classList.contains('link-down')&&!wires[0].classList.contains('link-up'));
 assert.equal(wires[0].getAttribute('data-state-text'),'down: b Ethernet1 is dormant (as of 14:02)');
 h.context.mapLinkClear();
 assert.equal(wires[0].getAttribute('data-state-text'),null);assert.ok(wires[0].classList.contains('impaired'),'clearing link state never drops the impairment');
 assert.equal(wires[0].querySelector('title').textContent,'a:eth1 — b:Ethernet1 · impaired at a eth1 (traffic leaving a): delay 20ms');
});

test('the poll: one fetch on the first render, the chip words, the legend, and 10 s after each of two successes (plan.floor)',async()=>{
 const h=harness();h.on('/operations/link-state',async()=>({json:async()=>answer()}));
 h.render();
 assert.equal(h.live().length,1);assert.equal(h.live()[0].ms,0,'the first fetch is immediate');
 h.context.mapLinkSchedule();h.context.mapLinkSchedule();assert.equal(h.live().length,1,'schedule is idempotent');
 await h.fire();
 assert.equal(h.requests.length,1);assert.match(h.requests[0],/^\/operations\/link-state\?lab_id=L1$/);
 assert.equal(h.live()[0].ms,10000);
 const chip=h.$('map-links').innerHTML;
 assert.match(chip,/Links: 2 up · 1 not checked/);assert.match(chip,/map-legend/);assert.match(chip,/dotted red = down/);assert.doesNotMatch(chip,/dashed amber/);
 await h.fire();assert.equal(h.live()[0].ms,10000,'two successes in a row still wait 10 s');
 assert.equal(h.requests.length,2);
});

test('no request while the drawer is open, the page hidden, the tab elsewhere, the stage not map, or the lab not running; an unlinked lab gets its sentence without a request',async()=>{
 const h=harness();h.on('/operations/link-state',async()=>({json:async()=>answer()}));
 h.$('details-dialog').open=true;h.render();assert.equal(h.live().length,0,'drawer open');
 h.$('details-dialog').open=false;h.context.visible=false;h.context.mapLinkSchedule();assert.equal(h.live().length,0,'hidden');
 h.context.visible=true;h.context.tab='devices';h.context.mapLinkSchedule();assert.equal(h.live().length,0,'another tab');
 h.context.tab='topology';h.svg.hidden=true;h.context.mapLinkSchedule();assert.equal(h.live().length,0,'stage not map');
 assert.equal(h.requests.length,0);
 for(const status of ['Not deployed','Stopped','Unknown']){const x=harness({status});x.render();assert.equal(x.live().length,0,status);assert.equal(x.requests.length,0);assert.equal(x.$('map-links').innerHTML.includes('the lab is not running'),true,status);}
 const u=harness({deployment_name:'',status:'Unlinked'});u.render();assert.equal(u.live().length,0);assert.match(u.$('map-links').innerHTML,/Link state off: This lab is not linked to a lab on the VM\./);
 for(const status of ['Running','Partially running']){const x=harness({status});x.render();assert.equal(x.live().length,1,status+' is polled');}
});

test('tab away and back with the drawing unchanged gives exactly one fetch; Stopped to Running gives exactly one; the drawer closing gives one fresh fetch',async()=>{
 const h=harness();h.on('/operations/link-state',async()=>({json:async()=>answer()}));
 h.render();await h.fire();assert.equal(h.requests.length,1);
 h.context.tab='devices';await h.fire();assert.equal(h.requests.length,1,'the armed timer stopped instead of fetching');assert.equal(h.live().length,0);
 h.context.tab='topology';h.context.mapLinkSchedule();assert.equal(h.live().length,1);await h.fire();assert.equal(h.requests.length,2);
 h.labs[0].deployment.status='Stopped';h.context.mapLinkSchedule();
 assert.equal(h.live().length,0);for(const w of h.scene.children.filter(c=>c.is('.topology-wire')))assert.equal(w.classList.contains('link-up'),false,'cleared when the lab stops');
 assert.match(h.$('map-links').innerHTML,/the lab is not running/);
 h.labs[0].deployment.status='Running';h.context.mapLinkSchedule();h.context.mapLinkSchedule();assert.equal(h.live().length,1);await h.fire();assert.equal(h.requests.length,3);
 h.$('details-dialog').open=true;await h.fire();assert.equal(h.requests.length,3,'drawer open: the armed poll stops');
 h.$('details-dialog').open=false;h.context.mapLinkDrawerClosed();assert.equal(h.live().length,1);await h.fire();assert.equal(h.requests.length,4);
});

test('available:false clears the colours and speaks once; 503 keeps them under "retrying"; three errors stop with Retry and the time; 30 minutes pause with Resume',async()=>{
 const h=harness();let mode='ok';
 h.on('/operations/link-state',async()=>{if(mode==='ok')return {json:async()=>answer({devices:{...answer().devices,b:{listed:true,interfaces:[row('eth1','dormant',{port:'Ethernet1'}),row('eth2','up',{port:'ge-0/0/1'})]}}})};if(mode==='503')throw Object.assign(new Error('busy'),{status:503});if(mode==='err')throw new TypeError('offline');return {json:async()=>({available:false,reason:'helper',text:'Link state needs the updated VM helper.'})};});
 const wires=h.render();await h.fire();
 assert.ok(wires[0].classList.contains('link-down'));assert.match(h.$('map-links').innerHTML,/Links: 1 up · 1 down · 1 not checked/);
 mode='503';await h.fire();
 assert.ok(wires[0].classList.contains('link-down'),'colours kept');assert.match(h.$('map-links').innerHTML,/Link state paused, retrying…/);assert.equal(h.live()[0].ms,20000);
 mode='err';await h.fire();await h.fire();await h.fire();
 assert.equal(h.live().length,0,'stopped');
 const asOf=h.context.mapLinkAsOf(h.clock.t);
 assert.match(h.$('map-links').innerHTML,new RegExp(`Link state stopped \\(as of ${asOf.replace(':','\\:')}\\)\\.`));assert.match(h.$('map-links').innerHTML,/data-map-link-retry="retry">Retry/);
 assert.equal(wires[0].getAttribute('data-state-text'),`down: b Ethernet1 is dormant (as of ${asOf})`);
 mode='unavailable';h.$('map-links').fire('click',{target:{closest:s=>s==='[data-map-link-retry]'?{}:null}});
 assert.equal(h.live().length,1);await h.fire();
 assert.equal(classes(wires[0]),'topology-wire');assert.match(h.$('map-links').innerHTML,/Link state off: Link state needs the updated VM helper\./);
 assert.equal(h.live().length,0,'no more polling on an old helper');
 // pause after 30 minutes
 const p=harness();p.on('/operations/link-state',async()=>({json:async()=>answer()}));p.render();p.clock.t+=31*60*1000;
 p.get('mapLinkPoll').plan={interval:10000,errors:0,startedAt:p.clock.t-31*60*1000,floor:10000};p.get('mapLinkPoll').fresh=false;
 await p.fire();assert.match(p.$('map-links').innerHTML,/Link state paused \(as of/);assert.match(p.$('map-links').innerHTML,/data-map-link-retry="resume">Resume/);assert.equal(p.live().length,0);
});

test('a VM-in-container device makes the chip say connected; a lab without one says up',async()=>{
 const h=harness();h.on('/operations/link-state',async()=>({json:async()=>answer({devices:{...answer().devices,a:{...answer().devices.a,vm:true}}})}));
 const wires=h.render();await h.fire();
 assert.match(h.$('map-links').innerHTML,/Links: 2 connected/);assert.match(h.$('map-links').innerHTML,/dotted red = down \(container link\)/);
 assert.match(wires[0].getAttribute('data-state-text'),/^connected \(the VM's link to a;/);
});

test('Find: the Devices haystack for a lab device, the label alone for a drawing node, dimmed wires need two dimmed ends, the count sentences, Enter fits',()=>{
 const h=harness();const wires=h.render();const find=h.$('map-find');
 const set=v=>{find.value=v;find.fire('input');};
 const dimmed=()=>h.scene.children.filter(c=>c.is('.map-device')).map(d=>d.classList.contains('dimmed'));
 set('ceos');same(dimmed(),[false,true,true,false],'platform label "Arista cEOS" matches a and c');
 assert.equal(h.$('map-find-count').textContent,'2 of 4 devices match');assert.equal(h.$('map-find-count').hidden,false);
 same(wires.map(w=>w.classList.contains('dimmed')),[false,true,false],'a wire with one matching end stays; both ends dimmed dims it');
 set('10.0.0.2');same(dimmed(),[true,false,true,true]);assert.equal(h.$('map-find-count').textContent,'1 of 4 devices matches');
 set('X');same(dimmed(),[true,true,false,true],'an unmatched drawing node matches by its label');
 set('zzz');assert.equal(h.$('map-find-count').textContent,'No device matches "zzz"');
 const ev=find.fire('keydown',{key:'Enter'});assert.ok(ev.prevented);
 same(h.get('mapBox'),h.get('mapBounds'),'nothing matches: Fit');
 set('b');find.fire('keydown',{key:'Enter'});const box=h.get('mapBox');assert.ok(box[2]>=200&&box[0]<100,'fitted to the match: '+box);
 set('');assert.equal(h.$('map-find-count').hidden,true);same(dimmed(),[false,false,false,false]);
 assert.equal(h.$('search').value,'','Find never touches the Devices search');
});

test('Find: Escape clears a term and stops there (the expanded map stays open); on an empty field it falls through',()=>{
 const h=harness();h.render();const find=h.$('map-find');
 find.value='a';find.fire('input');
 const first=find.fire('keydown',{key:'Escape'});
 assert.equal(find.value,'');assert.ok(first.prevented&&first.stopped);assert.equal(h.$('map-find-count').hidden,true);
 const second=find.fire('keydown',{key:'Escape'});assert.ok(!second.stopped&&!second.prevented,'an empty field lets Escape through to the expanded-map handler');
});

test('map-tools.js adds no document or window listener; a focused Find survives a render; the lab change resets the filter, the cache and the classes',async()=>{
 assert.equal(/(document|window)\.addEventListener/.test(src('map-tools.js')),false);
 const h=harness();h.on('/operations/link-state',async()=>({json:async()=>answer()}));
 assert.equal(h.docAdded,0);
 const wires=h.render();await h.fire();h.$('map-find').value='b';h.$('map-find').fire('input');
 const w2=h.render();assert.equal(h.$('map-find').value,'b','the input is static markup');assert.equal(h.$('map-find').focused,0);
 assert.ok(w2[0].classList.contains('link-up'),'the cached colours are re-applied after a rebuild');
 h.labs.push({id:'L2',name:'two',deployment_name:'x',deployment:{status:'Stopped'},nodes:[]});
 h.context.activeId='L2';h.context.mapLinkSchedule();
 assert.equal(h.$('map-find').value,'');assert.equal(h.$('map-find-count').hidden,true);assert.equal(h.live().length,0);
 assert.equal(JSON.stringify(h.get('mapLinkCache')),'{}');
});

test('hover: the wire and its two devices light up, the hover line carries the composed words, pointerout and focusout clear it',()=>{
 const h=harness();const wires=h.render();wires[0].setAttribute('data-state-text','up');h.context.mapWireText(wires[0]);
 const devices=h.scene.children.filter(c=>c.is('.map-device'));
 const child=wires[0].children[2];
 h.svg.fire('pointerover',{target:child});
 assert.ok(wires[0].classList.contains('hover'));same(devices.map(d=>d.classList.contains('hover-end')),[true,true,false,false]);
 assert.equal(h.$('map-link-hover').textContent,'a:eth1 — b:Ethernet1 · up');assert.equal(h.$('map-link-hover').hidden,false);
 h.svg.fire('pointerout',{target:child,relatedTarget:wires[0].children[1]});assert.ok(wires[0].classList.contains('hover'),'moving inside the wire keeps it');
 h.svg.fire('pointerout',{target:child,relatedTarget:null});assert.ok(!wires[0].classList.contains('hover'));assert.equal(h.$('map-link-hover').textContent,'');
 h.svg.fire('focusin',{target:wires[1]});assert.ok(wires[1].classList.contains('hover'));assert.ok(devices[2].classList.contains('hover-end'),'an unmatched node is found by #id');
 h.svg.fire('focusout',{target:wires[1],relatedTarget:null});assert.ok(!wires[1].classList.contains('hover'));
});

test('Download picture: the live map is neutralised before styles are read and restored after; hit paths, titles, aria, data and state go; styles are inlined',()=>{
 const h=harness();const wires=h.render();
 const devices=h.scene.children.filter(c=>c.is('.map-device'));
 devices[1].classList.add('dimmed');wires[0].classList.add('hover');wires[0].classList.add('link-down');wires[0].setAttribute('data-state-text','down: x');
 devices[0].append(new El('circle',{class:'device-state-dot'}),new El('g',{class:'device-state-glyph','aria-hidden':'true'}));
 const arrow=new El('polygon',{class:'line-arrow'});h.scene.append(arrow);
 const read=[];
 const style=el=>{read.push({cls:el.attrs.class||'',tag:el.tagName});const l=(el.attrs.class||'').split(' ');
  const props={'stroke':l.includes('link-down')?'rgb(179, 38, 30)':l.includes('state-neutral')?'rgb(100, 100, 100)':l.includes('state-ready')?'rgb(0, 128, 0)':'none','opacity':l.includes('dimmed')?'0.25':'1','stroke-width':'2px','font-family':'Inter','display':l.includes('device-state-glyph')?'none':'inline'};
  return {getPropertyValue:p=>props[p]||''};};
 const before=h.svg.all().map(e=>e.attrs.class||'');
 const built=h.context.mapPictureSvg(h.svg,{state:false,whole:true,background:true},style,[0,0,1000,600]);
 const neutral=read.filter(r=>r.cls.includes('map-device'));
 assert.ok(neutral.every(r=>r.cls.includes('state-neutral')&&!r.cls.includes('dimmed')&&!r.cls.includes('state-ready')),'devices read as neutral, undimmed');
 assert.ok(read.filter(r=>r.cls.includes('topology-wire')).every(r=>!r.cls.includes('hover')&&!r.cls.includes('link-down')));
 same(h.svg.all().map(e=>e.attrs.class||''),before,'the live map is back as it was');
 assert.equal(wires[0].getAttribute('data-state-text'),'down: x');
 const all=built.svg.all();
 assert.equal(all.filter(e=>(e.attrs.class||'').includes('capture-hit')).length,0);assert.equal(all.filter(e=>e.tagName==='title').length,0);
 assert.equal(all.filter(e=>e.getAttributeNames().some(n=>n.startsWith('data-')||n.startsWith('aria-')||n==='role'||n==='tabindex')).length,0);
 assert.equal(all.filter(e=>/(^| )(link-|state-|hover|dimmed)/.test(e.attrs.class||'')).length,0);
 assert.equal(all.filter(e=>(e.attrs.class||'').includes('device-state')).length,0,'badge dot and glyph go with the state off');
 assert.equal(all.filter(e=>e.attrs.class==='line-arrow').length,1,'the arrowhead stays');
 const dev=all.find(e=>e.tagName==='g'&&e.attrs.transform);assert.equal(dev.attrs.stroke,'rgb(100, 100, 100)');
 assert.equal(built.svg.attrs.viewBox,'0 0 1000 600');assert.equal(built.svg.attrs.xmlns,'http://www.w3.org/2000/svg');
 assert.ok(all.some(e=>e.attrs.class==='topology-bg'&&e.attrs.width==='1000'),'the background keeps the view box bounds');
 const on=h.context.mapPictureSvg(h.svg,{state:true,whole:false,background:false},style,[10,20,300,200]);
 assert.ok(on.svg.all().some(e=>e.attrs.stroke==='rgb(179, 38, 30)'),'with state on the red stroke is inlined');
 assert.ok(!on.svg.all().some(e=>(e.attrs.class||'').includes('topology-bg')),'no background when off');
 assert.equal(on.svg.attrs.viewBox,'10 20 300 200');
});

test('Download picture: the SVG file and the PNG path (a data: URL, never blob:), the names and the errors',async()=>{
 const h=harness();h.render();
 const c=h.context;
 c.getComputedStyle=()=>({getPropertyValue:()=>''});
 h.$('map-picture-svg').checked=true;h.$('map-picture-whole').checked=true;h.$('map-picture-background').checked=true;
 h.svg.__ser=()=>'<svg/>';
 vm.runInContext('XMLSerializer=class{serializeToString(){return "<svg/>";}}',c);
 const name=await c.mapPictureDownload();assert.equal(name,'Lab_ 1-map.svg');assert.equal(h.downloads[0].name,'Lab_ 1-map.svg');
 assert.equal(h.context.blobs[0].type,'image/svg+xml');assert.equal(h.$('map-picture-dialog').open,false);assert.equal(c.toasts.at(-1),'Picture saved as Lab_ 1-map.svg.');
 let image;c.Image=class{set src(v){image=v;setTimeout0(()=>this.onload());}};
 function setTimeout0(fn){Promise.resolve().then(fn);}
 const canvasCalls=[];
 const doc=c.document,create=doc.createElement;
 doc.createElement=t=>{if(t==='canvas')return {width:0,height:0,getContext:()=>({fillRect(){canvasCalls.push('fill');},drawImage(){canvasCalls.push('draw');}}),toBlob(cb){cb({type:'image/png'});}};return create(t);};
 h.$('map-picture-png').checked=true;
 const png=await c.mapPictureDownload();assert.equal(png,'Lab_ 1-map.png');assert.match(image,/^data:image\/svg\+xml;charset=utf-8,/);assert.doesNotMatch(image,/^blob:/);same(canvasCalls,['fill','draw']);
 await assert.rejects(c.mapPicturePng('<svg/>',9000,100,true),/too large for a PNG here \(over 8192 px\)\. Download the SVG\./);
 doc.createElement=t=>t==='canvas'?{getContext:()=>({drawImage(){}}),toBlob(cb){cb(null);}}:create(t);
 await assert.rejects(c.mapPicturePng('<svg/>',100,100,false),/The PNG could not be made in this browser\. Download the SVG instead\./);
 const form=h.$('map-picture-form'),status=h.$('map-picture-status');
 await c.mapToolsRun(form,status,async()=>{throw new Error('boom');});assert.equal(status.textContent,'boom');
 assert.equal(/blob:/.test(src('map-tools.js').match(/data:image\/svg[^\n]*/)[0]),false);
});

test('Export to draw.io: the choice goes into the URL, the file is named by Content-Disposition, a 400 shows the server sentence',async()=>{
 const h=harness();h.render();const c=h.context;
 h.on('/labs/L1/drawio',async url=>({blob:async()=>({}),headers:{get:()=>url.includes('rows')?'attachment; filename="Lab_ 1-rows.drawio"':''}}));
 h.$('map-drawio-layout-rows').checked=true;h.$('map-drawio-theme-print').checked=true;
 const name=await c.mapDrawioDownload();
 assert.equal(h.requests.at(-1),'/labs/L1/drawio?layout=rows&theme=print');assert.equal(name,'Lab_ 1-rows.drawio');assert.equal(h.downloads.at(-1).name,'Lab_ 1-rows.drawio');
 h.$('map-drawio-layout-rows').checked=false;h.$('map-drawio-theme-print').checked=false;
 assert.equal(await c.mapDrawioDownload(),'Lab_ 1.drawio','the fallback name when the header is empty');assert.equal(h.requests.at(-1),'/labs/L1/drawio?layout=map&theme=manager');
 h.on('/labs/L1/drawio',async()=>{throw Object.assign(new Error('Choose a supported layout.'),{status:400});});
 const status=h.$('map-drawio-status'),before=h.downloads.length;
 await c.mapToolsRun(h.$('map-drawio-form'),status,c.mapDrawioDownload);
 assert.equal(status.textContent,'Choose a supported layout.');assert.equal(h.downloads.length,before,'no file for an error');
});

test('Arrange: the dialog counts groups, disables Rows and Columns without links, posts {mode, revision}, re-fetches the map and offers Undo once',async()=>{
 const dw=drawing({decorations:[{type:'group'},{type:'group'},{type:'text'}]});
 const h=harness({dw});h.render();const c=h.context;
 h.on('/labs/L1/arrange',async(p,d)=>d.undo?{saved:true,revision:'r1',undo:false}:{saved:true,revision:'r2',undo:true});
 c.mapArrangeOpen();
 assert.equal(h.$('map-arrange-dialog').open,true);assert.equal(h.$('map-arrange-groups').textContent,'2 groups will no longer surround their devices.');
 assert.equal(h.$('map-arrange-rows').disabled,false);
 await c.mapArrangeRun('rows');
 same(h.context.posts[0],{p:'/labs/L1/arrange',m:'POST',d:{mode:'rows',revision:'r1'}});
 assert.equal(h.$('map-arrange-dialog').open,false);assert.equal(h.context.refreshes,1);assert.equal(h.context.toasts.at(-1),'Devices arranged in rows.');
 h.render(drawing({revision:'r2',decorations:dw.decorations}));
 assert.match(h.$('map-links').innerHTML,/Undo arrange/,'offered while the revision is the one arrange answered');
 h.render(drawing({revision:'r9'}));assert.doesNotMatch(h.$('map-links').innerHTML,/Undo arrange/,'someone else changed the map: gone');
 // undo path
 h.render(drawing({revision:'r2'}));await c.mapArrangeRun('ring');
 h.render(drawing({revision:'r2'}));assert.match(h.$('map-links').innerHTML,/Undo arrange/);
 await c.mapArrangeUndoRun();same(h.context.posts.at(-1).d,{undo:true,revision:'r2'});assert.doesNotMatch(h.$('map-links').innerHTML,/Undo arrange/);
 const none=harness({dw:drawing({links:[]})});none.render();none.context.mapArrangeOpen();
 assert.equal(none.$('map-arrange-rows').disabled,true);assert.equal(none.$('map-arrange-columns').disabled,true);assert.equal(none.$('map-arrange-ring').disabled,false);assert.equal(none.$('map-arrange-reason').hidden,false);
});

test('Arrange: a 409 keeps Undo and a 412 removes it and reloads; a busy arrange shows the server sentence in the dialog',async()=>{
 const h=harness();h.render();const c=h.context;let next={status:200};
 h.on('/labs/L1/arrange',async(p,d)=>{if(next.status===409)throw Object.assign(new Error('Wait for the current lab operation to finish.'),{status:409});if(next.status===412)throw Object.assign(new Error('The map changed since you looked at it. The map was reloaded; try again.'),{status:412});return {saved:true,revision:'r2',undo:true};});
 await c.mapArrangeRun('columns');h.render(drawing({revision:'r2'}));assert.match(h.$('map-links').innerHTML,/Undo arrange/);
 next={status:409};await c.mapArrangeUndoRun();
 assert.match(h.$('map-links').innerHTML,/Undo arrange/,'busy: nothing changed, Undo stays');assert.equal(h.$('map-status').textContent,'Wait for the current lab operation to finish.');
 next={status:412};const refreshes=h.context.refreshes;await c.mapArrangeUndoRun();
 assert.doesNotMatch(h.$('map-links').innerHTML,/Undo arrange/);assert.equal(h.context.refreshes,refreshes+1);
 c.mapArrangeOpen();await c.mapArrangeRun('ring');
 assert.match(h.$('map-arrange-status').textContent,/The map changed since you looked at it/);assert.equal(h.$('map-arrange-dialog').open,true);
 next={status:409};await c.mapArrangeRun('ring');assert.equal(h.$('map-arrange-status').textContent,'Wait for the current lab operation to finish.');assert.equal(h.$('map-arrange-ring').disabled,false);
});

test('the default-grid hint shows for a placed:false map with two or more devices only, and opens the dialog',()=>{
 const h=harness({dw:drawing({placed:false})});h.render();
 assert.match(h.$('map-links').innerHTML,/Devices sit on the default grid\./);assert.match(h.$('map-links').innerHTML,/id="map-arrange-hint"/);
 h.$('map-links').fire('click',{target:{closest:s=>s==='#map-arrange-hint'?{}:null}});assert.equal(h.$('map-arrange-dialog').open,true);
 const one=harness({dw:drawing({placed:false,nodes:[{id:'1',label:'a',inventory_name:'a'}],links:[]})});one.render();assert.doesNotMatch(one.$('map-links').innerHTML,/default grid/);
 const placed=harness();placed.render();assert.doesNotMatch(placed.$('map-links').innerHTML,/default grid/);
});

test('mapToolsReset and the markup: no inline style, esc() on every interpolation of a label or sentence',()=>{
 const js=src('map-tools.js');
 assert.equal(/\sstyle="/.test(js),false,'no inline style in the new markup');
 assert.equal(/transform\s*=/.test(js),false,'the arrange flow never writes positions into the DOM');
 const html=src('index.html');
 for(const id of ['map-find','map-links','map-find-count','map-link-hover','map-picture','map-drawio-export','map-arrange','map-picture-dialog','map-drawio-dialog','map-arrange-dialog'])assert.ok(html.includes(`id="${id}"`),id);
 for(const chunk of html.match(/<dialog id="map-(picture|drawio|arrange)-dialog"[\s\S]*?<\/dialog>/g))assert.doesNotMatch(chunk,/\sstyle="/);
 const h=harness();h.render();h.$('map-find').value='b';h.context.mapToolsReset();
 assert.equal(h.$('map-find').value,'');
});

test('S1b contract: a 409 helper sentence turns the colours off with that sentence and stops the poll; a 404 counts as an error',async()=>{
 const h=harness();let mode='ok';
 h.on('/operations/link-state',async()=>{if(mode==='409')throw Object.assign(new Error('Link state needs the updated VM helper (ask your instructor or administrator).'),{status:409});return {json:async()=>answer()};});
 const wires=h.render();await h.fire();assert.ok(wires[0].classList.contains('link-up'));
 mode='409';await h.fire();
 assert.equal(classes(wires[0]),'topology-wire');assert.match(h.$('map-links').innerHTML,/Link state off: Link state needs the updated VM helper/);assert.equal(h.live().length,0);
});

test('script-load race: a map drawn before map-tools.js ran is drawn once more, forced, so the hooks run; a page with no map drawn yet is left to the first refresh',()=>{
 const late=harness({drawnBefore:true});assert.equal(late.get('refreshes'),1);assert.equal(late.get('refreshForce'),true);
 const early=harness();assert.equal(early.get('refreshes'),0);
});
