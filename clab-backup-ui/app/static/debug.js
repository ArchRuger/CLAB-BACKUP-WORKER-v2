'use strict';
const debugElement=id=>document.getElementById(id);
let debugSnapshot=null,debugProbe=null;
function debugText(tag,text,className=''){
 const element=document.createElement(tag);element.textContent=text;if(className)element.className=className;return element;
}
async function debugFetch(path,options={}){
 const response=await fetch('/api/debug'+path,options);
 if(!response.ok)throw new Error('Diagnostic request failed (HTTP '+response.status+'). Refresh and retry; check the VM terminal if it persists.');
 return response.json();
}
function debugRows(){
 const body=debugElement('debug-requests');body.replaceChildren();
 const rows=(debugSnapshot?.requests||[]).filter(row=>!debugElement('debug-errors').checked||row.status>=400);
 for(const item of rows){
  const row=document.createElement('tr');
  for(const text of [item.time+' / '+item.id,item.method+' '+item.route,String(item.status),item.duration_ms+' ms'])row.append(debugText('td',text));
  if(item.status>=400)row.className='debug-failure';body.append(row);
 }
 if(!rows.length){const row=document.createElement('tr'),cell=debugText('td','No matching requests recorded. Reproduce the issue, then refresh.');cell.colSpan=4;row.append(cell);body.append(row);}
}
function debugRender(){
 const data=debugSnapshot,summary=debugElement('debug-summary');summary.replaceChildren();
 const cards=[['Running manager',{'Release':data.manager_version,'Python':data.python_version,'Uptime':data.uptime_seconds+' seconds',...data.packages}],
  ['VM connection',data.vm],['Saved workspace',data.saved_counts]];
 for(const [title,values] of cards){const card=debugText('section','','debug-card');card.append(debugText('h2',title));const list=document.createElement('dl');
  for(const [key,value] of Object.entries(values)){list.append(debugText('dt',key.replaceAll('_',' ')),debugText('dd',typeof value==='boolean'?(value?'Yes':'No'):String(value)));}card.append(list);summary.append(card);}
 debugRows();debugElement('debug-download').disabled=false;
}
async function debugRefresh(){
 debugElement('debug-refresh').disabled=true;
 try{debugSnapshot=await debugFetch('');debugRender();debugElement('debug-status').textContent='Snapshot updated '+debugSnapshot.generated_at;}
 catch(error){debugElement('debug-status').textContent=error.message;}
 finally{debugElement('debug-refresh').disabled=false;}
}
async function debugRun(event){
 event.preventDefault();debugElement('debug-probe').disabled=true;debugProbe=null;
 const checks=debugElement('debug-checks');checks.replaceChildren(debugText('p','Checking folder listing and helper capabilities…'));
 try{
  debugProbe=await debugFetch('/probe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:debugElement('debug-path').value})});
  checks.replaceChildren();
  for(const check of debugProbe.checks){checks.append(debugText('p',check.check+' · '+check.status.toUpperCase()+' · '+check.duration_ms+' ms'+(check.entry_count!==undefined?' · '+check.entry_count+' entries':'')+(check.helper_version?' · helper '+check.helper_version:'')+(check.message?' — '+check.message:''),check.status==='fail'?'debug-failure':''));}
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
