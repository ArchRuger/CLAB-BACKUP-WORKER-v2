const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const dir=path.join(__dirname,'../app/static');
const source=fs.readFileSync(path.join(dir,'login.js'),'utf8');
const version=fs.readFileSync(path.join(__dirname,'../VERSION'),'utf8').trim();
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const IDS=['signin-card','signin-form','signin-checking','signin-reason','signin-user','signin-password','signin-show','signin-error','signin-submit','signin-plain',
 'signin-change','change-form','change-current-field','change-current','change-new','change-confirm','change-show','change-error','change-submit','change-signout'];
const HIDDEN=['signin-form','signin-plain','signin-change','change-current-field'];
function node(tag,id){
 const n={tag,id:id||'',children:[],hidden:false,disabled:false,value:'',_text:'',className:'',attrs:{},
  get textContent(){return this._text+this.children.map(c=>c.text!==undefined?c.text:c.textContent).join('');},
  set textContent(v){this._text=String(v);this.children=[];},
  append(...items){for(const i of items)this.children.push(typeof i==='string'?{text:i}:i);},
  appendChild(i){this.children.push(i);return i;},
  replaceChildren(...items){this.children=[];this._text='';this.append(...items);},
  setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return k in this.attrs?this.attrs[k]:null;},
  focus(){focused.push(this.id);if(typeof elements!=='undefined'&&elements.get('signin-reason'))focusSeen.push(this.id+'|'+elements.get('signin-reason').textContent);}};
 return n;
}
let focused,focusSeen=[],elements;
function walk(n,id){if(n.id===id)return n;for(const c of n.children||[]){const f=c.text===undefined?walk(c,id):null;if(f)return f;}return null;}
function fixture({fetch,search='',hash='',protocol='https:',hostname='manager.lab'}){
 focused=[];
 focusSeen=[];elements=new Map();
 const replaced=[],intervals=[],cleared=[],requests=[];
 for(const id of IDS){const n=node('x',id);n.hidden=HIDDEN.includes(id);elements.set(id,n);}
 elements.get('signin-submit').textContent='Sign in';elements.get('change-submit').textContent='Change password and continue';elements.get('signin-show').textContent='Show';elements.get('change-show').textContent='Show';
 const get=id=>elements.get(id);
 const document={getElementById:get,createElement:tag=>node(tag),createTextNode:text=>({text})};
 const location={search,hash,protocol,hostname,replace:url=>replaced.push(url)};
 const wrapped=async(url,options={})=>{requests.push({url,method:options.method||'GET',body:options.body?JSON.parse(options.body):undefined,options});return fetch(url,options,requests.length);};
 const storageTrap={get length(){throw new Error('storage used');}};
 const context=vm.createContext({document,location,fetch:wrapped,URLSearchParams,JSON,Math,Number,String,Promise,
  setInterval:fn=>{intervals.push(fn);return intervals.length;},clearInterval:id=>cleared.push(id),
  localStorage:storageTrap,sessionStorage:storageTrap});
 vm.runInContext(source,context);
 return {context,get,replaced,intervals,cleared,requests,walk:(id)=>walk(get('signin-error'),id)||walk(get('signin-reason'),id)};
}
const reply=(status,body)=>({status,json:async()=>{if(body===undefined)throw new Error('not json');return body;}});
const done=reply(401,{detail:{code:'signed_out'}});
const submit=f=>f.context.loginSubmit({preventDefault(){}});
const changeSubmit=f=>f.context.changeSubmit({preventDefault(){}});
const fill=(f,u,p)=>{f.get('signin-user').value=u;f.get('signin-password').value=p;};
const GOOD='correct horse battery';

test('loginNext accepts same-origin paths and rejects every listed attack',()=>{
 const f=fixture({fetch:async()=>done}),n=(search,hash='')=>f.context.loginNext(search,hash);
 const q=v=>'?next='+encodeURIComponent(v);
 assert.equal(n(''),'/');assert.equal(n(q('')),'/');
 assert.equal(n(q('/#lab=a&view=devices')),'/#lab=a&view=devices');
 assert.equal(n(q('/static/workspace.html#mode=ssh')),'/static/workspace.html#mode=ssh');
 assert.equal(n(q('/?x=1')),'/?x=1');
 for(const bad of ['//evil','/\\evil','https://evil','javascript:alert(1)','/login','/login?next=/','/setup','/api/state','/api/','relative','/a\\b','/a\tb','/a\nb','/a\u0000b','/'+'a'.repeat(2000),'http://evil/','\\\\evil'])
  assert.equal(n(q(bad)),'/',JSON.stringify(bad));
 assert.equal(n(q('/'+'a'.repeat(1999))).length,2000);
});

test('loginNext appends the page hash under the same checks (REVIEW U7)',()=>{
 const f=fixture({fetch:async()=>done}),n=f.context.loginNext;
 assert.equal(n('?next=%2F','#lab=a&view=devices'),'/#lab=a&view=devices');
 assert.equal(n('','#lab=a'),'/#lab=a');
 assert.equal(n('?next='+encodeURIComponent('/x?y=1'),'#lab=a'),'/x?y=1#lab=a');
 assert.equal(n('?next='+encodeURIComponent('/#own'),'#other'),'/#own');
 assert.equal(n('?next=%2F','#a\\b'),'/');
 assert.equal(n('?next=%2F','#a\tb'),'/');
 assert.equal(n('?next=%2Fx','#a\\b'),'/x');
 assert.equal(n('?next=%2F','#'+'a'.repeat(2000)),'/');
 assert.equal(n('?next=%2F',''),'/');
 assert.equal(n('?next=%2F%2Fevil','#lab=a'),'/#lab=a');
});

test('pure helpers: reason, plain, message, countdown, change problems',()=>{
 const f=fixture({fetch:async()=>done}),c=f.context;
 assert.equal(c.loginReason('?reason=ended'),'Your session ended. Sign in again to continue.');
 assert.equal(c.loginReason('?reason=other'),'');assert.equal(c.loginReason(''),'');
 assert.equal(c.loginPlain('http:','manager.lab'),true);assert.equal(c.loginPlain('https:','manager.lab'),false);
 for(const h of ['localhost','127.0.0.1','::1','[::1]'])assert.equal(c.loginPlain('http:',h),false);
 assert.equal(c.loginMessage({detail:{message:'Said.'}},'Fallback.'),'Said.');
 for(const body of [null,{},{detail:'x'},{detail:{message:''}},{detail:{message:5}}])assert.equal(c.loginMessage(body,'Fallback.'),'Fallback.');
 assert.equal(c.loginCountdown(42),'Too many sign-in attempts. Try again in 42 s.');
 assert.equal(c.changeProblem('sam','',GOOD,GOOD,true),'Enter your current password.');
 assert.equal(c.changeProblem('sam','',GOOD,GOOD,false),'');
 assert.equal(c.changeProblem('sam','x','short','short',false),'Use at least 12 characters.');
 assert.equal(c.changeProblem('sam','x','a'.repeat(129),'a'.repeat(129),false),'Use at least 12 characters.');
 assert.equal(c.changeProblem('sam','x',GOOD,GOOD+'!',false),'The two passwords are not the same.');
 assert.equal(c.changeProblem('samsamsamsam','x','SAMSAMSAMSAM','SAMSAMSAMSAM',false),'Choose a password that is not your username.');
 assert.equal(c.changeProblem('sam','x','my-SAM-password','my-SAM-password',false),'Choose a password that is not your username.');
});

test('load check: the form stays hidden behind Checking until the session answered',async()=>{
 let release;
 const f=fixture({fetch:()=>new Promise(r=>{release=r;})});
 assert.equal(f.requests[0].url,'/api/session');assert.equal(f.requests[0].method,'GET');assert.equal(f.requests[0].options.cache,'no-store');
 assert.equal(f.get('signin-checking').hidden,false);assert.equal(f.get('signin-form').hidden,true);
 release(done);await tick();
 assert.equal(f.get('signin-checking').hidden,true);assert.equal(f.get('signin-form').hidden,false);
 assert.equal(f.get('signin-card').hidden,false);assert.equal(f.get('signin-change').hidden,true);
 assert.equal(focused.at(-1),'signin-user');
});

test('load check: 401, other statuses, non-JSON and a network failure show the form',async()=>{
 for(const answer of [()=>reply(401,{detail:{code:'signed_out'}}),()=>reply(500,{}),()=>reply(502),()=>reply(200),()=>{throw new TypeError('network');}]){
  const f=fixture({fetch:async()=>answer(),search:'?change=1'});await tick();
  assert.equal(f.get('signin-form').hidden,false);assert.equal(f.get('signin-change').hidden,true);
  assert.equal(f.get('signin-checking').hidden,true);assert.deepEqual(f.replaced,[]);
 }
});

test('load check: 200 leaves for next with the hash and shows no form',async()=>{
 const f=fixture({fetch:async()=>reply(200,{user:{name:'sam',role:'operator',must_change_password:false}}),search:'?next=%2F',hash:'#lab=a&view=devices'});await tick();
 assert.deepEqual(f.replaced,['/#lab=a&view=devices']);assert.equal(f.get('signin-form').hidden,true);
});

test('load check: a restricted 200 shows the change view asking for the current password',async()=>{
 const f=fixture({fetch:async()=>reply(200,{user:{name:'sam',role:'operator',must_change_password:true}})});await tick();
 assert.deepEqual(f.replaced,[]);assert.equal(f.get('signin-change').hidden,false);assert.equal(f.get('signin-card').hidden,true);
 assert.equal(f.get('change-current-field').hidden,false);assert.equal(focused.at(-1),'change-current');
});

test('reason line and the plain-http notice are applied before the answer',async()=>{
 const f=fixture({fetch:()=>new Promise(()=>{}),search:'?reason=ended',protocol:'http:'});
 assert.equal(f.get('signin-reason').hidden,false);assert.equal(f.get('signin-reason').textContent,'Your session ended. Sign in again to continue.');
 assert.equal(f.get('signin-plain').hidden,false);
 assert.equal(fixture({fetch:()=>new Promise(()=>{})}).get('signin-plain').hidden,true);
});

test('empty submit shows the sentence, focuses the empty field and sends nothing',async()=>{
 const f=fixture({fetch:async()=>done});await tick();
 fill(f,'   ','x');await submit(f);
 assert.equal(f.get('signin-error').textContent,'Enter your username and password.');assert.equal(focused.at(-1),'signin-user');
 fill(f,'sam','');await submit(f);assert.equal(focused.at(-1),'signin-password');
 assert.equal(f.requests.length,1);
});

test('submit lowercases the username, never trims the password and shows Signing in while sending',async()=>{
 let release;
 const f=fixture({fetch:(url,o,n)=>n===1?Promise.resolve(done):new Promise(r=>{release=r;})});await tick();
 fill(f,'  Sam ',' pass word ');
 const running=submit(f);
 assert.equal(f.get('signin-submit').disabled,true);assert.equal(f.get('signin-submit').textContent,'Signing in…');
 assert.deepEqual(f.requests[1].body,{username:'sam',password:' pass word '});
 assert.equal(f.requests[1].method,'POST');assert.equal(f.requests[1].options.headers['Content-Type'],'application/json');
 release(reply(200,{user:{name:'sam',role:'operator',must_change_password:false},expires:'x'}));await running;
 assert.deepEqual(f.replaced,['/']);
});

test('200 leaves with the safe next and the hash',async()=>{
 const f=fixture({fetch:async(u,o,n)=>n===1?done:reply(200,{user:{must_change_password:false}}),search:'?next=%2F%2Fevil',hash:'#lab=a'});await tick();
 fill(f,'sam','pw');await submit(f);assert.deepEqual(f.replaced,['/#lab=a']);
});

test('401 keeps the username, clears the password, shows the answer or the fallback',async()=>{
 for(const [body,expected] of [[{detail:{code:'invalid_credentials',message:'Wrong username or password.'}},'Wrong username or password.'],[{detail:{message:'Their sentence.'}},'Their sentence.'],[{},'Wrong username or password.']]){
  const f=fixture({fetch:async(u,o,n)=>n===1?done:reply(401,body)});await tick();
  fill(f,'sam','secret-value');await submit(f);
  assert.equal(f.get('signin-error').textContent,expected);assert.equal(f.get('signin-user').value,'sam');
  assert.equal(f.get('signin-password').value,'');assert.equal(focused.at(-1),'signin-password');
  assert.equal(f.get('signin-submit').disabled,false);assert.equal(f.get('signin-submit').textContent,'Sign in');
 }
});

test('429 announces once, ticks only the hidden-from-readers span and re-enables at the end (REVIEW U15)',async()=>{
 const f=fixture({fetch:async(u,o,n)=>n===1?done:reply(429,{detail:{code:'throttled',retry_after:3,message:'ignored'}}),search:'?reason=ended'});await tick();
 fill(f,'sam','pw');await submit(f);
 assert.match(f.get('signin-error').textContent,/^Too many sign-in attempts\. Try again in \d+ s\.$/);
 const said=f.walk('signin-wait-said'),wait=f.walk('signin-wait');
 assert.equal(said.textContent,'3');assert.equal(said.className,'sr-only');assert.equal(wait.textContent,'3');assert.equal(wait.attrs['aria-hidden'],'true');
 assert.equal(f.get('signin-submit').disabled,true);assert.equal(f.intervals.length,1);
 const requests=f.requests.length;
 await submit(f);assert.equal(f.requests.length,requests);
 f.intervals[0]();assert.equal(wait.textContent,'2');assert.equal(said.textContent,'3');
 f.intervals[0]();assert.equal(wait.textContent,'1');assert.equal(said.textContent,'3');assert.equal(f.get('signin-submit').disabled,true);
 f.intervals[0]();
 assert.equal(f.get('signin-submit').disabled,false);assert.equal(f.get('signin-error').textContent,'');
 assert.equal(f.get('signin-reason').textContent,'You can sign in again.');assert.equal(f.get('signin-reason').hidden,false);
 assert.equal(focused.at(-1),'signin-password');assert.deepEqual(f.cleared,[1]);
});

test('at the end of the delay focus moves before the status line is written, and the line is never hidden (U15)',async()=>{
 const f=fixture({fetch:async(u,o,n)=>n===1?done:reply(429,{detail:{retry_after:1}})});await tick();
 fill(f,'sam','pw');await submit(f);
 focusSeen.length=0;f.intervals[0]();
 assert.deepEqual(focusSeen,['signin-password|']);
 assert.equal(f.get('signin-reason').textContent,'You can sign in again.');
 assert.doesNotMatch(loginHtml,/id="signin-reason"[^>]*\shidden/);
 assert.match(loginHtml,/id="signin-reason"[^>]*role="status"/);
 assert.doesNotMatch(source,/signin-reason'\)\.hidden=true/);
});

test('429 without a usable retry_after counts from 60 and a huge one is capped at 3600',async()=>{
 for(const [retry,shown] of [[undefined,'60'],['x','60'],[99999,'3600'],[0,'1']]){
  const f=fixture({fetch:async(u,o,n)=>n===1?done:reply(429,{detail:{retry_after:retry}})});await tick();
  fill(f,'sam','pw');await submit(f);assert.equal(f.walk('signin-wait').textContent,shown);
 }
});

test('a 503 setup_required and a gate 403 show the manager sentence; none falls back to the generic one',async()=>{
 for(const [status,body] of [[503,{detail:{code:'setup_required',message:'This manager is not set up yet. Open /setup to create the first administrator.'}}],[403,{detail:{message:'Blocked.'}}]]){
  const f=fixture({fetch:async(u,o,n)=>n===1?done:reply(status,body)});await tick();
  fill(f,'sam','pw');await submit(f);
  assert.equal(f.get('signin-error').textContent,body.detail.message);
 }
});

test('loginNext refuses dot segments and percent escapes in the path',()=>{
 const f=fixture({fetch:async()=>done}),n=v=>f.context.loginNext('?next='+encodeURIComponent(v),'');
 for(const bad of ['/./api/state','/x/../api/state','/x/../login','/./login','/./setup','/%2e/api/state','/%2561pi/state','/%256Cogin','/a/%2e%2e/b','/a/./b','/a/..'])assert.equal(n(bad),'/',bad);
 assert.equal(n('/?x=%41#a'),'/?x=%41#a');assert.equal(n('/a.b/c..d'),'/a.b/c..d');
});

test('other statuses, non-JSON 2xx and network failures show the manager-did-not-answer sentence',async()=>{
 for(const answer of [()=>reply(500,{}),()=>reply(503),()=>reply(200),()=>reply(0),()=>{throw new TypeError('network');}]){
  const f=fixture({fetch:async(u,o,n)=>n===1?done:answer()});await tick();
  fill(f,'sam','pw');await submit(f);
  assert.equal(f.get('signin-error').textContent,'The manager did not answer. Try again.');
  assert.equal(f.get('signin-submit').disabled,false);assert.deepEqual(f.replaced,[]);
 }
});

test('Show toggles the password type, the label and aria-pressed without reading the value',async()=>{
 const f=fixture({fetch:async()=>done});await tick();
 const field=f.get('signin-password'),button=f.get('signin-show');field.type='password';
 button.onclick();assert.equal(field.type,'text');assert.equal(button.textContent,'Hide');assert.equal(button.attrs['aria-pressed'],'true');
 button.onclick();assert.equal(field.type,'password');assert.equal(button.textContent,'Show');assert.equal(button.attrs['aria-pressed'],'false');
 const both=fixture({fetch:async()=>done});await tick();
 both.get('change-new').type='password';both.get('change-confirm').type='password';
 both.get('change-show').onclick();assert.equal(both.get('change-new').type,'text');assert.equal(both.get('change-confirm').type,'text');
});

const restricted=reply(200,{user:{name:'sam',role:'operator',must_change_password:true},expires:'x'});
async function changeView(handler,extra={}){
 const f=fixture({fetch:async(u,o,n)=>{if(n===1)return done;if(n===2)return restricted;return handler(u,o,n);},...extra});await tick();
 fill(f,'sam','temporary-pass');await submit(f);return f;
}

test('change view after a sign-in: no current field, local problems send nothing, signedInWith is the current password',async()=>{
 const f=await changeView(async()=>reply(422,{detail:{code:'weak_password',message:'That password is too common. Choose another.'}}));
 assert.equal(f.get('signin-card').hidden,true);assert.equal(f.get('signin-change').hidden,false);
 assert.equal(f.get('change-current-field').hidden,true);assert.equal(f.get('signin-password').value,'');assert.equal(focused.at(-1),'change-new');
 const before=f.requests.length;
 f.get('change-new').value='short';f.get('change-confirm').value='short';await changeSubmit(f);
 assert.equal(f.get('change-error').textContent,'Use at least 12 characters.');assert.equal(focused.at(-1),'change-new');
 f.get('change-new').value=GOOD;f.get('change-confirm').value='different pass 1';await changeSubmit(f);
 assert.equal(f.get('change-error').textContent,'The two passwords are not the same.');assert.equal(focused.at(-1),'change-confirm');
 f.get('change-new').value='SAM-SAM-SAM-sam';f.get('change-confirm').value='SAM-SAM-SAM-sam';await changeSubmit(f);
 assert.equal(f.get('change-error').textContent,'Choose a password that is not your username.');
 assert.equal(f.requests.length,before);
 f.get('change-new').value='password1234';f.get('change-confirm').value='password1234';await changeSubmit(f);
 const first=f.requests.at(-1);assert.equal(first.url,'/api/session/password');assert.equal(first.method,'POST');
 assert.deepEqual(first.body,{current:'temporary-pass',password:'password1234'});
 assert.equal(f.get('change-error').textContent,'That password is too common. Choose another.');assert.equal(focused.at(-1),'change-new');
 assert.equal(f.get('change-submit').disabled,false);
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;await changeSubmit(f);
 assert.deepEqual(f.requests.at(-1).body,{current:'temporary-pass',password:GOOD});
});

test('the held password survives 429 and a network failure and is gone after 200',async()=>{
 const answers=[()=>reply(429,{detail:{message:'Too many sign-in attempts. Try again in 5 s.'}}),()=>{throw new TypeError('network');},()=>reply(200,{user:{must_change_password:false}})];
 const f=await changeView(async(u,o,n)=>answers[n-3](),{search:'?next=%2F',hash:'#lab=a'});
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;
 await changeSubmit(f);assert.equal(f.get('change-error').textContent,'Too many sign-in attempts. Try again in 5 s.');
 assert.equal(f.get('change-submit').disabled,false);assert.equal(f.walk('signin-wait'),null);
 await changeSubmit(f);assert.equal(f.get('change-error').textContent,'The manager did not answer. Try again.');
 await changeSubmit(f);
 for(const r of f.requests.slice(2))assert.equal(r.body.current,'temporary-pass');
 assert.deepEqual(f.replaced,['/#lab=a']);
});

test('the change view shows the manager sentence for any status that carries one (403 gate, 503 setup_required)',async()=>{
 for(const [status,body] of [[403,{detail:{message:'Open the manager from its own address.'}}],[503,{detail:{code:'setup_required',message:'This manager is not set up yet.'}}],[500,{}]]){
  const f=await changeView(async()=>reply(status,body));
  f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;await changeSubmit(f);
  assert.equal(f.get('change-error').textContent,(body.detail&&body.detail.message)||'The manager did not answer. Try again.');
  assert.equal(f.get('change-submit').disabled,false);assert.deepEqual(f.replaced,[]);
 }
});

test('Sign out is disabled while the password change is in flight, and the pending 200 cannot reopen the application after a sign-out',async()=>{
 let release;const pending=new Promise(r=>{release=r;});
 const f=await changeView(async()=>{await pending;return reply(200,{user:{must_change_password:false}});});
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;
 const running=changeSubmit(f);await tick();
 assert.equal(f.get('change-submit').disabled,true);assert.equal(f.get('change-signout').disabled,true);
 release();await running;
 assert.equal(f.get('change-signout').disabled,false);assert.deepEqual(f.replaced,['/']);
});

test('a sign-out that ran first stops a late change answer from navigating',async()=>{
 let release;const pending=new Promise(r=>{release=r;});
 const f=await changeView(async(u,o)=>{if(o&&o.method==='DELETE')return reply(200,{});await pending;return reply(200,{user:{must_change_password:false}});});
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;
 const running=changeSubmit(f);await tick();
 f.get('change-signout').disabled=false;
 await f.context.changeSignOut();
 release();await running;
 assert.deepEqual(f.replaced,[]);assert.equal(f.get('signin-form').hidden,false);
 assert.equal(f.requests.filter(r=>r.method==='DELETE').length,2);
});

test('the "You can sign in again." line is removed at the next attempt so it never sits beside a new answer',async()=>{
 for(const next of [()=>reply(429,{detail:{retry_after:5}}),()=>reply(401,{detail:{message:'Wrong username or password.'}})]){
  let n429=0;
  const f=fixture({fetch:async(u,o,n)=>{if(n===1)return done;n429+=1;return n429===1?reply(429,{detail:{retry_after:1}}):next();}});await tick();
  fill(f,'sam','pw');await submit(f);f.intervals[0]();
  assert.equal(f.get('signin-reason').textContent,'You can sign in again.');
  await submit(f);
  assert.equal(f.get('signin-reason').textContent,'');
 }
 const kept=fixture({fetch:async(u,o,n)=>n===1?done:reply(401,{})});await tick();
 kept.get('signin-reason').textContent='Your session ended. Sign in again to continue.';
 fill(kept,'sam','pw');await submit(kept);
 assert.equal(kept.get('signin-reason').textContent,'Your session ended. Sign in again to continue.');
});

test('401 invalid_credentials shows the current field and the next submit sends the typed value',async()=>{
 const answers=[()=>reply(401,{detail:{code:'invalid_credentials',message:'The current password is not right.'}}),()=>reply(200,{user:{must_change_password:false}})];
 const f=await changeView(async(u,o,n)=>answers[n-3]());
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;await changeSubmit(f);
 assert.equal(f.get('change-error').textContent,'The current password is not right.');
 assert.equal(f.get('change-current-field').hidden,false);assert.equal(focused.at(-1),'change-current');
 await changeSubmit(f);assert.equal(f.get('change-error').textContent,'Enter your current password.');assert.equal(focused.at(-1),'change-current');
 f.get('change-current').value='the real one';await changeSubmit(f);
 assert.equal(f.requests.at(-1).body.current,'the real one');assert.deepEqual(f.replaced,['/']);
});

test('401 signed_out during the change shows the sign-in form with the reason line',async()=>{
 const f=await changeView(async()=>reply(401,{detail:{code:'signed_out',message:'x'}}));
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;await changeSubmit(f);
 assert.equal(f.get('signin-card').hidden,false);assert.equal(f.get('signin-form').hidden,false);assert.equal(f.get('signin-change').hidden,true);
 assert.equal(f.get('signin-reason').textContent,'Your session ended. Sign in again to continue.');assert.equal(f.get('signin-reason').hidden,false);
 assert.equal(focused.at(-1),'signin-user');
});

test('after a reload the change view asks for the current password and sends it',async()=>{
 const f=fixture({fetch:async(u,o,n)=>n===1?restricted:reply(200,{user:{must_change_password:false}})});await tick();
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;await changeSubmit(f);
 assert.equal(f.get('change-error').textContent,'Enter your current password.');assert.equal(f.requests.length,1);
 f.get('change-current').value='temporary-pass';await changeSubmit(f);
 assert.deepEqual(f.requests.at(-1).body,{current:'temporary-pass',password:GOOD});
});

test('Sign out in the change view clears the held password and shows a clean form',async()=>{
 const f=await changeView(async(u,o)=>o&&o.method==='DELETE'?reply(500):reply(200,{}));
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;
 await f.context.changeSignOut();
 const out=f.requests.at(-1);assert.equal(out.url,'/api/session');assert.equal(out.method,'DELETE');assert.deepEqual(out.body,{});
 assert.equal(out.options.headers['Content-Type'],'application/json');
 assert.equal(f.get('signin-form').hidden,false);assert.equal(f.get('signin-change').hidden,true);
 assert.equal(f.get('change-new').value,'');assert.equal(f.get('change-confirm').value,'');assert.equal(f.get('signin-reason').textContent,'');
 f.get('change-new').value=GOOD;f.get('change-confirm').value=GOOD;f.get('change-current-field').hidden=true;
 await changeSubmit(f);assert.equal(f.requests.at(-1).body.current,'');
});

test('Sign out from the change view forgets the previous username',async()=>{
 const f=await changeView(async()=>reply(200,{}));
 f.get('signin-user').value='alex';
 await f.context.changeSignOut();
 assert.equal(f.get('signin-user').value,'');assert.equal(f.get('signin-password').value,'');
});

test('Sign out still shows the form when the request fails',async()=>{
 const f=await changeView(async()=>{throw new TypeError('network');});
 await f.context.changeSignOut();assert.equal(f.get('signin-form').hidden,false);assert.equal(f.get('signin-change').hidden,true);
});

test('the sign-in password is not kept in the field after the change view opens, and never in storage',async()=>{
 const f=await changeView(async()=>reply(200,{}));
 assert.equal(f.get('signin-password').value,'');
});

test('source pins: house style, no innerHTML, no inline style, no storage, no keydown',()=>{
 assert.match(source,/^'use strict';/);
 assert.doesNotMatch(source,/innerHTML|outerHTML|insertAdjacentHTML|document\.write|\.style\b|style=|localStorage|sessionStorage|indexedDB|document\.cookie|addEventListener\(\s*['"]keydown|onkeydown|\beval\(|new Function/);
});

const loginHtml=fs.readFileSync(path.join(dir,'login.html'),'utf8'),setupHtml=fs.readFileSync(path.join(dir,'setup.html'),'utf8');
const css=fs.readFileSync(path.join(dir,'login.css'),'utf8');

test('login.css names no selector of the application',()=>{
 const body=css.replace(/\/\*[\s\S]*?\*\//g,'');
 const selectors=[...body.matchAll(/(^|\})\s*([^{}@]+)\{/g)].map(m=>m[2].trim()).filter(s=>s&&!/^[\d.%]+$/.test(s));
 const allowed=new Set(['signin','signin-page','signin-card','signin-field','signin-password','brand','brandmark','actions','button','primary','secondary','banner','warn','form-error','form-help','sr-only','root','hover','disabled','focus','focus-visible','not','empty','placeholder','first-child','last-child','before','after']);
 const tokens=selectors.flatMap(s=>[...s.matchAll(/[.#:]([a-z][a-z0-9-]*)/g)].map(m=>m[1]));
 for(const token of tokens)assert.ok(allowed.has(token),'application selector in login.css: '+token);
 for(const word of ['save-chip','topbar','panel','topology','lab-','device','capture','menu','drawer','tab'])assert.ok(!body.includes(word),word);
 assert.doesNotMatch(body,/url\(\s*['"]?(?!\/static\/fabric-mark)/);
 assert.match(body,/--accent:\s*#1d6f8e/);
});

test('page assets: login.css and login.js carry the release, style.css is never linked, no inline styles',()=>{
 for(const [name,html] of [['login.html',loginHtml],['setup.html',setupHtml]]){
  assert.match(html,/<link rel="stylesheet" href="\/static\/login\.css\?v=([^"]+)">/,name);
  assert.doesNotMatch(html,/style\.css/,name);assert.doesNotMatch(html,/\sstyle=|<style|\son[a-z]+=/,name);
  const sheets=[...html.matchAll(/<link rel="stylesheet"/g)].length;assert.equal(sheets,1,name);
  const versions=[...html.matchAll(/\/static\/[^"\s?]+\?v=([^"\s]+)"/g)].map(m=>m[1]);
  assert.ok(versions.length>=2);for(const v of versions)assert.equal(v,version,name);
  assert.match(html,/<title>[^<]{2,40}<\/title>/);assert.match(html,/<html lang="en">/);
 }
 assert.match(loginHtml,/<title>Sign in<\/title>/);
 assert.deepEqual([...loginHtml.matchAll(/<script src="([^"]+)"/g)].map(m=>m[1]),['/static/login.js?v='+version]);
 assert.match(loginHtml,/<script src="\/static\/login\.js\?v=[^"]+" defer><\/script>/);
 assert.deepEqual([...setupHtml.matchAll(/<script src="([^"]+)"/g)].map(m=>m[1]),['/static/setup.js?v='+version]);
 for(const html of [loginHtml,setupHtml])for(const m of html.matchAll(/(?:src|href)="(\/static\/[^"?]+)/g))assert.ok(['/static/login.css','/static/login.js','/static/setup.js','/static/fabric-mark.svg'].includes(m[1]),m[1]);
});

test('login.html carries every id the script uses, with the pinned wording',()=>{
 for(const id of IDS)assert.match(loginHtml,new RegExp('id="'+id+'"'),id);
 assert.match(loginHtml,/id="signin-form"[^>]*\shidden/);assert.match(loginHtml,/id="signin-change"[^>]*\shidden/);
 assert.match(loginHtml,/id="change-current-field" hidden/);
 assert.doesNotMatch(loginHtml,/autofocus/);assert.doesNotMatch(loginHtml,/<form[^>]*\saction=/);
 for(const sentence of ['Use the account your administrator gave you.','Forgot your password? Ask an administrator to reset it.','Choose your own password','The password you signed in with was set by an administrator. Choose your own before you continue.','Change password and continue','This connection is not encrypted. Your password would travel in clear text. Ask the administrator to enable TLS before signing in from outside the lab network.','At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password.'])
  assert.ok(loginHtml.includes(sentence),sentence);
 assert.match(loginHtml,/id="signin-user"[^>]*maxlength="32"/);assert.match(loginHtml,/id="signin-password"[^>]*maxlength="128"/);
 assert.match(loginHtml,/id="signin-error"[^>]*role="alert"/);assert.match(loginHtml,/id="signin-checking"[^>]*role="status"/);
 assert.match(loginHtml,/aria-controls="change-new change-confirm"/);
 assert.match(loginHtml,/<form id="signin-form" novalidate/);assert.match(loginHtml,/<form id="change-form" novalidate/);
 assert.match(loginHtml,/<div class="brand">/);assert.doesNotMatch(loginHtml,/<a class="brand"/);
});
