// noVNC is provided by the pinned VM image; no CDN or workstation installation.
const $=id=>document.getElementById(id),sid=location.hash.slice(1);
let rfb,rfbConnected=false,ended=false,heartbeat;
const valid=/^[0-9a-f]{64}$/.test(sid),base='/api/capture/sessions/'+sid;
async function status(){
 const response=await fetch(base,{cache:'no-store'});
 const data=await response.json();
 if(!response.ok)throw Error(data.detail||'Session unavailable.');
 $('capture-name').textContent=data.name+' · '+data.interfaces.join(', ');
 if(!data.running)throw Error('Wireshark has closed. Download your saved files, or end this session and start a new capture.');
 return data;
}
async function connectViewer(){
 if(!valid){$('viewer-status').textContent='Invalid session link. Start a new capture from Tools › Packet capture in the lab manager.';return;}
 $('capture-download').href=base+'/download';$('capture-download').hidden=false;$('capture-end').disabled=false;
 try{
  await status();
  // The container may take a few seconds to initialize its desktop on first start.
  let ready=false;
  for(let attempt=0;attempt<20&&!ended;attempt++){
   const response=await fetch(base+'/assets/core/rfb.js',{cache:'no-store'});
   if(response.ok){ready=true;break;}
   $('viewer-status').textContent='Starting Wireshark…';
   await new Promise(resolve=>setTimeout(resolve,1500));
  }
  if(ended)return;
  if(!ready)throw Error('Wireshark is taking longer than expected to start. Click Reconnect viewer to try again.');
  const {default:RFB}=await import(base+'/assets/core/rfb.js');
  rfb=new RFB($('capture-screen'),(location.protocol==='https:'?'wss://':'ws://')+location.host+base+'/websockify');
  rfb.scaleViewport=true;rfb.resizeSession=true;
  rfb.addEventListener('connect',()=>{rfbConnected=true;$('viewer-status').textContent='Connected to Wireshark on the VM.';});
  rfb.addEventListener('disconnect',()=>{rfbConnected=false;if(!ended)$('viewer-status').textContent='Disconnected from Wireshark. Click Reconnect viewer — your capture may still be running.';});
  rfb.addEventListener('securityfailure',()=>{$('viewer-status').textContent='Wireshark refused the viewer connection. An administrator should check the capture service configuration.';});
 }catch(error){$('viewer-status').textContent=error.message;}
}
// Check first, then let the browser stream the archive itself: a plain link would
// render the manager's JSON explanation (nothing saved yet, session ended) as a page.
async function downloadCaptures(event){
 event.preventDefault();
 $('viewer-status').textContent='Checking for saved captures…';
 const control=new AbortController();
 try{
  const response=await fetch(base+'/download',{cache:'no-store',signal:control.signal});
  if(!response.ok){let detail='Capture files unavailable.';try{detail=(await response.json()).detail||detail;}catch{}throw Error(detail);}
  control.abort();
  const link=document.createElement('a');link.href=base+'/download';link.download='wireshark-captures.tar';
  document.body.appendChild(link);link.click();link.remove();
  $('viewer-status').textContent='Downloading saved captures as a .tar archive — extract it to get your .pcapng files.';
 }catch(error){$('viewer-status').textContent=error.name==='AbortError'?'Download cancelled.':error.message;}
}
$('capture-download').onclick=downloadCaptures;
$('capture-reconnect').onclick=()=>location.reload();
$('capture-end').onclick=async()=>{
 if(!confirm('End this session and delete its capture files? Download saved files first.'))return;
 try{
  const response=await fetch(base+'/end',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!response.ok)throw Error((await response.json()).detail||'Could not end session.');
  ended=true;clearInterval(heartbeat);
  // Ending removes the container, which already closed the desktop socket; only a
  // live viewer needs an explicit disconnect.
  if(rfbConnected)rfb.disconnect();
  $('capture-end').disabled=true;$('capture-download').hidden=true;
  $('viewer-status').textContent='Session ended. Its capture files were removed from the VM.';
 }catch(error){$('viewer-status').textContent=error.message;}
};
if(valid)heartbeat=setInterval(async()=>{try{const data=await status();if(data.remaining_seconds<300)$('viewer-status').textContent='This session ends in '+Math.ceil(data.remaining_seconds/60)+' minutes. Save and download your captures now.';}catch(error){$('viewer-status').textContent=error.message;}},30000);
connectViewer();
