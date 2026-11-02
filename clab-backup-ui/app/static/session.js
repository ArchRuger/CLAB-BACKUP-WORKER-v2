'use strict';
// session.js — what every page that sends a request shares about a session that ended (docs/sign-on/UI.md 3.2).
// Pure helpers, one flag and one set of resume functions. No top-level side effect, no DOM, no storage; the one
// `location` access is sessionGo(). The application's reaction (signedOut, the banner) lives in shell.js.
let sessionMarked=false;
const sessionResumes=new Set();
// A 401 whose body says signed_out. Any other 401 (invalid_credentials, the capture relay's own refusals) is a plain error.
function sessionLost(status,data){return status===401&&!!data&&typeof data==='object'&&!!data.detail&&typeof data.detail==='object'&&data.detail.code==='signed_out';}
function loginUrl(pathname,search,hash,reason){return '/login?next='+encodeURIComponent(String(pathname||'')+String(search||'')+String(hash||''))+(reason?'&reason=ended':'');}
function sessionEnded(){return sessionMarked;}
// True the first time (and the first time after sessionClear), so the caller tells the person once.
function sessionMark(){if(sessionMarked)return false;sessionMarked=true;return true;}
function sessionClear(){sessionMarked=false;}
// What a request helper throws, without sending anything, while the page is marked as signed out.
function sessionEndedError(){const error=new Error('Your session ended. Sign in again.');error.status=401;error.sessionEnded=true;return error;}
function sessionGo(reason){if(typeof location!=='undefined')location.replace(loginUrl(location.pathname,location.search,location.hash,reason));}
// A polling chain that stopped on a session end registers how to start again; sessionRetry() runs each once.
function sessionOnResume(fn){if(typeof fn==='function')sessionResumes.add(fn);}
// Try again: clear the flag, ask the manager (the application's refresh() when there is one), and either stay marked
// (the answer was 401 again: the functions are kept, resolve false) or come back (resolve true after every function ran once).
async function sessionRetry(){
 sessionClear();
 if(typeof refresh==='function'){try{await refresh();}catch{/* a network failure leaves the flag clear; the poll goes on at its next tick */}}
 if(sessionEnded())return false;
 if(typeof sessionRestored==='function')sessionRestored();
 const resumes=[...sessionResumes];sessionResumes.clear();
 for(const fn of resumes){try{const result=fn();if(result&&typeof result.catch==='function')result.catch(()=>{});}catch{/* one chain failing does not stop the others */}}
 return true;
}
