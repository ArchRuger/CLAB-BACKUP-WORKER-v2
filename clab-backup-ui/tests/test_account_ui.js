// The account in the header, Change password and Sign out (docs/sign-on/UI.md 4, 6, REVIEW R1, R10, U4): app.js (renderAccount, roleLabel) and
// account.js (passwordProblem, accountOpenPassword, accountSignOut) loaded with status.js and session.js, the harness of test_readiness_ui.js.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const STATIC=path.join(__dirname,'../app/static');
function harness({user={name:'ada',role:'admin',must_change_password:false},capture=undefined,answer={}}={}){
 const elements=new Map(),fetches=[],toasts=[],order=[];
 function element(id){
  const small={textContent:'',hidden:true},el={id,dataset:{},value:'',innerHTML:'',textContent:'',title:'',open:false,disabled:false,hidden:false,listeners:{},small,
   addEventListener(name,fn){this.listeners[name]=fn;},showModal(){this.open=true;order.push('showModal:'+id);},close(){this.open=false;},appendChild(){},remove(){},click(){},focus(){elements.focused=id;},
   querySelector(sel){return sel==='.menu-reason'&&/^(vm-settings|manager-settings)$/.test(id)?small:sel==='.form-error'?element(id+'-err'):sel.startsWith('button')?element(id+'-btn'):null;},reset(){}};
  return el;
 }
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element(id));return elements.get(id);},querySelectorAll(){return [];},createElement:element,body:element('body')};
 const context=vm.createContext({document,sessionStorage:{getItem(){return null;},setItem(){}},setTimeout:()=>0,clearTimeout(){},setInterval(){},URL:{createObjectURL:()=>'blob:x',revokeObjectURL(){}},URLSearchParams,Blob,console,Promise,Set,Error,encodeURIComponent,
  location:{pathname:'/',search:'',hash:'',replace(url){order.push('replace:'+url);}}});
 context.fetch=async(url,options={})=>{
  const call={url,method:options.method||'GET',body:options.body,headers:options.headers};
  if(url==='/api/state'&&!answer['GET /api/state'])return new Promise(()=>{});   // the page's own first poll: never answers, so it cannot overwrite the state under test
  fetches.push(call);order.push(call.method+' '+url);
  const hook=answer[call.method+' '+url];const r=hook?hook(call):{status:200,body:{}};
  if(r instanceof Error)throw r;
  return {ok:r.status>=200&&r.status<300,status:r.status,headers:{get:()=>''},json:async()=>r.body};
 };
 for(const name of ['status.js','session.js','app.js','account.js'])vm.runInContext(fs.readFileSync(path.join(STATIC,name),'utf8'),context,{filename:name});
 context.goSignIn=()=>{order.push('goSignIn');};
 context.shellRemove=(kind,key)=>{order.push('remove:'+kind+':'+key);return true;};
 context.notify=m=>{toasts.push(m);};
 if(capture!==undefined)vm.runInContext(`var captureEnabled=${JSON.stringify(capture)};`,context);
 Object.assign(context,{__user:user});vm.runInContext('state={labs:[],jobs:[],platforms:{},user:__user};',context);
 return {context,element:id=>document.getElementById(id),fetches,toasts,order,elements};
}
const run=(h,code)=>vm.runInContext(code,h.context);

test('roleLabel names the two roles and nothing else',()=>{
 const h=harness();
 assert.equal(h.context.roleLabel('admin'),'Administrator');assert.equal(h.context.roleLabel('operator'),'Operator');
 assert.equal(h.context.roleLabel('root'),'');assert.equal(h.context.roleLabel(undefined),'');
});

test('renderAccount for an administrator: chip and group show the name and role, People is offered, Diagnostics too, the two settings items are enabled and carry no reason',()=>{
 const h=harness();h.context.renderAccount();
 assert.equal(h.element('account-chip').textContent,'ada');assert.equal(h.element('account-chip').hidden,false);
 assert.equal(h.element('account-name').textContent,'ada');assert.equal(h.element('account-role').textContent,'Administrator');
 assert.equal(h.element('account-users').hidden,false);assert.equal(h.element('manager-diagnostics').hidden,false);
 for(const id of ['vm-settings','manager-settings']){assert.equal(h.element(id).disabled,false,id);assert.equal(h.element(id).small.textContent,'');assert.equal(h.element(id).small.hidden,true);}
});

test('REVIEW U4: renderAccount for an operator hides People and Diagnostics and DISABLES the two settings items with the visible reason Administrators only',()=>{
 const h=harness({user:{name:'bob',role:'operator',must_change_password:false}});h.context.renderAccount();
 assert.equal(h.element('account-role').textContent,'Operator');
 assert.equal(h.element('account-users').hidden,true);assert.equal(h.element('manager-diagnostics').hidden,true);
 for(const id of ['vm-settings','manager-settings']){
  assert.equal(h.element(id).disabled,true,id+' is disabled');
  assert.equal(h.element(id).small.textContent,'Administrators only',id+' shows its reason as text');assert.equal(h.element(id).small.hidden,false);
 }
 // and back: a role change reaches the menu on the next poll
 Object.assign(h.context,{__a:{name:'bob',role:'admin'}});run(h,'state.user=__a;');h.context.renderAccount();
 for(const id of ['vm-settings','manager-settings']){assert.equal(h.element(id).disabled,false);assert.equal(h.element(id).small.textContent,'');}
 assert.equal(h.element('account-users').hidden,false);
});

test('renderAccount with no user (state not loaded) hides the chip and People and leaves the items enabled',()=>{
 const h=harness({user:undefined});run(h,'state.user=undefined;');h.context.renderAccount();
 assert.equal(h.element('account-chip').hidden,true);assert.equal(h.element('account-chip').textContent,'');
 assert.equal(h.element('account-users').hidden,true);assert.equal(h.element('vm-settings').disabled,false);
});

test('a name is set as text, never as markup',()=>{
 const h=harness({user:{name:'<b>x</b>',role:'admin'}});h.context.renderAccount();
 assert.equal(h.element('account-chip').textContent,'<b>x</b>');assert.equal(h.element('account-chip').innerHTML,'');
});

test('REVIEW R1: renderAccount opens no dialog for must_change_password:true, and the render path holds no required-change code',()=>{
 const h=harness({user:{name:'ada',role:'admin',must_change_password:true}});h.context.renderAccount();
 assert.deepEqual(h.order.filter(o=>o.startsWith('showModal')),[]);
 const account=fs.readFileSync(path.join(STATIC,'account.js'),'utf8'),app=fs.readFileSync(path.join(STATIC,'app.js'),'utf8');
 assert.doesNotMatch(account,/required|must_change_password/);assert.doesNotMatch(app.slice(app.indexOf('function renderAccount')),/must_change_password[^]{0,60}showModal/);
});

test('the sign-out note is shown while capture is enabled or unknown and hidden when capture is not set up on this VM',()=>{
 for(const [capture,hidden] of [[null,false],[true,false],[false,true]]){
  const h=harness({capture});h.context.renderAccount();
  assert.equal(h.element('account-signout-note').hidden,hidden,'captureEnabled='+capture);
 }
 const none=harness();none.context.renderAccount();assert.equal(none.element('account-signout-note').hidden,false,'capture.js not loaded: unknown, shown');
});

test('passwordProblem: each check in the order of the dialog, none for a good entry',()=>{
 const h=harness(),p=(...a)=>h.context.passwordProblem(...a);
 assert.equal(p('ada','','long enough password','long enough password'),'Enter your current password.');
 assert.equal(p('ada','old','short','short'),'Use at least 12 characters.');
 assert.equal(p('ada','old','a good long password','a different long one'),'The two passwords are not the same.');
 assert.equal(p('ada','old','xxADAxxxxxxxxxx','xxADAxxxxxxxxxx'),'Choose a password that is not your username.','the username inside it, case-insensitive');
 assert.equal(p('someone-long-name','old','someone-long-name','someone-long-name'),'Choose a password that is not your username.');
 assert.equal(p('ada','same password 12','same password 12','same password 12'),'The new password is the same as the current one.');
 assert.equal(p('ada','old password','a fine new password','a fine new password'),'');
 assert.equal(p('ada','old password',undefined,undefined),'Use at least 12 characters.');
});

test('accountOpenPassword clears the fields and the error, opens the dialog and focuses the current password',()=>{
 const h=harness();h.element('password-current').value='x';h.element('password-new').value='y';h.element('password-error').textContent='old';
 h.context.accountOpenPassword();
 assert.equal(h.element('password-dialog').open,true);
 assert.equal(h.element('password-current').value,'');assert.equal(h.element('password-new').value,'');assert.equal(h.element('password-confirm').value,'');
 assert.equal(h.element('password-error').textContent,'');assert.equal(h.elements.focused,'password-current');
});

async function submit(h,{current='old password',next='a fine new password',confirm=next}={}){
 h.context.accountOpenPassword();
 h.element('password-current').value=current;h.element('password-new').value=next;h.element('password-confirm').value=confirm;
 await h.element('password-form').onsubmit({preventDefault(){}});
}
test('Change password: a problem is shown without a request; a good entry posts {current, password} and closes with the toast',async()=>{
 const bad=harness();await submit(bad,{next:'short',confirm:'short'});
 assert.equal(bad.fetches.length,0,'nothing sent');assert.equal(bad.element('password-error').textContent,'Use at least 12 characters.');assert.equal(bad.element('password-dialog').open,true);
 const good=harness({answer:{'POST /api/session/password':()=>({status:200,body:{changed:true}})}});await submit(good);
 assert.equal(good.fetches.length,1);assert.equal(good.fetches[0].url,'/api/session/password');assert.equal(good.fetches[0].method,'POST');
 assert.deepEqual(JSON.parse(good.fetches[0].body),{current:'old password',password:'a fine new password'});
 assert.equal(good.element('password-dialog').open,false);assert.deepEqual(good.toasts,['Password changed. Other sessions were signed out.']);
 assert.equal(good.element('password-new').value,'','the entries are cleared after success');
});
test('Change password: 401 invalid_credentials shows the manager\'s message, keeps the dialog and does not end the session',async()=>{
 const h=harness({answer:{'POST /api/session/password':()=>({status:401,body:{detail:{code:'invalid_credentials',message:'The current password is not right.'}}})}});
 await submit(h);
 assert.equal(h.element('password-error').textContent,'The current password is not right.');assert.equal(h.element('password-dialog').open,true);
 assert.equal(h.elements.focused,'password-current');assert.equal(h.context.sessionEnded(),false,'a wrong current password is not a signed-out session');
});
test('Change password: 422 and 429 show the manager\'s message as given; a network failure says the manager did not answer',async()=>{
 for(const [status,message] of [[422,'That password is too common. Choose another.'],[429,'Too many sign-in attempts. Try again in 12 s.']]){
  const h=harness({answer:{'POST /api/session/password':()=>({status,body:{detail:{code:'x',message}}})}});await submit(h);
  assert.equal(h.element('password-error').textContent,message);assert.equal(h.element('password-dialog').open,true);
 }
 const down=harness({answer:{'POST /api/session/password':()=>new TypeError('Failed to fetch')}});await submit(down);
 assert.equal(down.element('password-error').textContent,'The manager did not answer. Try again.');
});
test('Change password: Cancel and the × close the dialog without a request',()=>{
 const h=harness();h.context.accountOpenPassword();h.element('password-cancel').onclick();assert.equal(h.element('password-dialog').open,false);
 h.context.accountOpenPassword();h.element('password-close').onclick();assert.equal(h.element('password-dialog').open,false);assert.equal(h.fetches.length,0);
});

test('REVIEW R10: Sign out marks the session first, then ends the capture sessions, then deletes the session, then leaves; the poll\'s api() would refuse',async()=>{
 const h=harness({capture:true});
 const done=h.context.accountSignOut();
 assert.equal(h.context.sessionEnded(),true,'marked before any request');
 await done;
 assert.deepEqual(h.order.filter(o=>/^(POST|DELETE) |remove|goSignIn/.test(o)),['POST /api/capture/sessions/end-all','DELETE /api/session','remove:sessionStorage:activeLab','goSignIn']);
 for(const f of h.fetches.filter(f=>f.method!=='GET')){assert.equal(f.body,'{}');assert.match(JSON.stringify(f.headers),/application\/json/);}
 assert.equal(await run(h,'api("/state").then(()=>"sent",e=>e.sessionEnded===true)'),true,'api() sends nothing while the page is marked');
});
test('Sign out never goes through api() or json()',async()=>{
 const h=harness({capture:true});run(h,'api=async()=>{throw new Error("api used")};json=async()=>{throw new Error("json used")};');
 await h.context.accountSignOut();assert.ok(h.order.includes('goSignIn'));
});
test('Sign out: end-all is skipped when capture is not set up, and a failed end-all still leads to the DELETE',async()=>{
 const off=harness({capture:false});await off.context.accountSignOut();
 assert.equal(off.fetches.some(f=>/end-all/.test(f.url)),false);assert.ok(off.fetches.some(f=>f.method==='DELETE'));assert.ok(off.order.includes('goSignIn'));
 const failed=harness({capture:true,answer:{'POST /api/capture/sessions/end-all':()=>new TypeError('down')}});await failed.context.accountSignOut();
 assert.ok(failed.fetches.some(f=>f.method==='DELETE'));assert.ok(failed.order.includes('goSignIn'),'best effort');
 const refused=harness({capture:true,answer:{'POST /api/capture/sessions/end-all':()=>({status:500,body:{}})}});await refused.context.accountSignOut();
 assert.ok(refused.order.includes('goSignIn'));
});
test('REVIEW R14: only a 200 of DELETE /api/session leaves; any other status or a network failure stays, restores the page and says so',async()=>{
 for(const answer of [()=>({status:500,body:{}}),()=>({status:403,body:{}}),()=>new TypeError('down')]){
  const h=harness({capture:false,answer:{'DELETE /api/session':answer}});
  let refreshed=0;h.context.refresh=async()=>{refreshed++;};
  await h.context.accountSignOut();
  assert.equal(h.order.includes('goSignIn'),false,'the page stays');assert.equal(h.order.some(o=>o.startsWith('remove:')),false,'activeLab is kept');
  assert.deepEqual(h.toasts,['Sign-out did not reach the manager. Try again.']);
  assert.equal(h.context.sessionEnded(),false,'sessionRetry cleared the flag: the poll goes on');assert.equal(refreshed,1);
  assert.equal(h.element('account-signout').disabled,false,'Sign out stays enabled');
 }
});
test('menu items are wired: Change password opens the dialog, Sign out signs out',async()=>{
 const h=harness({capture:false});h.element('account-password').onclick();assert.equal(h.element('password-dialog').open,true);
 await h.element('account-signout').onclick();assert.ok(h.order.includes('goSignIn'));
});
test('the entries are cleared whichever way the dialog closes (Escape fires close)',()=>{
 const h=harness();h.context.accountOpenPassword();h.element('password-current').value='secret one';h.element('password-new').value='secret two';
 h.element('password-dialog').listeners.close();
 assert.equal(h.element('password-current').value,'');assert.equal(h.element('password-new').value,'');
});
test('account.js stores nothing and adds no document or window listener',()=>{
 const src=fs.readFileSync(path.join(STATIC,'account.js'),'utf8');
 assert.doesNotMatch(src,/setItem|shellSet\(|localStorage|document\.addEventListener|window\.addEventListener/);
});
