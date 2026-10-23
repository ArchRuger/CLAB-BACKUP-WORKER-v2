'use strict';
// Device drawer: the Impairments section (docs/parity-campaign/C05-DESIGN.md section 4.1). One <details> after the
// diagnostics sections (created here when index.html does not carry it), closed until the student opens it. One row per
// data interface with five fields; Apply and Reset per row and Clear for the device, each behind an inline question.
// The markup is rebuilt only by an event of this file (a fetched answer, a finished call, a question), never by the
// 4-second poll: renderDeviceImpairments() only toggles `disabled`/`title` and short texts, so typed values, focus and an
// open question survive it. The browser never names a container: it sends the lab id, the device name and the container
// id the Interfaces answer showed (`expected_id`). Declares only imp*/IMP_* names and loads in Node; the drawer's close
// hook in shell.js calls resetDeviceImpairments() behind a typeof guard.
const IMP_TIME='Delay and jitter are a number with ms or s, up to 60s.';
const IMP_JITTER='Set a delay before adding jitter.';
const IMP_PERCENT='Loss and corruption are a percentage from 0 to 100.';
const IMP_RATE='Rate is a whole number of kbit/s.';
const IMP_ZERO='Set at least one impairment, or use Reset to remove them.';
const IMP_BUSY=['Wait for the current lab operation to finish.','Wait for the lab backup or login job to finish.','Another lab operation is running on the VM (it may belong to another lab); try again when it has finished.'];
const IMP_NO_CAP='Not available on this VM — its containerlab or helper cannot set impairments (see Diagnostics)';
const IMP_NO_CONTAINER='No container for this device yet.';
const IMP_NO_LINKS='This device has no lab links.';
const IMP_PARTIAL='Some devices could not be read; try again.';
const IMP_STALE='The lab changed on the VM; Refresh to re-read the impairments.';
const IMP_OPEN_FIRST='Answer the open question first.';
const IMP_CAPTION='Impairments shape traffic leaving the interface (delay and jitter in ms or s, loss and corruption in percent, rate in kbit/s). A restart, a stop and start, or a redeploy of the device can remove them; the map re-checks after each operation. They cannot be changed while any lab operation runs on the VM.';
const IMP_FIELDS=['delay','jitter','loss','rate','corruption'];
const IMP_LABELS={delay:'Delay',jitter:'Jitter',loss:'Loss %',rate:'Rate kbit',corruption:'Corruption %'};
const IMP_PLACEHOLDERS={delay:'0ms',jitter:'0ms',loss:'0',rate:'0',corruption:'0'};
const IMP_TIME_RE=/^(0|[1-9][0-9]{0,5})(ms|s)$/;
const IMP_LIMIT_MS=60000, IMP_RATE_LIMIT=10000000;
// ---- Pure helpers (tested in tests/test_device_impairments_ui.js against tests/fixtures/impairment_values.json) --------
function impTimeMs(value){
 const m=typeof value==='string'?IMP_TIME_RE.exec(value):null;if(!m)return -1;
 const ms=Number(m[1])*(m[2]==='s'?1000:1);return ms>IMP_LIMIT_MS?-1:ms;
}
function impPercentOk(value){return typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=100;}
// The strict check of a wire row (what the helper receives); the same order and sentences as host_operations.impairment_values.
function impairmentProblem(v){
 v=v||{};
 const delay=impTimeMs(v.delay),jitter=impTimeMs(v.jitter);
 if(delay<0||jitter<0)return IMP_TIME;
 if(!impPercentOk(v.loss)||!impPercentOk(v.corruption))return IMP_PERCENT;
 if(typeof v.rate!=='number'||!Number.isInteger(v.rate)||v.rate<0||v.rate>IMP_RATE_LIMIT)return IMP_RATE;
 if(jitter&&!delay)return IMP_JITTER;
 if(!(delay||jitter||v.loss||v.corruption||v.rate))return IMP_ZERO;
 return '';
}
// Typed text to the wire spelling: '' is none, a bare number is milliseconds, leading zeros go, -0 is 0. Anything that is
// not a plain number stays text, so impairmentProblem() refuses it with the right sentence.
function impTime(text){
 let t=String(text===undefined||text===null?'':text).trim();
 if(t==='')return '0ms';
 if(/^[0-9]+$/.test(t))t+='ms';
 return t.replace(/^0+(?=[0-9])/,'');
}
function impNumber(text){
 const t=String(text===undefined||text===null?'':text).trim();
 if(t==='')return 0;
 return /^-?([0-9]+\.?[0-9]*|\.[0-9]+)$/.test(t)?(Number(t)||0):t;
}
function impWire(raw){
 raw=raw||{};
 return {delay:impTime(raw.delay),jitter:impTime(raw.jitter),loss:impNumber(raw.loss),rate:impNumber(raw.rate),corruption:impNumber(raw.corruption)};
}
function impSame(a,b){return IMP_FIELDS.every(k=>a[k]===b[k]);}
function impIsNone(wire){return impTimeMs(wire.delay)===0&&impTimeMs(wire.jitter)===0&&!wire.loss&&!wire.rate&&!wire.corruption;}
// What an input shows for a stored row: zero and empty values show as empty (the placeholder reads 0).
function impDisplay(wire){
 const time=t=>impTimeMs(t)===0?'':t;
 return {delay:time(wire.delay),jitter:time(wire.jitter),loss:wire.loss?String(wire.loss):'',rate:wire.rate?String(wire.rate):'',corruption:wire.corruption?String(wire.corruption):''};
}
function impSummary(wire){
 const parts=[];
 if(impTimeMs(wire.delay)>0)parts.push('delay '+wire.delay);
 if(impTimeMs(wire.jitter)>0)parts.push('jitter '+wire.jitter);
 if(wire.loss)parts.push('loss '+wire.loss+'%');
 if(wire.rate)parts.push('rate '+wire.rate+' kbit');
 if(wire.corruption)parts.push('corruption '+wire.corruption+'%');
 return parts.join(', ');
}
function impCount(n,word){return n+' '+word+(n===1?'':'s');}
function impPartialSentence(data,portOf){
 const total=Number(data.total)||0,cleared=Number(data.cleared)||0,failed=(data.failed||[])[0];
 if(failed)return `${cleared} of ${total} interfaces cleared; ${portOf(failed.interface)}: ${String(failed.reason||'').replace(/[.\s]+$/,'')}. Try again.`;
 return `${cleared} of ${total} interfaces cleared; the rest were not reached in time. Try again.`;
}
// ---- State ----------------------------------------------------------------------------------------------------------
function impNew(){
 return {key:'',lab:'',device:'',title:'',open:false,loading:false,loaded:false,loadFailed:false,answer:null,present:true,running:true,partial:false,
  noCap:false,rows:[],base:{},typed:{},id:'',question:null,flight:'',blocked:'',sawBusy:false,stale:false,stamp:''};
}
let imp=impNew(), impCapsAsked=0;
const IMP_SKELETON='<summary>Impairments</summary><div id="imp-body" class="diag-body"></div>'
 +'<p class="caption" id="imp-busy" hidden></p>'
 +'<p class="caption diag-status" id="imp-status" role="status" tabindex="-1"></p>'
 +'<p class="form-error" id="imp-error"></p>'
 +'<p class="caption" id="imp-stale" hidden><span>'+IMP_STALE+'</span> <button type="button" class="button secondary small" id="imp-refresh">Refresh</button></p>'
 +'<button type="button" class="button secondary small" id="imp-retry" hidden>Retry</button>'
 +'<p class="caption">'+IMP_CAPTION+'</p>';
function impCapsLacking(){
 if(typeof opCaps==='undefined'||!opCaps)return false;
 return !(opCaps.actions&&opCaps.actions.impairments&&opCaps.actions.impairments.available===true);
}
function impBusyReason(){
 if(imp.flight)return 'Working…';
 if(imp.blocked)return imp.blocked;
 if(typeof busyReason==='function'){const reason=busyReason();if(reason)return reason;}
 return '';
}
function impOperationStamp(){
 if(typeof state==='undefined'||!state||typeof activeId==='undefined')return '';
 return (state.operations||[]).filter(job=>job.lab_id===activeId&&job.finished).map(job=>String(job.finished)).sort().pop()||'';
}
function impPortOf(name){const row=imp.rows.find(r=>r.name===name);return row?row.label:name;}
function impEditing(){return imp.rows.some(r=>!impSame(imp.base[r.name],impWire(imp.typed[r.name])));}
function impImpaired(row){return !impIsNone(imp.base[row.name]);}
function impAnyImpaired(){return imp.rows.some(impImpaired);}
// ---- Markup ---------------------------------------------------------------------------------------------------------
function impInput(i,row,field){
 const typed=imp.typed[row.name]||{};
 return `<td><input type="text" inputmode="decimal" size="6" autocomplete="off" id="imp-in-${i}-${field}" data-imp-i="${i}" data-imp-f="${field}" aria-label="${esc(IMP_LABELS[field].replace(/ .*$/,'')+' on '+row.label)}" placeholder="${esc(IMP_PLACEHOLDERS[field])}" value="${esc(typed[field]||'')}"></td>`;
}
function impButtons(i){
 return `<button type="button" class="button primary small" id="imp-apply-${i}" data-imp-act="apply" data-imp-i="${i}" disabled>Apply</button> <button type="button" class="button ghost small" id="imp-reset-${i}" data-imp-act="reset" data-imp-i="${i}" disabled>Reset</button>`;
}
function impQuestion(q){
 const row=imp.rows[q.i],name=imp.title;let text,yes;
 if(q.kind==='set'){text=`Set ${impSummary(q.wire)} on ${name} ${row.label}? Traffic leaving this interface is shaped until you reset it.`;yes='Apply';}
 else if(q.kind==='reset'){text=`Remove the impairments on ${name} ${row.label}?`;yes='Reset';}
 else{text=`Remove every impairment on ${name} (${impCount(imp.rows.filter(impImpaired).length,'interface')})?`;yes='Clear';}
 return `<div class="imp-question" role="group" aria-labelledby="imp-q-text"><p id="imp-q-text">${esc(text)}</p><div class="actions"><button type="button" class="button danger small" id="imp-confirm" data-imp-act="confirm">${esc(yes)}</button> <button type="button" class="button secondary small" id="imp-keep" data-imp-act="cancel">${q.kind==='set'?'Keep as is':'Keep'}</button></div></div>`;
}
function impClearHtml(){
 return `<button type="button" class="button secondary small" id="imp-clear" data-imp-act="clear" disabled>${imp.flight==='clear'?'Clearing…':'Clear impairments on this device'}</button>`;
}
function impRowHtml(row,i){
 // Apply and Reset sit under the interface name (no Actions column), so five narrow inputs plus one slim column fit a 390 px drawer.
 return `<tr><td class="imp-first"><strong>${esc(row.label)}</strong>${row.label!==row.name?`<small class="mono">${esc(row.name)}</small>`:''}<div id="imp-act-${i}">${impButtons(i)}</div><small class="form-help" id="imp-hint-${i}"></small></td>${IMP_FIELDS.map(f=>impInput(i,row,f)).join('')}</tr>`;
}
function impBodyHtml(){
 const s=imp;
 if(s.noCap)return `<p class="diag-empty">${esc(IMP_NO_CAP)}</p>`;
 if(!s.answer){
  return s.loading?'<p class="diag-empty">Loading…</p>':'';
 }
 if(!s.present)return `<p class="diag-empty">${esc(IMP_NO_CONTAINER)}</p>`;
 if(!s.running)return `<p class="diag-empty">${esc(s.title+' is not running. Impairments can be set only on a running device.')}</p>`;
 if(!s.rows.length)return `<p class="diag-empty">${esc(IMP_NO_LINKS)}</p>`;
 const head=IMP_FIELDS.map(f=>`<th scope="col">${esc(IMP_LABELS[f])}</th>`).join('');
 return `<div id="imp-clear-zone" class="actions">${impClearHtml()}</div><div id="imp-question-zone">${imp.question?impQuestion(imp.question):''}</div>`
  +`<div class="table-wrap diag-wrap impairments-table" id="imp-region" tabindex="0" role="region" aria-label="${esc('Impairments of '+s.title)}"><table class="diag-table"><caption class="sr-only">${esc('Impairments of '+s.title)}</caption><thead><tr><th scope="col">Interface</th>${head}</tr></thead><tbody>${s.rows.map(impRowHtml).join('')}</tbody></table></div>`
  +(s.partial?`<p class="caption">${esc(IMP_PARTIAL)}</p>`:'');
}
function impPaintBody(){
 const body=$('imp-body');if(!body)return;
 body.innerHTML=impBodyHtml();
 impSync();
}
// The question sits in one full-width zone above the table (the drawer is too narrow for it inside a row); the row's own
// buttons stay and are disabled while it is open.
function impPaintActions(){
 const el=$('imp-question-zone'),zone=$('imp-clear-zone');
 if(el)el.innerHTML=imp.question?impQuestion(imp.question):'';
 if(zone)zone.innerHTML=impClearHtml();
}
function impFocus(ids){
 for(const id of ids.concat(['imp-status'])){const el=$(id);if(el&&!el.disabled&&!el.hidden&&typeof el.focus==='function'){el.focus();return;}}
}
function impSay(text){const el=$('imp-status');if(el&&el.textContent!==text)el.textContent=text;}
function impError(text){const el=$('imp-error');if(el)el.textContent=text;}
// Toggles disabled, title and the short texts only; never touches the inputs, the focus or an open question.
function impSync(){
 const busy=impBusyReason(),open=!!imp.question;
 const text=(id,value)=>{const el=$(id);if(el&&el.textContent!==value)el.textContent=value;};
 const reasonFor=()=>busy||(open?IMP_OPEN_FIRST:'');
 imp.rows.forEach((row,i)=>{
  const wire=impWire(imp.typed[row.name]),dirty=!impSame(imp.base[row.name],wire),problem=dirty?impairmentProblem(wire):'';
  const apply=$('imp-apply-'+i),reset=$('imp-reset-'+i),why=reasonFor();
  if(apply){apply.disabled=!!why||!dirty||!!problem;apply.title=why||problem||'';}
  if(reset){reset.disabled=!!why||!impImpaired(row);reset.title=why||'';}
  text('imp-hint-'+i,problem);
 });
 const clear=$('imp-clear');
 if(clear){const why=reasonFor();clear.disabled=!!why||!impAnyImpaired();clear.title=why||'';}
 const line=$('imp-busy');
 if(line){const shown=imp.flight?'':busy;if(line.textContent!==shown)line.textContent=shown;line.hidden=!shown;}
 const stale=$('imp-stale');if(stale)stale.hidden=!imp.stale;
 const retry=$('imp-retry');if(retry)retry.hidden=!(imp.blocked||imp.loadFailed);
}
// ---- Data -----------------------------------------------------------------------------------------------------------
function impZero(){return impWire({});}
// Adopt a device's public rows as the stored values; a row's typed text follows unless the person edited it and it did not change.
function impApplyValues(list,forget){
 const byName={};for(const item of list||[])if(item&&item.interface)byName[item.interface]=impWire(item);
 for(const row of imp.rows){
  const next=byName[row.name]||impZero(),before=imp.base[row.name];
  if(!before||!impSame(before,next)||row.name===forget)imp.typed[row.name]=impDisplay(next);
  imp.base[row.name]=next;
 }
}
function impAdopt(interfaces,impairments,keep){
 const ifs=interfaces||{},device=impairments&&impairments.devices?(impairments.devices[imp.device]||Object.values(impairments.devices)[0]):null;
 imp.answer=ifs;imp.present=ifs.present!==false&&!(device&&device.present===false);
 const status=ifs.facts&&ifs.facts.status;imp.running=!status||status==='running';
 imp.rows=(ifs.interfaces||[]).filter(i=>i&&i.role==='data').map(i=>({name:i.name,label:i.port||i.name}));
 imp.id=(ifs.facts&&ifs.facts.id)||(device&&device.id)||'';
 imp.partial=!!impairments&&impairments.complete===false;
 if(!keep){imp.base={};imp.typed={};}
 for(const row of imp.rows)if(!imp.base[row.name]){imp.base[row.name]=impZero();imp.typed[row.name]=impDisplay(impZero());}
 impApplyValues(device&&device.impairments||[],'');
}
// `force` is the person's own Refresh: it replaces typed text. A background reload that finds the person editing or an open
// question when its answer arrives drops the answer and shows the Refresh line instead (typed text, focus and question stay).
async function impLoad(force){
 const me=imp;if(me.loading)return;
 me.loading=true;me.loadFailed=false;me.stale=false;me.stamp=impOperationStamp();
 impError('');
 if(!me.answer)impPaintBody();
 const query=new URLSearchParams({lab_id:me.lab,node:me.device}).toString();
 try{
  const [ifs,imps]=await Promise.all([api('/operations/interfaces?'+query).then(r=>r.json()),api('/operations/impairments?'+query).then(r=>r.json())]);
  if(imp!==me)return;
  if(!force&&me.answer&&(impEditing()||me.question)){me.stale=true;me.loading=false;impSync();return;}
  me.question=null;impAdopt(ifs,imps,false);me.loaded=true;impSay('');
 }catch(e){
  if(imp!==me)return;
  me.loadFailed=true;impSay(e&&e.message?e.message:'The manager did not answer. Check the connection, then Retry.');impError(e&&e.message?e.message:'');
 }
 me.loading=false;impPaintBody();
}
function impPost(path,body){
 return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
}
// ---- Calls ----------------------------------------------------------------------------------------------------------
async function impConfirm(){
 const me=imp,q=me.question;if(!q||me.flight)return;
 const row=me.rows[q.i]||null,base={lab_id:me.lab,node:me.device};
 me.question=null;me.flight=q.kind;impPaintActions();impSync();
 impSay(q.kind==='clear'?'Clearing…':q.kind==='set'?'Applying…':'Resetting…');impError('');
 let focus=[];
 try{
  let said;
  if(q.kind==='set'){
   const data=await impPost('/operations/impairments/set',{...base,interface:row.name,...q.wire,expected_id:me.id});
   if(imp!==me)return;
   impApplyValues(data.impairments,row.name);said=`Impairments set on ${row.label}.`;focus=['imp-reset-'+q.i,'imp-apply-'+q.i];
  }else if(q.kind==='reset'){
   const data=await impPost('/operations/impairments/reset',{...base,interface:row.name,expected_id:me.id});
   if(imp!==me)return;
   impApplyValues(data.impairments,row.name);
   said=data.changed===false?`${row.label} had no impairments to remove.`:`Impairments removed from ${row.label}.`;focus=['imp-apply-'+q.i,'imp-reset-'+q.i];
  }else{
   const data=await impPost('/operations/impairments/clear',{...base});
   if(imp!==me)return;
   const device=data.devices&&(data.devices[me.device]||Object.values(data.devices)[0]);
   impApplyValues(device&&device.impairments||[],'');
   const full=!(data.failed||[]).length&&!(data.remaining||[]).length;
   said=full?`${impCount(Number(data.cleared)||0,'interface')} cleared.`:impPartialSentence(data,impPortOf);
   focus=['imp-clear','imp-region'];
  }
  me.flight='';impPaintBody();impSay(said);
  if(typeof opLoadImpairments==='function'&&me.lab)opLoadImpairments(me.lab);
  impFocus(focus);
 }catch(e){
  if(imp!==me)return;
  const message=e&&e.message?e.message:'The manager did not answer. Try again.';
  me.flight='';
  if(IMP_BUSY.includes(message)){me.blocked=message;me.sawBusy=typeof busyReason==='function'&&!!busyReason();}
  // A busy sentence is shown once, in the busy line; any other refusal in the status and the error line.
  impPaintBody();if(IMP_BUSY.includes(message))impSay('');else{impSay(message);impError(message);}
  impFocus(q.kind==='clear'?['imp-clear']:['imp-apply-'+q.i,'imp-reset-'+q.i]);
 }
}
function impAsk(kind,i){
 if(imp.flight||imp.question||impBusyReason())return;
 let q;
 if(kind==='set'){
  const row=imp.rows[i],wire=impWire(imp.typed[row&&row.name]),problem=impairmentProblem(wire);
  if(!row||problem||impSame(imp.base[row.name],wire)){impSync();return;}
  q={kind,i,wire};
 }else if(kind==='reset'){if(!imp.rows[i]||!impImpaired(imp.rows[i]))return;q={kind,i};}
 else{if(!impAnyImpaired())return;q={kind,i:-1};}
 imp.question=q;impPaintActions();impSync();impSay('');impError('');
 impFocus(['imp-keep']);
}
function impCancel(){
 const q=imp.question;if(!q)return;
 imp.question=null;impPaintActions();impSync();
 impFocus(q.kind==='clear'?['imp-clear']:q.kind==='set'?['imp-apply-'+q.i,'imp-reset-'+q.i]:['imp-reset-'+q.i,'imp-apply-'+q.i]);
}
function impOnClick(event){
 const button=event&&event.target&&event.target.closest?event.target.closest('[data-imp-act]'):null;
 if(!button||button.disabled)return;
 const act=button.dataset.impAct,i=Number(button.dataset.impI);
 if(act==='apply')impAsk('set',i);
 else if(act==='reset')impAsk('reset',i);
 else if(act==='clear')impAsk('clear',-1);
 else if(act==='cancel')impCancel();
 else if(act==='confirm')impConfirm();
}
function impOnInput(event){
 const input=event&&event.target;if(!input||!input.dataset||input.dataset.impF===undefined)return;
 const row=imp.rows[Number(input.dataset.impI)];if(!row)return;
 imp.typed[row.name]={...imp.typed[row.name],[input.dataset.impF]:input.value};
 impSync();
}
function impRetryFocus(){return imp.rows.flatMap((row,i)=>['imp-apply-'+i,'imp-reset-'+i]).concat(['imp-clear','imp-retry','imp-region']);}
function impRetry(){
 if(imp.blocked){imp.blocked='';imp.sawBusy=false;impSay('');impError('');impSync();impFocus(impRetryFocus());return;}
 if(imp.loadFailed)impLoad(true).then(()=>impFocus(impRetryFocus()));
}
// ---- Opening, refreshing, closing --------------------------------------------------------------------------------------
async function impOpen(){
 const me=imp;
 if(typeof opCapabilities==='function'){try{await opCapabilities();}catch{/* unknown capabilities count as available */}}
 if(imp!==me||!me.open)return;
 if(impCapsLacking()){me.noCap=true;impPaintBody();return;}
 impLoad();
}
function impOnToggle(){
 const box=$('details-impairments');if(!box||box.open===imp.open)return;
 imp.open=box.open;
 if(imp.open){imp.stamp=impOperationStamp();impOpen();}
}
// Optional hook for the Interfaces section: re-read after it changed something. Never overwrites typed text.
function refreshDeviceImpairments(){
 if(!imp.open||imp.noCap||imp.loading||imp.flight)return;
 if(impEditing()||imp.question){imp.stale=true;impSync();return;}
 impLoad();
}
function impEnsure(){
 let el=$('details-impairments');
 if(!el){
  if(typeof document==='undefined'||typeof document.createElement!=='function')return null;
  const anchor=$('details-diagnostics')||$('details-info');
  if(!anchor||!anchor.parentNode)return null;
  el=document.createElement('details');el.id='details-impairments';el.className='drawer-section diag-section';
  anchor.parentNode.insertBefore(el,anchor.nextSibling||null);
 }
 if(!el._impWired){
  if(!String(el.innerHTML||'').includes('id="imp-body"'))el.innerHTML=IMP_SKELETON;
  if(typeof el.addEventListener==='function'){
   el.addEventListener('toggle',impOnToggle);
   el.addEventListener('click',event=>{const t=event.target;if(t&&t.id==='imp-retry')impRetry();else if(t&&t.id==='imp-refresh')impLoad(true);else impOnClick(event);});
   el.addEventListener('input',impOnInput);
   // Escape inside an open question closes the question only, never the drawer around it.
   el.addEventListener('keydown',event=>{if(event&&event.key==='Escape'&&imp.question){if(event.preventDefault)event.preventDefault();if(event.stopPropagation)event.stopPropagation();impCancel();}});
  }
  el._impWired=true;
 }
 return el;
}
// shell.js calls this when the drawer closes: the section collapses and every answer, typed value and question is dropped.
function resetDeviceImpairments(){
 imp=impNew();
 const el=$('details-impairments');
 if(el){
  el.open=false;
  for(const id of ['imp-status','imp-error','imp-busy'])if($(id))$(id).textContent='';
  if($('imp-body'))$('imp-body').innerHTML='';
  if($('imp-stale'))$('imp-stale').hidden=true;
  if($('imp-retry'))$('imp-retry').hidden=true;
 }
}
// app.js calls this from renderDetails (every 4 s while the drawer is open): it never rewrites the section's markup.
function renderDeviceImpairments(n){
 const el=impEnsure();if(!el||!n)return;
 const key=(typeof activeId==='string'?activeId:'')+'/'+n.name;
 if(key!==imp.key){resetDeviceImpairments();imp.key=key;imp.lab=typeof activeId==='string'?activeId:'';imp.device=n.name;}
 imp.title=n.short_name||n.name;
 if((typeof opCaps==='undefined'||opCaps===null)&&typeof opCapabilities==='function'&&Date.now()-impCapsAsked>60000){
  impCapsAsked=Date.now();
  opCapabilities().then(()=>{const lab=typeof current==='function'?current():null,node=lab&&lab.nodes.find(x=>x.name===detailName);if(node&&$('details-dialog')&&$('details-dialog').open)renderDeviceImpairments(node);}).catch(()=>{});
 }
 el.hidden=impCapsLacking()&&!imp.noCap;
 if(el.hidden)return;
 if(imp.open&&imp.loaded&&!imp.loading&&!imp.flight){
  const stamp=impOperationStamp();
  if(stamp!==imp.stamp){
   if(impEditing()||imp.question){imp.stamp=stamp;imp.stale=true;}
   else impLoad();
  }
 }
 if(imp.blocked&&imp.sawBusy&&typeof busyReason==='function'&&!busyReason()){imp.blocked='';imp.sawBusy=false;impSay('');}
 else if(imp.blocked&&!imp.sawBusy&&typeof busyReason==='function'&&busyReason())imp.sawBusy=true;
 impSync();
}
