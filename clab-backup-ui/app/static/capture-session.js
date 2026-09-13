// noVNC is provided by the pinned VM image; no CDN or workstation installation.
const $=id=>document.getElementById(id),sid=location.hash.slice(1);
let rfb,ended=false,heartbeat;
const valid=/^[0-9a-f]{64}$/.test(sid),base='/api/capture/sessions/'+sid;
async function status(){
 const response=await fetch(base,{cache:'no-store'});
 const data=await response.json();
 if(!response.ok)throw Error(data.detail||'Session unavailable.');
 $('capture-name').textContent=data.name+' · '+data.interfaces.join(', ');
 if(!data.running)throw Error('Wireshark exited. Download saved files or end this session and start a new capture.');
 return data;
}
async function connectViewer(){
 if(!valid){$('viewer-status').textContent='Invalid session link. Open Capture packets in the manager.';return;}
 $('capture-download').href=base+'/download';$('capture-download').hidden=false;$('capture-end').disabled=false;
 try{
  await status();
  // The container may take a few seconds to initialize its desktop on first start.
  let ready=false;
  for(let attempt=0;attempt<20&&!ended;attempt++){
   const response=await fetch(base+'/assets/core/rfb.js',{cache:'no-store'});
   if(response.ok){ready=true;break;}
   $('viewer-status').textContent='Starting the Wireshark desktop…';
   await new Promise(resolve=>setTimeout(resolve,1500));
  }
  if(ended)return;
  if(!ready)throw Error('The viewer is not ready. Check the capture service and click Reconnect viewer.');
  const {default:RFB}=await import(base+'/assets/core/rfb.js');
  rfb=new RFB($('capture-screen'),(location.protocol==='https:'?'wss://':'ws://')+location.host+base+'/websockify');
  rfb.scaleViewport=true;rfb.resizeSession=true;
  rfb.addEventListener('connect',()=>{$('viewer-status').textContent='Connected to Wireshark on the VM. Check its packet list for live traffic.';});
  rfb.addEventListener('disconnect',()=>{if(!ended)$('viewer-status').textContent='Viewer disconnected. Reconnect to the existing session; capture may still be running.';});
  rfb.addEventListener('securityfailure',()=>{$('viewer-status').textContent='Viewer authentication failed. Check the pinned capture image and service configuration.';});
 }catch(error){$('viewer-status').textContent=error.message;}
}
$('capture-reconnect').onclick=()=>location.reload();
$('capture-end').onclick=async()=>{
 if(!confirm('End this session and delete its temporary captures? Download saved files first.'))return;
 try{
  const response=await fetch(base+'/end',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!response.ok)throw Error((await response.json()).detail||'Could not end session.');
  ended=true;clearInterval(heartbeat);rfb?.disconnect();$('capture-end').disabled=true;$('capture-download').hidden=true;
  $('viewer-status').textContent='Session ended. Temporary captures were removed from the VM.';
 }catch(error){$('viewer-status').textContent=error.message;}
};
if(valid)heartbeat=setInterval(async()=>{try{const data=await status();if(data.remaining_seconds<300)$('viewer-status').textContent='Session expires in '+Math.ceil(data.remaining_seconds/60)+' minutes. Save and download captures now.';}catch(error){$('viewer-status').textContent=error.message;}},30000);
connectViewer();
