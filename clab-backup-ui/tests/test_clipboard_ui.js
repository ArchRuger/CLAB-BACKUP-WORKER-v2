// clipboard.js: copyText (Clipboard API, then a textarea inside the open dialog or the body, then the selected target), the one
// delegated click for button[data-copy] with the Copied flip, copyButton markup and where the result is announced.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/static/clipboard.js'),'utf8');
const settle=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
function node(tag,attrs={}){
 const n={tag,attrs:{...attrs},children:[],parentElement:null,textContent:attrs.text||'',className:attrs.class||'',dataset:{...(attrs.dataset||{})},disabled:false,value:'',selected:false,
  getAttribute(k){return k in this.attrs?this.attrs[k]:null;},setAttribute(k,v){this.attrs[k]=String(v);},removeAttribute(k){delete this.attrs[k];},
  get id(){return this.attrs.id||'';},get classList(){const self=this;return {contains:c=>self.className.split(/\s+/).includes(c)};},
  get nextElementSibling(){const p=this.parentElement;if(!p)return null;return p.children[p.children.indexOf(this)+1]||null;},
  appendChild(c){c.parentElement=this;this.children.push(c);return c;},
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.parentElement=null;},
  get parentNode(){return this.parentElement;},removeChild(c){c.remove();},
  closest(sel){let x=this;while(x){if(sel==='dialog[open]'?x.tag==='dialog'&&x.open:sel==='button[data-copy]'?x.tag==='button'&&x.dataset.copy!==undefined:false)return x;x=x.parentElement;}return null;},
  querySelector(sel){const cls=sel.slice(1),find=x=>{for(const c of x.children){if(c.className.split(/\s+/).includes(cls))return c;const d=find(c);if(d)return d;}return null;};return find(this);},
  focus(){if(!this.noFocus)env.activeElement=this;}};
 if(tag==='textarea'||tag==='input')n.select=function(){this.selected=true;this.selectionStart=0;this.selectionEnd=this.value.length;};
 return n;
}
let env;
function harness({clipboard,execResult=true,notify,withTools=false}={}){
 const body=node('body'),listeners={};
 const document={body,activeElement:null,getElementById:id=>{const find=x=>{if(x.id===id)return x;for(const c of x.children){const d=find(c);if(d)return d;}return null;};return find(body);},
  createElement:tag=>node(tag),addEventListener(type,fn){listeners[type]=fn;},createRange:()=>({selectNodeContents(n){this.node=n;}}),
  execCommand:cmd=>{document.execs.push({cmd,active:document.activeElement});return execResult;},execs:[]};
 env=document;
 const timers=[],selections=[];
 const ctx={document,navigator:{clipboard},window:{getSelection:()=>({removeAllRanges(){},addRange(r){selections.push(r.node);}})},setTimeout:(fn)=>{timers.push(fn);return timers.length;},clearTimeout(i){timers[i-1]=null;},console};
 ctx.window.document=document;if(notify)ctx.notify=notify;
 const c=vm.createContext(ctx);vm.runInContext(source,c);
 if(withTools)body.appendChild(node('span',{id:'tools-status'}));
 return {c,document,body,listeners,timers,selections,click:target=>listeners.click({target})};
}
const button=(parent,extra={})=>{const b=node('button',{text:'Copy','aria-label':'Copy the address',...extra});b.dataset={copy:'172.20.20.2:22',copyTarget:'fact',label:'Copy',...(extra.dataset||{})};parent.appendChild(b);return b;};
test('clipboard.js loads without a document, a navigator or a window',()=>{
 const c=vm.createContext({});vm.runInContext(source,c);
 assert.equal(typeof vm.runInContext('copyText',c),'function');assert.equal(vm.runInContext('copyButton("","x","y")',c),'');
});
test('the Clipboard API is used first and its value is the text unchanged',async()=>{
 const written=[],h=harness({clipboard:{writeText:async t=>{written.push(t);}}});
 assert.equal(await vm.runInContext('copyText("a\\nb",null)',h.c),true);assert.deepEqual(written,['a\nb']);assert.equal(h.document.execs.length,0);
});
test('without navigator.clipboard the textarea is appended to the open dialog, else the body, and removed afterwards',async()=>{
 const h=harness({}),dialog=node('dialog');dialog.open=true;h.body.appendChild(dialog);const b=button(dialog);
 let hostSeen=null;const real=dialog.appendChild.bind(dialog);dialog.appendChild=c=>{if(c.tag==='textarea')hostSeen='dialog';return real(c);};
 const bodyReal=h.body.appendChild.bind(h.body);h.body.appendChild=c=>{if(c.tag==='textarea')hostSeen='body';return bodyReal(c);};
 h.c.__b=b;assert.equal(await vm.runInContext('copyText("v",__b)',h.c),true);
 assert.equal(hostSeen,'dialog');assert.equal(h.document.execs.length,1);assert.equal(h.document.execs[0].active.tag,'textarea');assert.equal(dialog.children.length,1,'only the button is left');
 hostSeen=null;const plain=button(h.body);h.c.__b=plain;await vm.runInContext('copyText("v",__b)',h.c);assert.equal(hostSeen,'body');
 hostSeen=null;await vm.runInContext('copyText("v",null)',h.c);assert.equal(hostSeen,'body');
});
test('a closed dialog is not a host: a textarea in an inert page would copy nothing',async()=>{
 const h=harness({}),dialog=node('dialog');h.body.appendChild(dialog);const b=button(dialog);let host=null;
 const bodyReal=h.body.appendChild.bind(h.body);h.body.appendChild=c=>{if(c.tag==='textarea')host='body';return bodyReal(c);};
 h.c.__b=b;await vm.runInContext('copyText("v",__b)',h.c);assert.equal(host,'body');
});
test('execCommand runs only when the textarea really holds focus and its selection; otherwise the failure path',async()=>{
 const h=harness({});let ok=true;
 const real=h.document.createElement;h.document.createElement=tag=>{const n=real(tag);n.noFocus=true;return n;};
 const fact=node('dd',{id:'fact'});fact.textContent='172.20.20.2';h.body.appendChild(fact);const b=button(h.body);
 h.c.__b=b;ok=await vm.runInContext('copyText("172.20.20.2:22",__b)',h.c);
 assert.equal(ok,false,'an inert page never reports Copied');assert.equal(h.document.execs.length,0,'execCommand is not even tried without focus');
 assert.deepEqual(h.selections,[fact],'the named target is selected');
});
test('a failing execCommand falls through to selecting the target element, never the button',async()=>{
 const h=harness({execResult:false}),fact=node('dd',{id:'fact'});h.body.appendChild(fact);const b=button(h.body);
 h.c.__b=b;assert.equal(await vm.runInContext('copyText("x",__b)',h.c),false);
 assert.deepEqual(h.selections,[fact]);assert.equal(h.selections.includes(b),false);assert.equal(h.body.children.some(x=>x.tag==='textarea'),false);
 // a text field target is selected through select()
 const input=node('input',{id:'field'});input.value='abc';h.body.appendChild(input);const b2=button(h.body,{dataset:{copyTarget:'field'}});
 h.c.__b=b2;await vm.runInContext('copyText("abc",__b)',h.c);assert.equal(input.selected,true);
});
test('copyText never throws, whatever the page does',async()=>{
 const h=harness({clipboard:{writeText:async()=>{throw new Error('denied');}},execResult:false});h.document.createElement=()=>{throw new Error('no dom');};
 assert.equal(await vm.runInContext('copyText("x",{})',h.c),false);
});
test('a click on button[data-copy] copies, flips text and aria-label to Copied and restores them; a double click cannot stick',async()=>{
 const written=[],h=harness({clipboard:{writeText:async t=>{written.push(t);}},withTools:true}),b=button(h.body);
 h.click(b);await settle();assert.deepEqual(written,['172.20.20.2:22']);assert.equal(b.textContent,'Copied');assert.equal(b.getAttribute('aria-label'),'Copied');
 h.click(b);await settle();assert.equal(b.textContent,'Copied');
 const pending=h.timers.filter(Boolean);assert.equal(pending.length,1,'the first restore timer was cancelled by the second click');pending[0]();
 assert.equal(b.textContent,'Copy');assert.equal(b.getAttribute('aria-label'),'Copy the address');
 // a click elsewhere or on a disabled button does nothing
 written.length=0;h.listeners.click({target:node('div')});b.disabled=true;h.click(b);await settle();assert.deepEqual(written,[]);
});
test('a failed copy never flips the button to Copied',async()=>{
 const h=harness({clipboard:{writeText:async()=>{throw new Error('x');}},execResult:false,withTools:true}),b=button(h.body);
 h.click(b);await settle();assert.equal(b.textContent,'Copy');assert.equal(h.document.getElementById('tools-status').textContent,'Could not copy. The value is selected: press Ctrl+C.');
});
test('the result is announced in the status span inside a dialog, with the failure also in .form-error',async()=>{
 const ok=harness({clipboard:{writeText:async()=>{}}}),dialog=node('dialog'),b=button(dialog),status=node('span',{class:'copy-status'}),error=node('p',{class:'form-error'});dialog.open=true;
 dialog.appendChild(status);dialog.appendChild(error);ok.body.appendChild(dialog);
 const notified=[];ok.c.notify=m=>notified.push(m);
 ok.click(b);await settle();assert.equal(status.textContent,'Copied');assert.deepEqual(notified,[],'the toast is underneath a modal');assert.equal(error.textContent,'');
 const bad=harness({clipboard:{writeText:async()=>{throw new Error('x');}},execResult:false}),d2=node('dialog'),b2=button(d2),s2=node('span',{class:'copy-status'}),e2=node('p',{class:'form-error'});d2.open=true;d2.appendChild(s2);d2.appendChild(e2);bad.body.appendChild(d2);
 bad.click(b2);await settle();assert.equal(s2.textContent,'Could not copy. The value is selected: press Ctrl+C.');assert.equal(e2.textContent,s2.textContent);
});
test('outside a dialog notify() announces when it exists; with neither it is silent but still copies',async()=>{
 const notified=[],h=harness({clipboard:{writeText:async()=>{}},notify:m=>notified.push(m)}),b=button(h.body);
 h.click(b);await settle();assert.deepEqual(notified,['Copied']);
 const quiet=harness({clipboard:{writeText:async()=>{}}}),q=button(quiet.body);quiet.click(q);await settle();assert.equal(q.textContent,'Copied');
});
test('on terminal.html the status goes to #tools-status, not to a toast',async()=>{
 const notified=[],h=harness({clipboard:{writeText:async()=>{}},notify:m=>notified.push(m),withTools:true}),b=button(h.body);
 h.click(b);await settle();assert.equal(h.document.getElementById('tools-status').textContent,'Copied');assert.deepEqual(notified,[]);
});
test('copyButton writes the markup of the design, escapes every value and is empty for an empty value',()=>{
 const h=harness({});h.c.esc=s=>String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
 const html=vm.runInContext('copyButton(\'a"b<\',"the name","fact-name")',h.c);
 assert.match(html,/^<button type="button" class="button ghost small copy-button" data-copy="a&quot;b&lt;" data-copy-target="fact-name" data-label="Copy" aria-label="Copy the name">Copy<\/button><span class="copy-status" role="status"><\/span>$/);
 assert.equal(vm.runInContext('copyButton("","n","t")',h.c),'');assert.equal(vm.runInContext('copyButton(null,"n","t")',h.c),'');
 const bare=harness({});assert.match(vm.runInContext('copyButton("<b>","n","t")',bare.c),/data-copy="&lt;b&gt;"/,'without esc() on the page it still escapes');
});
