'use strict';
const get=id=>document.getElementById(id);
const SETUP_DOWN='The manager did not answer. Try again.';
const SETUP_HEAD='Too many sign-in attempts. Try again in ';
const SETUP_TAIL=' s.';
const SETUP_CODE_HELP='That setup code is not right. On the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code';
const SETUP_READY='You can sign in again.';
let setupTimer=null;
function setupRecover(search){return new URLSearchParams(search||'').get('recover')==='1';}
function setupProblem(username,password,confirm){
 if(password.length<12||password.length>128)return 'Use at least 12 characters.';
 if(password!==confirm)return 'The two passwords are not the same.';
 const name=String(username||'').trim().toLowerCase();
 if(name&&password.toLowerCase().includes(name))return 'Choose a password that is not your username.';
 return '';
}
function setupField(message){return message==='The two passwords are not the same.'?'setup-confirm':'setup-password';}
function setupPlain(protocol,hostname){return protocol==='http:'&&!['localhost','127.0.0.1','::1','[::1]'].includes(hostname);}
function setupMessage(data,fallback){
 const message=data&&data.detail&&data.detail.message;
 return typeof message==='string'&&message?message:fallback;
}
function setupRetry(data){
 const value=data&&data.detail&&data.detail.retry_after;
 return typeof value==='number'&&Number.isFinite(value)?Math.min(3600,Math.max(1,Math.floor(value))):60;
}
async function setupRequest(url,options){
 try{
  const response=await fetch(url,options);
  if(response.redirected||response.status===0)return null;
  let data=null;
  try{data=await response.json();}catch{data=null;}
  return {status:response.status,data};
 }catch{return null;}
}
function setupThrottle(data,button,idle){
 let left=setupRetry(data);
 const said=document.createElement('span'),wait=document.createElement('span');
 said.className='sr-only';said.id='setup-wait-said';said.textContent=String(left);
 wait.id='setup-wait';wait.setAttribute('aria-hidden','true');wait.textContent=String(left);
 get('setup-error').replaceChildren(document.createTextNode(SETUP_HEAD),said,wait,document.createTextNode(SETUP_TAIL));
 button.disabled=true;
 setupTimer=setInterval(()=>{
  left-=1;
  if(left>0){wait.textContent=String(left);return;}
  clearInterval(setupTimer);setupTimer=null;
  get('setup-error').textContent='';
  button.disabled=false;button.textContent=idle;
  get('setup-code').focus();
  get('setup-reason').textContent=SETUP_READY;
 },1000);
}
async function setupSubmit(event){
 event.preventDefault();
 if(setupTimer!==null)return;
 const error=get('setup-error'),button=get('setup-submit');
 const code=get('setup-code').value.trim(),username=get('setup-user').value.trim().toLowerCase();
 const password=get('setup-password').value,confirm=get('setup-confirm').value;
 if(!code){error.textContent='Enter the setup code.';get('setup-code').focus();return;}
 const problem=setupProblem(username,password,confirm);
 if(problem){error.textContent=problem;get(setupField(problem)).focus();return;}
 const idle=button.textContent;
 button.disabled=true;button.textContent='Creating…';error.textContent='';
 if(get('setup-reason').textContent===SETUP_READY)get('setup-reason').textContent='';
 const answer=await setupRequest('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,username,password})});
 if(answer&&answer.status===429){
  button.textContent=idle;
  setupThrottle(answer.data,button,idle);
  return;
 }
 button.disabled=false;button.textContent=idle;
 const status=answer&&answer.status;
 if(status===200&&answer.data){location.replace('/');return;}
 if(status===401){
  error.textContent=setupMessage(answer.data,SETUP_CODE_HELP);
  get('setup-code').value='';get('setup-code').focus();
  return;
 }
 if(status===409){
  error.textContent=setupMessage(answer.data,'That name already exists. Choose a new name for the recovery administrator.');
  get('setup-user').focus();
  return;
 }
 if(status===404){
  error.textContent=setupMessage(answer.data,'Setup is closed. Sign in, or ask the VM administrator to run the recovery command.');
  get('setup-signin').hidden=false;
  return;
 }
 if(status===422){
  error.textContent=setupMessage(answer.data,'The manager did not accept those details. Check them and try again.');
  return;
 }
 error.textContent=setupMessage(answer&&answer.data,SETUP_DOWN);
}
function setupToggle(){
 const button=get('setup-show'),show=button.getAttribute('aria-pressed')!=='true';
 for(const id of ['setup-password','setup-confirm'])get(id).type=show?'text':'password';
 button.setAttribute('aria-pressed',show?'true':'false');
 button.textContent=show?'Hide':'Show';
}
if(setupRecover(location.search)){
 get('setup-title').textContent='Recovery: create one new administrator';
 get('setup-lead').textContent='Enter the code the recovery command printed, then choose a new administrator account. Existing accounts are not changed.';
}
if(setupPlain(location.protocol,location.hostname))get('signin-plain').hidden=false;
get('setup-form').onsubmit=setupSubmit;
get('setup-form').hidden=false;
get('setup-code').focus();
get('setup-show').onclick=setupToggle;
