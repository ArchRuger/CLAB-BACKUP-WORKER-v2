const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const staticDir=path.join(__dirname,'../app/static');
const source=fs.readFileSync(path.join(staticDir,'users.js'),'utf8'),statusSource=fs.readFileSync(path.join(staticDir,'status.js'),'utf8'),page=fs.readFileSync(path.join(staticDir,'users.html'),'utf8');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
const ADMIN_ONLY='The last administrator stays.',OWN_DEACTIVATE='Sign out instead.',OWN_ROLE='Ask another administrator.',OWN_RESET='Use Manager ▾ › Change password… for your own account.';
const person=(name,role='operator',extra={})=>({name,role,disabled:false,must_change_password:false,created:'2026-10-01T08:00:00Z',created_by:'sam',password_changed:'2026-10-01T08:00:00Z',last_signin:null,sessions:0,...extra});
const flat=node=>(node.children||[]).length?node.children.map(flat).join(''):String(node.textContent??'');
const walk=(node,found=[])=>{found.push(node);for(const child of node.children||[])walk(child,found);return found;};
const reply=(status,body)=>({ok:status>=200&&status<300,status,json:async()=>{if(body===undefined)throw new Error('no body');return body;}});

// A DOM that keeps what the page does: elements by id, children, attributes, focus, dialogs.
function fixture(routes,{ended=false}={}){
 const elements=new Map(),calls=[],focused=[],sessionCalls=[];let isEnded=ended;
 const element=(tag,id='')=>{
  const node={tag,id,children:[],attributes:{},className:'',textContent:'',disabled:false,hidden:false,value:'',open:false,
   append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
   setAttribute(name,value){this.attributes[name]=String(value);},getAttribute(name){return this.attributes[name];},
   focus(){focused.push(this.id||this.tag);},showModal(){this.open=true;},close(){this.open=false;}};
  Object.defineProperty(node,'innerHTML',{get(){return '';},set(value){if(value)throw new Error('innerHTML is not used for untrusted text');}});
  return node;
 };
 const get=id=>{if(!elements.has(id)){const node=element('x',id);if(id==='audit-since')node.value='day';elements.set(id,node);}return elements.get(id);};
 const fetch=async(url,options={})=>{
  calls.push({url,method:options.method||'GET',body:options.body?JSON.parse(options.body):undefined});
  const key=(options.method||'GET')+' '+url.split('?')[0],handler=routes[key];
  if(!handler)throw new Error('no route '+key);
  return typeof handler==='function'?handler(url,options.body?JSON.parse(options.body):undefined):handler;
 };
 const context=vm.createContext({document:{getElementById:get,createElement:tag=>element(tag)},fetch,URLSearchParams,Date,
  setTimeout:()=>1,clearTimeout:()=>{},
  sessionEnded:()=>isEnded,sessionMark:()=>{isEnded=true;sessionCalls.push('mark');return true;},
  sessionGo:reason=>sessionCalls.push('go:'+reason),
  sessionLost:(status,data)=>status===401&&data?.detail?.code==='signed_out',
  sessionEndedError:()=>Object.assign(new Error('Your session ended. Sign in again.'),{status:401,sessionEnded:true})});
 vm.runInContext(statusSource,context);
 vm.runInContext(source,context);
 return {context,read:name=>vm.runInContext(name,context),get,calls,focused,sessionCalls,rows:()=>get('users-rows').children,auditRows:()=>get('audit-rows').children};
}
const sessionOf=(name,role='admin')=>reply(200,{user:{name,role,must_change_password:false},expires:'2026-11-01T18:00:00Z'});
const auditOf=(entries=[],total=entries.length)=>reply(200,{entries,total});
function routesFor(users,extra={},{me='sam',audit=auditOf()}={}){
 return {'GET /api/session':sessionOf(me),'GET /api/users':reply(200,{users}),'GET /api/audit':audit,...extra};
}
const buttonsOf=(f,name)=>Object.fromEntries(walk(f.rows().find(r=>flat(r.children[0])===name)).filter(n=>n.tag==='button').map(b=>[b.textContent,b]));
const captionsOf=(f,name)=>walk(f.rows().find(r=>flat(r.children[0])===name)).filter(n=>n.tag==='small').map(n=>n.textContent);

test('people rows are text: a name with markup renders as text and innerHTML is never used',async()=>{
 const f=fixture(routesFor([person('<b>x</b>'),person('sam','admin',{last_signin:null})]));await settle();
 assert.equal(f.rows().length,2);
 const cells=f.rows()[0].children;
 assert.equal(flat(cells[0]),'<b>x</b>');assert.equal(flat(cells[1]),'Operator');assert.equal(flat(cells[2]),'Active');assert.equal(flat(cells[3]),'Never');
 assert.ok(!walk(f.get('users-rows')).some(n=>n.tag==='b'));
 assert.doesNotMatch(source,/innerHTML|insertAdjacentHTML|outerHTML/);
 assert.equal(f.get('users-status').textContent.replace(/updated .*/,'updated'),'2 people · updated');
});

test('status and last sign-in: Inactive, a relative time, Administrator',async()=>{
 const recent=new Date(Date.now()-3*86400000).toISOString();
 const f=fixture(routesFor([person('jo','operator',{disabled:true,last_signin:recent}),person('sam','admin'),person('kim','admin')]));await settle();
 assert.equal(flat(f.rows()[0].children[2]),'Inactive');assert.equal(flat(f.rows()[0].children[3]),'3 days ago');assert.equal(flat(f.rows()[1].children[1]),'Administrator');
});

test('the only active administrator keeps Deactivate and Change role disabled with the sentence; their own Reset password too',async()=>{
 const f=fixture(routesFor([person('sam','admin'),person('jo')]));await settle();
 const sam=buttonsOf(f,'sam');
 assert.equal(sam['Deactivate'].disabled,true);assert.equal(sam['Deactivate'].attributes.title,ADMIN_ONLY);
 assert.equal(sam['Change role…'].disabled,true);assert.equal(sam['Change role…'].attributes.title,ADMIN_ONLY);
 assert.equal(sam['Reset password…'].disabled,true);assert.equal(sam['Reset password…'].attributes.title,OWN_RESET);
 assert.ok(captionsOf(f,'sam').includes(ADMIN_ONLY),'a visible caption, not only a title');assert.ok(captionsOf(f,'sam').includes(OWN_RESET));
 const jo=buttonsOf(f,'jo');assert.deepEqual(Object.values(jo).map(b=>b.disabled),[false,false,false]);assert.deepEqual(captionsOf(f,'jo'),[]);
 assert.equal(sam['Deactivate'].attributes['aria-describedby']!==undefined,true);
});

test('an inactive administrator does not count: the one active administrator is still the last',async()=>{
 const f=fixture(routesFor([person('sam','admin'),person('kim','admin',{disabled:true})]));await settle();
 assert.equal(buttonsOf(f,'sam')['Deactivate'].attributes.title,ADMIN_ONLY);
 assert.equal(buttonsOf(f,'kim')['Reactivate'].disabled,false);
});

test('own row with another administrator: the three own-row sentences (REVIEW R12); the other administrator is free',async()=>{
 const f=fixture(routesFor([person('sam','admin'),person('kim','admin')]));await settle();
 const sam=buttonsOf(f,'sam'),kim=buttonsOf(f,'kim');
 assert.equal(sam['Deactivate'].attributes.title,OWN_DEACTIVATE);assert.equal(sam['Change role…'].attributes.title,OWN_ROLE);assert.equal(sam['Reset password…'].attributes.title,OWN_RESET);
 assert.deepEqual(Object.values(sam).map(b=>b.disabled),[true,true,true]);
 assert.deepEqual(captionsOf(f,'sam').sort(),[OWN_DEACTIVATE,OWN_RESET,OWN_ROLE].sort());
 assert.deepEqual(Object.values(kim).map(b=>b.disabled),[false,false,false]);
});

test('403 on the people list shows #users-forbidden and hides both cards',async()=>{
 const f=fixture(routesFor([],{'GET /api/users':reply(403,{detail:{code:'admin_required',message:'Administrators only.'}})}));await settle();
 assert.equal(f.get('users-forbidden').hidden,false);assert.equal(f.get('users-card').hidden,true);assert.equal(f.get('audit-card').hidden,true);
});

test('an operator session shows #users-forbidden without asking for the people list',async()=>{
 const f=fixture({'GET /api/session':sessionOf('jo','operator')});await settle();
 assert.equal(f.get('users-forbidden').hidden,false);assert.ok(!f.calls.some(c=>c.url.startsWith('/api/users')||c.url.startsWith('/api/audit')));
});

test('a 403 from the audit list alone also shows #users-forbidden',async()=>{
 const f=fixture(routesFor([person('sam','admin')],{'GET /api/audit':reply(403,{detail:{code:'admin_required',message:'Administrators only.'}})}));await settle();
 assert.equal(f.get('users-forbidden').hidden,false);assert.equal(f.get('audit-card').hidden,true);
});

test('401 signed_out goes to the sign-in page once and later calls send nothing',async()=>{
 const f=fixture({'GET /api/session':reply(401,{detail:{code:'signed_out',message:'Your session ended. Sign in again.'}})});await settle();
 assert.deepEqual(f.sessionCalls,['mark','go:ended']);
 const before=f.calls.length;
 await assert.rejects(f.context.usersApi('/users'),error=>error.sessionEnded===true);
 assert.equal(f.calls.length,before,'no request while the session is marked ended');
});

test('a page loaded after the session ended sends no request at all',async()=>{
 const f=fixture(routesFor([person('sam','admin')]),{ended:true});await settle();
 assert.equal(f.calls.length,0);
});

test('a plain 401 (not signed_out) is an error, not a navigation',async()=>{
 const f=fixture(routesFor([person('sam','admin'),person('jo')],{'POST /api/users/jo/password':reply(401,{detail:{code:'invalid_credentials',message:'Wrong.'}})}));await settle();
 f.context.usersOpenReset(f.read("usersList")[1]);
 f.get('reset-password').value='correct horse battery';f.get('reset-confirm').value='correct horse battery';
 await f.get('reset-form').onsubmit({preventDefault(){}});
 assert.deepEqual(f.sessionCalls,[]);assert.equal(f.get('reset-error').textContent,'Wrong.');
});

test('the audit query carries every filter',async()=>{
 const f=fixture(routesFor([person('sam','admin')]));await settle();
 f.get('audit-since').value='hour';f.get('audit-actor').value=' sam ';f.get('audit-event').value='signin.failed,signin.throttled';f.get('audit-outcome').value='throttled';f.get('audit-address').value='198.51.100.9';
 await f.get('audit-form').onsubmit({preventDefault(){}});
 const url=new URL('http://x'+f.calls.filter(c=>c.url.startsWith('/api/audit')).at(-1).url),q=url.searchParams;
 assert.equal(q.get('limit'),'500');assert.equal(q.get('offset'),'0');assert.equal(q.get('event'),'signin.failed,signin.throttled');assert.equal(q.get('actor'),'sam');
 assert.equal(q.get('outcome'),'throttled');assert.equal(q.get('address'),'198.51.100.9');
 const since=Date.parse(q.get('since'));assert.ok(Math.abs(Date.now()-3600000-since)<60000,'one hour back');
});

test('an empty filter sends no parameter; All sends no since',async()=>{
 const f=fixture(routesFor([person('sam','admin')]));await settle();
 f.get('audit-since').value='all';await f.get('audit-form').onsubmit({preventDefault(){}});
 const q=new URL('http://x'+f.calls.filter(c=>c.url.startsWith('/api/audit')).at(-1).url).searchParams;
 for(const key of ['event','actor','outcome','since','address'])assert.equal(q.has(key),false,key);
});

test('the default audit window is the last 24 hours',async()=>{
 const f=fixture(routesFor([person('sam','admin')]));await settle();
 const q=new URL('http://x'+f.calls.find(c=>c.url.startsWith('/api/audit')).url).searchParams;
 assert.ok(Math.abs(Date.now()-86400000-Date.parse(q.get('since')))<60000);
});

test('audit rows are text; actor - shows a dash; an unknown code shows itself',async()=>{
 const entries=[
  {time:'2026-11-01T09:12:30Z',actor:'<i>sam</i>',event:'signin',outcome:'ok',source:'203.0.113.7',target:'',detail:''},
  {time:'2026-11-01T09:10:00Z',actor:'-',event:'signin.throttled',outcome:'throttled',source:'198.51.100.9',target:'',detail:'pair count=12 retry_after=30'},
  {time:'2026-11-01T09:00:00Z',actor:'sam',event:'brand.new',outcome:'weird',source:'',target:'',detail:'novel'}];
 const f=fixture(routesFor([person('sam','admin')],{},{audit:auditOf(entries,3)}));await settle();
 const rows=f.auditRows();assert.equal(rows.length,3);
 assert.equal(flat(rows[0].children[0]),'2026-11-01 09:12');assert.equal(flat(rows[0].children[1]),'<i>sam</i>');assert.ok(!walk(f.get('audit-rows')).some(n=>n.tag==='i'));
 assert.equal(flat(rows[0].children[2]),'Signed in');assert.equal(flat(rows[0].children[3]),'Succeeded');assert.equal(flat(rows[0].children[4]),'203.0.113.7');
 assert.equal(flat(rows[1].children[1]),'—');assert.equal(flat(rows[1].children[2]),'Sign-in attempt');assert.equal(flat(rows[1].children[3]),'Throttled');
 assert.equal(flat(rows[1].children[5]),'this name from this source · 12 attempts in one minute · delayed 30 s');
 assert.equal(flat(rows[2].children[2]),'brand.new');assert.equal(flat(rows[2].children[3]),'weird');assert.equal(flat(rows[2].children[5]),'novel');
 assert.match(f.get('audit-status').textContent,/^3 events shown \(latest 500 matching\)\. Updated \d\d:\d\d\.$/);
});

test('every event, outcome and reason code of the one vocabulary has a label; the lists are exactly these codes',()=>{
 const f=fixture({});const c=f.context;
 const events=['setup','setup.failed','recover.requested','recover.expired','signin','signin.failed','signin.throttled','signout','session.expired','session.ended','password.changed','user.created','user.deleted','user.disabled','user.enabled','user.role','user.password_reset','forbidden','manager.reset'];
 const reasons=['setup','recover','invalid_code','weak_password','invalid_name','exists','invalid_credentials','disabled','bad_record','pair','source','name','busy','idle','absolute','user_disabled','user_deleted','password_reset','password_changed','evicted','admin_required'];
 assert.deepEqual(Object.keys(JSON.parse(JSON.stringify(f.read("AUDIT_EVENT_LABELS")))).sort(),[...events].sort());
 assert.deepEqual(Object.keys(JSON.parse(JSON.stringify(f.read("AUDIT_OUTCOME_LABELS")))).sort(),['failed','ok','throttled']);
 assert.deepEqual(Object.keys(JSON.parse(JSON.stringify(f.read("AUDIT_DETAIL_LABELS")))).sort(),[...reasons].sort());
 const labelled={setup:'First administrator created','setup.failed':'Setup attempt','recover.requested':'Recovery code created','recover.expired':'Recovery code expired',signin:'Signed in','signin.failed':'Sign-in attempt','signin.throttled':'Sign-in attempt',signout:'Signed out','session.expired':'Session ended','session.ended':'Session ended','password.changed':'Password changed','user.created':'Person added','user.deleted':'Person deleted','user.disabled':'Deactivated','user.enabled':'Reactivated','user.role':'Role changed','user.password_reset':'Password reset by an administrator',forbidden:'Refused (administrators only)','manager.reset':'Manager reset'};
 for(const code of events)assert.equal(c.auditEventLabel(code),labelled[code],code);
 assert.equal(c.auditEventLabel('setup','recover'),'Recovery administrator created');
 assert.equal(c.auditEventLabel('mystery'),'mystery');
 assert.equal(c.auditOutcomeLabel('ok'),'Succeeded');assert.equal(c.auditOutcomeLabel('failed'),'Failed');assert.equal(c.auditOutcomeLabel('throttled'),'Throttled');assert.equal(c.auditOutcomeLabel('odd'),'odd');
});

test('the label maps are JSON object literals a Python test can lift out of the file',()=>{
 for(const name of ['AUDIT_EVENT_LABELS','AUDIT_OUTCOME_LABELS','AUDIT_DETAIL_LABELS']){
  const match=source.match(new RegExp('const '+name+'=(\\{[\\s\\S]*?\\n\\});'));
  assert.ok(match,name);
  const parsed=JSON.parse(match[1]);assert.ok(Object.keys(parsed).length>=3);
  for(const line of match[1].split('\n').slice(1,-1))assert.match(line,/^ "[^"]+":"[^"]+",?$/,'one entry per line, quoted keys: '+line);
 }
});

test('auditDetail translates tokens and joins them with a middle dot',()=>{
 const {auditDetail}=fixture({}).context;
 assert.equal(auditDetail('signin.failed','invalid_credentials count=12'),'wrong password · 12 attempts in one minute');
 assert.equal(auditDetail('signin.failed','count=1'),'1 attempt in one minute');
 assert.equal(auditDetail('signin.throttled','source count=3 retry_after=30'),'this source · 3 attempts in one minute · delayed 30 s');
 assert.equal(auditDetail('user.created','role=admin'),'Administrator');assert.equal(auditDetail('user.role','role=operator'),'Operator');
 assert.equal(auditDetail('session.expired','idle'),'idle');assert.equal(auditDetail('session.expired','absolute'),'after the maximum session length');
 assert.equal(auditDetail('session.ended','password_reset'),'password reset by an administrator');assert.equal(auditDetail('session.ended','evicted'),'too many sessions');
 assert.equal(auditDetail('setup','recover'),'recovery');assert.equal(auditDetail('setup','setup'),'first run');
 assert.equal(auditDetail('signin.failed','strange_word'),'strange_word');assert.equal(auditDetail('signin',''),'');assert.equal(auditDetail('signin',undefined),'');
 assert.equal(auditDetail('forbidden','admin_required count=2'),'administrators only · 2 attempts in one minute');
});

test('the target joins the details: for a person on user rows, at a route on forbidden',async()=>{
 const entries=[{time:'2026-11-01T09:00:00Z',actor:'sam',event:'user.created',outcome:'ok',source:'203.0.113.7',target:'jo',detail:'role=operator'},
  {time:'2026-11-01T08:59:00Z',actor:'jo',event:'forbidden',outcome:'failed',source:'203.0.113.8',target:'/api/users',detail:'admin_required count=1'},
  {time:'2026-11-01T08:58:00Z',actor:'sam',event:'user.disabled',outcome:'ok',source:'203.0.113.7',target:'jo',detail:''}];
 const f=fixture(routesFor([person('sam','admin')],{},{audit:auditOf(entries)}));await settle();
 assert.equal(flat(f.auditRows()[0].children[5]),'Operator · for jo');
 assert.equal(flat(f.auditRows()[1].children[5]),'administrators only · 1 attempt in one minute · at /api/users');
 assert.equal(flat(f.auditRows()[2].children[5]),'for jo');
});

test('the Event filter has one option per label and Sign-in attempt sends both codes',async()=>{
 const f=fixture(routesFor([person('sam','admin')]));await settle();
 const options=f.get('audit-event').children.map(o=>[o.textContent,o.value]);
 assert.deepEqual(options[0],['All','']);
 assert.deepEqual(options.find(o=>o[0]==='Sign-in attempt'),['Sign-in attempt','signin.failed,signin.throttled']);
 assert.deepEqual(options.find(o=>o[0]==='Session ended'),['Session ended','session.expired,session.ended']);
 assert.equal(new Set(options.map(o=>o[0])).size,options.length,'no label twice');
 const codes=options.flatMap(o=>o[1]?o[1].split(','):[]).sort();
 assert.deepEqual(codes,Object.keys(JSON.parse(JSON.stringify(f.read('AUDIT_EVENT_LABELS')))).sort());
});

test('empty audit result, audit failure and network failure each say so; none leaves a loading state',async()=>{
 let f=fixture(routesFor([person('sam','admin')]));await settle();
 assert.equal(flat(f.auditRows()[0]),'No events match. Change the filters.');assert.equal(f.get('audit-apply').disabled,false);
 f=fixture(routesFor([person('sam','admin')],{'GET /api/audit':reply(500,{detail:{code:'x',message:'The audit log could not be read.'}})}));await settle();
 assert.equal(f.get('audit-status').textContent,'The list could not be loaded: The audit log could not be read.');assert.equal(f.get('audit-apply').disabled,false);
 f=fixture(routesFor([person('sam','admin')],{'GET /api/users':async()=>{throw new Error('offline');}}));await settle();
 assert.equal(f.get('users-status').textContent,'The list could not be loaded: The manager did not answer. Try again.');
});

test('Add person disabled until the list is known',async()=>{
 let release;
 const f=fixture(routesFor([person('sam','admin')],{'GET /api/users':()=>new Promise(resolve=>{release=()=>resolve(reply(200,{users:[person('sam','admin')]}));})}));await settle();
 assert.equal(f.get('users-add').disabled,true);assert.equal(f.get('users-status').textContent,'Loading…');
 release();await settle();assert.equal(f.get('users-add').disabled,false);
});

test('Add a person: checks first, then POST with a lowercased name, then both lists reload and a toast says so',async()=>{
 const users=[person('sam','admin')];
 const f=fixture(routesFor(users,{'POST /api/users':(url,body)=>{users.push(person(body.name,body.role));return reply(200,{user:person(body.name,body.role)});}}));await settle();
 f.get('users-add').onclick();assert.equal(f.get('user-dialog').open,true);assert.equal(f.get('user-role').value,'operator');
 const submit=()=>f.get('user-form').onsubmit({preventDefault(){}});
 f.get('user-name').value='J!';f.get('user-password').value='correct horse battery';f.get('user-confirm').value='correct horse battery';await submit();
 assert.equal(f.get('user-error').textContent,'Use lowercase letters, digits, dot, dash or underscore, 2 to 32 characters.');
 f.get('user-name').value='Jo';f.get('user-password').value='short';f.get('user-confirm').value='short';await submit();
 assert.equal(f.get('user-error').textContent,'Use at least 12 characters.');
 f.get('user-password').value='correct horse battery';f.get('user-confirm').value='correct horse batterY';await submit();
 assert.equal(f.get('user-error').textContent,'The two passwords are not the same.');
 f.get('user-password').value='JO-jo-jo-jo-jo-jo';f.get('user-name').value='jo-jo-jo-jo-jo';
 f.get('user-password').value='Jo-Jo-Jo-Jo-Jo';f.get('user-confirm').value='Jo-Jo-Jo-Jo-Jo';await submit();
 assert.equal(f.get('user-error').textContent,'Choose a password that is not your username.');
 assert.ok(!f.calls.some(c=>c.method==='POST'),'nothing sent for a refused form');
 const before=f.calls.length;
 f.get('user-name').value='Jo';f.get('user-role').value='admin';f.get('user-password').value='correct horse battery';f.get('user-confirm').value='correct horse battery';await submit();
 const post=f.calls.find(c=>c.method==='POST');assert.deepEqual(post.body,{name:'jo',role:'admin',password:'correct horse battery'});
 assert.equal(f.get('user-dialog').open,false);assert.equal(f.get('toast').textContent,'jo added.');assert.equal(f.get('toast').hidden,false);
 const after=f.calls.slice(before);assert.ok(after.some(c=>c.url==='/api/users'),'people reloaded');assert.ok(after.some(c=>c.url.startsWith('/api/audit')),'audit reloaded');
 assert.equal(f.rows().length,2);
});

test('a 409 from the manager is shown as given and the dialog stays open with the fields kept',async()=>{
 const f=fixture(routesFor([person('sam','admin')],{'POST /api/users':reply(409,{detail:{code:'exists',message:'That name already exists.'}})}));await settle();
 f.get('users-add').onclick();f.get('user-name').value='sam';f.get('user-password').value='correct horse battery';f.get('user-confirm').value='correct horse battery';
 await f.get('user-form').onsubmit({preventDefault(){}});
 assert.equal(f.get('user-error').textContent,'That name already exists.');assert.equal(f.get('user-dialog').open,true);
 assert.equal(f.get('user-name').value,'sam');assert.equal(f.get('user-submit').disabled,false);
 assert.ok(f.focused.includes('user-name'));
});

test('a 422 without a message shows a sentence, not undefined; a list-shaped detail falls back',async()=>{
 const f=fixture(routesFor([person('sam','admin')],{'POST /api/users':reply(422,{detail:[{loc:['body'],msg:'x'}]})}));await settle();
 f.get('users-add').onclick();f.get('user-name').value='jo';f.get('user-password').value='correct horse battery';f.get('user-confirm').value='correct horse battery';
 await f.get('user-form').onsubmit({preventDefault(){}});
 assert.doesNotMatch(f.get('user-error').textContent,/undefined|object/);assert.ok(f.get('user-error').textContent.length>10);
});

test('the submit button is disabled while a request is in flight (no double submit)',async()=>{
 let release;const hits=[];
 const f=fixture(routesFor([person('sam','admin'),person('jo')],{'PATCH /api/users/jo':(url,body)=>{hits.push(body);return new Promise(resolve=>{release=()=>resolve(reply(200,{user:person('jo','admin')}));});}}));await settle();
 f.context.usersOpenRole(f.read("usersList")[1]);f.get('role-select').value='admin';
 const sending=f.get('role-form').onsubmit({preventDefault(){}});
 assert.equal(f.get('role-submit').disabled,true);
 f.get('role-form').onsubmit({preventDefault(){}});
 release();await sending;await settle();
 assert.equal(hits.length,1);assert.equal(f.get('role-submit').disabled,false);
});

test('Change role sends {role}; an unchanged role sends nothing; the toast names the new role',async()=>{
 const users=[person('sam','admin'),person('jo')];
 const f=fixture(routesFor(users,{'PATCH /api/users/jo':(url,body)=>{users[1]=person('jo',body.role);return reply(200,{user:users[1]});}}));await settle();
 buttonsOf(f,'jo')['Change role…'].onclick();
 assert.equal(f.get('role-dialog').open,true);assert.equal(f.get('role-name').textContent,'jo');assert.equal(f.get('role-select').value,'operator');
 await f.get('role-form').onsubmit({preventDefault(){}});
 assert.ok(!f.calls.some(c=>c.method==='PATCH'),'unchanged: no request');assert.equal(f.get('role-dialog').open,false);
 buttonsOf(f,'jo')['Change role…'].onclick();f.get('role-select').value='admin';await f.get('role-form').onsubmit({preventDefault(){}});
 assert.deepEqual(f.calls.find(c=>c.method==='PATCH').body,{role:'admin'});assert.equal(f.get('toast').textContent,'jo is now an administrator.');
 buttonsOf(f,'jo')['Change role…'].onclick();f.get('role-select').value='operator';await f.get('role-form').onsubmit({preventDefault(){}});
 assert.equal(f.get('toast').textContent,'jo is now an operator.');
});

test('Deactivate and Reactivate send {disabled}; the dialog words and button class differ',async()=>{
 const f=fixture(routesFor([person('sam','admin'),person('jo'),person('al','operator',{disabled:true})],{'PATCH /api/users/jo':reply(200,{user:person('jo')}),'PATCH /api/users/al':reply(200,{user:person('al')})}));await settle();
 buttonsOf(f,'jo')['Deactivate'].onclick();
 assert.equal(f.get('active-title').textContent,'Deactivate jo?');assert.equal(f.get('active-text').textContent,'Their open sessions end now. Their labs stay.');
 assert.equal(f.get('active-submit').textContent,'Deactivate');assert.match(f.get('active-submit').className,/danger/);
 await f.get('active-form').onsubmit({preventDefault(){}});
 assert.deepEqual(f.calls.find(c=>c.url==='/api/users/jo').body,{disabled:true});assert.equal(f.get('toast').textContent,'jo deactivated.');
 buttonsOf(f,'al')['Reactivate'].onclick();
 assert.equal(f.get('active-title').textContent,'Reactivate al?');assert.equal(f.get('active-text').textContent,'They can sign in again with their current password.');
 assert.equal(f.get('active-submit').textContent,'Reactivate');assert.match(f.get('active-submit').className,/primary/);assert.doesNotMatch(f.get('active-submit').className,/danger/);
 await f.get('active-form').onsubmit({preventDefault(){}});
 assert.deepEqual(f.calls.find(c=>c.url==='/api/users/al').body,{disabled:false});assert.equal(f.get('toast').textContent,'al reactivated.');
});

test('Reset password: policy checks, then POST {password} to the encoded name, toast, no password kept',async()=>{
 const f=fixture(routesFor([person('sam','admin'),person('jo.x')],{'POST /api/users/jo.x/password':reply(200,{user:person('jo.x')})}));await settle();
 buttonsOf(f,'jo.x')['Reset password…'].onclick();
 assert.equal(f.get('reset-name').textContent,'jo.x');
 f.get('reset-password').value='short';f.get('reset-confirm').value='short';await f.get('reset-form').onsubmit({preventDefault(){}});
 assert.equal(f.get('reset-error').textContent,'Use at least 12 characters.');
 f.get('reset-password').value='JO.X';f.get('reset-password').value='correct horse battery';f.get('reset-confirm').value='different horse battery';await f.get('reset-form').onsubmit({preventDefault(){}});
 assert.equal(f.get('reset-error').textContent,'The two passwords are not the same.');
 f.get('reset-confirm').value='correct horse battery';await f.get('reset-form').onsubmit({preventDefault(){}});
 const post=f.calls.find(c=>c.method==='POST');assert.deepEqual(post.body,{password:'correct horse battery'});assert.equal(f.get('toast').textContent,'Password set for jo.x.');
 assert.equal(f.get('reset-password').value,'');assert.equal(f.get('reset-confirm').value,'');
 assert.doesNotMatch(JSON.stringify(f.get('toast')),/correct horse/);
});

test('a forged request past a disabled button: the manager 409 is shown as given',async()=>{
 const message='You cannot deactivate your own account. Sign out instead.';
 const f=fixture(routesFor([person('sam','admin'),person('kim','admin')],{'PATCH /api/users/sam':reply(409,{detail:{code:'self_change',message}})}));await settle();
 f.context.usersOpenActive(f.read("usersList")[0],true);await f.get('active-form').onsubmit({preventDefault(){}});
 assert.equal(f.get('active-error').textContent,message);
});

test('after a change the same button gets the focus again; the dialog closes',async()=>{
 const f=fixture(routesFor([person('sam','admin'),person('jo')],{'PATCH /api/users/jo':reply(200,{user:person('jo')})}));await settle();
 buttonsOf(f,'jo')['Deactivate'].onclick();f.focused.length=0;
 await f.get('active-form').onsubmit({preventDefault(){}});await settle();
 assert.equal(f.get('active-dialog').open,false);assert.ok(f.focused.length>0,'focus returns somewhere on the page');
});

test('every dialog has a Close button and a Cancel that close it',async()=>{
 const f=fixture(routesFor([person('sam','admin')]));await settle();
 for(const [id,close,cancel] of [['user-dialog','user-close','user-cancel'],['role-dialog','role-close','role-cancel'],['reset-dialog','reset-close','reset-cancel'],['active-dialog','active-close','active-cancel']]){
  for(const button of [close,cancel]){f.get(id).open=true;f.get(button).onclick();assert.equal(f.get(id).open,false,button);}
 }
});

test('a stale answer does not overwrite a newer one',async()=>{
 const releases=[];
 const f=fixture(routesFor([person('sam','admin')],{'GET /api/audit':()=>new Promise(resolve=>releases.push(resolve))}));await settle();
 const second=f.context.auditLoad();await settle();
 releases[1](auditOf([{time:'2026-11-01T09:00:00Z',actor:'new',event:'signin',outcome:'ok',source:'1.1.1.1',target:'',detail:''}]));await settle();
 releases[0](auditOf([{time:'2026-11-01T08:00:00Z',actor:'old',event:'signin',outcome:'ok',source:'1.1.1.1',target:'',detail:''}]));await settle();await second;
 assert.equal(flat(f.auditRows()[0].children[1]),'new');
});

test('users.html: ids, scripts with ?v=, no inline style or handler, dialogs with Close, every id users.js reads exists',()=>{
 assert.match(page,/<title>People and sign-ins · Containerlab Node Manager<\/title>/);
 assert.match(page,/<h1>People and sign-ins<\/h1>/);
 assert.match(page,/<a class="workspace-back" href="\/">← Back to My labs<\/a>/);
 for(const script of ['status.js','session.js','users.js'])assert.match(page,new RegExp('<script src="/static/'+script+'\\?v=\\d+\\.\\d+\\.\\d+" defer></script>'));
 assert.ok(page.indexOf('status.js')<page.indexOf('session.js')&&page.indexOf('session.js')<page.indexOf('users.js'));
 assert.match(page,/<link rel="stylesheet" href="\/static\/style\.css\?v=\d+\.\d+\.\d+">/);
 assert.doesNotMatch(page,/\sstyle=|<style|\son\w+=/i);
 const ids=new Set([...page.matchAll(/\sid="([^"]+)"/g)].map(m=>m[1]));
 for(const used of new Set([...source.matchAll(/usersEl\('([^']+)'\)/g)].map(m=>m[1])))assert.ok(ids.has(used),'users.html lacks #'+used);
 for(const pair of source.matchAll(/\['([a-z-]+-close)','([a-z-]+-cancel)','([a-z-]+-dialog)'\]/g))for(const id of pair.slice(1))assert.ok(ids.has(id),id);
 assert.equal((page.match(/class="icon-button close"[^>]*aria-label="Close"/g)||[]).length,4);
 assert.equal((page.match(/<dialog /g)||[]).length,4);
 for(const id of ['users-rows','users-status','users-add','user-dialog','role-dialog','reset-dialog','active-dialog','audit-rows','audit-since','audit-actor','audit-event','audit-outcome','audit-address','audit-apply','audit-form','audit-status','users-forbidden','toast'])assert.ok(ids.has(id),id);
 assert.match(page,/id="users-forbidden"[^>]*hidden/);assert.match(page,/Only administrators can open this page\./);
 assert.match(page,/<option value="day" selected>Last 24 hours<\/option>/);
 for(const field of ['user-password','user-confirm','reset-password','reset-confirm'])assert.match(page,new RegExp('id="'+field+'"[^>]*autocomplete="new-password"|autocomplete="new-password"[^>]*id="'+field+'"'));
 assert.match(page,/id="user-name"[^>]*autocomplete="off"|autocomplete="off"[^>]*id="user-name"/);
 assert.match(page,/<th scope="col">Time \(UTC\)<\/th>/);
});

test('users.js keeps the house rules: strict mode, no storage, no location outside the guarded session helpers',()=>{
 assert.match(source,/^'use strict';/);
 assert.doesNotMatch(source,/localStorage|sessionStorage|location\./);
 assert.match(source,/typeof sessionGo==='function'/);
});
