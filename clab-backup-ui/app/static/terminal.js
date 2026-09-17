'use strict';
const params=new URLSearchParams(location.hash.slice(1)),lab=params.get('lab'),name=params.get('node'),labLabel=params.get('label')||'Lab';
const get=id=>document.getElementById(id);
document.title=(name||'Device')+' · '+labLabel+' · Containerlab Node Manager';get('title').textContent=(name||'Unknown device')+' · '+labLabel;
if(get('back')){get('back').href='/#'+new URLSearchParams({lab:lab||'',device:name||''});get('back').textContent='← '+labLabel;get('back').hidden=!lab;}
if(get('notice-text'))get('notice-text').textContent=`Logged in with the credentials saved for ${name||'this device'}. The session closes after 15 minutes without activity.`;
const terminal=new Terminal({cursorBlink:true,scrollback:3000,fontSize:14,fontFamily:'Consolas, "Liberation Mono", monospace',theme:{background:'#172431',foreground:'#e7eff2',cursor:'#9ad4ea',selectionBackground:'#41637780'}});
const fit=new FitAddon.FitAddon();terminal.loadAddon(fit);terminal.open(get('terminal'));
let socket=null,generation=0;
// The visible status is a student sentence; the manager's exact message stays in the title attribute.
function statusText(raw){
 const device=name||'the device',text=String(raw||'');
 const map=[[/^Connecting/,`Connecting to ${device}…`],[/^Connected$/,'Connected'],[/^Disconnected$/,'Disconnected'],[/^Session timeout/,'Closed after 15 minutes without activity. Click Reconnect to continue.'],[/^Session ended/,`The session ended. Check the device's saved credentials, or close other CLIs if too many are open.`],[/^Connection failed/,`Could not connect to ${device}.`],[/refresh VM discovery/,`${device} is not running or the lab status is stale. Refresh the lab list and try again.`],[/Assign SSH credentials/,`${device} needs login credentials. Add them in the lab under Advanced › Credentials.`],[/session limit|Too many pending/,'Too many CLIs are open (limit 32). Close one and try again.'],[/^(Lab|Node) not found/,'This lab or device is no longer in the manager.']];
 const hit=map.find(([re])=>re.test(text));return hit?hit[1]:text;
}
function setStatus(raw){const el=get('status'),text=statusText(raw);el.textContent=text;if(text===raw)el.removeAttribute('title');else el.title=raw;}
function setConnectEnabled(enabled){const b=get('connect');b.disabled=!enabled;b.title=enabled?'':'Connected — click Disconnect first to start a new session';}
function resize(){fit.fit();if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'resize',cols:Math.max(20,Math.min(400,terminal.cols)),rows:Math.max(5,Math.min(150,terminal.rows))}));}
new ResizeObserver(resize).observe(get('terminal'));
terminal.onData(data=>{if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'input',data}));});
function disconnect(){generation++;if(socket)socket.close();socket=null;setStatus('Disconnected');setConnectEnabled(true);}
async function connect(){
 disconnect();const request=++generation;
 if(!lab||!name){setStatus('Open this CLI from a device in the lab.');return;}
 setConnectEnabled(false);setStatus('Connecting…');
 try{
  const response=await fetch('/api/labs/'+encodeURIComponent(lab)+'/terminal-ticket',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
  if(request!==generation)return;
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Connection failed');
  get('endpoint').textContent=data.endpoint||'';
  if(request!==generation)return;
  const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/api/terminal');socket=ws;ws.binaryType='arraybuffer';
  ws.onopen=()=>{ws.send(JSON.stringify({ticket:data.ticket}));terminal.reset();terminal.focus();};
  ws.onmessage=event=>{if(request!==generation)return;if(event.data instanceof ArrayBuffer)terminal.write(new Uint8Array(event.data));else{const message=JSON.parse(event.data);setStatus(message.message);if(message.message==='Connected')resize();}};
  // On close the reason (if any) is kept after "Disconnected" instead of being appended to whatever was shown.
  ws.onclose=()=>{if(request!==generation)return;socket=null;setConnectEnabled(true);const shown=get('status').textContent;const reason=/^(Connected|Connecting|Disconnected)/.test(shown)?'':shown;get('status').textContent=reason?'Disconnected — '+reason:'Disconnected';get('status').removeAttribute('title');};
  ws.onerror=()=>{if(request===generation)setStatus('Connection failed');};
 }catch(error){if(request===generation){setStatus(error.message);setConnectEnabled(true);}}
}
get('connect').onclick=connect;get('disconnect').onclick=disconnect;
window.addEventListener('beforeunload',disconnect);connect();
