'use strict';
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const params=new URLSearchParams(location.hash.slice(1));let activeId=params.get('lab')||'',state={labs:[],jobs:[],operations:[]},toastTimer;
const current=()=>state.labs.find(l=>l.id===activeId),busy=()=>[...state.jobs,...state.operations].some(j=>['queued','running'].includes(j.status));
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(path,options={}){const response=await fetch('/api'+path,options);if(!response.ok){const value=await response.json();throw new Error(value.detail||'Request failed.');}return response;}
async function json(path,method,data){return(await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).json();}
function attachmentName(response,fallback){const match=(response.headers.get('Content-Disposition')||'').match(/filename\*=UTF-8''([^;]+)/i);return match?decodeURIComponent(match[1]):fallback;}
async function refresh(){state=await(await api('/state')).json();}
async function launchWorkspace(){
 try{
  await refresh();$('workspace-message').textContent='';
  if(params.get('mode')==='ssh'){
   const lab=current();if(!lab)throw new Error('This saved lab is no longer available.');
   $('workspace-title').textContent='SSH sessions · '+lab.name;$('workspace-open').hidden=true;
   const nodes=lab.nodes.filter(n=>n.ssh_ready);
   $('workspace-message').textContent=nodes.length+' of '+lab.nodes.length+' nodes ready for SSH. Each session opens in its own browser tab. Allow popups for Open all, or use the individual links. Up to 32 simultaneous terminals are supported.';
   const link=n=>'/static/terminal.html#'+new URLSearchParams({lab:lab.id,node:n.name,label:lab.name});
   $('workspace-content').innerHTML='<button class="button primary" id="ssh-launch-all">Open all ready sessions ↗</button><div class="op-session-list">'+lab.nodes.map(n=>`<p><strong>${esc(n.short_name||n.name)}</strong> · ${esc(n.address)} ${n.ssh_ready?`<a class="button secondary" target="_blank" rel="opener" href="${esc(link(n))}">SSH ↗</a>`:'<span>Unavailable or missing credentials</span>'}</p>`).join('')+'</div>';
   $('ssh-launch-all').onclick=()=>{let blocked=0;for(const n of nodes.slice(0,32))if(!window.open(link(n),'_blank'))blocked++;notify(blocked?blocked+' popups were blocked. Use the individual SSH links.':nodes.length>32?'Opened the first 32. Close sessions before opening more.':'Sessions opened.');};
  }else{$('workspace-title').textContent='Deploy New Lab';$('workspace-message').textContent='Choose a topology from your VM to create and start a training lab. Open Lab Topologies when you are ready.';}
 }catch(e){$('workspace-message').textContent=e.message;}
}
document.addEventListener('DOMContentLoaded',()=>{launchWorkspace();$('workspace-open').onclick=()=>opTask(null,()=>opBrowse(params.get('path')||'',activeId));$('workspace-history').onclick=()=>opHistory()});
