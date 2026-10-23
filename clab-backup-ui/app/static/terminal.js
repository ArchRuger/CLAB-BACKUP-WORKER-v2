'use strict';
const params=new URLSearchParams(location.hash.slice(1)),lab=params.get('lab'),name=params.get('node'),labLabel=params.get('label')||'Lab';
const get=id=>document.getElementById(id);
document.title=(name||'Device')+' · '+labLabel+' · Containerlab Node Manager';get('title').textContent=(name||'Unknown device')+' · '+labLabel;
if(get('back')){get('back').href='/#'+new URLSearchParams({lab:lab||'',device:name||''});get('back').textContent='← '+labLabel;get('back').hidden=!lab;}
if(get('notice-text'))get('notice-text').textContent=`Logged in with the credentials saved for ${name||'this device'}. The session closes after 15 minutes without activity. Alt+T moves to the terminal tools; Alt+Up, Alt+Down and Alt+0 change the text size.`;
const FONT_SIZES=[11,12,13,14,15,16,17,18],FONT_DEFAULT=14,FONT_KEY='clab.terminal.fontSize',SCROLLBACK=3000;
// Browser storage may be blocked or absent: the size is then simply not remembered.
function prefGet(key){try{return localStorage.getItem(key);}catch{return null;}}
function prefSet(key,value){try{localStorage.setItem(key,String(value));}catch{}}
function clampFont(n){const v=Math.round(Number(n));return Number.isFinite(v)?Math.max(FONT_SIZES[0],Math.min(FONT_SIZES[FONT_SIZES.length-1],v)):FONT_DEFAULT;}
let fontSize=clampFont(prefGet(FONT_KEY)??FONT_DEFAULT);
const terminal=new Terminal({cursorBlink:true,scrollback:SCROLLBACK,fontSize,fontFamily:'Consolas, "Liberation Mono", monospace',theme:{background:'#172431',foreground:'#e7eff2',cursor:'#9ad4ea',selectionBackground:'#41637780'}});
const fit=new FitAddon.FitAddon();terminal.loadAddon(fit);terminal.open(get('terminal'));
let socket=null,generation=0,opened=false;
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
  ws.onopen=()=>{ws.send(JSON.stringify({ticket:data.ticket}));terminal.reset();terminal.focus();if(opened)toolsStatus('Reconnected; the previous screen was cleared');opened=true;};
  ws.onmessage=event=>{if(request!==generation)return;if(event.data instanceof ArrayBuffer)terminal.write(new Uint8Array(event.data));else{const message=JSON.parse(event.data);setStatus(message.message);if(message.message==='Connected')resize();}};
  // On close the reason (if any) is kept after "Disconnected" instead of being appended to whatever was shown.
  ws.onclose=()=>{if(request!==generation)return;socket=null;setConnectEnabled(true);const shown=get('status').textContent;const reason=/^(Connected|Connecting|Disconnected)/.test(shown)?'':shown;get('status').textContent=reason?'Disconnected — '+reason:'Disconnected';get('status').removeAttribute('title');};
  ws.onerror=()=>{if(request===generation)setStatus('Connection failed');};
 }catch(error){if(request===generation){setStatus(error.message);setConnectEnabled(true);}}
}
// ---- terminal tools (docs/parity-campaign/C02-DESIGN.md section 1): text size, copy, clear, save as text; nothing is sent to the manager ----
const TOOL_IDS=['font-down','font-up','font-reset','copy-selection','copy-screen','clear','export-screen','export-session'];
let roving=0;
function toolsStatus(text){const el=get('tools-status');if(el)el.textContent=text;}
function toolButton(id){return get(id);}
function setRoving(index){roving=index;TOOL_IDS.forEach((id,i)=>{const b=toolButton(id);if(b)b.setAttribute('tabindex',i===index?'0':'-1');});}
function moveRoving(step){
 for(let k=1;k<=TOOL_IDS.length;k++){
  const index=(roving+step*k+TOOL_IDS.length*k)%TOOL_IDS.length,b=toolButton(TOOL_IDS[index]);
  if(b&&!b.disabled){setRoving(index);b.focus();return;}
 }
}
function jumpRoving(start,step){
 for(let i=start;i>=0&&i<TOOL_IDS.length;i+=step){const b=toolButton(TOOL_IDS[i]);if(b&&!b.disabled){setRoving(i);b.focus();return;}}
}
function syncFontButtons(){
 const down=toolButton('font-down'),up=toolButton('font-up');if(!down||!up)return;
 const min=FONT_SIZES[0],max=FONT_SIZES[FONT_SIZES.length-1];
 down.disabled=fontSize<=min;up.disabled=fontSize>=max;
 // A disabled button cannot keep focus or the roving stop: hand both to the other size button.
 if(down.disabled&&(document.activeElement===down||roving===0)){setRoving(1);if(document.activeElement===down)up.focus();}
 if(up.disabled&&(document.activeElement===up||roving===1)){setRoving(0);if(document.activeElement===up)down.focus();}
}
function setFont(n,announce=true){
 fontSize=clampFont(n);terminal.options.fontSize=fontSize;resize();prefSet(FONT_KEY,fontSize);syncFontButtons();
 if(announce)toolsStatus(`Text size ${fontSize} px`);
}
function rowsText(buffer,from,to){
 const lines=[];let current=null;
 for(let i=from;i<=to;i++){
  const line=buffer.getLine(i);if(!line)continue;
  const text=line.translateToString(false);
  if(line.isWrapped&&current!==null)current+=text;
  else{if(current!==null)lines.push(current);current=text;}
 }
 if(current!==null)lines.push(current);
 const trimmed=lines.map(l=>l.replace(/\s+$/,''));
 while(trimmed.length&&trimmed[trimmed.length-1]==='')trimmed.pop();
 return trimmed.join('\n');
}
function screenText(){const b=terminal.buffer.active;return rowsText(b,b.viewportY,b.viewportY+terminal.rows-1);}
function sessionText(){const b=terminal.buffer.normal;return rowsText(b,0,b.length-1);}
function exportName(labText,deviceText,date){
 const clean=(value,fallback)=>String(value??'').replace(/[^A-Za-z0-9_.-]+/g,'-').replace(/^[-.]+|-+$/g,'')||fallback;
 const stamp=date.toISOString().replace(/[-:]/g,'').replace(/\.\d+Z$/,'Z');
 return `${clean(labText,'lab')}-${clean(deviceText,'device')}-${stamp}.txt`;
}
function download(text,filename){
 const url=URL.createObjectURL(new Blob([text],{type:'text/plain'})),a=document.createElement('a');
 a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function exportText(kind){
 const text=(kind==='session'?sessionText():screenText())+'\n';
 download(text,exportName(labLabel,name,new Date()));
 const limited=kind==='session'&&terminal.buffer.normal.length>=SCROLLBACK;
 toolsStatus('Saved on this computer only. The manager keeps no copy of this session.'+(limited?' The file holds the last 3,000 lines.':''));
}
async function copyTool(text,button){const ok=await copyText(text,button);toolsStatus(ok?'Copied':'Could not copy. Select the text and press Ctrl+Insert.');return ok;}
async function copySelection(button){const text=terminal.getSelection();if(!text){toolsStatus('Nothing is selected');return false;}return copyTool(text,button||get('copy-selection'));}
async function copyScreen(button){return copyTool(screenText(),button||get('copy-screen'));}
function clearScreen(){terminal.clear();toolsStatus('Screen cleared. The device was not told.');}
// A button hands focus back to the terminal only after a pointer activation, so Enter on a button never reaches the device.
function afterTool(event){if(event&&event.detail>0)terminal.focus();}
const TOOL_ACTIONS={'font-down':()=>setFont(fontSize-1),'font-up':()=>setFont(fontSize+1),'font-reset':()=>setFont(FONT_DEFAULT),'copy-selection':()=>copySelection(),'copy-screen':()=>copyScreen(),'clear':clearScreen,'export-screen':()=>exportText('screen'),'export-session':()=>exportText('session')};
TOOL_IDS.forEach((id,index)=>{
 const b=toolButton(id);if(!b)return;
 b.onclick=event=>{setRoving(index);TOOL_ACTIONS[id]();afterTool(event);};
 if(typeof b.addEventListener==='function')b.addEventListener('focus',()=>{if(roving!==index)setRoving(index);});
});
const toolbar=get('terminal-tools');
if(toolbar&&typeof toolbar.addEventListener==='function')toolbar.addEventListener('keydown',event=>{
 if(event.key==='ArrowRight'){event.preventDefault();moveRoving(1);}
 else if(event.key==='ArrowLeft'){event.preventDefault();moveRoving(-1);}
 else if(event.key==='Home'){event.preventDefault();jumpRoving(0,1);}
 else if(event.key==='End'){event.preventDefault();jumpRoving(TOOL_IDS.length-1,-1);}
});
// xterm calls this for keydown, keypress and keyup: act on keydown only, but swallow every event type of a handled chord.
function chordOf(e){
 if(e.altKey&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey){
  if(e.key==='ArrowUp')return 'larger';if(e.key==='ArrowDown')return 'smaller';
  if(e.key==='0'||e.code==='Digit0')return 'reset';if(e.code==='KeyT'||e.key==='t'||e.key==='T')return 'tools';
 }
 if(e.ctrlKey&&!e.altKey&&!e.metaKey&&!e.shiftKey&&e.key==='Insert')return 'copy';
 return '';
}
function keyHandler(e){
 const chord=chordOf(e);if(!chord)return true;
 if(e.type!=='keydown')return false;
 if(chord==='copy')copySelection();
 else{
  if(typeof e.preventDefault==='function')e.preventDefault();
  if(chord==='larger')setFont(fontSize+1);else if(chord==='smaller')setFont(fontSize-1);else if(chord==='reset')setFont(FONT_DEFAULT);
  else{const b=toolButton(TOOL_IDS[roving]);if(b)b.focus();}
 }
 return false;
}
if(typeof terminal.attachCustomKeyEventHandler==='function')terminal.attachCustomKeyEventHandler(keyHandler);
syncFontButtons();
get('connect').onclick=connect;get('disconnect').onclick=disconnect;
window.addEventListener('beforeunload',disconnect);connect();
