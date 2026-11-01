'use strict';
// account.js — Change password and Sign out for index.html (docs/sign-on/UI.md 6). Loaded after preferences.js.
// The password dialog is static markup; the entries are never stored. A forced change of an administrator-set password is not made here (REVIEW R1): it is a view of the sign-in page.
let accountBusy=false;
const SIGNOUT_END_ALL_MS=5000;
// The checks the page can make before sending (UI.md 2.3); the manager checks the same and the deny-list. '' when there is nothing to say.
function passwordProblem(username,current,next,confirm){
 const name=String(username||'').toLowerCase(),fresh=String(next||''),again=String(confirm||'');
 if(!current)return 'Enter your current password.';
 if(fresh.length<12)return 'Use at least 12 characters.';
 if(fresh!==again)return 'The two passwords are not the same.';
 if(name&&fresh.toLowerCase().includes(name))return 'Choose a password that is not your username.';
 if(fresh===current)return 'The new password is the same as the current one.';
 return '';
}
function accountOpenPassword(){
 for(const id of ['password-current','password-new','password-confirm'])if($(id))$(id).value='';
 if($('password-error'))$('password-error').textContent='';
 const dialog=$('password-dialog');if(!dialog)return;
 if(typeof dialog.showModal==='function'&&!dialog.open)dialog.showModal();
 if($('password-current')&&typeof $('password-current').focus==='function')$('password-current').focus();
}
function accountClosePassword(){const dialog=$('password-dialog');if(dialog&&dialog.open&&typeof dialog.close==='function')dialog.close();for(const id of ['password-current','password-new','password-confirm'])if($(id))$(id).value='';}
async function accountPasswordSubmit(e){
 if(e&&typeof e.preventDefault==='function')e.preventDefault();
 const error=$('password-error'),submit=$('password-submit'),user=typeof state==='object'&&state&&state.user?state.user:null;
 const current=$('password-current').value,next=$('password-new').value,confirm=$('password-confirm').value;
 const problem=passwordProblem(user&&user.name,current,next,confirm);
 if(problem){error.textContent=problem;const field=!current?$('password-current'):$('password-new');if(field&&typeof field.focus==='function')field.focus();return;}
 error.textContent='';if(submit){submit.disabled=true;submit.textContent='Changing…';}
 try{
  await json('/session/password','POST',{current,password:next});
  accountClosePassword();notify('Password changed. Other sessions were signed out.');
 }catch(failure){
  // A wrong current password is a plain 401 (not signed_out), 422 and 429 carry the manager's sentence; only a missing answer is ours.
  error.textContent=failure&&failure.status?failure.message:'The manager did not answer. Try again.';
  if(failure&&failure.detail&&failure.detail.code==='invalid_credentials'&&$('password-current')&&typeof $('password-current').focus==='function')$('password-current').focus();
 }finally{if(submit){submit.disabled=false;submit.textContent='Change password';}}
}
// Sign out (UI.md 6.4). The page is marked first so the poll stops before the cookie is gone; the two requests go straight through fetch because
// api() and json() refuse to send once the page is marked. Only a 200 of DELETE /api/session leaves: anything else keeps the page, restores it and says so.
async function accountSignOut(){
 if(accountBusy)return false;accountBusy=true;
 try{
  if(typeof sessionMark==='function')sessionMark();
  const headers={'Content-Type':'application/json'};
  if(!(typeof captureEnabled!=='undefined'&&captureEnabled===false)){
   // A stuck end-all must not hold the sign-out back: say so, wait a few seconds, then give it up (best effort; the DELETE below clears the session).
   notify('Signing out…');
   const limit=typeof AbortController==='function'?new AbortController():null,timer=limit?setTimeout(()=>limit.abort(),SIGNOUT_END_ALL_MS):0;
   try{await fetch('/api/capture/sessions/end-all',{method:'POST',headers,body:'{}',signal:limit?limit.signal:undefined});}catch{/* best effort: the owner cookie is cleared by the DELETE below */}
   if(timer)clearTimeout(timer);
  }
  let status=0;try{status=(await fetch('/api/session',{method:'DELETE',headers,body:'{}'})).status;}catch{status=0;}
  if(status===200){if(typeof shellRemove==='function')shellRemove('sessionStorage','activeLab');if(typeof goSignIn==='function')goSignIn();return true;}
  if(typeof sessionRetry==='function')await sessionRetry();
  notify('Sign-out did not reach the manager. Try again.');
  return false;
 }finally{accountBusy=false;}
}
if($('account-password'))$('account-password').onclick=()=>accountOpenPassword();
if($('account-signout'))$('account-signout').onclick=()=>accountSignOut();
if($('password-form'))$('password-form').onsubmit=accountPasswordSubmit;
if($('password-cancel'))$('password-cancel').onclick=accountClosePassword;
if($('password-close'))$('password-close').onclick=accountClosePassword;
// Escape closes the dialog natively: the entries go with it, whichever way it closed.
if($('password-dialog'))$('password-dialog').addEventListener('close',()=>{for(const id of ['password-current','password-new','password-confirm'])if($(id))$(id).value='';});
