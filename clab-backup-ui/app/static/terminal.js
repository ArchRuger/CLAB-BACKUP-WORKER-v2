'use strict';
const params=new URLSearchParams(location.hash.slice(1)),lab=params.get('lab'),name=params.get('node');
const get=id=>document.getElementById(id);
document.title=(name||'Node')+' · Containerlab Node Manager SSH';get('title').textContent=(params.get('label')||'Lab')+' / '+(name||'Unknown node');
const terminal=new Terminal({cursorBlink:true,scrollback:3000,fontSize:14,fontFamily:'Consolas, "Liberation Mono", monospace',theme:{background:'#152631',foreground:'#e7eff2',cursor:'#79e8f6',selectionBackground:'#41637780'}});
const fit=new FitAddon.FitAddon();terminal.loadAddon(fit);terminal.open(get('terminal'));
let socket=null,generation=0;
function resize(){fit.fit();if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'resize',cols:Math.max(20,Math.min(400,terminal.cols)),rows:Math.max(5,Math.min(150,terminal.rows))}));}
new ResizeObserver(resize).observe(get('terminal'));
terminal.onData(data=>{if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'input',data}));});
function disconnect(){generation++;if(socket)socket.close();socket=null;get('status').textContent='Disconnected';get('connect').disabled=false;}
async function connect(){
 disconnect();const request=++generation;
 if(!lab||!name){get('status').textContent='Open this terminal from a node in the dashboard.';return;}
 if(!sessionStorage.getItem('uiToken')){get('unlock').hidden=false;return;}
 get('connect').disabled=true;get('status').textContent='Connecting…';
 try{
  const response=await fetch('/api/labs/'+encodeURIComponent(lab)+'/terminal-ticket',{method:'POST',headers:{Authorization:'Bearer '+sessionStorage.getItem('uiToken'),'Content-Type':'application/json'},body:JSON.stringify({name})});
  if(request!==generation)return;
  if(response.status===401){sessionStorage.removeItem('uiToken');get('unlock').hidden=false;throw new Error('Enter the worker access token.');}
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Connection failed');
  get('endpoint').textContent=data.endpoint||'';
  if(request!==generation)return;
  const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/api/terminal');socket=ws;ws.binaryType='arraybuffer';
  ws.onopen=()=>{ws.send(JSON.stringify({ticket:data.ticket}));terminal.reset();terminal.focus();};
  ws.onmessage=event=>{if(request!==generation)return;if(event.data instanceof ArrayBuffer)terminal.write(new Uint8Array(event.data));else{const message=JSON.parse(event.data);get('status').textContent=message.message;if(message.message==='Connected')resize();}};
  ws.onclose=()=>{if(request!==generation)return;socket=null;get('connect').disabled=false;get('status').textContent+=' · Disconnected';};
  ws.onerror=()=>{if(request===generation)get('status').textContent='Connection failed';};
 }catch(error){if(request===generation){get('status').textContent=error.message;get('connect').disabled=false;}}
}
get('connect').onclick=connect;get('disconnect').onclick=disconnect;
get('unlock').onsubmit=event=>{event.preventDefault();sessionStorage.setItem('uiToken',get('token').value.trim());get('token').value='';get('unlock').hidden=true;connect();};
window.addEventListener('beforeunload',disconnect);connect();
