'use strict';
const debugElement=id=>document.getElementById(id);
let debugSnapshot=null,debugProbe=null;
function debugText(tag,text,className=''){
 const element=document.createElement(tag);element.textContent=text;if(className)element.className=className;return element;
}
async function debugFetch(path,options={}){
 const response=await fetch('/api/debug'+path,options);
 if(!response.ok){
  let detail='';try{const body=await response.json();if(typeof body?.detail==='string')detail=body.detail;}catch{detail='';}
  throw new Error('The manager did not answer (HTTP '+response.status+'). Refresh to try again.'+(detail?' '+detail:''));
 }
 return response.json();
}
// Student sentences for the manager's diagnostic vocabulary; the raw hint follows in the same row.
const debugCheckNames={browse:'Folder listing',capabilities:'VM commands'};
const debugStatusWords={pass:'PASSED',warning:'WARNING',warn:'WARNING',fail:'FAILED'};
const debugCodeSentences={'host-trust':"The VM's host fingerprint is missing or changed — open VM connection and confirm it.",'vm-disabled':'The VM connection is switched off — enable it in VM connection.','gateway-permission':'The VM account cannot run lab operations — ask the administrator to re-run the VM setup with operations enabled.','gateway-account':'The VM account cannot run lab operations — ask the administrator to re-run the VM setup with operations enabled.','untrusted-folder':'This folder is outside the allowed lab folders.','missing-folder':'This folder does not exist on the VM.','not-directory':'This is a file, not a folder.','symlink-folder':'Linked (symlink) folders are not allowed — use the real folder.',timeout:'The VM did not answer in time.',authentication:'The VM refused the saved password — check VM connection.','helper-unavailable':'The VM helper is not installed or is out of date — re-run the VM setup.'};
const debugVmLabels={configured:'Connection saved',enabled:'Enabled',password_saved:'Password saved',fingerprint_saved:'Host fingerprint saved',connected:'Connected',checking:'Checking now',file_import_supported:'File import supported',discovery_helper_version:'VM helper version',helper_version:'VM helper version'};
const debugCountLabels={labs:'Labs',jobs:'Configuration saves',operations:'Lab operations',git_jobs:'Progress saves',restore_jobs:'Configuration changes'};
function debugUptime(seconds){const total=Math.max(0,Math.round(Number(seconds)||0)),h=Math.floor(total/3600),m=Math.floor((total%3600)/60);return h?`${h} h ${m} min`:m?`${m} min`:`${total} s`;}
function debugCheckLine(check){
 const status=String(check.status||''),word=debugStatusWords[status]||status.toUpperCase();
 const parts=[(debugCheckNames[check.check]||check.check)+' — '+word];
 if(check.entry_count!==undefined)parts.push(check.entry_count+' entries');
 if(check.helper_version)parts.push('VM helper '+check.helper_version);
 parts.push(check.duration_ms+' ms');
 let line=parts.join(' · ');
 const sentence=status==='fail'?debugCodeSentences[check.code]:check.check==='capabilities'&&status!=='pass'&&check.helper_version?`The VM helper (${check.helper_version}) and the manager are different releases — update the VM from the same release.`:'';
 if(sentence)line+=' — '+sentence+(check.message?' (raw: '+check.message+')':'');
 else if(check.message)line+=' — '+check.message;
 return line;
}
function debugRows(){
 const body=debugElement('debug-requests');body.replaceChildren();
 const rows=(debugSnapshot?.requests||[]).filter(row=>!debugElement('debug-errors').checked||row.status>=400);
 for(const item of rows){
  const row=document.createElement('tr');
  for(const text of [item.time+' / '+item.id,item.method+' '+item.route,String(item.status),item.duration_ms+' ms'])row.append(debugText('td',text));
  if(item.status>=400)row.className='debug-failure';body.append(row);
 }
 if(!rows.length){const row=document.createElement('tr'),cell=debugText('td','No matching requests yet. Repeat the action that failed, then refresh.');cell.colSpan=4;row.append(cell);body.append(row);}
}
function debugRender(){
 const data=debugSnapshot,summary=debugElement('debug-summary');summary.replaceChildren();
 // Card 0 keeps the order Version · Python · Running for · Activity log before the packages (the report tests read it by position).
 const cards=[['This manager',{'Version':data.manager_version,'Python':data.python_version,'Running for':debugUptime(data.uptime_seconds),'Activity log':data.audit_log_available===false?'Failed — check storage':'Working',...data.packages}],
  ['VM connection',Object.fromEntries(Object.entries(data.vm||{}).map(([k,v])=>[debugVmLabels[k]||k.replaceAll('_',' '),v]))],['Saved in this manager',Object.fromEntries(Object.entries(data.saved_counts||{}).map(([k,v])=>[debugCountLabels[k]||k.replaceAll('_',' '),v]))]];
 for(const [title,values] of cards){const card=debugText('section','','debug-card');card.append(debugText('h2',title));const list=document.createElement('dl');
  for(const [key,value] of Object.entries(values)){list.append(debugText('dt',key),debugText('dd',typeof value==='boolean'?(value?'Yes':'No'):String(value)));}card.append(list);summary.append(card);}
 debugRows();debugElement('debug-download').disabled=false;
}
async function debugRefresh(){
 debugElement('debug-refresh').disabled=true;
 try{debugSnapshot=await debugFetch('');debugRender();debugElement('debug-status').textContent='Updated '+debugSnapshot.generated_at;}
 catch(error){debugElement('debug-status').textContent=error.message;}
 finally{debugElement('debug-refresh').disabled=false;}
}
async function debugRun(event){
 event.preventDefault();debugElement('debug-probe').disabled=true;debugProbe=null;
 const checks=debugElement('debug-checks');checks.replaceChildren(debugText('p','Checking folder listing and VM commands…'));
 try{
  debugProbe=await debugFetch('/probe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:debugElement('debug-path').value})});
  checks.replaceChildren();
  for(const check of debugProbe.checks)checks.append(debugText('p',debugCheckLine(check),check.status==='fail'?'debug-failure':''));
  checks.append(debugText('small','Checked '+debugProbe.generated_at));await debugRefresh();
 }catch(error){checks.replaceChildren(debugText('p',error.message,'debug-failure'));}
 finally{debugElement('debug-probe').disabled=false;}
}
function debugDownload(){
 if(!debugSnapshot)return;
 const report={...debugSnapshot,probe:debugProbe};
 const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)+'\n'],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='clab-debug-'+debugSnapshot.generated_at.replace(/[:.]/g,'-')+'.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
debugElement('debug-refresh').onclick=debugRefresh;
debugElement('debug-download').onclick=debugDownload;
debugElement('debug-errors').onchange=debugRows;
debugElement('debug-probe-form').onsubmit=debugRun;
debugRefresh();
