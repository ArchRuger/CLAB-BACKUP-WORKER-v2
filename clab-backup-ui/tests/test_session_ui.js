// session.js: the shared "signed out" vocabulary of every page that sends a request (docs/sign-on/UI.md 3.2).
// Pure functions plus one flag and one resume set; the only `location` access is inside sessionGo().
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const SOURCE=fs.readFileSync(path.join(__dirname,'../app/static/session.js'),'utf8');
function harness(extra={}){
 const replaced=[];
 const context=vm.createContext({location:{pathname:'/',search:'',hash:'',replace(url){replaced.push(url);}},console,encodeURIComponent,Promise,Set,Error,...extra});
 vm.runInContext(SOURCE,context,{filename:'session.js'});
 return {context,replaced};
}
const run=(h,code)=>vm.runInContext(code,h.context);

test('sessionLost is true only for a 401 whose body says signed_out',()=>{
 const h=harness();
 assert.equal(h.context.sessionLost(401,{detail:{code:'signed_out',message:'x'}}),true);
 assert.equal(h.context.sessionLost(401,{detail:{code:'invalid_credentials'}}),false,'a wrong password is a plain error');
 assert.equal(h.context.sessionLost(401,{detail:'text'}),false);
 assert.equal(h.context.sessionLost(401,null),false);
 assert.equal(h.context.sessionLost(401,undefined),false);
 assert.equal(h.context.sessionLost(403,{detail:{code:'signed_out'}}),false,'403 is not a session end');
 assert.equal(h.context.sessionLost(200,{detail:{code:'signed_out'}}),false);
});

test('loginUrl encodes path, search and hash into next, and adds reason=ended only when given',()=>{
 const h=harness();
 assert.equal(h.context.loginUrl('/','','#lab=a&view=devices'),'/login?next='+encodeURIComponent('/#lab=a&view=devices'));
 assert.equal(h.context.loginUrl('/static/workspace.html','?mode=ssh','#x'),'/login?next='+encodeURIComponent('/static/workspace.html?mode=ssh#x'));
 assert.equal(h.context.loginUrl('/','','','ended'),'/login?next=%2F&reason=ended');
 assert.equal(h.context.loginUrl('/','','',false),'/login?next=%2F');
 assert.equal(h.context.loginUrl('/',undefined,undefined),'/login?next=%2F');
});

test('sessionMark is true the first time, false while set, true again after sessionClear',()=>{
 const h=harness();
 assert.equal(h.context.sessionEnded(),false);
 assert.equal(h.context.sessionMark(),true);assert.equal(h.context.sessionEnded(),true);
 assert.equal(h.context.sessionMark(),false);assert.equal(h.context.sessionEnded(),true);
 assert.equal(h.context.sessionClear(),undefined);assert.equal(h.context.sessionEnded(),false);
 assert.equal(h.context.sessionMark(),true);
});

test('sessionEndedError carries the sentence, status 401 and the sessionEnded marker',()=>{
 const h=harness(),error=h.context.sessionEndedError();
 assert.ok(error instanceof Error||error.name==='Error'||typeof error.message==='string');
 assert.equal(error.message,'Your session ended. Sign in again.');
 assert.equal(error.status,401);assert.equal(error.sessionEnded,true);
});

test('sessionGo replaces the location with the sign-in address and reason, and touches nothing else',()=>{
 const h=harness();
 h.context.location.pathname='/';h.context.location.search='';h.context.location.hash='#lab=a&view=devices';
 h.context.sessionGo('ended');
 assert.deepEqual(h.replaced,['/login?next='+encodeURIComponent('/#lab=a&view=devices')+'&reason=ended']);
 h.context.sessionGo();
 assert.equal(h.replaced[1],'/login?next='+encodeURIComponent('/#lab=a&view=devices'));
 const bare=vm.createContext({console,encodeURIComponent,Set,Error,Promise});
 vm.runInContext(SOURCE,bare);
 assert.doesNotThrow(()=>bare.sessionGo('ended'),'no location: nothing to do, nothing thrown');
});

test('loading session.js has no side effect, and its one `location` access is inside sessionGo()',()=>{
 const code=SOURCE.split('\n').filter(l=>!/^\s*\/\//.test(l)).join('\n');
 assert.doesNotMatch(code,/addEventListener|setTimeout|setInterval|localStorage|sessionStorage|document\b/);
 const outside=code.split('\n').filter(l=>!/^function sessionGo\b/.test(l)).join('\n');
 assert.match(code,/function sessionGo/);
 assert.doesNotMatch(outside,/\blocation\b/,'location is read only inside sessionGo');
});

test('sessionOnResume keeps one entry per function and ignores a non-function',async()=>{
 const h=harness();let a=0,b=0;
 const fa=()=>{a++;},fb=()=>{b++;};
 h.context.sessionOnResume(fa);h.context.sessionOnResume(fa);h.context.sessionOnResume(fb);h.context.sessionOnResume('x');h.context.sessionOnResume(null);
 assert.equal(await h.context.sessionRetry(),true);
 assert.equal(a,1);assert.equal(b,1);
 assert.equal(await h.context.sessionRetry(),true);
 assert.equal(a,1,'the set was emptied by the first retry');
});

test('sessionRetry with a refresh that resolves clears the flag, restores the page, runs each function once and resolves true',async()=>{
 const order=[];
 const h=harness({refresh:async()=>{order.push('refresh');},sessionRestored(){order.push('restored');}});
 h.context.sessionMark();let ran=0;h.context.sessionOnResume(()=>{ran++;order.push('resume');});
 assert.equal(await h.context.sessionRetry(),true);
 assert.deepEqual(order,['refresh','restored','resume']);
 assert.equal(ran,1);assert.equal(h.context.sessionEnded(),false);
});

test('sessionRetry after a refresh that fails on the network resolves true and leaves the flag clear',async()=>{
 let ran=0;
 const h=harness({refresh:async()=>{throw new Error('The manager did not respond.');}});
 h.context.sessionMark();h.context.sessionOnResume(()=>{ran++;});
 assert.equal(await h.context.sessionRetry(),true);
 assert.equal(ran,1);assert.equal(h.context.sessionEnded(),false);
});

test('sessionRetry after a refresh that marks the session again runs none, keeps them and resolves false',async()=>{
 let ran=0,restored=0;
 const h=harness({sessionRestored(){restored++;}});
 h.context.refresh=async()=>{h.context.sessionMark();throw Object.assign(new Error('Your session ended. Sign in again.'),{status:401});};
 h.context.sessionMark();h.context.sessionOnResume(()=>{ran++;});
 assert.equal(await h.context.sessionRetry(),false);
 assert.equal(ran,0);assert.equal(restored,0);assert.equal(h.context.sessionEnded(),true);
 // the functions were kept: a later successful retry runs them
 h.context.refresh=async()=>{};
 assert.equal(await h.context.sessionRetry(),true);
 assert.equal(ran,1);
});

test('sessionRetry without a refresh global (a standalone page) just runs the registered functions',async()=>{
 const h=harness();let ran=0;h.context.sessionMark();h.context.sessionOnResume(()=>{ran++;});
 assert.equal(await h.context.sessionRetry(),true);assert.equal(ran,1);assert.equal(h.context.sessionEnded(),false);
});

test('an exception in one resume function does not stop the others, and an async rejection is swallowed',async()=>{
 const h=harness();let ran=0;
 h.context.sessionOnResume(()=>{throw new Error('boom');});
 h.context.sessionOnResume(async()=>{throw new Error('async boom');});
 h.context.sessionOnResume(()=>{ran++;});
 assert.equal(await h.context.sessionRetry(),true);
 assert.equal(ran,1);
});

test('the top-level names of session.js are the ones the contract lists',()=>{
 const names=[...SOURCE.matchAll(/^(?:async\s+)?function\s+(\w+)/gm)].map(m=>m[1]).sort();
 assert.deepEqual(names,['loginUrl','sessionClear','sessionEnded','sessionEndedError','sessionGo','sessionLost','sessionMark','sessionOnResume','sessionRetry']);
});
