'use strict';
// noVNC is provided by the pinned VM image; no CDN or workstation installation.
const $=id=>document.getElementById(id),sid=location.hash.slice(1);
let rfb,rfbConnected=false,ended=false,heartbeat;
const valid=/^[0-9a-f]{64}$/.test(sid),base='/api/capture/sessions/'+sid;
const VIEWER_SIGNED_OUT='Your session ended. Sign in again in the lab manager, then click Reconnect viewer.';
// The manager's refusal text: a plain string, or the sign-on answers' {code,message} (REVIEW U11).
function captureDetail(body,fallback){
 const detail=body&&body.detail;
 return typeof detail==='string'&&detail?detail:detail&&typeof detail==='object'&&typeof detail.message==='string'&&detail.message?detail.message:fallback;
}
// What the person reads for a failure: the viewer sentence for a lost session, else the error's own text.
function captureSentence(error){return error&&(error.signedOut||error.sessionEnded)?VIEWER_SIGNED_OUT:error&&error.message?error.message:'Session unavailable.';}
// Every request of this page goes through here. A page that is signed out sends nothing (REVIEW U8); a 401 signed_out
// marks the page and stops the heartbeat. The capture owner cookie is separate: an expiry does not end the capture,
// so `ended` stays false and Reconnect viewer works after a sign-in elsewhere. The relay's own 401 refusals are plain errors.
async function captureFetch(url,options){
 if(typeof sessionEnded==='function'&&sessionEnded())throw Object.assign(new Error(VIEWER_SIGNED_OUT),{status:401,signedOut:true});
 const response=await fetch(url,options);
 if(response.status===401&&typeof sessionLost==='function'){
  let body=null;try{body=await(typeof response.clone==='function'?response.clone():response).json();}catch{body=null;}
  if(sessionLost(401,body)){
   if(typeof sessionMark==='function')sessionMark();
   clearInterval(heartbeat);
   throw Object.assign(new Error(VIEWER_SIGNED_OUT),{status:401,signedOut:true});
  }
 }
 return response;
}
async function status(){
 const response=await captureFetch(base,{cache:'no-store'});
 const data=await response.json();
 if(!response.ok)throw Error(captureDetail(data,'Session unavailable.'));
 $('capture-name').textContent=data.name+' · '+data.interfaces.join(', ');
 // Up to four viewers can be open at once: the tab strip tells them apart.
 document.title=data.name+' · '+data.interfaces.join(', ')+' — Wireshark';
 // Wireshark restarts inside a running desktop. A stopped desktop has usually lost its tmpfs /pcaps, but the
 // download is the check: the service reports the loss only when the archive really holds no file.
 if(!data.running)throw Error('The Wireshark desktop stopped. Click Download saved captures to check for files saved under /pcaps (a stopped desktop usually loses them), then end this session and start a new capture.');
 return data;
}
// The manager relays only the pinned image's own noVNC modules; kept apart so tests can stand in for it.
function loadRFB(url){return import(url);}
async function connectViewer(){
 if(!valid){$('viewer-status').textContent='Invalid session link. Start a new capture from Tools › Packet capture in the lab manager.';return;}
 $('capture-download').href=base+'/download';$('capture-download').hidden=false;$('capture-end').disabled=false;
 try{
  const data=await status();
  // The container may take a few seconds to initialize its desktop on first start.
  let ready=false;
  for(let attempt=0;attempt<20&&!ended;attempt++){
   const response=await captureFetch(base+'/assets/core/rfb.js',{cache:'no-store'});
   if(response.ok){ready=true;break;}
   // 404 and 503 mean the desktop is still starting or the capture service is briefly unreachable; any other answer (the 502 for a refused, unpinned viewer file) does not change by waiting.
   if(response.status!==404&&response.status!==503){let detail='Browser viewer unavailable. Click Reconnect viewer to try again.';try{detail=captureDetail(await response.json(),detail);}catch{}throw Error(detail);}
   $('viewer-status').textContent='Starting Wireshark…';
   await new Promise(resolve=>setTimeout(resolve,1500));
  }
  if(ended)return;
  if(!ready)throw Error('Wireshark is taking longer than expected to start. Click Reconnect viewer to try again.');
  // The probe above covers only rfb.js; the relay refuses any file it imports whose hash differs from the pinned one, which rejects the import with the browser's raw wording.
  let RFB;
  try{RFB=(await loadRFB(base+'/assets/core/rfb.js')).default;}catch{throw Error('The Wireshark viewer could not be loaded because one of its files was refused or unavailable. Click Reconnect viewer; if this repeats, end this session and start a new capture.');}
  // Each desktop asks for its own session password. It reaches this page only through the manager's relay, which passes the status answer to the owning browser and neither stores nor logs it.
  rfb=new RFB($('capture-screen'),(location.protocol==='https:'?'wss://':'ws://')+location.host+base+'/websockify',data.viewer_password?{credentials:{password:data.viewer_password}}:{});
  rfb.scaleViewport=true;rfb.resizeSession=true;
  rfb.addEventListener('connect',()=>{rfbConnected=true;$('viewer-status').textContent='Connected to Wireshark on the VM.';});
  rfb.addEventListener('disconnect',()=>{rfbConnected=false;if(!ended)$('viewer-status').textContent='Disconnected from Wireshark. Click Reconnect viewer — your capture may still be running.';});
  rfb.addEventListener('credentialsrequired',()=>{$('viewer-status').textContent='Wireshark asked for this session\'s desktop password, which the viewer does not have. Click Reconnect viewer; if this repeats, end the session and start a new capture.';});
  rfb.addEventListener('securityfailure',()=>{$('viewer-status').textContent='Wireshark refused the viewer connection. An administrator should check the capture service configuration.';});
 }catch(error){$('viewer-status').textContent=captureSentence(error);}
}
// Check first, then let the browser stream the archive itself: a plain link would
// render the manager's JSON explanation (nothing saved yet, session ended) as a page.
async function downloadCaptures(event){
 event.preventDefault();
 $('viewer-status').textContent='Checking for saved captures…';
 const control=new AbortController();
 try{
  const response=await captureFetch(base+'/download',{cache:'no-store',signal:control.signal});
  if(!response.ok){let detail='Capture files unavailable.';try{detail=captureDetail(await response.json(),detail);}catch{}throw Error(detail);}
  control.abort();
  const link=document.createElement('a');link.href=base+'/download';link.download='wireshark-captures.tar';
  document.body.appendChild(link);link.click();link.remove();
  $('viewer-status').textContent='Downloading saved captures as a .tar archive — extract it to get your .pcapng files.';
 }catch(error){$('viewer-status').textContent=error.name==='AbortError'?'Download cancelled.':captureSentence(error);}
}
$('capture-download').onclick=downloadCaptures;
$('capture-reconnect').onclick=()=>location.reload();
$('capture-end').onclick=async()=>{
 if(!confirm('End this session and delete its capture files? Download saved files first.'))return;
 try{
  const response=await captureFetch(base+'/end',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!response.ok)throw Error(captureDetail(await response.json().catch(()=>null),'Could not end session.'));
  ended=true;clearInterval(heartbeat);
  // Ending removes the container, which already closed the desktop socket; only a
  // live viewer needs an explicit disconnect.
  if(rfbConnected)rfb.disconnect();
  $('capture-end').disabled=true;$('capture-download').hidden=true;
  $('viewer-status').textContent='Session ended. Its capture files were removed from the VM.';
 }catch(error){$('viewer-status').textContent=captureSentence(error);}
};
if(valid)heartbeat=setInterval(async()=>{try{const data=await status();if(data.remaining_seconds<300)$('viewer-status').textContent='This session ends in '+Math.ceil(data.remaining_seconds/60)+' minutes. Save and download your captures now.';}catch(error){$('viewer-status').textContent=captureSentence(error);}},30000);
connectViewer();
