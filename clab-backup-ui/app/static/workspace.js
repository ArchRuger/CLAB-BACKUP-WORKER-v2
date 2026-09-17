'use strict';
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const params=new URLSearchParams(location.hash.slice(1));let activeId=params.get('lab')||'',state={labs:[],jobs:[],operations:[]},toastTimer;
const current=()=>state.labs.find(l=>l.id===activeId),busy=()=>[...state.jobs,...state.operations].some(j=>['queued','running'].includes(j.status));
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(path,options={}){const response=await fetch('/api'+path,options);if(!response.ok){const value=await response.json();throw new Error(value.detail||'Request failed.');}return response;}
async function json(path,method,data){return(await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).json();}
function attachmentName(response,fallback){const match=(response.headers.get('Content-Disposition')||'').match(/filename\*=UTF-8''([^;]+)/i);return match?decodeURIComponent(match[1]):fallback;}
async function refresh(){state=await(await api('/state')).json();}
// A device row of the CLI launcher: name, state and either the Open CLI link or the reason there is none.
function workspaceDeviceRow(lab,n,link){
 const ds=typeof deviceState==='function'?deviceState(n):{label:n.ssh_ready?'Ready':'Not ready',detail:'Waiting for the device to accept SSH.',pill:n.ssh_ready?'ok':'neutral'};
 return `<p class="op-session-row"><strong>${esc(n.short_name||n.name)}</strong> <span class="pill ${esc(ds.pill||'neutral')}">${esc(ds.label)}</span> <small>${esc(n.address||'')}</small> ${n.ssh_ready?`<a class="button secondary" target="_blank" rel="opener" href="${esc(link(n))}">Open CLI <span aria-hidden="true">↗</span></a>`:`<span class="caption">${esc(ds.detail)}</span>`}</p>`;
}
async function launchWorkspace(){
 try{
  await refresh();$('workspace-message').textContent='';
  if(params.get('mode')==='ssh'){
   const lab=current();if(!lab)throw new Error('This lab is no longer in the manager. Go back to My labs.');
   $('workspace-title').textContent='Open CLIs · '+lab.name;document.title='Open CLIs · '+lab.name+' · Containerlab Node Manager';$('workspace-open').hidden=true;
   if($('workspace-choices'))$('workspace-choices').hidden=true;
   const nodes=lab.nodes.filter(n=>n.ssh_ready);
   $('workspace-message').textContent=nodes.length+' of '+lab.nodes.length+' devices ready. Each CLI opens in its own browser tab — allow pop-ups for Open all, or use the links below. Up to 32 CLIs can be open at once.';
   const link=n=>'/static/terminal.html#'+new URLSearchParams({lab:lab.id,node:n.name,label:lab.name});
   $('workspace-content').innerHTML=`<button class="button primary" id="ssh-launch-all" ${nodes.length?'':'disabled'}>Open all ready CLIs <span aria-hidden="true">↗</span></button>${nodes.length?'':'<p class="caption">No device is ready yet.</p>'}<div class="op-session-list">${lab.nodes.map(n=>workspaceDeviceRow(lab,n,link)).join('')}</div><p class="workspace-links"><button type="button" class="button ghost small" id="ssh-history">Operation history…</button></p>`;
   $('ssh-history').onclick=()=>opTask(null,()=>opHistory());
   $('ssh-launch-all').onclick=()=>{let blocked=0;for(const n of nodes.slice(0,32))if(!window.open(link(n),'_blank'))blocked++;notify(blocked?'Your browser blocked '+blocked+' tabs. Use the Open CLI links below.':nodes.length>32?'Opened the first 32 CLIs. Close some before opening more.':'CLIs opened.');};
  }else{$('workspace-title').textContent='Deploy a new lab';$('workspace-message').textContent='Choose a lab topology on the VM to start.';}
 }catch(e){$('workspace-message').textContent=e.message;}
}
document.addEventListener('DOMContentLoaded',()=>{launchWorkspace();$('workspace-open').onclick=()=>opTask(null,()=>opBrowse(params.get('path')||'',activeId));$('workspace-history').onclick=()=>opTask(null,()=>opHistory());});
