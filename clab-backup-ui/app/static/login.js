'use strict';
const get=id=>document.getElementById(id);
const LOGIN_ENDED='Your session ended. Sign in again to continue.';
const LOGIN_DOWN='The manager did not answer. Try again.';
const LOGIN_HEAD='Too many sign-in attempts. Try again in ';
const LOGIN_TAIL=' s.';
let signedInWith='',changeName='',loginTimer=null;
function loginSafe(value){
 if(typeof value!=='string'||!value||value.length>2000)return '';
 if(value[0]!=='/'||value[1]==='/'||value[1]==='\\')return '';
 if(/[\\\u0000-\u001f\u007f]/.test(value))return '';
 const path=value.split(/[?#]/)[0];
 if(path.includes('%')||path.split('/').some(part=>part==='.'||part==='..'))return '';
 if(/^\/(login|setup)/.test(path)||path.startsWith('/api/'))return '';
 return value;
}
function loginNext(search,hash){
 let next=loginSafe(new URLSearchParams(search||'').get('next'))||'/';
 if(!next.includes('#')&&typeof hash==='string'&&hash.length>1&&hash[0]==='#'&&!/[\\\u0000-\u001f\u007f]/.test(hash)&&next.length+hash.length<=2000)next+=hash;
 return next;
}
function loginReason(search){return new URLSearchParams(search||'').get('reason')==='ended'?LOGIN_ENDED:'';}
function loginCountdown(seconds){return LOGIN_HEAD+seconds+LOGIN_TAIL;}
function loginPlain(protocol,hostname){return protocol==='http:'&&!['localhost','127.0.0.1','::1','[::1]'].includes(hostname);}
function loginMessage(data,fallback){
 const message=data&&data.detail&&data.detail.message;
 return typeof message==='string'&&message?message:fallback;
}
function changeProblem(username,current,password,confirm,askCurrent){
 if(askCurrent&&!current)return 'Enter your current password.';
 if(password.length<12||password.length>128)return 'Use at least 12 characters.';
 if(password!==confirm)return 'The two passwords are not the same.';
 const name=String(username||'').toLowerCase(),lower=password.toLowerCase();
 if(name&&lower.includes(name))return 'Choose a password that is not your username.';
 return '';
}
function changeField(message){
 if(message==='Enter your current password.')return 'change-current';
 if(message==='The two passwords are not the same.')return 'change-confirm';
 return 'change-new';
}
async function loginRequest(url,options){
 try{
  const response=await fetch(url,options);
  if(response.redirected||response.status===0)return null;
  let data=null;
  try{data=await response.json();}catch{data=null;}
  return {status:response.status,data};
 }catch{return null;}
}
function loginRetry(data){
 const value=data&&data.detail&&data.detail.retry_after;
 return typeof value==='number'&&Number.isFinite(value)?Math.min(3600,Math.max(1,Math.floor(value))):60;
}
function loginShowForm(focus){
 get('signin-checking').hidden=true;
 get('signin-change').hidden=true;
 get('signin-card').hidden=false;
 get('signin-form').hidden=false;
 if(focus)get('signin-user').focus();
}
function loginShowChange(user,askCurrent){
 get('signin-checking').hidden=true;
 get('signin-card').hidden=true;
 get('signin-change').hidden=false;
 get('change-error').textContent='';
 for(const id of ['change-current','change-new','change-confirm'])get(id).value='';
 get('change-current-field').hidden=!askCurrent;
 changeName=user&&user.name||'';
 get(askCurrent?'change-current':'change-new').focus();
}
function loginToggle(button,fields){
 const show=button.getAttribute('aria-pressed')!=='true';
 for(const field of fields)field.type=show?'text':'password';
 button.setAttribute('aria-pressed',show?'true':'false');
 button.textContent=show?'Hide':'Show';
}
function loginThrottle(data,button,idle,focusId){
 let left=loginRetry(data);
 const said=document.createElement('span'),wait=document.createElement('span');
 said.className='sr-only';said.id='signin-wait-said';said.textContent=String(left);
 wait.id='signin-wait';wait.setAttribute('aria-hidden','true');wait.textContent=String(left);
 get('signin-error').replaceChildren(document.createTextNode(LOGIN_HEAD),said,wait,document.createTextNode(LOGIN_TAIL));
 button.disabled=true;
 loginTimer=setInterval(()=>{
  left-=1;
  if(left>0){wait.textContent=String(left);return;}
  clearInterval(loginTimer);loginTimer=null;
  get('signin-error').textContent='';
  button.disabled=false;button.textContent=idle;
  get(focusId).focus();
  get('signin-reason').textContent='You can sign in again.';
 },1000);
}
async function loginLoad(){
 const reason=loginReason(location.search);
 if(reason)get('signin-reason').textContent=reason;
 if(loginPlain(location.protocol,location.hostname))get('signin-plain').hidden=false;
 const answer=await loginRequest('/api/session',{cache:'no-store'});
 const user=answer&&answer.status===200&&answer.data&&answer.data.user;
 if(!user){loginShowForm(true);return;}
 if(user.must_change_password){loginShowChange(user,true);return;}
 location.replace(loginNext(location.search,location.hash));
}
async function loginSubmit(event){
 event.preventDefault();
 if(loginTimer!==null)return;
 const userField=get('signin-user'),passField=get('signin-password'),error=get('signin-error'),button=get('signin-submit');
 const username=userField.value.trim().toLowerCase(),password=passField.value;
 if(!username||!password){
  error.textContent='Enter your username and password.';
  (username?passField:userField).focus();
  return;
 }
 const idle=button.textContent;
 button.disabled=true;button.textContent='Signing in…';error.textContent='';
 const answer=await loginRequest('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
 if(answer&&answer.status===429){
  button.textContent=idle;
  loginThrottle(answer.data,button,idle,'signin-password');
  return;
 }
 button.disabled=false;button.textContent=idle;
 if(answer&&answer.status===200&&answer.data&&answer.data.user){
  if(answer.data.user.must_change_password){
   signedInWith=password;
   passField.value='';
   loginShowChange(answer.data.user,false);
   return;
  }
  location.replace(loginNext(location.search,location.hash));
  return;
 }
 if(answer&&answer.status===401){
  error.textContent=loginMessage(answer.data,'Wrong username or password.');
  passField.value='';passField.focus();
  return;
 }
 error.textContent=loginMessage(answer&&answer.data,LOGIN_DOWN);
}
async function changeSubmit(event){
 event.preventDefault();
 const askCurrent=!get('change-current-field').hidden,error=get('change-error'),button=get('change-submit');
 const typed=get('change-current').value,password=get('change-new').value,confirm=get('change-confirm').value;
 const problem=changeProblem(changeName,typed,password,confirm,askCurrent);
 if(problem){error.textContent=problem;get(changeField(problem)).focus();return;}
 const idle=button.textContent;
 button.disabled=true;button.textContent='Changing…';error.textContent='';
 const answer=await loginRequest('/api/session/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current:askCurrent?typed:signedInWith,password})});
 button.disabled=false;button.textContent=idle;
 const status=answer&&answer.status;
 if(status===200){
  signedInWith='';
  location.replace(loginNext(location.search,location.hash));
  return;
 }
 if(status===401&&loginCode(answer.data)==='signed_out'){
  signedInWith='';
  loginShowForm(true);
  get('signin-reason').textContent=LOGIN_ENDED;
  return;
 }
 if(status===401){
  signedInWith='';
  error.textContent=loginMessage(answer.data,'The current password is not right.');
  get('change-current-field').hidden=false;get('change-current').focus();
  return;
 }
 if(status===422){
  error.textContent=loginMessage(answer.data,LOGIN_DOWN);
  get('change-new').focus();
  return;
 }
 error.textContent=status===429?loginMessage(answer.data,LOGIN_DOWN):LOGIN_DOWN;
}
function loginCode(data){return data&&data.detail&&data.detail.code;}
async function changeSignOut(){
 signedInWith='';
 await loginRequest('/api/session',{method:'DELETE',headers:{'Content-Type':'application/json'},body:'{}'});
 for(const id of ['change-current','change-new','change-confirm','signin-password','signin-user'])get(id).value='';
 get('change-error').textContent='';
 get('change-current-field').hidden=true;
 get('signin-reason').textContent='';
 get('signin-error').textContent='';
 loginShowForm(true);
}
get('signin-form').onsubmit=loginSubmit;
get('signin-show').onclick=()=>loginToggle(get('signin-show'),[get('signin-password')]);
get('change-form').onsubmit=changeSubmit;
get('change-show').onclick=()=>loginToggle(get('change-show'),[get('change-new'),get('change-confirm')]);
get('change-signout').onclick=changeSignOut;
loginLoad();
