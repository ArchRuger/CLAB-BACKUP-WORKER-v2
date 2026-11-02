'use strict';
const usersEl=id=>document.getElementById(id);
// The one vocabulary of DESIGN.md 10.2. JSON object literals, one entry per line, so test_audit.py can lift them out of this file.
const AUDIT_EVENT_LABELS={
 "setup":"First administrator created",
 "setup.failed":"Setup attempt",
 "recover.requested":"Recovery code created",
 "recover.expired":"Recovery code expired",
 "signin":"Signed in",
 "signin.failed":"Sign-in attempt",
 "signin.throttled":"Sign-in attempt",
 "signout":"Signed out",
 "session.expired":"Session ended",
 "session.ended":"Session ended",
 "password.changed":"Password changed",
 "user.created":"Person added",
 "user.deleted":"Person deleted",
 "user.disabled":"Deactivated",
 "user.enabled":"Reactivated",
 "user.role":"Role changed",
 "user.password_reset":"Password reset by an administrator",
 "forbidden":"Refused (administrators only)",
 "manager.reset":"Manager reset"
};
const AUDIT_OUTCOME_LABELS={
 "ok":"Succeeded",
 "failed":"Failed",
 "throttled":"Throttled"
};
const AUDIT_DETAIL_LABELS={
 "setup":"first run",
 "recover":"recovery",
 "invalid_code":"wrong code",
 "weak_password":"password refused",
 "invalid_name":"name refused",
 "exists":"name taken",
 "invalid_credentials":"wrong password",
 "disabled":"account deactivated",
 "bad_record":"record unreadable",
 "pair":"this name from this source",
 "source":"this source",
 "name":"this name from an unfamiliar source",
 "busy":"the manager was busy",
 "idle":"idle",
 "absolute":"after the maximum session length",
 "user_disabled":"deactivated",
 "user_deleted":"deleted",
 "password_reset":"password reset by an administrator",
 "password_changed":"password changed",
 "evicted":"too many sessions",
 "admin_required":"administrators only"
};
const USERS_ROLES={admin:'Administrator',operator:'Operator'};
const USERS_NO_ANSWER='The manager did not answer. Try again.';
const USERS_SENTENCES={last:'The last administrator stays.',ownDeactivate:'Sign out instead.',ownRole:'Ask another administrator.',ownReset:'Use Manager ▾ › Change password… for your own account.'};
const USERS_NAME_RULE='Use lowercase letters, digits, dot, dash or underscore, 2 to 32 characters.';
const AUDIT_WINDOWS={hour:3600000,day:86400000,week:604800000};
// var, not let: the tests read the list through the context.
var usersList=[];
let usersMe='',usersSeq=0,auditSeq=0,usersToastTimer,usersButtons=new Map(),usersTarget='',usersDisable=true,usersFailed=false,usersGen=0;

function usersRoleLabel(role){return USERS_ROLES[role]||String(role||'');}
function auditEventLabel(event,detail){
 if(event==='setup'&&String(detail||'').split(/\s+/).includes('recover'))return 'Recovery administrator created';
 return Object.hasOwn(AUDIT_EVENT_LABELS,event)?AUDIT_EVENT_LABELS[event]:String(event??'');
}
function auditOutcomeLabel(outcome){return Object.hasOwn(AUDIT_OUTCOME_LABELS,outcome)?AUDIT_OUTCOME_LABELS[outcome]:String(outcome??'');}
// detail is a space-separated list of tokens; each is translated, the translations are joined with a middle dot.
function auditDetail(event,detail){
 const tokens=String(detail??'').split(/\s+/).filter(Boolean);
 return tokens.map(token=>{
  const pair=token.match(/^(count|retry_after|role)=(.*)$/);
  if(pair){
   const [,key,value]=pair;
   if(key==='count')return value==='1'?'1 attempt in one minute':value+' attempts in one minute';
   if(key==='retry_after')return 'delayed '+value+' s';
   return usersRoleLabel(value);
  }
  return Object.hasOwn(AUDIT_DETAIL_LABELS,token)?AUDIT_DETAIL_LABELS[token]:token;
 }).join(' · ');
}
// The Details cell: the translated detail, then the target ("for jo" on a person row, "at /api/users" on a refusal).
function auditDetailCell(entry){
 const parts=[auditDetail(entry.event,entry.detail)].filter(Boolean),target=String(entry.target??'');
 if(target&&String(entry.event).startsWith('user.'))parts.push('for '+target);
 else if(target&&entry.event==='forbidden')parts.push('at '+target);
 return parts.join(' · ');
}
function auditTime(value){
 const time=Date.parse(value);
 return Number.isNaN(time)?String(value??''):new Date(time).toISOString().slice(0,16).replace('T',' ');
}
function usersClock(){const now=new Date();return String(now.getHours()).padStart(2,'0')+':'+String(now.getMinutes()).padStart(2,'0');}
function usersPasswordProblem(password,confirm,name){
 if(password.length<12)return 'Use at least 12 characters.';
 if(password.length>128)return 'Use at most 128 characters.';
 if(password!==confirm)return 'The two passwords are not the same.';
 if(name&&password.toLowerCase()===String(name).toLowerCase())return 'Choose a password that is not your username.';
 return '';
}
function usersNode(tag,text,className){
 const node=document.createElement(tag);
 if(text!==undefined)node.textContent=text;
 if(className)node.className=className;
 return node;
}
function usersToast(message){
 const toast=usersEl('toast');toast.textContent=message;toast.hidden=false;
 clearTimeout(usersToastTimer);usersToastTimer=setTimeout(()=>{toast.hidden=true;},5000);
}
function usersFocus(id){const node=usersEl(id);if(node&&typeof node.focus==='function')node.focus();}
function usersError(status,message,extra){return Object.assign(new Error(message),{status},extra);}
function usersEnded(){return typeof sessionEnded==='function'&&sessionEnded();}

// Every request of this page. While the session is marked ended nothing is sent (UI.md 3.1).
async function usersApi(path,method='GET',data){
 if(usersEnded())throw typeof sessionEndedError==='function'?sessionEndedError():usersError(401,'Your session ended. Sign in again.',{sessionEnded:true});
 const options=method==='GET'?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data??{})};
 let response,body=null;
 try{response=await fetch('/api'+path,options);}catch{throw usersError(0,USERS_NO_ANSWER);}
 try{body=await response.json();}catch{body=null;}
 const lost=typeof sessionLost==='function'?sessionLost(response.status,body):response.status===401&&body?.detail?.code==='signed_out';
 if(lost){
  if(typeof sessionMark==='function')sessionMark();
  if(typeof sessionGo==='function')sessionGo('ended');
  throw usersError(401,'Your session ended. Sign in again.');
 }
 if(!response.ok){
  const detail=body?.detail;
  const message=typeof detail?.message==='string'&&detail.message?detail.message:typeof detail==='string'&&detail?detail:body===null?'The manager answered HTTP '+response.status+'. Try again.':'The manager did not accept that. Check the form fields and try again.';
  throw usersError(response.status,message,{code:detail?.code});
 }
 if(body===null)throw usersError(response.status,USERS_NO_ANSWER);
 return body;
}

// 403: this page is for administrators. Both cards go, one sentence stays.
function usersForbidden(){
 for(const id of ['user-dialog','role-dialog','reset-dialog','active-dialog']){const dialog=usersEl(id);if(dialog.open&&typeof dialog.close==='function')dialog.close();}
 usersEl('users-card').hidden=true;usersEl('audit-card').hidden=true;usersEl('users-forbidden').hidden=false;
}
function usersForbiddenError(error){if(error?.status===403){usersForbidden();return true;}return false;}

function usersButton(label,name,action,reason,onclick,index){
 const button=usersNode('button',label,'button secondary small');
 button.type='button';button.setAttribute('data-user',name);button.setAttribute('data-action',action);
 usersButtons.set(name+'\n'+action,button);
 if(reason){
  button.disabled=true;button.setAttribute('title',reason);
  const caption=usersNode('small',reason,'menu-reason');caption.id='users-hint-'+index+'-'+action;button.setAttribute('aria-describedby',caption.id);
  return [button,caption];
 }
 button.onclick=onclick;
 return [button];
}
function usersRender(){
 const body=usersEl('users-rows');body.replaceChildren();usersButtons=new Map();
 const admins=usersList.filter(user=>user.role==='admin'&&!user.disabled).length;
 if(!usersList.length){
  const row=document.createElement('tr'),cell=usersNode('td','No people yet.');cell.colSpan=5;row.append(cell);body.append(row);return;
 }
 usersList.forEach((user,index)=>{
  const own=user.name===usersMe,last=user.role==='admin'&&!user.disabled&&admins===1;
  const row=document.createElement('tr'),status=usersNode('span',user.disabled?'Inactive':'Active','pill '+(user.disabled?'neutral':'ok'));
  const when=user.last_signin?(typeof relativeTimeShort==='function'?relativeTimeShort(user.last_signin):auditTime(user.last_signin)):'';
  const cells=[usersNode('td',user.name),usersNode('td',usersRoleLabel(user.role)),document.createElement('td'),usersNode('td',when||'Never'),document.createElement('td')];
  cells[2].append(status);
  // The last administrator's sentence wins on Deactivate and Change role: no other administrator exists to ask.
  const deactivateReason=user.disabled?'':last?USERS_SENTENCES.last:own?USERS_SENTENCES.ownDeactivate:'';
  const roleReason=last?USERS_SENTENCES.last:own?USERS_SENTENCES.ownRole:'';
  const resetReason=own?USERS_SENTENCES.ownReset:'';
  cells[4].append(
   ...usersButton('Change role…',user.name,'role',roleReason,()=>usersOpenRole(user),index),
   ...usersButton('Reset password…',user.name,'reset',resetReason,()=>usersOpenReset(user),index),
   ...(user.disabled?usersButton('Reactivate',user.name,'active','',()=>usersOpenActive(user,false),index):usersButton('Deactivate',user.name,'active',deactivateReason,()=>usersOpenActive(user,true),index)));
  row.append(...cells);body.append(row);
 });
}
async function usersLoad(){
 const seq=++usersSeq,status=usersEl('users-status');
 status.textContent='Loading…';usersEl('users-add').disabled=true;usersEl('users-retry').hidden=true;usersFailed=false;
 try{
  if(!usersMe){
   const session=await usersApi('/session');
   if(session?.user?.role!=='admin'){usersForbidden();return false;}
   usersMe=String(session.user.name||'');
  }
  const data=await usersApi('/users');
  if(seq!==usersSeq)return false;
  usersList=Array.isArray(data.users)?data.users:[];usersRender();
  usersEl('users-add').disabled=false;
  status.textContent=(usersList.length===1?'1 person':usersList.length+' people')+' · updated '+usersClock();
  return true;
 }catch(error){
  if(seq!==usersSeq||usersEnded())return false;
  if(usersForbiddenError(error))return false;
  status.textContent='The list could not be loaded: '+error.message;usersEl('users-retry').hidden=false;usersFailed=true;return false;
 }
}

// Dialogs
// Every opening is a new dialog: an answer to an earlier one must not act on it (usersGen), and its button works again.
function usersOpen(id,first){const dialog=usersEl(id);usersGen++;usersEl(id.replace(/-dialog$/,'-submit')).disabled=false;if(typeof dialog.showModal==='function')dialog.showModal();else dialog.open=true;if(first)usersFocus(first);}
function usersClose(id){const dialog=usersEl(id);if(typeof dialog.close==='function')dialog.close();else dialog.open=false;}
function usersOpenAdd(){
 for(const id of ['user-name','user-password','user-confirm'])usersEl(id).value='';
 usersEl('user-role').value='operator';usersEl('user-error').textContent='';usersOpen('user-dialog','user-name');
}
function usersOpenRole(user){
 usersTarget=user.name;usersEl('role-name').textContent=user.name;usersEl('role-select').value=user.role;usersEl('role-error').textContent='';usersOpen('role-dialog','role-select');
}
function usersOpenReset(user){
 usersTarget=user.name;usersEl('reset-name').textContent=user.name;usersEl('reset-password').value='';usersEl('reset-confirm').value='';usersEl('reset-error').textContent='';usersOpen('reset-dialog','reset-password');
}
function usersOpenActive(user,disable){
 usersTarget=user.name;usersDisable=disable;
 usersEl('active-title').textContent=(disable?'Deactivate ':'Reactivate ')+user.name+'?';
 usersEl('active-text').textContent=disable?'Their open sessions end now. Their labs stay.':'They can sign in again with their current password.';
 const submit=usersEl('active-submit');submit.textContent=disable?'Deactivate':'Reactivate';submit.className='button '+(disable?'danger':'primary');
 usersEl('active-error').textContent='';usersOpen('active-dialog','active-cancel');
}

// One send: error text in the dialog, button disabled meanwhile, a 403 sends the person to the forbidden sentence.
// stale() is true once another dialog was opened since the send: the outcome then goes to the toast only, naming who it was for.
async function usersSend(submitId,errorId,who,work,focusFor){
 const button=usersEl(submitId),gen=usersGen,stale=()=>gen!==usersGen;
 if(button.disabled)return false;
 usersEl(errorId).textContent='';button.disabled=true;
 try{await work(stale);return true;}
 catch(error){
  if(!usersForbiddenError(error)){
   if(stale())usersToast(who+': '+error.message);
   else{
    usersEl(errorId).textContent=error.message;
    // The dialog was closed some other way meanwhile: the refusal must still be seen.
    if(!usersEl(errorId.replace(/-error$/,'-dialog')).open)usersToast(error.message);
    const target=focusFor?.(error);if(target)usersFocus(target);
   }
  }
  return false;
 }finally{if(!stale())button.disabled=false;}
}
async function usersDone(dialogId,message,focusKey,stale){
 if(!stale)usersClose(dialogId);
 usersToast(message);
 await usersRefresh();
 if(stale)return;
 const button=usersButtons.get(focusKey);
 if(button)button.focus();else usersFocus('users-add');
}
async function usersSubmitAdd(event){
 event.preventDefault();
 const name=usersEl('user-name').value.trim().toLowerCase(),role=usersEl('user-role').value,password=usersEl('user-password').value,confirm=usersEl('user-confirm').value,error=usersEl('user-error');
 if(!/^[a-z0-9][a-z0-9._-]{1,31}$/.test(name)){error.textContent=USERS_NAME_RULE;usersFocus('user-name');return;}
 const problem=usersPasswordProblem(password,confirm,name);
 if(problem){error.textContent=problem;usersFocus('user-password');return;}
 await usersSend('user-submit','user-error',name,async stale=>{
  await usersApi('/users','POST',{name,role,password});
  if(!stale()){usersEl('user-password').value='';usersEl('user-confirm').value='';}
  await usersDone('user-dialog',name+' added.',name+'\nrole',stale());
 },failure=>failure.code==='exists'||failure.code==='invalid_name'?'user-name':failure.code==='weak_password'?'user-password':'');
}
async function usersSubmitRole(event){
 event.preventDefault();
 const name=usersTarget,user=usersList.find(item=>item.name===name),role=usersEl('role-select').value;
 if(!user||user.role===role){usersClose('role-dialog');return;}
 await usersSend('role-submit','role-error',name,async stale=>{
  await usersApi('/users/'+encodeURIComponent(name),'PATCH',{role});
  await usersDone('role-dialog',name+' is now '+(role==='admin'?'an administrator':'an operator')+'.',name+'\nrole',stale());
 });
}
async function usersSubmitReset(event){
 event.preventDefault();
 const password=usersEl('reset-password').value,confirm=usersEl('reset-confirm').value,error=usersEl('reset-error'),name=usersTarget;
 const problem=usersPasswordProblem(password,confirm,name);
 if(problem){error.textContent=problem;usersFocus('reset-password');return;}
 await usersSend('reset-submit','reset-error',name,async stale=>{
  await usersApi('/users/'+encodeURIComponent(name)+'/password','POST',{password});
  if(!stale()){usersEl('reset-password').value='';usersEl('reset-confirm').value='';}
  await usersDone('reset-dialog','Password set for '+name+'.',name+'\nreset',stale());
 },failure=>failure.code==='weak_password'?'reset-password':'');
}
async function usersSubmitActive(event){
 event.preventDefault();
 const name=usersTarget,disable=usersDisable;
 await usersSend('active-submit','active-error',name,async stale=>{
  await usersApi('/users/'+encodeURIComponent(name),'PATCH',{disabled:disable});
  await usersDone('active-dialog',name+(disable?' deactivated.':' reactivated.'),name+'\nactive',stale());
 });
}

// The audit table
function auditQuery(){
 const query=new URLSearchParams({limit:'500',offset:'0'});
 const event=usersEl('audit-event').value,actor=usersEl('audit-actor').value.trim(),outcome=usersEl('audit-outcome').value,address=usersEl('audit-address').value.trim(),window=AUDIT_WINDOWS[usersEl('audit-since').value];
 if(event)query.set('event',event);
 if(actor)query.set('actor',actor);
 if(outcome)query.set('outcome',outcome);
 if(window)query.set('since',new Date(Date.now()-window).toISOString());
 if(address)query.set('address',address);
 return query;
}
function auditRender(entries){
 const body=usersEl('audit-rows');body.replaceChildren();
 if(!entries.length){const row=document.createElement('tr'),cell=usersNode('td','No events match. Change the filters.');cell.colSpan=6;row.append(cell);body.append(row);return;}
 for(const entry of entries){
  const row=document.createElement('tr'),actor=entry.actor&&entry.actor!=='-'?String(entry.actor):'—';
  row.append(usersNode('td',auditTime(entry.time)),usersNode('td',actor),usersNode('td',auditEventLabel(entry.event,entry.detail)),usersNode('td',auditOutcomeLabel(entry.outcome)),usersNode('td',String(entry.source||'—')),usersNode('td',auditDetailCell(entry)));
  body.append(row);
 }
}
async function auditLoad(){
 const seq=++auditSeq,status=usersEl('audit-status'),apply=usersEl('audit-apply');
 status.textContent='Loading…';apply.disabled=true;
 try{
  const data=await usersApi('/audit?'+auditQuery().toString());
  if(seq!==auditSeq)return false;
  const entries=Array.isArray(data.entries)?data.entries:[];
  auditRender(entries);
  status.textContent=(entries.length===1?'1 event':entries.length+' events')+' shown (latest 500 matching). Updated '+usersClock()+'.';
  return true;
 }catch(error){
  if(seq!==auditSeq||usersEnded())return false;
  if(usersForbiddenError(error))return false;
  usersEl('audit-rows').replaceChildren();
  status.textContent='The list could not be loaded: '+error.message;return false;
 }finally{if(seq===auditSeq)apply.disabled=false;}
}
async function usersRefresh(){
 if(await usersLoad()||usersFailed)await auditLoad();
}

// One option per label; its value carries every code of that label (Sign-in attempt sends both).
function auditFillEvents(){
 const select=usersEl('audit-event'),groups=new Map();
 for(const [code,label] of Object.entries(AUDIT_EVENT_LABELS))groups.set(label,[...(groups.get(label)||[]),code]);
 const all=usersNode('option','All');all.value='';
 select.replaceChildren(all,...[...groups].map(([label,codes])=>{const option=usersNode('option',label);option.value=codes.join(',');return option;}));
}
function usersInit(){
 auditFillEvents();
 usersEl('users-add').onclick=usersOpenAdd;usersEl('users-retry').onclick=()=>usersRefresh();
 usersEl('user-form').onsubmit=usersSubmitAdd;usersEl('role-form').onsubmit=usersSubmitRole;usersEl('reset-form').onsubmit=usersSubmitReset;usersEl('active-form').onsubmit=usersSubmitActive;
 usersEl('audit-form').onsubmit=event=>{event.preventDefault();return auditLoad();};
 for(const [close,cancel,dialog] of [['user-close','user-cancel','user-dialog'],['role-close','role-cancel','role-dialog'],['reset-close','reset-cancel','reset-dialog'],['active-close','active-cancel','active-dialog']]){
  usersEl(close).onclick=()=>usersClose(dialog);usersEl(cancel).onclick=()=>usersClose(dialog);
 }
 return usersRefresh();
}
usersInit();
