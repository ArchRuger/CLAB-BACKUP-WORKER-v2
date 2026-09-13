const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function harness(host){
 const elements=new Map(),element=id=>{
  if(!elements.has(id))elements.set(id,{value:'',hidden:false,checked:false,required:false,reset(){element('vm-password').value='';},querySelector(){return {};},showModal(){this.open=true;},close(){this.open=false;},addEventListener(){}});
  return elements.get(id);
 };
 const calls=[],pending=[];
 const context=vm.createContext({$:element,state:{discovery:{host}},document:{body:{insertAdjacentHTML(){}},querySelectorAll(){return [];},addEventListener(){}},
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
