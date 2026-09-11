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
 return {element,calls,pending};
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
