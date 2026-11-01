const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const dir=path.join(__dirname,'../app/static');
const source=fs.readFileSync(path.join(dir,'setup.js'),'utf8');
const html=fs.readFileSync(path.join(dir,'setup.html'),'utf8');
const IDS=['setup-title','setup-lead','setup-form','setup-code','setup-user','setup-password','setup-confirm','setup-show','setup-error','setup-reason','setup-submit','setup-signin','signin-plain'];
let focused;
function walk(n,id){if(n.id===id)return n;for(const c of n.children||[]){const f=c.text===undefined?walk(c,id):null;if(f)return f;}return null;}
function node(tag,id){
 return {tag,id:id||'',children:[],hidden:false,disabled:false,value:'',_text:'',className:'',attrs:{},href:'',
  get textContent(){return this._text+this.children.map(c=>c.text!==undefined?c.text:c.textContent).join('');},
  set textContent(v){this._text=String(v);this.children=[];},
  append(...items){for(const i of items)this.children.push(typeof i==='string'?{text:i}:i);},
  replaceChildren(...items){this.children=[];this._text='';this.append(...items);},
  setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return k in this.attrs?this.attrs[k]:null;},
  focus(){focused.push(this.id);}};
}
function fixture({fetch,search='',protocol='https:',hostname='manager.lab'}={}){
 focused=[];
 const elements=new Map(),replaced=[],intervals=[],requests=[];
 for(const id of IDS){const n=node('x',id);n.hidden=['setup-reason','setup-signin','signin-plain'].includes(id);elements.set(id,n);}
 elements.get('setup-submit').textContent='Create account and sign in';elements.get('setup-show').textContent='Show';
 elements.get('setup-title').textContent='Create the first administrator';
 const get=id=>elements.get(id);
 const trap={get length(){throw new Error('storage used');}};
 const context=vm.createContext({document:{getElementById:get,createElement:tag=>node(tag),createTextNode:text=>({text})},
  location:{search,protocol,hostname,replace:url=>replaced.push(url),get href(){throw new Error('href read');}},
  fetch:async(url,options={})=>{requests.push({url,method:options.method,body:options.body?JSON.parse(options.body):undefined,options});return fetch(url,options,requests.length);},
  URLSearchParams,JSON,Math,Number,String,Promise,setInterval:fn=>{intervals.push(fn);return intervals.length;},clearInterval(){},localStorage:trap,sessionStorage:trap});
 vm.runInContext(source,context);
 return {context,get,replaced,intervals,requests,walk:id=>walk(get('setup-error'),id)||walk(get('setup-reason'),id)};
}
const reply=(status,body)=>({status,json:async()=>{if(body===undefined)throw new Error('not json');return body;}});
const GOOD='correct horse battery';
const send=f=>f.context.setupSubmit({preventDefault(){}});
const fill=(f,{code=' abcd-1234 ',user='Admin',password=GOOD,confirm=GOOD}={})=>{f.get('setup-code').value=code;f.get('setup-user').value=user;f.get('setup-password').value=password;f.get('setup-confirm').value=confirm;};

test('setupProblem returns each page-side sentence in order',()=>{
 const c=fixture().context;
 assert.equal(c.setupProblem('admin','short','short'),'Use at least 12 characters.');
 assert.equal(c.setupProblem('admin','a'.repeat(129),'a'.repeat(129)),'Use at least 12 characters.');
 assert.equal(c.setupProblem('admin',GOOD,GOOD+'x'),'The two passwords are not the same.');
 assert.equal(c.setupProblem('administrator','ADMINISTRATOR','ADMINISTRATOR'),'Choose a password that is not your username.');
 assert.equal(c.setupProblem('admin','my-Admin-password','my-Admin-password'),'Choose a password that is not your username.');
 assert.equal(c.setupProblem('admin',GOOD,GOOD),'');
 assert.equal(c.setupProblem('',GOOD,GOOD),'');
});

test('setupRecover reads recover=1 only',()=>{
 const c=fixture().context;
 assert.equal(c.setupRecover('?recover=1'),true);assert.equal(c.setupRecover('?x=1&recover=1'),true);
 assert.equal(c.setupRecover('?recover=0'),false);assert.equal(c.setupRecover(''),false);assert.equal(c.setupRecover('?recover=11'),false);
});

test('recovery wording replaces the heading and lead; first run keeps the markup',()=>{
 const first=fixture();assert.equal(first.get('setup-title').textContent,'Create the first administrator');
 const f=fixture({search:'?recover=1'});
 assert.equal(f.get('setup-title').textContent,'Recovery: create one new administrator');
 assert.equal(f.get('setup-lead').textContent,'Enter the code the recovery command printed, then choose a new administrator account. Existing accounts are not changed.');
});

test('plain http shows the notice',()=>{
 assert.equal(fixture({protocol:'http:'}).get('signin-plain').hidden,false);
 assert.equal(fixture({protocol:'http:',hostname:'localhost'}).get('signin-plain').hidden,true);
 assert.equal(fixture().get('signin-plain').hidden,true);
});

test('empty code and page problems send nothing and focus the field',async()=>{
 const f=fixture({fetch:async()=>reply(200,{})});
 fill(f,{code:'   '});await send(f);assert.equal(f.get('setup-error').textContent,'Enter the setup code.');assert.equal(focused.at(-1),'setup-code');
 fill(f,{password:'short',confirm:'short'});await send(f);assert.equal(f.get('setup-error').textContent,'Use at least 12 characters.');assert.equal(focused.at(-1),'setup-password');
 fill(f,{confirm:'other password 1'});await send(f);assert.equal(focused.at(-1),'setup-confirm');
 fill(f,{user:'admin',password:'ADMIN-admin-1',confirm:'ADMIN-admin-1'});await send(f);assert.equal(focused.at(-1),'setup-password');
 assert.equal(f.requests.length,0);
});

test('submit sends the trimmed code and lowercased username, shows Creating while sending, 200 goes to /',async()=>{
 let release;
 const f=fixture({fetch:()=>new Promise(r=>{release=r;})});
 fill(f);const running=send(f);
 assert.equal(f.get('setup-submit').disabled,true);assert.equal(f.get('setup-submit').textContent,'Creating…');
 assert.equal(f.requests[0].url,'/api/setup');assert.equal(f.requests[0].method,'POST');
 assert.deepEqual(f.requests[0].body,{code:'abcd-1234',username:'admin',password:GOOD});
 assert.equal(f.requests[0].options.headers['Content-Type'],'application/json');
 release(reply(200,{user:{name:'admin'}}));await running;
 assert.deepEqual(f.replaced,['/']);
});

test('401 shows the answer, clears and focuses the code and keeps the rest',async()=>{
 const message='That setup code is not right. On the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code';
 const f=fixture({fetch:async()=>reply(401,{detail:{code:'invalid_code',message}})});
 fill(f);await send(f);
 assert.equal(f.get('setup-error').textContent,message);assert.equal(f.get('setup-code').value,'');assert.equal(focused.at(-1),'setup-code');
 assert.equal(f.get('setup-user').value,'Admin');assert.equal(f.get('setup-password').value,GOOD);assert.equal(f.get('setup-submit').disabled,false);
 assert.equal(f.get('setup-submit').textContent,'Create account and sign in');
 const bare=fixture({fetch:async()=>reply(401,{})});fill(bare);await send(bare);
 assert.equal(bare.get('setup-error').textContent,message);
});

test('409 exists keeps every field and focuses the username',async()=>{
 const message='That name already exists. Choose a new name for the recovery administrator.';
 const f=fixture({fetch:async()=>reply(409,{detail:{code:'exists',message}})});
 fill(f);await send(f);
 assert.equal(f.get('setup-error').textContent,message);assert.equal(focused.at(-1),'setup-user');
 assert.equal(f.get('setup-code').value,' abcd-1234 ');assert.equal(f.get('setup-password').value,GOOD);assert.equal(f.get('setup-confirm').value,GOOD);
});

test('404 shows Setup is closed and unhides the Sign in link',async()=>{
 const message='Setup is closed. Sign in, or ask the VM administrator to run the recovery command.';
 const f=fixture({fetch:async()=>reply(404,{detail:{code:'setup_closed',message}})});
 fill(f);await send(f);
 assert.equal(f.get('setup-error').textContent,message);assert.equal(f.get('setup-signin').hidden,false);assert.equal(f.get('setup-submit').disabled,false);
});

test('422 shows the manager sentence as given',async()=>{
 const f=fixture({fetch:async()=>reply(422,{detail:{code:'invalid',message:'That password is too common. Choose another.'}})});
 fill(f);await send(f);assert.equal(f.get('setup-error').textContent,'That password is too common. Choose another.');
 assert.equal(f.get('setup-signin').hidden,true);
});

test('other statuses, non-JSON and a network failure say the manager did not answer',async()=>{
 for(const answer of [()=>reply(500,{}),()=>reply(502),()=>reply(200),()=>{throw new TypeError('network');}]){
  const f=fixture({fetch:async()=>answer()});fill(f);await send(f);
  assert.equal(f.get('setup-error').textContent,'The manager did not answer. Try again.');assert.equal(f.get('setup-submit').disabled,false);assert.deepEqual(f.replaced,[]);
 }
});

test('429 announces once, ticks only the aria-hidden span, re-enables at 0 (REVIEW U15)',async()=>{
 const f=fixture({fetch:async()=>reply(429,{detail:{retry_after:3,message:'x'}})});
 fill(f);await send(f);
 assert.match(f.get('setup-error').textContent,/^Too many sign-in attempts\. Try again in \d+ s\.$/);
 const said=f.walk('setup-wait-said'),wait=f.walk('setup-wait');
 assert.equal(said.textContent,'3');assert.equal(said.className,'sr-only');assert.equal(wait.textContent,'3');assert.equal(wait.attrs['aria-hidden'],'true');
 assert.equal(f.get('setup-submit').disabled,true);
 const count=f.requests.length;await send(f);assert.equal(f.requests.length,count);
 f.intervals[0]();assert.equal(wait.textContent,'2');assert.equal(said.textContent,'3');
 f.intervals[0]();assert.equal(wait.textContent,'1');assert.equal(said.textContent,'3');
 f.intervals[0]();
 assert.equal(f.get('setup-submit').disabled,false);assert.equal(f.get('setup-error').textContent,'');
 assert.equal(f.get('setup-reason').textContent,'You can sign in again.');assert.equal(f.get('setup-reason').hidden,false);assert.equal(focused.at(-1),'setup-code');
});

test('429 default and cap',async()=>{
 for(const [retry,shown] of [[undefined,'60'],[99999,'3600']]){
  const f=fixture({fetch:async()=>reply(429,{detail:{retry_after:retry}})});fill(f);await send(f);assert.equal(f.walk('setup-wait').textContent,shown);
 }
});

test('Show toggles both password fields; the code never reaches location or storage',async()=>{
 const f=fixture({fetch:async()=>reply(200,{})});
 f.get('setup-password').type='password';f.get('setup-confirm').type='password';
 f.get('setup-show').onclick();assert.equal(f.get('setup-password').type,'text');assert.equal(f.get('setup-confirm').type,'text');
 assert.equal(f.get('setup-show').textContent,'Hide');assert.equal(f.get('setup-show').attrs['aria-pressed'],'true');
 f.get('setup-show').onclick();assert.equal(f.get('setup-password').type,'password');assert.equal(f.get('setup-show').textContent,'Show');
 fill(f);await send(f);assert.deepEqual(f.replaced,['/']);
});

test('source pins and page markup',()=>{
 assert.match(source,/^'use strict';/);
 assert.doesNotMatch(source,/innerHTML|outerHTML|insertAdjacentHTML|\.style\b|style=|localStorage|sessionStorage|indexedDB|document\.cookie|location\.(href|assign)|addEventListener\(\s*['"]keydown|\beval\(/);
 for(const id of IDS)assert.match(html,new RegExp('id="'+id+'"'),id);
 assert.match(html,/<title>Create an administrator<\/title>/);
 assert.match(html,/id="setup-code"[^>]*\sautofocus/);assert.match(html,/id="setup-code"[^>]*autocomplete="one-time-code"/);
 assert.match(html,/id="setup-signin"[^>]*href="\/login"[^>]*\shidden/);
 assert.match(html,/<form id="setup-form" novalidate/);assert.doesNotMatch(html,/<form[^>]*\saction=/);
 assert.match(html,/id="setup-error"[^>]*role="alert"/);assert.match(html,/id="setup-reason"[^>]*role="status"/);
 for(const s of ['Create the first administrator','Enter the setup code the installer printed, then choose the account you will sign in with.','Printed at the end of the installation. On the VM:','sudo cat /srv/containerlab-node-manager/data/setup-code','Lowercase letters, digits, dot, dash and underscore. 2 to 32 characters.','Create account and sign in','At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password.'])
  assert.ok(html.includes(s),s);
 assert.match(html,/aria-controls="setup-password setup-confirm"/);
});
