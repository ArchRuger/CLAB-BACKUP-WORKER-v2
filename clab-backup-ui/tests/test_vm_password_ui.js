const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function harness(host,user){
 const elements=new Map(),element=id=>{
  if(!elements.has(id))elements.set(id,{value:'',hidden:false,checked:false,required:false,reset(){element('vm-password').value='';},querySelector(){return {};},showModal(){this.open=true;},close(){this.open=false;},addEventListener(){}});
  return elements.get(id);
 };
 const calls=[],pending=[];
 const context=vm.createContext({$:element,state:{discovery:{host},...(user?{user}:{})},document:{body:{insertAdjacentHTML(){}},querySelectorAll(){return [];},addEventListener(){}},
  withForm:(_,fn)=>pending.push(fn()),json:async(url,method,body)=>{calls.push({url,method,body});return {connected:true};},refresh:async()=>{},notify(){}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/management.js'),'utf8'),context);
 return {element,calls,pending,context};
}
test('first setup requires a password; saved passwords stay blank; old keys show migration',()=>{
 for(const host of [undefined,{auth:'password'},{auth:'key',fingerprint:'SHA256:retained'}]){
  const h=harness(host);h.element('vm-settings').onclick();
  assert.equal(h.element('vm-password').value,'');
  assert.equal(h.element('vm-password').required,host?.auth!=='password');
  assert.equal(h.element('vm-password-migration').hidden,host?.auth!=='key');
  assert.equal(h.element('vm-user').value,'clab-discovery');
 }
});
test('saving sends password only, clears it, and tests the connection',async()=>{
 const h=harness({auth:'key'});h.element('vm-settings').onclick();h.element('vm-password').value='user-created-password';
 h.element('vm-form').onsubmit({preventDefault(){},currentTarget:h.element('vm-form')});await Promise.all(h.pending);
 assert.equal(h.calls[0].body.auth,'password');assert.equal(h.calls[0].body.password,'user-created-password');
 assert.equal(Object.hasOwn(h.calls[0].body,'private_key'),false);assert.equal(Object.hasOwn(h.calls[0].body,'passphrase'),false);
 assert.equal(h.calls[1].url,'/discovery/refresh');assert.equal(h.element('vm-password').value,'');
 assert.equal(h.element('vm-dialog').open,false);
});
test('automatic discovery and trusting a replacement host key are on by default',async()=>{
 const h=harness({auth:'password',enabled:true});h.element('vm-settings').onclick();
 assert.equal(h.element('vm-enabled').checked,true);assert.equal(h.element('vm-reset-key').checked,true);
 h.element('vm-form').onsubmit({preventDefault(){},currentTarget:h.element('vm-form')});await Promise.all(h.pending);
 assert.equal(h.calls[0].body.reset_fingerprint,true);assert.equal(h.calls[0].body.enabled,true);
 const paused=harness({auth:'password',enabled:false});paused.element('vm-settings').onclick();
 assert.equal(paused.element('vm-enabled').checked,false,'an explicitly paused discovery stays paused');
 assert.equal(paused.element('vm-reset-key').checked,true);
});
test('first load prompts for the VM connection once when none is configured',()=>{
 const h=harness(undefined);
 h.context.state={discovery:{configured:false}};
 h.context.maybePromptVmConnection();
 assert.equal(h.element('vm-dialog').open,true);
 assert.equal(h.element('vm-user').value,'clab-discovery');
 // Dismissing it must not reopen the dialog on later renders in the same session.
 h.element('vm-dialog').close();
 h.context.maybePromptVmConnection();
 assert.equal(h.element('vm-dialog').open,false);
});
test('an already configured VM connection is never auto-prompted',()=>{
 const h=harness(undefined);
 h.context.state={discovery:{configured:true,host:{enabled:true}}};
 h.context.maybePromptVmConnection();
 assert.notEqual(h.element('vm-dialog').open,true);
});
test('the prompt waits until discovery status has loaded',()=>{
 const h=harness(undefined);
 h.context.state={};
 h.context.maybePromptVmConnection();
 assert.notEqual(h.element('vm-dialog').open,true);
});

// REVIEW R13 (docs/sign-on/UI.md 4.5): the VM connection is administrators-only, so an Operator is never sent into a form whose Save answers 403.
const OPERATOR={name:'bob',role:'operator',must_change_password:false},ADMIN={name:'ada',role:'admin',must_change_password:false};
const puts=h=>h.calls.filter(c=>c.url==='/host'&&c.method==='PUT');
test('REVIEW R13: openVmDialog as an operator shows #vm-operator instead of #vm-form and sends nothing',()=>{
 const h=harness({auth:'password'},OPERATOR);h.context.openVmDialog();
 assert.equal(h.element('vm-dialog').open,true,'the dialog opens with the sentence');
 assert.equal(h.element('vm-operator').hidden,false);assert.equal(h.element('vm-form').hidden,true);
 assert.deepEqual(h.calls,[]);assert.equal(h.element('vm-user').value,'','nothing of the form is filled for an operator');
});
test('REVIEW R13: an administrator (or no known user) gets the form, never the operator block',()=>{
 for(const user of [ADMIN,undefined]){
  const h=harness({auth:'password'},user);h.context.openVmDialog();
  assert.equal(h.element('vm-form').hidden,false);assert.equal(h.element('vm-operator').hidden,true);assert.equal(h.element('vm-user').value,'clab-discovery');
 }
});
test('REVIEW R13: every entry point this harness can call, as an operator, sends no PUT /api/host and shows no form',()=>{
 const entries={
  'vm-settings':h=>h.element('vm-settings').onclick(),
  'openVmDialog':h=>h.context.openVmDialog(),
  'maybePromptVmConnection':h=>{h.context.state={discovery:{configured:false},user:OPERATOR};h.context.maybePromptVmConnection();},
  'vm-connect-empty':h=>h.element('vm-connect-empty').onclick(),
  'home-vm-connect':h=>h.element('home-vm-connect').onclick()};
 for(const [name,call] of Object.entries(entries)){
  const h=harness(undefined,OPERATOR);call(h);
  assert.deepEqual(puts(h),[],name+' sent a PUT /api/host');
  if(name==='maybePromptVmConnection')assert.notEqual(h.element('vm-dialog').open,true,'the prompt does not open at all');
  else assert.equal(h.element('vm-form').hidden,true,name+' left the form hidden');
 }
});
test('REVIEW R13: the automatic first-load prompt is an administrator\'s: for an operator it never opens, even when nothing is configured',()=>{
 const h=harness(undefined,OPERATOR);h.context.state={discovery:{configured:false},user:OPERATOR};
 h.context.maybePromptVmConnection();assert.notEqual(h.element('vm-dialog').open,true);
 const admin=harness(undefined,ADMIN);admin.context.state={discovery:{configured:false},user:ADMIN};
 admin.context.maybePromptVmConnection();assert.equal(admin.element('vm-dialog').open,true);
});
test('REVIEW R13: the Home banner for an operator asks for an administrator, hides the Connect button; the empty state hides its Connect button',()=>{
 const operator=harness(undefined,OPERATOR);
 operator.context.renderLanding({configured:false,connected:false},undefined);
 assert.equal(operator.element('home-vm-banner-text').textContent,'The lab VM is not connected yet. Ask an administrator to connect it.');
 assert.equal(operator.element('home-vm-connect').hidden,true);assert.equal(operator.element('vm-connect-empty').hidden,true);
 assert.equal(operator.element('home-vm-banner').hidden,false);
 const admin=harness(undefined,ADMIN);admin.context.renderLanding({configured:false,connected:false},undefined);
 assert.match(admin.element('home-vm-banner-text').textContent,/^Connect this manager to your lab VM first\./);
 assert.equal(admin.element('home-vm-connect').hidden,false);assert.equal(admin.element('home-vm-connect').textContent,'Connect the VM');assert.equal(admin.element('vm-connect-empty').hidden,false);
 // a configured VM that does not answer: the operator still has no button to press
 const waiting=harness(undefined,OPERATOR);waiting.context.renderLanding({configured:true,connected:false},undefined);
 assert.equal(waiting.element('home-vm-connect').hidden,true);
});
test('REVIEW R13 and U5: the file-check hint names Diagnostics through diagnosticsAdvice, per role',()=>{
 const src=fs.readFileSync(path.join(__dirname,'../app/static/management.js'),'utf8');
 assert.match(src,/diagnosticsAdvice\(/,'management.js uses the helper');
 assert.doesNotMatch(src,/\(Manager ▾ › Diagnostics\)/,'the fixed administrator sentence is gone');
});
test('REVIEW R13: the other entry points reach the dialog only through openVmDialog() (so the role check covers them)',()=>{
 const read=f=>fs.readFileSync(path.join(__dirname,'../app/static/'+f),'utf8');
 for(const [file,pattern] of [['save-drawers.js',/action==='vm'\)\{saveDrawerClose\(\);if\(typeof openVmDialog==='function'\)openVmDialog\(\);return;\}/g],['save-drawers.js',/case 'vm':saveDrawerClose\(\);if\(typeof openVmDialog==='function'\)openVmDialog\(\);break;/g],['save-header.js',/case 'vm':saveClosePanel\(true\);if\(typeof openVmDialog==='function'\)openVmDialog\(\);return;/g]]){
  assert.ok((read(file).match(pattern)||[]).length>=1,file+' still opens the dialog through openVmDialog()');
 }
 const app=read('app.js');
 assert.match(app,/banner-vm/);
 const unknown=app.split('\n').find(l=>l.includes("ls.key==='unknown'"));
 assert.match(unknown,/openVmDialog\(\)/);assert.match(unknown,/role|operator|Operator/,'the lab banner omits its VM action for an operator');
});
